"""
Schema definition for FdcPortion collection.

FdcPortion stores portion conversion data for FDC foods (non-vectorized).
"""

from weaviate.classes.config import (
    Property,
    DataType,
    Tokenization,
)

FDC_PORTION_SCHEMA = {
    "name": "FdcPortion",
    "properties": [
        Property(name="fdc_id", data_type=DataType.INT),  # Links to FdcFood
        Property(name="amount", data_type=DataType.NUMBER),
        Property(name="measure_unit", data_type=DataType.TEXT),  # "cup", "oz", "tbsp", etc.
        Property(name="gram_weight", data_type=DataType.NUMBER),  # Conversion to grams
    ],
    "vector_config": None,  # Non-vectorized
    "references": [],
}

