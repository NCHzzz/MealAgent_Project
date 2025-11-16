"""
Unit tests for planning helper functions.

Tests for:
- _get_meal_macros
- _validate_macro_targets
- _validate_constraints
"""

import pytest
from MealAgent.tools.utils.planning_helpers import (
    _get_meal_macros,
    _validate_macro_targets,
    _validate_constraints,
)


def test_get_meal_macros_with_macros():
    """Test extracting macros from recipe with macros_per_serving."""
    recipe = {
        "food_id": "recipe_001",
        "dish_name": "Test Recipe",
        "macros_per_serving": {
            "kcal": 450.0,
            "protein_g": 15.0,
            "fat_g": 12.0,
            "carb_g": 65.0,
        },
    }
    
    macros = _get_meal_macros(recipe)
    assert macros["kcal"] == 450.0
    assert macros["protein_g"] == 15.0
    assert macros["fat_g"] == 12.0
    assert macros["carb_g"] == 65.0


def test_get_meal_macros_missing_macros():
    """Test extracting macros from recipe without macros_per_serving."""
    recipe = {
        "food_id": "recipe_001",
        "dish_name": "Test Recipe",
    }
    
    macros = _get_meal_macros(recipe)
    assert macros["kcal"] == 0.0
    assert macros["protein_g"] == 0.0
    assert macros["fat_g"] == 0.0
    assert macros["carb_g"] == 0.0


def test_get_meal_macros_invalid_macros():
    """Test extracting macros from recipe with invalid macros_per_serving."""
    recipe = {
        "food_id": "recipe_001",
        "dish_name": "Test Recipe",
        "macros_per_serving": "invalid",  # Not a dict
    }
    
    macros = _get_meal_macros(recipe)
    assert macros["kcal"] == 0.0
    assert macros["protein_g"] == 0.0
    assert macros["fat_g"] == 0.0
    assert macros["carb_g"] == 0.0


def test_validate_macro_targets_within_tolerance():
    """Test validation when macros are within tolerance."""
    total_macros = {
        "kcal": 2000.0,
        "protein_g": 150.0,
        "fat_g": 67.0,
        "carb_g": 200.0,
    }
    targets = {
        "kcal": 2000.0,
        "protein_g": 150.0,
        "fat_g": 67.0,
        "carb_g": 200.0,
    }
    
    validation = _validate_macro_targets(total_macros, targets, tolerance_percent=0.15)
    assert validation["valid"] is True
    assert len(validation["violations"]) == 0


def test_validate_macro_targets_exceeds_tolerance():
    """Test validation when macros exceed tolerance."""
    total_macros = {
        "kcal": 2500.0,  # 25% over target
        "protein_g": 150.0,
        "fat_g": 67.0,
        "carb_g": 200.0,
    }
    targets = {
        "kcal": 2000.0,
        "protein_g": 150.0,
        "fat_g": 67.0,
        "carb_g": 200.0,
    }
    
    validation = _validate_macro_targets(total_macros, targets, tolerance_percent=0.15)
    assert validation["valid"] is False
    assert len(validation["violations"]) > 0
    assert any(v["macro"] == "kcal" for v in validation["violations"])


def test_validate_macro_targets_warning_threshold():
    """Test validation when macros are near tolerance (warning)."""
    total_macros = {
        "kcal": 2200.0,  # 10% over target (within tolerance but near limit)
        "protein_g": 150.0,
        "fat_g": 67.0,
        "carb_g": 200.0,
    }
    targets = {
        "kcal": 2000.0,
        "protein_g": 150.0,
        "fat_g": 67.0,
        "carb_g": 200.0,
    }
    
    validation = _validate_macro_targets(total_macros, targets, tolerance_percent=0.15)
    # Should be valid but may have warnings
    assert validation["valid"] is True
    # May have warnings for kcal


def test_validate_constraints_diet_match():
    """Test constraint validation when diet types match."""
    plan = {
        "meals": {
            "breakfast": {
                "recipe": {
                    "food_id": "recipe_001",
                    "dish_name": "Vegetarian Pasta",
                    "diet_type": "vegetarian",
                },
            },
        },
    }
    
    validation = _validate_constraints(plan, diet_types=["vegetarian"])
    assert validation["valid"] is True
    assert len(validation["violations"]) == 0


def test_validate_constraints_diet_mismatch():
    """Test constraint validation when diet types don't match."""
    plan = {
        "meals": {
            "breakfast": {
                "recipe": {
                    "food_id": "recipe_001",
                    "dish_name": "Chicken Pasta",
                    "diet_type": "omnivore",
                },
            },
        },
    }
    
    validation = _validate_constraints(plan, diet_types=["vegetarian"])
    assert validation["valid"] is False
    assert len(validation["violations"]) > 0
    assert any(v["type"] == "diet_mismatch" for v in validation["violations"])


def test_validate_constraints_allergen_violation():
    """Test constraint validation when allergens are present."""
    plan = {
        "meals": {
            "breakfast": {
                "recipe": {
                    "food_id": "recipe_001",
                    "dish_name": "Peanut Butter Toast",
                    "allergens": ["peanuts", "gluten"],
                },
            },
        },
    }
    
    validation = _validate_constraints(plan, exclude_allergens=["peanuts"])
    assert validation["valid"] is False
    assert len(validation["violations"]) > 0
    assert any(v["type"] == "allergen_violation" for v in validation["violations"])


def test_validate_constraints_no_violations():
    """Test constraint validation when no violations."""
    plan = {
        "meals": {
            "breakfast": {
                "recipe": {
                    "food_id": "recipe_001",
                    "dish_name": "Vegetarian Pasta",
                    "diet_type": "vegetarian",
                    "allergens": [],
                },
            },
        },
    }
    
    validation = _validate_constraints(plan, diet_types=["vegetarian"], exclude_allergens=["dairy"])
    assert validation["valid"] is True
    assert len(validation["violations"]) == 0

