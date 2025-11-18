from typing import AsyncGenerator, Optional
import logging

from elysia.tree.objects import TreeData
from elysia.objects import Result, Error, Response
from elysia.util.client import ClientManager
from elysia import tool

from MealAgent.tools.utils.weaviate_filters import build_filters_from_where


REQUIRED_FIELDS = [
    "user_id",
    "age",
    "gender",
    "weight_kg",
    "height_cm",
    "activity_level",
]


def _validate_profile_payload(profile_data: Optional[dict]) -> Optional[str]:
    """
    Validate profile data with type and range checks.
    
    Args:
        profile_data: Profile data dictionary to validate
        
    Returns:
        Error message string if validation fails, None if valid
    """
    if not isinstance(profile_data, dict):
        return "profile_data must be an object"
    
    missing = [f for f in REQUIRED_FIELDS if f not in profile_data]
    if missing:
        return f"Missing required fields: {missing}"
    
    # Type and range validation with explicit None checks
    age = profile_data.get("age")
    if age is None or not isinstance(age, int) or age <= 0 or age > 120:
        return f"age must be an integer between 1 and 120, got: {age}"
    
    gender = profile_data.get("gender", "").lower()
    if gender not in ["male", "female", "other"]:
        return f"gender must be 'male', 'female', or 'other', got: {profile_data.get('gender')}"
    
    weight_kg = profile_data.get("weight_kg")
    if weight_kg is None or not isinstance(weight_kg, (int, float)) or weight_kg <= 0 or weight_kg > 500:
        return f"weight_kg must be a positive number <= 500, got: {weight_kg}"
    
    height_cm = profile_data.get("height_cm")
    if height_cm is None or not isinstance(height_cm, (int, float)) or height_cm <= 0 or height_cm > 300:
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
) -> AsyncGenerator[Result | Response | Error, None]:
    """
    Create, read, or update a UserProfile in Weaviate.

    Environment interface:
    - Writes:
      - profile_crud_tool.profile: [{ ...profile fields... }]

    Decision hints:
    - Presence of profile_crud_tool.profile means profile is available for downstream
      tools (macro_calc_tool, constraints_guard_tool, etc.).
    - This tool should not be auto-invoked without payload; when missing inputs it
      emits a Response("Skipping ...") and returns to avoid noisy errors.
    """
    logging.info(f"profile_crud_tool: start (action={action})")
    yield Response(f"Processing profile {action}...")

    # Ensure valid action
    allowed = {"create", "update", "read"}
    if action not in allowed:
        error_msg = f"Unsupported action: {action}. Allowed: {sorted(list(allowed))}"
        logging.error(f"profile_crud_tool: {error_msg}")
        yield Error(error_msg)
        return

    try:
        client = client_manager.get_client()
        collection = client.collections.get("UserProfile")

        if action in {"create", "update"}:
            error = _validate_profile_payload(profile_data)
            if error:
                # Graceful skip instead of hard error when auto-invoked without payload
                logging.warning(f"profile_crud_tool: skipping {action} due to invalid/missing payload: {error}")
                yield Response(f"Skipping profile {action}: {error}")
                return

            # Upsert by user_id: try fetch, then insert/update
            user_id = profile_data["user_id"]
            existing_filter = build_filters_from_where(
                {"path": ["user_id"], "operator": "Equal", "valueString": user_id}
            )
            existing = collection.query.fetch_objects(filters=existing_filter, limit=1)

            if existing.objects:
                collection.data.update(
                    uuid=existing.objects[0].uuid,
                    properties=profile_data,
                )
                logging.info(f"profile_crud_tool: updated profile for user {user_id}")
            else:
                collection.data.insert(profile_data)
                logging.info(f"profile_crud_tool: created profile for user {user_id}")

            yield Result(
                name="profile",
                objects=[profile_data],
                metadata={"action": action, "user_id": user_id},
                payload_type="generic",
                display=True,
            )
            yield Response(f"Profile {action}d successfully for user {user_id}")

        else:  # read
            user_id = (
                profile_data.get("user_id")
                if isinstance(profile_data, dict)
                else kwargs.get("user_id")
            )
            if not user_id:
                yield Response("Skipping profile read: user_id is required")
                return

            result_filter = build_filters_from_where(
                {"path": ["user_id"], "operator": "Equal", "valueString": user_id}
            )
            result = collection.query.fetch_objects(filters=result_filter, limit=1)

            if not result.objects:
                yield Response(f"Profile not found for user {user_id}")
                return

            profile = result.objects[0].properties
            logging.info(f"profile_crud_tool: retrieved profile for user {user_id}")
            
            yield Result(
                name="profile",
                objects=[profile],
                metadata={"action": "read", "user_id": user_id},
                payload_type="generic",
                display=True,
            )
            yield Response(f"Profile read successfully for user {user_id}")

    except ValueError as e:
        error_msg = f"Invalid input: {str(e)}"
        logging.error(f"profile_crud_tool: {error_msg}", exc_info=True)
        yield Error(error_msg)
        return
    except Exception as e:
        error_msg = f"Profile operation ({action}) failed: {str(e)}"
        logging.error(f"profile_crud_tool: {error_msg}", exc_info=True)
        yield Error(error_msg)
        return


