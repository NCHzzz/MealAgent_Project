#!/usr/bin/env python3
"""
Script to audit and correct recipe macros using the configured LLM.

This script:
  1. Fetches recipes from Weaviate (including ones missing or with invalid macros)
  2. Groups them into batches (default 100 recipes per batch)
  3. Calls the LLM once per batch to:
       - detect macros that look unrealistic, and
       - fill in missing macros_per_serving when needed
  4. Optionally writes the LLM‑adjusted macros back to Weaviate

Usage:
    python -m MealAgent.scripts.validate_recipe_macros --limit 200 --batch-size 100 --dry-run

Options:
    --limit N       : Maximum number of recipes to inspect (default: all)
    --batch-size N  : Recipes per LLM batch (default: 100)
    --dry-run       : Only report what would change, do not update Weaviate
"""

import argparse
import asyncio
import logging
import sys
import unicodedata
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone

import os

script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.abspath(os.path.join(script_dir, "../.."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from dotenv import load_dotenv

load_dotenv()

from dspy import LM

import dspy

from elysia.config import settings, load_base_lm
from elysia.tree.objects import TreeData, CollectionData, Atlas, Environment
from elysia.util.client import ClientManager
from elysia.util.elysia_chain_of_thought import ElysiaChainOfThought

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(
            f"validate_macros_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
        ),
    ],
)
logger = logging.getLogger(__name__)


def _sanitize_text(text: str | None) -> str:
    """Return ASCII-safe version of text for Windows console logging."""
    if not text:
        return ""
    normalized = unicodedata.normalize("NFKD", str(text))
    return normalized.encode("ascii", "ignore").decode("ascii")


def _compute_token_usage(base_lm: Optional[LM]) -> Dict[str, int]:
    stats = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
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
            continue

    stats["total_tokens"] = stats["input_tokens"] + stats["output_tokens"]
    return stats


def init_client_manager() -> ClientManager:
    return ClientManager(
        wcd_url=os.getenv("WEAVIATE_URL"),
        wcd_api_key=os.getenv("WEAVIATE_API_KEY"),
        weaviate_is_local=os.getenv("WEAVIATE_IS_LOCAL", "true").lower() == "true",
        local_weaviate_port=int(os.getenv("WEAVIATE_PORT", "8078")),
        local_weaviate_grpc_port=int(os.getenv("WEAVIATE_GRPC_PORT", "50051")),
        logger=logger,
    )


def init_base_lm(
    model_override: Optional[str] = None, api_key_override: Optional[str] = None
) -> Optional[LM]:
    """
    Mirror MealAgent behaviour: prefer global Elysia settings, allow overrides for CLI usage.
    """
    try:
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
                    "LM API key not provided. Validation will run without LLM insights."
                )
                return None
            base_lm = dspy.LM(model=model, api_key=api_key)
            logger.info("Initialized override base_lm with model: %s", model)
            return base_lm

        base_lm = load_base_lm(settings)
        logger.info(
            "Initialized base_lm via Elysia settings: provider=%s, model=%s",
            settings.BASE_PROVIDER,
            settings.BASE_MODEL,
        )
        return base_lm
    except Exception as exc:
        logger.error("Failed to initialize base_lm: %s", exc)
        return None


async def fetch_recipes(
    client_manager: ClientManager,
    limit: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """
    Fetch recipes from Weaviate.

    NOTE:
    - Unlike the original version, this now returns *all* recipes, including those
      with missing or zero/invalid macros so that the LLM can both validate and
      *fill in* nutrition when absent.
    """
    logger.info("Fetching recipes from Weaviate (including those missing macros)...")
    all_recipes: List[Dict[str, Any]] = []
    offset = 0
    batch_size = 100

    with client_manager.connect_to_client() as client:
        collection = client.collections.get("Recipe")

        while True:
            results = collection.query.fetch_objects(limit=batch_size, offset=offset)
            if not results.objects:
                break

            for obj in results.objects:
                recipe = obj.properties
                recipe["_uuid"] = obj.uuid

                # Do NOT filter here. We want:
                #   - recipes with existing macros (for validation)
                #   - recipes missing or with invalid macros (for LLM to fill in)
                all_recipes.append(recipe)
                if limit and len(all_recipes) >= limit:
                    break

            if limit and len(all_recipes) >= limit:
                break

            offset += batch_size
            logger.info("Fetched %d recipes so far...", len(all_recipes))

    logger.info("Total recipes queued for validation: %d", len(all_recipes))
    return all_recipes


async def _validate_macros_with_lm(
    recipe: Dict[str, Any],
    base_lm: Optional[LM],
    tree_data: TreeData,
) -> Optional[Dict[str, Any]]:
    """
    Legacy per‑recipe validator (kept for reference / potential reuse).
    Current implementation uses the new batch validator below.
    """
    if base_lm is None:
        return None

    macros = recipe.get("macros_per_serving", {})
    servings = float(recipe.get("serving_size", 1.0) or 1.0)
    if servings <= 0:
        servings = 1.0

    ingredients = recipe.get("ingredients_with_qty") or recipe.get("ingredients", [])
    cooking_notes = recipe.get("cooking_method") or recipe.get("instructions", "")

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
        ingredients="\n".join(str(item) for item in ingredients),
        macros=macros,
        cooking_notes=cooking_notes,
    )

    verdict = (pred.verdict or "").strip().lower()
    reason = (pred.reason or "").strip()
    macros_adjusted = None

    if verdict == "adjust" and pred.macros_adjusted:
        import json

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
                "LM returned invalid macros_adjusted JSON for recipe %s: %s",
                recipe.get("food_id"),
                exc,
            )

    return {
        "verdict": verdict or "unknown",
        "reason": reason,
        "macros_adjusted": macros_adjusted,
    }


async def _batch_validate_macros_with_lm(
    recipes: List[Dict[str, Any]],
    base_lm: Optional[LM],
    tree_data: TreeData,
) -> Dict[str, Dict[str, Any]]:
    """
    Validate a batch of recipes with a *single* LLM call.

    The LLM is instructed to return a strict JSON array so that we can
    reliably parse and apply the suggested macros.
    """
    if base_lm is None or not recipes:
        return {}

    import json

    # Build a compact, LLM‑friendly summary for each recipe.
    recipe_summaries: List[Dict[str, Any]] = []
    for r in recipes:
        macros = r.get("macros_per_serving") or {}
        servings = float(r.get("serving_size", 1.0) or 1.0)
        if servings <= 0:
            servings = 1.0

        ingredients = r.get("ingredients_with_qty") or r.get("ingredients", [])
        cooking_notes = r.get("cooking_method") or r.get("instructions", "")

        summary = {
            "id": r.get("_uuid") or r.get("food_id") or "",
            "food_id": r.get("food_id") or "",
            "dish_name": r.get("dish_name") or "",
            "servings": servings,
            "ingredients": [str(item) for item in ingredients],
            "cooking_notes": str(cooking_notes),
            # Macros can be missing or invalid; LLM should propose values when needed.
            "macros_per_serving": {
                "kcal": macros.get("kcal"),
                "protein_g": macros.get("protein_g"),
                "fat_g": macros.get("fat_g"),
                "carb_g": macros.get("carb_g"),
            }
            if isinstance(macros, dict)
            else None,
        }
        recipe_summaries.append(summary)

    class MacroAuditBatchSignature(dspy.Signature):
        """
        Review whether the provided macros per serving are realistic for each recipe.

        You are given a list of recipes. For *each* recipe:
          - If macros look reasonable and are present, mark verdict "ok".
          - If macros look wrong OR are missing/invalid, mark verdict "adjust" and
            provide corrected macros_per_serving PER SERVING.

        STRICT RESPONSE FORMAT (VERY IMPORTANT):
          - Respond with a single JSON array (no surrounding text, no comments).
          - Each element MUST be an object:
              {
                "id": "<the id from input>",          // REQUIRED
                "verdict": "ok" | "adjust",           // REQUIRED
                "reason": "<short explanation>",      // REQUIRED
                "macros_adjusted": {                  // REQUIRED when verdict=="adjust"
                  "kcal": <number>,
                  "protein_g": <number>,
                  "fat_g": <number>,
                  "carb_g": <number>
                }
              }
        """

        recipes = dspy.InputField(
            description=(
                "JSON array of recipes, each with fields: id, food_id, dish_name, "
                "servings, ingredients, cooking_notes, macros_per_serving."
            )
        )
        batch_result_json = dspy.OutputField(
            description=(
                "STRICT JSON array as described above, with NO extra keys or text."
            )
        )

    cot = ElysiaChainOfThought(
        MacroAuditBatchSignature,
        tree_data=tree_data,
        reasoning=False,
        impossible=False,
        message_update=False,
    )

    raw_recipes_json = json.dumps(recipe_summaries, ensure_ascii=False)

    pred = await cot.aforward(
        lm=base_lm,
        recipes=raw_recipes_json,
    )

    raw_output = (pred.batch_result_json or "").strip()
    if not raw_output:
        logger.warning("Batch LLM validation returned empty output.")
        return {}

    # Try to robustly extract the JSON array even if the model adds stray text.
    try:
        # If the model followed instructions, this should succeed directly.
        parsed = json.loads(raw_output)
    except Exception:
        try:
            start = raw_output.find("[")
            end = raw_output.rfind("]")
            if start != -1 and end != -1 and end > start:
                parsed = json.loads(raw_output[start : end + 1])
            else:
                raise ValueError("No JSON array brackets found in LLM output.")
        except Exception as exc:
            logger.error("Failed to parse batch LLM JSON output: %s", exc)
            logger.debug("Raw LLM output: %s", _sanitize_text(raw_output))
            return {}

    if not isinstance(parsed, list):
        logger.error("Batch LLM JSON output is not a list. Got type: %s", type(parsed))
        return {}

    results_by_id: Dict[str, Dict[str, Any]] = {}
    for item in parsed:
        if not isinstance(item, dict):
            continue

        rid = str(item.get("id") or "").strip()
        verdict = (str(item.get("verdict") or "")).strip().lower() or "unknown"
        reason = str(item.get("reason") or "").strip()
        macros_adjusted_raw = item.get("macros_adjusted")

        macros_adjusted: Optional[Dict[str, float]] = None
        if isinstance(macros_adjusted_raw, dict) and verdict == "adjust":
            try:
                macros_adjusted = {
                    "kcal": float(macros_adjusted_raw.get("kcal", 0.0)),
                    "protein_g": float(macros_adjusted_raw.get("protein_g", 0.0)),
                    "fat_g": float(macros_adjusted_raw.get("fat_g", 0.0)),
                    "carb_g": float(macros_adjusted_raw.get("carb_g", 0.0)),
                }
            except (TypeError, ValueError):
                logger.warning(
                    "Invalid macros_adjusted values for id %s in batch response.", rid
                )
                macros_adjusted = None

        if not rid:
            continue

        results_by_id[rid] = {
            "verdict": verdict,
            "reason": reason,
            "macros_adjusted": macros_adjusted,
        }

    return results_by_id


async def _update_recipe_macros(
    recipe: Dict[str, Any],
    macros: Dict[str, float],
    reason: str,
    client_manager: ClientManager,
) -> bool:
    try:
        with client_manager.connect_to_client() as client:
            collection = client.collections.get("Recipe")
            uuid = recipe.get("_uuid")
            if not uuid:
                logger.warning(
                    "Cannot update macros for recipe %s: missing UUID",
                    recipe.get("food_id"),
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
            "Error updating macros for recipe %s: %s",
            recipe.get("food_id"),
            exc,
        )
        return False


async def process_recipes(
    recipes: List[Dict[str, Any]],
    client_manager: ClientManager,
    base_lm: Optional[LM],
    batch_size: int = 100,
    dry_run: bool = False,
) -> Dict[str, int]:
    stats = {
        "total": len(recipes),
        "processed": 0,
        "ok": 0,
        "adjusted": 0,
        "skipped": 0,
        "failed": 0,
    }

    collection_data = CollectionData(collection_names=[])
    atlas = Atlas()
    environment = Environment(environment={}, self_info=False)
    tree_data = TreeData(
        collection_data=collection_data,
        atlas=atlas,
        environment=environment,
    )

    logger.info(
        "Validating %d recipes in batches of %d (one LLM call per batch)...",
        len(recipes),
        batch_size,
    )

    for batch_idx in range(0, len(recipes), batch_size):
        batch = recipes[batch_idx : batch_idx + batch_size]
        batch_num = (batch_idx // batch_size) + 1
        total_batches = (len(recipes) + batch_size - 1) // batch_size

        logger.info("\n%s", "=" * 60)
        logger.info("Batch %d/%d (%d recipes)", batch_num, total_batches, len(batch))
        logger.info("%s", "=" * 60)

        # Single LLM call for the entire batch.
        batch_results = await _batch_validate_macros_with_lm(
            batch,
            base_lm,
            tree_data,
        )

        for recipe in batch:
            stats["processed"] += 1
            dish_name = _sanitize_text(recipe.get("dish_name"))
            food_id = _sanitize_text(recipe.get("food_id"))
            logger.info(
                "[%d/%d] Auditing %s (ID: %s)",
                stats["processed"],
                stats["total"],
                dish_name,
                food_id,
            )

            rid = recipe.get("_uuid") or recipe.get("food_id") or ""
            result = batch_results.get(str(rid))

            if not result:
                logger.info(
                    "  No LLM verdict available for this recipe, treated as OK/unchanged."
                )
                stats["ok"] += 1
                continue

            verdict = result["verdict"]
            reason = result["reason"]
            macros_adjusted = result["macros_adjusted"]

            # If macros are considered OK (including cases where they were originally
            # missing but LLM still decided they are fine), we only log.
            if verdict != "adjust" or not macros_adjusted:
                logger.info(
                    "  ✅ LLM verdict: OK / no change (%s)",
                    reason or "no issues found",
                )
                stats["ok"] += 1
                continue

            logger.warning(
                "  ⚠️ LLM suggests adjustment (%s). New macros: %s",
                reason,
                macros_adjusted,
            )

            if dry_run:
                logger.info("  [DRY RUN] Would update macros with LLM suggestion.")
                stats["adjusted"] += 1
                continue

            success = await _update_recipe_macros(
                recipe,
                macros_adjusted,
                reason,
                client_manager,
            )
            if success:
                logger.info("  ✅ Updated recipe %s with LLM-adjusted macros.", food_id)
                stats["adjusted"] += 1
            else:
                logger.warning("  FAILED to update recipe %s.", food_id)
                stats["failed"] += 1

    return stats


async def main():
    parser = argparse.ArgumentParser(
        description="Validate existing recipe macros using the configured LLM."
    )
    parser.add_argument("--limit", type=int, default=None, help="Max recipes to validate.")
    parser.add_argument(
        "--batch-size",
        type=int,
        default=100,
        help="Recipes per LLM batch (default: 100 recipes per single LLM call).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report proposed changes without updating Weaviate.",
    )
    parser.add_argument(
        "--lm-model",
        type=str,
        default=None,
        help="Override base LM model.",
    )
    parser.add_argument(
        "--lm-api-key",
        type=str,
        default=None,
        help="Override LM API key.",
    )

    args = parser.parse_args()

    logger.info("=" * 60)
    logger.info("Recipe Macros Validation Script")
    logger.info("=" * 60)
    logger.info(
        "Options: limit=%s, batch_size=%s, dry_run=%s",
        args.limit,
        args.batch_size,
        args.dry_run,
    )

    client_manager = init_client_manager()
    base_lm = init_base_lm(model_override=args.lm_model, api_key_override=args.lm_api_key)

    recipes = await fetch_recipes(client_manager, limit=args.limit)
    if not recipes:
        logger.info("No recipes available for validation. Exiting.")
        await client_manager.close_clients()
        return

    start_time = datetime.now()
    stats = await process_recipes(
        recipes,
        client_manager,
        base_lm,
        batch_size=args.batch_size,
        dry_run=args.dry_run,
    )
    end_time = datetime.now()
    duration = (end_time - start_time).total_seconds()
    usage = _compute_token_usage(base_lm)

    logger.info("\n%s", "=" * 60)
    logger.info("FINAL SUMMARY")
    logger.info("=" * 60)
    logger.info("Total recipes: %d", stats["total"])
    logger.info("Processed: %d", stats["processed"])
    logger.info("OK: %d", stats["ok"])
    logger.info("Adjusted: %d", stats["adjusted"])
    logger.info("Skipped: %d", stats["skipped"])
    logger.info("Failed updates: %d", stats["failed"])
    logger.info("Time taken: %.1f seconds (%.1f minutes)", duration, duration / 60)
    if stats["processed"] > 0:
        logger.info(
            "Average time per recipe: %.1f seconds",
            duration / stats["processed"],
        )
    logger.info(
        "LM token usage: input_tokens=%d, output_tokens=%d, total_tokens=%d",
        usage["input_tokens"],
        usage["output_tokens"],
        usage["total_tokens"],
    )
    logger.info("=" * 60)

    await client_manager.close_clients()


if __name__ == "__main__":
    asyncio.run(main())

