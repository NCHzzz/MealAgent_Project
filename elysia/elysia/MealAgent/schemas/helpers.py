"""
Helper functions for creating Weaviate collections from schema definitions.
"""

from typing import Dict, List, Any, TYPE_CHECKING

if TYPE_CHECKING:
    import weaviate


def create_collection_from_schema(
    client: "weaviate.WeaviateClient",
    schema: Dict[str, Any]
) -> None:
    """
    Create a Weaviate collection from a schema definition.
    
    Args:
        client: Weaviate client instance
        schema: Schema dictionary with keys: name, properties, vector_config, references
    """
    name = schema["name"]
    properties = schema["properties"]
    vector_config = schema.get("vector_config")
    references = schema.get("references", [])
    
    # Check if collection already exists
    existing_collections = client.collections.list_all()
    if name in existing_collections:
        print(f"   ⚠️  Collection {name} already exists, skipping...")
        return
    
    # Create collection
    try:
        kwargs = {
            "name": name,
            "properties": properties,
        }
        
        if vector_config:
            kwargs["vector_config"] = vector_config
        
        if references:
            kwargs["references"] = references
        
        client.collections.create(**kwargs)
        print(f"   ✅ Created: {name}")
    except Exception as e:
        print(f"   ❌ Failed to create {name}: {e}")
        raise


def create_all_collections_from_schemas(
    client: "weaviate.WeaviateClient",
    schemas: List[Dict[str, Any]],
    drop_existing: bool = False
) -> None:
    """
    Create all collections from a list of schema definitions.
    
    Args:
        client: Weaviate client instance
        schemas: List of schema dictionaries
        drop_existing: If True, drop existing collections before creating
    """
    existing_collections = client.collections.list_all()
    collections_to_create = [s["name"] for s in schemas]
    
    if drop_existing:
        print("🔄 Dropping existing collections...")
        for name in collections_to_create:
            if name in existing_collections:
                try:
                    client.collections.delete(name)
                    print(f"   ✅ Dropped: {name}")
                except Exception as e:
                    print(f"   ⚠️  Failed to drop {name}: {e}")
    
    print("🏗️  Creating collections from schemas...")
    for schema in schemas:
        try:
            create_collection_from_schema(client, schema)
        except Exception as e:
            print(f"   ❌ Failed to create {schema['name']}: {e}")
    
    print("✅ Collection creation complete!")

