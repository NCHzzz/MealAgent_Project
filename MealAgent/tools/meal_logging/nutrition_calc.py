from typing import AsyncGenerator, Dict, Any
import logging

from elysia.tree.objects import TreeData
from elysia.objects import Result, Error, Response
from elysia.util.client import ClientManager
from elysia import tool

# Constants
MAX_PORTION_QUERY_LIMIT = 10


@tool
async def nutrition_calc_tool(
    tree_data: TreeData,
    client_manager: ClientManager,
    **kwargs,
) -> AsyncGenerator[Result | str | Error, None]:
    """
    Calculate nutrition (macros/micros) from parsed meal ingredients.

    Code-Based Tool: Uses FdcFood per-100g fields (simplified - uses FdcFood directly instead of FdcNutrient for performance).

    Environment reads:
      - environment["meal_parser_tool"]["parsed_meal"]
    Environment writes:
      - environment["nutrition_calc_tool"]["calculated"]
    """
    logging.info("nutrition_calc_tool: start")
    yield Response("Calculating nutrition...")

    try:
        # Read parsed meal from environment
        parsed_results = tree_data.environment.find("meal_parser_tool", "parsed_meal")
        if not parsed_results or not parsed_results[0].objects:
            error_msg = "Parsed meal not found. Run meal_parser_tool first."
            logging.error(f"nutrition_calc_tool: {error_msg}")
            yield Error(error_msg)
            return

        parsed_meal = parsed_results[0].objects[0]
        ingredients = parsed_meal.get("ingredients", [])
        portion_size = parsed_meal.get("portion_size", 1.0)

        client = client_manager.get_client()
        fdc_collection = client.collections.get("FdcFood")

        total_macros = {"kcal": 0.0, "protein_g": 0.0, "fat_g": 0.0, "carb_g": 0.0}
        total_micros: Dict[str, float] = {}
        warnings = []  # Collect warnings for all ingredients

        # Calculate nutrition for each ingredient
        for ing in ingredients:
            fdc_id = ing.get("fdc_id")
            amount = float(ing.get("amount", 0))
            unit = ing.get("unit", "g")

            if not fdc_id:
                continue

            # Fetch FdcFood
            fdc_results = fdc_collection.query.fetch_objects(
                where={"path": ["fdc_id"], "operator": "Equal", "valueInt": int(fdc_id)},
                limit=1,
            )

            if not fdc_results.objects:
                continue

            fdc_food = fdc_results.objects[0].properties

            # Convert to grams using FdcPortion if unit is not "g"
            grams = amount
            if unit != "g":
                # Try to find matching portion conversion
                portion_collection = client.collections.get("FdcPortion")
                portion_results = portion_collection.query.fetch_objects(
                    where={
                        "path": ["fdc_id"],
                        "operator": "Equal",
                        "valueInt": int(fdc_id),
                    },
                    limit=MAX_PORTION_QUERY_LIMIT,
                )
                
                # Find matching portion by unit and approximate amount
                converted = False
                for portion_obj in portion_results.objects:
                    portion = portion_obj.properties
                    if portion.get("measure_unit", "").lower() == unit.lower():
                        # Use gram_weight if available, otherwise estimate
                        gram_weight = portion.get("gram_weight", 0.0)
                        if gram_weight > 0:
                            # Scale by amount / portion amount
                            portion_amount = portion.get("amount", 1.0)
                            grams = (amount / portion_amount) * gram_weight
                            converted = True
                            break
                
                # If no match found, assume unit is grams (may be inaccurate)
                if not converted:
                    warnings.append(f"Could not convert {amount} {unit} to grams for ingredient '{ing.get('name', 'unknown')}', assuming grams")

            # Calculate nutrition (per 100g basis from FdcFood)
            scale = (grams * portion_size) / 100.0

            # Macros from FdcFood
            total_macros["kcal"] += float(fdc_food.get("energy_kcal_100g", 0.0)) * scale
            total_macros["protein_g"] += float(fdc_food.get("protein_g_100g", 0.0)) * scale
            total_macros["fat_g"] += float(fdc_food.get("fat_g_100g", 0.0)) * scale
            total_macros["carb_g"] += float(fdc_food.get("carbohydrate_g_100g", 0.0)) * scale

            # Micronutrients from FdcFood (if available)
            micro_fields = [
                "calcium_mg_100g",
                "iron_mg_100g",
                "potassium_mg_100g",
                "vitamin_c_mg_100g",
            ]
            for field in micro_fields:
                if field in fdc_food:
                    key = field.replace("_100g", "")
                    total_micros[key] = total_micros.get(key, 0.0) + float(fdc_food.get(field, 0.0)) * scale

        calculated_nutrition = {
            "calculated_macros": total_macros,
            "calculated_micros": total_micros,
            "portion_size": portion_size,
        }

        logging.info(
            f"nutrition_calc_tool: complete (ingredients={len(ingredients)}, "
            f"kcal={total_macros['kcal']:.0f}, warnings={len(warnings)})"
        )

        yield Result(
            name="calculated",
            objects=[calculated_nutrition],
            metadata={
                "ingredients_count": len(ingredients),
                "validated_count": sum(1 for ing in ingredients if ing.get("fdc_id")),
                "warnings": warnings,
            },
            payload_type="generic",
        )
        result_msg = f"Nutrition calculated: {total_macros['kcal']:.0f} kcal | {total_macros['protein_g']:.0f}g P"
        if warnings:
            result_msg += f" | Warning: {'; '.join(warnings)}"
        yield Response(result_msg)

    except ValueError as e:
        error_msg = f"Invalid input: {str(e)}"
        logging.error(f"nutrition_calc_tool: {error_msg}", exc_info=True)
        yield Error(error_msg)
        return
    except Exception as e:
        dish_name = parsed_meal.get("dish", "unknown") if 'parsed_meal' in locals() else "unknown"
        error_msg = f"Nutrition calculation failed for meal '{dish_name}': {str(e)}"
        logging.error(f"nutrition_calc_tool: {error_msg}", exc_info=True)
        yield Error(error_msg)
        return

