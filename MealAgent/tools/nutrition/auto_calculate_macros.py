from __future__ import annotations

from typing import AsyncGenerator, Any, Dict, List, Set
from datetime import datetime
import logging

from elysia import tool
from elysia.objects import Response, Error, Result
from elysia.tree.objects import TreeData
from elysia.util.client import ClientManager

from weaviate.collections.classes.filters import Filter

from MealAgent.tools.nutrition.calculate_recipe_macros import calculate_recipe_macros_tool

logger = logging.getLogger(__name__)


def _extract_objects(results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Helper to flatten environment responses into a list of objects."""
    collected: List[Dict[str, Any]] = []
    for entry in results or []:
        objects = entry.get("objects")
        if isinstance(objects, list):
            collected.extend(obj for obj in objects if isinstance(obj, dict))
    return collected


def _extract_missing_ids(results: List[Dict[str, Any]]) -> List[str]:
    ids: List[str] = []
    for entry in results or []:
        objects = entry.get("objects") or []
        for obj in objects:
            recipe_ids = obj.get("recipe_ids")
            if isinstance(recipe_ids, list):
                ids.extend(str(rid) for rid in recipe_ids if rid is not None)
    return ids


async def _calculate_for_recipe(
    recipe: Dict[str, Any],
    tree_data: TreeData,
    client_manager: ClientManager,
    base_lm,
) -> bool:
    """Invoke calculate_recipe_macros_tool for a single recipe by food_id."""
    food_id = recipe.get("food_id")
    if not food_id:
        return False

    try:
        async for event in calculate_recipe_macros_tool(
            inputs={"recipe_id": str(food_id)},
            complex_lm=None,
            tree_data=tree_data,
            client_manager=client_manager,
            base_lm=base_lm,
        ):
            if isinstance(event, Error):
                logger.warning(
                    "auto_calculate_macros_tool: macro calc errored for %s (%s)",
                    food_id,
                    event.feedback,
                )
                return False
            if isinstance(event, Result) and event.name == "macros" and event.objects:
                recipe["macros_per_serving"] = event.objects[0]
                return True
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("auto_calculate_macros_tool: macro calc failed for %s (%s)", food_id, exc)
        return False
    return False


@tool
async def auto_calculate_macros_tool(
    tree_data: TreeData,
    client_manager: ClientManager,
    base_lm=None,
    max_recipes: int = 25,
    **kwargs,
) -> AsyncGenerator[Result | Response | Error, None]:
    """
    Batch macro backfill orchestrator for the nutrition branch.

    Environment contract:
      Reads
        • `search_and_rank_tool.topk` – latest ranked recipes surfacing to the agent.
        • `plan_day_e2e_tool.missing_macros` / `plan_week_e2e_tool.missing_macros` – blocking recipe IDs.
      Writes
        • `auto_calculate_macros_tool.summary` – aggregate attempt counters.
        • `auto_calculate_macros_tool.resolved` – recipe IDs whose macros were filled successfully.

    Decision hints:
      • After `summary` events show `failures=[]`, the agent can safely retry planning.
      • If `failures` persist, consider surfacing an explanation or asking for different recipes.
    """
    if base_lm is None:
        yield Error("auto_calculate_macros_tool requires base_lm for translation.")
        return

    topk_results = tree_data.environment.find("search_and_rank_tool", "topk")
    candidates = _extract_objects(topk_results)

    # Check both daily and weekly plan missing macros
    missing_records_day = tree_data.environment.find("plan_day_e2e_tool", "missing_macros")
    missing_records_week = tree_data.environment.find("plan_week_e2e_tool", "missing_macros")
    missing_ids = _extract_missing_ids(missing_records_day)
    missing_ids.extend(_extract_missing_ids(missing_records_week))
    # Deduplicate
    missing_ids = list(dict.fromkeys(missing_ids))  # Preserves order while removing duplicates

    if missing_ids:
        try:
            client = client_manager.get_client()
            try:
                recipe_collection = client.collections.get("Recipe")
            except Exception as e:
                logger.warning(f"Recipe collection not found: {str(e)}")
                # Continue without fetching missing recipes
                recipe_collection = None
            
            if recipe_collection:
                for rid in missing_ids[:max_recipes]:
                    try:
                        filters = Filter.by_property("food_id").equal(str(rid))
                        fetched = recipe_collection.query.fetch_objects(
                            filters=filters,
                            limit=1,
                        )
                        if fetched.objects:
                            candidates.append(fetched.objects[0].properties)
                    except Exception as exc:
                        logger.debug("auto_calculate_macros_tool: failed fetching recipe %s (%s)", rid, exc)
        except Exception as exc:
            logger.debug("auto_calculate_macros_tool: unable to query Recipe collection (%s)", exc)

    if not candidates:
        yield Error("No recipes available in the environment to process. Run search first.")
        return

    seen: Set[str] = set()
    missing_recipes: List[Dict[str, Any]] = []
    for recipe in candidates:
        food_id = recipe.get("food_id")
        if not food_id or food_id in seen:
            continue
        seen.add(str(food_id))
        macros = recipe.get("macros_per_serving")
        if not isinstance(macros, dict) or not macros.get("kcal"):
            missing_recipes.append(recipe)

    if not missing_recipes:
        yield Response("✅ All candidate recipes already have nutrition data.")
        return

    to_process = missing_recipes[:max_recipes]
    pending_ids = ", ".join(str(r.get("food_id")) for r in to_process[:5])
    yield Response(
        f"🧮 Calculating nutrition for {len(to_process)} recipe(s) "
        f"(processing up to {max_recipes}; e.g. {pending_ids})."
    )

    success = 0
    failures: List[str] = []
    resolved_ids: List[str] = []
    for recipe in to_process:
        ok = await _calculate_for_recipe(recipe, tree_data, client_manager, base_lm)
        if ok:
            success += 1
            resolved_ids.append(str(recipe.get("food_id")))
        else:
            failures.append(str(recipe.get("food_id")))

    yield Response(
        f"Completed macro backfill: {success} success, {len(failures)} failure(s)."
    )

    tree_data.environment.add_objects(
        "auto_calculate_macros_tool",
        "summary",
        [
            {
                "timestamp": datetime.now().isoformat(),
                "success": success,
                "failures": failures,
            }
        ],
    )
    if resolved_ids:
        tree_data.environment.add_objects(
            "auto_calculate_macros_tool",
            "resolved",
            [
                {
                    "recipe_ids": resolved_ids,
                    "timestamp": datetime.now().isoformat(),
                }
            ],
        )

    yield Result(
        name="auto_calculate_macros_summary",
        objects=[
            {"success": success, "failures": failures, "attempted": len(to_process)}
        ],
        metadata={"tool": "auto_calculate_macros_tool"},
        payload_type="generic",
        display=False,
    )


