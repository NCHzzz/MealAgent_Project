from typing import AsyncGenerator, List, Dict, Any

from elysia.tree.objects import TreeData
from elysia.objects import Result, Error
from elysia.util.client import ClientManager
from elysia import tool


def _calculate_macro_fit_score(
    recipe_macros: Dict[str, float],
    target_per_meal: Dict[str, float],
) -> float:
    """Calculate macro fit score (0-100, higher is better)."""
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
    """Calculate diversity score based on ingredient overlap (0-100, higher is better)."""
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
    top_k: int = 20,
    macro_weight: float = 0.6,
    semantic_weight: float = 0.3,
    diversity_weight: float = 0.1,
    **kwargs,
) -> AsyncGenerator[Result | str | Error, None]:
    """
    Multi-criteria scoring and ranking of recipes.

    Environment reads:
      - environment["query_postprocessing_tool"]["deduped"]
      - environment["macro_calc_tool"]["targets"]
    Environment writes:
      - environment["score_and_rank_tool"]["topk"]
    """
    yield "Ranking recipes by fit and diversity..."

    # Read recipes
    recipes_results = tree_data.environment.find("query_postprocessing_tool", "deduped")
    if not recipes_results or not recipes_results[0].objects:
        recipes = []
    else:
        recipes = recipes_results[0].objects

    # Read targets
    targets_results = tree_data.environment.find("macro_calc_tool", "targets")
    if not targets_results or not targets_results[0].objects:
        yield Error("Targets not found in environment. Run macro_calc_tool first.")
        return

    targets = targets_results[0].objects[0]

    if not recipes:
        yield Error("No recipes to rank")
        return

    # Calculate target per meal (assume 3 meals/day)
    target_per_meal = {
        "kcal": targets.get("tdee_kcal", 2000) / 3.0,
        "protein_g": targets.get("protein_g", 150) / 3.0,
        "fat_g": targets.get("fat_g", 67) / 3.0,
        "carb_g": targets.get("carb_g", 200) / 3.0,
    }

    # Score each recipe
    scored_recipes = []
    seen_ingredients: set[str] = set()
    missing_macros_count = 0

    for recipe in recipes:
        macros = recipe.get("macros_per_serving", {})
        if not macros or not isinstance(macros, dict) or not macros.get("kcal"):
            # Recipe missing macros - will score 0 for macro fit
            # Note: CalculateRecipeMacrosTool should be called to populate macros_per_serving
            missing_macros_count += 1
            macro_score = 0.0
        else:
            macro_score = _calculate_macro_fit_score(macros, target_per_meal)

        # Semantic score (from hybrid search, if available in metadata)
        semantic_score = 50.0  # Default
        if "_additional" in recipe:
            search_score = recipe.get("_additional", {}).get("score", 0.5)
            semantic_score = search_score * 100.0

        # Diversity score
        diversity_score = _calculate_diversity_score(recipe, seen_ingredients)

        # Weighted composite score
        total_score = (
            macro_weight * macro_score
            + semantic_weight * semantic_score
            + diversity_weight * diversity_score
        )

        scored_recipes.append({
            **recipe,
            "fit_score": total_score,
            "_score_breakdown": {
                "macro": macro_score,
                "semantic": semantic_score,
                "diversity": diversity_score,
            },
        })

        # Update seen ingredients for next recipe
        ingredients = recipe.get("ingredients", [])
        seen_ingredients.update(str(ing).lower().strip() for ing in ingredients)

    # Sort by score (descending) and take top_k
    scored_recipes.sort(key=lambda x: x.get("fit_score", 0.0), reverse=True)
    top_recipes = scored_recipes[:top_k]

    yield Result(
        name="topk",
        objects=top_recipes,
        metadata={
            "top_k": top_k,
            "total_scored": len(scored_recipes),
            "missing_macros_count": missing_macros_count,
            "weights": {
                "macro": macro_weight,
                "semantic": semantic_weight,
                "diversity": diversity_weight,
            },
        },
    )
    warning_msg = ""
    if missing_macros_count > 0:
        warning_msg = f" Warning: {missing_macros_count} recipes missing macros_per_serving (consider running calculate_recipe_macros_tool)."
    yield f"Top {len(top_recipes)} recipes ranked by fit.{warning_msg}"

