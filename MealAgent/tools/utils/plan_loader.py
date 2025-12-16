"""
Helper functions to load meal plans from Weaviate database.

IMPORTANT: Tools should load plans from Weaviate (source of truth), not from environment cache.
Environment is only for LLM agent navigation and system operations.
"""

import json
import logging
from datetime import datetime, timedelta
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
        try:
            plan_collection = client.collections.get("MealPlan")
            item_collection = client.collections.get("MealPlanItem")
            recipe_collection = client.collections.get("Recipe")
        except Exception as e:
            logger.error(f"load_plan_from_weaviate: collections not available: {str(e)}")
            return None
        
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

                    # If the plan item already stored aggregated macros (actual_macros), prefer it
                    actual_macros = item.get("actual_macros")
                    if actual_macros:
                        # Parse JSON string if needed
                        if isinstance(actual_macros, str):
                            try:
                                actual_macros = json.loads(actual_macros)
                            except json.JSONDecodeError:
                                logger.warning(f"Failed to parse actual_macros JSON for item {item.get('recipe_id')}")
                                actual_macros = None
                        
                        if isinstance(actual_macros, dict) and actual_macros:
                            # Override macros with server-side saved totals (already includes accompaniments)
                            meal_data["macros"] = {
                                "kcal": float(actual_macros.get("kcal", meal_data["macros"]["kcal"])),
                                "protein_g": float(actual_macros.get("protein_g", meal_data["macros"]["protein_g"])),
                                "fat_g": float(actual_macros.get("fat_g", meal_data["macros"]["fat_g"])),
                                "carb_g": float(actual_macros.get("carb_g", meal_data["macros"]["carb_g"])),
                            }
                            meal_data["macros_total"] = meal_data["macros"]
                
                plan["meals"][meal_type] = meal_data
                
                # Add to total macros
                for macro in ["kcal", "protein_g", "fat_g", "carb_g"]:
                    plan["total_macros"][macro] += meal_data["macros"][macro]
            
            elif plan_type == "week":
                # Weekly reconstruction is handled after this loop using day_index
                continue

        # Weekly plan reconstruction from MealPlanItem (aligned with plan_week_e2e_tool)
        if plan_type == "week":
            plan["days"] = {}

            # Group raw items by day_index and meal_type
            day_meals: Dict[int, Dict[str, List[Dict[str, Any]]]] = {}
            for item_obj in item_results.objects:
                item_props = item_obj.properties
                try:
                    day_index = int(item_props.get("day_index", 0))
                except (TypeError, ValueError):
                    day_index = 0
                meal_type = item_props.get("meal_type")
                if not meal_type or meal_type not in ["breakfast", "lunch", "dinner"]:
                    # Skip snacks for now
                    continue
                if day_index not in day_meals:
                    day_meals[day_index] = {}
                if meal_type not in day_meals[day_index]:
                    day_meals[day_index][meal_type] = []
                day_meals[day_index][meal_type].append(item_props)

            # Derive base date from start_date if available
            base_date = None
            start_date_str = plan_props.get("start_date")
            if start_date_str:
                try:
                    normalized = start_date_str.replace("Z", "+00:00")
                    base_date = datetime.fromisoformat(normalized).date()
                except Exception:
                    base_date = None

            # Reconstruct per-day meal structure
            for day_index, meals_by_type in day_meals.items():
                # Compute calendar date key (YYYY-MM-DD) if possible
                if base_date is not None:
                    try:
                        day_date = (base_date + timedelta(days=day_index)).isoformat()
                    except Exception:
                        day_date = f"day_{day_index}"
                else:
                    day_date = f"day_{day_index}"

                day_plan = {
                    "day_index": day_index,
                    "date": day_date,
                    "meals": {},
                }

                for mt, items in meals_by_type.items():
                    meal_data = {
                        "meal_type": mt,
                        "recipe": None,
                        "servings": 1.0,
                        "accompaniments": [],
                        "macros": {"kcal": 0.0, "protein_g": 0.0, "fat_g": 0.0, "carb_g": 0.0},
                    }

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
                            recipe_filter = build_filters_from_where(
                                {"path": ["food_id"], "operator": "Equal", "valueString": recipe_id}
                            )
                            recipe_results = recipe_collection.query.fetch_objects(filters=recipe_filter, limit=1)
                            if not recipe_results.objects:
                                logger.warning(f"Recipe {recipe_id} not found for weekly plan item")
                                continue
                            recipe = recipe_results.objects[0].properties

                        recipe_macros = _get_meal_macros(recipe)

                        # Determine if it's main recipe or accompaniment (aligned with daily loader)
                        if mt == "breakfast":
                            # Breakfast: single main dish, others as sides
                            if meal_data["recipe"] is None:
                                meal_data["recipe"] = recipe
                                meal_data["servings"] = servings
                            else:
                                meal_data["accompaniments"].append(
                                    {
                                        "recipe": recipe,
                                        "servings": servings,
                                        "type": "side",
                                    }
                                )
                        elif _is_main_dish(recipe):
                            if meal_data["recipe"] is None:
                                meal_data["recipe"] = recipe
                                meal_data["servings"] = servings
                            else:
                                meal_data["accompaniments"].append(
                                    {
                                        "recipe": recipe,
                                        "servings": servings,
                                        "type": "main",
                                    }
                                )
                        elif _is_carb_dish(recipe):
                            if meal_data["recipe"] is None:
                                meal_data["recipe"] = recipe
                                meal_data["servings"] = servings
                            else:
                                meal_data["accompaniments"].append(
                                    {
                                        "recipe": recipe,
                                        "servings": servings,
                                        "type": "carb",
                                    }
                                )
                        else:
                            meal_data["accompaniments"].append(
                                {
                                    "recipe": recipe,
                                    "servings": servings,
                                    "type": "vegetable"
                                    if "vegetable" in recipe.get("dish_type", "").lower()
                                    else "fruit",
                                }
                            )

                        # Aggregate macros for the meal
                        for macro in ["kcal", "protein_g", "fat_g", "carb_g"]:
                            meal_data["macros"][macro] += recipe_macros.get(macro, 0.0) * servings

                    day_plan["meals"][mt] = meal_data

                    # Accumulate into plan total_macros
                    for macro in ["kcal", "protein_g", "fat_g", "carb_g"]:
                        plan["total_macros"][macro] += meal_data["macros"][macro]

                plan["days"][day_date] = day_plan

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
        try:
            plan_collection = client.collections.get("MealPlan")
        except Exception as e:
            logger.error(f"load_latest_plan_from_weaviate: MealPlan collection not available: {str(e)}")
            return None
        
        # Find latest plan for user
        user_filter = build_filters_from_where({
            "operator": "And",
            "operands": [
                {"path": ["user_id"], "operator": "Equal", "valueString": user_id},
                {"path": ["plan_type"], "operator": "Equal", "valueString": plan_type},
            ]
        })
        
        # Sort by created_at descending, get most recent
        # Note: Weaviate may not support sort parameter directly, so we fetch multiple and sort in-memory
        plan_results = plan_collection.query.fetch_objects(
            filters=user_filter,
            limit=10,  # Fetch top 10 and sort in-memory
        )
        
        if not plan_results.objects:
            logger.debug(f"No {plan_type} plan found for user {user_id}")
            return None
        
        # Sort by created_at descending (most recent first)
        sorted_plans = sorted(
            plan_results.objects,
            key=lambda obj: obj.properties.get("created_at", ""),
            reverse=True
        )
        
        plan_obj = sorted_plans[0]
        plan_id = plan_obj.properties.get("plan_id")
        
        if not plan_id:
            logger.warning(f"load_latest_plan_from_weaviate: plan found but plan_id is missing")
            return None
        
        # Load full plan using plan_id
        return load_plan_from_weaviate(plan_id, client_manager, user_id)
        
    except Exception as e:
        logger.error(f"Failed to load latest plan from Weaviate: {e}", exc_info=True)
        return None

