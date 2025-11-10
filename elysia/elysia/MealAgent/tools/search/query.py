from typing import AsyncGenerator, Dict, Any

from elysia.tree.objects import TreeData
from elysia.objects import Result, Error
from elysia.util.client import ClientManager
from elysia import tool


def _merge_where_clauses(clauses: list[Dict | None]) -> Dict | None:
    """Merge multiple where clauses with AND operator."""
    valid = [c for c in clauses if c]
    if not valid:
        return None
    if len(valid) == 1:
        return valid[0]
    return {"operator": "And", "operands": valid}


@tool
async def query_tool(
    tree_data: TreeData,
    client_manager: ClientManager,
    query_text: str = "",
    limit: int = 100,
    alpha: float = 0.5,
    **kwargs,
) -> AsyncGenerator[Result | str | Error, None]:
    """
    Hybrid search on Recipe collection with filters from constraint tools.

    Environment reads:
      - environment["diet_allergen_guard_tool"]["filters"]
      - environment["time_device_guard_tool"]["filters"]
    Environment writes:
      - environment["query_tool"]["results"]
    """
    yield f"Searching recipes: '{query_text}'..."

    try:
        with client_manager.connect_to_client() as client:
            collection = client.collections.get("Recipe")

            # Collect where clauses from environment
            where_clauses: list[Dict | None] = []

            # Read diet/allergen filters
            diet_results = tree_data.environment.find("diet_allergen_guard_tool", "filters")
            if diet_results and diet_results[0].objects:
                diet_filters = diet_results[0].objects[0]
                where_clauses.append(diet_filters.get("where"))

            # Read time/device filters
            time_results = tree_data.environment.find("time_device_guard_tool", "filters")
            if time_results and time_results[0].objects:
                time_filters = time_results[0].objects[0]
                where_clauses.append(time_filters.get("where"))

            # Merge all where clauses
            where_clause = _merge_where_clauses(where_clauses)

            # Execute hybrid search
            results = collection.query.hybrid(
                query=query_text,
                alpha=alpha,
                filters=where_clause,
                limit=limit,
            )

            recipes = [obj.properties for obj in results.objects]

            yield Result(
                name="results",
                objects=recipes,
                metadata={"query": query_text, "count": len(recipes), "alpha": alpha},
            )
            yield f"Found {len(recipes)} matching recipes"

    except Exception as e:
        yield Error(f"Search failed for query '{query_text}': {str(e)}")
        return

