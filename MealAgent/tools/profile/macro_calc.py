from typing import AsyncGenerator
import logging

from elysia.tree.objects import TreeData
from elysia.objects import Result, Error, Response
from elysia.util.client import ClientManager
from elysia import tool

from MealAgent.utils.nutrition import build_default_macro_targets, calculate_harris_benedict_tdee


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

    Environment interface:
    - Reads:
      - profile_crud_tool.profile (required; if absent, tool will skip)
    - Writes:
      - macro_calc_tool.targets: [{ tdee_kcal, protein_g, fat_g, carb_g, split }]

    Decision hints:
    - If macro_calc_tool.targets exists, planning/ranking tools can use them.
    - If profile missing, this tool emits a skip Response to prevent noisy errors.
    """
    logging.info(f"macro_calc_tool: start (protein_share={protein_share}, fat_share={fat_share}, carb_share={carb_share})")
    yield Response("Calculating nutritional targets...")

    try:
        results = tree_data.environment.find("profile_crud_tool", "profile")
        profile = results[0]["objects"][0] if results and results[0]["objects"] else None

        fallback_reason = None
        targets: dict[str, float] | None = None

        if profile:
            try:
                calorie_override = next(
                    (
                        profile.get(key)
                        for key in (
                            "target_calories",
                            "daily_calorie_target",
                            "calorie_target",
                            "tdee_kcal",
                        )
                        if profile.get(key) is not None
                    ),
                    None,
                )

                if calorie_override is not None:
                    tdee = float(calorie_override)
                else:
                    tdee = calculate_harris_benedict_tdee(
                        age=profile["age"],
                        gender=profile["gender"],
                        weight_kg=profile["weight_kg"],
                        height_cm=profile["height_cm"],
                        activity_level=profile["activity_level"],
                    )

                total = max(1e-6, float(protein_share) + float(fat_share) + float(carb_share))
                p_share = float(protein_share) / total
                f_share = float(fat_share) / total
                c_share = float(carb_share) / total

                protein_override = profile.get("protein_g")
                fat_override = profile.get("fat_g")
                carb_override = profile.get("carb_g")

                protein_g = (
                    float(protein_override)
                    if isinstance(protein_override, (int, float))
                    else (tdee * p_share) / 4.0
                )
                fat_g = (
                    float(fat_override)
                    if isinstance(fat_override, (int, float))
                    else (tdee * f_share) / 9.0
                )
                carb_g = (
                    float(carb_override)
                    if isinstance(carb_override, (int, float))
                    else (tdee * c_share) / 4.0
                )

                targets = {
                    "tdee_kcal": float(tdee),
                    "protein_g": float(protein_g),
                    "fat_g": float(fat_g),
                    "carb_g": float(carb_g),
                    "split": {"protein": p_share, "fat": f_share, "carb": c_share},
                }
            except (KeyError, ValueError, TypeError) as exc:
                logging.warning("macro_calc_tool: falling back to WHO defaults (%s)", exc)
                fallback_reason = "profile_missing_fields"

        if targets is None:
            targets = build_default_macro_targets()
            fallback_reason = fallback_reason or "profile_unavailable"

        summary_kcal = float(targets["tdee_kcal"])
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
                "No personalized profile available; using WHO baseline "
                f"{summary_kcal:.0f} kcal | {summary_protein:.0f}g P | {summary_fat:.0f}g F | {summary_carb:.0f}g C"
            )
        else:
            yield Response(
                f"Target: {summary_kcal:.0f} kcal | {summary_protein:.0f}g P | "
                f"{summary_fat:.0f}g F | {summary_carb:.0f}g C"
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


