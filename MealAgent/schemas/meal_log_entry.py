"""
Schema definition for MealLogEntry collection.

MealLogEntry stores logged meal data for nutrition tracking.
"""

from weaviate.classes.config import (
    Property,
    DataType,
    Tokenization,
)

MEAL_LOG_ENTRY_SCHEMA = {
    "name": "MealLogEntry",
    "properties": [
        Property(name="log_id", data_type=DataType.TEXT, tokenization=Tokenization.FIELD),
        Property(name="user_id", data_type=DataType.TEXT, tokenization=Tokenization.FIELD),
        Property(name="logged_at", data_type=DataType.DATE),
        Property(name="meal_description", data_type=DataType.TEXT),  # Original user input (e.g., "I ate chicken salad")
        Property(name="parsed_dish", data_type=DataType.TEXT),  # LLM-parsed dish name
        Property(name="recipe_id", data_type=DataType.TEXT, tokenization=Tokenization.FIELD),  # Canonical recipe/FDC id when known
        Property(name="dish_name", data_type=DataType.TEXT),  # Human-readable dish name for personalization/variety
        Property(name="source_plan_id", data_type=DataType.TEXT, tokenization=Tokenization.FIELD),  # MealPlan accepted into this log
        Property(name="meal_type", data_type=DataType.TEXT),  # breakfast/lunch/dinner/snack
        Property(name="ingredients", data_type=DataType.TEXT),  # JSON string: [{"name": str, "amount": float, "unit": str, "fdc_id": int?}]
        Property(name="portion_size", data_type=DataType.NUMBER),  # Portion multiplier
        Property(name="calculated_macros", data_type=DataType.TEXT),  # JSON string: {"kcal": float, "protein_g": float, "fat_g": float, "carb_g": float}
        Property(name="calculated_micros", data_type=DataType.TEXT),  # JSON string: micronutrients if available
        Property(name="validation_status", data_type=DataType.TEXT),  # "complete", "partial", "failed"
        Property(name="parsing_method", data_type=DataType.TEXT),  # "llm", "manual_fallback"
    ],
    "vector_config": None,  # Non-vectorized
    "references": [],
}

