from typing import AsyncGenerator, Dict, Any, List
import logging
from datetime import datetime, timedelta, timezone
from collections import Counter
import random

from elysia.tree.objects import TreeData
from elysia.objects import Result, Error, Response
from elysia.util.client import ClientManager
from elysia import tool

from MealAgent.tools.utils.planning_helpers import (
    _get_meal_macros,
    _validate_macro_targets,
    sync_plan_to_weaviate,
    _calculate_plan_micronutrients,
    ensure_rfc3339_datetime,
)
from MealAgent.tools.utils.recipe_classifiers import (
    _is_vietnamese_breakfast,
    _is_rice_dish,
    _is_noodle_soup,
    _is_soup,
    _is_main_dish,
    _is_vegetable_dish,
    _is_fruit,
    _is_combined_dish,
    _matches_meal_slot,
)
from MealAgent.tools.plan_day.plan_day_e2e import _create_default_white_rice_recipe, _enrich_rice_meal
from MealAgent.tools.utils.meal_selection import (
    select_meal_by_strategy,
    calculate_recipe_fit_score,
)
from MealAgent.tools.utils.meal_assembly import select_accompaniments, add_supplementary_dishes
from MealAgent.utils.nutrition import build_default_macro_targets
from MealAgent.tools.utils.weaviate_filters import build_filters_from_where
from MealAgent.tools.utils.recipe_refresh import refresh_recipes
from MealAgent.tools.utils.profile_targets import (
    ensure_macro_targets,
    ensure_profile_loaded,
    resolve_user_id,
)
from MealAgent.tools.utils.llm_draft import generate_llm_draft
from MealAgent.schemas.llm_draft import LLMDraftResponse


logger = logging.getLogger(__name__)

# Toggle for very verbose LLM suggestion mapping logs.
# Default False to avoid log spam; set to True only when deep-debugging mapping behavior.
LLM_SUGGESTION_DEBUG_VERBOSE = False


def _record_missing_macro_state(tree_data: TreeData, recipe_ids: List[str]) -> None:
    try:
        tree_data.environment.add_objects(
            "plan_week_e2e_tool",
            "missing_macros",
            [
                {
                    "recipe_ids": recipe_ids,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
            ],
        )
    except Exception:
        logging.debug("plan_week_e2e_tool: failed to record missing macros in environment.")


def _clear_missing_macro_state(tree_data: TreeData) -> None:
    """Signal to the tree that nutrition blockers have been resolved."""
    try:
        tree_data.environment.add_objects(
            "plan_week_e2e_tool",
            "missing_macros",
            [
                {
                    "recipe_ids": [],
                    "status": "resolved",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
            ],
        )
    except Exception:
        logging.debug("plan_week_e2e_tool: failed to clear missing macros state.")


def _strip_device_filters(filters_results: list[Dict[str, Any]] | None) -> tuple[Dict[str, Any] | None, Dict[str, Any] | None]:
    """
    Remove any device-related constraints from the cached constraints_guard_tool result.
    This ensures weekly planning does not depend on `devices` in Recipe collection.
    """
    if not filters_results or not filters_results[0].get("objects"):
        return None, None

    filters_entry = filters_results[0]
    metadata = dict(filters_entry.get("metadata") or {})
    where = filters_entry["objects"][0].get("where") or {}

    def _clean(node: Dict[str, Any] | None) -> Dict[str, Any] | None:
        if not isinstance(node, dict):
            return node
        path = node.get("path")
        if path and "devices" in path:
            return None
        if "operator" in node and "operands" in node:
            cleaned = [o for o in (_clean(op) for op in node.get("operands", [])) if o]
            if not cleaned:
                return {}
            if len(cleaned) == 1:
                return cleaned[0]
            return {k: v for k, v in node.items() if k != "operands"} | {"operands": cleaned}
        return node

    cleaned_where = _clean(where) or {}
    filters_entry["objects"][0]["where"] = cleaned_where
    # Strip device metadata so downstream logic ignores it
    for key in ("required_device", "exclude_devices"):
        if key in metadata:
            metadata[key] = None if key == "required_device" else []
    filters_entry["metadata"] = metadata
    return cleaned_where, metadata


# Recipe classification functions imported from MealAgent.tools.utils.recipe_classifiers
# _calculate_recipe_fit_score moved to MealAgent.tools.utils.meal_selection.calculate_recipe_fit_score
# _select_meal_by_strategy moved to MealAgent.tools.utils.meal_selection.select_meal_by_strategy


def _validate_constraints_weekly(
    plan: Dict[str, Any],
    diet_types: List[str] | None = None,
    exclude_allergens: List[str] | None = None,
) -> Dict[str, Any]:
    """Validate that weekly plan meals respect diet/allergen constraints."""
    violations = []

    # Iterate through all days and meals
    for day_key, day_data in plan.get("days", {}).items():
        for meal_key, meal_data in day_data.get("meals", {}).items():
            recipe = meal_data.get("recipe", {})
            recipe_id = recipe.get("food_id", "")

            # Check diet type (if Recipe has diet_type field)
            if diet_types:
                recipe_diet = recipe.get("diet_type")
                if recipe_diet:
                    recipe_diets = [recipe_diet] if isinstance(recipe_diet, str) else recipe_diet
                    if not any(dt in recipe_diets for dt in diet_types):
                        violations.append({
                            "day": day_key,
                            "meal": meal_key,
                            "recipe_id": recipe_id,
                            "type": "diet_mismatch",
                            "expected": diet_types,
                            "actual": recipe_diets,
                        })

            # Check allergens (if Recipe has allergens field)
            if exclude_allergens:
                recipe_allergens = recipe.get("allergens", [])
                if recipe_allergens:
                    overlap = set(recipe_allergens) & set(exclude_allergens)
                    if overlap:
                        violations.append({
                            "day": day_key,
                            "meal": meal_key,
                            "recipe_id": recipe_id,
                            "type": "allergen_violation",
                            "forbidden_allergens": list(overlap),
                        })

    return {
        "valid": len(violations) == 0,
        "violations": violations,
    }


def _calculate_variety_score(plan: Dict[str, Any]) -> float:
    """
    Calculate variety score (0-100, higher is better).
    
    User requirement: OK to repeat ingredients (beef, chicken, pork, fish) with different recipes/cooking methods.
    Score based on:
    - Number of unique recipes
    - Cooking method diversity (nướng, kho, xào, chiên, hấp, etc.)
    - Ingredient diversity
    - Reduced penalty for same ingredient with different cooking methods
    """
    recipe_counts = Counter()
    cooking_methods = set()
    main_ingredients = set()  # Track main proteins (gà, bò, heo, cá)
    recipe_cooking_map = {}  # Map recipe to cooking method
    
    # Cooking method keywords
    cooking_keywords = {
        "nướng": ["nướng", "nuong", "grill", "roast", "barbecue"],
        "kho": ["kho", "braise", "stew"],
        "xào": ["xào", "xao", "stir-fry", "sauté"],
        "chiên": ["chiên", "chien", "fry", "fried"],
        "hấp": ["hấp", "hap", "steam", "steamed"],
        "luộc": ["luộc", "luoc", "boil", "boiled"],
        "nấu": ["nấu", "nau", "cook", "cooked"],
        "canh": ["canh", "soup"],
    }
    
    # Main protein keywords
    protein_keywords = {
        "gà": ["gà", "ga", "chicken"],
        "bò": ["bò", "bo", "beef"],
        "heo": ["heo", "pork"],
        "cá": ["cá", "ca", "fish"],
        "tôm": ["tôm", "tom", "shrimp"],
    }
    
    for day_data in plan.get("days", {}).values():
        for meal_data in day_data.get("meals", {}).values():
            recipe = meal_data.get("recipe", {})
            food_id = recipe.get("food_id")
            if food_id:
                recipe_counts[food_id] += 1
                
                # Extract cooking method from dish name
                dish_name = str(recipe.get("dish_name", "")).lower()
                cooking_method = None
                for method, keywords in cooking_keywords.items():
                    if any(kw in dish_name for kw in keywords):
                        cooking_method = method
                        break
                if cooking_method:
                    cooking_methods.add(cooking_method)
                    recipe_cooking_map[food_id] = cooking_method
                
                # Extract main protein from dish name
                for protein, keywords in protein_keywords.items():
                    if any(kw in dish_name for kw in keywords):
                        main_ingredients.add(protein)
                        break
    
    if not recipe_counts:
        return 0.0
    
    total_meals = sum(recipe_counts.values())
    unique_recipes = len(recipe_counts)
    
    # Base score: percentage of unique recipes
    uniqueness_ratio = unique_recipes / total_meals if total_meals > 0 else 0.0
    
    # Cooking method diversity (user requirement: different cooking methods increase variety)
    cooking_diversity = min(1.0, len(cooking_methods) / 8.0)  # 8 different cooking methods max
    
    # Repetition penalty - reduced if same ingredient has different cooking methods
    repetition_penalty = 0.0
    recipe_cooking_pairs = {}  # Track (ingredient, cooking_method) pairs
    
    for food_id, count in recipe_counts.items():
        if count > 1:
            # Check if this recipe has different cooking methods (less penalty)
            cooking_method = recipe_cooking_map.get(food_id)
            if cooking_method:
                # Reduced penalty if cooking method is diverse
                penalty = (count - 1) * 0.05  # Reduced from 0.1 to 0.05
            else:
                # Full penalty if no cooking method identified
                penalty = (count - 1) * 0.1
            repetition_penalty += penalty
    
    max_penalty = (total_meals - unique_recipes) * 0.1
    penalty_ratio = repetition_penalty / max_penalty if max_penalty > 0 else 0.0
    
    # Ingredient diversity
    all_ingredients = set()
    for day_data in plan.get("days", {}).values():
        for meal_data in day_data.get("meals", {}).values():
            recipe = meal_data.get("recipe", {})
            ingredients = recipe.get("ingredients", [])
            for ing in ingredients:
                if isinstance(ing, str):
                    all_ingredients.add(ing.lower().strip())
                elif isinstance(ing, dict):
                    all_ingredients.add(str(ing.get("name", "")).lower().strip())
    
    ingredient_diversity = min(1.0, len(all_ingredients) / (total_meals * 3))
    
    # Main protein diversity (user requirement: OK to repeat proteins with different recipes)
    protein_diversity = min(1.0, len(main_ingredients) / 5.0)  # 5 different proteins max
    
    # Composite score - adjusted weights to favor cooking method diversity
    variety_score = (
        uniqueness_ratio * 0.35 +  # Reduced from 0.5
        (1.0 - penalty_ratio) * 0.25 +  # Reduced from 0.3
        cooking_diversity * 0.20 +  # NEW: cooking method diversity
        ingredient_diversity * 0.15 +  # Reduced from 0.2
        protein_diversity * 0.05  # NEW: main protein diversity
    ) * 100.0
    
    return max(0.0, min(100.0, variety_score))


@tool
async def plan_week_e2e_tool(
    tree_data: TreeData,
    client_manager: ClientManager,
    base_lm=None,
    query_text: str = "",
    start_date: str | None = None,
    macro_tolerance_percent: float = 0.15,
    min_variety_score: float = 50.0,
    user_id: str | None = None,
    plan_id: str | None = None,
    recent_plan_window_minutes: int = 10080,  # 7 days (7 * 24 * 60 = 10080 minutes) - recipes won't repeat within 7 days
    **kwargs,
) -> AsyncGenerator[Result | Response | Error, None]:
    """
    Weekly end-to-end planner: combine ranked recipes and targets into a 7‑day (21‑meal) plan.

    IMPORTANT: Recipes should have macros pre-calculated in the database.
    This tool only reads macros from Weaviate, it does NOT calculate macros automatically.
    Use `calculate_recipe_macros_tool` explicitly for new recipes that are missing macros.

    Environment contract:
      Reads
        • `macro_calc_tool.targets` – daily macros (multiplied internally ×7 for validation).
        • `constraints_guard_tool.filters` – guardrail filters.
        • `search_and_rank_tool.topk` – ranked recipes (should have `macros_per_serving` pre-calculated).
      Writes
        • `plan_week_e2e_tool.plan` – normalized weekly payload used by downstream tooling/UI.
        • `plan_week_e2e_tool.missing_macros` – list of recipe IDs missing macros (for manual calculation if needed).

    Decision hints:
      • Use this tool when the user asks for a **weekly meal plan** (e.g. "lên thực đơn cả tuần"), not for ad‑hoc recipe lists.
      • `plan_week_e2e_tool.plan` existing implies success; consult metadata.valid & variety_score.
      • Non-empty `missing_macros` indicates recipes need macro calculation (run `calculate_recipe_macros_tool`).
    """
    logging.info(
        "plan_week_e2e_tool: start query='%s' user_id=%s macro_tol=%.2f recent_window_min=%s variety_min=%.1f",
        (query_text or "").strip(),
        user_id,
        macro_tolerance_percent,
        recent_plan_window_minutes,
        min_variety_score,
    )
    yield Response("📅 Planning your weekly meals (21 meals over 7 days)...")
    
    try:
        hidden_store = tree_data.environment.hidden_environment
        resolved_user_id = resolve_user_id(tree_data, user_id)
        if resolved_user_id:
            hidden_store["user_id"] = resolved_user_id
        user_id = resolved_user_id

        profile, profile_loaded = await ensure_profile_loaded(
            tree_data=tree_data,
            client_manager=client_manager,
            user_id=resolved_user_id,
            base_lm=base_lm,
            complex_lm=None,
            **kwargs,
        )
        if profile_loaded and profile and resolved_user_id:
            yield Response(f"✅ Profile loaded for user {resolved_user_id}")
        logging.debug(
            "plan_week_e2e_tool: profile_loaded=%s user_id=%s profile_fields=%s",
            profile_loaded,
            resolved_user_id,
            list(profile.keys()) if isinstance(profile, dict) else None,
        )

        # Defer macro target calculation until after we have a candidate recipe list
        targets: Dict[str, Any] | None = None
        
        # Step 2: Read constraints filters (for validation)
        # Align behaviour with plan_day_e2e_tool:
        # - Ensure constraints_guard_tool is invoked if no filters exist yet
        # - Then read and strip device-related filters for validation only
        filters_results = tree_data.environment.find("constraints_guard_tool", "filters")
        filters_metadata: Dict[str, Any] | None = None

        try:
            if not filters_results or not filters_results[0].get("objects"):
                # Lazily initialize constraints if they have not been set up in this session
                from MealAgent.tools.constraints.constraints_guard import constraints_guard_tool

                async for result in constraints_guard_tool(
                    tree_data=tree_data,
                    inputs={},
                    base_lm=base_lm,
                    complex_lm=None,
                    client_manager=client_manager,
                    **kwargs,
                ):
                    if isinstance(result, Error):
                        error_msg = str(result) if hasattr(result, "__str__") else "Unknown error"
                        logging.warning(
                            "plan_week_e2e_tool: constraints_guard_tool failed: %s",
                            error_msg,
                        )
                        break
                # Re-read after constraints_guard_tool
                filters_results = tree_data.environment.find("constraints_guard_tool", "filters")
        except Exception as cg_exc:
            logging.debug("plan_week_e2e_tool: constraints_guard_tool invocation failed: %s", cg_exc)

        if filters_results and filters_results[0].get("objects"):
            _strip_device_filters(filters_results)
            filters_metadata = filters_results[0].get("metadata") or {}
            diet_types = filters_metadata.get("diet_types", [])
            allergens = filters_metadata.get("exclude_allergens", [])
            constraint_msg = "✅ Applying your dietary preferences"
            if diet_types:
                constraint_msg += f" ({', '.join(diet_types)})"
            if allergens:
                constraint_msg += f" (excluding: {', '.join(allergens)})"
            yield Response(constraint_msg)
        else:
            yield Response("ℹ️ No dietary constraints specified")
        
        # Step 3: Search recipes from Weaviate database
        # IMPORTANT: Always search from Weaviate to get latest data, not from environment cache
        # Environment cache may be stale - Weaviate is the source of truth
        yield Response("🔍 Searching recipes from database...")
        try:
            from MealAgent.tools.search.search_and_rank import search_and_rank_tool

            # Search recipes from Weaviate database
            # This ensures we always get the latest recipes with up-to-date macros
            search_query = query_text if query_text else "Vietnamese recipes"
            recipes: list[Dict[str, Any]] = []
            
            async for result in search_and_rank_tool(
                tree_data=tree_data,
                inputs={},
                base_lm=base_lm,
                complex_lm=None,
                client_manager=client_manager,
                query_text=search_query,
                collection_name="Recipe",
                limit=1000,  # Maximum allowed by search_and_rank_tool (increased from 200 to 1000 for maximum variety)
                top_k=1000,  # Top 1000 for planning (increased from 200 to 1000, max allowed by Weaviate)
                **kwargs,
            ):
                if isinstance(result, Error):
                    error_msg = str(result) if hasattr(result, '__str__') else "Unknown error"
                    yield Error(
                        f"Failed to search recipes from database: {error_msg}. "
                        "Please check your search query or try a different query."
                    )
                    return
                if isinstance(result, Response):
                    # Forward progress messages to the user
                    yield result
                elif isinstance(result, Result) and result.objects:
                    # Capture the ranked recipes from Weaviate search
                    recipes = list(result.objects)

            # Fallback: If search returned no results, try reading from environment cache
            # This is only a fallback - primary source is always Weaviate
            if not recipes:
                logging.debug("plan_week_e2e_tool: No recipes from Weaviate search, trying environment cache...")
                sr = tree_data.environment.find("search_and_rank_tool", "topk")
                if sr:
                    for entry in reversed(sr):
                        objs = entry.get("objects") or []
                        if objs:
                            # Handle case where objs is a list containing a list of recipes
                            if len(objs) == 1 and isinstance(objs[0], list):
                                recipes = objs[0]
                            else:
                                recipes = objs
                            break
                    if recipes:
                        yield Response("⚠️ Using cached recipes (database search returned no results)")
            
            if not recipes:
                yield Error(
                    "No recipes found in database. "
                    "Please check your search query or ensure recipes are available in Weaviate."
                )
                return

            yield Response(f"✅ Found {len(recipes)} recipe(s) from database for planning.")
            logging.debug(
                "plan_week_e2e_tool: recipes from Weaviate search count=%d query='%s'",
                len(recipes),
                query_text,
            )
        except Exception as e:  # pragma: no cover - defensive
            logging.error("plan_week_e2e_tool: Failed to search recipes from Weaviate: %s", e)
            # Last resort: try environment cache
            sr = tree_data.environment.find("search_and_rank_tool", "topk")
            recipes = []
            if sr:
                for entry in reversed(sr):
                    objs = entry.get("objects") or []
                    if objs:
                        if len(objs) == 1 and isinstance(objs[0], list):
                            recipes = objs[0]
                        else:
                            recipes = objs
                        break
                if recipes:
                    yield Response("⚠️ Using cached recipes (database search failed)")
            
            if not recipes:
                yield Error(
                    f"Failed to search recipes from database: {str(e)}. "
                    "Please search for recipes first using search_and_rank_tool."
                )
                return
        
        # IMPROVED VARIETY: Exclude recently used recipes (by ID and name) to avoid repetition
        recent_recipe_ids = set()
        recent_recipe_names = set()
        try:
            client = client_manager.get_client()
            plan_collection = client.collections.get("MealPlan")
            item_collection = client.collections.get("MealPlanItem")
            meal_log_collection = client.collections.get("MealLogEntry")
            
            # Get recent plans within 7 days window for better variety
            if user_id:
                window_days = 7
                recent_date = ensure_rfc3339_datetime(
                    datetime.now(timezone.utc) - timedelta(days=window_days)
                )
                plan_filter = build_filters_from_where({
                    "operator": "And",
                    "operands": [
                        {"path": ["user_id"], "operator": "Equal", "valueString": user_id},
                        {"path": ["created_at"], "operator": "GreaterThan", "valueDate": recent_date}
                    ]
                })
                
                recent_plans = plan_collection.query.fetch_objects(filters=plan_filter, limit=10)
                if recent_plans.objects:
                    # Collect all recipe IDs from recent plans
                    for plan_obj in recent_plans.objects:
                        plan_id = plan_obj.properties.get("plan_id")
                        if plan_id:
                            item_filter = build_filters_from_where(
                                {"path": ["plan_id"], "operator": "Equal", "valueString": plan_id}
                            )
                            items = item_collection.query.fetch_objects(filters=item_filter, limit=100)
                            for item_obj in items.objects:
                                recipe_id = item_obj.properties.get("recipe_id")
                                if recipe_id:
                                    recent_recipe_ids.add(str(recipe_id))
                                dish_name = item_obj.properties.get("dish_name")
                                if dish_name:
                                    recent_recipe_names.add(str(dish_name).lower().strip())
                
                # Also get meal history recipe IDs (last 30 days) from MealLogEntry,
                # consistent with plan_day_e2e_tool (consumed meals, not just suggested plans)
                meal_history_date = ensure_rfc3339_datetime(
                    datetime.now(timezone.utc) - timedelta(days=30)
                )
                meal_filter = build_filters_from_where(
                    {
                        "operator": "And",
                        "operands": [
                            {"path": ["user_id"], "operator": "Equal", "valueString": user_id},
                            {"path": ["logged_at"], "operator": "GreaterThan", "valueDate": meal_history_date},
                        ],
                    }
                )

                meal_logs = meal_log_collection.query.fetch_objects(filters=meal_filter, limit=100)
                for log_obj in meal_logs.objects:
                    recipe_id = log_obj.properties.get("recipe_id")
                    if recipe_id:
                        recent_recipe_ids.add(str(recipe_id))
                    dish_name = log_obj.properties.get("dish_name")
                    if dish_name:
                        recent_recipe_names.add(str(dish_name).lower().strip())
                
                # Always allow default white rice as fallback (do not block it)
                recent_recipe_ids.discard("default_white_rice")
                recent_recipe_names.discard("cơm trắng")
                recent_recipe_names.discard("com trang")
                recent_recipe_names.discard("white rice")

                # CRITICAL: Use fuzzy matching to block similar dishes (aligned with plan_day_e2e.py)
                def _dish_name_similar(name1: str, name2: str, threshold: float = 0.7) -> bool:
                    """
                    Check if two dish names are similar (fuzzy match).
                    Returns True if similarity >= threshold (0.7 = 70% similar).
                    """
                    name1 = name1.lower().strip()
                    name2 = name2.lower().strip()
                    
                    # Exact match
                    if name1 == name2:
                        return True
                    
                    # Check if one contains the other (common case: "Thịt Kho Mắm Ruốc" vs "Thịt Heo Kho Mắm Ruốc")
                    if name1 in name2 or name2 in name1:
                        # Calculate similarity ratio
                        shorter = min(len(name1), len(name2))
                        longer = max(len(name1), len(name2))
                        if shorter > 0:
                            similarity = shorter / longer
                            if similarity >= threshold:
                                return True
                    
                    # Check word overlap (at least 70% of words match)
                    words1 = set(name1.split())
                    words2 = set(name2.split())
                    if words1 and words2:
                        common_words = words1 & words2
                        total_words = words1 | words2
                        if total_words:
                            word_similarity = len(common_words) / len(total_words)
                            if word_similarity >= threshold:
                                return True
                    
                    return False
                
                def _apply_exclusion(pool: list[Dict[str, Any]], ids: set[str], names: set[str]) -> list[Dict[str, Any]]:
                    """
                    Apply exclusion with fuzzy matching (aligned with plan_day_e2e.py).
                    Blocks recipes by exact ID match, exact name match, and fuzzy name match (similarity > 0.7).
                    """
                    if not pool:
                        return pool
                    id_block = ids or set()
                    name_block = names or set()
                    # CRITICAL: Always apply strong exclusion first (both ID and name block)
                    # This prevents meal repetition even if it reduces the pool significantly
                    # IMPROVED: Also use fuzzy matching to block similar dish names (not just exact match)
                    filtered = []
                    for r in pool:
                        rid = str(r.get("food_id", ""))
                        rname = str(r.get("dish_name", "")).lower().strip()
                        
                        # Block by exact ID match
                        if rid in id_block:
                            continue
                        
                        # Block by exact name match
                        if rname in name_block:
                            continue
                        
                        # CRITICAL: Block by fuzzy name match (similar dishes)
                        # This prevents selecting "Thịt Kho Mắm Ruốc" when "Thịt Heo Kho Mắm Ruốc" was already used
                        is_similar = False
                        for blocked_name in name_block:
                            if _dish_name_similar(rname, blocked_name, threshold=0.7):
                                is_similar = True
                                break
                        
                        if is_similar:
                            continue
                        
                        filtered.append(r)
                    
                    # Only relax if we have very few recipes left (less than 20)
                    # This ensures we still block most duplicates even with small recipe pool
                    if len(filtered) >= 20:
                        return filtered
                    
                    # If too few remain, relax fuzzy name block but ALWAYS keep ID block and exact name block
                    # ID block is more reliable than name block (exact match vs fuzzy match)
                    filtered = []
                    for r in pool:
                        rid = str(r.get("food_id", ""))
                        rname = str(r.get("dish_name", "")).lower().strip()
                        
                        # Always block by exact ID match
                        if rid in id_block:
                            continue
                        
                        # Always block by exact name match
                        if rname in name_block:
                            continue
                        
                        # Relax fuzzy matching - only block if very similar (threshold 0.85 instead of 0.7)
                        is_very_similar = False
                        for blocked_name in name_block:
                            if _dish_name_similar(rname, blocked_name, threshold=0.85):
                                is_very_similar = True
                                break
                        
                        if is_very_similar:
                            continue
                        
                        filtered.append(r)
                    
                    if len(filtered) >= 10:
                        return filtered
                    
                    # Last resort: if we have less than 10 recipes after ID block, 
                    # we still apply ID block but allow name matches (better than nothing)
                    # This is rare and only happens when recipe pool is very small
                    return filtered if filtered else pool

                # CRITICAL: Use _apply_exclusion with fuzzy matching (aligned with plan_day_e2e.py)
                before = len(recipes)
                recipes = _apply_exclusion(recipes, recent_recipe_ids, recent_recipe_names)
                after = len(recipes)
                dropped = before - after
                
                # Log detailed info about what was blocked
                if dropped > 0:
                        yield Response(
                        f"🔄 Excluded {dropped} recently used recipe(s) (including similar dishes) "
                            f"to ensure variety across your weekly meal plan"
                        )
                #     logging.info(
                #         "plan_week_e2e_tool: VARIETY_FILTER_APPLIED | user_id=%s | "
                #         "recipes_before=%d recipes_after=%d dropped=%d | "
                #         "blocked_ids=%d blocked_names=%d",
                #         user_id,
                #         before,
                #         after,
                #         dropped,
                #         len(recent_recipe_ids),
                #         len(recent_recipe_names),
                #     )
                # else:
                #     logging.debug(
                #         "plan_week_e2e_tool: VARIETY_FILTER_APPLIED | user_id=%s | "
                #         "no_dishes_dropped recipes_before=%d recipes_after=%d | "
                #         "blocked_ids=%d blocked_names=%d",
                #         user_id,
                #         before,
                #         after,
                #         len(recent_recipe_ids),
                #         len(recent_recipe_names),
                            # )
        except Exception as e:
            logging.debug(f"plan_week_e2e_tool: Could not check recent plans for variety: {e}")
            # Continue with all recipes if check fails
        
        if len(recipes) < 7:
            yield Response(
                f"⚠️ Warning: Only {len(recipes)} recipes available. Some recipes will be reused for 21 meals."
            )
        
        # Refresh recipes from Weaviate to ensure we have latest macros.
        # To avoid excessive logging from refresh_recipes (one log per recipe),
        # only refresh when there are actually recipes missing macros, similar to plan_day_e2e_tool.
        def _count_missing_macros(items: list[Dict[str, Any]]) -> int:
            return sum(
                1
                for r in items
                if not r.get("macros_per_serving")
                or not isinstance(r.get("macros_per_serving"), dict)
                or not r.get("macros_per_serving", {}).get("kcal")
            )

        missing_before_refresh = _count_missing_macros(recipes)
        if missing_before_refresh > 0:
            try:
                client = client_manager.get_client()
                recipes = refresh_recipes(recipes, client, collection_name="Recipe", hydrate_fields=True)
                missing_after_refresh = _count_missing_macros(recipes)
                logging.debug(
                    "plan_week_e2e_tool: refresh_recipes done | missing_before=%d missing_after=%d",
                    missing_before_refresh,
                    missing_after_refresh,
                )
            except Exception as refresh_exc:
                logging.debug(
                    "plan_week_e2e_tool: refresh_recipes failed, continue without refresh: %s",
                    refresh_exc,
                )

        # Shuffle a few times to avoid clustered selections and improve variety
        for _ in range(3):
            random.shuffle(recipes)
        
        # Check for missing macros (should be rare if recipes are pre-processed)
        missing_macros = [
            r for r in recipes
            if not r.get("macros_per_serving") or not isinstance(r.get("macros_per_serving"), dict)
            or not r.get("macros_per_serving", {}).get("kcal")
        ]
        
        if missing_macros:
            missing_ids = [str(r.get("food_id")) for r in missing_macros[:10] if r.get("food_id")]
            if missing_ids:
                _record_missing_macro_state(tree_data, missing_ids)
                yield Response(
                    f"⚠️ {len(missing_macros)} recipe(s) missing nutrition data. "
                    f"Run calculate_recipe_macros_tool for these recipes if needed. "
                    f"Continuing with available recipes..."
                )
        
        # At this point we have candidate recipes. Now ensure nutritional targets are ready
        targets, targets_refreshed = await ensure_macro_targets(
            tree_data=tree_data,
            client_manager=client_manager,
            user_id=resolved_user_id,
            base_lm=base_lm,
            complex_lm=None,
            **kwargs,
        )
        if targets_refreshed and targets:
            yield Response("🧮 Recalculating nutritional targets from your profile...")

        if targets:
            yield Response(
                f"📊 Using your targets: {targets.get('tdee_kcal', 0):.0f} kcal | "
                f"{targets.get('protein_g', 0):.0f}g protein | "
                f"{targets.get('carb_g', 0):.0f}g carbs"
            )
        else:
            targets = build_default_macro_targets()
            yield Response(
                f"📊 Using default targets: {targets['tdee_kcal']:.0f} kcal/day "
                "(create a profile for personalized targets)"
            )

        # Step 4: Parse start_date or use today
        if start_date:
            try:
                date_str = start_date.replace("Z", "+00:00")
                try:
                    start = datetime.fromisoformat(date_str)
                except ValueError:
                    try:
                        start = datetime.fromisoformat(start_date)
                    except ValueError:
                        for fmt in ["%Y-%m-%d", "%Y/%m/%d", "%d-%m-%Y", "%d/%m/%Y"]:
                            try:
                                start = datetime.strptime(start_date, fmt)
                                break
                            except ValueError:
                                continue
                        else:
                            raise ValueError(f"Unsupported date format: {start_date}")
                start = start.replace(hour=0, minute=0, second=0, microsecond=0)
            except (ValueError, AttributeError) as e:
                yield Error(f"Invalid start_date format: {start_date}. Use ISO format (YYYY-MM-DD). Error: {str(e)}")
                return
        else:
            start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        
        # Step 5: Generate LLM draft for meal suggestions (aligned with plan_day)
        llm_draft: LLMDraftResponse | None = None
        if base_lm:
            try:
                yield Response("🤖 Generating meal suggestions with AI...")
                profile_results = tree_data.environment.find("profile_crud_tool", "profile")
                user_preferences = ""
                if profile_results and profile_results[0]["objects"]:
                    profile = profile_results[0]["objects"][0]
                    user_preferences = profile.get("preferences", "") or ""
                
                # Collect meal history for context
                meal_history_dish_names = []
                try:
                    client = client_manager.get_client()
                    # Use MealLogEntry for CONSUMED meals, aligned with plan_day_e2e_tool
                    meal_log_collection = client.collections.get("MealLogEntry")
                    if user_id:
                        meal_history_date = ensure_rfc3339_datetime(
                            datetime.now(timezone.utc) - timedelta(days=30)
                        )
                        meal_filter = build_filters_from_where(
                            {
                                "operator": "And",
                                "operands": [
                                    {"path": ["user_id"], "operator": "Equal", "valueString": user_id},
                                    {"path": ["logged_at"], "operator": "GreaterThan", "valueDate": meal_history_date},
                                ],
                            }
                        )
                        meal_logs = meal_log_collection.query.fetch_objects(filters=meal_filter, limit=50)
                        for log_obj in meal_logs.objects:
                            dish_name = log_obj.properties.get("dish_name")
                            if dish_name:
                                meal_history_dish_names.append(str(dish_name))
                except Exception as e:
                    logging.debug(f"plan_week_e2e_tool: Could not collect meal history: {e}")
                
                # Build constraints dict
                constraints_dict = {}
                if filters_metadata:
                    constraints_dict = {
                        "diet_types": filters_metadata.get("diet_types", []),
                        "exclude_allergens": filters_metadata.get("exclude_allergens", []),
                    }
                
                llm_draft = await generate_llm_draft(
                    base_lm=base_lm,
                    meal_history=meal_history_dish_names,
                    constraints=constraints_dict,
                    user_preferences=user_preferences if user_preferences else None,
                    tree_data=tree_data,
                )
                if llm_draft:
                    yield Response("✅ AI suggestions ready. Using to guide meal selection...")
                else:
                    yield Response("ℹ️ Using rule-based selection (AI suggestions unavailable)")
            except Exception as e:
                logging.warning(f"plan_week_e2e_tool: LLM draft failed: {e}")
                llm_draft = None
        else:
            logging.debug("plan_week_e2e_tool: No base_lm available, skipping LLM draft")
        
        # Step 6: Assemble 21-meal plan with Vietnamese meal patterns
        # Use macro_fit strategy if targets available for better quality
        selection_strategy = "macro_fit" if targets else "balanced"
        yield Response("🔍 Selecting 21 meals following Vietnamese meal patterns and your nutritional targets...")
        
        weekly_plan = {}
        total_macros = {"kcal": 0.0, "protein_g": 0.0, "fat_g": 0.0, "carb_g": 0.0}
        used_recipe_ids: set[str] = set()
        used_recipes: List[Dict[str, Any]] = []
        # CRITICAL: Track breakfast IDs separately to avoid repetition across days
        used_breakfast_ids: set[str] = set()
        # Track dish names to reduce repeats across the week (case-insensitive)
        used_dish_names: set[str] = set()
        # CRITICAL: Track recently used recipes per day to avoid repetition in recent days
        recently_used_per_day: Dict[int, set[str]] = {}

        def _track_name(recipe: Dict[str, Any]) -> None:
            dname = str(recipe.get("dish_name", "")).lower().strip() if recipe else ""
            if dname:
                used_dish_names.add(dname)

        def _is_default_white_rice_id(recipe_id: str | None) -> bool:
            """Return True if the id corresponds to the default white rice fallback."""
            return str(recipe_id) == "default_white_rice"
        
        # Calculate max_kcal per meal to avoid selecting dishes that are too high
        # Align with daily planner: lighter lunch, heavier dinner for VN pattern
        if targets:
            breakfast_max_kcal = min(550.0, targets.get("tdee_kcal", 2000) * 0.25)
            lunch_max_kcal = min(700.0, targets.get("tdee_kcal", 2000) * 0.30)
            dinner_max_kcal = min(950.0, targets.get("tdee_kcal", 2000) * 0.40)
        else:
            breakfast_max_kcal = 550.0
            lunch_max_kcal = 700.0
            dinner_max_kcal = 950.0

        def _filter_reasonable_recipes(
            recipes: List[Dict[str, Any]],
            day_index: int,
        ) -> List[Dict[str, Any]]:
            """
            Filter out unreasonable recipes (kcal too high or protein too low).
            Returns filtered list and logs filtered count.
            CRITICAL: Relaxed filtering to preserve variety - only filter extreme outliers.
            """
            filtered_recipes = []
            filtered_count = 0
            for recipe in recipes:
                macros = _get_meal_macros(recipe)
                recipe_kcal = macros.get("kcal", 0.0)
                recipe_protein = macros.get("protein_g", 0.0)
                
                is_breakfast = _is_vietnamese_breakfast(recipe)
                # RELAXED: Only filter extreme outliers to preserve variety
                # Increased breakfast cap from 600 to 800 to allow more breakfast options
                # Increased main dish kcal cap from 2000 to 2500 to allow more variety
                max_reasonable_kcal = 2500.0 if not is_breakfast else 800.0
                # RELAXED: Only filter main dishes with extremely low protein (< 3g instead of 5g)
                # This allows more variety while still filtering truly unreasonable dishes
                min_reasonable_protein = 3.0
                
                # Only filter if kcal is extremely high (not just slightly over)
                if recipe_kcal > max_reasonable_kcal * 1.2:  # Only filter if >20% over cap
                    filtered_count += 1
                    logging.debug(
                        f"plan_week_e2e_tool: Day {day_index + 1} - Filtered out recipe '{recipe.get('dish_name', 'Unknown')}' "
                        f"(food_id={recipe.get('food_id', 'Unknown')}) - kcal extremely high: {recipe_kcal:.1f} > {max_reasonable_kcal * 1.2:.1f}"
                    )
                    continue
                
                # Only filter main dishes with extremely low protein
                if _is_main_dish(recipe) and recipe_protein < min_reasonable_protein:
                    filtered_count += 1
                    logging.debug(
                        f"plan_week_e2e_tool: Day {day_index + 1} - Filtered out recipe '{recipe.get('dish_name', 'Unknown')}' "
                        f"(food_id={recipe.get('food_id', 'Unknown')}) - protein extremely low: {recipe_protein:.1f} < {min_reasonable_protein:.1f}"
                    )
                    continue
                
                filtered_recipes.append(recipe)
            
            if filtered_count > 0:
                logging.info(
                    f"plan_week_e2e_tool: Day {day_index + 1} - Filtered out {filtered_count} unreasonable recipe(s) "
                    f"(available_recipes: {len(recipes)} -> {len(filtered_recipes)})"
                )
            return filtered_recipes

        def _search_breakfast_pools(
            recipes_pool: List[Dict[str, Any]],
            all_recipes: List[Dict[str, Any]] | None,
            used_ids: set[str],
            used_breakfast_ids: set[str] | None,
            used_names: set[str] | None = None,
            min_kcal: float = 0.0,
            max_kcal: float = float("inf"),
            min_protein: float = 0.0,
            prefer_unused: bool = True,
        ) -> Dict[str, Any] | None:
            """
            Unified helper to search for breakfast in recipes_pool and all_recipes.
            Prioritizes unused breakfasts if prefer_unused=True.
            Returns best breakfast found (highest protein) or None.
            """
            # Fallback to empty set when caller does not provide used_names
            used_names = used_names or set()

            search_pools = [recipes_pool]
            if all_recipes:
                search_pools.append(all_recipes)
            
            best_breakfast = None
            best_protein = 0.0
            
            # First pass: try unused breakfasts if prefer_unused
            if prefer_unused and used_breakfast_ids:
                for pool in search_pools:
                    for recipe in pool:
                        recipe_id = str(recipe.get("food_id", ""))
                        if recipe_id in used_ids:
                            continue
                        if recipe_id in used_breakfast_ids:
                            continue
                        dish_name = str(recipe.get("dish_name", "")).lower().strip()
                        if dish_name and dish_name in used_names:
                            continue
                        if not _is_vietnamese_breakfast(recipe):
                            continue
                        
                        macros = _get_meal_macros(recipe)
                        kcal = macros.get("kcal", 0.0)
                        protein = macros.get("protein_g", 0.0)
                        
                        if min_kcal <= kcal <= max_kcal and protein >= min_protein and protein > best_protein:
                            best_breakfast = recipe
                            best_protein = protein
                
                if best_breakfast:
                    return best_breakfast
            
            # Second pass: allow reuse if no unused breakfast found
            for pool in search_pools:
                for recipe in pool:
                    recipe_id = str(recipe.get("food_id", ""))
                    if recipe_id in used_ids:
                        continue
                        dish_name = str(recipe.get("dish_name", "")).lower().strip()
                        if dish_name and dish_name in used_names:
                            continue
                    if not _is_vietnamese_breakfast(recipe):
                        continue
                    
                    macros = _get_meal_macros(recipe)
                    kcal = macros.get("kcal", 0.0)
                    protein = macros.get("protein_g", 0.0)
                    
                    if min_kcal <= kcal <= max_kcal and protein >= min_protein and protein > best_protein:
                        best_breakfast = recipe
                        best_protein = protein
            
            return best_breakfast

        def _validate_and_select_main_dish(
            meal_slot: str,
            day_index: int,
            candidate: Dict[str, Any] | None,
            available_recipes: List[Dict[str, Any]],
            excluded: List[Dict[str, Any]],
            used_ids: set[str],
            used_names: set[str],
            meal_targets: Dict[str, float] | None,
            max_kcal: float,
            min_protein: float,
            llm_draft=None,
        ) -> Dict[str, Any] | None:
            """
            Unified function to validate and select main dish for lunch/dinner.
            Returns validated main dish or None.
            """
            # Try LLM suggestions first
            if not candidate and llm_draft:
                candidate = _try_select_from_llm_suggestions(
                    llm_draft, meal_slot, "main",
                    available_recipes, excluded, used_ids,
                    min_kcal=50.0, max_kcal=max_kcal
                )
                if candidate:
                    dname = str(candidate.get("dish_name", "")).lower().strip()
                    if dname and dname in used_names:
                        candidate = None  # reject if repeated by name
            
            # Fallback to rule-based selection
            # CRITICAL: Try multiple strategies with rotation to increase variety
            # Rotate strategies based on day_index to ensure different selections each day
            strategies = ["highest_protein", "balanced", "macro_fit", "highest_carb"]
            strategy_index = day_index % len(strategies)
            
            # Try strategies in rotated order
            for i in range(len(strategies)):
                current_strategy = strategies[(strategy_index + i) % len(strategies)]
                if not candidate:
                    candidate = select_meal_by_strategy(
                        available_recipes, current_strategy,
                        exclude=excluded, used_recipe_ids=used_ids,
                        preferred_meal_type=meal_slot, dish_category="main",
                        target_macros=meal_targets,
                        require_macros=True,
                        min_kcal=50.0,
                        max_kcal=max_kcal,
                        min_protein=min_protein,
                    )
                    if candidate:
                        dname = str(candidate.get("dish_name", "")).lower().strip()
                        if dname and dname in used_names:
                            candidate = None  # skip repeated dish name across week
                        else:
                            logging.debug(
                                f"plan_week_e2e_tool: Day {day_index + 1} - {meal_slot} main selected using strategy '{current_strategy}'"
                            )
                            break
            
            # Final fallback: try without category restriction for maximum variety
            if not candidate:
                candidate = select_meal_by_strategy(
                    available_recipes, "balanced",
                    exclude=excluded, used_recipe_ids=used_ids,
                    preferred_meal_type=meal_slot,
                    target_macros=meal_targets,
                    require_macros=True,
                    min_kcal=50.0,
                    max_kcal=max_kcal,
                )
                if candidate:
                    dname = str(candidate.get("dish_name", "")).lower().strip()
                    if dname and dname in used_names:
                        candidate = None
            
            # Validate candidate
            if candidate:
                main_macros = _get_meal_macros(candidate)
                main_kcal = main_macros.get("kcal", 0.0)
                main_protein = main_macros.get("protein_g", 0.0)
                
                if main_kcal > 2000.0:
                    logging.warning(
                        f"plan_week_e2e_tool: Day {day_index + 1} - Rejecting invalid {meal_slot} main "
                        f"'{candidate.get('dish_name', 'Unknown')}' (food_id={candidate.get('food_id', 'Unknown')}) - "
                        f"kcal too high: {main_kcal:.1f} > 2000.0"
                    )
                    return None
                elif not _is_main_dish(candidate):
                    logging.warning(
                        f"plan_week_e2e_tool: Day {day_index + 1} - Rejecting invalid {meal_slot} main "
                        f"'{candidate.get('dish_name', 'Unknown')}' (food_id={candidate.get('food_id', 'Unknown')}) - not a main dish"
                    )
                    return None
                elif main_protein < 5.0:
                    logging.warning(
                        f"plan_week_e2e_tool: Day {day_index + 1} - Rejecting invalid {meal_slot} main "
                        f"'{candidate.get('dish_name', 'Unknown')}' (food_id={candidate.get('food_id', 'Unknown')}) - "
                        f"protein too low: {main_protein:.1f} < 5.0"
                    )
                    return None
                else:
                    logging.debug(
                        f"plan_week_e2e_tool: Day {day_index + 1} - {meal_slot.capitalize()} main selected: '{candidate.get('dish_name', 'Unknown')}' "
                        f"(food_id={candidate.get('food_id', 'Unknown')}) | "
                        f"Macros: kcal={main_macros.get('kcal', 0):.1f} protein={main_macros.get('protein_g', 0):.1f} "
                        f"fat={main_macros.get('fat_g', 0):.1f} carb={main_macros.get('carb_g', 0):.1f}"
                    )
                    return candidate
            
            return None

        def _select_side_dish(
            meal_slot: str,
            day_index: int,
            dish_type: str,  # "vegetable" or "fruit"
            available_recipes: List[Dict[str, Any]],
            excluded: List[Dict[str, Any]],
            used_ids: set[str],
            used_names: set[str],
            meal_targets: Dict[str, float] | None,
            max_retries: int = 3,
        ) -> Dict[str, Any] | None:
            """
            Unified function to select vegetable or fruit dish with validation and retry logic.
            Returns validated side dish or None.
            """
            is_vegetable = dish_type == "vegetable"
            validator = _is_vegetable_dish if is_vegetable else _is_fruit
            
            # CRITICAL: Try multiple strategies with day-based rotation to increase variety
            strategies = ["balanced", "highest_carb", "macro_fit", "highest_protein"] if is_vegetable else ["balanced", "highest_carb", "macro_fit"]
            strategy_index = (day_index * 2 + (0 if is_vegetable else 1)) % len(strategies)  # Different rotation for veg vs fruit
            for retry in range(max_retries):
                strategy = strategies[(strategy_index + retry) % len(strategies)]  # Rotate strategies for variety
                candidate = select_meal_by_strategy(
                    available_recipes, strategy,
                    exclude=excluded, used_recipe_ids=used_ids,
                    preferred_meal_type=meal_slot, dish_category=dish_type,
                    target_macros=meal_targets,
                    require_macros=True,
                    min_kcal=30.0,
                    max_kcal=150.0,
                )
                if candidate:
                    dname = str(candidate.get("dish_name", "")).lower().strip()
                    if dname and dname in used_names:
                        candidate = None
                
                # Validate candidate
                if candidate and validator(candidate):
                    if is_vegetable and _is_main_dish(candidate):
                        # Invalid: vegetable should not be a main dish
                        excluded.append(candidate)
                        logging.debug(
                            f"plan_week_e2e_tool: Day {day_index + 1} - Rejecting invalid {meal_slot} {dish_type} candidate "
                            f"'{candidate.get('dish_name', 'Unknown')}' (retry {retry + 1}/{max_retries})"
                        )
                        continue
                    
                    macros = _get_meal_macros(candidate)
                    logging.debug(
                        f"plan_week_e2e_tool: Day {day_index + 1} - {meal_slot.capitalize()} {dish_type} selected: "
                        f"'{candidate.get('dish_name', 'Unknown')}' (food_id={candidate.get('food_id', 'Unknown')}) | "
                        f"Macros: kcal={macros.get('kcal', 0):.1f}"
                    )
                    return candidate
                elif candidate:
                    # Invalid selection, exclude it and retry
                    excluded.append(candidate)
                    logging.debug(
                        f"plan_week_e2e_tool: Day {day_index + 1} - Rejecting invalid {meal_slot} {dish_type} candidate "
                        f"'{candidate.get('dish_name', 'Unknown')}' (retry {retry + 1}/{max_retries})"
                    )
            
            return None

        def _calculate_meal_requirements(
            remaining_targets: Dict[str, float] | None,
            targets: Dict[str, Any] | None,
        ) -> tuple[float, float]:
            """
            Calculate max_kcal and min_protein requirements for main dish selection.
            Returns (max_main_kcal, min_main_protein).
            """
            max_main_kcal = 500.0
            min_main_protein = 18.0
            
            if remaining_targets and targets:
                protein_remaining = remaining_targets.get("protein_g", 0.0)
                daily_protein = targets.get("protein_g", 150.0)
                protein_ratio = protein_remaining / daily_protein if daily_protein > 0 else 1.0
                
                kcal_remaining = remaining_targets.get("kcal", 0.0)
                daily_kcal = targets.get("tdee_kcal", 2000.0)
                kcal_ratio = kcal_remaining / daily_kcal if daily_kcal > 0 else 1.0
                reduction_factor = 0.85 if kcal_ratio < 0.5 else 1.0
                
                if protein_ratio > 0.5:
                    max_main_kcal = min(600.0 * reduction_factor, 500.0)
                    min_main_protein = 32.0
                elif protein_ratio > 0.4:
                    max_main_kcal = min(550.0 * reduction_factor, 450.0)
                    min_main_protein = 28.0
                elif protein_ratio > 0.2:
                    max_main_kcal = min(450.0 * reduction_factor, 400.0)
                    min_main_protein = 25.0
                else:
                    max_main_kcal = min(400.0 * reduction_factor, 350.0)
                    min_main_protein = 22.0
            
            return max_main_kcal, min_main_protein

        def _try_select_from_llm_suggestions(
            llm_draft,
            meal_slot: str,
            role: str,
            recipes: List[Dict[str, Any]],
            excluded: List[Dict[str, Any]],
            used_ids: set[str],
            min_kcal: float = 0.0,
            max_kcal: float | None = None,
        ) -> Dict[str, Any] | None:
            """
            Try to select a recipe from LLM suggestions for a specific role.
            
            Returns selected recipe or None if no good match found.
            """
            if not llm_draft:
                return None
            
            meal_draft = getattr(llm_draft, meal_slot, None)
            if not meal_draft or not meal_draft.suggestions:
                return None
            
            for suggestion in meal_draft.suggestions:
                suggestion_dict = suggestion.model_dump() if hasattr(suggestion, 'model_dump') else suggestion
                suggestion_role = suggestion_dict.get("role", "")
                
                if suggestion_role == role:
                    mapped_recipe = _map_llm_suggestion_to_recipe(
                        suggestion_dict,
                        recipes,
                        role
                    )
                    if mapped_recipe and mapped_recipe not in excluded:
                        if str(mapped_recipe.get("food_id", "")) not in used_ids:
                            # Validate kcal range if specified
                            if max_kcal or min_kcal > 0:
                                macros = _get_meal_macros(mapped_recipe)
                                kcal = macros.get("kcal", 0.0)
                                if min_kcal <= kcal <= (max_kcal or float('inf')):
                                    return mapped_recipe
                            else:
                                return mapped_recipe
            return None

        def _map_llm_suggestion_to_recipe(
            suggestion: Dict[str, Any],
            recipes: List[Dict[str, Any]],
            role: str,
        ) -> Dict[str, Any] | None:
            """
            Map LLM suggestion to actual recipe from database with improved fuzzy matching.
            
            Args:
                suggestion: LLM suggestion with dish_name, general_term, role, category
                recipes: List of recipes from database
                role: Expected role (breakfast, carb, main, vegetable, fruit)
            
            Returns:
                Best matching recipe, or None if not found
            """
            dish_name = suggestion.get("dish_name", "").lower().strip()
            general_term = suggestion.get("general_term", "").lower().strip()
            category = suggestion.get("category", "").lower().strip()
            
            if not dish_name:
                if LLM_SUGGESTION_DEBUG_VERBOSE:
                    logging.debug(
                        "_map_llm_suggestion_to_recipe: Empty dish_name in suggestion: %s",
                        suggestion,
                    )
                return None
            
            # Extract keywords from dish_name (remove common words)
            import re
            common_words = {"và", "với", "kèm", "và", "của", "the", "with", "and", "for"}
            dish_keywords = [w for w in re.split(r'[\s,]+', dish_name) if w and w not in common_words and len(w) > 2]
            
            # Score recipes by match quality
            scored_recipes = []
            for recipe in recipes:
                recipe_name = str(recipe.get("dish_name", "")).lower().strip()
                recipe_type = str(recipe.get("dish_type", "")).lower()
                
                if not recipe_name:
                    continue
                
                score = 0.0
                
                # Exact name match (highest priority)
                if dish_name == recipe_name:
                    score += 200.0
                elif dish_name in recipe_name or recipe_name in dish_name:
                    score += 100.0
                
                # Keyword matching (fuzzy match) - count matching keywords
                if dish_keywords:
                    matching_keywords = sum(1 for kw in dish_keywords if kw in recipe_name)
                    if matching_keywords > 0:
                        keyword_ratio = matching_keywords / len(dish_keywords)
                        score += 60.0 * keyword_ratio  # Up to 60 points for keyword match
                
                # General term match
                if general_term:
                    if general_term == recipe_name:
                        score += 90.0
                    elif general_term in recipe_name:
                        score += 80.0
                    # Also check if general_term keywords match
                    general_keywords = [w for w in re.split(r'[-_\s]+', general_term) if w and len(w) > 2]
                    if general_keywords:
                        matching_general = sum(1 for kw in general_keywords if kw in recipe_name)
                        if matching_general > 0:
                            score += 40.0 * (matching_general / len(general_keywords))
                
                # Category match
                if category:
                    if category == "rice" and _is_rice_dish(recipe):
                        score += 50.0
                    elif category == "noodle" and _is_noodle_soup(recipe):
                        score += 50.0
                    elif category == "soup" and _is_soup(recipe):
                        score += 50.0
                    elif category == "main_dish" and _is_main_dish(recipe):
                        score += 50.0
                    elif category == "vegetable" and _is_vegetable_dish(recipe):
                        score += 50.0
                    elif category == "fruit" and _is_fruit(recipe):
                        score += 50.0
                
                # Role match (with validation to prevent mismatches)
                if role == "breakfast" and _is_vietnamese_breakfast(recipe):
                    score += 30.0
                elif role == "carb":
                    # CRITICAL: Only match if it's actually a carb dish (rice/noodle) AND NOT a main dish
                    if (_is_rice_dish(recipe) or _is_noodle_soup(recipe)) and not _is_main_dish(recipe):
                        score += 30.0
                    else:
                        # Penalize main dishes when role is "carb"
                        if _is_main_dish(recipe):
                            score -= 50.0  # Heavy penalty for main dish when expecting carb
                elif role == "main" and _is_main_dish(recipe):
                    score += 30.0
                elif role == "vegetable" and _is_vegetable_dish(recipe):
                    score += 30.0
                elif role == "fruit" and _is_fruit(recipe):
                    score += 30.0
                
                if score > 0:
                    scored_recipes.append((recipe, score))
            
            # Return best match (with improved threshold to avoid poor matches)
            if scored_recipes:
                scored_recipes.sort(key=lambda x: x[1], reverse=True)
                best_recipe, best_score = scored_recipes[0]
                
                # IMPROVED THRESHOLD: Require at least one meaningful match, not just role/category
                # Calculate what contributed to the score
                recipe_name = str(best_recipe.get("dish_name", "")).lower().strip()
                
                # Check for name-based matches (exact, substring, keyword)
                has_exact_match = dish_name == recipe_name
                has_substring_match = dish_name in recipe_name or recipe_name in dish_name
                has_keyword_match = False
                if dish_keywords:
                    matching_keywords_count = sum(1 for kw in dish_keywords if kw in recipe_name)
                    has_keyword_match = matching_keywords_count > 0
                
                # Check for general term match
                has_general_term_match = False
                if general_term:
                    has_general_term_match = general_term == recipe_name or general_term in recipe_name
                
                # Minimum threshold: Require at least ONE of:
                # 1. Exact match (200 points)
                # 2. Substring match (100 points) 
                # 3. Keyword match (at least 1 keyword, score >= 50)
                # 4. General term match (80+ points)
                # 5. Multiple criteria combined (score >= 60)
                # This prevents matches based ONLY on role/category (30 points)
                
                if (
                    has_exact_match
                    or has_substring_match
                    or (has_keyword_match and best_score >= 50.0)
                    or (has_general_term_match and best_score >= 80.0)
                    or best_score >= 60.0
                ):
                    if LLM_SUGGESTION_DEBUG_VERBOSE:
                        logging.debug(
                            "_map_llm_suggestion_to_recipe: Matched '%s' -> '%s' "
                            "(score: %.1f, role: %s, exact: %s, substring: %s, "
                            "keyword: %s, general: %s)",
                            dish_name,
                            best_recipe.get("dish_name", "Unknown"),
                            best_score,
                            role,
                            has_exact_match,
                            has_substring_match,
                            has_keyword_match,
                            has_general_term_match,
                        )
                    return best_recipe
                else:
                    if LLM_SUGGESTION_DEBUG_VERBOSE:
                        logging.debug(
                            "_map_llm_suggestion_to_recipe: No good match for '%s' "
                            "(best score: %.1f - only role/category match, insufficient)",
                            dish_name,
                            best_score,
                        )
            
            if LLM_SUGGESTION_DEBUG_VERBOSE:
                logging.debug(
                    "_map_llm_suggestion_to_recipe: No match found for '%s' (role: %s)",
                    dish_name,
                    role,
                )
            return None

        def _select_carb_with_validation(
            meal_slot: str,
            recipes: List[Dict[str, Any]],
            excluded: List[Dict[str, Any]],
            used_ids: set[str],
            selection_strategy: str,
            meal_targets: Dict[str, float] | None,
            meal_max_kcal: float,
            llm_draft=None,
        ) -> tuple[Dict[str, Any] | None, bool, bool]:
            """
            Select carb (rice/noodle) for a meal slot with LLM fallback and validation (aligned with plan_day).
            
            Returns: (carb_recipe, is_combined, is_noodle)
            """
            # Prefer a plain white rice candidate up-front if available
            for recipe in recipes:
                if (
                    recipe not in excluded
                    and str(recipe.get("food_id", "")) not in used_ids
                    and _is_rice_dish(recipe)
                    and not _is_main_dish(recipe)
                    and not _is_combined_dish(recipe)
                ):
                    name_lower = str(recipe.get("dish_name", "")).lower()
                    if "cơm trắng" in name_lower or "com trang" in name_lower or "white rice" in name_lower:
                        macros = _get_meal_macros(recipe)
                        kcal = macros.get("kcal", 0.0)
                        if 80.0 <= kcal <= meal_max_kcal:
                            logging.debug(
                                f"plan_week_e2e_tool: Found plain white rice for {meal_slot}: "
                                f"'{recipe.get('dish_name', 'Unknown')}'"
                            )
                            return recipe, False, False

            # Try LLM suggestions first
            carb_recipe = _try_select_from_llm_suggestions(
                llm_draft, meal_slot, "carb",
                recipes, excluded, used_ids,
                min_kcal=100.0, max_kcal=meal_max_kcal
            )
            
            if carb_recipe:
                # Validate it's actually a carb dish
                if not _is_rice_dish(carb_recipe) and not _is_noodle_soup(carb_recipe):
                    logging.warning(f"LLM suggested {meal_slot} carb is not rice/noodle: {carb_recipe.get('dish_name', 'Unknown')}")
                    carb_recipe = None
                elif _is_main_dish(carb_recipe):
                    logging.warning(f"LLM suggested {meal_slot} carb is a main dish: {carb_recipe.get('dish_name', 'Unknown')}")
                    carb_recipe = None

            # Fallback to rule-based selection
            # CRITICAL: Try multiple strategies with rotation to increase variety
            # Use meal_slot to create variation (lunch vs dinner get different strategy order)
            strategies = ["highest_carb", "balanced", "macro_fit", selection_strategy if meal_targets else "balanced"]
            # Remove duplicates while preserving order
            strategies = list(dict.fromkeys(strategies))
            strategy_offset = 0 if meal_slot == "lunch" else 1  # Different offset for lunch vs dinner
            
            # Try strategies in rotated order
            for i in range(len(strategies)):
                current_strategy = strategies[(strategy_offset + i) % len(strategies)]
                if not carb_recipe:
                    # First try with category restriction
                    carb_recipe = select_meal_by_strategy(
                        recipes, current_strategy,
                        exclude=excluded,
                        used_recipe_ids=used_ids,
                        preferred_meal_type=meal_slot,
                        dish_category="rice",
                        target_macros=meal_targets,
                        require_macros=True,
                        max_kcal=meal_max_kcal
                    )
                    if carb_recipe:
                        logging.debug(
                            f"plan_week_e2e_tool: {meal_slot} carb selected using strategy '{current_strategy}'"
                        )
                        break
            
            # Final fallback: try without category restriction
            if not carb_recipe:
                carb_recipe = select_meal_by_strategy(
                    recipes, "balanced",
                    exclude=excluded,
                    used_recipe_ids=used_ids,
                    preferred_meal_type=meal_slot,
                    target_macros=meal_targets,
                    require_macros=True,
                    max_kcal=meal_max_kcal
                )
            
            # Validate it's actually a carb dish
            if carb_recipe:
                if not _is_rice_dish(carb_recipe) and not _is_noodle_soup(carb_recipe):
                    logging.warning(
                        f"plan_week_e2e_tool: Selected {meal_slot} carb is not rice/noodle: "
                        f"'{carb_recipe.get('dish_name', 'Unknown')}'"
                    )
                    carb_recipe = None
                elif _is_main_dish(carb_recipe):
                    logging.warning(
                        f"plan_week_e2e_tool: Selected {meal_slot} carb is a main dish: "
                        f"'{carb_recipe.get('dish_name', 'Unknown')}'"
                    )
                    carb_recipe = None
            
            # Try standalone noodle dishes if still not found
            if not carb_recipe:
                for recipe in recipes:
                    if recipe in excluded or str(recipe.get("food_id", "")) in used_ids:
                        continue
                    if _is_noodle_soup(recipe) and not _is_combined_dish(recipe):
                        macros = _get_meal_macros(recipe)
                        kcal = macros.get("kcal", 0.0)
                        if 100.0 <= kcal <= meal_max_kcal:
                            carb_recipe = recipe
                            logging.debug(
                                f"plan_week_e2e_tool: Found noodle dish for {meal_slot}: "
                                f"'{carb_recipe.get('dish_name', 'Unknown')}'"
                            )
                            break
            
            # Validate and normalize
            is_combined = carb_recipe and _is_combined_dish(carb_recipe)
            is_noodle = carb_recipe and _is_noodle_soup(carb_recipe) and not is_combined
            
            if not carb_recipe:
                logging.warning(
                    f"plan_week_e2e_tool: No valid rice/noodle found for {meal_slot}, using default white rice"
                )
                return _create_default_white_rice_recipe(), False, False
            
            # Final validation: must be rice or noodle, not main dish
            if not _is_rice_dish(carb_recipe) and not _is_noodle_soup(carb_recipe):
                logging.warning(
                    f"plan_week_e2e_tool: Selected {meal_slot}_carb is not rice/noodle: "
                    f"'{carb_recipe.get('dish_name', 'Unknown')}', using default white rice"
                )
                return _create_default_white_rice_recipe(), False, False
            
            if _is_main_dish(carb_recipe):
                logging.warning(
                    f"plan_week_e2e_tool: Selected {meal_slot}_carb is a main dish: "
                    f"'{carb_recipe.get('dish_name', 'Unknown')}', using default white rice"
                )
                return _create_default_white_rice_recipe(), False, False
            
            # If combined rice dish, use default white rice
            if _is_rice_dish(carb_recipe) and is_combined:
                logging.warning(
                    f"plan_week_e2e_tool: Selected {meal_slot}_carb is combined dish, using default white rice"
                )
                return _create_default_white_rice_recipe(), False, False
            
            return carb_recipe, is_combined, is_noodle

        def _select_breakfast(
            recipes_pool: List[Dict[str, Any]],
            used_ids: set[str],
            remaining: Dict[str, float] | None,
            used_breakfast_ids: set[str] | None = None,
            llm_draft=None,
            all_recipes: List[Dict[str, Any]] | None = None,  # Full recipes pool for fallback
        ) -> Dict[str, Any] | None:
            """
            Pick a Vietnamese breakfast with stronger nutrition guarantees (aligned with plan_day).
            Prioritizes protein, enforces kcal/fat caps, and has multiple fallback layers.
            Uses LLM suggestions if available.
            
            Args:
                recipes_pool: Available recipes (may be filtered by used_recipe_ids)
                used_ids: Set of recipe IDs already used in this day
                remaining: Remaining nutritional targets
                used_breakfast_ids: Set of breakfast IDs used in previous days
                llm_draft: LLM draft suggestions
                all_recipes: Full recipes pool for fallback when recipes_pool is exhausted
            """
            breakfast_targets = targets.copy() if targets else None
            if breakfast_targets and remaining:
                breakfast_targets["_remaining_targets"] = remaining.copy()

            daily_protein = breakfast_targets.get("protein_g", 150.0) if breakfast_targets else 150.0
            # Calculate minimum acceptable protein for breakfast (aligned with plan_day)
            if daily_protein > 180:
                min_acceptable_protein = 20.0
            elif daily_protein > 150:
                min_acceptable_protein = 18.0
            else:
                min_acceptable_protein = 15.0

            breakfast_max_kcal = 550.0  # Cap breakfast at 550 kcal (aligned with plan_day)

            # Count Vietnamese breakfasts in recipes_pool and all_recipes for debugging
            vietnamese_breakfasts_in_pool = [r for r in recipes_pool if _is_vietnamese_breakfast(r)]
            unused_in_pool = [r for r in vietnamese_breakfasts_in_pool 
                             if used_breakfast_ids and str(r.get("food_id", "")) not in used_breakfast_ids]
            all_vietnamese_breakfasts = []
            unused_in_all = []
            if all_recipes:
                all_vietnamese_breakfasts = [r for r in all_recipes if _is_vietnamese_breakfast(r)]
                unused_in_all = [r for r in all_vietnamese_breakfasts 
                                if used_breakfast_ids and str(r.get("food_id", "")) not in used_breakfast_ids]
            
            logging.debug(
                f"plan_week_e2e_tool: _select_breakfast called | recipes_pool={len(recipes_pool)} | used_ids={len(used_ids)} | "
                f"used_breakfast_ids={list(used_breakfast_ids) if used_breakfast_ids else None} | has_llm_draft={llm_draft is not None} | "
                f"vietnamese_breakfasts_in_pool={len(vietnamese_breakfasts_in_pool)} unused_in_pool={len(unused_in_pool)} | "
                f"all_vietnamese_breakfasts={len(all_vietnamese_breakfasts)} unused_in_all={len(unused_in_all)}"
            )

            # Try LLM suggestions first (aligned with plan_day)
            breakfast = None
            if llm_draft:
                meal_draft = getattr(llm_draft, "breakfast", None)
                if meal_draft and meal_draft.suggestions:
                    for suggestion in meal_draft.suggestions:
                        suggestion_dict = suggestion.model_dump() if hasattr(suggestion, 'model_dump') else suggestion
                        suggestion_role = suggestion_dict.get("role", "")
                        if suggestion_role == "breakfast":
                            # Try recipes_pool first
                            mapped_recipe = _map_llm_suggestion_to_recipe(
                                suggestion_dict,
                                recipes_pool,
                                "breakfast"
                            )
                            # If not found in recipes_pool, try all_recipes
                            if not mapped_recipe and all_recipes:
                                mapped_recipe = _map_llm_suggestion_to_recipe(
                                    suggestion_dict,
                                    all_recipes,
                                    "breakfast"
                                )
                            if mapped_recipe and str(mapped_recipe.get("food_id", "")) not in used_ids:
                                if _is_vietnamese_breakfast(mapped_recipe):
                                    macros = _get_meal_macros(mapped_recipe)
                                    kcal = macros.get("kcal", 0.0)
                                    if 100.0 <= kcal <= breakfast_max_kcal:
                                        breakfast = mapped_recipe
                                        logging.debug(
                                            f"plan_week_e2e_tool: Selected breakfast from LLM suggestion: "
                                            f"'{breakfast.get('dish_name', 'Unknown')}'"
                                        )
                                        break

            # CRITICAL: Prefer breakfasts not used in previous days to avoid repetition
            # Use unified search helper to find unused breakfasts first
            if not breakfast and used_breakfast_ids:
                # Filter unused breakfasts and use strategy selection
                unused_breakfasts = [
                    r for r in recipes_pool
                    if str(r.get("food_id", "")) not in used_breakfast_ids
                    and _is_vietnamese_breakfast(r)
                ]
                if unused_breakfasts:
                    breakfast = select_meal_by_strategy(
                        unused_breakfasts, "highest_protein",
                        used_recipe_ids=used_ids,
                        preferred_meal_type="breakfast",
                        dish_category="breakfast",
                        target_macros=breakfast_targets,
                        require_macros=True,
                        min_kcal=100.0,
                        max_kcal=breakfast_max_kcal,
                        min_protein=min_acceptable_protein,
                    )
                    if breakfast:
                        logging.debug(
                            f"plan_week_e2e_tool: _select_breakfast - Selected from unused breakfasts in recipes_pool: "
                            f"'{breakfast.get('dish_name', 'Unknown')}' (food_id={breakfast.get('food_id', 'Unknown')})"
                        )
                
                # If no unused breakfast in recipes_pool, try all_recipes
                if not breakfast and all_recipes:
                    unused_breakfasts_all = [
                        r for r in all_recipes
                        if str(r.get("food_id", "")) not in used_breakfast_ids
                        and str(r.get("food_id", "")) not in used_ids
                        and _is_vietnamese_breakfast(r)
                    ]
                    if unused_breakfasts_all:
                        breakfast = select_meal_by_strategy(
                            unused_breakfasts_all, "highest_protein",
                            used_recipe_ids=used_ids,
                            preferred_meal_type="breakfast",
                            dish_category="breakfast",
                            target_macros=breakfast_targets,
                            require_macros=True,
                            min_kcal=100.0,
                            max_kcal=breakfast_max_kcal,
                            min_protein=min_acceptable_protein,
                        )
                        if breakfast:
                            logging.debug(
                                f"plan_week_e2e_tool: _select_breakfast - Selected from unused breakfasts in all_recipes: "
                                f"'{breakfast.get('dish_name', 'Unknown')}' (food_id={breakfast.get('food_id', 'Unknown')})"
                            )
            
            # Fallback: try all recipes if no unused breakfast found
            if not breakfast:
                logging.debug(
                    f"plan_week_e2e_tool: _select_breakfast - No unused breakfast found, trying all recipes "
                    f"(used_breakfast_ids={list(used_breakfast_ids) if used_breakfast_ids else None})"
                )
                breakfast = select_meal_by_strategy(
                    recipes_pool, "highest_protein",
                    used_recipe_ids=used_ids,
                    preferred_meal_type="breakfast",
                    dish_category="breakfast",
                    target_macros=breakfast_targets,
                    require_macros=True,
                    min_kcal=100.0,
                    max_kcal=breakfast_max_kcal,
                    min_protein=min_acceptable_protein,
                )
                if not breakfast and all_recipes:
                    breakfast = select_meal_by_strategy(
                        all_recipes, "highest_protein",
                        used_recipe_ids=used_ids,
                        preferred_meal_type="breakfast",
                        dish_category="breakfast",
                        target_macros=breakfast_targets,
                        require_macros=True,
                        min_kcal=100.0,
                        max_kcal=breakfast_max_kcal,
                        min_protein=min_acceptable_protein,
                    )
                if breakfast:
                    breakfast_id = str(breakfast.get("food_id", ""))
                    is_reused = used_breakfast_ids and breakfast_id in used_breakfast_ids
                    logging.debug(
                        f"plan_week_e2e_tool: _select_breakfast - Selected from all recipes: "
                        f"'{breakfast.get('dish_name', 'Unknown')}' (food_id={breakfast_id}) | "
                        f"is_reused={is_reused}"
                    )

            # Fallback: balanced breakfast if protein-first failed
            if not breakfast:
                logging.debug(
                    f"plan_week_e2e_tool: _select_breakfast - Protein-first failed, trying balanced strategy"
                )
                breakfast = select_meal_by_strategy(
                    recipes_pool, "balanced",
                    used_recipe_ids=used_ids,
                    preferred_meal_type="breakfast",
                    dish_category="breakfast",
                    target_macros=breakfast_targets,
                    require_macros=True,
                    min_kcal=100.0,
                    max_kcal=breakfast_max_kcal,
                )
                if not breakfast and all_recipes:
                    breakfast = select_meal_by_strategy(
                        all_recipes, "balanced",
                        used_recipe_ids=used_ids,
                        preferred_meal_type="breakfast",
                        dish_category="breakfast",
                        target_macros=breakfast_targets,
                        require_macros=True,
                        min_kcal=100.0,
                        max_kcal=breakfast_max_kcal,
                    )
                if breakfast:
                    breakfast_id = str(breakfast.get("food_id", ""))
                    is_reused = used_breakfast_ids and breakfast_id in used_breakfast_ids
                    logging.debug(
                        f"plan_week_e2e_tool: _select_breakfast - Selected from balanced strategy: "
                        f"'{breakfast.get('dish_name', 'Unknown')}' (food_id={breakfast_id}) | "
                        f"is_reused={is_reused}"
                    )

            # CRITICAL: Final validation - ensure breakfast is actually a Vietnamese breakfast dish
            if breakfast and not _is_vietnamese_breakfast(breakfast):
                logging.warning(
                    f"plan_week_e2e_tool: Selected breakfast '{breakfast.get('dish_name', 'Unknown')}' "
                    f"is not a Vietnamese breakfast dish. Searching for valid breakfast..."
                )
                breakfast = None

            # If still no breakfast, try to find best valid Vietnamese breakfast using helper
            if not breakfast:
                logging.debug(
                    f"plan_week_e2e_tool: _select_breakfast - All strategies failed, trying manual search "
                    f"(used_breakfast_ids={list(used_breakfast_ids) if used_breakfast_ids else None})"
                )
                best_breakfast = _search_breakfast_pools(
                    recipes_pool, all_recipes, used_ids, used_breakfast_ids,
                    min_kcal=100.0, max_kcal=breakfast_max_kcal,
                    min_protein=0.0, prefer_unused=True
                )
                
                # If no unused breakfast found, allow reuse
                if not best_breakfast:
                    logging.warning(
                        f"plan_week_e2e_tool: _select_breakfast - No unused breakfast found, allowing reuse "
                        f"(used_breakfast_ids={list(used_breakfast_ids) if used_breakfast_ids else None})"
                    )
                    best_breakfast = _search_breakfast_pools(
                        recipes_pool, all_recipes, used_ids, used_breakfast_ids,
                        min_kcal=100.0, max_kcal=breakfast_max_kcal,
                        min_protein=0.0, prefer_unused=False
                    )
                    if best_breakfast:
                        breakfast_id = str(best_breakfast.get("food_id", ""))
                        is_reused = used_breakfast_ids and breakfast_id in used_breakfast_ids
                        logging.warning(
                            f"plan_week_e2e_tool: _select_breakfast - Reusing breakfast "
                            f"'{best_breakfast.get('dish_name', 'Unknown')}' (food_id={breakfast_id}) "
                            f"due to limited variety | is_reused={is_reused}"
                        )
                
                if best_breakfast:
                    breakfast = best_breakfast
                    logging.debug(
                        f"plan_week_e2e_tool: _select_breakfast - Found valid breakfast fallback: "
                        f"'{breakfast.get('dish_name', 'Unknown')}' (food_id={breakfast.get('food_id', 'Unknown')})"
                    )

            # CRITICAL: Validate breakfast kcal, protein, and fat after selection (aligned with plan_day)
            if breakfast:
                breakfast_macros = _get_meal_macros(breakfast)
                breakfast_kcal = breakfast_macros.get("kcal", 0.0)
                breakfast_protein = breakfast_macros.get("protein_g", 0.0)
                breakfast_fat = breakfast_macros.get("fat_g", 0.0)

                # If breakfast protein is too low, try to find a better option using helper
                if breakfast_protein < min_acceptable_protein:
                    logging.warning(
                        f"plan_week_e2e_tool: Breakfast protein ({breakfast_protein:.1f}g) is below minimum "
                        f"({min_acceptable_protein:.1f}g), trying to find better option..."
                    )
                    # Create filtered pools excluding current breakfast
                    filtered_pool = [r for r in recipes_pool if r != breakfast]
                    filtered_all = [r for r in all_recipes if r != breakfast] if all_recipes else None
                    
                    best_breakfast = _search_breakfast_pools(
                        filtered_pool, filtered_all, used_ids, used_breakfast_ids,
                        min_kcal=100.0, max_kcal=breakfast_max_kcal,
                        min_protein=breakfast_protein, prefer_unused=True
                    )
                    
                    if not best_breakfast:
                        best_breakfast = _search_breakfast_pools(
                            filtered_pool, filtered_all, used_ids, used_breakfast_ids,
                            min_kcal=100.0, max_kcal=breakfast_max_kcal,
                            min_protein=breakfast_protein, prefer_unused=False
                        )
                        if best_breakfast:
                            logging.warning(
                                f"plan_week_e2e_tool: Reusing breakfast '{best_breakfast.get('dish_name', 'Unknown')}' "
                                f"due to limited variety (protein replacement)"
                            )
                    
                    if best_breakfast:
                        best_macros = _get_meal_macros(best_breakfast)
                        best_protein = best_macros.get("protein_g", 0.0)
                        if best_protein >= min_acceptable_protein:
                            breakfast = best_breakfast
                            breakfast_macros = best_macros
                            breakfast_kcal = breakfast_macros.get("kcal", 0.0)
                            breakfast_fat = breakfast_macros.get("fat_g", 0.0)
                            logging.info(
                                f"plan_week_e2e_tool: Replaced breakfast with higher protein option: "
                                f"'{breakfast.get('dish_name', 'Unknown')}' ({best_protein:.1f}g protein)"
                            )

                # If breakfast over cap, try to find a better balanced option using helper
                if breakfast_kcal > breakfast_max_kcal * 1.1 or breakfast_fat > 25.0:
                    logging.warning(
                        f"plan_week_e2e_tool: Breakfast over cap (kcal={breakfast_kcal:.1f}>{breakfast_max_kcal:.1f} "
                        f"or fat={breakfast_fat:.1f}>25). Trying to find better option..."
                    )
                    # Create filtered pools excluding current breakfast and filter by kcal/fat
                    filtered_pool = []
                    for r in recipes_pool:
                        if r == breakfast:
                            continue
                        if not _is_vietnamese_breakfast(r):
                            continue
                        macros = _get_meal_macros(r)
                        if (100.0 <= macros.get("kcal", 0.0) <= breakfast_max_kcal and
                            macros.get("fat_g", 0.0) <= 25.0 and
                            macros.get("protein_g", 0.0) >= min_acceptable_protein):
                            filtered_pool.append(r)
                    
                    filtered_all = None
                    if all_recipes:
                        filtered_all = []
                        for r in all_recipes:
                            if r == breakfast:
                                continue
                            if not _is_vietnamese_breakfast(r):
                                continue
                            macros = _get_meal_macros(r)
                            if (100.0 <= macros.get("kcal", 0.0) <= breakfast_max_kcal and
                                macros.get("fat_g", 0.0) <= 25.0 and
                                macros.get("protein_g", 0.0) >= min_acceptable_protein):
                                filtered_all.append(r)
                    
                    # Find best breakfast by score (prioritize protein, consider kcal/fat)
                    best_breakfast = None
                    best_score = 0.0
                    for pool in [filtered_pool, filtered_all]:
                        if not pool:
                            continue
                        for recipe in pool:
                            if str(recipe.get("food_id", "")) in used_ids:
                                continue
                            if used_breakfast_ids and str(recipe.get("food_id", "")) in used_breakfast_ids:
                                continue
                            macros = _get_meal_macros(recipe)
                            protein = macros.get("protein_g", 0.0)
                            kcal = macros.get("kcal", 0.0)
                            fat = macros.get("fat_g", 0.0)
                            score = protein * 2.0 - (kcal / 10.0) - (fat * 0.5)
                            if score > best_score:
                                best_breakfast = recipe
                                best_score = score
                    
                    if not best_breakfast:
                        # Allow reuse
                        for pool in [filtered_pool, filtered_all]:
                            if not pool:
                                continue
                            for recipe in pool:
                                if str(recipe.get("food_id", "")) in used_ids:
                                    continue
                                macros = _get_meal_macros(recipe)
                                protein = macros.get("protein_g", 0.0)
                                kcal = macros.get("kcal", 0.0)
                                fat = macros.get("fat_g", 0.0)
                                score = protein * 2.0 - (kcal / 10.0) - (fat * 0.5)
                                if score > best_score:
                                    best_breakfast = recipe
                                    best_score = score
                        if best_breakfast:
                            logging.warning(
                                f"plan_week_e2e_tool: Reusing breakfast '{best_breakfast.get('dish_name', 'Unknown')}' "
                                f"due to limited variety (kcal/fat cap replacement)"
                            )
                    
                    if best_breakfast:
                        breakfast = best_breakfast
                        breakfast_macros = _get_meal_macros(breakfast)
                        breakfast_kcal = breakfast_macros.get("kcal", 0.0)
                        breakfast_fat = breakfast_macros.get("fat_g", 0.0)
                        logging.info(
                            f"plan_week_e2e_tool: Replaced breakfast with better balanced option: "
                            f"'{breakfast.get('dish_name', 'Unknown')}'"
                        )

                # Hard fallback to light breakfast if still over cap using helper
                if breakfast_kcal > breakfast_max_kcal * 1.1 or breakfast_fat > 25.0:
                    # Find any breakfast that meets caps
                    light_breakfast = _search_breakfast_pools(
                        recipes_pool, all_recipes, used_ids, used_breakfast_ids,
                        min_kcal=100.0, max_kcal=breakfast_max_kcal,
                        min_protein=0.0, prefer_unused=True
                    )
                    # Validate it meets fat cap
                    if light_breakfast:
                        light_macros = _get_meal_macros(light_breakfast)
                        if light_macros.get("fat_g", 0.0) <= 25.0:
                            breakfast = light_breakfast
                            logging.warning(
                                f"plan_week_e2e_tool: Fallback: forced lower-calorie breakfast to meet caps: "
                                f"'{breakfast.get('dish_name', 'Unknown')}'"
                            )
                    # If still not found, allow reuse
                    if (breakfast_kcal > breakfast_max_kcal * 1.1 or breakfast_fat > 25.0):
                        light_breakfast = _search_breakfast_pools(
                            recipes_pool, all_recipes, used_ids, used_breakfast_ids,
                            min_kcal=100.0, max_kcal=breakfast_max_kcal,
                            min_protein=0.0, prefer_unused=False
                        )
                        if light_breakfast:
                            light_macros = _get_meal_macros(light_breakfast)
                            if light_macros.get("fat_g", 0.0) <= 25.0:
                                breakfast = light_breakfast
                                logging.warning(
                                    f"plan_week_e2e_tool: Fallback: forced lower-calorie breakfast to meet caps (reuse): "
                                    f"'{breakfast.get('dish_name', 'Unknown')}'"
                                )

            return breakfast

        def _trim_excess_mains(accompaniments: List[Dict[str, Any]]) -> None:
            """
            Keep only the first main dish in accompaniments to avoid overcrowded meals.
            """
            main_seen = False
            trimmed = []
            for acc in accompaniments:
                if acc.get("type") == "main":
                    if main_seen:
                        # drop extra mains
                        continue
                    main_seen = True
                trimmed.append(acc)
            if len(trimmed) != len(accompaniments):
                logging.debug(
                    "plan_week_e2e_tool: trimmed %d extra main(s) from accompaniments",
                    len(accompaniments) - len(trimmed),
                )
            accompaniments[:] = trimmed

        def _is_rice_recipe(recipe: Dict[str, Any] | None) -> bool:
            """
            Lightweight rice detector for weekly planning.
            Treats both real rice dishes and default white rice as 'rice'.
            """
            if not recipe:
                return False
            food_id = str(recipe.get("food_id", "") or "")
            dish_name = str(recipe.get("dish_name", "") or "").lower()
            if food_id == "default_white_rice":
                return True
            if "cơm trắng" in dish_name or "com trang" in dish_name or "white rice" in dish_name:
                return True
            # Fallback: use existing classifier if available on recipe
            return bool(str(recipe.get("dish_type", "")).lower() == "rice")

        def _normalize_servings_day(day_plan: Dict[str, Any]) -> None:
            """
            Normalize servings for a single day's meals (aligned with plan_day_e2e):
              - Noodle/bún/phở (noodle soups): always 1 serving.
              - Rice dishes (including default white rice): integer 1..4 servings.
              - Main / vegetable dishes: integer 1 or 2 servings.
              - Others (soup/fruit/side): fixed 1 serving.

            This keeps weekly plan servings discrete and realistic, while still
            allowing rice to scale for carb deficits.
            """
            def _clamp(servings: float, is_rice: bool) -> float:
                if is_rice:
                    return float(min(4, max(1, int(round(servings or 1.0)))))
                return float(min(2, max(1, int(round(servings or 1.0)))))

            for meal_key, meal_data in day_plan.items():
                recipe = meal_data.get("recipe")
                is_rice = _is_rice_recipe(recipe)
                # Main dish for the meal (carb base)
                if recipe:
                    if _is_noodle_soup(recipe):
                        meal_data["servings"] = 1.0
                    elif is_rice:
                        meal_data["servings"] = _clamp(meal_data.get("servings", 1.0), True)
                    elif _is_main_dish(recipe) or _is_vegetable_dish(recipe):
                        meal_data["servings"] = _clamp(min(2.0, meal_data.get("servings", 1.0)), False)
                    else:
                        meal_data["servings"] = 1.0

                # Accompaniments
                for acc in meal_data.get("accompaniments", []):
                    acc_recipe = acc.get("recipe")
                    if not acc_recipe:
                        continue
                    acc_is_rice = _is_rice_recipe(acc_recipe)
                    if _is_noodle_soup(acc_recipe):
                        acc["servings"] = 1.0
                    elif acc_is_rice:
                        acc["servings"] = _clamp(acc.get("servings", 1.0), True)
                    elif _is_main_dish(acc_recipe) or _is_vegetable_dish(acc_recipe):
                        acc["servings"] = _clamp(min(2.0, acc.get("servings", 1.0)), False)
                    else:
                        acc["servings"] = 1.0

        def _calculate_day_macros(day_plan: Dict[str, Any]) -> Dict[str, float]:
            totals = {"kcal": 0.0, "protein_g": 0.0, "fat_g": 0.0, "carb_g": 0.0}
            for meal_data in day_plan.values():
                recipe = meal_data.get("recipe")
                if recipe:
                    macros = _get_meal_macros(recipe)
                    for k in totals:
                        totals[k] += macros.get(k, 0.0) * meal_data.get("servings", 1.0)
                for acc in meal_data.get("accompaniments", []):
                    acc_recipe = acc.get("recipe")
                    if acc_recipe:
                        acc_macros = _get_meal_macros(acc_recipe)
                        for k in totals:
                            totals[k] += acc_macros.get(k, 0.0) * acc.get("servings", 1.0)
            return totals

        def _maybe_add_supplementary(
            meal_slot: str,
            day_plan: Dict[str, Any],
            is_combined: bool,
            is_noodle: bool,
        ) -> None:
            """
            Lightweight supplementary step: add one more dish if daily deficit is large.
            Priority: protein > kcal. Adds to dinner first, then lunch.
            """
            if not targets:
                return
            daily_kcal = targets.get("tdee_kcal", 0.0)
            daily_protein = targets.get("protein_g", 0.0)
            daily_fat = targets.get("fat_g", 0.0) or 0.0
            daily_carb = targets.get("carb_g", 0.0) or 0.0
            if not daily_kcal or not daily_protein:
                return

            current = _calculate_day_macros(day_plan)
            kcal_deficit = daily_kcal - current["kcal"]
            protein_deficit = daily_protein - current["protein_g"]
            fat_excess_pct = (current["fat_g"] / daily_fat * 100) if daily_fat else 0.0
            carb_excess_pct = (current["carb_g"] / daily_carb * 100) if daily_carb else 0.0

            # Need a meaningful deficit to act
            # CRITICAL: Lower thresholds to catch deficits earlier and ensure daily targets are met
            # Changed from 350.0/20.0 to 200.0/10.0 to be more proactive
            if kcal_deficit < 200.0 and protein_deficit < 10.0:
                return

            # Avoid adding if fat/carb already too high
            # CRITICAL: Be more lenient with fat excess (was 135%, now 150%) to allow adding dishes when needed
            # This ensures we can still add dishes even if fat is slightly high, as long as we need kcal/protein
            if fat_excess_pct > 150.0 or carb_excess_pct > 150.0:
                return

            # Choose pool and placement
            target_meal = day_plan.get(meal_slot, {})
            if not target_meal:
                return

            accompaniments = target_meal.get("accompaniments", [])
            # Avoid overcrowding mains for combined/noodle dishes
            allowed_main = not is_combined and not is_noodle

            # Pick a supplementary dish
            supp = select_meal_by_strategy(
                recipes,
                "highest_protein",
                exclude=[acc.get("recipe") for acc in accompaniments if acc.get("recipe")] + [target_meal.get("recipe")],
                used_recipe_ids=used_recipe_ids,
                preferred_meal_type=meal_slot,
                target_macros=targets,
                require_macros=True,
                min_kcal=100.0,
                max_kcal=450.0,
                min_protein=15.0,
            )
            if not supp:
                return

            # Decide type
            dish_type = "main"
            if not allowed_main or _is_vegetable_dish(supp):
                dish_type = "vegetable"
            elif _is_fruit(supp):
                dish_type = "fruit"
            elif _is_soup(supp):
                dish_type = "soup"
            elif not _is_main_dish(supp):
                # fallback to vegetable if not a real main
                dish_type = "vegetable"

            accompaniments.append(
                {"recipe": supp, "servings": 1.0, "type": dish_type}
            )
            supp_id = str(supp.get("food_id", ""))
            if not _is_default_white_rice_id(supp_id):
                used_recipe_ids.add(supp_id)
            # Re-trim mains if we added another main
            _trim_excess_mains(accompaniments)

        def _recompute_weekly_totals(plan: Dict[str, Any]) -> Dict[str, float]:
            totals = {"kcal": 0.0, "protein_g": 0.0, "fat_g": 0.0, "carb_g": 0.0}
            for day in plan.values():
                for meal_data in day.get("meals", {}).values():
                    recipe = meal_data.get("recipe")
                    if recipe:
                        macros = _get_meal_macros(recipe)
                        servings = meal_data.get("servings", 1.0)
                        for k in totals:
                            totals[k] += macros.get(k, 0.0) * servings
                    for acc in meal_data.get("accompaniments", []):
                        acc_recipe = acc.get("recipe")
                        if acc_recipe:
                            acc_macros = _get_meal_macros(acc_recipe)
                            acc_servings = acc.get("servings", 1.0)
                            for k in totals:
                                totals[k] += acc_macros.get(k, 0.0) * acc_servings
            return totals

        def _score_totals(totals: Dict[str, float], target_totals: Dict[str, float]) -> float:
            def rel_diff(k: str) -> float:
                tgt = target_totals.get(k, 0.0) or 0.0
                if tgt <= 0:
                    return 0.0
                return abs(totals.get(k, 0.0) - tgt) / tgt

            # Heavier weight on kcal and protein
            return (
                rel_diff("kcal") * 0.5
                + rel_diff("protein_g") * 0.4
                + rel_diff("fat_g") * 0.05
                + rel_diff("carb_g") * 0.05
            )

        def _try_optimize_macros(weekly_plan: Dict[str, Any], total_macros: Dict[str, float]) -> Dict[str, float]:
            """
            Lightweight swap optimizer: try swapping main accompaniments to improve weekly macro fit.
            Prioritizes reducing over-coverage when totals exceed targets.
            Limits swaps to keep runtime low.
            """
            if not targets:
                return total_macros

            weekly_targets = {
                "kcal": targets.get("tdee_kcal", 0.0) * 7.0,
                "protein_g": targets.get("protein_g", 0.0) * 7.0,
                "fat_g": targets.get("fat_g", 0.0) * 7.0,
                "carb_g": targets.get("carb_g", 0.0) * 7.0,
            }
            best_score = _score_totals(total_macros, weekly_targets)
            swaps_made = 0
            max_swaps = 10  # Increased from 6 to allow more optimization
            
            # Check if we're over-coverage (need to reduce) or under-coverage (need to increase)
            is_over_coverage = (
                total_macros.get("kcal", 0.0) > weekly_targets.get("kcal", 0.0) * 1.1 or
                total_macros.get("protein_g", 0.0) > weekly_targets.get("protein_g", 0.0) * 1.1
            )
            is_under_coverage = (
                total_macros.get("kcal", 0.0) < weekly_targets.get("kcal", 0.0) * 0.90 or
                total_macros.get("protein_g", 0.0) < weekly_targets.get("protein_g", 0.0) * 0.90
            )
            
            logging.debug(
                f"plan_week_e2e_tool: Macro optimizer start - Current totals: "
                f"kcal={total_macros.get('kcal', 0):.1f} protein={total_macros.get('protein_g', 0):.1f} | "
                f"Targets: kcal={weekly_targets.get('kcal', 0):.1f} protein={weekly_targets.get('protein_g', 0):.1f} | "
                f"Over-coverage: {is_over_coverage} | Under-coverage: {is_under_coverage}"
            )

            for iteration in range(max_swaps):
                improved = False
                # Iterate days and meals to find a better main replacement
                for day_data in weekly_plan.values():
                    meals = day_data.get("meals", {})
                    for meal_key in ("lunch", "dinner"):
                        meal_data = meals.get(meal_key, {})
                        accompaniments = meal_data.get("accompaniments", [])
                        # Find existing main accompaniment
                        main_idx = None
                        for idx, acc in enumerate(accompaniments):
                            if acc.get("type") == "main" and acc.get("recipe"):
                                main_idx = idx
                                break
                        if main_idx is None:
                            continue
                        current_main = accompaniments[main_idx]["recipe"]
                        current_id = str(current_main.get("food_id", ""))
                        current_macros = _get_meal_macros(current_main)

                        # Candidate pool: main dishes with macros and not already used
                        candidates = [
                            r for r in recipes
                            if r.get("macros_per_serving")
                            and isinstance(r.get("macros_per_serving"), dict)
                            and r.get("macros_per_serving", {}).get("kcal")
                            and _is_main_dish(r)
                            and str(r.get("food_id", "")) not in used_recipe_ids
                        ]
                        
                        # If over-coverage, prioritize lower-calorie/lower-protein options
                        if is_over_coverage:
                            # Sort by kcal ascending (lower is better for reducing over-coverage)
                            candidates = sorted(
                                candidates,
                                key=lambda r: (
                                    _get_meal_macros(r).get("kcal", 0.0),
                                    -_get_meal_macros(r).get("protein_g", 0.0)  # Still want some protein
                                ),
                            )[:12]  # Try more candidates when reducing
                        elif is_under_coverage:
                            # CRITICAL: If under-coverage, prioritize higher-kcal/higher-protein options
                            # Sort by kcal descending (higher is better for increasing under-coverage)
                            candidates = sorted(
                                candidates,
                                key=lambda r: (
                                    _get_meal_macros(r).get("kcal", 0.0),
                                    _get_meal_macros(r).get("protein_g", 0.0)
                                ),
                                reverse=True,
                            )[:12]  # Try more candidates when increasing
                        else:
                            # Normal optimization: try protein-dense options
                            candidates = sorted(
                                candidates,
                                key=lambda r: _get_meal_macros(r).get("protein_g", 0.0),
                                reverse=True,
                            )[:8]

                        for cand in candidates:
                            cand_id = str(cand.get("food_id", ""))
                            if not cand_id:
                                continue
                            cand_macros = _get_meal_macros(cand)
                            
                            # If over-coverage, prefer swaps that reduce kcal/protein
                            if is_over_coverage:
                                kcal_reduction = current_macros.get("kcal", 0.0) - cand_macros.get("kcal", 0.0)
                                protein_reduction = current_macros.get("protein_g", 0.0) - cand_macros.get("protein_g", 0.0)
                                # Only consider swaps that reduce kcal or protein
                                if kcal_reduction <= 0 and protein_reduction <= 0:
                                    continue
                            # CRITICAL: If under-coverage, prefer swaps that increase kcal/protein
                            elif is_under_coverage:
                                kcal_increase = cand_macros.get("kcal", 0.0) - current_macros.get("kcal", 0.0)
                                protein_increase = cand_macros.get("protein_g", 0.0) - current_macros.get("protein_g", 0.0)
                                # Only consider swaps that increase kcal or protein
                                if kcal_increase <= 0 and protein_increase <= 0:
                                    continue
                            
                            # Tentatively swap
                            accompaniments[main_idx] = {"recipe": cand, "servings": 1.0, "type": "main"}
                            new_totals = _recompute_weekly_totals(weekly_plan)
                            new_score = _score_totals(new_totals, weekly_targets)
                            if new_score + 0.005 < best_score:  # require a real improvement
                                # Accept swap
                                used_recipe_ids.discard(current_id)
                                if not _is_default_white_rice_id(cand_id):
                                    used_recipe_ids.add(cand_id)
                                best_score = new_score
                                total_macros.update(new_totals)
                                swaps_made += 1
                                improved = True
                                logging.debug(
                                    f"plan_week_e2e_tool: Macro optimizer swap #{swaps_made} - "
                                    f"Replaced '{current_main.get('dish_name', 'Unknown')}' "
                                    f"(kcal={current_macros.get('kcal', 0):.1f}) with "
                                    f"'{cand.get('dish_name', 'Unknown')}' "
                                    f"(kcal={cand_macros.get('kcal', 0):.1f}) | "
                                    f"New score: {new_score:.3f}"
                                )
                                break
                            # Revert
                            accompaniments[main_idx] = {"recipe": current_main, "servings": 1.0, "type": "main"}
                        if improved:
                            break
                    if improved:
                        break
                if not improved:
                    break

            if swaps_made > 0:
                logging.info(
                    f"plan_week_e2e_tool: Macro optimizer swapped {swaps_made} main(s) "
                    f"(score={best_score:.3f}, final totals: kcal={total_macros.get('kcal', 0):.1f} "
                    f"protein={total_macros.get('protein_g', 0):.1f})"
                )
            return total_macros
        
        for day_index in range(7):
            day_date = start + timedelta(days=day_index)
            day_key = day_date.date().isoformat()
            
            # Track remaining targets for this day (reset each day)
            remaining_targets = {
                "kcal": targets.get("tdee_kcal", 2000.0) if targets else 2000.0,
                "protein_g": targets.get("protein_g", 150.0) if targets else 150.0,
                "fat_g": targets.get("fat_g", 65.0) if targets else 65.0,
                "carb_g": targets.get("carb_g", 200.0) if targets else 200.0,
            } if targets else None
            
            # Get available recipes (prefer unused, but allow reuse for variety)
            # User insight: OK to repeat ingredients (beef, chicken, pork, fish) with different recipes
            # CRITICAL: Increase threshold to 30 to maintain variety longer before allowing reuse
            # This ensures we explore more unique recipes before repeating
            # CRITICAL: Also avoid recipes used in recent days (last 2 days) to increase variety
            recent_days_used = set()
            for recent_day_idx in range(max(0, day_index - 2), day_index):
                if recent_day_idx in recently_used_per_day:
                    recent_days_used.update(recently_used_per_day[recent_day_idx])
            
            # First, prefer recipes not used at all
            available_recipes = [r for r in recipes if str(r.get("food_id", "")) not in used_recipe_ids]
            
            # If we have enough unused recipes, also avoid recently used ones (last 2 days) for better variety
            if len(available_recipes) >= 20:
                available_recipes = [r for r in available_recipes if str(r.get("food_id", "")) not in recent_days_used]
                if len(available_recipes) < 15:
                    # If avoiding recent days reduces too much, allow them back
                    available_recipes = [r for r in recipes if str(r.get("food_id", "")) not in used_recipe_ids]
                    logging.debug(
                        f"plan_week_e2e_tool: Day {day_index + 1} - Avoiding recent days reduced pool too much, "
                        f"allowing recent recipes back (available={len(available_recipes)})"
                    )
                else:
                    logging.debug(
                        f"plan_week_e2e_tool: Day {day_index + 1} - Avoiding recipes from last 2 days for variety "
                        f"(available={len(available_recipes)}, recent_days_used={len(recent_days_used)})"
                    )
            
            if not available_recipes or len(available_recipes) < 30:
                # Allow recipe reuse if we're running low on unique recipes
                # This enables variety through different cooking methods of same ingredients
                # But only if we've already used many recipes (threshold increased from 10 to 30)
                if len(available_recipes) < 15:
                    # Only allow reuse if we have very few unique recipes left
                    available_recipes = recipes
                    logging.debug(
                        f"plan_week_e2e_tool: Day {day_index + 1} - Allowing recipe reuse for variety "
                        f"(available={len(available_recipes)} recipes, used={len(used_recipe_ids)})"
                    )
                else:
                    logging.debug(
                        f"plan_week_e2e_tool: Day {day_index + 1} - Still have {len(available_recipes)} unique recipes, "
                        f"not allowing reuse yet (used={len(used_recipe_ids)})"
                    )
            
            # CRITICAL: Filter out unreasonable recipes (kcal too high or protein too low)
            available_recipes = _filter_reasonable_recipes(available_recipes, day_index)
            
            logging.debug(
                f"plan_week_e2e_tool: Day {day_index + 1} ({day_key}) - Starting meal selection | "
                f"Available recipes: {len(available_recipes)} | "
                f"Remaining targets: kcal={remaining_targets['kcal']:.1f} protein={remaining_targets['protein_g']:.1f} "
                f"fat={remaining_targets['fat_g']:.1f} carb={remaining_targets['carb_g']:.1f}" if remaining_targets else "No targets"
            )
            
            # Breakfast: Vietnamese breakfast dishes with stronger nutrition guarantees (aligned with plan_day)
            # CRITICAL: Pass used_breakfast_ids to avoid repetition across days
            logging.info(
                f"plan_week_e2e_tool: Day {day_index + 1} - Starting breakfast selection | "
                f"used_breakfast_ids={list(used_breakfast_ids) if used_breakfast_ids else 'None'} | "
                f"available_recipes={len(available_recipes)}"
            )
            breakfast = _select_breakfast(
                available_recipes,
                used_ids=used_recipe_ids,
                remaining=remaining_targets,
                used_breakfast_ids=used_breakfast_ids,
                llm_draft=llm_draft,
                all_recipes=recipes,  # Pass full recipes pool for fallback
            )
            # DEBUG: Log result from _select_breakfast
            if breakfast:
                breakfast_id = str(breakfast.get("food_id", ""))
                is_reused = used_breakfast_ids and breakfast_id in used_breakfast_ids
                logging.info(
                    f"plan_week_e2e_tool: Day {day_index + 1} - _select_breakfast returned: "
                    f"'{breakfast.get('dish_name', 'Unknown')}' (food_id={breakfast_id}) | "
                    f"is_reused={is_reused}"
                )
            else:
                logging.warning(
                    f"plan_week_e2e_tool: Day {day_index + 1} - _select_breakfast returned None, "
                    f"running fallback logic"
                )
            # CRITICAL: Only run fallback if _select_breakfast returned None
            # This prevents duplicate selection and ensures we only track breakfast once
            if not breakfast:
                # Try all available recipes to find Vietnamese breakfast (prefer unused)
                for recipe in available_recipes:
                    if _is_vietnamese_breakfast(recipe):
                        # Prefer breakfasts not used in previous days
                        if used_breakfast_ids and str(recipe.get("food_id", "")) not in used_breakfast_ids:
                            breakfast = recipe
                            logging.debug(
                                f"plan_week_e2e_tool: Day {day_index + 1} - Breakfast fallback found (unused): "
                                f"'{breakfast.get('dish_name', 'Unknown')}'"
                            )
                            break
                # If still no breakfast, try any Vietnamese breakfast (allow reuse only if no unused breakfasts available)
                # CRITICAL: Check used_breakfast_ids to avoid immediate repetition
                if not breakfast:
                    # First, try to find any Vietnamese breakfast that hasn't been used recently
                    for recipe in recipes:
                        if _is_vietnamese_breakfast(recipe):
                            # Prefer breakfasts not used in previous days
                            if used_breakfast_ids and str(recipe.get("food_id", "")) not in used_breakfast_ids:
                                breakfast = recipe
                                logging.debug(
                                    f"plan_week_e2e_tool: Day {day_index + 1} - Breakfast fallback found (unused from full recipes): "
                                    f"'{breakfast.get('dish_name', 'Unknown')}'"
                                )
                                break
                    # Only allow reuse if absolutely no unused breakfasts found
                    # CRITICAL: Use improved round-robin to avoid repeating the same breakfast
                    if not breakfast:
                        # Collect all Vietnamese breakfasts
                        all_vietnamese_breakfasts = [r for r in recipes if _is_vietnamese_breakfast(r)]
                        if all_vietnamese_breakfasts:
                            # Sort by food_id for consistent ordering
                            all_vietnamese_breakfasts.sort(key=lambda r: str(r.get("food_id", "")))
                            
                            # IMPROVED: Find the least recently used breakfast using better round-robin
                            if used_breakfast_ids and len(used_breakfast_ids) > 0:
                                # Count how many times each breakfast has been used (more accurate)
                                breakfast_usage = {}
                                for recipe in all_vietnamese_breakfasts:
                                    breakfast_id = str(recipe.get("food_id", ""))
                                    # Count actual occurrences in used_breakfast_ids
                                    breakfast_usage[breakfast_id] = list(used_breakfast_ids).count(breakfast_id)
                                
                                # IMPROVED: Group breakfasts by usage count, then use round-robin within each group
                                # This ensures we cycle through all breakfasts evenly
                                usage_groups = {}
                                for recipe in all_vietnamese_breakfasts:
                                    breakfast_id = str(recipe.get("food_id", ""))
                                    usage_count = breakfast_usage.get(breakfast_id, 0)
                                    if usage_count not in usage_groups:
                                        usage_groups[usage_count] = []
                                    usage_groups[usage_count].append(recipe)
                                
                                # Sort usage groups by usage count (least used first)
                                sorted_usage_counts = sorted(usage_groups.keys())
                                
                                # Find the least used group
                                least_used_count = sorted_usage_counts[0]
                                least_used_breakfasts = usage_groups[least_used_count]
                                
                                # Sort by food_id for consistent ordering
                                least_used_breakfasts.sort(key=lambda r: str(r.get("food_id", "")))
                                
                                # Use round-robin within the least used group
                                breakfast_index = day_index % len(least_used_breakfasts)
                                breakfast = least_used_breakfasts[breakfast_index]
                            else:
                                # No breakfasts used yet, pick first one
                                breakfast = all_vietnamese_breakfasts[0]
                            
                            breakfast_id = str(breakfast.get("food_id", ""))
                            was_already_used = breakfast_id in used_breakfast_ids if used_breakfast_ids else False
                            logging.warning(
                                f"plan_week_e2e_tool: Day {day_index + 1} - Breakfast fallback with reuse (round-robin): "
                                f"'{breakfast.get('dish_name', 'Unknown')}' (food_id={breakfast_id}) | "
                                f"was_already_used={was_already_used} (limited variety - all breakfasts used)"
                            )
                if not breakfast:
                    logging.error(
                        f"plan_week_e2e_tool: Day {day_index + 1} - No Vietnamese breakfast found in available recipes!"
                    )
            
            # CRITICAL: Track breakfast ID to avoid repetition in future days
            if breakfast and breakfast.get("food_id"):
                breakfast_id = str(breakfast.get("food_id"))
                was_already_used = breakfast_id in used_breakfast_ids if used_breakfast_ids else False
                used_breakfast_ids.add(breakfast_id)
                logging.info(
                    f"plan_week_e2e_tool: Day {day_index + 1} - Tracked breakfast ID: {breakfast_id} | "
                    f"was_already_used={was_already_used} | "
                    f"used_breakfast_ids now={list(used_breakfast_ids)}"
                )
            
            # Update remaining targets after breakfast
            if remaining_targets and breakfast:
                breakfast_macros = _get_meal_macros(breakfast)
                logging.debug(
                    f"plan_week_e2e_tool: Day {day_index + 1} - Breakfast selected: '{breakfast.get('dish_name', 'Unknown')}' "
                    f"(food_id={breakfast.get('food_id', 'Unknown')}) | "
                    f"Macros: kcal={breakfast_macros.get('kcal', 0):.1f} protein={breakfast_macros.get('protein_g', 0):.1f} "
                    f"fat={breakfast_macros.get('fat_g', 0):.1f} carb={breakfast_macros.get('carb_g', 0):.1f}"
                )
                remaining_targets["kcal"] = max(0.0, remaining_targets["kcal"] - breakfast_macros.get("kcal", 0.0))
                remaining_targets["protein_g"] = max(0.0, remaining_targets["protein_g"] - breakfast_macros.get("protein_g", 0.0))
                remaining_targets["fat_g"] = max(0.0, remaining_targets["fat_g"] - breakfast_macros.get("fat_g", 0.0))
                remaining_targets["carb_g"] = max(0.0, remaining_targets["carb_g"] - breakfast_macros.get("carb_g", 0.0))
                logging.debug(
                    f"plan_week_e2e_tool: Day {day_index + 1} - After breakfast, remaining: "
                    f"kcal={remaining_targets['kcal']:.1f} protein={remaining_targets['protein_g']:.1f} "
                    f"fat={remaining_targets['fat_g']:.1f} carb={remaining_targets['carb_g']:.1f}"
                )
            
            # Lunch: Rice + Main + Vegetable + Fruit
            excluded = [breakfast] if breakfast else []
            
            # Prepare targets with remaining_targets for lunch
            lunch_targets = targets.copy() if targets else None
            if lunch_targets and remaining_targets:
                lunch_targets["_remaining_targets"] = remaining_targets.copy()
            
            # Calculate dynamic requirements based on remaining protein
            max_main_kcal, min_main_protein = _calculate_meal_requirements(remaining_targets, targets)
            
            logging.debug(
                f"plan_week_e2e_tool: Day {day_index + 1} - Lunch selection params: "
                f"max_main_kcal={max_main_kcal:.1f} min_main_protein={min_main_protein:.1f} "
                f"lunch_max_kcal={lunch_max_kcal:.1f}"
            )
            
            # Use validated carb selection (aligned with plan_day)
            lunch_rice, is_lunch_combined, is_lunch_noodle = _select_carb_with_validation(
                "lunch",
                available_recipes,
                excluded,
                used_recipe_ids,
                selection_strategy if targets else "balanced",
                lunch_targets,
                lunch_max_kcal,
                llm_draft=llm_draft,
            )
            
            if lunch_rice:
                excluded.append(lunch_rice)
                rice_macros = _get_meal_macros(lunch_rice)
                logging.debug(
                    f"plan_week_e2e_tool: Day {day_index + 1} - Lunch rice selected: '{lunch_rice.get('dish_name', 'Unknown')}' "
                    f"(food_id={lunch_rice.get('food_id', 'Unknown')}) | "
                    f"Macros: kcal={rice_macros.get('kcal', 0):.1f} protein={rice_macros.get('protein_g', 0):.1f} "
                    f"fat={rice_macros.get('fat_g', 0):.1f} carb={rice_macros.get('carb_g', 0):.1f} | "
                    f"is_combined={is_lunch_combined} is_noodle={is_lunch_noodle}"
                )
            
            # is_lunch_combined and is_lunch_noodle already set by _select_carb_with_validation

            # CRITICAL: Use select_accompaniments (aligned with plan_day_e2e.py)
            # This ensures consistent meal structure: main + soup + vegetable + fruit
            lunch_main, lunch_soup, lunch_veg, lunch_fruit = select_accompaniments(
                "lunch", is_lunch_combined, is_lunch_noodle,
                available_recipes, excluded, used_recipe_ids,
                selection_strategy if targets else "balanced", lunch_targets,
                    llm_draft=llm_draft,
                try_select_from_llm_suggestions=None,  # Can add if needed
                carb_dish=lunch_rice,
            )
            
            # Mark used to prevent intra-plan reuse
            for dish in (lunch_main, lunch_soup, lunch_veg, lunch_fruit):
                if dish:
                    excluded.append(dish)
                    _track_name(dish)
            
            # CRITICAL: If eating with rice and deficit remains, force-add accompaniments (main/veg/soup)
            # This aligns with plan_day_e2e.py logic
            def _mark_used_cb(recipe):
                if recipe:
                    excluded.append(recipe)
                    _track_name(recipe)
                    if recipe.get("food_id"):
                        used_recipe_ids.add(str(recipe.get("food_id")))
            
            lunch_main, lunch_veg, lunch_soup, lunch_msgs = _enrich_rice_meal(
                meal_slot="lunch",
                is_noodle=is_lunch_noodle,
                is_combined=is_lunch_combined,
                meal_main=lunch_main,
                meal_veg=lunch_veg,
                meal_soup=lunch_soup,
                remaining_targets=remaining_targets,
                targets=targets,
                recipes=available_recipes,
                excluded=excluded,
                recent_recipe_ids_set=used_recipe_ids,
                used_today_ids=set(),  # Not tracking per-day in weekly plan
                preferred_meal_type="lunch",
                main_max_kcal=700.0,
                soup_max_kcal=180.0,
                mark_used_cb=_mark_used_cb,
            )
            for msg in lunch_msgs:
                yield Response(msg)
            
            # CRITICAL: Initialize supplementary dishes list (aligned with plan_day_e2e.py)
            lunch_supplementary_dishes = []
            
            # CRITICAL: Add supplementary dishes if still deficient in nutrition (iterative approach)
            # This aligns with plan_day_e2e.py logic
            if remaining_targets and targets:
                current_lunch_dishes = [d for d in [lunch_rice, lunch_main, lunch_soup, lunch_veg, lunch_fruit] if d]
                # Use iterative approach to keep adding until nutrition targets are met
                max_iterations = 3
                iteration = 0
                all_supplementary_dishes = []
                
                while iteration < max_iterations:
                    # CRITICAL: Calculate what we ACTUALLY need based on original targets (aligned with plan_day)
                    breakfast_macros = _get_meal_macros(breakfast) if breakfast else {"kcal": 0.0, "protein_g": 0.0, "fat_g": 0.0, "carb_g": 0.0}
                    current_lunch_macros = {}
                    for dish in current_lunch_dishes:
                        dish_macros = _get_meal_macros(dish)
                        for k in dish_macros:
                            current_lunch_macros[k] = current_lunch_macros.get(k, 0.0) + dish_macros.get(k, 0.0)
                    
                    total_consumed_kcal = breakfast_macros.get("kcal", 0.0) + current_lunch_macros.get("kcal", 0.0)
                    total_consumed_protein = breakfast_macros.get("protein_g", 0.0) + current_lunch_macros.get("protein_g", 0.0)
                    
                    daily_protein = targets.get("protein_g", 150.0)
                    daily_kcal = targets.get("tdee_kcal", 2000.0)
                    
                    # Calculate ACTUAL remaining needs from original targets
                    actual_protein_needed = max(0.0, daily_protein - total_consumed_protein)
                    actual_kcal_needed = max(0.0, daily_kcal - total_consumed_kcal)
                    
                    # Also check remaining_targets (may be updated in loop)
                    protein_needed_from_remaining = remaining_targets.get("protein_g", 0.0)
                    kcal_needed_from_remaining = remaining_targets.get("kcal", 0.0)
                    
                    # Use the MAXIMUM of actual_needed and remaining_targets (aligned with plan_day)
                    protein_needed = max(protein_needed_from_remaining, actual_protein_needed)
                    kcal_needed = max(kcal_needed_from_remaining, actual_kcal_needed)
                    
                    # Update remaining_targets to reflect actual needs if it's incorrect
                    if actual_protein_needed > protein_needed_from_remaining or actual_kcal_needed > kcal_needed_from_remaining:
                        remaining_targets["protein_g"] = actual_protein_needed
                        remaining_targets["kcal"] = actual_kcal_needed
                    
                    # Calculate deficit ratios
                    protein_deficit_ratio = protein_needed / daily_protein if daily_protein > 0 else 0.0
                    kcal_deficit_ratio = kcal_needed / daily_kcal if daily_kcal > 0 else 0.0
                    
                    # CRITICAL: Calculate fat/carb excess based on total consumed (aligned with plan_day)
                    daily_fat = targets.get("fat_g", 60.0)
                    daily_carb = targets.get("carb_g", 200.0)
                    total_consumed_fat = breakfast_macros.get("fat_g", 0.0) + current_lunch_macros.get("fat_g", 0.0)
                    total_consumed_carb = breakfast_macros.get("carb_g", 0.0) + current_lunch_macros.get("carb_g", 0.0)
                    fat_excess_ratio = (total_consumed_fat - daily_fat) / daily_fat if daily_fat > 0 and total_consumed_fat > daily_fat else 0.0
                    carb_excess_ratio = (total_consumed_carb - daily_carb) / daily_carb if daily_carb > 0 and total_consumed_carb > daily_carb else 0.0
                    kcal_excess_ratio = (total_consumed_kcal - daily_kcal) / daily_kcal if daily_kcal > 0 and total_consumed_kcal > daily_kcal else 0.0
                    has_severe_fat_excess = fat_excess_ratio > 0.15
                    has_severe_carb_excess = carb_excess_ratio > 0.15
                    has_severe_kcal_excess = kcal_excess_ratio > 0.15
                    
                    # CRITICAL: Stop conditions (aligned with plan_day)
                    if fat_excess_ratio > 0.40:
                        if protein_deficit_ratio > 0.35 or kcal_deficit_ratio > 0.40:
                            pass  # Continue if deficit is critical
                        else:
                            break
                    elif carb_excess_ratio > 0.50:
                        if protein_deficit_ratio > 0.30 or kcal_deficit_ratio > 0.35:
                            pass
                        else:
                            break
                    elif kcal_excess_ratio > 0.50:
                        if protein_deficit_ratio > 0.30 or kcal_deficit_ratio > 0.35:
                            pass
                        else:
                            break
                    elif has_severe_fat_excess or has_severe_carb_excess or has_severe_kcal_excess:
                        if protein_deficit_ratio > 0.20 or kcal_deficit_ratio > 0.25:
                            pass
                        elif protein_deficit_ratio < 0.20 and kcal_deficit_ratio < 0.25:
                            break
                    
                    # Stop if too many main dishes AND daily deficit is low
                    current_main_count = sum(1 for d in current_lunch_dishes if _is_main_dish(d))
                    if current_main_count >= 3:
                        if kcal_deficit_ratio < 0.15 and protein_deficit_ratio < 0.20:
                            break
                    
                    # Stop if close enough to targets AND meal is already substantial
                    current_meal_kcal = current_lunch_macros.get('kcal', 0)
                    meal_size_ratio = current_meal_kcal / lunch_max_kcal if lunch_max_kcal > 0 else 0
                    if kcal_deficit_ratio < 0.10 and protein_deficit_ratio < 0.15 and meal_size_ratio > 0.80:
                        break
                    elif kcal_deficit_ratio > 0.20 or protein_deficit_ratio > 0.25:
                        pass  # Continue if daily deficit is still high
                    
                    # Calculate total consumed so far for accurate excess detection
                    total_consumed_so_far = {
                        "kcal": total_consumed_kcal,
                        "protein_g": total_consumed_protein,
                        "fat_g": breakfast_macros.get("fat_g", 0.0) + current_lunch_macros.get("fat_g", 0.0),
                        "carb_g": breakfast_macros.get("carb_g", 0.0) + current_lunch_macros.get("carb_g", 0.0),
                    }
                    
                    # Add supplementary dishes (skip if standalone noodle)
                    if is_lunch_noodle:
                        supplementary_dishes = []
                    else:
                        # Allow more tolerance when deficit is high (aligned with plan_day)
                        if protein_deficit_ratio > 0.30 or kcal_deficit_ratio > 0.40:
                            effective_meal_max_kcal = lunch_max_kcal * 1.4
                        elif is_lunch_noodle or is_lunch_combined or protein_deficit_ratio > 0.20 or kcal_deficit_ratio > 0.30:
                            effective_meal_max_kcal = lunch_max_kcal * 1.3
                        else:
                            effective_meal_max_kcal = lunch_max_kcal * 1.2
                        
                        # Collect all dish names for similarity check
                        excluded_names = set()
                        for ex_recipe in excluded:
                            if ex_recipe:
                                ex_name = str(ex_recipe.get("dish_name", "")).lower().strip()
                                if ex_name:
                                    excluded_names.add(ex_name)
                        for dish in current_lunch_dishes:
                            if dish:
                                dish_name = str(dish.get("dish_name", "")).lower().strip()
                                if dish_name:
                                    excluded_names.add(dish_name)
                        
                        supplementary_dishes = add_supplementary_dishes(
                            "lunch",
                            current_lunch_dishes,
                            remaining_targets,
                            targets,
                            available_recipes,
                            excluded,
                            used_recipe_ids,
                            effective_meal_max_kcal,
                            0.15,  # macro_tolerance_percent
                            total_consumed_so_far=total_consumed_so_far,
                            used_recipe_names=set(),  # Not tracking names in weekly plan
                        )
                        
                        # Filter out invalid/empty supplementary entries
                        filtered_supplementary = []
                        for d in supplementary_dishes:
                            if isinstance(d, dict):
                                if d.get("recipe") or d.get("dish_name") or d.get("food_id"):
                                    filtered_supplementary.append(d)
                        supplementary_dishes = filtered_supplementary
                    
                    if not supplementary_dishes:
                        break  # No more dishes to add
                    
                    # Update current_lunch_dishes and remaining_targets for next iteration
                    for supp_dish in supplementary_dishes:
                        supp_recipe = supp_dish.get("recipe", supp_dish)
                        all_supplementary_dishes.append(supp_dish)
                        current_lunch_dishes.append(supp_recipe)
                        excluded.append(supp_recipe)
                        used_recipe_ids.add(str(supp_recipe.get("food_id", "")))
                        # Update remaining_targets using the actual recipe macros
                        dish_macros = _get_meal_macros(supp_recipe)
                        for k in remaining_targets:
                            remaining_targets[k] = max(0.0, remaining_targets[k] - dish_macros.get(k, 0.0))
                    
                    iteration += 1
                
                supplementary_dishes = all_supplementary_dishes
                
                # Add supplementary dishes to lunch components (aligned with plan_day)
                assigned_supp_dishes = []
                for supp_dish in supplementary_dishes:
                    supp_recipe = supp_dish.get("recipe", supp_dish)
                    dish_name = supp_recipe.get('dish_name', 'Unknown')
                    assigned = False
                    if _is_main_dish(supp_recipe):
                        if lunch_main:
                            logging.info(f"Added additional main dish to lunch: {dish_name}")
                        else:
                            lunch_main = supp_recipe
                            assigned = True
                            yield Response(f"✅ Added main dish to meet nutrition targets: {dish_name}")
                    elif _is_vegetable_dish(supp_recipe):
                        if not lunch_veg:
                            lunch_veg = supp_recipe
                            assigned = True
                            yield Response(f"✅ Added vegetable to meet nutrition targets: {dish_name}")
                        else:
                            logging.info(f"Added additional vegetable to lunch: {dish_name}")
                    elif _is_soup(supp_recipe):
                        if not lunch_soup:
                            lunch_soup = supp_recipe
                            assigned = True
                            yield Response(f"✅ Added soup to meet nutrition targets: {dish_name}")
                        else:
                            logging.info(f"Added additional soup to lunch: {dish_name}")
                    
                    if assigned:
                        assigned_supp_dishes.append(supp_dish)
                    else:
                        lunch_supplementary_dishes.append(supp_dish)
            
            # CRITICAL: Update remaining_targets AFTER calculating final lunch_total_macros (including supplementary dishes)
            # This aligns with plan_day_e2e.py logic - calculate from original targets
            if remaining_targets and targets:
                lunch_total_macros = _get_meal_macros(lunch_rice) if lunch_rice else {}
                if lunch_main:
                    main_macros = _get_meal_macros(lunch_main)
                    for k in lunch_total_macros:
                        lunch_total_macros[k] = lunch_total_macros.get(k, 0.0) + main_macros.get(k, 0.0)
                if lunch_soup:
                    soup_macros = _get_meal_macros(lunch_soup)
                    for k in lunch_total_macros:
                        lunch_total_macros[k] = lunch_total_macros.get(k, 0.0) + soup_macros.get(k, 0.0)
                if lunch_veg:
                    veg_macros = _get_meal_macros(lunch_veg)
                    for k in lunch_total_macros:
                        lunch_total_macros[k] = lunch_total_macros.get(k, 0.0) + veg_macros.get(k, 0.0)
                if lunch_fruit:
                    fruit_macros = _get_meal_macros(lunch_fruit)
                    for k in lunch_total_macros:
                        lunch_total_macros[k] = lunch_total_macros.get(k, 0.0) + fruit_macros.get(k, 0.0)
                # Add only supplementary dishes that were NOT assigned to existing slots
                if 'assigned_supp_dishes' in locals():
                    unassigned_supp_dishes = [d for d in lunch_supplementary_dishes if d not in assigned_supp_dishes]
                else:
                    unassigned_supp_dishes = lunch_supplementary_dishes
                for supp_dish in unassigned_supp_dishes:
                    supp_recipe = supp_dish.get("recipe", supp_dish)
                    supp_macros = _get_meal_macros(supp_recipe)
                    for k in lunch_total_macros:
                        lunch_total_macros[k] = lunch_total_macros.get(k, 0.0) + supp_macros.get(k, 0.0)
                
                # CRITICAL: Calculate what we actually consumed vs what we need (from original targets)
                breakfast_macros_check = _get_meal_macros(breakfast) if breakfast else {"kcal": 0.0, "protein_g": 0.0, "fat_g": 0.0, "carb_g": 0.0}
                total_consumed_so_far_kcal = breakfast_macros_check.get("kcal", 0.0) + lunch_total_macros.get("kcal", 0.0)
                total_consumed_so_far_protein = breakfast_macros_check.get("protein_g", 0.0) + lunch_total_macros.get("protein_g", 0.0)
                total_consumed_so_far_fat = breakfast_macros_check.get("fat_g", 0.0) + lunch_total_macros.get("fat_g", 0.0)
                total_consumed_so_far_carb = breakfast_macros_check.get("carb_g", 0.0) + lunch_total_macros.get("carb_g", 0.0)
                
                daily_protein_check = targets.get("protein_g", 150.0)
                daily_kcal_check = targets.get("tdee_kcal", 2000.0)
                daily_fat_check = targets.get("fat_g", 60.0)
                daily_carb_check = targets.get("carb_g", 200.0)
                
                # CRITICAL: Always use actual calculation from original targets (more accurate)
                actual_remaining_kcal = max(0.0, daily_kcal_check - total_consumed_so_far_kcal)
                actual_remaining_protein = max(0.0, daily_protein_check - total_consumed_so_far_protein)
                actual_remaining_fat = max(0.0, daily_fat_check - total_consumed_so_far_fat)
                actual_remaining_carb = max(0.0, daily_carb_check - total_consumed_so_far_carb)
                
                # Update remaining_targets using actual calculation (single source of truth)
                remaining_targets["kcal"] = actual_remaining_kcal
                remaining_targets["protein_g"] = actual_remaining_protein
                remaining_targets["fat_g"] = actual_remaining_fat
                remaining_targets["carb_g"] = actual_remaining_carb
                
                logging.debug(
                    f"plan_week_e2e_tool: Day {day_index + 1} - After lunch (with supplementary), remaining: "
                    f"kcal={remaining_targets['kcal']:.1f} protein={remaining_targets['protein_g']:.1f} "
                    f"fat={remaining_targets['fat_g']:.1f} carb={remaining_targets['carb_g']:.1f}"
                )
            
            # Dinner: Rice + Main + Vegetable + Fruit
            excluded = [breakfast, lunch_rice] if breakfast and lunch_rice else [breakfast] if breakfast else []
            if lunch_main:
                excluded.append(lunch_main)
            if lunch_veg:
                excluded.append(lunch_veg)
            if lunch_fruit:
                excluded.append(lunch_fruit)
            
            # Prepare targets with remaining_targets for dinner
            dinner_targets = targets.copy() if targets else None
            if dinner_targets and remaining_targets:
                dinner_targets["_remaining_targets"] = remaining_targets.copy()
            
            # Recalculate dynamic requirements for dinner
            max_main_kcal, min_main_protein = _calculate_meal_requirements(remaining_targets, targets)
            
            logging.debug(
                f"plan_week_e2e_tool: Day {day_index + 1} - Dinner selection params: "
                f"max_main_kcal={max_main_kcal:.1f} min_main_protein={min_main_protein:.1f} "
                f"dinner_max_kcal={dinner_max_kcal:.1f}"
            )
            
            # Use validated carb selection (aligned with plan_day)
            dinner_rice, is_dinner_combined, is_dinner_noodle = _select_carb_with_validation(
                "dinner",
                available_recipes,
                excluded,
                used_recipe_ids,
                selection_strategy if targets else "balanced",
                dinner_targets,
                dinner_max_kcal,
                llm_draft=llm_draft,
            )
            
            if dinner_rice:
                excluded.append(dinner_rice)
                rice_macros = _get_meal_macros(dinner_rice)
                logging.debug(
                    f"plan_week_e2e_tool: Day {day_index + 1} - Dinner rice selected: '{dinner_rice.get('dish_name', 'Unknown')}' "
                    f"(food_id={dinner_rice.get('food_id', 'Unknown')}) | "
                    f"Macros: kcal={rice_macros.get('kcal', 0):.1f} protein={rice_macros.get('protein_g', 0):.1f} "
                    f"fat={rice_macros.get('fat_g', 0):.1f} carb={rice_macros.get('carb_g', 0):.1f} | "
                    f"is_combined={is_dinner_combined} is_noodle={is_dinner_noodle}"
                )
            
            # is_dinner_combined and is_dinner_noodle already set by _select_carb_with_validation

            # CRITICAL: Use select_accompaniments (aligned with plan_day_e2e.py)
            dinner_main, dinner_soup, dinner_veg, dinner_fruit = select_accompaniments(
                "dinner", is_dinner_combined, is_dinner_noodle,
                available_recipes, excluded, used_recipe_ids,
                selection_strategy if targets else "balanced", dinner_targets,
                    llm_draft=llm_draft,
                try_select_from_llm_suggestions=None,
                carb_dish=dinner_rice,
            )
            
            # Mark used to prevent intra-plan reuse
            for dish in (dinner_main, dinner_soup, dinner_veg, dinner_fruit):
                if dish:
                    excluded.append(dish)
                    _track_name(dish)
            
            # CRITICAL: If eating with rice and deficit remains, force-add accompaniments (main/veg/soup)
            dinner_main, dinner_veg, dinner_soup, dinner_msgs = _enrich_rice_meal(
                meal_slot="dinner",
                is_noodle=is_dinner_noodle,
                is_combined=is_dinner_combined,
                meal_main=dinner_main,
                meal_veg=dinner_veg,
                meal_soup=dinner_soup,
                remaining_targets=remaining_targets,
                targets=targets,
                recipes=available_recipes,
                excluded=excluded,
                recent_recipe_ids_set=used_recipe_ids,
                used_today_ids=set(),
                preferred_meal_type="dinner",
                main_max_kcal=700.0,
                soup_max_kcal=180.0,
                mark_used_cb=_mark_used_cb,
            )
            for msg in dinner_msgs:
                yield Response(msg)
            
            # CRITICAL: Initialize supplementary dishes list (aligned with plan_day_e2e.py)
            dinner_supplementary_dishes = []
            
            # CRITICAL: Add supplementary dishes if still deficient in nutrition (iterative approach)
            if remaining_targets and targets:
                current_dinner_dishes = [d for d in [dinner_rice, dinner_main, dinner_soup, dinner_veg, dinner_fruit] if d]
                max_iterations = 3
                iteration = 0
                all_supplementary_dishes = []
                
                while iteration < max_iterations:
                    # Calculate what we ACTUALLY need based on original targets
                    breakfast_macros = _get_meal_macros(breakfast) if breakfast else {"kcal": 0.0, "protein_g": 0.0, "fat_g": 0.0, "carb_g": 0.0}
                    lunch_total_macros = _get_meal_macros(lunch_rice) if lunch_rice else {}
                    if lunch_main:
                        main_macros = _get_meal_macros(lunch_main)
                        for k in lunch_total_macros:
                            lunch_total_macros[k] = lunch_total_macros.get(k, 0.0) + main_macros.get(k, 0.0)
                    if lunch_soup:
                        soup_macros = _get_meal_macros(lunch_soup)
                        for k in lunch_total_macros:
                            lunch_total_macros[k] = lunch_total_macros.get(k, 0.0) + soup_macros.get(k, 0.0)
                    if lunch_veg:
                        veg_macros = _get_meal_macros(lunch_veg)
                        for k in lunch_total_macros:
                            lunch_total_macros[k] = lunch_total_macros.get(k, 0.0) + veg_macros.get(k, 0.0)
                    if lunch_fruit:
                        fruit_macros = _get_meal_macros(lunch_fruit)
                        for k in lunch_total_macros:
                            lunch_total_macros[k] = lunch_total_macros.get(k, 0.0) + fruit_macros.get(k, 0.0)
                    
                    current_dinner_macros = {}
                    for dish in current_dinner_dishes:
                        dish_macros = _get_meal_macros(dish)
                        for k in dish_macros:
                            current_dinner_macros[k] = current_dinner_macros.get(k, 0.0) + dish_macros.get(k, 0.0)
                    
                    total_consumed_kcal = breakfast_macros.get("kcal", 0.0) + lunch_total_macros.get("kcal", 0.0) + current_dinner_macros.get("kcal", 0.0)
                    total_consumed_protein = breakfast_macros.get("protein_g", 0.0) + lunch_total_macros.get("protein_g", 0.0) + current_dinner_macros.get("protein_g", 0.0)
                    
                    daily_protein = targets.get("protein_g", 150.0)
                    daily_kcal = targets.get("tdee_kcal", 2000.0)
                    
                    actual_protein_needed = max(0.0, daily_protein - total_consumed_protein)
                    actual_kcal_needed = max(0.0, daily_kcal - total_consumed_kcal)
                    
                    protein_needed_from_remaining = remaining_targets.get("protein_g", 0.0)
                    kcal_needed_from_remaining = remaining_targets.get("kcal", 0.0)
                    
                    protein_needed = max(protein_needed_from_remaining, actual_protein_needed)
                    kcal_needed = max(kcal_needed_from_remaining, actual_kcal_needed)
                    
                    if actual_protein_needed > protein_needed_from_remaining or actual_kcal_needed > kcal_needed_from_remaining:
                        remaining_targets["protein_g"] = actual_protein_needed
                        remaining_targets["kcal"] = actual_kcal_needed
                    
                    protein_deficit_ratio = protein_needed / daily_protein if daily_protein > 0 else 0.0
                    kcal_deficit_ratio = kcal_needed / daily_kcal if daily_kcal > 0 else 0.0
                    
                    daily_fat = targets.get("fat_g", 60.0)
                    daily_carb = targets.get("carb_g", 200.0)
                    total_consumed_fat = breakfast_macros.get("fat_g", 0.0) + lunch_total_macros.get("fat_g", 0.0) + current_dinner_macros.get("fat_g", 0.0)
                    total_consumed_carb = breakfast_macros.get("carb_g", 0.0) + lunch_total_macros.get("carb_g", 0.0) + current_dinner_macros.get("carb_g", 0.0)
                    fat_excess_ratio = (total_consumed_fat - daily_fat) / daily_fat if daily_fat > 0 and total_consumed_fat > daily_fat else 0.0
                    carb_excess_ratio = (total_consumed_carb - daily_carb) / daily_carb if daily_carb > 0 and total_consumed_carb > daily_carb else 0.0
                    kcal_excess_ratio = (total_consumed_kcal - daily_kcal) / daily_kcal if daily_kcal > 0 and total_consumed_kcal > daily_kcal else 0.0
                    has_severe_fat_excess = fat_excess_ratio > 0.15
                    has_severe_carb_excess = carb_excess_ratio > 0.15
                    has_severe_kcal_excess = kcal_excess_ratio > 0.15
                    
                    # Stop conditions (aligned with plan_day)
                    if fat_excess_ratio > 0.40:
                        if protein_deficit_ratio > 0.35 or kcal_deficit_ratio > 0.40:
                            pass
                        else:
                            break
                    elif carb_excess_ratio > 0.50:
                        if protein_deficit_ratio > 0.30 or kcal_deficit_ratio > 0.35:
                            pass
                        else:
                            break
                    elif kcal_excess_ratio > 0.50:
                        if protein_deficit_ratio > 0.30 or kcal_deficit_ratio > 0.35:
                            pass
                        else:
                            break
                    elif has_severe_fat_excess or has_severe_carb_excess or has_severe_kcal_excess:
                        if protein_deficit_ratio > 0.20 or kcal_deficit_ratio > 0.25:
                            pass
                        elif protein_deficit_ratio < 0.20 and kcal_deficit_ratio < 0.25:
                            break
                    
                    current_main_count = sum(1 for d in current_dinner_dishes if _is_main_dish(d))
                    if current_main_count >= 3:
                        if kcal_deficit_ratio < 0.15 and protein_deficit_ratio < 0.20:
                            break
                    
                    current_meal_kcal = current_dinner_macros.get('kcal', 0)
                    meal_size_ratio = current_meal_kcal / dinner_max_kcal if dinner_max_kcal > 0 else 0
                    if kcal_deficit_ratio < 0.10 and protein_deficit_ratio < 0.15 and meal_size_ratio > 0.80:
                        break
                    elif kcal_deficit_ratio > 0.20 or protein_deficit_ratio > 0.25:
                        pass
                    
                    total_consumed_so_far = {
                        "kcal": total_consumed_kcal,
                        "protein_g": total_consumed_protein,
                        "fat_g": breakfast_macros.get("fat_g", 0.0) + lunch_total_macros.get("fat_g", 0.0) + current_dinner_macros.get("fat_g", 0.0),
                        "carb_g": breakfast_macros.get("carb_g", 0.0) + lunch_total_macros.get("carb_g", 0.0) + current_dinner_macros.get("carb_g", 0.0),
                    }
                    
                    if is_dinner_noodle:
                        supplementary_dishes = []
                    else:
                        if protein_deficit_ratio > 0.30 or kcal_deficit_ratio > 0.40:
                            effective_meal_max_kcal = dinner_max_kcal * 1.4
                        elif is_dinner_noodle or is_dinner_combined or protein_deficit_ratio > 0.20 or kcal_deficit_ratio > 0.30:
                            effective_meal_max_kcal = dinner_max_kcal * 1.3
                        else:
                            effective_meal_max_kcal = dinner_max_kcal * 1.2
                        
                        excluded_names = set()
                        for ex_recipe in excluded:
                            if ex_recipe:
                                ex_name = str(ex_recipe.get("dish_name", "")).lower().strip()
                                if ex_name:
                                    excluded_names.add(ex_name)
                        for dish in current_dinner_dishes:
                            if dish:
                                dish_name = str(dish.get("dish_name", "")).lower().strip()
                                if dish_name:
                                    excluded_names.add(dish_name)
                        
                        supplementary_dishes = add_supplementary_dishes(
                            "dinner",
                            current_dinner_dishes,
                            remaining_targets,
                            targets,
                            available_recipes,
                            excluded,
                            used_recipe_ids,
                            effective_meal_max_kcal,
                            0.15,
                            total_consumed_so_far=total_consumed_so_far,
                            used_recipe_names=set(),
                        )
                        
                        filtered_supplementary = []
                        for d in supplementary_dishes:
                            if isinstance(d, dict):
                                if d.get("recipe") or d.get("dish_name") or d.get("food_id"):
                                    filtered_supplementary.append(d)
                        supplementary_dishes = filtered_supplementary
                    
                    if not supplementary_dishes:
                        break
                    
                    for supp_dish in supplementary_dishes:
                        supp_recipe = supp_dish.get("recipe", supp_dish)
                        all_supplementary_dishes.append(supp_dish)
                        current_dinner_dishes.append(supp_recipe)
                        excluded.append(supp_recipe)
                        used_recipe_ids.add(str(supp_recipe.get("food_id", "")))
                        dish_macros = _get_meal_macros(supp_recipe)
                        for k in remaining_targets:
                            remaining_targets[k] = max(0.0, remaining_targets[k] - dish_macros.get(k, 0.0))
                    
                    iteration += 1
                
                supplementary_dishes = all_supplementary_dishes
                
                assigned_supp_dishes = []
                for supp_dish in supplementary_dishes:
                    supp_recipe = supp_dish.get("recipe", supp_dish)
                    dish_name = supp_recipe.get('dish_name', 'Unknown')
                    assigned = False
                    if _is_main_dish(supp_recipe):
                        if dinner_main:
                            logging.info(f"Added additional main dish to dinner: {dish_name}")
                        else:
                            dinner_main = supp_recipe
                            assigned = True
                            yield Response(f"✅ Added main dish to meet nutrition targets: {dish_name}")
                    elif _is_vegetable_dish(supp_recipe):
                        if not dinner_veg:
                            dinner_veg = supp_recipe
                            assigned = True
                            yield Response(f"✅ Added vegetable to meet nutrition targets: {dish_name}")
                        else:
                            logging.info(f"Added additional vegetable to dinner: {dish_name}")
                    elif _is_soup(supp_recipe):
                        if not dinner_soup:
                            dinner_soup = supp_recipe
                            assigned = True
                            yield Response(f"✅ Added soup to meet nutrition targets: {dish_name}")
                        else:
                            logging.info(f"Added additional soup to dinner: {dish_name}")
                    
                    if assigned:
                        assigned_supp_dishes.append(supp_dish)
                    else:
                        dinner_supplementary_dishes.append(supp_dish)
            
            # CRITICAL: Update remaining_targets AFTER calculating final dinner_total_macros
            if remaining_targets and targets:
                dinner_total_macros = _get_meal_macros(dinner_rice) if dinner_rice else {}
                if dinner_main:
                    main_macros = _get_meal_macros(dinner_main)
                    for k in dinner_total_macros:
                        dinner_total_macros[k] = dinner_total_macros.get(k, 0.0) + main_macros.get(k, 0.0)
                if dinner_soup:
                    soup_macros = _get_meal_macros(dinner_soup)
                    for k in dinner_total_macros:
                        dinner_total_macros[k] = dinner_total_macros.get(k, 0.0) + soup_macros.get(k, 0.0)
                if dinner_veg:
                    veg_macros = _get_meal_macros(dinner_veg)
                    for k in dinner_total_macros:
                        dinner_total_macros[k] = dinner_total_macros.get(k, 0.0) + veg_macros.get(k, 0.0)
                if dinner_fruit:
                    fruit_macros = _get_meal_macros(dinner_fruit)
                    for k in dinner_total_macros:
                        dinner_total_macros[k] = dinner_total_macros.get(k, 0.0) + fruit_macros.get(k, 0.0)
                if 'assigned_supp_dishes' in locals():
                    unassigned_supp_dishes = [d for d in dinner_supplementary_dishes if d not in assigned_supp_dishes]
                else:
                    unassigned_supp_dishes = dinner_supplementary_dishes
                for supp_dish in unassigned_supp_dishes:
                    supp_recipe = supp_dish.get("recipe", supp_dish)
                    supp_macros = _get_meal_macros(supp_recipe)
                    for k in dinner_total_macros:
                        dinner_total_macros[k] = dinner_total_macros.get(k, 0.0) + supp_macros.get(k, 0.0)
                
                breakfast_macros_check = _get_meal_macros(breakfast) if breakfast else {"kcal": 0.0, "protein_g": 0.0, "fat_g": 0.0, "carb_g": 0.0}
                lunch_total_macros_check = _get_meal_macros(lunch_rice) if lunch_rice else {}
                if lunch_main:
                    main_macros = _get_meal_macros(lunch_main)
                    for k in lunch_total_macros_check:
                        lunch_total_macros_check[k] = lunch_total_macros_check.get(k, 0.0) + main_macros.get(k, 0.0)
                if lunch_soup:
                    soup_macros = _get_meal_macros(lunch_soup)
                    for k in lunch_total_macros_check:
                        lunch_total_macros_check[k] = lunch_total_macros_check.get(k, 0.0) + soup_macros.get(k, 0.0)
                if lunch_veg:
                    veg_macros = _get_meal_macros(lunch_veg)
                    for k in lunch_total_macros_check:
                        lunch_total_macros_check[k] = lunch_total_macros_check.get(k, 0.0) + veg_macros.get(k, 0.0)
                if lunch_fruit:
                    fruit_macros = _get_meal_macros(lunch_fruit)
                    for k in lunch_total_macros_check:
                        lunch_total_macros_check[k] = lunch_total_macros_check.get(k, 0.0) + fruit_macros.get(k, 0.0)
                
                total_consumed_so_far_kcal = breakfast_macros_check.get("kcal", 0.0) + lunch_total_macros_check.get("kcal", 0.0) + dinner_total_macros.get("kcal", 0.0)
                total_consumed_so_far_protein = breakfast_macros_check.get("protein_g", 0.0) + lunch_total_macros_check.get("protein_g", 0.0) + dinner_total_macros.get("protein_g", 0.0)
                total_consumed_so_far_fat = breakfast_macros_check.get("fat_g", 0.0) + lunch_total_macros_check.get("fat_g", 0.0) + dinner_total_macros.get("fat_g", 0.0)
                total_consumed_so_far_carb = breakfast_macros_check.get("carb_g", 0.0) + lunch_total_macros_check.get("carb_g", 0.0) + dinner_total_macros.get("carb_g", 0.0)
                
                daily_protein_check = targets.get("protein_g", 150.0)
                daily_kcal_check = targets.get("tdee_kcal", 2000.0)
                daily_fat_check = targets.get("fat_g", 60.0)
                daily_carb_check = targets.get("carb_g", 200.0)
                
                actual_remaining_kcal = max(0.0, daily_kcal_check - total_consumed_so_far_kcal)
                actual_remaining_protein = max(0.0, daily_protein_check - total_consumed_so_far_protein)
                actual_remaining_fat = max(0.0, daily_fat_check - total_consumed_so_far_fat)
                actual_remaining_carb = max(0.0, daily_carb_check - total_consumed_so_far_carb)
                
                remaining_targets["kcal"] = actual_remaining_kcal
                remaining_targets["protein_g"] = actual_remaining_protein
                remaining_targets["fat_g"] = actual_remaining_fat
                remaining_targets["carb_g"] = actual_remaining_carb
                
                logging.debug(
                    f"plan_week_e2e_tool: Day {day_index + 1} - After dinner (with supplementary), remaining: "
                    f"kcal={remaining_targets['kcal']:.1f} protein={remaining_targets['protein_g']:.1f} "
                    f"fat={remaining_targets['fat_g']:.1f} carb={remaining_targets['carb_g']:.1f}"
                )
            
            if not breakfast or not lunch_rice or not lunch_main or not dinner_rice or not dinner_main:
                yield Error(f"Could not assemble meals for day {day_index + 1}")
                return
            
            # Track used recipes (including soup and supplementary dishes)
            all_meals = [breakfast, lunch_rice, lunch_main, dinner_rice, dinner_main]
            if lunch_soup:
                all_meals.append(lunch_soup)
            if lunch_veg:
                all_meals.append(lunch_veg)
            if lunch_fruit:
                all_meals.append(lunch_fruit)
            if dinner_soup:
                all_meals.append(dinner_soup)
            if dinner_veg:
                all_meals.append(dinner_veg)
            if dinner_fruit:
                all_meals.append(dinner_fruit)
            
            # Add supplementary dishes to tracking
            if 'lunch_supplementary_dishes' in locals():
                for supp_dish in lunch_supplementary_dishes:
                    supp_recipe = supp_dish.get("recipe", supp_dish)
                    if supp_recipe:
                        all_meals.append(supp_recipe)
            if 'dinner_supplementary_dishes' in locals():
                for supp_dish in dinner_supplementary_dishes:
                    supp_recipe = supp_dish.get("recipe", supp_dish)
                    if supp_recipe:
                        all_meals.append(supp_recipe)
            
            # Track recipes used in this day
            day_used_ids = set()
            for meal in all_meals:
                if meal and meal.get("food_id"):
                    meal_id = str(meal.get("food_id"))
                    if not _is_default_white_rice_id(meal_id):
                        used_recipe_ids.add(meal_id)
                        day_used_ids.add(meal_id)
                    used_recipes.append(meal)
            
            # Store recently used recipes for this day
            recently_used_per_day[day_index] = day_used_ids
            
            # Build day plan with Vietnamese meal structure (aligned with plan_day_e2e.py)
            day_plan = {
                "breakfast": {"recipe": breakfast, "servings": 1.0, "meal_type": "breakfast"},
                "lunch": {
                    "recipe": lunch_rice,
                    "servings": 1.0,
                    "meal_type": "lunch",
                    "accompaniments": []
                },
                "dinner": {
                    "recipe": dinner_rice,
                    "servings": 1.0,
                    "meal_type": "dinner",
                    "accompaniments": []
                },
            }
            
            # Add accompaniments (main, soup, vegetable, fruit) - aligned with plan_day structure
            if lunch_main:
                day_plan["lunch"]["accompaniments"].append({"recipe": lunch_main, "servings": 1.0, "type": "main"})
            if lunch_soup:
                day_plan["lunch"]["accompaniments"].append({"recipe": lunch_soup, "servings": 1.0, "type": "soup"})
            if lunch_veg:
                day_plan["lunch"]["accompaniments"].append({"recipe": lunch_veg, "servings": 1.0, "type": "vegetable"})
            if lunch_fruit:
                day_plan["lunch"]["accompaniments"].append({"recipe": lunch_fruit, "servings": 1.0, "type": "fruit"})
            
            if dinner_main:
                day_plan["dinner"]["accompaniments"].append({"recipe": dinner_main, "servings": 1.0, "type": "main"})
            if dinner_soup:
                day_plan["dinner"]["accompaniments"].append({"recipe": dinner_soup, "servings": 1.0, "type": "soup"})
            if dinner_veg:
                day_plan["dinner"]["accompaniments"].append({"recipe": dinner_veg, "servings": 1.0, "type": "vegetable"})
            if dinner_fruit:
                day_plan["dinner"]["accompaniments"].append({"recipe": dinner_fruit, "servings": 1.0, "type": "fruit"})
            
            # Add supplementary dishes that weren't assigned to existing slots
            if 'lunch_supplementary_dishes' in locals():
                for supp_dish in lunch_supplementary_dishes:
                    supp_recipe = supp_dish.get("recipe", supp_dish)
                    if supp_recipe:
                        supp_type = "main" if _is_main_dish(supp_recipe) else "vegetable" if _is_vegetable_dish(supp_recipe) else "soup" if _is_soup(supp_recipe) else "other"
                        day_plan["lunch"]["accompaniments"].append({"recipe": supp_recipe, "servings": 1.0, "type": supp_type})
            if 'dinner_supplementary_dishes' in locals():
                for supp_dish in dinner_supplementary_dishes:
                    supp_recipe = supp_dish.get("recipe", supp_dish)
                    if supp_recipe:
                        supp_type = "main" if _is_main_dish(supp_recipe) else "vegetable" if _is_vegetable_dish(supp_recipe) else "soup" if _is_soup(supp_recipe) else "other"
                        day_plan["dinner"]["accompaniments"].append({"recipe": supp_recipe, "servings": 1.0, "type": supp_type})

            # Prevent overcrowding: keep at most one main accompaniment per meal
            _trim_excess_mains(day_plan["lunch"]["accompaniments"])
            _trim_excess_mains(day_plan["dinner"]["accompaniments"])

            # CRITICAL: If daily macros are far below target, add supplementary dishes BEFORE scaling
            # This ensures we have enough dishes before scaling reduces them
            if targets:
                _maybe_add_supplementary("dinner", day_plan, is_dinner_combined, is_dinner_noodle)
                _maybe_add_supplementary("lunch", day_plan, is_lunch_combined, is_lunch_noodle)
                # Re-trim after supplements
                _trim_excess_mains(day_plan["lunch"]["accompaniments"])
                _trim_excess_mains(day_plan["dinner"]["accompaniments"])
            
            # Calculate initial day macros (will be recalculated after scaling)
            day_macros = {"kcal": 0.0, "protein_g": 0.0, "fat_g": 0.0, "carb_g": 0.0}
            for meal_key, meal_data in day_plan.items():
                # Main recipe
                recipe = meal_data["recipe"]
                servings = meal_data.get("servings", 1.0)
                macros = _get_meal_macros(recipe)
                for key in day_macros:
                    day_macros[key] += macros[key] * servings
                    total_macros[key] += macros[key] * servings
                
                # Accompaniments (for lunch/dinner Vietnamese meals)
                accompaniments = meal_data.get("accompaniments", [])
                for acc in accompaniments:
                    acc_recipe = acc.get("recipe")
                    acc_servings = acc.get("servings", 1.0)
                    if acc_recipe:
                        acc_macros = _get_meal_macros(acc_recipe)
                        for key in day_macros:
                            day_macros[key] += acc_macros[key] * acc_servings
                            total_macros[key] += acc_macros[key] * acc_servings
            
            # CRITICAL: Ensure each day meets its daily targets (user requirement)
            # User feedback: "Tôi cần planning meal đảm bảo dinh dưỡng theo từng ngày, hiện tại tôi thấy có ngày ăn ít ngày ăn nhiều"
            # Goal: Ensure each day reaches at least 85-90% of daily targets before moving to next day
            if targets and remaining_targets:
                daily_kcal = targets.get("tdee_kcal", 2000.0)
                daily_protein = targets.get("protein_g", 150.0)
                daily_fat = targets.get("fat_g", 65.0)
                daily_carb = targets.get("carb_g", 200.0)
                
                kcal_deficit = daily_kcal - day_macros["kcal"]
                protein_deficit = daily_protein - day_macros["protein_g"]
                fat_deficit = daily_fat - day_macros["fat_g"]
                carb_deficit = daily_carb - day_macros["carb_g"]
                
                # Calculate coverage percentages
                kcal_coverage = (day_macros["kcal"] / daily_kcal * 100) if daily_kcal > 0 else 0.0
                protein_coverage = (day_macros["protein_g"] / daily_protein * 100) if daily_protein > 0 else 0.0
                
                # CRITICAL: Ensure each day reaches at least 90-95% of daily targets
                # This ensures weekly plan meets targets (7 days * 90% = 630% total, but we aim for 700% = 100% per day)
                min_coverage_threshold = 90.0  # Increased from 85% to 90% to ensure better weekly coverage
                if kcal_coverage < min_coverage_threshold or protein_coverage < min_coverage_threshold:
                    logging.info(
                        f"plan_week_e2e_tool: Day {day_index + 1} - Daily coverage below threshold: "
                        f"kcal={kcal_coverage:.1f}% protein={protein_coverage:.1f}% | "
                        f"deficit: kcal={kcal_deficit:.1f} protein={protein_deficit:.1f} carb={carb_deficit:.1f}, attempting to fill..."
                    )
                    
                    # User requirement: If missing carb, increase white rice serving
                    # Lower threshold from 15% to 10% to catch deficits earlier
                    if carb_deficit > daily_carb * 0.10:
                        # Find white rice in lunch or dinner
                        for meal_key in ["lunch", "dinner"]:
                            meal_data = day_plan.get(meal_key, {})
                            meal_recipe = meal_data.get("recipe")
                            if meal_recipe:
                                dish_name = str(meal_recipe.get("dish_name", "")).lower()
                                if "cơm trắng" in dish_name or "com trang" in dish_name or "white rice" in dish_name:
                                    # Increase serving to fill carb deficit
                                    current_serving = meal_data.get("servings", 1.0)
                                    rice_macros = _get_meal_macros(meal_recipe)
                                    carb_per_serving = rice_macros.get("carb_g", 0.0)
                                    if carb_per_serving > 0:
                                        additional_servings = min(2.0, carb_deficit / carb_per_serving)
                                        new_serving = current_serving + additional_servings
                                        meal_data["servings"] = round(new_serving, 2)
                                        # Recalculate day macros
                                        additional_carb = carb_per_serving * additional_servings
                                        additional_kcal = rice_macros.get("kcal", 0.0) * additional_servings
                                        day_macros["carb_g"] += additional_carb
                                        day_macros["kcal"] += additional_kcal
                                        total_macros["carb_g"] += additional_carb
                                        total_macros["kcal"] += additional_kcal
                                        carb_deficit -= additional_carb
                                        logging.info(
                                            f"plan_week_e2e_tool: Day {day_index + 1} - Increased white rice serving "
                                            f"from {current_serving:.2f} to {new_serving:.2f} to meet carb target "
                                            f"(added {additional_carb:.1f}g carb)"
                                        )
                                        break
                    
                    # User requirement: If missing protein, prioritize chicken/beef dishes (especially for gym users)
                    # CRITICAL: Also check kcal deficit - if kcal deficit is large, add dishes even if protein is OK
                    # This ensures we meet daily kcal target (critical for weekly coverage)
                    if protein_deficit > 5.0 or kcal_deficit > 200.0:
                        # First, try to find chicken or beef dishes
                        excluded = [breakfast, lunch_rice, lunch_main, dinner_rice, dinner_main] + \
                                   [acc.get("recipe") for meal in day_plan.values() 
                                    for acc in meal.get("accompaniments", []) if acc.get("recipe")]
                        
                        # CRITICAL: Block similar dishes completely (aligned with meal_assembly.py and plan_day_e2e.py)
                        def _dish_name_similar_local(name1: str, name2: str, threshold: float = 0.7) -> bool:
                            """Local helper for similarity check."""
                            name1 = name1.lower().strip()
                            name2 = name2.lower().strip()
                            if name1 == name2:
                                return True
                            if name1 in name2 or name2 in name1:
                                shorter = min(len(name1), len(name2))
                                longer = max(len(name1), len(name2))
                                if shorter > 0:
                                    similarity = shorter / longer
                                    if similarity >= threshold:
                                        return True
                            words1 = set(name1.split())
                            words2 = set(name2.split())
                            if words1 and words2:
                                common_words = words1 & words2
                                total_words = words1 | words2
                                if total_words:
                                    word_similarity = len(common_words) / len(total_words)
                                    if word_similarity >= threshold:
                                        return True
                            return False
                        
                        # Collect all dish names from excluded recipes for similarity check
                        excluded_names = set()
                        for ex_recipe in excluded:
                            if ex_recipe:
                                ex_name = str(ex_recipe.get("dish_name", "")).lower().strip()
                                if ex_name:
                                    excluded_names.add(ex_name)
                        
                        # Also check all dishes already used in the week
                        for day_data in weekly_plan.values():
                            day_meals = day_data.get("meals", {})
                            for meal_key, meal_data in day_meals.items():
                                meal_recipe = meal_data.get("recipe")
                                if meal_recipe:
                                    meal_name = str(meal_recipe.get("dish_name", "")).lower().strip()
                                    if meal_name:
                                        excluded_names.add(meal_name)
                                for acc in meal_data.get("accompaniments", []):
                                    acc_recipe = acc.get("recipe")
                                    if acc_recipe:
                                        acc_name = str(acc_recipe.get("dish_name", "")).lower().strip()
                                        if acc_name:
                                            excluded_names.add(acc_name)
                        
                        # Filter for chicken/beef dishes
                        chicken_beef_candidates = []
                        for recipe in available_recipes:
                            if recipe in excluded:
                                continue
                            if not _is_main_dish(recipe):
                                continue
                            
                            dish_name = str(recipe.get("dish_name", "")).lower().strip()
                            
                            # CRITICAL: Block similar dishes completely (similarity > 0.7)
                            is_similar = False
                            for excluded_name in excluded_names:
                                if _dish_name_similar_local(dish_name, excluded_name, threshold=0.7):
                                    is_similar = True
                                    logging.debug(
                                        f"plan_week_e2e_tool: Day {day_index + 1} - Blocking similar dish "
                                        f"'{dish_name}' (similar to '{excluded_name}')"
                                    )
                                    break
                            
                            if is_similar:
                                continue
                            
                            # Check for chicken (gà) or beef (bò)
                            if "gà" in dish_name or "ga" in dish_name or "chicken" in dish_name or \
                               "bò" in dish_name or "bo" in dish_name or "beef" in dish_name:
                                macros = _get_meal_macros(recipe)
                                # CRITICAL: Filter out recipes with excessive kcal to avoid scaling
                                # Also require higher protein (25g+) for better protein coverage
                                # Reduced max_kcal from 500 to 450 to prevent scaling
                                if (macros.get("protein_g", 0.0) >= 25.0 and 
                                    macros.get("kcal", 0.0) <= min(400.0, kcal_deficit * 1.2) and
                                    macros.get("kcal", 0.0) <= 450.0):  # Reduced hard cap from 500 to avoid scaling
                                    chicken_beef_candidates.append((recipe, macros.get("protein_g", 0.0)))
                        
                        # Sort by protein content (highest first)
                        chicken_beef_candidates.sort(key=lambda x: x[1], reverse=True)
                        
                        supp = None
                        if chicken_beef_candidates:
                            # Use highest protein chicken/beef dish
                            supp = chicken_beef_candidates[0][0]
                            logging.debug(
                                f"plan_week_e2e_tool: Day {day_index + 1} - Found chicken/beef dish for protein: "
                                f"'{supp.get('dish_name', 'Unknown')}' ({chicken_beef_candidates[0][1]:.1f}g protein)"
                            )
                        else:
                            # Fallback: use highest protein dish (not necessarily chicken/beef)
                            # CRITICAL: Filter out recipes with excessive kcal to avoid scaling
                            # CRITICAL: Also filter out similar dishes before calling select_meal_by_strategy
                            filtered_available = []
                            for recipe in available_recipes:
                                if recipe in excluded:
                                    continue
                                dish_name = str(recipe.get("dish_name", "")).lower().strip()
                                
                                # Block similar dishes
                                is_similar = False
                                for excluded_name in excluded_names:
                                    if _dish_name_similar_local(dish_name, excluded_name, threshold=0.7):
                                        is_similar = True
                                        break
                                
                                if not is_similar:
                                    filtered_available.append(recipe)
                            
                            supp = select_meal_by_strategy(
                                filtered_available if filtered_available else available_recipes,
                                "highest_protein",
                                exclude=excluded,
                                used_recipe_ids=set(),  # Allow reuse for daily target fulfillment
                                preferred_meal_type="dinner",
                                target_macros={"protein_g": protein_deficit, "kcal": kcal_deficit},
                                require_macros=True,
                                min_kcal=100.0,
                                max_kcal=min(400.0, kcal_deficit * 1.2),  # Reduced from 450.0 to avoid scaling
                                min_protein=25.0,  # Increased from 20.0 for better protein coverage
                            )
                        
                        if supp and _is_main_dish(supp):
                            day_plan["dinner"]["accompaniments"].append(
                                {"recipe": supp, "servings": 1.0, "type": "main"}
                            )
                            supp_macros = _get_meal_macros(supp)
                            day_macros["kcal"] += supp_macros["kcal"]
                            day_macros["protein_g"] += supp_macros["protein_g"]
                            day_macros["fat_g"] += supp_macros["fat_g"]
                            day_macros["carb_g"] += supp_macros["carb_g"]
                            total_macros["kcal"] += supp_macros["kcal"]
                            total_macros["protein_g"] += supp_macros["protein_g"]
                            total_macros["fat_g"] += supp_macros["fat_g"]
                            total_macros["carb_g"] += supp_macros["carb_g"]
                            logging.info(
                                f"plan_week_e2e_tool: Day {day_index + 1} - Added supplementary dish "
                                f"'{supp.get('dish_name', 'Unknown')}' to meet daily protein target "
                                f"({supp_macros.get('protein_g', 0):.1f}g protein)"
                            )
                            _trim_excess_mains(day_plan["dinner"]["accompaniments"])
            
            weekly_plan[day_key] = {
                "day_index": day_index,
                "date": day_key,
                "meals": day_plan,
                "total_macros": day_macros,  # Will be recalculated after scaling
            }
        
        # Normalize servings per day to discrete values (aligned with plan_day)
        for day_data in weekly_plan.values():
            _normalize_servings_day(day_data.get("meals", {}))

        # Apply per-meal scaling to prevent over-coverage (aligned with plan_day)
        def _scale_meal_if_needed(meal_key: str, day_plan: Dict[str, Any], cap_kcal: float, cap_fat: float, day_macros_before: Dict[str, float] = None) -> None:
            """
            Scale down meal servings if it exceeds kcal/fat caps.
            CRITICAL: Don't scale too much if daily target is not yet met.
            """
            meal = day_plan.get(meal_key)
            if not meal:
                return
            
            meal_kcal = 0.0
            meal_fat = 0.0
            
            # Calculate total kcal and fat for meal (including accompaniments)
            recipe = meal.get("recipe")
            servings = meal.get("servings", 1.0)
            if recipe:
                macros = _get_meal_macros(recipe)
                meal_kcal += macros.get("kcal", 0.0) * servings
                meal_fat += macros.get("fat_g", 0.0) * servings
            
            for acc in meal.get("accompaniments", []):
                acc_recipe = acc.get("recipe", {})
                acc_servings = acc.get("servings", 1.0)
                if acc_recipe:
                    acc_macros = _get_meal_macros(acc_recipe)
                    meal_kcal += acc_macros.get("kcal", 0.0) * acc_servings
                    meal_fat += acc_macros.get("fat_g", 0.0) * acc_servings

            scale_factors = [1.0]
            if cap_kcal and meal_kcal > cap_kcal:
                scale_factors.append(cap_kcal / meal_kcal)
            if cap_fat and meal_fat > cap_fat:
                scale_factors.append(cap_fat / meal_fat)
            
            # CRITICAL: Check if daily target is met before scaling
            # If daily target is not met, be more lenient with scaling
            min_scale = 0.5  # Default minimum scale
            if day_macros_before and targets:
                daily_kcal = targets.get("tdee_kcal", 2000.0)
                daily_protein = targets.get("protein_g", 150.0)
                kcal_coverage = (day_macros_before.get("kcal", 0.0) / daily_kcal * 100) if daily_kcal > 0 else 0.0
                protein_coverage = (day_macros_before.get("protein_g", 0.0) / daily_protein * 100) if daily_protein > 0 else 0.0
                
                # If daily coverage is below 90%, don't scale too much (minimum 0.7 instead of 0.5)
                if kcal_coverage < 90.0 or protein_coverage < 90.0:
                    min_scale = 0.7  # More lenient: only scale down to 70% instead of 50%
                    logging.debug(
                        f"plan_week_e2e_tool: Daily coverage low (kcal={kcal_coverage:.1f}% protein={protein_coverage:.1f}%), "
                        f"using lenient scaling (min_scale={min_scale})"
                    )
                # If daily coverage is below 80%, be even more lenient (minimum 0.8)
                elif kcal_coverage < 80.0 or protein_coverage < 80.0:
                    min_scale = 0.8
                    logging.debug(
                        f"plan_week_e2e_tool: Daily coverage very low (kcal={kcal_coverage:.1f}% protein={protein_coverage:.1f}%), "
                        f"using very lenient scaling (min_scale={min_scale})"
                    )
            
            scale = max(min_scale, min(scale_factors))  # Don't scale below min_scale
            if scale < 0.999:
                logging.warning(
                    f"plan_week_e2e_tool: Scaling {meal_key} meal: "
                    f"kcal={meal_kcal:.1f} fat={meal_fat:.1f} cap_kcal={cap_kcal:.1f} cap_fat={cap_fat:.1f} scale={scale:.3f}"
                )
                meal["servings"] = round(meal.get("servings", 1.0) * scale, 3)
                for acc in meal.get("accompaniments", []):
                    acc["servings"] = round(acc.get("servings", 1.0) * scale, 3)
        
        # Apply scaling to all days to prevent over-coverage
        if targets:
            # CRITICAL: Calculate day_macros BEFORE scaling to check daily coverage
            day_macros_before_scaling = {}
            for day_key, day_data in weekly_plan.items():
                day_plan = day_data.get("meals", {})
                day_macros = {"kcal": 0.0, "protein_g": 0.0, "fat_g": 0.0, "carb_g": 0.0}
                
                for meal_key, meal_data in day_plan.items():
                    recipe = meal_data.get("recipe")
                    servings = meal_data.get("servings", 1.0)
                    if recipe:
                        macros = _get_meal_macros(recipe)
                        for key in day_macros:
                            day_macros[key] += macros.get(key, 0.0) * servings
                    
                    accompaniments = meal_data.get("accompaniments", [])
                    for acc in accompaniments:
                        acc_recipe = acc.get("recipe")
                        acc_servings = acc.get("servings", 1.0)
                        if acc_recipe:
                            acc_macros = _get_meal_macros(acc_recipe)
                            for key in day_macros:
                                day_macros[key] += acc_macros.get(key, 0.0) * acc_servings
                
                day_macros_before_scaling[day_key] = day_macros
            
            for day_key, day_data in weekly_plan.items():
                day_plan = day_data.get("meals", {})
                day_macros_before = day_macros_before_scaling.get(day_key, {})
                # Apply per-meal caps (kcal + fat) before final macro calc (aligned with plan_day)
                # CRITICAL: Pass day_macros_before to avoid scaling too much when daily target not met
                _scale_meal_if_needed("breakfast", day_plan, breakfast_max_kcal, 25.0, day_macros_before)
                _scale_meal_if_needed("lunch", day_plan, lunch_max_kcal, 60.0, day_macros_before)
                _scale_meal_if_needed("dinner", day_plan, dinner_max_kcal, 60.0, day_macros_before)
            
            # Recalculate totals after scaling
            total_macros = {"kcal": 0.0, "protein_g": 0.0, "fat_g": 0.0, "carb_g": 0.0}
            for day_key, day_data in weekly_plan.items():
                day_plan = day_data.get("meals", {})
                day_macros = {"kcal": 0.0, "protein_g": 0.0, "fat_g": 0.0, "carb_g": 0.0}
                
                for meal_key, meal_data in day_plan.items():
                    recipe = meal_data.get("recipe")
                    servings = meal_data.get("servings", 1.0)
                    if recipe:
                        macros = _get_meal_macros(recipe)
                        for key in day_macros:
                            day_macros[key] += macros.get(key, 0.0) * servings
                            total_macros[key] += macros.get(key, 0.0) * servings
                    
                    accompaniments = meal_data.get("accompaniments", [])
                    for acc in accompaniments:
                        acc_recipe = acc.get("recipe")
                        acc_servings = acc.get("servings", 1.0)
                        if acc_recipe:
                            acc_macros = _get_meal_macros(acc_recipe)
                            for key in day_macros:
                                day_macros[key] += acc_macros.get(key, 0.0) * acc_servings
                                total_macros[key] += acc_macros.get(key, 0.0) * acc_servings
                
                day_data["total_macros"] = day_macros
                
                # CRITICAL: After scaling, check if daily target is still met and fill if needed
                daily_kcal = targets.get("tdee_kcal", 2000.0)
                daily_protein = targets.get("protein_g", 150.0)
                daily_carb = targets.get("carb_g", 200.0)
                
                kcal_coverage = (day_macros["kcal"] / daily_kcal * 100) if daily_kcal > 0 else 0.0
                protein_coverage = (day_macros["protein_g"] / daily_protein * 100) if daily_protein > 0 else 0.0
                carb_coverage = (day_macros["carb_g"] / daily_carb * 100) if daily_carb > 0 else 0.0
                
                # CRITICAL: If coverage dropped below 90% after scaling, add supplementary dishes
                if kcal_coverage < 90.0 or protein_coverage < 90.0:
                    logging.info(
                        f"plan_week_e2e_tool: Day {day_data.get('day_index', 0) + 1} - Coverage dropped after scaling: "
                        f"kcal={kcal_coverage:.1f}% protein={protein_coverage:.1f}%, attempting to fill..."
                    )
                    
                    kcal_deficit = daily_kcal - day_macros["kcal"]
                    protein_deficit = daily_protein - day_macros["protein_g"]
                    carb_deficit = daily_carb - day_macros["carb_g"]
                    
                    # Fill carb deficit first (increase rice serving)
                    if carb_deficit > daily_carb * 0.10:
                        for meal_key in ["lunch", "dinner"]:
                            meal_data = day_plan.get(meal_key, {})
                            meal_recipe = meal_data.get("recipe")
                            if meal_recipe:
                                dish_name = str(meal_recipe.get("dish_name", "")).lower()
                                if "cơm trắng" in dish_name or "com trang" in dish_name or "white rice" in dish_name:
                                    current_serving = meal_data.get("servings", 1.0)
                                    rice_macros = _get_meal_macros(meal_recipe)
                                    carb_per_serving = rice_macros.get("carb_g", 0.0)
                                    if carb_per_serving > 0:
                                        additional_servings = min(2.0, carb_deficit / carb_per_serving)
                                        new_serving = current_serving + additional_servings
                                        meal_data["servings"] = round(new_serving, 2)
                                        additional_carb = carb_per_serving * additional_servings
                                        additional_kcal = rice_macros.get("kcal", 0.0) * additional_servings
                                        day_macros["carb_g"] += additional_carb
                                        day_macros["kcal"] += additional_kcal
                                        total_macros["carb_g"] += additional_carb
                                        total_macros["kcal"] += additional_kcal
                                        logging.info(
                                            f"plan_week_e2e_tool: Day {day_data.get('day_index', 0) + 1} - Increased rice serving "
                                            f"after scaling: {current_serving:.2f} -> {new_serving:.2f}"
                                        )
                                        break
                    
                    # Fill protein/kcal deficit with supplementary dishes
                    if protein_deficit > 10.0 or kcal_deficit > 300.0:
                        # Find available recipes (not used in this day)
                        excluded = []
                        for meal_data in day_plan.values():
                            recipe = meal_data.get("recipe")
                            if recipe:
                                excluded.append(recipe)
                            for acc in meal_data.get("accompaniments", []):
                                acc_recipe = acc.get("recipe")
                                if acc_recipe:
                                    excluded.append(acc_recipe)
                        
                        # Try to add supplementary dish to dinner
                        # Use full recipes pool (not available_recipes which is scoped to day loop)
                        supp = select_meal_by_strategy(
                            recipes,
                            "highest_protein",
                            exclude=excluded,
                            used_recipe_ids=set(),  # Allow reuse for daily target fulfillment
                            preferred_meal_type="dinner",
                            target_macros={"protein_g": protein_deficit, "kcal": kcal_deficit},
                            require_macros=True,
                            min_kcal=100.0,
                            max_kcal=min(500.0, kcal_deficit * 1.2),
                            min_protein=20.0,
                        )
                        
                        if supp and _is_main_dish(supp):
                            day_plan["dinner"]["accompaniments"].append(
                                {"recipe": supp, "servings": 1.0, "type": "main"}
                            )
                            supp_macros = _get_meal_macros(supp)
                            day_macros["kcal"] += supp_macros["kcal"]
                            day_macros["protein_g"] += supp_macros["protein_g"]
                            day_macros["fat_g"] += supp_macros["fat_g"]
                            day_macros["carb_g"] += supp_macros["carb_g"]
                            total_macros["kcal"] += supp_macros["kcal"]
                            total_macros["protein_g"] += supp_macros["protein_g"]
                            total_macros["fat_g"] += supp_macros["fat_g"]
                            total_macros["carb_g"] += supp_macros["carb_g"]
                            logging.info(
                                f"plan_week_e2e_tool: Day {day_data.get('day_index', 0) + 1} - Added supplementary dish "
                                f"after scaling: '{supp.get('dish_name', 'Unknown')}' "
                                f"({supp_macros.get('protein_g', 0):.1f}g protein, {supp_macros.get('kcal', 0):.1f} kcal)"
                            )
                            _trim_excess_mains(day_plan["dinner"]["accompaniments"])
        
        # Optional optimization: swap some mains to improve weekly macro fit
        total_macros = _try_optimize_macros(weekly_plan, total_macros)

        # Calculate average daily macros
        average_daily_macros = {
            "kcal": total_macros["kcal"] / 7.0,
            "protein_g": total_macros["protein_g"] / 7.0,
            "fat_g": total_macros["fat_g"] / 7.0,
            "carb_g": total_macros["carb_g"] / 7.0,
        }
        # Quick coverage check vs targets to surface quality issues early
        if targets:
            target_kcal = targets.get("tdee_kcal", 0.0)
            target_protein = targets.get("protein_g", 0.0)
            kcal_cov = (average_daily_macros["kcal"] / target_kcal * 100) if target_kcal else 0.0
            protein_cov = (average_daily_macros["protein_g"] / target_protein * 100) if target_protein else 0.0
            if kcal_cov < 85.0 or protein_cov < 85.0:
                logging.warning(
                    "plan_week_e2e_tool: LOW_WEEKLY_COVERAGE kcal=%.1f%% protein=%.1f%%",
                    kcal_cov,
                    protein_cov,
                )
            if kcal_cov > 125.0 or protein_cov > 125.0:
                logging.warning(
                    "plan_week_e2e_tool: HIGH_WEEKLY_COVERAGE kcal=%.1f%% protein=%.1f%%",
                    kcal_cov,
                    protein_cov,
                )
        logging.debug(
            "plan_week_e2e_tool: weekly totals kcal=%.1f protein=%.1f fat=%.1f carb=%.1f | avg/day kcal=%.1f protein=%.1f fat=%.1f carb=%.1f",
            total_macros["kcal"],
            total_macros["protein_g"],
            total_macros["fat_g"],
            total_macros["carb_g"],
            average_daily_macros["kcal"],
            average_daily_macros["protein_g"],
            average_daily_macros["fat_g"],
            average_daily_macros["carb_g"],
        )
        
        # Step 6: Calculate variety score
        plan_for_variety = {
            "plan_type": "week",
            "days": weekly_plan,
        }
        variety_score = _calculate_variety_score(plan_for_variety)
        
        # Step 7: Validate
        validation = {"valid": True, "macro_validation": {}, "constraint_validation": {}, "variety_validation": {}}
        
        if targets:
            yield Response("✅ Checking weekly nutritional balance...")
            # Validate against weekly targets (7x daily targets)
            weekly_targets = {
                "tdee_kcal": targets.get("tdee_kcal", 2000) * 7.0,
                "protein_g": targets.get("protein_g", 150) * 7.0,
                "fat_g": targets.get("fat_g", 67) * 7.0,
                "carb_g": targets.get("carb_g", 200) * 7.0,
            }
            macro_validation = _validate_macro_targets(total_macros, weekly_targets, macro_tolerance_percent)
            validation["macro_validation"] = macro_validation
            
            # Calculate macro accuracy percentage for better feedback
            macro_accuracy = 100.0
            if total_macros.get("kcal", 0) > 0:
                kcal_deviation = abs(total_macros.get("kcal", 0) - weekly_targets.get("tdee_kcal", 14000)) / weekly_targets.get("tdee_kcal", 14000)
                macro_accuracy = max(0.0, 100.0 - (kcal_deviation * 100.0))
            
            if not macro_validation["valid"]:
                validation["valid"] = False
                violations = len(macro_validation.get('violations', []))
                warnings = len(macro_validation.get('warnings', []))
                if violations > 0:
                    yield Response(f"⚠️ Weekly macros: {violations} deviation(s) from targets (Accuracy: {macro_accuracy:.1f}%)")
                if warnings > 0:
                    yield Response(f"ℹ️ {warnings} minor deviation(s) detected (Accuracy: {macro_accuracy:.1f}%)")
            else:
                yield Response(f"✅ Weekly macros within target range (Accuracy: {macro_accuracy:.1f}%)")
        
        if filters_metadata:
            yield Response("✅ Verifying dietary constraints across all meals...")
            diet_types = filters_metadata.get("diet_types", [])
            exclude_allergens = filters_metadata.get("exclude_allergens", [])
            constraint_validation = _validate_constraints_weekly(
                {"days": weekly_plan},
                diet_types if diet_types else None,
                exclude_allergens if exclude_allergens else None,
            )
            validation["constraint_validation"] = constraint_validation
            if not constraint_validation["valid"]:
                validation["valid"] = False
                violations = len(constraint_validation.get('violations', []))
                yield Response(f"⚠️ {violations} constraint violation(s) found")
            else:
                yield Response("✅ All dietary constraints satisfied")
        
        # Variety validation
        variety_validation = {
            "valid": variety_score >= min_variety_score,
            "score": variety_score,
            "min_required": min_variety_score,
        }
        validation["variety_validation"] = variety_validation
        if not variety_validation["valid"]:
            validation["valid"] = False
            yield Response(f"⚠️ Variety score {variety_score:.1f}/100 (minimum: {min_variety_score:.1f})")
        else:
            yield Response(f"✅ Variety score: {variety_score:.1f}/100 (excellent variety!)")
        
        # Step 6: Calculate micronutrients
        yield Response("🔬 Calculating micronutrients (vitamins & minerals)...")
        profile_results = tree_data.environment.find("profile_crud_tool", "profile")
        gender = None
        if profile_results and profile_results[0]["objects"]:
            gender = profile_results[0]["objects"][0].get("gender")
        
        try:
            micronutrients = await _calculate_plan_micronutrients(
                {"plan_type": "week", "days": weekly_plan},
                client_manager=client_manager,
                gender=gender,
            )
        except Exception as e:
            logging.warning(f"plan_week_e2e_tool: Failed to calculate micronutrients: {e}")
            micronutrients = {
                "total_micros": {},
                "average_daily_micros": {},
                "rdas": {},
                "deficits": {},
                "has_deficits": False,
            }
        
        plan_output = {
            "plan_type": "week",
            "start_date": start.date().isoformat(),
            "days": weekly_plan,
            "total_macros": total_macros,
            "average_daily_macros": average_daily_macros,
            "micronutrients": micronutrients,
            "validation": validation,
            "variety_score": variety_score,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        if plan_id:
            plan_output["plan_id"] = plan_id

        # IMPORTANT: Two types of meal data storage (aligned with plan_day_e2e_tool):
        # 1. MealPlan + MealPlanItem: stores SUGGESTED plans (weekly plans generated here).
        #    - Saved immediately after generation via sync_plan_to_weaviate (below).
        #    - Used for: plan history, variety filtering, plan retrieval.
        # 2. MealLogEntry: stores ACCEPTED / CONSUMED meals.
        #    - NEVER created from this tool.
        #    - Only created when the user presses the "Accept" button (via accept_plan/log_meal tools).
        #
        # This means plan_week_e2e_tool only persists the suggested week plan (MealPlan/MealPlanItem).
        # It does NOT log anything to MealLogEntry; consumption is recorded later when user accepts.
        if user_id:
            plan_output = sync_plan_to_weaviate(
                plan_output,
                user_id=user_id,
                client_manager=client_manager,
                start_date=plan_output["start_date"],
            )
            yield Response(f"💾 Weekly plan saved (ID: {plan_output.get('plan_id', 'N/A')})")
        else:
            yield Response("ℹ️ Plan stored in memory (create profile to save permanently)")
        
        # Stream response first for immediate feedback
        status_icon = "✅" if validation["valid"] else "⚠️"
        yield Response(
            f"{status_icon} Weekly meal plan ready! "
            f"Total: {total_macros['kcal']:.0f} kcal | "
            f"Daily avg: {average_daily_macros['kcal']:.0f} kcal | "
            f"Variety: {variety_score:.1f}/100"
        )
        
        # Show micronutrient summary
        if micronutrients.get("average_daily_micros"):
            micros_summary = []
            avg_micros = micronutrients.get("average_daily_micros", {})
            rdas = micronutrients.get("rdas", {})
            
            # Show key vitamins and minerals
            key_micros = ["vitamin_c_mg", "vitamin_a_rae_ug", "calcium_mg", "iron_mg", "potassium_mg"]
            for key in key_micros:
                if key in avg_micros:
                    value = avg_micros[key]
                    rda = rdas.get(key, 0)
                    if rda > 0:
                        percent = (value / rda) * 100
                        micros_summary.append(f"{key.replace('_', ' ').title()}: {value:.1f} ({percent:.0f}% RDA)")
            
            if micros_summary:
                yield Response(f"💊 Daily avg micronutrients: {', '.join(micros_summary[:3])}...")
            
            # Show deficits if any
            if micronutrients.get("has_deficits"):
                deficits = micronutrients.get("deficits", {})
                deficit_list = []
                for nutrient, data in list(deficits.items())[:3]:
                    nutrient_name = nutrient.replace("_mg", "").replace("_ug", "").replace("_", " ").title()
                    deficit_list.append(f"{nutrient_name} ({data['deficit_percent']:.0f}% below RDA)")
                if deficit_list:
                    yield Response(f"⚠️ Micronutrient gaps: {', '.join(deficit_list)}")
            else:
                yield Response("✅ All key micronutrients meet RDA requirements!")
        
        # Then yield Result for data consistency
        # Use "meal_plan" payload_type for explicit frontend detection
        yield Result(
            name="plan",
            objects=[plan_output],
            metadata={
                "plan_type": "week",
                "meals_count": 21,
                "days_count": 7,
                "valid": validation["valid"],
                "variety_score": variety_score,
                "macro_violations": len(validation.get("macro_validation", {}).get("violations", [])),
                "constraint_violations": len(validation.get("constraint_validation", {}).get("violations", [])),
                "plan_id": plan_output.get("plan_id"),
                "user_id": user_id,
                "can_accept": True,
                "stop_calling_tool": True,
                "end_conversation": True,
            },
            payload_type="meal_plan",
            display=True,
        )
        _clear_missing_macro_state(tree_data)
    
    except ValueError as e:
        error_msg = f"Invalid input: {str(e)}"
        logging.error(f"plan_week_e2e_tool: {error_msg}", exc_info=True)
        yield Error(error_msg)
        return
    except Exception as e:
        error_msg = f"plan_week_e2e_tool failed: {str(e)}"
        logging.error(f"plan_week_e2e_tool: {error_msg}", exc_info=True)
        yield Error(error_msg)
        return

