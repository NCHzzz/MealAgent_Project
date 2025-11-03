"""
Elysia Collection Preprocessing Script for Meal Agent

This module provides utilities to preprocess, manage, and view Elysia collections
for the Meal Agent application. It handles four primary collections:
- Recipe: Recipe data with ingredients and directions
- FdcFood: USDA FoodData Central food items
- FdcPortion: Portion size information
- FdcNutrient: Nutrient metadata

Features:
    - Preprocess collections with LLM-generated summaries and statistics
    - Configure frontend display mappings (document/generic/table types)
    - Delete preprocessed metadata
    - View preprocessed collection details
    - Auto-detect and warn about Weaviate QUERY_MAXIMUM_RESULTS limits

Usage Examples:
    # Preprocess all collections
    python -m elysia.meal_agents.etl.preprocess --all --show
    
    # Preprocess specific collection
    python -m elysia.meal_agents.etl.preprocess -c FdcFood --force
    
    # Delete preprocessed metadata
    python -m elysia.meal_agents.etl.preprocess delete -c FdcFood
    python -m elysia.meal_agents.etl.preprocess delete --all --show
    
    # View preprocessed collections
    python -m elysia.meal_agents.etl.preprocess view -c FdcFood Recipe

Author: Meal Agent Team
Date: October 2025
"""

from __future__ import annotations
import argparse
import logging
from datetime import datetime
from typing import List, Optional

# Elysia public API imports
from elysia import (
    preprocess,
    preprocessed_collection_exists,
    edit_preprocessed_collection,
    view_preprocessed_collection,
    delete_preprocessed_collection,
)
from elysia.util.client import ClientManager

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# Default collections to process
DEFAULT_COLLECTIONS = ["FdcFood", "FdcPortion", "FdcNutrient", "Recipe"]


# ============================================================================
# Helper Functions
# ============================================================================


def _get_total_count(collection_name: str) -> Optional[int]:
    """
    Retrieve the total number of records in a Weaviate collection.
    
    This function safely connects to Weaviate, queries the collection's
    aggregate count, and ensures the connection is properly closed.
    
    Args:
        collection_name: Name of the collection to query
        
    Returns:
        Total number of records in the collection, or None if query fails
        
    Note:
        Uses context manager to ensure proper connection cleanup
    """
    try:
        with ClientManager().connect_to_client() as client:
            col = client.collections.get(collection_name)
            agg = col.aggregate.over_all(total_count=True)
            return int(agg.total_count or 0)
    except Exception as e:
        logger.warning(
            f"[Skip QMR-check] Unable to retrieve total_count for {collection_name}: {e}"
        )
        return None


def _suggest_qmr(total: int) -> int:
    """
    Calculate recommended QUERY_MAXIMUM_RESULTS setting for Weaviate.
    
    Applies conservative scaling rules to avoid query limit errors while
    maintaining performance:
    - Minimum baseline: 50,000 records
    - Scaling factor: 1.2x total records
    - Maximum cap: 1,000,000 records
    
    Args:
        total: Total number of records in the collection
        
    Returns:
        Recommended QUERY_MAXIMUM_RESULTS value
        
    Examples:
        >>> _suggest_qmr(10000)
        50000
        >>> _suggest_qmr(100000)
        120000
    """
    base = max(50_000, int(total * 1.2))
    return min(1_000_000, base)


def _warn_qmr_if_needed(collection_name: str) -> None:
    """
    Check collection size and warn if QUERY_MAXIMUM_RESULTS may be insufficient.
    
    For collections with 10,000+ records, displays a warning with recommended
    QUERY_MAXIMUM_RESULTS settings to prevent Weaviate pagination errors.
    
    Args:
        collection_name: Name of the collection to check
        
    Note:
        Non-blocking - warnings are logged but don't stop execution
        Silently continues if total count cannot be retrieved
    """
    total = _get_total_count(collection_name)
    if total is None:
        return
    
    # Warn when collection size exceeds typical QMR limits
    if total >= 10_000:
        rec = _suggest_qmr(total)
        logger.warning(
            f"[Hint] {collection_name} contains ~{total:,} records. "
            f"Consider setting QUERY_MAXIMUM_RESULTS ≥ {rec:,} in Weaviate "
            f"to avoid 'invalid pagination params: query maximum results exceeded' errors."
        )
        logger.warning(
            "  See Weaviate docs: Increase limit via QUERY_MAXIMUM_RESULTS env var. "
            "Only increase as needed to avoid performance impact."
        )


# ============================================================================
# Core Operations
# ============================================================================


def do_delete(collections: List[str], show: bool = False) -> None:
    """
    Delete preprocessed metadata for specified collections.
    
    Args:
        collections: List of collection names to delete metadata for
        show: If True, display detailed status after each deletion
    """
    start_time = datetime.now()
    logger.info("=" * 70)
    logger.info("STARTING PREPROCESSED COLLECTION DELETION")
    logger.info("=" * 70)

    for idx, name in enumerate(collections, 1):
        logger.info(f"\n[{idx}/{len(collections)}] Deleting: {name}")

        exists = preprocessed_collection_exists(name)
        if exists:
            delete_preprocessed_collection(collection_name=name)
            logger.info(f"  ✓ Deleted '{name}'")
        else:
            logger.info(f"  • Skipped '{name}' (not preprocessed)")

        if show:
            still_exists = preprocessed_collection_exists(name)
            print(f"\n[DELETED] {name} - Still exists: {still_exists}\n")

    # Summary
    total_duration = (datetime.now() - start_time).total_seconds()
    logger.info(f"\n✓ Completed in {total_duration:.2f}s - {len(collections)} collections")


def do_preprocess(
    collections: List[str],
    force: bool = False,
    show: bool = False,
) -> None:
    """
    Preprocess Elysia collections with LLM-generated summaries and mappings.
    
    Args:
        collections: List of collection names to preprocess
        force: If True, reprocess even if metadata already exists
        show: If True, display detailed collection info after processing
    """
    start_time = datetime.now()
    logger.info("=" * 70)
    logger.info("STARTING COLLECTION PREPROCESSING")
    logger.info("=" * 70)

    for idx, name in enumerate(collections, 1):
        logger.info(f"\n[{idx}/{len(collections)}] Processing: {name}")

        # Warn about potential QMR issues
        _warn_qmr_if_needed(name)

        exists = preprocessed_collection_exists(name)
        if (not exists) or force:
            preprocess(collection_names=[name], force=force)
            logger.info(f"  ✓ Preprocessed '{name}'")
        else:
            logger.info(f"  • Skipped '{name}' (use --force to reprocess)")

        if show:
            view_result = view_preprocessed_collection(collection_name=name)
            print(f"\n{'='*60}\n{name}\n{'='*60}\n{view_result}\n")

    # Summary
    total_duration = (datetime.now() - start_time).total_seconds()
    logger.info(f"\n✓ Completed in {total_duration:.2f}s - {len(collections)} collections")


# ============================================================================
# Command Line Interface
# ============================================================================


def main():
    """
    Main entry point for the preprocessing script.
    
    Subcommands: preprocess (default), delete, view
    """
    parser = argparse.ArgumentParser(
        description="Elysia Collection Preprocessing Tool for Meal Agent"
    )
    
    # Subcommands
    subparsers = parser.add_subparsers(dest="command", help="Available commands")
    
    # Preprocess subcommand
    preprocess_parser = subparsers.add_parser("preprocess", help="Preprocess collections")
    preprocess_parser.add_argument("-c", "--collections", nargs="+", default=DEFAULT_COLLECTIONS)
    preprocess_parser.add_argument("--all", action="store_true")
    preprocess_parser.add_argument("--force", action="store_true")
    preprocess_parser.add_argument("--show", action="store_true")
    
    # Delete subcommand
    delete_parser = subparsers.add_parser("delete", help="Delete metadata")
    delete_parser.add_argument("-c", "--collections", nargs="+", default=DEFAULT_COLLECTIONS)
    delete_parser.add_argument("--all", action="store_true")
    delete_parser.add_argument("--show", action="store_true")
    
    # View subcommand
    view_parser = subparsers.add_parser("view", help="View metadata")
    view_parser.add_argument("-c", "--collections", nargs="+", required=True)
    
    # Backward compatibility (no subcommand)
    parser.add_argument("-c", "--collections", nargs="+", default=DEFAULT_COLLECTIONS)
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--show", action="store_true")
    
    args = parser.parse_args()
    command = args.command if args.command else "preprocess"
    
    # Execute command
    try:
        if command == "delete":
            cols = DEFAULT_COLLECTIONS if args.all else args.collections
            logger.info(f"🗑️  Deleting metadata: {cols}")
            do_delete(collections=cols, show=args.show)
            
        elif command == "view":
            logger.info(f"👁️  Viewing metadata: {args.collections}")
            for name in args.collections:
                if preprocessed_collection_exists(name):
                    result = view_preprocessed_collection(collection_name=name)
                    print(f"\n{'='*60}\n{name}\n{'='*60}\n{result}\n")
                else:
                    print(f"\n⚠️  '{name}' not preprocessed yet.\n")
            
        else:  # preprocess
            cols = DEFAULT_COLLECTIONS if args.all else args.collections
            logger.info(f"🔧 Preprocessing: {cols}")
            do_preprocess(collections=cols, force=args.force, show=args.show)
            
        logger.info("✓ Completed successfully!")
        
    except KeyboardInterrupt:
        logger.warning("\n⚠️  User interrupted (Ctrl+C)")
        return 130
    except Exception as e:
        logger.error(f"✗ Error: {e}", exc_info=True)
        raise


if __name__ == "__main__":
    main()
