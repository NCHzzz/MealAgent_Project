"""
Schema definitions for MealPlan and MealPlanItem collections.
"""

from weaviate.classes.config import (
    Property,
    DataType,
    ReferenceProperty,
    Tokenization,
)

MEAL_PLAN_SCHEMA = {
    "name": "MealPlan",
    "properties": [
        Property(name="plan_id", data_type=DataType.TEXT, tokenization=Tokenization.FIELD),
        Property(name="user_id", data_type=DataType.TEXT, tokenization=Tokenization.FIELD),
        Property(name="plan_type", data_type=DataType.TEXT),  # "day", "week"
        Property(name="start_date", data_type=DataType.DATE),
        Property(name="created_at", data_type=DataType.DATE),
    ],
    "vector_config": None,  # Non-vectorized
    "references": [],
}

MEAL_PLAN_ITEM_SCHEMA = {
    "name": "MealPlanItem",
    "properties": [
        Property(name="plan_id", data_type=DataType.TEXT, tokenization=Tokenization.FIELD),
        Property(name="day_index", data_type=DataType.INT),  # 0-6 for weekly
        Property(name="meal_type", data_type=DataType.TEXT),  # "breakfast", "lunch", "dinner", "snack"
        Property(name="recipe_id", data_type=DataType.TEXT, tokenization=Tokenization.FIELD),
        Property(name="dish_name", data_type=DataType.TEXT),  # Denormalized for variety filters and plan reload fallback
        Property(name="servings", data_type=DataType.NUMBER),  # Portion multiplier
        Property(name="actual_macros", data_type=DataType.TEXT),  # JSON string: {"kcal": float, "protein_g": float, ...}
    ],
    "vector_config": None,  # Non-vectorized
    "references": [
        ReferenceProperty(name="has_recipe", target_collection="Recipe"),
    ],
}

