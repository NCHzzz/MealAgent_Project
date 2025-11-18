DEFAULT_DAILY_KCAL = 2000.0
DEFAULT_MACRO_SPLIT = {"protein": 0.30, "fat": 0.30, "carb": 0.40}


def calculate_harris_benedict_tdee(
    age: int,
    gender: str,
    weight_kg: float,
    height_cm: float,
    activity_level: str,
) -> float:
    """
    Calculate Total Daily Energy Expenditure (TDEE) using Harris-Benedict.

    Activity multipliers:
      - sedentary: 1.2
      - light: 1.375
      - moderate: 1.55
      - very_active: 1.725
      - extra_active: 1.9
    """
    gender_lower = (gender or "").lower()
    if gender_lower == "male":
        bmr = 88.362 + (13.397 * float(weight_kg)) + (4.799 * float(height_cm)) - (5.677 * int(age))
    else:
        bmr = 447.593 + (9.247 * float(weight_kg)) + (3.098 * float(height_cm)) - (4.330 * int(age))

    activity_multipliers = {
        "sedentary": 1.2,
        "light": 1.375,
        "moderate": 1.55,
        "very_active": 1.725,
        "extra_active": 1.9,
    }

    multiplier = activity_multipliers.get((activity_level or "").lower(), 1.2)
    return float(bmr) * float(multiplier)


def build_default_macro_targets(calorie_target: float | None = None) -> dict[str, float]:
    """
    Create a baseline macro target dictionary following WHO dietary guidance.

    Args:
        calorie_target: Optional override for kcal target (defaults to 2000 kcal).
    """

    kcal = float(calorie_target or DEFAULT_DAILY_KCAL)
    protein_g = (kcal * DEFAULT_MACRO_SPLIT["protein"]) / 4.0
    fat_g = (kcal * DEFAULT_MACRO_SPLIT["fat"]) / 9.0
    carb_g = (kcal * DEFAULT_MACRO_SPLIT["carb"]) / 4.0

    return {
        "tdee_kcal": kcal,
        "protein_g": float(protein_g),
        "fat_g": float(fat_g),
        "carb_g": float(carb_g),
        "split": DEFAULT_MACRO_SPLIT.copy(),
    }

