from typing import AsyncGenerator, Dict, Any
import logging

from elysia.tree.objects import TreeData
from elysia.objects import Result, Error, Response
from elysia.util.client import ClientManager
from elysia import tool

# Constants
DEFAULT_SEARCH_LIMIT = 50  # Reduced from 100 to reduce token usage
DEFAULT_HYBRID_ALPHA = 0.5
MAX_SEARCH_LIMIT = 1000
MIN_SEARCH_LIMIT = 1

# Allowed collections for security
ALLOWED_COLLECTIONS = {
    "Recipe",
    "FdcFood",
    "FdcNutrient",
    "FdcPortion",
    "UserProfile",
    "MealPlan",
    "MealPlanItem",
    "MealLogEntry",
    "Pantry",
    "PantryItem",
    "ShoppingList",
    "ShoppingItem",
}


def _merge_where_clauses(clauses: list[Dict | None]) -> Dict | None:
    """
    Merge multiple where clauses with AND operator.
    
    Args:
        clauses: List of filter dictionaries or None values
        
    Returns:
        Combined filter dictionary with AND operator, or None if no valid clauses
    """
    valid = [c for c in clauses if c]
    if not valid:
        return None
    if len(valid) == 1:
        return valid[0]
    return {"operator": "And", "operands": valid}


def _get_search_filters(collection_name: str, filters: Dict | None) -> Dict | None:
    """
    Determine if filters should be applied based on collection type.
    
    Args:
        collection_name: Name of the collection
        filters: Filter dictionary or None
        
    Returns:
        Filter dictionary if applicable, None otherwise
    """
    # Recipe collection always uses filters if provided
    if collection_name == "Recipe":
        return filters
    # Other collections may not support all filter types
    return filters if filters else None


def _try_search_with_fallbacks(
    collection, collection_name: str, query_text: str, filters: Dict | None, limit: int, alpha: float
) -> tuple[Any, str | None]:
    """
    Try search methods in order: hybrid → bm25 → fetch_objects.
    
    Args:
        collection: Weaviate collection object
        collection_name: Name of the collection
        query_text: Search query text
        filters: Filter dictionary or None
        limit: Maximum number of results
        alpha: Hybrid search alpha parameter
        
    Returns:
        Tuple of (results, method_name) or (None, None) if all methods fail
    """
    search_filters = _get_search_filters(collection_name, filters)
    last_error = None
    
    # Method 1: Hybrid search
    if query_text:
        try:
            results = collection.query.hybrid(
                query=query_text,
                alpha=alpha,
                where=search_filters if search_filters else None,
                limit=limit,
            )
            return results, "hybrid"
        except Exception as e:
            logging.debug(f"query_tool: hybrid search failed: {e}")
            last_error = e
    
    # Method 2: BM25 search (only if query_text provided)
    if query_text:
        try:
            results = collection.query.bm25(
                query=query_text,
                limit=limit,
            )
            return results, "bm25"
        except Exception as e:
            logging.debug(f"query_tool: bm25 search failed: {e}")
            last_error = e
    
    # Method 3: Fetch objects (only if no query_text)
    if not query_text:
        try:
            results = collection.query.fetch_objects(
                where=search_filters if search_filters else None,
                limit=limit,
            )
            return results, "fetch_objects"
        except Exception as e:
            logging.debug(f"query_tool: fetch_objects failed: {e}")
            last_error = e
    
    # All methods failed
    logging.error(
        f"query_tool: All search methods failed for collection {collection_name}. "
        f"Last error: {str(last_error)}"
    )
    return None, None


@tool
async def query_tool(
    tree_data: TreeData,
    client_manager: ClientManager,
    query_text: str = "",
    collection_name: str = "Recipe",
    limit: int = DEFAULT_SEARCH_LIMIT,
    alpha: float = DEFAULT_HYBRID_ALPHA,
    missing_field: str | None = None,
    **kwargs,
) -> AsyncGenerator[Result | str | Error, None]:
    """
    Hybrid search on any collection with filters from constraint tools.
    
    This tool performs semantic and keyword search across MealAgent collections.
    Supports multiple collections: Recipe, FdcFood, FdcNutrient, FdcPortion, etc.
    
    **Usage Guidelines:**
    - For Recipe collection: Use semantic queries like "low carb high protein meals"
    - For FdcFood collection: Use queries like "high energy foods", "foods with vitamin D", 
      or specific nutrient queries like "foods with energy > 300 kcal per 100g"
    - For nutrient-based queries: Use descriptive text that mentions the nutrient and criteria
    - The tool automatically applies diet/allergen and time/device constraints if available
    
    **Query Examples:**
    - "foods with energy > 300 kcal per 100g" → searches FdcFood for high-energy items
    - "low protein high fat foods" → searches FdcFood for items matching criteria
    - "chicken recipes under 30 minutes" → searches Recipe collection
    - "foods with missing vitamin D" → use missing_field="vitamin_d_iu_100g"
    
    **Collection Selection:**
    - Use "FdcFood" for food database queries (nutrients, energy, macros)
    - Use "Recipe" for recipe searches (default)
    - Use "FdcNutrient" for nutrient-specific queries
    
    **Search Behavior:**
    - Hybrid search balances semantic (vector) and keyword (BM25) matching
    - alpha=0.5 (default) balances both approaches
    - alpha=0.0 emphasizes keywords, alpha=1.0 emphasizes semantic similarity
    - Falls back to BM25 if hybrid fails, then to fetch_objects if no query_text

    Args:
        collection_name: Name of the collection to search. 
                       Options: "Recipe", "FdcFood", "FdcNutrient", "FdcPortion", etc.
                       Default: "Recipe"
        query_text: Natural language search query. 
                   For FdcFood: describe nutrient criteria (e.g., "high energy", "low sodium")
                   For Recipe: describe meal preferences (e.g., "vegetarian pasta", "quick breakfast")
                   Can be empty if using filters only.
        limit: Maximum number of results to return (1-1000, default: 50)
        alpha: Hybrid search balance (0.0-1.0, default: 0.5)
               0.0 = keyword-only, 1.0 = vector-only, 0.5 = balanced
        missing_field: Optional field name to find records where this field is null/missing.
                       Example: "vitamin_d_iu_100g" to find foods missing vitamin D data.
                       When provided, uses fetch_objects with IsNull filter.

    Environment reads:
      - environment["diet_allergen_guard_tool"]["filters"] - diet/allergen constraints
      - environment["time_device_guard_tool"]["filters"] - time/equipment constraints
    Environment writes:
      - environment["query_tool"]["results"] - search results with metadata
    """
    logging.info(
        f"query_tool: start (collection={collection_name}, query='{query_text[:50]}...', limit={limit}, alpha={alpha})"
    )
    
    # Input validation
    if limit < MIN_SEARCH_LIMIT or limit > MAX_SEARCH_LIMIT:
        error_msg = f"limit must be between {MIN_SEARCH_LIMIT} and {MAX_SEARCH_LIMIT}, got: {limit}"
        logging.error(f"query_tool: {error_msg}")
        yield Error(error_msg)
        return
    
    if not 0.0 <= alpha <= 1.0:
        error_msg = f"alpha must be between 0.0 and 1.0, got: {alpha}"
        logging.error(f"query_tool: {error_msg}")
        yield Error(error_msg)
        return
    
    if collection_name not in ALLOWED_COLLECTIONS:
        error_msg = f"Invalid collection name: {collection_name}. Allowed: {sorted(ALLOWED_COLLECTIONS)}"
        logging.error(f"query_tool: {error_msg}")
        yield Error(error_msg)
        return
    
    if missing_field:
        yield Response(f"Searching {collection_name} for records with missing {missing_field}...")
    else:
        yield Response(f"Searching {collection_name}: '{query_text}'...")

    try:
        client = client_manager.get_client()
        # Validate collection exists
        try:
            collection = client.collections.get(collection_name)
        except Exception as e:
            error_msg = f"Collection '{collection_name}' not found: {str(e)}"
            logging.error(f"query_tool: {error_msg}")
            yield Error(error_msg)
            return

        # Collect where clauses from environment
        where_clauses: list[Dict | None] = []

        # Read combined constraints (single source of truth)
        combined_results = tree_data.environment.find("constraints_guard_tool", "filters")
        if combined_results and combined_results[0].objects:
            combined_filters = combined_results[0].objects[0]
            where_clauses.append(combined_filters.get("where"))

        # Add missing field filter if provided
        if missing_field:
            where_clauses.append({
                "path": [missing_field],
                "operator": "IsNull",
                "valueBoolean": True,
            })

        # Merge all where clauses into a single `where` filter
        where = _merge_where_clauses(where_clauses)

        # Execute search
        if missing_field:
            # Combine with explicit IsNull filter if necessary
            missing_filter = {
                "path": [missing_field],
                "operator": "IsNull",
                "valueBoolean": True,
            }
            combined_where = (
                {"operator": "And", "operands": [where, missing_filter]}
                if where
                else missing_filter
            )
            results = collection.query.fetch_objects(
                where=combined_where,
                limit=limit,
            )
        else:
            # Use hybrid search for semantic/keyword search with fallback chain
            results, method_used = _try_search_with_fallbacks(
                collection, collection_name, query_text, where, limit, alpha
            )
            if results is None:
                error_msg = (
                    f"Collection {collection_name} does not support any search method. "
                    f"Please check if the collection exists and supports vector/keyword search."
                )
                logging.error(f"query_tool: {error_msg}")
                yield Error(error_msg)
                return
            logging.debug(f"query_tool: search method used: {method_used}")

        items = [obj.properties for obj in results.objects]

        logging.info(f"query_tool: complete (found {len(items)} items in {collection_name})")
        
        # Yield text message first for immediate feedback
        yield Response(f"Found {len(items)} matching items in {collection_name}")
        
        # Then yield Result object
        yield Result(
            name="results",
            objects=items,
            metadata={
                "query": query_text,
                "collection": collection_name,
                "count": len(items),
                "alpha": alpha,
            },
            payload_type="table",
        )

    except ValueError as e:
        error_msg = f"Invalid input: {str(e)}"
        logging.error(f"query_tool: {error_msg}", exc_info=True)
        yield Error(error_msg)
        return
    except Exception as e:
        error_msg = f"Search failed for query '{query_text}': {str(e)}"
        logging.error(f"query_tool: {error_msg}", exc_info=True)
        yield Error(error_msg)
        return

