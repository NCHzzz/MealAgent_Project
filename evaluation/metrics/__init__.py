"""
Evaluation metrics for MealAgent.

This module provides various evaluation methods:
- Nutrition error metrics (MAE, % Error)
- RAGAS evaluation for Agentic RAG
- LLM-as-a-judge evaluation
- BERTScore semantic similarity
"""

from .nutrition_error import NutritionErrorEvaluator
from .llm_judge import LLMJudgeEvaluator
# from .bertscore_eval import BERTScoreEvaluator

__all__ = [
    "NutritionErrorEvaluator",
    "RAGASEvaluator",
    "LLMJudgeEvaluator",
    "BERTScoreEvaluator",
]

