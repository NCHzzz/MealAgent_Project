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

