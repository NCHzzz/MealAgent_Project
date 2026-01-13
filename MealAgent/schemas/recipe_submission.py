"""
Schema definition for RecipeSubmission collection.

RecipeSubmission stores user-submitted recipes pending admin approval.
When approved, recipe data is copied to the main Recipe collection.
"""

from weaviate.classes.config import (
    Property,
    DataType,
    Tokenization,
)

RECIPE_SUBMISSION_SCHEMA = {
    "name": "RecipeSubmission",
    "properties": [
        # Submission metadata
        Property(
            name="submission_id",
            data_type=DataType.TEXT,
            tokenization=Tokenization.FIELD,
            description="Unique submission identifier"
        ),
        Property(
            name="submitted_by",
            data_type=DataType.TEXT,
            tokenization=Tokenization.FIELD,
            description="User ID who submitted the recipe"
        ),
        Property(
            name="submitted_at",
            data_type=DataType.DATE,
            description="Timestamp when recipe was submitted"
        ),
        Property(
            name="status",
            data_type=DataType.TEXT,
            description="Submission status: pending, approved, rejected"
        ),
        Property(
            name="reviewed_by",
            data_type=DataType.TEXT,
            tokenization=Tokenization.FIELD,
            description="Admin user ID who reviewed the submission"
        ),
        Property(
            name="reviewed_at",
            data_type=DataType.DATE,
            description="Timestamp when submission was reviewed"
        ),
        Property(
            name="rejection_reason",
            data_type=DataType.TEXT,
            description="Reason for rejection if rejected"
        ),
        
        # Recipe data (matches Recipe schema)
        Property(name="dish_name", data_type=DataType.TEXT),
        Property(name="dish_type", data_type=DataType.TEXT),
        Property(name="serving_size", data_type=DataType.INT),
        Property(name="cooking_time", data_type=DataType.INT),
        Property(name="ingredients_with_qty", data_type=DataType.TEXT_ARRAY),
        Property(name="ingredients", data_type=DataType.TEXT_ARRAY),
        Property(name="cooking_method_array", data_type=DataType.TEXT_ARRAY),
        Property(name="image_link", data_type=DataType.TEXT),
        Property(name="diet_type", data_type=DataType.TEXT_ARRAY),
        Property(name="allergens", data_type=DataType.TEXT_ARRAY),
        Property(name="devices", data_type=DataType.TEXT_ARRAY),
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
    ],
    "vector_config": None,  # No vectorization needed for pending submissions
    "references": [],
}
