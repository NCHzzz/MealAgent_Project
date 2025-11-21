"""
CookMode tool: parse a recipe into cooking steps and stream them.

Environment interface (per docs/ai/design/environment_keys.md):
- Reads:
  - plan_day_e2e_tool.plan / plan_week_e2e_tool.plan (nested recipes)
  - search_and_rank_tool.topk
  - cook_mode_tool.recipe_id (preferred selection if present)
- Writes:
  - cook_mode_tool.steps: [{ food_id, dish_name, steps: [...] }]
  - cook_mode_tool.completed: [{ food_id, timestamp }]

Decision hints:
- If cook_mode_tool.steps is present, consider cooking guidance provided.
- If cook_mode_tool.completed exists, treat request as fulfilled unless the user asks for follow-ups.
"""
from typing import AsyncGenerator, Dict, Any, List
import re
import logging

from elysia.tree.objects import TreeData
from elysia.objects import Result, Error, Response
from elysia.util.client import ClientManager
from elysia import tool
import dspy
from elysia.util.elysia_chain_of_thought import ElysiaChainOfThought
from types import GeneratorType


def _extract_steps_from_recipe(recipe: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Build simple cooking steps from cooking_method_array or fallback to ingredients list.
    This is deterministic and avoids LLM; good as a baseline.
    """
    steps: List[Dict[str, Any]] = []

    cooking_steps = recipe.get("cooking_method_array") or recipe.get("directions") or []
    # Materialise non-list iterables (e.g., generators) into a list
    if cooking_steps and not isinstance(cooking_steps, (list, str)):
        try:
            if hasattr(cooking_steps, "__iter__"):
                cooking_steps = [s for s in cooking_steps]
        except Exception:
            cooking_steps = []
    if isinstance(cooking_steps, str):
        # Split by sentences if string provided
        cooking_steps = re.split(r"(?<=[.!?])\s+", cooking_steps)

    if cooking_steps and isinstance(cooking_steps, list):
        for idx, s in enumerate(cooking_steps, start=1):
            if not s:
                continue
            steps.append({
                "index": idx,
                "instruction": str(s),
                "estimated_seconds": _estimate_duration_seconds(str(s)),
            })
    else:
        # Fallback: create generic steps from ingredients
        ingredients = recipe.get("ingredients_with_qty") or recipe.get("ingredients") or []
        if not isinstance(ingredients, list):
            ingredients = []
        steps.append({"index": 1, "instruction": "Gather all ingredients.", "estimated_seconds": 60})
        for i, ing in enumerate(ingredients, start=2):
            steps.append({
                "index": i,
                "instruction": f"Prepare: {ing}",
                "estimated_seconds": 45,
            })
        steps.append({"index": len(steps) + 1, "instruction": "Cook following your preferred method.", "estimated_seconds": 300})

    return steps


def _estimate_duration_seconds(text: str) -> int:
    """Naive duration extractor: look for numbers + (min|minute|seconds)."""
    text_l = text.lower()
    # Match minutes first
    m = re.search(r"(\d{1,3})\s*(?:min|mins|minute|minutes)", text_l)
    if m:
        return int(m.group(1)) * 60
    s = re.search(r"(\d{1,3})\s*(?:sec|secs|second|seconds)", text_l)
    if s:
        return int(s.group(1))
    # Default small step
    return 60


def _normalise_recipe_object(obj: Any) -> Dict[str, Any] | None:
    """Normalise various possible recipe object shapes into a dict of fields.
    Accepts:
      - dict (returned as-is)
      - Weaviate object with .properties
      - generator/iterable yielding dicts (returns the first dict)
    """
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj
    # Weaviate object shape
    if hasattr(obj, "properties") and isinstance(getattr(obj, "properties"), dict):
        return getattr(obj, "properties")
    # Generator / iterable of dicts
    if isinstance(obj, GeneratorType) or (hasattr(obj, "__iter__") and not isinstance(obj, (str, bytes, dict))):
        try:
            for item in obj:
                if isinstance(item, dict):
                    return item
                if hasattr(item, "properties") and isinstance(getattr(item, "properties"), dict):
                    return getattr(item, "properties")
        except Exception:
            pass
    return None


def _find_recipe_from_environment(tree_data: TreeData, food_id: str | None) -> Dict[str, Any] | None:
    """Try to locate a recipe object from various environment slots."""
    # 0) If a recipe_id was previously selected and stored, prioritise it
    try:
        selected = tree_data.environment.find("cook_mode_tool", "recipe_id")
        if selected and selected[0]["objects"]:
            sel_obj = selected[0]["objects"][0]
            selected_id = sel_obj.get("food_id") or sel_obj.get("recipe_id")
            if selected_id and (food_id is None or str(food_id) == str(selected_id)):
                food_id = str(selected_id)
    except Exception:
        pass
    # 1) From weekly or daily plan (E2E tools)
    for tool_name, name in [("plan_week_e2e_tool", "plan"), ("plan_day_e2e_tool", "plan")]:
        res = tree_data.environment.find(tool_name, name)
        if res and res[0]["objects"]:
            plan = res[0]["objects"][0]
            if plan.get("plan_type") == "day":
                for meal_data in plan.get("meals", {}).values():
                    r = meal_data.get("recipe")
                    if r:
                        r_norm = _normalise_recipe_object(r)
                        if r_norm and (food_id is None or str(r_norm.get("food_id")) == str(food_id)):
                            return r_norm
            elif plan.get("plan_type") == "week":
                for day in plan.get("days", {}).values():
                    for meal_data in day.get("meals", {}).values():
                        r = meal_data.get("recipe")
                        if r:
                            r_norm = _normalise_recipe_object(r)
                            if r_norm and (food_id is None or str(r_norm.get("food_id")) == str(food_id)):
                                return r_norm

    # 2) From search/topk
    res = tree_data.environment.find("search_and_rank_tool", "topk")
    if res and res[0]["objects"]:
        for r in res[0]["objects"]:
            if not isinstance(r, dict):
                continue
            if food_id is None or str(r.get("food_id")) == str(food_id):
                return _normalise_recipe_object(r) or r

    return None


@tool(end=False)
async def cook_mode_tool(
    tree_data: TreeData,
    client_manager: ClientManager,
    food_id: str | None = None,
    base_lm=None,
    polish: bool = False,
    **kwargs,
) -> AsyncGenerator[Result | Response | Error, None]:
    """
    Produce step-by-step cooking guidance for a recipe and stream steps.

    This tool delivers the full cooking workflow (steps + optional tips).
    After it finishes, the explain branch (cited_summarize) should be invoked
    to provide a natural-language recap with citations before ending.

    If cooking guidance has already been provided (cook_mode_tool.completed exists), this tool will skip execution.

    Inputs:
      - food_id: optional; if not provided, will use first available recipe from plan or search results.

    Environment reads:
      - cook_mode_tool.completed (checks if already completed to avoid re-execution)
      - plan_day_e2e_tool.plan or plan_week_e2e_tool.plan (recipes inside)
      - search_and_rank_tool.topk
    Environment writes:
      - cook_mode_tool.steps: [{ food_id, dish_name, steps: [...] }]
      - cook_mode_tool.completed: [{ food_id, timestamp }] - **SIGNALS TASK COMPLETION**
      - cook_mode_tool.final_summary: [{ title, text }] - signals cooking guidance is complete
      - cook_mode_tool.next_action_hint: [{ suggested_action: "explain", reason: "summarize cooking result" }] - tells agent to run explain branch

    Decision hints for LLM:
      - If cook_mode_tool.completed exists, the cooking request is ALREADY FULFILLED.
      - If cook_mode_tool.final_summary is present, cooking guidance is done; run explain branch for recap.
      - If cook_mode_tool.next_action_hint suggests "explain", call the explain branch (cited_summarize) before ending.
      - If cook_mode_tool.steps is present, cooking guidance has been provided successfully.
    """
    logging.info("cook_mode_tool: start (food_id=%s)", food_id)
    
    # Early return if cooking has already been completed
    completed_check = tree_data.environment.find("cook_mode_tool", "completed")
    if completed_check and completed_check[0].get("objects"):
        logging.info("cook_mode_tool: already completed; skipping re-execution")
        yield Response("✅ Cooking instructions are already available. Task completed.")
        # Re-emit steps if available for frontend display
        try:
            steps_results = tree_data.environment.find("cook_mode_tool", "steps")
            if steps_results and steps_results[0].get("objects"):
                steps_data = steps_results[0]["objects"][0]
                steps = steps_data.get("steps", [])
                # Re-emit steps for frontend display
                yield Result(
                    name="steps",
                    objects=[steps_data],
                    metadata={"steps_count": len(steps) if isinstance(steps, list) else 0, "tool": "cook_mode_tool"},
                    payload_type="cooking_steps",
                    display=True,
                )
        except Exception:
            pass
        # Emit clear completion signal to prevent further calls
        yield Result(
            name="task_complete",
            objects=[{"status": "completed", "message": "Cooking instructions have been provided."}],
            metadata={
                "task_complete": True,
                "stop_calling_tool": True,
                "suggested_action": "explain",
            },
            payload_type="generic",
            display=False,
        )
        return

    # Stream initial message first for immediate feedback
    yield Response("🔪 Preparing step-by-step cooking instructions...")

    recipe = _find_recipe_from_environment(tree_data, food_id)
    if not recipe:
        msg = "No recipe found. Please select a recipe from your meal plan or search results first."
        logging.warning("cook_mode_tool: %s", msg)
        yield Error(msg)
        return

    # Normalise possible object types before extracting steps
    recipe = _normalise_recipe_object(recipe) or recipe
    if not isinstance(recipe, dict):
        logging.error("cook_mode_tool: recipe object is not a dict; type=%s", type(recipe))
        yield Error("Recipe format not recognised")
        return
    steps = _extract_steps_from_recipe(recipe)
    if not steps:
        logging.error("cook_mode_tool: no steps extracted (food_id=%s)", recipe.get("food_id"))
        yield Error("Could not extract steps from recipe")
        return
    dish_name = str(recipe.get("dish_name") or "the dish")

    # Stream steps FIRST for immediate user feedback, then emit Result objects
    # This ensures frontend receives streaming text immediately
    total_time = sum(s.get("estimated_seconds", 0) for s in steps)
    total_minutes = total_time // 60
    yield Response(f"📋 Found {len(steps)} steps for {dish_name} (est. {total_minutes} min total)")
    
    for step in steps:
        idx = step.get("index")
        txt = step.get("instruction")
        dur = step.get("estimated_seconds")
        dur_min = dur // 60 if dur >= 60 else dur
        dur_unit = "min" if dur >= 60 else "sec"
        logging.debug("cook_mode_tool: step %s (%ss): %s", idx, dur, txt)
        yield Response(f"Step {idx}: {txt} (~{dur_min} {dur_unit})")
    
    # Stream completion message
    yield Response(f"✅ Cooking instructions ready for {dish_name}!")
    
    # Emit Result objects FIRST to ensure cooking steps display appears before tips
    # This ensures the main recipe component is shown before supplementary tips
    # Calculate total cooking time for metadata
    total_time_seconds = sum(s.get("estimated_seconds", 0) for s in steps)
    total_time_minutes = total_time_seconds // 60
    
    yield Result(
        name="steps",
        objects=[{
            "food_id": str(recipe.get("food_id") or ""), 
            "dish_name": str(recipe.get("dish_name") or ""), 
            "steps": steps,
            "total_time_seconds": total_time_seconds,
            "total_time_minutes": total_time_minutes,
            "serving_size": recipe.get("serving_size", 1),
        }],
        metadata={
            "steps_count": len(steps),
            "tool": "cook_mode_tool",
            "total_time_seconds": total_time_seconds,
            "total_time_minutes": total_time_minutes,
            "dish_name": dish_name,
        },
        payload_type="cooking_steps",
        display=True,
    )
    
    # Optional polish with ElysiaChainOfThought for a brief intro/tips
    # These are supplementary tips shown AFTER the main recipe component
    if base_lm and polish:
        try:
            class CookIntroPrompt(dspy.Signature):
                """
                Create a short, friendly cooking intro and 3 quick tips based on the dish name and number of steps.
                Keep it concise and practical, do not repeat step content.
                """
                dish_name = dspy.InputField(description="Dish name.")
                num_steps = dspy.InputField(description="Number of steps.")
                message_update = dspy.OutputField(description="One-sentence update about polishing the guidance.")
                intro = dspy.OutputField(description="A 1-2 sentence intro with a positive tone.")
                tips = dspy.OutputField(description="A short bulleted list (max 3 bullets).")

            cot = ElysiaChainOfThought(
                CookIntroPrompt,
                tree_data=tree_data,
                reasoning=False,
                impossible=False,
                message_update=True,
                environment=False,
                tasks_completed=False,
            )
            pred = await cot.aforward(
                lm=base_lm,
                dish_name=str(recipe.get("dish_name") or "your dish"),
                num_steps=len(steps),
            )
            if getattr(pred, "message_update", None):
                yield Response(str(pred.message_update))
            intro_text = str(getattr(pred, "intro", "")).strip()
            tips_text = str(getattr(pred, "tips", "")).strip()
            if intro_text:
                yield Response(intro_text)
            if tips_text:
                yield Response(tips_text)
        except Exception as e:
            logging.debug(f"cook_mode_tool: CoT polish skipped due to error: {str(e)}")
    # Provide a concise document-style summary to help the decision agent conclude
    # CRITICAL: These signals tell the decision agent that the task is COMPLETE
    try:
        dish = dish_name
        steps_count = len(steps)
        yield Result(
            name="final_summary",
            objects=[{
                "title": f"Cooking instructions for {dish}",
                "text": f"Provided {steps_count} step-by-step instructions for {dish}. Run the explain branch for a brief recap before closing.",
            }],
            metadata={
                "dish_name": dish, 
                "steps_count": steps_count,
                "task_complete": True,
                "should_explain": True,
            },
            payload_type="generic",
            display=False,  # Internal signal for decision agent only, not for user display
        )
        # Hint to decision agent: run explanation before ending
        yield Result(
            name="next_action_hint",
            objects=[{
                "suggested_action": "explain", 
                "reason": "primary goal completed - provide a cited summary of the cooking steps",
                "instruction": "Call the explain branch (cited_summarize) to summarize the dish, then decide whether to end.",
            }],
            metadata={
                "suggested_action": "explain",
                "task_complete": True,
                "should_explain": True,
            },
            payload_type="generic",
            display=False,  # Internal signal for decision agent only, not for user display
        )
    except Exception:
        pass
    # Mark cooking session complete for decision agent awareness
    try:
        from datetime import datetime
        tree_data.environment.add_objects(
            "cook_mode_tool",
            "completed",
            [{"food_id": str(recipe.get("food_id") or ""), "timestamp": datetime.now(datetime.timezone.utc).isoformat()}],
            metadata={"status": "done"},
        )
    except Exception:
        pass
    
    # Emit final completion signal to prevent further tool calls
    yield Result(
        name="task_complete",
        objects=[{"status": "completed", "message": f"Cooking instructions for {dish_name} have been provided."}],
        metadata={
            "task_complete": True,
            "stop_calling_tool": True,
            "suggested_action": "explain",
            "dish_name": dish_name,
            "steps_count": len(steps),
        },
        payload_type="generic",
        display=False,
    )
    
    logging.info("cook_mode_tool: complete (steps=%s)", len(steps))
