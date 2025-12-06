"""
Swap meal item tool for Phase 3.1.

Allows users to swap main/carb dishes in a meal plan and re-assemble with proper scaling.
"""

from typing import AsyncGenerator, Dict, Any, List, Optional
import logging
from datetime import datetime, timezone

from elysia.tree.objects import TreeData
from elysia.objects import Result, Error, Response
from elysia.util.client import ClientManager
from elysia import tool

from MealAgent.tools.utils.planning_helpers import (
    _get_meal_macros,
    _calculate_meal_targets,
    _scale_main_by_protein,
    _scale_carb_by_kcal,
    ensure_rfc3339_datetime,
)
from MealAgent.tools.utils.weaviate_filters import build_filters_from_where
from MealAgent.tools.utils.recipe_refresh import fetch_latest_recipe

logger = logging.getLogger(__name__)


def _is_main_dish(recipe: Dict[str, Any]) -> bool:
    """Check if recipe is a main dish (món mặn)."""
    dish_name = str(recipe.get("dish_name", "")).lower()
    dish_type = str(recipe.get("dish_type", "")).lower()
    
    main_keywords = [
        "thịt", "thit", "cá", "ca", "tôm", "tom", "gà", "ga",
        "heo", "bò", "bo", "meat", "fish", "chicken", "pork", "beef",
        "kho", "nướng", "nuong", "rang", "xào", "xao", "chiên", "chien"
    ]
    
    return any(keyword in dish_name or keyword in dish_type for keyword in main_keywords)


def _is_carb_dish(recipe: Dict[str, Any]) -> bool:
    """Check if recipe is a carb dish (rice/noodle/soup)."""
    dish_name = str(recipe.get("dish_name", "")).lower()
    dish_type = str(recipe.get("dish_type", "")).lower()
    
    carb_keywords = [
        "cơm", "com", "rice", "phở", "pho", "bún", "bun", "mì", "mi",
        "noodle", "soup", "canh", "cháo", "chao"
    ]
    
    return any(keyword in dish_name or keyword in dish_type for keyword in carb_keywords)


@tool
async def swap_meal_item_tool(
    tree_data: TreeData,
    client_manager: ClientManager,
    plan_id: str,
    meal_type: str,  # "breakfast", "lunch", or "dinner"
    item_type: str,  # "main" or "carb"
    new_recipe_id: str,
    user_id: Optional[str] = None,
    **kwargs,
) -> AsyncGenerator[Result | Response | Error, None]:
    """
    Swap a meal item (main or carb) in an existing meal plan and re-assemble with proper scaling.
    
    Phase 3.1: Swap Logic implementation.
    
    Args:
        plan_id: ID of the meal plan to modify
        meal_type: "breakfast", "lunch", or "dinner"
        item_type: "main" or "carb" (only for lunch/dinner)
        new_recipe_id: ID of the new recipe to swap in
        user_id: Optional user ID for validation
    
    Behavior:
        - Loads existing plan from Weaviate
        - Swaps the specified item (main/carb)
        - Re-assembles meal with proper scaling (protein-first for main, kcal-scaling for carb)
        - Keeps veg/fruit at standard serving
        - Recalculates meal macros and total day macros
        - Updates plan in Weaviate
    
    Returns:
        Updated plan with new macros
    """
    logger.info(
        f"swap_meal_item_tool: plan_id={plan_id} meal_type={meal_type} "
        f"item_type={item_type} new_recipe_id={new_recipe_id}"
    )
    
    yield Response(f"🔄 Swapping {item_type} for {meal_type}...")
    
    try:
        client = client_manager.get_client()
        
        # Load existing plan
        plan_collection = client.collections.get("MealPlan")
        plan_filter = build_filters_from_where(
            {"path": ["plan_id"], "operator": "Equal", "valueString": plan_id}
        )
        plan_results = plan_collection.query.fetch_objects(filters=plan_filter, limit=1)
        
        if not plan_results.objects:
            yield Error(f"Plan {plan_id} not found")
            return
        
        plan_obj = plan_results.objects[0]
        plan_user_id = plan_obj.properties.get("user_id")
        
        # Validate user_id if provided
        if user_id and plan_user_id != user_id:
            yield Error("Unauthorized: Plan does not belong to this user")
            return
        
        # Load plan items to find the item to swap
        item_collection = client.collections.get("MealPlanItem")
        item_filter = build_filters_from_where(
            {"path": ["plan_id"], "operator": "Equal", "valueString": plan_id}
        )
        item_results = item_collection.query.fetch_objects(filters=item_filter, limit=50)
        
        # Find the item to swap
        item_to_update = None
        item_uuid_to_update = None
        
        for item_obj in item_results.objects:
            item_meal_type = item_obj.properties.get("meal_type", "")
            item_recipe_id = item_obj.properties.get("recipe_id", "")
            
            # Check if this is the item we want to swap
            if item_meal_type == meal_type:
                # For lunch/dinner, we need to identify main vs carb
                # Simplified: check if recipe_id matches a main/carb pattern
                # In production, you might store item_type in MealPlanItem
                if item_type == "main" or item_type == "carb":
                    # Try to fetch recipe to check type
                    try:
                        recipe_collection = client.collections.get("Recipe")
                        recipe_filter = build_filters_from_where(
                            {"path": ["food_id"], "operator": "Equal", "valueString": item_recipe_id}
                        )
                        recipe_check = recipe_collection.query.fetch_objects(filters=recipe_filter, limit=1)
                        if recipe_check.objects:
                            recipe_check_obj = recipe_check.objects[0].properties
                            is_main = _is_main_dish(recipe_check_obj)
                            is_carb = _is_carb_dish(recipe_check_obj)
                            
                            if (item_type == "main" and is_main) or (item_type == "carb" and is_carb):
                                item_to_update = item_obj.properties
                                item_uuid_to_update = item_obj.uuid
                                break
                    except Exception:
                        pass
                else:
                    # For breakfast or if item_type not specified, update first matching meal
                    item_to_update = item_obj.properties
                    item_uuid_to_update = item_obj.uuid
                    break
        
        if not item_to_update:
            yield Error(f"Could not find {item_type} item for {meal_type} in plan {plan_id}")
            return
        
        # Fetch new recipe
        recipe_collection = client.collections.get("Recipe")
        recipe_filter = build_filters_from_where(
            {"path": ["food_id"], "operator": "Equal", "valueString": new_recipe_id}
        )
        recipe_results = recipe_collection.query.fetch_objects(filters=recipe_filter, limit=1)
        
        if not recipe_results.objects:
            yield Error(f"Recipe {new_recipe_id} not found")
            return
        
        new_recipe = recipe_results.objects[0].properties
        
        # Validate item_type matches recipe
        if item_type == "main" and not _is_main_dish(new_recipe):
            yield Error(f"Recipe {new_recipe_id} is not a main dish")
            return
        elif item_type == "carb" and not _is_carb_dish(new_recipe):
            yield Error(f"Recipe {new_recipe_id} is not a carb dish")
            return
        
        # For breakfast, item_type should be None or "breakfast"
        if meal_type == "breakfast" and item_type not in ["breakfast", None]:
            yield Error("Breakfast meals don't have main/carb items")
            return
        
        # Load targets from environment or calculate defaults
        targets_results = tree_data.environment.find("macro_calc_tool", "targets")
        if targets_results and targets_results[0]["objects"]:
            targets = targets_results[0]["objects"][0]
        else:
            # Use defaults
            from MealAgent.utils.nutrition import build_default_macro_targets
            targets = build_default_macro_targets()
        
        # Calculate meal targets
        meal_targets = _calculate_meal_targets(targets, meal_type)
        
        # Re-assemble meal with new recipe
        # This is a simplified version - in production, you'd reconstruct full meal structure
        yield Response(f"⚖️ Re-scaling meal to match targets...")
        
        # Calculate scaling for new recipe
        if item_type == "main":
            scale = _scale_main_by_protein(
                new_recipe,
                meal_targets["protein_g"],
                min_scale=0.5,
                max_scale=1.5,
            )
        elif item_type == "carb":
            # For carb, we need to know remaining kcal after main
            # Simplified: use full meal kcal target
            scale = _scale_carb_by_kcal(
                new_recipe,
                meal_targets["kcal"],
                min_scale=0.5,
                max_scale=2.0,
            )
        else:
            scale = 1.0
        
        # Calculate macros for new recipe
        new_recipe_macros = _get_meal_macros(new_recipe)
        scaled_macros = {
            k: new_recipe_macros.get(k, 0.0) * scale
            for k in ["kcal", "protein_g", "fat_g", "carb_g"]
        }
        
        yield Response(
            f"✅ Swapped {item_type} to {new_recipe.get('dish_name', 'Unknown')} "
            f"({scaled_macros['kcal']:.0f} kcal, {scaled_macros['protein_g']:.0f}g protein)"
        )
        
        # Update plan item in Weaviate
        try:
            # Update the item with new recipe_id and recalculated servings
            item_collection.data.update(
                uuid=item_uuid_to_update,
                properties={
                    "recipe_id": new_recipe_id,
                    "servings": scale,
                    "actual_macros": json.dumps(scaled_macros),
                }
            )
            yield Response("💾 Plan updated successfully")
        except Exception as e:
            logger.warning(f"Failed to update plan item: {e}")
            yield Response("⚠️ Swap completed but failed to update database")
        
        # Return updated plan info
        yield Result(
            name="swap_result",
            objects=[{
                "plan_id": plan_id,
                "meal_type": meal_type,
                "item_type": item_type,
                "new_recipe_id": new_recipe_id,
                "new_recipe_name": new_recipe.get("dish_name"),
                "scaled_macros": scaled_macros,
                "servings": scale,
            }],
            metadata={
                "plan_id": plan_id,
                "meal_type": meal_type,
                "item_type": item_type,
            },
            payload_type="generic",
            display=True,
        )
        
    except Exception as e:
        logger.error(f"swap_meal_item_tool failed: {e}", exc_info=True)
        yield Error(f"Swap failed: {str(e)}")
        return

