from typing import AsyncGenerator, Dict, Any
import json
import logging
from datetime import datetime, timezone, timedelta

from elysia.tree.objects import TreeData
from elysia.objects import Result, Error, Response
from elysia.util.client import ClientManager
from elysia import tool

from MealAgent.tools.utils.plan_loader import load_plan_from_weaviate
from MealAgent.tools.utils.weaviate_filters import build_filters_from_where

logger = logging.getLogger(__name__)


def _serialize_macros(macros: Dict[str, Any] | None) -> str:
    if not isinstance(macros, dict):
        return json.dumps({})
    safe_macros = {
        "kcal": float(macros.get("kcal", 0.0)),
        "protein_g": float(macros.get("protein_g", 0.0)),
        "fat_g": float(macros.get("fat_g", 0.0)),
        "carb_g": float(macros.get("carb_g", 0.0)),
    }
    return json.dumps(safe_macros)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _ensure_date_only(date_str: str | None) -> str | None:
    """Return YYYY-MM-DD from various date inputs, or None if invalid."""
    if not date_str:
        return None
    try:
        normalized = date_str.replace("Z", "+00:00")
        dt = datetime.fromisoformat(normalized)
        return dt.date().isoformat()
    except Exception:
        try:
            # if already date-only string
            return datetime.fromisoformat(f"{date_str}T00:00:00").date().isoformat()
        except Exception:
            return None


def _delete_logs_for_date(log_collection, user_id: str, date_only: str):
    """Delete ALL MealLogEntry for a specific UTC date for this user. Returns count of deleted entries."""
    deleted_count = 0
    if not date_only:
        logger.warning(f"accept_plan_tool: Cannot delete logs - date_only is empty")
        return 0
    
    try:
        # Parse date and create UTC datetime range for the entire day
        try:
            # Ensure date_only is in YYYY-MM-DD format
            if len(date_only) == 10 and date_only.count("-") == 2:
                date_obj = datetime.fromisoformat(f"{date_only}T00:00:00").date()
            else:
                # Try to normalize
                date_obj = datetime.fromisoformat(date_only.replace("Z", "+00:00")).date()
        except Exception as e:
            logger.warning(f"accept_plan_tool: Invalid date format '{date_only}': {str(e)}")
            return 0
        
        # Create UTC datetime range: start of day (00:00:00) to start of next day
        start_dt = datetime.combine(date_obj, datetime.min.time()).replace(tzinfo=timezone.utc)
        end_dt = start_dt + timedelta(days=1)
        
        # Format for Weaviate (ISO format with Z suffix)
        start_iso = start_dt.isoformat().replace("+00:00", "Z")
        end_iso = end_dt.isoformat().replace("+00:00", "Z")
        
        logger.debug(f"accept_plan_tool: Deleting logs for date {date_only} (range: {start_iso} to {end_iso})")
        
        where_clause = {
            "operator": "And",
            "operands": [
                {"path": ["user_id"], "operator": "Equal", "valueString": user_id},
                {"path": ["logged_at"], "operator": "GreaterThanEqual", "valueDate": start_iso},
                {"path": ["logged_at"], "operator": "LessThan", "valueDate": end_iso},
            ],
        }
        filters = build_filters_from_where(where_clause)
        
        # Fetch all matching entries (increase limit if needed)
        existing = log_collection.query.fetch_objects(filters=filters, limit=500)
        
        logger.debug(f"accept_plan_tool: Found {len(existing.objects)} existing MealLogEntry entries for date {date_only} using date range query")
        
        # If no entries found with date range query, try a fallback: query all user entries and filter by date
        if len(existing.objects) == 0:
            logger.debug(f"accept_plan_tool: No entries found with date range query, trying fallback: query all user entries and filter by date")
            try:
                # Query all entries for this user (limit 1000 to handle edge cases)
                user_filter = build_filters_from_where(
                    {"path": ["user_id"], "operator": "Equal", "valueString": user_id}
                )
                all_user_entries = log_collection.query.fetch_objects(filters=user_filter, limit=1000)
                
                # Filter by date in Python (more flexible with date formats)
                for obj in all_user_entries.objects:
                    logged_at_str = obj.properties.get("logged_at", "")
                    if not logged_at_str:
                        continue
                    
                    try:
                        # Try to parse logged_at and extract date
                        logged_at_parsed = None
                        if isinstance(logged_at_str, str):
                            # Try various formats
                            for fmt in ["%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"]:
                                try:
                                    if "Z" in logged_at_str or "+" in logged_at_str or "-" in logged_at_str[-6:]:
                                        logged_at_parsed = datetime.fromisoformat(logged_at_str.replace("Z", "+00:00"))
                                    else:
                                        logged_at_parsed = datetime.fromisoformat(logged_at_str)
                                    break
                                except:
                                    continue
                        
                        if logged_at_parsed:
                            # Normalize to UTC and extract date
                            if logged_at_parsed.tzinfo is None:
                                logged_at_parsed = logged_at_parsed.replace(tzinfo=timezone.utc)
                            else:
                                logged_at_parsed = logged_at_parsed.astimezone(timezone.utc)
                            
                            entry_date = logged_at_parsed.date().isoformat()
                            if entry_date == date_only:
                                log_collection.data.delete_by_id(obj.uuid)
                                deleted_count += 1
                                logger.debug(f"accept_plan_tool: Deleted log entry {obj.uuid} via fallback (logged_at: {logged_at_str}, date: {entry_date})")
                    except Exception as e:
                        logger.debug(f"accept_plan_tool: Failed to parse logged_at '{logged_at_str}' for entry {obj.uuid}: {str(e)}")
                        continue
            except Exception as e:
                logger.warning(f"accept_plan_tool: Fallback query failed: {str(e)}")
        
        # Delete entries found via date range query
        for obj in existing.objects:
            try:
                logged_at_value = obj.properties.get("logged_at", "")
                log_collection.data.delete_by_id(obj.uuid)
                deleted_count += 1
                logger.debug(f"accept_plan_tool: Deleted log entry {obj.uuid} (logged_at: {logged_at_value})")
            except Exception as e:
                logger.warning(f"accept_plan_tool: failed deleting old log {obj.uuid}: {str(e)}")
        
        if deleted_count > 0:
            logger.info(f"accept_plan_tool: Deleted {deleted_count} old MealLogEntry entries for date {date_only}")
        else:
            logger.debug(f"accept_plan_tool: No old MealLogEntry entries found for date {date_only} to delete")
            
    except Exception as e:
        logger.exception(f"accept_plan_tool: unable to purge logs for {date_only}: {str(e)}")
    return deleted_count


def _log_plan_meal(
    log_collection,
    user_id: str,
    meal_desc: str,
    macros: Dict[str, Any],
    ingredients: list[Dict[str, Any]] | None = None,
    logged_at: str | None = None,
) -> None:
    log_entry = {
        "log_id": f"log_{user_id}_{int(datetime.now().timestamp())}",
        "user_id": user_id,
        "logged_at": logged_at or _now_iso(),
        "meal_description": meal_desc,
        "parsed_dish": meal_desc,
        "ingredients": json.dumps(ingredients or []),
        "portion_size": 1.0,
        "calculated_macros": _serialize_macros(macros),
        "calculated_micros": json.dumps({}),
        "validation_status": "complete",
        "parsing_method": "plan_accept",
    }
    log_collection.data.insert(log_entry)


def _delete_old_plans_for_date(plan_collection, item_collection, user_id: str, date_only: str, exclude_plan_id: str = None):
    """Delete old MealPlan and MealPlanItem records for a specific date (except the one being accepted)."""
    try:
        duplicate_filter = build_filters_from_where(
            {
                "operator": "And",
                "operands": [
                    {"path": ["user_id"], "operator": "Equal", "valueString": user_id},
                    {"path": ["plan_type"], "operator": "Equal", "valueString": "day"},
                    {"path": ["start_date"], "operator": "Equal", "valueDate": date_only},
                ],
            }
        )
        existing_plans = plan_collection.query.fetch_objects(filters=duplicate_filter, limit=10)
        
        deleted_count = 0
        for obj in existing_plans.objects:
            old_plan_id = obj.properties.get("plan_id")
            # Skip the plan being accepted
            if exclude_plan_id and old_plan_id == exclude_plan_id:
                continue
            
            # Delete old MealPlanItem records tied to the old plan
            if old_plan_id:
                old_plan_filter = build_filters_from_where(
                    {"path": ["plan_id"], "operator": "Equal", "valueString": old_plan_id}
                )
                old_items = item_collection.query.fetch_objects(filters=old_plan_filter, limit=256)
                for itm in old_items.objects:
                    try:
                        item_collection.data.delete_by_id(itm.uuid)
                    except Exception as e:
                        logger.debug(f"accept_plan_tool: failed deleting old item {itm.uuid}: {str(e)}")
            
            # Delete the old MealPlan record
            try:
                plan_collection.data.delete_by_id(obj.uuid)
                deleted_count += 1
            except Exception as e:
                logger.debug(f"accept_plan_tool: failed deleting old plan {obj.uuid}: {str(e)}")
        
        if deleted_count > 0:
            logger.info(f"accept_plan_tool: deleted {deleted_count} old MealPlan(s) for date {date_only}")
    except Exception as e:
        logger.warning(f"accept_plan_tool: unable to purge old plans for {date_only}: {str(e)}")


def log_plan_to_meal_log(
    plan: Dict[str, Any],
    user_id: str,
    client_manager: ClientManager,
) -> list[Dict[str, Any]]:
    """
    Persist a plan into MealLogEntry and return logged meal metadata.
    Also deletes old MealPlan records for the same date to prevent duplicates.
    Raises exceptions on failure for the caller to handle (tool or API layer).
    """
    client = client_manager.get_client()
    try:
        log_collection = client.collections.get("MealLogEntry")
        plan_collection = client.collections.get("MealPlan")
        item_collection = client.collections.get("MealPlanItem")
    except Exception as e:
        raise RuntimeError(f"Collections not found: {str(e)}")

    logged: list[Dict[str, Any]] = []
    plan_type = plan.get("plan_type", "day")
    plan_start_date = _ensure_date_only(plan.get("start_date"))
    if not plan_start_date:
        # Fallback: use today's date (UTC) if plan is missing start_date
        plan_start_date = datetime.now(timezone.utc).date().isoformat()
        plan["start_date"] = plan_start_date
    plan_id = plan.get("plan_id")
    
    # CRITICAL: Delete old MealPlan records for the same date (to prevent multiple plans per day)
    if plan_type == "day" and plan_start_date and plan_id:
        _delete_old_plans_for_date(plan_collection, item_collection, user_id, plan_start_date, exclude_plan_id=plan_id)

    def _day_logged_at(day_offset: int | None = None, explicit_date: str | None = None) -> str:
        """Return logged_at ISO anchored to plan date or today."""
        base_date = _ensure_date_only(explicit_date) or plan_start_date
        if not base_date:
            base_date = datetime.now(timezone.utc).date().isoformat()
        if day_offset is not None:
            try:
                dt = datetime.fromisoformat(f"{base_date}T00:00:00") + timedelta(days=day_offset)
                base_date = dt.date().isoformat()
            except Exception:
                pass
        # use noon to avoid DST edge cases, always UTC
        return f"{base_date}T12:00:00Z"

    def _log_meal(meal_obj: Dict[str, Any], meal_label: str, logged_at: str):
        """Log a meal including main dish and all accompaniments.

        Robust to partially reconstructed meals (e.g. some weekly items without main recipe).
        """
        if not isinstance(meal_obj, dict):
            logger.warning(
                "accept_plan_tool: _log_meal called with non-dict meal_obj (%s) for label=%s, skipping",
                type(meal_obj),
                meal_label,
            )
            return

        recipe = meal_obj.get("recipe")
        if not isinstance(recipe, dict):
            # If there is no main recipe but there are accompaniments, try to infer from first accompaniment
            accompaniments = meal_obj.get("accompaniments") or []
            if accompaniments and isinstance(accompaniments[0], dict):
                acc_recipe = accompaniments[0].get("recipe")
                if isinstance(acc_recipe, dict):
                    recipe = acc_recipe
                else:
                    recipe = {}
            else:
                recipe = {}

            logger.debug(
                "accept_plan_tool: _log_meal fallback recipe resolution | label=%s | "
                "has_accompaniments=%s | resolved_recipe=%s",
                meal_label,
                bool(accompaniments),
                bool(recipe),
            )

        dish_name = recipe.get("dish_name") or meal_label
        servings = meal_obj.get("servings", 1.0)
        
        # Get accompaniments (side dishes, extra dishes)
        accompaniments = meal_obj.get("accompaniments", []) if isinstance(meal_obj, dict) else []
        
        # Calculate total macros including accompaniments
        # Prefer precomputed totals if present to avoid double-scaling.
        # Prefer precomputed totals from plan_day_e2e to avoid double-counting.
        # plan_day_e2e sets:
        #  - lunch/dinner: macros_total (already includes accompaniments & servings)
        #  - breakfast: macros (total for the meal)
        preferred_macros = (
            meal_obj.get("macros_total")
            or meal_obj.get("macros")
            or meal_obj.get("macros_with_sides")
            or meal_obj.get("macros_total_with_sides")
        )

        # Always recompute as a safety check (main + accompaniments with servings)
        recomputed_macros = {}
        # Recompute based on primary recipe macros_per_serving (avoid reusing meal_obj.macros which may already include sides)
        base_macros = (
            recipe.get("macros_per_serving")
            or meal_obj.get("macros")
            or {}
        )
        for k in ["kcal", "protein_g", "fat_g", "carb_g"]:
            recomputed_macros[k] = float(base_macros.get(k, 0.0)) * float(servings or 1.0)
        for acc in accompaniments:
            acc_recipe = acc.get("recipe", {}) if isinstance(acc, dict) else {}
            acc_servings = float(acc.get("servings", 1.0))
            acc_macros = acc.get("macros", {}) or acc_recipe.get("macros_per_serving", {})
            for k in ["kcal", "protein_g", "fat_g", "carb_g"]:
                recomputed_macros[k] += float(acc_macros.get(k, 0.0)) * acc_servings

        scaled_macros = {}
        if preferred_macros and isinstance(preferred_macros, dict) and any(preferred_macros.values()):
            for k in ["kcal", "protein_g", "fat_g", "carb_g"]:
                scaled_macros[k] = float(preferred_macros.get(k, 0.0))
            # preferred macros present; use as-is
        else:
            logger.warning(
                "accept_plan_tool: no preferred macros present for %s; using recomputed from main + accompaniments",
                meal_label,
            )
            scaled_macros = recomputed_macros

        # If preferred looks too low versus recomputed (likely missing accompaniments), switch to recomputed.
        preferred_kcal = scaled_macros.get("kcal", 0.0)
        recomputed_kcal = recomputed_macros.get("kcal", 0.0)
        if len(accompaniments) > 0 and recomputed_kcal > preferred_kcal * 1.1:
            logger.warning(
                "accept_plan_tool: preferred macros for %s appear low (preferred_kcal=%.1f vs recomputed_kcal=%.1f), "
                "using recomputed totals to include accompaniments",
                meal_label,
                preferred_kcal,
                recomputed_kcal,
            )
            scaled_macros = recomputed_macros

        # Collect all ingredients from main dish and accompaniments
        all_ingredients = recipe.get("ingredients_with_qty") or recipe.get("ingredients") or []
        for acc in accompaniments:
            acc_recipe = acc.get("recipe", {}) if isinstance(acc, dict) else {}
            acc_ingredients = acc_recipe.get("ingredients_with_qty") or acc_recipe.get("ingredients") or []
            if isinstance(acc_ingredients, list):
                all_ingredients.extend(acc_ingredients)
        
        # Build meal description including accompaniments
        meal_items = [dish_name]
        for acc in accompaniments:
            acc_recipe = acc.get("recipe", {}) if isinstance(acc, dict) else {}
            acc_name = acc_recipe.get("dish_name", "Unknown")
            meal_items.append(acc_name)
        meal_desc = f"{meal_label}: {', '.join(meal_items)}"
        
        _log_plan_meal(
            log_collection,
            user_id=user_id,
            meal_desc=meal_desc,
            macros=scaled_macros,
            ingredients=all_ingredients if isinstance(all_ingredients, list) else [],
            logged_at=logged_at,
        )
        logged.append({"meal": meal_label, "dish": meal_desc, "macros": scaled_macros})

    if plan_type == "day":
        # CRITICAL: Delete ALL old MealLogEntry for the same date BEFORE logging new plan
        # This ensures only ONE accepted plan per day (the latest one)
        deleted_count = 0
        if plan_start_date:
            logger.info(f"accept_plan_tool: Attempting to delete old MealLogEntry entries for date {plan_start_date} before logging new plan")
            deleted_count = _delete_logs_for_date(log_collection, user_id, plan_start_date)
            if deleted_count > 0:
                logger.info(f"accept_plan_tool: Deleted {deleted_count} old MealLogEntry entries for date {plan_start_date} before logging new plan")
            else:
                logger.debug(f"accept_plan_tool: No old MealLogEntry entries found for date {plan_start_date} (this is OK if it's the first plan for this date)")
        else:
            logger.warning(f"accept_plan_tool: plan_start_date is None, cannot delete old entries. Plan start_date: {plan.get('start_date')}")
        
        # Log only the meals from the accepted plan (breakfast, lunch, dinner)
        # Each meal includes main dish + all accompaniments in a single entry
        meals_logged = 0
        for meal_key in ["breakfast", "lunch", "dinner"]:
            meal_obj = plan.get("meals", {}).get(meal_key) if plan.get("meals") else plan.get(meal_key)
            if meal_obj:
                _log_meal(meal_obj, meal_key, _day_logged_at())
                meals_logged += 1
                logger.debug(f"accept_plan_tool: Logged {meal_key} (main + {len(meal_obj.get('accompaniments', []))} accompaniments)")
        
        logger.info(f"accept_plan_tool: Successfully logged {meals_logged} meals for plan {plan_id} (replaced {deleted_count} old entries)")
    elif plan_type == "week":
        logger.info("accept_plan_tool: Logging weekly plan %s for user %s", plan_id, user_id)
        days = plan.get("days", {})
        logger.debug("accept_plan_tool: Weekly plan has %d day(s)", len(days))
        for day_key, day in days.items():
            meals = day.get("meals", {})
            day_idx = day.get("day_index") or day.get("day") or 0

            # Prefer explicit date from plan.days; if missing, derive from plan_start_date + day_idx
            raw_day_date = day.get("date")
            day_date = _ensure_date_only(raw_day_date)
            # Fallback: derive date from plan_start_date + day_idx
            if not day_date:
                base = plan_start_date or datetime.now(timezone.utc).date().isoformat()
                try:
                    dt = datetime.fromisoformat(f"{base}T00:00:00") + timedelta(days=int(day_idx))
                    day_date = dt.date().isoformat()
                except Exception:
                    day_date = base

            # logged_at is always anchored to day_date at noon UTC
            logged_at = f"{day_date}T12:00:00Z"

            if day_date:
                _delete_logs_for_date(log_collection, user_id, day_date)

            for meal_key, meal_obj in meals.items():
                logger.debug(
                    "accept_plan_tool: Logging weekly meal | day_idx=%s day_key=%s date=%s "
                    "meal_key=%s has_recipe=%s has_accompaniments=%s",
                    day_idx,
                    day_key,
                    day_date,
                    meal_key,
                    isinstance(meal_obj, dict) and isinstance(meal_obj.get('recipe'), dict),
                    isinstance(meal_obj, dict) and bool(meal_obj.get('accompaniments')),
                )
                _log_meal(meal_obj, f"day_{day_idx}_{meal_key}", logged_at)
    else:
        raise ValueError(f"Unsupported plan_type: {plan_type}")

    return logged


@tool
async def accept_plan_tool(
    tree_data: TreeData,
    client_manager: ClientManager,
    plan_id: str,
    user_id: str = "",
    **kwargs,
) -> AsyncGenerator[Result | Response | Error, None]:
    """
    Accept a prepared meal plan and persist it into MealLogEntry.
    
    CRITICAL: This tool should ONLY be called when:
    1. User explicitly accepts a plan via UI (button click)
    2. User chats with agent accepting the proposed plan (user message indicates acceptance)
    
    DO NOT call this tool automatically after creating a plan. Wait for user acceptance.

    Flow:
    1) Load plan from Weaviate (source of truth)
    2) For each meal, log into MealLogEntry with macros and metadata
    3) Return summary of logged meals
    4) Delete old MealLogEntry for the same date (if any) before logging new plan

    This is the preferred method for accepting plans. Alternative: use log_meal_e2e_tool with user_accepted=True.
    
    COMPLETION HINT: After successfully logging the plan, the task is COMPLETE. 
    DO NOT call any additional tools (profile_crud_tool, macro_calc_tool, explain, etc.).
    Simply confirm to the user that the plan has been saved and END the conversation.
    """
    if not plan_id:
        yield Error("plan_id is required to accept plan")
        return

    if not user_id:
        # Try environment profile cache
        profile_results = tree_data.environment.find("profile_crud_tool", "profile")
        if profile_results and profile_results[0]["objects"]:
            profile = profile_results[0]["objects"][0]
            user_id = profile.get("user_id", "")

    if not user_id:
        yield Error("user_id is required to accept plan")
        return

    yield Response("✅ Đang lưu kế hoạch vào MealLogEntry...")

    try:
        plan = load_plan_from_weaviate(plan_id, client_manager, user_id)
        if not plan:
            yield Error(f"Plan {plan_id} not found for user {user_id}")
            return
    except Exception as e:
        yield Error(f"Failed to load plan {plan_id}: {str(e)}")
        return

    try:
        logged = log_plan_to_meal_log(plan, user_id, client_manager)

        yield Result(
            name="plan_accepted",
            objects=[{"plan_id": plan_id, "user_id": user_id, "logged_meals": logged}],
            metadata={"plan_id": plan_id, "logged_count": len(logged)},
            payload_type="meal_history",
            display=True,
        )
        yield Response(f"🎉 Đã lưu {len(logged)} bữa ăn vào MealLogEntry")

    except Exception as e:
        logger.exception("accept_plan_tool failure")
        yield Error(f"Failed to accept plan {plan_id}: {str(e)}")
        return
