"""
Main evaluation runner for MealAgent.

Chạy tất cả các phương pháp đánh giá và tổng hợp kết quả.
"""

import json
import os
from datetime import datetime
from typing import Dict, List, Any, Optional
from pathlib import Path
import pandas as pd

from evaluation.metrics.nutrition_error import NutritionErrorEvaluator
from evaluation.metrics.llm_judge import LLMJudgeEvaluator
from evaluation.metrics.bertscore_eval import BERTScoreEvaluator
from evaluation.test_cases.test_profiles import get_test_profiles
from evaluation.test_cases.test_scenarios import get_test_scenarios
from evaluation.utils.weaviate_data_loader import (
    load_evaluation_data_from_weaviate,
    get_all_user_ids_from_weaviate,
    create_client_manager,
)


class EvaluationRunner:
    """
    Main runner để chạy tất cả các phương pháp đánh giá.
    
    Hỗ trợ:
    - Nutrition Error (MAE & % Error)
    - LLM-as-a-judge
    - BERTScore evaluation
    """
    
    def __init__(
        self,
        results_dir: str = "evaluation/results",
        gemini_api_key: Optional[str] = None
    ):
        """
        Initialize the evaluation runner.
        
        Args:
            results_dir: Directory to save results
            gemini_api_key: Gemini API key for LLM judge (optional, can use env var)
        """
        self.results_dir = Path(results_dir)
        self.results_dir.mkdir(parents=True, exist_ok=True)
        
        # Initialize evaluators
        self.nutrition_evaluator = NutritionErrorEvaluator()
        
        # LLM judge evaluator (may fail if no API key)
        try:
            self.llm_judge = LLMJudgeEvaluator(api_key=gemini_api_key)
        except (ImportError, ValueError) as e:
            self.llm_judge = None
            print(f"Warning: LLM judge not available: {e}")
        
        # BERTScore evaluator (may fail if not installed)
        try:
            self.bertscore_evaluator = BERTScoreEvaluator()
        except ImportError:
            self.bertscore_evaluator = None
            print("Warning: BERTScore evaluator not available")
    
    def run_nutrition_evaluation(
        self,
        meal_plans: List[Dict[str, Any]],
        user_profiles: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Chạy đánh giá sai số dinh dưỡng.
        
        Args:
            meal_plans: List of meal plan dictionaries
            user_profiles: List of user profile dictionaries
        
        Returns:
            Evaluation results dictionary
        """
        print("Running Nutrition Error Evaluation...")
        
        results = self.nutrition_evaluator.evaluate_batch(
            meal_plans, user_profiles
        )
        
        # Aggregate results
        aggregated = self.nutrition_evaluator.aggregate_results(results)
        
        # Convert individual results to dicts
        individual_results = [r.to_dict() for r in results]
        
        return {
            "method": "nutrition_error",
            "individual_results": individual_results,
            "aggregated": aggregated,
        }
    
    def run_llm_judge_evaluation(
        self,
        meal_plans: List[Dict[str, Any]],
        user_profiles: List[Dict[str, Any]]
    ) -> Optional[Dict[str, Any]]:
        """
        Chạy đánh giá LLM-as-a-judge.
        
        Args:
            meal_plans: List of meal plan dictionaries
            user_profiles: List of user profile dictionaries
        
        Returns:
            Evaluation results dictionary or None if not available
        """
        if not self.llm_judge:
            print("Skipping LLM Judge evaluation (not available)")
            return None
        
        print("Running LLM-as-a-Judge Evaluation...")
        
        try:
            results = self.llm_judge.evaluate_batch(
                meal_plans, user_profiles
            )
            
            # Convert to dicts
            individual_results = [r.to_dict() for r in results]
            
            # Aggregate
            aggregated = {
                "overall_score": {
                    "mean": sum(r.overall_score for r in results) / len(results),
                    "std": pd.Series([r.overall_score for r in results]).std(),
                },
                "nutrition_score": {
                    "mean": sum(r.nutrition_score for r in results) / len(results),
                    "std": pd.Series([r.nutrition_score for r in results]).std(),
                },
                "variety_score": {
                    "mean": sum(r.variety_score for r in results) / len(results),
                    "std": pd.Series([r.variety_score for r in results]).std(),
                },
                "balance_score": {
                    "mean": sum(r.balance_score for r in results) / len(results),
                    "std": pd.Series([r.balance_score for r in results]).std(),
                },
                "feasibility_score": {
                    "mean": sum(r.feasibility_score for r in results) / len(results),
                    "std": pd.Series([r.feasibility_score for r in results]).std(),
                },
            }
            
            return {
                "method": "llm_judge",
                "individual_results": individual_results,
                "aggregated": aggregated,
            }
        except Exception as e:
            print(f"Error in LLM Judge evaluation: {e}")
            return None
    
    def run_bertscore_evaluation(
        self,
        meal_plans: List[Dict[str, Any]],
        user_profiles: List[Dict[str, Any]],
        reference_plans: Optional[List[Dict[str, Any]]] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Chạy đánh giá BERTScore.
        
        Args:
            meal_plans: List of meal plan dictionaries
            user_profiles: List of user profile dictionaries
            reference_plans: Optional list of reference meal plans
        
        Returns:
            Evaluation results dictionary or None if not available
        """
        if not self.bertscore_evaluator:
            print("Skipping BERTScore evaluation (not available)")
            return None
        
        print("Running BERTScore Evaluation...")
        
        try:
            results = self.bertscore_evaluator.evaluate_batch(
                meal_plans, user_profiles, reference_plans
            )
            
            # Convert to dicts
            individual_results = [r.to_dict() for r in results]
            
            # Aggregate
            aggregated = {
                "precision": {
                    "mean": sum(r.precision for r in results) / len(results),
                    "std": pd.Series([r.precision for r in results]).std(),
                },
                "recall": {
                    "mean": sum(r.recall for r in results) / len(results),
                    "std": pd.Series([r.recall for r in results]).std(),
                },
                "f1": {
                    "mean": sum(r.f1 for r in results) / len(results),
                    "std": pd.Series([r.f1 for r in results]).std(),
                },
            }
            
            return {
                "method": "bertscore",
                "individual_results": individual_results,
                "aggregated": aggregated,
            }
        except Exception as e:
            print(f"Error in BERTScore evaluation: {e}")
            return None
    
    def run_all_evaluations(
        self,
        meal_plans: List[Dict[str, Any]],
        user_profiles: List[Dict[str, Any]],
        user_queries: Optional[List[str]] = None,
        reference_plans: Optional[List[Dict[str, Any]]] = None
    ) -> Dict[str, Any]:
        """
        Chạy tất cả các phương pháp đánh giá.
        
        Args:
            meal_plans: List of meal plan dictionaries
            user_profiles: List of user profile dictionaries
            user_queries: Optional list of user queries
            reference_plans: Optional list of reference meal plans
        
        Returns:
            Dictionary với tất cả kết quả đánh giá
        """
        print(f"Running evaluations for {len(meal_plans)} meal plans...")
        
        results = {
            "timestamp": datetime.now().isoformat(),
            "num_plans": len(meal_plans),
            "evaluations": {},
        }
        
        # Run all evaluations
        results["evaluations"]["nutrition_error"] = self.run_nutrition_evaluation(
            meal_plans, user_profiles
        )
        
        results["evaluations"]["llm_judge"] = self.run_llm_judge_evaluation(
            meal_plans, user_profiles
        )
        
        results["evaluations"]["bertscore"] = self.run_bertscore_evaluation(
            meal_plans, user_profiles, reference_plans
        )
        
        return results
    
    def save_results(
        self,
        results: Dict[str, Any],
        filename: Optional[str] = None
    ) -> str:
        """
        Lưu kết quả đánh giá vào file.
        
        Args:
            results: Results dictionary
            filename: Optional filename (default: auto-generated)
        
        Returns:
            Path to saved file
        """
        if filename is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"evaluation_results_{timestamp}.json"
        
        filepath = self.results_dir / filename
        
        # Save JSON
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
        
        print(f"Results saved to: {filepath}")
        
        # Also save CSV summary
        self._save_csv_summary(results, filepath.stem)
        
        return str(filepath)
    
    def _save_csv_summary(
        self,
        results: Dict[str, Any],
        base_name: str
    ):
        """Save CSV summary of results."""
        rows = []
        
        evaluations = results.get("evaluations", {})
        num_plans = results.get("num_plans", 0)
        
        for method, eval_results in evaluations.items():
            if eval_results is None:
                continue
            
            aggregated = eval_results.get("aggregated", {})
            
            if method == "nutrition_error":
                # Nutrition error metrics
                mae = aggregated.get("mae", {})
                pct_error = aggregated.get("percentage_error", {})
                
                for metric in ["protein_g", "carb_g", "fat_g", "calories", "overall"]:
                    rows.append({
                        "method": method,
                        "metric": f"MAE_{metric}",
                        "mean": mae.get(metric, {}).get("mean", 0),
                        "std": mae.get(metric, {}).get("std", 0),
                    })
                    rows.append({
                        "method": method,
                        "metric": f"PctError_{metric}",
                        "mean": pct_error.get(metric, {}).get("mean", 0),
                        "std": pct_error.get(metric, {}).get("std", 0),
                    })
            
            elif method == "llm_judge":
                # LLM judge metrics
                for metric in ["overall_score", "nutrition_score", "variety_score", "balance_score", "feasibility_score"]:
                    rows.append({
                        "method": method,
                        "metric": metric,
                        "mean": aggregated.get(metric, {}).get("mean", 0),
                        "std": aggregated.get(metric, {}).get("std", 0),
                    })
            
            elif method == "bertscore":
                # BERTScore metrics
                for metric in ["precision", "recall", "f1"]:
                    rows.append({
                        "method": method,
                        "metric": metric,
                        "mean": aggregated.get(metric, {}).get("mean", 0),
                        "std": aggregated.get(metric, {}).get("std", 0),
                    })
        
        if rows:
            df = pd.DataFrame(rows)
            csv_path = self.results_dir / f"{base_name}_summary.csv"
            df.to_csv(csv_path, index=False)
            print(f"CSV summary saved to: {csv_path}")
    
    @staticmethod
    def load_data_from_weaviate(
        user_ids: Optional[List[str]] = None,
        plan_type: str = "day",
        use_latest: bool = True
    ) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """
        Helper method để load meal plans và user profiles từ Weaviate.
        
        Args:
            user_ids: List of user IDs (nếu None, sẽ lấy tất cả users)
            plan_type: "day" hoặc "week"
            use_latest: Load plan mới nhất của mỗi user
        
        Returns:
            Tuple of (meal_plans, user_profiles)
        """
        client_manager = create_client_manager()
        
        if not client_manager.is_client:
            raise ValueError(
                "Weaviate client is not available. "
                "Please check your Weaviate configuration (WCD_URL, WCD_API_KEY, WEAVIATE_IS_LOCAL)."
            )
        
        if user_ids is None:
            user_ids = get_all_user_ids_from_weaviate(client_manager, limit=100)
            if not user_ids:
                raise ValueError("No users found in Weaviate")
        
        return load_evaluation_data_from_weaviate(
            user_ids, client_manager, plan_type, use_latest
        )

