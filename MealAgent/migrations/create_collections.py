"""
Migration script to create all Weaviate collections for MealAgent.

This script uses schema definitions from elysia.MealAgent.schemas to create
all required collections in Weaviate.
"""

import argparse
import sys
from pathlib import Path

# Add parent directory to path to enable imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

try:
    import weaviate
    from weaviate.classes.config import Configure
except ImportError:
    print("❌ Error: weaviate-client not installed. Install with: pip install weaviate-client")
    sys.exit(1)

from MealAgent.schemas import (
    RECIPE_SCHEMA,
    FDC_FOOD_SCHEMA,
    FDC_NUTRIENT_SCHEMA,
    FDC_PORTION_SCHEMA,
    USER_PROFILE_SCHEMA,
    MEAL_PLAN_SCHEMA,
    MEAL_PLAN_ITEM_SCHEMA,
    MEAL_LOG_ENTRY_SCHEMA,
    PANTRY_SCHEMA,
    PANTRY_ITEM_SCHEMA,
    SHOPPING_LIST_SCHEMA,
    SHOPPING_ITEM_SCHEMA,
)
from MealAgent.schemas.helpers import create_all_collections_from_schemas


def connect(host="localhost", port=8078, grpc_port=50051):
    """Connect to local Weaviate instance."""
    return weaviate.connect_to_local(
        host=host, port=port, grpc_port=grpc_port,
    )


def list_all_collections(client):
    """List all existing collections."""
    print("\n" + "="*80)
    print("📋 WEAVIATE COLLECTIONS OVERVIEW")
    print("="*80)
    
    names = client.collections.list_all()
    if not names:
        print("❌ No collections found!")
        return
    
    for name in sorted(names):
        col = client.collections.get(name)
        cfg = col.config.get()
        props = list(getattr(cfg, "properties", []) or [])
        pnames = [p.name for p in props]
        more = f" (+{len(pnames)-5} more)" if len(pnames) > 5 else ""
        print(f"  📊 {name}\n     Properties: {', '.join(pnames[:5])}{more}")


def drop_collections(client, collection_names: list):
    """Drop specified collections."""
    print("🗑️  Dropping collections...")
    dropped_count = 0
    existing = client.collections.list_all()
    
    for name in collection_names:
        if name in existing:
            try:
                client.collections.delete(name)
                print(f"   ✅ Dropped: {name}")
                dropped_count += 1
            except Exception as e:
                print(f"   ⚠️  {name}: {str(e)}")
    
    print(f"✅ Dropped {dropped_count} collections.")


def create_all_collections(client, drop_existing=False):
    """Create all MealAgent collections from schema definitions."""
    all_schemas = [
        RECIPE_SCHEMA,
        # Ensure referenced classes are created before FdcFood
        FDC_NUTRIENT_SCHEMA,
        FDC_PORTION_SCHEMA,
        FDC_FOOD_SCHEMA,
        USER_PROFILE_SCHEMA,
        MEAL_PLAN_SCHEMA,
        MEAL_PLAN_ITEM_SCHEMA,
        MEAL_LOG_ENTRY_SCHEMA,
        PANTRY_SCHEMA,
        PANTRY_ITEM_SCHEMA,
        SHOPPING_LIST_SCHEMA,
        SHOPPING_ITEM_SCHEMA,
    ]
    
    # Note: NutrientTarget is NOT a separate collection - it's embedded in UserProfile per design doc
    
    collection_names = [s["name"] for s in all_schemas]
    
    if drop_existing:
        drop_collections(client, collection_names)
    
    create_all_collections_from_schemas(client, all_schemas, drop_existing=False)


def create_specific_collections(client, names: list[str]):
    """Create only the specified collections by name."""
    # Build name → schema map
    name_to_schema = {
        RECIPE_SCHEMA["name"]: RECIPE_SCHEMA,
        FDC_FOOD_SCHEMA["name"]: FDC_FOOD_SCHEMA,
        FDC_NUTRIENT_SCHEMA["name"]: FDC_NUTRIENT_SCHEMA,
        FDC_PORTION_SCHEMA["name"]: FDC_PORTION_SCHEMA,
        USER_PROFILE_SCHEMA["name"]: USER_PROFILE_SCHEMA,
        MEAL_PLAN_SCHEMA["name"]: MEAL_PLAN_SCHEMA,
        MEAL_PLAN_ITEM_SCHEMA["name"]: MEAL_PLAN_ITEM_SCHEMA,
        MEAL_LOG_ENTRY_SCHEMA["name"]: MEAL_LOG_ENTRY_SCHEMA,
        PANTRY_SCHEMA["name"]: PANTRY_SCHEMA,
        PANTRY_ITEM_SCHEMA["name"]: PANTRY_ITEM_SCHEMA,
        SHOPPING_LIST_SCHEMA["name"]: SHOPPING_LIST_SCHEMA,
        SHOPPING_ITEM_SCHEMA["name"]: SHOPPING_ITEM_SCHEMA,
    }
    wanted = []
    for n in names:
        s = name_to_schema.get(n)
        if s is None:
            print(f"⚠️  Unknown collection name: {n}")
            continue
        wanted.append(s)
    if not wanted:
        print("No valid collection names provided to create.")
        return
    create_all_collections_from_schemas(client, wanted, drop_existing=False)


def main():
    """CLI entry point."""
    ap = argparse.ArgumentParser(description="Manage Weaviate collections for MealAgent")
    ap.add_argument("--drop", action="store_true", help="Drop all MealAgent collections")
    ap.add_argument("--create", action="store_true", help="Create collections (drop existing first if --drop also specified)")
    ap.add_argument("--list", action="store_true", help="List all existing collections")
    ap.add_argument("--drop-only", nargs="+", help="Drop only the specified collection names (space-separated)")
    ap.add_argument("--create-only", nargs="+", help="Create only the specified collection names (space-separated)")
    ap.add_argument("--host", default="localhost", help="Weaviate host")
    ap.add_argument("--port", type=int, default=8078, help="Weaviate HTTP port")
    ap.add_argument("--grpc-port", type=int, default=50051, help="Weaviate gRPC port")
    args = ap.parse_args()

    try:
        with connect(args.host, args.port, args.grpc_port) as client:
            # Targeted ops first
            if args.drop_only:
                existing = client.collections.list_all()
                to_drop = [n for n in args.drop_only if n in existing]
                if not to_drop:
                    print("No matching collections to drop.")
                else:
                    drop_collections(client, to_drop)
                # If only targeted drop requested, exit unless also combined with create-only
                if not args.create_only and not any([args.drop, args.create, args.list]):
                    return

            if args.create_only:
                create_specific_collections(client, args.create_only)
                # Exit unless combined with global flags
                if not any([args.drop, args.create, args.list]):
                    return

            if args.list:
                list_all_collections(client)
                return

            if args.drop:
                # Get all collection names from schemas
                all_schemas = [
                    RECIPE_SCHEMA,
                    # Drop order not critical, but keep consistent with create
                    FDC_NUTRIENT_SCHEMA, FDC_PORTION_SCHEMA, FDC_FOOD_SCHEMA,
                    USER_PROFILE_SCHEMA, MEAL_PLAN_SCHEMA, MEAL_PLAN_ITEM_SCHEMA,
                    MEAL_LOG_ENTRY_SCHEMA, PANTRY_SCHEMA, PANTRY_ITEM_SCHEMA,
                    SHOPPING_LIST_SCHEMA, SHOPPING_ITEM_SCHEMA,
                ]
                collection_names = [s["name"] for s in all_schemas]
                drop_collections(client, collection_names)
                if not args.create:
                    return

            if args.create or not any([args.drop, args.list]):
                # Auto-drop existing collections with same names before creating
                create_all_collections(client, drop_existing=True)
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()

