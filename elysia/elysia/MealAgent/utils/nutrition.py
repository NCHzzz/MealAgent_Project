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


