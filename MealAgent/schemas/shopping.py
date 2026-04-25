"""
Schema definitions for ShoppingList and ShoppingItem collections.
"""

from weaviate.classes.config import (
    Property,
    DataType,
    Tokenization,
)

SHOPPING_LIST_SCHEMA = {
    "name": "ShoppingList",
    "properties": [
        Property(name="list_id", data_type=DataType.TEXT, tokenization=Tokenization.FIELD),
        Property(name="user_id", data_type=DataType.TEXT, tokenization=Tokenization.FIELD),
        Property(name="plan_id", data_type=DataType.TEXT),  # Links to MealPlan
        Property(name="plan_start_date", data_type=DataType.DATE),  # Start date of the plan for display
        Property(name="created_at", data_type=DataType.DATE),
    ],
    "vector_config": None,  # Non-vectorized
    "references": [],
}

SHOPPING_ITEM_SCHEMA = {
    "name": "ShoppingItem",
    "properties": [
        Property(name="list_id", data_type=DataType.TEXT, tokenization=Tokenization.FIELD),
        Property(name="user_id", data_type=DataType.TEXT, tokenization=Tokenization.FIELD),
        Property(name="ingredient_name", data_type=DataType.TEXT),
        Property(name="quantity", data_type=DataType.NUMBER),
        Property(name="unit", data_type=DataType.TEXT),
        Property(name="category", data_type=DataType.TEXT),  # "produce", "dairy", "meat", etc. for grouping
        Property(name="purchased", data_type=DataType.BOOL),
    ],
    "vector_config": None,  # Non-vectorized
    "references": [],
}

