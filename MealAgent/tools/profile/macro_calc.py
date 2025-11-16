from typing import AsyncGenerator
import logging

from elysia.tree.objects import TreeData
from elysia.objects import Result, Error, Response
from elysia.util.client import ClientManager
from elysia import tool

from MealAgent.utils.nutrition import calculate_harris_benedict_tdee


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
        if not results or not results[0]["objects"]:
            logging.info("macro_calc_tool: no profile in environment; skipping macro calc")
            yield Response("Skipping macro calculation: no profile available")
            return

        profile = results[0]["objects"][0]
        tdee = calculate_harris_benedict_tdee(
            age=profile["age"],
            gender=profile["gender"],
            weight_kg=profile["weight_kg"],
            height_cm=profile["height_cm"],
            activity_level=profile["activity_level"],
        )

        # Sanity normalize shares
        total = max(1e-6, float(protein_share) + float(fat_share) + float(carb_share))
        p_share = float(protein_share) / total
        f_share = float(fat_share) / total
        c_share = float(carb_share) / total

        protein_g = (tdee * p_share) / 4.0
        fat_g = (tdee * f_share) / 9.0
        carb_g = (tdee * c_share) / 4.0

        targets = {
            "tdee_kcal": float(tdee),
            "protein_g": float(protein_g),
            "fat_g": float(fat_g),
            "carb_g": float(carb_g),
            "split": {"protein": p_share, "fat": f_share, "carb": c_share},
        }

        logging.info(
            f"macro_calc_tool: complete (tdee={tdee:.0f} kcal, protein={protein_g:.0f}g, "
            f"fat={fat_g:.0f}g, carb={carb_g:.0f}g)"
        )
        
        yield Result(
            name="targets",
            objects=[targets],
            metadata={"calculated_from": profile.get("user_id")},
            payload_type="generic",
            display=True,
        )
        yield Response(f"Target: {tdee:.0f} kcal | {protein_g:.0f}g P | {fat_g:.0f}g F | {carb_g:.0f}g C")
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


