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
  - cook_mode_tool.final_summary: [{ title, text }]

Decision hints:
- If `cook_mode_tool.steps` is present, consider cooking guidance provided.
- If `cook_mode_tool.completed` exists for a given `food_id`, treat that dish
  as fulfilled unless the user explicitly asks for follow-ups.
"""
from typing import AsyncGenerator, Dict, Any, List
import re
import logging
from datetime import datetime, timezone

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


def _find_recipe_from_weaviate(
    food_id: str,
    client_manager,
) -> Dict[str, Any] | None:
    """Load recipe from Weaviate database by food_id."""
    try:
        client = client_manager.get_client()
        recipe_collection = client.collections.get("Recipe")
        from MealAgent.tools.utils.weaviate_filters import build_filters_from_where
        
        recipe_filter = build_filters_from_where({
            "path": ["food_id"], "operator": "Equal", "valueString": str(food_id)
        })
        recipe_results = recipe_collection.query.fetch_objects(filters=recipe_filter, limit=1)
        
        if recipe_results.objects:
            return recipe_results.objects[0].properties
    except Exception as e:
        logging.debug(f"Failed to load recipe {food_id} from Weaviate: {e}")
    return None


def _find_recipe_from_environment(
    tree_data: TreeData,
    food_id: str | None,
    client_manager=None,
) -> Dict[str, Any] | None:
    """
    Try to locate a recipe object.
    
    IMPORTANT: If food_id is provided, always try Weaviate database first (source of truth).
    Environment cache is only used as fallback.
    """
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
    
    # 1) If food_id provided, try Weaviate database first (source of truth)
    if food_id and client_manager:
        recipe = _find_recipe_from_weaviate(food_id, client_manager)
        if recipe:
            return _normalise_recipe_object(recipe) or recipe
    
    # 2) From weekly or daily plan (E2E tools) - fallback to environment cache
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

    # 3) From search/topk - fallback to environment cache
    res = tree_data.environment.find("search_and_rank_tool", "topk")
    if res and res[0]["objects"]:
        for r in res[0]["objects"]:
            if not isinstance(r, dict):
                continue
            if food_id is None or str(r.get("food_id")) == str(food_id):
                return _normalise_recipe_object(r) or r

    # 4) Final fallback: handle special pseudo-recipes that don't exist in Recipe collection
    #    e.g., default white rice that user added manually outside Recipe collection.
    if food_id and str(food_id) in {"default_white_rice", "white_rice", "plain_white_rice"}:
        # Minimal synthetic recipe so cooking steps are deterministic and reusable
        return {
            "food_id": str(food_id),
            "dish_name": "Cơm Trắng",
            "ingredients_with_qty": ["Gạo tẻ", "Nước"],
        }

    return None


@tool(end=True)
async def cook_mode_tool(
    tree_data: TreeData,
    client_manager: ClientManager,
    food_id: str | None = None,
    base_lm=None,
    polish: bool = False,
    stream_steps: bool = False,
    **kwargs,
) -> AsyncGenerator[Result | Response | Error, None]:
    """
    Produce step-by-step cooking guidance for a recipe and stream steps.

    This tool delivers the full cooking workflow (steps + optional tips) and is
    self-contained for most user requests. The `steps` Result plus the
    `final_summary` object are enough to satisfy "cho tôi công thức nấu ăn"
    without needing any additional tools.

    Only call the `explain` branch (cited_summarize) if the user explicitly
    asks for a higher-level recap or explanation after seeing the steps.

    If cooking guidance has already been provided for a particular `food_id`
    (recorded in `cook_mode_tool.completed`), this tool will skip execution for
    that dish and re-emit the cached steps.

    Inputs:
      - food_id: optional; if not provided, will use first available recipe from
        plan or search results.

    Environment reads:
      - cook_mode_tool.completed (checks if already completed to avoid re-execution)
      - plan_day_e2e_tool.plan or plan_week_e2e_tool.plan (recipes inside)
      - search_and_rank_tool.topk
    Environment writes:
      - cook_mode_tool.steps: [{ food_id, dish_name, steps: [...] }]
      - cook_mode_tool.completed: [{ food_id, timestamp }] - **SIGNALS TASK COMPLETION**
      - cook_mode_tool.final_summary: [{ title, text }] - human-readable recap of the dish

    Decision hints for LLM:
      - **CRITICAL**: If `cook_mode_tool.completed` exists for ALL recipes in the plan 
        (or the requested `food_id`), the cooking request is ALREADY FULFILLED. 
        Do NOT call this tool again. The tool will emit `task_complete` with 
        `stop_calling_tool=True` and `end_conversation=True` - RESPECT THIS SIGNAL 
        and END the conversation immediately. Do NOT restart the tree or call any 
        other tools. If you see `task_complete` with `batch_processed=True` or 
        `all_completed=True`, ALL dishes have been processed - END immediately.
      - If `cook_mode_tool.final_summary` is present, the user's cooking request has 
        been fully satisfied. Do NOT call `explain` unless the user explicitly asks 
        for a higher-level recap (e.g., "tóm tắt lại", "giải thích thêm").
      - If `cook_mode_tool.steps` is present, step-by-step guidance has been provided 
        and is visible in the UI. This is sufficient to satisfy "hướng dẫn nấu" requests.
      - When this tool emits `Result(name="task_complete")` with `task_complete=True`, 
        `stop_calling_tool=True`, and `end_conversation=True`, the task is COMPLETE. 
        END the conversation branch immediately. Do NOT call any other tools or restart 
        the tree. The user's request has been fully satisfied. If you see this signal,
        you MUST choose the "explain" branch to provide a final summary, or END the 
        conversation if no summary is needed.
    """
    logging.info("cook_mode_tool: start (food_id=%s)", food_id)

    # Early return if cooking for this specific food_id has already been completed.
    # This helps avoid repeating guidance when the same dish (e.g., Cơm Trắng)
    # appears multiple times in a plan.
    try:
        completed_check = tree_data.environment.find("cook_mode_tool", "completed")
        completed_food_ids: set[str] = set()
        if completed_check and completed_check[0].get("objects"):
            for obj in completed_check[0]["objects"]:
                fid = str(obj.get("food_id") or "").strip()
                if fid:
                    completed_food_ids.add(fid)
    except Exception:
        completed_food_ids = set()

    if food_id is not None and str(food_id) in completed_food_ids:
        logging.info(
            "cook_mode_tool: food_id %s already completed; re-emitting cached steps",
            food_id,
        )
        yield Response(
            "✅ Cooking instructions are already available for this dish. Reusing existing steps."
        )
        # Re-emit cached steps for this specific food_id (or all if not found)
        try:
            steps_results = tree_data.environment.find("cook_mode_tool", "steps")
            if steps_results and steps_results[0].get("objects"):
                all_steps_data = steps_results[0]["objects"]
                matched = [
                    s
                    for s in all_steps_data
                    if str(s.get("food_id") or "") == str(food_id)
                ]
                if not matched:
                    matched = all_steps_data
                for steps_data in matched:
                    steps_list = steps_data.get("steps", [])
                    yield Result(
                        name="steps",
                        objects=[steps_data],
                        metadata={
                            "steps_count": len(steps_list)
                            if isinstance(steps_list, list)
                            else 0,
                            "tool": "cook_mode_tool",
                        },
                        payload_type="cooking_steps",
                        display=True,
                    )
        except Exception as e:
            logging.debug(
                f"cook_mode_tool: failed to re-emit cached steps from environment: {e}"
            )

        # Add a clear Response message to signal completion
        yield Response("✅ Hướng dẫn nấu ăn đã có sẵn. Đang hiển thị lại các bước đã lưu.")
        
        yield Result(
            name="task_complete",
            objects=[
                {
                    "status": "completed",
                    "message": "Cooking instructions have already been provided for this dish.",
                }
            ],
            metadata={
                "task_complete": True,
                "stop_calling_tool": True,
                "should_explain": False,  # Explicitly signal NOT to call explain
                "task_fully_complete": True,  # Strong signal that nothing more is needed
                "end_conversation": True,  # Signal to end the conversation branch
            },
            payload_type="generic",
            display=False,
        )
        return

    # Stream initial message first for immediate feedback
    yield Response("🔪 Preparing step-by-step cooking instructions...")

    # BATCH PROCESSING: If food_id is None, check if we should process all recipes from plan
    recipes_to_process: List[Dict[str, Any]] = []
    
    if food_id is None:
        # Check if there's a plan with multiple recipes
        plan_res = tree_data.environment.find("plan_day_e2e_tool", "plan")
        if not plan_res:
            plan_res = tree_data.environment.find("plan_week_e2e_tool", "plan")
        
        if plan_res and plan_res[0]["objects"]:
            plan = plan_res[0]["objects"][0]
            all_recipes = []
            
            # Collect all unique recipes from plan
            if plan.get("plan_type") == "day":
                for meal_data in plan.get("meals", {}).values():
                    main_recipe = meal_data.get("recipe")
                    if main_recipe:
                        all_recipes.append(main_recipe)
                    for acc in meal_data.get("accompaniments", []):
                        acc_recipe = acc.get("recipe")
                        if acc_recipe:
                            all_recipes.append(acc_recipe)
            elif plan.get("plan_type") == "week":
                for day in plan.get("days", {}).values():
                    for meal_data in day.get("meals", {}).values():
                        main_recipe = meal_data.get("recipe")
                        if main_recipe:
                            all_recipes.append(main_recipe)
                        for acc in meal_data.get("accompaniments", []):
                            acc_recipe = acc.get("recipe")
                            if acc_recipe:
                                all_recipes.append(acc_recipe)
            
            # Filter out already completed recipes
            for recipe_obj in all_recipes:
                recipe_norm = _normalise_recipe_object(recipe_obj) or recipe_obj
                if not isinstance(recipe_norm, dict):
                    continue
                
                recipe_fid = str(recipe_norm.get("food_id") or "")
                if recipe_fid and recipe_fid not in completed_food_ids:
                    recipes_to_process.append(recipe_norm)
            
            # Early return: If all recipes in plan are already completed
            if len(all_recipes) > 0 and len(recipes_to_process) == 0:
                logging.info("cook_mode_tool: all recipes in plan already completed")
                yield Response("✅ Tất cả các món trong kế hoạch đã được xử lý. Bạn có thể xem các bước chi tiết ở trên.")
                yield Result(
                    name="task_complete",
                    objects=[{"status": "completed", "message": "All recipes in plan have already been processed."}],
                    metadata={
                        "task_complete": True,
                        "stop_calling_tool": True,
                        "should_explain": False,
                        "task_fully_complete": True,
                        "end_conversation": True,
                        "all_completed": True,
                    },
                    payload_type="generic",
                    display=False,
                )
                return
    
    # If we have multiple recipes to process, handle them all in batch
    if len(recipes_to_process) > 1:
        logging.info(f"cook_mode_tool: batch processing {len(recipes_to_process)} recipes from plan")
        yield Response(f"📋 Đang xử lý {len(recipes_to_process)} món từ kế hoạch của bạn...")
        
        all_steps_payloads = []
        processed_count = 0
        
        for recipe in recipes_to_process:
            try:
                recipe_fid = str(recipe.get("food_id") or "")
                dish_name = str(recipe.get("dish_name") or "món ăn")
                
                # Extract steps
                steps = _extract_steps_from_recipe(recipe)
                if not steps:
                    logging.warning(f"cook_mode_tool: no steps for {dish_name} (food_id={recipe_fid})")
                    continue
                
                # Calculate times
                total_time_seconds = sum(s.get("estimated_seconds", 0) for s in steps)
                total_time_minutes = total_time_seconds // 60
                
                steps_payload = {
                    "food_id": recipe_fid,
                    "dish_name": dish_name,
                    "steps": steps,
                    "total_time_seconds": total_time_seconds,
                    "total_time_minutes": total_time_minutes,
                    "serving_size": recipe.get("serving_size", 1),
                    "image_link": recipe.get("image_link"),
                    "cooking_time": recipe.get("cooking_time"),
                }
                
                # Emit Result for this dish immediately
                yield Result(
                    name="steps",
                    objects=[steps_payload],
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
                
                all_steps_payloads.append(steps_payload)
                processed_count += 1
                
            except Exception as e:
                logging.error(f"cook_mode_tool: error processing recipe {recipe.get('food_id')}: {e}")
                continue
        
        # Persist all steps at once
        if all_steps_payloads:
            try:
                tree_data.environment.add_objects(
                    "cook_mode_tool",
                    "steps",
                    all_steps_payloads,
                    metadata={
                        "tool": "cook_mode_tool",
                        "stored_at": datetime.now(timezone.utc).isoformat(),
                        "batch_processed": True,
                    },
                )
            except Exception as e:
                logging.debug(f"cook_mode_tool: unable to persist batch steps: {e}")
            
            # Mark all as completed
            completed_entries = [
                {
                    "food_id": str(payload.get("food_id") or ""),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
                for payload in all_steps_payloads
            ]
            try:
                tree_data.environment.add_objects(
                    "cook_mode_tool",
                    "completed",
                    completed_entries,
                    metadata={"status": "done", "batch_processed": True},
                )
            except Exception as e:
                logging.debug(f"cook_mode_tool: unable to persist batch completed flags: {e}")
        
        # Final completion message
        if processed_count > 0:
            yield Response(f"✅ Đã hoàn tất hướng dẫn nấu ăn cho {processed_count} món. Bạn có thể xem các bước chi tiết ở trên.")
            
            yield Result(
                name="task_complete",
                objects=[{"status": "completed", "message": f"Cooking instructions for {processed_count} dishes have been provided."}],
                metadata={
                    "task_complete": True,
                    "stop_calling_tool": True,
                    "should_explain": False,
                    "task_fully_complete": True,
                    "end_conversation": True,
                    "dishes_count": processed_count,
                    "batch_processed": True,
                },
                payload_type="generic",
                display=False,
            )
            
            logging.info(f"cook_mode_tool: batch complete ({processed_count} dishes)")
        else:
            # No recipes were processed (all failed or empty)
            yield Error("No recipes could be processed from the plan.")
        
        return
    
    # SINGLE RECIPE PROCESSING: Handle single recipe (either from food_id or first from plan)
    recipe = None
    dish_name: str | None = None  # track for logging even if auto-search fails
    if food_id:
        # Try to find specific recipe
        recipe = _find_recipe_from_environment(tree_data, food_id, client_manager)
    elif recipes_to_process:
        # Use first unprocessed recipe from plan
        recipe = recipes_to_process[0]
    else:
        # Try to find recipe from environment
        recipe = _find_recipe_from_environment(tree_data, food_id, client_manager)
    
    # If no recipe found and food_id is None, try to search from user_prompt
    if not recipe and food_id is None:
        logging.info("cook_mode_tool: entering auto-search path (no recipe, no food_id)")

        # Primary source: tree_data.user_prompt or explicit query_text
        user_prompt = getattr(tree_data, "user_prompt", "") or kwargs.get(
            "query_text", ""
        )
        logging.info(
            "cook_mode_tool: initial user_prompt from tree_data/kwargs='%s'",
            str(user_prompt)[:200],
        )

        # Fallback: last user message in conversation_history (more robust across recursions)
        if not user_prompt:
            try:
                history = getattr(tree_data, "conversation_history", []) or []
                for msg in reversed(history):
                    if (
                        isinstance(msg, dict)
                        and msg.get("role") == "user"
                        and msg.get("content")
                    ):
                        user_prompt = str(msg["content"])
                        logging.info(
                            "cook_mode_tool: using last user message from conversation_history as prompt='%s'",
                            user_prompt[:200],
                        )
                        break
            except Exception as e:
                # Best-effort only; log the issue but continue
                logging.warning(
                    "cook_mode_tool: failed to read conversation_history for auto-search fallback: %s",
                    e,
                )
                user_prompt = user_prompt or ""

        if user_prompt:
            logging.info(
                "cook_mode_tool: auto-search activated with user_prompt='%s'",
                user_prompt[:200],
            )

            # Extract dish name from common Vietnamese cooking request patterns.
            # NOTE: We intentionally capture everything after "nấu " so multi-word
            # dish names like "phở bò" or "cơm tấm sườn bì chả" are preserved.
            patterns = [
                r"hướng dẫn.*?nấu\s+(.+)$",
                r"cách.*?nấu\s+(.+)$",
                r"công thức.*?nấu\s+(.+)$",
                r"nấu\s+(.+)$",
            ]
            for pattern in patterns:
                match = re.search(pattern, user_prompt, re.IGNORECASE)
                if match:
                    dish_name = match.group(1).strip()
                    logging.info(
                        "cook_mode_tool: extracted dish_name='%s' using pattern='%s'",
                        dish_name,
                        pattern,
                    )
                    break

            if not dish_name:
                # Fallback: remove common filler words then normalise whitespace
                dish_name = re.sub(
                    r"(hướng dẫn|cách|công thức|nấu|tôi|bạn|cho|giúp)",
                    "",
                    user_prompt,
                    flags=re.IGNORECASE,
                )
                dish_name = re.sub(r"\s+", " ", dish_name).strip()
                logging.info(
                    "cook_mode_tool: fallback dish_name extraction → '%s'", dish_name
                )

            if dish_name and len(dish_name) > 2:
                logging.info(
                    "cook_mode_tool: auto-searching for dish '%s' from user prompt",
                    dish_name,
                )
                yield Response(f"🔍 Đang tìm kiếm công thức '{dish_name}'...")

                # Search directly in Recipe collection using Weaviate
                try:
                    client = client_manager.get_client()
                    recipe_collection = client.collections.get("Recipe")

                    # Build a small set of candidate queries to improve recall:
                    #  - full dish_name (e.g. 'phở bò viên')
                    #  - relaxed first 1–2 tokens (e.g. 'phở bò')
                    #  - full user_prompt as last resort
                    search_queries: List[str] = []
                    primary = dish_name
                    search_queries.append(primary)

                    tokens = primary.split()
                    if len(tokens) > 2:
                        relaxed = " ".join(tokens[:2])
                        if relaxed.lower() != primary.lower():
                            search_queries.append(relaxed)

                    if user_prompt and user_prompt not in search_queries:
                        search_queries.append(user_prompt)

                    for q in search_queries:
                        logging.info(
                            "cook_mode_tool: BM25 search in Recipe for query='%s'", q
                        )
                        search_results = recipe_collection.query.bm25(
                            query=q,
                            limit=5,
                            return_metadata=["score"],
                        )
                        num_results = (
                            len(search_results.objects)
                            if getattr(search_results, "objects", None)
                            else 0
                        )
                        logging.info(
                            "cook_mode_tool: BM25 query='%s' returned %d candidate recipes",
                            q,
                            num_results,
                        )

                        if search_results.objects and num_results > 0:
                            # Use the first (best) result
                            recipe = search_results.objects[0].properties
                            food_id = str(recipe.get("food_id") or "")
                            logging.info(
                                "cook_mode_tool: selected recipe food_id=%s dish_name='%s' via query='%s'",
                                food_id,
                                recipe.get("dish_name"),
                                q,
                            )
                            yield Response(
                                f"✅ Đã tìm thấy công thức '{recipe.get('dish_name', dish_name)}'"
                            )
                            break

                    if not recipe:
                        logging.warning(
                            "cook_mode_tool: no recipes found for dish_name='%s' "
                            "(queries tried: %s)",
                            dish_name,
                            ", ".join(search_queries),
                        )
                except Exception as e:
                    logging.error(
                        "cook_mode_tool: error during auto-search for dish_name='%s': %s",
                        dish_name,
                        e,
                    )
    
    if not recipe:
        msg = "No recipe found. Please select a recipe from your meal plan or search results first."
        user_prompt_str = getattr(tree_data, "user_prompt", "")[:200]
        logging.warning(
            "cook_mode_tool: %s (dish_name='%s', user_prompt='%s')",
            msg,
            dish_name,
            user_prompt_str,
        )

        # Surface a clear error to the UI
        yield Error(msg)

        # Also emit a task_complete signal so the tree does NOT keep retrying
        # cook_mode_tool in a loop when no matching recipe exists.
        yield Result(
            name="task_complete",
            objects=[
                {
                    "status": "failed",
                    "message": msg,
                    "dish_name": dish_name or "",
                    "user_prompt": user_prompt_str,
                }
            ],
            metadata={
                "task_complete": True,
                "stop_calling_tool": True,
                # We cannot satisfy the request automatically; end this branch
                # and let the user decide the next step (e.g. rephrase or pick another dish).
                "end_conversation": True,
                "task_fully_complete": False,
            },
            payload_type="generic",
            display=False,
        )
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

    # Stream brief progress; per-step streaming is optional to avoid duplicate UI with cards
    total_time = sum(s.get("estimated_seconds", 0) for s in steps)
    total_minutes = total_time // 60
    yield Response(f"📋 Found {len(steps)} steps for {dish_name} (est. {total_minutes} min total)")

    if stream_steps:
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

    steps_payload = {
        "food_id": str(recipe.get("food_id") or ""),
        "dish_name": str(recipe.get("dish_name") or ""),
        "steps": steps,
        "total_time_seconds": total_time_seconds,
        "total_time_minutes": total_time_minutes,
        "serving_size": recipe.get("serving_size", 1),
        # Pass through useful recipe metadata for frontend (image, time)
        "image_link": recipe.get("image_link"),
        "cooking_time": recipe.get("cooking_time"),
    }

    yield Result(
        name="steps",
        objects=[steps_payload],
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

    # Persist steps so they can be reused if the same dish is requested again.
    try:
        tree_data.environment.add_objects(
            "cook_mode_tool",
            "steps",
            [steps_payload],
            metadata={
                "tool": "cook_mode_tool",
                "stored_at": datetime.now(timezone.utc).isoformat(),
            },
        )
    except Exception as e:
        logging.debug(f"cook_mode_tool: unable to persist steps payload: {e}")
    
    # Note: CoT-based "polish" (intro + tips) was disabled to reduce latency and token usage.
    # If you want to re-enable it, wrap the ElysiaChainOfThought block here and gate it
    # behind an explicit configuration flag instead of relying on `polish=True` from the LLM.
    # Provide a concise document-style summary to help the decision agent conclude.
    # This is intended to be the final recap for this dish; `explain` is optional.
    try:
        dish = dish_name
        steps_count = len(steps)
        yield Result(
            name="final_summary",
            objects=[{
                "title": f"Cách nấu {dish}",
                "text": (
                    f"Đã cung cấp {steps_count} bước hướng dẫn nấu món {dish}. "
                    "Thường không cần thêm tóm tắt; chỉ gọi nhánh 'explain' nếu "
                    "người dùng yêu cầu giải thích hoặc mẹo bổ sung."
                ),
            }],
            metadata={
                "dish_name": dish,
                "steps_count": steps_count,
                "task_complete": True,
                "should_explain": False,
            },
            payload_type="generic",
            display=False,  # Internal signal for decision agent only, not for user display
        )
    except Exception:
        pass
    # Mark cooking session complete for decision agent awareness
    try:
        tree_data.environment.add_objects(
            "cook_mode_tool",
            "completed",
            [
                {
                    "food_id": str(recipe.get("food_id") or ""),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
            ],
            metadata={"status": "done"},
        )
    except Exception as e:
        logging.debug(f"cook_mode_tool: unable to persist completed flag: {e}")
    
    # Emit final completion signal to prevent further tool calls
    # Add a clear Response message first to signal completion
    yield Response(f"✅ Hướng dẫn nấu {dish_name} đã hoàn tất. Bạn có thể xem các bước chi tiết ở trên.")
    
    yield Result(
        name="task_complete",
        objects=[{"status": "completed", "message": f"Cooking instructions for {dish_name} have been provided."}],
        metadata={
            "task_complete": True,
            "stop_calling_tool": True,
            "should_explain": False,  # Explicitly signal NOT to call explain
            "task_fully_complete": True,  # Strong signal that nothing more is needed
            "end_conversation": True,  # Signal to end the conversation branch
            "dish_name": dish_name,
            "steps_count": len(steps),
        },
        payload_type="generic",
        display=False,
    )
    
    logging.info("cook_mode_tool: complete (steps=%s)", len(steps))
