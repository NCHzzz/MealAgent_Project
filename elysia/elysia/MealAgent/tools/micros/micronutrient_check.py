"""
Aggregate micronutrients from FdcFood per-100g fields for meal plans.

Note: This implementation uses FdcFood per-100g fields for simplicity.
For more accurate micronutrient tracking, consider integrating FdcNutrient
collection which provides detailed nutrient breakdowns with proper units.
"""
from typing import AsyncGenerator, Dict, Any, List

from elysia.tree.objects import TreeData
from elysia.objects import Result, Error
from elysia.util.client import ClientManager
from elysia import tool


def _convert_to_grams(quantity: float, unit: str, fdc_id: int | None, client) -> float:
    """Convert quantity to grams using FdcPortion."""
    if unit.lower() == "g":
        return quantity

    if fdc_id:
        try:
            portion_collection = client.collections.get("FdcPortion")
            portion_results = portion_collection.query.fetch_objects(
                where={
                    "path": ["fdc_id"],
                    "operator": "Equal",
                    "valueInt": int(fdc_id),
                },
                limit=10,
            )

            for portion_obj in portion_results.objects:
                portion = portion_obj.properties
                if portion.get("measure_unit", "").lower() == unit.lower():
                    gram_weight = portion.get("gram_weight", 0.0)
                    if gram_weight > 0:
                        portion_amount = portion.get("amount", 1.0)
                        return (quantity / portion_amount) * gram_weight
        except Exception:
            pass

    return quantity  # Fallback: assume grams


@tool
async def micronutrient_check_tool(
    tree_data: TreeData,
    client_manager: ClientManager,
    **kwargs,
) -> AsyncGenerator[Result | str | Error, None]:
    """
    Aggregate micronutrients from FdcNutrient + FdcPortion for meal plans.

    Environment reads:
      - environment["plan_assemble_day_tool"]["plan"] or
      - environment["plan_assemble_weekly_tool"]["plan"]
    Environment writes:
      - environment["micronutrient_check_tool"]["micros"]
    """
    yield "Calculating micronutrients..."

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

    try:
        with client_manager.connect_to_client() as client:
            fdc_collection = client.collections.get("FdcFood")
            # Note: FdcNutrient collection is available but not used in this simplified implementation
            # For production, consider querying FdcNutrient for more accurate micronutrient data

            # Aggregate micronutrients
            total_micros: Dict[str, float] = {}

            if plan.get("plan_type") == "day":
                for meal_data in plan.get("meals", {}).values():
                    recipe = meal_data.get("recipe", {})
                    servings = float(meal_data.get("servings", 1.0))
                    ingredient_map = recipe.get("ingredient_fdc_map", [])

                    for ing_entry in ingredient_map:
                        if isinstance(ing_entry, dict):
                            fdc_id = ing_entry.get("fdc_id")
                            quantity_g = float(ing_entry.get("quantity_g", 0.0))

                            if fdc_id:
                                # Get FdcFood
                                fdc_results = fdc_collection.query.fetch_objects(
                                    where={"path": ["fdc_id"], "operator": "Equal", "valueInt": int(fdc_id)},
                                    limit=1,
                                )
                                if fdc_results.objects:
                                    fdc_food = fdc_results.objects[0].properties
                                    scale = (quantity_g * servings) / 100.0

                                    # Get micronutrients from FdcFood (simplified - using per-100g fields)
                                    micro_fields = [
                                        "calcium_mg_100g",
                                        "iron_mg_100g",
                                        "potassium_mg_100g",
                                        "vitamin_c_mg_100g",
                                        "vitamin_a_iu_100g",
                                    ]
                                    for field in micro_fields:
                                        if field in fdc_food:
                                            key = field.replace("_100g", "").replace("_iu", "_IU")
                                            total_micros[key] = total_micros.get(key, 0.0) + float(fdc_food.get(field, 0.0)) * scale

            elif plan.get("plan_type") == "week":
                for day_data in plan.get("days", {}).values():
                    for meal_data in day_data.get("meals", {}).values():
                        recipe = meal_data.get("recipe", {})
                        servings = float(meal_data.get("servings", 1.0))
                        ingredient_map = recipe.get("ingredient_fdc_map", [])

                        for ing_entry in ingredient_map:
                            if isinstance(ing_entry, dict):
                                fdc_id = ing_entry.get("fdc_id")
                                quantity_g = float(ing_entry.get("quantity_g", 0.0))

                                if fdc_id:
                                    fdc_results = fdc_collection.query.fetch_objects(
                                        where={"path": ["fdc_id"], "operator": "Equal", "valueInt": int(fdc_id)},
                                        limit=1,
                                    )
                                    if fdc_results.objects:
                                        fdc_food = fdc_results.objects[0].properties
                                        scale = (quantity_g * servings) / 100.0

                                        micro_fields = [
                                            "calcium_mg_100g",
                                            "iron_mg_100g",
                                            "potassium_mg_100g",
                                            "vitamin_c_mg_100g",
                                            "vitamin_a_iu_100g",
                                        ]
                                        for field in micro_fields:
                                            if field in fdc_food:
                                                key = field.replace("_100g", "").replace("_iu", "_IU")
                                                total_micros[key] = total_micros.get(key, 0.0) + float(fdc_food.get(field, 0.0)) * scale

            # Calculate averages for weekly plans
            if plan.get("plan_type") == "week":
                avg_micros = {k: v / 7.0 for k, v in total_micros.items()}
            else:
                avg_micros = total_micros

            micros_output = {
                "plan_type": plan.get("plan_type"),
                "total_micros": total_micros,
                "average_daily_micros": avg_micros,
            }

            yield Result(
                name="micros",
                objects=[micros_output],
                metadata={"plan_type": plan.get("plan_type"), "micro_count": len(total_micros)},
            )

            micro_summary = ", ".join([f"{k}: {v:.1f}" for k, v in list(total_micros.items())[:3]])
            yield f"Micronutrients calculated: {micro_summary}..."

    except Exception as e:
        yield Error(f"Micronutrient calculation failed: {str(e)}")
        return

