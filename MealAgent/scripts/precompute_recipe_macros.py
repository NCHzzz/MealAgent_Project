#!/usr/bin/env python3
"""
Script to precompute nutrition macros for all recipes in Weaviate.

This script:
1. Fetches all recipes from Weaviate
2. Identifies recipes missing macros_per_serving
3. Calculates macros for missing recipes
4. Updates recipes in Weaviate with calculated macros
5. (Optional) Validates all recipes with macros using LLM

Usage:
    python -m MealAgent.scripts.precompute_recipe_macros [--limit N] [--batch-size N] [--resume] [--validate]
    
Options:
    --limit N: Maximum number of recipes to process (default: all)
    --batch-size N: Number of recipes to process in each batch (default: 10)
    --resume: Skip recipes that already have macros_per_serving
    --dry-run: Show what would be done without actually updating
    --validate: After calculating, validate all recipes with macros using LLM
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
from elysia.util.elysia_chain_of_thought import ElysiaChainOfThought
from dspy import LM
import dspy
import json
from datetime import timezone

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


async def extract_recipe_metadata(
    recipe: Dict[str, Any],
    base_lm: Optional[LM],
    tree_data: TreeData,
) -> Optional[Dict[str, Any]]:
    """
    Extract diet_type, allergens, and devices from recipe using LLM.
    Returns dict with keys: diet_type (list), allergens (list), devices (list)
    """
    if base_lm is None:
        return None

    dish_name = recipe.get("dish_name", "")
    ingredients_raw = recipe.get("ingredients_with_qty") or recipe.get("ingredients", [])
    cooking_method = recipe.get("cooking_method_array") or []
    
    # Truncate ingredients for token optimization
    ingredients = _truncate_ingredients(ingredients_raw, max_items=15, max_length=600)
    cooking_method_str = ", ".join(str(m) for m in cooking_method[:5])  # Limit to 5 methods

    class RecipeMetadataSignature(dspy.Signature):
        """
        Extract dietary metadata from a Vietnamese recipe.
        
        Respond with:
          - diet_type: List of applicable diet types (e.g., ["vegetarian", "vegan", "keto", "paleo", "halal", "kosher", "gluten-free", "dairy-free", "none"])
          - allergens: List of allergens present (e.g., ["peanuts", "tree_nuts", "dairy", "eggs", "fish", "shellfish", "soy", "wheat", "sesame", "none"])
          - devices: List of required cooking devices/equipment (e.g., ["oven", "stovetop", "microwave", "blender", "food_processor", "air_fryer", "pressure_cooker", "none"])
        
        Use lowercase, underscore-separated values. Return "none" if no applicable items.
        """

        dish_name = dspy.InputField(description="Vietnamese dish name.")
        ingredients = dspy.InputField(description="List of ingredients (truncated for efficiency).")
        cooking_method = dspy.InputField(description="Cooking methods used.")
        diet_type = dspy.OutputField(description='JSON array of diet types, e.g. ["vegetarian", "none"]')
        allergens = dspy.OutputField(description='JSON array of allergens, e.g. ["dairy", "eggs", "none"]')
        devices = dspy.OutputField(description='JSON array of required devices, e.g. ["oven", "stovetop", "none"]')

    cot = ElysiaChainOfThought(
        RecipeMetadataSignature,
        tree_data=tree_data,
        reasoning=False,
        impossible=False,
        message_update=False,
    )

    try:
        pred = await cot.aforward(
            lm=base_lm,
            dish_name=dish_name,
            ingredients=ingredients,
            cooking_method=cooking_method_str,
        )

        # Parse JSON responses
        diet_type_list = []
        allergens_list = []
        devices_list = []

        if pred.diet_type:
            try:
                diet_type_list = json.loads(pred.diet_type)
                if not isinstance(diet_type_list, list):
                    diet_type_list = [diet_type_list] if diet_type_list else []
            except Exception:
                # Fallback: try to extract from string
                diet_type_str = str(pred.diet_type).strip().lower()
                if diet_type_str and diet_type_str != "none":
                    diet_type_list = [d.strip() for d in diet_type_str.replace("[", "").replace("]", "").split(",")]

        if pred.allergens:
            try:
                allergens_list = json.loads(pred.allergens)
                if not isinstance(allergens_list, list):
                    allergens_list = [allergens_list] if allergens_list else []
            except Exception:
                allergens_str = str(pred.allergens).strip().lower()
                if allergens_str and allergens_str != "none":
                    allergens_list = [a.strip() for a in allergens_str.replace("[", "").replace("]", "").split(",")]

        if pred.devices:
            try:
                devices_list = json.loads(pred.devices)
                if not isinstance(devices_list, list):
                    devices_list = [devices_list] if devices_list else []
            except Exception:
                devices_str = str(pred.devices).strip().lower()
                if devices_str and devices_str != "none":
                    devices_list = [d.strip() for d in devices_str.replace("[", "").replace("]", "").split(",")]

        # Filter out "none" values
        diet_type_list = [d for d in diet_type_list if d and d.lower() != "none"]
        allergens_list = [a for a in allergens_list if a and a.lower() != "none"]
        devices_list = [d for d in devices_list if d and d.lower() != "none"]

        return {
            "diet_type": diet_type_list if diet_type_list else [],
            "allergens": allergens_list if allergens_list else [],
            "devices": devices_list if devices_list else [],
        }
    except Exception as e:
        logger.warning(f"Failed to extract metadata for recipe {recipe.get('food_id')}: {e}")
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


async def update_recipe_metadata(
    recipe: Dict[str, Any],
    metadata: Dict[str, Any],
    client_manager: ClientManager,
) -> bool:
    """Update recipe in Weaviate with metadata (diet_type, allergens, devices)."""
    try:
        with client_manager.connect_to_client() as client:
            collection = client.collections.get("Recipe")
            
            uuid = recipe.get("_uuid")
            if not uuid:
                logger.warning(f"Recipe missing UUID: {recipe.get('dish_name', 'Unknown')}")
                return False
            
            update_props = {}
            if metadata.get("diet_type"):
                update_props["diet_type"] = metadata["diet_type"]
            if metadata.get("allergens"):
                update_props["allergens"] = metadata["allergens"]
            if metadata.get("devices"):
                update_props["devices"] = metadata["devices"]
            
            if update_props:
                collection.data.update(uuid=uuid, properties=update_props)
            
            return True
    except Exception as e:
        logger.error(f"Error updating recipe metadata {recipe.get('food_id')}: {e}")
        return False


async def process_recipes(
    recipes: List[Dict[str, Any]],
    client_manager: ClientManager,
    base_lm: Optional[LM],
    batch_size: int = 10,
    dry_run: bool = False,
    enrich_metadata: bool = True,
    metadata_every: int = 50,
    validate_every: int = 0,
    token_report_interval: int = 100,
) -> Dict[str, int]:
    """
    Process recipes in batches, calculating and updating macros.
    
    Args:
        enrich_metadata: If True, also extract and update diet_type, allergens, devices using LLM
        metadata_every: Run metadata extraction every N recipes (default 50)
        validate_every: If >0, run inline validation on chunks of that size
        token_report_interval: Log token usage deltas every N processed recipes
    """
    stats = {
        "total": len(recipes),
        "processed": 0,
        "success": 0,
        "failed": 0,
        "skipped": 0,
        "metadata_enriched": 0,
        "metadata_skipped_due_to_frequency": 0,
    }
    
    # For inline validation and token reporting
    recent_for_validation: List[Dict[str, Any]] = []
    next_token_report = token_report_interval if token_report_interval > 0 else None
    last_token_total = (
        _compute_token_usage(base_lm)["total_tokens"] if base_lm else 0
    )
    
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
        
        if dry_run:
            for recipe in batch:
                stats["processed"] += 1
                dish_name = _sanitize_text(recipe.get("dish_name", "Unknown"))
                logger.info(f"[{stats['processed']}/{stats['total']}] {dish_name}: [DRY RUN] Would process")
                stats["success"] += 1
            continue

        for recipe in batch:
            stats["processed"] += 1
            food_id = recipe.get("food_id")
            dish_name = recipe.get("dish_name", "Unknown")
            safe_dish_name = _sanitize_text(dish_name)
            logger.info(
                f"[{stats['processed']}/{stats['total']}] Processing: "
                f"{safe_dish_name} (ID: {_sanitize_text(food_id)})"
            )
            
            ingredients = recipe.get("ingredients_with_qty") or recipe.get("ingredients", [])
            if not ingredients:
                logger.warning("  WARNING: Recipe has no ingredients, skipping...")
                stats["skipped"] += 1
                continue
            
            macros = await calculate_macros_for_recipe(
                recipe,
                tree_data,
                client_manager,
                base_lm,
            )
            
            if not macros:
                logger.warning("  FAILED to calculate macros")
                stats["failed"] += 1
                continue
            
            success = await update_recipe_macros(recipe, macros, client_manager)
            
            if not success:
                logger.warning("  FAILED to update recipe macros in Weaviate")
                stats["failed"] += 1
                continue
            
            if enrich_metadata and base_lm:
                has_metadata = (
                    recipe.get("diet_type") or 
                    recipe.get("allergens") or 
                    recipe.get("devices")
                )
                
                if not has_metadata:
                    metadata_obj = None
                    if metadata_every > 1 and (stats["processed"] % metadata_every) != 0:
                        logger.info(
                            f"  Skipping metadata extraction (only every {metadata_every} recipe)"
                        )
                        stats["metadata_skipped_due_to_frequency"] += 1
                    else:
                        logger.info("  Extracting metadata (diet_type, allergens, devices)...")
                        metadata_obj = await extract_recipe_metadata(recipe, base_lm, tree_data)
                    
                    if metadata_obj:
                        metadata_success = await update_recipe_metadata(recipe, metadata_obj, client_manager)
                        if metadata_success:
                            diet_str = ", ".join(metadata_obj.get("diet_type", [])) or "none"
                            allergen_str = ", ".join(metadata_obj.get("allergens", [])) or "none"
                            devices_str = ", ".join(metadata_obj.get("devices", [])) or "none"
                            logger.info(
                                f"  Metadata: diet={diet_str}, allergens={allergen_str}, devices={devices_str}"
                            )
                            stats["metadata_enriched"] += 1
                        else:
                            logger.warning("  Failed to update recipe metadata")
                    elif metadata_obj is not None:
                        logger.warning("  Failed to extract recipe metadata")
                else:
                    logger.debug("  Metadata already exists, skipping extraction")
            
            logger.info(
                f"  SUCCESS: Macros {macros.get('kcal', 0):.0f} kcal, "
                f"{macros.get('protein_g', 0):.1f}g protein"
            )
            stats["success"] += 1
            recent_for_validation.append(recipe)
            
            if (
                token_report_interval > 0
                and next_token_report is not None
                and stats["processed"] >= next_token_report
            ):
                total_tokens_now = (
                    _compute_token_usage(base_lm)["total_tokens"] if base_lm else 0
                )
                delta = total_tokens_now - last_token_total
                logger.info(
                    "[Token usage] %d recipes processed -> +%d tokens (total %d).",
                    stats["processed"],
                    delta,
                    total_tokens_now,
                )
                last_token_total = total_tokens_now
                next_token_report += token_report_interval
            
            if validate_every > 0 and len(recent_for_validation) >= validate_every and base_lm:
                chunk = list(recent_for_validation)
                recent_for_validation.clear()
                validation_stats = await validate_recipes(
                    chunk,
                    client_manager,
                    base_lm,
                    batch_size=min(validate_every, len(chunk)),
                    dry_run=dry_run,
                )
                logger.info(
                    "[Validation] Chunk completed: OK=%d, adjusted=%d, skipped=%d, failed=%d",
                    validation_stats["ok"],
                    validation_stats["adjusted"],
                    validation_stats["skipped"],
                    validation_stats["failed"],
                )
        
        # Progress summary
        logger.info(f"\nBatch {batch_num} complete. Progress: {stats['success']} success, "
                   f"{stats['failed']} failed, {stats['skipped']} skipped")
    
    if validate_every > 0 and base_lm and recent_for_validation:
        validation_stats = await validate_recipes(
            recent_for_validation,
            client_manager,
            base_lm,
            batch_size=min(validate_every, len(recent_for_validation)),
            dry_run=dry_run,
        )
        logger.info(
            "[Validation] Final chunk completed: OK=%d, adjusted=%d, skipped=%d, failed=%d",
            validation_stats["ok"],
            validation_stats["adjusted"],
            validation_stats["skipped"],
            validation_stats["failed"],
        )
    
    return stats


def _truncate_ingredients(ingredients: List[Any], max_items: int = 15, max_length: int = 600) -> str:
    """
    Truncate ingredients list to reduce token usage while preserving important information.
    
    Strategy:
    - Keep high-calorie ingredients (oils, fats, sugars) even if they're later in the list
    - Prioritize first items (usually main ingredients)
    - Ensure we capture key macro contributors
    """
    if not ingredients:
        return ""
    
    # Convert to strings
    ing_strs = [str(item).lower() for item in ingredients]
    
    # Identify high-calorie keywords that should be prioritized
    high_calorie_keywords = [
        'dầu', 'oil', 'mỡ', 'fat', 'bơ', 'butter', 'đường', 'sugar', 
        'đường', 'sweet', 'kem', 'cream', 'phô mai', 'cheese', 'sữa', 'milk',
        'thịt mỡ', 'fatty', 'chiên', 'fried', 'xào', 'stir-fried'
    ]
    
    # Separate into priority and regular ingredients
    priority_ings = []
    regular_ings = []
    
    for i, ing in enumerate(ing_strs):
        is_priority = any(keyword in ing for keyword in high_calorie_keywords)
        if is_priority:
            priority_ings.append((i, str(ingredients[i])))  # Keep original format
        else:
            regular_ings.append((i, str(ingredients[i])))
    
    # Combine: priority items first, then regular items up to max_items
    selected = []
    selected_indices = set()
    
    # Add priority items (up to max_items)
    for idx, ing in priority_ings[:max_items]:
        selected.append(ing)
        selected_indices.add(idx)
    
    # Fill remaining slots with regular items
    remaining_slots = max_items - len(selected)
    for idx, ing in regular_ings:
        if remaining_slots <= 0:
            break
        if idx not in selected_indices:
            selected.append(ing)
            selected_indices.add(idx)
            remaining_slots -= 1
    
    result = "\n".join(selected)
    
    # If still too long, truncate intelligently
    if len(result) > max_length:
        # Try to keep complete items
        lines = result.split('\n')
        truncated = []
        current_length = 0
        for line in lines:
            if current_length + len(line) + 1 <= max_length - 20:  # Reserve space for "..."
                truncated.append(line)
                current_length += len(line) + 1
            else:
                break
        result = "\n".join(truncated)
        if len(ingredients) > len(truncated):
            result += f"\n... (+{len(ingredients) - len(truncated)} more ingredients)"
    
    return result


def _truncate_cooking_notes(notes: str, max_length: int = 250) -> str:
    """
    Truncate cooking notes to reduce token usage while preserving key cooking methods.
    
    Priority: Keep cooking methods that affect macros (fried, deep-fried, etc.)
    """
    if not notes:
        return ""
    if len(notes) <= max_length:
        return notes
    
    # Check if important cooking methods are mentioned
    important_methods = ['chiên', 'fried', 'deep-fried', 'xào', 'stir-fried', 'rán', 'nướng', 'grilled']
    notes_lower = notes.lower()
    
    # If important methods are in the first part, keep more context
    important_found = any(method in notes_lower[:max_length] for method in important_methods)
    
    if important_found:
        # Try to keep complete sentences
        truncated = notes[:max_length]
        # Find last sentence boundary
        last_period = truncated.rfind('.')
        last_exclamation = truncated.rfind('!')
        last_question = truncated.rfind('?')
        last_sentence = max(last_period, last_exclamation, last_question)
        
        if last_sentence > max_length * 0.7:  # If sentence boundary is reasonably close
            truncated = notes[:last_sentence + 1]
        
        return truncated + "..."
    
    return notes[:max_length] + "..."


def _should_skip_validation(recipe: Dict[str, Any], macros: Dict[str, float], strict_mode: bool = False) -> bool:
    """
    Heuristic to skip validation for recipes with obviously reasonable macros.
    This saves tokens by not validating recipes that are clearly fine.
    
    Args:
        strict_mode: If True, only skip very obvious cases (higher quality, more tokens)
    
    Returns:
        True if validation can be skipped, False if validation is needed
    """
    if strict_mode:
        # In strict mode, only skip if macros are perfect
        return False
    
    kcal = macros.get("kcal", 0)
    protein = macros.get("protein_g", 0)
    fat = macros.get("fat_g", 0)
    carb = macros.get("carb_g", 0)
    
    # Never skip if macros are zero or negative
    if kcal <= 0 or protein < 0 or fat < 0 or carb < 0:
        return False
    
    # Never skip if macros are extremely high (might be calculation error)
    if kcal > 1500:  # Very high calorie dishes should be validated
        return False
    
    # Never skip if macros are extremely low (might be missing data)
    if kcal < 50:  # Very low calorie might indicate missing ingredients
        return False
    
    # Check if macros make sense (protein + carbs + fat should roughly match kcal)
    # 1g protein = 4 kcal, 1g carb = 4 kcal, 1g fat = 9 kcal
    calculated_kcal = (protein * 4) + (carb * 4) + (fat * 9)
    
    # More lenient check: macros should be in reasonable range AND match calculated kcal
    # Typical range: 150-1000 kcal per serving (wider range for diverse dishes)
    if 150 <= kcal <= 1000:
        # Allow 25% variance for calculated kcal (some dishes have fiber, alcohol, etc.)
        if 0.75 * calculated_kcal <= kcal <= 1.25 * calculated_kcal:
            # Additional check: individual macros should be reasonable
            # Protein: typically 10-50g per serving
            # Fat: typically 5-50g per serving  
            # Carb: typically 20-100g per serving
            if (10 <= protein <= 80 and 5 <= fat <= 80 and 10 <= carb <= 150):
                return True  # Skip - macros look reasonable
    
    return False  # Validate - macros might be off


async def _validate_macros_with_lm(
    recipe: Dict[str, Any],
    base_lm: Optional[LM],
    tree_data: TreeData,
) -> Optional[Dict[str, Any]]:
    """Validate recipe macros using LLM with optimized token usage."""
    if base_lm is None:
        return None

    macros = recipe.get("macros_per_serving", {})
    servings = float(recipe.get("serving_size", 1.0) or 1.0)
    if servings <= 0:
        servings = 1.0

    # Optimize: Truncate ingredients and cooking notes to reduce tokens
    # But preserve important information (high-calorie ingredients, cooking methods)
    ingredients_raw = recipe.get("ingredients_with_qty") or recipe.get("ingredients", [])
    ingredients = _truncate_ingredients(ingredients_raw, max_items=15, max_length=600)
    
    cooking_notes_raw = recipe.get("cooking_method") or recipe.get("instructions", "")
    cooking_notes = _truncate_cooking_notes(cooking_notes_raw, max_length=250)

    class MacroAuditSignature(dspy.Signature):
        """
        Review whether the provided macros per serving are realistic for the dish.

        Respond with:
          - verdict: "ok" if macros look reasonable, otherwise "adjust".
          - reason: short explanation (<= 2 sentences).
          - macros_adjusted: JSON object with fields kcal, protein_g, fat_g, carb_g (per serving) if verdict == "adjust".
        """

        dish_name = dspy.InputField(description="Vietnamese dish name.")
        servings = dspy.InputField(description="Number of servings the recipe yields.")
        ingredients = dspy.InputField(description="List of ingredients with quantities.")
        macros = dspy.InputField(description="Existing macros per serving (kcal, protein_g, fat_g, carb_g).")
        cooking_notes = dspy.InputField(description="Cooking method or notable preparation details.")
        verdict = dspy.OutputField(description='Either "ok" or "adjust".')
        reason = dspy.OutputField(description="Short justification of the verdict.")
        macros_adjusted = dspy.OutputField(description="JSON string with revised macros if verdict == 'adjust'.")

    cot = ElysiaChainOfThought(
        MacroAuditSignature,
        tree_data=tree_data,
        reasoning=False,
        impossible=False,
        message_update=False,
    )

    pred = await cot.aforward(
        lm=base_lm,
        dish_name=recipe.get("dish_name", ""),
        servings=servings,
        ingredients=ingredients,  # Already truncated
        macros=macros,
        cooking_notes=cooking_notes,  # Already truncated
    )

    verdict = (pred.verdict or "").strip().lower()
    reason = (pred.reason or "").strip()
    macros_adjusted = None

    if verdict == "adjust" and pred.macros_adjusted:
        try:
            candidate = json.loads(pred.macros_adjusted)
            parsed = {
                "kcal": float(candidate.get("kcal", 0.0)),
                "protein_g": float(candidate.get("protein_g", 0.0)),
                "fat_g": float(candidate.get("fat_g", 0.0)),
                "carb_g": float(candidate.get("carb_g", 0.0)),
            }
            macros_adjusted = parsed
        except Exception as exc:
            logger.warning(
                f"LM returned invalid macros_adjusted JSON for recipe {recipe.get('food_id')}: {exc}"
            )

    return {
        "verdict": verdict or "unknown",
        "reason": reason,
        "macros_adjusted": macros_adjusted,
    }


async def _update_validated_macros(
    recipe: Dict[str, Any],
    macros: Dict[str, float],
    reason: str,
    client_manager: ClientManager,
) -> bool:
    """Update recipe with validated macros."""
    try:
        with client_manager.connect_to_client() as client:
            collection = client.collections.get("Recipe")
            uuid = recipe.get("_uuid")
            if not uuid:
                logger.warning(
                    f"Cannot update macros for recipe {recipe.get('food_id')}: missing UUID"
                )
                return False

            metadata = {
                "macros_per_serving": macros,
                "macro_validation_note": reason or "Adjusted by validation script",
                "macro_validated_at": datetime.now(timezone.utc).isoformat(),
            }

            collection.data.update(uuid=uuid, properties=metadata)
            return True
    except Exception as exc:
        logger.error(
            f"Error updating macros for recipe {recipe.get('food_id')}: {exc}"
        )
        return False


async def validate_recipes(
    recipes: List[Dict[str, Any]],
    client_manager: ClientManager,
    base_lm: Optional[LM],
    batch_size: int = 10,
    dry_run: bool = False,
    skip_reasonable: bool = True,
    strict_quality: bool = False,
) -> Dict[str, int]:
    """
    Validate recipes with macros using LLM with token optimization.
    
    Args:
        skip_reasonable: Skip validation for recipes with obviously reasonable macros (saves tokens)
        strict_quality: If True, disable heuristic skipping for maximum quality (uses more tokens)
    """
    stats = {
        "total": len(recipes),
        "processed": 0,
        "ok": 0,
        "adjusted": 0,
        "skipped": 0,
        "failed": 0,
        "skipped_reasonable": 0,
    }

    collection_data = CollectionData(collection_names=[])
    atlas = Atlas()
    environment = Environment(environment={}, self_info=False)
    tree_data = TreeData(
        collection_data=collection_data,
        atlas=atlas,
        environment=environment,
    )

    logger.info(f"\n{'='*60}")
    logger.info("VALIDATION PHASE")
    logger.info(f"{'='*60}")
    logger.info(f"Validating {len(recipes)} recipes in batches of {batch_size}...")

    for batch_idx in range(0, len(recipes), batch_size):
        batch = recipes[batch_idx : batch_idx + batch_size]
        batch_num = (batch_idx // batch_size) + 1
        total_batches = (len(recipes) + batch_size - 1) // batch_size

        logger.info(f"\n{'='*60}")
        logger.info(f"Validation batch {batch_num}/{total_batches} ({len(batch)} recipes)")
        logger.info(f"{'='*60}")

        for recipe in batch:
            stats["processed"] += 1
            dish_name = _sanitize_text(recipe.get("dish_name"))
            food_id = _sanitize_text(recipe.get("food_id"))
            logger.info(
                f"[{stats['processed']}/{stats['total']}] Validating {dish_name} (ID: {food_id})"
            )

            macros = recipe.get("macros_per_serving")
            if not macros:
                logger.warning("  Skipping: no macros stored.")
                stats["skipped"] += 1
                continue

            # Token optimization: Skip validation if macros look obviously reasonable
            # But only if strict_quality is False (prioritize quality over token savings)
            if skip_reasonable and not strict_quality and _should_skip_validation(recipe, macros, strict_mode=False):
                logger.debug(f"  Skipping validation: macros look reasonable (saving tokens)")
                stats["skipped_reasonable"] += 1
                stats["ok"] += 1  # Count as OK since we're skipping
                continue

            result = await _validate_macros_with_lm(recipe, base_lm, tree_data)
            if not result:
                logger.info("  No LM verdict available, treated as OK.")
                stats["ok"] += 1
                continue

            verdict = result["verdict"]
            reason = result["reason"]
            macros_adjusted = result["macros_adjusted"]

            if verdict != "adjust" or not macros_adjusted:
                logger.info(f"  ✅ LLM verdict: OK ({reason or 'no issues found'})")
                stats["ok"] += 1
                continue

            logger.warning(
                f"  ⚠️ LLM suggests adjustment ({reason}). New macros: {macros_adjusted}"
            )

            if dry_run:
                logger.info("  [DRY RUN] Would update macros with LLM suggestion.")
                stats["adjusted"] += 1
                continue

            success = await _update_validated_macros(
                recipe,
                macros_adjusted,
                reason,
                client_manager,
            )
            if success:
                logger.info(f"  ✅ Updated recipe {food_id} with LLM-adjusted macros.")
                stats["adjusted"] += 1
            else:
                logger.warning(f"  FAILED to update recipe {food_id}.")
                stats["failed"] += 1

    return stats


async def main():
    parser = argparse.ArgumentParser(
        description="Precompute nutrition macros and essential metadata for recipes"
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
        help="Show what would be done without actually updating Weaviate"
    )
    parser.add_argument(
        "--no-enrich-metadata",
        action="store_false",
        dest="enrich_metadata",
        default=True,
        help="Skip metadata enrichment to save LM calls"
    )
    parser.add_argument(
        "--metadata-every",
        type=int,
        default=50,
        help="Only run metadata enrichment every N recipes (default: 50)"
    )
    parser.add_argument(
        "--validate-every",
        type=int,
        default=0,
        help="Automatically run LLM validation after every N processed recipes (0 disables)"
    )
    parser.add_argument(
        "--validate",
        action="store_true",
        help="After calculating macros, validate cached macros with the LM"
    )
    
    args = parser.parse_args()
    
    metadata_every = max(1, args.metadata_every)
    
    logger.info("="*60)
    logger.info("Recipe Macros Precomputation Script")
    logger.info("="*60)
    logger.info(
        "Options: limit=%s, batch_size=%s, resume=%s, dry_run=%s, enrich_metadata=%s, metadata_every=%s, validate_every=%s",
        args.limit,
        args.batch_size,
        args.resume,
        args.dry_run,
        args.enrich_metadata,
        metadata_every,
        max(0, args.validate_every),
    )
    
    # Initialize components
    logger.info("\nInitializing components...")
    client_manager = init_client_manager()
    base_lm = init_base_lm()
    
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
        enrich_metadata=args.enrich_metadata,
        metadata_every=metadata_every,
        validate_every=max(0, args.validate_every),
    )
    end_time = datetime.now()
    duration = (end_time - start_time).total_seconds()

    # Token usage summary (if LM tracked it)
    usage = _compute_token_usage(base_lm)
    
    # Final summary for calculation phase
    logger.info("\n" + "="*60)
    logger.info("CALCULATION PHASE SUMMARY")
    logger.info("="*60)
    logger.info(f"Total recipes: {stats['total']}")
    logger.info(f"Successfully processed: {stats['success']}")
    logger.info(f"Failed: {stats['failed']}")
    logger.info(f"Skipped: {stats['skipped']}")
    if stats.get('metadata_enriched', 0) > 0:
        logger.info(f"Metadata enriched: {stats['metadata_enriched']}")
    if stats.get("metadata_skipped_due_to_frequency", 0) > 0:
        logger.info(
            f"Metadata skipped (frequency control): {stats['metadata_skipped_due_to_frequency']}"
        )
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

