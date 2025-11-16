"""
Helper functions for meal planning tools.
Extracted from legacy tools to be shared across E2E tools.
"""

from typing import Dict, Any, List


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

