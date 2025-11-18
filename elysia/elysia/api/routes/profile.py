import datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from elysia.api.core.log import logger
from elysia.api.dependencies.common import get_user_manager
from elysia.api.services.user import UserManager
from MealAgent.tools.profile.profile_crud import _validate_profile_payload
from MealAgent.tools.utils.weaviate_filters import build_filters_from_where


router = APIRouter()


class ProfileUpsertRequest(BaseModel):
    profile: dict[str, Any]


class ProfileResponse(BaseModel):
    error: str = ""
    profile: Optional[dict[str, Any]] = None


async def _ensure_user(
    user_id: str, user_manager: UserManager
) -> dict[str, Any]:
    if not user_manager.user_exists(user_id):
        await user_manager.add_user_local(user_id)
    return await user_manager.get_user_local(user_id)


def _get_profile(collection, user_id: str):
    filters = build_filters_from_where(
        {"path": ["user_id"], "operator": "Equal", "valueString": user_id}
    )
    return collection.query.fetch_objects(filters=filters, limit=1)


def _serialize_profile(obj) -> dict[str, Any]:
    if not obj:
        return {}
    props = dict(obj.properties)
    props["user_id"] = props.get("user_id")
    return props


@router.get("/{user_id}", response_model=ProfileResponse)
async def get_profile(
    user_id: str, user_manager: UserManager = Depends(get_user_manager)
):
    user = await _ensure_user(user_id, user_manager)
    client = user["client_manager"].get_client()
    collection = client.collections.get("UserProfile")

    result = _get_profile(collection, user_id)
    if not result.objects:
        return ProfileResponse(error="", profile=None)

    return ProfileResponse(error="", profile=_serialize_profile(result.objects[0]))


@router.post("/{user_id}", response_model=ProfileResponse)
async def upsert_profile(
    user_id: str,
    request: ProfileUpsertRequest,
    user_manager: UserManager = Depends(get_user_manager),
):
    if not isinstance(request.profile, dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="profile must be an object",
        )

    profile = dict(request.profile)
    profile["user_id"] = user_id

    error = _validate_profile_payload(profile)
    if error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=error,
        )

    user = await _ensure_user(user_id, user_manager)
    client = user["client_manager"].get_client()
    collection = client.collections.get("UserProfile")

    now = datetime.datetime.utcnow().isoformat()
    existing = _get_profile(collection, user_id)

    if existing.objects:
        existing_props = dict(existing.objects[0].properties)
        profile.setdefault("created_at", existing_props.get("created_at"))
        profile["updated_at"] = now
        collection.data.update(
            uuid=existing.objects[0].uuid,
            properties=profile,
        )
        logger.info("Updated profile for user %s", user_id)
    else:
        profile["created_at"] = now
        profile["updated_at"] = now
        collection.data.insert(profile)
        logger.info("Created profile for user %s", user_id)

    return ProfileResponse(error="", profile=profile)


