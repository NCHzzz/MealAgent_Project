"""
BERTScore Evaluation for Semantic Similarity.

Đo lường độ tương đồng ngữ nghĩa giữa meal plan và reference/ground truth
sử dụng BERTScore.
"""

from typing import Dict, List, Any, Optional
from dataclasses import dataclass
import numpy as np

try:
    from bert_score import score
    BERTSCORE_AVAILABLE = True
except ImportError:
    BERTSCORE_AVAILABLE = False
    print("Warning: BERTScore not available. Install with: pip install bert-score")


@dataclass
class BERTScoreResult:
    """Kết quả đánh giá BERTScore."""
    precision: float  # P (precision)
    recall: float  # R (recall)
    f1: float  # F1 score
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "precision": self.precision,
            "recall": self.recall,
            "f1": self.f1,
        }


class BERTScoreEvaluator:
    """
    Đánh giá semantic similarity sử dụng BERTScore.
    
    BERTScore sử dụng contextual embeddings từ BERT để đo lường
    độ tương đồng ngữ nghĩa giữa các câu/text.
    """
    
    def __init__(
        self,
        model_type: str = "bert-base-multilingual-cased",
        lang: str = "vi"
    ):
        """
        Initialize the BERTScore evaluator.
        
        Args:
            model_type: BERT model type to use
            lang: Language code (vi for Vietnamese, en for English)
        """
        if not BERTSCORE_AVAILABLE:
            raise ImportError(
                "BERTScore is not installed. Install with: pip install bert-score"
            )
        
        self.model_type = model_type
        self.lang = lang
    
    def meal_plan_to_text(
        self,
        meal_plan: Dict[str, Any]
    ) -> str:
        """
        Convert meal plan thành text string để đánh giá.
        
        Args:
            meal_plan: Meal plan dictionary
        
        Returns:
            Text representation of meal plan
        """
        parts = []
        
        # Add meals
        meals = meal_plan.get("meals", {})
        for meal_type, meal_data in meals.items():
            recipe = meal_data.get("recipe", {})
            if recipe:
                dish_name = recipe.get("dish_name", "")
                parts.append(f"{meal_type}: {dish_name}")
                
                # Add accompaniments
                accompaniments = meal_data.get("accompaniments", [])
                for acc in accompaniments:
                    acc_recipe = acc.get("recipe", {})
                    acc_name = acc_recipe.get("dish_name", "")
                    parts.append(acc_name)
        
        # Add nutrition summary
        total_macros = meal_plan.get("total_macros", {})
        if total_macros:
            parts.append(
                f"{total_macros.get('kcal', 0):.0f} calories "
                f"{total_macros.get('protein_g', 0):.1f}g protein "
                f"{total_macros.get('carb_g', 0):.1f}g carb "
                f"{total_macros.get('fat_g', 0):.1f}g fat"
            )
        
        return " ".join(parts)
    
    def create_reference_text(
        self,
        user_profile: Dict[str, Any],
        reference_plan: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Tạo reference text từ user profile hoặc reference plan.
        
        Args:
            user_profile: User profile dictionary
            reference_plan: Optional reference meal plan
        
        Returns:
            Reference text string
        """
        if reference_plan:
            # Use reference plan if available
            return self.meal_plan_to_text(reference_plan)
        
        # Otherwise, create from user profile targets
        parts = []
        
        # Add target nutrition
        targets = {
            "calories": user_profile.get("tdee_kcal", 0),
            "protein": user_profile.get("protein_g", 0),
            "carb": user_profile.get("carb_g", 0),
            "fat": user_profile.get("fat_g", 0),
        }
        
        parts.append(
            f"target {targets['calories']:.0f} calories "
            f"{targets['protein']:.1f}g protein "
            f"{targets['carb']:.1f}g carb "
            f"{targets['fat']:.1f}g fat"
        )
        
        # Add constraints
        diet_type = user_profile.get("diet_type")
        if diet_type:
            parts.append(f"diet {diet_type}")
        
        allergens = user_profile.get("allergens", [])
        if allergens:
            parts.append(f"avoid {', '.join(allergens)}")
        
        return " ".join(parts)
    
    def evaluate(
        self,
        meal_plan: Dict[str, Any],
        user_profile: Dict[str, Any],
        reference_plan: Optional[Dict[str, Any]] = None
    ) -> BERTScoreResult:
        """
        Đánh giá semantic similarity sử dụng BERTScore.
        
        Args:
            meal_plan: Meal plan dictionary to evaluate
            user_profile: User profile dictionary
            reference_plan: Optional reference meal plan (ground truth)
        
        Returns:
            BERTScoreResult object
        """
        # Convert to text
        candidate_text = self.meal_plan_to_text(meal_plan)
        reference_text = self.create_reference_text(user_profile, reference_plan)
        
        # Calculate BERTScore
        # BERTScore expects lists of strings
        P, R, F1 = score(
            [candidate_text],
            [reference_text],
            model_type=self.model_type,
            lang=self.lang,
            verbose=False,
        )
        
        return BERTScoreResult(
            precision=float(P[0].item()),
            recall=float(R[0].item()),
            f1=float(F1[0].item()),
        )
    
    def evaluate_batch(
        self,
        meal_plans: List[Dict[str, Any]],
        user_profiles: List[Dict[str, Any]],
        reference_plans: Optional[List[Dict[str, Any]]] = None
    ) -> List[BERTScoreResult]:
        """
        Đánh giá nhiều meal plans.
        
        Args:
            meal_plans: List of meal plan dictionaries
            user_profiles: List of user profile dictionaries
            reference_plans: Optional list of reference meal plans
        
        Returns:
            List of BERTScoreResult objects
        """
        if len(meal_plans) != len(user_profiles):
            raise ValueError(
                f"meal_plans ({len(meal_plans)}) and user_profiles "
                f"({len(user_profiles)}) must have the same length"
            )
        
        if reference_plans and len(reference_plans) != len(meal_plans):
            raise ValueError(
                f"reference_plans ({len(reference_plans)}) must match "
                f"meal_plans length ({len(meal_plans)})"
            )
        
        # Convert all to text
        candidate_texts = [
            self.meal_plan_to_text(plan) for plan in meal_plans
        ]
        reference_texts = [
            self.create_reference_text(
                profile,
                reference_plans[i] if reference_plans else None
            )
            for i, profile in enumerate(user_profiles)
        ]
        
        # Calculate BERTScore for all
        P, R, F1 = score(
            candidate_texts,
            reference_texts,
            model_type=self.model_type,
            lang=self.lang,
            verbose=False,
        )
        
        # Convert to results
        results = []
        for i in range(len(meal_plans)):
            results.append(BERTScoreResult(
                precision=float(P[i].item()),
                recall=float(R[i].item()),
                f1=float(F1[i].item()),
            ))
        
        return results

