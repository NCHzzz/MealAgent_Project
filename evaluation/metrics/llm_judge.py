"""
LLM-as-a-Judge Evaluation.

Sử dụng mô hình LLM thông minh (Gemini 3) đóng vai trò chuyên gia dinh dưỡng
để đánh giá chất lượng meal plan.
"""

from typing import Dict, List, Any, Optional
from dataclasses import dataclass
import json
import os

try:
    import google.generativeai as genai
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False
    print("Warning: Google Generative AI not available. Install with: pip install google-generativeai")


@dataclass
class LLMJudgeResult:
    """Kết quả đánh giá từ LLM judge."""
    overall_score: float  # 0-100
    nutrition_score: float  # 0-100
    variety_score: float  # 0-100
    balance_score: float  # 0-100
    feasibility_score: float  # 0-100
    
    # Detailed feedback
    feedback: str
    strengths: List[str]
    weaknesses: List[str]
    suggestions: List[str]
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "scores": {
                "overall": self.overall_score,
                "nutrition": self.nutrition_score,
                "variety": self.variety_score,
                "balance": self.balance_score,
                "feasibility": self.feasibility_score,
            },
            "feedback": self.feedback,
            "strengths": self.strengths,
            "weaknesses": self.weaknesses,
            "suggestions": self.suggestions,
        }


class LLMJudgeEvaluator:
    """
    Đánh giá meal plan sử dụng LLM (Gemini 3) như một chuyên gia dinh dưỡng.
    
    LLM judge sẽ đánh giá:
    - Nutrition accuracy (độ chính xác dinh dưỡng)
    - Variety (tính đa dạng)
    - Balance (tính cân bằng)
    - Feasibility (tính khả thi)
    """
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        model_name: str = "gemini-2.0-flash-exp"
    ):
        """
        Initialize the LLM judge evaluator.
        
        Args:
            api_key: Google API key (or set GEMINI_API_KEY env var)
            model_name: Model name to use (default: gemini-2.0-flash-exp)
        """
        if not GEMINI_AVAILABLE:
            raise ImportError(
                "Google Generative AI is not installed. "
                "Install with: pip install google-generativeai"
            )
        
        # Get API key
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        if not self.api_key:
            raise ValueError(
                "GEMINI_API_KEY must be provided as argument or environment variable"
            )
        
        # Configure Gemini
        genai.configure(api_key=self.api_key)
        self.model = genai.GenerativeModel(model_name)
        self.model_name = model_name
    
    def format_meal_plan_for_judge(
        self,
        meal_plan: Dict[str, Any]
    ) -> str:
        """
        Format meal plan thành text để LLM judge đánh giá.
        
        Args:
            meal_plan: Meal plan dictionary
        
        Returns:
            Formatted string
        """
        lines = ["=== MEAL PLAN ==="]
        
        # Add meals
        meals = meal_plan.get("meals", {})
        for meal_type, meal_data in meals.items():
            recipe = meal_data.get("recipe", {})
            if recipe:
                dish_name = recipe.get("dish_name", "")
                macros = meal_data.get("macros", {})
                
                lines.append(f"\n{meal_type.upper()}:")
                lines.append(f"  Dish: {dish_name}")
                if macros:
                    lines.append(
                        f"  Nutrition: {macros.get('kcal', 0):.0f} kcal, "
                        f"{macros.get('protein_g', 0):.1f}g protein, "
                        f"{macros.get('carb_g', 0):.1f}g carb, "
                        f"{macros.get('fat_g', 0):.1f}g fat"
                    )
                
                # Add accompaniments
                accompaniments = meal_data.get("accompaniments", [])
                if accompaniments:
                    for acc in accompaniments:
                        acc_recipe = acc.get("recipe", {})
                        acc_name = acc_recipe.get("dish_name", "")
                        acc_type = acc.get("type", "")
                        lines.append(f"  - {acc_name} ({acc_type})")
        
        # Add total nutrition
        total_macros = meal_plan.get("total_macros", {})
        if total_macros:
            lines.append("\n=== TOTAL NUTRITION ===")
            lines.append(
                f"Calories: {total_macros.get('kcal', 0):.0f} kcal"
            )
            lines.append(
                f"Protein: {total_macros.get('protein_g', 0):.1f}g"
            )
            lines.append(
                f"Carb: {total_macros.get('carb_g', 0):.1f}g"
            )
            lines.append(
                f"Fat: {total_macros.get('fat_g', 0):.1f}g"
            )
        
        return "\n".join(lines)
    
    def format_user_profile_for_judge(
        self,
        user_profile: Dict[str, Any]
    ) -> str:
        """
        Format user profile thành text để LLM judge đánh giá.
        
        Args:
            user_profile: User profile dictionary
        
        Returns:
            Formatted string
        """
        lines = ["=== USER PROFILE ==="]
        
        # Basic info
        lines.append(f"Age: {user_profile.get('age', 'N/A')}")
        lines.append(f"Gender: {user_profile.get('gender', 'N/A')}")
        lines.append(f"Weight: {user_profile.get('weight_kg', 'N/A')} kg")
        lines.append(f"Height: {user_profile.get('height_cm', 'N/A')} cm")
        lines.append(f"Activity Level: {user_profile.get('activity_level', 'N/A')}")
        lines.append(f"Goal: {user_profile.get('goal', 'N/A')}")
        
        # Nutrition targets
        lines.append("\n=== NUTRITION TARGETS ===")
        lines.append(f"TDEE: {user_profile.get('tdee_kcal', 0):.0f} kcal")
        lines.append(f"Protein: {user_profile.get('protein_g', 0):.1f}g")
        lines.append(f"Carb: {user_profile.get('carb_g', 0):.1f}g")
        lines.append(f"Fat: {user_profile.get('fat_g', 0):.1f}g")
        
        # Dietary constraints
        diet_type = user_profile.get("diet_type")
        if diet_type:
            lines.append(f"\nDiet Type: {diet_type}")
        
        allergens = user_profile.get("allergens", [])
        if allergens:
            lines.append(f"Allergens to avoid: {', '.join(allergens)}")
        
        preferences = user_profile.get("preferences", [])
        if preferences:
            lines.append(f"Preferences: {', '.join(preferences)}")
        
        return "\n".join(lines)
    
    def create_judge_prompt(
        self,
        meal_plan_text: str,
        user_profile_text: str
    ) -> str:
        """
        Tạo prompt cho LLM judge.
        
        Args:
            meal_plan_text: Formatted meal plan text
            user_profile_text: Formatted user profile text
        
        Returns:
            Judge prompt
        """
        prompt = f"""Bạn là một chuyên gia dinh dưỡng với nhiều năm kinh nghiệm. 
Hãy đánh giá meal plan dưới đây dựa trên user profile và đưa ra đánh giá chi tiết.

{user_profile_text}

{meal_plan_text}

Hãy đánh giá meal plan này trên các tiêu chí sau (mỗi tiêu chí 0-100 điểm):

1. **Nutrition Score**: Độ chính xác dinh dưỡng - meal plan có đáp ứng mục tiêu dinh dưỡng không?
2. **Variety Score**: Tính đa dạng - các món ăn có đa dạng không, có lặp lại quá nhiều không?
3. **Balance Score**: Tính cân bằng - các bữa ăn có cân bằng về dinh dưỡng và hương vị không?
4. **Feasibility Score**: Tính khả thi - meal plan có thực tế, dễ nấu, phù hợp với constraints không?

Hãy trả về kết quả dưới dạng JSON với format sau:
{{
    "overall_score": <tổng điểm trung bình 0-100>,
    "nutrition_score": <điểm dinh dưỡng 0-100>,
    "variety_score": <điểm đa dạng 0-100>,
    "balance_score": <điểm cân bằng 0-100>,
    "feasibility_score": <điểm khả thi 0-100>,
    "feedback": "<đánh giá tổng quan chi tiết>",
    "strengths": ["<điểm mạnh 1>", "<điểm mạnh 2>", ...],
    "weaknesses": ["<điểm yếu 1>", "<điểm yếu 2>", ...],
    "suggestions": ["<gợi ý cải thiện 1>", "<gợi ý cải thiện 2>", ...]
}}

Chỉ trả về JSON, không thêm text khác."""
        
        return prompt
    
    def parse_judge_response(
        self,
        response_text: str
    ) -> Dict[str, Any]:
        """
        Parse response từ LLM judge.
        
        Args:
            response_text: Response text from LLM
        
        Returns:
            Parsed dictionary
        """
        # Try to extract JSON from response
        response_text = response_text.strip()
        
        # Remove markdown code blocks if present
        if response_text.startswith("```"):
            lines = response_text.split("\n")
            response_text = "\n".join(lines[1:-1])
        
        # Try to parse JSON
        try:
            result = json.loads(response_text)
        except json.JSONDecodeError:
            # Try to extract JSON from text
            start_idx = response_text.find("{")
            end_idx = response_text.rfind("}") + 1
            if start_idx >= 0 and end_idx > start_idx:
                result = json.loads(response_text[start_idx:end_idx])
            else:
                # Fallback: return default structure
                result = {
                    "overall_score": 50.0,
                    "nutrition_score": 50.0,
                    "variety_score": 50.0,
                    "balance_score": 50.0,
                    "feasibility_score": 50.0,
                    "feedback": "Could not parse LLM response",
                    "strengths": [],
                    "weaknesses": [],
                    "suggestions": [],
                }
        
        return result
    
    def evaluate(
        self,
        meal_plan: Dict[str, Any],
        user_profile: Dict[str, Any]
    ) -> LLMJudgeResult:
        """
        Đánh giá meal plan sử dụng LLM judge.
        
        Args:
            meal_plan: Meal plan dictionary
            user_profile: User profile dictionary
        
        Returns:
            LLMJudgeResult object
        """
        # Format inputs
        meal_plan_text = self.format_meal_plan_for_judge(meal_plan)
        user_profile_text = self.format_user_profile_for_judge(user_profile)
        
        # Create prompt
        prompt = self.create_judge_prompt(meal_plan_text, user_profile_text)
        
        # Call LLM
        try:
            response = self.model.generate_content(prompt)
            response_text = response.text
        except Exception as e:
            # Fallback on error
            response_text = json.dumps({
                "overall_score": 50.0,
                "nutrition_score": 50.0,
                "variety_score": 50.0,
                "balance_score": 50.0,
                "feasibility_score": 50.0,
                "feedback": f"Error calling LLM: {str(e)}",
                "strengths": [],
                "weaknesses": [],
                "suggestions": [],
            })
        
        # Parse response
        parsed = self.parse_judge_response(response_text)
        
        return LLMJudgeResult(
            overall_score=float(parsed.get("overall_score", 50.0)),
            nutrition_score=float(parsed.get("nutrition_score", 50.0)),
            variety_score=float(parsed.get("variety_score", 50.0)),
            balance_score=float(parsed.get("balance_score", 50.0)),
            feasibility_score=float(parsed.get("feasibility_score", 50.0)),
            feedback=parsed.get("feedback", ""),
            strengths=parsed.get("strengths", []),
            weaknesses=parsed.get("weaknesses", []),
            suggestions=parsed.get("suggestions", []),
        )
    
    def evaluate_batch(
        self,
        meal_plans: List[Dict[str, Any]],
        user_profiles: List[Dict[str, Any]]
    ) -> List[LLMJudgeResult]:
        """
        Đánh giá nhiều meal plans.
        
        Args:
            meal_plans: List of meal plan dictionaries
            user_profiles: List of user profile dictionaries
        
        Returns:
            List of LLMJudgeResult objects
        """
        if len(meal_plans) != len(user_profiles):
            raise ValueError(
                f"meal_plans ({len(meal_plans)}) and user_profiles "
                f"({len(user_profiles)}) must have the same length"
            )
        
        results = []
        for meal_plan, user_profile in zip(meal_plans, user_profiles):
            result = self.evaluate(meal_plan, user_profile)
            results.append(result)
        
        return results

