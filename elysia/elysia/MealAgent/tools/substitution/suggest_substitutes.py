"""
Suggest ingredient substitutes based on macro matching (±20%).
"""
from typing import AsyncGenerator, Dict, Any, List

from elysia.tree.objects import TreeData
from elysia.objects import Result, Error, Response
from elysia.util.client import ClientManager
from elysia import tool


def _macro_match_score(
    original_macros: Dict[str, float],
    substitute_macros: Dict[str, float],
    tolerance: float = 0.2,
) -> float:
    """
    Calculate how well substitute matches original macros (0-100, higher is better).
    Uses ±20% tolerance by default.
    """
    if not original_macros or not substitute_macros:
        return 0.0

    scores = []
    for macro in ["kcal", "protein_g", "fat_g", "carb_g"]:
        original_val = original_macros.get(macro, 0.0)
        substitute_val = substitute_macros.get(macro, 0.0)

        if original_val > 0:
            ratio = substitute_val / original_val
            # Score: 100 if exact match, decreases as ratio deviates from 1.0
            # Within tolerance (0.8-1.2), score is high
            if 1.0 - tolerance <= ratio <= 1.0 + tolerance:
                score = 100.0 - abs(ratio - 1.0) * 100.0 / tolerance
                scores.append(max(0.0, score))
            else:
                scores.append(0.0)
        elif substitute_val == 0:
            scores.append(100.0)  # Both zero = match
        else:
            scores.append(0.0)

    return sum(scores) / len(scores) if scores else 0.0


@tool
async def suggest_substitutes_tool(
    tree_data: TreeData,
    client_manager: ClientManager,
    ingredient_name: str = "",
    fdc_id: int | None = None,
    tolerance: float = 0.2,
    top_k: int = 10,
    **kwargs,
) -> AsyncGenerator[Result | str | Error, None]:
    """
    Suggest ingredient substitutes based on macro matching (±20% tolerance).

    Environment writes:
      - environment["suggest_substitutes_tool"]["substitutes"]
    """
    yield Response("Finding ingredient substitutes...")

    if not ingredient_name and not fdc_id:
        yield Error("ingredient_name or fdc_id is required")
        return

    try:
        client = client_manager.get_client()
        fdc_collection = client.collections.get("FdcFood")

        # Get original ingredient macros
        original_fdc = None
        if fdc_id:
            results = fdc_collection.query.fetch_objects(
                where={"path": ["fdc_id"], "operator": "Equal", "valueInt": int(fdc_id)},
                limit=1,
            )
            if results.objects:
                original_fdc = results.objects[0].properties
        elif ingredient_name:
            # Search by description
            results = fdc_collection.query.bm25(
                query=ingredient_name,
                limit=1,
            )
            if results.objects:
                original_fdc = results.objects[0].properties
                fdc_id = original_fdc.get("fdc_id")

        if not original_fdc:
            yield Error(f"Ingredient not found: {ingredient_name or fdc_id}")
            return

        # Get original macros (per 100g)
        original_macros = {
            "kcal": float(original_fdc.get("energy_kcal_100g", 0.0)),
            "protein_g": float(original_fdc.get("protein_g_100g", 0.0)),
            "fat_g": float(original_fdc.get("fat_g_100g", 0.0)),
            "carb_g": float(original_fdc.get("carbohydrate_g_100g", 0.0)),
        }

        # Search for similar foods (same category or similar description)
        # For MVP, search by description similarity
        search_query = ingredient_name if ingredient_name else original_fdc.get("description", "")
        search_results = fdc_collection.query.bm25(
            query=search_query,
            limit=100,  # Get pool to filter
        )

        # Score and rank substitutes
        scored_substitutes = []
        for obj in search_results.objects:
            substitute = obj.properties
            sub_fdc_id = substitute.get("fdc_id")
            if sub_fdc_id == fdc_id:
                continue  # Skip original

            sub_macros = {
                "kcal": float(substitute.get("energy_kcal_100g", 0.0)),
                "protein_g": float(substitute.get("protein_g_100g", 0.0)),
                "fat_g": float(substitute.get("fat_g_100g", 0.0)),
                "carb_g": float(substitute.get("carbohydrate_g_100g", 0.0)),
            }

            match_score = _macro_match_score(original_macros, sub_macros, tolerance)
            if match_score > 0:
                scored_substitutes.append({
                    "fdc_id": sub_fdc_id,
                    "description": substitute.get("description", ""),
                    "macros_per_100g": sub_macros,
                    "match_score": match_score,
                })

        # Sort by match score and take top_k
        scored_substitutes.sort(key=lambda x: x.get("match_score", 0.0), reverse=True)
        suggestions = scored_substitutes[:top_k]

        substitutes_output = {
            "original_ingredient": {
                "name": ingredient_name,
                "fdc_id": fdc_id,
                "macros_per_100g": original_macros,
            },
            "substitutes": suggestions,
            "count": len(suggestions),
            "tolerance": tolerance,
        }

        yield Result(
            name="substitutes",
            objects=[substitutes_output],
            metadata={
                "substitute_count": len(suggestions),
                "tolerance": tolerance,
            },
            payload_type="generic",
        )
        # Table view of suggestions (rows) for display
        yield Result(
            name="substitutes_table",
            objects=suggestions,
            metadata={
                "substitute_count": len(suggestions),
                "tolerance": tolerance,
            },
            payload_type="table",
        )

        if suggestions:
            yield Response(f"Found {len(suggestions)} substitute suggestions")
        else:
            yield Response("No suitable substitutes found within tolerance")

    except Exception as e:
        yield Error(f"Substitute suggestion failed: {str(e)}")
        return

