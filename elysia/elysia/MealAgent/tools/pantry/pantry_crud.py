"""
CRUD operations for Pantry and PantryItem collections.
"""
from typing import AsyncGenerator, Dict, Any, List, Optional
from datetime import datetime

from elysia.tree.objects import TreeData
from elysia.objects import Result, Error
from elysia.util.client import ClientManager
from elysia import tool


def _validate_pantry_item(item: Dict[str, Any]) -> tuple[bool, str]:
    """
    Validate pantry item data.
    Returns (is_valid, error_message).
    """
    if not isinstance(item, dict):
        return False, "Item must be a dictionary"
    
    ingredient_name = item.get("ingredient_name")
    if not ingredient_name or not isinstance(ingredient_name, str) or not ingredient_name.strip():
        return False, "ingredient_name is required and must be a non-empty string"
    
    quantity = item.get("quantity")
    if quantity is None:
        return False, "quantity is required"
    try:
        quantity_float = float(quantity)
        if quantity_float < 0:
            return False, "quantity must be non-negative"
    except (ValueError, TypeError):
        return False, "quantity must be a number"
    
    unit = item.get("unit", "g")
    if not isinstance(unit, str):
        return False, "unit must be a string"
    
    fdc_id = item.get("fdc_id")
    if fdc_id is not None:
        try:
            fdc_id_int = int(fdc_id)
            if fdc_id_int <= 0:
                return False, "fdc_id must be a positive integer if provided"
        except (ValueError, TypeError):
            return False, "fdc_id must be a positive integer if provided"
    
    expiry_date = item.get("expiry_date")
    if expiry_date is not None:
        if not isinstance(expiry_date, str):
            return False, "expiry_date must be a string (ISO format) if provided"
        # Basic ISO format check
        try:
            datetime.fromisoformat(expiry_date.replace("Z", "+00:00"))
        except ValueError:
            return False, "expiry_date must be in ISO format if provided"
    
    return True, ""


@tool
async def pantry_crud_tool(
    tree_data: TreeData,
    client_manager: ClientManager,
    action: str = "read",
    user_id: str = "",
    pantry_items: List[Dict[str, Any]] | None = None,
    **kwargs,
) -> AsyncGenerator[Result | str | Error, None]:
    """
    Create, read, update, or delete pantry items for a user.

    Actions:
        - "read": Get all pantry items for user
        - "create": Add new pantry items
        - "update": Update existing pantry items
        - "delete": Remove pantry items

    Environment writes:
      - environment["pantry_crud_tool"]["state"]
    """
    yield f"Processing pantry {action}..."

    if not user_id:
        yield Error("user_id is required")
        return

    allowed_actions = {"create", "read", "update", "delete"}
    if action not in allowed_actions:
        yield Error(f"Unsupported action: {action}. Allowed: {sorted(list(allowed_actions))}")
        return

    try:
        client = client_manager.get_client()
        pantry_collection = client.collections.get("Pantry")
        item_collection = client.collections.get("PantryItem")

        if action == "read":
            # Get pantry (create if doesn't exist)
            pantry_results = pantry_collection.query.fetch_objects(
                where={"path": ["user_id"], "operator": "Equal", "valueString": user_id},
                limit=1,
            )

            if not pantry_results.objects:
                # Create pantry
                pantry_data = {
                    "user_id": user_id,
                    "updated_at": datetime.now().isoformat(),
                }
                pantry_collection.data.insert(pantry_data)

            # Get all pantry items
            items_results = item_collection.query.fetch_objects(
                where={"path": ["user_id"], "operator": "Equal", "valueString": user_id},
            )

            items = [obj.properties for obj in items_results.objects]

            state = {
                "user_id": user_id,
                "items": items,
                "item_count": len(items),
            }

            yield Result(
                name="state",
                objects=[state],
                metadata={"action": "read", "user_id": user_id, "item_count": len(items)},
                payload_type="generic",
            )
            # Table rows of items for display
            yield Result(
                name="items",
                objects=items,
                metadata={"action": "read", "user_id": user_id, "item_count": len(items)},
                payload_type="table",
            )
            yield f"Retrieved {len(items)} pantry items"

        elif action == "create":
            if not pantry_items:
                yield Error("pantry_items is required for create action")
                return

            # Ensure pantry exists
            pantry_results = pantry_collection.query.fetch_objects(
                where={"path": ["user_id"], "operator": "Equal", "valueString": user_id},
                limit=1,
            )
            if not pantry_results.objects:
                pantry_data = {
                    "user_id": user_id,
                    "updated_at": datetime.now().isoformat(),
                }
                pantry_collection.data.insert(pantry_data)

            # Insert items with validation
            created_items = []
            for idx, item in enumerate(pantry_items):
                is_valid, error_msg = _validate_pantry_item(item)
                if not is_valid:
                    yield Error(f"Invalid pantry item at index {idx}: {error_msg}")
                    return
                
                item_data = {
                    "user_id": user_id,
                    "ingredient_name": item.get("ingredient_name", "").strip(),
                    "quantity": float(item.get("quantity", 0.0)),
                    "unit": item.get("unit", "g"),
                    "fdc_id": item.get("fdc_id"),  # Optional
                    "expiry_date": item.get("expiry_date"),  # Optional
                }
                item_collection.data.insert(item_data)
                created_items.append(item_data)

            # Update pantry timestamp
            if pantry_results.objects:
                pantry = pantry_results.objects[0]
                pantry.properties["updated_at"] = datetime.now().isoformat()
                pantry_collection.data.update(uuid=pantry.uuid, properties=pantry.properties)

            state = {
                "user_id": user_id,
                "items": created_items,
                "item_count": len(created_items),
            }

            yield Result(
                name="state",
                objects=[state],
                metadata={"action": "create", "user_id": user_id, "created_count": len(created_items)},
                payload_type="generic",
            )
            yield Result(
                name="items",
                objects=created_items,
                metadata={"action": "create", "user_id": user_id, "created_count": len(created_items)},
                payload_type="table",
            )
            yield f"Created {len(created_items)} pantry items"

        elif action == "update":
            if not pantry_items:
                yield Error("pantry_items is required for update action")
                return

            # Update items (by ingredient_name + user_id) with validation
            updated_count = 0
            for idx, item in enumerate(pantry_items):
                is_valid, error_msg = _validate_pantry_item(item)
                if not is_valid:
                    yield Error(f"Invalid pantry item at index {idx}: {error_msg}")
                    return
                
                ingredient_name = item.get("ingredient_name", "").strip()
                if not ingredient_name:
                    continue

                # Find existing item
                item_results = item_collection.query.fetch_objects(
                    where={
                        "operator": "And",
                        "operands": [
                            {"path": ["user_id"], "operator": "Equal", "valueString": user_id},
                            {"path": ["ingredient_name"], "operator": "Equal", "valueString": ingredient_name},
                        ],
                    },
                    limit=1,
                )

                if item_results.objects:
                    # Update existing
                    item_obj = item_results.objects[0]
                    item_obj.properties.update({
                        "quantity": float(item.get("quantity", item_obj.properties.get("quantity", 0.0))),
                        "unit": item.get("unit", item_obj.properties.get("unit", "g")),
                        "fdc_id": item.get("fdc_id", item_obj.properties.get("fdc_id")),
                        "expiry_date": item.get("expiry_date", item_obj.properties.get("expiry_date")),
                    })
                    item_collection.data.update(uuid=item_obj.uuid, properties=item_obj.properties)
                    updated_count += 1

            # Update pantry timestamp only if items were actually updated
            if updated_count > 0:
                pantry_results = pantry_collection.query.fetch_objects(
                    where={"path": ["user_id"], "operator": "Equal", "valueString": user_id},
                    limit=1,
                )
                if pantry_results.objects:
                    pantry = pantry_results.objects[0]
                    pantry.properties["updated_at"] = datetime.now().isoformat()
                    pantry_collection.data.update(uuid=pantry.uuid, properties=pantry.properties)

            state = {
                "user_id": user_id,
                "updated_count": updated_count,
            }

            yield Result(
                name="state",
                objects=[state],
                metadata={"action": "update", "user_id": user_id, "updated_count": updated_count},
                payload_type="generic",
            )
            # For update, fetch latest items for table view (optional minimal change: skip fetch; no rows emitted)
            yield f"Updated {updated_count} pantry items"

        elif action == "delete":
            if not pantry_items:
                yield Error("pantry_items is required for delete action")
                return

            # Delete items (by ingredient_name + user_id)
            deleted_count = 0
            for item in pantry_items:
                if not isinstance(item, dict):
                    continue
                ingredient_name = item.get("ingredient_name")
                if not ingredient_name or not isinstance(ingredient_name, str):
                    continue
                ingredient_name = ingredient_name.strip()
                if not ingredient_name:
                    continue

                item_results = item_collection.query.fetch_objects(
                    where={
                        "operator": "And",
                        "operands": [
                            {"path": ["user_id"], "operator": "Equal", "valueString": user_id},
                            {"path": ["ingredient_name"], "operator": "Equal", "valueString": ingredient_name},
                        ],
                    },
                    limit=1,
                )

                if item_results.objects:
                    item_collection.data.delete_by_id(item_results.objects[0].uuid)
                    deleted_count += 1

            # Update pantry timestamp
            pantry_results = pantry_collection.query.fetch_objects(
                where={"path": ["user_id"], "operator": "Equal", "valueString": user_id},
                limit=1,
            )
            if pantry_results.objects:
                pantry = pantry_results.objects[0]
                pantry.properties["updated_at"] = datetime.now().isoformat()
                pantry_collection.data.update(uuid=pantry.uuid, properties=pantry.properties)

            state = {
                "user_id": user_id,
                "deleted_count": deleted_count,
            }

            yield Result(
                name="state",
                objects=[state],
                metadata={"action": "delete", "user_id": user_id, "deleted_count": deleted_count},
                payload_type="generic",
            )
            # For delete, we can also emit remaining items table on demand (skipped here to avoid extra fetch)
            yield f"Deleted {deleted_count} pantry items"

    except Exception as e:
        yield Error(f"Pantry operation {action} failed for user {user_id}: {str(e)}")
        return

