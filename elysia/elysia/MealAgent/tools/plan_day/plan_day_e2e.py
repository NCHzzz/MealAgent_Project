from typing import AsyncGenerator, Dict, Any, List
import logging

from elysia.tree.objects import TreeData
from elysia.objects import Result, Error, Response
from elysia.util.client import ClientManager
from elysia import tool

from .plan_assemble import _get_meal_macros


def _select_meal_by_strategy(recipes: List[Dict[str, Any]], strategy: str, exclude: List[Dict[str, Any]] | None = None) -> Dict[str, Any] | None:
    if not recipes:
        return None
    exclude_ids = {r.get("food_id") for r in (exclude or []) if r.get("food_id")}
    candidates = [r for r in recipes if r.get("food_id") not in exclude_ids]
    if not candidates:
        return None
    if strategy == "highest_carb":
        candidates.sort(key=lambda r: _get_meal_macros(r).get("carb_g", 0.0), reverse=True)
    elif strategy == "highest_protein":
        candidates.sort(key=lambda r: _get_meal_macros(r).get("protein_g", 0.0), reverse=True)
    elif strategy == "balanced":
        candidates.sort(key=lambda r: r.get("fit_score", 0.0), reverse=True)
    return candidates[0] if candidates else None


@tool
async def plan_day_e2e_tool(
    tree_data: TreeData,
    client_manager: ClientManager,
    query_text: str = "",
    collection_name: str = "Recipe",
    **kwargs,
) -> AsyncGenerator[Result | str | Error, None]:
    """
    End-to-end: search_and_rank → assemble 3-meal plan in one tool.
    Expects ranked items already available or fails fast.
    """
    logging.info("plan_day_e2e_tool: start")
    yield Response("Building daily plan in one step...")

    try:
        sr = tree_data.environment.find("search_and_rank_tool", "topk")
        if sr and sr[0]["objects"]:
            recipes = sr[0]["objects"]
        else:
            q = tree_data.environment.find("score_and_rank_tool", "topk")
            if q and q[0]["objects"]:
                recipes = q[0]["objects"]
            else:
                yield Error("No ranked items available. Run search_and_rank_tool or score_and_rank_tool first.")
                return

        if len(recipes) < 3:
            yield Error("Insufficient recipes for 3-meal plan. Need at least 3 recipes.")
            return

        breakfast = _select_meal_by_strategy(recipes, "highest_carb")
        if not breakfast:
            yield Error("Could not select breakfast meal")
            return
        lunch = _select_meal_by_strategy(recipes, "balanced", exclude=[breakfast]) or _select_meal_by_strategy(recipes, "highest_carb", exclude=[breakfast])
        if not lunch:
            yield Error("Could not select lunch meal")
            return
        dinner = _select_meal_by_strategy(recipes, "highest_protein", exclude=[breakfast, lunch])
        if not dinner:
            exclude_ids = {breakfast.get("food_id"), lunch.get("food_id")}
            remaining = [r for r in recipes if r.get("food_id") not in exclude_ids]
            dinner = remaining[0] if remaining else None
        if not dinner:
            yield Error("Could not select dinner meal")
            return

        plan = {
            "breakfast": {"recipe": breakfast, "servings": 1.0, "meal_type": "breakfast"},
            "lunch": {"recipe": lunch, "servings": 1.0, "meal_type": "lunch"},
            "dinner": {"recipe": dinner, "servings": 1.0, "meal_type": "dinner"},
        }

        total_macros = {"kcal": 0.0, "protein_g": 0.0, "fat_g": 0.0, "carb_g": 0.0}
        for meal_data in plan.values():
            recipe = meal_data["recipe"]
            servings = meal_data["servings"]
            macros = _get_meal_macros(recipe)
            for k in total_macros:
                total_macros[k] += macros[k] * servings

        plan_output = {
            "plan_type": "day",
            "meals": plan,
            "total_macros": total_macros,
            "created_at": None,
        }

        yield Result(
            name="plan",
            objects=[plan_output],
            metadata={"plan_type": "day", "meals_count": 3},
            payload_type="generic",
        )
        yield Response(f"Daily plan (one-step) assembled: {total_macros['kcal']:.0f} kcal | {total_macros['protein_g']:.0f}g P")

    except Exception as e:
        yield Error(f"plan_day_e2e_tool failed: {str(e)}")
        return


