"""
Unit tests for swap meal item tool (Phase 3.1).
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from MealAgent.tools.plan_day.swap_meal_item import (
    swap_meal_item_tool,
    _is_main_dish,
    _is_carb_dish,
)


def test_is_main_dish():
    """Test identifying main dishes."""
    main_recipe = {
        "dish_name": "Thịt kho",
        "dish_type": "main dish",
    }
    assert _is_main_dish(main_recipe) is True
    
    non_main = {
        "dish_name": "Cơm trắng",
        "dish_type": "rice",
    }
    assert _is_main_dish(non_main) is False


def test_is_carb_dish():
    """Test identifying carb dishes."""
    carb_recipe = {
        "dish_name": "Cơm trắng",
        "dish_type": "rice",
    }
    assert _is_carb_dish(carb_recipe) is True
    
    noodle_recipe = {
        "dish_name": "Phở bò",
        "dish_type": "noodle soup",
    }
    assert _is_carb_dish(noodle_recipe) is True
    
    non_carb = {
        "dish_name": "Thịt kho",
        "dish_type": "main dish",
    }
    assert _is_carb_dish(non_carb) is False


# Integration tests for swap_meal_item_tool would require complex mocking
# For now, we test the helper functions which are the core logic
# Full integration tests can be added later with proper fixtures

