"""
Example usage of the MealAgent evaluation framework.

Script này minh họa cách sử dụng evaluation framework để đánh giá MealAgent.
"""

import os
import sys
from pathlib import Path

# Add parent directory to path to import MealAgent
sys.path.insert(0, str(Path(__file__).parent.parent))

from evaluation.runners.evaluation_runner import EvaluationRunner
from evaluation.test_cases.test_profiles import get_test_profiles
from evaluation.test_cases.test_scenarios import get_test_scenarios
from evaluation.utils.weaviate_data_loader import (
    load_evaluation_data_from_weaviate,
    get_all_user_ids_from_weaviate,
    create_client_manager,
)


def example_evaluation(use_weaviate: bool = False, user_ids: list = None):
    """
    Ví dụ chạy evaluation với meal plans.
    
    Args:
        use_weaviate: Nếu True, load dữ liệu từ Weaviate. Nếu False, dùng mock data.
        user_ids: List of user IDs để load từ Weaviate (nếu None và use_weaviate=True, sẽ lấy tất cả)
    
    Trong thực tế, bạn có thể:
    1. Load meal plans từ Weaviate (đã được tạo bởi MealAgent)
    2. Load user profiles từ Weaviate
    3. Chạy evaluation với dữ liệu thực tế
    """
    
    if use_weaviate:
        print("📥 Loading data from Weaviate...")
        try:
            client_manager = create_client_manager()
            if not client_manager.is_client:
                print("❌ Weaviate client not available. Falling back to mock data.")
                use_weaviate = False
            else:
                if user_ids is None:
                    # Lấy tất cả user IDs từ Weaviate
                    user_ids = get_all_user_ids_from_weaviate(client_manager, limit=10)
                    if not user_ids:
                        print("❌ No users found in Weaviate. Falling back to mock data.")
                        use_weaviate = False
                
                if use_weaviate:
                    meal_plans, user_profiles = load_evaluation_data_from_weaviate(
                        user_ids, client_manager, plan_type="day", use_latest=True
                    )
                    print(f"   Loaded {len(meal_plans)} meal plans and {len(user_profiles)} profiles")
                    
                    # Tạo user_queries từ scenarios (nếu có)
                    test_scenarios = get_test_scenarios()
                    user_queries = []
                    for profile in user_profiles:
                        user_id = profile.get("user_id")
                        scenario = next(
                            (s for s in test_scenarios if s.get("user_id") == user_id),
                            None
                        )
                        if scenario:
                            user_queries.append(scenario["query"])
                        else:
                            user_queries.append(f"Create a meal plan for user {user_id}")
        except Exception as e:
            print(f"❌ Error loading from Weaviate: {e}")
            print("   Falling back to mock data.")
            use_weaviate = False
    
    if not use_weaviate:
        print("📥 Using mock test data...")
        # Lấy test profiles và scenarios
        test_profiles = get_test_profiles()
        test_scenarios = get_test_scenarios()
        
        # NOTE: Đây chỉ là ví dụ với meal plans giả định
        meal_plans = []
        user_profiles = []
        user_queries = []
        
        for scenario in test_scenarios[:3]:  # Chỉ lấy 3 scenarios đầu
            user_id = scenario["user_id"]
            profile = next(p for p in test_profiles if p["user_id"] == user_id)
            
            # Tạo meal plan giả định (trong thực tế, gọi MealAgent)
            meal_plan = create_mock_meal_plan(profile)
            
            meal_plans.append(meal_plan)
            user_profiles.append(profile)
            user_queries.append(scenario["query"])
    
    # Khởi tạo evaluation runner
    # NOTE: Cần set GEMINI_API_KEY environment variable cho LLM judge
    runner = EvaluationRunner(
        results_dir="evaluation/results",
        gemini_api_key=os.getenv("GEMINI_API_KEY")
    )
    
    # Chạy tất cả evaluations
    results = runner.run_all_evaluations(
        meal_plans=meal_plans,
        user_profiles=user_profiles,
        user_queries=user_queries,
        reference_plans=None  # Optional: có thể cung cấp reference plans
    )
    
    # Lưu kết quả
    filepath = runner.save_results(results)
    print(f"\n✅ Evaluation completed! Results saved to: {filepath}")
    
    return results


def create_mock_meal_plan(user_profile: dict) -> dict:
    """
    Tạo meal plan giả định cho ví dụ.
    
    Trong thực tế, bạn sẽ gọi MealAgent tools để tạo meal plans thực tế.
    """
    # Đây chỉ là mock data - trong thực tế cần gọi MealAgent
    return {
        "plan_id": f"plan_{user_profile['user_id']}",
        "plan_type": "day",
        "meals": {
            "breakfast": {
                "meal_type": "breakfast",
                "recipe": {
                    "food_id": "recipe_001",
                    "dish_name": "Phở bò",
                    "macros_per_serving": {
                        "kcal": 450.0,
                        "protein_g": 30.0,
                        "fat_g": 15.0,
                        "carb_g": 50.0,
                    },
                },
                "servings": 1.0,
                "macros": {
                    "kcal": 450.0,
                    "protein_g": 30.0,
                    "fat_g": 15.0,
                    "carb_g": 50.0,
                },
            },
            "lunch": {
                "meal_type": "lunch",
                "recipe": {
                    "food_id": "recipe_002",
                    "dish_name": "Cơm trắng",
                    "macros_per_serving": {
                        "kcal": 200.0,
                        "protein_g": 4.0,
                        "fat_g": 0.5,
                        "carb_g": 45.0,
                    },
                },
                "servings": 1.0,
                "accompaniments": [
                    {
                        "recipe": {
                            "food_id": "recipe_003",
                            "dish_name": "Thịt kho",
                            "macros_per_serving": {
                                "kcal": 300.0,
                                "protein_g": 40.0,
                                "fat_g": 15.0,
                                "carb_g": 5.0,
                            },
                        },
                        "servings": 1.0,
                        "type": "main",
                        "macros": {
                            "kcal": 300.0,
                            "protein_g": 40.0,
                            "fat_g": 15.0,
                            "carb_g": 5.0,
                        },
                    },
                ],
                "macros": {
                    "kcal": 500.0,
                    "protein_g": 44.0,
                    "fat_g": 15.5,
                    "carb_g": 50.0,
                },
            },
            "dinner": {
                "meal_type": "dinner",
                "recipe": {
                    "food_id": "recipe_004",
                    "dish_name": "Cơm cá",
                    "macros_per_serving": {
                        "kcal": 400.0,
                        "protein_g": 35.0,
                        "fat_g": 12.0,
                        "carb_g": 45.0,
                    },
                },
                "servings": 1.0,
                "macros": {
                    "kcal": 400.0,
                    "protein_g": 35.0,
                    "fat_g": 12.0,
                    "carb_g": 45.0,
                },
            },
        },
        "total_macros": {
            "kcal": 1350.0,
            "protein_g": 109.0,
            "fat_g": 42.5,
            "carb_g": 145.0,
        },
        "validation": {
            "valid": True,
        },
    }


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Run evaluation example")
    parser.add_argument(
        "--use-weaviate",
        action="store_true",
        help="Load data from Weaviate instead of using mock data"
    )
    parser.add_argument(
        "--user-ids",
        nargs="+",
        help="List of user IDs to load from Weaviate (only used with --use-weaviate)"
    )
    
    args = parser.parse_args()
    
    print("Running MealAgent Evaluation Example...")
    print("=" * 60)
    
    try:
        results = example_evaluation(
            use_weaviate=args.use_weaviate,
            user_ids=args.user_ids
        )
        print("\n✅ Example completed successfully!")
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()

