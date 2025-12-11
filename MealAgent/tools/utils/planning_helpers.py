"""
Helper functions for meal planning tools.
Extracted from legacy tools to be shared across E2E tools.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
from uuid import uuid4

from MealAgent.tools.utils.weaviate_filters import build_filters_from_where

# RDA (Recommended Daily Allowance) values for common micronutrients
# Source: USDA Dietary Guidelines
DEFAULT_RDAs = {
    "calcium_mg": 1000.0,
    "iron_mg": 18.0,
    "potassium_mg": 2600.0,
    "vitamin_c_mg": 90.0,
    "vitamin_a_rae_ug": 900.0,
    "vitamin_d_ug": 15.0,
    "vitamin_e_mg": 15.0,
    "vitamin_b6_mg": 1.3,
    "vitamin_b12_ug": 2.4,
    "thiamin_b1_mg": 1.2,
    "riboflavin_b2_mg": 1.3,
    "niacin_b3_mg": 16.0,
    "magnesium_mg": 400.0,
    "zinc_mg": 11.0,
}


def _get_meal_macros(recipe: Dict[str, Any]) -> Dict[str, float]:
    """Extract macros from recipe, defaulting to 0 if missing."""
    macros = recipe.get("macros_per_serving", {})
    if not isinstance(macros, dict):
        return {"kcal": 0.0, "protein_g": 0.0, "fat_g": 0.0, "carb_g": 0.0}
    return {
        "kcal": float(macros.get("kcal", 0.0)),
        "protein_g": float(macros.get("protein_g", 0.0)),
        "fat_g": float(macros.get("fat_g", 0.0)),
        "carb_g": float(macros.get("carb_g", 0.0)),
    }


def _validate_macro_targets(
    total_macros: Dict[str, float],
    targets: Dict[str, float],
    tolerance_percent: float = 0.15,
) -> Dict[str, Any]:
    """Validate that plan macros are within tolerance of targets."""
    violations = []
    warnings = []

    for key in ["kcal", "protein_g", "fat_g", "carb_g"]:
        target_val = targets.get(key, 0.0)
        actual_val = total_macros.get(key, 0.0)

        if target_val <= 0:
            continue

        deviation = abs(actual_val - target_val) / target_val
        if deviation > tolerance_percent:
            violations.append({
                "macro": key,
                "target": target_val,
                "actual": actual_val,
                "deviation_percent": deviation * 100,
            })
        elif deviation > tolerance_percent * 0.7:  # Warning threshold
            warnings.append({
                "macro": key,
                "target": target_val,
                "actual": actual_val,
                "deviation_percent": deviation * 100,
            })

    return {
        "valid": len(violations) == 0,
        "violations": violations,
        "warnings": warnings,
    }


def _validate_constraints(
    plan: Dict[str, Any],
    diet_types: List[str] | None = None,
    exclude_allergens: List[str] | None = None,
) -> Dict[str, Any]:
    """Validate that plan meals respect diet/allergen constraints."""
    violations = []

    for meal_key, meal_data in plan.get("meals", {}).items():
        recipe = meal_data.get("recipe", {})
        recipe_id = recipe.get("food_id", "")

        # Check diet type (if Recipe has diet_type field)
        if diet_types:
            recipe_diet = recipe.get("diet_type")
            if recipe_diet:
                recipe_diets = [recipe_diet] if isinstance(recipe_diet, str) else recipe_diet
                if not any(dt in recipe_diets for dt in diet_types):
                    violations.append({
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
                        "meal": meal_key,
                        "recipe_id": recipe_id,
                        "type": "allergen_violation",
                        "forbidden_allergens": list(overlap),
                    })

    return {
        "valid": len(violations) == 0,
        "violations": violations,
    }


def _calculate_meal_targets(
    targets: Dict[str, float],
    meal_type: str,
    breakfast_ratio: float = 0.25,
    lunch_ratio: float = 0.40,
    dinner_ratio: float = 0.35,
) -> Dict[str, float]:
    """
    Calculate macro targets for a specific meal (breakfast, lunch, or dinner).
    
    Args:
        targets: Daily macro targets (tdee_kcal, protein_g, fat_g, carb_g)
        meal_type: "breakfast", "lunch", or "dinner"
        breakfast_ratio: Ratio of daily calories for breakfast (default 0.25)
        lunch_ratio: Ratio of daily calories for lunch (default 0.40)
        dinner_ratio: Ratio of daily calories for dinner (default 0.35)
    
    Returns:
        Dict with meal-specific targets (kcal, protein_g, fat_g, carb_g)
    """
    ratios = {
        "breakfast": breakfast_ratio,
        "lunch": lunch_ratio,
        "dinner": dinner_ratio,
    }
    ratio = ratios.get(meal_type, 0.33)
    
    return {
        "kcal": targets.get("tdee_kcal", 2000.0) * ratio,
        "protein_g": targets.get("protein_g", 150.0) * ratio,
        "fat_g": targets.get("fat_g", 65.0) * ratio,
        "carb_g": targets.get("carb_g", 200.0) * ratio,
    }


def _scale_main_by_protein(
    recipe: Dict[str, Any],
    target_protein: float,
    *,
    min_scale: float = 0.5,
    max_scale: float = 1.2,
) -> float:
    """
    Calculate serving scale for main dish based on protein target.
    
    Args:
        recipe: Recipe dict with macros_per_serving
        target_protein: Target protein in grams
        max_scale: Maximum scaling factor (default 1.2)
    
    Returns:
        Serving scale factor (clamped between 0.5 and max_scale)
    """
    macros = _get_meal_macros(recipe)
    current_protein = macros.get("protein_g", 0.0)
    
    if current_protein <= 0:
        return 1.0
    
    scale = target_protein / current_protein
    return max(min_scale, min(max_scale, scale))


def _scale_carb_by_kcal(
    recipe: Dict[str, Any],
    target_kcal: float,
    *,
    min_scale: float = 0.5,
    max_scale: float = 1.5,
) -> float:
    """
    Calculate serving scale for carb dish based on kcal target.
    
    Args:
        recipe: Recipe dict with macros_per_serving
        target_kcal: Target kcal
        max_scale: Maximum scaling factor (default 1.5)
    
    Returns:
        Serving scale factor (clamped between 0.5 and max_scale)
    """
    macros = _get_meal_macros(recipe)
    current_kcal = macros.get("kcal", 0.0)
    
    if current_kcal <= 0:
        return 1.0
    
    scale = target_kcal / current_kcal
    return max(min_scale, min(max_scale, scale))


def _calculate_macro_deviation(
    actual: Dict[str, float],
    target: Dict[str, float],
) -> Dict[str, float]:
    """
    Calculate deviation percentage for each macro.
    
    Args:
        actual: Actual macro values
        target: Target macro values
    
    Returns:
        Dict with deviation percentages for each macro
    """
    deviations = {}
    for key in ["kcal", "protein_g", "fat_g", "carb_g"]:
        target_val = target.get(key, 0.0)
        actual_val = actual.get(key, 0.0)
        
        if target_val <= 0:
            deviations[key] = 0.0
        else:
            deviations[key] = abs(actual_val - target_val) / target_val
    
    return deviations


def _calculate_total_deviation_score(
    actual: Dict[str, float],
    target: Dict[str, float],
) -> float:
    """
    Calculate total deviation score (average of all macro deviations).
    
    Args:
        actual: Actual macro values
        target: Target macro values
    
    Returns:
        Average deviation score (0.0 to 1.0+)
    """
    deviations = _calculate_macro_deviation(actual, target)
    if not deviations:
        return 0.0
    
    return sum(deviations.values()) / len(deviations)


def _try_swap_alternatives(
    current_recipe: Dict[str, Any],
    alternatives: List[Dict[str, Any]],
    target_macros: Dict[str, float],
    dish_type: str,  # "main" or "carb"
    current_servings: float = 1.0,
    max_alternatives: int = 5,
    max_kcal: float | None = None,
) -> tuple[Dict[str, Any] | None, float, float]:
    """
    Try swapping current recipe with alternatives to improve macro fit.
    
    Args:
        current_recipe: Current recipe to potentially swap
        alternatives: List of alternative recipes
        target_macros: Target macros for the meal
        dish_type: "main" (protein-based) or "carb" (kcal-based)
        current_servings: Current serving size (default 1.0)
        max_alternatives: Maximum number of alternatives to try (default 5)
        max_kcal: Maximum kcal for filtering alternatives (optional)
    
    Returns:
        Tuple of (best_recipe, best_servings, best_score) or (None, 1.0, float('inf'))
    """
    if not alternatives:
        return None, 1.0, float('inf')
    
    # Filter alternatives by max_kcal if provided
    if max_kcal is not None:
        alternatives = [
            r for r in alternatives
            if _get_meal_macros(r).get("kcal", 0.0) <= max_kcal
        ]
    
    if not alternatives:
        return None, 1.0, float('inf')
    
    # Limit number of alternatives to try
    alternatives = alternatives[:max_alternatives]
    
    best_recipe = None
    best_servings = 1.0
    best_score = float('inf')
    
    # Calculate current score
    current_macros = _get_meal_macros(current_recipe)
    current_meal_macros = {k: current_macros[k] * current_servings for k in current_macros}
    current_score = _calculate_total_deviation_score(current_meal_macros, target_macros)
    
    for alt_recipe in alternatives:
        alt_macros = _get_meal_macros(alt_recipe)
        
        # Calculate optimal serving size
        if dish_type == "main":
            # Scale by protein for main dishes
            target_protein = target_macros.get("protein_g", 0.0)
            alt_servings = _scale_main_by_protein(alt_recipe, target_protein, max_scale=1.2)
        else:  # carb
            # Scale by kcal for carb dishes
            target_kcal = target_macros.get("kcal", 0.0)
            alt_servings = _scale_carb_by_kcal(alt_recipe, target_kcal, max_scale=1.5)
        
        # Always use 1.0 serving (user requirement)
        alt_servings = 1.0
        
        # Calculate score for this alternative
        alt_meal_macros = {k: alt_macros[k] * alt_servings for k in alt_macros}
        alt_score = _calculate_total_deviation_score(alt_meal_macros, target_macros)
        
        if alt_score < best_score and alt_score < current_score:
            best_recipe = alt_recipe
            best_servings = alt_servings
            best_score = alt_score
    
    return best_recipe, best_servings, best_score


def _generate_plan_id(user_id: str | None = None) -> str:
    """
    Generate a unique plan ID.
    
    Args:
        user_id: Optional user ID to prefix the plan ID
        
    Returns:
        Unique plan ID string (e.g., "user123_plan_a1b2c3d4e5f6")
    """
    prefix = f"{user_id}_" if user_id else ""
    return f"{prefix}plan_{uuid4().hex[:12]}"


def _safe_float(value, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def ensure_rfc3339_datetime(value: datetime | str | None, *, date_only: bool = False) -> str:
    """
    Normalize any datetime/date input into an RFC3339 string (UTC, 'Z' suffixed).
    """
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str) and value:
        normalized = value.replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(normalized)
        except ValueError:
            if date_only and len(value) == 10:
                dt = datetime.fromisoformat(f"{value}T00:00:00")
            else:
                raise
    else:
        dt = datetime.now(timezone.utc)

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)

    if date_only:
        dt = dt.replace(hour=0, minute=0, second=0, microsecond=0)

    return dt.isoformat(timespec="seconds").replace("+00:00", "Z")


def _build_plan_items(plan: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Build MealPlanItem records from a plan dictionary.
    
    Handles both daily and weekly plans, including accompaniments for Vietnamese meals.
    
    Args:
        plan: Plan dictionary with meals and optional snacks
        
    Returns:
        List of MealPlanItem dictionaries ready for Weaviate insertion
    """
    items: List[Dict[str, Any]] = []
    plan_type = plan.get("plan_type", "day")

    def _append_meal_entries(meals: Dict[str, Any], day_index: int):
        for meal_key, meal_data in meals.items():
            # Main recipe
            recipe = meal_data.get("recipe", {})
            if not isinstance(recipe, dict):
                continue
            recipe_id = recipe.get("food_id") or recipe.get("recipe_id")
            if not recipe_id:
                continue
            servings = _safe_float(meal_data.get("servings", 1.0), default=1.0)
            macros = _get_meal_macros(recipe)
            
            # Calculate total macros including accompaniments
            total_macros = {
                k: macros.get(k, 0.0) * servings for k in ["kcal", "protein_g", "fat_g", "carb_g"]
            }
            
            # Add accompaniments macros (for Vietnamese meals)
            accompaniments = meal_data.get("accompaniments", [])
            for acc in accompaniments:
                acc_recipe = acc.get("recipe", {})
                acc_servings = _safe_float(acc.get("servings", 1.0), default=1.0)
                if acc_recipe and isinstance(acc_recipe, dict):
                    acc_macros = _get_meal_macros(acc_recipe)
                    for k in total_macros:
                        total_macros[k] += acc_macros.get(k, 0.0) * acc_servings
            
            items.append(
                {
                    "day_index": day_index,
                    "meal_type": meal_data.get("meal_type", meal_key),
                    "recipe_id": str(recipe_id),
                    # Persist dish_name so variety filters can block by name in future plans
                    "dish_name": str(recipe.get("dish_name", "")).strip(),
                    "servings": servings,
                    # Store as map to align with MealPlanItem schema
                    "actual_macros": total_macros if isinstance(total_macros, dict) else {},
                }
            )

    if plan_type == "day":
        _append_meal_entries(plan.get("meals", {}), day_index=0)
        for snack in plan.get("snacks", []):
            _append_meal_entries({snack.get("meal_type", "snack"): snack}, day_index=0)
    else:
        for day_data in plan.get("days", {}).values():
            if not isinstance(day_data, dict):
                continue
            day_index = int(day_data.get("day_index", 0))
            _append_meal_entries(day_data.get("meals", {}), day_index=day_index)
            for snack in day_data.get("snacks", []):
                _append_meal_entries({snack.get("meal_type", "snack"): snack}, day_index=day_index)

    return items


async def _calculate_plan_micronutrients(
    plan: Dict[str, Any],
    client_manager,
    gender: str | None = None,
) -> Dict[str, Any]:
    """
    Calculate total micronutrients from a plan by aggregating from all recipes' ingredient_fdc_map.
    
    Args:
        plan: Plan dictionary with meals and optional snacks
        client_manager: ClientManager for Weaviate access
        gender: Optional gender for RDA adjustments
        
    Returns:
        Dictionary with total_micros, average_daily_micros, rdas, and deficits
    """
    # Get RDA values (adjust for gender if provided)
    rdas = DEFAULT_RDAs.copy()
    if gender and gender.lower() == "female":
        rdas["iron_mg"] = 18.0
        rdas["vitamin_c_mg"] = 75.0
        rdas["vitamin_a_rae_ug"] = 700.0
    elif gender and gender.lower() == "male":
        rdas["iron_mg"] = 8.0
        rdas["vitamin_c_mg"] = 90.0
        rdas["vitamin_a_rae_ug"] = 900.0
    
    client = client_manager.get_client()
    try:
        fdc_collection = client.collections.get("FdcFood")
    except Exception:
        logging.warning("FdcFood collection not available for micronutrient calculation")
        return {
            "total_micros": {},
            "average_daily_micros": {},
            "rdas": rdas,
            "deficits": {},
            "has_deficits": False,
        }
    
    total_micros: Dict[str, float] = {}
    fdc_data_map: Dict[int, List[Dict[str, Any]]] = {}
    
    # Collect all fdc_ids and their quantities
    def _collect_from_meal(meal_data: Dict[str, Any]):
        recipe = meal_data.get("recipe", {})
        servings = _safe_float(meal_data.get("servings", 1.0), default=1.0)
        ingredient_map = recipe.get("ingredient_fdc_map", [])
        
        for ing_entry in ingredient_map:
            if isinstance(ing_entry, dict):
                fdc_id = ing_entry.get("fdc_id")
                quantity_g = _safe_float(ing_entry.get("quantity_g", 0.0), default=0.0)
                
                if fdc_id:
                    fdc_id_int = int(fdc_id)
                    if fdc_id_int not in fdc_data_map:
                        fdc_data_map[fdc_id_int] = []
                    fdc_data_map[fdc_id_int].append({
                        "quantity_g": quantity_g,
                        "servings": servings,
                    })
        
        # Also check accompaniments
        accompaniments = meal_data.get("accompaniments", [])
        for acc in accompaniments:
            acc_recipe = acc.get("recipe", {})
            acc_servings = _safe_float(acc.get("servings", 1.0), default=1.0)
            if acc_recipe:
                acc_ingredient_map = acc_recipe.get("ingredient_fdc_map", [])
                for ing_entry in acc_ingredient_map:
                    if isinstance(ing_entry, dict):
                        fdc_id = ing_entry.get("fdc_id")
                        quantity_g = _safe_float(ing_entry.get("quantity_g", 0.0), default=0.0)
                        
                        if fdc_id:
                            fdc_id_int = int(fdc_id)
                            if fdc_id_int not in fdc_data_map:
                                fdc_data_map[fdc_id_int] = []
                            fdc_data_map[fdc_id_int].append({
                                "quantity_g": quantity_g,
                                "servings": acc_servings,
                            })
    
    plan_type = plan.get("plan_type", "day")
    if plan_type == "day":
        for meal_data in plan.get("meals", {}).values():
            _collect_from_meal(meal_data)
        for snack in plan.get("snacks", []):
            _collect_from_meal(snack)
    elif plan_type == "week":
        for day_data in plan.get("days", {}).values():
            for meal_data in day_data.get("meals", {}).values():
                _collect_from_meal(meal_data)
            for snack in day_data.get("snacks", []):
                _collect_from_meal(snack)
    
    # Batch fetch FDC foods
    if fdc_data_map:
        unique_fdc_ids = list(fdc_data_map.keys())
        try:
            batch_filter = build_filters_from_where(
                {"path": ["fdc_id"], "operator": "ContainsAny", "valueIntArray": unique_fdc_ids}
            )
            batch_results = fdc_collection.query.fetch_objects(filters=batch_filter, limit=len(unique_fdc_ids))
            
            fdc_foods_map: Dict[int, Dict[str, Any]] = {}
            for obj in batch_results.objects:
                fdc_id = obj.properties.get("fdc_id")
                if fdc_id:
                    fdc_foods_map[int(fdc_id)] = obj.properties
            
            # Micro fields mapping
            micro_fields = [
                ("calcium_mg_100g", "calcium_mg"),
                ("iron_mg_100g", "iron_mg"),
                ("potassium_mg_100g", "potassium_mg"),
                ("vitamin_c_mg_100g", "vitamin_c_mg"),
                ("vitamin_a_rae_ug_100g", "vitamin_a_rae_ug"),
                ("vitamin_d_ug_100g", "vitamin_d_ug"),
                ("vitamin_e_mg_100g", "vitamin_e_mg"),
                ("vitamin_b6_mg_100g", "vitamin_b6_mg"),
                ("vitamin_b12_ug_100g", "vitamin_b12_ug"),
                ("thiamin_b1_mg_100g", "thiamin_b1_mg"),
                ("riboflavin_b2_mg_100g", "riboflavin_b2_mg"),
                ("niacin_b3_mg_100g", "niacin_b3_mg"),
                ("magnesium_mg_100g", "magnesium_mg"),
                ("zinc_mg_100g", "zinc_mg"),
            ]
            
            for fdc_id, data_list in fdc_data_map.items():
                fdc_food = fdc_foods_map.get(fdc_id)
                if not fdc_food:
                    continue
                
                for data in data_list:
                    quantity_g = data["quantity_g"]
                    servings = data["servings"]
                    scale = (quantity_g * servings) / 100.0
                    
                    for field, key in micro_fields:
                        if field in fdc_food:
                            value = _safe_float(fdc_food.get(field, 0.0), default=0.0)
                            total_micros[key] = total_micros.get(key, 0.0) + value * scale
        except Exception as e:
            logging.warning(f"Failed to batch fetch FDC foods for micros: {str(e)}")
    
    # Calculate averages for weekly plans
    if plan_type == "week":
        avg_micros = {k: v / 7.0 for k, v in total_micros.items()}
    else:
        avg_micros = total_micros
    
    # Identify deficits
    deficits = {}
    for nutrient, total in avg_micros.items():
        rda = rdas.get(nutrient, 0.0)
        if rda > 0 and total < rda:
            deficit = rda - total
            deficits[nutrient] = {
                "total": total,
                "rda": rda,
                "deficit": deficit,
                "deficit_percent": (deficit / rda) * 100.0,
            }
    
    return {
        "total_micros": total_micros,
        "average_daily_micros": avg_micros,
        "rdas": rdas,
        "deficits": deficits,
        "has_deficits": len(deficits) > 0,
    }


def _ensure_meal_plan_collections(client):
    """
    Ensure MealPlan and MealPlanItem collections exist, return (plan_collection, item_collection) or (None, None).
    
    Args:
        client: Weaviate client
        
    Returns:
        Tuple of (plan_collection, item_collection) or (None, None) if collections don't exist
    """
    try:
        plan_collection = client.collections.get("MealPlan")
        item_collection = client.collections.get("MealPlanItem")
        return plan_collection, item_collection
    except Exception as e:
        logging.error(f"MealPlan collections not available: {str(e)}. Ensure collections are created via migrations.")
        return None, None


def sync_plan_to_weaviate(
    plan: Dict[str, Any],
    user_id: str,
    client_manager,
    start_date: str | None = None,
) -> Dict[str, Any]:
    """
    Upsert MealPlan + MealPlanItem records so downstream tools can rely on persisted data.
    
    IMPORTANT: This function is the source of truth for plan persistence.
    Always call this after modifying a plan to ensure changes are saved.
    
    Args:
        plan: Plan dictionary (will be modified in-place with plan_id, user_id, dates)
        user_id: User ID
        client_manager: ClientManager instance
        start_date: Optional start date override
        
    Returns:
        Plan dictionary with plan_id, user_id, start_date, created_at set
    """
    if not user_id:
        logging.warning("sync_plan_to_weaviate: user_id not provided, skipping persistence")
        return plan

    client = client_manager.get_client()
    plan_collection, item_collection = _ensure_meal_plan_collections(client)
    if not plan_collection or not item_collection:
        logging.warning("sync_plan_to_weaviate: collections unavailable, returning plan without persistence")
        return plan

    plan_type = plan.get("plan_type", "day")
    plan_id = plan.get("plan_id") or _generate_plan_id(user_id)
    
    # Normalize dates to RFC3339 format (UTC, 'Z' suffix)
    try:
        created_at = ensure_rfc3339_datetime(plan.get("created_at"))
        plan_start_date = ensure_rfc3339_datetime(
            plan.get("start_date") or start_date,
            date_only=True,
        )
    except Exception as e:
        logging.error(f"sync_plan_to_weaviate: date parsing error: {str(e)}")
        # Fallback to current time
        now = datetime.now(timezone.utc)
        created_at = ensure_rfc3339_datetime(now)
        plan_start_date = ensure_rfc3339_datetime(now, date_only=True)

    plan_payload = {
        "plan_id": plan_id,
        "user_id": user_id,
        "plan_type": plan_type,
        "start_date": plan_start_date,
        "created_at": created_at,
    }

    # Prevent duplicate day plans on the same date for the same user:
    # if a new day plan is being saved for a date where another day plan exists, delete the old plan + items.
    if plan_type == "day":
        try:
            duplicate_filter = build_filters_from_where(
                {
                    "operator": "And",
                    "operands": [
                        {"path": ["user_id"], "operator": "Equal", "valueString": user_id},
                        {"path": ["plan_type"], "operator": "Equal", "valueString": "day"},
                        {"path": ["start_date"], "operator": "Equal", "valueDate": plan_start_date},
                    ],
                }
            )
            existing_same_day = plan_collection.query.fetch_objects(
                filters=duplicate_filter,
                limit=5,
            )
            if existing_same_day.objects:
                for obj in existing_same_day.objects:
                    old_plan_id = obj.properties.get("plan_id")
                    # Delete old MealPlanItem records tied to the old plan
                    if old_plan_id:
                        old_plan_filter = build_filters_from_where(
                            {"path": ["plan_id"], "operator": "Equal", "valueString": old_plan_id}
                        )
                        old_items = item_collection.query.fetch_objects(filters=old_plan_filter, limit=256)
                        for itm in old_items.objects:
                            try:
                                item_collection.data.delete_by_id(itm.uuid)
                            except Exception as e:
                                logging.debug(f"sync_plan_to_weaviate: failed deleting old item {itm.uuid}: {str(e)}")
                    # Delete the old MealPlan record
                    try:
                        plan_collection.data.delete_by_id(obj.uuid)
                    except Exception as e:
                        logging.debug(f"sync_plan_to_weaviate: failed deleting old plan {obj.uuid}: {str(e)}")
        except Exception as e:
            logging.warning(f"sync_plan_to_weaviate: unable to purge existing day plan for {plan_start_date}: {str(e)}")

    plan_filter = build_filters_from_where(
        {"path": ["plan_id"], "operator": "Equal", "valueString": plan_id}
    )
    
    # Upsert MealPlan
    try:
        existing_plan = plan_collection.query.fetch_objects(filters=plan_filter, limit=1)
        if existing_plan.objects:
            plan_collection.data.update(uuid=existing_plan.objects[0].uuid, properties=plan_payload)
            logging.debug(f"sync_plan_to_weaviate: updated MealPlan {plan_id}")
        else:
            plan_collection.data.insert(plan_payload)
            logging.debug(f"sync_plan_to_weaviate: inserted new MealPlan {plan_id}")
    except Exception as e:
        logging.error(f"sync_plan_to_weaviate: failed to upsert MealPlan: {str(e)}")
        return plan  # Return plan without items if plan metadata fails

    # Build and sync MealPlanItems
    items = _build_plan_items(plan)
    if not items:
        logging.warning(f"sync_plan_to_weaviate: no items to sync for plan {plan_id}")
        plan["plan_id"] = plan_id
        plan["user_id"] = user_id
        plan["start_date"] = plan_start_date
        plan["created_at"] = created_at
        return plan

    # OPTIMIZATION: Batch delete existing items
    try:
        existing_items = item_collection.query.fetch_objects(filters=plan_filter, limit=256)
        if existing_items.objects:
            deleted_count = 0
            for obj in existing_items.objects:
                try:
                    item_collection.data.delete_by_id(obj.uuid)
                    deleted_count += 1
                except Exception as e:
                    logging.debug(f"sync_plan_to_weaviate: item {obj.uuid} already deleted or error: {str(e)}")
            logging.debug(f"sync_plan_to_weaviate: deleted {deleted_count} existing MealPlanItems for plan {plan_id}")
    except Exception as e:
        logging.warning(f"sync_plan_to_weaviate: failed to delete existing items: {str(e)}, continuing with insert")

    # OPTIMIZATION: Batch insert items
    inserted_count = 0
    for item in items:
        try:
            item_collection.data.insert({"plan_id": plan_id, **item})
            inserted_count += 1
        except Exception as e:
            logging.warning(f"sync_plan_to_weaviate: failed to insert plan item: {str(e)}")
            continue  # Continue with other items
    
    logging.debug(f"sync_plan_to_weaviate: inserted {inserted_count}/{len(items)} MealPlanItems for plan {plan_id}")

    # Update plan dict with persisted values
    plan["plan_id"] = plan_id
    plan["user_id"] = user_id
    plan["start_date"] = plan_start_date
    plan["created_at"] = created_at
    return plan
