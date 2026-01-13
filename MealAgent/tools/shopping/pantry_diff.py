"""
Subtract pantry items from shopping list to get final shopping list.
"""
from typing import AsyncGenerator, Dict, Any, List, Tuple
from datetime import datetime, timezone, timedelta
from uuid import uuid4
import hashlib
import logging
import re

from elysia.tree.objects import TreeData
from elysia.objects import Result, Error, Response
from elysia.util.client import ClientManager
from elysia import tool

from MealAgent.tools.utils.weaviate_filters import build_filters_from_where
from MealAgent.tools.utils.ingredient_parser import parse_ingredient_string, convert_to_grams as parser_convert_to_grams, DEFAULT_UNIT_WEIGHTS

logger = logging.getLogger(__name__)


def _convert_to_grams(quantity: float, unit: str, fdc_id: int | None, client) -> float:
    """
    Convert quantity to grams using FdcPortion if available, 
    otherwise fall back to robust default weight table.
    """
    normalized_unit = unit.lower()
    if normalized_unit == "g":
        return quantity
    
    # Try FDC conversion first
    if fdc_id:
        try:
            try:
                portion_collection = client.collections.get("FdcPortion")
            except Exception:
                # Collection might not exist yet or be inaccessible
                pass
            else:
                portion_filter = build_filters_from_where(
                    {"path": ["fdc_id"], "operator": "Equal", "valueInt": int(fdc_id)}
                )
                portion_results = portion_collection.query.fetch_objects(filters=portion_filter, limit=10)
                
                for portion_obj in portion_results.objects:
                    portion = portion_obj.properties
                    if portion.get("measure_unit", "").lower() == normalized_unit:
                        gram_weight = portion.get("gram_weight", 0.0)
                        if gram_weight > 0:
                            portion_amount = portion.get("amount", 1.0)
                            return (quantity / portion_amount) * gram_weight
        except Exception:
            pass 
    
    # Fallback to parser's default weight table
    return parser_convert_to_grams(quantity, unit)


def _extract_ingredients_from_plan(plan: Dict[str, Any], client=None) -> List[Dict[str, Any]]:
    """
    Extract and aggregate ingredients from plan (daily or weekly).
    Returns list of shopping items with ingredient_name, quantity, unit, fdc_id.
    Standardizes everything to grams/ml for robust aggregation.
    """
    # Key: normalized_name
    ingredient_map: Dict[str, Dict[str, Any]] = {}
    
    plan_type = plan.get("plan_type", "day")
    
    def _process_recipe_ingredients(recipe: Dict[str, Any], requested_servings: float, meal_key: str, day_key: str | None = None):
        """Helper to process ingredients from a recipe (main or accompaniment)."""
        ingredients_with_qty = recipe.get("ingredients_with_qty", [])
        ingredients = recipe.get("ingredients", [])
        ingredient_fdc_map = recipe.get("ingredient_fdc_map", [])
        
        try:
            raw_serving = recipe.get("serving_size", 1.0)
            if isinstance(raw_serving, (str, bytes)):
                import re
                match = re.search(r"([\d\.]+)", str(raw_serving))
                recipe_servings = float(match.group(1)) if match else 1.0
            else:
                recipe_servings = float(raw_serving or 1.0)
        except (ValueError, TypeError):
            recipe_servings = 1.0
        
        # Build FDC lookup
        fdc_lookup = {}
        if ingredient_fdc_map:
            for mapping in ingredient_fdc_map:
                if isinstance(mapping, dict):
                    ing_vn = mapping.get("ingredient_vn", "").lower().strip()
                    fdc_id = mapping.get("fdc_id")
                    if ing_vn and fdc_id:
                        fdc_lookup[ing_vn] = fdc_id
        
        scale = requested_servings / recipe_servings
        raw_list = ingredients_with_qty if ingredients_with_qty else ingredients
        
        for ing_str in raw_list:
            if not isinstance(ing_str, str):
                continue
            
            parsed = parse_ingredient_string(ing_str)
            name = parsed["name"].lower().strip()
            if not name:
                continue
                
            qty = parsed["quantity"] * scale
            unit = parsed["unit"]
            fdc_id = fdc_lookup.get(name)
            
            # Convert to grams/ml for aggregation
            grams = _convert_to_grams(qty, unit, fdc_id, client)
            
            if name not in ingredient_map:
                ingredient_map[name] = {
                    "ingredient_name": name,
                    "total_grams": 0.0,
                    "unit": unit, # Keep last unit as representative
                    "fdc_id": fdc_id,
                    "is_liquid": unit.lower() in ["ml", "l", "lít"],
                }
            
            ingredient_map[name]["total_grams"] += grams
    
    if plan_type == "day":
        for meal_key, meal_data in plan.get("meals", {}).items():
            recipe = meal_data.get("recipe", {})
            servings = float(meal_data.get("servings", 1.0))
            _process_recipe_ingredients(recipe, servings, meal_key)
            
            accompaniments = meal_data.get("accompaniments", [])
            for acc in accompaniments:
                acc_recipe = acc.get("recipe", {})
                acc_servings = float(acc.get("servings", 1.0))
                if acc_recipe:
                    _process_recipe_ingredients(acc_recipe, acc_servings, meal_key)
    
    elif plan_type == "week":
        for day_key, day_data in plan.get("days", {}).items():
            for meal_key, meal_data in day_data.get("meals", {}).items():
                recipe = meal_data.get("recipe", {})
                servings = float(meal_data.get("servings", 1.0))
                _process_recipe_ingredients(recipe, servings, meal_key, day_key)
                
                accompaniments = meal_data.get("accompaniments", [])
                for acc in accompaniments:
                    acc_recipe = acc.get("recipe", {})
                    acc_servings = float(acc.get("servings", 1.0))
                    if acc_recipe:
                        _process_recipe_ingredients(acc_recipe, acc_servings, meal_key, day_key)
    
    # Convert back to readable units
    items = []
    for item in ingredient_map.values():
        name = item["ingredient_name"]
        grams = item["total_grams"]
        is_liquid = item["is_liquid"]
        
        final_qty = grams
        final_unit = "ml" if is_liquid else "g"
        
        # Check if we should preserve a discrete unit
        # Use a case-insensitive check against keys
        preferred_unit_lower = item.get("unit", "").lower()
        # Find matching key in DEFAULT_UNIT_WEIGHTS (which are mostly lowercase)
        # But we want to preserve the casing of the item['unit'] if possible, or use the key
        
        if preferred_unit_lower in DEFAULT_UNIT_WEIGHTS:
            weight_per_unit = DEFAULT_UNIT_WEIGHTS[preferred_unit_lower]
            if weight_per_unit > 0:
                final_qty = grams / weight_per_unit
                final_unit = item.get("unit") # Use original casing
        else:
            # Standard conversion to kg/l if large enough
            if final_qty >= 1000:
                final_qty /= 1000.0
                final_unit = "l" if is_liquid else "kg"
        
        items.append({
            "ingredient_name": name,
            "quantity": round(final_qty, 2),
            "unit": final_unit,
            "fdc_id": item.get("fdc_id"),
            "total_grams": grams, # For internal use
        })
    
    return items



def _normalize_ingredient_name(name: str) -> str:
    """
    Normalize ingredient name for matching.
    Uses the same logic as the ingredient parser for consistency.
    """
    if not name:
        return ""
    parsed = parse_ingredient_string(name)
    return parsed["name"].lower().strip()


@tool
async def pantry_diff_tool(
    tree_data: TreeData,
    client_manager: ClientManager,
    user_id: str = "",
    **kwargs,
) -> AsyncGenerator[Result | Response | Error, None]:
    """
    Generate pantry-aware shopping lists by subtracting on-hand inventory from plan ingredients.
    
    ⚠️ CRITICAL: This tool is ONLY for generating shopping lists from meal plans.
    
    **WHEN TO CALL THIS TOOL:**
    ✅ CALL this tool when:
    - User explicitly asks for a shopping list from a meal plan (e.g., "cho tôi danh sách nguyên liệu cần mua của plan này")
    - User wants to know what to buy for a specific plan
    - User asks "what do I need to buy?" in context of a meal plan
    - User asks follow-up questions about shopping list AFTER a plan has been created
      **IMPORTANT**: Even if `plan_day_e2e_tool` or `plan_week_e2e_tool` set `end_conversation=True`,
      if the user asks a NEW question about shopping list, this is a VALID follow-up request.
      The `end_conversation=True` signal only applies to the PLANNING task, not to new user requests.
    
    ❌ DO NOT call this tool when:
    - User asks "what's in my pantry?" → Use pantry_crud_tool(action="read") instead
    - User asks "list my pantry items" → Use pantry_crud_tool(action="read") instead
    - User asks "show me my inventory" → Use pantry_crud_tool(action="read") instead
    - User is asking about pantry contents (not shopping list)
    
    ⚠️ IMPORTANT: If pantry_crud_tool(action="read") was just called and completed successfully,
    the task is COMPLETE. Do NOT automatically call pantry_diff_tool.

    Environment contract:
      Reads
        • `plan_day_e2e_tool.plan` / `plan_week_e2e_tool.plan` for ingredient requirements.
        • `pantry_crud_tool.state` for the latest pantry snapshot.
      Writes
        • `pantry_diff_tool.diff` (diagnostics) and `pantry_diff_tool.shopping_list` (UI payload).

    Decision hints:
      • **CRITICAL**: When user asks for shopping list AFTER a plan is created, this is a NEW request.
        The `end_conversation=True` from planning tools only applies to the planning conversation,
        NOT to follow-up questions. If user asks "cho tôi danh sách nguyên liệu cần mua của plan này",
        you MUST call this tool, regardless of previous `end_conversation=True` signals.
      • ONLY call this tool when user explicitly wants a shopping list from a meal plan.
      • To list pantry items, use pantry_crud_tool(action="read") instead.
      • `shopping_list` result with `final_items=[]` implies pantry already covers the plan.
      • Errors typically indicate missing pantry state—prompt the user to run pantry CRUD first.
      • **CRITICAL**: When this tool emits `Result(name="task_complete")` with `task_complete=True`,
        `stop_calling_tool=True`, and `end_conversation=True`, the task is COMPLETE. 
        Do NOT call `explain` or any other tools. The `shopping_list` Result with `display=True` 
        is sufficient for the user. END the conversation branch immediately.
    """
    yield Response("🛒 Generating shopping list (checking pantry inventory)...")

    # Try to infer user_id from cached profile / hidden environment if not explicitly provided
    user_id_auto_detected = False
    if not user_id:
        try:
            # Follow the same pattern as macro_calc_tool for robustness
            profile_results = tree_data.environment.find("profile_crud_tool", "profile")
            profile = None
            if profile_results:
                for entry in reversed(profile_results):
                    objs = entry.get("objects") or []
                    if objs:
                        profile = objs[0]
                        break

            if isinstance(profile, dict):
                detected_id = profile.get("user_id")
                if detected_id:
                    user_id = detected_id
                    user_id_auto_detected = True

            # Fallback: hidden_environment may store user_id even if profile is missing
            if not user_id:
                hidden_env = getattr(tree_data.environment, "hidden_environment", {})
                detected_id = hidden_env.get("user_id")
                if detected_id:
                    user_id = detected_id
                    user_id_auto_detected = True
        except Exception:
            # Best-effort only – fall back to explicit user_id requirement
            pass

    if not user_id:
        yield Error("user_id is required")
        return
    
    # Inform agent that user_id was automatically detected (helps agent understand context)
    if user_id_auto_detected:
        yield Response(f"ℹ️ Using user_id from profile: {user_id[:8]}...")

    # Determine target date (default to today)
    target_date = kwargs.get("date")
    if not target_date:
        # Check if date is in query string (best effort for Vietnamese)
        query = kwargs.get("query", "").lower()
        if "hôm nay" in query or "hom nay" in query:
            target_date = datetime.now(timezone.utc).date().isoformat()
        elif "ngày mai" in query or "ngay mai" in query:
            target_date = (datetime.now(timezone.utc) + timedelta(days=1)).date().isoformat()
        elif "hôm qua" in query or "hom qua" in query:
            target_date = (datetime.now(timezone.utc) - timedelta(days=1)).date().isoformat()
        else:
            # Check for dd/mm or yyyy-mm-dd
            match = re.search(r"(\d{4}-\d{2}-\d{2})", query)
            if match:
                target_date = match.group(1)
            else:
                # Default to today
                target_date = datetime.now(timezone.utc).date().isoformat()

    plan = None
    plan_source = "none"
    is_today = (target_date == datetime.now(timezone.utc).date().isoformat())

    # 1. Environment Cache (Only if today and no explicit plan_id)
    if is_today and not kwargs.get("plan_id"):
        # Detect preference from query
        query = kwargs.get("query", "").lower()
        prefers_week = "tuần" in query or "week" in query
        
        # Pull both from cache
        day_plan_results = tree_data.environment.find("plan_day_e2e_tool", "plan")
        week_plan_results = tree_data.environment.find("plan_week_e2e_tool", "plan")
        
        # Prioritize based on intent
        if prefers_week and week_plan_results and week_plan_results[-1].get("objects"):
            plan = week_plan_results[-1]["objects"][0]
            plan_source = "current_session"
            yield Response("💡 Using weekly plan from current chat session")
        elif day_plan_results and day_plan_results[-1].get("objects"):
            plan = day_plan_results[-1]["objects"][0]
            plan_source = "current_session"
            yield Response("💡 Using plan from current chat session")
        elif week_plan_results and week_plan_results[-1].get("objects"):
            plan = week_plan_results[-1]["objects"][0]
            plan_source = "current_session"
            yield Response("💡 Using weekly plan from current chat session")

    # 2. MealLogEntry (Accepted/Consumed meals for the specific date)
    if not plan and not kwargs.get("plan_id"):
        from MealAgent.tools.utils.plan_loader import load_plan_from_logs
        plan = load_plan_from_logs(user_id, client_manager, target_date)
        if plan:
            plan_source = "accepted_meals"
            yield Response(f"✅ Loaded accepted meals for {target_date}")

    # 3. MealPlan (Suggested plans in database)
    if not plan:
        from MealAgent.tools.utils.plan_loader import load_plan_from_weaviate, load_plan_by_date, load_latest_plan_from_weaviate
        
        if kwargs.get("plan_id"):
            plan = load_plan_from_weaviate(kwargs["plan_id"], client_manager, user_id)
            if plan: plan_source = "specific_plan"
        else:
            # Try specific date in suggest plans
            plan = load_plan_by_date(user_id, client_manager, target_date, "day")
            if not plan:
                plan = load_plan_by_date(user_id, client_manager, target_date, "week")
            
            # Fallback: Latest plan if it's today and nothing else found
            if not plan and is_today:
                plan = load_latest_plan_from_weaviate(user_id, client_manager, "day")
                if not plan:
                    plan = load_latest_plan_from_weaviate(user_id, client_manager, "week")
            
            if plan:
                plan_source = "suggested_plan"
                yield Response(f"📋 Loaded latest suggested plan for {target_date if plan.get('start_date') == target_date else 'the user'}")

    if not plan:
        yield Error(f"No plan found for {target_date}. Please generate a plan first.")
        return
    
    plan_id = plan.get("plan_id")
    plan_user_id = plan.get("user_id") or user_id
    plan_start_date = plan.get("start_date")
    plan_type = plan.get("plan_type", "day")
    
    # Log plan date for debugging
    if plan_start_date:
        logger.info(f"pantry_diff_tool: Plan {plan_id} has start_date: {plan_start_date} (type: {type(plan_start_date)})")
    else:
        logger.warning(f"pantry_diff_tool: Plan {plan_id} has no start_date field")
    
    client = client_manager.get_client()
    
    # Extract shopping items from plan
    shopping_items = _extract_ingredients_from_plan(plan, client=client)
    yield Response(f"📋 Extracted and aggregated {len(shopping_items)} ingredient(s) from {plan_type} plan")

    # Load pantry state from Weaviate database (PantryItem collection)
    try:
        client = client_manager.get_client()
        try:
            item_collection = client.collections.get("PantryItem")
        except Exception as e:
            yield Error(f"PantryItem collection not found: {str(e)}. Please ensure collections are created.")
            return
        
        # Get all pantry items for user
        items_filter = build_filters_from_where(
            {"path": ["user_id"], "operator": "Equal", "valueString": plan_user_id}
        )
        items_results = item_collection.query.fetch_objects(filters=items_filter, limit=500)
        
        pantry_items = [obj.properties for obj in items_results.objects]
        yield Response(f"📦 Loaded pantry with {len(pantry_items)} item(s) from database")
        
    except Exception as e:
        logger.error(f"Failed to load pantry from Weaviate: {e}")
        # Fallback: try environment cache
        pantry_results = tree_data.environment.find("pantry_crud_tool", "state")
        if pantry_results and pantry_results[-1].get("objects"):
            pantry_state = pantry_results[-1]["objects"][0]
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

                if needed_grams > 0.1:  # Only add if significant amount needed
                    # Convert to sensible display unit
                    # Convert to sensible display unit
                    display_qty = needed_grams
                    is_liquid = shop_unit.lower() in ["ml", "l", "lít"]
                    
                    if shop_unit.lower() in DEFAULT_UNIT_WEIGHTS:
                         weight_per_unit = DEFAULT_UNIT_WEIGHTS[shop_unit.lower()]
                         if weight_per_unit > 0:
                            display_qty = needed_grams / weight_per_unit
                            display_unit = shop_unit
                         else:
                            display_unit = "ml" if is_liquid else "g"
                    else:
                        display_unit = "ml" if is_liquid else "g"
                        if display_qty >= 1000:
                            display_qty /= 1000.0
                            display_unit = "l" if is_liquid else "kg"
                        
                    final_item = {
                        "ingredient_name": ingredient_name,
                        "quantity": round(display_qty, 2),
                        "unit": display_unit,
                        "fdc_id": shop_fdc_id,
                        "original_quantity": shop_quantity,
                        "original_unit": shop_unit,
                        "pantry_deducted_grams": pantry_grams,
                    }
                    final_items.append(final_item)
                elif needed_grams < -0.1:
                    warnings.append(f"{ingredient_name}: pantry has {pantry_grams:.1f}g, only need {shop_grams:.1f}g")
            else:
                # Not in pantry, use the already aggregated/sensible version from shopping_items
                final_items.append(shop_item)

        diff_output = {
            "user_id": user_id,
            "original_items": shopping_items,
            "final_items": final_items,
            "items_removed": len(shopping_items) - len(final_items),
            "warnings": warnings,
        }

        # Normalize plan start_date for storage
        # plan_start_date was already extracted above, but normalize it here for consistency
        if plan_start_date:
            if isinstance(plan_start_date, str):
                # Already a string, use as-is
                pass
            elif hasattr(plan_start_date, "isoformat"):
                plan_start_date = plan_start_date.isoformat()
            else:
                logger.warning(f"pantry_diff_tool: Unexpected plan_start_date type: {type(plan_start_date)}, setting to None")
                plan_start_date = None
        else:
            plan_start_date = None
            logger.warning(f"pantry_diff_tool: No plan_start_date found for plan {plan_id}")

        # Check for existing shopping list for this plan_id FIRST
        # This prevents creating duplicate lists for the same plan
        existing_list_id = None
        if plan_id:
            existing_list_filter = build_filters_from_where(
                {"path": ["plan_id"], "operator": "Equal", "valueString": plan_id}
            )
            existing_lists = shopping_list_collection.query.fetch_objects(
                filters=existing_list_filter, limit=1
            )
            if existing_lists.objects:
                # Reuse existing list_id
                existing_list_id = existing_lists.objects[0].properties.get("list_id")
                logger.info(f"pantry_diff_tool: Found existing shopping list {existing_list_id} for plan {plan_id}, reusing it")
                
                # Delete existing items to replace with new ones
                list_filter = build_filters_from_where(
                    {"path": ["list_id"], "operator": "Equal", "valueString": existing_list_id}
                )
                existing_items = shopping_item_collection.query.fetch_objects(
                    filters=list_filter, limit=256
                )
                for obj in existing_items.objects:
                    shopping_item_collection.data.delete_by_id(obj.uuid)
                
                # Update existing list with new data and plan_start_date
                existing_list_obj = existing_lists.objects[0]
                updated_props = dict(existing_list_obj.properties)
                updated_props["plan_start_date"] = plan_start_date
                updated_props["created_at"] = datetime.now(timezone.utc).isoformat()  # Update timestamp
                shopping_list_collection.data.update(uuid=existing_list_obj.uuid, properties=updated_props)
        
        # Generate list_id: reuse existing or create new deterministic one
        if existing_list_id:
            list_id = existing_list_id
        elif plan_id:
            # Deterministic list_id based on plan_id (no random UUID)
            list_id_hash = hashlib.md5(f"{plan_id}_shopping".encode()).hexdigest()[:8]
            list_id = f"{plan_id}_shopping_{list_id_hash}"
        else:
            # Fallback: use random UUID only if no plan_id
            list_id = f"{user_id}_shopping_{uuid4().hex[:8]}"
        
        # Log final plan_start_date value (after list_id is defined)
        if plan_start_date:
            logger.info(f"pantry_diff_tool: Using plan_start_date: {plan_start_date} for shopping list {list_id}")
        else:
            logger.warning(f"pantry_diff_tool: Shopping list {list_id} will be created without plan_start_date")
        
        # Only create new list if we don't have an existing one
        if not existing_list_id:
            shopping_payload = {
                "list_id": list_id,
                "user_id": plan_user_id or user_id,
                "plan_id": plan_id,
                "plan_start_date": plan_start_date,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            shopping_list_collection.data.insert(shopping_payload)
            logger.info(f"pantry_diff_tool: Created new shopping list {list_id} for plan {plan_id}")
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
        
        # Include plan date in success message if available
        date_info = ""
        if plan_start_date:
            try:
                from datetime import datetime as dt
                plan_date_obj = dt.fromisoformat(plan_start_date.replace('Z', '+00:00')) if isinstance(plan_start_date, str) else plan_start_date
                if isinstance(plan_date_obj, str):
                    plan_date_obj = dt.fromisoformat(plan_date_obj.replace('Z', '+00:00'))
                date_info = f" cho {plan_date_obj.strftime('%d/%m/%Y')}"
            except Exception as e:
                logger.debug(f"pantry_diff_tool: Could not format plan date: {e}")
        
        yield Response(
            f"✅ Shopping list ready: {len(final_items)} item(s) needed "
            f"({removed_count} already in pantry){date_info}"
        )
        yield Response(f"💾 Shopping list saved (ID: {list_id})")
        
        # Emit task_complete signal to prevent unnecessary explain branch
        # The shopping_list Result with display=True is sufficient for the user
        yield Result(
            name="task_complete",
            objects=[{
                "status": "completed",
                "message": f"Shopping list with {len(final_items)} items has been generated and saved."
            }],
            metadata={
                "task_complete": True,
                "stop_calling_tool": True,
                "should_explain": False,  # Explicitly signal NOT to call explain
                "task_fully_complete": True,  # Strong signal that nothing more is needed
                "end_conversation": True,  # Signal to end the conversation branch
                "shopping_list_id": list_id,
                "items_count": len(final_items),
            },
            payload_type="generic",
            display=False,
        )

    except Exception as e:
        yield Error(f"Pantry diff calculation failed for user {user_id}: {str(e)}")
        return

