import weaviate
from weaviate.classes.config import Property, DataType
import sys

def migrate():
    print("🚀 Starting migration: Adding 'role' to UserProfile...")
    
    # Connect to Weaviate
    try:
        client = weaviate.connect_to_local(
            host="localhost",
            port=8078,
            grpc_port=50051
        )
        print("✅ Connected to Weaviate.")
    except Exception as e:
        print(f"❌ Failed to connect to Weaviate: {e}")
        return

    try:
        # 1. Update Schema
        collection = client.collections.get("UserProfile")
        config = collection.config.get()
        
        has_role = any(p.name == "role" for p in config.properties)
        if not has_role:
            print("📝 Adding 'role' property to UserProfile schema...")
            collection.config.add_property(
                Property(name="role", data_type=DataType.TEXT)
            )
            print("✅ 'role' property added.")
        else:
            print("ℹ️ 'role' property already exists in schema.")

        # 2. Migrate Data
        print("🔍 Searching for users without a role...")
        # Get all users
        users = collection.query.fetch_objects(limit=1000)
        
        updated_count = 0
        for user in users.objects:
            # We check if role is missing or None
            if not user.properties.get("role"):
                collection.data.update(
                    uuid=user.uuid,
                    properties={"role": "user"}
                )
                updated_count += 1
        
        print(f"✅ Migration complete. Updated {updated_count} users to role 'user'.")

    except Exception as e:
        print(f"❌ Error during migration: {e}")
    finally:
        client.close()
        print("🔌 Connection closed.")

if __name__ == "__main__":
    migrate()
