from typing import AsyncGenerator, Dict, Any, List
import logging

from elysia.tree.objects import TreeData
from elysia.objects import Result, Error, Response
from elysia.util.client import ClientManager
from elysia import tool

# Defaults
DEFAULT_SEARCH_LIMIT = 50
DEFAULT_HYBRID_ALPHA = 0.5
DEFAULT_TOP_K = 20


def _merge_where_clauses(clauses: list[Dict | None]) -> Dict | None:
    valid = [c for c in clauses if c]
    if not valid:
        return None
    if len(valid) == 1:
        return valid[0]
    return {"operator": "And", "operands": valid}


def _normalize_item(item: Dict[str, Any], collection_name: str) -> Dict[str, Any]:
    normalized = item.copy()
    if collection_name == "Recipe":
        for field in ["dish_name", "dish_type"]:
            if field in normalized and isinstance(normalized[field], str):
                normalized[field] = normalized[field].lower().strip()
        for field in ["ingredients", "ingredients_with_qty", "cooking_method_array"]:
            if field in normalized and not isinstance(normalized.get(field), list):
                normalized[field] = []
    elif collection_name == "FdcFood":
        for field in ["description", "food_name"]:
            if field in normalized and isinstance(normalized[field], str):
                normalized[field] = normalized[field].strip()
    return normalized


def _deduplicate_items(items: List[Dict[str, Any]], collection_name: str) -> List[Dict[str, Any]]:
    seen_ids = set()
    seen_names = set()
    deduped: List[Dict[str, Any]] = []
    for item in items:
        item_id = item.get("food_id") or item.get("id")
        if item_id and item_id not in seen_ids:
            seen_ids.add(item_id)
            deduped.append(item)
            continue
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


def _calculate_macro_fit_score(recipe_macros: Dict[str, float], target_per_meal: Dict[str, float]) -> float:
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
    avg_dev = sum(deviations) / len(deviations) if deviations else 1.0
    return max(0.0, 100.0 - (avg_dev * 100.0))


@tool
async def search_and_rank_tool(
    tree_data: TreeData,
    client_manager: ClientManager,
    query_text: str = "",
    collection_name: str = "Recipe",
    limit: int = DEFAULT_SEARCH_LIMIT,
    alpha: float = DEFAULT_HYBRID_ALPHA,
    top_k: int = DEFAULT_TOP_K,
    **kwargs,
) -> AsyncGenerator[Result | str | Error, None]:
    """
    End-to-end search → normalize/deduplicate → rank.
    Applies combined constraints if available. Returns top_k in one Result.

    Environment interface:
    - Reads:
      - constraints_guard_tool.filters (preferred combined where)
      - macro_calc_tool.targets (optional for macro-aware ranking)
      - legacy: diet_allergen_guard_tool.filters, time_device_guard_tool.filters
    - Writes:
      - search_and_rank_tool.topk: ranked candidate items

    Decision hints:
    - Presence of search_and_rank_tool.topk means downstream tools can proceed
      (e.g., cook_mode_tool will select a recipe_id from here if none provided).
    """
    logging.info("search_and_rank_tool: start")
    yield Response(f"Searching and ranking {collection_name}...")

    if limit <= 0 or limit > 1000:
        yield Error("limit must be between 1 and 1000")
        return
    if not 0.0 <= alpha <= 1.0:
        yield Error("alpha must be between 0.0 and 1.0")
        return

    try:
        client = client_manager.get_client()
        try:
            collection = client.collections.get(collection_name)
        except Exception as e:
            yield Error(f"Collection '{collection_name}' not found: {str(e)}")
            return

        # Collect constraints (combined preferred)
        where_clauses: list[Dict | None] = []
        combined_results = tree_data.environment.find("constraints_guard_tool", "filters")
        if combined_results and combined_results[0]["objects"]:
            where_clauses.append(combined_results[0]["objects"][0].get("where"))
        else:
            diet_results = tree_data.environment.find("diet_allergen_guard_tool", "filters")
            if diet_results and diet_results[0]["objects"]:
                where_clauses.append(diet_results[0]["objects"][0].get("where"))
            time_results = tree_data.environment.find("time_device_guard_tool", "filters")
            if time_results and time_results[0]["objects"]:
                where_clauses.append(time_results[0]["objects"][0].get("where"))

        where = _merge_where_clauses(where_clauses)

        # Execute search with fallback
        def _hybrid():
            return collection.query.hybrid(query=query_text, alpha=alpha, where=where if where else None, limit=limit)

        def _bm25():
            return collection.query.bm25(query=query_text, limit=limit)

        def _fetch():
            return collection.query.fetch_objects(where=where if where else None, limit=limit)

        results = None
        if query_text:
            try:
                results = _hybrid()
            except Exception:
                try:
                    results = _bm25()
                except Exception:
                    results = None
        else:
            try:
                results = _fetch()
            except Exception:
                results = None

        if results is None or not results.objects:
            yield Error("No results found")
            return

        items = [obj.properties for obj in results.objects]

        # Normalize and deduplicate
        normalized = [_normalize_item(item, collection_name) for item in items]
        deduped = _deduplicate_items(normalized, collection_name)

        # Targets (optional)
        targets_results = tree_data.environment.find("macro_calc_tool", "targets")
        targets = targets_results[0]["objects"][0] if (targets_results and targets_results[0]["objects"]) else None
        has_targets = bool(targets)
        target_per_meal = None
        if has_targets:
            target_per_meal = {
                "kcal": targets.get("tdee_kcal", 2000) / 3.0,
                "protein_g": targets.get("protein_g", 150) / 3.0,
                "fat_g": targets.get("fat_g", 67) / 3.0,
                "carb_g": targets.get("carb_g", 200) / 3.0,
            }

        # Score
        scored_items = []
        seen_ingredients: set[str] = set()
        missing_macros_count = 0
        for item in deduped:
            macro_score = 0.0
            if has_targets and target_per_meal:
                macros = item.get("macros_per_serving", {})
                if macros and isinstance(macros, dict) and macros.get("kcal"):
                    macro_score = _calculate_macro_fit_score(macros, target_per_meal)
                else:
                    missing_macros_count += 1

            semantic_score = 50.0
            if "_additional" in item:
                semantic_score = item.get("_additional", {}).get("score", 0.5) * 100.0
            elif "energy_kcal_100g" in item:
                energy = item.get("energy_kcal_100g", 0)
                semantic_score = min(100.0, (energy / 9.0) * 10.0)

            diversity_score = 50.0
            if "ingredients" in item:
                ings = set(str(ing).lower().strip() for ing in item.get("ingredients", []))
                overlap = len(ings & seen_ingredients)
                total = len(ings) or 1
                diversity_ratio = 1.0 - (overlap / total)
                diversity_score = diversity_ratio * 100.0
                seen_ingredients.update(ings)

            if has_targets and target_per_meal:
                total_score = 0.6 * macro_score + 0.3 * semantic_score + 0.1 * diversity_score
            else:
                total_score = 0.7 * semantic_score + 0.3 * diversity_score

            scored_items.append({
                **item,
                "fit_score": total_score,
                "_score_breakdown": {
                    "macro": macro_score if has_targets else None,
                    "semantic": semantic_score,
                    "diversity": diversity_score if "ingredients" in item else None,
                },
            })

        scored_items.sort(key=lambda x: x.get("fit_score", 0.0), reverse=True)
        top_items = scored_items[:top_k]

        warn = ""
        if missing_macros_count > 0 and has_targets:
            warn = f" Warning: {missing_macros_count} items missing macros_per_serving."
        yield Response(f"Ranked top {len(top_items)} items.{warn}")

        yield Result(
            name="topk",
            objects=top_items,
            metadata={
                "top_k": top_k,
                "total_scored": len(scored_items),
                "has_targets": has_targets,
                "collection": collection_name,
            },
            payload_type="table",
        )
        # Suggest a sensible next action for the decision agent
        try:
            suggested = "cook_mode" if collection_name.lower() == "recipe" else "inspect_results"
            yield Result(
                name="next_action_hint",
                objects=[{"suggested_action": suggested, "reason": "ranked results available"}],
                metadata={"suggested_action": suggested},
                payload_type="generic",
            )
        except Exception:
            pass

    except Exception as e:
        yield Error(f"search_and_rank_tool failed: {str(e)}")
        return



