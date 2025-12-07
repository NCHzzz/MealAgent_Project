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
    _scale_main_by_protein,
    _scale_carb_by_kcal,
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
    }


# Recipe classification functions moved to MealAgent.tools.utils.recipe_classifiers


def _calculate_recipe_fit_score(
    recipe: Dict[str, Any],
    target_macros: Dict[str, float] | None = None,
    meal_type: str | None = None,
) -> float:
    """
    Calculate how well a recipe fits the target macros for a specific meal.
    Higher score = better fit.
    """
    if not target_macros:
        return recipe.get("fit_score", 50.0)
    
    recipe_macros = _get_meal_macros(recipe)
    if not recipe_macros.get("kcal"):
        return 0.0
    
    # Calculate per-meal targets (divide daily by 3)
    meal_targets = {
        "kcal": target_macros.get("tdee_kcal", 2000) / 3.0,
        "protein_g": target_macros.get("protein_g", 150) / 3.0,
        "fat_g": target_macros.get("fat_g", 67) / 3.0,
        "carb_g": target_macros.get("carb_g", 200) / 3.0,
    }
    
    # Adjust targets by meal type
    if meal_type == "breakfast":
        # Breakfast typically lighter (25% of daily)
        meal_targets = {k: v * 0.75 for k, v in meal_targets.items()}
    elif meal_type in ["lunch", "dinner"]:
        # Lunch/dinner typically heavier (35-40% of daily)
        meal_targets = {k: v * 1.1 for k, v in meal_targets.items()}
    
    # Calculate fit score with balanced nutrition weights (not just kcal)
    # Weights: protein (30%), carbs (25%), fat (20%), kcal (25%) - prioritize protein and carbs
    macro_weights = {
        "protein_g": 0.30,  # Highest priority - essential for muscle/health
        "carb_g": 0.25,     # High priority - energy source
        "kcal": 0.25,       # Important but not the only factor
        "fat_g": 0.20,      # Important but lower priority
    }
    
    weighted_scores = []
    for macro in ["kcal", "protein_g", "fat_g", "carb_g"]:
        recipe_val = recipe_macros.get(macro, 0.0)
        target_val = meal_targets.get(macro, 1.0)
        weight = macro_weights.get(macro, 0.25)
        
        if target_val > 0:
            ratio = recipe_val / target_val
            # Best fit is when ratio is close to 1.0 (within 0.7-1.3 range)
            if 0.7 <= ratio <= 1.3:
                score = 100.0 - abs(ratio - 1.0) * 50.0  # Max score when ratio = 1.0
            elif 0.5 <= ratio < 0.7 or 1.3 < ratio <= 1.5:
                score = 60.0 - abs(ratio - 1.0) * 20.0  # Medium score
            else:
                score = max(0.0, 30.0 - abs(ratio - 1.0) * 10.0)  # Low score
            
            # Penalize severely if protein is too low (critical for nutrition)
            if macro == "protein_g" and ratio < 0.5:
                score *= 0.5  # Heavy penalty for low protein
            
            weighted_scores.append(score * weight)
        else:
            weighted_scores.append(0.0)
    
    # Sum weighted scores (not average) to emphasize balanced nutrition
    total_fit = sum(weighted_scores) / sum(macro_weights.values()) if weighted_scores else 0.0
    
    # Combine with original fit_score if available (lower weight on original)
    original_fit = recipe.get("fit_score", 50.0)
    return (total_fit * 0.8) + (original_fit * 0.2)


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
        carb_recipe = _select_meal_by_strategy(
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


def _select_accompaniments(
    llm_draft,
    meal_slot: str,
    is_combined: bool,
    is_noodle: bool,
    recipes: List[Dict[str, Any]],
    excluded: List[Dict[str, Any]],
    recent_recipe_ids_set: set[str],
    selection_strategy: str,
    targets: Optional[Dict[str, float]],
) -> tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]], Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """
    Select meal accompaniments (main, soup, vegetable, fruit).
    
    Returns: (main, soup, vegetable, fruit)
    """
    main = None
    soup = None
    vegetable = None
    fruit = None
    
    if is_combined or is_noodle:
        # Combined/noodle: only fruit
        fruit = _try_select_from_llm_suggestions(
            llm_draft, meal_slot, "fruit",
            recipes, excluded, recent_recipe_ids_set,
            min_kcal=30.0
        )
        if not fruit:
            fruit = _select_meal_by_strategy(
                recipes, "balanced",
                exclude=excluded,
                used_recipe_ids=recent_recipe_ids_set,
                preferred_meal_type=meal_slot,
                dish_category="fruit",
                target_macros=targets,
                require_macros=True,
                min_kcal=30.0,
            )
        if fruit and not _is_fruit(fruit):
            logging.warning(f"Selected 'fruit' is not actually a fruit: {fruit.get('dish_name', 'Unknown')}")
            fruit = None
    else:
        # Plain rice: main + soup + vegetable/fruit
        # Select main dish
        main = _try_select_from_llm_suggestions(
            llm_draft, meal_slot, "main",
            recipes, excluded, recent_recipe_ids_set,
            min_kcal=50.0, max_kcal=500.0
        )
        if not main:
            main = _select_meal_by_strategy(
                recipes, selection_strategy if targets else "highest_protein",
                exclude=excluded,
                used_recipe_ids=recent_recipe_ids_set,
                preferred_meal_type=meal_slot,
                dish_category="main",
                target_macros=targets,
                require_macros=True,
                min_kcal=50.0,
                max_kcal=500.0,
            )
        if not main:
            main = _select_meal_by_strategy(
                recipes, "highest_protein",
                exclude=excluded,
                used_recipe_ids=recent_recipe_ids_set,
                preferred_meal_type=meal_slot,
                target_macros=targets,
                require_macros=True,
                min_kcal=50.0,
                max_kcal=500.0,
            )
        
        if main:
            excluded.append(main)
            
            # Select soup
            soup = _select_meal_by_strategy(
                recipes, "balanced",
                exclude=excluded,
                used_recipe_ids=recent_recipe_ids_set,
                preferred_meal_type=meal_slot,
                target_macros=targets,
                require_macros=True,
                min_kcal=30.0,
            )
            if soup and not _is_soup(soup):
                soup = None
            if not soup:
                for recipe in recipes:
                    if recipe in excluded:
                        continue
                    if _is_soup(recipe):
                        soup = recipe
                        break
            if soup:
                excluded.append(soup)
            
            # Select vegetable (preferred) or fruit
            vegetable = _try_select_from_llm_suggestions(
                llm_draft, meal_slot, "vegetable",
                recipes, excluded, recent_recipe_ids_set,
                min_kcal=30.0
            )
            if not vegetable:
                vegetable = _select_meal_by_strategy(
                    recipes, "balanced",
                    exclude=excluded,
                    used_recipe_ids=recent_recipe_ids_set,
                    preferred_meal_type=meal_slot,
                    dish_category="vegetable",
                    target_macros=targets,
                    require_macros=True,
                    min_kcal=30.0,
                )
            
            if vegetable:
                excluded.append(vegetable)
            else:
                # Fallback to fruit if no vegetable
                fruit = _try_select_from_llm_suggestions(
                    llm_draft, meal_slot, "fruit",
                    recipes, excluded, recent_recipe_ids_set,
                    min_kcal=30.0
                )
                if not fruit:
                    fruit = _select_meal_by_strategy(
                        recipes, "balanced",
                        exclude=excluded,
                        used_recipe_ids=recent_recipe_ids_set,
                        preferred_meal_type=meal_slot,
                        dish_category="fruit",
                        target_macros=targets,
                        require_macros=True,
                        min_kcal=30.0,
                    )
                if fruit:
                    excluded.append(fruit)
    
    return main, soup, vegetable, fruit


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


def _select_meal_by_strategy(
    recipes: List[Dict[str, Any]],
    strategy: str,
    exclude: List[Dict[str, Any]] | None = None,
    used_recipe_ids: set[str] | None = None,
    preferred_meal_type: str | None = None,
    dish_category: str | None = None,
    target_macros: Dict[str, float] | None = None,
    require_macros: bool = False,
    min_kcal: float = 30.0,
    max_kcal: float | None = None,  # Filter out dishes with too high kcal
) -> Dict[str, Any] | None:
    """
    Select recipe based on strategy with improved macro-aware selection.
    
    Args:
        recipes: List of recipe candidates
        strategy: Selection strategy (highest_carb, highest_protein, balanced, macro_fit)
        exclude: Recipes to exclude
        used_recipe_ids: Recently used recipe IDs to avoid for variety
        preferred_meal_type: Preferred meal type (breakfast/lunch/dinner)
        dish_category: Specific dish category (rice/main/vegetable/fruit/breakfast)
        target_macros: Target macros for better selection (optional)
    """
    if not recipes:
        return None
    exclude_ids = {r.get("food_id") for r in (exclude or []) if r.get("food_id")}
    if used_recipe_ids:
        exclude_ids.update(str(rid) for rid in used_recipe_ids)
    candidates = [r for r in recipes if r.get("food_id") not in exclude_ids]
    if require_macros or max_kcal:
        filtered = []
        for r in candidates:
            macros = r.get("macros_per_serving", {})
            if isinstance(macros, dict):
                kcal = macros.get("kcal", 0)
                # Filter by min_kcal if require_macros
                if require_macros and kcal < min_kcal:
                    continue
                # Filter by max_kcal to avoid dishes that are too high in calories
                if max_kcal and kcal > max_kcal:
                    continue
                filtered.append(r)
        if filtered:
            candidates = filtered
    if not candidates:
        candidates = recipes

    # Filter by dish category if specified
    if dish_category:
        if dish_category == "breakfast":
            category_candidates = [r for r in candidates if _is_vietnamese_breakfast(r) and not _is_combined_dish(r)]
        elif dish_category == "rice":
            # For rice category, we want plain rice OR standalone noodles, but NOT combined dishes or main dishes
            # Also exclude breakfast items (pancake, bánh, etc.) and protein-rich dishes
            category_candidates = [
                r for r in candidates 
                if (_is_rice_dish(r) or _is_noodle_soup(r)) 
                and not _is_combined_dish(r) 
                and not _is_main_dish(r)  # Exclude main dishes (e.g., "Cá Kho Riềng", "Chả Hoa Ngũ Sắc Phô Mai")
                and not _is_vietnamese_breakfast(r)  # Exclude breakfast items like "Pancake Trứng Chiên"
            ]
            # If still no candidates, try just rice dishes (excluding main dishes and breakfast items)
            if not category_candidates:
                category_candidates = [
                    r for r in candidates 
                    if _is_rice_dish(r) 
                    and not _is_main_dish(r)
                    and not _is_vietnamese_breakfast(r)
                ]
            # Final fallback: noodle/soup dishes (standalone, not combined, not main, not breakfast)
            if not category_candidates:
                category_candidates = [
                    r for r in candidates 
                    if _is_noodle_soup(r) 
                    and not _is_combined_dish(r) 
                    and not _is_main_dish(r)
                    and not _is_vietnamese_breakfast(r)
                ]
        elif dish_category == "main":
            # Main dish should NOT be combined dish
            category_candidates = [r for r in candidates if _is_main_dish(r) and not _is_combined_dish(r)]
        elif dish_category == "vegetable":
            # Vegetable should NOT be combined dish or have protein
            category_candidates = [r for r in candidates if _is_vegetable_dish(r) and not _is_combined_dish(r)]
        elif dish_category == "fruit":
            # Fruit should NOT be combined dish, gỏi, main dish, or breakfast items
            category_candidates = [
                r for r in candidates 
                if _is_fruit(r) 
                and not _is_combined_dish(r) 
                and not _is_main_dish(r)  # Exclude main dishes (e.g., "Chả Hoa Ngũ Sắc Phô Mai")
            ]
        else:
            category_candidates = candidates
        
        if category_candidates:
            candidates = category_candidates

    # Filter by meal type
    if preferred_meal_type:
        typed_candidates = [r for r in candidates if _matches_meal_slot(r, preferred_meal_type)]
        if typed_candidates:
            candidates = typed_candidates

    # Apply strategy with improved macro-aware selection
    if strategy == "highest_carb":
        candidates.sort(key=lambda r: _get_meal_macros(r).get("carb_g", 0.0), reverse=True)
    elif strategy == "highest_protein":
        candidates.sort(key=lambda r: _get_meal_macros(r).get("protein_g", 0.0), reverse=True)
    elif strategy == "macro_fit" and target_macros:
        # New strategy: Select based on macro fit score
        for r in candidates:
            r["_macro_fit_score"] = _calculate_recipe_fit_score(r, target_macros, preferred_meal_type)
        candidates.sort(key=lambda r: r.get("_macro_fit_score", 0.0), reverse=True)
    elif strategy == "balanced":
        # Use macro_fit if targets available, otherwise use fit_score
        if target_macros:
            for r in candidates:
                r["_macro_fit_score"] = _calculate_recipe_fit_score(r, target_macros, preferred_meal_type)
            candidates.sort(key=lambda r: r.get("_macro_fit_score", r.get("fit_score", 0.0)), reverse=True)
        else:
            candidates.sort(key=lambda r: r.get("fit_score", 0.0), reverse=True)
    
    # CRITICAL: After sorting, add random factor to break ties and ensure variety
    # This prevents always selecting the same top candidates
    if len(candidates) > 1:
        # Shuffle candidates with similar scores to ensure variety
        # Group candidates by score ranges and shuffle within groups
        if target_macros:
            # For macro_fit strategy, add small random variation to scores
            for r in candidates:
                base_score = r.get("_macro_fit_score", r.get("fit_score", 0.0))
                # Add random variation (±5%) to break ties
                r["_variety_score"] = base_score * (1.0 + random.uniform(-0.05, 0.05))
            candidates.sort(key=lambda r: r.get("_variety_score", 0.0), reverse=True)
        else:
            # For other strategies, shuffle candidates with similar fit_score
            # Group by score ranges and shuffle within groups
            score_groups = {}
            for r in candidates:
                score = r.get("fit_score", 0.0)
                # Round to nearest 10 to group similar scores
                score_group = int(score / 10) * 10
                if score_group not in score_groups:
                    score_groups[score_group] = []
                score_groups[score_group].append(r)
            
            # Shuffle within each group, then combine
            shuffled_candidates = []
            for score_group in sorted(score_groups.keys(), reverse=True):
                group = score_groups[score_group]
                random.shuffle(group)
                shuffled_candidates.extend(group)
            candidates = shuffled_candidates
    
    # IMPROVED VARIETY: Randomly select from a larger pool to ensure better variety
    # Instead of always picking top 5, use a weighted random selection from top candidates
    if len(candidates) > 1:
        # Use larger pool for better variety (top 20% or at least 10, max 30)
        pool_size = max(10, min(30, int(len(candidates) * 0.2)))
        top_candidates = candidates[:pool_size]
        
        # Weighted random: higher weight for better candidates, but still allow lower-ranked ones
        # This ensures variety while maintaining quality
        weights = [1.0 / (i + 1) for i in range(len(top_candidates))]  # Decreasing weights
        total_weight = sum(weights)
        weights = [w / total_weight for w in weights]  # Normalize
        
        selected = random.choices(top_candidates, weights=weights, k=1)[0]
        return selected
    elif candidates:
        return candidates[0]
    else:
        return None


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
    recent_plan_window_minutes: int = 10,  # for testing; set to 10080 (7 days) in production
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
                limit=100,  # Get more recipes for better variety (increased from 50)
                top_k=50,  # Top 50 for planning (increased from 30 for better variety)
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
                    
                    # Also add meal history recipe IDs to exclusion
                    if 'meal_history_recipe_ids' in locals():
                        recent_recipe_ids.update(meal_history_recipe_ids)
                    
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
        # Breakfast: ~25% of daily target, max 600 kcal
        # Lunch/Dinner: ~37.5% of daily target, max 900 kcal per meal
        breakfast_max_kcal = min(600.0, (targets.get("tdee_kcal", 2000) * 0.25 * 1.2) if targets else 600.0)
        meal_max_kcal = min(900.0, (targets.get("tdee_kcal", 2000) * 0.375 * 1.2) if targets else 900.0)
        
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
                    breakfast = mapped_recipe
                    yield Response(f"✅ Selected breakfast from AI suggestion: {breakfast.get('dish_name', 'Unknown')}")
                    break
        
        # Fallback to rule-based selection if LLM mapping failed
        if not breakfast:
            breakfast = _select_meal_by_strategy(
                recipes, selection_strategy if targets else "highest_carb", 
                used_recipe_ids=recent_recipe_ids_set,
                preferred_meal_type="breakfast",
                dish_category="breakfast",
                target_macros=targets
            )
        if not breakfast:
            # Fallback: try any breakfast-type dish
            breakfast = _select_meal_by_strategy(
                recipes, "highest_carb", 
                used_recipe_ids=recent_recipe_ids_set,
                preferred_meal_type="breakfast", 
                target_macros=targets
            )
        if not breakfast:
            yield Response("⚠️ No breakfast dish found. Selecting best available option...")
            breakfast = recipes[0] if recipes else None
            if not breakfast:
                yield Response("❌ No recipes available for planning. Please search for recipes first.")
                return
        
        # Lunch: Vietnamese lunch pattern - use helper functions
        excluded = [breakfast]
        
        # Select lunch carb with validation
        lunch_carb, is_lunch_combined, is_lunch_noodle = _select_carb_with_validation(
            llm_draft, "lunch",
            recipes, excluded, recent_recipe_ids_set,
            selection_strategy, targets, meal_max_kcal
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
            
            lunch_main, lunch_soup, lunch_veg, lunch_fruit = _select_accompaniments(
                llm_draft, "lunch", is_lunch_combined, is_lunch_noodle,
                recipes, excluded, recent_recipe_ids_set,
                selection_strategy, targets
            )
            
            # User feedback for LLM selections
            if lunch_main and _try_select_from_llm_suggestions(llm_draft, "lunch", "main", recipes, [], recent_recipe_ids_set, 50.0, 500.0):
                yield Response(f"✅ Selected lunch main from AI suggestion: {lunch_main.get('dish_name', 'Unknown')}")
            if lunch_veg and _try_select_from_llm_suggestions(llm_draft, "lunch", "vegetable", recipes, [], recent_recipe_ids_set, 30.0):
                yield Response(f"✅ Selected lunch vegetable from AI suggestion: {lunch_veg.get('dish_name', 'Unknown')}")
            if lunch_fruit and _try_select_from_llm_suggestions(llm_draft, "lunch", "fruit", recipes, [], recent_recipe_ids_set, 30.0):
                yield Response(f"✅ Selected lunch fruit from AI suggestion: {lunch_fruit.get('dish_name', 'Unknown')}")
        
        # Validate lunch components
        if not lunch_rice:
            yield Response("⚠️ Could not find lunch dish. Using available options...")
            remaining = [r for r in recipes if r not in [breakfast]]
            lunch_rice = remaining[0] if remaining else breakfast
            is_lunch_combined = lunch_rice and _is_combined_dish(lunch_rice)
        
        if not is_lunch_combined and not lunch_main:
            # If plain rice but no main dish, try to find one
            excluded = [breakfast, lunch_rice]
            lunch_main = _select_meal_by_strategy(
                recipes, "highest_protein", 
                exclude=excluded, 
                used_recipe_ids=recent_recipe_ids_set,
                preferred_meal_type="lunch", 
                target_macros=targets,
                require_macros=True,
                min_kcal=50.0,
            )
        
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
        
        # Select dinner carb with validation
        dinner_carb, is_dinner_combined, is_dinner_noodle = _select_carb_with_validation(
            llm_draft, "dinner",
            recipes, excluded, recent_recipe_ids_set,
            selection_strategy, targets, meal_max_kcal
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
            
            dinner_main, dinner_soup, dinner_veg, dinner_fruit = _select_accompaniments(
                llm_draft, "dinner", is_dinner_combined, is_dinner_noodle,
                recipes, excluded, recent_recipe_ids_set,
                selection_strategy, targets
            )
            
            # User feedback for LLM selections
            if dinner_main and _try_select_from_llm_suggestions(llm_draft, "dinner", "main", recipes, [], recent_recipe_ids_set, 50.0, 500.0):
                yield Response(f"✅ Selected dinner main from AI suggestion: {dinner_main.get('dish_name', 'Unknown')}")
            if dinner_veg and _try_select_from_llm_suggestions(llm_draft, "dinner", "vegetable", recipes, [], recent_recipe_ids_set, 30.0):
                yield Response(f"✅ Selected dinner vegetable from AI suggestion: {dinner_veg.get('dish_name', 'Unknown')}")
            if dinner_fruit and _try_select_from_llm_suggestions(llm_draft, "dinner", "fruit", recipes, [], recent_recipe_ids_set, 30.0):
                yield Response(f"✅ Selected dinner fruit from AI suggestion: {dinner_fruit.get('dish_name', 'Unknown')}")
        
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
            dinner_main = _select_meal_by_strategy(
                recipes, "highest_protein", 
                exclude=excluded, 
                used_recipe_ids=recent_recipe_ids_set,
                preferred_meal_type="dinner", 
                target_macros=targets,
                require_macros=True,
                min_kcal=50.0,
            )

        # Phase 3.2: Stream draft early (tên món) before macro calculations
        yield Response("📋 Draft meal plan:")
        breakfast_name = breakfast.get("dish_name", "Unknown") if breakfast else "Not selected"
        yield Response(f"  🌅 Breakfast: {breakfast_name}")
        
        if lunch_rice:
            lunch_items = [lunch_rice.get("dish_name", "Unknown")]
            # If combined dish or noodle dish, no separate main dish
            if lunch_main:
                lunch_items.append(lunch_main.get("dish_name", "Unknown"))
            if lunch_soup:
                lunch_items.append(lunch_soup.get("dish_name", "Unknown"))
            if lunch_veg:
                lunch_items.append(lunch_veg.get("dish_name", "Unknown"))
            if lunch_fruit:
                lunch_items.append(lunch_fruit.get("dish_name", "Unknown"))
            yield Response(f"  🍽️ Lunch: {', '.join(lunch_items)}")
        
        if dinner_rice:
            dinner_items = [dinner_rice.get("dish_name", "Unknown")]
            # If combined dish or noodle dish, no separate main dish
            if dinner_main:
                dinner_items.append(dinner_main.get("dish_name", "Unknown"))
            if dinner_soup:
                dinner_items.append(dinner_soup.get("dish_name", "Unknown"))
            if dinner_veg:
                dinner_items.append(dinner_veg.get("dish_name", "Unknown"))
            if dinner_fruit:
                dinner_items.append(dinner_fruit.get("dish_name", "Unknown"))
            yield Response(f"  🌙 Dinner: {', '.join(dinner_items)}")
        
        yield Response("⚖️ Calculating nutrition details...")

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
        
        # Calculate macros for lunch and dinner (including accompaniments)
        lunch_macros = _calculate_meal_macros(lunch_rice, plan["lunch"]["servings"])
        for acc in plan["lunch"]["accompaniments"]:
            acc_macros = _calculate_meal_macros(acc["recipe"], acc["servings"])
            for k in lunch_macros:
                lunch_macros[k] += acc_macros[k]
        plan["lunch"]["macros"] = lunch_macros
        
        # Keep both main-only macros and total (with accompaniments) for FE display vs validation
        plan["lunch"]["macros_main"] = _calculate_meal_macros(lunch_rice, plan["lunch"]["servings"])
        plan["lunch"]["macros_total"] = lunch_macros

        dinner_macros = _calculate_meal_macros(dinner_rice, plan["dinner"]["servings"])
        for acc in plan["dinner"]["accompaniments"]:
            acc_macros = _calculate_meal_macros(acc["recipe"], acc["servings"])
            for k in dinner_macros:
                dinner_macros[k] += acc_macros[k]
        plan["dinner"]["macros"] = dinner_macros
        plan["dinner"]["macros_main"] = _calculate_meal_macros(dinner_rice, plan["dinner"]["servings"])
        plan["dinner"]["macros_total"] = dinner_macros

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
        total_macros = {"kcal": 0.0, "protein_g": 0.0, "fat_g": 0.0, "carb_g": 0.0}
        for meal_key, meal_data in plan.items():
            # Main recipe
            recipe = meal_data["recipe"]
            servings = meal_data.get("servings", 1.0)
            macros = _get_meal_macros(recipe)
            for k in total_macros:
                total_macros[k] += macros[k] * servings
            
            # Accompaniments (for lunch/dinner Vietnamese meals)
            accompaniments = meal_data.get("accompaniments", [])
            for acc in accompaniments:
                acc_recipe = acc.get("recipe")
                acc_servings = acc.get("servings", 1.0)
                if acc_recipe:
                    acc_macros = _get_meal_macros(acc_recipe)
                    for k in total_macros:
                        total_macros[k] += acc_macros[k] * acc_servings

        logging.debug(
            "plan_day_e2e_tool: plan macros totals kcal=%.1f protein=%.1f fat=%.1f carb=%.1f | targets=%s",
            total_macros["kcal"],
            total_macros["protein_g"],
            total_macros["fat_g"],
            total_macros["carb_g"],
            targets,
        )
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
                    max_iterations = 3  # Maximum iterations to avoid infinite loops
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


