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
    _is_glutinous_rice_dish,
    _is_carb_dish,
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
                    "timestamp": datetime.now(timezone.utc).isoformat(),
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
                    "timestamp": datetime.now(timezone.utc).isoformat(),
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


def _is_default_white_rice_id(recipe_id: str | None) -> bool:
    """Return True if the id corresponds to the default white rice fallback."""
    return str(recipe_id) == "default_white_rice"


def _recompute_meal_macros(plan: Dict[str, Any]) -> None:
    """
    Recalculate per-meal macros (macros_main, macros_total) using current servings.
    This is a lightweight helper to keep meal totals consistent after scaling or swaps.
    """
    for meal_key, meal_data in plan.items():
        recipe = meal_data.get("recipe")
        servings = meal_data.get("servings", 1.0)
        base_macros = _get_meal_macros(recipe) if recipe else {"kcal": 0.0, "protein_g": 0.0, "fat_g": 0.0, "carb_g": 0.0}

        # macros for the primary recipe (main carb for lunch/dinner, dish for breakfast)
        macros_main = {k: base_macros.get(k, 0.0) * servings for k in ["kcal", "protein_g", "fat_g", "carb_g"]}
        macros_total = macros_main.copy()

        # accompaniments (main/soup/veg/fruit/supplementary)
        for acc in meal_data.get("accompaniments", []):
            acc_recipe = acc.get("recipe")
            acc_servings = acc.get("servings", 1.0)
            acc_macros = _get_meal_macros(acc_recipe) if acc_recipe else {"kcal": 0.0, "protein_g": 0.0, "fat_g": 0.0, "carb_g": 0.0}
            for k in macros_total:
                macros_total[k] += acc_macros.get(k, 0.0) * acc_servings

        # Persist back to plan
        meal_data["macros"] = macros_total.copy()  # single source of truth per meal
        if meal_key in ("lunch", "dinner"):
            meal_data["macros_main"] = macros_main
            meal_data["macros_total"] = macros_total


def _calculate_plan_totals(plan: Dict[str, Any]) -> Dict[str, float]:
    """
    Sum macros across all meals using the per-meal totals.
    Assumes _recompute_meal_macros has run to keep per-meal fields in sync.
    """
    totals = {"kcal": 0.0, "protein_g": 0.0, "fat_g": 0.0, "carb_g": 0.0}
    for meal_data in plan.values():
        meal_macros = meal_data.get("macros")
        if not meal_macros:
            # Fall back to recomputing from recipe if macros missing
            recipe = meal_data.get("recipe")
            servings = meal_data.get("servings", 1.0)
            meal_macros = _get_meal_macros(recipe) if recipe else {"kcal": 0.0, "protein_g": 0.0, "fat_g": 0.0, "carb_g": 0.0}
            meal_macros = {k: meal_macros.get(k, 0.0) * servings for k in totals}
            for acc in meal_data.get("accompaniments", []):
                acc_recipe = acc.get("recipe")
                acc_servings = acc.get("servings", 1.0)
                acc_macros = _get_meal_macros(acc_recipe) if acc_recipe else {"kcal": 0.0, "protein_g": 0.0, "fat_g": 0.0, "carb_g": 0.0}
                for k in totals:
                    meal_macros[k] += acc_macros.get(k, 0.0) * acc_servings
        for k in totals:
            totals[k] += meal_macros.get(k, 0.0)
    return totals


def _is_rice_recipe(recipe: Dict[str, Any] | None) -> bool:
    """Helper to detect rice staples (including default white rice)."""
    if not recipe:
        return False
    if _is_default_white_rice_id(str(recipe.get("food_id", ""))):
        return True
    return _is_rice_dish(recipe)


def _normalize_servings(plan: Dict[str, Any]) -> None:
    """
    Enforce serving rules:
      - Noodle/bún/phở: always 1 serving
      - Default and other rice dishes: integer 1..4 servings
      - Main or vegetable dishes: integer 1 or 2 servings
      - Others (soup/fruit/side): 1 serving
    """
    def _clamp_servings(servings: float, is_rice: bool) -> float:
        return float(min(4, max(1, int(round(servings))))) if is_rice else float(min(2, max(1, int(round(servings)))))

    for meal_data in plan.values():
        recipe = meal_data.get("recipe")
        is_rice = _is_rice_recipe(recipe)
        if _is_noodle_soup(recipe):
            meal_data["servings"] = 1.0
        elif is_rice:
            meal_data["servings"] = _clamp_servings(meal_data.get("servings", 1.0), True)
        elif _is_main_dish(recipe) or _is_vegetable_dish(recipe):
            meal_data["servings"] = _clamp_servings(min(2.0, meal_data.get("servings", 1.0)), False)
        else:
            meal_data["servings"] = 1.0

        for acc in meal_data.get("accompaniments", []):
            acc_recipe = acc.get("recipe")
            acc_is_rice = _is_rice_recipe(acc_recipe)
            if _is_noodle_soup(acc_recipe):
                acc["servings"] = 1.0
            elif acc_is_rice:
                acc["servings"] = _clamp_servings(acc.get("servings", 1.0), True)
            elif _is_main_dish(acc_recipe) or _is_vegetable_dish(acc_recipe):
                acc["servings"] = _clamp_servings(min(2.0, acc.get("servings", 1.0)), False)
            else:
                acc["servings"] = 1.0


def _enrich_rice_meal(
    meal_slot: str,
    is_noodle: bool,
    is_combined: bool,
    meal_main: Dict[str, Any] | None,
    meal_veg: Dict[str, Any] | None,
    meal_soup: Dict[str, Any] | None,
    remaining_targets: Dict[str, float] | None,
    targets: Dict[str, float] | None,
    recipes: List[Dict[str, Any]],
    excluded: List[Dict[str, Any]],
    recent_recipe_ids_set: set[str],
    used_today_ids: set[str],
    preferred_meal_type: str,
    main_max_kcal: float,
    soup_max_kcal: float,
    mark_used_cb,
) -> tuple[Dict[str, Any] | None, Dict[str, Any] | None, Dict[str, Any] | None, list[str]]:
    """
    For rice meals with deficits, force-add main/veg/soup to close nutrition gaps.
    Returns updated (main, veg, soup, messages).
    """
    messages: list[str] = []
    if is_noodle or is_combined or not remaining_targets or not targets:
        return meal_main, meal_veg, meal_soup, messages

    kcal_need = remaining_targets.get("kcal", 0)
    protein_need = remaining_targets.get("protein_g", 0)
    # Add/replace main if missing or deficit large
    if (not meal_main) or (kcal_need > targets.get("tdee_kcal", 0) * 0.20 or protein_need > targets.get("protein_g", 0) * 0.20):
        forced_main = select_meal_by_strategy(
            recipes, "highest_protein",
            exclude=excluded,
            used_recipe_ids=recent_recipe_ids_set | used_today_ids,
            preferred_meal_type=preferred_meal_type,
            dish_category="main",
            target_macros=targets,
            require_macros=True,
            min_kcal=250.0,
            max_kcal=main_max_kcal,
            min_protein=28.0,
        )
        if forced_main:
            meal_main = forced_main
            mark_used_cb(meal_main)
            excluded.append(meal_main)
            messages.append(f"✅ Added main dish to {meal_slot} to boost macros: {meal_main.get('dish_name','Unknown')}")

    # Add vegetable if missing and still need macros
    if not meal_veg and (kcal_need > 0 or protein_need > 0):
        forced_veg = select_meal_by_strategy(
            recipes, "balanced",
            exclude=excluded,
            used_recipe_ids=recent_recipe_ids_set | used_today_ids,
            preferred_meal_type=preferred_meal_type,
            dish_category="vegetable",
            target_macros=targets,
            require_macros=True,
            min_kcal=60.0,
            max_kcal=220.0,
        )
        if forced_veg and _is_vegetable_dish(forced_veg):
            meal_veg = forced_veg
            mark_used_cb(meal_veg)
            excluded.append(meal_veg)
            messages.append(f"✅ Added vegetable for {meal_slot}: {meal_veg.get('dish_name','Unknown')}")

    # Add soup if missing and still need kcal
    if not meal_soup and kcal_need > 0:
        forced_soup = select_meal_by_strategy(
            recipes, "balanced",
            exclude=excluded,
            used_recipe_ids=recent_recipe_ids_set | used_today_ids,
            preferred_meal_type=preferred_meal_type,
            dish_category="soup",
            target_macros=targets,
            require_macros=True,
            min_kcal=60.0,
            max_kcal=soup_max_kcal,
        )
        if forced_soup and _is_soup(forced_soup):
            meal_soup = forced_soup
            mark_used_cb(meal_soup)
            excluded.append(meal_soup)
            messages.append(f"✅ Added soup for {meal_slot}: {meal_soup.get('dish_name','Unknown')}")

    return meal_main, meal_veg, meal_soup, messages


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


def _is_selected_from_llm(
    selected_recipe: Dict[str, Any] | None,
    llm_draft,
    meal_slot: str,
    role: str,
    recipes: List[Dict[str, Any]],
) -> bool:
    """
    Check if the chosen recipe originates from the LLM draft suggestions by ID match.
    Avoids reselecting/altering the current pick; only performs identity check.
    """
    if not selected_recipe or not llm_draft:
        return False
    meal_draft = getattr(llm_draft, meal_slot, None)
    if not meal_draft or not meal_draft.suggestions:
        return False

    selected_id = str(selected_recipe.get("food_id", "") or selected_recipe.get("recipe_id", ""))
    if not selected_id:
        return False

    for suggestion in meal_draft.suggestions:
        suggestion_dict = suggestion.model_dump() if hasattr(suggestion, "model_dump") else suggestion
        mapped = _map_llm_suggestion_to_recipe(
            suggestion_dict,
            recipes,
            role,
        )
        if mapped and str(mapped.get("food_id", "") or mapped.get("recipe_id", "")) == selected_id:
            return True
    return False


def _select_carb_with_validation(
    llm_draft,
    meal_slot: str,
    recipes: List[Dict[str, Any]],
    excluded: List[Dict[str, Any]],
    recent_recipe_ids_set: set[str],
    used_today_ids_set: set[str],
    selection_strategy: str,
    targets: Optional[Dict[str, float]],
    meal_max_kcal: float,
    existing_carb_in_meal: Optional[Dict[str, Any]] = None,
) -> tuple[Dict[str, Any], bool, bool]:
    """
    Select carb (rice/noodle) for a meal slot with LLM fallback and validation.
    
    Args:
        existing_carb_in_meal: If a carb dish is already selected in this meal, 
                              prevent selecting duplicate carbs (e.g., if white rice exists, 
                              don't select other rice/noodle/glutinous rice dishes)
    
    Returns: (carb_recipe, is_combined, is_noodle)
    """
    # CRITICAL: If white rice already exists in meal, reject other carb dishes
    if existing_carb_in_meal:
        dish_name_lower = str(existing_carb_in_meal.get('dish_name', '')).lower()
        is_white_rice = any(term in dish_name_lower for term in ['cơm trắng', 'com trang', 'white rice'])
        
        if is_white_rice:
            # White rice already selected - reject all other carb dishes
            logging.info(f"{meal_slot.capitalize()} already has white rice, rejecting other carb dishes to avoid duplicates")
            return existing_carb_in_meal, False, False
        else:
            # Other carb already selected - reject white rice
            logging.info(f"{meal_slot.capitalize()} already has carb dish '{existing_carb_in_meal.get('dish_name', 'Unknown')}', rejecting white rice to avoid duplicates")
            # Continue to select, but will reject white rice later
    
    # Prefer a plain white rice candidate up-front if available in search results
    for recipe in recipes:
        if (
            recipe not in excluded
            and str(recipe.get("food_id", "")) not in recent_recipe_ids_set
            and str(recipe.get("food_id", "")) not in used_today_ids_set
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

    # Try ALL LLM suggestions first (not just the first one) to avoid fallback
    carb_recipe = None
    if llm_draft:
        meal_draft = getattr(llm_draft, meal_slot, None)
        if meal_draft and meal_draft.suggestions:
            # Try all suggestions, not just the first one
            for suggestion in meal_draft.suggestions:
                suggestion_dict = suggestion.model_dump() if hasattr(suggestion, 'model_dump') else suggestion
                suggestion_role = suggestion_dict.get("role", "")
                
                if suggestion_role == "carb":
                    mapped_recipe = _map_llm_suggestion_to_recipe(
                        suggestion_dict,
                        recipes,
                        "carb"
                    )
                    if mapped_recipe and mapped_recipe not in excluded:
                        if str(mapped_recipe.get("food_id", "")) not in (recent_recipe_ids_set | used_today_ids_set):
                            # RELAXED VALIDATION: Accept LLM suggestions more leniently
                            dish_name_lower = str(mapped_recipe.get('dish_name', '')).lower()
                            has_rice_noodle_in_name = any(term in dish_name_lower for term in ['cơm', 'com', 'rice', 'bún', 'bun', 'phở', 'pho', 'mì', 'mi', 'noodle'])
                            
                            is_rice_or_noodle = _is_rice_dish(mapped_recipe) or _is_noodle_soup(mapped_recipe)
                            is_main = _is_main_dish(mapped_recipe)
                            
                            # Accept if: (1) is rice/noodle, OR (2) is main dish but has rice/noodle in name
                            if is_rice_or_noodle or (is_main and has_rice_noodle_in_name):
                                # CRITICAL: Prevent duplicate carbs in same meal
                                # If white rice exists, reject other carbs; if other carb exists, reject white rice
                                mapped_dish_name_lower = str(mapped_recipe.get('dish_name', '')).lower()
                                mapped_is_white_rice = any(term in mapped_dish_name_lower for term in ['cơm trắng', 'com trang', 'white rice'])
                                mapped_is_glutinous = _is_glutinous_rice_dish(mapped_recipe)
                                mapped_is_carb = _is_carb_dish(mapped_recipe)
                                
                                if existing_carb_in_meal:
                                    existing_dish_name_lower = str(existing_carb_in_meal.get('dish_name', '')).lower()
                                    existing_is_white_rice = any(term in existing_dish_name_lower for term in ['cơm trắng', 'com trang', 'white rice'])
                                    
                                    # Reject if: (1) white rice exists and trying to add another carb, OR
                                    #            (2) another carb exists and trying to add white rice, OR
                                    #            (3) trying to add glutinous rice when white rice exists
                                    if (existing_is_white_rice and (mapped_is_carb or mapped_is_glutinous)) or \
                                       (not existing_is_white_rice and mapped_is_white_rice) or \
                                       (existing_is_white_rice and mapped_is_glutinous):
                                        logging.debug(f"Rejecting duplicate carb: '{mapped_recipe.get('dish_name', 'Unknown')}' (meal already has '{existing_carb_in_meal.get('dish_name', 'Unknown')}')")
                                        continue
                                
                                # Validate kcal range
                                macros = mapped_recipe.get("macros_per_serving", {})
                                if isinstance(macros, dict):
                                    kcal = macros.get("kcal", 0)
                                    if 100.0 <= kcal <= meal_max_kcal:
                                        carb_recipe = mapped_recipe
                                        logging.info(f"Accepted LLM suggestion for {meal_slot} carb: {carb_recipe.get('dish_name', 'Unknown')}")
                                        break
    
    # Fallback to rule-based selection
    if not carb_recipe:
        # CRITICAL: Filter out duplicate carbs if white rice already exists
        filtered_excluded = list(excluded)
        if existing_carb_in_meal:
            existing_dish_name_lower = str(existing_carb_in_meal.get('dish_name', '')).lower()
            existing_is_white_rice = any(term in existing_dish_name_lower for term in ['cơm trắng', 'com trang', 'white rice'])
            
            if existing_is_white_rice:
                # Exclude all other carb dishes (rice, noodle, glutinous rice)
                for recipe in recipes:
                    if _is_carb_dish(recipe) or _is_glutinous_rice_dish(recipe):
                        if recipe not in filtered_excluded:
                            filtered_excluded.append(recipe)
            else:
                # Exclude white rice
                for recipe in recipes:
                    dish_name_lower = str(recipe.get('dish_name', '')).lower()
                    if any(term in dish_name_lower for term in ['cơm trắng', 'com trang', 'white rice']):
                        if recipe not in filtered_excluded:
                            filtered_excluded.append(recipe)
        
        carb_recipe = select_meal_by_strategy(
            recipes, selection_strategy if targets else "balanced",
            exclude=filtered_excluded,
            used_recipe_ids=recent_recipe_ids_set | used_today_ids_set,
            preferred_meal_type=meal_slot,
            dish_category="rice",
            target_macros=targets,
            max_kcal=meal_max_kcal
        )
    
    # Try standalone noodle dishes if still not found
    if not carb_recipe:
        for recipe in recipes:
            if recipe in excluded or str(recipe.get("food_id", "")) in recent_recipe_ids_set or str(recipe.get("food_id", "")) in used_today_ids_set:
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
    
    # RELAXED FINAL VALIDATION: Accept more leniently to avoid fallback
    dish_name_lower = str(carb_recipe.get('dish_name', '')).lower()
    has_rice_noodle_in_name = any(term in dish_name_lower for term in ['cơm', 'com', 'rice', 'bún', 'bun', 'phở', 'pho', 'mì', 'mi', 'noodle'])
    
    is_rice_or_noodle = _is_rice_dish(carb_recipe) or _is_noodle_soup(carb_recipe)
    is_main = _is_main_dish(carb_recipe)
    
    # Accept if: (1) is rice/noodle, OR (2) is main dish but has rice/noodle in name
    if not is_rice_or_noodle and not (is_main and has_rice_noodle_in_name):
        logging.warning(f"Selected {meal_slot}_carb is not rice/noodle: {carb_recipe.get('dish_name', 'Unknown')}")
        return _create_default_white_rice_recipe(), False, False
    
    if is_main and not has_rice_noodle_in_name:
        # Only reject main dish if it doesn't have rice/noodle in name
        logging.warning(f"Selected {meal_slot}_carb is a main dish without rice/noodle: {carb_recipe.get('dish_name', 'Unknown')}")
        return _create_default_white_rice_recipe(), False, False
    
    # If combined rice dish, use default white rice
    if _is_rice_dish(carb_recipe) and is_combined:
        return _create_default_white_rice_recipe(), False, False
    
    # For lunch/dinner: allow rice first; if not rice but is noodle/soup, accept; otherwise fallback to rice
    if meal_slot in ("lunch", "dinner"):
        if _is_rice_dish(carb_recipe):
            return carb_recipe, is_combined, is_noodle
        if _is_noodle_soup(carb_recipe):
            # Reject “ingredient-only” noodles (e.g., plain fresh noodles) by checking calories/protein
            macros = carb_recipe.get("macros_per_serving", {}) or {}
            kcal = macros.get("kcal", 0) or 0
            protein = macros.get("protein_g", 0) or 0
            if kcal < 120 or protein < 5:
                logging.info(
                    f"{meal_slot.capitalize()} noodle carb '{carb_recipe.get('dish_name', 'Unknown')}' "
                    f"too light (kcal={kcal}, protein={protein}), falling back to default white rice."
                )
                return _create_default_white_rice_recipe(), False, False
            return carb_recipe, is_combined, True  # allow bún/phở/mì as carb
        if is_combined and not _is_rice_dish(carb_recipe):
            # Combined but not rice (e.g., salad phở) => serve with white rice base
            return _create_default_white_rice_recipe(), False, False
        logging.info(
            f"{meal_slot.capitalize()} carb '{carb_recipe.get('dish_name', 'Unknown')}' is not rice/noodle; "
            "falling back to default white rice to keep Vietnamese meal pattern."
        )
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
        
        # RELAXED THRESHOLD: Accept more LLM suggestions to avoid repetitive fallbacks
        # Require at least ONE of:
        # 1. Exact match (200 points)
        # 2. Substring match (100 points) 
        # 3. Keyword match (at least 1 keyword, score >= 40) - REDUCED from 50
        # 4. General term match (60+ points) - REDUCED from 80
        # 5. Multiple criteria combined (score >= 40) - REDUCED from 60
        # This allows more LLM suggestions to be accepted, reducing fallback to default dishes
        
        if (has_exact_match or has_substring_match or 
            (has_keyword_match and best_score >= 40.0) or
            (has_general_term_match and best_score >= 60.0) or
            best_score >= 40.0):
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

    # Local helpers to keep recipe objects and macros consistent across the long workflow.
    macros_cache: dict[str, Dict[str, float]] = {}

    def _as_recipe(obj: Dict[str, Any] | None) -> Dict[str, Any]:
        """Normalize to the underlying recipe dict (unwrap {'recipe': {...}} if present)."""
        if isinstance(obj, dict) and isinstance(obj.get("recipe"), dict):
            return obj["recipe"]
        return obj or {}

    def _macros(recipe: Dict[str, Any] | None) -> Dict[str, float]:
        """Cached macros lookup by recipe id to avoid repeated calculations."""
        recipe_obj = _as_recipe(recipe)
        rid = str(
            recipe_obj.get("food_id", "")
            or recipe_obj.get("recipe_id", "")
            or recipe_obj.get("id", "")
        )
        if rid and rid in macros_cache:
            return macros_cache[rid]
        m = _get_meal_macros(recipe_obj)
        if rid:
            macros_cache[rid] = m
        return m

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
            pass

        # Prepare constraints for LLM draft
        constraints_dict = {
            "diet_types": filters_metadata.get("diet_types", []) if filters_metadata else [],
            "exclude_allergens": filters_metadata.get("exclude_allergens", []) if filters_metadata else [],
        }
        
        # Get CONSUMED meal history from MealLogEntry for LLM draft (before recipe search)
        # IMPORTANT: MealLogEntry stores meals that user has ACCEPTED or actually EATEN
        # This is different from MealPlan/MealPlanItem which stores SUGGESTED plans
        # We use this history to:
        # 1. Provide context to LLM for better meal suggestions
        # 2. Exclude consumed meals from variety filter to avoid repetition
        # Track both dish names and recipe IDs for better variety
        meal_history_dish_names: List[str] = []
        meal_history_recipe_ids: set[str] = set()
        try:
            if resolved_user_id:
                client = client_manager.get_client()
                meal_log_collection = client.collections.get("MealLogEntry")  # CONSUMED meals collection
                
                # Get recent CONSUMED meal logs (last 30 days for better variety tracking)
                # These are meals that were logged via log_meal_e2e_tool (user accepted/ate them)
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
            logging.debug(f"plan_day_e2e_tool: Could not load consumed meal history from MealLogEntry: {e}")
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
                    logging.debug("plan_day_e2e_tool: using rule-based selection (AI suggestions unavailable)")
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
                limit=300,
                top_k=300,
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
        
        # IMPROVED VARIETY: shuffle and exclude recently used recipes/names with stronger penalty
        def _shuffle_recipes(items: list[Dict[str, Any]], times: int = 3) -> None:
            for _ in range(times):
                random.shuffle(items)

        _shuffle_recipes(recipes, times=3)

        # VARIETY FILTER: Build blocklist to prevent meal repetition
        # IMPORTANT: We check TWO sources to avoid repetition:
        # 1. MealPlan/MealPlanItem: SUGGESTED plans (plans generated but not yet accepted)
        #    - These are plans that were created but user hasn't accepted yet
        #    - We exclude these to avoid suggesting the same plan multiple times
        # 2. MealLogEntry: CONSUMED meals (meals that user has accepted or actually eaten)
        #    - These are meals that were logged via log_meal_e2e_tool
        #    - We exclude these to avoid suggesting meals user has already eaten
        recent_recipe_ids = set()
        recent_recipe_names: set[str] = set()
        try:
            client = client_manager.get_client()
            plan_collection = client.collections.get("MealPlan")  # SUGGESTED plans collection
            item_collection = client.collections.get("MealPlanItem")  # SUGGESTED plan items collection
            # Tracking counters to understand where blocklist comes from
            ids_from_mealplan = 0  # From MealPlan/MealPlanItem (suggested plans)
            names_from_mealplan = 0
            ids_from_meallog = 0  # From MealLogEntry (consumed meals)
            names_from_meallog = 0
            ids_from_env_cache = 0  # From environment cache (current session)
            names_from_env_cache = 0

            if user_id:
                # SOURCE 1: Check SUGGESTED plans from MealPlan/MealPlanItem (last 30 days)
                # These are plans that were generated but may not have been accepted yet
                # We exclude them to avoid suggesting duplicate plans
                # Increased from 7 to 30 days to prevent repetition across multiple days
                window_days = 30
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

                # Fetch more plans to ensure we block all recent suggestions
                recent_plans = plan_collection.query.fetch_objects(filters=plan_filter, limit=50)
                
                # CRITICAL: Also check plans from TODAY to prevent duplicates in same session
                # This prevents suggesting the same plan multiple times in one day
                # Check BOTH created_at (when plan was created) AND start_date (plan date)
                today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
                today_start_str = today_start.isoformat().replace("+00:00", "Z")
                
                # Filter 1: Plans created today (most recent plans)
                today_created_filter = build_filters_from_where({
                    "operator": "And",
                    "operands": [
                        {"path": ["user_id"], "operator": "Equal", "valueString": user_id},
                        {"path": ["plan_type"], "operator": "Equal", "valueString": "day"},
                        {"path": ["created_at"], "operator": "GreaterThanEqual", "valueDate": today_start_str}
                    ]
                })
                today_created_plans = plan_collection.query.fetch_objects(filters=today_created_filter, limit=50)
                
                # Filter 2: Plans with start_date = today (plans for today)
                today_startdate_filter = build_filters_from_where({
                    "operator": "And",
                    "operands": [
                        {"path": ["user_id"], "operator": "Equal", "valueString": user_id},
                        {"path": ["plan_type"], "operator": "Equal", "valueString": "day"},
                        {"path": ["start_date"], "operator": "GreaterThanEqual", "valueDate": today_start_str}
                    ]
                })
                today_startdate_plans = plan_collection.query.fetch_objects(filters=today_startdate_filter, limit=50)
                
                # Merge all today's plans into recent_plans to ensure we block duplicates from same day
                all_today_plans = []
                if today_created_plans.objects:
                    all_today_plans.extend(today_created_plans.objects)
                if today_startdate_plans.objects:
                    all_today_plans.extend(today_startdate_plans.objects)
                
                # Deduplicate by UUID and merge into recent_plans
                seen_uuids = {p.uuid for p in recent_plans.objects}
                for plan_obj in all_today_plans:
                    if plan_obj.uuid not in seen_uuids:
                        recent_plans.objects.append(plan_obj)
                        seen_uuids.add(plan_obj.uuid)
                if recent_plans.objects:
                    for plan_obj in recent_plans.objects:
                        pid = plan_obj.properties.get("plan_id")
                        if not pid:
                            continue
                        item_filter = build_filters_from_where(
                            {"path": ["plan_id"], "operator": "Equal", "valueString": pid}
                        )
                        # Fetch all items for each plan to ensure complete blocklist
                        items = item_collection.query.fetch_objects(filters=item_filter, limit=200)
                        for item_obj in items.objects:
                            rid = item_obj.properties.get("recipe_id")
                            if rid:
                                recent_recipe_ids.add(str(rid))
                                ids_from_mealplan += 1
                            dname = item_obj.properties.get("dish_name")
                            if dname:
                                recent_recipe_names.add(str(dname).lower().strip())
                                names_from_mealplan += 1

            # SOURCE 2: Add CONSUMED meals from MealLogEntry (meal history)
            # These are meals that user has accepted or actually eaten (logged via log_meal_e2e_tool)
            # We exclude them to avoid suggesting meals user has already consumed
            # NOTE: meal_history_recipe_ids and meal_history_dish_names were loaded earlier from MealLogEntry
            if "meal_history_recipe_ids" in locals():
                before_len = len(recent_recipe_ids)
                recent_recipe_ids.update(meal_history_recipe_ids)  # From MealLogEntry (consumed meals)
                ids_from_meallog = len(recent_recipe_ids) - before_len
            if "meal_history_dish_names" in locals():
                before_len_names = len(recent_recipe_names)
                recent_recipe_names.update(str(n).lower().strip() for n in meal_history_dish_names if n)  # From MealLogEntry (consumed meals)
                names_from_meallog = len(recent_recipe_names) - before_len_names

            # CRITICAL: Block dishes from ALL plans cached in environment (same session)
            # This prevents repetition when user asks for plan multiple times in same session
            # Plan structure: plan_output["meals"]["breakfast/lunch/dinner"]
            env_plans = tree_data.environment.find("plan_day_e2e_tool", "plan")
            if env_plans:
                logging.debug(f"plan_day_e2e_tool: Found {len(env_plans)} plan entries in environment cache")
                # Check ALL plans in environment, not just the latest one
                for plan_entry in env_plans:
                    plan_objs = plan_entry.get("objects") or []
                    logging.debug(f"plan_day_e2e_tool: Processing {len(plan_objs)} plan objects from environment entry")
                    for plan_obj in plan_objs:
                        try:
                            # Plan structure: plan_output["meals"]["breakfast/lunch/dinner"]
                            # Also support direct access: plan["breakfast/lunch/dinner"] (backward compatibility)
                            meals_dict = plan_obj.get("meals") or {}
                            if not meals_dict:
                                # Try direct access (backward compatibility)
                                meals_dict = {k: v for k, v in plan_obj.items() if k in ["breakfast", "lunch", "dinner"]}
                            
                            if not meals_dict:
                                logging.debug(f"plan_day_e2e_tool: No meals found in plan_obj, skipping. Keys: {list(plan_obj.keys())}")
                                continue
                            
                            # Block all dishes from all meals in this plan
                            for meal_key in ["breakfast", "lunch", "dinner"]:
                                meal_obj = meals_dict.get(meal_key) or {}
                                if not meal_obj:
                                    continue
                                
                                # Block main recipe
                                main_recipe = meal_obj.get("recipe") or {}
                                if main_recipe:
                                    # CRITICAL: Check both food_id and recipe_id (different plans may use different fields)
                                    rid = str(main_recipe.get("food_id", "")).strip() or str(main_recipe.get("recipe_id", "")).strip()
                                    rname = str(main_recipe.get("dish_name", "")).lower().strip()
                                    if rid and rid != "default_white_rice" and rid != "None" and rid:
                                        ids_from_env_cache += 1
                                        recent_recipe_ids.add(rid)
                                    if rname and rname not in ["cơm trắng", "com trang", "white rice", "none", ""]:
                                        names_from_env_cache += 1
                                        recent_recipe_names.add(rname)
                                
                                # Block all accompaniments
                                for acc in meal_obj.get("accompaniments", []) or []:
                                    acc_recipe = acc.get("recipe") or {}
                                    if acc_recipe:
                                        # CRITICAL: Check both food_id and recipe_id (different plans may use different fields)
                                        acc_rid = str(acc_recipe.get("food_id", "")).strip() or str(acc_recipe.get("recipe_id", "")).strip()
                                        acc_name = str(acc_recipe.get("dish_name", "")).lower().strip()
                                        if acc_rid and acc_rid != "default_white_rice" and acc_rid != "None" and acc_rid:
                                            ids_from_env_cache += 1
                                            recent_recipe_ids.add(acc_rid)
                                        if acc_name and acc_name not in ["cơm trắng", "com trang", "white rice", "none", ""]:
                                            names_from_env_cache += 1
                                            recent_recipe_names.add(acc_name)
                        except Exception as env_exc:
                            logging.debug(f"plan_day_e2e_tool: failed to parse env cached plan for variety: {env_exc}")

            # Always allow default white rice as fallback (do not block it)
            recent_recipe_ids.discard("default_white_rice")
            recent_recipe_names.discard("cơm trắng")
            recent_recipe_names.discard("com trang")
            recent_recipe_names.discard("white rice")

            # Count total plans checked for debugging
            total_plans_checked = len(recent_plans.objects) if 'recent_plans' in locals() and recent_plans.objects else 0
            total_today_plans = len(all_today_plans) if 'all_today_plans' in locals() else 0
            
            logging.info(
                "plan_day_e2e_tool: VARIETY_FILTER_BLOCKLIST | user_id=%s | "
                "total_blocked ids=%d names=%d | "
                "from_mealplan (SUGGESTED plans) ids=%d names=%d | "
                "from_meallog (CONSUMED meals) ids=%d names=%d | "
                "from_env_cache (same session) ids=%d names=%d | "
                "total_plans_checked=%d today_plans=%d",
                user_id,
                len(recent_recipe_ids),
                len(recent_recipe_names),
                ids_from_mealplan,
                names_from_mealplan,
                ids_from_meallog,
                names_from_meallog,
                ids_from_env_cache,
                names_from_env_cache,
                total_plans_checked,
                total_today_plans,
            )

            def _apply_exclusion(pool: list[Dict[str, Any]], ids: set[str], names: set[str]) -> list[Dict[str, Any]]:
                if not pool:
                    return pool
                id_block = ids or set()
                name_block = names or set()
                # CRITICAL: Always apply strong exclusion first (both ID and name block)
                # This prevents meal repetition even if it reduces the pool significantly
                filtered = [r for r in pool if str(r.get("food_id", "")) not in id_block and str(r.get("dish_name", "")).lower().strip() not in name_block]
                
                # Only relax if we have very few recipes left (less than 20)
                # This ensures we still block most duplicates even with small recipe pool
                if len(filtered) >= 20:
                    return filtered
                
                # If too few remain, relax name block but ALWAYS keep ID block (stronger exclusion)
                # ID block is more reliable than name block (exact match vs fuzzy match)
                filtered = [r for r in pool if str(r.get("food_id", "")) not in id_block]
                if len(filtered) >= 10:
                    return filtered
                
                # Last resort: if we have less than 10 recipes after ID block, 
                # we still apply ID block but allow name matches (better than nothing)
                # This is rare and only happens when recipe pool is very small
                return filtered if filtered else pool

            before = len(recipes)
            recipes = _apply_exclusion(recipes, recent_recipe_ids, recent_recipe_names)
            after = len(recipes)
            dropped = before - after
            
            # Log detailed info about what was blocked
            if dropped > 0:
                yield Response(f"🔄 Giảm lặp: bỏ {dropped} món đã xuất hiện gần đây để tăng đa dạng.")
                logging.info(
                    "plan_day_e2e_tool: VARIETY_FILTER_APPLIED | user_id=%s | "
                    "recipes_before=%d recipes_after=%d dropped=%d | "
                    "blocked_ids=%d blocked_names=%d",
                    user_id,
                    before,
                    after,
                    dropped,
                    len(recent_recipe_ids),
                    len(recent_recipe_names),
                )
            else:
                logging.debug(
                    "plan_day_e2e_tool: VARIETY_FILTER_APPLIED | user_id=%s | "
                    "no_dishes_dropped recipes_before=%d recipes_after=%d | "
                    "blocked_ids=%d blocked_names=%d",
                    user_id,
                    before,
                    after,
                    len(recent_recipe_ids),
                    len(recent_recipe_names),
                )

            _shuffle_recipes(recipes, times=2)

        except Exception as e:
            logging.debug(f"plan_day_e2e_tool: Could not check recent plans for variety: {e}")

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
        missing_after_refresh = missing_before_refresh
        # Skip refresh if all recipes already have macros to save time/tokens
        if missing_before_refresh > 0:
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
                ][:3]
                logging.debug(
                    "plan_day_e2e_tool: refresh_recipes done | missing_before=%d missing_after=%d sample_missing=%s",
                    missing_before_refresh,
                    missing_after_refresh,
                    missing_ids or "none",
                )
            except Exception as refresh_exc:
                logging.debug(f"plan_day_e2e_tool: refresh_recipes failed, continue without refresh: {refresh_exc}")
        
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
        # Ensure default white rice is never blocked by recency filters
        recent_recipe_ids_set.discard("default_white_rice")

        # Track recipes used inside this planning session to avoid intra-plan repetition
        used_today_ids: set[str] = set()
        used_today_names: set[str] = set()

        def _mark_used(recipe: Dict[str, Any] | None):
            """Remember selected recipe to avoid reusing within the same plan."""
            if not recipe:
                return
            rid = str(recipe.get("food_id", "") or "")
            name = str(recipe.get("dish_name", "")).lower().strip()
            # Skip tracking default white rice to allow daily staple reuse
            if rid and rid != "default_white_rice":
                used_today_ids.add(rid)
            if name and name not in {"cơm trắng", "com trang", "white rice"}:
                used_today_names.add(name)
            logging.debug(
                "plan_day_e2e_tool: mark_used id=%s name=%s | used_today_ids=%d used_today_names=%d",
                rid,
                name,
                len(used_today_ids),
                len(used_today_names),
            )
        
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
                if mapped_recipe and str(mapped_recipe.get("food_id", "")) not in recent_recipe_ids_set and str(mapped_recipe.get("food_id", "")) not in used_today_ids:
                    if _is_hotpot(mapped_recipe):
                        logging.warning(
                            "BREAKFAST_REJECT_HOTPOT: Skipping hotpot for breakfast suggestion: %s",
                            mapped_recipe.get("dish_name"),
                        )
                        continue
                    breakfast = mapped_recipe
                    yield Response(f"✅ Selected breakfast from AI suggestion: {breakfast.get('dish_name', 'Unknown')}")
                    _mark_used(breakfast)
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
                used_recipe_ids=recent_recipe_ids_set | used_today_ids,
                used_recipe_names=used_today_names,
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
            if breakfast:
                _mark_used(breakfast)
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
                used_recipe_ids=recent_recipe_ids_set | used_today_ids,
                used_recipe_names=used_today_names,
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
            if breakfast:
                _mark_used(breakfast)
        if not breakfast:
            yield Response("⚠️ No breakfast dish found. Selecting best available Vietnamese breakfast option...")
            # CRITICAL: Only select Vietnamese breakfast dishes, not main dishes
            best_breakfast = None
            best_protein = 0.0
            for recipe in recipes:
                rid = str(recipe.get("food_id", ""))
                if rid in recent_recipe_ids_set or rid in used_today_ids:
                    continue
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
                    rid = str(recipe.get("food_id", ""))
                    if rid in recent_recipe_ids_set or rid in used_today_ids:
                        continue
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
                        rid = str(recipe.get("food_id", ""))
                        if rid in recent_recipe_ids_set or rid in used_today_ids:
                            continue
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

        # Remember breakfast to avoid reusing within this plan (avoid double-marking)
        bf_id = str(breakfast.get("food_id", ""))
        if bf_id not in used_today_ids:
            _mark_used(breakfast)
        
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
        
        # RELAXED BREAKFAST REPLACEMENT: Only replace if protein is VERY low (< 10g) to preserve LLM suggestions
        # This prevents replacing LLM suggestions with repetitive default dishes
        if breakfast_protein < 10.0:  # REDUCED from min_acceptable_protein (15-20g)
            logging.warning(f"Breakfast protein ({breakfast_protein:.1f}g) is very low (< 10g), trying to find better option...")
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
            # Only replace if significantly better (at least 10g more protein)
            if best_breakfast and best_protein >= breakfast_protein + 10.0:
                breakfast = best_breakfast
                breakfast_macros = _get_meal_macros(best_breakfast)
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
        
        # Reject hotpot for breakfast
        if breakfast and _is_hotpot(breakfast):
            logging.warning(f"Breakfast '{breakfast.get('dish_name', 'Unknown')}' is hotpot; reverting to default light breakfast.")
            breakfast = None
            breakfast_macros = {"kcal": 0, "protein_g": 0, "fat_g": 0, "carb_g": 0}
            breakfast_kcal = 0
            breakfast_protein = 0
            breakfast_fat = 0
        
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
            recipes, excluded, recent_recipe_ids_set, used_today_ids,
            selection_strategy, lunch_targets, lunch_max_kcal
        )
        
        if lunch_carb:
            carb_name = lunch_carb.get('dish_name', 'Unknown')
            if lunch_carb.get("food_id") != "default_white_rice":
                yield Response(f"✅ Selected lunch carb from AI suggestion: {carb_name}")
            else:
                yield Response("ℹ️ No suitable lunch dish found. Using default white rice.")
        
        lunch_rice = lunch_carb
        _mark_used(lunch_rice)
        
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

            # If eating with rice and deficit remains, force-add accompaniments (main/veg/soup)
            lunch_main, lunch_veg, lunch_soup, lunch_msgs = _enrich_rice_meal(
                meal_slot="lunch",
                is_noodle=is_lunch_noodle,
                is_combined=is_lunch_combined,
                meal_main=lunch_main,
                meal_veg=lunch_veg,
                meal_soup=lunch_soup,
                remaining_targets=remaining_targets,
                targets=targets,
                recipes=recipes,
                excluded=excluded,
                recent_recipe_ids_set=recent_recipe_ids_set,
                used_today_ids=used_today_ids,
                preferred_meal_type="lunch",
                main_max_kcal=700.0,
                soup_max_kcal=180.0,
                mark_used_cb=_mark_used,
            )
            for msg in lunch_msgs:
                yield Response(msg)
            
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

            # Mark used to prevent intra-plan reuse
            for dish in (lunch_rice, lunch_main, lunch_veg, lunch_soup, lunch_fruit):
                _mark_used(dish)
            
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
            lunch_main_from_llm = lunch_main and _is_selected_from_llm(lunch_main, llm_draft, "lunch", "main", recipes)
            lunch_veg_from_llm = lunch_veg and _is_selected_from_llm(lunch_veg, llm_draft, "lunch", "vegetable", recipes)
            lunch_fruit_from_llm = lunch_fruit and _is_selected_from_llm(lunch_fruit, llm_draft, "lunch", "fruit", recipes)

            if lunch_main_from_llm:
                yield Response(f"✅ Selected lunch main from AI suggestion: {lunch_main.get('dish_name', 'Unknown')}")
            if lunch_veg_from_llm:
                yield Response(f"✅ Selected lunch vegetable from AI suggestion: {lunch_veg.get('dish_name', 'Unknown')}")
            if lunch_fruit_from_llm:
                yield Response(f"✅ Selected lunch fruit from AI suggestion: {lunch_fruit.get('dish_name', 'Unknown')}")
            
            # CRITICAL: Add supplementary dishes if still deficient in nutrition
            # IMPORTANT: Also add for noodle dishes if nutrition is still deficient
            if remaining_targets and targets:
                current_lunch_dishes = [d for d in [lunch_rice, lunch_main, lunch_soup, lunch_veg, lunch_fruit] if d]
                # For noodle/combined dishes, allow adding more dishes if nutrition is still deficient
                # Use iterative approach to keep adding until nutrition targets are met
                # Reduced to 3 iterations to prevent too many main dishes
                max_iterations = 3
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
                    
                    # CRITICAL: Only stop if too many main dishes AND daily deficit is low
                    # If daily deficit is high, allow more main dishes to meet nutrition targets
                    current_main_count = sum(1 for d in current_lunch_dishes if _is_main_dish(d))
                    if current_main_count >= 3:
                        # Only stop if daily deficit is low - otherwise continue to meet daily targets
                        if kcal_deficit_ratio < 0.15 and protein_deficit_ratio < 0.20:
                            logging.debug(
                                f"LUNCH_SUPP_STOP: Too many main dishes ({current_main_count}) AND "
                                f"daily deficit is low (kcal={kcal_deficit_ratio*100:.1f}%, protein={protein_deficit_ratio*100:.1f}%), "
                                f"stopping to prevent meal imbalance"
                            )
                            break
                        else:
                            # Daily deficit is still high - allow more main dishes
                            logging.debug(
                                f"LUNCH_SUPP_CONTINUE: Daily deficit still high "
                                f"(kcal={kcal_deficit_ratio*100:.1f}%, protein={protein_deficit_ratio*100:.1f}%), "
                                f"allowing more main dishes ({current_main_count}) to meet daily targets"
                            )
                    
                    # CRITICAL: Don't stop too early when daily deficit is still high
                    # Only stop if we're very close to targets AND meal is already large enough
                    # This ensures we continue adding when daily still needs more nutrition
                    current_meal_kcal = current_lunch_macros.get('kcal', 0)
                    meal_size_ratio = current_meal_kcal / lunch_max_kcal if lunch_max_kcal > 0 else 0
                    
                    # Stop only if: (1) deficit is low AND (2) meal is already substantial (>80% of max)
                    if kcal_deficit_ratio < 0.10 and protein_deficit_ratio < 0.15 and meal_size_ratio > 0.80:
                        logging.debug(
                            f"LUNCH_SUPP_STOP: Close enough to targets "
                            f"(kcal_deficit={kcal_deficit_ratio*100:.1f}% < 10%, "
                            f"protein_deficit={protein_deficit_ratio*100:.1f}% < 15%, "
                            f"meal_size={meal_size_ratio*100:.1f}% > 80%)"
                        )
                        break
                    # If daily deficit is still high (>20% kcal or >25% protein), continue even if meal is large
                    elif kcal_deficit_ratio > 0.20 or protein_deficit_ratio > 0.25:
                        # Continue adding to meet daily targets, even if meal exceeds normal limits
                        logging.debug(
                            f"LUNCH_SUPP_CONTINUE: Daily deficit still high "
                            f"(kcal_deficit={kcal_deficit_ratio*100:.1f}%, "
                            f"protein_deficit={protein_deficit_ratio*100:.1f}%), continuing to add dishes"
                        )
                    
                    # CRITICAL: Calculate total consumed so far for accurate excess detection
                    total_consumed_so_far = {
                        "kcal": total_consumed_kcal,
                        "protein_g": total_consumed_protein,
                        "fat_g": breakfast_macros.get("fat_g", 0.0) + current_lunch_macros.get("fat_g", 0.0),
                        "carb_g": breakfast_macros.get("carb_g", 0.0) + current_lunch_macros.get("carb_g", 0.0),
                    }
                    
                    # Add supplementary dishes (skip if standalone noodle)
                    if is_lunch_noodle:
                        logging.debug("LUNCH_SUPP_SKIP: noodle dish selected; skipping supplementary dishes.")
                        supplementary_dishes = []
                    else:
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
                            used_recipe_names=used_today_names,
                        )
                        # Filter out invalid/empty supplementary entries (avoid 'Unknown' zero-macro dishes)
                        # CRITICAL: accept both formats: direct recipe objects OR {"recipe": ...} format
                        filtered_supplementary = []
                        for d in supplementary_dishes:
                            if isinstance(d, dict):
                                # Check if it's a recipe object (has dish_name/food_id) OR wrapped format
                                if d.get("recipe") or d.get("dish_name") or d.get("food_id"):
                                    filtered_supplementary.append(d)
                        supplementary_dishes = filtered_supplementary
                    if not supplementary_dishes:
                        logging.debug(f"LUNCH_SUPP_ITERATION_{iteration + 1}: No more supplementary dishes found, stopping")
                        break  # No more dishes to add
                    
                    logging.debug(
                        f"LUNCH_SUPP_ITERATION_{iteration + 1}: Found {len(supplementary_dishes)} supplementary dish(es): "
                        f"{[d.get('dish_name', 'Unknown') for d in supplementary_dishes]}"
                    )
                    
                    # Update current_lunch_dishes and remaining_targets for next iteration
                    for supp_dish in supplementary_dishes:
                        supp_recipe = supp_dish.get("recipe", supp_dish)
                        all_supplementary_dishes.append(supp_dish)
                        current_lunch_dishes.append(supp_recipe)
                        excluded.append(supp_recipe)
                        recent_recipe_ids_set.add(str(supp_recipe.get("food_id", "")))
                        # Update remaining_targets using the actual recipe macros
                        dish_macros = _macros(supp_recipe)
                        dish_name = (
                            supp_recipe.get("dish_name")
                            or "Unknown"
                        )
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
                    supp_recipe = supp_dish.get("recipe", supp_dish)
                    dish_name = supp_recipe.get('dish_name', 'Unknown')
                    dish_macros = _macros(supp_recipe)
                    assigned = False
                    if _is_main_dish(supp_recipe):
                        # If we already have a main, add as additional main
                        if lunch_main:
                            # Store as additional main (we'll handle this in plan structure)
                            logging.info(f"Added additional main dish to lunch: {dish_name}")
                        else:
                            lunch_main = supp_recipe
                            assigned = True  # Assigned to lunch_main, don't double-count
                            yield Response(f"✅ Added main dish to meet nutrition targets: {dish_name}")
                    elif _is_vegetable_dish(supp_recipe):
                        if not lunch_veg:
                            lunch_veg = supp_recipe
                            assigned = True  # Assigned to lunch_veg, don't double-count
                            yield Response(f"✅ Added vegetable to meet nutrition targets: {dish_name}")
                        else:
                            logging.info(f"Added additional vegetable to lunch: {dish_name}")
                    elif _is_soup(supp_recipe):
                        if not lunch_soup:
                            lunch_soup = supp_recipe
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
                        supp_recipe = supp_dish.get("recipe", supp_dish)
                        supp_macros = _macros(supp_recipe)
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
                    
                    # CRITICAL: Always use actual calculation from original targets (more accurate)
                    # This prevents mismatch when meal exceeds remaining_targets
                    actual_remaining_kcal = max(0.0, daily_kcal_check - total_consumed_so_far_kcal)
                    actual_remaining_protein = max(0.0, daily_protein_check - total_consumed_so_far_protein)
                    actual_remaining_fat = max(0.0, daily_fat_check - total_consumed_so_far_fat)
                    actual_remaining_carb = max(0.0, daily_carb_check - total_consumed_so_far_carb)
                    
                    # Update remaining_targets using actual calculation (single source of truth)
                    remaining_targets["kcal"] = actual_remaining_kcal
                    remaining_targets["protein_g"] = actual_remaining_protein
                    remaining_targets["fat_g"] = actual_remaining_fat
                    remaining_targets["carb_g"] = actual_remaining_carb
                    
                    # Log remaining targets AFTER update (debug only)
                    logging.debug(
                        f"REMAINING_TARGETS (after lunch): "
                        f"kcal={remaining_targets.get('kcal', 0):.1f} protein={remaining_targets.get('protein_g', 0):.1f}g | "
                        f"coverage_kcal={((total_consumed_so_far_kcal / daily_kcal_check) * 100) if daily_kcal_check > 0 else 0:.1f}%"
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
            min_main_kcal = 200.0  # CRITICAL: Require minimum kcal to ensure sufficient nutrition
            if remaining_targets:
                protein_remaining = remaining_targets.get("protein_g", 0.0)
                protein_ratio = protein_remaining / daily_protein if daily_protein > 0 else 1.0
                if protein_ratio > 0.5:
                    max_main_kcal = 650.0
                    min_main_protein = max(base_min_protein, 40.0)
                    min_main_kcal = 300.0  # Increased minimum kcal
                elif protein_remaining > daily_protein * 0.4:
                    max_main_kcal = 600.0
                    min_main_protein = max(base_min_protein, 35.0)
                    min_main_kcal = 250.0
                elif protein_remaining > daily_protein * 0.2:
                    min_main_protein = max(base_min_protein, 30.0)
                    min_main_kcal = 200.0
            elif targets:
                # If no remaining_targets but have targets, assume we need protein
                max_main_kcal = 600.0
                min_main_protein = base_min_protein
                min_main_kcal = 200.0
            
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
                used_recipe_ids=recent_recipe_ids_set | used_today_ids,
                used_recipe_names=used_today_names,
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
                    used_recipe_ids=recent_recipe_ids_set | used_today_ids,
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
            recipes, excluded, recent_recipe_ids_set, used_today_ids,
            selection_strategy, dinner_targets, dinner_max_kcal
        )
        
        if dinner_carb:
            carb_name = dinner_carb.get('dish_name', 'Unknown')
            if dinner_carb.get("food_id") != "default_white_rice":
                yield Response(f"✅ Selected dinner carb from AI suggestion: {carb_name}")
            else:
                yield Response("ℹ️ No suitable dinner dish found. Using default white rice.")
        
        dinner_rice = dinner_carb
        _mark_used(dinner_rice)
        
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
                carb_dish=dinner_rice,
            )

            # If eating with rice and deficit remains, force-add accompaniments (main/veg/soup)
            dinner_main, dinner_veg, dinner_soup, dinner_msgs = _enrich_rice_meal(
                meal_slot="dinner",
                is_noodle=is_dinner_noodle,
                is_combined=is_dinner_combined,
                meal_main=dinner_main,
                meal_veg=dinner_veg,
                meal_soup=dinner_soup,
                remaining_targets=remaining_targets,
                targets=targets,
                recipes=recipes,
                excluded=excluded,
                recent_recipe_ids_set=recent_recipe_ids_set,
                used_today_ids=used_today_ids,
                preferred_meal_type="dinner",
                main_max_kcal=800.0,
                soup_max_kcal=200.0,
                mark_used_cb=_mark_used,
            )
            for msg in dinner_msgs:
                yield Response(msg)
            
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

            # Mark used to prevent intra-plan reuse (before supplementary selection)
            for dish in (dinner_rice, dinner_main, dinner_veg, dinner_soup, dinner_fruit):
                _mark_used(dish)
            
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
            dinner_main_from_llm = dinner_main and _is_selected_from_llm(dinner_main, llm_draft, "dinner", "main", recipes)
            dinner_veg_from_llm = dinner_veg and _is_selected_from_llm(dinner_veg, llm_draft, "dinner", "vegetable", recipes)
            dinner_fruit_from_llm = dinner_fruit and _is_selected_from_llm(dinner_fruit, llm_draft, "dinner", "fruit", recipes)

            if dinner_main_from_llm:
                yield Response(f"✅ Selected dinner main from AI suggestion: {dinner_main.get('dish_name', 'Unknown')}")
            if dinner_veg_from_llm:
                yield Response(f"✅ Selected dinner vegetable from AI suggestion: {dinner_veg.get('dish_name', 'Unknown')}")
            if dinner_fruit_from_llm:
                yield Response(f"✅ Selected dinner fruit from AI suggestion: {dinner_fruit.get('dish_name', 'Unknown')}")
            
            # CRITICAL: Add supplementary dishes if still deficient in nutrition
            # IMPORTANT: Also add for noodle dishes if nutrition is still deficient
            if remaining_targets and targets:
                current_dinner_dishes = [d for d in [dinner_rice, dinner_main, dinner_soup, dinner_veg, dinner_fruit] if d]
                # For noodle/combined dishes, allow adding more dishes if nutrition is still deficient
                # Use iterative approach to keep adding until nutrition targets are met
                # Reduced to 3 iterations to prevent too many main dishes
                max_iterations = 3
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
                    
                    # CRITICAL: Only stop if too many main dishes AND daily deficit is low
                    # If daily deficit is high, allow more main dishes to meet nutrition targets
                    current_main_count = sum(1 for d in current_dinner_dishes if _is_main_dish(d))
                    if current_main_count >= 3:
                        # Only stop if daily deficit is low - otherwise continue to meet daily targets
                        if kcal_deficit_ratio < 0.15 and protein_deficit_ratio < 0.20:
                            logging.debug(
                                f"DINNER_SUPP_STOP: Too many main dishes ({current_main_count}) AND "
                                f"daily deficit is low (kcal={kcal_deficit_ratio*100:.1f}%, protein={protein_deficit_ratio*100:.1f}%), "
                                f"stopping to prevent meal imbalance"
                            )
                            break
                        else:
                            # Daily deficit is still high - allow more main dishes
                            logging.debug(
                                f"DINNER_SUPP_CONTINUE: Daily deficit still high "
                                f"(kcal={kcal_deficit_ratio*100:.1f}%, protein={protein_deficit_ratio*100:.1f}%), "
                                f"allowing more main dishes ({current_main_count}) to meet daily targets"
                            )
                    
                    # CRITICAL: Don't stop too early when daily deficit is still high
                    # Only stop if we're very close to targets AND meal is already large enough
                    current_meal_kcal = current_dinner_macros.get('kcal', 0)
                    meal_size_ratio = current_meal_kcal / dinner_max_kcal if dinner_max_kcal > 0 else 0
                    
                    # Stop only if: (1) deficit is low AND (2) meal is already substantial (>80% of max)
                    if kcal_deficit_ratio < 0.10 and protein_deficit_ratio < 0.15 and meal_size_ratio > 0.80:
                        logging.debug(
                            f"DINNER_SUPP_STOP: Close enough to targets "
                            f"(kcal_deficit={kcal_deficit_ratio*100:.1f}% < 10%, "
                            f"protein_deficit={protein_deficit_ratio*100:.1f}% < 15%)"
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
                    
                    # Add supplementary dishes (skip if standalone noodle ONLY if daily deficit is low)
                    # CRITICAL: If daily deficit is high, still add dishes even for noodle to meet nutrition targets
                    if is_dinner_noodle:
                        # Only skip if daily deficit is low (<15% kcal and <20% protein)
                        if kcal_deficit_ratio < 0.15 and protein_deficit_ratio < 0.20:
                            logging.debug("DINNER_SUPP_SKIP: noodle dish selected and daily deficit is low; skipping supplementary dishes.")
                            supplementary_dishes = []
                        else:
                            logging.debug(
                                f"DINNER_SUPP_CONTINUE: noodle dish selected but daily deficit is high "
                                f"(kcal={kcal_deficit_ratio*100:.1f}%, protein={protein_deficit_ratio*100:.1f}%), "
                                f"adding supplementary dishes to meet daily targets."
                            )
                            # Continue to add supplementary dishes below
                            # CRITICAL: Allow more tolerance when deficit is high to meet nutrition targets
                            # Increase tolerance when deficit is significant (>30% protein or >40% kcal)
                            if protein_deficit_ratio > 0.30 or kcal_deficit_ratio > 0.40:
                                effective_meal_max_kcal = dinner_max_kcal * 1.4  # Allow 40% when deficit is very high
                            elif is_dinner_combined or protein_deficit_ratio > 0.20 or kcal_deficit_ratio > 0.30:
                                effective_meal_max_kcal = dinner_max_kcal * 1.3  # Allow 30% for combined or medium deficit
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
                                effective_meal_max_kcal,
                                macro_tolerance_percent,
                                total_consumed_so_far=total_consumed_so_far,
                                used_recipe_names=used_today_names,
                            )
                            # Filter out invalid/empty supplementary entries (avoid 'Unknown' zero-macro dishes)
                            # CRITICAL: accept both formats: direct recipe objects OR {"recipe": ...} format
                            filtered_supplementary = []
                            for d in supplementary_dishes:
                                if isinstance(d, dict):
                                    # Check if it's a recipe object (has dish_name/food_id) OR wrapped format
                                    if d.get("recipe") or d.get("dish_name") or d.get("food_id"):
                                        filtered_supplementary.append(d)
                            supplementary_dishes = filtered_supplementary
                    else:
                        # CRITICAL: Allow more tolerance when deficit is high to meet nutrition targets
                        # Increase tolerance when deficit is significant (>30% protein or >40% kcal)
                        if protein_deficit_ratio > 0.30 or kcal_deficit_ratio > 0.40:
                            effective_meal_max_kcal = dinner_max_kcal * 1.4  # Allow 40% when deficit is very high
                        elif is_dinner_combined or protein_deficit_ratio > 0.20 or kcal_deficit_ratio > 0.30:
                            effective_meal_max_kcal = dinner_max_kcal * 1.3  # Allow 30% for combined or medium deficit
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
                        # Filter out invalid/empty supplementary entries (avoid 'Unknown' zero-macro dishes)
                        # CRITICAL: accept both formats: direct recipe objects OR {"recipe": ...} format
                        filtered_supplementary = []
                        for d in supplementary_dishes:
                            if isinstance(d, dict):
                                # Check if it's a recipe object (has dish_name/food_id) OR wrapped format
                                if d.get("recipe") or d.get("dish_name") or d.get("food_id"):
                                    filtered_supplementary.append(d)
                        supplementary_dishes = filtered_supplementary
                    
                    if not supplementary_dishes:
                        logging.debug(f"DINNER_SUPP_ITERATION_{iteration + 1}: No more supplementary dishes found, stopping")
                        break  # No more dishes to add
                    
                    logging.debug(
                        f"DINNER_SUPP_ITERATION_{iteration + 1}: Found {len(supplementary_dishes)} supplementary dish(es): "
                        f"{[d.get('dish_name', 'Unknown') for d in supplementary_dishes]}"
                    )
                    
                    # Update current_dinner_dishes and remaining_targets for next iteration
                    for supp_dish in supplementary_dishes:
                        supp_recipe = supp_dish.get("recipe", supp_dish)
                        all_supplementary_dishes.append(supp_dish)
                        current_dinner_dishes.append(supp_recipe)
                        excluded.append(supp_recipe)
                        recent_recipe_ids_set.add(str(supp_recipe.get("food_id", "")))
                        # Update remaining_targets using the actual recipe macros
                        dish_macros = _macros(supp_recipe)
                        dish_name = (
                            supp_recipe.get("dish_name")
                            or "Unknown"
                        )
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
                    supp_recipe = supp_dish.get("recipe", supp_dish)
                    dish_name = supp_recipe.get('dish_name', 'Unknown')
                    dish_macros = _macros(supp_recipe)
                    assigned = False
                    if _is_main_dish(supp_recipe):
                        # If we already have a main, add as additional main
                        if dinner_main:
                            # Store as additional main (we'll handle this in plan structure)
                            logging.info(f"Added additional main dish to dinner: {dish_name}")
                        else:
                            dinner_main = supp_recipe
                            assigned = True  # Assigned to dinner_main, don't double-count
                            yield Response(f"✅ Added main dish to meet nutrition targets: {dish_name}")
                    elif _is_vegetable_dish(supp_recipe):
                        if not dinner_veg:
                            dinner_veg = supp_recipe
                            assigned = True  # Assigned to dinner_veg, don't double-count
                            yield Response(f"✅ Added vegetable to meet nutrition targets: {dish_name}")
                        else:
                            logging.info(f"Added additional vegetable to dinner: {dish_name}")
                    elif _is_soup(supp_recipe):
                        if not dinner_soup:
                            dinner_soup = supp_recipe
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
                        supp_recipe = supp_dish.get("recipe", supp_dish)
                        supp_macros = _macros(supp_recipe)
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
                    
                    # CRITICAL: Always use actual calculation from original targets (more accurate)
                    # This prevents mismatch when meal exceeds remaining_targets
                    actual_remaining_kcal = max(0.0, daily_kcal_check - total_consumed_so_far_kcal)
                    actual_remaining_protein = max(0.0, daily_protein_check - total_consumed_so_far_protein)
                    actual_remaining_fat = max(0.0, daily_fat_check - total_consumed_so_far_fat)
                    actual_remaining_carb = max(0.0, daily_carb_check - total_consumed_so_far_carb)
                    
                    # Update remaining_targets using actual calculation (single source of truth)
                    remaining_targets["kcal"] = actual_remaining_kcal
                    remaining_targets["protein_g"] = actual_remaining_protein
                    remaining_targets["fat_g"] = actual_remaining_fat
                    remaining_targets["carb_g"] = actual_remaining_carb
                    
                    # Log remaining targets AFTER update (debug only)
                    logging.debug(
                        f"REMAINING_TARGETS (after dinner): "
                        f"kcal={remaining_targets.get('kcal', 0):.1f} protein={remaining_targets.get('protein_g', 0):.1f}g | "
                        f"coverage_kcal={((total_consumed_so_far_kcal / daily_kcal_check) * 100) if daily_kcal_check > 0 else 0:.1f}%"
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
                used_recipe_ids=recent_recipe_ids_set | used_today_ids,
                used_recipe_names=used_today_names,
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
                    used_recipe_ids=recent_recipe_ids_set | used_today_ids,
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
            macros = _macros(recipe)
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
            supp_recipe = supp_dish.get("recipe", supp_dish)
            dish_name = supp_recipe.get('dish_name', 'Unknown')
            dish_macros = _macros(supp_recipe)
            if dish_macros.get("kcal", 0) > 0:
                # Determine dish type
                dish_type = "main"
                if _is_vegetable_dish(supp_recipe):
                    dish_type = "vegetable"
                elif _is_soup(supp_recipe):
                    dish_type = "soup"
                elif _is_fruit(supp_recipe):
                    dish_type = "fruit"
                
                plan["lunch"]["accompaniments"].append({
                    "recipe": supp_recipe,
                    "servings": 1.0,
                    "type": dish_type,
                    "macros": _calculate_meal_macros(supp_recipe, 1.0),
                })
                logging.debug(
                    f"PLAN_LUNCH_ADD_SUPP: Added {dish_name} ({dish_type}) to plan accompaniments | "
                    f"kcal={dish_macros.get('kcal', 0):.1f} | protein={dish_macros.get('protein_g', 0):.1f}g"
                )
        
        for supp_dish in dinner_supplementary_dishes:
            supp_recipe = supp_dish.get("recipe", supp_dish)
            dish_name = supp_recipe.get('dish_name', 'Unknown')
            dish_macros = _macros(supp_recipe)
            if dish_macros.get("kcal", 0) > 0:
                # Determine dish type
                dish_type = "main"
                if _is_vegetable_dish(supp_recipe):
                    dish_type = "vegetable"
                elif _is_soup(supp_recipe):
                    dish_type = "soup"
                elif _is_fruit(supp_recipe):
                    dish_type = "fruit"
                
                plan["dinner"]["accompaniments"].append({
                    "recipe": supp_recipe,
                    "servings": 1.0,
                    "type": dish_type,
                    "macros": _calculate_meal_macros(supp_recipe, 1.0),
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
                    # First try soup (preferred replacement) - expand search to all recipes if needed
                    soup_candidates = [
                        r for r in recipes_list 
                        if str(r.get("food_id", "")) not in excluded_ids
                        and str(r.get("food_id", "")) not in [str(rid) for rid in recent_recipe_ids_set]
                        and _is_soup(r) 
                        and not _is_main_dish(r)
                        and _get_meal_macros(r).get("kcal", 0) >= 30.0
                        and _get_meal_macros(r).get("kcal", 0) <= 200.0
                    ]
                    
                    # If no soup found in recipes_list, try searching from all available recipes
                    if not soup_candidates and 'recipes' in globals():
                        soup_candidates = [
                            r for r in recipes
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
                    
                    # If soup not found, try vegetable - expand search if needed
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
                        
                        # If no vegetable found in recipes_list, try searching from all available recipes
                        if not veg_candidates and 'recipes' in globals():
                            veg_candidates = [
                                r for r in recipes
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
                    
                    # If still not found, just remove the excess main dish (better than keeping too many)
                    if not replacement_found:
                        meal_accompaniments.remove(main_to_replace)
                        logging.info(
                            f"{meal_slot.upper()}_REMOVED_EXCESS_MAIN: Removed excess main dish "
                            f"'{main_to_replace.get('recipe', {}).get('dish_name', 'Unknown')}' "
                            f"(could not find suitable soup/vegetable replacement)"
                        )
                        replacements_made += 1
                
                if replacements_made > 0:
                    logging.info(f"{meal_slot.upper()}_REPLACEMENT_SUMMARY: Replaced {replacements_made} main dish(es) with soup/vegetable")
        
        # Check and replace excess main dishes for lunch and dinner
        check_and_replace_excess_main_dishes("lunch", plan["lunch"], recipes, recent_recipe_ids_set)
        check_and_replace_excess_main_dishes("dinner", plan["dinner"], recipes, recent_recipe_ids_set)

        # Prepare target macros for downstream calculations (needed before first use)
        target_kcal = targets.get("tdee_kcal", 0.0) if targets else 0.0
        target_protein = targets.get("protein_g", 0.0) if targets else 0.0
        target_fat = targets.get("fat_g", 0.0) if targets else 0.0
        target_carb = targets.get("carb_g", 0.0) if targets else 0.0

        # Calculate total macros BEFORE any per-meal downscale so we know if we are still far from targets
        totals_before_scaling = _calculate_plan_totals(plan)
        kcal_coverage_before = (totals_before_scaling.get("kcal", 0.0) / target_kcal) if target_kcal else 0.0
        carb_deficit_before = max(0.0, target_carb - totals_before_scaling.get("carb_g", 0.0))
        carb_deficit_ratio_before = (carb_deficit_before / target_carb) if target_carb else 0.0

        # If we are still missing a lot of kcal/carb, do NOT downscale meals by cap – keep servings as-is
        skip_downscale_for_deficit = (kcal_coverage_before < 0.90) or (carb_deficit_ratio_before > 0.20)
        if skip_downscale_for_deficit:
            logging.info(
                "PLAN_SKIP_DOWNSCALE: totals_before=kcal=%.1f(%.1f%%) protein=%.1f fat=%.1f carb=%.1f "
                "| target_kcal=%s target_carb=%s | reason=high_deficit",
                totals_before_scaling.get("kcal", 0.0),
                kcal_coverage_before * 100,
                totals_before_scaling.get("protein_g", 0.0),
                totals_before_scaling.get("fat_g", 0.0),
                totals_before_scaling.get("carb_g", 0.0),
                target_kcal,
                target_carb,
            )

        def _scale_meal_if_needed(meal_key: str, cap_kcal: float, cap_fat: float) -> None:
            meal = plan.get(meal_key)
            if not meal:
                return
            if skip_downscale_for_deficit:
                return  # keep servings to help recover large deficits
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

        # CRITICAL: Scale DOWN if overshooting targets
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
        
        # CRITICAL: Scale UP servings (1.0 - 2.0 max) if still below targets
        # This helps meet daily kcal targets without adding too many dishes
        # CRITICAL: Check ALL macros before scaling - don't scale if protein/fat already exceed tolerance
        max_allowed_protein = target_protein * (1.0 + macro_tolerance_percent) if target_protein else 0.0
        
        # Check current macro status
        current_protein = total_macros.get("protein_g", 0.0)
        current_fat = total_macros.get("fat_g", 0.0)
        current_carb = total_macros.get("carb_g", 0.0)
        current_kcal = total_macros.get("kcal", 0.0)
        
        protein_excess_ratio = (current_protein / target_protein - 1.0) if target_protein > 0 else 0.0
        fat_excess_ratio = (current_fat / target_fat - 1.0) if target_fat > 0 else 0.0
        carb_excess_ratio = (current_carb / target_carb - 1.0) if target_carb > 0 else 0.0
        kcal_deficit_ratio = (target_kcal - current_kcal) / target_kcal if target_kcal > 0 else 0.0
        
        # Only scale UP if:
        # 1. Kcal is below target (deficit > 5%)
        # 2. Macros within tolerance OR kcal deficit is high enough to justify scaling despite mild excess
        within_tolerance = (
            protein_excess_ratio < macro_tolerance_percent
            and fat_excess_ratio < macro_tolerance_percent
            and carb_excess_ratio < macro_tolerance_percent
        )
        kcal_deficit_high = kcal_deficit_ratio > 0.20  # >20% deficit
        mild_macro_excess = (
            protein_excess_ratio < 0.35  # allow up to +35% protein if kcal thiếu nhiều
            and fat_excess_ratio < 0.35
            and carb_excess_ratio < 0.35
        )
        should_scale_up = (
            target_kcal > 0
            and current_kcal < target_kcal * 0.95  # Kcal deficit > 5%
            and (within_tolerance or (kcal_deficit_high and mild_macro_excess))
        )
        
        if should_scale_up:
            # Calculate optimal scale based on kcal deficit
            # More aggressive scaling: if deficit is >20%, allow up to 2.0x
            if kcal_deficit_ratio > 0.20:
                optimal_scale_kcal = min(2.0, 1.0 + (kcal_deficit_ratio * 2.0))  # More aggressive: up to 2.0x
            else:
                optimal_scale_kcal = min(2.0, 1.0 + (kcal_deficit_ratio * 1.5))  # Normal scaling
            
            # CRITICAL: Limit scale based on protein/fat/carb to prevent excessive excess
            # Calculate max safe scale for each macro (if within tolerance); if we are already mildly over but kcal thiếu lớn, relax caps slightly
            max_safe_scale = 2.0  # Default max
            
            if within_tolerance:
                if target_protein > 0 and current_protein > 0:
                    max_protein_scale = max_allowed_protein / current_protein if current_protein > 0 else 2.0
                    max_safe_scale = min(max_safe_scale, max_protein_scale)
                if target_fat > 0 and current_fat > 0:
                    max_fat_scale = max_allowed_fat / current_fat if current_fat > 0 else 2.0
                    max_safe_scale = min(max_safe_scale, max_fat_scale)
                if target_carb > 0 and current_carb > 0:
                    max_carb_scale = max_allowed_carb / current_carb if current_carb > 0 else 2.0
                    max_safe_scale = min(max_safe_scale, max_carb_scale)
            else:
                # Nếu đang thiếu kcal >20% nhưng macro hơi dư, cho phép scale tới 1.3x để bù kcal mà không vượt quá xa
                max_safe_scale = min(max_safe_scale, 1.3)
            
            # Use the minimum of kcal-based scale and safe scale
            optimal_scale = min(optimal_scale_kcal, max_safe_scale)
            
            # Only scale up if it would meaningfully increase kcal (>3% increase)
            if optimal_scale > 1.03:
                logging.info(
                    "PLAN_SERVING_INCREASE: Increasing servings to %.2f to meet kcal targets "
                    "(before_scale: %.1f kcal, target: %.1f kcal, deficit: %.1f%%) | "
                    "protein=%.1f/%.1f (%.1f%%) fat=%.1f/%.1f (%.1f%%) | "
                    "max_safe_scale=%.2f (limited by macro constraints)",
                    optimal_scale,
                    current_kcal,
                    target_kcal,
                    kcal_deficit_ratio * 100,
                    current_protein,
                    target_protein,
                    (current_protein / target_protein * 100) if target_protein > 0 else 0,
                    current_fat,
                    target_fat,
                    (current_fat / target_fat * 100) if target_fat > 0 else 0,
                    max_safe_scale,
                )
                
                # Apply scale to all meals and accompaniments
                for meal_data in plan.values():
                    current_servings = meal_data.get("servings", 1.0)
                    new_servings = min(2.0, round(current_servings * optimal_scale, 2))
                    meal_data["servings"] = new_servings
                    
                    for acc in meal_data.get("accompaniments", []):
                        acc_current_servings = acc.get("servings", 1.0)
                        acc_new_servings = min(2.0, round(acc_current_servings * optimal_scale, 2))
                        acc["servings"] = acc_new_servings
                
                # Recalculate macros with new servings
                _recompute_meal_macros(plan)
                total_macros = _calculate_plan_totals(plan)
                
                logging.info(
                    "PLAN_SERVING_INCREASE_COMPLETE: New totals kcal=%.1f (target=%.1f, coverage=%.1f%%) | "
                    "protein=%.1f/%.1f (%.1f%%) fat=%.1f/%.1f (%.1f%%) carb=%.1f/%.1f (%.1f%%)",
                    total_macros.get("kcal", 0),
                    target_kcal,
                    (total_macros.get("kcal", 0) / target_kcal * 100) if target_kcal > 0 else 0,
                    total_macros.get("protein_g", 0),
                    target_protein,
                    (total_macros.get("protein_g", 0) / target_protein * 100) if target_protein > 0 else 0,
                    total_macros.get("fat_g", 0),
                    target_fat,
                    (total_macros.get("fat_g", 0) / target_fat * 100) if target_fat > 0 else 0,
                    total_macros.get("carb_g", 0),
                    target_carb,
                    (total_macros.get("carb_g", 0) / target_carb * 100) if target_carb > 0 else 0,
                )
                logging.debug(
                    "PLAN_SERVING_INCREASE_SERVINGS: breakfast=%.2f lunch=%.2f dinner=%.2f",
                    plan.get("breakfast", {}).get("servings", 1.0),
                    plan.get("lunch", {}).get("servings", 1.0),
                    plan.get("dinner", {}).get("servings", 1.0),
                )
            else:
                logging.debug(
                    "PLAN_SERVING_INCREASE_SKIP: Optimal scale (%.2f) too small (<1.03), skipping scale UP",
                    optimal_scale,
                )
        else:
            # Log why we're not scaling up
            if current_kcal >= target_kcal * 0.95:
                logging.debug(
                    "PLAN_SERVING_INCREASE_SKIP: Kcal already at %.1f%% of target (%.1f/%.1f), no need to scale UP",
                    (current_kcal / target_kcal * 100) if target_kcal > 0 else 0,
                    current_kcal,
                    target_kcal,
                )
            elif protein_excess_ratio >= macro_tolerance_percent:
                logging.warning(
                    "PLAN_SERVING_INCREASE_SKIP: Protein already exceeds tolerance (%.1f%% excess, %.1f/%.1f), "
                    "cannot scale UP without worsening excess",
                    protein_excess_ratio * 100,
                    current_protein,
                    target_protein,
                )
            elif fat_excess_ratio >= macro_tolerance_percent:
                logging.warning(
                    "PLAN_SERVING_INCREASE_SKIP: Fat already exceeds tolerance (%.1f%% excess, %.1f/%.1f), "
                    "cannot scale UP without worsening excess",
                    fat_excess_ratio * 100,
                    current_fat,
                    target_fat,
                )
            elif carb_excess_ratio >= macro_tolerance_percent:
                logging.warning(
                    "PLAN_SERVING_INCREASE_SKIP: Carb already exceeds tolerance (%.1f%% excess, %.1f/%.1f), "
                    "cannot scale UP without worsening excess",
                    carb_excess_ratio * 100,
                    current_carb,
                    target_carb,
                )

        kcal_coverage = (total_macros["kcal"] / target_kcal * 100) if target_kcal > 0 else 0.0
        protein_coverage = (total_macros["protein_g"] / target_protein * 100) if target_protein > 0 else 0.0
        fat_coverage = (total_macros["fat_g"] / target_fat * 100) if target_fat > 0 else 0.0
        carb_coverage = (total_macros["carb_g"] / target_carb * 100) if target_carb > 0 else 0.0

        logging.info(
            "PLAN_MACROS_SUMMARY: total_kcal=%.1f/%.1f (%.1f%%) | protein=%.1f/%.1f (%.1f%%) | "
            "fat=%.1f/%.1f (%.1f%%) | carb=%.1f/%.1f (%.1f%%)",
            total_macros["kcal"],
            target_kcal,
            kcal_coverage,
            total_macros["protein_g"],
            targets.get("protein_g", 0),
            protein_coverage,
            total_macros["fat_g"],
            targets.get("fat_g", 0),
            fat_coverage,
            total_macros["carb_g"],
            targets.get("carb_g", 0),
            carb_coverage,
        )

        logging.info(
            "PLAN_DEFICIT_DETAIL: kcal_def=%.1f (%.1f%%) protein_def=%.1f (%.1f%%) fat_def=%.1f (%.1f%%) carb_def=%.1f (%.1f%%)",
            target_kcal - total_macros["kcal"],
            100 - kcal_coverage,
            target_protein - total_macros["protein_g"],
            100 - protein_coverage,
            target_fat - total_macros["fat_g"],
            100 - fat_coverage,
            target_carb - total_macros["carb_g"],
            100 - carb_coverage,
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
            
            # REMOVED: LLM suggestions for nutrition deficit
            # This was causing unnecessary API calls, wasting time, and attribute errors
            # The supplementary dish logic already handles nutrition gaps effectively
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

        # Normalize servings to allowed discrete values before final validation.
        # Rules: non-rice dishes => 1 or 2 servings; rice (incl. default) => 1..4.
        _normalize_servings(plan)
        _recompute_meal_macros(plan)
        total_macros = _calculate_plan_totals(plan)

        # Final carb/kcal top-up: if carb deficit remains, increase rice servings
        # (lunch/dinner) up to the cap. Protein excess is acceptable; priority is
        # kcal/carb as requested.
        target_kcal = targets.get("tdee_kcal", 0.0) if targets else 0.0
        target_carb = targets.get("carb_g", 0.0) if targets else 0.0
        if target_kcal > 0 and target_carb > 0:
            carb_deficit = max(0.0, target_carb - total_macros.get("carb_g", 0.0))
            kcal_deficit = max(0.0, target_kcal - total_macros.get("kcal", 0.0))
            if carb_deficit > 0 or kcal_deficit > 0:
                for meal_key in ("lunch", "dinner"):
                    meal = plan.get(meal_key, {})
                    if not meal:
                        continue
                    recipe = meal.get("recipe") or {}
                    # Skip top-up for noodle/combined dishes
                    if _is_noodle_soup(recipe) or _is_combined_dish(recipe):
                        continue
                    # Ensure primary carb is rice; if not, swap to default white rice
                    if not _is_rice_recipe(recipe):
                        meal["recipe"] = _create_default_white_rice_recipe()
                        recipe = meal["recipe"]
                    # Increase rice servings while under cap and deficits remain
                    while meal.get("servings", 1.0) < 4 and (carb_deficit > 0 or kcal_deficit > 0):
                        meal["servings"] += 1.0
                        _recompute_meal_macros(plan)
                        total_macros = _calculate_plan_totals(plan)
                        carb_deficit = max(0.0, target_carb - total_macros.get("carb_g", 0.0))
                        kcal_deficit = max(0.0, target_kcal - total_macros.get("kcal", 0.0))
                        if carb_deficit <= 0 and kcal_deficit <= 0:
                            break

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

        # Generate plan_id early so we can use it in responses
        from MealAgent.tools.utils.planning_helpers import _generate_plan_id
        if not plan_output.get("plan_id"):
            plan_output["plan_id"] = _generate_plan_id(user_id)
        if user_id:
            plan_output["user_id"] = user_id

        # Stream response first for immediate feedback (before saving to DB)
        # Use consistent formatting with 1 decimal place to match other displays
        status_icon = "✅" if validation["valid"] else "⚠️"
        yield Response(
            f"{status_icon} Daily meal plan ready! "
            f"Total: {total_macros['kcal']:.1f} kcal | "
            f"{total_macros['protein_g']:.1f}g protein | "
            f"{total_macros['fat_g']:.1f}g fat | "
            f"{total_macros['carb_g']:.1f}g carbs"
        )
        
        logging.info(
            "PLAN_FINAL_TOTALS: kcal=%.1f prot=%.1f fat=%.1f carb=%.1f | servings: bf=%.2f ln=%.2f dn=%.2f",
            total_macros["kcal"],
            total_macros["protein_g"],
            total_macros["fat_g"],
            total_macros["carb_g"],
            plan.get("breakfast", {}).get("servings", 1.0),
            plan.get("lunch", {}).get("servings", 1.0),
            plan.get("dinner", {}).get("servings", 1.0),
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
        
        # IMPORTANT: Two types of meal data storage:
        # 1. MealPlan + MealPlanItem: Stores SUGGESTED plans (plans that are generated but NOT yet accepted by user)
        #    - These are saved IMMEDIATELY after plan generation (BEFORE yielding to UI)
        #    - Used for: Plan history, variety filtering, plan retrieval
        # 2. MealLogEntry: Stores ACCEPTED/CONSUMED meals (meals that user has accepted or actually eaten)
        #    - These are saved ONLY in 3 cases:
        #      a) User accepts plan via UI (use accept_plan_tool)
        #      b) User says they accept in chat (call log_meal_e2e_tool with user_accepted=True)
        #      c) User says they ate something (call log_meal_e2e_tool with meal_description)
        #    - DO NOT automatically call log_meal_e2e_tool after creating plan
        #    - Used for: Daily nutrition tracking, meal history, remaining targets calculation
        
        # CRITICAL: Save SUGGESTED plan to MealPlan and MealPlanItem collections BEFORE yielding Result
        # This ensures:
        # 1. Plan is available in database when variety filter runs in next request (prevents repetition)
        # 2. Plan is available in database when user accepts (log_meal_e2e_tool loads from Weaviate)
        # IMPORTANT: Tools must work with database (Weaviate) as source of truth
        # - MealPlan: Stores the plan metadata (plan_id, user_id, start_date, etc.)
        # - MealPlanItem: Stores individual meal items in the plan (breakfast, lunch, dinner with recipes)
        # NOTE: This does NOT create MealLogEntry - that only happens when user accepts via log_meal_e2e_tool
        if user_id:
            try:
                # Save to MealPlan and MealPlanItem (suggested plan storage) - synchronous save BEFORE yielding
                saved_plan = sync_plan_to_weaviate(
                    plan_output.copy(),
                    user_id=user_id,
                    client_manager=client_manager,
                    start_date=plan_output.get("start_date"),
                )
                logging.info(
                    "plan_day_e2e_tool: MEALPLAN_SAVE_SUCCESS | plan_id=%s | "
                    "saved_to=MealPlan/MealPlanItem (SUGGESTED plan, not consumed) | "
                    "saved_BEFORE_yield=True (ensures plan available for variety filter in next request)",
                    saved_plan.get('plan_id') if saved_plan else plan_output.get("plan_id"),
                )
                # Update plan_output with saved plan data (in case sync_plan_to_weaviate modified it)
                if saved_plan:
                    plan_output.update(saved_plan)
            except Exception as e:
                logging.error(
                    "plan_day_e2e_tool: MEALPLAN_SAVE_FAILED | plan_id=%s | error=%s",
                    plan_output.get("plan_id"),
                    str(e),
                )
                # Continue even if save fails - plan can still be displayed, but accept may fail
        
        logging.info(
            "plan_day_e2e_tool: PLAN_GENERATED | plan_id=%s user_id=%s | "
            "total_kcal=%.1f total_protein=%.1fg | "
            "meals: breakfast=%s lunch=%s dinner=%s | validation_valid=%s",
            plan_output.get("plan_id"),
            user_id,
            total_macros.get("kcal", 0),
            total_macros.get("protein_g", 0),
            breakfast.get("dish_name", "None") if breakfast else "None",
            lunch_rice.get("dish_name", "None") if lunch_rice else "None",
            dinner_rice.get("dish_name", "None") if dinner_rice else "None",
            validation.get("valid", False),
        )
        
        # Then yield Result for data consistency and UI display
        # Use "meal_plan" payload_type for explicit frontend detection
        # IMPORTANT: Plan is already saved to Weaviate (database) above - database is source of truth
        # Environment may store plan_id for support, but tools must load from Weaviate
        # The plan will be displayed on UI immediately (display=True) so user can review before accepting
        # CRITICAL: Result is automatically saved to environment as "plan_day_e2e_tool.plan" for variety filter
        # Short summary for user (replace separate cited_summarize step)
        bf_name = breakfast.get("dish_name", "Unknown") if breakfast else "None"
        lunch_items = [lunch_rice.get("dish_name", "Unknown") if lunch_rice else "None"]
        for acc in plan.get("lunch", {}).get("accompaniments", []):
            acc_name = acc.get("recipe", {}).get("dish_name", "Unknown")
            if acc_name not in lunch_items:
                lunch_items.append(acc_name)
        dinner_items = [dinner_rice.get("dish_name", "Unknown") if dinner_rice else "None"]
        for acc in plan.get("dinner", {}).get("accompaniments", []):
            acc_name = acc.get("recipe", {}).get("dish_name", "Unknown")
            if acc_name not in dinner_items:
                dinner_items.append(acc_name)
        yield Response(
            f"📋 Tóm tắt nhanh: 🌅 {bf_name} | 🍽️ {', '.join(lunch_items)} | 🌙 {', '.join(dinner_items)}"
        )

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
                "user_id": user_id,
                "can_accept": True,
                "stop_calling_tool": True,
                "end_conversation": True,
            },
            payload_type="meal_plan",
            display=True,
        )

        yield Response("👍 Kế hoạch đã sẵn sàng. Bạn có thể bấm Accept hoặc điều chỉnh.")
        
        logging.info(
            "plan_day_e2e_tool: PLAN_READY | plan_id=%s | plan summarised inline (no cited_summarize).",
            plan_output.get("plan_id"),
        )
        
        # Store plan_id in environment for support (quick reference, not source of truth)
        # IMPORTANT: Environment is only for support - tools must load from Weaviate (database)
        # This plan_id can be used by other tools to quickly reference, but they must load from Weaviate
        if plan_output.get("plan_id"):
            try:
                tree_data.environment.add_objects(
                    "plan_day_e2e_tool",
                    "plan_id",
                    [{"plan_id": plan_output.get("plan_id")}],  # Must be dict, not string
                )
            except Exception as e:
                logging.debug(f"plan_day_e2e_tool: failed to store plan_id in environment: {e}")
        
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


