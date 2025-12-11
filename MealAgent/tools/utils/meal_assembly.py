"""
Meal assembly module for meal planning tools.
Centralizes logic for assembling meals with accompaniments and supplementary dishes.
"""

from typing import Dict, Any, List, Optional, Tuple
import logging

from MealAgent.tools.utils.planning_helpers import _get_meal_macros
from MealAgent.tools.utils.recipe_classifiers import (
    _is_main_dish,
    _is_vegetable_dish,
    _is_fruit,
    _is_soup,
)
from MealAgent.tools.utils.meal_selection import select_meal_by_strategy

logger = logging.getLogger(__name__)


def calculate_meal_macros(
    dishes: List[Dict[str, Any]],
    servings: float = 1.0,
) -> Dict[str, float]:
    """
    Calculate total macros for a list of dishes.
    
    Args:
        dishes: List of recipe dictionaries
        servings: Serving size multiplier (default 1.0)
    
    Returns:
        Dictionary with total macros
    """
    total_macros = {"kcal": 0.0, "protein_g": 0.0, "fat_g": 0.0, "carb_g": 0.0}
    for dish in dishes:
        if dish:
            macros = _get_meal_macros(dish)
            for k in total_macros:
                total_macros[k] += macros.get(k, 0.0) * servings
    return total_macros


def add_supplementary_dishes(
    meal_slot: str,
    current_dishes: List[Dict[str, Any]],
    remaining_targets: Dict[str, float],
    targets: Dict[str, float],
    recipes: List[Dict[str, Any]],
    excluded: List[Dict[str, Any]],
    recent_recipe_ids_set: set[str],
    meal_max_kcal: float,
    macro_tolerance: float = 0.15,
    total_consumed_so_far: Optional[Dict[str, float]] = None,
) -> List[Dict[str, Any]]:
    """
    Add supplementary dishes to meet nutrition targets if still deficient.
    
    Args:
        meal_slot: "lunch" or "dinner"
        current_dishes: List of already selected dishes for this meal
        remaining_targets: Remaining nutrition targets after current dishes
        targets: Full daily nutrition targets
        recipes: Available recipes
        excluded: Dishes to exclude
        recent_recipe_ids_set: Recently used recipe IDs
        meal_max_kcal: Maximum kcal for this meal
        macro_tolerance: Tolerance for macro targets (default 15%)
    
    Returns:
        List of additional dishes to add
    """
    additional_dishes = []
    
    if not remaining_targets or not targets:
        return additional_dishes
    
    # Calculate current meal macros
    current_meal_macros = calculate_meal_macros(current_dishes)
    
    # Check if we need more nutrition
    protein_needed = remaining_targets.get("protein_g", 0.0)
    kcal_needed = remaining_targets.get("kcal", 0.0)
    fat_needed = remaining_targets.get("fat_g", 0.0)
    carb_needed = remaining_targets.get("carb_g", 0.0)
    daily_protein = targets.get("protein_g", 150.0)
    daily_kcal = targets.get("tdee_kcal", 2000.0)
    daily_fat = targets.get("fat_g", 60.0)
    daily_carb = targets.get("carb_g", 219.0)
    
    # CRITICAL: Calculate fat/carb excess based on TOTAL consumed so far, not just remaining_targets
    # This is more accurate because remaining_targets may not be updated correctly
    if total_consumed_so_far:
        total_consumed_fat = total_consumed_so_far.get("fat_g", 0.0) + current_meal_macros.get("fat_g", 0.0)
        total_consumed_carb = total_consumed_so_far.get("carb_g", 0.0) + current_meal_macros.get("carb_g", 0.0)
        total_consumed_kcal = total_consumed_so_far.get("kcal", 0.0) + current_meal_macros.get("kcal", 0.0)
        total_consumed_protein = total_consumed_so_far.get("protein_g", 0.0) + current_meal_macros.get("protein_g", 0.0)
        
        # Calculate excess based on total consumed vs daily targets
        actual_fat_excess = total_consumed_fat - daily_fat
        actual_carb_excess = total_consumed_carb - daily_carb
        actual_kcal_excess = total_consumed_kcal - daily_kcal
        
        fat_excess_ratio = actual_fat_excess / daily_fat if daily_fat > 0 and actual_fat_excess > 0 else 0.0
        carb_excess_ratio = actual_carb_excess / daily_carb if daily_carb > 0 and actual_carb_excess > 0 else 0.0
        kcal_excess_ratio = actual_kcal_excess / daily_kcal if daily_kcal > 0 and actual_kcal_excess > 0 else 0.0
        
        has_fat_excess = actual_fat_excess > 0
        has_carb_excess = actual_carb_excess > 0
        has_kcal_excess = actual_kcal_excess > 0
        fat_excess_amount = actual_fat_excess if has_fat_excess else 0.0
        carb_excess_amount = actual_carb_excess if has_carb_excess else 0.0
    else:
        # Fallback to remaining_targets if total_consumed_so_far not provided
        protein_deficit_ratio = protein_needed / daily_protein if daily_protein > 0 else 0.0
        kcal_deficit_ratio = kcal_needed / daily_kcal if daily_kcal > 0 else 0.0
        fat_excess_ratio = -fat_needed / daily_fat if daily_fat > 0 and fat_needed < 0 else 0.0
        carb_excess_ratio = -carb_needed / daily_carb if daily_carb > 0 and carb_needed < 0 else 0.0
        has_fat_excess = fat_needed < 0
        has_carb_excess = carb_needed < 0
        has_kcal_excess = False
        fat_excess_amount = abs(fat_needed) if has_fat_excess else 0.0
        carb_excess_amount = abs(carb_needed) if has_carb_excess else 0.0
    
    # Calculate deficit ratios - use lower thresholds to add more dishes
    protein_deficit_ratio = protein_needed / daily_protein if daily_protein > 0 else 0.0
    kcal_deficit_ratio = kcal_needed / daily_kcal if daily_kcal > 0 else 0.0
    
    # CRITICAL: Calculate carb deficit ratio to prioritize adding carb when needed
    carb_needed = remaining_targets.get("carb_g", 0.0)
    carb_deficit_ratio = carb_needed / daily_carb if daily_carb > 0 and carb_needed > 0 else 0.0
    has_carb_deficit = carb_needed > 0
    
    # CRITICAL: Log key information about current state (simplified)
    logger.debug(
        f"ADD_SUPP_DISHES_{meal_slot.upper()}: "
        f"protein_needed={protein_needed:.1f}g ({protein_deficit_ratio*100:.1f}%) | "
        f"kcal_needed={kcal_needed:.1f} ({kcal_deficit_ratio*100:.1f}%) | "
        f"fat_excess={fat_excess_ratio*100:.1f}% | "
        f"carb_excess={carb_excess_ratio*100:.1f}% | "
        f"current_meal_kcal={current_meal_macros.get('kcal', 0):.1f} | "
        f"remaining_meal_kcal={meal_max_kcal - current_meal_macros.get('kcal', 0):.1f}"
    )
    
    # CRITICAL: Add dishes if we're below targets - but STRICTLY control excess
    # Priority: protein first, then kcal, but STOP if we exceed targets
    # Tighter cap to avoid runaway additions/repeated mains
    max_additional_dishes = 1
    dishes_added = 0
    
    # Get all excluded dish IDs
    excluded_ids = {str(d.get("food_id", "")) for d in excluded if d}
    excluded_ids.update({str(d.get("food_id", "")) for d in current_dishes if d})
    
    # Initialize excess flags
    has_severe_fat_excess = False
    has_severe_carb_excess = False
    has_severe_kcal_excess = False
    
    # Helper function to recalculate excess after adding dishes
    def recalculate_excess():
        """Recalculate excess ratios based on current meal macros and total consumed so far."""
        nonlocal fat_excess_ratio, carb_excess_ratio, kcal_excess_ratio, has_severe_fat_excess, has_severe_carb_excess, has_severe_kcal_excess
        if total_consumed_so_far:
            total_consumed_fat = total_consumed_so_far.get("fat_g", 0.0) + current_meal_macros.get("fat_g", 0.0)
            total_consumed_carb = total_consumed_so_far.get("carb_g", 0.0) + current_meal_macros.get("carb_g", 0.0)
            total_consumed_kcal = total_consumed_so_far.get("kcal", 0.0) + current_meal_macros.get("kcal", 0.0)
            
            actual_fat_excess = total_consumed_fat - daily_fat
            actual_carb_excess = total_consumed_carb - daily_carb
            actual_kcal_excess = total_consumed_kcal - daily_kcal
            
            fat_excess_ratio = actual_fat_excess / daily_fat if daily_fat > 0 and actual_fat_excess > 0 else 0.0
            carb_excess_ratio = actual_carb_excess / daily_carb if daily_carb > 0 and actual_carb_excess > 0 else 0.0
            kcal_excess_ratio = actual_kcal_excess / daily_kcal if daily_kcal > 0 and actual_kcal_excess > 0 else 0.0
        else:
            fat_needed = remaining_targets.get("fat_g", 0.0)
            carb_needed = remaining_targets.get("carb_g", 0.0)
            fat_excess_ratio = -fat_needed / daily_fat if daily_fat > 0 and fat_needed < 0 else 0.0
            carb_excess_ratio = -carb_needed / daily_carb if daily_carb > 0 and carb_needed < 0 else 0.0
            kcal_excess_ratio = 0.0
        
        # CRITICAL: Balanced threshold - stop at 15% excess, but allow more if deficit is high
        has_severe_fat_excess = fat_excess_ratio > 0.15  # Balanced: 15% to prevent over-eating but allow nutrition
        has_severe_carb_excess = carb_excess_ratio > 0.15  # Balanced: 15%
        has_severe_kcal_excess = kcal_excess_ratio > 0.15 if total_consumed_so_far else False  # Balanced: 15%
    
    # Initialize excess flags
    recalculate_excess()
    
    # Helper function to check if we should stop adding dishes
    def should_stop_adding():
        """Check if we should stop adding dishes due to excess."""
        # CRITICAL: Stop immediately if fat excess is very high (>40%) - this is unhealthy
        if fat_excess_ratio > 0.40:
            # Only continue if we REALLY need protein/kcal (very high threshold: >35% protein or >40% kcal)
            if protein_deficit_ratio > 0.35 or kcal_deficit_ratio > 0.40:
                return False  # Continue only if deficit is critical
            return True  # Stop if fat excess is high
        
        # CRITICAL: Stop if carb excess is extremely high (>50%)
        if carb_excess_ratio > 0.50:
            if protein_deficit_ratio > 0.30 or kcal_deficit_ratio > 0.35:
                return False
            return True
        
        # CRITICAL: Stop if kcal excess is extremely high (>50%)
        if kcal_excess_ratio > 0.50:
            if protein_deficit_ratio > 0.30 or kcal_deficit_ratio > 0.35:
                return False
            return True
        
        # For moderate excess (15-50%), stricter: only continue when deficit is still meaningful
        if has_severe_fat_excess or has_severe_carb_excess or has_severe_kcal_excess:
            if protein_deficit_ratio > 0.25 or kcal_deficit_ratio > 0.25:
                return False
            return True
        return False
    
    # CRITICAL: Stop adding if we have severe excess in ANY macro (fat, carb, or kcal)
    should_add_main = (protein_deficit_ratio > 0.05 or kcal_deficit_ratio > 0.10) and dishes_added < max_additional_dishes
    # If we have severe excess, only add if we really need protein/kcal (very high threshold)
    if should_stop_adding():
        should_add_main = False
        logger.debug(
            f"ADD_SUPP_PRIORITY1_{meal_slot.upper()}_STOP_EXCESS: "
            f"fat_excess={fat_excess_ratio*100:.1f}% | "
            f"carb_excess={carb_excess_ratio*100:.1f}% | "
            f"kcal_excess={kcal_excess_ratio*100:.1f}% | "
            f"protein_deficit={protein_deficit_ratio*100:.1f}% | "
            f"kcal_deficit={kcal_deficit_ratio*100:.1f}%"
        )
    logger.debug(
        f"ADD_SUPP_PRIORITY1_{meal_slot.upper()}: "
        f"should_add_main={should_add_main} | "
        f"protein_deficit_ratio={protein_deficit_ratio*100:.1f}% | "
        f"kcal_deficit_ratio={kcal_deficit_ratio*100:.1f}% | "
        f"dishes_added={dishes_added}/{max_additional_dishes}"
    )
    
    if should_add_main:
        remaining_meal_kcal = meal_max_kcal - current_meal_macros.get("kcal", 0.0)
        # CRITICAL: Allow adding dishes even if we're close to meal_max_kcal, but prioritize if we have budget
        # If remaining_meal_kcal is small but we still need nutrition, allow dishes that might slightly exceed
        if remaining_meal_kcal > 20.0 or (protein_deficit_ratio > 0.20 or kcal_deficit_ratio > 0.30):  # Very low threshold or high deficit
            # CRITICAL: Calculate min_protein_needed more aggressively to meet targets
            min_protein_needed = min(protein_needed * 0.25, 12.0)  # Lower threshold to allow more dishes
            
            # CRITICAL: STRICTLY control max_kcal_for_dish to prevent over-eating
            # Don't allow dishes that would cause meal to exceed meal_max_kcal by more than 20%
            max_meal_kcal_allowed = meal_max_kcal * 1.2  # Maximum 20% over meal_max_kcal
            remaining_before_exceed = max_meal_kcal_allowed - current_meal_macros.get("kcal", 0.0)
            
            if remaining_meal_kcal < 0:
                # If already exceeded meal_max_kcal, only allow small dishes (max 200-300 kcal)
                if protein_deficit_ratio > 0.30 or kcal_deficit_ratio > 0.40:
                    max_kcal_for_dish = min(350.0, remaining_before_exceed)  # Increased to allow larger dishes when deficit is high
                    min_kcal_for_dish = 30.0
                elif protein_deficit_ratio > 0.20 or kcal_deficit_ratio > 0.30:
                    max_kcal_for_dish = min(300.0, remaining_before_exceed)  # Increased to allow medium dishes
                    min_kcal_for_dish = 30.0
                else:
                    max_kcal_for_dish = min(200.0, remaining_before_exceed)  # Keep smaller for low deficit
                    min_kcal_for_dish = 30.0
            else:
                # Normal case: remaining_meal_kcal is positive
                # CRITICAL: Allow larger dishes when deficit is high to meet nutrition targets
                # Increase max_kcal when deficit is significant
                if protein_deficit_ratio > 0.30 or kcal_deficit_ratio > 0.40:
                    effective_max_kcal = min(remaining_meal_kcal * 1.3, remaining_before_exceed, 500.0)  # Allow larger when deficit is high
                else:
                    effective_max_kcal = min(remaining_meal_kcal * 1.1, remaining_before_exceed, 400.0)  # Normal case
                max_kcal_for_dish = max(100.0, effective_max_kcal)  # At least 100 kcal
                min_kcal_for_dish = max(50.0, remaining_meal_kcal * 0.2) if remaining_meal_kcal < 200.0 else 80.0
            
            logger.debug(
                f"ADD_SUPP_PRIORITY1_{meal_slot.upper()}_SEARCH_PARAMS: "
                f"remaining_meal_kcal={remaining_meal_kcal:.1f} | "
                f"min_protein_needed={min_protein_needed:.1f}g | "
                f"min_kcal={min_kcal_for_dish:.1f} | "
                f"max_kcal={max_kcal_for_dish:.1f} | "
                f"protein_deficit_ratio={protein_deficit_ratio*100:.1f}% | "
                f"kcal_deficit_ratio={kcal_deficit_ratio*100:.1f}%"
            )
            
            # Find a main dish with high protein (only 1 supplementary allowed overall)
            best_main = None
            best_score = 0.0
            for recipe in recipes:
                recipe_id = str(recipe.get("food_id", ""))
                if recipe_id in excluded_ids or recipe_id in recent_recipe_ids_set:
                    continue
                if recipe in excluded or recipe in current_dishes:
                    continue
                
                macros = recipe.get("macros_per_serving", {})
                if isinstance(macros, dict):
                    protein = macros.get("protein_g", 0)
                    kcal = macros.get("kcal", 0)
                    fat = macros.get("fat_g", 0)
                    carb = macros.get("carb_g", 0)
                    if (protein >= min_protein_needed and 
                        min_kcal_for_dish <= kcal <= max_kcal_for_dish and
                        _is_main_dish(recipe)):
                        # CRITICAL: Score based on protein and kcal, but penalize fat/carb if we have excess
                        # Base score: prioritize protein and kcal
                        score = protein * 3.0 + (kcal / 5.0)
                        
                        # CRITICAL: MUCH stronger penalty for fat when fat excess is very high (>40%)
                        if has_fat_excess:
                            if fat_excess_ratio > 0.40:  # High fat excess - very heavy penalty
                                if fat > 15.0:
                                    fat_penalty = min(fat / 1.8, 70.0)  # Very heavy penalty up to 70 points
                                    score -= fat_penalty
                                elif fat > 10.0:
                                    fat_penalty = min(fat / 2.2, 50.0)  # Heavy penalty up to 50 points
                                    score -= fat_penalty
                                elif fat > 8.0:
                                    fat_penalty = min(fat / 2.5, 35.0)  # Moderate-heavy penalty
                                    score -= fat_penalty
                            elif fat > 20.0:  # Heavy penalty for very high fat dishes
                                fat_penalty = min(fat / 3.0, 40.0)  # Increased penalty up to 40 points
                                score -= fat_penalty
                            elif fat > 15.0:  # Moderate penalty for high fat dishes
                                fat_penalty = min(fat / 4.0, 25.0)  # Increased penalty up to 25 points
                                score -= fat_penalty
                            elif fat > 10.0:  # Light penalty for medium fat dishes
                                fat_penalty = min(fat / 5.0, 15.0)
                                score -= fat_penalty
                        
                        # CRITICAL: Strongly penalize high carb if we already have carb excess
                        if has_carb_excess:
                            if carb > 50.0:  # Heavy penalty for very high carb dishes
                                carb_penalty = min(carb / 8.0, 30.0)  # Increased penalty up to 30 points
                                score -= carb_penalty
                            elif carb > 30.0:  # Moderate penalty for high carb dishes
                                carb_penalty = min(carb / 10.0, 20.0)  # Increased penalty up to 20 points
                                score -= carb_penalty
                        
                        # CRITICAL: Strong bonus for carb when carb is deficient (prioritize carb-rich dishes)
                        if has_carb_deficit and carb_deficit_ratio > 0.30:  # Carb deficit >30%
                            if carb > 30.0:  # Bonus for high-carb dishes when carb is needed
                                carb_bonus = min(carb / 3.0, 30.0)  # Bonus up to 30 points
                                score += carb_bonus
                            elif carb > 20.0:
                                carb_bonus = min(carb / 4.0, 20.0)  # Bonus up to 20 points
                                score += carb_bonus
                        
                        # CRITICAL: Strong bonus for low fat/carb when we have excess (prefer lean dishes)
                        if has_fat_excess and fat <= 8.0:  # Lowered threshold from 10.0 to 8.0
                            score += 15.0  # Increased bonus from 10.0 to 15.0 for very low-fat dishes when fat excess is high
                        elif has_fat_excess and fat <= 12.0:
                            score += 8.0  # Increased bonus from 5.0 to 8.0 for low-fat dishes
                        if has_carb_excess and carb <= 15.0:  # Lowered threshold from 20.0 to 15.0
                            score += 8.0  # Increased bonus from 3.0 to 8.0 for very low-carb dishes
                        elif has_carb_excess and carb <= 25.0:
                            score += 3.0  # Bonus for low-carb dishes
                        
                        if score > best_score:
                            best_main = recipe
                            best_score = score
            
            if best_main:
                additional_dishes.append(best_main)
                excluded_ids.add(str(best_main.get("food_id", "")))
                excluded.append(best_main)
                dishes_added += 1
                # Update current meal macros
                main_macros = _get_meal_macros(best_main)
                for k in current_meal_macros:
                    current_meal_macros[k] += main_macros.get(k, 0.0)
                protein_needed -= main_macros.get("protein_g", 0.0)
                kcal_needed -= main_macros.get("kcal", 0.0)
                # CRITICAL: Update remaining targets and recalculate excess
                remaining_targets["fat_g"] = remaining_targets.get("fat_g", 0.0) - main_macros.get("fat_g", 0.0)
                remaining_targets["carb_g"] = remaining_targets.get("carb_g", 0.0) - main_macros.get("carb_g", 0.0)
                fat_needed = remaining_targets.get("fat_g", 0.0)
                carb_needed = remaining_targets.get("carb_g", 0.0)
                has_fat_excess = fat_needed < 0
                has_carb_excess = carb_needed < 0
                # Recalculate excess ratios after adding dish
                recalculate_excess()
                logger.info(f"Added supplementary main dish to {meal_slot}: {best_main.get('dish_name', 'Unknown')} ({main_macros.get('protein_g', 0):.1f}g protein, {main_macros.get('kcal', 0):.1f} kcal)")
                logger.debug(
                    f"ADD_SUPP_PRIORITY1_{meal_slot.upper()}_SUCCESS: "
                    f"dish={best_main.get('dish_name', 'Unknown')} | "
                    f"protein={main_macros.get('protein_g', 0):.1f}g | "
                    f"kcal={main_macros.get('kcal', 0):.1f} | "
                    f"remaining_protein={protein_needed:.1f}g | "
                    f"remaining_kcal={kcal_needed:.1f}"
                )
            else:
                logger.debug(
                    f"ADD_SUPP_PRIORITY1_{meal_slot.upper()}_NO_MATCH: "
                    f"min_protein_needed={min_protein_needed:.1f}g | "
                    f"min_kcal={min_kcal_for_dish:.1f} | "
                    f"max_kcal={max_kcal_for_dish:.1f} | "
                    f"remaining_meal_kcal={remaining_meal_kcal:.1f}"
                )
    
    # Priority 2: Add vegetable dish if still need more nutrition and have kcal budget
    # CRITICAL: Check excess before adding - stop if we have severe excess
    should_add_veg = (protein_deficit_ratio > 0.05 or kcal_deficit_ratio > 0.05) and dishes_added < max_additional_dishes
    if should_stop_adding():
        should_add_veg = False
        logger.debug(
            f"ADD_SUPP_PRIORITY2_{meal_slot.upper()}_STOP_EXCESS: "
            f"fat_excess={fat_excess_ratio*100:.1f}% | "
            f"carb_excess={carb_excess_ratio*100:.1f}% | "
            f"kcal_excess={kcal_excess_ratio*100:.1f}%"
        )
    logger.debug(
        f"ADD_SUPP_PRIORITY2_{meal_slot.upper()}: "
        f"should_add_veg={should_add_veg} | "
        f"protein_deficit_ratio={protein_deficit_ratio*100:.1f}% | "
        f"kcal_deficit_ratio={kcal_deficit_ratio*100:.1f}% | "
        f"dishes_added={dishes_added}/{max_additional_dishes}"
    )
    
    if should_add_veg:
        remaining_meal_kcal = meal_max_kcal - current_meal_macros.get("kcal", 0.0)
        # Allow adding even with small budget if we still need nutrition
        if remaining_meal_kcal > 20.0 or (protein_deficit_ratio > 0.15 or kcal_deficit_ratio > 0.20):
            effective_max_kcal = max(remaining_meal_kcal * 1.2, 100.0) if remaining_meal_kcal < 150.0 else min(remaining_meal_kcal * 1.3, 300.0)
            max_kcal_for_dish = min(effective_max_kcal, 300.0)  # Increased back to 300.0 to allow more nutrition
            
            # Find a vegetable dish
            best_veg = None
            best_score = 0.0
            for recipe in recipes:
                recipe_id = str(recipe.get("food_id", ""))
                if recipe_id in excluded_ids or recipe_id in recent_recipe_ids_set:
                    continue
                if recipe in excluded or recipe in current_dishes:
                    continue
                
                macros = recipe.get("macros_per_serving", {})
                if isinstance(macros, dict):
                    protein = macros.get("protein_g", 0)
                    kcal = macros.get("kcal", 0)
                    if (30 <= kcal <= max_kcal_for_dish and
                        _is_vegetable_dish(recipe) and
                        not _is_main_dish(recipe)):
                        # Score: prioritize protein but also consider kcal
                        score = protein * 2.0 + (kcal / 10.0)
                        if score > best_score:
                            best_veg = recipe
                            best_score = score
            
            if best_veg:
                additional_dishes.append(best_veg)
                excluded_ids.add(str(best_veg.get("food_id", "")))
                excluded.append(best_veg)
                dishes_added += 1
                # Update current meal macros
                veg_macros = _get_meal_macros(best_veg)
                for k in current_meal_macros:
                    current_meal_macros[k] += veg_macros.get(k, 0.0)
                protein_needed -= veg_macros.get("protein_g", 0.0)
                kcal_needed -= veg_macros.get("kcal", 0.0)
                remaining_targets["fat_g"] = remaining_targets.get("fat_g", 0.0) - veg_macros.get("fat_g", 0.0)
                remaining_targets["carb_g"] = remaining_targets.get("carb_g", 0.0) - veg_macros.get("carb_g", 0.0)
                # Recalculate excess after adding dish
                recalculate_excess()
                logger.info(f"Added supplementary vegetable to {meal_slot}: {best_veg.get('dish_name', 'Unknown')}")
                logger.debug(
                    f"ADD_SUPP_PRIORITY2_{meal_slot.upper()}_SUCCESS: "
                    f"dish={best_veg.get('dish_name', 'Unknown')} | "
                    f"protein={veg_macros.get('protein_g', 0):.1f}g | "
                    f"kcal={veg_macros.get('kcal', 0):.1f} | "
                    f"remaining_protein={protein_needed:.1f}g | "
                    f"remaining_kcal={kcal_needed:.1f}"
                )
            else:
                logger.debug(f"ADD_SUPP_PRIORITY2_{meal_slot.upper()}_NO_MATCH: No suitable vegetable dish found")
    
    # Priority 3: Add soup if still need more nutrition and have kcal budget
    # CRITICAL: Check excess before adding - stop if we have severe excess
    should_add_soup = (protein_deficit_ratio > 0.03 or kcal_deficit_ratio > 0.03) and dishes_added < max_additional_dishes
    if should_stop_adding():
        should_add_soup = False
        logger.debug(
            f"ADD_SUPP_PRIORITY3_{meal_slot.upper()}_STOP_EXCESS: "
            f"fat_excess={fat_excess_ratio*100:.1f}% | "
            f"carb_excess={carb_excess_ratio*100:.1f}% | "
            f"kcal_excess={kcal_excess_ratio*100:.1f}%"
        )
    logger.debug(
        f"ADD_SUPP_PRIORITY3_{meal_slot.upper()}: "
        f"should_add_soup={should_add_soup} | "
        f"protein_deficit_ratio={protein_deficit_ratio*100:.1f}% | "
        f"kcal_deficit_ratio={kcal_deficit_ratio*100:.1f}% | "
        f"dishes_added={dishes_added}/{max_additional_dishes}"
    )
    
    if should_add_soup:
        remaining_meal_kcal = meal_max_kcal - current_meal_macros.get("kcal", 0.0)
        # Allow adding even with small budget if we still need nutrition
        if remaining_meal_kcal > 15.0 or (protein_deficit_ratio > 0.10 or kcal_deficit_ratio > 0.15):
            effective_max_kcal = max(remaining_meal_kcal * 1.2, 80.0) if remaining_meal_kcal < 120.0 else min(remaining_meal_kcal * 1.3, 250.0)
            max_kcal_for_dish = min(effective_max_kcal, 250.0)  # Increased back to 250.0
            
            # Find a soup
            best_soup = None
            best_score = 0.0
            for recipe in recipes:
                recipe_id = str(recipe.get("food_id", ""))
                if recipe_id in excluded_ids or recipe_id in recent_recipe_ids_set:
                    continue
                if recipe in excluded or recipe in current_dishes:
                    continue
                
                macros = recipe.get("macros_per_serving", {})
                if isinstance(macros, dict):
                    protein = macros.get("protein_g", 0)
                    kcal = macros.get("kcal", 0)
                    if (30 <= kcal <= max_kcal_for_dish and _is_soup(recipe)):
                        # Score: prioritize protein but also consider kcal
                        score = protein * 2.0 + (kcal / 10.0)
                        if score > best_score:
                            best_soup = recipe
                            best_score = score
            
            if best_soup:
                additional_dishes.append(best_soup)
                excluded_ids.add(str(best_soup.get("food_id", "")))
                excluded.append(best_soup)
                dishes_added += 1
                # Update current meal macros
                soup_macros = _get_meal_macros(best_soup)
                for k in current_meal_macros:
                    current_meal_macros[k] += soup_macros.get(k, 0.0)
                protein_needed -= soup_macros.get("protein_g", 0.0)
                kcal_needed -= soup_macros.get("kcal", 0.0)
                remaining_targets["fat_g"] = remaining_targets.get("fat_g", 0.0) - soup_macros.get("fat_g", 0.0)
                remaining_targets["carb_g"] = remaining_targets.get("carb_g", 0.0) - soup_macros.get("carb_g", 0.0)
                # Recalculate excess after adding dish
                recalculate_excess()
                logger.info(f"Added supplementary soup to {meal_slot}: {best_soup.get('dish_name', 'Unknown')}")
                logger.debug(
                    f"ADD_SUPP_PRIORITY3_{meal_slot.upper()}_SUCCESS: "
                    f"dish={best_soup.get('dish_name', 'Unknown')} | "
                    f"protein={soup_macros.get('protein_g', 0):.1f}g | "
                    f"kcal={soup_macros.get('kcal', 0):.1f} | "
                    f"remaining_protein={protein_needed:.1f}g | "
                    f"remaining_kcal={kcal_needed:.1f}"
                )
            else:
                logger.debug(f"ADD_SUPP_PRIORITY3_{meal_slot.upper()}_NO_MATCH: No suitable soup found")
    
    # Priority 4: Continue adding main dishes if still significantly deficient in protein or kcal
    # CRITICAL: STRICTLY control to prevent over-eating
    priority4_iteration = 0

    def should_continue_priority4():
        if dishes_added >= max_additional_dishes:
            return False
        if not (protein_deficit_ratio > 0.05 or kcal_deficit_ratio > 0.10):
            return False
        # CRITICAL: Stop if we have severe excess in ANY macro (fat, carb, or kcal)
        # Only continue if we REALLY need protein/kcal (very high threshold: 30%/35%)
        if should_stop_adding():
            logger.debug(
                f"ADD_SUPP_PRIORITY4_{meal_slot.upper()}_STOP_EXCESS: "
                f"fat_excess={fat_excess_ratio*100:.1f}% | "
                f"carb_excess={carb_excess_ratio*100:.1f}% | "
                f"kcal_excess={kcal_excess_ratio*100:.1f}% | "
                f"protein_deficit={protein_deficit_ratio*100:.1f}% | "
                f"kcal_deficit={kcal_deficit_ratio*100:.1f}%"
            )
            return False
        return True
    
    while should_continue_priority4():
        priority4_iteration += 1
        logger.debug(
            f"ADD_SUPP_PRIORITY4_{meal_slot.upper()}_ITER_{priority4_iteration}: "
            f"protein_deficit_ratio={protein_deficit_ratio*100:.1f}% | "
            f"kcal_deficit_ratio={kcal_deficit_ratio*100:.1f}% | "
            f"dishes_added={dishes_added}/{max_additional_dishes} | "
            f"remaining_protein={protein_needed:.1f}g | "
            f"remaining_kcal={kcal_needed:.1f}"
        )
        remaining_meal_kcal = meal_max_kcal - current_meal_macros.get("kcal", 0.0)
        
        logger.debug(
            f"ADD_SUPP_PRIORITY4_{meal_slot.upper()}_ITER_{priority4_iteration}_CHECK: "
            f"remaining_meal_kcal={remaining_meal_kcal:.1f} | "
            f"protein_deficit_ratio={protein_deficit_ratio*100:.1f}% | "
            f"kcal_deficit_ratio={kcal_deficit_ratio*100:.1f}% | "
            f"current_meal_kcal={current_meal_macros.get('kcal', 0):.1f} | "
            f"meal_max_kcal={meal_max_kcal:.1f}"
        )
        
        # CRITICAL: Only break if we have very little budget AND low deficit
        # If remaining_meal_kcal is negative but we still have high deficit, continue adding dishes
        if remaining_meal_kcal <= 20.0 and protein_deficit_ratio < 0.10 and kcal_deficit_ratio < 0.15:
            logger.debug(
                f"ADD_SUPP_PRIORITY4_{meal_slot.upper()}_ITER_{priority4_iteration}_STOP: "
                f"Low budget (remaining_meal_kcal={remaining_meal_kcal:.1f}) and low deficit "
                f"(protein={protein_deficit_ratio*100:.1f}%, kcal={kcal_deficit_ratio*100:.1f}%)"
            )
            break  # No more kcal budget and targets are close enough
        
        # CRITICAL: If remaining_meal_kcal is negative but we still have high deficit, allow adding dishes
        # Calculate requirements for next main dish
        min_protein_needed = min(protein_needed * 0.20, 10.0)  # Even lower threshold to allow more dishes
        
        # CRITICAL: STRICTLY control max_kcal_for_dish to prevent over-eating
        # Don't allow dishes that would cause meal to exceed meal_max_kcal by more than 20%
        max_meal_kcal_allowed = meal_max_kcal * 1.2  # Maximum 20% over meal_max_kcal
        remaining_before_exceed = max_meal_kcal_allowed - current_meal_macros.get("kcal", 0.0)
        
        if remaining_meal_kcal < 0:
            # If already exceeded meal_max_kcal, allow larger dishes when deficit is high
            if protein_deficit_ratio > 0.30 or kcal_deficit_ratio > 0.40:
                effective_max_kcal = min(320.0, remaining_before_exceed)  # tighter when already over
                min_kcal_for_dish = 30.0
            elif protein_deficit_ratio > 0.20 or kcal_deficit_ratio > 0.30:
                effective_max_kcal = min(260.0, remaining_before_exceed)
                min_kcal_for_dish = 30.0
            else:
                effective_max_kcal = min(200.0, remaining_before_exceed)
                min_kcal_for_dish = 30.0
        else:
            # Normal case: remaining_meal_kcal is positive
            # CRITICAL: Allow larger dishes when deficit is high to meet nutrition targets
            effective_remaining_kcal = remaining_meal_kcal
            if protein_deficit_ratio > 0.30 or kcal_deficit_ratio > 0.40:
                effective_max_kcal = min(effective_remaining_kcal * 1.3, remaining_before_exceed, 600.0)  # Allow larger when deficit is high
            else:
                effective_max_kcal = min(effective_remaining_kcal * 1.1, remaining_before_exceed, 500.0)  # Normal case
            min_kcal_for_dish = max(40.0, effective_remaining_kcal * 0.2) if effective_remaining_kcal < 200.0 else 80.0
        
        max_kcal_for_dish = max(100.0, effective_max_kcal)  # At least 100 kcal, cap at calculated limit
        
        logger.debug(
            f"ADD_SUPP_PRIORITY4_{meal_slot.upper()}_ITER_{priority4_iteration}_SEARCH: "
            f"min_protein_needed={min_protein_needed:.1f}g | "
            f"min_kcal={min_kcal_for_dish:.1f} | "
            f"max_kcal={max_kcal_for_dish:.1f} | "
            f"remaining_meal_kcal={remaining_meal_kcal:.1f} | "
            f"protein_deficit_ratio={protein_deficit_ratio*100:.1f}% | "
            f"kcal_deficit_ratio={kcal_deficit_ratio*100:.1f}%"
        )
        
        # Find another main dish
        best_main = None
        best_score = 0.0
        candidates_checked = 0
        candidates_filtered = 0
        
        for recipe in recipes:
            recipe_id = str(recipe.get("food_id", ""))
            if recipe_id in excluded_ids or recipe_id in recent_recipe_ids_set:
                continue
            if recipe in excluded or recipe in current_dishes:
                continue
            
            candidates_checked += 1
            macros = recipe.get("macros_per_serving", {})
            if isinstance(macros, dict):
                protein = macros.get("protein_g", 0)
                kcal = macros.get("kcal", 0)
                fat = macros.get("fat_g", 0)
                carb = macros.get("carb_g", 0)
                is_main = _is_main_dish(recipe)
                
                # Log why recipe is filtered out
                if not is_main:
                    continue
                if protein < min_protein_needed:
                    candidates_filtered += 1
                    continue
                if kcal < min_kcal_for_dish or kcal > max_kcal_for_dish:
                    candidates_filtered += 1
                    continue
                
                # Score: prioritize protein but also consider kcal
                score = protein * 3.0 + (kcal / 5.0)
                
                # CRITICAL: MUCH stronger penalty for fat when fat excess is very high (>40%)
                if has_fat_excess:
                    if fat_excess_ratio > 0.40:  # High fat excess - very heavy penalty
                        if fat > 15.0:
                            fat_penalty = min(fat / 1.8, 70.0)  # Very heavy penalty up to 70 points
                            score -= fat_penalty
                        elif fat > 10.0:
                            fat_penalty = min(fat / 2.2, 50.0)  # Heavy penalty up to 50 points
                            score -= fat_penalty
                        elif fat > 8.0:
                            fat_penalty = min(fat / 2.5, 35.0)  # Moderate-heavy penalty
                            score -= fat_penalty
                    elif fat > 20.0:  # Heavy penalty for very high fat dishes
                        fat_penalty = min(fat / 3.0, 40.0)  # Increased penalty up to 40 points
                        score -= fat_penalty
                    elif fat > 15.0:  # Moderate penalty for high fat dishes
                        fat_penalty = min(fat / 4.0, 25.0)  # Increased penalty up to 25 points
                        score -= fat_penalty
                    elif fat > 10.0:  # Light penalty for medium fat dishes
                        fat_penalty = min(fat / 5.0, 15.0)
                        score -= fat_penalty
                
                if has_carb_excess:
                    if carb > 50.0:  # Heavy penalty for very high carb dishes
                        carb_penalty = min(carb / 8.0, 30.0)  # Increased penalty up to 30 points
                        score -= carb_penalty
                    elif carb > 30.0:  # Moderate penalty for high carb dishes
                        carb_penalty = min(carb / 10.0, 20.0)  # Increased penalty up to 20 points
                        score -= carb_penalty
                
                # CRITICAL: Strong bonus for carb when carb is deficient (prioritize carb-rich dishes)
                if has_carb_deficit and carb_deficit_ratio > 0.30:  # Carb deficit >30%
                    if carb > 30.0:  # Bonus for high-carb dishes when carb is needed
                        carb_bonus = min(carb / 3.0, 30.0)  # Bonus up to 30 points
                        score += carb_bonus
                    elif carb > 20.0:
                        carb_bonus = min(carb / 4.0, 20.0)  # Bonus up to 20 points
                        score += carb_bonus
                
                # CRITICAL: Strong bonus for low fat/carb when we have excess (prefer lean dishes)
                if has_fat_excess and fat <= 8.0:  # Lowered threshold from 10.0 to 8.0
                    score += 15.0  # Increased bonus from 10.0 to 15.0 for very low-fat dishes when fat excess is high
                elif has_fat_excess and fat <= 12.0:
                    score += 8.0  # Increased bonus from 5.0 to 8.0 for low-fat dishes
                if has_carb_excess and carb <= 15.0:  # Lowered threshold from 20.0 to 15.0
                    score += 8.0  # Increased bonus from 3.0 to 8.0 for very low-carb dishes
                elif has_carb_excess and carb <= 25.0:
                    score += 3.0  # Bonus for low-carb dishes
                
                if score > best_score:
                    best_main = recipe
                    best_score = score
        
        logger.debug(
            f"ADD_SUPP_PRIORITY4_{meal_slot.upper()}_ITER_{priority4_iteration}_SEARCH_RESULT: "
            f"candidates_checked={candidates_checked} | "
            f"candidates_filtered={candidates_filtered} | "
            f"best_main={best_main.get('dish_name', 'None') if best_main else 'None'} | "
            f"best_score={best_score:.1f}"
        )
        
        if not best_main:
            logger.debug(
                f"ADD_SUPP_PRIORITY4_{meal_slot.upper()}_ITER_{priority4_iteration}_NO_MATCH: "
                f"No more suitable main dishes | "
                f"min_protein_needed={min_protein_needed:.1f}g | "
                f"min_kcal={min_kcal_for_dish:.1f} | "
                f"max_kcal={max_kcal_for_dish:.1f} | "
                f"remaining_meal_kcal={remaining_meal_kcal:.1f}"
            )
            break  # No more suitable main dishes
        
        additional_dishes.append(best_main)
        excluded_ids.add(str(best_main.get("food_id", "")))
        excluded.append(best_main)
        dishes_added += 1
        
        # Update current meal macros and recalculate deficit ratios
        main_macros = _get_meal_macros(best_main)
        for k in current_meal_macros:
            current_meal_macros[k] += main_macros.get(k, 0.0)
        protein_needed -= main_macros.get("protein_g", 0.0)
        kcal_needed -= main_macros.get("kcal", 0.0)
        # CRITICAL: Also update fat and carb remaining targets
        remaining_targets["fat_g"] = remaining_targets.get("fat_g", 0.0) - main_macros.get("fat_g", 0.0)
        remaining_targets["carb_g"] = remaining_targets.get("carb_g", 0.0) - main_macros.get("carb_g", 0.0)
        
        # Recalculate deficit ratios and excess ratios
        protein_deficit_ratio = protein_needed / daily_protein if daily_protein > 0 else 0.0
        kcal_deficit_ratio = kcal_needed / daily_kcal if daily_kcal > 0 else 0.0
        
        # CRITICAL: Recalculate carb deficit ratio
        carb_needed = remaining_targets.get("carb_g", 0.0)
        carb_deficit_ratio = carb_needed / daily_carb if daily_carb > 0 and carb_needed > 0 else 0.0
        has_carb_deficit = carb_needed > 0
        
        # CRITICAL: Recalculate excess using recalculate_excess() function
        recalculate_excess()
        
        # Note: should_continue_priority4() function will be re-evaluated in next iteration
        
        logger.info(f"Added additional main dish to {meal_slot}: {best_main.get('dish_name', 'Unknown')} ({main_macros.get('protein_g', 0):.1f}g protein, {main_macros.get('kcal', 0):.1f} kcal)")
        logger.debug(
            f"ADD_SUPP_PRIORITY4_{meal_slot.upper()}_ITER_{priority4_iteration}_SUCCESS: "
            f"dish={best_main.get('dish_name', 'Unknown')} | "
            f"protein={main_macros.get('protein_g', 0):.1f}g | "
            f"kcal={main_macros.get('kcal', 0):.1f} | "
            f"remaining_protein={protein_needed:.1f}g ({protein_deficit_ratio*100:.1f}%) | "
            f"remaining_kcal={kcal_needed:.1f} ({kcal_deficit_ratio*100:.1f}%)"
        )
    
    return additional_dishes


def select_accompaniments(
    meal_slot: str,
    is_combined: bool,
    is_noodle: bool,
    recipes: List[Dict[str, Any]],
    excluded: List[Dict[str, Any]],
    recent_recipe_ids_set: set[str],
    selection_strategy: str,
    targets: Optional[Dict[str, float]],
    llm_draft: Any = None,
    try_select_from_llm_suggestions: Optional[callable] = None,
) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]], Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """
    Select meal accompaniments (main, soup, vegetable, fruit).
    
    Args:
        llm_draft: LLM draft with suggestions
        meal_slot: Meal slot (lunch/dinner)
        is_combined: Whether this is a combined dish
        is_noodle: Whether this is a noodle dish
        recipes: Available recipes
        excluded: Recipes to exclude
        recent_recipe_ids_set: Recently used recipe IDs
        selection_strategy: Selection strategy
        targets: Target macros
        try_select_from_llm_suggestions: Function to try selecting from LLM suggestions
    
    Returns:
        Tuple of (main, soup, vegetable, fruit)
    """
    main = None
    soup = None
    vegetable = None
    fruit = None
    
    if is_combined or is_noodle:
        # Combined/noodle: only fruit
        fruit = None
        if try_select_from_llm_suggestions and llm_draft:
            fruit = try_select_from_llm_suggestions(
                llm_draft, meal_slot, "fruit",
                recipes, excluded, recent_recipe_ids_set,
                min_kcal=30.0,
                max_kcal=150.0
            )
        if not fruit:
            fruit = select_meal_by_strategy(
                recipes, "balanced",
                exclude=excluded,
                used_recipe_ids=recent_recipe_ids_set,
                preferred_meal_type=meal_slot,
                dish_category="fruit",
                target_macros=targets,
                require_macros=True,
                min_kcal=30.0,
                max_kcal=150.0,
            )
        # CRITICAL: Final validation - ensure fruit is actually a fruit and within kcal limit
        if fruit:
            fruit_macros = _get_meal_macros(fruit)
            fruit_kcal = fruit_macros.get("kcal", 0)
            if fruit_kcal > 150.0:
                logger.warning(f"Fruit '{fruit.get('dish_name', 'Unknown')}' kcal ({fruit_kcal:.1f}) exceeds limit (150.0), rejecting...")
                fruit = None
            elif not _is_fruit(fruit):
                logger.warning(f"Selected 'fruit' is not actually a fruit: {fruit.get('dish_name', 'Unknown')}")
                fruit = None
    else:
        # Plain rice: main + soup + vegetable/fruit
        # Select main dish - prioritize protein if remaining protein is high
        remaining_targets = targets.get("_remaining_targets") if targets else None
        
        # CRITICAL: If no remaining_targets provided, assume we need full protein (starting fresh)
        if not remaining_targets and targets:
            remaining_targets = {
                "kcal": targets.get("tdee_kcal", 2000.0),
                "protein_g": targets.get("protein_g", 150.0),
                "fat_g": targets.get("fat_g", 65.0),
                "carb_g": targets.get("carb_g", 200.0),
            }
        
        if remaining_targets:
            protein_remaining = remaining_targets.get("protein_g", 0.0)
            daily_protein = targets.get("protein_g", 150.0) if targets else 150.0
            protein_ratio = protein_remaining / daily_protein if daily_protein > 0 else 1.0
            
            # Calculate dynamic max_kcal and min_protein based on remaining protein needs
            daily_protein = targets.get("protein_g", 150.0) if targets else 150.0
            if daily_protein > 180:
                base_min_protein = 35.0
            elif daily_protein > 150:
                base_min_protein = 30.0
            else:
                base_min_protein = 25.0
            
            if protein_ratio > 0.5:
                max_main_kcal = 650.0
                min_main_protein = max(base_min_protein, 40.0)
            elif protein_ratio > 0.4:
                max_main_kcal = 600.0
                min_main_protein = max(base_min_protein, 35.0)
            elif protein_ratio > 0.2:
                max_main_kcal = 500.0
                min_main_protein = max(base_min_protein, 30.0)
            else:
                max_main_kcal = 450.0
                min_main_protein = base_min_protein
            
            # If still need >40% of daily protein, prioritize highest_protein strategy
            if protein_ratio > 0.4:
                main = None
                if try_select_from_llm_suggestions and llm_draft:
                    main = try_select_from_llm_suggestions(
                        llm_draft, meal_slot, "main",
                        recipes, excluded, recent_recipe_ids_set,
                        min_kcal=50.0, max_kcal=max_main_kcal
                    )
                if not main:
                    main = select_meal_by_strategy(
                        recipes, "highest_protein",
                        exclude=excluded,
                        used_recipe_ids=recent_recipe_ids_set,
                        preferred_meal_type=meal_slot,
                        dish_category="main",
                        target_macros=targets,
                        require_macros=True,
                        min_kcal=50.0,
                        max_kcal=max_main_kcal,
                        min_protein=min_main_protein,
                    )
                if not main:
                    # Fallback: try without min_protein requirement but still prioritize protein
                    main = select_meal_by_strategy(
                        recipes, "highest_protein",
                        exclude=excluded,
                        used_recipe_ids=recent_recipe_ids_set,
                        preferred_meal_type=meal_slot,
                        target_macros=targets,
                        require_macros=True,
                        min_kcal=50.0,
                        max_kcal=max_main_kcal,
                    )
            else:
                # Use macro_fit strategy when protein needs are more balanced
                main = None
                if try_select_from_llm_suggestions and llm_draft:
                    main = try_select_from_llm_suggestions(
                        llm_draft, meal_slot, "main",
                        recipes, excluded, recent_recipe_ids_set,
                        min_kcal=50.0, max_kcal=max_main_kcal
                    )
                if not main:
                    main = select_meal_by_strategy(
                        recipes, selection_strategy if targets else "highest_protein",
                        exclude=excluded,
                        used_recipe_ids=recent_recipe_ids_set,
                        preferred_meal_type=meal_slot,
                        dish_category="main",
                        target_macros=targets,
                        require_macros=True,
                        min_kcal=50.0,
                        max_kcal=max_main_kcal,
                        min_protein=min_main_protein,
                    )
                if not main:
                    # Fallback: try without min_protein requirement
                    main = select_meal_by_strategy(
                        recipes, "highest_protein",
                        exclude=excluded,
                        used_recipe_ids=recent_recipe_ids_set,
                        preferred_meal_type=meal_slot,
                        target_macros=targets,
                        require_macros=True,
                        min_kcal=50.0,
                        max_kcal=max_main_kcal,
                    )
        else:
            # No remaining targets and no targets provided - use aggressive protein strategy
            daily_protein = targets.get("protein_g", 150.0) if targets else 150.0
            if daily_protein > 180:
                min_main_protein = 35.0
            elif daily_protein > 150:
                min_main_protein = 30.0
            else:
                min_main_protein = 25.0
            max_main_kcal = 600.0
            
            main = None
            if try_select_from_llm_suggestions and llm_draft:
                main = try_select_from_llm_suggestions(
                    llm_draft, meal_slot, "main",
                    recipes, excluded, recent_recipe_ids_set,
                    min_kcal=50.0, max_kcal=max_main_kcal
                )
            if not main:
                main = select_meal_by_strategy(
                    recipes, "highest_protein",
                    exclude=excluded,
                    used_recipe_ids=recent_recipe_ids_set,
                    preferred_meal_type=meal_slot,
                    dish_category="main",
                    target_macros=targets,
                    require_macros=True,
                    min_kcal=50.0,
                    max_kcal=max_main_kcal,
                    min_protein=min_main_protein,
                )
            if not main:
                # Fallback: try with lower min_protein but still prioritize protein
                main = select_meal_by_strategy(
                    recipes, "highest_protein",
                    exclude=excluded,
                    used_recipe_ids=recent_recipe_ids_set,
                    preferred_meal_type=meal_slot,
                    dish_category="main",
                    target_macros=targets,
                    require_macros=True,
                    min_kcal=50.0,
                    max_kcal=max_main_kcal,
                    min_protein=15.0,
                )
        
        if main:
            # CRITICAL: Validate main is actually a main dish
            if not _is_main_dish(main):
                logger.warning(f"Selected main '{main.get('dish_name', 'Unknown')}' is not a main dish, rejecting...")
                main = None
            else:
                excluded.append(main)
            
            # Select soup only if main is valid
            if main:
                soup = select_meal_by_strategy(
                    recipes, "balanced",
                    exclude=excluded,
                    used_recipe_ids=recent_recipe_ids_set,
                    preferred_meal_type=meal_slot,
                    target_macros=targets,
                    require_macros=True,
                    min_kcal=30.0,
                    max_kcal=200.0,
                )
                if soup and not _is_soup(soup):
                    logger.warning(f"Selected soup '{soup.get('dish_name', 'Unknown')}' is not a soup, rejecting...")
                    soup = None
                if soup:
                    soup_macros = _get_meal_macros(soup)
                    soup_kcal = soup_macros.get("kcal", 0)
                    if soup_kcal > 200.0:
                        logger.warning(f"Soup '{soup.get('dish_name', 'Unknown')}' kcal ({soup_kcal:.1f}) exceeds limit (200.0), rejecting...")
                        soup = None
                if soup:
                    excluded.append(soup)
            
            # Select vegetable (preferred) or fruit
            vegetable = None
            if try_select_from_llm_suggestions and llm_draft:
                vegetable = try_select_from_llm_suggestions(
                    llm_draft, meal_slot, "vegetable",
                    recipes, excluded, recent_recipe_ids_set,
                    min_kcal=30.0
                )
            if vegetable and not _is_vegetable_dish(vegetable):
                logger.warning(f"LLM suggested vegetable '{vegetable.get('dish_name', 'Unknown')}' is not a vegetable dish, rejecting...")
                vegetable = None
            if not vegetable:
                vegetable = select_meal_by_strategy(
                    recipes, "balanced",
                    exclude=excluded,
                    used_recipe_ids=recent_recipe_ids_set,
                    preferred_meal_type=meal_slot,
                    dish_category="vegetable",
                    target_macros=targets,
                    require_macros=True,
                    min_kcal=30.0,
                    max_kcal=150.0,
                )
            if vegetable:
                veg_macros = _get_meal_macros(vegetable)
                veg_kcal = veg_macros.get("kcal", 0)
                if veg_kcal > 150.0:
                    logger.warning(f"Vegetable '{vegetable.get('dish_name', 'Unknown')}' kcal ({veg_kcal:.1f}) exceeds limit (150.0), rejecting...")
                    vegetable = None
                elif not _is_vegetable_dish(vegetable):
                    logger.warning(f"Selected vegetable '{vegetable.get('dish_name', 'Unknown')}' is not a vegetable dish, rejecting...")
                    vegetable = None
                elif _is_main_dish(vegetable):
                    logger.warning(f"Selected vegetable '{vegetable.get('dish_name', 'Unknown')}' is actually a main dish, rejecting...")
                    vegetable = None
            
            if vegetable:
                excluded.append(vegetable)
            else:
                # Fallback to fruit if no vegetable
                fruit = None
                if try_select_from_llm_suggestions and llm_draft:
                    fruit = try_select_from_llm_suggestions(
                        llm_draft, meal_slot, "fruit",
                        recipes, excluded, recent_recipe_ids_set,
                        min_kcal=30.0
                    )
                if not fruit:
                    fruit = select_meal_by_strategy(
                        recipes, "balanced",
                        exclude=excluded,
                        used_recipe_ids=recent_recipe_ids_set,
                        preferred_meal_type=meal_slot,
                        dish_category="fruit",
                        target_macros=targets,
                        require_macros=True,
                        min_kcal=30.0,
                        max_kcal=150.0,
                    )
                if fruit:
                    fruit_macros = _get_meal_macros(fruit)
                    fruit_kcal = fruit_macros.get("kcal", 0)
                    if fruit_kcal > 150.0:
                        logger.warning(f"Fruit '{fruit.get('dish_name', 'Unknown')}' kcal ({fruit_kcal:.1f}) exceeds limit (150.0), rejecting...")
                        fruit = None
                    elif not _is_fruit(fruit):
                        logger.warning(f"Selected fruit '{fruit.get('dish_name', 'Unknown')}' is not a fruit, rejecting...")
                        fruit = None
                if fruit:
                    excluded.append(fruit)
    
    return main, soup, vegetable, fruit

