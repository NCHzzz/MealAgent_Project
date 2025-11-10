"""
Suggest snacks to fill macro deficits.
"""
from typing import AsyncGenerator, Dict, Any, List

from elysia.tree.objects import TreeData
from elysia.objects import Result, Error
from elysia.util.client import ClientManager
from elysia import tool


def _calculate_macro_fit(
    recipe_macros: Dict[str, float],
    deficit_macros: Dict[str, float],
) -> float:
    """Calculate how well recipe fits the deficit needs (0-100, higher is better)."""
    if not deficit_macros:
        return 0.0

    fit_scores = []
    for macro, deficit in deficit_macros.items():
        recipe_val = recipe_macros.get(macro, 0.0)
        if deficit > 0 and recipe_val > 0:
            # Score based on how close recipe is to deficit (without exceeding too much)
            ratio = min(1.0, recipe_val / deficit) if deficit > 0 else 0.0
            fit_scores.append(ratio)
        elif deficit > 0:
            fit_scores.append(0.0)

    return (sum(fit_scores) / len(fit_scores) * 100.0) if fit_scores else 0.0


@tool
async def suggest_snack_tool(
    tree_data: TreeData,
    client_manager: ClientManager,
    top_k: int = 5,
    **kwargs,
) -> AsyncGenerator[Result | str | Error, None]:
    """
    Suggest snacks to fill macro deficits.

    Environment reads:
      - environment["gap_calc_tool"]["deficits"]
    Environment writes:
      - environment["suggest_snack_tool"]["suggestions"]
    """
    yield "Suggesting snacks to fill deficits..."

    # Read deficits
    deficit_results = tree_data.environment.find("gap_calc_tool", "deficits")
    if not deficit_results or not deficit_results[0].objects:
        yield Error("Deficits not found. Run gap_calc_tool first.")
        return

    deficits_data = deficit_results[0].objects[0]
    deficit_macros = deficits_data.get("deficit_macros", {})

    if not deficit_macros:
        yield Error("No deficits found. Plan already meets targets.")
        return

    try:
        with client_manager.connect_to_client() as client:
            recipe_collection = client.collections.get("Recipe")

            # Search for recipes that could fill deficits
            # Filter by dish_type="snack" if available, otherwise get all recipes
            try:
                # Try to filter by snack dish_type
                results = recipe_collection.query.fetch_objects(
                    where={"path": ["dish_type"], "operator": "Equal", "valueString": "snack"},
                    limit=100,
                )
                if not results.objects:
                    # Fallback: get all recipes if no snacks found
                    results = recipe_collection.query.fetch_objects(limit=100)
            except Exception:
                # If dish_type filtering fails, get all recipes
                results = recipe_collection.query.fetch_objects(limit=100)

            # Score recipes by how well they fit deficits
            scored_recipes = []
            for obj in results.objects:
                recipe = obj.properties
                macros = recipe.get("macros_per_serving", {})
                if isinstance(macros, dict) and macros.get("kcal"):
                    fit_score = _calculate_macro_fit(macros, deficit_macros)
                    if fit_score > 0:
                        scored_recipes.append({
                            **recipe,
                            "fit_score": fit_score,
                        })

            # Sort by fit score and take top_k
            scored_recipes.sort(key=lambda x: x.get("fit_score", 0.0), reverse=True)
            suggestions = scored_recipes[:top_k]

            suggestions_output = {
                "deficit_macros": deficit_macros,
                "suggestions": suggestions,
                "count": len(suggestions),
            }

            yield Result(
                name="suggestions",
                objects=[suggestions_output],
                metadata={
                    "suggestion_count": len(suggestions),
                    "deficit_count": len(deficit_macros),
                },
            )

            if suggestions:
                yield f"Found {len(suggestions)} snack suggestions to fill deficits"
            else:
                yield "No suitable snacks found to fill deficits"

    except Exception as e:
        yield Error(f"Snack suggestion failed: {str(e)}")
        return

