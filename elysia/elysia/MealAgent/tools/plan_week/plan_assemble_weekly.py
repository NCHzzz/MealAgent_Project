"""
Assemble weekly meal plan (21 meals: 7 days × 3 meals per day).
"""
from typing import AsyncGenerator, List, Dict, Any
from datetime import datetime, timedelta

from elysia.tree.objects import TreeData
from elysia.objects import Result, Error, Response
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

    candidates = [r for r in recipes if r.get("food_id") not in exclude_ids]
    if not candidates:
        return None

    if strategy == "highest_carb":
        candidates.sort(key=lambda r: _get_meal_macros(r).get("carb_g", 0.0), reverse=True)
    elif strategy == "highest_protein":
        candidates.sort(key=lambda r: _get_meal_macros(r).get("protein_g", 0.0), reverse=True)
    elif strategy == "balanced":
        candidates.sort(key=lambda r: r.get("fit_score", 0.0), reverse=True)
    else:
        pass

    return candidates[0] if candidates else None


@tool
async def plan_assemble_weekly_tool(
    tree_data: TreeData,
    client_manager: ClientManager,
    start_date: str | None = None,
    **kwargs,
) -> AsyncGenerator[Result | str | Error, None]:
    """
    Assemble 21-meal weekly plan (7 days × 3 meals) from top-ranked recipes.

    Strategy per day:
        - Breakfast: Highest carb recipe (energy for day)
        - Lunch: Balanced macro recipe
        - Dinner: Highest protein recipe (recovery)

    Environment reads:
      - environment["score_and_rank_tool"]["topk"]
      - environment["target_resolver_tool"]["resolved"] (optional)
    Environment writes:
      - environment["plan_assemble_weekly_tool"]["plan"]
    """
    yield Response("Assembling weekly meal plan (21 meals)...")

    # Read ranked recipes
    recipes_results = tree_data.environment.find("score_and_rank_tool", "topk")
    if not recipes_results or not recipes_results[0].objects:
        yield Error("No ranked recipes found. Run score_and_rank_tool first.")
        return

    recipes = recipes_results[0].objects

    if len(recipes) < 21:
        yield Response(f"Warning: Only {len(recipes)} recipes available, may need to reuse recipes for 21 meals.")

    # Parse start_date or use today
    if start_date:
        try:
            # Try multiple date formats for robustness
            date_str = start_date.replace("Z", "+00:00")
            # Try ISO format first
            try:
                start = datetime.fromisoformat(date_str)
            except ValueError:
                # Try without timezone
                try:
                    start = datetime.fromisoformat(start_date)
                except ValueError:
                    # Try common formats
                    for fmt in ["%Y-%m-%d", "%Y/%m/%d", "%d-%m-%Y", "%d/%m/%Y"]:
                        try:
                            start = datetime.strptime(start_date, fmt)
                            break
                        except ValueError:
                            continue
                    else:
                        raise ValueError(f"Unsupported date format: {start_date}")
            # Normalize to start of day
            start = start.replace(hour=0, minute=0, second=0, microsecond=0)
        except (ValueError, AttributeError) as e:
            yield Error(f"Invalid start_date format: {start_date}. Use ISO format (YYYY-MM-DD) or common date formats. Error: {str(e)}")
            return
    else:
        start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

    # Build weekly plan (7 days)
    weekly_plan = {}
    total_macros = {"kcal": 0.0, "protein_g": 0.0, "fat_g": 0.0, "carb_g": 0.0}
    used_recipes = []  # Track used recipes to encourage variety

    for day_index in range(7):
        day_date = start + timedelta(days=day_index)
        day_key = day_date.date().isoformat()

        # Get available recipes (prefer unused, but allow reuse if needed)
        # Track all used recipe IDs for better variety
        used_recipe_ids = {ur.get("food_id") for ur in used_recipes if ur.get("food_id")}
        available_recipes = [r for r in recipes if r.get("food_id") not in used_recipe_ids]
        if not available_recipes:
            # If we've used all recipes, allow reuse but prefer less recently used ones
            # Use round-robin approach: cycle through recipes
            available_recipes = recipes  # Fallback to all recipes

        # Select meals for this day
        breakfast = _select_meal_by_strategy(available_recipes, "highest_carb")
        if not breakfast:
            breakfast = available_recipes[0] if available_recipes else None

        lunch = _select_meal_by_strategy(available_recipes, "balanced", exclude=[breakfast] if breakfast else None)
        if not lunch:
            lunch = _select_meal_by_strategy(available_recipes, "highest_carb", exclude=[breakfast] if breakfast else None)
        if not lunch:
            lunch = [r for r in available_recipes if r.get("food_id") != breakfast.get("food_id")][0] if breakfast and len(available_recipes) > 1 else breakfast

        dinner = _select_meal_by_strategy(available_recipes, "highest_protein", exclude=[breakfast, lunch] if breakfast and lunch else [])
        if not dinner:
            exclude_ids = {r.get("food_id") for r in [breakfast, lunch] if r}
            remaining = [r for r in available_recipes if r.get("food_id") not in exclude_ids]
            dinner = remaining[0] if remaining else breakfast

        if not breakfast or not lunch or not dinner:
            yield Error(f"Could not assemble meals for day {day_index + 1}")
            return

        # Track used recipes
        used_recipes.extend([breakfast, lunch, dinner])

        # Build day plan
        day_plan = {
            "breakfast": {
                "recipe": breakfast,
                "servings": 1.0,
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

        # Calculate day macros
        day_macros = {"kcal": 0.0, "protein_g": 0.0, "fat_g": 0.0, "carb_g": 0.0}
        for meal_data in day_plan.values():
            recipe = meal_data["recipe"]
            servings = meal_data["servings"]
            macros = _get_meal_macros(recipe)
            for key in day_macros:
                day_macros[key] += macros[key] * servings
                total_macros[key] += macros[key] * servings

        weekly_plan[day_key] = {
            "day_index": day_index,
            "date": day_key,
            "meals": day_plan,
            "total_macros": day_macros,
        }

    plan_output = {
        "plan_type": "week",
        "start_date": start.date().isoformat(),
        "days": weekly_plan,
        "total_macros": total_macros,
        "average_daily_macros": {
            "kcal": total_macros["kcal"] / 7.0,
            "protein_g": total_macros["protein_g"] / 7.0,
            "fat_g": total_macros["fat_g"] / 7.0,
            "carb_g": total_macros["carb_g"] / 7.0,
        },
        "created_at": datetime.now().isoformat(),
    }

    yield Result(
        name="plan",
        objects=[plan_output],
        metadata={"plan_type": "week", "meals_count": 21, "days_count": 7},
        payload_type="generic",
    )
    yield Response(f"Weekly plan assembled: {total_macros['kcal']:.0f} kcal total | {total_macros['kcal']/7:.0f} kcal/day avg")

