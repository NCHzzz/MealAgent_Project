import weaviate
from weaviate.classes.config import Property, DataType
import sys

def migrate_to_admin():
    print("🚀 Starting migration: Promoting all existing users to 'admin'...")
    
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
        # Get collection
        collection = client.collections.get("UserProfile")
        
        # 1. Ensure property exists
        config = collection.config.get()
        has_role = any(p.name == "role" for p in config.properties)
        if not has_role:
            print("📝 Adding 'role' property to UserProfile schema...")
            collection.config.add_property(
                Property(name="role", data_type=DataType.TEXT)
            )
            print("✅ 'role' property added.")

        # 2. Promote all users
        print("🔍 Scanning all users...")
        users = collection.query.fetch_objects(limit=1000)
        
        updated_count = 0
        for user in users.objects:
            # Set everyone to admin as requested
            collection.data.update(
                uuid=user.uuid,
                properties={"role": "admin"}
            )
            updated_count += 1
        
        print(f"✅ Migration complete. Promoted {updated_count} users to role 'admin'.")

    except Exception as e:
        print(f"❌ Error during migration: {e}")
    finally:
        client.close()
        print("🔌 Connection closed.")

if __name__ == "__main__":
    migrate_to_admin()
