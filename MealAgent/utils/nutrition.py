DEFAULT_DAILY_KCAL = 2000.0
DEFAULT_MACRO_SPLIT = {"protein": 0.30, "fat": 0.30, "carb": 0.40}

# Goal-based TDEE adjustments
GOAL_TDEE_ADJUSTMENTS = {
    "weight_loss": {
        "slow": 0.90,  # -10% (sustainable, ~250 kcal deficit)
        "fast": 0.80,  # -20% (aggressive, ~500 kcal deficit)
        "default": 0.90,  # Use slow by default for safety
    },
    "weight_gain": {
        "lean": 1.10,  # +10% (lean bulk, ~250 kcal surplus)
        "fast": 1.20,  # +20% (dirty bulk, ~500 kcal surplus)
        "default": 1.10,  # Use lean by default
    },
    "muscle_gain": {
        "default": 1.10,  # +10% for muscle building
    },
    "gym": {  # Alias for muscle_gain
        "default": 1.10,
    },
    "maintenance": {
        "default": 1.0,  # No adjustment
    },
}

# Macro split by goal (Method 1: Percentage-based)
GOAL_MACRO_SPLITS = {
    "weight_loss": {
        "protein_share": 0.40,  # Higher protein to preserve muscle
        "fat_share": 0.40,
        "carb_share": 0.20,  # Low carb
    },
    "weight_gain": {
        "protein_share": 0.25,
        "fat_share": 0.30,
        "carb_share": 0.45,  # Higher carbs for energy
    },
    "muscle_gain": {
        "protein_share": 0.30,  # Will be overridden by weight-based calculation
        "fat_share": 0.25,
        "carb_share": 0.45,
    },
    "gym": {  # Alias for muscle_gain
        "protein_share": 0.30,  # Will be overridden by weight-based calculation
        "fat_share": 0.25,
        "carb_share": 0.45,
    },
    "maintenance": {
        "protein_share": 0.30,
        "fat_share": 0.35,
        "carb_share": 0.35,
    },
}


def calculate_mifflin_st_jeor_bmr(
    age: int,
    gender: str,
    weight_kg: float,
    height_cm: float,
) -> float:
    """
    Calculate Basal Metabolic Rate (BMR) using Mifflin-St Jeor equation.
    More accurate than Harris-Benedict for modern populations.
    
    Formula: BMR = (10 × W) + (6.25 × H) - (5 × A) + S
    Where:
      W: Weight (kg)
      H: Height (cm)
      A: Age (years)
      S: Gender constant (+5 for male, -161 for female)
    
    Args:
        age: Age in years
        gender: "male" or "female"
        weight_kg: Weight in kilograms
        height_cm: Height in centimeters
    
    Returns:
        BMR in kcal/day
    """
    W = float(weight_kg)
    H = float(height_cm)
    A = int(age)
    
    gender_lower = (gender or "").lower()
    if gender_lower == "male":
        S = 5
    else:
        S = -161
    
    bmr = (10 * W) + (6.25 * H) - (5 * A) + S
    return float(bmr)


def calculate_tdee(
    age: int,
    gender: str,
    weight_kg: float,
    height_cm: float,
    activity_level: str,
) -> float:
    """
    Calculate Total Daily Energy Expenditure (TDEE) using Mifflin-St Jeor BMR.
    
    TDEE = BMR × PAL (Physical Activity Level)
    
    Activity multipliers (PAL):
      - sedentary: 1.2 (Ít vận động, làm văn phòng)
      - light: 1.375 (Tập nhẹ 1-3 ngày/tuần)
      - moderate: 1.55 (Tập vừa phải 3-5 ngày/tuần)
      - very_active: 1.725 (Tập nặng 6-7 ngày/tuần)
      - extra_active: 1.9 (Vận động viên chuyên nghiệp)
    
    Args:
        age: Age in years
        gender: "male" or "female"
        weight_kg: Weight in kilograms
        height_cm: Height in centimeters
        activity_level: Activity level string
    
    Returns:
        TDEE in kcal/day
    """
    bmr = calculate_mifflin_st_jeor_bmr(age, gender, weight_kg, height_cm)
    
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


def adjust_targets_by_goal(
    tdee: float,
    goal: str | None = None,
    weight_kg: float | None = None,
    age: int | None = None,
    gender: str | None = None,
    height_cm: float | None = None,
    protein_override: float | None = None,
    fat_override: float | None = None,
    carb_override: float | None = None,
    use_weight_based_protein: bool = False,
) -> dict[str, float]:
    """
    Adjust TDEE and macro targets based on user goal.
    
    Workflow: Mifflin-St Jeor BMR → TDEE → Goal-adjusted Target Calories → Macros.
    
    Step 3: Target Calories = TDEE + Adjustment
      - weight_loss: TDEE - 10% (slow) or -20% (fast)
      - weight_gain: TDEE + 10% (lean) or +20% (fast)
      - muscle_gain/gym: TDEE + 10%
      - maintenance: TDEE (no change)
    
    Step 4: Macro Split
      Method 1 (Percentage-based): For weight_loss, weight_gain, maintenance
      Method 2 (Weight-based protein): For muscle_gain/gym (1.6-2.2g/kg protein)
    
    Args:
        tdee: Base TDEE calculated from Mifflin-St Jeor
        goal: User goal ("weight_loss", "weight_gain", "muscle_gain", "gym", "maintenance")
        weight_kg: User weight in kg (required for weight-based protein calculation)
        age: User age (for BMR safety check)
        gender: User gender (for BMR safety check)
        height_cm: User height (for BMR safety check)
        protein_override: Override protein target (g)
        fat_override: Override fat target (g)
        carb_override: Override carb target (g)
        use_weight_based_protein: If True, use Method 2 (protein by weight) for gym/muscle_gain
    
    Returns:
        Dictionary with adjusted tdee_kcal, protein_g, fat_g, carb_g (rounded)
    """
    goal_lower = (goal or "maintenance").lower()
    
    # Step 3: Adjust TDEE based on goal to get Target Calories
    tdee_adjustments = GOAL_TDEE_ADJUSTMENTS.get(goal_lower, GOAL_TDEE_ADJUSTMENTS["maintenance"])
    tdee_multiplier = tdee_adjustments.get("default", 1.0)
    target_calories = tdee * tdee_multiplier
    
    # Safety check: Ensure target calories >= BMR (metabolic health)
    if age and gender and height_cm and weight_kg:
        bmr = calculate_mifflin_st_jeor_bmr(age, gender, weight_kg, height_cm)
        if target_calories < bmr:
            target_calories = bmr
    
    # Step 4: Calculate macros
    # Method 2: Weight-based protein (for gym/muscle_gain) - Recommended for advanced systems
    if use_weight_based_protein and weight_kg and goal_lower in ("muscle_gain", "gym"):
        # Protein: 1.6-2.2g per kg body weight (use 2.0g as default, can be adjusted)
        protein_g = weight_kg * 2.0
        calo_protein = protein_g * 4.0  # 1g protein = 4 cal
        
        # Fat: 20-30% of total calories (use 25% for hormone maintenance)
        calo_fat = target_calories * 0.25
        fat_g = calo_fat / 9.0  # 1g fat = 9 cal
        
        # Carb: Remaining calories
        calo_carb = target_calories - calo_protein - calo_fat
        carb_g = calo_carb / 4.0  # 1g carb = 4 cal
        
        # Calculate actual percentages for reference
        protein_share = calo_protein / target_calories
        fat_share = calo_fat / target_calories
        carb_share = calo_carb / target_calories
    else:
        # Method 1: Percentage-based (default) - Easier to implement
        macro_splits = GOAL_MACRO_SPLITS.get(goal_lower, GOAL_MACRO_SPLITS["maintenance"])
        protein_share = macro_splits["protein_share"]
        fat_share = macro_splits["fat_share"]
        carb_share = macro_splits["carb_share"]
        
        # Calculate macros from percentages
        # Formula: Gram = (TargetCalories × Percentage) / Calories_per_gram
        protein_g = (target_calories * protein_share) / 4.0  # 1g protein = 4 cal
        fat_g = (target_calories * fat_share) / 9.0  # 1g fat = 9 cal
        carb_g = (target_calories * carb_share) / 4.0  # 1g carb = 4 cal
    
    # Apply overrides if provided
    if protein_override is not None:
        protein_g = float(protein_override)
    if fat_override is not None:
        fat_g = float(fat_override)
    if carb_override is not None:
        carb_g = float(carb_override)
    
    # Round values: TDEE to nearest integer, macros to 1 decimal place
    return {
        "tdee_kcal": round(target_calories),
        "protein_g": round(protein_g, 1),
        "fat_g": round(fat_g, 1),
        "carb_g": round(carb_g, 1),
        "split": {"protein": protein_share, "fat": fat_share, "carb": carb_share},
    }

