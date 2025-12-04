#!/usr/bin/env python3
"""
Export Weaviate collections to CSV files.

This script is intended for local use with the MealAgent Weaviate instance
defined in `Docker/docker-compose.yml`. It will:

  - Connect to Weaviate (local or cloud, same env vars as other scripts)
  - Page through all objects in each requested collection
  - Write one CSV file per collection with all scalar properties

Usage (from repo root):

    # Export the four MealAgent base collections to CSV in ./exports
    python -m MealAgent.scripts.export_weaviate_collections ^
        --collections FdcFood FdcNutrient FdcPortion Recipe ^
        --out-dir exports

If you omit --collections it defaults to FdcFood, FdcNutrient, FdcPortion, Recipe.

Environment (same as `validate_recipe_macros.py`):
    WEAVIATE_IS_LOCAL=true
    WEAVIATE_PORT=8078
    WEAVIATE_GRPC_PORT=50051
    # or WEAVIATE_URL / WEAVIATE_API_KEY for WCD
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

from dotenv import load_dotenv

# Ensure project root is on sys.path when running as a script
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, "../.."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from elysia.util.client import ClientManager  # type: ignore[import]


load_dotenv()


@dataclass
class ExportConfig:
    collections: Sequence[str]
    out_dir: Path
    batch_size: int = 500


def init_client_manager() -> ClientManager:
    """
    Initialise a ClientManager configured for local or cloud Weaviate.

    Mirrors the settings used in `validate_recipe_macros.py` so that
    exports behave consistently with the rest of MealAgent tooling.
    """

    # Lazy import of logging to avoid forcing configuration here
    import logging

    logger = logging.getLogger("export_weaviate_collections")

    return ClientManager(
        wcd_url=os.getenv("WEAVIATE_URL"),
        wcd_api_key=os.getenv("WEAVIATE_API_KEY"),
        weaviate_is_local=os.getenv("WEAVIATE_IS_LOCAL", "true").lower() == "true",
        local_weaviate_port=int(os.getenv("WEAVIATE_PORT", "8078")),
        local_weaviate_grpc_port=int(os.getenv("WEAVIATE_GRPC_PORT", "50051")),
        logger=logger,
    )


def _flatten_properties(props: Dict[str, Any]) -> Dict[str, Any]:
    """
    Flatten Weaviate object properties to a CSV‑friendly dict.

    - Scalar values are kept as‑is
    - Lists are joined with " | "
    - Nested dicts/objects are JSON‑serialised strings
    """

    import json

    flat: Dict[str, Any] = {}
    for key, value in props.items():
        if isinstance(value, (str, int, float, bool)) or value is None:
            flat[key] = value
        elif isinstance(value, list):
            # Convert list elements to string and join with a safe separator
            flat[key] = " | ".join(str(v) for v in value)
        elif isinstance(value, dict):
            flat[key] = json.dumps(value, ensure_ascii=False)
        else:
            # Fallback: best‑effort string representation
            flat[key] = str(value)
    return flat


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def export_collection_to_csv(
    client_manager: ClientManager,
    collection_name: str,
    out_dir: Path,
    batch_size: int = 500,
    encoding: str = "utf-8-sig",
) -> Path:
    """
    Export a single Weaviate collection to CSV.

    Returns:
        Path to the written CSV file.
    """

    from tqdm import tqdm  # type: ignore[import]

    _ensure_dir(out_dir)
    out_path = out_dir / f"{collection_name}.csv"

    # We build the header dynamically as the union of all property keys we see.
    fieldnames: List[str] = []
    rows: List[Dict[str, Any]] = []

    with client_manager.connect_to_client() as client:
        collection = client.collections.get(collection_name)

        # Use cursor-based pagination (`after`) instead of offset to avoid
        # hitting Weaviate's QUERY_MAXIMUM_RESULTS limit.
        cursor: Optional[str] = None

        progress_desc = f"Exporting {collection_name}"
        pbar = tqdm(total=None, desc=progress_desc, unit="obj")

        while True:
            if cursor:
                result = collection.query.fetch_objects(limit=batch_size, after=cursor)
            else:
                result = collection.query.fetch_objects(limit=batch_size)

            objects: Iterable[Any] = getattr(result, "objects", []) or []
            objects = list(objects)
            if not objects:
                break

            for obj in objects:
                # `obj.properties` is a dict of the stored properties
                props = getattr(obj, "properties", {}) or {}
                flat = _flatten_properties(props)

                # Include UUID for traceability
                uuid_val = getattr(obj, "uuid", None)
                if uuid_val is not None and "uuid" not in flat:
                    flat["uuid"] = str(uuid_val)

                rows.append(flat)

                # Grow fieldname set
                for k in flat.keys():
                    if k not in fieldnames:
                        fieldnames.append(k)

            # Advance cursor to the last object's UUID
            last_uuid = getattr(objects[-1], "uuid", None)
            cursor = str(last_uuid) if last_uuid is not None else None

            pbar.update(len(objects))

        pbar.close()

    # Write all rows using the unioned header
    # Use UTF‑8 with BOM (utf-8-sig) so that Excel trên Windows nhận diện đúng tiếng Việt.
    with out_path.open("w", encoding=encoding, newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)

    return out_path


def parse_args(argv: Sequence[str] | None = None) -> ExportConfig:
    parser = argparse.ArgumentParser(
        description="Export Weaviate collections to CSV files.",
    )
    parser.add_argument(
        "--collections",
        nargs="+",
        default=["FdcFood", "FdcNutrient", "FdcPortion", "Recipe"],
        help="List of Weaviate collection names to export.",
    )
    parser.add_argument(
        "--out-dir",
        type=str,
        default="exports",
        help="Output directory for CSV files (will be created if missing).",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=500,
        help="Number of objects to fetch per batch from Weaviate.",
    )

    args = parser.parse_args(argv)

    return ExportConfig(
        collections=args.collections,
        out_dir=Path(args.out_dir),
        batch_size=args.batch_size,
    )


def main(argv: Sequence[str] | None = None) -> None:
    config = parse_args(argv)
    client_manager = init_client_manager()

    try:
        for name in config.collections:
            csv_path = export_collection_to_csv(
                client_manager,
                name,
                config.out_dir,
                batch_size=config.batch_size,
            )
            print(f"✅ Exported collection {name} to {csv_path}")
    finally:
        # Close any background client resources.
        try:
            # Newer ClientManager exposes close_clients; if missing, ignore.
            close = getattr(client_manager, "close_clients", None)
            if callable(close):
                import asyncio

                asyncio.run(close())
        except Exception:
            pass


if __name__ == "__main__":
    main()


