from typing import AsyncGenerator, Dict, Any, List, Optional
import json
import logging
from datetime import datetime, timedelta, timezone

import dspy
from elysia.tree.objects import TreeData
from elysia.objects import Result, Error, Response
from elysia.util.client import ClientManager
from elysia.util.elysia_chain_of_thought import ElysiaChainOfThought
from elysia import tool

from MealAgent.tools.utils.weaviate_filters import build_filters_from_where


def _safe_float(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


async def _log_meal_with_macros(
    tree_data: TreeData,
    client_manager: ClientManager,
    user_id: str,
    meal_description: str,
    meal_macros: Dict[str, float],
    recipe: Optional[Dict[str, Any]] = None,
    accompaniments: Optional[List[Dict[str, Any]]] = None,
) -> AsyncGenerator[Result | Response | Error, None]:
    """
    Log a meal with pre-calculated macros (no LLM parsing needed).
    Used for logging meals from saved plans where macros are already calculated.
    """
    try:
        client = client_manager.get_client()
        try:
            profile_collection = client.collections.get("UserProfile")
            log_collection = client.collections.get("MealLogEntry")
        except Exception as e:
            yield Error(f"Required collections not found: {str(e)}")
            return

        # Get profile
        from MealAgent.tools.utils.weaviate_filters import build_filters_from_where
        profile_filter = build_filters_from_where(
            {"path": ["user_id"], "operator": "Equal", "valueString": user_id}
        )
        profile_results = profile_collection.query.fetch_objects(filters=profile_filter, limit=1)
        if not profile_results.objects:
            yield Error(f"Profile not found for user {user_id}")
            return
        profile = profile_results.objects[0].properties
        profile_uuid = profile_results.objects[0].uuid

        # Calculate today's consumed macros
        now_utc = datetime.now(timezone.utc)
        today_start = now_utc.replace(hour=0, minute=0, second=0, microsecond=0)
        today_end = today_start + timedelta(days=1)
        today_filter = build_filters_from_where(
            {
                "operator": "And",
                "operands": [
                    {"path": ["user_id"], "operator": "Equal", "valueString": user_id},
                    {"path": ["logged_at"], "operator": "GreaterThanEqual", "valueDate": today_start.isoformat().replace("+00:00", "Z")},
                    {"path": ["logged_at"], "operator": "LessThan", "valueDate": today_end.isoformat().replace("+00:00", "Z")},
                ],
            }
        )
        today_logs = log_collection.query.fetch_objects(filters=today_filter)
        today_consumed = {"kcal": 0.0, "protein_g": 0.0, "fat_g": 0.0, "carb_g": 0.0}
        for obj in today_logs.objects:
            macros_str = obj.properties.get("calculated_macros", "{}")
            if isinstance(macros_str, str):
                try:
                    macros = json.loads(macros_str)
                except json.JSONDecodeError:
                    macros = {}
            else:
                macros = macros_str
            if isinstance(macros, dict):
                today_consumed["kcal"] += float(macros.get("kcal", 0.0))
                today_consumed["protein_g"] += float(macros.get("protein_g", 0.0))
                today_consumed["fat_g"] += float(macros.get("fat_g", 0.0))
                today_consumed["carb_g"] += float(macros.get("carb_g", 0.0))

        # Add this meal's macros
        today_consumed["kcal"] += meal_macros["kcal"]
        today_consumed["protein_g"] += meal_macros["protein_g"]
        today_consumed["fat_g"] += meal_macros["fat_g"]
        today_consumed["carb_g"] += meal_macros["carb_g"]

        # Calculate remaining targets
        target_macros = {
            "kcal": _safe_float(profile.get("tdee_kcal", 2000), 2000.0),
            "protein_g": _safe_float(profile.get("protein_g", 150), 150.0),
            "fat_g": _safe_float(profile.get("fat_g", 67), 67.0),
            "carb_g": _safe_float(profile.get("carb_g", 200), 200.0),
        }
        remaining_targets = {
            "kcal": max(0.0, target_macros["kcal"] - today_consumed["kcal"]),
            "protein_g": max(0.0, target_macros["protein_g"] - today_consumed["protein_g"]),
            "fat_g": max(0.0, target_macros["fat_g"] - today_consumed["fat_g"]),
            "carb_g": max(0.0, target_macros["carb_g"] - today_consumed["carb_g"]),
        }

        # Create log entry
        logged_at_iso = now_utc.isoformat().replace("+00:00", "Z")
        log_entry = {
            "log_id": f"log_{user_id}_{int(datetime.now().timestamp())}",
            "user_id": user_id,
            "logged_at": logged_at_iso,
            "meal_description": meal_description,
            "parsed_dish": meal_description,
            "ingredients": json.dumps([]),
            "portion_size": 1.0,
            "calculated_macros": json.dumps(meal_macros),
            "calculated_micros": json.dumps({}),
            "validation_status": "complete",
            "parsing_method": "pre_calculated",
            # Persist IDs/names for variety filters
            "recipe_id": str((recipe or {}).get("food_id") or (recipe or {}).get("recipe_id") or ""),
            "dish_name": str((recipe or {}).get("dish_name") or meal_description).strip(),
        }
        log_collection.data.insert(log_entry)

        # Also log accompaniments as separate entries to capture their names/IDs for variety
        if accompaniments:
            for acc in accompaniments:
                acc_recipe = acc.get("recipe", {})
                acc_macros = acc.get("macros", {})
                acc_servings = _safe_float(acc.get("servings", 1.0), 1.0)
                # compute macros for accompaniment if not provided
                if not acc_macros or not isinstance(acc_macros, dict):
                    try:
                        from MealAgent.tools.utils.planning_helpers import _get_meal_macros
                        acc_macros = _get_meal_macros(acc_recipe)
                    except Exception:
                        acc_macros = {"kcal": 0.0, "protein_g": 0.0, "fat_g": 0.0, "carb_g": 0.0}
                acc_total = {
                    "kcal": acc_macros.get("kcal", 0.0) * acc_servings,
                    "protein_g": acc_macros.get("protein_g", 0.0) * acc_servings,
                    "fat_g": acc_macros.get("fat_g", 0.0) * acc_servings,
                    "carb_g": acc_macros.get("carb_g", 0.0) * acc_servings,
                }
                acc_entry = {
                    "log_id": f"log_{user_id}_{int(datetime.now().timestamp())}_{acc_recipe.get('food_id','acc')}",
                    "user_id": user_id,
                    "logged_at": logged_at_iso,
                    "meal_description": f"{meal_description} - {acc_recipe.get('dish_name','Side')}",
                    "parsed_dish": acc_recipe.get("dish_name", "Side"),
                    "ingredients": json.dumps([]),
                    "portion_size": acc_servings,
                    "calculated_macros": json.dumps(acc_total),
                    "calculated_micros": json.dumps({}),
                    "validation_status": "complete",
                    "parsing_method": "pre_calculated",
                    "recipe_id": str(acc_recipe.get("food_id") or acc_recipe.get("recipe_id") or ""),
                    "dish_name": str(acc_recipe.get("dish_name", "")).strip(),
                }
                try:
                    log_collection.data.insert(acc_entry)
                except Exception as e:
                    logging.debug(f"log_meal_e2e: failed to insert accompaniment log: {e}")

        # Update profile
        profile["updated_at"] = logged_at_iso
        profile_collection.data.update(uuid=profile_uuid, properties=profile)

        updated = {
            "remaining_targets": remaining_targets,
            "consumed_today": today_consumed,
            "consumed_this_meal": meal_macros,
            "log_entry": log_entry,
            "warnings": [],
        }

        yield Result(
            name="updated_profile",
            objects=[updated],
            metadata={"user_id": user_id, "logged_at": log_entry["logged_at"]},
            payload_type="generic",
            display=False,  # Hide raw table; a human-friendly summary is provided separately
        )
        yield Response(
            f"📥 Đã ghi nhận: {meal_description} | "
            f"{meal_macros['kcal']:.0f} kcal · "
            f"{meal_macros['protein_g']:.1f}g P · "
            f"{meal_macros['fat_g']:.1f}g F · "
            f"{meal_macros['carb_g']:.1f}g C. "
            f"Còn lại hôm nay: {remaining_targets['kcal']:.0f} kcal · "
            f"{remaining_targets['protein_g']:.1f}g P · "
            f"{remaining_targets['fat_g']:.1f}g F · "
            f"{remaining_targets['carb_g']:.1f}g C."
        )

    except Exception as e:
        yield Error(f"_log_meal_with_macros failed: {str(e)}")


async def _log_single_meal(
    tree_data: TreeData,
    client_manager: ClientManager,
    base_lm,
    user_id: str,
    meal_description: str,
    meal_macros: Dict[str, float],
    recipe: Optional[Dict[str, Any]] = None,
    accompaniments: Optional[List[Dict[str, Any]]] = None,
) -> AsyncGenerator[Result | Response | Error, None]:
    """
    Log a single meal with pre-calculated macros.
    Wrapper around _log_meal_with_macros for consistency.
    """
    async for result in _log_meal_with_macros(
        tree_data, client_manager, user_id, meal_description, meal_macros, recipe, accompaniments
    ):
        yield result


async def _parse_meal_with_lm(meal_description: str, base_lm, tree_data: TreeData) -> Dict[str, Any]:
    """Use the configured LM (dspy) to turn a free-text meal into structured fields."""
    if base_lm is None:
        raise ValueError("base_lm is required for LLM parsing")

    class MealParseSignature(dspy.Signature):
        """Parse meal description to dish name, ingredients array, and portion size."""

        meal_description = dspy.InputField(
            desc="Free-text meal description with dish name and ingredients."
        )
        dish = dspy.OutputField(desc="Dish name/title.")
        ingredients = dspy.OutputField(
            desc="List of objects: name, amount (number), unit (string)."
        )
        portion_size = dspy.OutputField(desc="Number of portions/servings (float).")

    cot = ElysiaChainOfThought(
        MealParseSignature,
        tree_data=tree_data,
        reasoning=False,
        impossible=False,
        message_update=False,
    )
    pred = await cot.aforward(lm=base_lm, meal_description=meal_description)

    dish = str(getattr(pred, "dish", "") or "").strip()
    ingredients = getattr(pred, "ingredients", []) or []
    portion_size_raw = getattr(pred, "portion_size", 1.0)

    # Normalise ingredients into expected dict shape
    cleaned_ingredients: List[Dict[str, Any]] = []
    if isinstance(ingredients, str):
        try:
            ingredients = json.loads(ingredients)
        except json.JSONDecodeError:
            ingredients = []
    if isinstance(ingredients, list):
        for item in ingredients:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name", "")).strip()
            if not name:
                continue
            amount = item.get("amount")
            try:
                amount = float(amount) if amount is not None else 0.0
            except (TypeError, ValueError):
                amount = 0.0
            unit = str(item.get("unit", "g") or "g").strip() or "g"
            cleaned_ingredients.append({"name": name, "amount": amount, "unit": unit})

    try:
        portion_size = float(portion_size_raw) if portion_size_raw is not None else 1.0
    except (TypeError, ValueError):
        portion_size = 1.0

    return {
        "dish": dish or meal_description.strip() or "Meal",
        "ingredients": cleaned_ingredients,
        "portion_size": portion_size,
    }


@tool
async def log_meal_e2e_tool(
    tree_data: TreeData,
    client_manager: ClientManager,
    base_lm,
    user_id: str,
    meal_description: str = "",
    plan_id: str = "",
    user_accepted: bool = False,
    **kwargs,
) -> AsyncGenerator[Result | Response | Error, None]:
    """
    Meal logging E2E flow: LLM parsing → FDC validation → nutrition calc → profile + log persistence.
    
    CRITICAL: This tool should ONLY be called in these 3 cases:
    1. User explicitly accepts a plan via UI (user_accepted=True or plan_id provided with explicit acceptance)
    2. User says they actually ate something (meal_description provided by user)
    3. User chats with agent accepting the proposed plan (user message indicates acceptance)
    
    DO NOT call this tool automatically after creating a plan. Wait for user acceptance.
    
    Can log either:
    - Single meal: Provide meal_description (e.g., "Phở bò") - when user says they ate something
    - Entire plan: Provide plan_id to log all meals from a saved plan - when user accepts plan
    
    Parameters:
        user_accepted: Set to True when user explicitly accepts a plan. If False and plan_id is provided,
                      this indicates automatic call which should be prevented.

    Environment contract:
      Reads
        • `profile_crud_tool.profile` (optional) for cached profile context / faster UUID lookups.
        • `plan_day_e2e_tool.plan` (optional) if plan_id not provided but plan is in environment.
      Writes
        • `log_meal_e2e_tool.updated_profile` containing `remaining_targets`, consumed macros, and persisted log metadata.

    Decision hints:
      • Presence of `updated_profile` = meal logged; agent can summarize and/or adjust future plans.
      • Errors typically mean the profile is missing or FDC match failed; prompt user accordingly.
    """
    yield Response("🍽️ Logging your meal and calculating nutrition...")

    if not user_id:
        yield Error("user_id is required")
        return
    
    # CRITICAL VALIDATION: Prevent automatic logging without user acceptance
    # Only allow logging if:
    # 1. User provided meal_description (user says they ate something) - OK to proceed
    # 2. User explicitly accepted plan (user_accepted=True) - OK to proceed
    # 3. plan_id provided without user_accepted - This might be automatic call, log warning
    if plan_id and not user_accepted and not meal_description:
        # This is likely an automatic call after plan creation (should be prevented)
        # Log strong warning but still allow (in case it's from accept_plan_tool or user acceptance via chat)
        logging.warning(
            f"log_meal_e2e_tool: POTENTIAL AUTOMATIC CALL DETECTED - plan_id={plan_id} but user_accepted=False and meal_description empty. "
            f"This tool should ONLY be called when: "
            f"1) User accepts plan via UI (use accept_plan_tool instead), "
            f"2) User says they accept in chat (set user_accepted=True), "
            f"3) User says they ate something (provide meal_description). "
            f"Proceeding with caution - ensure this is from user acceptance."
        )
        # Note: We still proceed because accept_plan_tool might call this internally,
        # or agent might have detected user acceptance from chat context
    
    # Option 1: Log entire plan if plan_id provided
    # IMPORTANT: Always load from Weaviate (database is source of truth)
    # Environment is only for support (e.g., storing plan_id for quick reference)
    if plan_id:
        from MealAgent.tools.utils.plan_loader import load_plan_from_weaviate
        
        # Load plan from Weaviate (database is source of truth)
        plan = load_plan_from_weaviate(plan_id, client_manager, user_id)  # Not async, no await needed
        
        if not plan:
            yield Error(
                f"Plan {plan_id} not found in Weaviate database. "
                f"Please check the plan_id or create a new plan."
            )
            return
        
        # Log all meals from the plan
        total_logged_macros = {"kcal": 0.0, "protein_g": 0.0, "fat_g": 0.0, "carb_g": 0.0}
        meals_logged = []
        
        # Plan structure: plan["breakfast"], plan["lunch"], plan["dinner"] (not plan["meals"])
        # Log breakfast
        breakfast = plan.get("breakfast") or plan.get("meals", {}).get("breakfast")
        if breakfast:
            recipe = breakfast.get("recipe", {})
            servings = breakfast.get("servings", 1.0)
            macros = breakfast.get("macros", {})
            accompaniments = breakfast.get("accompaniments", [])
            
            if recipe and macros:
                dish_name = recipe.get("dish_name", "Breakfast")
                meal_desc = f"{dish_name} (servings: {servings:.1f})"
                
                # Calculate total macros for this meal
                meal_macros = {
                    "kcal": macros.get("kcal", 0.0) * servings,
                    "protein_g": macros.get("protein_g", 0.0) * servings,
                    "fat_g": macros.get("fat_g", 0.0) * servings,
                    "carb_g": macros.get("carb_g", 0.0) * servings,
                }
                
                # Log this meal
                async for result in _log_single_meal(
                    tree_data, client_manager, base_lm, user_id, meal_desc, meal_macros, recipe, accompaniments
                ):
                    yield result
                    if isinstance(result, Result) and result.name == "updated_profile":
                        # Extract macros from logged meal
                        updated = result.objects[0] if result.objects else {}
                        consumed = updated.get("consumed_this_meal", {})
                        for k in total_logged_macros:
                            total_logged_macros[k] += consumed.get(k, 0.0)
                        meals_logged.append("breakfast")
        
        # Log lunch (including accompaniments)
        lunch = plan.get("lunch") or plan.get("meals", {}).get("lunch")
        if lunch:
            recipe = lunch.get("recipe", {})
            servings = lunch.get("servings", 1.0)
            accompaniments = lunch.get("accompaniments", [])
            
            # Build meal description
            meal_items = [recipe.get("dish_name", "Lunch")] if recipe else []
            
            # CRITICAL: Use macros_total if available (includes all accompaniments), otherwise calculate from recipe + accompaniments
            meal_macros = lunch.get("macros_total", {})
            if not meal_macros or all(v == 0.0 for v in meal_macros.values()):
                # Fallback: Calculate from recipe + accompaniments
                meal_macros = {"kcal": 0.0, "protein_g": 0.0, "fat_g": 0.0, "carb_g": 0.0}
                
                # Add main recipe macros
                if recipe:
                    recipe_macros = lunch.get("macros", {})
                    if not recipe_macros:
                        # Try to get from recipe object directly
                        from MealAgent.tools.utils.planning_helpers import _get_meal_macros
                        recipe_macros = _get_meal_macros(recipe)
                    for k in meal_macros:
                        meal_macros[k] += recipe_macros.get(k, 0.0) * servings
                
                # Add accompaniments
                for acc in accompaniments:
                    acc_recipe = acc.get("recipe", {})
                    acc_servings = acc.get("servings", 1.0)
                    if acc_recipe:
                        meal_items.append(acc_recipe.get("dish_name", "Side dish"))
                        acc_macros = acc.get("macros", {})
                        if not acc_macros:
                            from MealAgent.tools.utils.planning_helpers import _get_meal_macros
                            acc_macros = _get_meal_macros(acc_recipe)
                        for k in meal_macros:
                            meal_macros[k] += acc_macros.get(k, 0.0) * acc_servings
            else:
                # Use macros_total, but still build meal_items list for description
                for acc in accompaniments:
                    acc_recipe = acc.get("recipe", {})
                    if acc_recipe:
                        meal_items.append(acc_recipe.get("dish_name", "Side dish"))
            
            if meal_items:
                meal_desc = f"Lunch: {', '.join(meal_items)}"
                logging.debug(
                    f"LOG_MEAL_LUNCH: Using macros_total={meal_macros} | "
                    f"accompaniments_count={len(accompaniments)}"
                )
                async for result in _log_meal_with_macros(
                    tree_data, client_manager, user_id, meal_desc, meal_macros, recipe, accompaniments
                ):
                    yield result
                    if isinstance(result, Result) and result.name == "updated_profile":
                        updated = result.objects[0] if result.objects else {}
                        consumed = updated.get("consumed_this_meal", {})
                        for k in total_logged_macros:
                            total_logged_macros[k] += consumed.get(k, 0.0)
                        meals_logged.append("lunch")
        
        # Log dinner (including accompaniments)
        dinner = plan.get("dinner") or plan.get("meals", {}).get("dinner")
        if dinner:
            recipe = dinner.get("recipe", {})
            servings = dinner.get("servings", 1.0)
            accompaniments = dinner.get("accompaniments", [])
            
            # Build meal description
            meal_items = [recipe.get("dish_name", "Dinner")] if recipe else []
            
            # CRITICAL: Use macros_total if available (includes all accompaniments), otherwise calculate from recipe + accompaniments
            meal_macros = dinner.get("macros_total", {})
            if not meal_macros or all(v == 0.0 for v in meal_macros.values()):
                # Fallback: Calculate from recipe + accompaniments
                meal_macros = {"kcal": 0.0, "protein_g": 0.0, "fat_g": 0.0, "carb_g": 0.0}
                
                # Add main recipe macros
                if recipe:
                    recipe_macros = dinner.get("macros", {})
                    if not recipe_macros:
                        # Try to get from recipe object directly
                        from MealAgent.tools.utils.planning_helpers import _get_meal_macros
                        recipe_macros = _get_meal_macros(recipe)
                    for k in meal_macros:
                        meal_macros[k] += recipe_macros.get(k, 0.0) * servings
                
                # Add accompaniments
                for acc in accompaniments:
                    acc_recipe = acc.get("recipe", {})
                    acc_servings = acc.get("servings", 1.0)
                    if acc_recipe:
                        meal_items.append(acc_recipe.get("dish_name", "Side dish"))
                        acc_macros = acc.get("macros", {})
                        if not acc_macros:
                            from MealAgent.tools.utils.planning_helpers import _get_meal_macros
                            acc_macros = _get_meal_macros(acc_recipe)
                        for k in meal_macros:
                            meal_macros[k] += acc_macros.get(k, 0.0) * acc_servings
            else:
                # Use macros_total, but still build meal_items list for description
                for acc in accompaniments:
                    acc_recipe = acc.get("recipe", {})
                    if acc_recipe:
                        meal_items.append(acc_recipe.get("dish_name", "Side dish"))
            
            if meal_items:
                meal_desc = f"Dinner: {', '.join(meal_items)}"
                logging.debug(
                    f"LOG_MEAL_DINNER: Using macros_total={meal_macros} | "
                    f"accompaniments_count={len(accompaniments)}"
                )
                async for result in _log_meal_with_macros(
                    tree_data, client_manager, user_id, meal_desc, meal_macros, recipe, accompaniments
                ):
                    yield result
                    if isinstance(result, Result) and result.name == "updated_profile":
                        updated = result.objects[0] if result.objects else {}
                        consumed = updated.get("consumed_this_meal", {})
                        for k in total_logged_macros:
                            total_logged_macros[k] += consumed.get(k, 0.0)
                        meals_logged.append("dinner")
        
        # Summary with detailed macros
        logging.debug(
            f"LOG_MEAL_SUMMARY: meals_logged={len(meals_logged)} | "
            f"total_kcal={total_logged_macros['kcal']:.1f} | "
            f"total_protein={total_logged_macros['protein_g']:.1f}g | "
            f"total_fat={total_logged_macros['fat_g']:.1f}g | "
            f"total_carb={total_logged_macros['carb_g']:.1f}g"
        )
        yield Response(
            f"✅ Logged {len(meals_logged)} meal(s) from plan: {', '.join(meals_logged)}. "
            f"Total: {total_logged_macros['kcal']:.0f} kcal | {total_logged_macros['protein_g']:.0f}g protein | "
            f"{total_logged_macros['fat_g']:.0f}g fat | {total_logged_macros['carb_g']:.0f}g carbs"
        )
        return
    
    # Option 2: Log single meal (original behavior)
    if not meal_description:
        # Try to get plan_id from environment as fallback (environment is only for support)
        # IMPORTANT: We only use environment to get plan_id, then load plan from Weaviate (database)
        plan_id_from_env = None
        
        # Try to get plan_id from environment (support only, not source of truth)
        plan_id_result = tree_data.environment.find("plan_day_e2e_tool", "plan_id")
        if plan_id_result and plan_id_result[0].get("objects"):
            plan_id_obj = plan_id_result[0]["objects"][0] if plan_id_result[0]["objects"] else None
            # plan_id is stored as dict {"plan_id": "..."}
            if isinstance(plan_id_obj, dict):
                plan_id_from_env = plan_id_obj.get("plan_id")
            elif isinstance(plan_id_obj, str):
                # Fallback: if it's a string (old format)
                plan_id_from_env = plan_id_obj
            else:
                plan_id_from_env = None
        
        # Fallback: Try to get plan_id from plan object in environment
        if not plan_id_from_env:
            plan_result = tree_data.environment.find("plan_day_e2e_tool", "plan")
            if plan_result and plan_result[0].get("objects"):
                plan_obj = plan_result[0]["objects"][0]
                plan_id_from_env = plan_obj.get("plan_id") if isinstance(plan_obj, dict) else None
        
        if plan_id_from_env:
            # Recursively call with plan_id - this will load plan from Weaviate (database)
            async for result in log_meal_e2e_tool(
                tree_data=tree_data,
                client_manager=client_manager,
                base_lm=base_lm,
                user_id=user_id,
                plan_id=plan_id_from_env,
                **kwargs,
            ):
                yield result
            return
        
        yield Error("Either meal_description or plan_id is required")
        return

    # Parse meal with LM (fallback to simple parse on failure)
    parse_warning = None
    try:
        parsed_data = await _parse_meal_with_lm(meal_description, base_lm, tree_data)
    except Exception as e:
        parse_warning = f"LLM parsing fallback: {str(e)}"
        yield Response("⚠️ LLM parsing failed, using simple fallback.")
        parsed_data = {
            "dish": meal_description.strip() or "Meal",
            "ingredients": [],
            "portion_size": 1.0,
        }
    import logging
    logging.debug(
        "log_meal_e2e_tool: parsed meal dish=%s portion=%s ingredients=%d warning=%s",
        parsed_data.get("dish"),
        parsed_data.get("portion_size"),
        len(parsed_data.get("ingredients", [])),
        parse_warning,
    )

    # Nutrition calc + profile update
    try:
        client = client_manager.get_client()
        try:
            fdc_collection = client.collections.get("FdcFood")
            portion_collection = client.collections.get("FdcPortion")
            profile_collection = client.collections.get("UserProfile")
            log_collection = client.collections.get("MealLogEntry")
        except Exception as e:
            yield Error(f"Required collections not found: {str(e)}. Please ensure collections are created.")
            return

        # Validate ingredients against FDC
        validated_ingredients = []
        for ing in parsed_data.get("ingredients", []):
            name = ing.get("name", "")
            if not name:
                continue
            sr = fdc_collection.query.hybrid(query=name, limit=1)
            if sr.objects:
                f = sr.objects[0].properties
                validated_ingredients.append({**ing, "fdc_id": f.get("fdc_id")})
            else:
                validated_ingredients.append({**ing, "fdc_id": None, "validation_status": "not_found"})
        logging.debug(
            "log_meal_e2e_tool: validated ingredients %s",
            [
                (vi.get("name"), vi.get("fdc_id"), vi.get("validation_status"))
                for vi in validated_ingredients[:10]
            ],
        )

        # Calculate nutrition
        portion_size = float(parsed_data.get("portion_size", 1.0))
        total_macros = {"kcal": 0.0, "protein_g": 0.0, "fat_g": 0.0, "carb_g": 0.0}
        total_micros: Dict[str, float] = {}
        warnings: List[str] = []
        if parse_warning:
            warnings.append(parse_warning)

        for ing in validated_ingredients:
            fdc_id = ing.get("fdc_id")
            if not fdc_id:
                continue
            amount = float(ing.get("amount", 0))
            unit = ing.get("unit", "g")
            fdc_filter = build_filters_from_where(
                {"path": ["fdc_id"], "operator": "Equal", "valueInt": int(fdc_id)}
            )
            fdc_results = fdc_collection.query.fetch_objects(filters=fdc_filter, limit=1)
            if not fdc_results.objects:
                continue
            fdc_food = fdc_results.objects[0].properties
            grams = amount
            if unit != "g":
                portion_filter = build_filters_from_where(
                    {"path": ["fdc_id"], "operator": "Equal", "valueInt": int(fdc_id)}
                )
                pr = portion_collection.query.fetch_objects(filters=portion_filter, limit=10)
                converted = False
                for po in pr.objects:
                    p = po.properties
                    if p.get("measure_unit", "").lower() == unit.lower():
                        gw = p.get("gram_weight", 0.0)
                        if gw > 0:
                            portion_amount = p.get("amount", 1.0)
                            grams = (amount / portion_amount) * gw
                            converted = True
                            break
                if not converted:
                    warnings.append(f"Could not convert {amount} {unit} to grams for '{ing.get('name', 'unknown')}', assuming grams")
            scale = (grams * portion_size) / 100.0
            total_macros["kcal"] += float(fdc_food.get("energy_kcal_100g", 0.0)) * scale
            total_macros["protein_g"] += float(fdc_food.get("protein_g_100g", 0.0)) * scale
            total_macros["fat_g"] += float(fdc_food.get("fat_g_100g", 0.0)) * scale
            total_macros["carb_g"] += float(fdc_food.get("carbohydrate_g_100g", 0.0)) * scale

        # Update profile + create log
        # Try to read from environment first
        profile = None
        profile_uuid = None
        env_profile_results = tree_data.environment.find("profile_crud_tool", "profile")
        if env_profile_results and env_profile_results[0]["objects"]:
            profile = env_profile_results[0]["objects"][0]
            # Note: profile_uuid not available from environment, will need to fetch for update
        
        # If not in environment, fetch from Weaviate
        if not profile:
            profile_filter = build_filters_from_where(
                {"path": ["user_id"], "operator": "Equal", "valueString": user_id}
            )
            profile_results = profile_collection.query.fetch_objects(filters=profile_filter, limit=1)
            if not profile_results.objects:
                yield Error(f"Profile not found for user {user_id}")
                return
            profile = profile_results.objects[0].properties
            profile_uuid = profile_results.objects[0].uuid
        else:
            # Still need UUID for update, fetch it
            profile_filter = build_filters_from_where(
                {"path": ["user_id"], "operator": "Equal", "valueString": user_id}
            )
            profile_results = profile_collection.query.fetch_objects(filters=profile_filter, limit=1)
            if profile_results.objects:
                profile_uuid = profile_results.objects[0].uuid

        now_utc = datetime.now(timezone.utc)
        today_start = now_utc.replace(hour=0, minute=0, second=0, microsecond=0)
        today_end = today_start + timedelta(days=1)
        today_filter = build_filters_from_where(
            {
                "operator": "And",
                "operands": [
                    {"path": ["user_id"], "operator": "Equal", "valueString": user_id},
                    {"path": ["logged_at"], "operator": "GreaterThanEqual", "valueDate": today_start.isoformat().replace("+00:00", "Z")},
                    {"path": ["logged_at"], "operator": "LessThan", "valueDate": today_end.isoformat().replace("+00:00", "Z")},
                ],
            }
        )
        today_logs = log_collection.query.fetch_objects(filters=today_filter)
        today_consumed = {"kcal": 0.0, "protein_g": 0.0, "fat_g": 0.0, "carb_g": 0.0}
        for obj in today_logs.objects:
            macros_str = obj.properties.get("calculated_macros", "{}")
            if isinstance(macros_str, str):
                try:
                    macros = json.loads(macros_str)
                except json.JSONDecodeError:
                    macros = {}
            else:
                macros = macros_str
            if isinstance(macros, dict):
                today_consumed["kcal"] += float(macros.get("kcal", 0.0))
                today_consumed["protein_g"] += float(macros.get("protein_g", 0.0))
                today_consumed["fat_g"] += float(macros.get("fat_g", 0.0))
                today_consumed["carb_g"] += float(macros.get("carb_g", 0.0))

        today_consumed["kcal"] += total_macros["kcal"]
        today_consumed["protein_g"] += total_macros["protein_g"]
        today_consumed["fat_g"] += total_macros["fat_g"]
        today_consumed["carb_g"] += total_macros["carb_g"]

        target_macros = {
            "kcal": _safe_float(profile.get("tdee_kcal", 2000), 2000.0),
            "protein_g": _safe_float(profile.get("protein_g", 150), 150.0),
            "fat_g": _safe_float(profile.get("fat_g", 67), 67.0),
            "carb_g": _safe_float(profile.get("carb_g", 200), 200.0),
        }
        remaining_targets = {
            "kcal": max(0.0, target_macros["kcal"] - today_consumed["kcal"]),
            "protein_g": max(0.0, target_macros["protein_g"] - today_consumed["protein_g"]),
            "fat_g": max(0.0, target_macros["fat_g"] - today_consumed["fat_g"]),
            "carb_g": max(0.0, target_macros["carb_g"] - today_consumed["carb_g"]),
        }

        logged_at_iso = now_utc.isoformat().replace("+00:00", "Z")
        log_entry = {
            "log_id": f"log_{user_id}_{int(datetime.now().timestamp())}",
            "user_id": user_id,
            "logged_at": logged_at_iso,
            "meal_description": meal_description,
            "parsed_dish": parsed_data.get("dish", ""),
            "ingredients": json.dumps(validated_ingredients),
            "portion_size": parsed_data.get("portion_size", 1.0),
            "calculated_macros": json.dumps(total_macros),
            "calculated_micros": json.dumps({}),
            "validation_status": "complete" if all(ing.get("fdc_id") for ing in validated_ingredients) else "partial",
            "parsing_method": "llm",
        }
        log_collection.data.insert(log_entry)

        profile["updated_at"] = logged_at_iso
        profile_collection.data.update(uuid=profile_uuid, properties=profile)

        updated = {
            "remaining_targets": remaining_targets,
            "consumed_today": today_consumed,
            "consumed_this_meal": total_macros,
            "log_entry": log_entry,
            "warnings": warnings,
        }
        logging.debug(
            "log_meal_e2e_tool: totals meal kcal=%.1f protein=%.1f fat=%.1f carb=%.1f | today_consumed kcal=%.1f protein=%.1f fat=%.1f carb=%.1f | remaining kcal=%.1f protein=%.1f fat=%.1f carb=%.1f | logged_at=%s",
            total_macros["kcal"],
            total_macros["protein_g"],
            total_macros["fat_g"],
            total_macros["carb_g"],
            today_consumed["kcal"],
            today_consumed["protein_g"],
            today_consumed["fat_g"],
            today_consumed["carb_g"],
            remaining_targets["kcal"],
            remaining_targets["protein_g"],
            remaining_targets["fat_g"],
            remaining_targets["carb_g"],
            logged_at_iso,
        )

        # Stream response first for immediate feedback
        consumed_kcal = total_macros['kcal']
        remaining_kcal = remaining_targets['kcal']
        remaining_protein = remaining_targets['protein_g']
        yield Response(
            f"✅ Meal logged! Consumed: {consumed_kcal:.0f} kcal | "
            f"Remaining today: {remaining_kcal:.0f} kcal | {remaining_protein:.0f}g protein"
        )
        
        # Then yield Result for data consistency
        yield Result(
            name="updated_profile",
            objects=[updated],
            metadata={"user_id": user_id, "logged_at": log_entry["logged_at"]},
            payload_type="generic",
            display=True,
        )

    except Exception as e:
        yield Error(f"log_meal_e2e_tool failed: {str(e)}")
        return


