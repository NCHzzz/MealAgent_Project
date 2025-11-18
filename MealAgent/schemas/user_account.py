"""
Schema definition for UserAccount collection.

Used for authentication (email/password → user_id mapping).
"""

from weaviate.classes.config import Property, DataType

USER_ACCOUNT_SCHEMA = {
    "name": "UserAccount",
    "properties": [
        Property(
            name="user_id",
            data_type=DataType.TEXT,
        ),
        Property(
            name="email",
            data_type=DataType.TEXT,
        ),
        Property(
            name="password_hash",
            data_type=DataType.TEXT,
        ),
        Property(
            name="created_at",
            data_type=DataType.DATE,
        ),
        Property(
            name="last_login_at",
            data_type=DataType.DATE,
        ),
    ],
    "vector_config": None,
    "references": [],
}


