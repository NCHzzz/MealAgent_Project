from typing import AsyncGenerator
import logging

from elysia.tree.objects import TreeData
from elysia.objects import Result, Error, Response
from elysia.util.client import ClientManager
from elysia import tool

from MealAgent.utils.nutrition import (
    build_default_macro_targets,
    calculate_tdee,
    adjust_targets_by_goal,
)
from MealAgent.tools.utils.weaviate_filters import build_filters_from_where


def _safe_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_int(value):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


@tool
async def macro_calc_tool(
    tree_data: TreeData,
    client_manager: ClientManager,  # kept for consistent signature
    protein_share: float = 0.30,
    fat_share: float = 0.30,
    carb_share: float = 0.40,
    **kwargs,
) -> AsyncGenerator[Result | Response | Error, None]:
    """
    Calculate TDEE and macro targets (default 30/30/40 split).

    Environment contract:
      Reads – `profile_crud_tool.profile` (skips gracefully if missing).
      Writes – `macro_calc_tool.targets` (single source of truth for downstream tools).

    Decision hints:
      • If `targets` exists, search/planning tools may proceed; otherwise re-run profile onboarding.
      • Responses explicitly flag when defaults are used so the agent can prompt the user.
    """
    logging.info(f"macro_calc_tool: start (protein_share={protein_share}, fat_share={fat_share}, carb_share={carb_share})")
    yield Response("📊 Calculating your nutritional targets (TDEE & macros)...")

    try:
        # Always use the **latest** profile snapshot from the environment.
        # environment.find returns a history of Results; index 0 may be a stale
        # version from earlier in the conversation (without updated macros).
        results = tree_data.environment.find("profile_crud_tool", "profile")
        profile = None
        if results:
            for entry in reversed(results):
                objs = entry.get("objects") or []
                if objs:
                    profile = objs[0]
                    break

        # Hard refresh from Weaviate to ensure we see the most recent macros
        # embedded in UserProfile (tdee_kcal, protein_g, fat_g, carb_g).
        try:
            user_id = None
            if isinstance(profile, dict):
                user_id = profile.get("user_id")
            # Fallback to hidden_environment if user_id not present on profile
            if not user_id:
                hidden_env = getattr(tree_data.environment, "hidden_environment", {})
                user_id = hidden_env.get("user_id")

            if user_id:
                client = client_manager.get_client()
                collection = client.collections.get("UserProfile")
                user_filter = build_filters_from_where(
                    {"path": ["user_id"], "operator": "Equal", "valueString": str(user_id)}
                )
                fresh = collection.query.fetch_objects(filters=user_filter, limit=1)
                if fresh.objects:
                    profile = fresh.objects[0].properties
        except Exception:
            # If refresh fails, continue with whatever profile we already have.
            logging.debug("macro_calc_tool: failed to hard-refresh profile from Weaviate", exc_info=True)

        fallback_reason = None
        targets: dict[str, float] | None = None

        if profile:
            try:
                # 1) Prefer pre-computed targets embedded in UserProfile if available.
                #    This keeps the planning agent in sync with the values shown in the
                #    `/auth/profile` API and frontend Profile page.
                existing_tdee = _safe_float(profile.get("tdee_kcal"))
                existing_protein = _safe_float(profile.get("protein_g"))
                existing_fat = _safe_float(profile.get("fat_g"))
                existing_carb = _safe_float(profile.get("carb_g"))

                if all(v is not None for v in (existing_tdee, existing_protein, existing_fat, existing_carb)):
                    cal_protein = existing_protein * 4.0
                    cal_fat = existing_fat * 9.0
                    cal_carb = existing_carb * 4.0
                    total_calo = cal_protein + cal_fat + cal_carb
                    if total_calo <= 0 and existing_tdee:
                        total_calo = float(existing_tdee)
                    if total_calo <= 0:
                        total_calo = 1.0  # safety fallback

                    targets = {
                        "tdee_kcal": float(existing_tdee),
                        "protein_g": float(existing_protein),
                        "fat_g": float(existing_fat),
                        "carb_g": float(existing_carb),
                        "split": {
                            "protein": cal_protein / total_calo,
                            "fat": cal_fat / total_calo,
                            "carb": cal_carb / total_calo,
                        },
                    }
                    logging.debug(
                        "macro_calc_tool: using existing profile targets tdee=%s protein=%s fat=%s carb=%s",
                        existing_tdee,
                        existing_protein,
                        existing_fat,
                        existing_carb,
                    )
                else:
                    # 2) Otherwise, derive targets from profile fields.
                    calorie_override = next(
                        (
                            profile.get(key)
                            for key in (
                                "target_calories",
                                "daily_calorie_target",
                                "calorie_target",
                            )
                            if profile.get(key) is not None
                        ),
                        None,
                    )

                    if calorie_override is not None:
                        base_tdee = float(calorie_override)
                    else:
                        age_val = _safe_int(profile.get("age"))
                        gender_val = str(profile.get("gender")) if profile.get("gender") else None
                        weight_val = _safe_float(profile.get("weight_kg"))
                        height_val = _safe_float(profile.get("height_cm"))
                        activity_level = profile.get("activity_level")

                        if None in (age_val, gender_val, weight_val, height_val) or not activity_level:
                            raise ValueError("Profile missing required fields for TDEE calculation")

                        # Use Mifflin-St Jeor for more accurate calculation
                        base_tdee = calculate_tdee(
                            age=age_val,
                            gender=gender_val,
                            weight_kg=weight_val,
                            height_cm=height_val,
                            activity_level=activity_level,
                        )

                    # Get goal and timeline from profile
                    goal = profile.get("goal")
                    goal_lower = goal.lower() if isinstance(goal, str) else None
                    weight_val = _safe_float(profile.get("weight_kg"))
                    height_val = _safe_float(profile.get("height_cm"))
                    age_val = _safe_int(profile.get("age"))
                    gender_val = str(profile.get("gender")) if profile.get("gender") else None
                    timeline_months = profile.get("timeline_months")
                    # Default to 3 months if not specified
                    if timeline_months is None:
                        timeline_months = 3
                    else:
                        timeline_months = int(timeline_months)
                    
                    # Use weight-based protein for gym/muscle_gain goals
                    use_weight_based = bool(goal_lower in ("muscle_gain", "gym") and weight_val)
                    
                    # Get macro overrides (if user ever explicitly overrides)
                    protein_override = _safe_float(profile.get("protein_g"))
                    fat_override = _safe_float(profile.get("fat_g"))
                    carb_override = _safe_float(profile.get("carb_g"))
                    
                    # Adjust targets by goal (includes rounding)
                    targets = adjust_targets_by_goal(
                        tdee=base_tdee,
                        goal=goal,
                        weight_kg=weight_val,
                        age=age_val,
                        gender=gender_val,
                        height_cm=height_val,
                        protein_override=protein_override,
                        fat_override=fat_override,
                        carb_override=carb_override,
                        use_weight_based_protein=use_weight_based,
                        timeline_months=timeline_months,
                    )
                    logging.debug(
                        "macro_calc_tool: derived targets tdee=%.1f protein=%.1f fat=%.1f carb=%.1f (goal=%s overrides=%s/%s/%s)",
                        targets.get("tdee_kcal"),
                        targets.get("protein_g"),
                        targets.get("fat_g"),
                        targets.get("carb_g"),
                        goal,
                        protein_override,
                        fat_override,
                        carb_override,
                    )
            except (KeyError, ValueError, TypeError) as exc:
                logging.warning("macro_calc_tool: falling back to WHO defaults (%s)", exc)
                fallback_reason = "profile_missing_fields"

        if targets is None:
            default_targets = build_default_macro_targets()
            # Round default targets
            targets = {
                "tdee_kcal": round(default_targets["tdee_kcal"]),
                "protein_g": round(default_targets["protein_g"], 1),
                "fat_g": round(default_targets["fat_g"], 1),
                "carb_g": round(default_targets["carb_g"], 1),
                "split": default_targets["split"],
            }
            fallback_reason = fallback_reason or "profile_unavailable"

        summary_kcal = int(targets["tdee_kcal"])
        summary_protein = float(targets["protein_g"])
        summary_fat = float(targets["fat_g"])
        summary_carb = float(targets["carb_g"])

        logging.info(
            "macro_calc_tool: complete (tdee=%s kcal, protein=%s g, fat=%s g, carb=%s g)",
            f"{summary_kcal:.0f}",
            f"{summary_protein:.0f}",
            f"{summary_fat:.0f}",
            f"{summary_carb:.0f}",
        )

        yield Result(
            name="targets",
            objects=[targets],
            metadata={
                "calculated_from": profile.get("user_id") if profile else "default",
                "fallback_reason": fallback_reason,
            },
            payload_type="generic",
            display=True,
        )

        if fallback_reason:
            yield Response(
                f"📊 Using default targets: {summary_kcal:.0f} kcal | "
                f"{summary_protein:.0f}g protein | {summary_fat:.0f}g fat | {summary_carb:.0f}g carbs "
                "(create profile for personalized targets)"
            )
        else:
            yield Response(
                f"✅ Your targets: {summary_kcal:.0f} kcal | "
                f"{summary_protein:.0f}g protein | {summary_fat:.0f}g fat | {summary_carb:.0f}g carbs"
            )
    except ValueError as e:
        error_msg = f"Invalid input: {str(e)}"
        logging.error(f"macro_calc_tool: {error_msg}", exc_info=True)
        yield Error(error_msg)
        return
    except Exception as e:
        error_msg = f"Macro calculation failed: {str(e)}"
        logging.error(f"macro_calc_tool: {error_msg}", exc_info=True)
        yield Error(error_msg)
        return


