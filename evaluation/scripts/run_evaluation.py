"""
Script chính để chạy evaluation cho MealAgent.

Script này tích hợp với MealAgent để tạo meal plans thực tế và đánh giá chúng.
"""

import os
import sys
import asyncio
from pathlib import Path
from typing import List, Dict, Any, Optional

# Add parent directories to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from evaluation.runners.evaluation_runner import EvaluationRunner
from evaluation.test_cases.test_profiles import get_test_profiles, get_profile_by_id
from evaluation.test_cases.test_scenarios import get_test_scenarios, get_scenario_by_id


async def generate_meal_plan(
    user_profile: Dict[str, Any],
    query: str,
    plan_type: str = "day"
) -> Optional[Dict[str, Any]]:
    """
    Tạo meal plan thực tế bằng MealAgent.
    
    Args:
        user_profile: User profile dictionary
        query: User query
        plan_type: "day" or "week"
    
    Returns:
        Meal plan dictionary or None if failed
    """
    try:
        from elysia.tree.objects import TreeData
        from elysia.util.client import ClientManager
        from elysia.objects import Result
        
        # Import MealAgent tools
        if plan_type == "day":
            from MealAgent.tools.plan_day.plan_day_e2e import plan_day_e2e_tool
            tool = plan_day_e2e_tool
        else:
            from MealAgent.tools.plan_week.plan_week_e2e import plan_week_e2e_tool
            tool = plan_week_e2e_tool
        
        # Initialize TreeData and ClientManager
        tree_data = TreeData()
        tree_data.user_prompt = query
        tree_data.environment = type('Environment', (), {
            'find': lambda *args: None,
            'add': lambda *args: None,
            'add_objects': lambda *args: None,
            'replace': lambda *args: None,
            'remove': lambda *args: None,
            'hidden_environment': {}
        })()
        
        client_manager = ClientManager()
        
        # Call tool
        meal_plan = None
        async for result in tool(
            tree_data=tree_data,
            client_manager=client_manager,
            user_id=user_profile["user_id"],
            query=query
        ):
            if isinstance(result, Result) and result.name == "plan":
                meal_plan = result.objects[0]
                break
        
        return meal_plan
        
    except ImportError as e:
        print(f"❌ Import error: {e}")
        print("Make sure MealAgent and Elysia are installed and configured.")
        return None
    except Exception as e:
        print(f"❌ Error generating meal plan: {e}")
        import traceback
        traceback.print_exc()
        return None


async def run_evaluation(
    scenario_ids: Optional[List[str]] = None,
    methods: Optional[List[str]] = None,
    use_mock: bool = False
):
    """
    Chạy evaluation cho các scenarios.
    
    Args:
        scenario_ids: List of scenario IDs to run (None = all)
        methods: List of methods to run (None = all)
            Options: "nutrition_error", "ragas", "llm_judge", "bertscore"
        use_mock: If True, use mock meal plans instead of generating real ones
    """
    print("=" * 80)
    print("MealAgent Evaluation Runner")
    print("=" * 80)
    
    # Get test data
    test_profiles = get_test_profiles()
    test_scenarios = get_test_scenarios()
    
    # Filter scenarios if specified
    if scenario_ids:
        test_scenarios = [
            s for s in test_scenarios if s["scenario_id"] in scenario_ids
        ]
    
    if not test_scenarios:
        print("❌ No scenarios found!")
        return
    
    print(f"\n📋 Running evaluation for {len(test_scenarios)} scenario(s)...")
    
    # Generate meal plans
    meal_plans = []
    user_profiles = []
    user_queries = []
    
    for i, scenario in enumerate(test_scenarios, 1):
        user_id = scenario["user_id"]
        profile = get_profile_by_id(user_id)
        query = scenario["query"]
        
        if not profile:
            print(f"❌ Profile not found for user_id: {user_id}")
            continue
        
        print(f"\n[{i}/{len(test_scenarios)}] Processing scenario: {scenario['scenario_id']}")
        print(f"  User: {user_id}")
        print(f"  Query: {query}")
        
        if use_mock:
            # Use mock meal plan
            from evaluation.example_usage import create_mock_meal_plan
            meal_plan = create_mock_meal_plan(profile)
            print("  ✓ Using mock meal plan")
        else:
            # Generate real meal plan
            print("  ⏳ Generating meal plan with MealAgent...")
            meal_plan = await generate_meal_plan(
                profile,
                query,
                scenario.get("plan_type", "day")
            )
            
            if meal_plan:
                print("  ✓ Meal plan generated successfully")
            else:
                print("  ❌ Failed to generate meal plan, skipping...")
                continue
        
        meal_plans.append(meal_plan)
        user_profiles.append(profile)
        user_queries.append(query)
    
    if not meal_plans:
        print("\n❌ No meal plans generated! Cannot run evaluation.")
        return
    
    print(f"\n✅ Generated {len(meal_plans)} meal plan(s)")
    
    # Initialize evaluation runner
    print("\n🔧 Initializing evaluation runner...")
    runner = EvaluationRunner(
        results_dir="evaluation/results",
        gemini_api_key=os.getenv("GEMINI_API_KEY")
    )
    
    # Run evaluations
    print("\n📊 Running evaluations...")
    
    results = {
        "timestamp": None,
        "num_plans": len(meal_plans),
        "evaluations": {},
    }
    
    # Run each method
    all_methods = ["nutrition_error", "ragas", "llm_judge", "bertscore"]
    methods_to_run = methods if methods else all_methods
    
    for method in methods_to_run:
        print(f"\n  → Running {method}...")
        
        try:
            if method == "nutrition_error":
                result = runner.run_nutrition_evaluation(meal_plans, user_profiles)
                results["evaluations"][method] = result
            
            elif method == "ragas":
                result = runner.run_ragas_evaluation(meal_plans, user_profiles, user_queries)
                if result:
                    results["evaluations"][method] = result
            
            elif method == "llm_judge":
                result = runner.run_llm_judge_evaluation(meal_plans, user_profiles)
                if result:
                    results["evaluations"][method] = result
            
            elif method == "bertscore":
                result = runner.run_bertscore_evaluation(meal_plans, user_profiles)
                if result:
                    results["evaluations"][method] = result
            
            print(f"    ✓ {method} completed")
            
        except Exception as e:
            print(f"    ❌ {method} failed: {e}")
            import traceback
            traceback.print_exc()
    
    # Save results
    from datetime import datetime
    results["timestamp"] = datetime.now().isoformat()
    
    print("\n💾 Saving results...")
    filepath = runner.save_results(results)
    
    print("\n" + "=" * 80)
    print("✅ Evaluation completed!")
    print(f"📁 Results saved to: {filepath}")
    print("=" * 80)
    
    return results


def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Run MealAgent evaluation",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run all evaluations with all scenarios
  python -m evaluation.scripts.run_evaluation
  
  # Run specific scenarios
  python -m evaluation.scripts.run_evaluation --scenarios scenario_1 scenario_2
  
  # Run only nutrition error evaluation
  python -m evaluation.scripts.run_evaluation --methods nutrition_error
  
  # Use mock meal plans (faster, for testing)
  python -m evaluation.scripts.run_evaluation --use-mock
        """
    )
    
    parser.add_argument(
        "--scenarios",
        nargs="+",
        help="Scenario IDs to run (default: all)"
    )
    
    parser.add_argument(
        "--methods",
        nargs="+",
        choices=["nutrition_error", "ragas", "llm_judge", "bertscore"],
        help="Evaluation methods to run (default: all)"
    )
    
    parser.add_argument(
        "--use-mock",
        action="store_true",
        help="Use mock meal plans instead of generating real ones"
    )
    
    args = parser.parse_args()
    
    # Run evaluation
    asyncio.run(run_evaluation(
        scenario_ids=args.scenarios,
        methods=args.methods,
        use_mock=args.use_mock
    ))


if __name__ == "__main__":
    main()


