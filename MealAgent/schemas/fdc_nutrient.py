"""
Schema definition for FdcNutrient collection.

FdcNutrient stores nutrient data for FDC foods (non-vectorized).
"""

from weaviate.classes.config import (
    Property,
    DataType,
    Tokenization,
)

FDC_NUTRIENT_SCHEMA = {
    "name": "FdcNutrient",
    "properties": [
        Property(name="fdc_id", data_type=DataType.INT),
        Property(name="nutrient_id", data_type=DataType.INT),  # FDC nutrient ID (e.g., 1008 = Energy)
        Property(name="nutrient_name", data_type=DataType.TEXT),  # "Protein", "Vitamin C", etc.
        Property(name="amount_100g", data_type=DataType.NUMBER),
        Property(name="unit", data_type=DataType.TEXT),  # "g", "mg", "mcg", "IU"
    ],
    "vector_config": None,  # Non-vectorized
    "references": [],
}

