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


def _first_environment_object(results: Any) -> dict | None:
    """Return the first dict object from Environment.find-compatible results."""
    if not results:
        return None

    first_result = results[0]
    if isinstance(first_result, dict):
        objects = first_result.get("objects")
    else:
        objects = getattr(first_result, "objects", None)

    if isinstance(objects, list) and objects and isinstance(objects[0], dict):
        return objects[0]
    return None


def resolve_user_id(tree_data: TreeData, explicit_user_id: str | None = None) -> str | None:
    """
    Resolve user_id from (priority):
      1) Explicit argument passed into the tool
      2) Hidden environment (set by build_meal_agent_tree or previous tools)

    Extra logging is added here to help debug cases where user_id is unexpectedly None.
    """
    hidden = _hidden_env(tree_data)

    # Normalise explicit_user_id: sometimes the agent passes the literal string "None"
    # or other placeholder values. Treat these as "no explicit user" so we can fall
    # back to the hidden environment user_id set at tree creation.
    normalized_explicit: str | None = explicit_user_id
    if isinstance(explicit_user_id, str):
        if explicit_user_id.strip().lower() in {"", "none", "null", "undefined"}:
            normalized_explicit = None

    if normalized_explicit:
        logger.debug(
            "resolve_user_id: using explicit user_id='%s' (overrides hidden_environment)",
            normalized_explicit,
        )
        hidden["user_id"] = normalized_explicit
        return normalized_explicit

    resolved = hidden.get("user_id")
    if resolved:
        logger.debug(
            "resolve_user_id: resolved from hidden_environment user_id='%s'", resolved
        )
    else:
        logger.debug(
            "resolve_user_id: no user_id found (explicit=None, hidden keys=%s)",
            list(hidden.keys()),
        )
    return resolved


async def ensure_profile_loaded(
    tree_data: TreeData,
    client_manager: ClientManager,
    user_id: str | None = None,
    base_lm=None,
    complex_lm=None,
    force_refresh: bool = False,
    **kwargs,
) -> Tuple[dict | None, bool]:
    """
    Make sure profile_crud_tool.profile exists and is fresh from Weaviate.
    
    IMPORTANT: This function reads from Weaviate UserProfile collection, not just Environment.
    Environment may contain stale data, so we always refresh from Weaviate when needed.

    Returns:
        (profile_dict | None, bool loaded_now)
    """
    hidden = _hidden_env(tree_data)
    
    # If force_refresh, skip cache and Environment
    if not force_refresh:
        profile_results = tree_data.environment.find("profile_crud_tool", "profile")
        profile = _first_environment_object(profile_results)
        if profile is not None:
            # Still refresh from Weaviate to ensure we have latest data
            # (Environment may be stale if profile was updated elsewhere)
            resolved_user = profile.get("user_id") or resolve_user_id(tree_data, user_id)
            if not resolved_user:
                hidden["profile"] = profile
                return profile, False
            if resolved_user:
                try:
                    client = client_manager.get_client()
                    collection = client.collections.get("UserProfile")
                    from MealAgent.tools.utils.weaviate_filters import build_filters_from_where
                    profile_filter = build_filters_from_where(
                        {"path": ["user_id"], "operator": "Equal", "valueString": str(resolved_user)}
                    )
                    fresh_results = collection.query.fetch_objects(filters=profile_filter, limit=1)
                    fresh_objects = getattr(fresh_results, "objects", None)
                    if isinstance(fresh_objects, list) and fresh_objects:
                        fresh_profile = getattr(fresh_objects[0], "properties", None)
                        if isinstance(fresh_profile, dict):
                            hidden["profile"] = fresh_profile
                            return fresh_profile, False
                except Exception as refresh_exc:
                    logger.debug("Failed to refresh profile from Weaviate, using Environment data: %s", refresh_exc)
            # Fallback to Environment data when refresh fails or a mocked/empty
            # client does not return a real dict-shaped Weaviate object.
            hidden["profile"] = profile
            return profile, False

    resolved_user = resolve_user_id(tree_data, user_id)
    if not resolved_user:
        logger.debug(
            "ensure_profile_loaded: user_id not resolved (explicit=%r, hidden_keys=%s)",
            user_id,
            list(hidden.keys()),
        )
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
                # profile_crud_tool already reads from Weaviate, so this is fresh
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
    force_refresh: bool = False,
    **kwargs,
) -> Tuple[dict | None, bool]:
    """
    Ensure macro_calc_tool.targets exists and is fresh.
    
    IMPORTANT: macro_calc_tool already refreshes profile from Weaviate (line 67-86),
    so targets calculated from fresh profile will be accurate.
    
    Returns:
        (targets_dict | None, bool recalculated_now)
    """
    hidden = _hidden_env(tree_data)
    
    # If force_refresh, skip cache and Environment
    if not force_refresh:
        target_results = tree_data.environment.find("macro_calc_tool", "targets")
        if target_results and target_results[0]["objects"]:
            targets = target_results[0]["objects"][0]
            # Note: macro_calc_tool already does hard refresh from Weaviate (line 67-86),
            # so if targets exist in Environment, they should be relatively fresh.
            # However, if profile was updated after targets were calculated, we should recalculate.
            hidden["macro_targets"] = targets
            return targets, False

    profile, profile_loaded = await ensure_profile_loaded(
        tree_data,
        client_manager,
        user_id=user_id,
        base_lm=base_lm,
        complex_lm=complex_lm,
        force_refresh=force_refresh,
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
                # macro_calc_tool already reads fresh profile from Weaviate, so targets are accurate
                hidden["macro_targets"] = targets_obj
                return targets_obj, True
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("Exception while auto-calculating targets for user %s: %s", user_id, exc)
    return None, profile_loaded

