import weaviate
from weaviate.classes.config import Property, DataType
import argparse

def migrate_to_admin(user_ids: list[str], apply: bool = False):
    print("🚀 Starting migration: Promoting selected users to 'admin'...")
    if not user_ids:
        raise SystemExit("Refusing to promote users without explicit --user-id values.")
    if not apply:
        print("ℹ️ Dry run mode. Re-run with --apply to mutate data.")
    
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
            if apply:
                collection.config.add_property(
                    Property(name="role", data_type=DataType.TEXT)
                )
                print("✅ 'role' property added.")
            else:
                print("DRY RUN: would add 'role' property.")

        # 2. Promote selected users
        print("🔍 Scanning selected users...")
        users = collection.query.fetch_objects(limit=1000)
        
        updated_count = 0
        for user in users.objects:
            user_id = user.properties.get("user_id") or user.properties.get("id")
            if user_id in user_ids:
                if apply:
                    collection.data.update(
                        uuid=user.uuid,
                        properties={"role": "admin"}
                    )
                updated_count += 1
        
        verb = "Promoted" if apply else "Would promote"
        print(f"✅ Migration complete. {verb} {updated_count} selected users to role 'admin'.")

    except Exception as e:
        print(f"❌ Error during migration: {e}")
    finally:
        client.close()
        print("🔌 Connection closed.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Promote explicit UserProfile IDs to admin")
    parser.add_argument("--user-id", action="append", default=[], help="User ID to promote. Repeat for multiple users.")
    parser.add_argument("--apply", action="store_true", help="Apply data changes. Default is dry-run.")
    args = parser.parse_args()
    migrate_to_admin(user_ids=args.user_id, apply=args.apply)
