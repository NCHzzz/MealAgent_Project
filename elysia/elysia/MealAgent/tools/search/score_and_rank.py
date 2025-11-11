from typing import AsyncGenerator, List, Dict, Any
import logging

from elysia.tree.objects import TreeData
from elysia.objects import Result, Error, Response
from elysia.util.client import ClientManager
from elysia import tool

# Constants
DEFAULT_TOP_K = 20
DEFAULT_MACRO_WEIGHT = 0.6
DEFAULT_SEMANTIC_WEIGHT = 0.3
DEFAULT_DIVERSITY_WEIGHT = 0.1


def _calculate_macro_fit_score(
    recipe_macros: Dict[str, float],
    target_per_meal: Dict[str, float],
) -> float:
    """
    Calculate macro fit score (0-100, higher is better).
    
    Args:
        recipe_macros: Recipe macro values (kcal, protein_g, fat_g, carb_g)
        target_per_meal: Target macro values per meal
        
    Returns:
        Fit score between 0 and 100
    """
    if not recipe_macros:
        return 0.0

    deviations = []
    for key in ["kcal", "protein_g", "fat_g", "carb_g"]:
        recipe_val = recipe_macros.get(key, 0.0)
        target_val = target_per_meal.get(key, 1.0)
        if target_val > 0:
            dev = abs(recipe_val - target_val) / target_val
            deviations.append(dev)
        else:
            deviations.append(1.0)

    avg_deviation = sum(deviations) / len(deviations) if deviations else 1.0
    # Convert to score: 0 deviation = 100, 100% deviation = 0
    score = max(0.0, 100.0 - (avg_deviation * 100.0))
    return score


def _calculate_diversity_score(recipe: Dict[str, Any], seen_ingredients: set[str]) -> float:
    """
    Calculate diversity score based on ingredient overlap (0-100, higher is better).
    
    Args:
        recipe: Recipe dictionary
        seen_ingredients: Set of ingredient names already used
        
    Returns:
        Diversity score between 0 and 100
    """
    ingredients = recipe.get("ingredients", [])
    if not ingredients:
        return 50.0  # Neutral score if no ingredients

    unique_ingredients = set(str(ing).lower().strip() for ing in ingredients)
    overlap = len(unique_ingredients & seen_ingredients)
    total = len(unique_ingredients)

    if total == 0:
        return 50.0

    # Lower overlap = higher diversity score
    diversity_ratio = 1.0 - (overlap / total)
    return diversity_ratio * 100.0


@tool
async def score_and_rank_tool(
    tree_data: TreeData,
    client_manager: ClientManager,  # signature consistency
    top_k: int = DEFAULT_TOP_K,
    macro_weight: float = DEFAULT_MACRO_WEIGHT,
    semantic_weight: float = DEFAULT_SEMANTIC_WEIGHT,
    diversity_weight: float = DEFAULT_DIVERSITY_WEIGHT,
    **kwargs,
) -> AsyncGenerator[Result | str | Error, None]:
    """
    Multi-criteria scoring and ranking of search results.

    Works with Recipe, FdcFood, and other collections. Can operate with or without macro targets.
    - With targets: Scores items by macro fit, semantic relevance, and diversity
    - Without targets: Scores items by semantic relevance and diversity only

    Environment reads:
      - environment["query_postprocessing_tool"]["deduped"] (or ["query_tool"]["results"] as fallback)
      - environment["macro_calc_tool"]["targets"] (optional, for macro-based scoring)
    Environment writes:
      - environment["score_and_rank_tool"]["topk"]
    """
    logging.info(f"score_and_rank_tool: start (top_k={top_k}, weights: macro={macro_weight}, semantic={semantic_weight}, diversity={diversity_weight})")
    yield Response("Ranking items by relevance...")

    def _extract_objects(result_list, default=None):
        if not result_list:
            return default if default is not None else []

        first = result_list[0]

        if hasattr(first, "objects"):
            return first.objects or (default if default is not None else [])

        if isinstance(first, dict):
            if "objects" in first and isinstance(first["objects"], list):
                return first["objects"]
            # Some legacy formats may store the list directly
            if isinstance(first, list):
                return first
            return default if default is not None else []

        if isinstance(first, list):
            return first

        return default if default is not None else []

    try:
        # Read items from postprocessing or directly from query_tool
        items_results = tree_data.environment.find("query_postprocessing_tool", "deduped")
        items = _extract_objects(items_results)

        if not items:
            # Fallback to query_tool results
            items_results = tree_data.environment.find("query_tool", "results")
            items = _extract_objects(items_results)

        if not items:
            logging.warning("score_and_rank_tool: No items found in environment")

        # Read targets (optional)
        targets_results = tree_data.environment.find("macro_calc_tool", "targets")
        target_objects = _extract_objects(targets_results)
        has_targets = bool(target_objects)
        targets = target_objects[0] if has_targets else None

        if not items:
            error_msg = "No items to rank"
            logging.warning(f"score_and_rank_tool: {error_msg}")
            yield Error(error_msg)
            return

        # Calculate target per meal if targets available (for Recipe collection)
        target_per_meal = None
        if has_targets and targets:
            target_per_meal = {
                "kcal": targets.get("tdee_kcal", 2000) / 3.0,
                "protein_g": targets.get("protein_g", 150) / 3.0,
                "fat_g": targets.get("fat_g", 67) / 3.0,
                "carb_g": targets.get("carb_g", 200) / 3.0,
            }
            # Adjust weights if no targets: reduce macro weight, increase semantic
            if macro_weight > 0 and not has_targets:
                semantic_weight += macro_weight * 0.5
                diversity_weight += macro_weight * 0.5
                macro_weight = 0.0

        # Score each item
        scored_items = []
        seen_ingredients: set[str] = set()
        missing_macros_count = 0

        for item in items:
            # Macro score (only if targets available and item has macros)
            macro_score = 0.0
            if target_per_meal:
                macros = item.get("macros_per_serving", {})
                if macros and isinstance(macros, dict) and macros.get("kcal"):
                    macro_score = _calculate_macro_fit_score(macros, target_per_meal)
                else:
                    missing_macros_count += 1

            # Semantic score (from hybrid search, if available)
            semantic_score = 50.0  # Default neutral score
            if "_additional" in item:
                search_score = item.get("_additional", {}).get("score", 0.5)
                semantic_score = search_score * 100.0
            elif "energy_kcal_100g" in item:
                # For FdcFood: use energy as a proxy for relevance if no search score
                # Normalize to 0-100 scale (assuming max ~900 kcal/100g)
                energy = item.get("energy_kcal_100g", 0)
                semantic_score = min(100.0, (energy / 9.0) * 10.0)  # Scale to 0-100

            # Diversity score (for Recipe collection with ingredients)
            diversity_score = 50.0  # Default neutral
            if "ingredients" in item:
                diversity_score = _calculate_diversity_score(item, seen_ingredients)
                ingredients = item.get("ingredients", [])
                seen_ingredients.update(str(ing).lower().strip() for ing in ingredients)

            # Weighted composite score
            # If no targets, only use semantic and diversity
            if has_targets and target_per_meal:
                total_score = (
                    macro_weight * macro_score
                    + semantic_weight * semantic_score
                    + diversity_weight * diversity_score
                )
            else:
                # No targets: use semantic and diversity only
                total_score = (
                    semantic_weight * semantic_score
                    + diversity_weight * diversity_score
                ) / (semantic_weight + diversity_weight) * 100.0  # Normalize to 0-100

            scored_items.append({
                **item,
                "fit_score": total_score,
                "_score_breakdown": {
                    "macro": macro_score if has_targets else None,
                    "semantic": semantic_score,
                    "diversity": diversity_score if "ingredients" in item else None,
                },
            })

        # Sort by score (descending) and take top_k
        scored_items.sort(key=lambda x: x.get("fit_score", 0.0), reverse=True)
        top_items = scored_items[:top_k]

        logging.info(
            f"score_and_rank_tool: complete (scored {len(scored_items)} items, "
            f"selected top {len(top_items)}, has_targets={has_targets}, missing_macros={missing_macros_count})"
        )

        # Yield text message first for immediate feedback
        warning_msg = ""
        if missing_macros_count > 0 and has_targets:
            warning_msg = f" Warning: {missing_macros_count} items missing macros_per_serving (consider running calculate_recipe_macros_tool)."
        yield Response(f"Top {len(top_items)} items ranked by relevance.{warning_msg}")
        
        # Then yield Result object
        yield Result(
            name="topk",
            objects=top_items,
            metadata={
                "top_k": top_k,
                "total_scored": len(scored_items),
                "has_targets": has_targets,
                "missing_macros_count": missing_macros_count,
                "weights": {
                    "macro": macro_weight if has_targets else 0.0,
                    "semantic": semantic_weight,
                    "diversity": diversity_weight,
                },
            },
            payload_type="table",
        )

    except ValueError as e:
        error_msg = f"Invalid input: {str(e)}"
        logging.error(f"score_and_rank_tool: {error_msg}", exc_info=True)
        yield Error(error_msg)
        return
    except Exception as e:
        error_msg = f"Scoring and ranking failed: {str(e)}"
        logging.error(f"score_and_rank_tool: {error_msg}", exc_info=True)
        yield Error(error_msg)
        return

