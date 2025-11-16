"""
Subtract pantry items from shopping list to get final shopping list.
"""
from typing import AsyncGenerator, Dict, Any, List

from elysia.tree.objects import TreeData
from elysia.objects import Result, Error, Response
from elysia.util.client import ClientManager
from elysia import tool


def _convert_to_grams(quantity: float, unit: str, fdc_id: int | None, client) -> float:
    """
    Convert quantity to grams using FdcPortion if available.
    Returns quantity in grams.
    """
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
    
    if plan_type == "day":
        # Daily plan: iterate through meals
        for meal_key, meal_data in plan.get("meals", {}).items():
            recipe = meal_data.get("recipe", {})
            servings = meal_data.get("servings", 1.0)
            
            # Get ingredients_with_qty or ingredients
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
                    # Parse ingredient string (simplified - e.g., "200g thịt gà")
                    ing_lower = ing_str.lower().strip()
                    ing_key = ing_lower
                    
                    if ing_key not in ingredient_map:
                        ingredient_map[ing_key] = {
                            "ingredient_name": ing_str,  # Keep original format
                            "quantity": 0.0,
                            "unit": "g",  # Default
                            "fdc_id": fdc_lookup.get(ing_lower),
                            "recipes": [],
                        }
                    ingredient_map[ing_key]["quantity"] += servings
                    ingredient_map[ing_key]["recipes"].append({
                        "meal": meal_key,
                        "recipe_id": recipe.get("food_id"),
                    })
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
                    ingredient_map[ing_key]["recipes"].append({
                        "meal": meal_key,
                        "recipe_id": recipe.get("food_id"),
                    })
    
    elif plan_type == "week":
        # Weekly plan: iterate through all days and meals
        for day_key, day_data in plan.get("days", {}).items():
            for meal_key, meal_data in day_data.get("meals", {}).items():
                recipe = meal_data.get("recipe", {})
                servings = meal_data.get("servings", 1.0)
                
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
                        ingredient_map[ing_key]["recipes"].append({
                            "day": day_key,
                            "meal": meal_key,
                            "recipe_id": recipe.get("food_id"),
                        })
                elif ingredients:
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
                        ingredient_map[ing_key]["recipes"].append({
                            "day": day_key,
                            "meal": meal_key,
                            "recipe_id": recipe.get("food_id"),
                        })
    
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
    Subtract pantry items from shopping list to get final shopping list.
    
    Reads from E2E plan outputs (plan_day_e2e_tool.plan or plan_week_e2e_tool.plan),
    extracts shopping list items, and subtracts pantry stock.

    Environment reads:
      - environment["plan_day_e2e_tool"]["plan"] or environment["plan_week_e2e_tool"]["plan"]
      - environment["pantry_crud_tool"]["state"]
    Environment writes:
      - environment["pantry_diff_tool"]["diff"]
    """
    yield Response("Calculating shopping list after pantry deduction...")

    if not user_id:
        yield Error("user_id is required")
        return

    # Read plan from E2E tools (prefer daily, fallback to weekly)
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
    
    # Extract shopping items from plan
    shopping_items = _extract_ingredients_from_plan(plan)
    yield Response(f"Extracted {len(shopping_items)} items from {plan_source} plan")

    # Read pantry state
    pantry_results = tree_data.environment.find("pantry_crud_tool", "state")
    if not pantry_results or not pantry_results[0].objects:
        yield Error("Pantry state not found. Run pantry_crud_tool first.")
        return

    pantry_state = pantry_results[0].objects[0]
    pantry_items = pantry_state.get("items", [])

    try:
        client = client_manager.get_client()
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
        # Table view of final items (rows) for display
        yield Result(
            name="final_items",
            objects=final_items,
            metadata={
                "user_id": user_id,
                "final_count": len(final_items),
            },
            payload_type="table",
            display=True,
        )

        warning_msg = ""
        if warnings:
            warning_msg = f" Warnings: {len(warnings)} items have excess pantry stock."
        yield Response(f"Shopping list updated: {len(final_items)} items needed (removed {len(shopping_items) - len(final_items)} from pantry)")

    except Exception as e:
        yield Error(f"Pantry diff calculation failed for user {user_id}: {str(e)}")
        return

