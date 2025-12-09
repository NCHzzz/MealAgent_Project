"""
Subtract pantry items from shopping list to get final shopping list.
"""
from typing import AsyncGenerator, Dict, Any, List
from datetime import datetime, timezone
from uuid import uuid4

from elysia.tree.objects import TreeData
from elysia.objects import Result, Error, Response
from elysia.util.client import ClientManager
from elysia import tool

from MealAgent.tools.utils.weaviate_filters import build_filters_from_where


def _convert_to_grams(quantity: float, unit: str, fdc_id: int | None, client) -> float:
    """
    Convert quantity to grams using FdcPortion if available.
    Returns quantity in grams.
    """
    if unit.lower() == "g":
        return quantity
    
    if fdc_id:
        try:
            try:
                portion_collection = client.collections.get("FdcPortion")
            except Exception:
                return quantity  # Fallback: assume grams if collection unavailable
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
            pass  # Fallback to assuming grams
    
    # Fallback: assume unit is grams (may be inaccurate)
    return quantity


def _extract_ingredients_from_plan(plan: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Extract and aggregate ingredients from plan (daily or weekly).
    Returns list of shopping items with ingredient_name, quantity, unit, fdc_id.
    """
    ingredient_map: Dict[str, Dict[str, Any]] = {}
    
    plan_type = plan.get("plan_type", "day")
    
    def _process_recipe_ingredients(recipe: Dict[str, Any], servings: float, meal_key: str, day_key: str | None = None):
        """Helper to process ingredients from a recipe (main or accompaniment)."""
        ingredients_with_qty = recipe.get("ingredients_with_qty", [])
        ingredients = recipe.get("ingredients", [])
        ingredient_fdc_map = recipe.get("ingredient_fdc_map", [])
        
        # Build FDC lookup
        fdc_lookup = {}
        if ingredient_fdc_map:
            for mapping in ingredient_fdc_map:
                if isinstance(mapping, dict):
                    ing_vn = mapping.get("ingredient_vn", "").lower().strip()
                    fdc_id = mapping.get("fdc_id")
                    if ing_vn and fdc_id:
                        fdc_lookup[ing_vn] = fdc_id
        
        # Process ingredients_with_qty (preferred)
        if ingredients_with_qty:
            for ing_str in ingredients_with_qty:
                if not isinstance(ing_str, str):
                    continue
                ing_lower = ing_str.lower().strip()
                ing_key = ing_lower
                
                if ing_key not in ingredient_map:
                    ingredient_map[ing_key] = {
                        "ingredient_name": ing_str,
                        "quantity": 0.0,
                        "unit": "g",
                        "fdc_id": fdc_lookup.get(ing_lower),
                        "recipes": [],
                    }
                ingredient_map[ing_key]["quantity"] += servings
                recipe_info = {
                    "meal": meal_key,
                    "recipe_id": recipe.get("food_id"),
                }
                if day_key:
                    recipe_info["day"] = day_key
                ingredient_map[ing_key]["recipes"].append(recipe_info)
        elif ingredients:
            # Fallback: use simple ingredient names
            for ing in ingredients:
                if not isinstance(ing, str):
                    continue
                ing_lower = str(ing).lower().strip()
                ing_key = ing_lower
                
                if ing_key not in ingredient_map:
                    ingredient_map[ing_key] = {
                        "ingredient_name": str(ing),
                        "quantity": 0.0,
                        "unit": "g",
                        "fdc_id": fdc_lookup.get(ing_lower),
                        "recipes": [],
                    }
                ingredient_map[ing_key]["quantity"] += servings
                recipe_info = {
                    "meal": meal_key,
                    "recipe_id": recipe.get("food_id"),
                }
                if day_key:
                    recipe_info["day"] = day_key
                ingredient_map[ing_key]["recipes"].append(recipe_info)
    
    if plan_type == "day":
        # Daily plan: iterate through meals
        for meal_key, meal_data in plan.get("meals", {}).items():
            # Main recipe
            recipe = meal_data.get("recipe", {})
            servings = float(meal_data.get("servings", 1.0))
            _process_recipe_ingredients(recipe, servings, meal_key)
            
            # Accompaniments (for Vietnamese meals)
            accompaniments = meal_data.get("accompaniments", [])
            for acc in accompaniments:
                acc_recipe = acc.get("recipe", {})
                acc_servings = float(acc.get("servings", 1.0))
                if acc_recipe:
                    _process_recipe_ingredients(acc_recipe, acc_servings, meal_key)
    
    elif plan_type == "week":
        # Weekly plan: iterate through all days and meals
        for day_key, day_data in plan.get("days", {}).items():
            for meal_key, meal_data in day_data.get("meals", {}).items():
                # Main recipe
                recipe = meal_data.get("recipe", {})
                servings = float(meal_data.get("servings", 1.0))
                _process_recipe_ingredients(recipe, servings, meal_key, day_key)
                
                # Accompaniments (for Vietnamese meals)
                accompaniments = meal_data.get("accompaniments", [])
                for acc in accompaniments:
                    acc_recipe = acc.get("recipe", {})
                    acc_servings = float(acc.get("servings", 1.0))
                    if acc_recipe:
                        _process_recipe_ingredients(acc_recipe, acc_servings, meal_key, day_key)
    
    # Convert to list and clean up
    items = []
    for item in ingredient_map.values():
        items.append({
            "ingredient_name": item["ingredient_name"],
            "quantity": item["quantity"],
            "unit": item["unit"],
            "fdc_id": item.get("fdc_id"),
        })
    
    return items


def _normalize_ingredient_name(name: str) -> str:
    """
    Normalize ingredient name for matching.
    
    Note: This is a simple normalization. For production, consider:
    - Fuzzy matching (e.g., using difflib or rapidfuzz)
    - Synonym handling (e.g., "chicken breast" vs "chicken, breast")
    - Unit removal (e.g., "chicken 200g" vs "chicken")
    """
    if not name:
        return ""
    # Basic normalization: lowercase, strip, remove extra spaces
    normalized = " ".join(name.lower().strip().split())
    # Remove common punctuation that might cause mismatches
    normalized = normalized.replace(",", "").replace(";", "").replace(":", "")
    return normalized


@tool
async def pantry_diff_tool(
    tree_data: TreeData,
    client_manager: ClientManager,
    user_id: str = "",
    **kwargs,
) -> AsyncGenerator[Result | Response | Error, None]:
    """
    Generate pantry-aware shopping lists by subtracting on-hand inventory from plan ingredients.

    Environment contract:
      Reads
        • `plan_day_e2e_tool.plan` / `plan_week_e2e_tool.plan` for ingredient requirements.
        • `pantry_crud_tool.state` for the latest pantry snapshot.
      Writes
        • `pantry_diff_tool.diff` (diagnostics) and `pantry_diff_tool.shopping_list` (UI payload).

    Decision hints:
      • `shopping_list` result with `final_items=[]` implies pantry already covers the plan.
      • Errors typically indicate missing pantry state—prompt the user to run pantry CRUD first.
    """
    yield Response("🛒 Generating shopping list (checking pantry inventory)...")

    if not user_id:
        yield Error("user_id is required")
        return

    # Load plan from Weaviate database (source of truth)
    plan = None
    plan_source = None
    plan_id = None
    plan_user_id = None

    if plan_id:
        # Load specific plan by plan_id
        from MealAgent.tools.utils.plan_loader import load_plan_from_weaviate
        plan = load_plan_from_weaviate(plan_id, client_manager, user_id)
        if plan:
            plan_source = plan.get("plan_type", "day") + "_plan"
    elif user_id:
        # Load latest plan for user
        from MealAgent.tools.utils.plan_loader import load_latest_plan_from_weaviate
        plan = load_latest_plan_from_weaviate(user_id, client_manager, "day")
        if not plan:
            plan = load_latest_plan_from_weaviate(user_id, client_manager, "week")
    
    # Fallback: try environment cache (only as last resort)
    import logging
    logger = logging.getLogger(__name__)
    
    if not plan:
        logger.warning("pantry_diff_tool: No plan from database, trying environment cache")
        day_plan_results = tree_data.environment.find("plan_day_e2e_tool", "plan")
        if day_plan_results and day_plan_results[0]["objects"]:
            plan = day_plan_results[0]["objects"][0]
            plan_source = "plan_day_e2e_tool"
            yield Response("⚠️ Using cached plan (please provide plan_id or user_id for database access)")
        else:
            week_plan_results = tree_data.environment.find("plan_week_e2e_tool", "plan")
            if week_plan_results and week_plan_results[0]["objects"]:
                plan = week_plan_results[0]["objects"][0]
                plan_source = "plan_week_e2e_tool"
                yield Response("⚠️ Using cached plan (please provide plan_id or user_id for database access)")
    
    if not plan:
        yield Error("No plan found. Please provide plan_id or user_id, or run plan_day_e2e_tool/plan_week_e2e_tool first.")
        return
    
    plan_id = plan.get("plan_id")
    plan_user_id = plan.get("user_id") or user_id
    
    # Extract shopping items from plan
    shopping_items = _extract_ingredients_from_plan(plan)
    plan_type = plan.get("plan_type", "day")
    yield Response(f"📋 Extracted {len(shopping_items)} ingredient(s) from {plan_type} plan")

    # Load pantry state from Weaviate database
    try:
        client = client_manager.get_client()
        pantry_collection = client.collections.get("Pantry")
        
        # Find pantry for user
        pantry_filter = build_filters_from_where({
            "path": ["user_id"], "operator": "Equal", "valueString": plan_user_id
        })
        pantry_results = pantry_collection.query.fetch_objects(filters=pantry_filter, limit=1)
        
        if pantry_results.objects:
            pantry_obj = pantry_results.objects[0]
            pantry_state = pantry_obj.properties
            pantry_items = pantry_state.get("items", [])
            yield Response(f"📦 Loaded pantry with {len(pantry_items)} item(s) from database")
        else:
            # Fallback: try environment cache
            logger.warning("pantry_diff_tool: No pantry from database, trying environment cache")
            pantry_results = tree_data.environment.find("pantry_crud_tool", "state")
            if pantry_results and pantry_results[0].get("objects"):
                pantry_state = pantry_results[0]["objects"][0]
                pantry_items = pantry_state.get("items", [])
                yield Response("⚠️ Using cached pantry (please ensure pantry is saved to database)")
            else:
                yield Error("Pantry state not found in database. Please create or update your pantry first.")
                return
    except Exception as e:
        logger.error(f"Failed to load pantry from Weaviate: {e}")
        # Fallback: try environment cache
        pantry_results = tree_data.environment.find("pantry_crud_tool", "state")
        if pantry_results and pantry_results[0].get("objects"):
            pantry_state = pantry_results[0]["objects"][0]
            pantry_items = pantry_state.get("items", [])
            yield Response("⚠️ Using cached pantry (database access failed)")
        else:
            yield Error(f"Failed to load pantry: {str(e)}")
            return

    try:
        client = client_manager.get_client()
        try:
            shopping_list_collection = client.collections.get("ShoppingList")
            shopping_item_collection = client.collections.get("ShoppingItem")
        except Exception as e:
            yield Error(f"Shopping collections not found: {str(e)}. Please ensure collections are created.")
            return

        # Build pantry lookup (by normalized ingredient name)
        pantry_lookup: Dict[str, Dict[str, Any]] = {}
        for item in pantry_items:
            name = _normalize_ingredient_name(item.get("ingredient_name", ""))
            if name:
                pantry_lookup[name] = item

        # Process shopping items
        final_items = []
        warnings = []

        for shop_item in shopping_items:
            ingredient_name = shop_item.get("ingredient_name", "")
            shop_quantity = float(shop_item.get("quantity", 0.0))
            shop_unit = shop_item.get("unit", "g")
            shop_fdc_id = shop_item.get("fdc_id")

            # Convert shopping item to grams
            shop_grams = _convert_to_grams(shop_quantity, shop_unit, shop_fdc_id, client)

            # Check if in pantry
            normalized_name = _normalize_ingredient_name(ingredient_name)
            pantry_item = pantry_lookup.get(normalized_name)

            if pantry_item:
                # Item exists in pantry
                pantry_quantity = float(pantry_item.get("quantity", 0.0))
                pantry_unit = pantry_item.get("unit", "g")
                pantry_fdc_id = pantry_item.get("fdc_id")

                # Convert pantry item to grams
                pantry_grams = _convert_to_grams(pantry_quantity, pantry_unit, pantry_fdc_id, client)

                # Calculate difference
                needed_grams = shop_grams - pantry_grams

                if needed_grams > 0:
                    # Still need to buy
                    # Note: Quantity is in grams after conversion. 
                    # For non-gram units, we keep the original unit but quantity represents grams.
                    # In production, consider converting back to original unit using FdcPortion.
                    final_item = {
                        "ingredient_name": ingredient_name,
                        "quantity": needed_grams,  # Always in grams after conversion
                        "unit": "g",  # Standardized to grams for consistency
                        "fdc_id": shop_fdc_id,
                        "original_quantity": shop_quantity,
                        "original_unit": shop_unit,
                        "pantry_deducted": pantry_grams,
                    }
                    final_items.append(final_item)
                elif needed_grams < -0.1:  # Small tolerance
                    # Have more than needed
                    warnings.append(f"{ingredient_name}: pantry has {pantry_grams:.1f}g, only need {shop_grams:.1f}g")
                # If needed_grams is ~0, skip (have exactly what's needed)
            else:
                # Not in pantry, need to buy all
                final_items.append(shop_item)

        diff_output = {
            "user_id": user_id,
            "original_items": shopping_items,
            "final_items": final_items,
            "items_removed": len(shopping_items) - len(final_items),
            "warnings": warnings,
        }

        list_id = f"{plan_id or user_id}_shopping_{uuid4().hex[:8]}"
        shopping_payload = {
            "list_id": list_id,
            "user_id": plan_user_id or user_id,
            "plan_id": plan_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

        if plan_id:
            existing_list_filter = build_filters_from_where(
                {"path": ["plan_id"], "operator": "Equal", "valueString": plan_id}
            )
            existing_lists = shopping_list_collection.query.fetch_objects(
                filters=existing_list_filter, limit=5
            )
            for lst in existing_lists.objects:
                list_filter = build_filters_from_where(
                    {"path": ["list_id"], "operator": "Equal", "valueString": lst.properties.get("list_id")}
                )
                existing_items = shopping_item_collection.query.fetch_objects(
                    filters=list_filter, limit=256
                )
                for obj in existing_items.objects:
                    shopping_item_collection.data.delete_by_id(obj.uuid)
                shopping_list_collection.data.delete_by_id(lst.uuid)

        shopping_list_collection.data.insert(shopping_payload)
        for item in final_items:
            shopping_item_collection.data.insert(
                {
                    "list_id": list_id,
                    "ingredient_name": item.get("ingredient_name"),
                    "quantity": float(item.get("quantity", 0.0)),
                    "unit": item.get("unit", "g"),
                    "category": item.get("category", "general"),
                    "purchased": False,
                }
            )

        diff_output["shopping_list_id"] = list_id

        # Create shopping list payload for frontend display
        shopping_list_payload = {
            "items": final_items,
            "original_count": len(shopping_items),
            "removed_count": len(shopping_items) - len(final_items),
            "shopping_list_id": list_id,
            "warnings": warnings,
        }
        
        yield Result(
            name="diff",
            objects=[diff_output],
            metadata={
                "user_id": user_id,
                "original_count": len(shopping_items),
                "final_count": len(final_items),
                "removed_count": len(shopping_items) - len(final_items),
                "plan_source": plan_source,
            },
            payload_type="generic",
            display=True,
        )
        # Shopping list for frontend display component
        yield Result(
            name="shopping_list",
            objects=[shopping_list_payload],
            metadata={
                "user_id": user_id,
                "final_count": len(final_items),
                "removed_count": len(shopping_items) - len(final_items),
                "shopping_list_id": list_id,
            },
            payload_type="shopping_list",
            display=True,
        )

        removed_count = len(shopping_items) - len(final_items)
        if warnings:
            yield Response(f"ℹ️ {len(warnings)} item(s) have excess pantry stock")
        yield Response(
            f"✅ Shopping list ready: {len(final_items)} item(s) needed "
            f"({removed_count} already in pantry)"
        )
        yield Response(f"💾 Shopping list saved (ID: {list_id})")

    except Exception as e:
        yield Error(f"Pantry diff calculation failed for user {user_id}: {str(e)}")
        return

