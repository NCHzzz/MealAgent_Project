import logging
import time
from typing import Dict, Any, List, Optional

from MealAgent.tools.utils.weaviate_filters import build_filters_from_where

logger = logging.getLogger(__name__)


def fetch_latest_recipe(
    food_id: str,
    client,
    collection_name: str = "Recipe",
    *,
    hydrate_fields: bool = True,
    candidate_fields: Optional[list[str]] = None,
) -> Optional[Dict[str, Any]]:
    """
    Fetch a single recipe by food_id using both string and int filters to avoid stale lookups.
    Returns properties or None if not found.
    """
    try:
        collection = client.collections.get(collection_name)
    except Exception as exc:
        logger.debug("fetch_latest_recipe: collection %s not found: %s", collection_name, exc)
        return None

    fields = candidate_fields or ["food_id", "recipe_id", "id"]
    filters_to_try = []
    for field in fields:
        if not field:
            continue
        value = str(food_id)
        filters_to_try.append({"path": [field], "operator": "Equal", "valueString": value})
        if value.isdigit():
            filters_to_try.append({"path": [field], "operator": "Equal", "valueInt": int(value)})

    for payload in filters_to_try:
        try:
            recipe_filter = build_filters_from_where(payload)
            results = collection.query.fetch_objects(filters=recipe_filter, limit=1)
            if results.objects:
                props = results.objects[0].properties
                logger.debug(
                    "fetch_latest_recipe: hit %s=%s macros=%s",
                    payload["path"][0],
                    payload.get("valueString") or payload.get("valueInt"),
                    bool(props.get("macros_per_serving")),
                )
                return props if hydrate_fields else props
        except Exception as exc:
            logger.debug("fetch_latest_recipe: failed filter %s due to %s", payload, exc)
            continue

    return None


def refresh_recipes(
    recipes: List[Dict[str, Any]],
    client,
    collection_name: str = "Recipe",
    *,
    hydrate_fields: bool = True,
) -> List[Dict[str, Any]]:
    """
    Refresh a list of recipes from Weaviate by food_id, preserving order and hydrating key fields.
    """
    start_ts = time.perf_counter()
    refreshed = []
    missing_before = sum(
        1
        for r in recipes
        if not r.get("macros_per_serving")
        or not isinstance(r.get("macros_per_serving"), dict)
        or not r.get("macros_per_serving", {}).get("kcal")
    )
    logger.debug(
        "refresh_recipes: start refresh for %d recipes (missing macros before=%d)",
        len(recipes),
        missing_before,
    )
    for recipe in recipes:
        rid = recipe.get("food_id") or recipe.get("recipe_id") or recipe.get("id")
        rid_field = "food_id"
        if not recipe.get("food_id"):
            if recipe.get("recipe_id"):
                rid_field = "recipe_id"
            elif recipe.get("id"):
                rid_field = "id"
        latest = None
        if rid:
            latest = fetch_latest_recipe(
                str(rid),
                client,
                collection_name,
                hydrate_fields=hydrate_fields,
                candidate_fields=[rid_field, "food_id", "recipe_id", "id"],
            )
        if latest:
            # Merge important fields to avoid losing local context
            merged = {**recipe, **latest}
            # Ensure critical fields are present
            for key in ("macros_per_serving", "ingredient_fdc_map", "dish_name", "dish_type", "meal_type"):
                if key in latest:
                    merged[key] = latest[key]
            if not recipe.get("macros_per_serving") and merged.get("macros_per_serving"):
                logger.debug("refresh_recipes: macros updated for %s via %s", rid, rid_field)
            refreshed.append(merged)
        else:
            logger.debug("refresh_recipes: keeping original recipe (no latest) id=%s", rid)
            refreshed.append(recipe)
    missing_after = sum(
        1
        for r in refreshed
        if not r.get("macros_per_serving")
        or not isinstance(r.get("macros_per_serving"), dict)
        or not r.get("macros_per_serving", {}).get("kcal")
    )
    logger.debug(
        "refresh_recipes: completed refresh for %d recipes (missing macros after=%d, before=%d, duration=%.3fs)",
        len(refreshed),
        missing_after,
        missing_before,
        time.perf_counter() - start_ts,
    )
    return refreshed

