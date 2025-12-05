from typing import AsyncGenerator, Dict, Any, List
import logging
import random
from datetime import datetime, timedelta

from elysia.tree.objects import TreeData
from elysia.objects import Result, Error, Response, Retrieval
from elysia.util.client import ClientManager
from elysia import tool

from MealAgent.tools.utils.weaviate_filters import build_filters_from_where
from MealAgent.tools.utils.recipe_refresh import refresh_recipes
from MealAgent.tools.utils.profile_targets import (
    ensure_macro_targets,
    ensure_profile_loaded,
    resolve_user_id,
)

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
DEFAULT_TOP_K = 50


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
    *,
    sample_size: int = 200,
    randomize_offset: bool = True,
) -> List[Dict[str, Any]] | None:
    """
    Use custom search logic (direct Weaviate queries) with optional random offset sampling.
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

        # Determine fetch limit and offset for better diversity
        fetch_limit = min(max(limit, 50), sample_size)
        offset = 0
        if randomize_offset:
            try:
                # Heuristic: random offset when query is empty/short to sample broader set
                if not query_text or len(query_text.strip()) < 3:
                    offset = random.randint(0, 3000)
            except Exception:
                offset = 0

        # Execute search with fallback
        def _hybrid():
            return collection.query.hybrid(
                query=query_text,
                alpha=alpha,
                where=where if where else None,
                limit=fetch_limit,
                offset=offset,
            )

        def _bm25():
            return collection.query.bm25(query=query_text, limit=fetch_limit, offset=offset)

        def _fetch():
            filters = build_filters_from_where(where) if where else None
            return collection.query.fetch_objects(filters=filters, limit=fetch_limit, offset=offset)

        results = None
        if query_text and query_text.strip():
            # Has query text - try hybrid, then BM25
            try:
                results = _hybrid()
            except Exception:
                try:
                    results = _bm25()
                except Exception:
                    # Fallback to fetch if both fail
                    try:
                        results = _fetch()
                    except Exception:
                        results = None
        else:
            # No query text - fetch all (with filters if any)
            try:
                results = _fetch()
            except Exception:
                # If fetch fails, try without filters as last resort
                try:
                    if where:
                        # Try without constraints
                        results = collection.query.fetch_objects(limit=fetch_limit, offset=offset)
                    else:
                        results = None
                except Exception:
                    results = None

        if results is None or not results.objects:
            return None

        return [obj.properties for obj in results.objects]
    except Exception as e:
        logging.error(f"Custom search logic failed: {str(e)}")
        return None


def _calculate_macro_fit_score(recipe_macros: Dict[str, float], target_per_meal: Dict[str, float]) -> float:
    """
    Calculate how well recipe macros match target per-meal macros.
    Improved scoring: Prioritizes recipes that are close to targets (within 0.7-1.3x range).
    """
    if not recipe_macros or not recipe_macros.get("kcal"):
        return 0.0
    
    # Weight different macros by importance
    macro_weights = {
        "kcal": 0.4,      # Most important - total energy
        "protein_g": 0.3, # Very important - muscle building/satiety
        "carb_g": 0.2,    # Important - energy
        "fat_g": 0.1,     # Less critical - but still important
    }
    
    weighted_scores = []
    for key in ["kcal", "protein_g", "fat_g", "carb_g"]:
        recipe_val = recipe_macros.get(key, 0.0)
        target_val = target_per_meal.get(key, 1.0)
        weight = macro_weights.get(key, 0.25)
        
        if target_val > 0:
            ratio = recipe_val / target_val
            # Optimal range: 0.7-1.3x target (best fit)
            if 0.7 <= ratio <= 1.3:
                # Score decreases as ratio deviates from 1.0
                score = 100.0 - abs(ratio - 1.0) * 50.0
            elif 0.5 <= ratio < 0.7 or 1.3 < ratio <= 1.5:
                # Acceptable range: 0.5-0.7x or 1.3-1.5x
                score = 60.0 - abs(ratio - 1.0) * 20.0
            else:
                # Poor fit: <0.5x or >1.5x
                score = max(0.0, 30.0 - abs(ratio - 1.0) * 10.0)
            
            weighted_scores.append(score * weight)
        else:
            weighted_scores.append(0.0)
    
    # Return weighted average
    total_score = sum(weighted_scores) / sum(macro_weights.values()) if weighted_scores else 0.0
    return max(0.0, min(100.0, total_score))


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
    user_id: str | None = None,
    base_lm=None,
    complex_lm=None,
    recent_plan_window_minutes: int = 10,  # set 10080 for 7 days in production
    **kwargs,
) -> AsyncGenerator[Result | Response | Error, None]:
    """
    Hybrid recipe retrieval with constraint-aware filters, diversity scoring, and optional macro-fit ranking.

    IMPORTANT: Recipes should have macros pre-calculated in the database.
    This tool only reads macros from Weaviate, it does NOT calculate macros automatically.
    Use `calculate_recipe_macros_tool` explicitly for new recipes that are missing macros.

    Modes:
      1. `ElysiaQuery` (LLM-optimized) when `use_elysia_query=True` and models are available.
      2. Deterministic custom Weaviate hybrid/BM25 fetch (default), honoring filters + macro targets.
    
    Environment contract:
      Reads
        • `constraints_guard_tool.filters` (optional) – merged diet/allergen/time/device filters.
        • `macro_calc_tool.targets` (optional) – when present, used to bias scores toward per-meal targets.
      Writes
        • `search_and_rank_tool.topk`
            - `objects`: normalized, de-duplicated items for the chosen collection.
            - `metadata`: `top_k`, `total_scored`, `has_targets`, `collection`, `query`.

    Behaviour:
      • Never mutates profile or targets; it only reads environment state (profile/targets are owned by profile tools).
      • If no items are found, yields an `Error` and does not write `topk`.
      • Reads recipes from Weaviate to get latest macros (recipes should be pre-processed).

    Decision hints:
      • If `search_and_rank_tool.topk` is **absent or empty**, planning tools must not attempt to build a plan.
      • Use this tool for “gợi ý món ăn / danh sách công thức”; use `plan_day_e2e_tool` / `plan_day_workflow_tool`
        when the user asks for a complete **thực đơn** (daily plan).
    """
    logging.info(
        "search_and_rank_tool: start query='%s' collection=%s alpha=%.2f limit=%d top_k=%d user_id=%s use_elysia_query=%s",
        (query_text or "").strip(),
        collection_name,
        alpha,
        limit,
        top_k,
        user_id,
        use_elysia_query,
    )
    collection_display = "recipes" if collection_name == "Recipe" else collection_name.lower()
    yield Response(f"🔍 Searching and ranking {collection_display}...")

    if limit <= 0 or limit > 1000:
        yield Error("limit must be between 1 and 1000")
        return
    if not 0.0 <= alpha <= 1.0:
        yield Error("alpha must be between 0.0 and 1.0")
        return

    resolved_user_id = resolve_user_id(tree_data, user_id)
    tool_kwargs = dict(kwargs)
    tool_kwargs.setdefault("base_lm", base_lm)
    tool_kwargs.setdefault("complex_lm", complex_lm)
    profile, profile_loaded = await ensure_profile_loaded(
        tree_data,
        client_manager,
        user_id=resolved_user_id,
        base_lm=base_lm,
        complex_lm=complex_lm,
        **kwargs,
    )
    if profile_loaded:
        yield Response("👤 Loaded your profile to personalize search results.")

    targets, targets_refreshed = await ensure_macro_targets(
        tree_data,
        client_manager,
        user_id=resolved_user_id,
        base_lm=base_lm,
        complex_lm=complex_lm,
        **kwargs,
    )
    if targets_refreshed and targets:
        yield Response(
            f"📊 Personalized targets ready: {targets.get('tdee_kcal', 0):.0f} kcal | "
            f"{targets.get('protein_g', 0):.0f}g protein | "
            f"{targets.get('carb_g', 0):.0f}g carbs"
        )

    try:
        # Option 1: Use Elysia Query tool for LLM-driven query optimization
        if use_elysia_query and ELYSIA_QUERY_AVAILABLE and base_lm:
            yield Response("🤖 Using AI-powered search optimization...")
            items = await _search_with_elysia_query(
                tree_data, client_manager, query_text, collection_name, limit, alpha, tool_kwargs
            )
            if items is None:
                # Fallback to custom search if Elysia Query fails
                yield Response("⚠️ AI search unavailable, using standard search...")
                items = await _search_with_custom_logic(
                tree_data,
                client_manager,
                query_text,
                collection_name,
                limit,
                alpha,
                sample_size=tool_kwargs.get("sample_size", 200),
                randomize_offset=tool_kwargs.get("randomize_offset", True),
                )
        else:
            # Option 2: Use custom search logic (default, deterministic)
            items = await _search_with_custom_logic(
                tree_data,
                client_manager,
                query_text,
                collection_name,
                limit,
                alpha,
                sample_size=kwargs.get("sample_size", 200),
                randomize_offset=kwargs.get("randomize_offset", True),
            )

        if not items:
            yield Error("No results found")
            return
        logging.debug(
            "search_and_rank_tool: raw items fetched=%d (collection=%s)",
            len(items),
            collection_name,
        )

        # Normalize and deduplicate
        normalized = [_normalize_item(item, collection_name) for item in items]
        deduped = _deduplicate_items(normalized, collection_name)

        # Exclude recipes present in recent MealPlans (avoid repetition)
        if collection_name == "Recipe" and user_id:
            try:
                client = client_manager.get_client()
                plan_collection = client.collections.get("MealPlan")
                item_collection = client.collections.get("MealPlanItem")

                window_minutes = max(1, int(recent_plan_window_minutes or 10))
                recent_date = (datetime.now() - timedelta(minutes=window_minutes)).isoformat()
                plan_filter = build_filters_from_where({
                    "operator": "And",
                    "operands": [
                        {"path": ["user_id"], "operator": "Equal", "valueString": user_id},
                        {"path": ["created_at"], "operator": "GreaterThan", "valueDate": recent_date},
                    ],
                })
                recent_plans = plan_collection.query.fetch_objects(filters=plan_filter, limit=10)
                recent_recipe_ids: set[str] = set()
                for plan_obj in recent_plans.objects:
                    plan_id = plan_obj.properties.get("plan_id")
                    if not plan_id:
                        continue
                    item_filter = build_filters_from_where(
                        {"path": ["plan_id"], "operator": "Equal", "valueString": plan_id}
                    )
                    items_obj = item_collection.query.fetch_objects(filters=item_filter, limit=200)
                    for it in items_obj.objects:
                        rid = it.properties.get("recipe_id")
                        if rid:
                            recent_recipe_ids.add(str(rid))

                if recent_recipe_ids:
                    filtered = [r for r in deduped if str(r.get("food_id")) not in recent_recipe_ids]
                    # Ensure we still have enough items; if not, fall back to deduped
                    if len(filtered) >= max(top_k, 20):
                        deduped = filtered
            except Exception as e:
                logging.debug(f"search_and_rank_tool: skip recent-plan exclusion due to error: {e}")

        # Targets (optional)
        targets_results = tree_data.environment.find("macro_calc_tool", "targets")
        targets = targets_results[0]["objects"][0] if (targets_results and targets_results[0]["objects"]) else targets
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

            # IMPROVED SCORING: Prioritize macro fit when targets are available
            # This ensures recipes that match user's profile get higher priority
            if has_targets and target_per_meal:
                # Increased weight for macro_score (70%) to prioritize profile matching
                # Reduced semantic_score weight (20%) and diversity_score (10%)
                total_score = 0.7 * macro_score + 0.2 * semantic_score + 0.1 * diversity_score
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

        # IMPROVED VARIETY: randomize within a wider top pool and enforce macros presence
        top_items: list[Dict[str, Any]] = []
        seen_dish_names: set[str] = set()
        seen_ingredient_sets: set[frozenset] = set()

        # Build a larger pool then shuffle to increase diversity
        pool_size = max(top_k * 3, top_k + 50, 60)
        top_pool = scored_items[:pool_size]
        random.shuffle(top_pool)

        def _has_macros(item: Dict[str, Any]) -> bool:
            macros = item.get("macros_per_serving", {})
            return isinstance(macros, dict) and macros.get("kcal")

        for item in top_pool:
            if len(top_items) >= top_k:
                break

            # Skip items without macros to avoid 0-kcal entries
            if not _has_macros(item):
                continue

            dish_name = str(item.get("dish_name", "")).lower().strip()
            if dish_name and dish_name in seen_dish_names:
                continue

            ingredients = set(str(ing).lower().strip() for ing in item.get("ingredients", []))
            if ingredients:
                max_overlap_ratio = 0.0
                for seen_ings in seen_ingredient_sets:
                    if seen_ings:
                        overlap = len(ingredients & seen_ings)
                        total = len(ingredients | seen_ings)
                        if total > 0:
                            overlap_ratio = overlap / total
                            max_overlap_ratio = max(max_overlap_ratio, overlap_ratio)
                if max_overlap_ratio > 0.8:
                    continue

            top_items.append(item)
            if dish_name:
                seen_dish_names.add(dish_name)
            if ingredients:
                seen_ingredient_sets.add(frozenset(ingredients))

        # If still not enough, fill with remaining items that have macros
        if len(top_items) < top_k:
            remaining = [it for it in scored_items if it not in top_items and _has_macros(it)]
            top_items.extend(remaining[: top_k - len(top_items)])

        # Refresh recipes from Weaviate to ensure we have latest macros
        # Recipes should already have macros pre-calculated in the database
        if collection_name == "Recipe":
            def _count_missing(items: list[Dict[str, Any]]) -> int:
                return sum(
                    1
                    for item in items
                    if not item.get("macros_per_serving")
                    or not isinstance(item.get("macros_per_serving"), dict)
                    or not item.get("macros_per_serving", {}).get("kcal")
                )

            missing_before_refresh = _count_missing(top_items)
            try:
                client = client_manager.get_client()
                top_items = refresh_recipes(top_items, client, collection_name="Recipe", hydrate_fields=True)
                missing_after_refresh = _count_missing(top_items)
                missing_ids = [
                    str(item.get("food_id") or item.get("recipe_id") or item.get("id"))
                    for item in top_items
                    if not item.get("macros_per_serving")
                    or not isinstance(item.get("macros_per_serving"), dict)
                    or not item.get("macros_per_serving", {}).get("kcal")
                ][:5]
                logging.debug(
                    "search_and_rank_tool: refreshed %d recipes (missing macros before=%d, after=%d, sample_missing=%s)",
                    len(top_items),
                    missing_before_refresh,
                    missing_after_refresh,
                    missing_ids or "none",
                )
            except Exception as refresh_exc:
                logging.debug(f"Failed to refresh recipes from Weaviate: {refresh_exc}")
                # Continue with existing items if refresh fails
            
            # Check for missing macros (should be rare if recipes are pre-processed)
            missing_macros_count = sum(
                1
                for item in top_items
                if not item.get("macros_per_serving")
                or not isinstance(item.get("macros_per_serving"), dict)
                or not item.get("macros_per_serving", {}).get("kcal")
            )
            
            logging.debug(
                "search_and_rank_tool: scoring summary missing_macros=%d total_scored=%d top_items=%d",
                missing_macros_count,
                len(scored_items),
                len(top_items),
            )
            for preview in top_items[:3]:
                bd = preview.get("_score_breakdown", {})
                logging.debug(
                    "search_and_rank_tool: top preview id=%s dish=%s fit=%.2f macro=%s semantic=%s diversity=%s kcal=%s",
                    preview.get("food_id") or preview.get("recipe_id") or preview.get("id"),
                    preview.get("dish_name"),
                    preview.get("fit_score"),
                    bd.get("macro"),
                    bd.get("semantic"),
                    bd.get("diversity"),
                    (preview.get("macros_per_serving") or {}).get("kcal"),
                )
            
            if missing_macros_count > 0:
                sample_ids = ", ".join(
                    str(item.get("food_id")) for item in top_items[:5]
                    if not item.get("macros_per_serving") or not isinstance(item.get("macros_per_serving"), dict)
                    or not item.get("macros_per_serving", {}).get("kcal")
                )
                yield Response(
                    f"⚠️ {missing_macros_count} recipe(s) missing nutrition data (e.g. {sample_ids}). "
                    "Run calculate_recipe_macros_tool explicitly for new recipes."
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



