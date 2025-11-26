from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple
from uuid import uuid4
import secrets

import bcrypt
from fastapi import APIRouter, Depends, Header, HTTPException, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, EmailStr, Field
from weaviate.classes.query import Filter

from elysia.api.core.log import logger
from elysia.api.dependencies.common import get_user_manager
from elysia.api.services.user import UserManager
from elysia.util.client import ClientManager
from MealAgent.utils.nutrition import calculate_tdee, adjust_targets_by_goal


router = APIRouter()

_client_manager = ClientManager(logger=logger)
_SESSION_TTL = timedelta(hours=12)
_sessions: Dict[str, Dict[str, Any]] = {}


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    display_name: str = Field(min_length=1, max_length=80)
    age: Optional[int] = Field(None, ge=1, le=120)
    gender: Optional[str] = Field(None, max_length=32)
    weight_kg: Optional[float] = Field(None, ge=1, le=500)
    height_cm: Optional[float] = Field(None, ge=30, le=300)
    activity_level: Optional[str] = Field(
        None, pattern="^(sedentary|light|moderate|very_active|extra_active)$"
    )
    diet_type: Optional[str] = Field(None, max_length=64)
    allergens: Optional[list[str]] = None
    preferences: Optional[list[str]] = None
    max_cooking_time_min: Optional[int] = Field(None, ge=1, le=600)
    available_equipment: Optional[list[str]] = None


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class ProfileUpdateRequest(BaseModel):
    display_name: Optional[str] = Field(None, min_length=1, max_length=80)
    age: Optional[int] = Field(None, ge=1, le=120)
    gender: Optional[str] = Field(None, max_length=32)
    weight_kg: Optional[float] = Field(None, ge=1, le=500)
    height_cm: Optional[float] = Field(None, ge=30, le=300)
    activity_level: Optional[str] = Field(
        None, pattern="^(sedentary|light|moderate|very_active|extra_active)$"
    )
    diet_type: Optional[str] = Field(None, max_length=64)
    goal: Optional[str] = Field(
        None, pattern="^(weight_loss|weight_gain|muscle_gain|gym|maintenance)$"
    )
    allergens: Optional[list[str]] = None
    preferences: Optional[list[str]] = None
    max_cooking_time_min: Optional[int] = Field(None, ge=1, le=600)
    available_equipment: Optional[list[str]] = None


def _hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def _verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))
    except ValueError:
        return False


def _issue_token(user_id: str) -> str:
    token = secrets.token_urlsafe(32)
    _sessions[token] = {
        "user_id": user_id,
        "expires_at": datetime.now(timezone.utc) + _SESSION_TTL,
    }
    return token


def _validate_token(authorization: Optional[str]) -> Tuple[str, str]:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing token")
    token = authorization.split(" ", 1)[1].strip()
    session = _sessions.get(token)
    if not session:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    if session["expires_at"] < datetime.now(timezone.utc):
        del _sessions[token]
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired")
    return session["user_id"], token


async def _fetch_user_by_email(client, email: str) -> Tuple[Optional[str], Optional[dict]]:
    collection = client.collections.get("UserProfile")
    response = await collection.query.fetch_objects(
        filters=Filter.by_property("email").equal(email), limit=1
    )
    if response.objects:
        obj = response.objects[0]
        return obj.uuid, obj.properties  # type: ignore[attr-defined]
    return None, None


async def _fetch_user_by_id(client, user_id: str) -> Tuple[Optional[str], Optional[dict]]:
    collection = client.collections.get("UserProfile")
    response = await collection.query.fetch_objects(
        filters=Filter.by_property("user_id").equal(user_id), limit=1
    )
    if response.objects:
        obj = response.objects[0]
        return obj.uuid, obj.properties  # type: ignore[attr-defined]
    return None, None


def _to_iso(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _serialise_profile(properties: Optional[dict]) -> dict:
    if not properties:
        return {}
    return {
        "user_id": properties.get("user_id"),
        "email": properties.get("email"),
        "display_name": properties.get("display_name"),
        "age": properties.get("age"),
        "gender": properties.get("gender"),
        "weight_kg": properties.get("weight_kg"),
        "height_cm": properties.get("height_cm"),
        "activity_level": properties.get("activity_level"),
        "diet_type": properties.get("diet_type"),
        "allergens": properties.get("allergens") or [],
        "preferences": properties.get("preferences") or [],
        "max_cooking_time_min": properties.get("max_cooking_time_min"),
        "available_equipment": properties.get("available_equipment") or [],
        "created_at": _to_iso(properties.get("created_at")),
        "updated_at": _to_iso(properties.get("updated_at")),
    }


@router.post("/register")
async def register_user(payload: RegisterRequest, user_manager: UserManager = Depends(get_user_manager)):
    email = payload.email.lower()

    async with _client_manager.connect_to_async_client() as client:
        collection = client.collections.get("UserProfile")
        existing_uuid, _ = await _fetch_user_by_email(client, email)
        if existing_uuid:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Email already registered",
            )

        user_id = str(uuid4())
        now = datetime.now(timezone.utc).isoformat()
        properties = {
            "user_id": user_id,
            "email": email,
            "display_name": payload.display_name,
            "password_hash": _hash_password(payload.password),
            "age": payload.age,
            "gender": payload.gender,
            "weight_kg": payload.weight_kg,
            "height_cm": payload.height_cm,
            "activity_level": payload.activity_level,
            "diet_type": payload.diet_type,
            "allergens": payload.allergens or [],
            "preferences": payload.preferences or [],
            "max_cooking_time_min": payload.max_cooking_time_min,
            "available_equipment": payload.available_equipment or [],
            "created_at": now,
            "updated_at": now,
        }
        try:
            await collection.data.insert(properties=properties)
        except Exception as exc:
            logger.exception("Failed to create user profile")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=str(exc),
            ) from exc

    token = _issue_token(user_id)
    # Warm up user manager state for the new user
    try:
        await user_manager.add_user_local(user_id)
    except Exception as exc:
        logger.debug("Unable to pre-load user (%s)", exc)

    return JSONResponse(
        content={
            "error": "",
            "user_id": user_id,
            "email": email,
            "display_name": payload.display_name,
            "token": token,
            "profile": _serialise_profile(properties),
        }
    )


@router.post("/login")
async def login_user(payload: LoginRequest):
    email = payload.email.lower()
    async with _client_manager.connect_to_async_client() as client:
        _, properties = await _fetch_user_by_email(client, email)
        if not properties:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
        stored_hash = properties.get("password_hash")
        if not stored_hash or not _verify_password(payload.password, stored_hash):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    token = _issue_token(properties["user_id"])
    return JSONResponse(
        content={
            "error": "",
            "user_id": properties["user_id"],
            "email": email,
            "display_name": properties.get("display_name"),
            "token": token,
            "profile": _serialise_profile(properties),
        }
    )


@router.post("/logout")
async def logout_user(authorization: Optional[str] = Header(default=None)):
    _, token = _validate_token(authorization)
    _sessions.pop(token, None)
    return JSONResponse(content={"error": ""})


@router.get("/profile")
async def get_profile(authorization: Optional[str] = Header(default=None)):
    user_id, _ = _validate_token(authorization)
    async with _client_manager.connect_to_async_client() as client:
        _, properties = await _fetch_user_by_id(client, user_id)
        if not properties:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found")
    return JSONResponse(content={"error": "", "profile": _serialise_profile(properties)})


@router.put("/profile")
async def update_profile(
    payload: ProfileUpdateRequest,
    authorization: Optional[str] = Header(default=None),
):
    user_id, _ = _validate_token(authorization)
    updates = {k: v for k, v in payload.model_dump().items() if v is not None}
    if not updates:
        return JSONResponse(content={"error": "", "profile": {}})

    updates["updated_at"] = datetime.now(timezone.utc).isoformat()

    async with _client_manager.connect_to_async_client() as client:
        collection = client.collections.get("UserProfile")
        uuid, existing = await _fetch_user_by_id(client, user_id)
        if not uuid or not existing:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found")

        # Merge updates with existing profile for calculation
        merged_profile = {**existing, **updates}
        
        # Auto-recalculate TDEE and macros if relevant fields changed
        fields_affecting_calculation = {"age", "gender", "weight_kg", "height_cm", "activity_level", "goal"}
        if any(field in updates for field in fields_affecting_calculation):
            try:
                # Check if we have all required fields for calculation
                required_fields = ["age", "gender", "weight_kg", "height_cm", "activity_level"]
                if all(
                    merged_profile.get(field) is not None 
                    and (isinstance(merged_profile.get(field), (int, float)) or isinstance(merged_profile.get(field), str))
                    for field in required_fields
                ):
                    # Calculate base TDEE using Mifflin-St Jeor
                    calorie_override = merged_profile.get("tdee_kcal") or merged_profile.get("target_calories")
                    if calorie_override is not None:
                        base_tdee = float(calorie_override)
                    else:
                        base_tdee = calculate_tdee(
                            age=int(merged_profile["age"]),
                            gender=str(merged_profile["gender"]),
                            weight_kg=float(merged_profile["weight_kg"]),
                            height_cm=float(merged_profile["height_cm"]),
                            activity_level=str(merged_profile["activity_level"]),
                        )
                    
                    # Get goal and weight from merged profile
                    goal = merged_profile.get("goal")
                    weight_kg = merged_profile.get("weight_kg")
                    
                    # Use weight-based protein for gym/muscle_gain goals
                    use_weight_based = goal and goal.lower() in ("muscle_gain", "gym")
                    
                    # Get macro overrides
                    protein_override = merged_profile.get("protein_g")
                    fat_override = merged_profile.get("fat_g")
                    carb_override = merged_profile.get("carb_g")
                    
                    # Adjust targets by goal (includes rounding)
                    adjusted_targets = adjust_targets_by_goal(
                        tdee=base_tdee,
                        goal=goal,
                        weight_kg=float(weight_kg) if isinstance(weight_kg, (int, float)) else None,
                        age=int(merged_profile["age"]) if merged_profile.get("age") else None,
                        gender=str(merged_profile["gender"]) if merged_profile.get("gender") else None,
                        height_cm=float(merged_profile["height_cm"]) if merged_profile.get("height_cm") else None,
                        protein_override=float(protein_override) if isinstance(protein_override, (int, float)) else None,
                        fat_override=float(fat_override) if isinstance(fat_override, (int, float)) else None,
                        carb_override=float(carb_override) if isinstance(carb_override, (int, float)) else None,
                        use_weight_based_protein=use_weight_based,
                    )
                    
                    # Add calculated values to updates (already rounded)
                    updates["tdee_kcal"] = adjusted_targets["tdee_kcal"]
                    updates["protein_g"] = adjusted_targets["protein_g"]
                    updates["fat_g"] = adjusted_targets["fat_g"]
                    updates["carb_g"] = adjusted_targets["carb_g"]
                    
                    goal_str = f" (goal: {goal})" if goal else ""
                    logger.info(
                        f"Auto-calculated nutritional targets for user {user_id}{goal_str}: "
                        f"TDEE={adjusted_targets['tdee_kcal']} kcal, "
                        f"Protein={adjusted_targets['protein_g']}g, "
                        f"Fat={adjusted_targets['fat_g']}g, "
                        f"Carb={adjusted_targets['carb_g']}g"
                    )
                else:
                    logger.warning(
                        f"Cannot calculate nutritional targets for user {user_id}: "
                        f"Missing required fields. Required: {required_fields}"
                    )
            except (ValueError, TypeError, KeyError) as calc_exc:
                logger.warning(
                    f"Failed to auto-calculate nutritional targets for user {user_id}: {str(calc_exc)}"
                )
                # Continue with update even if calculation fails

        try:
            await collection.data.update(uuid=uuid, properties=updates)
        except Exception as exc:
            logger.exception("Failed to update profile")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=str(exc),
            ) from exc

        existing.update(updates)

    return JSONResponse(
        content={
            "error": "",
            "profile": _serialise_profile(existing),
        }
    )

