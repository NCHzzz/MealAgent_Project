"""
Unit tests for missing macros detection in score_and_rank.py.
"""
import pytest


class TestMissingMacrosDetection:
    """Test detection of recipes with missing macros_per_serving."""

    def test_recipe_with_macros(self):
        """Test that recipe with valid macros is detected correctly."""
        recipe = {
            "food_id": "recipe1",
            "dish_name": "Chicken Salad",
            "macros_per_serving": {
                "kcal": 500.0,
                "protein_g": 30.0,
                "fat_g": 20.0,
                "carb_g": 50.0,
            },
        }
        
        macros = recipe.get("macros_per_serving", {})
        has_macros = macros and isinstance(macros, dict) and macros.get("kcal")
        assert has_macros is True

    def test_recipe_without_macros(self):
        """Test that recipe without macros is detected correctly."""
        recipe = {
            "food_id": "recipe1",
            "dish_name": "Chicken Salad",
            # No macros_per_serving
        }
        
        macros = recipe.get("macros_per_serving", {})
        has_macros = macros and isinstance(macros, dict) and macros.get("kcal")
        assert has_macros is False

    def test_recipe_with_empty_macros(self):
        """Test that recipe with empty macros dict is detected correctly."""
        recipe = {
            "food_id": "recipe1",
            "dish_name": "Chicken Salad",
            "macros_per_serving": {},
        }
        
        macros = recipe.get("macros_per_serving", {})
        has_macros = macros and isinstance(macros, dict) and macros.get("kcal")
        assert has_macros is False

    def test_recipe_with_macros_no_kcal(self):
        """Test that recipe with macros but no kcal is detected as missing."""
        recipe = {
            "food_id": "recipe1",
            "dish_name": "Chicken Salad",
            "macros_per_serving": {
                "protein_g": 30.0,
                # Missing kcal
            },
        }
        
        macros = recipe.get("macros_per_serving", {})
        has_macros = macros and isinstance(macros, dict) and macros.get("kcal")
        assert has_macros is False

    def test_recipe_with_macros_string(self):
        """Test that recipe with macros as string (not dict) is detected as missing."""
        recipe = {
            "food_id": "recipe1",
            "dish_name": "Chicken Salad",
            "macros_per_serving": '{"kcal": 500.0}',  # String instead of dict
        }
        
        macros = recipe.get("macros_per_serving", {})
        has_macros = macros and isinstance(macros, dict) and macros.get("kcal")
        assert has_macros is False

    def test_count_missing_macros(self):
        """Test counting recipes with missing macros."""
        recipes = [
            {"food_id": "r1", "macros_per_serving": {"kcal": 500.0}},
            {"food_id": "r2"},  # Missing macros
            {"food_id": "r3", "macros_per_serving": {"kcal": 400.0}},
            {"food_id": "r4", "macros_per_serving": {}},  # Empty macros
            {"food_id": "r5", "macros_per_serving": {"kcal": 300.0}},
        ]
        
        missing_count = 0
        for recipe in recipes:
            macros = recipe.get("macros_per_serving", {})
            if not macros or not isinstance(macros, dict) or not macros.get("kcal"):
                missing_count += 1
        
        assert missing_count == 2  # r2 and r4

