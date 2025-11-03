"""
Schema definition for FdcFood collection.

FdcFood stores FoodData Central food items with vectorization for semantic search.
"""

from weaviate.classes.config import (
    Property,
    DataType,
    ReferenceProperty,
    Configure,
    Tokenization,
)

FDC_FOOD_SCHEMA = {
    "name": "FdcFood",
    "properties": [
        Property(name="fdc_id", data_type=DataType.INT),
        Property(name="description", data_type=DataType.TEXT),

        # Macronutrients (per 100g)
        Property(name="energy_kcal_100g", data_type=DataType.NUMBER),
        Property(name="protein_g_100g", data_type=DataType.NUMBER),
        Property(name="fat_g_100g", data_type=DataType.NUMBER),
        Property(name="carbohydrate_g_100g", data_type=DataType.NUMBER),
        Property(name="sugars_g_100g", data_type=DataType.NUMBER),
        Property(name="fiber_g_100g", data_type=DataType.NUMBER),
        Property(name="sodium_mg_100g", data_type=DataType.NUMBER),
        Property(name="sat_fat_g_100g", data_type=DataType.NUMBER),

        # Micronutrients (per 100g)
        Property(name="calcium_mg_100g", data_type=DataType.NUMBER),
        Property(name="iron_mg_100g", data_type=DataType.NUMBER),
        Property(name="potassium_mg_100g", data_type=DataType.NUMBER),
        Property(name="magnesium_mg_100g", data_type=DataType.NUMBER),
        Property(name="zinc_mg_100g", data_type=DataType.NUMBER),
        Property(name="vitamin_a_rae_ug_100g", data_type=DataType.NUMBER),
        Property(name="vitamin_b6_mg_100g", data_type=DataType.NUMBER),
        Property(name="vitamin_b12_ug_100g", data_type=DataType.NUMBER),
        Property(name="thiamin_b1_mg_100g", data_type=DataType.NUMBER),
        Property(name="riboflavin_b2_mg_100g", data_type=DataType.NUMBER),
        Property(name="niacin_b3_mg_100g", data_type=DataType.NUMBER),
        Property(name="vitamin_c_mg_100g", data_type=DataType.NUMBER),
        Property(name="vitamin_d_ug_100g", data_type=DataType.NUMBER),
        Property(name="vitamin_e_mg_100g", data_type=DataType.NUMBER),
    ],
    "vector_config": Configure.Vectors.text2vec_transformers(
        source_properties=["description"],
        vectorize_collection_name=False,
        dimensions=1024,
        vector_index_config=Configure.VectorIndex.hnsw(),
    ),
    "references": [
        ReferenceProperty(name="has_portion", target_collection="FdcPortion"),
        ReferenceProperty(name="has_nutrient", target_collection="FdcNutrient"),
    ],
}

