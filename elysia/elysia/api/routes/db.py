from fastapi import APIRouter, Depends, Query, Body
from fastapi.responses import JSONResponse
from datetime import datetime, timedelta, timezone
import json
from typing import Any

from pydantic import BaseModel

from elysia.api.dependencies.common import get_user_manager
from elysia.api.services.user import UserManager
from elysia.util.client import ClientManager
from weaviate.classes.query import Filter, Sort
from MealAgent.tools.meal_logging.accept_plan import log_plan_to_meal_log
from MealAgent.tools.utils.plan_loader import load_plan_from_weaviate
from MealAgent.tools.utils.planning_helpers import ensure_rfc3339_datetime

# Logging
from elysia.api.core.log import logger


class AcceptPlanPayload(BaseModel):
    plan_id: str


router = APIRouter()


def _logged_at_to_iso(value) -> str:
    """Normalize logged_at to RFC3339-like string for consistent serialization."""
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    if isinstance(value, str):
        # Already a string; best effort keep only seconds precision
        return value
    return ""


def _date_part(value) -> str:
    """Extract YYYY-MM-DD regardless of datetime or string input."""
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, str):
        return value[:10]
    return ""


def _json_safe(value: Any) -> Any:
    """
    Convert Weaviate/py objects (notably datetime) into JSON-serialisable values.
    """
    if isinstance(value, datetime):
        # Always return RFC3339-ish string
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_safe(v) for v in value]
    return value


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


@router.post("/{user_id}/accept_plan")
async def accept_plan(
    user_id: str,
    payload: AcceptPlanPayload = Body(...),
    user_manager: UserManager = Depends(get_user_manager),
):
    headers = {"Cache-Control": "no-cache"}

    try:
        user_local = await user_manager.get_user_local(user_id)
    except Exception as e:
        logger.error(f"User {user_id} not found for accept_plan: {str(e)}")
        return JSONResponse(
            content={"success": False, "error": f"User {user_id} not found"},
            status_code=404,
            headers=headers,
        )

    client_manager: ClientManager = user_local["client_manager"]
    if not client_manager.is_client:
        return JSONResponse(
            content={"success": False, "error": "Client manager is not connected"},
            status_code=400,
            headers=headers,
        )

    plan_id = (payload.plan_id or "").strip()
    if not plan_id:
        return JSONResponse(
            content={"success": False, "error": "plan_id is required"},
            status_code=400,
            headers=headers,
        )
    try:
        plan = load_plan_from_weaviate(plan_id, client_manager, user_id)
    except Exception as e:
        logger.exception(f"Failed to load plan {plan_id} for user {user_id}")
        return JSONResponse(
            content={
                "success": False,
                "error": f"Failed to load plan {plan_id}: {str(e)}",
            },
            status_code=500,
            headers=headers,
        )

    if not plan:
        return JSONResponse(
            content={
                "success": False,
                "error": f"Plan {plan_id} not found for user {user_id}",
            },
            status_code=404,
            headers=headers,
        )

    try:
        logged = log_plan_to_meal_log(plan, user_id, client_manager)
        logger.info(f"accept_plan: Successfully logged {len(logged)} meals for plan {plan_id}")
        return JSONResponse(
            content={
                "success": True,
                "plan_id": plan_id,
                "user_id": user_id,
                "logged": logged,
                "logged_count": len(logged),
                "message": f"Saved {len(logged)} meals to MealLogEntry",
                "error": "",
            },
            status_code=200,
            headers=headers,
        )
    except Exception as e:
        logger.exception("Error accepting plan")
        return JSONResponse(
            content={
                "success": False,
                "plan_id": plan_id,
                "user_id": user_id,
                "logged": [],
                "logged_count": 0,
                "error": str(e),
            },
            status_code=500,
            headers=headers,
        )


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
                logged_at_raw = log.get("logged_at")
                logged_at_iso = _logged_at_to_iso(logged_at_raw)
                log["logged_at"] = logged_at_iso  # ensure consistent type for frontend
                date = _date_part(logged_at_raw)
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


class PantryPayload(BaseModel):
    pantry_items: list[dict] | None = None


@router.get("/{user_id}/pantry")
@router.post("/{user_id}/pantry")
async def pantry_crud(
    user_id: str,
    action: str = Query("read", description="Action: read, create, update, or delete"),
    payload: PantryPayload | None = Body(None),
    user_manager: UserManager = Depends(get_user_manager),
):
    """
    CRUD operations for pantry items.
    GET: Read pantry items
    POST: Create, update, or delete pantry items (based on action query param)
    """
    headers = {"Cache-Control": "no-cache"}
    
    try:
        user_local = await user_manager.get_user_local(user_id)
        client_manager: ClientManager = user_local["client_manager"]

        if not client_manager.is_client:
            return JSONResponse(
                content={"state": None, "items": [], "error": "Client manager is not connected"},
                status_code=200,
                headers=headers,
            )

        allowed_actions = {"read", "create", "update", "delete"}
        if action not in allowed_actions:
            return JSONResponse(
                content={
                    "state": None,
                    "items": [],
                    "error": f"Unsupported action: {action}. Allowed: {sorted(list(allowed_actions))}",
                },
                status_code=400,
                headers=headers,
            )

        pantry_items = (payload.pantry_items if payload else None) or []

        async with client_manager.connect_to_async_client() as client:
            # Ensure collections exist
            if not await client.collections.exists("Pantry") or not await client.collections.exists("PantryItem"):
                return JSONResponse(
                    content={"state": None, "items": [], "error": "Pantry/PantryItem collections do not exist"},
                    status_code=200,
                    headers=headers,
                )

            pantry_collection = client.collections.get("Pantry")
            item_collection = client.collections.get("PantryItem")

            # Ensure pantry exists (for consistency with tool behavior)
            pantry_results = await pantry_collection.query.fetch_objects(
                filters=Filter.by_property("user_id").equal(user_id),
                limit=1,
            )
            if not pantry_results.objects:
                await pantry_collection.data.insert(
                    {"user_id": user_id, "updated_at": ensure_rfc3339_datetime(datetime.now(timezone.utc))}
                )

            if action == "read":
                item_results = await item_collection.query.fetch_objects(
                    filters=Filter.by_property("user_id").equal(user_id),
                    limit=9999,
                )
                items = [_json_safe(obj.properties) for obj in item_results.objects]
                state = _json_safe({"user_id": user_id, "items": items, "item_count": len(items)})
                return JSONResponse(
                    content={"state": state, "items": items, "error": ""},
                    status_code=200,
                    headers=headers,
                )

            # create/update/delete require payload items
            if not pantry_items:
                return JSONResponse(
                    content={"state": None, "items": [], "error": "pantry_items is required"},
                    status_code=400,
                    headers=headers,
                )

            # Basic validation + normalization
            normalized_items: list[dict] = []
            for i, it in enumerate(pantry_items):
                if not isinstance(it, dict):
                    return JSONResponse(
                        content={"state": None, "items": [], "error": f"pantry_items[{i}] must be an object"},
                        status_code=400,
                        headers=headers,
                    )
                name = (it.get("ingredient_name") or "").strip()
                if not name:
                    return JSONResponse(
                        content={"state": None, "items": [], "error": f"pantry_items[{i}].ingredient_name is required"},
                        status_code=400,
                        headers=headers,
                    )
                try:
                    qty = float(it.get("quantity"))
                except Exception:
                    return JSONResponse(
                        content={"state": None, "items": [], "error": f"pantry_items[{i}].quantity must be a number"},
                        status_code=400,
                        headers=headers,
                    )
                if qty < 0:
                    return JSONResponse(
                        content={"state": None, "items": [], "error": f"pantry_items[{i}].quantity must be non-negative"},
                        status_code=400,
                        headers=headers,
                    )
                unit = (it.get("unit") or "g").strip() or "g"
                fdc_id = it.get("fdc_id")
                expiry_date = it.get("expiry_date")
                normalized_items.append(
                    {
                        "user_id": user_id,
                        "ingredient_name": name,
                        "quantity": qty,
                        "unit": unit,
                        "fdc_id": fdc_id,
                        "expiry_date": expiry_date,
                    }
                )

            if action == "create":
                for it in normalized_items:
                    await item_collection.data.insert(it)

            elif action == "update":
                for it in normalized_items:
                    item_results = await item_collection.query.fetch_objects(
                        filters=Filter.all_of(
                            [
                                Filter.by_property("user_id").equal(user_id),
                                Filter.by_property("ingredient_name").equal(it["ingredient_name"]),
                            ]
                        ),
                        limit=1,
                    )
                    if item_results.objects:
                        obj = item_results.objects[0]
                        props = dict(obj.properties)
                        props.update(
                            {
                                "quantity": it["quantity"],
                                "unit": it["unit"],
                                "fdc_id": it.get("fdc_id"),
                                "expiry_date": it.get("expiry_date"),
                            }
                        )
                        await item_collection.data.update(uuid=obj.uuid, properties=props)
                    else:
                        # Upsert behavior: if not found, insert
                        await item_collection.data.insert(it)

            elif action == "delete":
                for it in normalized_items:
                    item_results = await item_collection.query.fetch_objects(
                        filters=Filter.all_of(
                            [
                                Filter.by_property("user_id").equal(user_id),
                                Filter.by_property("ingredient_name").equal(it["ingredient_name"]),
                            ]
                        ),
                        limit=10,
                    )
                    for obj in item_results.objects:
                        await item_collection.data.delete_by_id(obj.uuid)

            # Update pantry updated_at (best-effort)
            pantry_results = await pantry_collection.query.fetch_objects(
                filters=Filter.by_property("user_id").equal(user_id),
                limit=1,
            )
            if pantry_results.objects:
                pantry_obj = pantry_results.objects[0]
                props = dict(pantry_obj.properties)
                props["updated_at"] = ensure_rfc3339_datetime(datetime.now(timezone.utc))
                await pantry_collection.data.update(uuid=pantry_obj.uuid, properties=props)

            # Return latest state/items
            item_results = await item_collection.query.fetch_objects(
                filters=Filter.by_property("user_id").equal(user_id),
                limit=9999,
            )
            items = [_json_safe(obj.properties) for obj in item_results.objects]
            state = _json_safe({"user_id": user_id, "items": items, "item_count": len(items)})
            return JSONResponse(
                content={"state": state, "items": items, "error": ""},
                status_code=200,
                headers=headers,
            )

    except Exception as e:
        logger.exception(f"Error in /pantry API: {str(e)}")
        return JSONResponse(content={"state": None, "items": [], "error": str(e)}, status_code=500, headers=headers)


class ShoppingListPayload(BaseModel):
    list_id: str | None = None
    shopping_items: list[dict] | None = None


@router.get("/{user_id}/shopping")
@router.post("/{user_id}/shopping")
async def shopping_crud(
    user_id: str,
    action: str = Query("read", description="Action: read, create, update, delete, or toggle_purchased"),
    list_id: str | None = Query(None, description="Shopping list ID (required for read/update/delete)"),
    payload: ShoppingListPayload | None = Body(None),
    user_manager: UserManager = Depends(get_user_manager),
):
    """
    CRUD operations for shopping lists and items.
    GET: Read shopping lists and items
    POST: Create, update, delete shopping items, or toggle purchased status
    """
    headers = {"Cache-Control": "no-cache"}
    
    try:
        user_local = await user_manager.get_user_local(user_id)
        client_manager: ClientManager = user_local["client_manager"]

        if not client_manager.is_client:
            return JSONResponse(
                content={"lists": [], "items": [], "error": "Client manager is not connected"},
                status_code=200,
                headers=headers,
            )

        allowed_actions = {"read", "create", "update", "delete", "toggle_purchased"}
        if action not in allowed_actions:
            return JSONResponse(
                content={
                    "lists": [],
                    "items": [],
                    "error": f"Unsupported action: {action}. Allowed: {sorted(list(allowed_actions))}",
                },
                status_code=400,
                headers=headers,
            )

        async with client_manager.connect_to_async_client() as client:
            # Ensure collections exist
            if not await client.collections.exists("ShoppingList") or not await client.collections.exists("ShoppingItem"):
                return JSONResponse(
                    content={"lists": [], "items": [], "error": "ShoppingList/ShoppingItem collections do not exist"},
                    status_code=200,
                    headers=headers,
                )

            list_collection = client.collections.get("ShoppingList")
            item_collection = client.collections.get("ShoppingItem")

            if action == "read":
                # Read all shopping lists for user
                list_results = await list_collection.query.fetch_objects(
                    filters=Filter.by_property("user_id").equal(user_id),
                    sort=Sort.by_property("created_at", ascending=False),
                    limit=100,
                )
                
                lists = []
                for list_obj in list_results.objects:
                    list_props = _json_safe(list_obj.properties)
                    list_id_val = list_props.get("list_id")
                    
                    # Get items for this list
                    item_results = await item_collection.query.fetch_objects(
                        filters=Filter.by_property("list_id").equal(list_id_val),
                        limit=9999,
                    )
                    items = [_json_safe(obj.properties) for obj in item_results.objects]
                    
                    lists.append({
                        **list_props,
                        "items": items,
                        "item_count": len(items),
                    })
                
                # If list_id specified, return only that list
                if list_id:
                    filtered_lists = [lst for lst in lists if lst.get("list_id") == list_id]
                    if filtered_lists:
                        return JSONResponse(
                            content={"lists": filtered_lists, "items": filtered_lists[0].get("items", []), "error": ""},
                            status_code=200,
                            headers=headers,
                        )
                    else:
                        return JSONResponse(
                            content={"lists": [], "items": [], "error": f"Shopping list {list_id} not found"},
                            status_code=404,
                            headers=headers,
                        )
                
                # Return all lists
                all_items = []
                for lst in lists:
                    all_items.extend(lst.get("items", []))
                
                return JSONResponse(
                    content={"lists": lists, "items": all_items, "error": ""},
                    status_code=200,
                    headers=headers,
                )

            # Other actions require payload
            payload_list_id = (payload.list_id if payload else None) or list_id
            shopping_items = (payload.shopping_items if payload else None) or []

            if action == "create":
                if not payload_list_id:
                    return JSONResponse(
                        content={"lists": [], "items": [], "error": "list_id is required for create"},
                        status_code=400,
                        headers=headers,
                    )
                
                # Create shopping list if it doesn't exist
                existing_lists = await list_collection.query.fetch_objects(
                    filters=Filter.by_property("list_id").equal(payload_list_id),
                    limit=1,
                )
                if not existing_lists.objects:
                    await list_collection.data.insert({
                        "list_id": payload_list_id,
                        "user_id": user_id,
                        "plan_id": None,  # Can be set later
                        "created_at": ensure_rfc3339_datetime(datetime.now(timezone.utc)),
                    })

                # Create items
                if shopping_items:
                    for it in shopping_items:
                        if not isinstance(it, dict):
                            continue
                        name = (it.get("ingredient_name") or "").strip()
                        if not name:
                            continue
                        await item_collection.data.insert({
                            "list_id": payload_list_id,
                            "ingredient_name": name,
                            "quantity": float(it.get("quantity", 0.0)),
                            "unit": (it.get("unit") or "g").strip() or "g",
                            "category": (it.get("category") or "general").strip(),
                            "purchased": bool(it.get("purchased", False)),
                        })

            elif action == "update":
                if not payload_list_id:
                    return JSONResponse(
                        content={"lists": [], "items": [], "error": "list_id is required for update"},
                        status_code=400,
                        headers=headers,
                    )
                
                if not shopping_items:
                    return JSONResponse(
                        content={"lists": [], "items": [], "error": "shopping_items is required for update"},
                        status_code=400,
                        headers=headers,
                    )

                for it in shopping_items:
                    if not isinstance(it, dict):
                        continue
                    name = (it.get("ingredient_name") or "").strip()
                    if not name:
                        continue
                    
                    # Find existing item
                    item_results = await item_collection.query.fetch_objects(
                        filters=Filter.all_of([
                            Filter.by_property("list_id").equal(payload_list_id),
                            Filter.by_property("ingredient_name").equal(name),
                        ]),
                        limit=1,
                    )
                    
                    if item_results.objects:
                        obj = item_results.objects[0]
                        props = dict(obj.properties)
                        props.update({
                            "quantity": float(it.get("quantity", props.get("quantity", 0.0))),
                            "unit": (it.get("unit") or props.get("unit", "g")).strip() or "g",
                            "category": (it.get("category") or props.get("category", "general")).strip(),
                            "purchased": bool(it.get("purchased", props.get("purchased", False))),
                        })
                        await item_collection.data.update(uuid=obj.uuid, properties=props)
                    else:
                        # Upsert: create if not found
                        await item_collection.data.insert({
                            "list_id": payload_list_id,
                            "ingredient_name": name,
                            "quantity": float(it.get("quantity", 0.0)),
                            "unit": (it.get("unit") or "g").strip() or "g",
                            "category": (it.get("category") or "general").strip(),
                            "purchased": bool(it.get("purchased", False)),
                        })

            elif action == "delete":
                if not payload_list_id:
                    return JSONResponse(
                        content={"lists": [], "items": [], "error": "list_id is required for delete"},
                        status_code=400,
                        headers=headers,
                    )
                
                if shopping_items:
                    # Delete specific items
                    for it in shopping_items:
                        if not isinstance(it, dict):
                            continue
                        name = (it.get("ingredient_name") or "").strip()
                        if not name:
                            continue
                        
                        item_results = await item_collection.query.fetch_objects(
                            filters=Filter.all_of([
                                Filter.by_property("list_id").equal(payload_list_id),
                                Filter.by_property("ingredient_name").equal(name),
                            ]),
                            limit=10,
                        )
                        for obj in item_results.objects:
                            await item_collection.data.delete_by_id(obj.uuid)
                else:
                    # Delete entire list and all its items
                    item_results = await item_collection.query.fetch_objects(
                        filters=Filter.by_property("list_id").equal(payload_list_id),
                        limit=9999,
                    )
                    for obj in item_results.objects:
                        await item_collection.data.delete_by_id(obj.uuid)
                    
                    list_results = await list_collection.query.fetch_objects(
                        filters=Filter.by_property("list_id").equal(payload_list_id),
                        limit=1,
                    )
                    for obj in list_results.objects:
                        await list_collection.data.delete_by_id(obj.uuid)

            elif action == "toggle_purchased":
                if not payload_list_id:
                    return JSONResponse(
                        content={"lists": [], "items": [], "error": "list_id is required for toggle_purchased"},
                        status_code=400,
                        headers=headers,
                    )
                
                if not shopping_items:
                    return JSONResponse(
                        content={"lists": [], "items": [], "error": "shopping_items is required for toggle_purchased"},
                        status_code=400,
                        headers=headers,
                    )

                for it in shopping_items:
                    if not isinstance(it, dict):
                        continue
                    name = (it.get("ingredient_name") or "").strip()
                    if not name:
                        continue
                    
                    item_results = await item_collection.query.fetch_objects(
                        filters=Filter.all_of([
                            Filter.by_property("list_id").equal(payload_list_id),
                            Filter.by_property("ingredient_name").equal(name),
                        ]),
                        limit=1,
                    )
                    
                    if item_results.objects:
                        obj = item_results.objects[0]
                        props = dict(obj.properties)
                        props["purchased"] = not props.get("purchased", False)
                        await item_collection.data.update(uuid=obj.uuid, properties=props)

            # Return latest state
            if payload_list_id:
                list_results = await list_collection.query.fetch_objects(
                    filters=Filter.by_property("list_id").equal(payload_list_id),
                    limit=1,
                )
                if list_results.objects:
                    list_props = _json_safe(list_results.objects[0].properties)
                    item_results = await item_collection.query.fetch_objects(
                        filters=Filter.by_property("list_id").equal(payload_list_id),
                        limit=9999,
                    )
                    items = [_json_safe(obj.properties) for obj in item_results.objects]
                    return JSONResponse(
                        content={"lists": [{**list_props, "items": items, "item_count": len(items)}], "items": items, "error": ""},
                        status_code=200,
                        headers=headers,
                    )
            
            # Return all lists for user
            list_results = await list_collection.query.fetch_objects(
                filters=Filter.by_property("user_id").equal(user_id),
                sort=Sort.by_property("created_at", ascending=False),
                limit=100,
            )
            lists = []
            for list_obj in list_results.objects:
                list_props = _json_safe(list_obj.properties)
                list_id_val = list_props.get("list_id")
                item_results = await item_collection.query.fetch_objects(
                    filters=Filter.by_property("list_id").equal(list_id_val),
                    limit=9999,
                )
                items = [_json_safe(obj.properties) for obj in item_results.objects]
                lists.append({**list_props, "items": items, "item_count": len(items)})
            
            all_items = []
            for lst in lists:
                all_items.extend(lst.get("items", []))
            
            return JSONResponse(
                content={"lists": lists, "items": all_items, "error": ""},
                status_code=200,
                headers=headers,
            )

    except Exception as e:
        logger.exception(f"Error in /shopping API: {str(e)}")
        return JSONResponse(content={"lists": [], "items": [], "error": str(e)}, status_code=500, headers=headers)