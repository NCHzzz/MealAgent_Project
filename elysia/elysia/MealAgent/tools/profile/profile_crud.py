from typing import AsyncGenerator, Optional

from elysia.tree.objects import TreeData
from elysia.objects import Result, Error
from elysia.util.client import ClientManager
from elysia import tool


REQUIRED_FIELDS = [
    "user_id",
    "age",
    "gender",
    "weight_kg",
    "height_cm",
    "activity_level",
]


def _validate_profile_payload(profile_data: Optional[dict]) -> Optional[str]:
    """Validate profile data with type and range checks."""
    if not isinstance(profile_data, dict):
        return "profile_data must be an object"
    
    missing = [f for f in REQUIRED_FIELDS if f not in profile_data]
    if missing:
        return f"Missing required fields: {missing}"
    
    # Type and range validation
    age = profile_data.get("age")
    if not isinstance(age, int) or age <= 0 or age > 120:
        return f"age must be an integer between 1 and 120, got: {age}"
    
    gender = profile_data.get("gender", "").lower()
    if gender not in ["male", "female", "other"]:
        return f"gender must be 'male', 'female', or 'other', got: {profile_data.get('gender')}"
    
    weight_kg = profile_data.get("weight_kg")
    if not isinstance(weight_kg, (int, float)) or weight_kg <= 0 or weight_kg > 500:
        return f"weight_kg must be a positive number <= 500, got: {weight_kg}"
    
    height_cm = profile_data.get("height_cm")
    if not isinstance(height_cm, (int, float)) or height_cm <= 0 or height_cm > 300:
        return f"height_cm must be a positive number <= 300, got: {height_cm}"
    
    activity_level = profile_data.get("activity_level", "").lower()
    valid_activities = ["sedentary", "light", "moderate", "very_active", "extra_active"]
    if activity_level not in valid_activities:
        return f"activity_level must be one of {valid_activities}, got: {profile_data.get('activity_level')}"
    
    return None


@tool
async def profile_crud_tool(
    tree_data: TreeData,
    client_manager: ClientManager,
    action: str = "create",
    profile_data: dict | None = None,
    **kwargs,
) -> AsyncGenerator[Result | str | Error, None]:
    """
    Create, read, or update a UserProfile in Weaviate.

    Environment writes:
      - environment["profile_crud_tool"]["profile"]
    """
    yield f"Processing profile {action}..."

    # Ensure valid action
    allowed = {"create", "update", "read"}
    if action not in allowed:
        yield Error(f"Unsupported action: {action}. Allowed: {sorted(list(allowed))}")
        return

    try:
        with client_manager.connect_to_client() as client:
            collection = client.collections.get("UserProfile")

            if action in {"create", "update"}:
                error = _validate_profile_payload(profile_data)
                if error:
                    yield Error(error)
                    return

                # Upsert by user_id: try fetch, then insert/update
                user_id = profile_data["user_id"]
                existing = collection.query.fetch_objects(
                    where={
                        "path": ["user_id"],
                        "operator": "Equal",
                        "valueString": user_id,
                    },
                    limit=1,
                )

                if existing.objects:
                    collection.data.update(
                        uuid=existing.objects[0].uuid,
                        properties=profile_data,
                    )
                else:
                    collection.data.insert(profile_data)

                yield Result(
                    name="profile",
                    objects=[profile_data],
                    metadata={"action": action, "user_id": user_id},
                )
                yield f"Profile {action}d successfully for user {user_id}"

            else:  # read
                user_id = (
                    profile_data.get("user_id")
                    if isinstance(profile_data, dict)
                    else kwargs.get("user_id")
                )
                if not user_id:
                    yield Error("user_id is required for read operation")
                    return

                result = collection.query.fetch_objects(
                    where={
                        "path": ["user_id"],
                        "operator": "Equal",
                        "valueString": user_id,
                    },
                    limit=1,
                )

                if not result.objects:
                    yield Error(f"Profile not found for user {user_id}")
                    return

                profile = result.objects[0].properties
                yield Result(
                    name="profile",
                    objects=[profile],
                    metadata={"action": "read", "user_id": user_id},
                )
                yield f"Profile read successfully for user {user_id}"

    except Exception as e:
        action_str = f" ({action})" if action else ""
        yield Error(f"Profile operation{action_str} failed: {str(e)}")
        return


