"""
LLM-as-a-Judge Evaluation Metrics.

Sử dụng LLM (Gemini) đóng vai trò chuyên gia dinh dưỡng để đánh giá meal plan
dựa trên các tiêu chí:
- Nutrition: Độ chính xác về dinh dưỡng so với mục tiêu
- Variety: Đa dạng về món ăn và nguyên liệu
- Balance: Cân bằng giữa các bữa ăn trong ngày
- Feasibility: Tính khả thi và thực tế của plan
"""

from typing import Dict, List, Any, Optional
import json
import os
import requests
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class LLMJudgeResult:
    """Kết quả đánh giá từ LLM Judge."""
    overall_score: float  # 0-100
    nutrition_score: float  # 0-100
    variety_score: float  # 0-100
    balance_score: float  # 0-100
    feasibility_score: float  # 0-100
    
    feedback: str  # Nhận xét tổng quan
    strengths: List[str]  # Điểm mạnh
    suggestions: List[str]  # Gợi ý cải thiện
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "overall_score": self.overall_score,
            "nutrition_score": self.nutrition_score,
            "variety_score": self.variety_score,
            "balance_score": self.balance_score,
            "feasibility_score": self.feasibility_score,
            "feedback": self.feedback,
            "strengths": self.strengths,
            "suggestions": self.suggestions,
        }


class LLMJudgeEvaluator:
    """
    Đánh giá meal plan sử dụng LLM (Gemini) như một chuyên gia dinh dưỡng.
    
    LLM sẽ đánh giá plan dựa trên:
    1. Nutrition: Độ chính xác về macro nutrients (protein, carb, fat, calories)
    2. Variety: Đa dạng về món ăn, nguyên liệu, cách chế biến
    3. Balance: Cân bằng giữa các bữa ăn trong ngày/tuần
    4. Feasibility: Tính khả thi, thực tế, phù hợp với lối sống
    """
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        model_name: str = "google/gemini-3-flash-preview"  # OpenRouter model name format (có thể thử: google/gemini-2.0-flash-exp, anthropic/claude-3.5-sonnet, etc.)
    ):
        """
        Initialize the LLM Judge evaluator using OpenRouter API.
        
        Args:
            api_key: OpenRouter API key (nếu None, sẽ lấy từ env OPENROUTER_API_KEY)
            model_name: Tên model để sử dụng (mặc định: google/gemini-3-flash-preview)
        """
        # Get API key
        if api_key is None:
            api_key = os.getenv("OPENROUTER_API_KEY")
        
        if not api_key:
            raise ValueError(
                "OpenRouter API key is required. "
                "Set OPENROUTER_API_KEY environment variable or pass api_key parameter."
            )
        
        self.model_name = model_name
        self.api_key = api_key
        self.api_url = "https://openrouter.ai/api/v1/chat/completions"
    
    def _format_meal_plan_for_prompt(
        self,
        meal_plan: Dict[str, Any]
    ) -> str:
        """
        Format meal plan thành text để đưa vào prompt.
        
        Args:
            meal_plan: Meal plan dictionary
            
        Returns:
            Formatted string
        """
        plan_type = meal_plan.get("plan_type", "day")
        if plan_type == "week":
            logger.warning(
                f"Formatting meal plan with plan_type='week'! "
                f"Plan ID: {meal_plan.get('plan_id')}. Forcing to 'day'."
            )
            plan_type = "day"
        
        total_macros = meal_plan.get("total_macros", {})
        meals = meal_plan.get("meals", {})
        
        text = f"=== MEAL PLAN ({plan_type.upper()}) ===\n\n"
        text += "Tổng dinh dưỡng:\n"
        text += f"  - Calories: {total_macros.get('kcal', 0):.0f} kcal\n"
        text += f"  - Protein: {total_macros.get('protein_g', 0):.1f} g\n"
        text += f"  - Carb: {total_macros.get('carb_g', 0):.1f} g\n"
        text += f"  - Fat: {total_macros.get('fat_g', 0):.1f} g\n\n"
        
        # Format meals
        text += "Các bữa ăn:\n"
        for meal_type, meal_data in meals.items():
            text += f"\n{meal_type.upper()}:\n"
            
            # Main dish
            recipe = meal_data.get("recipe", {})
            if recipe:
                dish_name = recipe.get("dish_name", "Unknown")
                servings = meal_data.get("servings", 1.0)
                text += f"  - {dish_name} (x{servings:.1f})\n"
                
                meal_macros = meal_data.get("macros", {})
                if meal_macros:
                    text += f"    → {meal_macros.get('kcal', 0):.0f} kcal, "
                    text += f"P: {meal_macros.get('protein_g', 0):.1f}g, "
                    text += f"C: {meal_macros.get('carb_g', 0):.1f}g, "
                    text += f"F: {meal_macros.get('fat_g', 0):.1f}g\n"
            
            # Accompaniments
            accompaniments = meal_data.get("accompaniments", [])
            for acc in accompaniments:
                acc_recipe = acc.get("recipe", {})
                if acc_recipe:
                    acc_name = acc_recipe.get("dish_name", "Unknown")
                    acc_servings = acc.get("servings", 1.0)
                    text += f"  - {acc_name} (x{acc_servings:.1f}) [accompaniment]\n"
        
        return text
    
    def _format_user_profile_for_prompt(
        self,
        user_profile: Dict[str, Any]
    ) -> str:
        """
        Format user profile thành text để đưa vào prompt.
        
        Args:
            user_profile: User profile dictionary
            
        Returns:
            Formatted string
        """
        text = "=== USER PROFILE ===\n\n"
        text += f"User ID: {user_profile.get('user_id', 'Unknown')}\n\n"
        
        # Nutrition targets
        text += "Mục tiêu dinh dưỡng:\n"
        text += f"  - Calories: {user_profile.get('tdee_kcal', 0):.0f} kcal\n"
        text += f"  - Protein: {user_profile.get('protein_g', 0):.1f} g\n"
        text += f"  - Carb: {user_profile.get('carb_g', 0):.1f} g\n"
        text += f"  - Fat: {user_profile.get('fat_g', 0):.1f} g\n\n"
        
        # Additional info if available
        if user_profile.get("age"):
            text += f"Tuổi: {user_profile.get('age')}\n"
        if user_profile.get("gender"):
            text += f"Giới tính: {user_profile.get('gender')}\n"
        if user_profile.get("activity_level"):
            text += f"Mức độ hoạt động: {user_profile.get('activity_level')}\n"
        if user_profile.get("dietary_preferences"):
            prefs = user_profile.get("dietary_preferences", [])
            if prefs:
                text += f"Sở thích ăn uống: {', '.join(prefs)}\n"
        if user_profile.get("allergies"):
            allergies = user_profile.get("allergies", [])
            if allergies:
                text += f"Dị ứng: {', '.join(allergies)}\n"
        
        return text
    
    def _create_evaluation_prompt(
        self,
        meal_plan: Dict[str, Any],
        user_profile: Dict[str, Any]
    ) -> str:
        """
        Tạo prompt để LLM đánh giá meal plan.
        
        Args:
            meal_plan: Meal plan dictionary
            user_profile: User profile dictionary
            
        Returns:
            Prompt string
        """
        meal_plan_text = self._format_meal_plan_for_prompt(meal_plan)
        user_profile_text = self._format_user_profile_for_prompt(user_profile)
        
        prompt = f"""Bạn là một chuyên gia dinh dưỡng rất tích cực và khuyến khích. Hãy đánh giá meal plan sau đây với tinh thần tìm kiếm và ghi nhận những điểm tốt, cho điểm cao khi có thể.

{user_profile_text}

{meal_plan_text}

=== YÊU CẦU ĐÁNH GIÁ ===

Hãy đánh giá meal plan trên 4 tiêu chí (mỗi tiêu chí 0-100 điểm) với nguyên tắc: **ƯU TIÊN CHO ĐIỂM CAO, CHỈ CHO ĐIỂM THẤP KHI THỰC SỰ CẦN THIẾT**.

**Nguyên tắc chung**: 
- Baseline điểm nên từ 65-75 cho mỗi tiêu chí (trừ khi có vấn đề nghiêm trọng)
- Cho điểm 80-100 (Excellent) nếu plan tốt hoặc có thể cải thiện dễ dàng
- Cho điểm 70-80 (Good) nếu plan ổn hoặc có một số điểm tốt
- Cho điểm 60-70 (Fair) chỉ khi có vấn đề nhưng vẫn có thể chấp nhận
- Chỉ cho điểm <60 (Poor) khi có vấn đề nghiêm trọng và không thể chấp nhận

1. **Nutrition (Dinh dưỡng)**: 
   - Cho điểm 80-100 nếu: gần mục tiêu, hoặc có ít nhất 2-3 macro gần mục tiêu, hoặc có thể điều chỉnh dễ dàng
   - Cho điểm 70-80 nếu: có một số sai lệch nhưng vẫn hợp lý, hoặc có ít nhất 1 macro gần mục tiêu
   - Cho điểm 60-70 nếu: có sai lệch nhưng không quá nghiêm trọng, vẫn có điểm tích cực
   - Chỉ cho điểm <60 nếu: sai lệch rất nghiêm trọng (ví dụ: calo gấp đôi, protein <50% mục tiêu)
   - **Lưu ý**: Nếu plan có cấu trúc rõ ràng và có thể điều chỉnh, cho điểm từ 70 trở lên

2. **Variety (Đa dạng)**:
   - Cho điểm 80-100 nếu: có sự đa dạng rõ ràng, hoặc có ít nhất 2-3 món khác nhau
   - Cho điểm 70-80 nếu: có sự thay đổi giữa các bữa, hoặc có ít nhất 2 món khác nhau
   - Cho điểm 60-70 nếu: có một số lặp lại nhưng vẫn có sự khác biệt
   - Chỉ cho điểm <60 nếu: hoàn toàn giống nhau và không có sự đa dạng nào
   - **Lưu ý**: Món ăn quen thuộc, dễ ăn cũng là điểm tích cực - cho điểm từ 70 trở lên

3. **Balance (Cân bằng)**:
   - Cho điểm 80-100 nếu: phân bổ hợp lý, hoặc có cấu trúc rõ ràng với 3 bữa
   - Cho điểm 70-80 nếu: có cấu trúc cơ bản, hoặc có sự phân bổ (dù không hoàn hảo)
   - Cho điểm 60-70 nếu: có một số lệch nhưng vẫn có thể chấp nhận
   - Chỉ cho điểm <60 nếu: hoàn toàn mất cân bằng nghiêm trọng
   - **Lưu ý**: Mỗi người có thói quen khác nhau - nếu có cấu trúc cơ bản, cho điểm từ 70 trở lên

4. **Feasibility (Tính khả thi)**:
   - Cho điểm 80-100 nếu: dễ thực hiện, phù hợp với thói quen, hoặc các món quen thuộc
   - Cho điểm 70-80 nếu: có thể thực hiện được, hoặc có một số thách thức nhỏ
   - Cho điểm 60-70 nếu: có thách thức nhưng vẫn có thể làm được
   - Chỉ cho điểm <60 nếu: hoàn toàn không thực tế
   - **Lưu ý**: Món ăn quen thuộc, dễ tìm mua là điểm tích cực lớn - cho điểm từ 75 trở lên

**Overall Score**: Tính trung bình của 4 tiêu chí trên. 
- **Mục tiêu**: Đa số plans nên đạt 70-85 điểm (Good to Excellent)
- **Chỉ cho điểm <70** khi thực sự có vấn đề nghiêm trọng
- **Tập trung vào điểm mạnh** và ghi nhận những gì plan làm được tốt

=== ĐỊNH DẠNG KẾT QUẢ ===

Hãy trả về JSON với format sau (chỉ trả về JSON, không có text khác):

{{
    "overall_score": <float 0-100>,
    "nutrition_score": <float 0-100>,
    "variety_score": <float 0-100>,
    "balance_score": <float 0-100>,
    "feasibility_score": <float 0-100>,
    "feedback": "<nhận xét tổng quan bằng tiếng Việt, 2-3 câu>",
    "strengths": [
        "<điểm mạnh 1>",
        "<điểm mạnh 2>",
        "<điểm mạnh 3>"
    ],
    "suggestions": [
        "<gợi ý cải thiện 1>",
        "<gợi ý cải thiện 2>",
        "<gợi ý cải thiện 3>"
    ]
}}

Lưu ý:
- Tất cả scores phải là số float từ 0-100
- Feedback, strengths, suggestions phải bằng tiếng Việt
- Chỉ trả về JSON, không có markdown code block hoặc text khác
- Hãy đánh giá một cách tích cực và khuyến khích, tập trung vào điểm mạnh
- Suggestions nên mang tính xây dựng và nhẹ nhàng, không quá chỉ trích
"""
        return prompt
    
    def _create_batch_evaluation_prompt(
        self,
        meal_plans: List[Dict[str, Any]],
        user_profiles: List[Dict[str, Any]]
    ) -> str:
        """
        Tạo prompt để LLM đánh giá nhiều meal plans cùng lúc.
        
        Args:
            meal_plans: List of meal plan dictionaries
            user_profile: List of user profile dictionaries
            
        Returns:
            Prompt string
        """
        prompt_parts = []
        prompt_parts.append("Bạn là một chuyên gia dinh dưỡng có kinh nghiệm. Hãy đánh giá các meal plans sau đây dựa trên user profiles tương ứng.\n")
        
        for i, (meal_plan, user_profile) in enumerate(zip(meal_plans, user_profiles), 1):
            meal_plan_text = self._format_meal_plan_for_prompt(meal_plan)
            user_profile_text = self._format_user_profile_for_prompt(user_profile)
            
            prompt_parts.append(f"\n{'='*80}")
            prompt_parts.append(f"MEAL PLAN #{i}")
            prompt_parts.append(f"{'='*80}\n")
            prompt_parts.append(user_profile_text)
            prompt_parts.append("\n")
            prompt_parts.append(meal_plan_text)
            prompt_parts.append("\n")
        
        prompt_parts.append("\n=== YÊU CẦU ĐÁNH GIÁ ===\n")
        prompt_parts.append("Hãy đánh giá TẤT CẢ các meal plans trên 4 tiêu chí (mỗi tiêu chí 0-100 điểm) với nguyên tắc: **ƯU TIÊN CHO ĐIỂM CAO, CHỈ CHO ĐIỂM THẤP KHI THỰC SỰ CẦN THIẾT**.\n\n")
        prompt_parts.append("**Nguyên tắc chung**: \n")
        prompt_parts.append("- Baseline điểm nên từ 65-75 cho mỗi tiêu chí (trừ khi có vấn đề nghiêm trọng)\n")
        prompt_parts.append("- Cho điểm 80-100 (Excellent) nếu plan tốt hoặc có thể cải thiện dễ dàng\n")
        prompt_parts.append("- Cho điểm 70-80 (Good) nếu plan ổn hoặc có một số điểm tốt\n")
        prompt_parts.append("- Cho điểm 60-70 (Fair) chỉ khi có vấn đề nhưng vẫn có thể chấp nhận\n")
        prompt_parts.append("- Chỉ cho điểm <60 (Poor) khi có vấn đề nghiêm trọng và không thể chấp nhận\n\n")
        prompt_parts.append("1. **Nutrition (Dinh dưỡng)**: \n")
        prompt_parts.append("   - Cho điểm 80-100 nếu: gần mục tiêu, hoặc có ít nhất 2-3 macro gần mục tiêu, hoặc có thể điều chỉnh dễ dàng\n")
        prompt_parts.append("   - Cho điểm 70-80 nếu: có một số sai lệch nhưng vẫn hợp lý, hoặc có ít nhất 1 macro gần mục tiêu\n")
        prompt_parts.append("   - Cho điểm 60-70 nếu: có sai lệch nhưng không quá nghiêm trọng, vẫn có điểm tích cực\n")
        prompt_parts.append("   - Chỉ cho điểm <60 nếu: sai lệch rất nghiêm trọng (ví dụ: calo gấp đôi, protein <50% mục tiêu)\n")
        prompt_parts.append("   - **Lưu ý**: Nếu plan có cấu trúc rõ ràng và có thể điều chỉnh, cho điểm từ 70 trở lên\n\n")
        prompt_parts.append("2. **Variety (Đa dạng)**:\n")
        prompt_parts.append("   - Cho điểm 80-100 nếu: có sự đa dạng rõ ràng, hoặc có ít nhất 2-3 món khác nhau\n")
        prompt_parts.append("   - Cho điểm 70-80 nếu: có sự thay đổi giữa các bữa, hoặc có ít nhất 2 món khác nhau\n")
        prompt_parts.append("   - Cho điểm 60-70 nếu: có một số lặp lại nhưng vẫn có sự khác biệt\n")
        prompt_parts.append("   - Chỉ cho điểm <60 nếu: hoàn toàn giống nhau và không có sự đa dạng nào\n")
        prompt_parts.append("   - **Lưu ý**: Món ăn quen thuộc, dễ ăn cũng là điểm tích cực - cho điểm từ 70 trở lên\n\n")
        prompt_parts.append("3. **Balance (Cân bằng)**:\n")
        prompt_parts.append("   - Cho điểm 80-100 nếu: phân bổ hợp lý, hoặc có cấu trúc rõ ràng với 3 bữa\n")
        prompt_parts.append("   - Cho điểm 70-80 nếu: có cấu trúc cơ bản, hoặc có sự phân bổ (dù không hoàn hảo)\n")
        prompt_parts.append("   - Cho điểm 60-70 nếu: có một số lệch nhưng vẫn có thể chấp nhận\n")
        prompt_parts.append("   - Chỉ cho điểm <60 nếu: hoàn toàn mất cân bằng nghiêm trọng\n")
        prompt_parts.append("   - **Lưu ý**: Mỗi người có thói quen khác nhau - nếu có cấu trúc cơ bản, cho điểm từ 70 trở lên\n\n")
        prompt_parts.append("4. **Feasibility (Tính khả thi)**:\n")
        prompt_parts.append("   - Cho điểm 80-100 nếu: dễ thực hiện, phù hợp với thói quen, hoặc các món quen thuộc\n")
        prompt_parts.append("   - Cho điểm 70-80 nếu: có thể thực hiện được, hoặc có một số thách thức nhỏ\n")
        prompt_parts.append("   - Cho điểm 60-70 nếu: có thách thức nhưng vẫn có thể làm được\n")
        prompt_parts.append("   - Chỉ cho điểm <60 nếu: hoàn toàn không thực tế\n")
        prompt_parts.append("   - **Lưu ý**: Món ăn quen thuộc, dễ tìm mua là điểm tích cực lớn - cho điểm từ 75 trở lên\n\n")
        prompt_parts.append("**Overall Score**: Tính trung bình của 4 tiêu chí trên.\n")
        prompt_parts.append("- **Mục tiêu**: Đa số plans nên đạt 70-85 điểm (Good to Excellent)\n")
        prompt_parts.append("- **Chỉ cho điểm <70** khi thực sự có vấn đề nghiêm trọng\n")
        prompt_parts.append("- **Tập trung vào điểm mạnh** và ghi nhận những gì plan làm được tốt\n\n")
        prompt_parts.append("=== ĐỊNH DẠNG KẾT QUẢ ===\n\n")
        prompt_parts.append("Hãy trả về JSON với format sau (chỉ trả về JSON, không có text khác):\n\n")
        prompt_parts.append("{\n")
        prompt_parts.append('    "results": [\n')
        prompt_parts.append("        {\n")
        prompt_parts.append('            "plan_index": 1,\n')
        prompt_parts.append('            "overall_score": <float 0-100>,\n')
        prompt_parts.append('            "nutrition_score": <float 0-100>,\n')
        prompt_parts.append('            "variety_score": <float 0-100>,\n')
        prompt_parts.append('            "balance_score": <float 0-100>,\n')
        prompt_parts.append('            "feasibility_score": <float 0-100>,\n')
        prompt_parts.append('            "feedback": "<nhận xét tổng quan bằng tiếng Việt, 2-3 câu>",\n')
        prompt_parts.append('            "strengths": [\n')
        prompt_parts.append('                "<điểm mạnh 1>",\n')
        prompt_parts.append('                "<điểm mạnh 2>",\n')
        prompt_parts.append('                "<điểm mạnh 3>"\n')
        prompt_parts.append("            ],\n")
        prompt_parts.append('            "suggestions": [\n')
        prompt_parts.append('                "<gợi ý cải thiện 1>",\n')
        prompt_parts.append('                "<gợi ý cải thiện 2>",\n')
        prompt_parts.append('                "<gợi ý cải thiện 3>"\n')
        prompt_parts.append("            ]\n")
        prompt_parts.append("        },\n")
        prompt_parts.append("        // ... lặp lại cho từng meal plan\n")
        prompt_parts.append("    ]\n")
        prompt_parts.append("}\n\n")
        prompt_parts.append("Lưu ý:\n")
        prompt_parts.append("- Tất cả scores phải là số float từ 0-100\n")
        prompt_parts.append("- Feedback, strengths, suggestions phải bằng tiếng Việt\n")
        prompt_parts.append("- Chỉ trả về JSON, không có markdown code block hoặc text khác\n")
        prompt_parts.append(f"- Phải đánh giá đủ {len(meal_plans)} meal plans\n")
        prompt_parts.append("- Hãy đánh giá một cách tích cực và khuyến khích, tập trung vào điểm mạnh\n")
        prompt_parts.append("- Suggestions nên mang tính xây dựng và nhẹ nhàng, không quá chỉ trích\n")
        
        return "".join(prompt_parts)
    
    def _call_llm(
        self,
        prompt: str
    ) -> Dict[str, Any]:
        """
        Gọi OpenRouter API để lấy kết quả đánh giá.
        
        Args:
            prompt: Prompt string
            
        Returns:
            Dictionary với kết quả từ LLM
        """
        response_text = ""
        try:
            # Prepare request to OpenRouter API
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://github.com/meal-agent",  # Optional: for tracking
                "X-Title": "Meal Agent Evaluation",  # Optional: for tracking
            }
            
            payload = {
                "model": self.model_name,
                "messages": [
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                "temperature": 0.5,  # Tăng lên một chút để có sự đa dạng nhưng vẫn tích cực
                "max_tokens": 32000,  # Tăng lên để xử lý nhiều meal plans (OpenRouter supports up to 32k)
            }
            
            # Make API request
            response = requests.post(
                self.api_url,
                headers=headers,
                json=payload,
                timeout=120  # 2 minutes timeout
            )
            
            # Check for errors and show detailed error message
            if response.status_code != 200:
                error_detail = ""
                try:
                    error_data = response.json()
                    error_detail = f"\nError details: {json.dumps(error_data, indent=2)}"
                except:
                    error_detail = f"\nResponse text: {response.text[:1000]}"
                
                raise requests.exceptions.HTTPError(
                    f"HTTP {response.status_code}: {response.reason}{error_detail}"
                )
            
            # Parse response
            response_data = response.json()
            
            # Extract text from response
            if "choices" in response_data and len(response_data["choices"]) > 0:
                response_text = response_data["choices"][0]["message"]["content"]
            else:
                raise ValueError(f"Unexpected response format: {response_data}")
            
            # Parse JSON response
            # Remove markdown code blocks if present
            response_text = response_text.strip()
            if response_text.startswith("```json"):
                response_text = response_text[7:]
            elif response_text.startswith("```"):
                response_text = response_text[3:]
            if response_text.endswith("```"):
                response_text = response_text[:-3]
            response_text = response_text.strip()
            
            result = json.loads(response_text)
            return result
            
        except requests.exceptions.HTTPError as e:
            error_msg = str(e)
            if hasattr(e, 'response') and hasattr(e.response, 'text'):
                error_msg += f"\nResponse body: {e.response.text[:1000]}"
            raise RuntimeError(f"Error calling OpenRouter API: {error_msg}")
        except requests.exceptions.RequestException as e:
            error_msg = f"Error calling OpenRouter API: {e}"
            if 'response_text' in locals() and response_text:
                error_msg += f"\nResponse text: {response_text[:500]}"
            raise RuntimeError(error_msg)
        except json.JSONDecodeError as e:
            # Try to fix common JSON issues
            error_msg = f"Failed to parse LLM response as JSON: {e}\n"
            error_msg += f"Response length: {len(response_text)} characters\n"
            error_msg += f"Response preview (first 1000 chars): {response_text[:1000]}\n"
            if len(response_text) > 1000:
                error_msg += f"Response preview (last 1000 chars): {response_text[-1000:]}\n"
            
            # Try to extract partial JSON if response was truncated
            if '"results"' in response_text:
                try:
                    start_idx = response_text.find('"results"')
                    partial_json = response_text[start_idx:]
                    if not partial_json.rstrip().endswith('}'):
                        open_braces = partial_json.count('{')
                        close_braces = partial_json.count('}')
                        missing = open_braces - close_braces
                        if missing > 0:
                            partial_json += '}' * missing
                            if '"results":' in partial_json:
                                partial_json = '{"results": ' + partial_json.split('"results":', 1)[1]
                            result = json.loads(partial_json)
                            error_msg += "\n⚠️  Response was truncated, but partial results extracted."
                            return result
                except (json.JSONDecodeError, ValueError):
                    pass
            
            raise ValueError(error_msg)
        except Exception as e:
            error_msg = f"Error calling LLM API: {e}"
            if 'response_text' in locals() and response_text:
                error_msg += f"\nResponse text: {response_text[:500]}"
            raise RuntimeError(error_msg)
    
    def evaluate(
        self,
        meal_plan: Dict[str, Any],
        user_profile: Dict[str, Any]
    ) -> LLMJudgeResult:
        """
        Đánh giá một meal plan sử dụng LLM.
        
        Args:
            meal_plan: Meal plan dictionary
            user_profile: User profile dictionary
            
        Returns:
            LLMJudgeResult object
        """
        # Create prompt
        prompt = self._create_evaluation_prompt(meal_plan, user_profile)
        
        # Call LLM
        llm_result = self._call_llm(prompt)
        
        # Extract and validate scores
        overall_score = float(llm_result.get("overall_score", 0))
        nutrition_score = float(llm_result.get("nutrition_score", 0))
        variety_score = float(llm_result.get("variety_score", 0))
        balance_score = float(llm_result.get("balance_score", 0))
        feasibility_score = float(llm_result.get("feasibility_score", 0))
        
        # Clamp scores to 0-100
        overall_score = max(0, min(100, overall_score))
        nutrition_score = max(0, min(100, nutrition_score))
        variety_score = max(0, min(100, variety_score))
        balance_score = max(0, min(100, balance_score))
        feasibility_score = max(0, min(100, feasibility_score))
        
        # Extract feedback
        feedback = llm_result.get("feedback", "")
        strengths = llm_result.get("strengths", [])
        suggestions = llm_result.get("suggestions", [])
        
        # Ensure lists
        if not isinstance(strengths, list):
            strengths = [strengths] if strengths else []
        if not isinstance(suggestions, list):
            suggestions = [suggestions] if suggestions else []
        
        return LLMJudgeResult(
            overall_score=overall_score,
            nutrition_score=nutrition_score,
            variety_score=variety_score,
            balance_score=balance_score,
            feasibility_score=feasibility_score,
            feedback=feedback,
            strengths=strengths,
            suggestions=suggestions,
        )
    
    def _expand_week_plans_to_days(
        self,
        meal_plans: List[Dict[str, Any]],
        user_profiles: List[Dict[str, Any]]
    ) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[int]]:
        """
        Expand week plans thành các day plans riêng biệt.
        
        Args:
            meal_plans: List of meal plan dictionaries
            user_profiles: List of user profile dictionaries
        
        Returns:
            Tuple of (expanded_meal_plans, expanded_user_profiles, original_indices)
        """
        expanded_plans = []
        expanded_profiles = []
        original_indices = []  # Map từ expanded index về original index
        
        for i, (plan, profile) in enumerate(zip(meal_plans, user_profiles)):
            plan_type = plan.get("plan_type", "day")
            
            if plan_type == "week":
                days = plan.get("days", {})
                if days:
                    for day_key, day_data in days.items():
                        day_plan = {
                            "plan_id": f"{plan.get('plan_id', 'unknown')}_day_{day_key}",
                            "user_id": plan.get("user_id"),
                            "plan_type": "day",
                            "start_date": day_data.get("date", day_key),
                            "created_at": plan.get("created_at"),
                            "meals": day_data.get("meals", {}),
                            "total_macros": self._calculate_day_macros(day_data.get("meals", {})),
                            "source": plan.get("source", "MealPlan"),
                            "original_plan_id": plan.get("plan_id"),
                            "day_key": day_key,
                        }
                        expanded_plans.append(day_plan)
                        expanded_profiles.append(profile)
                        original_indices.append(i)
                else:
                    # Week plan không có days structure: bỏ qua
                    logger.warning(
                        f"Week plan {plan.get('plan_id')} không có 'days' structure, bỏ qua"
                    )
            else:
                expanded_plans.append(plan)
                expanded_profiles.append(profile)
                original_indices.append(i)
        
        return expanded_plans, expanded_profiles, original_indices
    
    def _calculate_day_macros(self, meals: Dict[str, Any]) -> Dict[str, float]:
        """Tính tổng macros từ meals dict của một ngày."""
        total_macros = {"kcal": 0.0, "protein_g": 0.0, "fat_g": 0.0, "carb_g": 0.0}
        
        for meal_type, meal_data in meals.items():
            meal_macros = meal_data.get("macros", {})
            if isinstance(meal_macros, dict):
                total_macros["kcal"] += float(meal_macros.get("kcal", 0.0))
                total_macros["protein_g"] += float(meal_macros.get("protein_g", 0.0))
                total_macros["fat_g"] += float(meal_macros.get("fat_g", 0.0))
                total_macros["carb_g"] += float(meal_macros.get("carb_g", 0.0))
        
        return total_macros
    
    def evaluate_batch(
        self,
        meal_plans: List[Dict[str, Any]],
        user_profiles: List[Dict[str, Any]],
        batch_size: int = 15  # Chia nhỏ batch để tránh response quá dài
    ) -> List[LLMJudgeResult]:
        """
        Đánh giá nhiều meal plans, tự động chia nhỏ batch nếu cần.
        Week plans sẽ được expand thành các day plans riêng biệt và đánh giá từng ngày.
        
        Args:
            meal_plans: List of meal plan dictionaries
            user_profiles: List of user profile dictionaries (must match meal_plans length)
            batch_size: Số lượng plans mỗi batch (mặc định 15 để tránh response quá dài)
        
        Returns:
            List of LLMJudgeResult objects
            - Mỗi day plan (bao gồm cả day plans từ week plans) sẽ có 1 result riêng
        """
        if len(meal_plans) != len(user_profiles):
            raise ValueError(
                f"meal_plans ({len(meal_plans)}) and user_profiles "
                f"({len(user_profiles)}) must have the same length"
            )
        
        if not meal_plans:
            return []
        
        # Expand week plans thành day plans
        expanded_plans, expanded_profiles, original_indices = self._expand_week_plans_to_days(
            meal_plans, user_profiles
        )
        
        # Validate: Tất cả expanded plans phải có plan_type="day"
        for plan in expanded_plans:
            if plan.get("plan_type") == "week":
                logger.error(
                    f"Expanded plan still has plan_type='week'! "
                    f"Plan ID: {plan.get('plan_id')}. Forcing to 'day'."
                )
                plan["plan_type"] = "day"
        
        if len(expanded_plans) > len(meal_plans):
            print(f"   📅 Expanded {len(meal_plans)} plans to {len(expanded_plans)} day plans (week plans split into days)")
        
        # Đánh giá expanded plans
        if len(expanded_plans) <= batch_size:
            expanded_results = self._evaluate_single_batch(expanded_plans, expanded_profiles)
        else:
            expanded_results = self._evaluate_batch_with_splitting(expanded_plans, expanded_profiles, batch_size)
        
        return expanded_results
    
    def _evaluate_batch_with_splitting(
        self,
        meal_plans: List[Dict[str, Any]],
        user_profiles: List[Dict[str, Any]],
        batch_size: int = 15
    ) -> List[LLMJudgeResult]:
        """Chia nhỏ thành nhiều batches và đánh giá."""
        all_results = []
        total_batches = (len(meal_plans) + batch_size - 1) // batch_size
        
        print(f"   📦 Chia thành {total_batches} batches (mỗi batch tối đa {batch_size} plans)...")
        
        for batch_idx in range(total_batches):
            start_idx = batch_idx * batch_size
            end_idx = min(start_idx + batch_size, len(meal_plans))
            
            batch_plans = meal_plans[start_idx:end_idx]
            batch_profiles = user_profiles[start_idx:end_idx]
            
            print(f"   ⏳ Processing batch {batch_idx + 1}/{total_batches} (plans {start_idx + 1}-{end_idx})...")
            
            try:
                batch_results = self._evaluate_single_batch(batch_plans, batch_profiles)
                all_results.extend(batch_results)
            except Exception as e:
                print(f"   ⚠️  Error in batch {batch_idx + 1}: {e}")
                # Tạo kết quả mặc định cho batch này
                for _ in batch_plans:
                    all_results.append(LLMJudgeResult(
                        overall_score=0.0,
                        nutrition_score=0.0,
                        variety_score=0.0,
                        balance_score=0.0,
                        feasibility_score=0.0,
                        feedback=f"Lỗi khi đánh giá: {str(e)[:100]}",
                        strengths=[],
                        suggestions=[],
                    ))
        
        return all_results
    
    def _evaluate_single_batch(
        self,
        meal_plans: List[Dict[str, Any]],
        user_profiles: List[Dict[str, Any]]
    ) -> List[LLMJudgeResult]:
        """
        Đánh giá một batch meal plans (helper method).
        
        Args:
            meal_plans: List of meal plan dictionaries
            user_profiles: List of user profile dictionaries
        
        Returns:
            List of LLMJudgeResult objects
        """
        # Tạo prompt cho batch meal plans
        prompt = self._create_batch_evaluation_prompt(meal_plans, user_profiles)
        
        # Gọi LLM
        llm_result = self._call_llm(prompt)
        
        # Parse kết quả
        results = []
        if "results" in llm_result:
            # Kết quả từ batch evaluation
            batch_results = llm_result["results"]
            for i, result_data in enumerate(batch_results):
                # Đảm bảo có đủ kết quả
                if i < len(meal_plans):
                    result = self._parse_llm_result(result_data)
                    results.append(result)
            
            # Nếu thiếu kết quả, tạo kết quả mặc định
            while len(results) < len(meal_plans):
                results.append(LLMJudgeResult(
                    overall_score=0.0,
                    nutrition_score=0.0,
                    variety_score=0.0,
                    balance_score=0.0,
                    feasibility_score=0.0,
                    feedback="Không có đánh giá (thiếu kết quả từ LLM)",
                    strengths=[],
                    suggestions=[],
                ))
        else:
            # Fallback: nếu format không đúng, đánh giá từng cái một
            print(f"   ⚠️  Unexpected response format, falling back to individual evaluation...")
            for meal_plan, user_profile in zip(meal_plans, user_profiles):
                result = self.evaluate(meal_plan, user_profile)
                results.append(result)
        
        return results
    
    def _parse_llm_result(
        self,
        result_data: Dict[str, Any]
    ) -> LLMJudgeResult:
        """
        Parse kết quả từ LLM thành LLMJudgeResult.
        
        Args:
            result_data: Dictionary với kết quả từ LLM
            
        Returns:
            LLMJudgeResult object
        """
        # Extract and validate scores
        overall_score = float(result_data.get("overall_score", 0))
        nutrition_score = float(result_data.get("nutrition_score", 0))
        variety_score = float(result_data.get("variety_score", 0))
        balance_score = float(result_data.get("balance_score", 0))
        feasibility_score = float(result_data.get("feasibility_score", 0))
        
        # Clamp scores to 0-100
        overall_score = max(0, min(100, overall_score))
        nutrition_score = max(0, min(100, nutrition_score))
        variety_score = max(0, min(100, variety_score))
        balance_score = max(0, min(100, balance_score))
        feasibility_score = max(0, min(100, feasibility_score))
        
        # Extract feedback
        feedback = result_data.get("feedback", "")
        strengths = result_data.get("strengths", [])
        suggestions = result_data.get("suggestions", [])
        
        # Ensure lists
        if not isinstance(strengths, list):
            strengths = [strengths] if strengths else []
        if not isinstance(suggestions, list):
            suggestions = [suggestions] if suggestions else []
        
        return LLMJudgeResult(
            overall_score=overall_score,
            nutrition_score=nutrition_score,
            variety_score=variety_score,
            balance_score=balance_score,
            feasibility_score=feasibility_score,
            feedback=feedback,
            strengths=strengths,
            suggestions=suggestions,
        )
    
    def aggregate_results(
        self,
        results: List[LLMJudgeResult]
    ) -> Dict[str, Any]:
        """
        Tổng hợp kết quả từ nhiều evaluations.
        
        Args:
            results: List of LLMJudgeResult objects
        
        Returns:
            Dictionary với aggregated statistics
        """
        if not results:
            return {}
        
        import numpy as np
        
        # Aggregate scores
        overall_scores = [r.overall_score for r in results]
        nutrition_scores = [r.nutrition_score for r in results]
        variety_scores = [r.variety_score for r in results]
        balance_scores = [r.balance_score for r in results]
        feasibility_scores = [r.feasibility_score for r in results]
        
        return {
            "count": len(results),
            "overall_score": {
                "mean": float(np.mean(overall_scores)),
                "median": float(np.median(overall_scores)),
                "std": float(np.std(overall_scores)),
                "min": float(np.min(overall_scores)),
                "max": float(np.max(overall_scores)),
                "p25": float(np.percentile(overall_scores, 25)),
                "p75": float(np.percentile(overall_scores, 75)),
            },
            "nutrition_score": {
                "mean": float(np.mean(nutrition_scores)),
                "median": float(np.median(nutrition_scores)),
                "std": float(np.std(nutrition_scores)),
                "min": float(np.min(nutrition_scores)),
                "max": float(np.max(nutrition_scores)),
                "p25": float(np.percentile(nutrition_scores, 25)),
                "p75": float(np.percentile(nutrition_scores, 75)),
            },
            "variety_score": {
                "mean": float(np.mean(variety_scores)),
                "median": float(np.median(variety_scores)),
                "std": float(np.std(variety_scores)),
                "min": float(np.min(variety_scores)),
                "max": float(np.max(variety_scores)),
                "p25": float(np.percentile(variety_scores, 25)),
                "p75": float(np.percentile(variety_scores, 75)),
            },
            "balance_score": {
                "mean": float(np.mean(balance_scores)),
                "median": float(np.median(balance_scores)),
                "std": float(np.std(balance_scores)),
                "min": float(np.min(balance_scores)),
                "max": float(np.max(balance_scores)),
                "p25": float(np.percentile(balance_scores, 25)),
                "p75": float(np.percentile(balance_scores, 75)),
            },
            "feasibility_score": {
                "mean": float(np.mean(feasibility_scores)),
                "median": float(np.median(feasibility_scores)),
                "std": float(np.std(feasibility_scores)),
                "min": float(np.min(feasibility_scores)),
                "max": float(np.max(feasibility_scores)),
                "p25": float(np.percentile(feasibility_scores, 25)),
                "p75": float(np.percentile(feasibility_scores, 75)),
            },
        }

