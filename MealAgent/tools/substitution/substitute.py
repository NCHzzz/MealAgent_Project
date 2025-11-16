"""
End-to-end substitution tool: suggest substitutes → optionally apply to plan.
"""
from typing import AsyncGenerator, Dict, Any, List
import copy
import logging

from elysia.tree.objects import TreeData
from elysia.objects import Result, Error, Response
from elysia.util.client import ClientManager
from elysia import tool

from MealAgent.tools.nutrition.calculate_recipe_macros import calculate_recipe_macros_tool


def _macro_match_score(
    original_macros: Dict[str, float],
    substitute_macros: Dict[str, float],
    tolerance: float = 0.2,
) -> float:
    """
    Calculate how well substitute matches original macros (0-100, higher is better).
    Uses ±20% tolerance by default.
    """
    if not original_macros or not substitute_macros:
        return 0.0

    scores = []
    for macro in ["kcal", "protein_g", "fat_g", "carb_g"]:
        original_val = original_macros.get(macro, 0.0)
        substitute_val = substitute_macros.get(macro, 0.0)

        if original_val > 0:
            ratio = substitute_val / original_val
            # Score: 100 if exact match, decreases as ratio deviates from 1.0
            # Within tolerance (0.8-1.2), score is high
            if 1.0 - tolerance <= ratio <= 1.0 + tolerance:
                score = 100.0 - abs(ratio - 1.0) * 100.0 / tolerance
                scores.append(max(0.0, score))
            else:
                scores.append(0.0)
        elif substitute_val == 0:
            scores.append(100.0)  # Both zero = match
        else:
            scores.append(0.0)

    return sum(scores) / len(scores) if scores else 0.0


@tool
async def substitute_tool(
    tree_data: TreeData,
    client_manager: ClientManager,
    ingredient_name: str = "",
    fdc_id: int | None = None,
    substitute_fdc_id: int | None = None,  # If provided, skip suggestion and apply directly
    tolerance: float = 0.2,
    top_k: int = 10,
    auto_apply: bool = False,  # If True, automatically apply best substitute
    recalculate_macros: bool = True,
    **kwargs,
) -> AsyncGenerator[Result | Response | Error, None]:
    """
    End-to-end substitution: suggest substitutes → optionally apply to plan.
    
    This tool orchestrates the full substitution workflow:
    1. Read plan from environment (plan_day_e2e_tool.plan or plan_week_e2e_tool.plan)
    2. Identify ingredient to substitute (from plan or parameters)
    3. Suggest macro-tolerant substitutes (±20% tolerance)
    4. Optionally apply best substitute to plan (if auto_apply=True)
    5. Recalculate recipe macros if needed
    
    Environment reads:
      - plan_day_e2e_tool.plan or plan_week_e2e_tool.plan (optional - if ingredient not specified)
      - macro_calc_tool.targets (for allergen checks)
    Environment writes:
      - substitute_tool.substitutes: suggested substitutes
      - substitute_tool.updated_plan: plan with substitute applied (if auto_apply=True)
    
    Decision hints:
      - If substitute_tool.substitutes is present, substitute suggestions are available.
      - If auto_apply=True, substitute_tool.updated_plan contains the plan with substitute applied.
    """
    logging.info("substitute_tool: start")
    yield Response("Finding ingredient substitutes...")
    
    try:
        # Step 1: Identify ingredient to substitute
        original_fdc_id = fdc_id
        original_ingredient_name = ingredient_name
        
        # If ingredient not specified, try to extract from plan (future enhancement)
        # For now, require ingredient_name or fdc_id
        
        if not original_ingredient_name and not original_fdc_id:
            yield Error("ingredient_name or fdc_id is required")
            return
        
        # Step 2: Get original ingredient macros
        client = client_manager.get_client()
        fdc_collection = client.collections.get("FdcFood")
        
        original_fdc = None
        if original_fdc_id:
            results = fdc_collection.query.fetch_objects(
                where={"path": ["fdc_id"], "operator": "Equal", "valueInt": int(original_fdc_id)},
                limit=1,
            )
            if results.objects:
                original_fdc = results.objects[0].properties
        elif original_ingredient_name:
            # Search by description
            results = fdc_collection.query.bm25(
                query=original_ingredient_name,
                limit=1,
            )
            if results.objects:
                original_fdc = results.objects[0].properties
                original_fdc_id = original_fdc.get("fdc_id")
        
        if not original_fdc:
            yield Error(f"Ingredient not found: {original_ingredient_name or original_fdc_id}")
            return
        
        # Get original macros (per 100g)
        original_macros = {
            "kcal": float(original_fdc.get("energy_kcal_100g", 0.0)),
            "protein_g": float(original_fdc.get("protein_g_100g", 0.0)),
            "fat_g": float(original_fdc.get("fat_g_100g", 0.0)),
            "carb_g": float(original_fdc.get("carbohydrate_g_100g", 0.0)),
        }
        
        # Step 3: Suggest substitutes (unless substitute_fdc_id provided)
        suggestions = []
        if substitute_fdc_id:
            # Direct apply mode - fetch substitute
            sub_results = fdc_collection.query.fetch_objects(
                where={"path": ["fdc_id"], "operator": "Equal", "valueInt": int(substitute_fdc_id)},
                limit=1,
            )
            if not sub_results.objects:
                yield Error(f"Substitute FDC ID {substitute_fdc_id} not found")
                return
            substitute_fdc = sub_results.objects[0].properties
            suggestions = [{
                "fdc_id": substitute_fdc_id,
                "description": substitute_fdc.get("description", ""),
                "macros_per_100g": {
                    "kcal": float(substitute_fdc.get("energy_kcal_100g", 0.0)),
                    "protein_g": float(substitute_fdc.get("protein_g_100g", 0.0)),
                    "fat_g": float(substitute_fdc.get("fat_g_100g", 0.0)),
                    "carb_g": float(substitute_fdc.get("carbohydrate_g_100g", 0.0)),
                },
                "match_score": 100.0,  # Assume perfect match for direct apply
            }]
        else:
            # Search for similar foods
            search_query = original_ingredient_name if original_ingredient_name else original_fdc.get("description", "")
            search_results = fdc_collection.query.bm25(
                query=search_query,
                limit=100,
            )
            
            # Score and rank substitutes
            scored_substitutes = []
            for obj in search_results.objects:
                substitute = obj.properties
                sub_fdc_id = substitute.get("fdc_id")
                if sub_fdc_id == original_fdc_id:
                    continue  # Skip original
                
                sub_macros = {
                    "kcal": float(substitute.get("energy_kcal_100g", 0.0)),
                    "protein_g": float(substitute.get("protein_g_100g", 0.0)),
                    "fat_g": float(substitute.get("fat_g_100g", 0.0)),
                    "carb_g": float(substitute.get("carbohydrate_g_100g", 0.0)),
                }
                
                match_score = _macro_match_score(original_macros, sub_macros, tolerance)
                if match_score > 0:
                    scored_substitutes.append({
                        "fdc_id": sub_fdc_id,
                        "description": substitute.get("description", ""),
                        "macros_per_100g": sub_macros,
                        "match_score": match_score,
                    })
            
            # Sort by match score and take top_k
            scored_substitutes.sort(key=lambda x: x.get("match_score", 0.0), reverse=True)
            suggestions = scored_substitutes[:top_k]
        
        if not suggestions:
            yield Response("No suitable substitutes found within tolerance")
            return
        
        # Step 4: Check allergens (if plan available)
        exclude_allergens = []
        plan = None
        plan_source = None
        
        day_plan_results = tree_data.environment.find("plan_day_e2e_tool", "plan")
        if day_plan_results and day_plan_results[0]["objects"]:
            plan = copy.deepcopy(day_plan_results[0]["objects"][0])
            plan_source = "plan_day_e2e_tool"
        else:
            week_plan_results = tree_data.environment.find("plan_week_e2e_tool", "plan")
            if week_plan_results and week_plan_results[0]["objects"]:
                plan = copy.deepcopy(week_plan_results[0]["objects"][0])
                plan_source = "plan_week_e2e_tool"
        
        # Read constraints for allergen checks
        if plan:
            filters_results = tree_data.environment.find("constraints_guard_tool", "filters")
            if filters_results and filters_results[0]["objects"]:
                filters_metadata = filters_results[0].metadata if hasattr(filters_results[0], "metadata") else {}
                exclude_allergens = filters_metadata.get("exclude_allergens", [])
        
        # Filter suggestions by allergens (if constraints available)
        if exclude_allergens:
            # Note: FdcFood doesn't have allergens field, so we can't filter here
            # This would require Recipe-level allergen checking
            pass
        
        # Yield suggestions
        substitutes_output = {
            "original_ingredient": {
                "name": original_ingredient_name or original_fdc.get("description", ""),
                "fdc_id": original_fdc_id,
                "macros_per_100g": original_macros,
            },
            "substitutes": suggestions,
            "count": len(suggestions),
            "tolerance": tolerance,
        }
        
        yield Result(
            name="substitutes",
            objects=[substitutes_output],
            metadata={
                "substitute_count": len(suggestions),
                "tolerance": tolerance,
            },
            payload_type="generic",
            display=True,
        )
        
        yield Result(
            name="substitutes_table",
            objects=suggestions,
            metadata={
                "substitute_count": len(suggestions),
                "tolerance": tolerance,
            },
            payload_type="table",
            display=True,
        )
        
        if suggestions:
            yield Response(f"Found {len(suggestions)} substitute suggestions")
        
        # Step 5: Optionally apply best substitute to plan
        if (auto_apply or substitute_fdc_id) and plan:
            best_substitute = suggestions[0]
            target_substitute_fdc_id = substitute_fdc_id or best_substitute.get("fdc_id")
            
            yield Response(f"Applying substitute: {best_substitute.get('description', 'Unknown')}")
            
            # Apply substitute to recipes in plan
            recipe_collection = client.collections.get("Recipe")
            updated_recipes = []
            
            # Find recipes in plan that use original ingredient
            recipes_to_update = []
            if plan.get("plan_type") == "day":
                for meal_data in plan.get("meals", {}).values():
                    recipe = meal_data.get("recipe", {})
                    if recipe.get("food_id"):
                        recipes_to_update.append((recipe, meal_data))
            elif plan.get("plan_type") == "week":
                for day_data in plan.get("days", {}).values():
                    for meal_data in day_data.get("meals", {}).values():
                        recipe = meal_data.get("recipe", {})
                        if recipe.get("food_id"):
                            recipes_to_update.append((recipe, meal_data))
            
            # Get substitute FDC data
            sub_results = fdc_collection.query.fetch_objects(
                where={"path": ["fdc_id"], "operator": "Equal", "valueInt": int(target_substitute_fdc_id)},
                limit=1,
            )
            if not sub_results.objects:
                yield Error(f"Substitute FDC ID {target_substitute_fdc_id} not found")
                return
            substitute_fdc = sub_results.objects[0].properties
            
            # Update recipes that contain the original ingredient
            for recipe, meal_data in recipes_to_update:
                food_id = recipe.get("food_id")
                ingredient_map = recipe.get("ingredient_fdc_map", [])
                
                # Check if recipe uses original ingredient
                uses_original = False
                updated_map = []
                for ing_entry in ingredient_map:
                    if isinstance(ing_entry, dict) and ing_entry.get("fdc_id") == original_fdc_id:
                        uses_original = True
                        # Replace with substitute
                        updated_map.append({
                            **ing_entry,
                            "fdc_id": target_substitute_fdc_id,
                            "ingredient_en": substitute_fdc.get("description", ing_entry.get("ingredient_en", "")),
                        })
                    else:
                        updated_map.append(ing_entry)
                
                if uses_original:
                    # Update recipe in Weaviate
                    recipe_results = recipe_collection.query.fetch_objects(
                        where={"path": ["food_id"], "operator": "Equal", "valueString": food_id},
                        limit=1,
                    )
                    if recipe_results.objects:
                        recipe_obj = recipe_results.objects[0]
                        recipe_obj.properties["ingredient_fdc_map"] = updated_map
                        recipe_collection.data.update(uuid=recipe_obj.uuid, properties=recipe_obj.properties)
                        
                        # Update recipe in plan
                        recipe["ingredient_fdc_map"] = updated_map
                        updated_recipes.append(food_id)
            
            if not updated_recipes:
                yield Response(f"No recipes found using ingredient with FDC ID {original_fdc_id}")
                return
            
            # Recalculate macros if requested
            macros_recalculated = False
            if recalculate_macros and kwargs.get("base_lm"):
                yield Response("Recalculating recipe macros after substitution...")
                for food_id in updated_recipes:
                    try:
                        async for result in calculate_recipe_macros_tool(
                            tree_data=tree_data,
                            client_manager=client_manager,
                            recipe_id=food_id,
                            base_lm=kwargs.get("base_lm"),
                        ):
                            if isinstance(result, Error):
                                yield Response(f"Warning: Failed to recalculate macros for recipe {food_id}")
                                break
                        macros_recalculated = True
                    except Exception as e:
                        logging.warning(f"substitute_tool: Error recalculating macros for recipe {food_id}: {str(e)}")
                        yield Response(f"Warning: Error recalculating macros for recipe {food_id}")
            elif recalculate_macros and not kwargs.get("base_lm"):
                yield Response("Warning: base_lm not provided. Macros not recalculated.")
            
            # Recalculate plan totals
            from MealAgent.tools.utils.planning_helpers import _get_meal_macros
            total_macros = {"kcal": 0.0, "protein_g": 0.0, "fat_g": 0.0, "carb_g": 0.0}
            if plan.get("plan_type") == "day":
                for meal_data in plan.get("meals", {}).values():
                    recipe = meal_data.get("recipe", {})
                    servings = meal_data.get("servings", 1.0)
                    macros = _get_meal_macros(recipe)
                    for key in total_macros:
                        total_macros[key] += macros[key] * servings
            elif plan.get("plan_type") == "week":
                for day_data in plan.get("days", {}).values():
                    for meal_data in day_data.get("meals", {}).values():
                        recipe = meal_data.get("recipe", {})
                        servings = meal_data.get("servings", 1.0)
                        macros = _get_meal_macros(recipe)
                        for key in total_macros:
                            total_macros[key] += macros[key] * servings
                plan["average_daily_macros"] = {
                    "kcal": total_macros["kcal"] / 7.0,
                    "protein_g": total_macros["protein_g"] / 7.0,
                    "fat_g": total_macros["fat_g"] / 7.0,
                    "carb_g": total_macros["carb_g"] / 7.0,
                }
            plan["total_macros"] = total_macros
            
            yield Result(
                name="updated_plan",
                objects=[plan],
                metadata={
                    "plan_type": plan.get("plan_type"),
                    "recipes_updated": len(updated_recipes),
                    "original_fdc_id": original_fdc_id,
                    "substitute_fdc_id": target_substitute_fdc_id,
                    "macros_recalculated": macros_recalculated,
                },
                payload_type="generic",
                display=True,
            )
            
            if macros_recalculated:
                yield Response(f"Substitute applied to {len(updated_recipes)} recipe(s). Macros recalculated.")
            else:
                yield Response(f"Substitute applied to {len(updated_recipes)} recipe(s). Run calculate_recipe_macros_tool to update macros.")
        
    except ValueError as e:
        error_msg = f"Invalid input: {str(e)}"
        logging.error(f"substitute_tool: {error_msg}", exc_info=True)
        yield Error(error_msg)
        return
    except Exception as e:
        error_msg = f"substitute_tool failed: {str(e)}"
        logging.error(f"substitute_tool: {error_msg}", exc_info=True)
        yield Error(error_msg)
        return

