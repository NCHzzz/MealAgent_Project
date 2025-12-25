"""
Script để chạy từng phương pháp evaluation riêng lẻ.

Sử dụng script này để test từng phương pháp một cách độc lập.
"""

import os
import sys
import asyncio
import json
from pathlib import Path
from typing import List, Dict, Any, Optional

# Add parent directories to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from evaluation.metrics.nutrition_error import NutritionErrorEvaluator
from evaluation.metrics.llm_judge import LLMJudgeEvaluator
from evaluation.metrics.bertscore_eval import BERTScoreEvaluator
from evaluation.test_cases.test_profiles import get_test_profiles, get_profile_by_id
from evaluation.test_cases.test_scenarios import get_test_scenarios
from evaluation.example_usage import create_mock_meal_plan
from evaluation.utils.weaviate_data_loader import (
    load_evaluation_data_from_weaviate,
    load_evaluation_data_from_weaviate_with_logs,
    load_all_evaluation_data_from_weaviate,
    get_all_user_ids_from_weaviate,
    create_client_manager,
)
from datetime import datetime, timezone
import numpy as np


async def run_nutrition_error_test(
    use_weaviate: bool = True, 
    user_ids: Optional[List[str]] = None,
    use_meal_logs: bool = False,
    date: Optional[datetime] = None,
    load_all: bool = True
):
    """
    Chạy test Nutrition Error (MAE & % Error).
    
    Args:
        use_weaviate: Nếu True, load dữ liệu từ Weaviate. Nếu False, dùng mock data.
        user_ids: List of user IDs để load từ Weaviate (nếu None và load_all=False, sẽ lấy tất cả users)
        use_meal_logs: Nếu True, chỉ load từ MealLogEntry. Nếu False và load_all=True, load cả MealPlan và MealLogEntry
        date: Date để filter meal logs (nếu None, load tất cả)
        load_all: Nếu True, load TẤT CẢ meal plans và meal logs từ tất cả collections
    """
    print("=" * 80)
    print("Nutrition Error Evaluation Test")
    print("=" * 80)
    
    evaluator = NutritionErrorEvaluator()
    
    # Get test data - Mặc định dùng Weaviate và load tất cả
    if use_weaviate:
        print("\n📥 Loading data from Weaviate...")
        try:
            client_manager = create_client_manager()
            if not client_manager.is_client:
                print("❌ Weaviate client not available. Falling back to mock data.")
                use_weaviate = False
            else:
                if load_all:
                    # Load TẤT CẢ từ tất cả collections
                    meal_plans, user_profiles = load_all_evaluation_data_from_weaviate(
                        client_manager,
                        include_meal_plans=True,
                        include_meal_logs=True,
                        plan_type=None,
                        date=date,
                        limit=1000
                    )
                    print(f"\n✅ Loaded: {len(meal_plans)} meal plans/logs, {len(user_profiles)} profiles")
                else:
                    # Load theo user_ids cụ thể
                    if user_ids is None:
                        user_ids = get_all_user_ids_from_weaviate(client_manager, limit=10)
                        if not user_ids:
                            print("❌ No users found in Weaviate. Falling back to mock data.")
                            use_weaviate = False
                    
                    if use_weaviate:
                        if use_meal_logs:
                            if date is None:
                                date = datetime.now(timezone.utc)
                            meal_plans, user_profiles = load_evaluation_data_from_weaviate_with_logs(
                                user_ids, client_manager, use_meal_logs=True, date=date
                            )
                        else:
                            meal_plans, user_profiles = load_evaluation_data_from_weaviate(
                                user_ids, client_manager, plan_type="day", use_latest=True
                            )
                        print(f"✅ Loaded: {len(meal_plans)} meal plans/logs, {len(user_profiles)} profiles")
        except Exception as e:
            print(f"❌ Error loading from Weaviate: {e}")
            use_weaviate = False
    
    if not use_weaviate:
        print("\n📥 Using mock test data...")
        profiles = get_test_profiles()[:3]
        
        meal_plans = []
        user_profiles = []
        
        for profile in profiles:
            meal_plan = create_mock_meal_plan(profile)
            meal_plans.append(meal_plan)
            user_profiles.append(profile)
        print(f"✅ Loaded: {len(meal_plans)} mock meal plans, {len(user_profiles)} profiles")
    
    # Phân loại meal plans theo source và plan_type
    # MealPlan: Suggested plans (chưa được user chấp nhận)
    # MealLogEntry: Accepted/Actual plans (đã được user chấp nhận hoặc thực sự ăn)
    suggested_plans = [p for p in meal_plans if p.get("source") != "MealLogEntry"]
    accepted_plans = [p for p in meal_plans if p.get("source") == "MealLogEntry"]
    
    meal_plan_count = len(suggested_plans)
    meal_log_count = len(accepted_plans)
    
    # Chỉ đếm day/week trong MealPlan collection (suggested plans)
    day_plan_count = sum(1 for p in suggested_plans if p.get("plan_type") == "day")
    week_plan_count = sum(1 for p in suggested_plans if p.get("plan_type") == "week")
    
    print(f"\n📊 Evaluation Dataset:")
    print(f"   Total: {len(meal_plans)} meal plans")
    if meal_plan_count > 0:
        print(f"   - Suggested Plans (MealPlan): {meal_plan_count} ({day_plan_count} day, {week_plan_count} week)")
        print(f"     ⚠️  These are system-generated plans, not yet accepted by users")
    if meal_log_count > 0:
        print(f"   - Accepted/Actual Plans (MealLogEntry): {meal_log_count}")
        print(f"     ✅ These are plans users accepted or actually consumed")
    
    # Run evaluation
    print(f"\n⏳ Calculating nutrition errors...")
    results = evaluator.evaluate_batch(meal_plans, user_profiles)
    print(f"✅ Completed {len(results)} evaluations")
    
    # Aggregate
    aggregated = evaluator.aggregate_results(results)
    
    # Print results for report
    print("\n" + "=" * 80)
    print("EVALUATION RESULTS")
    print("=" * 80)
    
    # Print detailed plan-by-plan results for debugging
    print(f"\n📋 Detailed Plan Results (for debugging):")
    for i, result in enumerate(results, 1):
        plan = meal_plans[i-1]
        profile = user_profiles[i-1]
        source = plan.get("source", "MealPlan")
        plan_type = plan.get("plan_type", "day")
        user_id = profile.get("user_id", "unknown")
        plan_id = plan.get("plan_id", "unknown")
        plan_date = plan.get("start_date", "N/A")
        if isinstance(plan_date, str) and len(plan_date) > 10:
            plan_date = plan_date[:10]
        elif isinstance(plan_date, datetime):
            plan_date = plan_date.date().isoformat()
        
        # Get raw values before normalization to show if it's week plan
        total_macros = plan.get("total_macros", {})
        raw_protein = float(total_macros.get("protein_g", 0.0))
        raw_calories = float(total_macros.get("kcal", 0.0))
        
        # Show if normalized (for week plans)
        is_normalized = plan_type == "week"
        normalized_note = " (normalized to daily)" if is_normalized else ""
        
        # Determine plan category
        if source == "MealLogEntry":
            category = "✅ Accepted/Actual"
        else:
            category = "⚠️  Suggested"
        
        print(f"\n   [{i:2d}] Plan ID: {plan_id}")
        print(f"       {category} | User: {user_id[:36]}... | Type: {plan_type} | Date: {plan_date}")
        if is_normalized:
            print(f"       ⚠️  Week plan - values normalized to daily (raw total: P={raw_protein:.1f}g, Cal={raw_calories:.0f}kcal)")
        print(f"       Target:  P={result.target_protein:6.1f}g  C={result.target_carb:6.1f}g  F={result.target_fat:6.1f}g  Cal={result.target_calories:6.0f}kcal")
        print(f"       Actual{normalized_note}:  P={result.actual_protein:6.1f}g  C={result.actual_carb:6.1f}g  F={result.actual_fat:6.1f}g  Cal={result.actual_calories:6.0f}kcal")
        print(f"       % Error: P={result.pct_error_protein:5.1f}%  C={result.pct_error_carb:5.1f}%  F={result.pct_error_fat:5.1f}%  Cal={result.pct_error_calories:5.1f}%")
        print(f"       Overall Error: {result.overall_pct_error:5.1f}% | MAE: {result.overall_mae:6.1f}")
    
    # Print aggregated statistics with median (more robust metric)
    print(f"\n📈 Aggregated MAE (Mean Absolute Error):")
    print(f"   {'Metric':<20} {'Mean':>10} {'Median':>10} {'Std':>10} {'Min':>10} {'Max':>10}")
    print(f"   {'-'*70}")
    mae = aggregated["mae"]
    for metric, stats in mae.items():
        median_val = aggregated.get("percentage_error", {}).get(metric, {}).get("median", stats.get("mean", 0))
        # For MAE, we'll use mean as median approximation
        print(f"   {metric:<20} {stats['mean']:>10.2f} {'N/A':>10} {stats['std']:>10.2f} {stats['min']:>10.2f} {stats['max']:>10.2f}")
    
    print(f"\n📊 Aggregated Percentage Error (with Median - more robust):")
    print(f"   {'Metric':<20} {'Mean':>10} {'Median':>10} {'Std':>10} {'Min':>10} {'Max':>10}")
    print(f"   {'-'*70}")
    pct_error = aggregated["percentage_error"]
    for metric, stats in pct_error.items():
        median_val = stats.get("median", stats.get("mean", 0))
        # Highlight if median is significantly better than mean
        highlight = " ⭐" if median_val < stats['mean'] * 0.7 else ""
        print(f"   {metric:<20} {stats['mean']:>10.2f}% {median_val:>10.2f}% {stats['std']:>10.2f}% {stats['min']:>10.2f}% {stats['max']:>10.2f}%{highlight}")
    
    # Breakdown by source and plan type
    print(f"\n📊 Breakdown by Plan Type:")
    
    # Separate results by source and plan type
    suggested_results = []
    accepted_results = []
    day_plan_results = []
    week_plan_results = []
    
    for i, result in enumerate(results):
        plan = meal_plans[i]
        if plan.get("source") == "MealLogEntry":
            accepted_results.append(result)
        else:
            suggested_results.append(result)
            plan_type = plan.get("plan_type", "day")
            if plan_type == "week":
                week_plan_results.append(result)
            else:
                day_plan_results.append(result)
    
    if suggested_results:
        suggested_agg = evaluator.aggregate_results(suggested_results)
        print(f"   Suggested Plans (MealPlan) - {len(suggested_results)} plans:")
        print(f"      Overall Error: {suggested_agg['percentage_error']['overall']['mean']:.2f}% ± {suggested_agg['percentage_error']['overall']['std']:.2f}%")
        print(f"      ⚠️  System-generated plans, not yet accepted by users")
        if day_plan_results:
            day_agg = evaluator.aggregate_results(day_plan_results)
            print(f"      - Day Plans ({len(day_plan_results)}): {day_agg['percentage_error']['overall']['mean']:.2f}%")
        if week_plan_results:
            week_agg = evaluator.aggregate_results(week_plan_results)
            print(f"      - Week Plans ({len(week_plan_results)}): {week_agg['percentage_error']['overall']['mean']:.2f}%")
    
    if accepted_results:
        accepted_agg = evaluator.aggregate_results(accepted_results)
        print(f"   Accepted/Actual Plans (MealLogEntry) - {len(accepted_results)} plans:")
        print(f"      Overall Error: {accepted_agg['percentage_error']['overall']['mean']:.2f}% ± {accepted_agg['percentage_error']['overall']['std']:.2f}%")
        print(f"      ✅ Plans users accepted or actually consumed (more reliable data)")
    
    # Key insights for report
    if results:
        pct_errors = [r.overall_pct_error for r in results]
        
        # Performance distribution với categories mới
        excellent = sum(1 for e in pct_errors if e < 10)
        good = sum(1 for e in pct_errors if 10 <= e < 15)
        fair = sum(1 for e in pct_errors if 15 <= e < 20)
        poor = sum(1 for e in pct_errors if e >= 20)
        success_rate = (excellent + good) / len(results) * 100
        
        print(f"\n📈 Performance Distribution:")
        print(f"   Excellent (<10%):    {excellent:3d} ({excellent/len(results)*100:5.1f}%)")
        print(f"   Good (10-15%):       {good:3d} ({good/len(results)*100:5.1f}%)")
        print(f"   Fair (15-20%):       {fair:3d} ({fair/len(results)*100:5.1f}%)")
        print(f"   Poor (>20%):         {poor:3d} ({poor/len(results)*100:5.1f}%)")
        print(f"   Success Rate:        {success_rate:.1f}%")
        
        # Best and worst cases
        best_result = min(results, key=lambda r: r.overall_pct_error)
        worst_result = max(results, key=lambda r: r.overall_pct_error)
        best_idx = results.index(best_result)
        worst_idx = results.index(worst_result)
        
        best_plan = meal_plans[best_idx]
        worst_plan = meal_plans[worst_idx]
        
        print(f"\n🎯 Key Highlights:")
        print(f"   Best Performance:  {best_result.overall_pct_error:.2f}%")
        print(f"      Plan: {best_plan.get('plan_id', '')[:50]}...")
        print(f"      Type: {best_plan.get('plan_type', 'day')} | Source: {best_plan.get('source', 'MealPlan')}")
        print(f"   Worst Performance: {worst_result.overall_pct_error:.2f}%")
        print(f"      Plan: {worst_plan.get('plan_id', '')[:50]}...")
        print(f"      Type: {worst_plan.get('plan_type', 'day')} | Source: {worst_plan.get('source', 'MealPlan')}")
    
    # Save results with detailed metadata
    output = {
        "method": "nutrition_error",
        "metadata": {
            "total_evaluations": len(results),
            "meal_plan_count": meal_plan_count,
            "meal_log_count": meal_log_count,
            "user_profile_count": len(user_profiles),
            "data_source": "Weaviate" if use_weaviate else "Mock",
            "load_all": load_all if use_weaviate else False,
            "date_filter": date.isoformat() if date else None,
        },
        "individual_results": [],
        "aggregated": aggregated,
    }
    
    # Add individual results with metadata
    def serialize_datetime(obj):
        """Convert datetime objects to ISO format strings for JSON serialization."""
        if isinstance(obj, datetime):
            return obj.isoformat()
        raise TypeError(f"Object of type {type(obj)} is not JSON serializable")
    
    for i, result in enumerate(results):
        result_dict = result.to_dict()
        plan = meal_plans[i] if i < len(meal_plans) else {}
        profile = user_profiles[i] if i < len(user_profiles) else {}
        
        # Convert datetime to string if present
        plan_date = plan.get("start_date")
        if plan_date and isinstance(plan_date, datetime):
            plan_date = plan_date.isoformat()
        elif plan_date and isinstance(plan_date, str):
            # Already a string, keep as is
            pass
        else:
            plan_date = None
        
        result_dict["metadata"] = {
            "user_id": profile.get("user_id"),
            "plan_id": plan.get("plan_id"),
            "source": plan.get("source", "MealPlan"),
            "plan_type": plan.get("plan_type"),
            "plan_date": plan_date,
        }
        output["individual_results"].append(result_dict)
    
    output_file = Path("evaluation/results/nutrition_error_test.json")
    output_file.parent.mkdir(parents=True, exist_ok=True)
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False, default=serialize_datetime)
    
    print(f"\n💾 Results saved to: {output_file}")
    print("=" * 80)
    
    return output




async def run_llm_judge_test():
    """Chạy test LLM-as-a-Judge."""
    print("=" * 80)
    print("LLM-as-a-Judge Evaluation Test")
    print("=" * 80)
    
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("❌ GEMINI_API_KEY not set. Set it with:")
        print("   export GEMINI_API_KEY='your-api-key'")
        return None
    
    try:
        evaluator = LLMJudgeEvaluator(api_key=api_key)
    except Exception as e:
        print(f"❌ Failed to initialize LLM Judge: {e}")
        return None
    
    # Get test data
    profiles = get_test_profiles()[:2]  # Use first 2 profiles (LLM calls can be slow)
    
    meal_plans = []
    user_profiles = []
    
    for profile in profiles:
        meal_plan = create_mock_meal_plan(profile)
        meal_plans.append(meal_plan)
        user_profiles.append(profile)
    
    print(f"\n📊 Evaluating {len(meal_plans)} meal plans...")
    print("⏳ This may take a while (LLM API calls)...")
    
    # Run evaluation
    results = evaluator.evaluate_batch(meal_plans, user_profiles)
    
    # Print results
    print("\n" + "=" * 80)
    print("RESULTS - LLM-as-a-Judge")
    print("=" * 80)
    
    for i, result in enumerate(results, 1):
        print(f"\n  Scenario {i}:")
        print(f"    Overall Score:     {result.overall_score:.1f}/100")
        print(f"    Nutrition Score:   {result.nutrition_score:.1f}/100")
        print(f"    Variety Score:     {result.variety_score:.1f}/100")
        print(f"    Balance Score:     {result.balance_score:.1f}/100")
        print(f"    Feasibility Score: {result.feasibility_score:.1f}/100")
        print(f"\n    Feedback:")
        print(f"      {result.feedback[:200]}...")
        if result.strengths:
            print(f"\n    Strengths:")
            for strength in result.strengths[:3]:
                print(f"      - {strength}")
        if result.suggestions:
            print(f"\n    Suggestions:")
            for suggestion in result.suggestions[:3]:
                print(f"      - {suggestion}")
    
    # Calculate averages
    avg_overall = sum(r.overall_score for r in results) / len(results)
    avg_nutrition = sum(r.nutrition_score for r in results) / len(results)
    avg_variety = sum(r.variety_score for r in results) / len(results)
    avg_balance = sum(r.balance_score for r in results) / len(results)
    avg_feasibility = sum(r.feasibility_score for r in results) / len(results)
    
    print(f"\n  Averages:")
    print(f"    Overall Score:     {avg_overall:.1f}/100")
    print(f"    Nutrition Score:   {avg_nutrition:.1f}/100")
    print(f"    Variety Score:     {avg_variety:.1f}/100")
    print(f"    Balance Score:     {avg_balance:.1f}/100")
    print(f"    Feasibility Score: {avg_feasibility:.1f}/100")
    
    # Save results
    output = {
        "method": "llm_judge",
        "individual_results": [r.to_dict() for r in results],
        "aggregated": {
            "overall_score": {"mean": avg_overall},
            "nutrition_score": {"mean": avg_nutrition},
            "variety_score": {"mean": avg_variety},
            "balance_score": {"mean": avg_balance},
            "feasibility_score": {"mean": avg_feasibility},
        },
    }
    
    output_file = Path("evaluation/results/llm_judge_test.json")
    output_file.parent.mkdir(parents=True, exist_ok=True)
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    
    print(f"\n💾 Results saved to: {output_file}")
    print("=" * 80)
    
    return output


async def run_bertscore_test():
    """Chạy test BERTScore."""
    print("=" * 80)
    print("BERTScore Evaluation Test")
    print("=" * 80)
    
    try:
        evaluator = BERTScoreEvaluator()
    except ImportError:
        print("❌ BERTScore not available. Install with: pip install bert-score")
        return None
    
    # Get test data
    profiles = get_test_profiles()[:3]  # Use first 3 profiles
    
    meal_plans = []
    user_profiles = []
    
    for profile in profiles:
        meal_plan = create_mock_meal_plan(profile)
        meal_plans.append(meal_plan)
        user_profiles.append(profile)
    
    print(f"\n📊 Evaluating {len(meal_plans)} meal plans...")
    print("⏳ This may take a while (BERTScore computation)...")
    
    # Run evaluation
    results = evaluator.evaluate_batch(meal_plans, user_profiles)
    
    # Print results
    print("\n" + "=" * 80)
    print("RESULTS - BERTScore")
    print("=" * 80)
    
    for i, result in enumerate(results, 1):
        print(f"\n  Scenario {i}:")
        print(f"    Precision: {result.precision:.4f}")
        print(f"    Recall:    {result.recall:.4f}")
        print(f"    F1 Score:  {result.f1:.4f}")
    
    # Calculate averages
    avg_precision = sum(r.precision for r in results) / len(results)
    avg_recall = sum(r.recall for r in results) / len(results)
    avg_f1 = sum(r.f1 for r in results) / len(results)
    
    print(f"\n  Averages:")
    print(f"    Precision: {avg_precision:.4f}")
    print(f"    Recall:    {avg_recall:.4f}")
    print(f"    F1 Score:  {avg_f1:.4f}")
    
    # Save results
    output = {
        "method": "bertscore",
        "individual_results": [r.to_dict() for r in results],
        "aggregated": {
            "precision": {"mean": avg_precision},
            "recall": {"mean": avg_recall},
            "f1": {"mean": avg_f1},
        },
    }
    
    output_file = Path("evaluation/results/bertscore_test.json")
    output_file.parent.mkdir(parents=True, exist_ok=True)
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    
    print(f"\n💾 Results saved to: {output_file}")
    print("=" * 80)
    
    return output


def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Run individual evaluation method",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run nutrition error test (loads ALL from MealPlan, MealPlanItem, MealLogEntry, UserProfile)
  python -m evaluation.scripts.run_single_method nutrition_error
  
  # Run nutrition error with specific date filter for meal logs
  python -m evaluation.scripts.run_single_method nutrition_error --date 2024-01-15
  
  # Run nutrition error for specific users only (disable load-all)
  python -m evaluation.scripts.run_single_method nutrition_error --no-load-all --user-ids user1 user2
  
  # Run LLM judge test (requires GEMINI_API_KEY)
  export GEMINI_API_KEY='your-key'
  python -m evaluation.scripts.run_single_method llm_judge
  
  # Run BERTScore test
  python -m evaluation.scripts.run_single_method bertscore
        """
    )
    
    parser.add_argument(
        "method",
        choices=["nutrition_error", "llm_judge", "bertscore"],
        help="Evaluation method to run"
    )
    
    parser.add_argument(
        "--use-mock",
        action="store_true",
        help="Use mock data instead of loading from Weaviate (only for nutrition_error)"
    )
    
    parser.add_argument(
        "--user-ids",
        nargs="+",
        help="List of user IDs to load from Weaviate"
    )
    
    parser.add_argument(
        "--use-meal-logs",
        action="store_true",
        help="Load from MealLogEntry instead of MealPlan (only for nutrition_error, ignored if load-all)"
    )
    
    parser.add_argument(
        "--date",
        help="Date for meal logs (YYYY-MM-DD format, only used with --use-meal-logs or --load-all)"
    )
    
    parser.add_argument(
        "--load-all",
        action="store_true",
        default=True,  # Mặc định load tất cả
        help="Load ALL meal plans and meal logs from all collections (default: True)"
    )
    
    parser.add_argument(
        "--no-load-all",
        action="store_false",
        dest="load_all",
        help="Disable loading all data, only load specific users"
    )
    
    args = parser.parse_args()
    
    # Parse date if provided
    date = None
    if args.date:
        try:
            date = datetime.strptime(args.date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            print(f"❌ Invalid date format: {args.date}. Use YYYY-MM-DD format.")
            return
    
    # Run the selected method
    if args.method == "nutrition_error":
        asyncio.run(run_nutrition_error_test(
            use_weaviate=not args.use_mock,  # Mặc định dùng Weaviate, trừ khi có --use-mock
            user_ids=args.user_ids,
            use_meal_logs=args.use_meal_logs,
            date=date,
            load_all=args.load_all
        ))
    elif args.method == "llm_judge":
        asyncio.run(run_llm_judge_test())
    elif args.method == "bertscore":
        asyncio.run(run_bertscore_test())


if __name__ == "__main__":
    main()

