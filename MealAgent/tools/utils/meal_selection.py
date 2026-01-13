"""
Meal selection module for meal planning tools.
Centralizes all recipe selection logic, strategies, and scoring.
"""

from typing import Dict, Any, List, Optional
import logging
import random

from MealAgent.tools.utils.planning_helpers import _get_meal_macros
from MealAgent.tools.utils.recipe_classifiers import (
    _is_vietnamese_breakfast,
    _is_rice_dish,
    _is_noodle_soup,
    _is_main_dish,
    _is_vegetable_dish,
    _is_fruit,
    _is_combined_dish,
    _matches_meal_slot,
)

logger = logging.getLogger(__name__)


def calculate_recipe_fit_score(
    recipe: Dict[str, Any],
    target_macros: Dict[str, float] | None = None,
    meal_type: str | None = None,
    remaining_targets: Dict[str, float] | None = None,
) -> float:
    """
    Calculate how well a recipe fits the target macros for a specific meal.
    Higher score = better fit.
    
    Args:
        recipe: Recipe to score
        target_macros: Daily macro targets (used if remaining_targets not provided)
        meal_type: Meal type (breakfast/lunch/dinner)
        remaining_targets: Remaining macro targets after previous meals (preferred)
    
    Returns:
        Fit score (0.0 to 100.0+)
    """
    if not target_macros and not remaining_targets:
        return recipe.get("fit_score", 50.0)
    
    recipe_macros = _get_meal_macros(recipe)
    if not recipe_macros.get("kcal"):
        return 0.0
    
    # Use remaining targets if provided, otherwise calculate per-meal targets
    if remaining_targets:
        meal_targets = remaining_targets.copy()
    else:
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
    
    # Calculate fit score with dynamic weights based on remaining needs
    # If protein is critically low, prioritize it heavily
    protein_remaining = meal_targets.get("protein_g", 0.0)
    protein_ratio = protein_remaining / target_macros.get("protein_g", 150.0) if target_macros else 0.33
    
    # Dynamic weights: increase protein weight if remaining protein is high (need more)
    if protein_ratio > 0.4:  # Still need >40% of daily protein
        macro_weights = {
            "protein_g": 0.60,  # VERY high priority when protein is critically needed
            "carb_g": 0.15,
            "kcal": 0.15,
            "fat_g": 0.10,
        }
    elif protein_ratio > 0.2:  # Still need >20% of daily protein
        macro_weights = {
            "protein_g": 0.50,  # High priority when protein is still needed
            "carb_g": 0.20,
            "kcal": 0.20,
            "fat_g": 0.10,
        }
    else:
        macro_weights = {
            "protein_g": 0.40,  # High priority - essential for muscle/health
            "carb_g": 0.25,     # High priority - energy source
            "kcal": 0.20,       # Important but not the only factor
            "fat_g": 0.15,      # Important but lower priority
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
            
            # CRITICAL: Heavy bonus for protein when remaining protein is high
            if macro == "protein_g":
                if protein_ratio > 0.4 and ratio > 0.8:  # High remaining need + good protein content
                    score *= 2.0  # Stronger bonus for high-protein recipes when protein is needed
                elif protein_ratio > 0.4 and ratio > 0.5:  # High remaining need + moderate protein
                    score *= 1.5  # Moderate bonus
                elif ratio < 0.3:  # Very low protein
                    score *= 0.2  # Heavier penalty for low protein
                elif ratio < 0.5:  # Low protein
                    score *= 0.5  # Penalty for low protein
            
            weighted_scores.append(score * weight)
        else:
            weighted_scores.append(0.0)
    
    # Sum weighted scores (not average) to emphasize balanced nutrition
    total_fit = sum(weighted_scores) / sum(macro_weights.values()) if weighted_scores else 0.0
    
    # Combine with original fit_score if available (lower weight on original)
    original_fit = recipe.get("fit_score", 50.0)
    return (total_fit * 0.8) + (original_fit * 0.2)


def filter_by_macro_requirements(
    candidates: List[Dict[str, Any]],
    require_macros: bool = False,
    min_kcal: float = 30.0,
    max_kcal: float | None = None,
    min_protein: float = 0.0,
    max_fat: float | None = None,
) -> List[Dict[str, Any]]:
    """
    Filter candidates by macro requirements.
    
    Args:
        candidates: List of recipe candidates
        require_macros: Whether to require macros
        min_kcal: Minimum kcal requirement
        max_kcal: Maximum kcal limit
        min_protein: Minimum protein requirement
        max_fat: Maximum fat limit
    
    Returns:
        Filtered list of candidates
    """
    if not (require_macros or max_kcal or min_protein > 0 or max_fat):
        return candidates
    
    filtered = []
    for r in candidates:
        macros = r.get("macros_per_serving", {})
        if isinstance(macros, dict):
            kcal = macros.get("kcal", 0)
            protein = macros.get("protein_g", 0)
            fat = macros.get("fat_g", 0)
            # Filter by min_kcal if require_macros
            if require_macros and kcal < min_kcal:
                continue
            # Filter by max_kcal to avoid dishes that are too high in calories
            if max_kcal and kcal > max_kcal:
                continue
            # CRITICAL: Filter by min_protein for main dishes to ensure adequate protein
            if min_protein > 0 and protein < min_protein:
                continue
            # CRITICAL: Filter by max_fat to prevent high-fat dishes from skewing daily total
            if max_fat and fat > max_fat:
                continue
            filtered.append(r)
    
    return filtered if filtered else candidates


def filter_by_dish_category(
    candidates: List[Dict[str, Any]],
    dish_category: str | None,
) -> List[Dict[str, Any]]:
    """
    Filter candidates by dish category.
    IMPROVED: Stricter filtering to prevent category mismatches.
    
    Args:
        candidates: List of recipe candidates
        dish_category: Category to filter by (breakfast/rice/main/vegetable/fruit)
    
    Returns:
        Filtered list of candidates
    """
    if not dish_category:
        return candidates
    
    if dish_category == "breakfast":
        # CRITICAL: Only return breakfast dishes, never fallback to all candidates
        category_candidates = [r for r in candidates if _is_vietnamese_breakfast(r) and not _is_combined_dish(r)]
        # If no breakfast candidates found, return empty list (don't fallback to all candidates)
        return category_candidates
    elif dish_category == "rice":
        # IMPROVED: Stricter filtering - must be rice/noodle AND NOT main dish AND NOT combined
        category_candidates = [
            r for r in candidates 
            if (_is_rice_dish(r) or _is_noodle_soup(r)) 
            and not _is_combined_dish(r) 
            and not _is_main_dish(r)
            and not _is_vietnamese_breakfast(r)
        ]
        # CRITICAL: If no valid candidates, return empty list (don't fallback to all candidates)
        # This prevents selecting main dishes for rice category
        return category_candidates
    elif dish_category == "main":
        # IMPROVED: Must be main dish AND NOT combined AND NOT rice/noodle/breakfast
        category_candidates = [
            r for r in candidates 
            if _is_main_dish(r) 
            and not _is_combined_dish(r)
            and not _is_rice_dish(r)
            and not _is_noodle_soup(r)
            and not _is_vietnamese_breakfast(r)
        ]
        return category_candidates if category_candidates else []
    elif dish_category == "vegetable":
        # IMPROVED: Must be vegetable AND NOT main AND NOT combined AND NOT breakfast
        category_candidates = [
            r for r in candidates 
            if _is_vegetable_dish(r) 
            and not _is_combined_dish(r)
            and not _is_main_dish(r)
            and not _is_vietnamese_breakfast(r)
        ]
        return category_candidates if category_candidates else []
    elif dish_category == "fruit":
        # IMPROVED: Must be fruit AND NOT main AND NOT combined AND NOT breakfast
        category_candidates = [
            r for r in candidates 
            if _is_fruit(r) 
            and not _is_combined_dish(r) 
            and not _is_main_dish(r)
            and not _is_vietnamese_breakfast(r)
        ]
        return category_candidates if category_candidates else []
    else:
        category_candidates = candidates
    
    return category_candidates if category_candidates else []


def apply_selection_strategy(
    candidates: List[Dict[str, Any]],
    strategy: str,
    target_macros: Dict[str, float] | None = None,
    preferred_meal_type: str | None = None,
) -> List[Dict[str, Any]]:
    """
    Apply selection strategy to sort candidates.
    
    Args:
        candidates: List of recipe candidates
        strategy: Selection strategy (highest_carb, highest_protein, balanced, macro_fit)
        target_macros: Target macros for macro_fit strategy
        preferred_meal_type: Preferred meal type for macro_fit strategy
    
    Returns:
        Sorted list of candidates
    """
    if strategy == "highest_carb":
        candidates.sort(key=lambda r: _get_meal_macros(r).get("carb_g", 0.0), reverse=True)
    elif strategy == "highest_protein":
        # IMPROVED: Balance protein priority with variety
        # Instead of pure protein sort, use a combined score: protein * 0.7 + fit_score * 0.3
        # This prevents always selecting the same high-protein dishes
        for r in candidates:
            protein = _get_meal_macros(r).get("protein_g", 0.0)
            fit_score = r.get("fit_score", 50.0)
            # Combined score: prioritize protein but also consider fit_score for variety
            r["_protein_priority_score"] = (protein * 0.7) + (fit_score * 0.3)
        candidates.sort(key=lambda r: r.get("_protein_priority_score", 0.0), reverse=True)
    elif strategy == "macro_fit" and target_macros:
        # Extract remaining_targets from target_macros if present
        remaining_targets = target_macros.get("_remaining_targets")
        for r in candidates:
            r["_macro_fit_score"] = calculate_recipe_fit_score(
                r, target_macros, preferred_meal_type, remaining_targets
            )
        candidates.sort(key=lambda r: r.get("_macro_fit_score", 0.0), reverse=True)
    elif strategy == "balanced":
        # Use macro_fit if targets available, otherwise use fit_score
        if target_macros:
            remaining_targets = target_macros.get("_remaining_targets")
            for r in candidates:
                r["_macro_fit_score"] = calculate_recipe_fit_score(
                    r, target_macros, preferred_meal_type, remaining_targets
                )
            candidates.sort(key=lambda r: r.get("_macro_fit_score", r.get("fit_score", 0.0)), reverse=True)
        else:
            candidates.sort(key=lambda r: r.get("fit_score", 0.0), reverse=True)
    
    return candidates


def add_variety_factor(
    candidates: List[Dict[str, Any]],
    target_macros: Dict[str, float] | None = None,
) -> List[Dict[str, Any]]:
    """
    Add variety factor to break ties and ensure better variety.
    IMPROVED: Much larger random variation and better grouping for maximum variety.
    
    Args:
        candidates: Sorted list of candidates
        target_macros: Optional target macros for score-based variety
    
    Returns:
        Candidates with variety factor applied
    """
    if len(candidates) <= 1:
        return candidates
    
    if target_macros:
        # CRITICAL: Add much larger random variation (±40% instead of ±20%) to significantly increase variety
        # This prevents the same high-protein dishes from being selected repeatedly
        # The larger variation allows lower-ranked candidates to be selected more often
        for r in candidates:
            base_score = r.get("_macro_fit_score", r.get("fit_score", 0.0))
            # Add much larger random variation (±40%) to break ties and maximize variety
            # This ensures we don't always pick the same top protein dishes
            r["_variety_score"] = base_score * (1.0 + random.uniform(-0.40, 0.40))
        candidates.sort(key=lambda r: r.get("_variety_score", 0.0), reverse=True)
    else:
        # IMPROVED: For other strategies, use much larger score groups (50 instead of 20) and shuffle more aggressively
        score_groups = {}
        for r in candidates:
            score = r.get("fit_score", 0.0)
            # Round to nearest 50 to group similar scores (much larger groups = much more variety)
            score_group = int(score / 50) * 50
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
    
    return candidates


def select_with_weighted_random(
    candidates: List[Dict[str, Any]],
    pool_size: int = 10,
) -> Dict[str, Any] | None:
    """
    Select a candidate using weighted random selection from top candidates.
    IMPROVED: Much larger pool and more balanced weights for better variety.
    
    Args:
        candidates: Sorted list of candidates
        pool_size: Size of pool to select from (default 10)
    
    Returns:
        Selected recipe or None
    """
    if not candidates:
        return None
    
    if len(candidates) == 1:
        return candidates[0]
    
    # CRITICAL: Use much larger pool (top 70% instead of 50%) to explore more candidates and reduce repetition
    # This ensures we consider many more dishes, not just the top protein ones
    # Increased from 50% to 70% to significantly improve variety
    actual_pool_size = max(pool_size, min(150, int(len(candidates) * 0.70)))
    top_candidates = candidates[:actual_pool_size]
    
    # CRITICAL: More balanced weights - use square root instead of cube root to make weights even less steep
    # This gives much more chance to lower-ranked candidates, significantly increasing variety
    # Square root (0.5) is less steep than cube root (0.33), giving more equal chances
    weights = [1.0 / ((i + 1) ** 0.5) for i in range(len(top_candidates))]  # Less steep weights for more variety
    total_weight = sum(weights)
    weights = [w / total_weight for w in weights]  # Normalize
    
    return random.choices(top_candidates, weights=weights, k=1)[0]


def validate_selected_recipe(
    recipe: Dict[str, Any] | None,
    dish_category: str | None,
    candidates: List[Dict[str, Any]] | None = None,
) -> Dict[str, Any] | None:
    """
    Validate that selected recipe matches the dish category.
    If not, try to find a better match from candidates.
    IMPROVED: Search through ALL candidates, not just candidates[1:], to find better alternatives.
    
    Args:
        recipe: Selected recipe
        dish_category: Expected dish category
        candidates: Optional list of candidates to search for alternatives
    
    Returns:
        Validated recipe or None
    """
    if not recipe or not dish_category:
        return recipe
    
    # Validate category match with detailed logging
    if dish_category == "main" and not _is_main_dish(recipe):
        logger.warning(
            f"CATEGORY_MISMATCH: Selected recipe '{recipe.get('dish_name', 'Unknown')}' "
            f"(food_id={recipe.get('food_id', 'Unknown')}) does not match category 'main'. "
            f"Recipe type: dish_type={recipe.get('dish_type', 'N/A')}, "
            f"meal_type={recipe.get('meal_type', 'N/A')}"
        )
        if candidates:
            # IMPROVED: Search through ALL candidates, not just candidates[1:]
            for candidate in candidates:
                if candidate != recipe and _is_main_dish(candidate):
                    logger.info(f"CATEGORY_FIX: Replaced with valid main dish '{candidate.get('dish_name', 'Unknown')}'")
                    return candidate
        return None
    elif dish_category == "vegetable" and not _is_vegetable_dish(recipe):
        logger.warning(
            f"CATEGORY_MISMATCH: Selected recipe '{recipe.get('dish_name', 'Unknown')}' "
            f"(food_id={recipe.get('food_id', 'Unknown')}) does not match category 'vegetable'. "
            f"Recipe type: dish_type={recipe.get('dish_type', 'N/A')}, "
            f"meal_type={recipe.get('meal_type', 'N/A')}"
        )
        if candidates:
            # IMPROVED: Search through ALL candidates, not just candidates[1:]
            for candidate in candidates:
                if candidate != recipe and _is_vegetable_dish(candidate) and not _is_main_dish(candidate):
                    logger.info(f"CATEGORY_FIX: Replaced with valid vegetable '{candidate.get('dish_name', 'Unknown')}'")
                    return candidate
        return None
    elif dish_category == "fruit" and not _is_fruit(recipe):
        logger.warning(
            f"CATEGORY_MISMATCH: Selected recipe '{recipe.get('dish_name', 'Unknown')}' "
            f"(food_id={recipe.get('food_id', 'Unknown')}) does not match category 'fruit'. "
            f"Recipe type: dish_type={recipe.get('dish_type', 'N/A')}, "
            f"meal_type={recipe.get('meal_type', 'N/A')}"
        )
        if candidates:
            # IMPROVED: Search through ALL candidates, not just candidates[1:]
            for candidate in candidates:
                if candidate != recipe and _is_fruit(candidate):
                    logger.info(f"CATEGORY_FIX: Replaced with valid fruit '{candidate.get('dish_name', 'Unknown')}'")
                    return candidate
        return None
    elif dish_category == "rice" and not _is_rice_dish(recipe) and not _is_noodle_soup(recipe):
        logger.warning(
            f"CATEGORY_MISMATCH: Selected recipe '{recipe.get('dish_name', 'Unknown')}' "
            f"(food_id={recipe.get('food_id', 'Unknown')}) does not match category 'rice'. "
            f"Recipe type: dish_type={recipe.get('dish_type', 'N/A')}, "
            f"meal_type={recipe.get('meal_type', 'N/A')}, "
            f"is_main={_is_main_dish(recipe)}, is_combined={_is_combined_dish(recipe)}"
        )
        if candidates:
            # IMPROVED: Search through ALL candidates, not just candidates[1:]
            for candidate in candidates:
                if candidate != recipe and (_is_rice_dish(candidate) or _is_noodle_soup(candidate)) and not _is_main_dish(candidate):
                    logger.info(f"CATEGORY_FIX: Replaced with valid rice/noodle '{candidate.get('dish_name', 'Unknown')}'")
                    return candidate
        return None
    
    return recipe


def select_meal_by_strategy(
    recipes: List[Dict[str, Any]],
    strategy: str,
    exclude: List[Dict[str, Any]] | None = None,
    used_recipe_ids: set[str] | None = None,
    used_recipe_names: set[str] | None = None,
    preferred_meal_type: str | None = None,
    dish_category: str | None = None,
    target_macros: Dict[str, float] | None = None,
    require_macros: bool = False,
    min_kcal: float = 30.0,
    max_kcal: float | None = None,
    min_protein: float = 0.0,
    max_fat: float | None = None,
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
        require_macros: Whether to require macros
        min_kcal: Minimum kcal requirement
        max_kcal: Maximum kcal limit
        min_protein: Minimum protein requirement (for main dishes)
        max_fat: Maximum fat limit to prevent excess
    
    Returns:
        Selected recipe or None
    """
    if not recipes:
        return None
    
    # Build exclude IDs set
    exclude_ids = {r.get("food_id") for r in (exclude or []) if r.get("food_id")}
    if used_recipe_ids:
        exclude_ids.update(str(rid) for rid in used_recipe_ids)
    
    # Build exclude name set (lowercased) for variety across meals
    exclude_names = {str(r.get("dish_name", "")).lower().strip() for r in (exclude or []) if r.get("dish_name")}
    if used_recipe_names:
        exclude_names.update(str(n).lower().strip() for n in used_recipe_names)
    # Always allow white rice staples
    exclude_names.discard("cơm trắng")
    exclude_names.discard("com trang")
    exclude_names.discard("white rice")
    
    # Filter by exclude IDs
    candidates = []
    for r in recipes:
        rid = str(r.get("food_id", "") or "")
        name_lower = str(r.get("dish_name", "")).lower().strip()
        if rid in exclude_ids:
            continue
        if name_lower and name_lower in exclude_names:
            continue
        candidates.append(r)
    
    # Filter by macro requirements
    candidates = filter_by_macro_requirements(
        candidates, require_macros, min_kcal, max_kcal, min_protein, max_fat
    )
    
    # Filter by dish category
    candidates = filter_by_dish_category(candidates, dish_category)
    
    # Filter by meal type
    if preferred_meal_type:
        typed_candidates = [r for r in candidates if _matches_meal_slot(r, preferred_meal_type)]
        if typed_candidates:
            candidates = typed_candidates
    
    if not candidates:
        return None
    
    # Apply selection strategy
    candidates = apply_selection_strategy(candidates, strategy, target_macros, preferred_meal_type)
    
    # Add variety factor
    candidates = add_variety_factor(candidates, target_macros)
    
    # Select with weighted random
    selected = select_with_weighted_random(candidates)
    
    # CRITICAL: Validate selection - ensure category match before returning
    selected = validate_selected_recipe(selected, dish_category, candidates)
    
    # IMPROVED: Additional strict validation - if dish_category is specified, ensure selected matches
    # If validation fails, try to find a valid alternative from filtered candidates
    if selected and dish_category:
        is_valid = False
        if dish_category == "breakfast":
            is_valid = _is_vietnamese_breakfast(selected) and not _is_combined_dish(selected)
        elif dish_category == "main":
            is_valid = _is_main_dish(selected) and not _is_combined_dish(selected) and not _is_rice_dish(selected) and not _is_noodle_soup(selected)
        elif dish_category == "rice":
            is_valid = (_is_rice_dish(selected) or _is_noodle_soup(selected)) and not _is_main_dish(selected) and not _is_combined_dish(selected)
        elif dish_category == "vegetable":
            is_valid = _is_vegetable_dish(selected) and not _is_main_dish(selected) and not _is_combined_dish(selected)
        elif dish_category == "fruit":
            is_valid = _is_fruit(selected) and not _is_main_dish(selected) and not _is_combined_dish(selected)
        else:
            is_valid = True  # Unknown category, accept
        
        if not is_valid:
            logger.warning(
                f"Selected recipe '{selected.get('dish_name', 'Unknown')}' does not match category '{dish_category}', "
                f"searching for valid alternative..."
            )
            # Try to find a valid alternative from filtered candidates
            # Filter candidates by category first to ensure we only consider valid options
            filtered_candidates = filter_by_dish_category(candidates, dish_category)
            if filtered_candidates:
                # Use the best candidate from filtered list
                selected = filtered_candidates[0]
                logger.info(f"Replaced with valid {dish_category}: '{selected.get('dish_name', 'Unknown')}'")
            else:
                # No valid candidates found, reject selection
                logger.warning(f"No valid {dish_category} candidates found, rejecting selection")
                selected = None
    
    return selected

