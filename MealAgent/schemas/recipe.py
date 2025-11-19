"""
Schema definition for Recipe collection.

Recipe stores recipe data with vectorization for semantic search.
"""

from weaviate.classes.config import (
    Property,
    DataType,
    ReferenceProperty,
    Configure,
    Tokenization,
)

RECIPE_SCHEMA = {
    "name": "Recipe",
    "properties": [
        # Exactly the CSV fields
        Property(name="food_id", data_type=DataType.TEXT, tokenization=Tokenization.FIELD),
        Property(name="dish_name", data_type=DataType.TEXT),
        Property(name="dish_type", data_type=DataType.TEXT),
        Property(name="serving_size", data_type=DataType.INT),
        Property(name="cooking_time", data_type=DataType.INT),
        Property(name="ingredients_with_qty", data_type=DataType.TEXT_ARRAY),
        Property(name="ingredients", data_type=DataType.TEXT_ARRAY),
        Property(name="cooking_method_array", data_type=DataType.TEXT_ARRAY),
        Property(name="image_link", data_type=DataType.TEXT),
         # Constraint filtering fields (optional; populated by tools or ETL enrichment)
        # Used by constraints_guard_tool / planning tools for diet/allergen/device filters
        Property(name="diet_type", data_type=DataType.TEXT_ARRAY),
        Property(name="allergens", data_type=DataType.TEXT_ARRAY),
        Property(name="devices", data_type=DataType.TEXT_ARRAY),
        # Computed field: macros per serving (object requires nested properties in Weaviate)
        Property(
            name="macros_per_serving",
            data_type=DataType.OBJECT,
            nested_properties=[
                Property(name="kcal", data_type=DataType.NUMBER),
                Property(name="protein_g", data_type=DataType.NUMBER),
                Property(name="fat_g", data_type=DataType.NUMBER),
                Property(name="carb_g", data_type=DataType.NUMBER),
            ],
        ),
        # Cached VN→EN ingredient mapping to FDC for faster subsequent queries
        Property(
            name="ingredient_fdc_map",
            data_type=DataType.OBJECT_ARRAY,
            nested_properties=[
                Property(name="ingredient_vn", data_type=DataType.TEXT),
                Property(name="ingredient_en", data_type=DataType.TEXT),
                Property(name="fdc_id", data_type=DataType.INT),
                Property(name="quantity_g", data_type=DataType.NUMBER),
                Property(name="confidence", data_type=DataType.NUMBER),
            ],
        ),
    ],
    "vector_config": Configure.Vectors.text2vec_transformers(
        source_properties=[
            "dish_name", "ingredients_with_qty", "ingredients", "cooking_method_array"
        ],
        vectorize_collection_name=False,
        dimensions=1024,
        vector_index_config=Configure.VectorIndex.hnsw(),
    ),
    "references": [],
}

