"""
Add snack to plan and recalculate totals.
"""
from typing import AsyncGenerator, Dict, Any
import copy

from elysia.tree.objects import TreeData
from elysia.objects import Result, Error
from elysia.util.client import ClientManager
from elysia import tool


def _get_meal_macros(recipe: Dict[str, Any]) -> Dict[str, float]:
    """Extract macros from recipe."""
    macros = recipe.get("macros_per_serving", {})
    if not isinstance(macros, dict):
        return {"kcal": 0.0, "protein_g": 0.0, "fat_g": 0.0, "carb_g": 0.0}
    return {
        "kcal": float(macros.get("kcal", 0.0)),
        "protein_g": float(macros.get("protein_g", 0.0)),
        "fat_g": float(macros.get("fat_g", 0.0)),
        "carb_g": float(macros.get("carb_g", 0.0)),
    }


def _recalculate_plan_macros(plan: Dict[str, Any]) -> Dict[str, float]:
    """Recalculate total macros from plan."""
    total = {"kcal": 0.0, "protein_g": 0.0, "fat_g": 0.0, "carb_g": 0.0}

    if plan.get("plan_type") == "day":
        for meal_data in plan.get("meals", {}).values():
            recipe = meal_data.get("recipe", {})
            servings = float(meal_data.get("servings", 1.0))
            macros = _get_meal_macros(recipe)
            for key in total:
                total[key] += macros[key] * servings
    elif plan.get("plan_type") == "week":
        for day_data in plan.get("days", {}).values():
            for meal_data in day_data.get("meals", {}).values():
                recipe = meal_data.get("recipe", {})
                servings = float(meal_data.get("servings", 1.0))
                macros = _get_meal_macros(recipe)
                for key in total:
                    total[key] += macros[key] * servings

    return total


@tool
async def apply_snack_tool(
    tree_data: TreeData,
    client_manager: ClientManager,
    snack_recipe: Dict[str, Any] | None = None,
    snack_food_id: str | None = None,
    servings: float = 1.0,
    meal_type: str = "snack",
    day_index: int | None = None,
    day_date: str | None = None,
    **kwargs,
) -> AsyncGenerator[Result | str | Error, None]:
    """
    Add snack to plan and recalculate totals.

    Environment reads:
      - environment["plan_assemble_day_tool"]["plan"] or
      - environment["plan_assemble_weekly_tool"]["plan"]
      - environment["suggest_snack_tool"]["suggestions"] (optional - if snack_recipe not provided)
    Environment writes:
      - environment["apply_snack_tool"]["updated_plan"]
    """
    yield "Adding snack to plan..."

    # Read plan (create a copy to avoid mutating the original)
    weekly_results = tree_data.environment.find("plan_assemble_weekly_tool", "plan")
    daily_results = tree_data.environment.find("plan_assemble_day_tool", "plan")

    plan = None
    plan_source = None
    if weekly_results and weekly_results[0].objects:
        plan = copy.deepcopy(weekly_results[0].objects[0])  # Deep copy to avoid mutations
        plan_source = "plan_assemble_weekly_tool"
    elif daily_results and daily_results[0].objects:
        plan = copy.deepcopy(daily_results[0].objects[0])  # Deep copy to avoid mutations
        plan_source = "plan_assemble_day_tool"
    else:
        yield Error("No plan found. Run plan_assemble_day_tool or plan_assemble_weekly_tool first.")
        return

    # Get snack recipe
    snack = snack_recipe
    if not snack and snack_food_id:
        try:
            with client_manager.connect_to_client() as client:
                recipe_collection = client.collections.get("Recipe")
                results = recipe_collection.query.fetch_objects(
                    where={"path": ["food_id"], "operator": "Equal", "valueString": snack_food_id},
                    limit=1,
                )
                if results.objects:
                    snack = results.objects[0].properties
        except Exception as e:
            yield Error(f"Failed to fetch snack recipe: {str(e)}")
            return

    if not snack:
        # Try to get from suggestions
        suggestions_results = tree_data.environment.find("suggest_snack_tool", "suggestions")
        if suggestions_results and suggestions_results[0].objects:
            suggestions = suggestions_results[0].objects[0].get("suggestions", [])
            if suggestions:
                snack = suggestions[0]  # Use first suggestion
            else:
                yield Error("No snack recipe provided and no suggestions available.")
                return
        else:
            yield Error("No snack recipe provided. Provide snack_recipe or snack_food_id, or run suggest_snack_tool first.")
            return

    # Add snack to plan
    snack_meal = {
        "recipe": snack,
        "servings": servings,
        "meal_type": meal_type,
    }

    if plan.get("plan_type") == "day":
        # Add to daily plan
        if "snacks" not in plan:
            plan["snacks"] = []
        plan["snacks"].append(snack_meal)
    elif plan.get("plan_type") == "week":
        # Determine target day
        target_day_key = None
        if day_date:
            # Use specific date
            target_day_key = day_date
        elif day_index is not None:
            # Use day index (0-6)
            if 0 <= day_index < 7:
                sorted_days = sorted(plan.get("days", {}).keys())
                if day_index < len(sorted_days):
                    target_day_key = sorted_days[day_index]
            else:
                yield Error(f"day_index must be between 0 and 6, got {day_index}")
                return
        else:
            # Default to first day
            target_day_key = sorted(plan.get("days", {}).keys())[0] if plan.get("days") else None
        
        if target_day_key and target_day_key in plan.get("days", {}):
            if "snacks" not in plan["days"][target_day_key]:
                plan["days"][target_day_key]["snacks"] = []
            plan["days"][target_day_key]["snacks"].append(snack_meal)
        else:
            yield Error(f"Target day not found: {target_day_key or day_date or day_index}")
            return

    # Recalculate totals
    updated_macros = _recalculate_plan_macros(plan)
    plan["total_macros"] = updated_macros

    if plan.get("plan_type") == "week":
        plan["average_daily_macros"] = {
            "kcal": updated_macros["kcal"] / 7.0,
            "protein_g": updated_macros["protein_g"] / 7.0,
            "fat_g": updated_macros["fat_g"] / 7.0,
            "carb_g": updated_macros["carb_g"] / 7.0,
        }

    yield Result(
        name="updated_plan",
        objects=[plan],
        metadata={"plan_type": plan.get("plan_type"), "snack_added": True},
    )
    yield f"Snack added. Updated totals: {updated_macros['kcal']:.0f} kcal | {updated_macros['protein_g']:.0f}g P"

