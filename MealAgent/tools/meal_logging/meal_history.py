from typing import AsyncGenerator, Dict, Any, List
from datetime import datetime, timedelta
import json

from elysia.tree.objects import TreeData
from elysia.objects import Result, Error, Response
from elysia.util.client import ClientManager
from elysia import tool

from MealAgent.tools.utils.weaviate_filters import build_filters_from_where


@tool
async def meal_history_tool(
    tree_data: TreeData,
    client_manager: ClientManager,
    user_id: str = "",
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int = 50,
    **kwargs,
) -> AsyncGenerator[Result | Response | Error, None]:
    """
    Retrieve meal log history for a user with optional date filtering.

    Environment writes:
      - environment["meal_history_tool"]["history"]
    """
    yield Response("📊 Retrieving your meal history...")

    if not user_id:
        yield Error("user_id is required")
        return

    try:
        client = client_manager.get_client()
        log_collection = client.collections.get("MealLogEntry")

        # Build where clause
        where_conditions = [{"path": ["user_id"], "operator": "Equal", "valueString": user_id}]

        if start_date:
            where_conditions.append({"path": ["logged_at"], "operator": "GreaterThanEqual", "valueDate": start_date})
        if end_date:
            where_conditions.append({"path": ["logged_at"], "operator": "LessThanEqual", "valueDate": end_date})

        where_clause = where_conditions[0] if len(where_conditions) == 1 else {"operator": "And", "operands": where_conditions}

        filters = build_filters_from_where(where_clause)
        results = log_collection.query.fetch_objects(
            filters=filters,
            limit=limit,
            sort={"path": ["logged_at"], "order": "desc"},
        )

        logs = [obj.properties for obj in results.objects]

        # Aggregate daily totals
        daily_totals: Dict[str, Dict[str, float]] = {}
        for log in logs:
            date = log.get("logged_at", "")[:10]  # Extract date part
            if date not in daily_totals:
                daily_totals[date] = {"kcal": 0.0, "protein_g": 0.0, "fat_g": 0.0, "carb_g": 0.0}

            # Deserialize JSON string if needed (schema stores as TEXT)
            macros_str = log.get("calculated_macros", "{}")
            if isinstance(macros_str, str):
                try:
                    macros = json.loads(macros_str)
                except json.JSONDecodeError:
                    macros = {}
            else:
                macros = macros_str
            
            if isinstance(macros, dict):
                daily_totals[date]["kcal"] += float(macros.get("kcal", 0.0))
                daily_totals[date]["protein_g"] += float(macros.get("protein_g", 0.0))
                daily_totals[date]["fat_g"] += float(macros.get("fat_g", 0.0))
                daily_totals[date]["carb_g"] += float(macros.get("carb_g", 0.0))
            
            # Also deserialize ingredients and calculated_micros for log objects
            if isinstance(log.get("ingredients"), str):
                try:
                    log["ingredients"] = json.loads(log["ingredients"])
                except json.JSONDecodeError:
                    pass
            if isinstance(log.get("calculated_micros"), str):
                try:
                    log["calculated_micros"] = json.loads(log["calculated_micros"])
                except json.JSONDecodeError:
                    pass
            if isinstance(log.get("calculated_macros"), str):
                log["calculated_macros"] = macros  # Use already deserialized value

        history = {
            "user_id": user_id,
            "logs": logs,
            "daily_totals": daily_totals,
            "total_logs": len(logs),
            "date_range": {"start": start_date, "end": end_date},
        }

        # Use meal_history payload_type for explicit frontend detection
        yield Result(
            name="history",
            objects=[history],
            metadata={"user_id": user_id, "logs_count": len(logs), "days_count": len(daily_totals)},
            payload_type="meal_history",
            display=True,
        )
        # Table view of logs for display (fallback for table view)
        yield Result(
            name="logs",
            objects=logs,
            metadata={"user_id": user_id, "logs_count": len(logs)},
            payload_type="table",
            display=True,
        )
        yield Response(
            f"✅ Found {len(logs)} meal log(s) across {len(daily_totals)} day(s)"
        )

    except Exception as e:
        yield Error(f"Meal history retrieval failed for user {user_id}: {str(e)}")
        return

