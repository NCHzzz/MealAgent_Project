import weaviate
from weaviate.classes.config import Property, DataType
import argparse


def iter_objects(collection, page_size: int = 1000):
    offset = 0
    while True:
        page = collection.query.fetch_objects(limit=page_size, offset=offset)
        objects = list(page.objects or [])
        if not objects:
            break
        for obj in objects:
            yield obj
        if len(objects) < page_size:
            break
        offset += page_size

def migrate(apply: bool = False):
    print("🚀 Starting migration: Adding 'role' to UserProfile...")
    if not apply:
        print("ℹ️ Dry run mode. Re-run with --apply to mutate schema/data.")
    
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
            if apply:
                collection.config.add_property(
                    Property(name="role", data_type=DataType.TEXT)
                )
                print("✅ 'role' property added.")
            else:
                print("DRY RUN: would add 'role' property.")
        else:
            print("ℹ️ 'role' property already exists in schema.")

        # 2. Migrate Data
        print("🔍 Searching for users without a role...")
        updated_count = 0
        scanned_count = 0
        for user in iter_objects(collection):
            scanned_count += 1
            # We check if role is missing or None
            if not user.properties.get("role"):
                if apply:
                    collection.data.update(
                        uuid=user.uuid,
                        properties={"role": "user"}
                    )
                updated_count += 1
        
        verb = "Updated" if apply else "Would update"
        print(f"✅ Migration complete. Scanned {scanned_count} users. {verb} {updated_count} users to role 'user'.")

    except Exception as e:
        print(f"❌ Error during migration: {e}")
    finally:
        client.close()
        print("🔌 Connection closed.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Add default UserProfile.role values")
    parser.add_argument("--apply", action="store_true", help="Apply schema/data changes. Default is dry-run.")
    migrate(apply=parser.parse_args().apply)
