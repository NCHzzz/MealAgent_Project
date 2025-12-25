"""
Test user profiles for evaluation.

Cung cấp các user profiles mẫu với các mục tiêu dinh dưỡng khác nhau
để test MealAgent.
"""

from typing import List, Dict, Any


def get_test_profiles() -> List[Dict[str, Any]]:
    """
    Lấy danh sách test user profiles.
    
    Returns:
        List of user profile dictionaries
    """
    profiles = [
        {
            "user_id": "test_user_1",
            "age": 30,
            "gender": "male",
            "weight_kg": 75.0,
            "height_cm": 175.0,
            "activity_level": "moderate",
            "goal": "weight_loss",
            "timeline_months": 3,
            "diet_type": "normal",
            "allergens": [],
            "preferences": ["Vietnamese cuisine"],
            "max_cooking_time_min": 60,
            "available_equipment": ["stovetop", "oven"],
            # Nutrition targets (calculated from Mifflin-St Jeor)
            "tdee_kcal": 2200.0,
            "protein_g": 165.0,  # 30% of calories
            "fat_g": 73.0,  # 30% of calories
            "carb_g": 220.0,  # 40% of calories
        },
        {
            "user_id": "test_user_2",
            "age": 25,
            "gender": "female",
            "weight_kg": 60.0,
            "height_cm": 165.0,
            "activity_level": "light",
            "goal": "maintenance",
            "timeline_months": 6,
            "diet_type": "vegetarian",
            "allergens": ["dairy"],
            "preferences": ["Asian cuisine", "spicy food"],
            "max_cooking_time_min": 45,
            "available_equipment": ["stovetop"],
            # Nutrition targets
            "tdee_kcal": 1800.0,
            "protein_g": 135.0,  # 30% of calories
            "fat_g": 60.0,  # 30% of calories
            "carb_g": 180.0,  # 40% of calories
        },
        {
            "user_id": "test_user_3",
            "age": 35,
            "gender": "male",
            "weight_kg": 85.0,
            "height_cm": 180.0,
            "activity_level": "very_active",
            "goal": "muscle_gain",
            "timeline_months": 3,
            "diet_type": "normal",
            "allergens": ["nuts"],
            "preferences": ["high protein", "quick meals"],
            "max_cooking_time_min": 30,
            "available_equipment": ["stovetop", "microwave"],
            # Nutrition targets (higher for muscle gain)
            "tdee_kcal": 2800.0,
            "protein_g": 210.0,  # 30% of calories
            "fat_g": 93.0,  # 30% of calories
            "carb_g": 280.0,  # 40% of calories
        },
        {
            "user_id": "test_user_4",
            "age": 28,
            "gender": "female",
            "weight_kg": 55.0,
            "height_cm": 160.0,
            "activity_level": "moderate",
            "goal": "weight_loss",
            "timeline_months": 6,
            "diet_type": "vegan",
            "allergens": ["gluten"],
            "preferences": ["Mediterranean cuisine"],
            "max_cooking_time_min": 90,
            "available_equipment": ["stovetop", "oven", "blender"],
            # Nutrition targets (lower for weight loss)
            "tdee_kcal": 1500.0,
            "protein_g": 112.5,  # 30% of calories
            "fat_g": 50.0,  # 30% of calories
            "carb_g": 150.0,  # 40% of calories
        },
        {
            "user_id": "test_user_5",
            "age": 40,
            "gender": "male",
            "weight_kg": 90.0,
            "height_cm": 175.0,
            "activity_level": "sedentary",
            "goal": "weight_loss",
            "timeline_months": 6,
            "diet_type": "normal",
            "allergens": ["seafood"],
            "preferences": ["comfort food"],
            "max_cooking_time_min": 120,
            "available_equipment": ["stovetop", "oven", "slow cooker"],
            # Nutrition targets
            "tdee_kcal": 2000.0,
            "protein_g": 150.0,  # 30% of calories
            "fat_g": 67.0,  # 30% of calories
            "carb_g": 200.0,  # 40% of calories
        },
    ]
    
    return profiles


def get_profile_by_id(user_id: str) -> Dict[str, Any]:
    """
    Lấy profile theo user_id.
    
    Args:
        user_id: User ID
    
    Returns:
        User profile dictionary or None if not found
    """
    profiles = get_test_profiles()
    for profile in profiles:
        if profile["user_id"] == user_id:
            return profile
    return None

