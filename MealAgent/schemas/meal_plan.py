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
        Property(name="servings", data_type=DataType.NUMBER),  # Portion multiplier
        # Actual macros for this slot; structured object for direct querying/aggregation
        Property(
            name="actual_macros",
            data_type=DataType.OBJECT,
            nested_properties=[
                Property(name="kcal", data_type=DataType.NUMBER),
                Property(name="protein_g", data_type=DataType.NUMBER),
                Property(name="fat_g", data_type=DataType.NUMBER),
                Property(name="carb_g", data_type=DataType.NUMBER),
            ],
        ),
    ],
    "vector_config": None,  # Non-vectorized
    "references": [
        ReferenceProperty(name="has_recipe", target_collection="Recipe"),
    ],
}

