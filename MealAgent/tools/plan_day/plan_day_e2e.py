from typing import AsyncGenerator, Dict, Any, List, Optional
import logging
import random
import asyncio
from datetime import datetime, timedelta, timezone

from elysia.tree.objects import TreeData
from elysia.objects import Result, Error, Response
from elysia.util.client import ClientManager
from elysia import tool

from MealAgent.tools.utils.planning_helpers import (
    _get_meal_macros,
    _validate_macro_targets,
    _validate_constraints,
    sync_plan_to_weaviate,
    _calculate_plan_micronutrients,
    ensure_rfc3339_datetime,
    _calculate_meal_targets,
    _calculate_total_deviation_score,
    _try_swap_alternatives,
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
from MealAgent.tools.utils.meal_selection import (
    select_meal_by_strategy,
    calculate_recipe_fit_score,
)
from MealAgent.tools.utils.meal_assembly import (
    add_supplementary_dishes,
    select_accompaniments,
    calculate_meal_macros,
)
from MealAgent.tools.utils.llm_draft import generate_llm_draft
from MealAgent.schemas.llm_draft import LLMDraftResponse
from MealAgent.tools.utils.llm_critic import create_critic_task
from MealAgent.utils.nutrition import build_default_macro_targets
from MealAgent.tools.utils.profile_targets import (
    ensure_macro_targets,
    ensure_profile_loaded,
    resolve_user_id,
)
from MealAgent.tools.utils.weaviate_filters import build_filters_from_where
from MealAgent.tools.utils.recipe_refresh import refresh_recipes, fetch_latest_recipe


def _record_missing_macro_state(tree_data: TreeData, recipe_ids: List[str]) -> None:
    """Persist the list of recipe IDs lacking macros for other tools."""
    try:
        tree_data.environment.add_objects(
            "plan_day_e2e_tool",
            "missing_macros",
            [
                {
                    "recipe_ids": recipe_ids,
                    "timestamp": datetime.now().isoformat(),
                }
            ],
        )
    except Exception:
        logging.debug("plan_day_e2e_tool: failed to record missing macros in environment.")


def _clear_missing_macro_state(tree_data: TreeData) -> None:
    """Publish a resolved signal so the decision agent stops re-running nutrition tools."""
    try:
        tree_data.environment.add_objects(
            "plan_day_e2e_tool",
            "missing_macros",
            [
                {
                    "recipe_ids": [],
                    "status": "resolved",
                    "timestamp": datetime.now().isoformat(),
                }
            ],
        )
    except Exception:
        logging.debug("plan_day_e2e_tool: failed to clear missing macros state.")


def _strip_device_filters(filters_results: list[Dict[str, Any]] | None) -> tuple[Dict[str, Any] | None, Dict[str, Any] | None]:
    """
    Remove any device-based constraints from constraints_guard_tool output so the
    planner does not depend on recipe.devices availability.
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
    for key in ("required_device", "exclude_devices"):
        if key in metadata:
            metadata[key] = None if key == "required_device" else []
    filters_entry["metadata"] = metadata
    return cleaned_where, metadata


# Recipe classification functions moved to MealAgent.tools.utils.recipe_classifiers


def _create_default_white_rice_recipe() -> Dict[str, Any]:
    """
    Create a default white rice recipe for Vietnamese meals.
    This is used when white rice is not found in the database.
    
    Macros per serving (1 chén cơm ~ 150g cooked rice):
    - Kcal: ~220 kcal
    - Protein: ~4.5g
    - Fat: ~0.5g
    - Carb: ~48g
    """
    return {
        "food_id": "default_white_rice",
        "dish_name": "Cơm Trắng",
        "dish_type": "rice",
        "meal_type": "lunch,dinner",
        "category": "rice",
        "servings": 1.0,
        "macros_per_serving": {
            "kcal": 220.0,
            "protein_g": 4.5,
            "fat_g": 0.5,
            "carb_g": 48.0,
        },
        "fiber_g": 0.5,
        "sugar_g": 0.1,
        "sodium_mg": 1.0,
        "description": "Cơm trắng nấu từ gạo tẻ, món cơ bản trong bữa ăn Việt Nam",
        "ingredients": ["Gạo tẻ", "Nước"],
        "cooking_time_min": 30,
        "serving_size": "1 chén",
        "is_default": True,  # Flag to indicate this is a default recipe
        "image_link": "/image/com_trang.jpg",  # Use provided white rice image for UI display
    }


def _is_hotpot(recipe: Dict[str, Any]) -> bool:
    """Detect lẩu/hotpot dishes to avoid for inappropriate meals (e.g., breakfast)."""
    name = str(recipe.get("dish_name", "")).lower()
    rtype = str(recipe.get("dish_type", "")).lower()
    keywords = ["lẩu", "lau", "hotpot", "hot pot"]
    return any(kw in name or kw in rtype for kw in keywords)


# Recipe classification functions moved to MealAgent.tools.utils.recipe_classifiers


# _calculate_recipe_fit_score moved to MealAgent.tools.utils.meal_selection.calculate_recipe_fit_score


def _try_select_from_llm_suggestions(
    llm_draft,
    meal_slot: str,
    role: str,
    recipes: List[Dict[str, Any]],
    excluded: List[Dict[str, Any]],
    recent_recipe_ids_set: set[str],
    min_kcal: float = 0.0,
    max_kcal: Optional[float] = None,
) -> Optional[Dict[str, Any]]:
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
                if str(mapped_recipe.get("food_id", "")) not in recent_recipe_ids_set:
                    # Validate kcal range if specified
                    if max_kcal or min_kcal > 0:
                        macros = mapped_recipe.get("macros_per_serving", {})
                        if isinstance(macros, dict):
                            kcal = macros.get("kcal", 0)
                            if min_kcal <= kcal <= (max_kcal or float('inf')):
                                return mapped_recipe
                    else:
                        return mapped_recipe
    return None


def _select_carb_with_validation(
    llm_draft,
    meal_slot: str,
    recipes: List[Dict[str, Any]],
    excluded: List[Dict[str, Any]],
    recent_recipe_ids_set: set[str],
    selection_strategy: str,
    targets: Optional[Dict[str, float]],
    meal_max_kcal: float,
) -> tuple[Dict[str, Any], bool, bool]:
    """
    Select carb (rice/noodle) for a meal slot with LLM fallback and validation.
    
    Returns: (carb_recipe, is_combined, is_noodle)
    """
    # Prefer a plain white rice candidate up-front if available in search results
    for recipe in recipes:
        if (
            recipe not in excluded
            and str(recipe.get("food_id", "")) not in recent_recipe_ids_set
            and _is_rice_dish(recipe)
            and not _is_main_dish(recipe)
            and not _is_combined_dish(recipe)
        ):
            name_lower = str(recipe.get("dish_name", "")).lower()
            if "cơm trắng" in name_lower or "com trang" in name_lower or "white rice" in name_lower:
                macros = recipe.get("macros_per_serving", {}) or {}
                kcal = macros.get("kcal", 0)
                if 80 <= kcal <= meal_max_kcal:
                    return recipe, False, False

    # Try LLM suggestions first
    carb_recipe = _try_select_from_llm_suggestions(
        llm_draft, meal_slot, "carb",
        recipes, excluded, recent_recipe_ids_set,
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
    if not carb_recipe:
        carb_recipe = select_meal_by_strategy(
            recipes, selection_strategy if targets else "balanced",
            exclude=excluded,
            used_recipe_ids=recent_recipe_ids_set,
            preferred_meal_type=meal_slot,
            dish_category="rice",
            target_macros=targets,
            max_kcal=meal_max_kcal
        )
    
    # Try standalone noodle dishes if still not found
    if not carb_recipe:
        for recipe in recipes:
            if recipe in excluded or str(recipe.get("food_id", "")) in recent_recipe_ids_set:
                continue
            if _is_noodle_soup(recipe) and not _is_combined_dish(recipe):
                macros = recipe.get("macros_per_serving", {})
                if isinstance(macros, dict):
                    kcal = macros.get("kcal", 0)
                    if 100 <= kcal <= meal_max_kcal:
                        carb_recipe = recipe
                        break
    
    # Validate and normalize
    is_combined = carb_recipe and _is_combined_dish(carb_recipe)
    is_noodle = carb_recipe and _is_noodle_soup(carb_recipe) and not is_combined
    
    if not carb_recipe:
        return _create_default_white_rice_recipe(), False, False
    
    # Final validation: must be rice or noodle, not main dish
    if not _is_rice_dish(carb_recipe) and not _is_noodle_soup(carb_recipe):
        logging.warning(f"Selected {meal_slot}_carb is not rice/noodle: {carb_recipe.get('dish_name', 'Unknown')}")
        return _create_default_white_rice_recipe(), False, False
    
    if _is_main_dish(carb_recipe):
        logging.warning(f"Selected {meal_slot}_carb is a main dish: {carb_recipe.get('dish_name', 'Unknown')}")
        return _create_default_white_rice_recipe(), False, False
    
    # If combined rice dish, use default white rice
    if _is_rice_dish(carb_recipe) and is_combined:
        return _create_default_white_rice_recipe(), False, False
    
    return carb_recipe, is_combined, is_noodle


# _add_supplementary_dishes moved to MealAgent.tools.utils.meal_assembly.add_supplementary_dishes


# _select_accompaniments moved to MealAgent.tools.utils.meal_assembly.select_accompaniments


def _map_llm_suggestion_to_recipe(
    suggestion: Dict[str, Any],
    recipes: List[Dict[str, Any]],
    role: str,
) -> Optional[Dict[str, Any]]:
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
        logging.debug(f"_map_llm_suggestion_to_recipe: Empty dish_name in suggestion: {suggestion}")
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
        
        # Role match
        if role == "breakfast" and _is_vietnamese_breakfast(recipe):
            score += 30.0
        elif role == "carb" and (_is_rice_dish(recipe) or _is_noodle_soup(recipe)):
            score += 30.0
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
        
        if (has_exact_match or has_substring_match or 
            (has_keyword_match and best_score >= 50.0) or
            (has_general_term_match and best_score >= 80.0) or
            best_score >= 60.0):
            logging.debug(
                f"_map_llm_suggestion_to_recipe: Matched '{dish_name}' -> '{best_recipe.get('dish_name', 'Unknown')}' "
                f"(score: {best_score:.1f}, role: {role}, exact: {has_exact_match}, "
                f"substring: {has_substring_match}, keyword: {has_keyword_match}, general: {has_general_term_match})"
            )
            return best_recipe
        else:
            logging.debug(
                f"_map_llm_suggestion_to_recipe: No good match for '{dish_name}' "
                f"(best score: {best_score:.1f} - only role/category match, insufficient)"
            )
    
    logging.debug(f"_map_llm_suggestion_to_recipe: No match found for '{dish_name}' (role: {role})")
    return None


# select_meal_by_strategy moved to MealAgent.tools.utils.meal_selection.select_meal_by_strategy


async def _ensure_recipe_macros_cached(
    recipe: Dict[str, Any],
    tree_data: TreeData,
    client_manager: ClientManager,
    base_lm=None,  # Not used anymore, kept for compatibility
) -> Dict[str, float] | None:
    """
    Read recipe macros from Weaviate if not already in memory.
    
    IMPORTANT: This function ONLY reads from Weaviate, does NOT calculate macros.
    Macros should be pre-calculated when recipes are added to the database.
    Only use calculate_recipe_macros_tool explicitly for new recipes.
    """
    recipe_id = recipe.get("food_id") or recipe.get("recipe_id") or recipe.get("id")
    macros = recipe.get("macros_per_serving")
    if isinstance(macros, dict) and macros.get("kcal"):
        return macros
    logging.debug(
        "plan_day_e2e_tool: macros missing in-memory for recipe %s, fetching latest",
        recipe_id,
    )

    food_id = recipe.get("food_id") or recipe.get("fdc_id") or recipe.get("recipe_id") or recipe.get("id")
    if not food_id:
        return macros

    # Read from Weaviate to get latest macros (recipes should already have macros)
    try:
        client = client_manager.get_client()
        fresh_recipe = fetch_latest_recipe(
            str(food_id),
            client,
            collection_name="Recipe",
            candidate_fields=["food_id", "recipe_id", "id"],
        )
        if fresh_recipe:
            fresh_macros = fresh_recipe.get("macros_per_serving")
            if fresh_macros and isinstance(fresh_macros, dict) and fresh_macros.get("kcal"):
                # Update recipe object in memory with fresh data from Weaviate
                recipe["macros_per_serving"] = fresh_macros
                # Also sync other fields that might have been updated
                if "ingredient_fdc_map" in fresh_recipe:
                    recipe["ingredient_fdc_map"] = fresh_recipe["ingredient_fdc_map"]
                # Sync meal typing fields if present
                for key in ("dish_name", "dish_type", "meal_type"):
                    if key in fresh_recipe:
                        recipe[key] = fresh_recipe[key]
                return fresh_macros
            logging.debug(
                "plan_day_e2e_tool: fetched recipe %s but macros still missing",
                food_id,
            )
    except Exception as weaviate_exc:
        logging.debug(
            "plan_day_e2e_tool: Failed to read recipe from Weaviate for %s (%s)",
            food_id,
            weaviate_exc,
        )

    # Return whatever is on the recipe (may be None or empty dict)
    return recipe.get("macros_per_serving")


@tool
async def plan_day_e2e_tool(
    tree_data: TreeData,
    client_manager: ClientManager,
    base_lm=None,
    complex_lm=None,
    query_text: str = "",
    collection_name: str = "Recipe",
    macro_tolerance_percent: float = 0.15,
    user_id: str | None = None,
    plan_id: str | None = None,
    start_date: str | None = None,
    recent_plan_window_minutes: int = 10080,  # 7 days (7 * 24 * 60 = 10080 minutes) - recipes won't repeat within 7 days
    **kwargs,
) -> AsyncGenerator[Result | Response | Error, None]:
    """
    End-to-end **daily planner**: consume ranked recipes and nutritional targets to build a 3-meal plan.

    IMPORTANT: Recipes should have macros pre-calculated in the database.
    This tool only reads macros from Weaviate, it does NOT calculate macros automatically.
    Use `calculate_recipe_macros_tool` explicitly for new recipes that are missing macros.

    Environment contract:
      Reads
        • `macro_calc_tool.targets` – individualized macro goals (TDEE-based).
        • `constraints_guard_tool.filters` (optional) – used only for validation/explanation, not retrieval.
        • `search_and_rank_tool.topk` (optional fallback) – cached recipes, only used if Weaviate search fails.
      Writes
        • `plan_day_e2e_tool.plan`
            - canonical day-plan payload used by the UI and downstream tools.
        • `plan_day_e2e_tool.missing_macros`
            - list of `recipe_ids` that are missing macros (for manual calculation if needed).

    Behaviour:
      • Does **not** own profile CRUD; it expects profile/targets/search results to be present (or will fall back to defaults).
      • **Always searches recipes from Weaviate database** via `search_and_rank_tool()` to ensure latest data.
      • Environment cache (`search_and_rank_tool.topk`) is only used as fallback if database search fails.
      • Reads recipes from Weaviate to get latest macros (recipes should be pre-processed).
      • When `missing_macros` is non-empty, planning still returns a best-effort plan but warns about missing nutrition data.

    Decision hints:
      • Use this tool when the user asks for a **daily meal plan** (e.g. "Gợi ý bữa ăn ngày hôm nay cho tôi"),
        not just a list of recipes.
      • Presence of `plan_day_e2e_tool.plan` with `metadata.valid=True` means planning succeeded.
      • Non-empty `plan_day_e2e_tool.missing_macros` indicates recipes need macro calculation (run `calculate_recipe_macros_tool`).
    """
    logging.info(
        "plan_day_e2e_tool: start query='%s' collection=%s user_id=%s macro_tol=%.2f recent_window_min=%s",
        (query_text or "").strip(),
        collection_name,
        user_id,
        macro_tolerance_percent,
        recent_plan_window_minutes,
    )
    yield Response("🍽️ Planning your daily meals (breakfast, lunch, dinner)...")

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
            complex_lm=complex_lm,
            **kwargs,
        )
        if profile_loaded and profile and resolved_user_id:
            yield Response(f"✅ Profile loaded for user {resolved_user_id}")
        logging.debug(
            "plan_day_e2e_tool: profile_loaded=%s user_id=%s profile_fields=%s",
            profile_loaded,
            resolved_user_id,
            list(profile.keys()) if isinstance(profile, dict) else None,
        )

        # Defer macro target calculation until after we have a candidate recipe list.
        # This aligns the execution flow with:
        #   1) Fetch recipes from Weaviate
        #   2) Then assemble a plan that respects the user's nutritional targets.
        targets: Dict[str, Any] | None = None

        # Step 2: Read constraints filters (for validation)
        filters_results = tree_data.environment.find("constraints_guard_tool", "filters")
        filters_metadata: Dict[str, Any] | None = None
        if filters_results and filters_results[0]["objects"]:
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

        # Prepare constraints for LLM draft
        constraints_dict = {
            "diet_types": filters_metadata.get("diet_types", []) if filters_metadata else [],
            "exclude_allergens": filters_metadata.get("exclude_allergens", []) if filters_metadata else [],
        }
        
        # Get meal history for LLM draft (before recipe search)
        # Track both dish names and recipe IDs for better variety
        meal_history_dish_names: List[str] = []
        meal_history_recipe_ids: set[str] = set()
        try:
            if resolved_user_id:
                client = client_manager.get_client()
                meal_log_collection = client.collections.get("MealLogEntry")
                
                # Get recent meal logs (last 30 days for better variety tracking)
                recent_date = ensure_rfc3339_datetime(
                    datetime.now(timezone.utc) - timedelta(days=30)  # Last 30 days
                )
                meal_filter = build_filters_from_where({
                    "operator": "And",
                    "operands": [
                        {"path": ["user_id"], "operator": "Equal", "valueString": resolved_user_id},
                        {"path": ["logged_at"], "operator": "GreaterThan", "valueDate": recent_date}
                    ]
                })
                
                # Fetch more meal logs to get better history
                meal_logs = meal_log_collection.query.fetch_objects(
                    filters=meal_filter, 
                    limit=100  # Fetch more to ensure we get comprehensive history
                )
                # Sort manually by logged_at descending and take top 50
                if meal_logs.objects:
                    sorted_objects = sorted(
                        list(meal_logs.objects), 
                        key=lambda x: x.properties.get("logged_at", ""), 
                        reverse=True
                    )[:50]
                    # Create a new result with sorted objects
                    from types import SimpleNamespace
                    meal_logs = SimpleNamespace(objects=sorted_objects)
                for log_obj in meal_logs.objects:
                    dish_name = log_obj.properties.get("dish_name")
                    recipe_id = log_obj.properties.get("recipe_id")
                    if dish_name:
                        meal_history_dish_names.append(dish_name)
                    if recipe_id:
                        meal_history_recipe_ids.add(str(recipe_id))
        except Exception as e:
            logging.debug(f"plan_day_e2e_tool: Could not load meal history for LLM draft: {e}")
            # Continue without meal history
        
        # Phase 2.1: LLM Draft Step (BEFORE recipe search, as per flow)
        llm_draft: LLMDraftResponse | None = None
        if base_lm:
            try:
                yield Response("🤖 Generating meal suggestions with AI...")
                user_preferences = (profile or {}).get("preferences", "")
                llm_draft = await generate_llm_draft(
                    base_lm=base_lm,
                    meal_history=meal_history_dish_names,
                    constraints=constraints_dict,
                    user_preferences=user_preferences if user_preferences else None,
                    tree_data=tree_data,
                )
                if llm_draft:
                    yield Response("✅ AI suggestions ready. Mapping to recipes...")
                else:
                    yield Response("ℹ️ Using rule-based selection (AI suggestions unavailable)")
            except Exception as e:
                logging.warning(f"plan_day_e2e_tool: LLM draft failed: {e}")
                llm_draft = None
        else:
            logging.debug("plan_day_e2e_tool: No base_lm available, skipping LLM draft")
        
        # Step 3: Search recipes from Weaviate database
        # IMPORTANT: Always search from Weaviate to get latest data, not from environment cache
        # Environment cache may be stale - Weaviate is the source of truth
        yield Response("🔍 Searching recipes from database...")
        try:
            from MealAgent.tools.search.search_and_rank import search_and_rank_tool
            from MealAgent.tools.constraints.constraints_guard import constraints_guard_tool

            # First, ensure constraints are set up
            constraints_results = tree_data.environment.find("constraints_guard_tool", "filters")
            if not constraints_results or not constraints_results[0]["objects"]:
                # Set up constraints (empty if no profile)
                async for result in constraints_guard_tool(
                    tree_data=tree_data,
                    inputs={},
                    base_lm=base_lm,
                    complex_lm=complex_lm,
                    client_manager=client_manager,
                    **kwargs,
                ):
                    if isinstance(result, Error):
                        error_msg = str(result) if hasattr(result, '__str__') else "Unknown error"
                        logging.warning(
                            "plan_day_e2e_tool: constraints_guard_tool failed: %s",
                            error_msg,
                        )
                        break

            # Search recipes from Weaviate database
            # This ensures we always get the latest recipes with up-to-date macros
            search_query = query_text if query_text else "Vietnamese recipes"
            recipes: list[Dict[str, Any]] = []
            
            async for result in search_and_rank_tool(
                tree_data=tree_data,
                inputs={},
                base_lm=base_lm,
                complex_lm=complex_lm,
                client_manager=client_manager,
                query_text=search_query,
                collection_name=collection_name,
                limit=1000,  # Maximum allowed by search_and_rank_tool (increased from 100 to 1000 for maximum variety)
                top_k=1000,  # Top 1000 for planning (increased from 50 to 1000, max allowed by Weaviate)
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
                logging.debug("plan_day_e2e_tool: No recipes from Weaviate search, trying environment cache...")
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
                "plan_day_e2e_tool: recipes from Weaviate search count=%d query='%s'",
                len(recipes),
                query_text,
            )
        except Exception as e:  # pragma: no cover - defensive
            logging.error("plan_day_e2e_tool: Failed to search recipes from Weaviate: %s", e)
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

        # At this point, `recipes` must be non-empty
        
        # IMPROVED VARIETY: Shuffle recipes and exclude recent plans to ensure better variety
        # Shuffle recipes multiple times for better randomization
        for _ in range(3):  # Shuffle 3 times for better randomization
            random.shuffle(recipes)
        
        # Check for recent plans and exclude their recipes (configurable minutes, default 10 minutes for testing)
        recent_recipe_ids = set()
        try:
            client = client_manager.get_client()
            plan_collection = client.collections.get("MealPlan")
            item_collection = client.collections.get("MealPlanItem")
            recent_recipe_names: set[str] = set()
            
            # Get recent plans within configured window (days) for this user
            # Use 7 days to ensure better variety and avoid repetition
            if user_id:
                # Use 7 days window for better variety (instead of minutes)
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
                            items = item_collection.query.fetch_objects(filters=item_filter, limit=50)
                            for item_obj in items.objects:
                                recipe_id = item_obj.properties.get("recipe_id")
                                if recipe_id:
                                    recent_recipe_ids.add(str(recipe_id))
                                dish_name = item_obj.properties.get("dish_name")
                                if dish_name:
                                    recent_recipe_names.add(str(dish_name).lower().strip())
                    
                    # Also add meal history recipe IDs to exclusion
                    if 'meal_history_recipe_ids' in locals():
                        recent_recipe_ids.update(meal_history_recipe_ids)
                    # And add meal history names to name-based exclusion
                    if 'meal_history_dish_names' in locals():
                        recent_recipe_names.update(
                            str(name).lower().strip() for name in meal_history_dish_names if name
                        )
                    
                    # Filter out recently used recipes (but keep at least 30 recipes for better variety)
                    # This ensures we have enough candidates even after exclusion
                    if recent_recipe_ids and len(recipes) > 30:
                        original_count = len(recipes)
                        recipes = [r for r in recipes if str(r.get("food_id", "")) not in recent_recipe_ids]
                        # Shuffle again after filtering
                        random.shuffle(recipes)
                        if original_count > len(recipes):
                            yield Response(
                                f"🔄 Excluded {original_count - len(recipes)} recently used recipe(s) "
                                f"to ensure variety in your meal plan"
                            )
                    elif recent_recipe_ids and len(recipes) <= 30:
                        # If we have few recipes, still exclude but warn
                        original_count = len(recipes)
                        recipes = [r for r in recipes if str(r.get("food_id", "")) not in recent_recipe_ids]
                        random.shuffle(recipes)
                        if len(recipes) < 10:
                            yield Response(
                                f"⚠️ Limited recipe variety: only {len(recipes)} unique recipes available "
                                f"after excluding {original_count - len(recipes)} recently used ones"
                            )
                    
                    # Additional safeguard: exclude by dish name from recent plans + meal history
                    if recent_recipe_names:
                        name_blocklist = {name for name in recent_recipe_names if name}
                        if name_blocklist and len(recipes) > 30:
                            original_count = len(recipes)
                            recipes = [r for r in recipes if str(r.get("dish_name", "")).lower().strip() not in name_blocklist]
                            random.shuffle(recipes)
                            if original_count > len(recipes):
                                yield Response(
                                    f"🔄 Excluded {original_count - len(recipes)} recently eaten dish(es) (name match) "
                                    f"to avoid repetition"
                                )
                        elif name_blocklist and len(recipes) <= 30:
                            original_count = len(recipes)
                            recipes = [r for r in recipes if str(r.get("dish_name", "")).lower().strip() not in name_blocklist]
                            random.shuffle(recipes)
                            if len(recipes) < 10:
                                yield Response(
                                    f"⚠️ Limited variety after excluding recently eaten dishes by name; "
                                    f"only {len(recipes)} recipes remain"
                                )
        except Exception as e:
            logging.debug(f"plan_day_e2e_tool: Could not check recent plans for variety: {e}")
            # Continue with all recipes if check fails

        if len(recipes) < 3:
            yield Error(
                "Not enough recipes found to create a daily plan. "
                "Need at least 3 recipes. Please try a broader search query or relax your constraints."
            )
            return

        # Refresh recipes from Weaviate to ensure we have latest macros
        # Recipes should already have macros pre-calculated in the database
        def _count_missing_macros(items: list[Dict[str, Any]]) -> int:
            return sum(
                1
                for r in items
                if not r.get("macros_per_serving")
                or not isinstance(r.get("macros_per_serving"), dict)
                or not r.get("macros_per_serving", {}).get("kcal")
            )

        missing_before_refresh = _count_missing_macros(recipes)
        try:
            client = client_manager.get_client()
            recipes = refresh_recipes(recipes, client, collection_name="Recipe", hydrate_fields=True)
            missing_after_refresh = _count_missing_macros(recipes)
            missing_ids = [
                str(r.get("food_id") or r.get("recipe_id") or r.get("id"))
                for r in recipes
                if not r.get("macros_per_serving")
                or not isinstance(r.get("macros_per_serving"), dict)
                or not r.get("macros_per_serving", {}).get("kcal")
            ][:5]
            logging.debug(
                "plan_day_e2e_tool: refreshed %d recipes (missing macros before=%d, after=%d, sample_missing=%s)",
                len(recipes),
                missing_before_refresh,
                missing_after_refresh,
                missing_ids or "none",
            )
            logging.debug(
                "plan_day_e2e_tool: recipe sample after refresh %s",
                [
                    (
                        str(r.get("food_id") or r.get("recipe_id") or r.get("id")),
                        (r.get("macros_per_serving") or {}).get("kcal"),
                    )
                    for r in recipes[:5]
                ],
            )
        except Exception as refresh_exc:
            logging.debug(f"Failed to refresh recipes from Weaviate: {refresh_exc}")
            # Continue with existing recipes if refresh fails
        
        # Check for missing macros (should be rare if recipes are pre-processed)
        missing_macros = [
            r for r in recipes
            if not r.get("macros_per_serving") or not isinstance(r.get("macros_per_serving"), dict)
            or not r.get("macros_per_serving", {}).get("kcal")
        ]
        
        if missing_macros:
            missing_ids = [str(r.get("food_id")) for r in missing_macros[:5] if r.get("food_id")]
            _record_missing_macro_state(tree_data, missing_ids)
            yield Response(
                f"⚠️ {len(missing_macros)} recipe(s) missing nutrition data. "
                f"Run calculate_recipe_macros_tool for these recipes if needed. "
                f"Continuing with available recipes..."
            )
        
        # Final check: Ensure we have at least some recipes with macros for planning
        recipes_with_macros = [
            r for r in recipes
            if r.get("macros_per_serving") and isinstance(r.get("macros_per_serving"), dict)
            and r.get("macros_per_serving", {}).get("kcal")
        ]
        
        if len(recipes_with_macros) < 3:
            yield Response(
                f"⚠️ Only {len(recipes_with_macros)} recipe(s) have complete nutrition data. "
                f"Please ensure recipes have macros calculated before planning."
            )

        # At this point we have candidate recipes. Now ensure nutritional targets are ready,
        # so the actual plan assembly uses the latest UserProfile-based macros.
        targets, targets_refreshed = await ensure_macro_targets(
            tree_data=tree_data,
            client_manager=client_manager,
            user_id=resolved_user_id,
            base_lm=base_lm,
            complex_lm=complex_lm,
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

        # Step 4: Assemble plan (Vietnamese meal pattern) with LLM-guided selection
        yield Response("🔍 Selecting meals following Vietnamese meal patterns and your nutritional targets...")
        
        # Use the recent_recipe_ids set already collected above (or empty set if not collected)
        # Also include meal history recipe IDs for better variety
        recent_recipe_ids_set = recent_recipe_ids if 'recent_recipe_ids' in locals() else set()
        if 'meal_history_recipe_ids' in locals():
            recent_recipe_ids_set.update(meal_history_recipe_ids)
        
        # Use macro_fit strategy if targets available for better quality
        selection_strategy = "macro_fit" if targets else "balanced"
        
        # Calculate max_kcal per meal to avoid selecting dishes that are too high
        # Breakfast: ~25% of daily target, max 550 kcal (strict limit)
        # Lunch: ~30% of daily target, max 700 kcal (lighter than dinner)
        # Dinner: ~40% of daily target, max 950 kcal (heavier than lunch - Vietnamese pattern)
        if targets:
            breakfast_max_kcal = min(550.0, targets.get("tdee_kcal", 2000) * 0.25)
            lunch_max_kcal = min(700.0, targets.get("tdee_kcal", 2000) * 0.30)  # Lighter
            dinner_max_kcal = min(950.0, targets.get("tdee_kcal", 2000) * 0.40)  # Heavier
        else:
            breakfast_max_kcal = 550.0
            lunch_max_kcal = 700.0
            dinner_max_kcal = 950.0
        
        # For backward compatibility, keep meal_max_kcal for lunch (will use lunch_max_kcal for lunch, dinner_max_kcal for dinner)
        meal_max_kcal = lunch_max_kcal  # Default for lunch
        
        # Track remaining targets after each meal for better selection
        remaining_targets = {
            "kcal": targets.get("tdee_kcal", 2000.0) if targets else 2000.0,
            "protein_g": targets.get("protein_g", 150.0) if targets else 150.0,
            "fat_g": targets.get("fat_g", 65.0) if targets else 65.0,
            "carb_g": targets.get("carb_g", 200.0) if targets else 200.0,
        } if targets else None
        
        # If LLM draft is available, use it to guide selection
        # Otherwise, fall back to rule-based selection
        breakfast = None
        if llm_draft and llm_draft.breakfast and llm_draft.breakfast.suggestions:
            # Try to map LLM suggestions to recipes
            for suggestion in llm_draft.breakfast.suggestions:
                mapped_recipe = _map_llm_suggestion_to_recipe(
                    suggestion.model_dump() if hasattr(suggestion, 'model_dump') else suggestion,
                    recipes,
                    "breakfast"
                )
                if mapped_recipe and str(mapped_recipe.get("food_id", "")) not in recent_recipe_ids_set:
                    if _is_hotpot(mapped_recipe):
                        logging.warning(
                            "BREAKFAST_REJECT_HOTPOT: Skipping hotpot for breakfast suggestion: %s",
                            mapped_recipe.get("dish_name"),
                        )
                        continue
                    breakfast = mapped_recipe
                    yield Response(f"✅ Selected breakfast from AI suggestion: {breakfast.get('dish_name', 'Unknown')}")
                    break
        
        # Fallback to rule-based selection if LLM mapping failed
        if not breakfast:
            # Prepare targets with remaining_targets for better selection
            breakfast_targets = targets.copy() if targets else None
            if breakfast_targets and remaining_targets:
                breakfast_targets["_remaining_targets"] = remaining_targets.copy()
            
            # CRITICAL: Always prioritize protein for breakfast when starting (remaining_targets is full)
            # Breakfast should contribute significantly to daily protein (at least 25-30g for high protein targets)
            breakfast_strategy = "highest_protein"  # Default to protein priority
            # CRITICAL: Increase base requirement to ensure adequate protein
            daily_protein = breakfast_targets.get("protein_g", 150.0) if breakfast_targets else 150.0
            # Base requirement: at least 20% of daily protein for breakfast (for 192g target = ~38g, but breakfast typically lighter)
            # For high protein targets (>150g), require at least 25g; for lower targets, require 20g
            if daily_protein > 180:
                min_breakfast_protein = 25.0  # High protein target - require more
            elif daily_protein > 150:
                min_breakfast_protein = 22.0  # Medium-high protein target
            else:
                min_breakfast_protein = 20.0  # Standard protein target
            
            if breakfast_targets and remaining_targets:
                protein_remaining = remaining_targets.get("protein_g", 0.0)
                protein_ratio = protein_remaining / daily_protein if daily_protein > 0 else 1.0
                
                # If we still need >50% of daily protein, require even more protein in breakfast
                if protein_ratio > 0.5:
                    min_breakfast_protein = max(min_breakfast_protein, 30.0)  # Require 30g+ protein when protein is critically needed
                elif protein_ratio > 0.3:
                    min_breakfast_protein = max(min_breakfast_protein, 25.0)  # Require 25g protein
                # If protein needs are lower, still prioritize protein but with lower requirement
                elif protein_ratio < 0.2:
                    breakfast_strategy = "balanced"  # Use balanced when protein needs are low
                    min_breakfast_protein = max(min_breakfast_protein, 18.0)  # Still require at least 18g
            
            breakfast = select_meal_by_strategy(
                recipes, breakfast_strategy, 
                used_recipe_ids=recent_recipe_ids_set,
                preferred_meal_type="breakfast",
                dish_category="breakfast",
                target_macros=breakfast_targets,
                require_macros=True,
                min_kcal=100.0,
                max_kcal=breakfast_max_kcal,  # CRITICAL: Enforce kcal limit
                min_protein=min_breakfast_protein,  # CRITICAL: Require minimum protein
            )
            if breakfast and _is_hotpot(breakfast):
                logging.warning("BREAKFAST_REJECT_HOTPOT: Rule-based breakfast is hotpot, retrying fallback...")
                breakfast = None
        if not breakfast:
            # Fallback: try any breakfast-type dish (still with kcal limit and protein requirement)
            breakfast_targets = targets.copy() if targets else None
            if breakfast_targets and remaining_targets:
                breakfast_targets["_remaining_targets"] = remaining_targets.copy()
            
            # Still prioritize protein for fallback, but with lower threshold
            breakfast_strategy = "highest_protein"
            daily_protein = breakfast_targets.get("protein_g", 150.0) if breakfast_targets else 150.0
            if daily_protein > 180:
                min_breakfast_protein = 20.0  # Lower but still significant for high protein targets
            elif daily_protein > 150:
                min_breakfast_protein = 18.0
            else:
                min_breakfast_protein = 15.0
            
            if breakfast_targets and remaining_targets:
                protein_remaining = remaining_targets.get("protein_g", 0.0)
                protein_ratio = protein_remaining / daily_protein if daily_protein > 0 else 1.0
                if protein_ratio > 0.5:
                    min_breakfast_protein = max(min_breakfast_protein, 25.0)
                elif protein_ratio > 0.3:
                    min_breakfast_protein = max(min_breakfast_protein, 20.0)
            
            breakfast = select_meal_by_strategy(
                recipes, breakfast_strategy, 
                used_recipe_ids=recent_recipe_ids_set,
                preferred_meal_type="breakfast",
                dish_category="breakfast",  # CRITICAL: Ensure only breakfast dishes are selected
                target_macros=breakfast_targets,
                require_macros=True,
                min_kcal=100.0,
                max_kcal=breakfast_max_kcal,  # CRITICAL: Enforce kcal limit
                min_protein=min_breakfast_protein,  # CRITICAL: Still require minimum protein
            )
            if breakfast and _is_hotpot(breakfast):
                logging.warning("BREAKFAST_REJECT_HOTPOT: Fallback breakfast is hotpot, clearing...")
                breakfast = None
        if not breakfast:
            yield Response("⚠️ No breakfast dish found. Selecting best available Vietnamese breakfast option...")
            # CRITICAL: Only select Vietnamese breakfast dishes, not main dishes
            best_breakfast = None
            best_protein = 0.0
            for recipe in recipes:
                if str(recipe.get("food_id", "")) not in recent_recipe_ids_set:
                    # CRITICAL: Must be Vietnamese breakfast dish
                    if not _is_vietnamese_breakfast(recipe):
                        continue
                    if _is_hotpot(recipe):
                        continue
                    macros = recipe.get("macros_per_serving", {})
                    if isinstance(macros, dict):
                        kcal = macros.get("kcal", 0)
                        protein = macros.get("protein_g", 0)
                        if 100 <= kcal <= breakfast_max_kcal and protein > best_protein:
                            best_breakfast = recipe
                            best_protein = protein
            if best_breakfast:
                breakfast = best_breakfast
            elif recipes:
                # Last resort: find highest protein Vietnamese breakfast regardless of kcal
                for recipe in recipes:
                    if str(recipe.get("food_id", "")) not in recent_recipe_ids_set:
                        # CRITICAL: Must be Vietnamese breakfast dish
                        if not _is_vietnamese_breakfast(recipe):
                            continue
                        macros = recipe.get("macros_per_serving", {})
                        if isinstance(macros, dict):
                            protein = macros.get("protein_g", 0)
                            if protein > best_protein:
                                best_breakfast = recipe
                                best_protein = protein
                if best_breakfast:
                    breakfast = best_breakfast
                else:
                    # Final fallback: find any Vietnamese breakfast dish
                    for recipe in recipes:
                        if str(recipe.get("food_id", "")) not in recent_recipe_ids_set:
                            if _is_vietnamese_breakfast(recipe):
                                breakfast = recipe
                                break
            if not breakfast:
                yield Response("❌ No Vietnamese breakfast dishes available. Please search for breakfast recipes first.")
                return
        
        # CRITICAL: Final validation - ensure breakfast is actually a Vietnamese breakfast dish
        if not _is_vietnamese_breakfast(breakfast):
            logging.warning(f"BREAKFAST_VALIDATION_FAILED: Selected breakfast '{breakfast.get('dish_name', 'Unknown')}' is not a Vietnamese breakfast dish. Searching for valid breakfast...")
            # Find any valid Vietnamese breakfast dish
            valid_breakfast = None
            for recipe in recipes:
                if str(recipe.get("food_id", "")) not in recent_recipe_ids_set:
                    if _is_vietnamese_breakfast(recipe):
                        macros = recipe.get("macros_per_serving", {})
                        if isinstance(macros, dict):
                            kcal = macros.get("kcal", 0)
                            if 100 <= kcal <= breakfast_max_kcal:
                                valid_breakfast = recipe
                                break
            if valid_breakfast:
                breakfast = valid_breakfast
                logging.info(f"BREAKFAST_REPLACED: Replaced with valid breakfast '{breakfast.get('dish_name', 'Unknown')}'")
            else:
                yield Response("❌ No valid Vietnamese breakfast dishes found. Please ensure breakfast recipes are available.")
                return
        
        # CRITICAL: Validate breakfast kcal and protein after selection
        breakfast_macros = _get_meal_macros(breakfast)
        breakfast_kcal = breakfast_macros.get("kcal", 0)
        breakfast_protein = breakfast_macros.get("protein_g", 0)
        breakfast_fat = breakfast_macros.get("fat_g", 0)
        daily_protein = targets.get("protein_g", 150.0) if targets else 150.0
        
        # Calculate minimum acceptable protein for breakfast
        if daily_protein > 180:
            min_acceptable_protein = 20.0
        elif daily_protein > 150:
            min_acceptable_protein = 18.0
        else:
            min_acceptable_protein = 15.0
        
        # If breakfast protein is too low, try to find a better option
        if breakfast_protein < min_acceptable_protein:
            logging.warning(f"Breakfast protein ({breakfast_protein:.1f}g) is below minimum ({min_acceptable_protein:.1f}g), trying to find better option...")
            best_breakfast = None
            best_protein = breakfast_protein
            for recipe in recipes:
                if recipe == breakfast:
                    continue
                if str(recipe.get("food_id", "")) not in recent_recipe_ids_set:
                    macros = recipe.get("macros_per_serving", {})
                    if isinstance(macros, dict):
                        kcal = macros.get("kcal", 0)
                        protein = macros.get("protein_g", 0)
                        if (100 <= kcal <= breakfast_max_kcal and 
                            protein > best_protein and 
                            _is_vietnamese_breakfast(recipe)):
                            best_breakfast = recipe
                            best_protein = protein
            if best_breakfast and best_protein >= min_acceptable_protein:
                breakfast = best_breakfast
                breakfast_macros = _get_meal_macros(breakfast)
                breakfast_kcal = breakfast_macros.get("kcal", 0)
                breakfast_protein = breakfast_macros.get("protein_g", 0)
                logging.info(f"Replaced breakfast with higher protein option: {breakfast.get('dish_name', 'Unknown')} ({breakfast_protein:.1f}g protein)")
        
        if breakfast_kcal > breakfast_max_kcal * 1.1 or breakfast_fat > 25.0:  # tighter cap
            logging.warning(
                "Breakfast over cap (kcal=%.1f>%.1f or fat=%.1f>25). Trying to find better option...",
                breakfast_kcal,
                breakfast_max_kcal,
                breakfast_fat,
            )
            # Try to find a better breakfast option that balances kcal and protein
            best_breakfast = None
            best_score = 0.0
            for recipe in recipes:
                if recipe == breakfast:
                    continue
                if str(recipe.get("food_id", "")) not in recent_recipe_ids_set:
                    macros = recipe.get("macros_per_serving", {})
                    if isinstance(macros, dict):
                        kcal = macros.get("kcal", 0)
                        protein = macros.get("protein_g", 0)
                        fat = macros.get("fat_g", 0)
                        if (100 <= kcal <= breakfast_max_kcal and
                            fat <= 25.0 and
                            _is_vietnamese_breakfast(recipe) and
                            protein >= min_acceptable_protein):
                            # Score: prioritize protein, but also consider kcal
                            score = protein * 2.0 - (kcal / 10.0) - (fat * 0.5)
                            if score > best_score:
                                best_breakfast = recipe
                                best_score = score
            if best_breakfast:
                breakfast = best_breakfast
                breakfast_macros = _get_meal_macros(breakfast)
                breakfast_kcal = breakfast_macros.get("kcal", 0)
                breakfast_fat = breakfast_macros.get("fat_g", 0)
                logging.info(f"Replaced breakfast with better balanced option: {breakfast.get('dish_name', 'Unknown')}")
        # Hard fallback to light breakfast if still over cap
        if breakfast_kcal > breakfast_max_kcal * 1.1 or breakfast_fat > 25.0:
            for recipe in recipes:
                if _is_vietnamese_breakfast(recipe):
                    macros = _get_meal_macros(recipe)
                    if macros.get("kcal", 0) <= breakfast_max_kcal and macros.get("fat_g", 0) <= 25.0:
                        breakfast = recipe
                        breakfast_macros = macros
                        breakfast_kcal = macros.get("kcal", 0)
                        breakfast_fat = macros.get("fat_g", 0)
                        breakfast_protein = macros.get("protein_g", 0)
                        logging.warning("Fallback: forced lower-calorie breakfast to meet caps.")
                        break
        
        # Update remaining targets after breakfast
        if remaining_targets and breakfast:
            breakfast_macros = _get_meal_macros(breakfast)
            breakfast_name = breakfast.get("dish_name", "Unknown")
            logging.debug(
                f"BREAKFAST: {breakfast_name} | "
                f"kcal={breakfast_macros.get('kcal', 0):.1f} | "
                f"protein={breakfast_macros.get('protein_g', 0):.1f}g | "
                f"fat={breakfast_macros.get('fat_g', 0):.1f}g | "
                f"carb={breakfast_macros.get('carb_g', 0):.1f}g"
            )
            
            # Log remaining targets BEFORE update
        # Removed verbose logging - only log when there's an issue
            
            # CRITICAL: Cap remaining targets to prevent negative values and ensure reasonable distribution
            remaining_targets["kcal"] = max(0.0, remaining_targets["kcal"] - breakfast_macros.get("kcal", 0.0))
            remaining_targets["protein_g"] = max(0.0, remaining_targets["protein_g"] - breakfast_macros.get("protein_g", 0.0))
            remaining_targets["fat_g"] = max(0.0, remaining_targets["fat_g"] - breakfast_macros.get("fat_g", 0.0))
            remaining_targets["carb_g"] = max(0.0, remaining_targets["carb_g"] - breakfast_macros.get("carb_g", 0.0))
            
            # Log remaining targets AFTER update
        # Removed verbose logging - only log when there's an issue
            
            # CRITICAL: Don't artificially adjust remaining targets - use actual remaining values
            # Only ensure it doesn't go negative
            if remaining_targets["kcal"] < 0:
                logging.warning(f"Remaining kcal after breakfast is negative ({remaining_targets['kcal']:.1f}), setting to 0")
                remaining_targets["kcal"] = 0.0
        
        # CRITICAL: Initialize supplementary dishes lists BEFORE they are used
        # These will store unassigned supplementary dishes to add to plan later
        lunch_supplementary_dishes = []  # Will store all supplementary dishes for lunch
        dinner_supplementary_dishes = []  # Will store all supplementary dishes for dinner
        
        # Lunch: Vietnamese lunch pattern - use helper functions
        excluded = [breakfast]
        
        # Prepare targets with remaining_targets for lunch selection
        lunch_targets = targets.copy() if targets else None
        if lunch_targets and remaining_targets:
            lunch_targets["_remaining_targets"] = remaining_targets.copy()
        
        # Select lunch carb with validation (use lunch_max_kcal for lighter lunch)
        lunch_carb, is_lunch_combined, is_lunch_noodle = _select_carb_with_validation(
            llm_draft, "lunch",
            recipes, excluded, recent_recipe_ids_set,
            selection_strategy, lunch_targets, lunch_max_kcal
        )
        
        if lunch_carb:
            carb_name = lunch_carb.get('dish_name', 'Unknown')
            if lunch_carb.get("food_id") != "default_white_rice":
                yield Response(f"✅ Selected lunch carb from AI suggestion: {carb_name}")
            else:
                yield Response("ℹ️ No suitable lunch dish found. Using default white rice.")
        
        lunch_rice = lunch_carb
        
        # Select accompaniments
        if lunch_rice:
            excluded.append(lunch_rice)
            
            if is_lunch_combined or is_lunch_noodle:
                if is_lunch_combined:
                    yield Response("ℹ️ Selected combined dish for lunch (contains both carbs and protein). Adding fruit only.")
                else:
                    yield Response("ℹ️ Selected noodle dish for lunch (standalone meal). Adding fruit only.")
            
            lunch_main, lunch_soup, lunch_veg, lunch_fruit = select_accompaniments(
                "lunch", is_lunch_combined, is_lunch_noodle,
                recipes, excluded, recent_recipe_ids_set,
                selection_strategy, lunch_targets,
                llm_draft=llm_draft,
                try_select_from_llm_suggestions=_try_select_from_llm_suggestions,
            )
            
            # CRITICAL: DO NOT update remaining_targets here - wait until AFTER supplementary dishes are added
            # This will be done after supplementary dishes are processed
            
            # CRITICAL: Validate lunch main is actually a main dish
            if lunch_main and not _is_main_dish(lunch_main):
                logging.warning(f"Lunch main '{lunch_main.get('dish_name', 'Unknown')}' is not a main dish, rejecting...")
                lunch_main = None
            
            # CRITICAL: Validate lunch vegetable is actually a vegetable dish (not a main dish)
            if lunch_veg:
                if not _is_vegetable_dish(lunch_veg):
                    logging.warning(f"Lunch vegetable '{lunch_veg.get('dish_name', 'Unknown')}' is not a vegetable dish, rejecting...")
                    lunch_veg = None
                elif _is_main_dish(lunch_veg):
                    logging.warning(f"Lunch vegetable '{lunch_veg.get('dish_name', 'Unknown')}' is actually a main dish, rejecting...")
                    lunch_veg = None
            
            # CRITICAL: Ensure no duplicate dishes in lunch
            lunch_dishes = [breakfast, lunch_rice, lunch_main, lunch_soup, lunch_veg, lunch_fruit]
            lunch_ids = {str(d.get("food_id", "")) for d in lunch_dishes if d and d.get("food_id")}
            if len(lunch_ids) < len([d for d in lunch_dishes if d]):
                logging.warning("Duplicate dishes detected in lunch, removing duplicates...")
                if lunch_main and str(lunch_main.get("food_id", "")) in [str(d.get("food_id", "")) for d in [breakfast, lunch_rice] if d]:
                    logging.warning(f"Removing duplicate lunch main: {lunch_main.get('dish_name', 'Unknown')}")
                    lunch_main = None
                if lunch_veg and str(lunch_veg.get("food_id", "")) in [str(d.get("food_id", "")) for d in [breakfast, lunch_rice, lunch_main] if d]:
                    logging.warning(f"Removing duplicate lunch vegetable: {lunch_veg.get('dish_name', 'Unknown')}")
                    lunch_veg = None
                if lunch_soup and str(lunch_soup.get("food_id", "")) in [str(d.get("food_id", "")) for d in [breakfast, lunch_rice, lunch_main, lunch_veg] if d]:
                    logging.warning(f"Removing duplicate lunch soup: {lunch_soup.get('dish_name', 'Unknown')}")
                    lunch_soup = None
                if lunch_fruit and str(lunch_fruit.get("food_id", "")) in [str(d.get("food_id", "")) for d in [breakfast, lunch_rice, lunch_main, lunch_veg, lunch_soup] if d]:
                    logging.warning(f"Removing duplicate lunch fruit: {lunch_fruit.get('dish_name', 'Unknown')}")
                    lunch_fruit = None
            
            # User feedback for LLM selections
            if lunch_main and _try_select_from_llm_suggestions(llm_draft, "lunch", "main", recipes, [], recent_recipe_ids_set, 50.0, 500.0):
                yield Response(f"✅ Selected lunch main from AI suggestion: {lunch_main.get('dish_name', 'Unknown')}")
            if lunch_veg and _try_select_from_llm_suggestions(llm_draft, "lunch", "vegetable", recipes, [], recent_recipe_ids_set, 30.0):
                yield Response(f"✅ Selected lunch vegetable from AI suggestion: {lunch_veg.get('dish_name', 'Unknown')}")
            if lunch_fruit and _try_select_from_llm_suggestions(llm_draft, "lunch", "fruit", recipes, [], recent_recipe_ids_set, 30.0):
                yield Response(f"✅ Selected lunch fruit from AI suggestion: {lunch_fruit.get('dish_name', 'Unknown')}")
            
            # CRITICAL: Add supplementary dishes if still deficient in nutrition
            # IMPORTANT: Also add for noodle dishes if nutrition is still deficient
            if remaining_targets and targets:
                current_lunch_dishes = [d for d in [lunch_rice, lunch_main, lunch_soup, lunch_veg, lunch_fruit] if d]
                # For noodle/combined dishes, allow adding more dishes if nutrition is still deficient
                # Use iterative approach to keep adding until nutrition targets are met
                max_iterations = 5  # Increased from 3 to 5 to allow more dishes to be added
                iteration = 0
                all_supplementary_dishes = []
                
                while iteration < max_iterations:
                    # CRITICAL: Calculate what we ACTUALLY need based on original targets, not just remaining_targets
                    # This ensures we don't stop too early if remaining_targets was incorrectly calculated
                    breakfast_macros = _get_meal_macros(breakfast) if breakfast else {"kcal": 0.0, "protein_g": 0.0, "fat_g": 0.0, "carb_g": 0.0}
                    current_lunch_macros = calculate_meal_macros(current_lunch_dishes)
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
                    
                    # Use the MAXIMUM of actual_needed and remaining_targets to ensure we don't stop too early
                    protein_needed = max(protein_needed_from_remaining, actual_protein_needed)
                    kcal_needed = max(kcal_needed_from_remaining, actual_kcal_needed)
                    
                    # CRITICAL: Update remaining_targets to reflect actual needs if it's incorrect
                    if actual_protein_needed > protein_needed_from_remaining or actual_kcal_needed > kcal_needed_from_remaining:
                        logging.warning(
                            f"LUNCH_SUPP_CORRECTION: remaining_targets was incorrect! "
                            f"actual_protein_needed={actual_protein_needed:.1f}g vs remaining={protein_needed_from_remaining:.1f}g | "
                            f"actual_kcal_needed={actual_kcal_needed:.1f} vs remaining={kcal_needed_from_remaining:.1f} | "
                            f"Updating remaining_targets to reflect actual needs"
                        )
                        remaining_targets["protein_g"] = actual_protein_needed
                        remaining_targets["kcal"] = actual_kcal_needed
                    
                    # Calculate deficit ratios
                    protein_deficit_ratio = protein_needed / daily_protein if daily_protein > 0 else 0.0
                    kcal_deficit_ratio = kcal_needed / daily_kcal if daily_kcal > 0 else 0.0
                    
                    # CRITICAL: Calculate fat/carb excess based on total consumed
                    daily_fat = targets.get("fat_g", 60.0)
                    daily_carb = targets.get("carb_g", 219.0)
                    total_consumed_fat = breakfast_macros.get("fat_g", 0.0) + current_lunch_macros.get("fat_g", 0.0)
                    total_consumed_carb = breakfast_macros.get("carb_g", 0.0) + current_lunch_macros.get("carb_g", 0.0)
                    fat_excess_ratio = (total_consumed_fat - daily_fat) / daily_fat if daily_fat > 0 and total_consumed_fat > daily_fat else 0.0
                    carb_excess_ratio = (total_consumed_carb - daily_carb) / daily_carb if daily_carb > 0 and total_consumed_carb > daily_carb else 0.0
                    kcal_excess_ratio = (total_consumed_kcal - daily_kcal) / daily_kcal if daily_kcal > 0 and total_consumed_kcal > daily_kcal else 0.0
                    has_severe_fat_excess = fat_excess_ratio > 0.15  # Balanced: 15% to prevent over-eating but allow nutrition
                    has_severe_carb_excess = carb_excess_ratio > 0.15  # Balanced: 15%
                    has_severe_kcal_excess = kcal_excess_ratio > 0.15  # Balanced: 15%
                    
                    logging.debug(
                        f"LUNCH_SUPP_ITERATION_{iteration + 1}: "
                        f"protein_needed={protein_needed:.1f}g ({protein_deficit_ratio*100:.1f}% of daily) | "
                        f"kcal_needed={kcal_needed:.1f} ({kcal_deficit_ratio*100:.1f}% of daily) | "
                        f"fat_excess={fat_excess_ratio*100:.1f}% | carb_excess={carb_excess_ratio*100:.1f}% | "
                        f"kcal_excess={kcal_excess_ratio*100:.1f}% | "
                        f"current_dishes_count={len(current_lunch_dishes)} | "
                        f"current_lunch_kcal={current_lunch_macros.get('kcal', 0):.1f} | "
                        f"current_lunch_protein={current_lunch_macros.get('protein_g', 0):.1f}g | "
                        f"total_consumed_kcal={total_consumed_kcal:.1f} | "
                        f"total_consumed_protein={total_consumed_protein:.1f}g | "
                        f"total_consumed_fat={total_consumed_fat:.1f}g | "
                        f"total_consumed_carb={total_consumed_carb:.1f}g | "
                        f"actual_protein_needed={actual_protein_needed:.1f}g | "
                        f"actual_kcal_needed={actual_kcal_needed:.1f}"
                    )
                    
                    # CRITICAL: Stop immediately if fat excess is very high (>40%) - this is unhealthy
                    if fat_excess_ratio > 0.40:
                        # Only continue if we REALLY need protein/kcal (very high threshold: >35% protein or >40% kcal)
                        if protein_deficit_ratio > 0.35 or kcal_deficit_ratio > 0.40:
                            # Continue only if deficit is critical
                            pass
                        else:
                            logging.warning(
                                f"LUNCH_SUPP_STOP_EXCESS: High fat excess detected! "
                                f"fat_excess={fat_excess_ratio*100:.1f}% | "
                                f"protein_deficit={protein_deficit_ratio*100:.1f}% | "
                                f"kcal_deficit={kcal_deficit_ratio*100:.1f}% | "
                                f"Stopping to prevent unhealthy fat excess"
                            )
                            break
                    # CRITICAL: Stop if carb excess is extremely high (>50%)
                    elif carb_excess_ratio > 0.50:
                        if protein_deficit_ratio > 0.30 or kcal_deficit_ratio > 0.35:
                            pass
                        else:
                            logging.warning(
                                f"LUNCH_SUPP_STOP_EXCESS: Extreme carb excess detected! "
                                f"carb_excess={carb_excess_ratio*100:.1f}% | "
                                f"protein_deficit={protein_deficit_ratio*100:.1f}% | "
                                f"kcal_deficit={kcal_deficit_ratio*100:.1f}% | "
                                f"Stopping to prevent unhealthy carb excess"
                            )
                            break
                    # CRITICAL: Stop if kcal excess is extremely high (>50%)
                    elif kcal_excess_ratio > 0.50:
                        if protein_deficit_ratio > 0.30 or kcal_deficit_ratio > 0.35:
                            pass
                        else:
                            logging.warning(
                                f"LUNCH_SUPP_STOP_EXCESS: Extreme kcal excess detected! "
                                f"kcal_excess={kcal_excess_ratio*100:.1f}% | "
                                f"protein_deficit={protein_deficit_ratio*100:.1f}% | "
                                f"kcal_deficit={kcal_deficit_ratio*100:.1f}% | "
                                f"Stopping to prevent unhealthy kcal excess"
                            )
                            break
                    # For moderate excess (15-50%), use balanced logic
                    elif has_severe_fat_excess or has_severe_carb_excess or has_severe_kcal_excess:
                        # Continue if we still have significant deficit (prioritize nutrition)
                        if protein_deficit_ratio > 0.20 or kcal_deficit_ratio > 0.25:
                            # Continue adding despite moderate excess because deficit is high
                            pass
                        elif protein_deficit_ratio < 0.20 and kcal_deficit_ratio < 0.25:  # Only stop if deficit is low
                            logging.warning(
                                f"LUNCH_SUPP_STOP_EXCESS: Moderate excess detected! "
                                f"fat_excess={fat_excess_ratio*100:.1f}% | "
                                f"carb_excess={carb_excess_ratio*100:.1f}% | "
                                f"kcal_excess={kcal_excess_ratio*100:.1f}% | "
                                f"protein_deficit={protein_deficit_ratio*100:.1f}% | "
                                f"kcal_deficit={kcal_deficit_ratio*100:.1f}% | "
                                f"Stopping to prevent further over-eating"
                            )
                            break
                    
                    # CRITICAL: Stop only if we're very close to targets (within 5% for kcal, 10% for protein)
                    # This ensures we keep adding dishes until nutrition is truly sufficient
                    if kcal_deficit_ratio < 0.05 and protein_deficit_ratio < 0.10:
                        logging.debug(
                            f"LUNCH_SUPP_STOP: Close enough to targets "
                            f"(kcal_deficit={kcal_deficit_ratio*100:.1f}% < 5%, "
                            f"protein_deficit={protein_deficit_ratio*100:.1f}% < 10%)"
                        )
                        break
                    
                    # CRITICAL: Calculate total consumed so far for accurate excess detection
                    total_consumed_so_far = {
                        "kcal": total_consumed_kcal,
                        "protein_g": total_consumed_protein,
                        "fat_g": breakfast_macros.get("fat_g", 0.0) + current_lunch_macros.get("fat_g", 0.0),
                        "carb_g": breakfast_macros.get("carb_g", 0.0) + current_lunch_macros.get("carb_g", 0.0),
                    }
                    
                    # Add supplementary dishes
                    # CRITICAL: Allow more tolerance when deficit is high to meet nutrition targets
                    # Increase tolerance when deficit is significant (>30% protein or >40% kcal)
                    if protein_deficit_ratio > 0.30 or kcal_deficit_ratio > 0.40:
                        effective_meal_max_kcal = lunch_max_kcal * 1.4  # Allow 40% when deficit is very high
                    elif is_lunch_noodle or is_lunch_combined or protein_deficit_ratio > 0.20 or kcal_deficit_ratio > 0.30:
                        effective_meal_max_kcal = lunch_max_kcal * 1.3  # Allow 30% for combined/noodle or medium deficit
                    else:
                        effective_meal_max_kcal = lunch_max_kcal * 1.2  # Normal case: 20%
                    supplementary_dishes = add_supplementary_dishes(
                        "lunch",
                        current_lunch_dishes,
                        remaining_targets,
                        targets,
                        recipes,
                        excluded,
                        recent_recipe_ids_set,
                        effective_meal_max_kcal,  # Allow more kcal to meet nutrition targets
                        macro_tolerance_percent,
                        total_consumed_so_far=total_consumed_so_far,  # CRITICAL: Pass total consumed for accurate excess detection
                    )
                    
                    if not supplementary_dishes:
                        logging.debug(f"LUNCH_SUPP_ITERATION_{iteration + 1}: No more supplementary dishes found, stopping")
                        break  # No more dishes to add
                    
                    logging.debug(
                        f"LUNCH_SUPP_ITERATION_{iteration + 1}: Found {len(supplementary_dishes)} supplementary dish(es): "
                        f"{[d.get('dish_name', 'Unknown') for d in supplementary_dishes]}"
                    )
                    
                    # Update current_lunch_dishes and remaining_targets for next iteration
                    for supp_dish in supplementary_dishes:
                        all_supplementary_dishes.append(supp_dish)
                        current_lunch_dishes.append(supp_dish)
                        excluded.append(supp_dish)
                        recent_recipe_ids_set.add(str(supp_dish.get("food_id", "")))
                        # Update remaining_targets
                        dish_macros = _get_meal_macros(supp_dish)
                        dish_name = supp_dish.get("dish_name", "Unknown")
                        # Simplified logging - only log dish name and macros
                        logging.debug(
                            f"LUNCH_SUPP_ADD: {dish_name} | "
                            f"kcal={dish_macros.get('kcal', 0):.1f} | "
                            f"protein={dish_macros.get('protein_g', 0):.1f}g"
                        )
                        for k in remaining_targets:
                            remaining_targets[k] = max(0.0, remaining_targets[k] - dish_macros.get(k, 0.0))
                    
                    iteration += 1
                
                logging.debug(
                    f"LUNCH_SUPP_COMPLETE: Total iterations={iteration}, "
                    f"total_supplementary_dishes={len(all_supplementary_dishes)}, "
                    f"final_remaining_kcal={remaining_targets.get('kcal', 0):.1f}, "
                    f"final_remaining_protein={remaining_targets.get('protein_g', 0):.1f}g"
                )
                
                supplementary_dishes = all_supplementary_dishes
                
                # CRITICAL: Log all supplementary dishes before assigning
                logging.debug(
                    f"LUNCH_SUPP_DISHES_TO_ASSIGN: {len(supplementary_dishes)} dish(es): "
                    f"{[d.get('dish_name', 'Unknown') for d in supplementary_dishes]}"
                )
                
                # Add supplementary dishes to lunch components
                # Track which supplementary dishes were assigned to existing slots to avoid double-counting
                assigned_supp_dishes = []
                for supp_dish in supplementary_dishes:
                    dish_name = supp_dish.get('dish_name', 'Unknown')
                    dish_macros = _get_meal_macros(supp_dish)
                    assigned = False
                    if _is_main_dish(supp_dish):
                        # If we already have a main, add as additional main
                        if lunch_main:
                            # Store as additional main (we'll handle this in plan structure)
                            logging.info(f"Added additional main dish to lunch: {dish_name}")
                        else:
                            lunch_main = supp_dish
                            assigned = True  # Assigned to lunch_main, don't double-count
                            yield Response(f"✅ Added main dish to meet nutrition targets: {dish_name}")
                    elif _is_vegetable_dish(supp_dish):
                        if not lunch_veg:
                            lunch_veg = supp_dish
                            assigned = True  # Assigned to lunch_veg, don't double-count
                            yield Response(f"✅ Added vegetable to meet nutrition targets: {dish_name}")
                        else:
                            logging.info(f"Added additional vegetable to lunch: {dish_name}")
                    elif _is_soup(supp_dish):
                        if not lunch_soup:
                            lunch_soup = supp_dish
                            assigned = True  # Assigned to lunch_soup, don't double-count
                            yield Response(f"✅ Added soup to meet nutrition targets: {dish_name}")
                        else:
                            logging.info(f"Added additional soup to lunch: {dish_name}")
                    
                    # Update excluded (remaining_targets already updated in iterative loop above)
                    # Only append if not already in excluded (to avoid duplicates)
                    if supp_dish not in excluded:
                        excluded.append(supp_dish)
                    if str(supp_dish.get("food_id", "")) not in recent_recipe_ids_set:
                        recent_recipe_ids_set.add(str(supp_dish.get("food_id", "")))
                    
                    # Track if this dish was assigned to an existing slot (to avoid double-counting in recalculation)
                    if assigned:
                        assigned_supp_dishes.append(supp_dish)
                    else:
                        # CRITICAL: Store unassigned supplementary dishes to add to plan later
                        # These are additional dishes that don't fit into existing slots
                        lunch_supplementary_dishes.append(supp_dish)
                        logging.debug(
                            f"LUNCH_SUPP_UNASSIGNED: {dish_name} will be added to plan accompaniments"
                        )
                
                # Recalculate lunch total macros after adding supplementary dishes (for validation only)
                # NOTE: Only add supplementary dishes that were NOT assigned to existing slots
                # (assigned ones are already included in lunch_main/lunch_veg/lunch_soup)
                if supplementary_dishes:
                    lunch_total_macros = _get_meal_macros(lunch_rice)
                    if lunch_main:
                        main_macros = _get_meal_macros(lunch_main)
                        for k in lunch_total_macros:
                            lunch_total_macros[k] += main_macros.get(k, 0.0)
                    if lunch_soup:
                        soup_macros = _get_meal_macros(lunch_soup)
                        for k in lunch_total_macros:
                            lunch_total_macros[k] += soup_macros.get(k, 0.0)
                    if lunch_veg:
                        veg_macros = _get_meal_macros(lunch_veg)
                        for k in lunch_total_macros:
                            lunch_total_macros[k] += veg_macros.get(k, 0.0)
                    if lunch_fruit:
                        fruit_macros = _get_meal_macros(lunch_fruit)
                        for k in lunch_total_macros:
                            lunch_total_macros[k] += fruit_macros.get(k, 0.0)
                    # Add only supplementary dishes that were NOT assigned to existing slots
                    unassigned_supp_dishes = [d for d in supplementary_dishes if d not in assigned_supp_dishes]
                    for supp_dish in unassigned_supp_dishes:
                        supp_macros = _get_meal_macros(supp_dish)
                        for k in lunch_total_macros:
                            lunch_total_macros[k] += supp_macros.get(k, 0.0)
                else:
                    # No supplementary dishes - calculate lunch_total_macros from base dishes
                    lunch_total_macros = _get_meal_macros(lunch_rice)
                    if lunch_main:
                        main_macros = _get_meal_macros(lunch_main)
                        for k in lunch_total_macros:
                            lunch_total_macros[k] += main_macros.get(k, 0.0)
                    if lunch_soup:
                        soup_macros = _get_meal_macros(lunch_soup)
                        for k in lunch_total_macros:
                            lunch_total_macros[k] += soup_macros.get(k, 0.0)
                    if lunch_veg:
                        veg_macros = _get_meal_macros(lunch_veg)
                        for k in lunch_total_macros:
                            lunch_total_macros[k] += veg_macros.get(k, 0.0)
                    if lunch_fruit:
                        fruit_macros = _get_meal_macros(lunch_fruit)
                        for k in lunch_total_macros:
                            lunch_total_macros[k] += fruit_macros.get(k, 0.0)
                
                # CRITICAL: Update remaining_targets AFTER calculating final lunch_total_macros (including supplementary dishes)
                if remaining_targets:
                    lunch_total_kcal = lunch_total_macros.get("kcal", 0.0)
                    lunch_total_protein = lunch_total_macros.get("protein_g", 0.0)
                    lunch_total_fat = lunch_total_macros.get("fat_g", 0.0)
                    lunch_total_carb = lunch_total_macros.get("carb_g", 0.0)
                    
                    # Log breakdown of lunch components
                    logging.debug(
                        f"LUNCH_COMPONENTS_BREAKDOWN: "
                        f"rice={lunch_rice.get('dish_name', 'None') if lunch_rice else 'None'} | "
                        f"main={lunch_main.get('dish_name', 'None') if lunch_main else 'None'} | "
                        f"soup={lunch_soup.get('dish_name', 'None') if lunch_soup else 'None'} | "
                        f"veg={lunch_veg.get('dish_name', 'None') if lunch_veg else 'None'} | "
                        f"fruit={lunch_fruit.get('dish_name', 'None') if lunch_fruit else 'None'} | "
                        f"supplementary_count={len(supplementary_dishes)}"
                    )
                    
                    logging.debug(
                        f"LUNCH_TOTAL_MACROS: "
                        f"kcal={lunch_total_kcal:.1f} | "
                        f"protein={lunch_total_protein:.1f}g | "
                        f"fat={lunch_total_fat:.1f}g | "
                        f"carb={lunch_total_carb:.1f}g | "
                        f"lunch_max_kcal={lunch_max_kcal:.1f} | "
                        f"exceeds_by={((lunch_total_kcal / lunch_max_kcal - 1.0) * 100) if lunch_max_kcal > 0 else 0:.1f}%"
                    )
                    
                    # CRITICAL: If lunch total exceeds lunch_max_kcal, log warning but allow for better nutrition
                    # Increased tolerance to 50% to ensure we meet nutritional targets
                    if lunch_total_kcal > lunch_max_kcal * 1.4:  # Allow up to 40% when deficit is high
                        logging.warning(
                            f"Lunch total kcal ({lunch_total_kcal:.1f}) exceeds limit ({lunch_max_kcal:.1f}) by "
                            f"{((lunch_total_kcal / lunch_max_kcal - 1.0) * 100):.1f}%"
                        )
                    elif lunch_total_kcal > lunch_max_kcal * 1.2:
                        logging.debug(
                            f"Lunch total kcal ({lunch_total_kcal:.1f}) exceeds limit ({lunch_max_kcal:.1f}) by "
                            f"{((lunch_total_kcal / lunch_max_kcal - 1.0) * 100):.1f}% (within tolerance for nutrition)"
                        )
                    
                    # Removed verbose logging - only log when there's an issue
                    
                    # CRITICAL: Calculate what we actually consumed vs what we need
                    # Don't just subtract - calculate from original targets
                    breakfast_macros_check = _get_meal_macros(breakfast) if breakfast else {"kcal": 0.0, "protein_g": 0.0, "fat_g": 0.0, "carb_g": 0.0}
                    total_consumed_so_far_kcal = breakfast_macros_check.get("kcal", 0.0) + lunch_total_kcal
                    total_consumed_so_far_protein = breakfast_macros_check.get("protein_g", 0.0) + lunch_total_protein
                    total_consumed_so_far_fat = breakfast_macros_check.get("fat_g", 0.0) + lunch_total_fat
                    total_consumed_so_far_carb = breakfast_macros_check.get("carb_g", 0.0) + lunch_total_carb
                    
                    daily_protein_check = targets.get("protein_g", 150.0)
                    daily_kcal_check = targets.get("tdee_kcal", 2000.0)
                    daily_fat_check = targets.get("fat_g", 60.0)
                    daily_carb_check = targets.get("carb_g", 219.0)
                    
                    # Calculate ACTUAL remaining needs from original targets
                    actual_remaining_kcal = max(0.0, daily_kcal_check - total_consumed_so_far_kcal)
                    actual_remaining_protein = max(0.0, daily_protein_check - total_consumed_so_far_protein)
                    actual_remaining_fat = max(0.0, daily_fat_check - total_consumed_so_far_fat)
                    actual_remaining_carb = max(0.0, daily_carb_check - total_consumed_so_far_carb)
                    
                    # Update remaining_targets using subtraction method (for tracking)
                    remaining_targets["kcal"] = max(0.0, remaining_targets["kcal"] - lunch_total_kcal)
                    remaining_targets["protein_g"] = max(0.0, remaining_targets["protein_g"] - lunch_total_protein)
                    remaining_targets["fat_g"] = max(0.0, remaining_targets["fat_g"] - lunch_total_fat)
                    remaining_targets["carb_g"] = max(0.0, remaining_targets["carb_g"] - lunch_total_carb)
                    
                    # CRITICAL: If subtraction method gives wrong result, use actual calculation
                    # This happens when lunch exceeds remaining_targets (e.g., lunch has more kcal than remaining)
                    if abs(remaining_targets["kcal"] - actual_remaining_kcal) > 5.0 or abs(remaining_targets["protein_g"] - actual_remaining_protein) > 5.0:
                        logging.warning(
                            f"LUNCH_REMAINING_TARGETS_MISMATCH: "
                            f"subtraction_method: kcal={remaining_targets['kcal']:.1f}, protein={remaining_targets['protein_g']:.1f}g | "
                            f"actual_calculation: kcal={actual_remaining_kcal:.1f}, protein={actual_remaining_protein:.1f}g | "
                            f"lunch_total_kcal={lunch_total_kcal:.1f} | lunch_total_protein={lunch_total_protein:.1f}g | "
                            f"Correcting remaining_targets to match actual needs"
                        )
                        remaining_targets["kcal"] = actual_remaining_kcal
                        remaining_targets["protein_g"] = actual_remaining_protein
                        remaining_targets["fat_g"] = actual_remaining_fat
                        remaining_targets["carb_g"] = actual_remaining_carb
                    
                    # Log remaining targets AFTER update
                    logging.debug(
                        f"REMAINING_TARGETS (after lunch update): "
                        f"kcal={remaining_targets.get('kcal', 0):.1f} | "
                        f"protein={remaining_targets.get('protein_g', 0):.1f}g | "
                        f"fat={remaining_targets.get('fat_g', 0):.1f}g | "
                        f"carb={remaining_targets.get('carb_g', 0):.1f}g | "
                        f"total_consumed_kcal={total_consumed_so_far_kcal:.1f} | "
                        f"total_consumed_protein={total_consumed_so_far_protein:.1f}g | "
                        f"coverage_kcal={((total_consumed_so_far_kcal / daily_kcal_check) * 100) if daily_kcal_check > 0 else 0:.1f}% | "
                        f"coverage_protein={((total_consumed_so_far_protein / daily_protein_check) * 100) if daily_protein_check > 0 else 0:.1f}%"
                    )
                    
                    # CRITICAL: Don't artificially adjust remaining targets - use actual remaining values
                    # Only ensure it doesn't go negative
                    if remaining_targets["kcal"] < 0:
                        logging.warning(f"Remaining kcal after lunch is negative ({remaining_targets['kcal']:.1f}), setting to 0")
                        remaining_targets["kcal"] = 0.0
        
        # Validate lunch components
        if not lunch_rice:
            yield Response("⚠️ Could not find lunch dish. Using available options...")
            remaining = [r for r in recipes if r not in [breakfast]]
            lunch_rice = remaining[0] if remaining else breakfast
            is_lunch_combined = lunch_rice and _is_combined_dish(lunch_rice)
        
        if not is_lunch_combined and not lunch_main:
            # If plain rice but no main dish, try to find one
            excluded = [breakfast, lunch_rice]
            # Calculate dynamic requirements based on remaining protein
            daily_protein = targets.get("protein_g", 150.0) if targets else 150.0
            if daily_protein > 180:
                base_min_protein = 35.0
            elif daily_protein > 150:
                base_min_protein = 30.0
            else:
                base_min_protein = 25.0
            
            max_main_kcal = 550.0
            min_main_protein = base_min_protein
            if remaining_targets:
                protein_remaining = remaining_targets.get("protein_g", 0.0)
                protein_ratio = protein_remaining / daily_protein if daily_protein > 0 else 1.0
                if protein_ratio > 0.5:
                    max_main_kcal = 650.0
                    min_main_protein = max(base_min_protein, 40.0)
                elif protein_remaining > daily_protein * 0.4:
                    max_main_kcal = 600.0
                    min_main_protein = max(base_min_protein, 35.0)
                elif protein_remaining > daily_protein * 0.2:
                    min_main_protein = max(base_min_protein, 30.0)
            elif targets:
                # If no remaining_targets but have targets, assume we need protein
                max_main_kcal = 600.0
                min_main_protein = base_min_protein
            
            logging.debug(
                f"LUNCH_MAIN_SELECTION: "
                f"min_protein={min_main_protein:.1f}g | "
                f"min_kcal={min_main_kcal:.1f} | "
                f"max_kcal={max_main_kcal:.1f} | "
                f"remaining_protein={remaining_targets.get('protein_g', 0):.1f}g | "
                f"remaining_kcal={remaining_targets.get('kcal', 0):.1f}"
            )
            
            lunch_main = select_meal_by_strategy(
                recipes, "highest_protein", 
                exclude=excluded, 
                used_recipe_ids=recent_recipe_ids_set,
                preferred_meal_type="lunch", 
                dish_category="main",  # CRITICAL: Specify category to ensure correct selection
                target_macros=targets,
                require_macros=True,
                min_kcal=min_main_kcal,  # CRITICAL: Require minimum kcal for better nutrition
                max_kcal=max_main_kcal,  # CRITICAL: Dynamic kcal limit
                min_protein=min_main_protein,  # CRITICAL: Require minimum protein
            )
            
            if lunch_main:
                main_macros = _get_meal_macros(lunch_main)
                logging.debug(
                    f"LUNCH_MAIN_SELECTED: {lunch_main.get('dish_name', 'Unknown')} | "
                    f"protein={main_macros.get('protein_g', 0):.1f}g | "
                    f"kcal={main_macros.get('kcal', 0):.1f} | "
                    f"fat={main_macros.get('fat_g', 0):.1f}g | "
                    f"carb={main_macros.get('carb_g', 0):.1f}g"
                )
            else:
                logging.warning(f"LUNCH_MAIN_NOT_FOUND: No main dish found with requirements (min_protein={min_main_protein:.1f}g, min_kcal={min_main_kcal:.1f})")
            # CRITICAL: Validate lunch main is actually a main dish
            if lunch_main and not _is_main_dish(lunch_main):
                logging.warning(f"Selected lunch main '{lunch_main.get('dish_name', 'Unknown')}' is not a main dish, rejecting...")
                lunch_main = None
            # CRITICAL: If still no main, try without category restriction but still prioritize protein
            if not lunch_main:
                logging.warning("No lunch main found with category restriction, trying without category but prioritizing protein...")
                lunch_main = select_meal_by_strategy(
                    recipes, "highest_protein",
                    exclude=excluded,
                    used_recipe_ids=recent_recipe_ids_set,
                    preferred_meal_type="lunch",
                    target_macros=targets,
                    require_macros=True,
                    min_kcal=min_main_kcal,  # CRITICAL: Require minimum kcal for better nutrition
                    max_kcal=max_main_kcal,
                    min_protein=min_main_protein,
                )
                # Validate it's actually a main dish
                if lunch_main and not _is_main_dish(lunch_main):
                    lunch_main = None
        
        # Dinner: Vietnamese dinner pattern - use helper functions
        excluded = [breakfast, lunch_rice]
        if lunch_main:
            excluded.append(lunch_main)
        if lunch_veg:
            excluded.append(lunch_veg)
        if lunch_soup:
            excluded.append(lunch_soup)
        if lunch_fruit:
            excluded.append(lunch_fruit)
        
        # Prepare targets with remaining_targets for dinner selection
        dinner_targets = targets.copy() if targets else None
        if dinner_targets and remaining_targets:
            dinner_targets["_remaining_targets"] = remaining_targets.copy()
        
        # Select dinner carb with validation (use dinner_max_kcal for heavier dinner)
        dinner_carb, is_dinner_combined, is_dinner_noodle = _select_carb_with_validation(
            llm_draft, "dinner",
            recipes, excluded, recent_recipe_ids_set,
            selection_strategy, dinner_targets, dinner_max_kcal
        )
        
        if dinner_carb:
            carb_name = dinner_carb.get('dish_name', 'Unknown')
            if dinner_carb.get("food_id") != "default_white_rice":
                yield Response(f"✅ Selected dinner carb from AI suggestion: {carb_name}")
            else:
                yield Response("ℹ️ No suitable dinner dish found. Using default white rice.")
        
        dinner_rice = dinner_carb
        
        # Select accompaniments
        if dinner_rice:
            excluded.append(dinner_rice)
            
            if is_dinner_combined or is_dinner_noodle:
                if is_dinner_combined:
                    yield Response("ℹ️ Selected combined dish for dinner (contains both carbs and protein). Adding fruit only.")
                else:
                    yield Response("ℹ️ Selected noodle dish for dinner (standalone meal). Adding fruit only.")
            
            dinner_main, dinner_soup, dinner_veg, dinner_fruit = select_accompaniments(
                "dinner", is_dinner_combined, is_dinner_noodle,
                recipes, excluded, recent_recipe_ids_set,
                selection_strategy, dinner_targets,
                llm_draft=llm_draft,
                try_select_from_llm_suggestions=_try_select_from_llm_suggestions,
            )
            
            # CRITICAL: Validate dinner main is actually a main dish
            if dinner_main and not _is_main_dish(dinner_main):
                logging.warning(f"Dinner main '{dinner_main.get('dish_name', 'Unknown')}' is not a main dish, rejecting...")
                dinner_main = None
            
            # CRITICAL: Validate dinner vegetable is actually a vegetable dish (not a main dish)
            if dinner_veg:
                if not _is_vegetable_dish(dinner_veg):
                    logging.warning(f"Dinner vegetable '{dinner_veg.get('dish_name', 'Unknown')}' is not a vegetable dish, rejecting...")
                    dinner_veg = None
                elif _is_main_dish(dinner_veg):
                    logging.warning(f"Dinner vegetable '{dinner_veg.get('dish_name', 'Unknown')}' is actually a main dish, rejecting...")
                    dinner_veg = None
            
            # CRITICAL: Ensure no duplicate dishes
            all_selected_dishes = [breakfast, lunch_rice, lunch_main, lunch_soup, lunch_veg, lunch_fruit, dinner_rice, dinner_main, dinner_soup, dinner_veg, dinner_fruit]
            all_selected_ids = {str(d.get("food_id", "")) for d in all_selected_dishes if d and d.get("food_id")}
            if len(all_selected_ids) < len([d for d in all_selected_dishes if d]):
                logging.warning("Duplicate dishes detected in plan, removing duplicates...")
                # Remove duplicates from dinner components
                if dinner_main and str(dinner_main.get("food_id", "")) in [str(d.get("food_id", "")) for d in [breakfast, lunch_rice, lunch_main, lunch_soup, lunch_veg, lunch_fruit, dinner_rice] if d]:
                    logging.warning(f"Removing duplicate dinner main: {dinner_main.get('dish_name', 'Unknown')}")
                    dinner_main = None
                if dinner_veg and str(dinner_veg.get("food_id", "")) in [str(d.get("food_id", "")) for d in [breakfast, lunch_rice, lunch_main, lunch_soup, lunch_veg, lunch_fruit, dinner_rice, dinner_main] if d]:
                    logging.warning(f"Removing duplicate dinner vegetable: {dinner_veg.get('dish_name', 'Unknown')}")
                    dinner_veg = None
                if dinner_soup and str(dinner_soup.get("food_id", "")) in [str(d.get("food_id", "")) for d in [breakfast, lunch_rice, lunch_main, lunch_soup, lunch_veg, lunch_fruit, dinner_rice, dinner_main, dinner_veg] if d]:
                    logging.warning(f"Removing duplicate dinner soup: {dinner_soup.get('dish_name', 'Unknown')}")
                    dinner_soup = None
                if dinner_fruit and str(dinner_fruit.get("food_id", "")) in [str(d.get("food_id", "")) for d in [breakfast, lunch_rice, lunch_main, lunch_soup, lunch_veg, lunch_fruit, dinner_rice, dinner_main, dinner_veg, dinner_soup] if d]:
                    logging.warning(f"Removing duplicate dinner fruit: {dinner_fruit.get('dish_name', 'Unknown')}")
                    dinner_fruit = None
            
            # User feedback for LLM selections
            if dinner_main and _try_select_from_llm_suggestions(llm_draft, "dinner", "main", recipes, [], recent_recipe_ids_set, 50.0, 500.0):
                yield Response(f"✅ Selected dinner main from AI suggestion: {dinner_main.get('dish_name', 'Unknown')}")
            if dinner_veg and _try_select_from_llm_suggestions(llm_draft, "dinner", "vegetable", recipes, [], recent_recipe_ids_set, 30.0):
                yield Response(f"✅ Selected dinner vegetable from AI suggestion: {dinner_veg.get('dish_name', 'Unknown')}")
            if dinner_fruit and _try_select_from_llm_suggestions(llm_draft, "dinner", "fruit", recipes, [], recent_recipe_ids_set, 30.0):
                yield Response(f"✅ Selected dinner fruit from AI suggestion: {dinner_fruit.get('dish_name', 'Unknown')}")
            
            # CRITICAL: Add supplementary dishes if still deficient in nutrition
            # IMPORTANT: Also add for noodle dishes if nutrition is still deficient
            if remaining_targets and targets:
                current_dinner_dishes = [d for d in [dinner_rice, dinner_main, dinner_soup, dinner_veg, dinner_fruit] if d]
                # For noodle/combined dishes, allow adding more dishes if nutrition is still deficient
                # Use iterative approach to keep adding until nutrition targets are met
                max_iterations = 5  # Increased from 3 to 5 to allow more dishes to be added
                iteration = 0
                all_supplementary_dishes = []  # dinner supplementary dishes collected in this loop
                
                # CRITICAL: Get lunch supplementary dishes to calculate accurate total consumed
                # Use the actual lunch_supplementary_dishes collected during lunch phase
                lunch_supp_dishes_for_calc = lunch_supplementary_dishes if 'lunch_supplementary_dishes' in locals() else []
                
                while iteration < max_iterations:
                    # CRITICAL: Calculate what we ACTUALLY need based on original targets, not just remaining_targets
                    # This ensures we don't stop too early if remaining_targets was incorrectly calculated
                    breakfast_macros = _get_meal_macros(breakfast) if breakfast else {"kcal": 0.0, "protein_g": 0.0, "fat_g": 0.0, "carb_g": 0.0}
                    # CRITICAL: Include lunch supplementary dishes in calculation
                    lunch_base_dishes = [d for d in [lunch_rice, lunch_main, lunch_soup, lunch_veg, lunch_fruit] if d]
                    lunch_all_dishes = lunch_base_dishes + lunch_supp_dishes_for_calc
                    lunch_total_macros_calc = calculate_meal_macros(lunch_all_dishes)
                    current_dinner_macros = calculate_meal_macros(current_dinner_dishes)
                    total_consumed_kcal = breakfast_macros.get("kcal", 0.0) + lunch_total_macros_calc.get("kcal", 0.0) + current_dinner_macros.get("kcal", 0.0)
                    total_consumed_protein = breakfast_macros.get("protein_g", 0.0) + lunch_total_macros_calc.get("protein_g", 0.0) + current_dinner_macros.get("protein_g", 0.0)
                    total_consumed_fat = breakfast_macros.get("fat_g", 0.0) + lunch_total_macros_calc.get("fat_g", 0.0) + current_dinner_macros.get("fat_g", 0.0)
                    total_consumed_carb = breakfast_macros.get("carb_g", 0.0) + lunch_total_macros_calc.get("carb_g", 0.0) + current_dinner_macros.get("carb_g", 0.0)
                    
                    daily_protein = targets.get("protein_g", 150.0)
                    daily_kcal = targets.get("tdee_kcal", 2000.0)
                    
                    # Calculate ACTUAL remaining needs from original targets
                    actual_protein_needed = max(0.0, daily_protein - total_consumed_protein)
                    actual_kcal_needed = max(0.0, daily_kcal - total_consumed_kcal)
                    
                    # Also check remaining_targets (may be updated in loop)
                    protein_needed_from_remaining = remaining_targets.get("protein_g", 0.0)
                    kcal_needed_from_remaining = remaining_targets.get("kcal", 0.0)
                    
                    # Use the MAXIMUM of actual_needed and remaining_targets to ensure we don't stop too early
                    protein_needed = max(protein_needed_from_remaining, actual_protein_needed)
                    kcal_needed = max(kcal_needed_from_remaining, actual_kcal_needed)
                    
                    # CRITICAL: Update remaining_targets to reflect actual needs if it's incorrect
                    if actual_protein_needed > protein_needed_from_remaining or actual_kcal_needed > kcal_needed_from_remaining:
                        logging.warning(
                            f"DINNER_SUPP_CORRECTION: remaining_targets was incorrect! "
                            f"actual_protein_needed={actual_protein_needed:.1f}g vs remaining={protein_needed_from_remaining:.1f}g | "
                            f"actual_kcal_needed={actual_kcal_needed:.1f} vs remaining={kcal_needed_from_remaining:.1f} | "
                            f"Updating remaining_targets to reflect actual needs"
                        )
                        remaining_targets["protein_g"] = actual_protein_needed
                        remaining_targets["kcal"] = actual_kcal_needed
                    
                    # Calculate deficit ratios
                    protein_deficit_ratio = protein_needed / daily_protein if daily_protein > 0 else 0.0
                    kcal_deficit_ratio = kcal_needed / daily_kcal if daily_kcal > 0 else 0.0
                    
                    # CRITICAL: Calculate fat/carb excess based on total consumed
                    daily_fat = targets.get("fat_g", 60.0)
                    daily_carb = targets.get("carb_g", 219.0)
                    fat_excess_ratio = (total_consumed_fat - daily_fat) / daily_fat if daily_fat > 0 and total_consumed_fat > daily_fat else 0.0
                    carb_excess_ratio = (total_consumed_carb - daily_carb) / daily_carb if daily_carb > 0 and total_consumed_carb > daily_carb else 0.0
                    kcal_excess_ratio = (total_consumed_kcal - daily_kcal) / daily_kcal if daily_kcal > 0 and total_consumed_kcal > daily_kcal else 0.0
                    has_severe_fat_excess = fat_excess_ratio > 0.15  # Balanced: 15% to prevent over-eating but allow nutrition
                    has_severe_carb_excess = carb_excess_ratio > 0.15  # Balanced: 15%
                    has_severe_kcal_excess = kcal_excess_ratio > 0.15  # Balanced: 15%
                    
                    logging.debug(
                        f"DINNER_SUPP_ITERATION_{iteration + 1}: "
                        f"protein_needed={protein_needed:.1f}g ({protein_deficit_ratio*100:.1f}% of daily) | "
                        f"kcal_needed={kcal_needed:.1f} ({kcal_deficit_ratio*100:.1f}% of daily) | "
                        f"fat_excess={fat_excess_ratio*100:.1f}% | carb_excess={carb_excess_ratio*100:.1f}% | "
                        f"kcal_excess={kcal_excess_ratio*100:.1f}% | "
                        f"current_dishes_count={len(current_dinner_dishes)} | "
                        f"current_dinner_kcal={current_dinner_macros.get('kcal', 0):.1f} | "
                        f"current_dinner_protein={current_dinner_macros.get('protein_g', 0):.1f}g | "
                        f"total_consumed_kcal={total_consumed_kcal:.1f} | "
                        f"total_consumed_protein={total_consumed_protein:.1f}g | "
                        f"total_consumed_fat={total_consumed_fat:.1f}g | "
                        f"total_consumed_carb={total_consumed_carb:.1f}g | "
                        f"actual_protein_needed={actual_protein_needed:.1f}g | "
                        f"actual_kcal_needed={actual_kcal_needed:.1f}"
                    )
                    
                    # CRITICAL: Stop immediately if fat excess is very high (>40%) - this is unhealthy
                    if fat_excess_ratio > 0.40:
                        # Only continue if we REALLY need protein/kcal (very high threshold: >35% protein or >40% kcal)
                        if protein_deficit_ratio > 0.35 or kcal_deficit_ratio > 0.40:
                            # Continue only if deficit is critical
                            pass
                        else:
                            logging.warning(
                                f"DINNER_SUPP_STOP_EXCESS: High fat excess detected! "
                                f"fat_excess={fat_excess_ratio*100:.1f}% | "
                                f"protein_deficit={protein_deficit_ratio*100:.1f}% | "
                                f"kcal_deficit={kcal_deficit_ratio*100:.1f}% | "
                                f"Stopping to prevent unhealthy fat excess"
                            )
                            break
                    # CRITICAL: Stop if carb excess is extremely high (>50%)
                    elif carb_excess_ratio > 0.50:
                        if protein_deficit_ratio > 0.30 or kcal_deficit_ratio > 0.35:
                            pass
                        else:
                            logging.warning(
                                f"DINNER_SUPP_STOP_EXCESS: Extreme carb excess detected! "
                                f"carb_excess={carb_excess_ratio*100:.1f}% | "
                                f"protein_deficit={protein_deficit_ratio*100:.1f}% | "
                                f"kcal_deficit={kcal_deficit_ratio*100:.1f}% | "
                                f"Stopping to prevent unhealthy carb excess"
                            )
                            break
                    # CRITICAL: Stop if kcal excess is extremely high (>50%)
                    elif kcal_excess_ratio > 0.50:
                        if protein_deficit_ratio > 0.30 or kcal_deficit_ratio > 0.35:
                            pass
                        else:
                            logging.warning(
                                f"DINNER_SUPP_STOP_EXCESS: Extreme kcal excess detected! "
                                f"kcal_excess={kcal_excess_ratio*100:.1f}% | "
                                f"protein_deficit={protein_deficit_ratio*100:.1f}% | "
                                f"kcal_deficit={kcal_deficit_ratio*100:.1f}% | "
                                f"Stopping to prevent unhealthy kcal excess"
                            )
                            break
                    # For moderate excess (15-40%), use balanced logic
                    elif has_severe_fat_excess or has_severe_carb_excess or has_severe_kcal_excess:
                        # Continue if we still have significant deficit (prioritize nutrition)
                        if protein_deficit_ratio > 0.20 or kcal_deficit_ratio > 0.25:
                            # Continue adding despite moderate excess because deficit is high
                            pass
                        elif protein_deficit_ratio < 0.20 and kcal_deficit_ratio < 0.25:  # Only stop if deficit is low
                            logging.warning(
                                f"DINNER_SUPP_STOP_EXCESS: Moderate excess detected! "
                                f"fat_excess={fat_excess_ratio*100:.1f}% | "
                                f"carb_excess={carb_excess_ratio*100:.1f}% | "
                                f"kcal_excess={kcal_excess_ratio*100:.1f}% | "
                                f"protein_deficit={protein_deficit_ratio*100:.1f}% | "
                                f"kcal_deficit={kcal_deficit_ratio*100:.1f}% | "
                                f"Stopping to prevent further over-eating"
                            )
                            break
                    
                    # CRITICAL: Stop only if we're very close to targets (within 5% for kcal, 10% for protein)
                    # This ensures we keep adding dishes until nutrition is truly sufficient
                    if kcal_deficit_ratio < 0.05 and protein_deficit_ratio < 0.10:
                        logging.debug(
                            f"DINNER_SUPP_STOP: Close enough to targets "
                            f"(kcal_deficit={kcal_deficit_ratio*100:.1f}% < 5%, "
                            f"protein_deficit={protein_deficit_ratio*100:.1f}% < 10%)"
                        )
                        break
                    
                    # CRITICAL: Calculate total consumed so far for accurate excess detection
                    # Use already calculated values from above
                    total_consumed_so_far_dinner = {
                        "kcal": total_consumed_kcal,
                        "protein_g": total_consumed_protein,
                        "fat_g": total_consumed_fat,
                        "carb_g": total_consumed_carb,
                    }
                    
                    # Add supplementary dishes
                    # CRITICAL: Allow more tolerance when deficit is high to meet nutrition targets
                    # Increase tolerance when deficit is significant (>30% protein or >40% kcal)
                    if protein_deficit_ratio > 0.30 or kcal_deficit_ratio > 0.40:
                        effective_meal_max_kcal = dinner_max_kcal * 1.4  # Allow 40% when deficit is very high
                    elif is_dinner_noodle or is_dinner_combined or protein_deficit_ratio > 0.20 or kcal_deficit_ratio > 0.30:
                        effective_meal_max_kcal = dinner_max_kcal * 1.3  # Allow 30% for combined/noodle or medium deficit
                    else:
                        effective_meal_max_kcal = dinner_max_kcal * 1.2  # Normal case: 20%
                    supplementary_dishes = add_supplementary_dishes(
                        "dinner",
                        current_dinner_dishes,
                        remaining_targets,
                        targets,
                        recipes,
                        excluded,
                        recent_recipe_ids_set,
                        effective_meal_max_kcal,  # Allow more kcal to meet nutrition targets
                        macro_tolerance_percent,
                        total_consumed_so_far=total_consumed_so_far_dinner,  # CRITICAL: Pass total consumed for accurate excess detection
                    )
                    
                    if not supplementary_dishes:
                        logging.debug(f"DINNER_SUPP_ITERATION_{iteration + 1}: No more supplementary dishes found, stopping")
                        break  # No more dishes to add
                    
                    logging.debug(
                        f"DINNER_SUPP_ITERATION_{iteration + 1}: Found {len(supplementary_dishes)} supplementary dish(es): "
                        f"{[d.get('dish_name', 'Unknown') for d in supplementary_dishes]}"
                    )
                    
                    # Update current_dinner_dishes and remaining_targets for next iteration
                    for supp_dish in supplementary_dishes:
                        all_supplementary_dishes.append(supp_dish)
                        current_dinner_dishes.append(supp_dish)
                        excluded.append(supp_dish)
                        recent_recipe_ids_set.add(str(supp_dish.get("food_id", "")))
                        # Update remaining_targets
                        dish_macros = _get_meal_macros(supp_dish)
                        dish_name = supp_dish.get("dish_name", "Unknown")
                        # Simplified logging - only log dish name and macros
                        logging.debug(
                            f"DINNER_SUPP_ADD: {dish_name} | "
                            f"kcal={dish_macros.get('kcal', 0):.1f} | "
                            f"protein={dish_macros.get('protein_g', 0):.1f}g"
                        )
                        for k in remaining_targets:
                            remaining_targets[k] = max(0.0, remaining_targets[k] - dish_macros.get(k, 0.0))
                    
                    iteration += 1
                
                logging.debug(
                    f"DINNER_SUPP_COMPLETE: Total iterations={iteration}, "
                    f"total_supplementary_dishes={len(all_supplementary_dishes)}, "
                    f"final_remaining_kcal={remaining_targets.get('kcal', 0):.1f}, "
                    f"final_remaining_protein={remaining_targets.get('protein_g', 0):.1f}g"
                )
                
                supplementary_dishes = all_supplementary_dishes
                
                # Add supplementary dishes to dinner components
                # Track which supplementary dishes were assigned to existing slots to avoid double-counting
                assigned_supp_dishes = []
                for supp_dish in supplementary_dishes:
                    dish_name = supp_dish.get('dish_name', 'Unknown')
                    dish_macros = _get_meal_macros(supp_dish)
                    assigned = False
                    if _is_main_dish(supp_dish):
                        # If we already have a main, add as additional main
                        if dinner_main:
                            # Store as additional main (we'll handle this in plan structure)
                            logging.info(f"Added additional main dish to dinner: {dish_name}")
                        else:
                            dinner_main = supp_dish
                            assigned = True  # Assigned to dinner_main, don't double-count
                            yield Response(f"✅ Added main dish to meet nutrition targets: {dish_name}")
                    elif _is_vegetable_dish(supp_dish):
                        if not dinner_veg:
                            dinner_veg = supp_dish
                            assigned = True  # Assigned to dinner_veg, don't double-count
                            yield Response(f"✅ Added vegetable to meet nutrition targets: {dish_name}")
                        else:
                            logging.info(f"Added additional vegetable to dinner: {dish_name}")
                    elif _is_soup(supp_dish):
                        if not dinner_soup:
                            dinner_soup = supp_dish
                            assigned = True  # Assigned to dinner_soup, don't double-count
                            yield Response(f"✅ Added soup to meet nutrition targets: {dish_name}")
                        else:
                            logging.info(f"Added additional soup to dinner: {dish_name}")
                    
                    # Update excluded (remaining_targets already updated in iterative loop above)
                    # Only append if not already in excluded (to avoid duplicates)
                    if supp_dish not in excluded:
                        excluded.append(supp_dish)
                    if str(supp_dish.get("food_id", "")) not in recent_recipe_ids_set:
                        recent_recipe_ids_set.add(str(supp_dish.get("food_id", "")))
                    
                    # Track if this dish was assigned to an existing slot (to avoid double-counting in recalculation)
                    if assigned:
                        assigned_supp_dishes.append(supp_dish)
                    else:
                        # CRITICAL: Store unassigned supplementary dishes to add to plan later
                        # These are additional dishes that don't fit into existing slots
                        dinner_supplementary_dishes.append(supp_dish)
                        logging.debug(
                            f"DINNER_SUPP_UNASSIGNED: {dish_name} will be added to plan accompaniments"
                        )
                
                # Recalculate dinner total macros after adding supplementary dishes (for validation only)
                # NOTE: Only add supplementary dishes that were NOT assigned to existing slots
                # (assigned ones are already included in dinner_main/dinner_veg/dinner_soup)
                # Also note: remaining_targets already updated in loop above, so don't update again here
                if supplementary_dishes:
                    dinner_total_macros = _get_meal_macros(dinner_rice)
                    if dinner_main:
                        main_macros = _get_meal_macros(dinner_main)
                        for k in dinner_total_macros:
                            dinner_total_macros[k] += main_macros.get(k, 0.0)
                    if dinner_soup:
                        soup_macros = _get_meal_macros(dinner_soup)
                        for k in dinner_total_macros:
                            dinner_total_macros[k] += soup_macros.get(k, 0.0)
                    if dinner_veg:
                        veg_macros = _get_meal_macros(dinner_veg)
                        for k in dinner_total_macros:
                            dinner_total_macros[k] += veg_macros.get(k, 0.0)
                    if dinner_fruit:
                        fruit_macros = _get_meal_macros(dinner_fruit)
                        for k in dinner_total_macros:
                            dinner_total_macros[k] += fruit_macros.get(k, 0.0)
                    # Add only supplementary dishes that were NOT assigned to existing slots
                    unassigned_supp_dishes = [d for d in supplementary_dishes if d not in assigned_supp_dishes]
                    for supp_dish in unassigned_supp_dishes:
                        supp_macros = _get_meal_macros(supp_dish)
                        for k in dinner_total_macros:
                            dinner_total_macros[k] += supp_macros.get(k, 0.0)
                else:
                    # No supplementary dishes - calculate dinner_total_macros from base dishes
                    dinner_total_macros = _get_meal_macros(dinner_rice)
                    if dinner_main:
                        main_macros = _get_meal_macros(dinner_main)
                        for k in dinner_total_macros:
                            dinner_total_macros[k] += main_macros.get(k, 0.0)
                    if dinner_soup:
                        soup_macros = _get_meal_macros(dinner_soup)
                        for k in dinner_total_macros:
                            dinner_total_macros[k] += soup_macros.get(k, 0.0)
                    if dinner_veg:
                        veg_macros = _get_meal_macros(dinner_veg)
                        for k in dinner_total_macros:
                            dinner_total_macros[k] += veg_macros.get(k, 0.0)
                    if dinner_fruit:
                        fruit_macros = _get_meal_macros(dinner_fruit)
                        for k in dinner_total_macros:
                            dinner_total_macros[k] += fruit_macros.get(k, 0.0)
                
                # CRITICAL: Update remaining_targets AFTER calculating final dinner_total_macros (including supplementary dishes)
                if remaining_targets:
                    dinner_total_kcal = dinner_total_macros.get("kcal", 0.0)
                    dinner_total_protein = dinner_total_macros.get("protein_g", 0.0)
                    dinner_total_fat = dinner_total_macros.get("fat_g", 0.0)
                    dinner_total_carb = dinner_total_macros.get("carb_g", 0.0)
                    
                    # Log breakdown of dinner components
                    logging.debug(
                        f"DINNER_COMPONENTS_BREAKDOWN: "
                        f"rice={dinner_rice.get('dish_name', 'None') if dinner_rice else 'None'} | "
                        f"main={dinner_main.get('dish_name', 'None') if dinner_main else 'None'} | "
                        f"soup={dinner_soup.get('dish_name', 'None') if dinner_soup else 'None'} | "
                        f"veg={dinner_veg.get('dish_name', 'None') if dinner_veg else 'None'} | "
                        f"fruit={dinner_fruit.get('dish_name', 'None') if dinner_fruit else 'None'} | "
                        f"supplementary_count={len(supplementary_dishes)}"
                    )
                    
                    logging.debug(
                        f"DINNER_TOTAL_MACROS: "
                        f"kcal={dinner_total_kcal:.1f} | "
                        f"protein={dinner_total_protein:.1f}g | "
                        f"fat={dinner_total_fat:.1f}g | "
                        f"carb={dinner_total_carb:.1f}g | "
                        f"dinner_max_kcal={dinner_max_kcal:.1f} | "
                        f"exceeds_by={((dinner_total_kcal / dinner_max_kcal - 1.0) * 100) if dinner_max_kcal > 0 else 0:.1f}%"
                    )
                    
                    # CRITICAL: If dinner total exceeds dinner_max_kcal, log warning but allow for better nutrition
                    # Increased tolerance to 50% to ensure we meet nutritional targets
                    if dinner_total_kcal > dinner_max_kcal * 1.4:  # Allow up to 40% when deficit is high
                        logging.warning(
                            f"Dinner total kcal ({dinner_total_kcal:.1f}) exceeds limit ({dinner_max_kcal:.1f}) by "
                            f"{((dinner_total_kcal / dinner_max_kcal - 1.0) * 100):.1f}%"
                        )
                    elif dinner_total_kcal > dinner_max_kcal * 1.2:
                        logging.debug(
                            f"Dinner total kcal ({dinner_total_kcal:.1f}) exceeds limit ({dinner_max_kcal:.1f}) by "
                            f"{((dinner_total_kcal / dinner_max_kcal - 1.0) * 100):.1f}% (within tolerance for nutrition)"
                        )
                    
                    # Removed verbose logging - only log when there's an issue
                    
                    # CRITICAL: Calculate ACTUAL remaining needs from original targets to verify
                    breakfast_macros_check = _get_meal_macros(breakfast) if breakfast else {"kcal": 0.0, "protein_g": 0.0, "fat_g": 0.0, "carb_g": 0.0}
                    # Include supplementary dishes from lunch to avoid underestimating consumed macros
                    lunch_supp_for_check = lunch_supplementary_dishes if 'lunch_supplementary_dishes' in locals() else []
                    lunch_total_macros_check = calculate_meal_macros(
                        [d for d in [lunch_rice, lunch_main, lunch_soup, lunch_veg, lunch_fruit] if d] + lunch_supp_for_check
                    )
                    total_consumed_so_far_kcal = breakfast_macros_check.get("kcal", 0.0) + lunch_total_macros_check.get("kcal", 0.0) + dinner_total_kcal
                    total_consumed_so_far_protein = breakfast_macros_check.get("protein_g", 0.0) + lunch_total_macros_check.get("protein_g", 0.0) + dinner_total_protein
                    total_consumed_so_far_fat = breakfast_macros_check.get("fat_g", 0.0) + lunch_total_macros_check.get("fat_g", 0.0) + dinner_total_fat
                    total_consumed_so_far_carb = breakfast_macros_check.get("carb_g", 0.0) + lunch_total_macros_check.get("carb_g", 0.0) + dinner_total_carb
                    
                    daily_protein_check = targets.get("protein_g", 150.0)
                    daily_kcal_check = targets.get("tdee_kcal", 2000.0)
                    daily_fat_check = targets.get("fat_g", 60.0)
                    daily_carb_check = targets.get("carb_g", 219.0)
                    
                    actual_remaining_kcal = max(0.0, daily_kcal_check - total_consumed_so_far_kcal)
                    actual_remaining_protein = max(0.0, daily_protein_check - total_consumed_so_far_protein)
                    actual_remaining_fat = max(0.0, daily_fat_check - total_consumed_so_far_fat)
                    actual_remaining_carb = max(0.0, daily_carb_check - total_consumed_so_far_carb)
                    
                    # Update remaining_targets using subtraction method
                    remaining_targets["kcal"] = max(0.0, remaining_targets["kcal"] - dinner_total_kcal)
                    remaining_targets["protein_g"] = max(0.0, remaining_targets["protein_g"] - dinner_total_protein)
                    remaining_targets["fat_g"] = max(0.0, remaining_targets["fat_g"] - dinner_total_fat)
                    remaining_targets["carb_g"] = max(0.0, remaining_targets["carb_g"] - dinner_total_carb)
                    
                    # CRITICAL: Verify and correct remaining_targets if it doesn't match actual calculation
                    if abs(remaining_targets["kcal"] - actual_remaining_kcal) > 1.0 or abs(remaining_targets["protein_g"] - actual_remaining_protein) > 1.0:
                        logging.warning(
                            f"DINNER_REMAINING_TARGETS_MISMATCH: "
                            f"remaining_targets says kcal={remaining_targets['kcal']:.1f}, protein={remaining_targets['protein_g']:.1f}g | "
                            f"but actual calculation shows kcal={actual_remaining_kcal:.1f}, protein={actual_remaining_protein:.1f}g | "
                            f"Correcting remaining_targets to match actual needs"
                        )
                        remaining_targets["kcal"] = actual_remaining_kcal
                        remaining_targets["protein_g"] = actual_remaining_protein
                        remaining_targets["fat_g"] = actual_remaining_fat
                        remaining_targets["carb_g"] = actual_remaining_carb
                    
                    # Log remaining targets AFTER update
                    logging.debug(
                        f"REMAINING_TARGETS (after dinner update): "
                        f"kcal={remaining_targets.get('kcal', 0):.1f} | "
                        f"protein={remaining_targets.get('protein_g', 0):.1f}g | "
                        f"fat={remaining_targets.get('fat_g', 0):.1f}g | "
                        f"carb={remaining_targets.get('carb_g', 0):.1f}g | "
                        f"total_consumed_kcal={total_consumed_so_far_kcal:.1f} | "
                        f"total_consumed_protein={total_consumed_so_far_protein:.1f}g | "
                        f"coverage_kcal={((total_consumed_so_far_kcal / daily_kcal_check) * 100) if daily_kcal_check > 0 else 0:.1f}% | "
                        f"coverage_protein={((total_consumed_so_far_protein / daily_protein_check) * 100) if daily_protein_check > 0 else 0:.1f}%"
                    )
        
        # Validate dinner components
        if not dinner_rice:
            yield Response("⚠️ Could not find dinner dish. Using available options...")
            excluded = [breakfast, lunch_rice]
            if lunch_main:
                excluded.append(lunch_main)
            remaining = [r for r in recipes if r not in excluded]
            dinner_rice = remaining[0] if remaining else lunch_rice
            is_dinner_combined = dinner_rice and _is_combined_dish(dinner_rice)
        
        if not is_dinner_combined and not dinner_main:
            # If plain rice but no main dish, try to find one
            excluded = [breakfast, lunch_rice, dinner_rice]
            if lunch_main:
                excluded.append(lunch_main)
            # CRITICAL: Calculate dynamic requirements based on remaining protein and kcal
            # Ensure we select dishes with sufficient nutrition to meet targets
            daily_protein = targets.get("protein_g", 150.0) if targets else 150.0
            daily_kcal = targets.get("tdee_kcal", 2000.0) if targets else 2000.0
            
            # Base requirements - increased to ensure better nutrition
            if daily_protein > 180:
                base_min_protein = 40.0  # Increased from 35.0
            elif daily_protein > 150:
                base_min_protein = 35.0  # Increased from 30.0
            else:
                base_min_protein = 30.0  # Increased from 25.0
            
            max_main_kcal = 700.0  # Increased from 550.0 to allow larger dishes
            min_main_protein = base_min_protein
            min_main_kcal = 200.0  # CRITICAL: Require minimum kcal to ensure sufficient nutrition
            
            if remaining_targets:
                protein_remaining = remaining_targets.get("protein_g", 0.0)
                kcal_remaining = remaining_targets.get("kcal", 0.0)
                protein_ratio = protein_remaining / daily_protein if daily_protein > 0 else 1.0
                kcal_ratio = kcal_remaining / daily_kcal if daily_kcal > 0 else 1.0
                
                # CRITICAL: If we still need a lot of nutrition, select larger dishes
                if protein_ratio > 0.5 or kcal_ratio > 0.5:
                    max_main_kcal = 800.0  # Increased from 650.0
                    min_main_protein = max(base_min_protein, 45.0)  # Increased from 40.0
                    min_main_kcal = 300.0  # Increased minimum kcal
                elif protein_remaining > daily_protein * 0.4 or kcal_remaining > daily_kcal * 0.4:
                    max_main_kcal = 750.0  # Increased from 600.0
                    min_main_protein = max(base_min_protein, 40.0)  # Increased from 35.0
                    min_main_kcal = 250.0
                elif protein_remaining > daily_protein * 0.2 or kcal_remaining > daily_kcal * 0.2:
                    min_main_protein = max(base_min_protein, 35.0)  # Increased from 30.0
                    min_main_kcal = 200.0
            elif targets:
                # If no remaining_targets but have targets, assume we need nutrition
                max_main_kcal = 700.0  # Increased from 600.0
                min_main_protein = base_min_protein
                min_main_kcal = 200.0
            
            logging.debug(
                f"DINNER_MAIN_SELECTION: "
                f"min_protein={min_main_protein:.1f}g | "
                f"min_kcal={min_main_kcal:.1f} | "
                f"max_kcal={max_main_kcal:.1f} | "
                f"remaining_protein={remaining_targets.get('protein_g', 0):.1f}g | "
                f"remaining_kcal={remaining_targets.get('kcal', 0):.1f}"
            )
            
            dinner_main = select_meal_by_strategy(
                recipes, "highest_protein", 
                exclude=excluded, 
                used_recipe_ids=recent_recipe_ids_set,
                preferred_meal_type="dinner", 
                dish_category="main",  # CRITICAL: Specify category to ensure correct selection
                target_macros=targets,
                require_macros=True,
                min_kcal=min_main_kcal,  # CRITICAL: Require minimum kcal for better nutrition
                max_kcal=max_main_kcal,  # CRITICAL: Dynamic kcal limit
                min_protein=min_main_protein,  # CRITICAL: Require minimum protein
            )
            
            if dinner_main:
                main_macros = _get_meal_macros(dinner_main)
                logging.debug(
                    f"DINNER_MAIN_SELECTED: {dinner_main.get('dish_name', 'Unknown')} | "
                    f"protein={main_macros.get('protein_g', 0):.1f}g | "
                    f"kcal={main_macros.get('kcal', 0):.1f} | "
                    f"fat={main_macros.get('fat_g', 0):.1f}g | "
                    f"carb={main_macros.get('carb_g', 0):.1f}g"
                )
            else:
                logging.warning(f"DINNER_MAIN_NOT_FOUND: No main dish found with requirements (min_protein={min_main_protein:.1f}g, min_kcal={min_main_kcal:.1f})")
            # CRITICAL: Validate dinner main is actually a main dish
            if dinner_main and not _is_main_dish(dinner_main):
                logging.warning(f"Selected dinner main '{dinner_main.get('dish_name', 'Unknown')}' is not a main dish, rejecting...")
                dinner_main = None
            # CRITICAL: If still no main, try without category restriction but still prioritize protein
            if not dinner_main:
                logging.warning("No dinner main found with category restriction, trying without category but prioritizing protein...")
                dinner_main = select_meal_by_strategy(
                    recipes, "highest_protein",
                    exclude=excluded,
                    used_recipe_ids=recent_recipe_ids_set,
                    preferred_meal_type="dinner",
                    target_macros=targets,
                    require_macros=True,
                    min_kcal=min_main_kcal if 'min_main_kcal' in locals() else 200.0,  # CRITICAL: Require minimum kcal
                    max_kcal=max_main_kcal,
                    min_protein=min_main_protein,
                )
                # Validate it's actually a main dish
                if dinner_main and not _is_main_dish(dinner_main):
                    dinner_main = None

        # Phase 3.2: Stream draft early (tên món) - MOVED to after supplementary dishes are added
        # This will be done after plan structure is built to include all supplementary dishes

        # Build plan with Vietnamese meal structure
        logging.debug(
            "plan_day_e2e_tool: selected dishes breakfast=%s lunch_rice=%s lunch_main=%s lunch_veg=%s lunch_fruit=%s dinner_rice=%s dinner_main=%s dinner_veg=%s dinner_fruit=%s",
            breakfast.get("dish_name") if breakfast else None,
            lunch_rice.get("dish_name") if lunch_rice else None,
            lunch_main.get("dish_name") if lunch_main else None,
            lunch_veg.get("dish_name") if lunch_veg else None,
            lunch_fruit.get("dish_name") if lunch_fruit else None,
            dinner_rice.get("dish_name") if dinner_rice else None,
            dinner_main.get("dish_name") if dinner_main else None,
            dinner_veg.get("dish_name") if dinner_veg else None,
            dinner_fruit.get("dish_name") if dinner_fruit else None,
        )
        # Calculate macros per meal for frontend display
        def _calculate_meal_macros(recipe: Dict[str, Any], servings: float = 1.0) -> Dict[str, float]:
            """Calculate total macros for a recipe with servings."""
            macros = _get_meal_macros(recipe)
            return {
                "kcal": macros["kcal"] * servings,
                "protein_g": macros["protein_g"] * servings,
                "fat_g": macros["fat_g"] * servings,
                "carb_g": macros["carb_g"] * servings,
            }
        
        # NOTE: lunch_supplementary_dishes and dinner_supplementary_dishes are initialized
        # earlier in the function (after breakfast planning) to ensure they exist when needed
        
        plan = {
            "breakfast": {
                "recipe": breakfast, 
                "servings": 1.0, 
                "meal_type": "breakfast",
                "macros": _calculate_meal_macros(breakfast, 1.0),
            },
            "lunch": {
                "recipe": lunch_rice,  # Primary dish (rice or combined dish)
                "servings": 1.0,
                "meal_type": "lunch",
                "accompaniments": []
            },
            "dinner": {
                "recipe": dinner_rice,  # Primary dish (rice or combined dish)
                "servings": 1.0,
                "meal_type": "dinner",
                "accompaniments": []
            },
        }
        
        # Add vegetables and fruits following Vietnamese meal patterns
        # Vietnamese lunch/dinner structure: 
        # - If combined dish (mì trộn, cơm chiên): Only add fruit
        # - If plain rice: Rice (carb) + Main dish (món mặn) + Vegetable/Canh (common) + Fruit (optional, less common)
        # Priority: Vegetable/Canh is more important than fruit in Vietnamese meals
        # Rule: Add vegetable if available, only add fruit if no vegetable (to avoid too many side dishes)
        
        # Lunch accompaniments
        # Only add main dish if not a combined dish or noodle dish
        if lunch_main and not is_lunch_combined and not is_lunch_noodle:
            lunch_main_macros = _get_meal_macros(lunch_main)
            if lunch_main_macros.get("kcal", 0) > 0:
                plan["lunch"]["accompaniments"].append({
                    "recipe": lunch_main,
                    "servings": 1.0,  # Always 1.0 serving
                    "type": "main",
                    "macros": _calculate_meal_macros(lunch_main, 1.0),
                })
        
        # Add soup (canh) - very common in Vietnamese rice meals
        if lunch_soup and not is_lunch_combined and not is_lunch_noodle:
            lunch_soup_macros = _get_meal_macros(lunch_soup)
            if lunch_soup_macros.get("kcal", 0) > 0:
                plan["lunch"]["accompaniments"].append({
                    "recipe": lunch_soup,
                    "servings": 1.0,  # Always 1.0 serving
                    "type": "soup",
                    "macros": _calculate_meal_macros(lunch_soup, 1.0),
                })
        
        if lunch_veg:
            lunch_veg_macros = _get_meal_macros(lunch_veg)
            if lunch_veg_macros.get("kcal", 0) > 0:  # Only add if has macros
                plan["lunch"]["accompaniments"].append({
                    "recipe": lunch_veg,
                    "servings": 1.0,  # Always 1.0 serving (Vietnamese meal pattern)
                    "type": "vegetable",
                    "macros": _calculate_meal_macros(lunch_veg, 1.0),
                })
        # Fruit is optional for lunch (less common in Vietnamese meals)
        # Only add fruit if vegetable was not added (to keep meal structure simple)
        elif lunch_fruit:  # Add fruit only if no vegetable
            lunch_fruit_macros = _get_meal_macros(lunch_fruit)
            if lunch_fruit_macros.get("kcal", 0) > 0:
                plan["lunch"]["accompaniments"].append({
                    "recipe": lunch_fruit,
                    "servings": 1.0,  # Always 1.0 serving
                    "type": "fruit",
                    "macros": _calculate_meal_macros(lunch_fruit, 1.0),
                })
        
        # Dinner accompaniments (same logic - prioritize vegetable over fruit)
        # Only add main dish if not a combined dish or noodle dish
        if dinner_main and not is_dinner_combined and not is_dinner_noodle:
            dinner_main_macros = _get_meal_macros(dinner_main)
            if dinner_main_macros.get("kcal", 0) > 0:
                plan["dinner"]["accompaniments"].append({
                    "recipe": dinner_main,
                    "servings": 1.0,  # Always 1.0 serving
                    "type": "main",
                    "macros": _calculate_meal_macros(dinner_main, 1.0),
                })
        
        # Add soup (canh) - very common in Vietnamese rice meals
        if dinner_soup and not is_dinner_combined and not is_dinner_noodle:
            dinner_soup_macros = _get_meal_macros(dinner_soup)
            if dinner_soup_macros.get("kcal", 0) > 0:
                plan["dinner"]["accompaniments"].append({
                    "recipe": dinner_soup,
                    "servings": 1.0,  # Always 1.0 serving
                    "type": "soup",
                    "macros": _calculate_meal_macros(dinner_soup, 1.0),
                })
        
        if dinner_veg:
            dinner_veg_macros = _get_meal_macros(dinner_veg)
            if dinner_veg_macros.get("kcal", 0) > 0:  # Only add if has macros
                plan["dinner"]["accompaniments"].append({
                    "recipe": dinner_veg,
                    "servings": 1.0,  # Always 1.0 serving (Vietnamese meal pattern)
                    "type": "vegetable",
                    "macros": _calculate_meal_macros(dinner_veg, 1.0),
                })
        # Fruit is optional for dinner (less common in Vietnamese meals)
        elif dinner_fruit:  # Add fruit only if no vegetable
            dinner_fruit_macros = _get_meal_macros(dinner_fruit)
            if dinner_fruit_macros.get("kcal", 0) > 0:
                plan["dinner"]["accompaniments"].append({
                    "recipe": dinner_fruit,
                    "servings": 1.0,  # Always 1.0 serving
                    "type": "fruit",
                    "macros": _calculate_meal_macros(dinner_fruit, 1.0),
                })
        
        # CRITICAL: Add unassigned supplementary dishes to plan accompaniments
        # These are additional dishes that were added to meet nutrition targets but didn't fit into existing slots
        for supp_dish in lunch_supplementary_dishes:
            dish_name = supp_dish.get('dish_name', 'Unknown')
            dish_macros = _get_meal_macros(supp_dish)
            if dish_macros.get("kcal", 0) > 0:
                # Determine dish type
                dish_type = "main"
                if _is_vegetable_dish(supp_dish):
                    dish_type = "vegetable"
                elif _is_soup(supp_dish):
                    dish_type = "soup"
                elif _is_fruit(supp_dish):
                    dish_type = "fruit"
                
                plan["lunch"]["accompaniments"].append({
                    "recipe": supp_dish,
                    "servings": 1.0,
                    "type": dish_type,
                    "macros": _calculate_meal_macros(supp_dish, 1.0),
                })
                logging.debug(
                    f"PLAN_LUNCH_ADD_SUPP: Added {dish_name} ({dish_type}) to plan accompaniments | "
                    f"kcal={dish_macros.get('kcal', 0):.1f} | protein={dish_macros.get('protein_g', 0):.1f}g"
                )
        
        for supp_dish in dinner_supplementary_dishes:
            dish_name = supp_dish.get('dish_name', 'Unknown')
            dish_macros = _get_meal_macros(supp_dish)
            if dish_macros.get("kcal", 0) > 0:
                # Determine dish type
                dish_type = "main"
                if _is_vegetable_dish(supp_dish):
                    dish_type = "vegetable"
                elif _is_soup(supp_dish):
                    dish_type = "soup"
                elif _is_fruit(supp_dish):
                    dish_type = "fruit"
                
                plan["dinner"]["accompaniments"].append({
                    "recipe": supp_dish,
                    "servings": 1.0,
                    "type": dish_type,
                    "macros": _calculate_meal_macros(supp_dish, 1.0),
                })
                logging.debug(
                    f"PLAN_DINNER_ADD_SUPP: Added {dish_name} ({dish_type}) to plan accompaniments | "
                    f"kcal={dish_macros.get('kcal', 0):.1f} | protein={dish_macros.get('protein_g', 0):.1f}g"
                )
        
        # Log total accompaniments count
        logging.debug(
            f"PLAN_ACCOMPANIMENTS_COUNT: lunch={len(plan['lunch']['accompaniments'])} | "
            f"dinner={len(plan['dinner']['accompaniments'])} | "
            f"lunch_supp={len(lunch_supplementary_dishes)} | dinner_supp={len(dinner_supplementary_dishes)}"
        )
        
        # CRITICAL: Check if a meal has too many main dishes (3-4), replace with soup/vegetable
        def check_and_replace_excess_main_dishes(meal_slot: str, meal_plan: dict, recipes_list: list, recent_recipe_ids_set: set):
            """Check if meal has too many main dishes and replace with soup/vegetable if needed."""
            meal_accompaniments = meal_plan.get("accompaniments", [])
            meal_recipe = meal_plan.get("recipe")  # Primary dish (rice or combined dish)
            
            # Count main dishes: include main dish in accompaniments AND primary dish if it's a main dish
            main_dishes = [acc for acc in meal_accompaniments if acc.get("type") == "main"]
            main_count = len(main_dishes)
            
            # Also check if primary dish is a main dish (e.g., "Sườn Nướng Cơm Tấm Sài Gòn")
            if meal_recipe and _is_main_dish(meal_recipe):
                main_count += 1
            
            if main_count >= 3:
                logging.warning(f"{meal_slot.upper()}_TOO_MANY_MAIN: Found {main_count} main dishes (primary={meal_recipe.get('dish_name', 'None') if meal_recipe and _is_main_dish(meal_recipe) else 'None'}, accompaniments={len([acc for acc in meal_accompaniments if acc.get('type') == 'main'])})), attempting to replace with soup/vegetable")
                
                # Calculate how many main dishes to replace (if 4+, replace 2; if 3, replace 1)
                num_to_replace = 2 if main_count >= 4 else 1
                
                # Get list of main dishes to consider for replacement (only from accompaniments, not primary dish)
                main_dishes_to_replace = sorted(main_dishes, key=lambda acc: acc.get("macros", {}).get("protein_g", 0))[:num_to_replace]
                
                # Get excluded recipe IDs (already used in this meal)
                excluded_ids = {str(acc.get("recipe", {}).get("food_id", "")) for acc in meal_accompaniments if acc.get("recipe", {}).get("food_id")}
                if meal_recipe and meal_recipe.get("food_id"):
                    excluded_ids.add(str(meal_recipe.get("food_id")))
                excluded_ids.update(str(rid) for rid in recent_recipe_ids_set)
                
                # Build excluded list for select_meal_by_strategy
                excluded_recipes = [acc.get("recipe") for acc in meal_accompaniments if acc.get("recipe")]
                if meal_recipe:
                    excluded_recipes.append(meal_recipe)
                
                replacements_made = 0
                for main_to_replace in main_dishes_to_replace:
                    if replacements_made >= num_to_replace:
                        break
                    
                    replacement_found = False
                    
                    # CRITICAL: Directly filter and select soup/vegetable from recipes_list
                    # First try soup (preferred replacement)
                    soup_candidates = [
                        r for r in recipes_list 
                        if str(r.get("food_id", "")) not in excluded_ids
                        and str(r.get("food_id", "")) not in [str(rid) for rid in recent_recipe_ids_set]
                        and _is_soup(r) 
                        and not _is_main_dish(r)
                        and _get_meal_macros(r).get("kcal", 0) >= 30.0
                        and _get_meal_macros(r).get("kcal", 0) <= 200.0
                    ]
                    
                    if soup_candidates:
                        # Sort by kcal (prefer lighter soups) and select first
                        soup_candidates.sort(key=lambda r: _get_meal_macros(r).get("kcal", 0))
                        soup_candidate = soup_candidates[0]
                        
                        # Replace main dish with soup
                        meal_accompaniments.remove(main_to_replace)
                        meal_accompaniments.append({
                            "recipe": soup_candidate,
                            "servings": 1.0,
                            "type": "soup",
                            "macros": _calculate_meal_macros(soup_candidate, 1.0),
                        })
                        excluded_recipes.append(soup_candidate)
                        excluded_ids.add(str(soup_candidate.get("food_id", "")))
                        logging.info(f"{meal_slot.upper()}_REPLACED_MAIN_WITH_SOUP: Replaced '{main_to_replace.get('recipe', {}).get('dish_name', 'Unknown')}' with '{soup_candidate.get('dish_name', 'Unknown')}'")
                        replacement_found = True
                        replacements_made += 1
                    
                    # If soup not found, try vegetable
                    if not replacement_found:
                        veg_candidates = [
                            r for r in recipes_list 
                            if str(r.get("food_id", "")) not in excluded_ids
                            and str(r.get("food_id", "")) not in [str(rid) for rid in recent_recipe_ids_set]
                            and _is_vegetable_dish(r) 
                            and not _is_main_dish(r)
                            and _get_meal_macros(r).get("kcal", 0) >= 30.0
                            and _get_meal_macros(r).get("kcal", 0) <= 250.0
                        ]
                        
                        if veg_candidates:
                            # Sort by kcal (prefer lighter vegetables) and select first
                            veg_candidates.sort(key=lambda r: _get_meal_macros(r).get("kcal", 0))
                            veg_candidate = veg_candidates[0]
                            
                            meal_accompaniments.remove(main_to_replace)
                            meal_accompaniments.append({
                                "recipe": veg_candidate,
                                "servings": 1.0,
                                "type": "vegetable",
                                "macros": _calculate_meal_macros(veg_candidate, 1.0),
                            })
                            excluded_recipes.append(veg_candidate)
                            excluded_ids.add(str(veg_candidate.get("food_id", "")))
                            logging.info(f"{meal_slot.upper()}_REPLACED_MAIN_WITH_VEG: Replaced '{main_to_replace.get('recipe', {}).get('dish_name', 'Unknown')}' with '{veg_candidate.get('dish_name', 'Unknown')}'")
                            replacement_found = True
                            replacements_made += 1
                    
                    if not replacement_found:
                        logging.warning(f"{meal_slot.upper()}_REPLACE_FAILED: Could not find suitable soup/vegetable to replace '{main_to_replace.get('recipe', {}).get('dish_name', 'Unknown')}'")
                
                if replacements_made > 0:
                    logging.info(f"{meal_slot.upper()}_REPLACEMENT_SUMMARY: Replaced {replacements_made} main dish(es) with soup/vegetable")
        
        # Check and replace excess main dishes for lunch and dinner
        check_and_replace_excess_main_dishes("lunch", plan["lunch"], recipes, recent_recipe_ids_set)
        check_and_replace_excess_main_dishes("dinner", plan["dinner"], recipes, recent_recipe_ids_set)
        
        def _scale_meal_if_needed(meal_key: str, cap_kcal: float, cap_fat: float) -> None:
            meal = plan.get(meal_key)
            if not meal:
                return
            meal_kcal = meal["recipe"] and _get_meal_macros(meal["recipe"]).get("kcal", 0.0) or 0.0
            meal_fat = meal["recipe"] and _get_meal_macros(meal["recipe"]).get("fat_g", 0.0) or 0.0
            for acc in meal.get("accompaniments", []):
                acc_macros = _get_meal_macros(acc.get("recipe", {}))
                meal_kcal += acc_macros.get("kcal", 0.0) * acc.get("servings", 1.0)
                meal_fat += acc_macros.get("fat_g", 0.0) * acc.get("servings", 1.0)

            scale_factors = [1.0]
            if cap_kcal and meal_kcal > cap_kcal:
                scale_factors.append(cap_kcal / meal_kcal)
            if cap_fat and meal_fat > cap_fat:
                scale_factors.append(cap_fat / meal_fat)
            scale = max(0.5, min(scale_factors))
            if scale < 0.999:
                logging.warning(
                    "%s_SCALING: meal_kcal=%.1f meal_fat=%.1f cap_kcal=%.1f cap_fat=%.1f scale=%.3f",
                    meal_key.upper(), meal_kcal, meal_fat, cap_kcal, cap_fat, scale
                )
                meal["servings"] = round(meal.get("servings", 1.0) * scale, 3)
                for acc in meal.get("accompaniments", []):
                    acc["servings"] = round(acc.get("servings", 1.0) * scale, 3)

        # Apply per-meal caps (kcal + fat) before final macro calc
        _scale_meal_if_needed("breakfast", breakfast_max_kcal, 25.0)
        _scale_meal_if_needed("lunch", lunch_max_kcal, 60.0)
        _scale_meal_if_needed("dinner", dinner_max_kcal, 60.0)

        # Phase 3.2: Stream draft meal plan AFTER supplementary dishes are added to plan structure
        # This ensures all dishes (including supplementary) are displayed
        yield Response("📋 Draft meal plan:")
        breakfast_name = breakfast.get("dish_name", "Unknown") if breakfast else "Not selected"
        yield Response(f"  🌅 Breakfast: {breakfast_name}")
        
        if lunch_rice:
            lunch_items = [lunch_rice.get("dish_name", "Unknown")]
            # Include all accompaniments (main, soup, veg, fruit, and supplementary dishes)
            for acc in plan.get("lunch", {}).get("accompaniments", []):
                acc_name = acc.get("recipe", {}).get("dish_name", "Unknown")
                if acc_name not in lunch_items:  # Avoid duplicates
                    lunch_items.append(acc_name)
            yield Response(f"  🍽️ Lunch: {', '.join(lunch_items)}")
        
        if dinner_rice:
            dinner_items = [dinner_rice.get("dish_name", "Unknown")]
            # Include all accompaniments (main, soup, veg, fruit, and supplementary dishes)
            for acc in plan.get("dinner", {}).get("accompaniments", []):
                acc_name = acc.get("recipe", {}).get("dish_name", "Unknown")
                if acc_name not in dinner_items:  # Avoid duplicates
                    dinner_items.append(acc_name)
            yield Response(f"  🌙 Dinner: {', '.join(dinner_items)}")
        
        yield Response("⚖️ Calculating nutrition details...")

        def _recompute_meal_macros(plan_dict: Dict[str, Any]) -> None:
            """Recalculate per-meal macros based on current servings (includes accompaniments)."""
            for meal_key in ("breakfast", "lunch", "dinner"):
                meal_data = plan_dict.get(meal_key, {})
                recipe_obj = meal_data.get("recipe")
                servings = meal_data.get("servings", 1.0)
                if not recipe_obj:
                    continue

                meal_macros = _calculate_meal_macros(recipe_obj, servings)
                for acc in meal_data.get("accompaniments", []):
                    acc_recipe = acc.get("recipe")
                    acc_servings = acc.get("servings", 1.0)
                    if acc_recipe:
                        acc_macros = _calculate_meal_macros(acc_recipe, acc_servings)
                        for k in meal_macros:
                            meal_macros[k] += acc_macros[k]

                meal_data["macros"] = meal_macros
                meal_data["macros_main"] = _calculate_meal_macros(recipe_obj, servings)
                meal_data["macros_total"] = meal_macros

        def _calculate_plan_totals(plan_dict: Dict[str, Any]) -> Dict[str, float]:
            """Aggregate macros for the entire plan."""
            totals = {"kcal": 0.0, "protein_g": 0.0, "fat_g": 0.0, "carb_g": 0.0}
            for meal_data in plan_dict.values():
                recipe_obj = meal_data.get("recipe")
                servings = meal_data.get("servings", 1.0)
                if recipe_obj:
                    macros = _get_meal_macros(recipe_obj)
                    for k in totals:
                        totals[k] += macros.get(k, 0.0) * servings
                for acc in meal_data.get("accompaniments", []):
                    acc_recipe = acc.get("recipe")
                    acc_servings = acc.get("servings", 1.0)
                    if acc_recipe:
                        acc_macros = _get_meal_macros(acc_recipe)
                        for k in totals:
                            totals[k] += acc_macros.get(k, 0.0) * acc_servings
            return totals

        # Initial macro calculation
        _recompute_meal_macros(plan)

        # Ensure all recipes in plan have macros (refresh from Weaviate if needed)
        for meal_data in plan.values():
            recipe_obj = meal_data.get("recipe", {})
            if recipe_obj:
                await _ensure_recipe_macros_cached(
                    recipe_obj,
                    tree_data=tree_data,
                    client_manager=client_manager,
                )
            
            # Check accompaniments too
            for acc in meal_data.get("accompaniments", []):
                acc_recipe = acc.get("recipe", {})
                if acc_recipe:
                    await _ensure_recipe_macros_cached(
                        acc_recipe,
                        tree_data=tree_data,
                        client_manager=client_manager,
                    )

        # Calculate total macros (including accompaniments for Vietnamese meals)
        total_macros = _calculate_plan_totals(plan)

        # Calculate coverage percentages
        target_kcal = targets.get("tdee_kcal", 0.0) if targets else 0.0
        target_protein = targets.get("protein_g", 0.0) if targets else 0.0
        target_fat = targets.get("fat_g", 0.0) if targets else 0.0
        target_carb = targets.get("carb_g", 0.0) if targets else 0.0
        
        # CRITICAL: Verify total_macros matches actual consumed (for debugging)
        # Calculate actual consumed from breakfast + lunch + dinner totals
        breakfast_macros_verify = _get_meal_macros(breakfast) if breakfast else {"kcal": 0.0, "protein_g": 0.0, "fat_g": 0.0, "carb_g": 0.0}
        lunch_total_macros_verify = plan["lunch"]["macros_total"]
        dinner_total_macros_verify = plan["dinner"]["macros_total"]
        
        actual_total_kcal = breakfast_macros_verify.get("kcal", 0.0) + lunch_total_macros_verify.get("kcal", 0.0) + dinner_total_macros_verify.get("kcal", 0.0)
        actual_total_protein = breakfast_macros_verify.get("protein_g", 0.0) + lunch_total_macros_verify.get("protein_g", 0.0) + dinner_total_macros_verify.get("protein_g", 0.0)
        actual_total_fat = breakfast_macros_verify.get("fat_g", 0.0) + lunch_total_macros_verify.get("fat_g", 0.0) + dinner_total_macros_verify.get("fat_g", 0.0)
        actual_total_carb = breakfast_macros_verify.get("carb_g", 0.0) + lunch_total_macros_verify.get("carb_g", 0.0) + dinner_total_macros_verify.get("carb_g", 0.0)
        
        # Check for mismatch
        kcal_diff = abs(total_macros["kcal"] - actual_total_kcal)
        protein_diff = abs(total_macros["protein_g"] - actual_total_protein)
        
        if kcal_diff > 5.0 or protein_diff > 5.0:
            logging.warning(
                f"PLAN_MACROS_MISMATCH: plan totals vs actual consumed | "
                f"plan: kcal={total_macros['kcal']:.1f}, protein={total_macros['protein_g']:.1f}g | "
                f"actual: kcal={actual_total_kcal:.1f}, protein={actual_total_protein:.1f}g | "
                f"diff: kcal={kcal_diff:.1f}, protein={protein_diff:.1f}g | "
                f"lunch_accompaniments={len(plan['lunch']['accompaniments'])} | "
                f"dinner_accompaniments={len(plan['dinner']['accompaniments'])}"
            )
            # Use actual totals for more accurate coverage calculation
            total_macros["kcal"] = actual_total_kcal
            total_macros["protein_g"] = actual_total_protein
            total_macros["fat_g"] = actual_total_fat
            total_macros["carb_g"] = actual_total_carb
        else:
            logging.debug(
                f"PLAN_MACROS_VERIFY: plan totals match actual consumed | "
                f"kcal={total_macros['kcal']:.1f}, protein={total_macros['protein_g']:.1f}g"
            )
        
        # Clamp plan down if it overshoots kcal/fat/carb targets beyond tolerance
        max_allowed_kcal = target_kcal * (1.0 + macro_tolerance_percent) if target_kcal else 0.0
        max_allowed_fat = target_fat * (1.0 + macro_tolerance_percent) if target_fat else 0.0
        max_allowed_carb = target_carb * (1.0 + macro_tolerance_percent) if target_carb else 0.0

        def _multi_macro_scale(current: Dict[str, float]) -> float:
            scales = [1.0]
            if max_allowed_kcal and current.get("kcal", 0) > max_allowed_kcal:
                scales.append(max_allowed_kcal / current["kcal"])
            if max_allowed_fat and current.get("fat_g", 0) > max_allowed_fat:
                scales.append(max_allowed_fat / current["fat_g"])
            if max_allowed_carb and current.get("carb_g", 0) > max_allowed_carb:
                scales.append(max_allowed_carb / current["carb_g"])
            return max(0.5, min(scales))

        scale = _multi_macro_scale(total_macros)
        if scale < 0.999:
            logging.warning(
                "PLAN_SCALING: scaling servings by %.3f due to overshoot "
                "(kcal %.1f/%.1f, fat %.1f/%.1f, carb %.1f/%.1f, tol=%.0f%%)",
                scale,
                total_macros.get("kcal", 0.0), max_allowed_kcal,
                total_macros.get("fat_g", 0.0), max_allowed_fat,
                total_macros.get("carb_g", 0.0), max_allowed_carb,
                macro_tolerance_percent * 100,
            )
            for meal_data in plan.values():
                meal_data["servings"] = round(meal_data.get("servings", 1.0) * scale, 3)
                for acc in meal_data.get("accompaniments", []):
                    acc["servings"] = round(acc.get("servings", 1.0) * scale, 3)

            _recompute_meal_macros(plan)
            total_macros = _calculate_plan_totals(plan)

        logging.debug(
            "plan_day_e2e_tool: plan macros totals kcal=%.1f protein=%.1f fat=%.1f carb=%.1f | targets=%s",
            total_macros["kcal"],
            total_macros["protein_g"],
            total_macros["fat_g"],
            total_macros["carb_g"],
            targets,
        )

        # Calculate coverage percentages
        kcal_coverage = (total_macros["kcal"] / target_kcal * 100) if target_kcal > 0 else 0.0
        protein_coverage = (total_macros["protein_g"] / target_protein * 100) if target_protein > 0 else 0.0
        fat_coverage = (total_macros["fat_g"] / target_fat * 100) if target_fat > 0 else 0.0
        carb_coverage = (total_macros["carb_g"] / target_carb * 100) if target_carb > 0 else 0.0

        # Calculate deficits
        kcal_deficit = target_kcal - total_macros["kcal"]
        protein_deficit = target_protein - total_macros["protein_g"]
        fat_deficit = target_fat - total_macros["fat_g"]
        carb_deficit = target_carb - total_macros["carb_g"]

        logging.info(
            "plan_day_e2e_tool: NUTRITION_COVERAGE | "
            "kcal=%.1f%% (%.1f/%.1f, deficit=%.1f) | "
            "protein=%.1f%% (%.1f/%.1f, deficit=%.1f) | "
            "fat=%.1f%% (%.1f/%.1f, deficit=%.1f) | "
            "carb=%.1f%% (%.1f/%.1f, deficit=%.1f)",
            kcal_coverage, total_macros["kcal"], target_kcal, kcal_deficit,
            protein_coverage, total_macros["protein_g"], target_protein, protein_deficit,
            fat_coverage, total_macros["fat_g"], target_fat, fat_deficit,
            carb_coverage, total_macros["carb_g"], target_carb, carb_deficit,
        )
        
        # Warnings for significant excess
        if fat_coverage > 150.0:
            logging.warning(f"NUTRITION_WARNING: Fat excess is very high ({fat_coverage:.1f}%) - consider reducing high-fat dishes")
        if kcal_coverage > 130.0:
            logging.warning(f"NUTRITION_WARNING: Kcal excess is high ({kcal_coverage:.1f}%) - consider reducing portion sizes")
        if carb_coverage > 130.0:
            logging.warning(f"NUTRITION_WARNING: Carb excess is high ({carb_coverage:.1f}%) - consider reducing high-carb dishes")
        if protein_coverage < 90.0:
            logging.warning(f"NUTRITION_WARNING: Protein coverage is low ({protein_coverage:.1f}%) - consider adding more protein-rich dishes")
        
        # CRITICAL: Log warning if coverage is too low
        if kcal_coverage < 80.0 or protein_coverage < 80.0:
            logging.warning(
                "plan_day_e2e_tool: LOW_NUTRITION_COVERAGE | "
                "kcal=%.1f%% (need %.1f more) | "
                "protein=%.1f%% (need %.1f more) | "
                "This indicates the meal planning algorithm needs improvement",
                kcal_coverage, kcal_deficit,
                protein_coverage, protein_deficit,
            )
            
            # CRITICAL: Call LLM to suggest additional dishes when nutrition is deficient
            try:
                yield Response("💡 Getting AI suggestions for additional dishes to meet nutrition targets...")
                # Prepare context for LLM
                deficit_info = []
                if kcal_coverage < 80.0:
                    deficit_info.append(f"thiếu {kcal_deficit:.0f} kcal ({100 - kcal_coverage:.1f}%)")
                if protein_coverage < 80.0:
                    deficit_info.append(f"thiếu {protein_deficit:.0f}g protein ({100 - protein_coverage:.1f}%)")
                if fat_coverage < 80.0:
                    deficit_info.append(f"thiếu {fat_deficit:.0f}g chất béo ({100 - fat_coverage:.1f}%)")
                if carb_coverage < 80.0:
                    deficit_info.append(f"thiếu {carb_deficit:.0f}g carb ({100 - carb_coverage:.1f}%)")
                
                deficit_text = ", ".join(deficit_info)
                llm_suggestion_query = f"Kế hoạch bữa ăn hiện tại {deficit_text}. Hãy gợi ý 3-5 món ăn Việt Nam bổ sung để đáp ứng đủ mục tiêu dinh dưỡng."
                
                # Get LLM suggestions
                if tree_data and base_lm:
                    # Collect all selected dish names for meal history
                    selected_dish_names = []
                    if breakfast:
                        selected_dish_names.append(breakfast.get("dish_name", ""))
                    for acc in plan.get("lunch", {}).get("accompaniments", []):
                        dish_name = acc.get("recipe", {}).get("dish_name", "")
                        if dish_name:
                            selected_dish_names.append(dish_name)
                    for acc in plan.get("dinner", {}).get("accompaniments", []):
                        dish_name = acc.get("recipe", {}).get("dish_name", "")
                        if dish_name:
                            selected_dish_names.append(dish_name)
                    
                    additional_suggestions = await generate_llm_draft(
                        meal_slot="general",
                        query=llm_suggestion_query,
                        meal_history=selected_dish_names,
                        constraints=constraints,
                        base_lm=base_lm,
                        tree_data=tree_data,
                    )
                    
                    if additional_suggestions and additional_suggestions.suggestions:
                        suggestion_names = [s.dish_name for s in additional_suggestions.suggestions[:5]]
                        yield Response(f"💡 AI gợi ý thêm món: {', '.join(suggestion_names)}")
                        logging.info(f"LLM_SUGGESTION_DEFICIT: Suggested {len(suggestion_names)} additional dishes to meet nutrition targets")
            except Exception as e:
                logging.warning(f"Failed to get LLM suggestions for nutrition deficit: {e}")
        logging.debug(
            "plan_day_e2e_tool: meal macros breakfast=%s lunch_main=%s lunch_total=%s dinner_main=%s dinner_total=%s accompaniments_lunch=%s accompaniments_dinner=%s",
            plan["breakfast"]["macros"],
            plan["lunch"]["macros_main"],
            plan["lunch"]["macros_total"],
            plan["dinner"]["macros_main"],
            plan["dinner"]["macros_total"],
            [(acc.get('type'), acc.get('macros')) for acc in plan['lunch'].get('accompaniments', [])],
            [(acc.get('type'), acc.get('macros')) for acc in plan['dinner'].get('accompaniments', [])],
        )
        # Emit response so frontend can compare calculations
        # Use consistent formatting with 1 decimal place for consistency
        yield Response(
            f"📊 Plan macros: {total_macros['kcal']:.1f} kcal | "
            f"{total_macros['protein_g']:.1f}g protein | "
            f"{total_macros['fat_g']:.1f}g fat | "
            f"{total_macros['carb_g']:.1f}g carbs"
        )

        # Step 4.5: Keep all servings at 1.0 (Vietnamese meal pattern - fixed portions)
        # Vietnamese meals typically use standard serving sizes (1 serving per dish)
        # No scaling needed - recipes should be designed for 1 serving
        if targets and total_macros.get("kcal", 0) > 0:
            # Ensure all servings are exactly 1.0
            if "breakfast" in plan:
                plan["breakfast"]["servings"] = 1.0
            
            if "lunch" in plan:
                plan["lunch"]["servings"] = 1.0
                for acc in plan["lunch"].get("accompaniments", []):
                    acc["servings"] = 1.0
            
            if "dinner" in plan:
                plan["dinner"]["servings"] = 1.0
                for acc in plan["dinner"].get("accompaniments", []):
                    acc["servings"] = 1.0
                    
            # Recalculate total macros and per-meal macros with fixed 1.0 servings
            total_macros = {"kcal": 0.0, "protein_g": 0.0, "fat_g": 0.0, "carb_g": 0.0}
            for meal_key, meal_data in plan.items():
                recipe = meal_data["recipe"]
                servings = 1.0  # Always 1.0 serving
                macros = _get_meal_macros(recipe)
                meal_macros = {k: macros[k] * servings for k in macros}
                
                accompaniments = meal_data.get("accompaniments", [])
                for acc in accompaniments:
                    acc_recipe = acc.get("recipe")
                    acc_servings = 1.0  # Always 1.0 serving
                    if acc_recipe:
                        acc_macros = _get_meal_macros(acc_recipe)
                        for k in meal_macros:
                            meal_macros[k] += acc_macros[k] * acc_servings
                
                # Update per-meal macros
                meal_data["macros"] = meal_macros
                
                # Update macros_main and macros_total for lunch/dinner
                if meal_key in ["lunch", "dinner"]:
                    meal_data["macros_main"] = {k: macros[k] * servings for k in macros}
                    meal_data["macros_total"] = meal_macros.copy()
                
                # Add to total
                for k in total_macros:
                    total_macros[k] += meal_macros[k]
            
            # Phase 1.2: Iterative adjust - try swapping alternatives if deviation is large
            if targets:
                target_kcal = targets.get("tdee_kcal", 2000)
                current_kcal = total_macros.get("kcal", 0)
                
                # Calculate overall deviation score
                overall_deviation = _calculate_total_deviation_score(total_macros, targets)
                
                # Check if deviation is significant (>20% for kcal or >15% overall)
                kcal_deviation_pct = abs(current_kcal - target_kcal) / target_kcal if target_kcal > 0 else 1.0
                if current_kcal > 0 and (kcal_deviation_pct > 0.2 or overall_deviation > 0.15):
                    yield Response(f"🔄 Trying alternative recipes to improve macro fit...")
                    
                    # Calculate meal targets for comparison
                    lunch_targets = _calculate_meal_targets(targets, "lunch")
                    dinner_targets = _calculate_meal_targets(targets, "dinner")
                    breakfast_targets = _calculate_meal_targets(targets, "breakfast")
                    
                    swaps_made = 0
                    max_swaps = 8  # Increased to allow more swaps for better overall balance
                    max_iterations = 5  # Increased from 3 to 5 to allow more dishes to be added
                    iteration = 0
                    
                    # Keep track of best overall score
                    best_overall_score = overall_deviation
                    best_plan_state = None
                    
                    # Iterative swapping: try to improve overall balance
                    while iteration < max_iterations and swaps_made < max_swaps:
                        iteration += 1
                        improved = False
                        
                        # Calculate current overall deviation
                        current_total_macros = {"kcal": 0.0, "protein_g": 0.0, "fat_g": 0.0, "carb_g": 0.0}
                        for meal_key, meal_data in plan.items():
                            recipe = meal_data.get("recipe", {})
                            servings = meal_data.get("servings", 1.0)
                            macros = _get_meal_macros(recipe)
                            meal_macros = {k: macros[k] * servings for k in macros}
                            
                            accompaniments = meal_data.get("accompaniments", [])
                            for acc in accompaniments:
                                acc_recipe = acc.get("recipe")
                                acc_servings = acc.get("servings", 1.0)
                                if acc_recipe:
                                    acc_macros = _get_meal_macros(acc_recipe)
                                    for k in meal_macros:
                                        meal_macros[k] += acc_macros[k] * acc_servings
                            
                            for k in current_total_macros:
                                current_total_macros[k] += meal_macros[k]
                        
                        current_overall_score = _calculate_total_deviation_score(current_total_macros, targets)
                        
                        # Try swapping lunch main if deviation is large
                        if "lunch" in plan and swaps_made < max_swaps:
                            lunch_data = plan["lunch"]
                        lunch_main = None
                        lunch_carb = lunch_data.get("recipe", {})
                        accompaniments = lunch_data.get("accompaniments", [])
                        
                        for acc in accompaniments:
                            if acc.get("type") == "main":
                                lunch_main = acc.get("recipe", {})
                                break
                        
                        if lunch_main:
                            # Calculate current meal macros
                            main_macros = _get_meal_macros(lunch_main)
                            main_servings = next((acc.get("servings", 1.0) for acc in accompaniments if acc.get("type") == "main"), 1.0)
                            carb_macros = _get_meal_macros(lunch_carb)
                            carb_servings = lunch_data.get("servings", 1.0)
                            
                            current_meal_macros = {
                                "kcal": main_macros.get("kcal", 0) * main_servings + carb_macros.get("kcal", 0) * carb_servings,
                                "protein_g": main_macros.get("protein_g", 0) * main_servings + carb_macros.get("protein_g", 0) * carb_servings,
                                "fat_g": main_macros.get("fat_g", 0) * main_servings + carb_macros.get("fat_g", 0) * carb_servings,
                                "carb_g": main_macros.get("carb_g", 0) * main_servings + carb_macros.get("carb_g", 0) * carb_servings,
                            }
                            
                            # Add veg/fruit/soup macros
                            for acc in accompaniments:
                                if acc.get("type") in ["vegetable", "fruit", "soup"]:
                                    acc_macros = _get_meal_macros(acc.get("recipe", {}))
                                    acc_servings = acc.get("servings", 1.0)
                                    for k in current_meal_macros:
                                        current_meal_macros[k] += acc_macros.get(k, 0) * acc_servings
                            
                            # Check if deviation is large for this meal
                            meal_deviation = _calculate_total_deviation_score(current_meal_macros, lunch_targets)
                            if meal_deviation > 0.2:  # >20% deviation
                                # Get alternative main dishes from recipes (with kcal filter)
                                alternative_mains = [
                                    r for r in recipes
                                    if r.get("food_id") != lunch_main.get("food_id")
                                    and _is_main_dish(r)
                                    and not _is_combined_dish(r)  # Exclude combined dishes
                                    and r.get("macros_per_serving", {}).get("kcal", 0) > 0
                                    and r.get("macros_per_serving", {}).get("kcal", 0) <= 500.0  # Filter out dishes that are too high in kcal
                                ][:5]  # Try top 5 alternatives for better selection
                                
                                if alternative_mains:
                                    best_main, best_scale, best_score = _try_swap_alternatives(
                                        lunch_main,
                                        alternative_mains,
                                        lunch_targets,
                                        "main",
                                        main_servings,
                                        max_alternatives=5,  # Increased from 2 to 5 for better selection
                                    )
                                    
                                    if best_main and best_score < meal_deviation:
                                        # Temporarily swap to check overall improvement
                                        temp_plan_state = {}
                                        for acc in accompaniments:
                                            if acc.get("type") == "main":
                                                temp_plan_state["old_recipe"] = acc.get("recipe")
                                                temp_plan_state["old_servings"] = acc.get("servings", 1.0)
                                                acc["recipe"] = best_main
                                                acc["servings"] = 1.0
                                                break
                                        
                                        # Recalculate total macros with swap
                                        temp_total_macros = {"kcal": 0.0, "protein_g": 0.0, "fat_g": 0.0, "carb_g": 0.0}
                                        for meal_key, meal_data in plan.items():
                                            recipe = meal_data.get("recipe", {})
                                            servings = meal_data.get("servings", 1.0)
                                            macros = _get_meal_macros(recipe)
                                            meal_macros = {k: macros[k] * servings for k in macros}
                                            
                                            accompaniments_temp = meal_data.get("accompaniments", [])
                                            for acc in accompaniments_temp:
                                                acc_recipe = acc.get("recipe")
                                                acc_servings = acc.get("servings", 1.0)
                                                if acc_recipe:
                                                    acc_macros = _get_meal_macros(acc_recipe)
                                                    for k in meal_macros:
                                                        meal_macros[k] += acc_macros[k] * acc_servings
                                            
                                            for k in temp_total_macros:
                                                temp_total_macros[k] += meal_macros[k]
                                        
                                        temp_overall_score = _calculate_total_deviation_score(temp_total_macros, targets)
                                        
                                        # Only keep swap if it improves overall balance
                                        if temp_overall_score < current_overall_score:
                                            swaps_made += 1
                                            improved = True
                                            current_overall_score = temp_overall_score
                                            if temp_overall_score < best_overall_score:
                                                best_overall_score = temp_overall_score
                                        else:
                                            # Revert swap
                                            for acc in accompaniments:
                                                if acc.get("type") == "main":
                                                    acc["recipe"] = temp_plan_state.get("old_recipe")
                                                    acc["servings"] = temp_plan_state.get("old_servings", 1.0)
                                                    break
                        
                        # Try swapping dinner main if deviation is large
                        if "dinner" in plan and swaps_made < max_swaps:
                            dinner_data = plan["dinner"]
                            dinner_main = None
                            dinner_carb = dinner_data.get("recipe", {})
                            accompaniments = dinner_data.get("accompaniments", [])
                            
                            for acc in accompaniments:
                                if acc.get("type") == "main":
                                    dinner_main = acc.get("recipe", {})
                                    break
                            
                            if dinner_main:
                                # Calculate current meal macros
                                main_macros = _get_meal_macros(dinner_main)
                                main_servings = next((acc.get("servings", 1.0) for acc in accompaniments if acc.get("type") == "main"), 1.0)
                                carb_macros = _get_meal_macros(dinner_carb)
                                carb_servings = dinner_data.get("servings", 1.0)
                                
                                current_meal_macros = {
                                    "kcal": main_macros.get("kcal", 0) * main_servings + carb_macros.get("kcal", 0) * carb_servings,
                                    "protein_g": main_macros.get("protein_g", 0) * main_servings + carb_macros.get("protein_g", 0) * carb_servings,
                                    "fat_g": main_macros.get("fat_g", 0) * main_servings + carb_macros.get("fat_g", 0) * carb_servings,
                                    "carb_g": main_macros.get("carb_g", 0) * main_servings + carb_macros.get("carb_g", 0) * carb_servings,
                                }
                                
                                # Add veg/fruit/soup macros
                                for acc in accompaniments:
                                    if acc.get("type") in ["vegetable", "fruit", "soup"]:
                                        acc_macros = _get_meal_macros(acc.get("recipe", {}))
                                        acc_servings = acc.get("servings", 1.0)
                                        for k in current_meal_macros:
                                            current_meal_macros[k] += acc_macros.get(k, 0) * acc_servings
                                
                                # Check if deviation is large for this meal
                                meal_deviation = _calculate_total_deviation_score(current_meal_macros, dinner_targets)
                                if meal_deviation > 0.2:  # >20% deviation
                                    # Get alternative main dishes from recipes (with kcal filter)
                                    alternative_mains = [
                                        r for r in recipes
                                        if r.get("food_id") != dinner_main.get("food_id")
                                        and _is_main_dish(r)
                                        and not _is_combined_dish(r)  # Exclude combined dishes
                                        and r.get("macros_per_serving", {}).get("kcal", 0) > 0
                                        and r.get("macros_per_serving", {}).get("kcal", 0) <= 500.0  # Filter out dishes that are too high in kcal
                                    ][:5]  # Try top 5 alternatives for better selection
                                    
                                    if alternative_mains:
                                        best_main, best_scale, best_score = _try_swap_alternatives(
                                            dinner_main,
                                            alternative_mains,
                                            dinner_targets,
                                            "main",
                                            main_servings,
                                            max_alternatives=5,  # Increased from 2 to 5 for better selection
                                        )
                                        
                                        if best_main and best_score < meal_deviation:
                                            # Temporarily swap to check overall improvement
                                            temp_plan_state = {}
                                            for acc in accompaniments:
                                                if acc.get("type") == "main":
                                                    temp_plan_state["old_recipe"] = acc.get("recipe")
                                                    temp_plan_state["old_servings"] = acc.get("servings", 1.0)
                                                    acc["recipe"] = best_main
                                                    acc["servings"] = 1.0
                                                    break
                                            
                                            # Recalculate total macros with swap
                                            temp_total_macros = {"kcal": 0.0, "protein_g": 0.0, "fat_g": 0.0, "carb_g": 0.0}
                                            for meal_key, meal_data in plan.items():
                                                recipe = meal_data.get("recipe", {})
                                                servings = meal_data.get("servings", 1.0)
                                                macros = _get_meal_macros(recipe)
                                                meal_macros = {k: macros[k] * servings for k in macros}
                                                
                                                accompaniments_temp = meal_data.get("accompaniments", [])
                                                for acc in accompaniments_temp:
                                                    acc_recipe = acc.get("recipe")
                                                    acc_servings = acc.get("servings", 1.0)
                                                    if acc_recipe:
                                                        acc_macros = _get_meal_macros(acc_recipe)
                                                        for k in meal_macros:
                                                            meal_macros[k] += acc_macros[k] * acc_servings
                                                
                                                for k in temp_total_macros:
                                                    temp_total_macros[k] += meal_macros[k]
                                            
                                            temp_overall_score = _calculate_total_deviation_score(temp_total_macros, targets)
                                            
                                            # Only keep swap if it improves overall balance
                                            if temp_overall_score < current_overall_score:
                                                swaps_made += 1
                                                improved = True
                                                current_overall_score = temp_overall_score
                                                if temp_overall_score < best_overall_score:
                                                    best_overall_score = temp_overall_score
                                            else:
                                                # Revert swap
                                                for acc in accompaniments:
                                                    if acc.get("type") == "main":
                                                        acc["recipe"] = temp_plan_state.get("old_recipe")
                                                        acc["servings"] = temp_plan_state.get("old_servings", 1.0)
                                                        break
                        
                        # Break early if no improvement was made
                        if not improved:
                            break
                    
                    # Recalculate total macros after swaps
                    if swaps_made > 0:
                        yield Response(f"✅ Swapped {swaps_made} recipe(s) to improve macro fit")
                        
                        # Ensure all servings remain at 1.0 (Vietnamese meal pattern - fixed portions)
                        for meal_key, meal_data in plan.items():
                            meal_data["servings"] = 1.0
                            for acc in meal_data.get("accompaniments", []):
                                acc["servings"] = 1.0
                        
                        # Recalculate total macros with fixed 1.0 servings (single source of truth)
                        total_macros = {"kcal": 0.0, "protein_g": 0.0, "fat_g": 0.0, "carb_g": 0.0}
                        for meal_key, meal_data in plan.items():
                            recipe = meal_data.get("recipe", {})
                            servings = 1.0  # Always 1.0
                            macros = _get_meal_macros(recipe)
                            meal_macros = {k: macros[k] * servings for k in macros}
                            
                            accompaniments = meal_data.get("accompaniments", [])
                            for acc in accompaniments:
                                acc_recipe = acc.get("recipe")
                                acc_servings = 1.0  # Always 1.0
                                if acc_recipe:
                                    acc_macros = _get_meal_macros(acc_recipe)
                                    for k in meal_macros:
                                        meal_macros[k] += acc_macros[k] * acc_servings
                            
                            # Update meal macros (single source of truth)
                            meal_data["macros"] = meal_macros.copy()
                            if meal_key in ["lunch", "dinner"]:
                                meal_data["macros_main"] = {k: macros[k] * servings for k in macros}
                                meal_data["macros_total"] = meal_macros.copy()
                            
                            # Add to total
                            for k in total_macros:
                                total_macros[k] += meal_macros[k]

        # Step 5: Validate
        validation = {"valid": True, "macro_validation": {}, "constraint_validation": {}}
        
        if targets:
            yield Response("✅ Checking nutritional balance...")
            macro_validation = _validate_macro_targets(total_macros, targets, macro_tolerance_percent)
            validation["macro_validation"] = macro_validation
            
            # Calculate macro accuracy percentage for better feedback
            macro_accuracy = 100.0
            if total_macros.get("kcal", 0) > 0:
                kcal_deviation = abs(total_macros.get("kcal", 0) - targets.get("tdee_kcal", 2000)) / targets.get("tdee_kcal", 2000)
                macro_accuracy = max(0.0, 100.0 - (kcal_deviation * 100.0))
            
            if not macro_validation["valid"]:
                validation["valid"] = False
                violations = len(macro_validation.get('violations', []))
                warnings = len(macro_validation.get('warnings', []))
                if violations > 0:
                    yield Response(f"⚠️ Macro balance: {violations} deviation(s) from targets (Accuracy: {macro_accuracy:.1f}%)")
                if warnings > 0:
                    yield Response(f"ℹ️ {warnings} minor deviation(s) detected (Accuracy: {macro_accuracy:.1f}%)")
            else:
                yield Response(f"✅ All macros within target range (Accuracy: {macro_accuracy:.1f}%)")
        
        if filters_metadata:
            yield Response("✅ Verifying dietary constraints...")
            diet_types = filters_metadata.get("diet_types", [])
            exclude_allergens = filters_metadata.get("exclude_allergens", [])
            constraint_validation = _validate_constraints(
                {"meals": plan},
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

        # Step 6: Calculate micronutrients
        yield Response("🔬 Calculating micronutrients (vitamins & minerals)...")
        gender = (profile or {}).get("gender")
        
        try:
            micronutrients = await _calculate_plan_micronutrients(
                {"plan_type": "day", "meals": plan},
                client_manager=client_manager,
                gender=gender,
            )
        except Exception as e:
            logging.warning(f"plan_day_e2e_tool: Failed to calculate micronutrients: {e}")
            micronutrients = {
                "total_micros": {},
                "average_daily_micros": {},
                "rdas": {},
                "deficits": {},
                "has_deficits": False,
            }
        
        now_utc = datetime.now(timezone.utc)
        plan_output = {
            "plan_type": "day",
            "meals": plan,
            "total_macros": total_macros,
            "micronutrients": micronutrients,
            "validation": validation,
            "created_at": ensure_rfc3339_datetime(now_utc),
        }
        if plan_id:
            plan_output["plan_id"] = plan_id

        normalized_start_date = (
            ensure_rfc3339_datetime(start_date, date_only=True)
            if start_date
            else ensure_rfc3339_datetime(now_utc, date_only=True)
        )
        plan_output["start_date"] = normalized_start_date

        if user_id:
            plan_output = sync_plan_to_weaviate(
                plan_output,
                user_id=user_id,
                client_manager=client_manager,
                start_date=plan_output.get("start_date"),
            )
            yield Response(f"💾 Plan saved (ID: {plan_output.get('plan_id', 'N/A')})")
        else:
            yield Response("ℹ️ Plan stored in memory (create profile to save permanently)")

        # Stream response first for immediate feedback
        # Use consistent formatting with 1 decimal place to match other displays
        status_icon = "✅" if validation["valid"] else "⚠️"
        yield Response(
            f"{status_icon} Daily meal plan ready! "
            f"Total: {total_macros['kcal']:.1f} kcal | "
            f"{total_macros['protein_g']:.1f}g protein | "
            f"{total_macros['fat_g']:.1f}g fat | "
            f"{total_macros['carb_g']:.1f}g carbs"
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
                yield Response(f"💊 Micronutrients: {', '.join(micros_summary[:3])}...")
            
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
                "plan_type": "day",
                "meals_count": 3,
                "valid": validation["valid"],
                "macro_violations": len(validation.get("macro_validation", {}).get("violations", [])),
                "constraint_violations": len(validation.get("constraint_validation", {}).get("violations", [])),
                "plan_id": plan_output.get("plan_id"),
            },
            payload_type="meal_plan",
            display=True,
        )
        # Suggest next action: ask user to accept and log meal history
        yield Response("👍 Kế hoạch đã sẵn sàng. Nếu bạn chấp nhận, tôi sẽ lưu vào lịch sử bữa ăn.")
        yield Result(
            name="next_action_hint",
            objects=[
                {
                    "suggested_action": "log_meal",
                    "reason": "Plan ready; log meal history after user accepts",
                    "plan_id": plan_output.get("plan_id"),
                    "user_id": user_id,
                }
            ],
            metadata={
                "suggested_action": "log_meal",
                "task_complete": False,
                "plan_id": plan_output.get("plan_id"),
            },
            payload_type="generic",
            display=False,
        )
        
        # Phase 2.2: LLM Critic (async, non-blocking)
        if base_lm and targets:
            try:
                critic_task = create_critic_task(
                    base_lm=base_lm,
                    plan=plan_output,
                    targets=targets,
                    validation=validation,
                )
                
                if critic_task:
                    # Try to get critic note quickly (with timeout)
                    try:
                        critic_note = await asyncio.wait_for(critic_task, timeout=5.0)
                        if critic_note:
                            plan_output["critic_note"] = critic_note
                            yield Response(f"💡 Gợi ý: {critic_note}")
                    except asyncio.TimeoutError:
                        # Critic taking too long, continue without it
                        logging.debug("LLM critic timeout, continuing without critic note")
                    except Exception as e:
                        logging.debug(f"LLM critic error: {e}")
            except Exception as e:
                logging.debug(f"Failed to create LLM critic task: {e}")
        
        _clear_missing_macro_state(tree_data)

    except ValueError as e:
        error_msg = f"Invalid input: {str(e)}"
        logging.error(f"plan_day_e2e_tool: {error_msg}", exc_info=True)
        yield Error(error_msg)
        return
    except Exception as e:
        error_msg = f"plan_day_e2e_tool failed: {str(e)}"
        logging.error(f"plan_day_e2e_tool: {error_msg}", exc_info=True)
        yield Error(error_msg)
        return


