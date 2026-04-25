"""Add non-destructive fields required by MealAgent hardening changes.

Existing Weaviate collections are not updated just because schema files changed.
Run this migration after upgrading an existing deployment so new writes using
metadata fields do not fail with unknown-property errors.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass

import weaviate
from weaviate.classes.config import DataType, Property, Tokenization


@dataclass(frozen=True)
class PropertySpec:
    collection: str
    name: str
    data_type: DataType
    tokenization: Tokenization | None = None

    def to_property(self) -> Property:
        kwargs = {"name": self.name, "data_type": self.data_type}
        if self.tokenization is not None:
            kwargs["tokenization"] = self.tokenization
        return Property(**kwargs)


REQUIRED_PROPERTIES = [
    PropertySpec("MealLogEntry", "recipe_id", DataType.TEXT, Tokenization.FIELD),
    PropertySpec("MealLogEntry", "dish_name", DataType.TEXT),
    PropertySpec("MealLogEntry", "source_plan_id", DataType.TEXT, Tokenization.FIELD),
    PropertySpec("MealLogEntry", "meal_type", DataType.TEXT),
    PropertySpec("MealPlanItem", "dish_name", DataType.TEXT),
    PropertySpec("PantryItem", "pantry_item_id", DataType.TEXT, Tokenization.FIELD),
    PropertySpec("ShoppingItem", "user_id", DataType.TEXT, Tokenization.FIELD),
]


def _existing_property_names(collection) -> set[str]:
    config = collection.config.get()
    return {prop.name for prop in (getattr(config, "properties", None) or [])}


def plan_missing_properties(client) -> list[PropertySpec]:
    missing: list[PropertySpec] = []
    for spec in REQUIRED_PROPERTIES:
        if not client.collections.exists(spec.collection):
            print(f"⚠️  Collection {spec.collection} does not exist; skipping {spec.name}.")
            continue
        collection = client.collections.get(spec.collection)
        if spec.name not in _existing_property_names(collection):
            missing.append(spec)
    return missing


def migrate(apply: bool = False, host: str = "localhost", port: int = 8078, grpc_port: int = 50051) -> list[PropertySpec]:
    client = weaviate.connect_to_local(host=host, port=port, grpc_port=grpc_port)
    try:
        missing = plan_missing_properties(client)
        if not missing:
            print("✅ All hardening properties already exist.")
            return []

        verb = "Adding" if apply else "Would add"
        for spec in missing:
            print(f"{verb} {spec.collection}.{spec.name}")
            if apply:
                client.collections.get(spec.collection).config.add_property(spec.to_property())

        if apply:
            print(f"✅ Added {len(missing)} missing property/properties.")
        else:
            print("ℹ️ Dry run mode. Re-run with --apply to mutate schema.")
        return missing
    finally:
        client.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Add non-destructive MealAgent hardening properties")
    parser.add_argument("--apply", action="store_true", help="Apply schema changes. Default is dry-run.")
    parser.add_argument("--host", default="localhost", help="Weaviate host")
    parser.add_argument("--port", type=int, default=8078, help="Weaviate HTTP port")
    parser.add_argument("--grpc-port", type=int, default=50051, help="Weaviate gRPC port")
    args = parser.parse_args()
    migrate(apply=args.apply, host=args.host, port=args.port, grpc_port=args.grpc_port)
