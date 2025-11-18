import datetime
from uuid import uuid4

import bcrypt
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, constr

from elysia.api.core.log import logger
from elysia.api.dependencies.common import get_user_manager
from elysia.api.services.user import UserManager
from elysia.util.client import ClientManager
from MealAgent.schemas.user_account import USER_ACCOUNT_SCHEMA
from MealAgent.tools.utils.weaviate_filters import build_filters_from_where


router = APIRouter()

_auth_client_manager: ClientManager | None = None


def _get_auth_client_manager() -> ClientManager:
    global _auth_client_manager
    if _auth_client_manager is None:
        _auth_client_manager = ClientManager(logger=logger)
    return _auth_client_manager


def _ensure_user_account_collection(client):
    collections = client.collections.list_all()
    if USER_ACCOUNT_SCHEMA["name"] not in collections:
        client.collections.create(
            name=USER_ACCOUNT_SCHEMA["name"],
            properties=USER_ACCOUNT_SCHEMA["properties"],
            vector_config=USER_ACCOUNT_SCHEMA.get("vector_config"),
            references=USER_ACCOUNT_SCHEMA.get("references"),
        )
    return client.collections.get(USER_ACCOUNT_SCHEMA["name"])


def _hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def _verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        return False


class AuthRequest(BaseModel):
    email: EmailStr
    password: constr(min_length=8)


class AuthResponse(BaseModel):
    error: str = ""
    user_id: str | None = None
    email: EmailStr | None = None


def _get_account_by_email(collection, email: str):
    filters = build_filters_from_where(
        {"path": ["email"], "operator": "Equal", "valueString": email}
    )
    return collection.query.fetch_objects(filters=filters, limit=1)


@router.post("/signup", response_model=AuthResponse)
async def signup_user(
    data: AuthRequest, user_manager: UserManager = Depends(get_user_manager)
):
    email = data.email.lower().strip()
    client_manager = _get_auth_client_manager()
    client = client_manager.get_client()
    collection = _ensure_user_account_collection(client)

    existing = _get_account_by_email(collection, email)
    if existing.objects:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email is already registered.",
        )

    user_id = str(uuid4())
    now = datetime.datetime.utcnow().isoformat()
    password_hash = _hash_password(data.password)

    collection.data.insert(
        {
            "user_id": user_id,
            "email": email,
            "password_hash": password_hash,
            "created_at": now,
            "last_login_at": now,
        }
    )

    await user_manager.add_user_local(user_id)

    logger.info("Created new user account %s", user_id)
    return AuthResponse(error="", user_id=user_id, email=email)


@router.post("/login", response_model=AuthResponse)
async def login_user(
    data: AuthRequest, user_manager: UserManager = Depends(get_user_manager)
):
    email = data.email.lower().strip()
    client_manager = _get_auth_client_manager()
    client = client_manager.get_client()
    collection = _ensure_user_account_collection(client)

    account = _get_account_by_email(collection, email)
    if not account.objects:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials."
        )

    account_obj = account.objects[0]
    props = account_obj.properties
    if not _verify_password(data.password, props.get("password_hash", "")):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials."
        )

    now = datetime.datetime.utcnow().isoformat()
    try:
        collection.data.update(
            uuid=account_obj.uuid,
            properties={"last_login_at": now},
        )
    except Exception as exc:
        logger.warning("Failed to update last_login_at for %s: %s", email, exc)

    user_id = props["user_id"]
    await user_manager.add_user_local(user_id)

    logger.info("User %s logged in successfully", user_id)
    return AuthResponse(error="", user_id=user_id, email=email)


