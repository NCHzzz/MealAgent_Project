"""
Schema definitions for Pantry and PantryItem collections.
"""

from weaviate.classes.config import (
    Property,
    DataType,
    Tokenization,
)

PANTRY_SCHEMA = {
    "name": "Pantry",
    "properties": [
        Property(name="user_id", data_type=DataType.TEXT, tokenization=Tokenization.FIELD),
        Property(name="updated_at", data_type=DataType.DATE),
    ],
    "vector_config": None,  # Non-vectorized
    "references": [],
}

PANTRY_ITEM_SCHEMA = {
    "name": "PantryItem",
    "properties": [
        Property(name="user_id", data_type=DataType.TEXT, tokenization=Tokenization.FIELD),
        Property(name="ingredient_name", data_type=DataType.TEXT),
        Property(name="quantity", data_type=DataType.NUMBER),
        Property(name="unit", data_type=DataType.TEXT),
        Property(name="fdc_id", data_type=DataType.INT),  # Optional link to FdcFood
        Property(name="expiry_date", data_type=DataType.DATE),  # Optional
    ],
    "vector_config": None,  # Non-vectorized
    "references": [],
}

