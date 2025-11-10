from typing import AsyncGenerator

from elysia.tree.objects import TreeData
from elysia.objects import Result, Error
from elysia.util.client import ClientManager
from elysia import tool

from elysia.MealAgent.utils.nutrition import calculate_harris_benedict_tdee


@tool
async def macro_calc_tool(
    tree_data: TreeData,
    client_manager: ClientManager,  # kept for consistent signature
    protein_share: float = 0.30,
    fat_share: float = 0.30,
    carb_share: float = 0.40,
    **kwargs,
) -> AsyncGenerator[Result | str | Error, None]:
    """
    Calculate TDEE and macro targets (default 30/30/40 split).

    Environment reads:
      - environment["profile_crud_tool"]["profile"]
    Environment writes:
      - environment["macro_calc_tool"]["targets"]
    """
    yield "Calculating nutritional targets..."

    results = tree_data.environment.find("profile_crud_tool", "profile")
    if not results or not results[0].objects:
        yield Error("Profile not found in environment. Run profile_crud_tool first.")
        return

    profile = results[0].objects[0]

    try:
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

        yield Result(name="targets", objects=[targets], metadata={"calculated_from": profile.get("user_id")})
        yield (
            f"Target: {tdee:.0f} kcal | {protein_g:.0f}g P | {fat_g:.0f}g F | {carb_g:.0f}g C"
        )
    except Exception as e:
        yield Error(f"Macro calculation failed: {str(e)}")
        return


