"""
Evaluation metrics for MealAgent.

This module provides various evaluation methods:
- Nutrition error metrics (MAE, % Error)
- LLM-as-a-judge evaluation
"""

from .nutrition_error import NutritionErrorEvaluator
from .llm_judge import LLMJudgeEvaluator

__all__ = [
    "NutritionErrorEvaluator",
    "LLMJudgeEvaluator",
]


