from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from datetime import datetime, timedelta, timezone
import json

from elysia.api.dependencies.common import get_user_manager
from elysia.api.services.user import UserManager
from elysia.util.client import ClientManager
from weaviate.classes.query import Filter, Sort

# Logging
from elysia.api.core.log import logger

router = APIRouter()


@router.get("/{user_id}/saved_trees")
async def get_saved_trees(
    user_id: str,
    user_manager: UserManager = Depends(get_user_manager),
):

    headers = {"Cache-Control": "no-cache"}

    user = await user_manager.get_user_local(user_id)
    save_location_client_manager = user["frontend_config"].save_location_client_manager
    if not save_location_client_manager.is_client:
        logger.warning(
            "In /get_saved_trees API, "
            "no valid destination for trees location found. "
            "Returning no error but an empty list of trees."
        )
        return JSONResponse(
            content={"trees": {}, "error": ""},
            status_code=200,
            headers=headers,
        )

    try:
        trees = await user_manager.get_saved_trees(
            user_id, save_location_client_manager
        )
        return JSONResponse(
            content={"trees": trees, "error": ""}, status_code=200, headers=headers
        )

    except Exception as e:
        logger.error(f"Error getting saved trees: {str(e)}")
        return JSONResponse(
            content={"trees": {}, "error": str(e)}, status_code=500, headers=headers
        )


@router.get("/{user_id}/load_tree/{conversation_id}")
async def load_tree(
    user_id: str,
    conversation_id: str,
    user_manager: UserManager = Depends(get_user_manager),
):

    headers = {"Cache-Control": "no-cache"}

    try:
        frontend_rebuild = await user_manager.load_tree(user_id, conversation_id)
        return JSONResponse(
            content={"rebuild": frontend_rebuild, "error": ""},
            status_code=200,
            headers=headers,
        )
    except Exception as e:
        logger.error(f"Error loading tree: {str(e)}")
        return JSONResponse(
            content={"rebuild": [], "error": str(e)},
            status_code=500,
            headers=headers,
        )


@router.post("/{user_id}/save_tree/{conversation_id}")
async def save_tree(
    user_id: str,
    conversation_id: str,
    user_manager: UserManager = Depends(get_user_manager),
):
    try:
        await user_manager.save_tree(user_id, conversation_id)
        return JSONResponse(content={"error": ""}, status_code=200)
    except Exception as e:
        logger.error(f"Error saving tree: {str(e)}")
        return JSONResponse(content={"error": str(e)}, status_code=500)


@router.delete("/{user_id}/delete_tree/{conversation_id}")
async def delete_tree(
    user_id: str,
    conversation_id: str,
    user_manager: UserManager = Depends(get_user_manager),
):
    try:
        await user_manager.delete_tree(user_id, conversation_id)
        return JSONResponse(content={"error": ""}, status_code=200)
    except Exception as e:
        logger.error(f"Error deleting tree: {str(e)}")
        return JSONResponse(content={"error": str(e)}, status_code=500)


@router.get("/{user_id}/meal_history")
async def get_meal_history(
    user_id: str,
    start_date: str | None = Query(None, description="Start date in YYYY-MM-DD format"),
    end_date: str | None = Query(None, description="End date in YYYY-MM-DD format"),
    days: int = Query(30, description="Number of days to look back (used if start_date not provided)"),
    limit: int = Query(50, description="Maximum number of logs to return"),
    user_manager: UserManager = Depends(get_user_manager),
):
    """
    Retrieve meal log history for a user with optional date filtering.
    This endpoint queries the database directly without using tools.
    
    Args:
        user_id: The ID of the user
        start_date: Optional start date in YYYY-MM-DD format
        end_date: Optional end date in YYYY-MM-DD format
        days: Number of days to look back (default 30, used if start_date not provided)
        limit: Maximum number of logs to return (default 50)
        user_manager: The user manager
    
    Returns:
        JSONResponse containing:
            - user_id: The user ID
            - logs: List of meal log entries
            - daily_totals: Dictionary of daily nutrition totals
            - total_logs: Total number of logs returned
            - date_range: Dictionary with start and end dates
            - error: Error message if any, otherwise empty string
    """
    headers = {"Cache-Control": "no-cache"}
    
    try:
        # Calculate date range if not provided
        # Weaviate requires RFC3339 format with timezone (e.g., "2025-12-02T23:59:59Z")
        def format_rfc3339(dt: datetime) -> str:
            """Format datetime to RFC3339 with UTC timezone."""
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.isoformat().replace('+00:00', 'Z')
        
        if not end_date:
            # End of today (23:59:59) in UTC
            end_date = format_rfc3339(
                datetime.now(timezone.utc).replace(hour=23, minute=59, second=59, microsecond=999999)
            )
        
        if not start_date:
            # Start of day N days ago (00:00:00) in UTC
            start_date_obj = datetime.now(timezone.utc) - timedelta(days=days)
            start_date = format_rfc3339(
                start_date_obj.replace(hour=0, minute=0, second=0, microsecond=0)
            )
        
        # If dates are provided as YYYY-MM-DD, convert to RFC3339 format
        if start_date and len(start_date) == 10:  # YYYY-MM-DD format
            dt = datetime.fromisoformat(start_date).replace(hour=0, minute=0, second=0, microsecond=0)
            start_date = format_rfc3339(dt.replace(tzinfo=timezone.utc))
        if end_date and len(end_date) == 10:  # YYYY-MM-DD format
            dt = datetime.fromisoformat(end_date).replace(hour=23, minute=59, second=59, microsecond=999999)
            end_date = format_rfc3339(dt.replace(tzinfo=timezone.utc))
        
        # Get user and client manager
        user_local = await user_manager.get_user_local(user_id)
        client_manager: ClientManager = user_local["client_manager"]
        
        if not client_manager.is_client:
            return JSONResponse(
                content={
                    "user_id": user_id,
                    "logs": [],
                    "daily_totals": {},
                    "total_logs": 0,
                    "date_range": {"start": start_date, "end": end_date},
                    "error": "Client manager is not connected",
                },
                status_code=200,
                headers=headers,
            )
        
        async with client_manager.connect_to_async_client() as client:
            # Check if collection exists
            if not await client.collections.exists("MealLogEntry"):
                return JSONResponse(
                    content={
                        "user_id": user_id,
                        "logs": [],
                        "daily_totals": {},
                        "total_logs": 0,
                        "date_range": {"start": start_date, "end": end_date},
                        "error": "MealLogEntry collection does not exist",
                    },
                    status_code=200,
                    headers=headers,
                )
            
            log_collection = client.collections.get("MealLogEntry")
            
            # Build filters
            filters = Filter.all_of([
                Filter.by_property("user_id").equal(user_id),
                Filter.by_property("logged_at").greater_or_equal(start_date),
                Filter.by_property("logged_at").less_or_equal(end_date),
            ])
            
            # Query the collection
            results = await log_collection.query.fetch_objects(
                filters=filters,
                limit=limit,
                sort=Sort.by_property(name="logged_at", ascending=False),
            )
            
            logs = [obj.properties for obj in results.objects]
            
            # Aggregate daily totals
            daily_totals: dict[str, dict[str, float]] = {}
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
            
            return JSONResponse(
                content={
                    **history,
                    "error": "",
                },
                status_code=200,
                headers=headers,
            )
    
    except Exception as e:
        logger.exception(f"Error in /meal_history API: {str(e)}")
        return JSONResponse(
            content={
                "user_id": user_id,
                "logs": [],
                "daily_totals": {},
                "total_logs": 0,
                "date_range": {"start": start_date, "end": end_date},
                "error": str(e),
            },
            status_code=500,
            headers=headers,
        )
