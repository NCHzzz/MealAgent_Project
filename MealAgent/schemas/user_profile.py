"""
Schema definition for UserProfile collection.

UserProfile stores user profile data including embedded nutritional targets.
Note: NutrientTarget properties are embedded directly in UserProfile per design doc.
"""

from weaviate.classes.config import (
    Property,
    DataType,
    Tokenization,
)

USER_PROFILE_SCHEMA = {
    "name": "UserProfile",
    "properties": [
        # Basic Profile Info
        Property(name="user_id", data_type=DataType.TEXT, tokenization=Tokenization.FIELD),
        Property(name="age", data_type=DataType.INT),
        Property(name="gender", data_type=DataType.TEXT),  # "male", "female", "other"
        Property(name="weight_kg", data_type=DataType.NUMBER),
        Property(name="height_cm", data_type=DataType.NUMBER),
        Property(name="activity_level", data_type=DataType.TEXT),  # "sedentary", "light", "moderate", "very_active", "extra_active"
        
        # Dietary Constraints
        Property(name="diet_type", data_type=DataType.TEXT),
        Property(name="allergens", data_type=DataType.TEXT_ARRAY),
        Property(name="preferences", data_type=DataType.TEXT_ARRAY),  # Liked cuisines/ingredients
        Property(name="max_cooking_time_min", data_type=DataType.INT),  # Optional constraint
        Property(name="available_equipment", data_type=DataType.TEXT_ARRAY),  # Optional constraint
        
        # Nutritional Targets (calculated from profile) - Embedded from NutrientTarget
        Property(name="tdee_kcal", data_type=DataType.NUMBER),  # Harris-Benedict calculated TDEE
        Property(name="protein_g", data_type=DataType.NUMBER),  # Daily protein target
        Property(name="fat_g", data_type=DataType.NUMBER),  # Daily fat target
        Property(name="carb_g", data_type=DataType.NUMBER),  # Daily carb target
        # Structured micronutrient targets for code/tools (stored as JSON-like object in Weaviate 4.x)
        Property(name="micronutrient_targets", data_type=DataType.OBJECT),
        
        # Metadata
        Property(name="created_at", data_type=DataType.DATE),
        Property(name="updated_at", data_type=DataType.DATE),
    ],
    "vector_config": None,  # Non-vectorized
    "references": [],
}

