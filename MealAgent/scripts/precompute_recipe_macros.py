#!/usr/bin/env python3
"""
Script to precompute nutrition macros for all recipes in Weaviate.

This script:
1. Fetches all recipes from Weaviate
2. Identifies recipes missing macros_per_serving
3. Calculates macros for missing recipes
4. Updates recipes in Weaviate with calculated macros

Usage:
    python -m MealAgent.scripts.precompute_recipe_macros [--limit N] [--batch-size N] [--resume]
    
Options:
    --limit N: Maximum number of recipes to process (default: all)
    --batch-size N: Number of recipes to process in each batch (default: 10)
    --resume: Skip recipes that already have macros_per_serving
    --dry-run: Show what would be done without actually updating
"""

import argparse
import asyncio
import logging
import sys
import unicodedata
from typing import Dict, Any, List, Optional
from datetime import datetime

# Add parent directory to path for imports
import os
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.abspath(os.path.join(script_dir, '../..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from elysia.util.client import ClientManager
from elysia.config import settings, load_base_lm
from elysia.tree.objects import TreeData, CollectionData, Atlas, Environment
from dspy import LM
import dspy

from MealAgent.tools.nutrition.calculate_recipe_macros import calculate_recipe_macros_tool
from elysia.objects import Result, Error, Response

from dotenv import load_dotenv
load_dotenv()

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(f'precompute_macros_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log')
    ]
)
logger = logging.getLogger(__name__)


def init_base_lm(model_override: Optional[str] = None, api_key_override: Optional[str] = None) -> Optional[LM]:
    """
    Initialize base_lm in a way that matches how Elysia configures models.

    Priority:
      1. If CLI overrides are provided, use them directly (backwards compatible).
      2. Otherwise, defer to Elysia's `load_base_lm(settings)`, which respects
         BASE_MODEL, BASE_PROVIDER, MODEL_API_BASE and all *_API_KEY env vars.
    """
    try:
        # Path 1: explicit CLI overrides (keep old behaviour for power users)
        if model_override or api_key_override:
            model = (
                model_override
                or getattr(settings, "BASE_MODEL", None)
                or os.getenv("OPENAI_MODEL")
                or os.getenv("ANTHROPIC_MODEL")
                or os.getenv("GEMINI_MODEL")
                or "gpt-4o-mini"
            )
            api_key = (
                api_key_override
                or os.getenv("OPENAI_API_KEY")
                or os.getenv("ANTHROPIC_API_KEY")
                or os.getenv("GEMINI_API_KEY")
            )

            if not api_key:
                logger.info(
                    "LM API key not provided for override model. "
                    "Running in fallback mode (recipes requiring translation may fail)."
                )
                return None

            base_lm = dspy.LM(model=model, api_key=api_key)
            logger.info(f"Initialized override base_lm with model: {model}")
            return base_lm

        # Path 2: mirror MealAgent/Elysia behaviour via global `settings`
        # This will:
        #   - read BASE_MODEL, BASE_PROVIDER, MODEL_API_BASE from env
        #   - pick the correct provider string (e.g. 'gemini', 'openrouter/google')
        #   - use the right API key from settings.API_KEYS (e.g. GEMINI_API_KEY)
        base_lm = load_base_lm(settings)
        logger.info(
            "Initialized base_lm via Elysia settings: provider=%s, model=%s",
            settings.BASE_PROVIDER,
            settings.BASE_MODEL,
        )
        return base_lm
    except Exception as e:
        logger.error(f"Failed to initialize base_lm: {e}")
        return None


def init_client_manager() -> ClientManager:
    """Initialize ClientManager from environment settings."""
    return ClientManager(
        wcd_url=os.getenv("WEAVIATE_URL"),
        wcd_api_key=os.getenv("WEAVIATE_API_KEY"),
        weaviate_is_local=os.getenv("WEAVIATE_IS_LOCAL", "true").lower() == "true",
        local_weaviate_port=int(os.getenv("WEAVIATE_PORT", "8078")),
        local_weaviate_grpc_port=int(os.getenv("WEAVIATE_GRPC_PORT", "50051")),
        logger=logger,
    )


def _sanitize_text(text: str | None) -> str:
    """Return ASCII-safe version of text for Windows console logging."""
    if not text:
        return ""
    normalized = unicodedata.normalize("NFKD", str(text))
    return normalized.encode("ascii", "ignore").decode("ascii")


def _compute_token_usage(base_lm: Optional[LM]) -> Dict[str, int]:
    """
    Best-effort aggregation of token usage from the underlying LM.

    This relies on dspy / litellm attaching a `history` with usage metadata.
    If unavailable, returns zeros without failing the script.
    """
    stats = {
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
    }

    if base_lm is None:
        return stats

    history = getattr(base_lm, "history", None)
    if not history:
        return stats

    for call in history:
        usage = None
        if isinstance(call, dict):
            usage = (
                call.get("usage")
                or call.get("token_usage")
                or call.get("metadata", {}).get("usage")
            )
        else:
            usage = (
                getattr(call, "usage", None)
                or getattr(call, "token_usage", None)
                or getattr(getattr(call, "metadata", None) or {}, "usage", None)
            )

        if not usage:
            continue

        # Accept common naming variants from litellm / providers
        in_tok = (
            usage.get("input_tokens")
            or usage.get("prompt_tokens")
            or usage.get("tokens_in")
            or 0
        )
        out_tok = (
            usage.get("output_tokens")
            or usage.get("completion_tokens")
            or usage.get("tokens_out")
            or 0
        )

        try:
            stats["input_tokens"] += int(in_tok)
            stats["output_tokens"] += int(out_tok)
        except (TypeError, ValueError):
            # Ignore malformed usage entries
            continue

    stats["total_tokens"] = stats["input_tokens"] + stats["output_tokens"]
    return stats


async def fetch_all_recipes(
    client_manager: ClientManager,
    limit: Optional[int] = None,
    resume: bool = True,
) -> List[Dict[str, Any]]:
    """Fetch all recipes from Weaviate, optionally filtering out those with macros."""
    logger.info("Fetching recipes from Weaviate...")
    
    all_recipes = []
    offset = 0
    batch_size = 100
    
    with client_manager.connect_to_client() as client:
        collection = client.collections.get("Recipe")
        
        while True:
            try:
                results = collection.query.fetch_objects(limit=batch_size, offset=offset)
                
                if not results.objects:
                    break
                
                for obj in results.objects:
                    recipe = obj.properties
                    recipe["_uuid"] = obj.uuid
                    
                    if resume:
                        macros = recipe.get("macros_per_serving")
                        if macros and isinstance(macros, dict) and macros.get("kcal"):
                            continue
                    
                    all_recipes.append(recipe)
                    
                    if limit and len(all_recipes) >= limit:
                        break
                
                if limit and len(all_recipes) >= limit:
                    break
                
                offset += batch_size
                logger.info(f"Fetched {len(all_recipes)} recipes so far...")
            
            except Exception as e:
                logger.error(f"Error fetching recipes: {e}")
                break
    
    logger.info(f"Total recipes to process: {len(all_recipes)}")
    return all_recipes


async def calculate_macros_for_recipe(
    recipe: Dict[str, Any],
    tree_data: TreeData,
    client_manager: ClientManager,
    base_lm: Optional[LM],
    force_recalculate: bool = False,
) -> Optional[Dict[str, float]]:
    """Calculate macros for a single recipe."""
    food_id = recipe.get("food_id")
    if not food_id:
        logger.warning(f"Recipe missing food_id: {recipe.get('dish_name', 'Unknown')}")
        return None
    
    try:
        macros_result = None
        async for result in calculate_recipe_macros_tool(
            inputs={"recipe_id": str(food_id), "force_recalculate": force_recalculate},
            complex_lm=None,
            tree_data=tree_data,
            client_manager=client_manager,
            base_lm=base_lm,
        ):
            if isinstance(result, Result) and result.name == "macros" and result.objects:
                macros_result = result.objects[0]
                break
            elif isinstance(result, Error):
                feedback = getattr(result, "feedback", None)
                message = getattr(result, "message", None)
                err_text = feedback or message or str(result)
                logger.warning(f"Error calculating macros for recipe {food_id}: {err_text}")
                return None
        
        return macros_result
    except Exception as e:
        logger.error(f"Exception calculating macros for recipe {food_id}: {e}")
        return None


async def update_recipe_macros(
    recipe: Dict[str, Any],
    macros: Dict[str, float],
    client_manager: ClientManager,
) -> bool:
    """Update recipe in Weaviate with calculated macros."""
    try:
        with client_manager.connect_to_client() as client:
            collection = client.collections.get("Recipe")
            
            uuid = recipe.get("_uuid")
            if not uuid:
                logger.warning(f"Recipe missing UUID: {recipe.get('dish_name', 'Unknown')}")
                return False
            
            collection.data.update(
                uuid=uuid,
                properties={"macros_per_serving": macros}
            )
            
            return True
    except Exception as e:
        logger.error(f"Error updating recipe {recipe.get('food_id')}: {e}")
        return False


async def process_recipes(
    recipes: List[Dict[str, Any]],
    client_manager: ClientManager,
    base_lm: Optional[LM],
    batch_size: int = 10,
    dry_run: bool = False,
    force_recalculate: bool = False,
) -> Dict[str, int]:
    """Process recipes in batches, calculating and updating macros."""
    stats = {
        "total": len(recipes),
        "processed": 0,
        "success": 0,
        "failed": 0,
        "skipped": 0,
    }
    
    # Initialize tree_data (minimal for tool execution)
    collection_data = CollectionData(collection_names=[])
    atlas = Atlas()
    environment = Environment(environment={}, self_info=False)
    tree_data = TreeData(
        collection_data=collection_data,
        atlas=atlas,
        environment=environment,
    )
    
    logger.info(f"Processing {len(recipes)} recipes in batches of {batch_size}...")
    
    for batch_idx in range(0, len(recipes), batch_size):
        batch = recipes[batch_idx:batch_idx + batch_size]
        batch_num = (batch_idx // batch_size) + 1
        total_batches = (len(recipes) + batch_size - 1) // batch_size
        
        logger.info(f"\n{'='*60}")
        logger.info(f"Processing batch {batch_num}/{total_batches} ({len(batch)} recipes)")
        logger.info(f"{'='*60}")
        
        for recipe in batch:
            stats["processed"] += 1
            food_id = recipe.get("food_id")
            dish_name = recipe.get("dish_name", "Unknown")
            safe_dish_name = _sanitize_text(dish_name)
            logger.info(
                f"[{stats['processed']}/{stats['total']}] Processing: "
                f"{safe_dish_name} (ID: {_sanitize_text(food_id)})"
            )
            
            # Check if recipe has ingredients
            ingredients = recipe.get("ingredients_with_qty") or recipe.get("ingredients", [])
            if not ingredients:
                logger.warning("  WARNING: Recipe has no ingredients, skipping...")
                stats["skipped"] += 1
                continue
            
            if dry_run:
                logger.info("  [DRY RUN] Would calculate macros for this recipe")
                stats["success"] += 1
                continue
            
            # Calculate macros
            macros = await calculate_macros_for_recipe(
                recipe,
                tree_data,
                client_manager,
                base_lm,
                force_recalculate=force_recalculate,
            )
            
            if not macros:
                logger.warning("  FAILED to calculate macros")
                stats["failed"] += 1
                continue
            
            # Update recipe
            success = await update_recipe_macros(recipe, macros, client_manager)
            
            if success:
                logger.info(
                    f"  SUCCESS: Macros {macros.get('kcal', 0):.0f} kcal, "
                    f"{macros.get('protein_g', 0):.1f}g protein"
                )
                stats["success"] += 1
            else:
                logger.warning("  FAILED to update recipe in Weaviate")
                stats["failed"] += 1
        
        # Progress summary
        logger.info(f"\nBatch {batch_num} complete. Progress: {stats['success']} success, "
                   f"{stats['failed']} failed, {stats['skipped']} skipped")
    
    return stats


async def main():
    parser = argparse.ArgumentParser(
        description="Precompute nutrition macros for all recipes in Weaviate"
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Maximum number of recipes to process (default: all)"
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=10,
        help="Number of recipes to process in each batch (default: 10)"
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Skip recipes that already have macros_per_serving"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without actually updating"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Recalculate macros even if macros_per_serving is already cached"
    )
    parser.add_argument(
        "--lm-model",
        type=str,
        default=None,
        help="LM model to use for ingredient translation (overrides settings/environment)."
    )
    parser.add_argument(
        "--lm-api-key",
        type=str,
        default=None,
        help="API key for the LM model (optional if already set via environment)."
    )
    
    args = parser.parse_args()
    
    logger.info("="*60)
    logger.info("Recipe Macros Precomputation Script")
    logger.info("="*60)
    logger.info(
        "Options: limit=%s, batch_size=%s, resume=%s, dry_run=%s, force=%s",
        args.limit,
        args.batch_size,
        args.resume,
        args.dry_run,
        args.force,
    )
    
    # Initialize components
    logger.info("\nInitializing components...")
    client_manager = init_client_manager()
    base_lm = init_base_lm(model_override=args.lm_model, api_key_override=args.lm_api_key)
    
    if not base_lm and not args.dry_run:
        logger.warning("WARNING: No base_lm available. Recipes requiring translation will be skipped.")
    
    # Fetch recipes
    recipes = await fetch_all_recipes(
        client_manager,
        limit=args.limit,
        resume=args.resume,
    )
    
    if not recipes:
        logger.info("No recipes to process. Exiting.")
        await client_manager.close_clients()
        return
    
    # Process recipes
    start_time = datetime.now()
    stats = await process_recipes(
        recipes,
        client_manager,
        base_lm,
        batch_size=args.batch_size,
        dry_run=args.dry_run,
        force_recalculate=args.force,
    )
    end_time = datetime.now()
    duration = (end_time - start_time).total_seconds()

    # Token usage summary (if LM tracked it)
    usage = _compute_token_usage(base_lm)
    
    # Final summary
    logger.info("\n" + "="*60)
    logger.info("FINAL SUMMARY")
    logger.info("="*60)
    logger.info(f"Total recipes: {stats['total']}")
    logger.info(f"Successfully processed: {stats['success']}")
    logger.info(f"Failed: {stats['failed']}")
    logger.info(f"Skipped: {stats['skipped']}")
    logger.info(f"Time taken: {duration:.1f} seconds ({duration/60:.1f} minutes)")
    if stats['success'] > 0:
        logger.info(f"Average time per recipe: {duration/stats['success']:.1f} seconds")
    logger.info(
        "LM token usage: input_tokens=%d, output_tokens=%d, total_tokens=%d",
        usage["input_tokens"],
        usage["output_tokens"],
        usage["total_tokens"],
    )
    logger.info("="*60)
    
    await client_manager.close_clients()


if __name__ == "__main__":
    asyncio.run(main())

