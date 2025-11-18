"""
Schema definitions for MealAgent Weaviate collections.

This module exports schema definitions for all collections used in MealAgent.
Each schema file defines a collection configuration that can be used to create
Weaviate collections via the migration script.
"""

from .recipe import RECIPE_SCHEMA
from .fdc_food import FDC_FOOD_SCHEMA
from .fdc_nutrient import FDC_NUTRIENT_SCHEMA
from .fdc_portion import FDC_PORTION_SCHEMA
from .user_profile import USER_PROFILE_SCHEMA
from .user_account import USER_ACCOUNT_SCHEMA
from .meal_plan import MEAL_PLAN_SCHEMA, MEAL_PLAN_ITEM_SCHEMA
from .meal_log_entry import MEAL_LOG_ENTRY_SCHEMA
from .pantry import PANTRY_SCHEMA, PANTRY_ITEM_SCHEMA
from .shopping import SHOPPING_LIST_SCHEMA, SHOPPING_ITEM_SCHEMA

__all__ = [
    "RECIPE_SCHEMA",
    "FDC_FOOD_SCHEMA",
    "FDC_NUTRIENT_SCHEMA",
    "FDC_PORTION_SCHEMA",
    "USER_PROFILE_SCHEMA",
    "USER_ACCOUNT_SCHEMA",
    "MEAL_PLAN_SCHEMA",
    "MEAL_PLAN_ITEM_SCHEMA",
    "MEAL_LOG_ENTRY_SCHEMA",
    "PANTRY_SCHEMA",
    "PANTRY_ITEM_SCHEMA",
    "SHOPPING_LIST_SCHEMA",
    "SHOPPING_ITEM_SCHEMA",
]

