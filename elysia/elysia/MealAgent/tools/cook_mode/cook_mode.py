"""
CookMode tool: parse a recipe into cooking steps and stream them.

Reads a recipe from environment (by food_id or from plan/search),
generates a list of structured steps, and streams guidance messages.
"""
from typing import AsyncGenerator, Dict, Any, List
import re
import logging

from elysia.tree.objects import TreeData
from elysia.objects import Result, Error
from elysia.util.client import ClientManager
from elysia import tool


def _extract_steps_from_recipe(recipe: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Build simple cooking steps from cooking_method_array or fallback to ingredients list.
    This is deterministic and avoids LLM; good as a baseline.
    """
    steps: List[Dict[str, Any]] = []

    cooking_steps = recipe.get("cooking_method_array") or recipe.get("directions") or []
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


def _find_recipe_from_environment(tree_data: TreeData, food_id: str | None) -> Dict[str, Any] | None:
    """Try to locate a recipe object from various environment slots."""
    # 1) From weekly or daily plan
    for tool_name, name in [("plan_assemble_weekly_tool", "plan"), ("plan_assemble_day_tool", "plan")]:
        res = tree_data.environment.find(tool_name, name)
        if res and res[0].objects:
            plan = res[0].objects[0]
            if plan.get("plan_type") == "day":
                for meal_data in plan.get("meals", {}).values():
                    r = meal_data.get("recipe")
                    if r and (food_id is None or r.get("food_id") == food_id):
                        return r
            elif plan.get("plan_type") == "week":
                for day in plan.get("days", {}).values():
                    for meal_data in day.get("meals", {}).values():
                        r = meal_data.get("recipe")
                        if r and (food_id is None or r.get("food_id") == food_id):
                            return r

    # 2) From search/topk
    res = tree_data.environment.find("score_and_rank_tool", "topk")
    if res and res[0].objects:
        for r in res[0].objects:
            if not isinstance(r, dict):
                continue
            if food_id is None or r.get("food_id") == food_id:
                return r

    return None


@tool
async def cook_mode_tool(
    tree_data: TreeData,
    client_manager: ClientManager,
    food_id: str | None = None,
    **kwargs,
) -> AsyncGenerator[Result | str | Error, None]:
    """
    Produce step-by-step cooking guidance for a recipe and stream steps.

    Inputs:
      - food_id: optional; if not provided, will use first available recipe from plan or search results.

    Environment reads:
      - plan_assemble_day_tool.plan or plan_assemble_weekly_tool.plan (recipes inside)
      - score_and_rank_tool.topk (as fallback)
    Environment writes:
      - cook_mode_tool.steps
    """
    logging.info("cook_mode_tool: start (food_id=%s)", food_id)
    yield "Preparing cooking steps..."

    recipe = _find_recipe_from_environment(tree_data, food_id)
    if not recipe:
        msg = "No recipe found in environment. Provide food_id or run planning/search first."
        logging.warning("cook_mode_tool: %s", msg)
        yield Error(msg)
        return

    steps = _extract_steps_from_recipe(recipe)
    if not steps:
        logging.error("cook_mode_tool: no steps extracted (food_id=%s)", recipe.get("food_id"))
        yield Error("Could not extract steps from recipe")
        return

    # Emit Result first
    yield Result(
        name="steps",
        objects=[{"food_id": recipe.get("food_id"), "dish_name": recipe.get("dish_name"), "steps": steps}],
        metadata={"steps_count": len(steps), "tool": "cook_mode_tool"},
    )

    # Stream each step as text
    for step in steps:
        idx = step.get("index")
        txt = step.get("instruction")
        dur = step.get("estimated_seconds")
        logging.debug("cook_mode_tool: step %s (%ss): %s", idx, dur, txt)
        yield f"Step {idx}: {txt} (est. {dur}s)"
    
    logging.info("cook_mode_tool: complete (steps=%s)", len(steps))
    yield "Cooking guidance complete."
