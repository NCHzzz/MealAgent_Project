from typing import AsyncGenerator, Dict, Any, List
import logging

from elysia.tree.objects import TreeData
from elysia.objects import Result, Error, Response, Retrieval
from elysia.util.client import ClientManager
from elysia import tool

from MealAgent.tools.utils.weaviate_filters import build_filters_from_where

# Try to import Elysia Query tool
try:
    from elysia.tools.retrieval.query import Query as ElysiaQuery
    ELYSIA_QUERY_AVAILABLE = True
except ImportError:
    ELYSIA_QUERY_AVAILABLE = False
    ElysiaQuery = None

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


async def _search_with_elysia_query(
    tree_data: TreeData,
    client_manager: ClientManager,
    query_text: str,
    collection_name: str,
    limit: int,
    alpha: float,
    kwargs: dict,
) -> List[Dict[str, Any]] | None:
    """
    Use Elysia Query tool for LLM-driven query optimization.
    Returns list of item properties or None if failed.
    
    Note: 
    - Elysia Query tool uses LLM to decide query strategy based on user_prompt.
    - It automatically reads from environment (including constraints_guard_tool.filters if available).
    - It yields Retrieval objects and stores results in environment["query"][collection_name].
    - Constraints from constraints_guard_tool.filters are available in environment for LLM to consider.
    """
    try:
        elysia_query = ElysiaQuery()
        
        # Ensure tree_data has user_prompt for Elysia Query tool
        # If not set, use query_text as fallback
        original_prompt = tree_data.user_prompt
        if not tree_data.user_prompt and query_text:
            # Temporarily set user_prompt for Elysia Query tool
            tree_data.user_prompt = query_text
        
        # Call Elysia Query tool
        retrieval_objects = []
        error_occurred = False
        async for result in elysia_query(
            tree_data=tree_data,
            base_lm=kwargs.get("base_lm"),
            complex_lm=kwargs.get("complex_lm"),
            client_manager=client_manager,
            inputs={"collection_names": [collection_name]},
        ):
            if isinstance(result, Error):
                logging.warning(f"Elysia Query tool returned error: {result.feedback}")
                error_occurred = True
                break
            if isinstance(result, Retrieval):
                # Extract objects from Retrieval
                if result.objects:
                    retrieval_objects.extend(result.objects)
            # Also handle Response/Status objects (ignore them, they're just progress updates)
        
        # Restore original user_prompt
        if original_prompt != tree_data.user_prompt:
            tree_data.user_prompt = original_prompt
        
        # If we got results from yielded Retrieval objects, return them
        if retrieval_objects:
            # Limit to requested limit
            return retrieval_objects[:limit]
        
        # Check environment for results (Elysia Query stores in environment["query"][collection_name])
        # Elysia Query tool stores results with name=collection_name
        query_results = tree_data.environment.find("query", collection_name)
        if query_results and query_results[0]["objects"]:
            items = query_results[0]["objects"]
            return items[:limit] if items else None
        
        # If error occurred or no results, return None (will trigger fallback)
        if error_occurred:
            logging.warning("Elysia Query tool encountered errors, will fallback to custom search")
        
        return None
    except Exception as e:
        logging.warning(f"Elysia Query tool failed: {str(e)}")
        return None


async def _search_with_custom_logic(
    tree_data: TreeData,
    client_manager: ClientManager,
    query_text: str,
    collection_name: str,
    limit: int,
    alpha: float,
) -> List[Dict[str, Any]] | None:
    """
    Use custom search logic (direct Weaviate queries).
    Returns list of item properties or None if failed.
    """
    try:
        client = client_manager.get_client()
        try:
            collection = client.collections.get(collection_name)
        except Exception as e:
            logging.error(f"Collection '{collection_name}' not found: {str(e)}")
            return None

        # Collect constraints from environment (per design: only constraints_guard_tool)
        where = None
        constraints_results = tree_data.environment.find("constraints_guard_tool", "filters")
        if constraints_results and constraints_results[0]["objects"]:
            where = constraints_results[0]["objects"][0].get("where")

        # Execute search with fallback
        def _hybrid():
            return collection.query.hybrid(query=query_text, alpha=alpha, where=where if where else None, limit=limit)

        def _bm25():
            return collection.query.bm25(query=query_text, limit=limit)

        def _fetch():
            filters = build_filters_from_where(where) if where else None
            return collection.query.fetch_objects(filters=filters, limit=limit)

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
            return None

        return [obj.properties for obj in results.objects]
    except Exception as e:
        logging.error(f"Custom search logic failed: {str(e)}")
        return None


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
    use_elysia_query: bool = False,  # Option to use Elysia Query tool for LLM-driven optimization
    **kwargs,
) -> AsyncGenerator[Result | Response | Error, None]:
    """
    Hybrid recipe retrieval with constraint-aware filters, diversity scoring, and macro-fit ranking.

    Modes:
      1. `ElysiaQuery` (LLM-optimized) when `use_elysia_query=True` and models are available.
      2. Deterministic custom Weaviate hybrid/BM25 fetch (default), honoring filters + macro targets.

    Environment contract:
      Reads
        • `constraints_guard_tool.filters` for user diet/allergen/time guardrails.
        • `macro_calc_tool.targets` (optional) to bias scoring toward per-meal targets.
      Writes
        • `search_and_rank_tool.topk` – normalized candidate list used by planning/search displays.

    Decision hints:
      • Lack of `search_and_rank_tool.topk` means downstream planning tools must not run.
      • Metadata includes `has_targets` so the agent knows whether nutrition-aware scoring ran.
    """
    logging.info(f"search_and_rank_tool: start (use_elysia_query={use_elysia_query})")
    collection_display = "recipes" if collection_name == "Recipe" else collection_name.lower()
    yield Response(f"🔍 Searching and ranking {collection_display}...")

    if limit <= 0 or limit > 1000:
        yield Error("limit must be between 1 and 1000")
        return
    if not 0.0 <= alpha <= 1.0:
        yield Error("alpha must be between 0.0 and 1.0")
        return

    try:
        # Option 1: Use Elysia Query tool for LLM-driven query optimization
        if use_elysia_query and ELYSIA_QUERY_AVAILABLE and kwargs.get("base_lm"):
            yield Response("🤖 Using AI-powered search optimization...")
            items = await _search_with_elysia_query(
                tree_data, client_manager, query_text, collection_name, limit, alpha, kwargs
            )
            if items is None:
                # Fallback to custom search if Elysia Query fails
                yield Response("⚠️ AI search unavailable, using standard search...")
                items = await _search_with_custom_logic(
                    tree_data, client_manager, query_text, collection_name, limit, alpha
                )
        else:
            # Option 2: Use custom search logic (default, deterministic)
            items = await _search_with_custom_logic(
                tree_data, client_manager, query_text, collection_name, limit, alpha
            )

        if not items:
            yield Error("No results found")
            return

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

        # Score and rank
        # Note: Recipes missing macros_per_serving will have lower macro_score (0.0)
        # The calculate_recipe_macros_tool can be called separately to backfill macros
        # before ranking, or plan_day_e2e_tool can handle macro calculation as needed
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
                    # Note: Could call calculate_recipe_macros_tool here, but that would
                    # require base_lm and add complexity. Better to handle at plan_day_e2e_tool level.

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

        # Auto-calculate missing macros for top_k items if base_lm is available
        # This ensures recipes have nutrition data before being used in meal planning
        if collection_name == "Recipe" and kwargs.get("base_lm"):
            from MealAgent.tools.nutrition.calculate_recipe_macros import calculate_recipe_macros_tool
            
            calculated_count = 0
            failed_ids: list[str] = []
            for item in top_items:
                macros = item.get("macros_per_serving", {})
                if not macros or not isinstance(macros, dict) or not macros.get("kcal"):
                    # Missing macros - try to calculate
                    food_id = item.get("food_id")
                    if food_id:
                        try:
                            async for result in calculate_recipe_macros_tool(
                                inputs={"recipe_id": str(food_id)},
                                complex_lm=None,
                                tree_data=tree_data,
                                client_manager=client_manager,
                                recipe_id=str(food_id),
                                base_lm=kwargs.get("base_lm"),
                            ):
                                if isinstance(result, Result) and result.name == "macros" and result.objects:
                                    item["macros_per_serving"] = result.objects[0]
                                    calculated_count += 1
                                    break
                                elif isinstance(result, Error):
                                    failed_ids.append(str(food_id))
                                    break
                        except Exception as e:
                            logging.warning(f"Failed to auto-calculate macros for recipe {food_id}: {str(e)}")
                            failed_ids.append(str(food_id))
                            continue

            if calculated_count > 0:
                yield Response(f"🧮 Calculated nutrition for {calculated_count} recipe(s).")
            remaining_missing = [
                item for item in top_items
                if not isinstance(item.get("macros_per_serving"), dict)
                or not item.get("macros_per_serving", {}).get("kcal")
            ]
            if remaining_missing:
                sample_ids = ", ".join(str(item.get("food_id")) for item in remaining_missing[:5])
                yield Response(
                    f"⚠️ Still missing nutrition for {len(remaining_missing)} recipe(s) (e.g. {sample_ids}). "
                    "Run calculate_recipe_macros_tool explicitly if needed."
                )

        warn = ""
        if missing_macros_count > 0 and has_targets:
            warn = f" ⚠️ {missing_macros_count} item(s) missing nutrition data."
        yield Response(f"✅ Ranked top {len(top_items)} result(s).{warn}")

        # Use recipe_card payload_type if collection is Recipe for better frontend detection
        payload_type = "recipe_card" if collection_name == "Recipe" else "generic"
        
        yield Result(
            name="topk",
            objects=top_items,
            metadata={
                "top_k": top_k,
                "total_scored": len(scored_items),
                "has_targets": has_targets,
                "collection": collection_name,
                "query": query_text,
            },
            payload_type=payload_type,
            display=True,
        )

    except Exception as e:
        yield Error(f"search_and_rank_tool failed: {str(e)}")
        return



