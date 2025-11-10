"""
Calculate macro deficits in meal plans.
"""
from typing import AsyncGenerator, Dict, Any

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


def _calculate_plan_macros(plan: Dict[str, Any]) -> Dict[str, float]:
    """Calculate total macros from a plan."""
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
async def gap_calc_tool(
    tree_data: TreeData,
    client_manager: ClientManager,
    **kwargs,
) -> AsyncGenerator[Result | str | Error, None]:
    """
    Calculate macro deficits (gaps) in meal plans.

    Environment reads:
      - environment["plan_assemble_day_tool"]["plan"] or
      - environment["plan_assemble_weekly_tool"]["plan"]
      - environment["target_resolver_tool"]["resolved"] or
      - environment["macro_calc_tool"]["targets"]
    Environment writes:
      - environment["gap_calc_tool"]["deficits"]
    """
    yield "Calculating macro deficits..."

    # Read plan
    weekly_results = tree_data.environment.find("plan_assemble_weekly_tool", "plan")
    daily_results = tree_data.environment.find("plan_assemble_day_tool", "plan")

    plan = None
    if weekly_results and weekly_results[0].objects:
        plan = weekly_results[0].objects[0]
    elif daily_results and daily_results[0].objects:
        plan = daily_results[0].objects[0]
    else:
        yield Error("No plan found. Run plan_assemble_day_tool or plan_assemble_weekly_tool first.")
        return

    # Read targets
    target_results = tree_data.environment.find("target_resolver_tool", "resolved")
    if not target_results or not target_results[0].objects:
        target_results = tree_data.environment.find("macro_calc_tool", "targets")

    if not target_results or not target_results[0].objects:
        yield Error("Targets not found. Run target_resolver_tool or macro_calc_tool first.")
        return

    targets = target_results[0].objects[0]

    # Calculate plan macros
    plan_macros = _calculate_plan_macros(plan)

    # Get target macros (adjust for weekly if needed)
    if plan.get("plan_type") == "week":
        # Weekly targets = daily targets × 7
        target_macros = {
            "kcal": float(targets.get("tdee_kcal", 2000)) * 7.0,
            "protein_g": float(targets.get("protein_g", 150)) * 7.0,
            "fat_g": float(targets.get("fat_g", 67)) * 7.0,
            "carb_g": float(targets.get("carb_g", 200)) * 7.0,
        }
    else:
        # Daily targets
        target_macros = {
            "kcal": float(targets.get("tdee_kcal", 2000)),
            "protein_g": float(targets.get("protein_g", 150)),
            "fat_g": float(targets.get("fat_g", 67)),
            "carb_g": float(targets.get("carb_g", 200)),
        }

    # Calculate deficits (negative = deficit, positive = surplus)
    deficits = {
        "kcal": target_macros["kcal"] - plan_macros["kcal"],
        "protein_g": target_macros["protein_g"] - plan_macros["protein_g"],
        "fat_g": target_macros["fat_g"] - plan_macros["fat_g"],
        "carb_g": target_macros["carb_g"] - plan_macros["carb_g"],
    }

    # Identify which macros have deficits
    deficit_macros = {k: v for k, v in deficits.items() if v > 0}

    deficits_output = {
        "plan_type": plan.get("plan_type"),
        "plan_macros": plan_macros,
        "target_macros": target_macros,
        "deficits": deficits,
        "deficit_macros": deficit_macros,
        "has_deficits": len(deficit_macros) > 0,
    }

    yield Result(
        name="deficits",
        objects=[deficits_output],
        metadata={
            "plan_type": plan.get("plan_type"),
            "has_deficits": len(deficit_macros) > 0,
            "deficit_count": len(deficit_macros),
        },
    )

    if deficit_macros:
        deficit_str = ", ".join([f"{k}: {v:.1f}" for k, v in deficit_macros.items()])
        yield f"Deficits found: {deficit_str}"
    else:
        yield "No deficits - plan meets or exceeds targets"

