from __future__ import annotations

import logging
from typing import Any, Tuple

from elysia.tree.objects import TreeData
from elysia.util.client import ClientManager
from elysia.objects import Result, Error

from MealAgent.tools.profile.profile_crud import profile_crud_tool
from MealAgent.tools.profile.macro_calc import macro_calc_tool

logger = logging.getLogger(__name__)


def _hidden_env(tree_data: TreeData) -> dict:
    return getattr(tree_data.environment, "hidden_environment", {})


def resolve_user_id(tree_data: TreeData, explicit_user_id: str | None = None) -> str | None:
    hidden = _hidden_env(tree_data)
    if explicit_user_id:
        hidden["user_id"] = explicit_user_id
        return explicit_user_id
    return hidden.get("user_id")


async def ensure_profile_loaded(
    tree_data: TreeData,
    client_manager: ClientManager,
    user_id: str | None = None,
    base_lm=None,
    complex_lm=None,
    **kwargs,
) -> Tuple[dict | None, bool]:
    """
    Make sure profile_crud_tool.profile exists in the environment.

    Returns:
        (profile_dict | None, bool loaded_now)
    """
    hidden = _hidden_env(tree_data)
    cached_profile = hidden.get("profile")
    if cached_profile:
        return cached_profile, False

    profile_results = tree_data.environment.find("profile_crud_tool", "profile")
    if profile_results and profile_results[0]["objects"]:
        profile = profile_results[0]["objects"][0]
        hidden["profile"] = profile
        return profile, False

    resolved_user = resolve_user_id(tree_data, user_id)
    if not resolved_user:
        return None, False

    try:
        async for result in profile_crud_tool(
            tree_data=tree_data,
            inputs={},
            base_lm=base_lm,
            complex_lm=complex_lm,
            client_manager=client_manager,
            action="read",
            profile_data={"user_id": resolved_user},
            **kwargs,
        ):
            if isinstance(result, Error):
                logger.warning("Failed to auto-load profile for user %s: %s", resolved_user, result.message)
                return None, False
            if isinstance(result, Result) and result.objects:
                profile_obj = result.objects[0]
                hidden["profile"] = profile_obj
                return profile_obj, True
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("Exception while auto-loading profile for user %s: %s", resolved_user, exc)
    return None, False


async def ensure_macro_targets(
    tree_data: TreeData,
    client_manager: ClientManager,
    user_id: str | None = None,
    base_lm=None,
    complex_lm=None,
    **kwargs,
) -> Tuple[dict | None, bool]:
    """
    Ensure macro_calc_tool.targets exists. Returns (targets, recalculated_now).
    """
    hidden = _hidden_env(tree_data)
    cached_targets = hidden.get("macro_targets")
    if cached_targets:
        return cached_targets, False

    target_results = tree_data.environment.find("macro_calc_tool", "targets")
    if target_results and target_results[0]["objects"]:
        targets = target_results[0]["objects"][0]
        hidden["macro_targets"] = targets
        return targets, False

    profile, profile_loaded = await ensure_profile_loaded(
        tree_data,
        client_manager,
        user_id=user_id,
        base_lm=base_lm,
        complex_lm=complex_lm,
        **kwargs,
    )
    if not profile:
        return None, False

    try:
        async for result in macro_calc_tool(
            tree_data=tree_data,
            inputs={},
            base_lm=base_lm,
            complex_lm=complex_lm,
            client_manager=client_manager,
            **kwargs,
        ):
            if isinstance(result, Error):
                logger.warning("Failed to auto-calculate targets for user %s: %s", user_id, result.message)
                return None, profile_loaded
            if isinstance(result, Result) and result.objects:
                targets_obj = result.objects[0]
                hidden["macro_targets"] = targets_obj
                return targets_obj, True
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("Exception while auto-calculating targets for user %s: %s", user_id, exc)
    return None, profile_loaded

