"""
Pytest configuration and fixtures for MealAgent tests.

This module provides shared fixtures for testing MealAgent tools, including:
- Mock TreeData and Environment
- Mock ClientManager
- Mock LLM clients
- Sample test data (profiles, recipes, etc.)
"""

import pytest
from unittest.mock import MagicMock, AsyncMock
from typing import Dict, Any, List
import sys
import os

# Try to import Elysia modules, fallback to mocks if not available
try:
    from elysia.tree.objects import TreeData
    from elysia.util.client import ClientManager
except ImportError:
    # If Elysia is not installed, use mocks
    TreeData = MagicMock
    ClientManager = MagicMock


@pytest.fixture
def mock_tree_data():
    """Create a mock TreeData object with environment."""
    tree_data = MagicMock(spec=TreeData)
    tree_data.environment = MagicMock()
    tree_data.environment.find = MagicMock(return_value=None)
    tree_data.environment.add = MagicMock()
    tree_data.environment.add_objects = MagicMock()
    tree_data.environment.replace = MagicMock()
    tree_data.environment.remove = MagicMock()
    tree_data.environment.hidden_environment = {}
    tree_data.user_prompt = ""
    return tree_data


@pytest.fixture
def mock_client_manager():
    """Create a mock ClientManager."""
    client_manager = MagicMock(spec=ClientManager)
    client = MagicMock()
    client_manager.get_client = MagicMock(return_value=client)
    client_manager.get_async_client = MagicMock(return_value=AsyncMock())
    return client_manager


@pytest.fixture
def mock_base_lm():
    """Create a mock base LLM client."""
    base_lm = MagicMock()
    base_lm.generate_structured = AsyncMock(return_value='{"result": "test"}')
    return base_lm


@pytest.fixture
def sample_profile_data():
    """Sample user profile data for testing."""
    return {
        "user_id": "test_user_123",
        "age": 30,
        "gender": "male",
        "weight_kg": 75.0,
        "height_cm": 175.0,
        "activity_level": "moderate",
        "diet_type": "vegetarian",
        "allergens": ["dairy"],
        "max_cooking_time_min": 30,
        "available_equipment": ["oven", "stovetop"],
    }


@pytest.fixture
def sample_recipe_data():
    """Sample recipe data for testing."""
    return {
        "food_id": "recipe_001",
        "dish_name": "Vegetarian Pasta",
        "dish_type": "main",
        "serving_size": 2,
        "cooking_time": 25,
        "ingredients": ["pasta", "tomato", "basil", "olive oil"],
        "ingredients_with_qty": ["200g pasta", "2 tomatoes", "10g basil", "20ml olive oil"],
        "cooking_method_array": ["Boil pasta", "Sauté tomatoes", "Mix together"],
        "macros_per_serving": {
            "kcal": 450.0,
            "protein_g": 15.0,
            "fat_g": 12.0,
            "carb_g": 65.0,
        },
        "diet_type": ["vegetarian"],
        "allergens": [],
    }


@pytest.fixture
def sample_targets():
    """Sample macro targets for testing."""
    return {
        "tdee_kcal": 2200.0,
        "protein_g": 165.0,
        "fat_g": 73.0,
        "carb_g": 220.0,
        "split": {"protein": 0.30, "fat": 0.30, "carb": 0.40},
    }


@pytest.fixture
def sample_meal_plan():
    """Sample daily meal plan for testing."""
    return {
        "plan_type": "day",
        "meals": {
            "breakfast": {
                "meal_type": "breakfast",
                "recipe": {
                    "food_id": "recipe_001",
                    "dish_name": "Vegetarian Pasta",
                    "macros_per_serving": {
                        "kcal": 450.0,
                        "protein_g": 15.0,
                        "fat_g": 12.0,
                        "carb_g": 65.0,
                    },
                    "diet_type": ["vegetarian"],
                    "allergens": [],
                },
                "servings": 1.0,
                "macros": {
                    "kcal": 450.0,
                    "protein_g": 15.0,
                    "fat_g": 12.0,
                    "carb_g": 65.0,
                },
            },
            "lunch": {
                "meal_type": "lunch",
                "recipe": {
                    "food_id": "recipe_002",
                    "dish_name": "Vegetarian Salad",
                    "macros_per_serving": {
                        "kcal": 300.0,
                        "protein_g": 10.0,
                        "fat_g": 8.0,
                        "carb_g": 45.0,
                    },
                    "diet_type": ["vegetarian"],
                    "allergens": [],
                },
                "servings": 1.0,
                "macros": {
                    "kcal": 300.0,
                    "protein_g": 10.0,
                    "fat_g": 8.0,
                    "carb_g": 45.0,
                },
            },
            "dinner": {
                "meal_type": "dinner",
                "recipe": {
                    "food_id": "recipe_003",
                    "dish_name": "Vegetarian Stir Fry",
                    "macros_per_serving": {
                        "kcal": 500.0,
                        "protein_g": 20.0,
                        "fat_g": 15.0,
                        "carb_g": 60.0,
                    },
                    "diet_type": ["vegetarian"],
                    "allergens": [],
                },
                "servings": 1.0,
                "macros": {
                    "kcal": 500.0,
                    "protein_g": 20.0,
                    "fat_g": 15.0,
                    "carb_g": 60.0,
                },
            },
        },
        "total_macros": {
            "kcal": 1250.0,
            "protein_g": 45.0,
            "fat_g": 35.0,
            "carb_g": 170.0,
        },
        "validation": {
            "valid": True,
            "macro_validation": {"valid": True, "violations": [], "warnings": []},
            "constraint_validation": {"valid": True, "violations": []},
        },
    }


@pytest.fixture
def sample_meal_log():
    """Sample meal log entry for testing."""
    return {
        "log_id": "log_001",
        "user_id": "test_user_123",
        "logged_at": "2025-01-27T12:00:00",
        "meal_description": "I ate chicken salad with olive oil",
        "parsed_dish": "Chicken Salad",
        "calculated_macros": {
            "kcal": 350.0,
            "protein_g": 25.0,
            "fat_g": 20.0,
            "carb_g": 15.0,
        },
        "portion_size": 1.0,
    }
