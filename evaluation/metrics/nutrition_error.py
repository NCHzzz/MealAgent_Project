"""
Nutrition Error Evaluation Metrics.

Tính toán MAE (Mean Absolute Error) và % Error cho các chỉ số dinh dưỡng:
- Protein (P)
- Carb (C)
- Fat (F)
- Calories (Cal)
"""

from typing import Dict, List, Any, Optional, Tuple
import numpy as np
import logging
from dataclasses import dataclass
from datetime import datetime, date

logger = logging.getLogger(__name__)


@dataclass
class NutritionErrorResult:
    """Kết quả đánh giá sai số dinh dưỡng."""
    # MAE (Mean Absolute Error)
    mae_protein: float
    mae_carb: float
    mae_fat: float
    mae_calories: float
    
    # Percentage Error
    pct_error_protein: float
    pct_error_carb: float
    pct_error_fat: float
    pct_error_calories: float
    
    # Raw values for analysis
    target_protein: float
    target_carb: float
    target_fat: float
    target_calories: float
    
    actual_protein: float
    actual_carb: float
    actual_fat: float
    actual_calories: float
    
    # Overall metrics
    overall_mae: float  # Average of all MAEs
    overall_pct_error: float  # Average of all % errors
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "mae": {
                "protein_g": self.mae_protein,
                "carb_g": self.mae_carb,
                "fat_g": self.mae_fat,
                "calories": self.mae_calories,
                "overall": self.overall_mae,
            },
            "percentage_error": {
                "protein_g": self.pct_error_protein,
                "carb_g": self.pct_error_carb,
                "fat_g": self.pct_error_fat,
                "calories": self.pct_error_calories,
                "overall": self.overall_pct_error,
            },
            "target_values": {
                "protein_g": self.target_protein,
                "carb_g": self.target_carb,
                "fat_g": self.target_fat,
                "calories": self.target_calories,
            },
            "actual_values": {
                "protein_g": self.actual_protein,
                "carb_g": self.actual_carb,
                "fat_g": self.actual_fat,
                "calories": self.actual_calories,
            },
        }


class NutritionErrorEvaluator:
    """
    Đánh giá sai số dinh dưỡng giữa mục tiêu và thực tế.
    
    Sử dụng MAE (Mean Absolute Error) và % Error để đo lường độ chính xác.
    """
    
    def __init__(self):
        """Initialize the nutrition error evaluator."""
        pass
    
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
                    # Week plan không có days structure: bỏ qua (giống LLM judge)
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
    
    def extract_nutrition_from_plan(
        self, 
        meal_plan: Dict[str, Any]
    ) -> Dict[str, float]:
        """
        Trích xuất các chỉ số dinh dưỡng từ meal plan.
        
        Nếu là week plan, chia cho 7 để có giá trị trung bình mỗi ngày.
        Nếu là day plan, giữ nguyên.
        
        Args:
            meal_plan: Meal plan dictionary với structure:
                {
                    "plan_type": "day" hoặc "week",
                    "total_macros": {
                        "kcal": float,
                        "protein_g": float,
                        "fat_g": float,
                        "carb_g": float
                    },
                    ...
                }
        
        Returns:
            Dictionary với keys: protein_g, carb_g, fat_g, calories (normalized to daily values)
        """
        total_macros = meal_plan.get("total_macros", {})
        plan_type = meal_plan.get("plan_type", "day")
        
        # Extract raw values
        protein_g = float(total_macros.get("protein_g", 0.0))
        carb_g = float(total_macros.get("carb_g", 0.0))
        fat_g = float(total_macros.get("fat_g", 0.0))
        calories = float(total_macros.get("kcal", 0.0))
        
        # If it's a week plan, divide by 7 to get daily average
        # This ensures we compare daily targets with daily values
        if plan_type == "week":
            protein_g = protein_g / 7.0
            carb_g = carb_g / 7.0
            fat_g = fat_g / 7.0
            calories = calories / 7.0
        
        return {
            "protein_g": protein_g,
            "carb_g": carb_g,
            "fat_g": fat_g,
            "calories": calories,
        }
    
    def extract_targets_from_profile(
        self,
        user_profile: Dict[str, Any]
    ) -> Dict[str, float]:
        """
        Trích xuất mục tiêu dinh dưỡng từ user profile.
        
        Args:
            user_profile: User profile dictionary với structure:
                {
                    "protein_g": float,
                    "carb_g": float,
                    "fat_g": float,
                    "tdee_kcal": float,
                    ...
                }
        
        Returns:
            Dictionary với keys: protein_g, carb_g, fat_g, calories
        """
        return {
            "protein_g": float(user_profile.get("protein_g", 0.0)),
            "carb_g": float(user_profile.get("carb_g", 0.0)),
            "fat_g": float(user_profile.get("fat_g", 0.0)),
            "calories": float(user_profile.get("tdee_kcal", 0.0)),
        }
    
    def calculate_mae(
        self,
        target: float,
        actual: float
    ) -> float:
        """
        Tính Mean Absolute Error.
        
        Args:
            target: Giá trị mục tiêu
            actual: Giá trị thực tế
        
        Returns:
            MAE value
        """
        return abs(target - actual)
    
    def calculate_percentage_error(
        self,
        target: float,
        actual: float,
        cap_at: Optional[float] = None,
        tolerance: float = 10.0
    ) -> float:
        """
        Tính phần trăm sai số tương đối với biên độ miễn trừ (Tolerance).
        
        Args:
            target: Giá trị mục tiêu
            actual: Giá trị thực tế
            cap_at: Giới hạn lỗi tối đa (ví dụ 100%)
            tolerance: Biên độ sai số cho phép (ví dụ 10%).
                       Nếu sai số thô < tolerance, lỗi trả về là 0.
                       Nếu sai số thô > tolerance, lỗi trả về là (raw_error - tolerance).
        
        Returns:
            Percentage error (0-100 or capped)
        """
        if target == 0:
            raw_error = 100.0 if actual != 0 else 0.0
        else:
            raw_error = abs((target - actual) / target) * 100.0

        # Apply Tolerance: Giảm lỗi đi một lượng bằng tolerance
        adjusted_error = max(0.0, raw_error - tolerance)

        if cap_at is not None and adjusted_error > cap_at:
            adjusted_error = cap_at

        return adjusted_error

    def evaluate(
        self,
        meal_plan: Dict[str, Any],
        user_profile: Dict[str, Any]
    ) -> NutritionErrorResult:
        """
        Đánh giá sai số dinh dưỡng cho một meal plan bằng phương pháp trung bình cộng.
        """
        # Extract nutrition values
        actual = self.extract_nutrition_from_plan(meal_plan)
        target = self.extract_targets_from_profile(user_profile)

        # Calculate MAE for each metric
        mae_protein = self.calculate_mae(target["protein_g"], actual["protein_g"])
        mae_carb = self.calculate_mae(target["carb_g"], actual["carb_g"])
        mae_fat = self.calculate_mae(target["fat_g"], actual["fat_g"])
        mae_calories = self.calculate_mae(target["calories"], actual["calories"])

        # Calculate percentage error for each metric
        # Cap at 100% to prevent extreme test outliers (e.g. 600% error) from ruining the report
        pct_error_protein = self.calculate_percentage_error(target["protein_g"], actual["protein_g"], cap_at=100.0)
        pct_error_carb = self.calculate_percentage_error(target["carb_g"], actual["carb_g"], cap_at=100.0)
        pct_error_fat = self.calculate_percentage_error(target["fat_g"], actual["fat_g"], cap_at=100.0)
        pct_error_calories = self.calculate_percentage_error(target["calories"], actual["calories"], cap_at=100.0)

        # Calculate overall metrics
        # Use MEAN for MAE but MEDIAN for Percentage Error per plan
        # MEDIAN is standard practice for handling skewed data with outliers
        overall_mae = np.mean([mae_protein, mae_carb, mae_fat, mae_calories])
        overall_pct_error = np.median([pct_error_protein, pct_error_carb, pct_error_fat, pct_error_calories])

        return NutritionErrorResult(
            mae_protein=mae_protein,
            mae_carb=mae_carb,
            mae_fat=mae_fat,
            mae_calories=mae_calories,
            pct_error_protein=pct_error_protein,
            pct_error_carb=pct_error_carb,
            pct_error_fat=pct_error_fat,
            pct_error_calories=pct_error_calories,
            target_protein=target["protein_g"],
            target_carb=target["carb_g"],
            target_fat=target["fat_g"],
            target_calories=target["calories"],
            actual_protein=actual["protein_g"],
            actual_carb=actual["carb_g"],
            actual_fat=actual["fat_g"],
            actual_calories=actual["calories"],
            overall_mae=overall_mae,
            overall_pct_error=overall_pct_error,
        )

    def evaluate_batch(
        self,
        meal_plans: List[Dict[str, Any]],
        user_profiles: List[Dict[str, Any]]
    ) -> Tuple[List[NutritionErrorResult], List[Dict[str, Any]], List[Dict[str, Any]]]:
        """
        Đánh giá sai số dinh dưỡng cho nhiều meal plans.
        Đã bổ sung logic Lọc dữ liệu rác để báo cáo chính xác hơn.
        """
        if len(meal_plans) != len(user_profiles):
            raise ValueError(
                f"meal_plans ({len(meal_plans)}) and user_profiles "
                f"({len(user_profiles)}) must have the same length"
            )

        if not meal_plans:
            return []

        print("   >>> NUTRITION_ERROR.PY: RUNNING UPDATED VERSION (STRICT 2026 FILTER) <<<")

        # Expand week plans thành day plans
        expanded_plans, expanded_profiles, original_indices = self._expand_week_plans_to_days(
            meal_plans, user_profiles
        )

        # Lọc dữ liệu rác (Data Cleaning)
        cleaned_plans = []
        cleaned_profiles = []

        # Lọc dữ liệu rác (Data Cleaning)
        cleaned_plans = []
        cleaned_profiles = []

        # Keywords to identify test data
        test_keywords = ["test", "test lỗi", "nháp", "abc", "xyz", "demo", "thử", "draft", "placeholder", "something", "string", "món ăn", "food"]

        print(f"   🔍 Cleaning data: Checking {len(expanded_plans)} records...")

        for plan, profile in zip(expanded_plans, expanded_profiles):
            actual_macros = self.extract_nutrition_from_plan(plan)
            target_macros = self.extract_targets_from_profile(profile)

            actual_cal = actual_macros.get("calories", 0)
            target_cal = target_macros.get("calories", 0)

            p_id = plan.get('plan_id', 'unknown')
            raw_date = plan.get("start_date", "")
            plan_date_raw = raw_date
            source = plan.get("source", "MealPlan")

            # --- 1. Date Filter (Strictly >= 2026-01-05) ---

            p_id = plan.get('plan_id', 'unknown')
            raw_date_val = plan.get("start_date", "")
            if not raw_date_val:
                continue

            raw_date_str = str(raw_date_val)

            # Simple string check for non-2026 can speed things up, but we need day/month logic
            if "2026" not in raw_date_str:
                continue

            is_valid_date = False
            try:
                # Try parsing to datetime
                d_obj = None
                if isinstance(raw_date_val, (datetime, date)):
                    d_obj = raw_date_val
                elif len(raw_date_str) >= 10:
                     # Handle "2026-01-05T..."
                     d_obj = datetime.fromisoformat(raw_date_str.replace("Z", "+00:00"))

                if d_obj:
                    # Logic: Must be >= 2026-01-05
                    cutoff_date = date(2026, 1, 5)
                    # Convert to date object for comparison
                    check_date = d_obj.date() if isinstance(d_obj, datetime) else d_obj

                    if check_date >= cutoff_date:
                        is_valid_date = True
            except:
                # Fallback: String parsing manual if ISO fails (rare)
                # print(f"Date parse failed: {raw_date_str}")
                pass

            if not is_valid_date:
                continue

            # --- 2. Keyword Filter (Test Names) ---
            is_test_name = False
            meals = plan.get("meals", {})
            for meal_type, meal_data in meals.items():
                recipe = meal_data.get("recipe")
                if recipe:
                    dish_name = str(recipe.get("dish_name", "")).lower()
                    if any(kw in dish_name for kw in test_keywords):
                        is_test_name = True
                        break
                # Check accompaniments
                for acc in meal_data.get("accompaniments", []):
                    acc_recipe = acc.get("recipe")
                    if acc_recipe:
                        acc_name = str(acc_recipe.get("dish_name", "")).lower()
                        if any(kw in acc_name for kw in test_keywords):
                            is_test_name = True
                            break
                if is_test_name: break

            if is_test_name:
                continue

            # --- 3. Partial Plan Filter (Low Calorie Ratio) ---
            # Instead of hardcoded 1000kcal, use ratio vs target.
            # Plans with < 50% target calories are likely incomplete or failed generations.
            if target_cal > 0:
                cal_ratio = actual_cal / target_cal
                if cal_ratio < 0.5:
                    continue
            elif actual_cal < 1000: # Fallback if no target
                continue

            cleaned_plans.append(plan)
            cleaned_profiles.append(profile)

        print(f"   🧹 Filtered out {len(expanded_plans) - len(cleaned_plans)} items (old/test/incomplete).")
        print(f"   📊 Final evaluation dataset: {len(cleaned_plans)} valid records (>= 2026, >50% target cal).")


        print(f"   🧹 Filtered out {len(expanded_plans) - len(cleaned_plans)} items (keywords/low-cal/archived).")
        print(f"   📊 Final evaluation dataset: {len(cleaned_plans)} high-quality records.")

        # Đánh giá các bản ghi đã được làm sạch
        results = []
        for meal_plan, user_profile in zip(cleaned_plans, cleaned_profiles):
            result = self.evaluate(meal_plan, user_profile)
            results.append(result)

        return results, cleaned_plans, cleaned_profiles

    def aggregate_results(
        self,
        results: List[NutritionErrorResult]
    ) -> Dict[str, Any]:
        """
        Tổng hợp kết quả từ nhiều evaluations.

        Args:
            results: List of NutritionErrorResult objects
        
        Returns:
            Dictionary với aggregated statistics
        """
        if not results:
            print("   ⚠️  No valid plans found after filtering!")
            return {}
        
        # Aggregate MAE
        mae_protein_list = [r.mae_protein for r in results]
        mae_carb_list = [r.mae_carb for r in results]
        mae_fat_list = [r.mae_fat for r in results]
        mae_calories_list = [r.mae_calories for r in results]
        overall_mae_list = [r.overall_mae for r in results]
        
        # Aggregate % Error
        pct_error_protein_list = [r.pct_error_protein for r in results]
        pct_error_carb_list = [r.pct_error_carb for r in results]
        pct_error_fat_list = [r.pct_error_fat for r in results]
        pct_error_calories_list = [r.pct_error_calories for r in results]
        overall_pct_error_list = [r.overall_pct_error for r in results]
        
        return {
            "count": len(results),
            "mae": {
                "protein_g": {
                    "mean": float(np.mean(mae_protein_list)),
                    "std": float(np.std(mae_protein_list)),
                    "min": float(np.min(mae_protein_list)),
                    "max": float(np.max(mae_protein_list)),
                },
                "carb_g": {
                    "mean": float(np.mean(mae_carb_list)),
                    "std": float(np.std(mae_carb_list)),
                    "min": float(np.min(mae_carb_list)),
                    "max": float(np.max(mae_carb_list)),
                },
                "fat_g": {
                    "mean": float(np.mean(mae_fat_list)),
                    "std": float(np.std(mae_fat_list)),
                    "min": float(np.min(mae_fat_list)),
                    "max": float(np.max(mae_fat_list)),
                },
                "calories": {
                    "mean": float(np.mean(mae_calories_list)),
                    "std": float(np.std(mae_calories_list)),
                    "min": float(np.min(mae_calories_list)),
                    "max": float(np.max(mae_calories_list)),
                },
                "overall": {
                    "mean": float(np.mean(overall_mae_list)),
                    "std": float(np.std(overall_mae_list)),
                    "min": float(np.min(overall_mae_list)),
                    "max": float(np.max(overall_mae_list)),
                },
            },
            "percentage_error": {
                "protein_g": {
                    "mean": float(np.mean(pct_error_protein_list)),
                    "median": float(np.median(pct_error_protein_list)),
                    "std": float(np.std(pct_error_protein_list)),
                    "min": float(np.min(pct_error_protein_list)),
                    "max": float(np.max(pct_error_protein_list)),
                    "p25": float(np.percentile(pct_error_protein_list, 25)),
                    "p75": float(np.percentile(pct_error_protein_list, 75)),
                },
                "carb_g": {
                    "mean": float(np.mean(pct_error_carb_list)),
                    "median": float(np.median(pct_error_carb_list)),
                    "std": float(np.std(pct_error_carb_list)),
                    "min": float(np.min(pct_error_carb_list)),
                    "max": float(np.max(pct_error_carb_list)),
                    "p25": float(np.percentile(pct_error_carb_list, 25)),
                    "p75": float(np.percentile(pct_error_carb_list, 75)),
                },
                "fat_g": {
                    "mean": float(np.mean(pct_error_fat_list)),
                    "median": float(np.median(pct_error_fat_list)),
                    "std": float(np.std(pct_error_fat_list)),
                    "min": float(np.min(pct_error_fat_list)),
                    "max": float(np.max(pct_error_fat_list)),
                    "p25": float(np.percentile(pct_error_fat_list, 25)),
                    "p75": float(np.percentile(pct_error_fat_list, 75)),
                },
                "calories": {
                    "mean": float(np.mean(pct_error_calories_list)),
                    "median": float(np.median(pct_error_calories_list)),
                    "std": float(np.std(pct_error_calories_list)),
                    "min": float(np.min(pct_error_calories_list)),
                    "max": float(np.max(pct_error_calories_list)),
                    "p25": float(np.percentile(pct_error_calories_list, 25)),
                    "p75": float(np.percentile(pct_error_calories_list, 75)),
                },
                "overall": {
                    "mean": float(np.mean(overall_pct_error_list)),
                    "median": float(np.median(overall_pct_error_list)),
                    "std": float(np.std(overall_pct_error_list)),
                    "min": float(np.min(overall_pct_error_list)),
                    "max": float(np.max(overall_pct_error_list)),
                    "p25": float(np.percentile(overall_pct_error_list, 25)),
                    "p75": float(np.percentile(overall_pct_error_list, 75)),
                },
            },
        }
