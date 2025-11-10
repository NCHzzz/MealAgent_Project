from typing import AsyncGenerator, List, Dict, Any

from elysia.tree.objects import TreeData
from elysia.objects import Result, Error
from elysia.util.client import ClientManager
from elysia import tool


def _get_meal_macros(recipe: Dict[str, Any]) -> Dict[str, float]:
    """Extract macros from recipe, defaulting to 0 if missing."""
    macros = recipe.get("macros_per_serving", {})
    if not isinstance(macros, dict):
        return {"kcal": 0.0, "protein_g": 0.0, "fat_g": 0.0, "carb_g": 0.0}
    return {
        "kcal": float(macros.get("kcal", 0.0)),
        "protein_g": float(macros.get("protein_g", 0.0)),
        "fat_g": float(macros.get("fat_g", 0.0)),
        "carb_g": float(macros.get("carb_g", 0.0)),
    }


def _select_meal_by_strategy(
    recipes: List[Dict[str, Any]],
    strategy: str,
    exclude: List[Dict[str, Any]] | None = None,
) -> Dict[str, Any] | None:
    """Select recipe based on strategy (highest_carb, highest_protein, balanced)."""
    if not recipes:
        return None

    exclude_ids = set()
    if exclude:
        exclude_ids = {r.get("food_id") for r in exclude if r.get("food_id")}

    # Filter out excluded recipes
    candidates = [r for r in recipes if r.get("food_id") not in exclude_ids]
    if not candidates:
        return None

    if strategy == "highest_carb":
        candidates.sort(key=lambda r: _get_meal_macros(r).get("carb_g", 0.0), reverse=True)
    elif strategy == "highest_protein":
        candidates.sort(key=lambda r: _get_meal_macros(r).get("protein_g", 0.0), reverse=True)
    elif strategy == "balanced":
        # Balanced = closest to average macro distribution
        # For now, use highest fit_score if available
        candidates.sort(key=lambda r: r.get("fit_score", 0.0), reverse=True)
    else:
        # Default: use first candidate
        pass

    return candidates[0] if candidates else None


@tool
async def plan_assemble_day_tool(
    tree_data: TreeData,
    client_manager: ClientManager,  # signature consistency
    **kwargs,
) -> AsyncGenerator[Result | str | Error, None]:
    """
    Assemble 3-meal daily plan from top-ranked recipes.

    Strategy:
        - Breakfast: Highest carb recipe (energy for day)
        - Lunch: Balanced macro recipe
        - Dinner: Highest protein recipe (recovery)

    Environment reads:
      - environment["score_and_rank_tool"]["topk"]
      - environment["target_resolver_tool"]["resolved"] (optional - for validation)
    Environment writes:
      - environment["plan_assemble_day_tool"]["plan"]
    """
    yield "Assembling daily meal plan..."

    # Read ranked recipes
    recipes_results = tree_data.environment.find("score_and_rank_tool", "topk")
    if not recipes_results or not recipes_results[0].objects:
        yield Error("No ranked recipes found. Run score_and_rank_tool first.")
        return

    recipes = recipes_results[0].objects

    if len(recipes) < 3:
        yield Error("Insufficient recipes for 3-meal plan. Need at least 3 recipes.")
        return
    
    # Check for missing macros
    missing_macros = [r for r in recipes if not r.get("macros_per_serving") or not isinstance(r.get("macros_per_serving"), dict) or not r.get("macros_per_serving", {}).get("kcal")]
    if missing_macros:
        yield f"Warning: {len(missing_macros)} recipes missing macros_per_serving. Consider running calculate_recipe_macros_tool for accurate planning."

    # Select meals by strategy
    breakfast = _select_meal_by_strategy(recipes, "highest_carb")
    if not breakfast:
        yield Error("Could not select breakfast meal")
        return

    lunch = _select_meal_by_strategy(recipes, "balanced", exclude=[breakfast])
    if not lunch:
        # Fallback to second highest carb if balanced selection fails
        lunch = _select_meal_by_strategy(recipes, "highest_carb", exclude=[breakfast])
    if not lunch:
        yield Error("Could not select lunch meal")
        return

    dinner = _select_meal_by_strategy(recipes, "highest_protein", exclude=[breakfast, lunch])
    if not dinner:
        # Fallback to any remaining recipe
        exclude_ids = {breakfast.get("food_id"), lunch.get("food_id")}
        remaining = [r for r in recipes if r.get("food_id") not in exclude_ids]
        if remaining:
            dinner = remaining[0]
        else:
            yield Error("Could not select dinner meal")
            return

    # Build plan structure
    plan = {
        "breakfast": {
            "recipe": breakfast,
            "servings": 1.0,  # Default 1 serving, can be adjusted
            "meal_type": "breakfast",
        },
        "lunch": {
            "recipe": lunch,
            "servings": 1.0,
            "meal_type": "lunch",
        },
        "dinner": {
            "recipe": dinner,
            "servings": 1.0,
            "meal_type": "dinner",
        },
    }

    # Calculate total macros
    total_macros = {"kcal": 0.0, "protein_g": 0.0, "fat_g": 0.0, "carb_g": 0.0}
    for meal_data in plan.values():
        recipe = meal_data["recipe"]
        servings = meal_data["servings"]
        macros = _get_meal_macros(recipe)
        for key in total_macros:
            total_macros[key] += macros[key] * servings

    plan_output = {
        "plan_type": "day",
        "meals": plan,
        "total_macros": total_macros,
        "created_at": None,  # Can be set by caller
    }

    yield Result(
        name="plan",
        objects=[plan_output],
        metadata={"plan_type": "day", "meals_count": 3},
    )
    yield f"Daily plan assembled: {total_macros['kcal']:.0f} kcal | {total_macros['protein_g']:.0f}g P | {total_macros['fat_g']:.0f}g F | {total_macros['carb_g']:.0f}g C"

