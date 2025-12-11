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
    """Delete MealLogEntry for a specific UTC date for this user."""
    try:
        start_dt = datetime.fromisoformat(f"{date_only}T00:00:00").replace(tzinfo=timezone.utc)
        end_dt = start_dt + timedelta(days=1)
        where_clause = {
            "operator": "And",
            "operands": [
                {"path": ["user_id"], "operator": "Equal", "valueString": user_id},
                {"path": ["logged_at"], "operator": "GreaterThanEqual", "valueDate": start_dt.isoformat().replace("+00:00", "Z")},
                {"path": ["logged_at"], "operator": "LessThan", "valueDate": end_dt.isoformat().replace("+00:00", "Z")},
            ],
        }
        filters = build_filters_from_where(where_clause)
        existing = log_collection.query.fetch_objects(filters=filters, limit=256)
        for obj in existing.objects:
            try:
                log_collection.data.delete_by_id(obj.uuid)
            except Exception:
                logger.debug(f"accept_plan_tool: failed deleting old log {obj.uuid}")
    except Exception as e:
        logger.warning(f"accept_plan_tool: unable to purge logs for {date_only}: {str(e)}")


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

    Flow:
    1) Load plan from Weaviate (source of truth)
    2) For each meal, log into MealLogEntry with macros and metadata
    3) Return summary of logged meals

    Only logs when user explicitly accepts the final plan.
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
        client = client_manager.get_client()
        try:
            log_collection = client.collections.get("MealLogEntry")
        except Exception as e:
            yield Error(f"MealLogEntry collection not found: {str(e)}")
            return

        logged = []
        plan_type = plan.get("plan_type", "day")

        plan_start_date = _ensure_date_only(plan.get("start_date"))

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
            recipe = meal_obj.get("recipe", {}) if isinstance(meal_obj, dict) else {}
            dish_name = recipe.get("dish_name") or meal_label
            servings = meal_obj.get("servings", 1.0) if isinstance(meal_obj, dict) else 1.0
            macros = (
                meal_obj.get("macros_total")
                or meal_obj.get("macros")
                or recipe.get("macros_per_serving")
                or {}
            )
            # Multiply macros by servings if they look like per-serving
            scaled_macros = {}
            for k in ["kcal", "protein_g", "fat_g", "carb_g"]:
                scaled_macros[k] = float(macros.get(k, 0.0)) * float(servings or 1.0)

            ingredients = recipe.get("ingredients_with_qty") or recipe.get("ingredients") or []
            _log_plan_meal(
                log_collection,
                user_id=user_id,
                meal_desc=f"{meal_label}: {dish_name}",
                macros=scaled_macros,
                ingredients=ingredients if isinstance(ingredients, list) else [],
                logged_at=logged_at,
            )
            logged.append({"meal": meal_label, "dish": dish_name, "macros": scaled_macros})

        if plan_type == "day":
            # Remove existing logs for the plan date
            if plan_start_date:
                _delete_logs_for_date(log_collection, user_id, plan_start_date)
            for meal_key in ["breakfast", "lunch", "dinner"]:
                meal_obj = plan.get("meals", {}).get(meal_key) if plan.get("meals") else plan.get(meal_key)
                if meal_obj:
                    _log_meal(meal_obj, meal_key, _day_logged_at())
        elif plan_type == "week":
            for day in plan.get("days", {}).values():
                meals = day.get("meals", {})
                day_idx = day.get("day_index") or day.get("day") or 0
                day_date = _ensure_date_only(day.get("date"))
                logged_at = _day_logged_at(day_offset=int(day_idx), explicit_date=day_date)
                if day_date:
                    _delete_logs_for_date(log_collection, user_id, day_date)
                for meal_key, meal_obj in meals.items():
                    _log_meal(meal_obj, f"day_{day_idx}_{meal_key}", logged_at)
        else:
            yield Error(f"Unsupported plan_type: {plan_type}")
            return

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

