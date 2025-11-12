from typing import AsyncGenerator, List, Dict, Any
import logging

from elysia.tree.objects import TreeData
from elysia.objects import Result, Error, Response
from elysia.util.client import ClientManager
from elysia import tool




def _normalize_item(item: Dict[str, Any], collection_name: str) -> Dict[str, Any]:
    """
    Normalize item fields based on collection type.
    
    Args:
        item: Item dictionary to normalize
        collection_name: Name of the collection (Recipe, FdcFood, etc.)
        
    Returns:
        Normalized item dictionary
    """
    normalized = item.copy()
    
    if collection_name == "Recipe":
        # Normalize text fields to lowercase for comparison
        for field in ["dish_name", "dish_type"]:
            if field in normalized and isinstance(normalized[field], str):
                normalized[field] = normalized[field].lower().strip()
        
        # Ensure arrays are lists
        for field in ["ingredients", "ingredients_with_qty", "cooking_method_array"]:
            if field in normalized and not isinstance(normalized.get(field), list):
                normalized[field] = []
    elif collection_name == "FdcFood":
        # Normalize FdcFood fields
        for field in ["description", "food_name"]:
            if field in normalized and isinstance(normalized[field], str):
                normalized[field] = normalized[field].strip()
    # For other collections, just return as-is
    
    return normalized


def _deduplicate_items(items: List[Dict[str, Any]], collection_name: str) -> List[Dict[str, Any]]:
    """
    Remove duplicate items based on collection-specific identifiers.
    
    Args:
        items: List of item dictionaries
        collection_name: Name of the collection
        
    Returns:
        Deduplicated list of items
    """
    seen_ids = set()
    seen_names = set()
    deduped = []
    
    for item in items:
        # Primary: use food_id or id if available
        item_id = item.get("food_id") or item.get("id")
        if item_id and item_id not in seen_ids:
            seen_ids.add(item_id)
            deduped.append(item)
            continue
        
        # Fallback: use name field based on collection
        name_field = None
        if collection_name == "Recipe":
            name_field = item.get("dish_name", "").lower().strip()
        elif collection_name == "FdcFood":
            name_field = (item.get("description") or item.get("food_name", "")).strip()
        else:
            name_field = (item.get("name") or item.get("description", "")).strip()
        
        if name_field and name_field not in seen_names:
            seen_names.add(name_field)
            deduped.append(item)
    
    return deduped


@tool
async def query_postprocessing_tool(
    tree_data: TreeData,
    client_manager: ClientManager,  # signature consistency
    **kwargs,
) -> AsyncGenerator[Result | str | Error, None]:
    """
    Deduplicate and normalize search results from any collection.

    Works with Recipe, FdcFood, FdcNutrient, and other MealAgent collections.
    Normalizes fields and removes duplicates based on collection-specific identifiers.

    Environment reads:
      - environment["query_tool"]["results"]
    Environment writes:
      - environment["query_postprocessing_tool"]["deduped"]
    """
    logging.info("query_postprocessing_tool: start")
    yield Response("Postprocessing search results...")

    try:
        results = tree_data.environment.find("query_tool", "results")
        if not results:
            error_msg = "No search results found in environment. Run query_tool first."
            logging.error(f"query_postprocessing_tool: {error_msg}")
            yield Error(error_msg)
            return
        
        # Handle both Result object and dict formats
        first_result = results[0]
        if hasattr(first_result, "objects"):
            items = first_result.objects
            metadata = first_result.metadata if hasattr(first_result, "metadata") else {}
        elif isinstance(first_result, dict) and "objects" in first_result:
            items = first_result["objects"]
            metadata = first_result.get("metadata", {})
        else:
            error_msg = "Invalid result format from query_tool. Expected Result object or dict with 'objects' key."
            logging.error(f"query_postprocessing_tool: {error_msg}")
            yield Error(error_msg)
            return
        
        if not items:
            error_msg = "No items found in search results."
            logging.warning(f"query_postprocessing_tool: {error_msg}")
            yield Error(error_msg)
            return

        # Get collection name from metadata
        collection_name = metadata.get("collection", "Recipe")

        # Normalize based on collection type
        normalized = [_normalize_item(item, collection_name) for item in items]

        # Deduplicate based on collection type
        deduped = _deduplicate_items(normalized, collection_name)

        logging.info(
            f"query_postprocessing_tool: complete (deduplicated {len(items)} → {len(deduped)} items from {collection_name})"
        )

        # Yield text message first for immediate feedback
        yield Response(f"Deduplicated {len(items)} → {len(deduped)} items from {collection_name}")
        
        # Then yield Result object
        yield Result(
            name="deduped",
            objects=deduped,
            metadata={
                "original_count": len(items),
                "deduped_count": len(deduped),
                "removed": len(items) - len(deduped),
                "collection": collection_name,
            },
            payload_type="table",
        )

    except Exception as e:
        error_msg = f"Postprocessing failed: {str(e)}"
        logging.error(f"query_postprocessing_tool: {error_msg}", exc_info=True)
        yield Error(error_msg)
        return

