"""
End-to-end micronutrient tool: check totals → identify deficits → suggest foods.
"""
from typing import AsyncGenerator, Dict, Any, List
import logging

from elysia.tree.objects import TreeData
from elysia.objects import Result, Error, Response
from elysia.util.client import ClientManager
from elysia import tool

from MealAgent.tools.utils.weaviate_filters import build_filters_from_where


# RDA (Recommended Daily Allowance) values for common micronutrients
# Source: USDA Dietary Guidelines
DEFAULT_RDAs = {
    "calcium_mg": 1000.0,
    "iron_mg": 18.0,
    "potassium_mg": 2600.0,
    "vitamin_c_mg": 90.0,
    "vitamin_a_rae_ug": 900.0,
}


def _convert_to_grams(quantity: float, unit: str, fdc_id: int | None, client) -> float:
    """Convert quantity to grams using FdcPortion."""
    if unit.lower() == "g":
        return quantity

    if fdc_id:
        try:
            portion_collection = client.collections.get("FdcPortion")
            portion_filter = build_filters_from_where(
                {"path": ["fdc_id"], "operator": "Equal", "valueInt": int(fdc_id)}
            )
            portion_results = portion_collection.query.fetch_objects(filters=portion_filter, limit=10)

            for portion_obj in portion_results.objects:
                portion = portion_obj.properties
                if portion.get("measure_unit", "").lower() == unit.lower():
                    gram_weight = portion.get("gram_weight", 0.0)
                    if gram_weight > 0:
                        portion_amount = portion.get("amount", 1.0)
                        return (quantity / portion_amount) * gram_weight
        except Exception:
            return quantity  # Fallback: assume grams if collection unavailable

    return quantity  # Fallback: assume grams


@tool
async def micros_tool(
    tree_data: TreeData,
    client_manager: ClientManager,
    rda_overrides: Dict[str, float] | None = None,  # Override default RDAs
    top_k: int = 10,  # Number of food suggestions per deficient nutrient
    **kwargs,
) -> AsyncGenerator[Result | Response | Error, None]:
    """
    Micronutrient auditor: plan aggregation → deficit detection → food suggestions.

    Contract:
      Reads – latest plan (day/week) plus optional `profile` metadata for gender-based RDAs.
      Writes – `micros_tool.totals` (with `deficits` flag) and `micros_tool.suggestions` / table for UI.

    Decision hints:
      • `totals.has_deficits=False` ⇒ no action required.
      • `suggestions` gives actionable foods; pair with substitution or gap-fill follow-ups.
    """
    logging.info("micros_tool: start")
    yield Response("🔬 Analyzing micronutrients (vitamins & minerals) in your plan...")
    
    try:
        # Step 1: Read plan from E2E tools
        plan = None
        plan_source = None
        
        day_plan_results = tree_data.environment.find("plan_day_e2e_tool", "plan")
        if day_plan_results and day_plan_results[0]["objects"]:
            plan = day_plan_results[0]["objects"][0]
            plan_source = "plan_day_e2e_tool"
        else:
            week_plan_results = tree_data.environment.find("plan_week_e2e_tool", "plan")
            if week_plan_results and week_plan_results[0]["objects"]:
                plan = week_plan_results[0]["objects"][0]
                plan_source = "plan_week_e2e_tool"
            else:
                yield Error("No plan found. Run plan_day_e2e_tool or plan_week_e2e_tool first.")
                return
        
        # Step 2: Get RDA values (adjust for gender if profile available)
        rdas = DEFAULT_RDAs.copy()
        if rda_overrides:
            rdas.update(rda_overrides)
        
        # Try to get gender from profile for RDA adjustments
        profile_results = tree_data.environment.find("profile_crud_tool", "profile")
        if profile_results and profile_results[0]["objects"]:
            profile = profile_results[0]["objects"][0]
            gender = profile.get("gender", "").lower()
            if gender == "female":
                rdas["iron_mg"] = 18.0
                rdas["vitamin_c_mg"] = 75.0
                rdas["vitamin_a_rae_ug"] = 700.0
            elif gender == "male":
                rdas["iron_mg"] = 8.0
                rdas["vitamin_c_mg"] = 90.0
                rdas["vitamin_a_rae_ug"] = 900.0
        
        # Step 3: Aggregate micronutrients from plan
        yield Response("📊 Aggregating micronutrients from all meals...")
        
        client = client_manager.get_client()
        try:
            fdc_collection = client.collections.get("FdcFood")
        except Exception as e:
            yield Error(f"FdcFood collection not found: {str(e)}. Please ensure collections are created.")
            return
        
        total_micros: Dict[str, float] = {}
        
        # Collect all fdc_ids and their quantities first (batch optimization)
        fdc_data_map: Dict[int, List[Dict[str, Any]]] = {}
        
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
                            fdc_id_int = int(fdc_id)
                            if fdc_id_int not in fdc_data_map:
                                fdc_data_map[fdc_id_int] = []
                            fdc_data_map[fdc_id_int].append({
                                "quantity_g": quantity_g,
                                "servings": servings,
                            })
        
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
                                fdc_id_int = int(fdc_id)
                                if fdc_id_int not in fdc_data_map:
                                    fdc_data_map[fdc_id_int] = []
                                fdc_data_map[fdc_id_int].append({
                                    "quantity_g": quantity_g,
                                    "servings": servings,
                                })
        
        # Batch fetch all FDC foods at once
        if fdc_data_map:
            unique_fdc_ids = list(fdc_data_map.keys())
            # Batch fetch using ContainsAny filter (more efficient than multiple queries)
            try:
                batch_filter = build_filters_from_where(
                    {"path": ["fdc_id"], "operator": "ContainsAny", "valueIntArray": unique_fdc_ids}
                )
                batch_results = fdc_collection.query.fetch_objects(filters=batch_filter, limit=len(unique_fdc_ids))
                
                # Create lookup map
                fdc_foods_map: Dict[int, Dict[str, Any]] = {}
                for obj in batch_results.objects:
                    fdc_id = obj.properties.get("fdc_id")
                    if fdc_id:
                        fdc_foods_map[int(fdc_id)] = obj.properties
                
                # Process all collected data
                micro_fields = [
                    ("calcium_mg_100g", "calcium_mg"),
                    ("iron_mg_100g", "iron_mg"),
                    ("potassium_mg_100g", "potassium_mg"),
                    ("vitamin_c_mg_100g", "vitamin_c_mg"),
                    ("vitamin_a_rae_ug_100g", "vitamin_a_rae_ug"),
                ]
                
                for fdc_id, data_list in fdc_data_map.items():
                    fdc_food = fdc_foods_map.get(fdc_id)
                    if not fdc_food:
                        continue
                    
                    for data in data_list:
                        quantity_g = data["quantity_g"]
                        servings = data["servings"]
                        scale = (quantity_g * servings) / 100.0
                        
                        for field, key in micro_fields:
                            if field in fdc_food:
                                total_micros[key] = total_micros.get(key, 0.0) + float(fdc_food.get(field, 0.0)) * scale
            except Exception as e:
                logging.warning(f"Batch fetch failed, falling back to individual queries: {str(e)}")
                # Fallback to individual queries if batch fails
                for fdc_id, data_list in fdc_data_map.items():
                    try:
                        fdc_filter = build_filters_from_where(
                            {"path": ["fdc_id"], "operator": "Equal", "valueInt": fdc_id}
                        )
                        fdc_results = fdc_collection.query.fetch_objects(filters=fdc_filter, limit=1)
                        if fdc_results.objects:
                            fdc_food = fdc_results.objects[0].properties
                            micro_fields = [
                                ("calcium_mg_100g", "calcium_mg"),
                                ("iron_mg_100g", "iron_mg"),
                                ("potassium_mg_100g", "potassium_mg"),
                                ("vitamin_c_mg_100g", "vitamin_c_mg"),
                                ("vitamin_a_rae_ug_100g", "vitamin_a_rae_ug"),
                            ]
                            for data in data_list:
                                scale = (data["quantity_g"] * data["servings"]) / 100.0
                                for field, key in micro_fields:
                                    if field in fdc_food:
                                        total_micros[key] = total_micros.get(key, 0.0) + float(fdc_food.get(field, 0.0)) * scale
                    except Exception:
                        continue
        
        # Calculate averages for weekly plans
        if plan.get("plan_type") == "week":
            avg_micros = {k: v / 7.0 for k, v in total_micros.items()}
            # Compare against daily RDA (not weekly)
            target_micros = rdas
        else:
            avg_micros = total_micros
            target_micros = rdas
        
        # Step 4: Identify deficits
        deficits = {}
        for nutrient, total in avg_micros.items():
            rda = target_micros.get(nutrient, 0.0)
            if rda > 0 and total < rda:
                deficit = rda - total
                deficits[nutrient] = {
                    "total": total,
                    "rda": rda,
                    "deficit": deficit,
                    "deficit_percent": (deficit / rda) * 100.0,
                }
        
        totals_output = {
            "plan_type": plan.get("plan_type"),
            "total_micros": total_micros,
            "average_daily_micros": avg_micros,
            "rdas": target_micros,
            "deficits": deficits,
            "has_deficits": len(deficits) > 0,
        }
        
        yield Result(
            name="totals",
            objects=[totals_output],
            metadata={
                "plan_type": plan.get("plan_type"),
                "micro_count": len(total_micros),
                "deficit_count": len(deficits),
            },
            payload_type="generic",
            display=True,
        )
        
        if deficits:
            deficit_list = []
            for k, v in list(deficits.items())[:3]:
                nutrient_name = k.replace("_mg", "").replace("_ug", "").replace("_", " ").title()
                deficit_list.append(f"{nutrient_name}: {v['deficit']:.1f}")
            deficit_str = ", ".join(deficit_list)
            yield Response(f"⚠️ Micronutrient deficits: {deficit_str}...")
        else:
            yield Response("✅ All micronutrients meet or exceed RDA values!")
            return
        
        # Step 5: Suggest foods for deficient nutrients
        yield Response("🔍 Searching for foods rich in deficient nutrients...")
        
        deficient_nutrients = list(deficits.keys())
        nutrient_field_map = {
            "calcium_mg": "calcium_mg_100g",
            "iron_mg": "iron_mg_100g",
            "potassium_mg": "potassium_mg_100g",
            "vitamin_c_mg": "vitamin_c_mg_100g",
            "vitamin_a_rae_ug": "vitamin_a_rae_ug_100g",
        }
        
        all_suggestions = []
        
        try:
            # Query once with higher limit
            results = fdc_collection.query.fetch_objects(limit=500)
            
            # Process each deficient nutrient
            for nutrient in deficient_nutrients:
                field = nutrient_field_map.get(nutrient)
                if not field:
                    continue
                
                # Filter and score by nutrient content
                scored_foods = []
                for obj in results.objects:
                    food = obj.properties
                    nutrient_value = float(food.get(field, 0.0))
                    if nutrient_value > 0:
                        scored_foods.append({
                            "fdc_id": food.get("fdc_id"),
                            "description": food.get("description", ""),
                            "nutrient": nutrient,
                            "nutrient_value": nutrient_value,
                            "nutrient_value_per_100g": nutrient_value,
                        })
                
                # Sort by nutrient value and take top_k
                scored_foods.sort(key=lambda x: x.get("nutrient_value", 0.0), reverse=True)
                all_suggestions.extend(scored_foods[:top_k])
        
        except Exception as e:
            logging.error(f"micros_tool: Failed to query FDC foods: {str(e)}", exc_info=True)
            yield Error(f"Failed to query FDC foods: {str(e)}")
            return
        
        # Deduplicate by fdc_id
        seen = set()
        unique_suggestions = []
        for sug in all_suggestions:
            fdc_id = sug.get("fdc_id")
            if fdc_id and fdc_id not in seen:
                seen.add(fdc_id)
                unique_suggestions.append(sug)
        
        suggestions_output = {
            "deficient_nutrients": deficient_nutrients,
            "suggestions": unique_suggestions[:top_k * len(deficient_nutrients)],
            "count": len(unique_suggestions[:top_k * len(deficient_nutrients)]),
        }
        
        yield Result(
            name="suggestions",
            objects=[suggestions_output],
            metadata={
                "suggestion_count": len(unique_suggestions[:top_k * len(deficient_nutrients)]),
                "deficient_count": len(deficient_nutrients),
            },
            payload_type="generic",
            display=True,
        )
        
        yield Result(
            name="suggestions_table",
            objects=unique_suggestions[:top_k * len(deficient_nutrients)],
            metadata={
                "suggestion_count": len(unique_suggestions[:top_k * len(deficient_nutrients)]),
                "deficient_count": len(deficient_nutrients),
            },
            payload_type="table",
            display=True,
        )
        
        if unique_suggestions:
            count = len(unique_suggestions[:top_k * len(deficient_nutrients)])
            yield Response(f"✅ Found {count} food suggestion(s) to fill micronutrient gaps")
        else:
            yield Response("⚠️ No suitable foods found for deficient nutrients")
    
    except ValueError as e:
        error_msg = f"Invalid input: {str(e)}"
        logging.error(f"micros_tool: {error_msg}", exc_info=True)
        yield Error(error_msg)
        return
    except Exception as e:
        error_msg = f"micros_tool failed: {str(e)}"
        logging.error(f"micros_tool: {error_msg}", exc_info=True)
        yield Error(error_msg)
        return

