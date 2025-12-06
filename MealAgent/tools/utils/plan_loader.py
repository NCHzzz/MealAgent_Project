"""
Helper functions to load meal plans from Weaviate database.

IMPORTANT: Tools should load plans from Weaviate (source of truth), not from environment cache.
Environment is only for LLM agent navigation and system operations.
"""

import logging
from typing import Dict, Any, Optional, List
from MealAgent.tools.utils.weaviate_filters import build_filters_from_where
from MealAgent.tools.utils.planning_helpers import _get_meal_macros

# Helper functions to identify dish types
def _is_main_dish(recipe: Dict[str, Any]) -> bool:
    """Check if recipe is a main dish (món mặn)."""
    dish_type = recipe.get("dish_type", "").lower()
    dish_name = recipe.get("dish_name", "").lower()
    main_keywords = ["main", "thịt", "cá", "gà", "bò", "heo", "tôm", "cua", "mực"]
    return any(kw in dish_type or kw in dish_name for kw in main_keywords)

def _is_carb_dish(recipe: Dict[str, Any]) -> bool:
    """Check if recipe is a carb dish (cơm/mì)."""
    dish_type = recipe.get("dish_type", "").lower()
    dish_name = recipe.get("dish_name", "").lower()
    carb_keywords = ["rice", "cơm", "noodle", "mì", "bún", "phở", "hủ tiếu"]
    return any(kw in dish_type or kw in dish_name for kw in carb_keywords)

logger = logging.getLogger(__name__)


def load_plan_from_weaviate(
    plan_id: str,
    client_manager,
    user_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    Load a meal plan from Weaviate database by plan_id.
    
    Args:
        plan_id: The plan_id to load
        client_manager: ClientManager instance
        user_id: Optional user_id for validation
        
    Returns:
        Plan dictionary or None if not found
    """
    try:
        client = client_manager.get_client()
        plan_collection = client.collections.get("MealPlan")
        item_collection = client.collections.get("MealPlanItem")
        recipe_collection = client.collections.get("Recipe")
        
        # Load plan metadata
        plan_filter = build_filters_from_where(
            {"path": ["plan_id"], "operator": "Equal", "valueString": plan_id}
        )
        plan_results = plan_collection.query.fetch_objects(filters=plan_filter, limit=1)
        
        if not plan_results.objects:
            logger.warning(f"Plan {plan_id} not found in Weaviate")
            return None
        
        plan_obj = plan_results.objects[0]
        plan_props = plan_obj.properties
        plan_user_id = plan_props.get("user_id")
        
        # Validate user_id if provided
        if user_id and plan_user_id != user_id:
            logger.warning(f"Plan {plan_id} does not belong to user {user_id}")
            return None
        
        # Load plan items
        item_filter = build_filters_from_where(
            {"path": ["plan_id"], "operator": "Equal", "valueString": plan_id}
        )
        item_results = item_collection.query.fetch_objects(filters=item_filter, limit=100)
        
        # Reconstruct plan structure
        plan_type = plan_props.get("plan_type", "day")
        plan = {
            "plan_id": plan_id,
            "user_id": plan_user_id,
            "plan_type": plan_type,
            "start_date": plan_props.get("start_date"),
            "created_at": plan_props.get("created_at"),
            "meals": {},
            "total_macros": {"kcal": 0.0, "protein_g": 0.0, "fat_g": 0.0, "carb_g": 0.0},
        }
        
        if plan_type == "week":
            plan["days"] = {}
        
        # Group items by meal_type
        meal_items = {}
        for item_obj in item_results.objects:
            item_props = item_obj.properties
            meal_type = item_props.get("meal_type")
            if not meal_type:
                continue
            
            if meal_type not in meal_items:
                meal_items[meal_type] = []
            meal_items[meal_type].append(item_props)
        
        # Reconstruct meals from items
        for meal_type, items in meal_items.items():
            if plan_type == "day":
                if meal_type not in ["breakfast", "lunch", "dinner"]:
                    continue  # Skip snacks for now
                
                meal_data = {
                    "meal_type": meal_type,
                    "recipe": None,
                    "servings": 1.0,
                    "accompaniments": [],
                    "macros": {"kcal": 0.0, "protein_g": 0.0, "fat_g": 0.0, "carb_g": 0.0},
                }
                
                # Fetch recipes and reconstruct meal structure
                for item in items:
                    recipe_id = item.get("recipe_id")
                    servings = float(item.get("servings", 1.0))
                    
                    if not recipe_id:
                        continue
                    
                    # Handle default white rice (not in database)
                    if recipe_id == "default_white_rice":
                        from MealAgent.tools.plan_day.plan_day_e2e import _create_default_white_rice_recipe
                        recipe = _create_default_white_rice_recipe()
                    else:
                        # Fetch recipe from Weaviate
                        recipe_filter = build_filters_from_where(
                            {"path": ["food_id"], "operator": "Equal", "valueString": recipe_id}
                        )
                        recipe_results = recipe_collection.query.fetch_objects(filters=recipe_filter, limit=1)
                        
                        if not recipe_results.objects:
                            logger.warning(f"Recipe {recipe_id} not found for plan item")
                            continue
                        
                        recipe = recipe_results.objects[0].properties
                    recipe_macros = _get_meal_macros(recipe)
                    
                    # Determine if it's main recipe or accompaniment
                    if meal_type == "breakfast":
                        meal_data["recipe"] = recipe
                        meal_data["servings"] = servings
                    elif _is_main_dish(recipe):
                        if meal_data["recipe"] is None:
                            meal_data["recipe"] = recipe
                            meal_data["servings"] = servings
                        else:
                            meal_data["accompaniments"].append({
                                "recipe": recipe,
                                "servings": servings,
                                "type": "main",
                            })
                    elif _is_carb_dish(recipe):
                        if meal_data["recipe"] is None:
                            meal_data["recipe"] = recipe
                            meal_data["servings"] = servings
                        else:
                            meal_data["accompaniments"].append({
                                "recipe": recipe,
                                "servings": servings,
                                "type": "carb",
                            })
                    else:
                        # Vegetable or fruit
                        meal_data["accompaniments"].append({
                            "recipe": recipe,
                            "servings": servings,
                            "type": "vegetable" if "vegetable" in recipe.get("dish_type", "").lower() else "fruit",
                        })
                    
                    # Add to meal macros
                    for macro in ["kcal", "protein_g", "fat_g", "carb_g"]:
                        meal_data["macros"][macro] += recipe_macros.get(macro, 0.0) * servings
                
                plan["meals"][meal_type] = meal_data
                
                # Add to total macros
                for macro in ["kcal", "protein_g", "fat_g", "carb_g"]:
                    plan["total_macros"][macro] += meal_data["macros"][macro]
            
            elif plan_type == "week":
                # For weekly plans, group by day
                # This is simplified - full implementation would need day tracking
                # For now, just collect items
                pass
        
        return plan
        
    except Exception as e:
        logger.error(f"Failed to load plan from Weaviate: {e}", exc_info=True)
        return None


def load_latest_plan_from_weaviate(
    user_id: str,
    client_manager,
    plan_type: str = "day",
) -> Optional[Dict[str, Any]]:
    """
    Load the latest meal plan for a user from Weaviate database.
    
    Args:
        user_id: User ID
        client_manager: ClientManager instance
        plan_type: "day" or "week"
        
    Returns:
        Latest plan dictionary or None if not found
    """
    try:
        client = client_manager.get_client()
        plan_collection = client.collections.get("MealPlan")
        
        # Find latest plan for user
        user_filter = build_filters_from_where({
            "operator": "And",
            "operands": [
                {"path": ["user_id"], "operator": "Equal", "valueString": user_id},
                {"path": ["plan_type"], "operator": "Equal", "valueString": plan_type},
            ]
        })
        
        # Sort by created_at descending, get most recent
        plan_results = plan_collection.query.fetch_objects(
            filters=user_filter,
            limit=1,
            sort="created_at:desc" if hasattr(plan_collection.query, 'sort') else None,
        )
        
        if not plan_results.objects:
            logger.debug(f"No {plan_type} plan found for user {user_id}")
            return None
        
        plan_obj = plan_results.objects[0]
        plan_id = plan_obj.properties.get("plan_id")
        
        if not plan_id:
            return None
        
        # Load full plan using plan_id
        return load_plan_from_weaviate(plan_id, client_manager, user_id)
        
    except Exception as e:
        logger.error(f"Failed to load latest plan from Weaviate: {e}", exc_info=True)
        return None

