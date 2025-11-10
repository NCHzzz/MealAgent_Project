from typing import AsyncGenerator, List, Dict, Any

from elysia.tree.objects import TreeData
from elysia.objects import Result, Error
from elysia.util.client import ClientManager
from elysia import tool


def _normalize_recipe(recipe: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize recipe fields (lowercase text fields, ensure consistent types)."""
    normalized = recipe.copy()
    
    # Normalize text fields to lowercase for comparison
    for field in ["dish_name", "dish_type"]:
        if field in normalized and isinstance(normalized[field], str):
            normalized[field] = normalized[field].lower().strip()
    
    # Ensure arrays are lists
    for field in ["ingredients", "ingredients_with_qty", "cooking_method_array"]:
        if field in normalized and not isinstance(normalized.get(field), list):
            normalized[field] = []
    
    return normalized


def _deduplicate_recipes(recipes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Remove duplicate recipes based on food_id or dish_name."""
    seen_ids = set()
    seen_names = set()
    deduped = []
    
    for recipe in recipes:
        # Primary: use food_id if available
        food_id = recipe.get("food_id")
        if food_id and food_id not in seen_ids:
            seen_ids.add(food_id)
            deduped.append(recipe)
            continue
        
        # Fallback: use normalized dish_name
        dish_name = recipe.get("dish_name", "").lower().strip()
        if dish_name and dish_name not in seen_names:
            seen_names.add(dish_name)
            deduped.append(recipe)
    
    return deduped


@tool
async def query_postprocessing_tool(
    tree_data: TreeData,
    client_manager: ClientManager,  # signature consistency
    **kwargs,
) -> AsyncGenerator[Result | str | Error, None]:
    """
    Deduplicate and normalize recipe search results.

    Environment reads:
      - environment["query_tool"]["results"]
    Environment writes:
      - environment["query_postprocessing_tool"]["deduped"]
    """
    yield "Postprocessing search results..."

    results = tree_data.environment.find("query_tool", "results")
    if not results or not results[0].objects:
        yield Error("No search results found in environment. Run query_tool first.")
        return

    recipes = results[0].objects

    # Normalize
    normalized = [_normalize_recipe(r) for r in recipes]

    # Deduplicate
    deduped = _deduplicate_recipes(normalized)

    yield Result(
        name="deduped",
        objects=deduped,
        metadata={
            "original_count": len(recipes),
            "deduped_count": len(deduped),
            "removed": len(recipes) - len(deduped),
        },
    )
    yield f"Deduplicated {len(recipes)} → {len(deduped)} recipes"

