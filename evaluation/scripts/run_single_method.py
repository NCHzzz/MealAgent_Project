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

from evaluation.utils.weaviate_data_loader import (
    load_evaluation_data_from_weaviate,
    load_evaluation_data_from_weaviate_with_logs,
    load_all_evaluation_data_from_weaviate,
    get_all_user_ids_from_weaviate,
    create_client_manager,
)
from datetime import datetime, timezone
import numpy as np


def generate_nutrition_error_summary(output: Dict[str, Any], output_file: Path) -> None:
    """
    Tạo file markdown summary report cho nutrition error evaluation.
    
    Args:
        output: Dictionary chứa kết quả evaluation từ run_nutrition_error_test
        output_file: Path đến file JSON output (để tạo summary cùng thư mục)
    """
    individual_results = output.get("individual_results", [])
    aggregated = output.get("aggregated", {})
    metadata = output.get("metadata", {})
    
    # Phân loại plans theo source
    meal_plan_results = [r for r in individual_results if r.get("metadata", {}).get("source") == "MealPlan"]
    meal_log_results = [r for r in individual_results if r.get("metadata", {}).get("source") == "MealLogEntry"]
    
    # Phân loại theo overall_pct_error ranges (tương tự llm_judge với score ranges)
    excellent = [r for r in individual_results if r.get("percentage_error", {}).get("overall", 100) < 10]
    good = [r for r in individual_results if 10 <= r.get("percentage_error", {}).get("overall", 100) < 15]
    fair = [r for r in individual_results if 15 <= r.get("percentage_error", {}).get("overall", 100) < 20]
    poor = [r for r in individual_results if r.get("percentage_error", {}).get("overall", 100) >= 20]
    
    # Phân tích các vấn đề phổ biến dựa trên macro differences
    common_issues = {
        "low_protein": [],
        "high_protein": [],
        "low_calories": [],
        "high_calories": [],
        "high_carb": [],
        "high_fat": [],
    }
    
    for result in individual_results:
        target = result.get("target_values", {})
        actual = result.get("actual_values", {})
        pct_error = result.get("percentage_error", {})
        
        # Calculate differences
        protein_diff = actual.get("protein_g", 0) - target.get("protein_g", 0)
        carb_diff = actual.get("carb_g", 0) - target.get("carb_g", 0)
        fat_diff = actual.get("fat_g", 0) - target.get("fat_g", 0)
        calorie_diff = actual.get("calories", 0) - target.get("calories", 0)
        
        plan_id = result.get("metadata", {}).get("plan_id", "unknown")
        overall_error = pct_error.get("overall", 0)
        
        # Low protein (<50g below target)
        if protein_diff < -50:
            common_issues["low_protein"].append({
                "plan_id": plan_id,
                "protein_diff": protein_diff,
                "overall_error": overall_error,
            })
        
        # High protein (>50g above target)
        if protein_diff > 50:
            common_issues["high_protein"].append({
                "plan_id": plan_id,
                "protein_diff": protein_diff,
                "overall_error": overall_error,
            })
        
        # Low calories (<500kcal below target)
        if calorie_diff < -500:
            common_issues["low_calories"].append({
                "plan_id": plan_id,
                "calorie_diff": calorie_diff,
                "overall_error": overall_error,
            })
        
        # High calories (>500kcal above target)
        if calorie_diff > 500:
            common_issues["high_calories"].append({
                "plan_id": plan_id,
                "calorie_diff": calorie_diff,
                "overall_error": overall_error,
            })
        
        # High carb (>100g above target)
        if carb_diff > 100:
            common_issues["high_carb"].append({
                "plan_id": plan_id,
                "carb_diff": carb_diff,
                "overall_error": overall_error,
            })
        
        # High fat (>50g above target)
        if fat_diff > 50:
            common_issues["high_fat"].append({
                "plan_id": plan_id,
                "fat_diff": fat_diff,
                "overall_error": overall_error,
            })
    
    # Tìm best và worst plans (dựa trên overall_pct_error - thấp hơn = tốt hơn)
    best_plans = sorted(individual_results, key=lambda x: x.get("percentage_error", {}).get("overall", 100))[:5]
    worst_plans = sorted(individual_results, key=lambda x: x.get("percentage_error", {}).get("overall", 100), reverse=True)[:5]
    
    # Tạo markdown report
    total_evaluations = len(individual_results)
    report = f"""# Nutrition Error Evaluation Summary Report

Generated: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

## Overview

- **Total Evaluations**: {total_evaluations}
- **Meal Plans (Suggested)**: {len(meal_plan_results)}
- **Meal Logs (Accepted/Actual)**: {len(meal_log_results)}

## Performance Distribution

- **Excellent (<10%)**: {len(excellent)} ({len(excellent)/total_evaluations*100:.1f}%)
- **Good (10-15%)**: {len(good)} ({len(good)/total_evaluations*100:.1f}%)
- **Fair (15-20%)**: {len(fair)} ({len(fair)/total_evaluations*100:.1f}%)
- **Poor (≥20%)**: {len(poor)} ({len(poor)/total_evaluations*100:.1f}%)

## Aggregated Metrics

### Overall Percentage Error
- Mean: {aggregated.get('percentage_error', {}).get('overall', {}).get('mean', 0):.2f}%
- Median: {aggregated.get('percentage_error', {}).get('overall', {}).get('median', 0):.2f}%
- Std: {aggregated.get('percentage_error', {}).get('overall', {}).get('std', 0):.2f}%
- Range: {aggregated.get('percentage_error', {}).get('overall', {}).get('min', 0):.2f}% - {aggregated.get('percentage_error', {}).get('overall', {}).get('max', 0):.2f}%

### Protein Error
- Mean: {aggregated.get('percentage_error', {}).get('protein_g', {}).get('mean', 0):.2f}%
- Median: {aggregated.get('percentage_error', {}).get('protein_g', {}).get('median', 0):.2f}%
- Std: {aggregated.get('percentage_error', {}).get('protein_g', {}).get('std', 0):.2f}%

### Carb Error
- Mean: {aggregated.get('percentage_error', {}).get('carb_g', {}).get('mean', 0):.2f}%
- Median: {aggregated.get('percentage_error', {}).get('carb_g', {}).get('median', 0):.2f}%
- Std: {aggregated.get('percentage_error', {}).get('carb_g', {}).get('std', 0):.2f}%

### Fat Error
- Mean: {aggregated.get('percentage_error', {}).get('fat_g', {}).get('mean', 0):.2f}%
- Median: {aggregated.get('percentage_error', {}).get('fat_g', {}).get('median', 0):.2f}%
- Std: {aggregated.get('percentage_error', {}).get('fat_g', {}).get('std', 0):.2f}%

### Calories Error
- Mean: {aggregated.get('percentage_error', {}).get('calories', {}).get('mean', 0):.2f}%
- Median: {aggregated.get('percentage_error', {}).get('calories', {}).get('median', 0):.2f}%
- Std: {aggregated.get('percentage_error', {}).get('calories', {}).get('std', 0):.2f}%

## Aggregated MAE (Mean Absolute Error)

### Overall MAE
- Mean: {aggregated.get('mae', {}).get('overall', {}).get('mean', 0):.2f}
- Std: {aggregated.get('mae', {}).get('overall', {}).get('std', 0):.2f}
- Range: {aggregated.get('mae', {}).get('overall', {}).get('min', 0):.2f} - {aggregated.get('mae', {}).get('overall', {}).get('max', 0):.2f}

### Protein MAE
- Mean: {aggregated.get('mae', {}).get('protein_g', {}).get('mean', 0):.2f}g
- Std: {aggregated.get('mae', {}).get('protein_g', {}).get('std', 0):.2f}g

### Carb MAE
- Mean: {aggregated.get('mae', {}).get('carb_g', {}).get('mean', 0):.2f}g
- Std: {aggregated.get('mae', {}).get('carb_g', {}).get('std', 0):.2f}g

### Fat MAE
- Mean: {aggregated.get('mae', {}).get('fat_g', {}).get('mean', 0):.2f}g
- Std: {aggregated.get('mae', {}).get('fat_g', {}).get('std', 0):.2f}g

### Calories MAE
- Mean: {aggregated.get('mae', {}).get('calories', {}).get('mean', 0):.2f}kcal
- Std: {aggregated.get('mae', {}).get('calories', {}).get('std', 0):.2f}kcal

## Common Issues

### Low Protein (<50g below target)
**Count**: {len(common_issues['low_protein'])} plans

### High Protein (>50g above target)
**Count**: {len(common_issues['high_protein'])} plans

### Low Calories (<500kcal below target)
**Count**: {len(common_issues['low_calories'])} plans

### High Calories (>500kcal above target)
**Count**: {len(common_issues['high_calories'])} plans

### High Carb (>100g above target)
**Count**: {len(common_issues['high_carb'])} plans

### High Fat (>50g above target)
**Count**: {len(common_issues['high_fat'])} plans

## Top 5 Best Plans (Lowest Error)

"""
    
    for i, result in enumerate(best_plans, 1):
        plan_id = result.get("metadata", {}).get("plan_id", "unknown")
        source = result.get("metadata", {}).get("source", "MealPlan")
        overall_error = result.get("percentage_error", {}).get("overall", 0)
        report += f"{i}. Plan ID: `{plan_id}` - Error: {overall_error:.2f}% ({source})\n"
    
    report += "\n## Top 5 Worst Plans (Highest Error)\n\n"
    
    for i, result in enumerate(worst_plans, 1):
        plan_id = result.get("metadata", {}).get("plan_id", "unknown")
        source = result.get("metadata", {}).get("source", "MealPlan")
        overall_error = result.get("percentage_error", {}).get("overall", 0)
        report += f"{i}. Plan ID: `{plan_id}` - Error: {overall_error:.2f}% ({source})\n"
    
    report += "\n## Recommendations\n\n"
    report += "### For Meal Plan Generation:\n"
    
    # Dynamic recommendations based on common issues
    if len(common_issues['low_protein']) > len(common_issues['high_protein']):
        report += "1. **Increase Protein**: Many plans lack sufficient protein. Consider adding more lean protein sources.\n"
    elif len(common_issues['high_protein']) > 0:
        report += "1. **Reduce Protein**: Some plans exceed protein targets. Adjust portion sizes.\n"
    else:
        report += "1. **Maintain Protein Balance**: Protein levels are generally appropriate.\n"
    
    if len(common_issues['high_calories']) > len(common_issues['low_calories']):
        report += "2. **Control Calories**: Many plans exceed calorie targets. Reduce portion sizes or choose lower-calorie options.\n"
    elif len(common_issues['low_calories']) > 0:
        report += "2. **Increase Calories**: Some plans are below calorie targets. Add more nutrient-dense foods.\n"
    else:
        report += "2. **Maintain Calorie Balance**: Calorie levels are generally appropriate.\n"
    
    if len(common_issues['high_fat']) > 0:
        report += "3. **Reduce Fat**: High-fat plans are common. Use cooking methods that reduce fat (steaming, grilling).\n"
    else:
        report += "3. **Maintain Fat Balance**: Fat levels are generally appropriate.\n"
    
    if len(common_issues['high_carb']) > 0:
        report += "4. **Control Carbs**: Some plans exceed carb targets. Consider reducing portion sizes of carb-rich foods.\n"
    else:
        report += "4. **Maintain Carb Balance**: Carb levels are generally appropriate.\n"
    
    report += "5. **Improve Overall Accuracy**: Focus on better macro distribution and portion size estimation.\n"
    
    report += "\n### For System Improvement:\n"
    report += "- Review and fix data quality issues (especially MealLogEntry with unrealistic macros)\n"
    report += "- Implement better macro validation before saving plans\n"
    report += "- Improve portion size estimation algorithms\n"
    report += "- Consider user feedback and adjust targets accordingly\n"
    report += "- Monitor and reduce outliers in nutrition calculations\n"
    
    # Save report
    summary_file = output_file.parent / "nutrition_error_summary.md"
    with open(summary_file, "w", encoding="utf-8") as f:
        f.write(report)
    
    print(f"💾 Summary report saved to: {summary_file}")


# OPENROUTER_API_KEY='your-api-key'
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
        print("\n❌ Weaviate is not available and mock data is not supported.")
        print("   Please ensure Weaviate is configured or use --use-mock flag is removed.")
        return None
    
    # Phân loại meal plans theo source và plan_type (sử dụng original plans trước khi expand)
    # MealPlan: Suggested plans (chưa được user chấp nhận)
    # MealLogEntry: Accepted/Actual plans (đã được user chấp nhận hoặc thực sự ăn)
    suggested_plans = [p for p in meal_plans if p.get("source") != "MealLogEntry"]
    accepted_plans = [p for p in meal_plans if p.get("source") == "MealLogEntry"]
    
    meal_plan_count = len(suggested_plans)
    meal_log_count = len(accepted_plans)
    
    # Chỉ đếm day/week trong MealPlan collection (suggested plans) - original plans
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
    # Note: evaluate_batch sẽ expand week plans thành day plans
    print(f"\n⏳ Calculating nutrition errors...")
    print("⏳ Week plans will be split into individual day plans for evaluation...")
    results = evaluator.evaluate_batch(meal_plans, user_profiles)
    print(f"✅ Completed {len(results)} evaluations")
    
    # Get expanded plans để match với results
    # evaluate_batch đã expand week plans, nên ta cần expand lại để có đúng mapping
    expanded_plans, expanded_profiles, original_indices = evaluator._expand_week_plans_to_days(
        meal_plans, user_profiles
    )
    
    # Sử dụng expanded_plans và expanded_profiles cho output
    output_plans = expanded_plans
    output_profiles = expanded_profiles
    
    # Aggregate
    aggregated = evaluator.aggregate_results(results)
    
    # Print results for report
    print("\n" + "=" * 80)
    print("EVALUATION RESULTS")
    print("=" * 80)
    
    # Print detailed plan-by-plan results for debugging
    print(f"\n📋 Detailed Plan Results (for debugging):")
    for i, result in enumerate(results, 1):
        plan = output_plans[i-1] if i-1 < len(output_plans) else {}
        profile = output_profiles[i-1] if i-1 < len(output_profiles) else {}
        source = plan.get("source", "MealPlan")
        plan_type = plan.get("plan_type", "day")
        user_id = profile.get("user_id", "unknown")
        plan_id = plan.get("plan_id", "unknown")
        plan_date = plan.get("start_date", "N/A")
        if isinstance(plan_date, str) and len(plan_date) > 10:
            plan_date = plan_date[:10]
        elif isinstance(plan_date, datetime):
            plan_date = plan_date.date().isoformat()
        
        # Nếu là day plan từ week plan, hiển thị thông tin
        original_plan_id = plan.get("original_plan_id")
        if original_plan_id:
            plan_id_display = f"{plan_id} (from week plan {original_plan_id})"
        else:
            plan_id_display = plan_id
        
        # Determine plan category
        if source == "MealLogEntry":
            category = "✅ Accepted/Actual"
        else:
            category = "⚠️  Suggested"
        
        print(f"\n   [{i:2d}] Plan ID: {plan_id_display}")
        print(f"       {category} | User: {user_id[:36]}... | Type: {plan_type} | Date: {plan_date}")
        print(f"       Target:  P={result.target_protein:6.1f}g  C={result.target_carb:6.1f}g  F={result.target_fat:6.1f}g  Cal={result.target_calories:6.0f}kcal")
        print(f"       Actual:  P={result.actual_protein:6.1f}g  C={result.actual_carb:6.1f}g  F={result.actual_fat:6.1f}g  Cal={result.actual_calories:6.0f}kcal")
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
    
    for i, result in enumerate(results):
        plan = output_plans[i] if i < len(output_plans) else {}
        if plan.get("source") == "MealLogEntry":
            accepted_results.append(result)
        else:
            suggested_results.append(result)
            plan_type = plan.get("plan_type", "day")
            # Week plans đã được expand thành day plans, nên không còn week_plan_results
            # Tất cả đều là day plans bây giờ
            day_plan_results.append(result)
    
    if suggested_results:
        suggested_agg = evaluator.aggregate_results(suggested_results)
        print(f"   Suggested Plans (MealPlan) - {len(suggested_results)} plans:")
        print(f"      Overall Error: {suggested_agg['percentage_error']['overall']['mean']:.2f}% ± {suggested_agg['percentage_error']['overall']['std']:.2f}%")
        print(f"      ⚠️  System-generated plans, not yet accepted by users")
        if day_plan_results:
            day_agg = evaluator.aggregate_results(day_plan_results)
            print(f"      - Day Plans ({len(day_plan_results)}): {day_agg['percentage_error']['overall']['mean']:.2f}%")
            # Đếm số day plans từ week plans
            week_day_count = sum(1 for i, p in enumerate(output_plans[:len(results)]) 
                               if i < len(results) and p.get("original_plan_id"))
            if week_day_count > 0:
                print(f"        (including {week_day_count} days from week plans)")
    
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
        
        best_plan = output_plans[best_idx] if best_idx < len(output_plans) else {}
        worst_plan = output_plans[worst_idx] if worst_idx < len(output_plans) else {}
        
        best_plan_id = best_plan.get('plan_id', '')
        if best_plan.get('original_plan_id'):
            best_plan_id = f"{best_plan_id} (from week plan {best_plan.get('original_plan_id')})"
        
        worst_plan_id = worst_plan.get('plan_id', '')
        if worst_plan.get('original_plan_id'):
            worst_plan_id = f"{worst_plan_id} (from week plan {worst_plan.get('original_plan_id')})"
        
        print(f"\n🎯 Key Highlights:")
        print(f"   Best Performance:  {best_result.overall_pct_error:.2f}%")
        print(f"      Plan: {best_plan_id[:50]}...")
        print(f"      Type: {best_plan.get('plan_type', 'day')} | Source: {best_plan.get('source', 'MealPlan')}")
        print(f"   Worst Performance: {worst_result.overall_pct_error:.2f}%")
        print(f"      Plan: {worst_plan_id[:50]}...")
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
    
    # Add individual results with metadata
    # Sử dụng output_plans và output_profiles (đã được expand)
    for i, result in enumerate(results):
        result_dict = result.to_dict()
        plan = output_plans[i] if i < len(output_plans) else {}
        profile = output_profiles[i] if i < len(output_profiles) else {}
        
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
        
        # Nếu là day plan từ week plan, thêm thông tin original_plan_id
        if plan.get("original_plan_id"):
            result_dict["metadata"]["original_plan_id"] = plan.get("original_plan_id")
            result_dict["metadata"]["day_key"] = plan.get("day_key")
        
        output["individual_results"].append(result_dict)
    
    output_file = Path("evaluation/results/nutrition_error_test.json")
    output_file.parent.mkdir(parents=True, exist_ok=True)
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False, default=serialize_datetime)
    
    print(f"\n💾 Results saved to: {output_file}")
    
    # Generate summary report
    print("\n📝 Generating summary report...")
    generate_nutrition_error_summary(output, output_file)
    
    print("=" * 80)
    
    return output





async def run_llm_judge_test(
    use_weaviate: bool = True,
    user_ids: Optional[List[str]] = None,
    use_meal_logs: bool = False,
    date: Optional[datetime] = None,
    load_all: bool = True
):
    """
    Chạy test LLM-as-a-Judge.
    
    Args:
        use_weaviate: Nếu True, load dữ liệu từ Weaviate. Nếu False, dùng mock data.
        user_ids: List of user IDs để load từ Weaviate (nếu None và load_all=False, sẽ lấy tất cả users)
        use_meal_logs: Nếu True, chỉ load từ MealLogEntry. Nếu False và load_all=True, load cả MealPlan và MealLogEntry
        date: Date để filter meal logs (nếu None, load tất cả)
        load_all: Nếu True, load TẤT CẢ meal plans và meal logs từ tất cả collections
    """
    print("=" * 80)
    print("LLM-as-a-Judge Evaluation Test")
    print("=" * 80)
    
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        print("❌ OPENROUTER_API_KEY not set. Set it with:")
        print("   export OPENROUTER_API_KEY='your-api-key'")
        print("   Get your API key from: https://openrouter.ai/keys")
        return None
    
    try:
        evaluator = LLMJudgeEvaluator(api_key=api_key)
    except Exception as e:
        print(f"❌ Failed to initialize LLM Judge: {e}")
        return None
    
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
        print("\n❌ Weaviate is not available and mock data is not supported.")
        print("   Please ensure Weaviate is configured or use --use-mock flag is removed.")
        return None
    
    # Phân loại meal plans theo source và plan_type
    suggested_plans = [p for p in meal_plans if p.get("source") != "MealLogEntry"]
    accepted_plans = [p for p in meal_plans if p.get("source") == "MealLogEntry"]
    
    meal_plan_count = len(suggested_plans)
    meal_log_count = len(accepted_plans)
    
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
    # Note: evaluate_batch sẽ expand week plans thành day plans
    # Nên số lượng results có thể nhiều hơn số lượng meal_plans ban đầu
    print(f"\n⏳ Evaluating {len(meal_plans)} meal plans...")
    print("⏳ This may take a while (LLM API calls)...")
    print("⏳ Week plans will be split into individual day plans for evaluation...")
    
    results = evaluator.evaluate_batch(meal_plans, user_profiles)
    print(f"✅ Completed {len(results)} evaluations")
    
    # Get expanded plans để match với results
    # evaluate_batch đã expand week plans, nhưng không trả về expanded_plans
    # Nên ta cần expand lại để có đúng mapping
    expanded_plans, expanded_profiles, original_indices = evaluator._expand_week_plans_to_days(
        meal_plans, user_profiles
    )
    
    # Sử dụng expanded_plans và expanded_profiles cho output
    output_plans = expanded_plans
    output_profiles = expanded_profiles
    
    # Aggregate results
    aggregated = evaluator.aggregate_results(results)
    
    # Print results for report
    print("\n" + "=" * 80)
    print("EVALUATION RESULTS")
    print("=" * 80)
    
    # Print detailed plan-by-plan results (limit to first 10 for readability)
    print(f"\n📋 Detailed Plan Results (showing first 10):")
    for i, result in enumerate(results[:10], 1):
        plan = output_plans[i-1] if i-1 < len(output_plans) else {}
        profile = output_profiles[i-1] if i-1 < len(output_profiles) else {}
        source = plan.get("source", "MealPlan")
        plan_type = plan.get("plan_type", "day")
        user_id = profile.get("user_id", "unknown")
        plan_id = plan.get("plan_id", "unknown")
        
        # Nếu là day plan từ week plan, hiển thị thông tin
        original_plan_id = plan.get("original_plan_id")
        if original_plan_id:
            plan_id_display = f"{plan_id} (from week plan {original_plan_id})"
        else:
            plan_id_display = plan_id
        
        category = "✅ Accepted/Actual" if source == "MealLogEntry" else "⚠️  Suggested"
        
        print(f"\n   [{i:2d}] Plan ID: {plan_id_display}")
        print(f"       {category} | User: {user_id[:36]}... | Type: {plan_type}")
        print(f"       Overall: {result.overall_score:5.1f}/100 | Nutrition: {result.nutrition_score:5.1f} | Variety: {result.variety_score:5.1f} | Balance: {result.balance_score:5.1f} | Feasibility: {result.feasibility_score:5.1f}")
    
    if len(results) > 10:
        print(f"\n   ... and {len(results) - 10} more plans")
    
    # Print aggregated statistics
    print(f"\n📈 Aggregated Scores:")
    print(f"   {'Metric':<20} {'Mean':>10} {'Median':>10} {'Std':>10} {'Min':>10} {'Max':>10}")
    print(f"   {'-'*70}")
    
    for metric in ["overall_score", "nutrition_score", "variety_score", "balance_score", "feasibility_score"]:
        stats = aggregated.get(metric, {})
        print(f"   {metric:<20} {stats.get('mean', 0):>10.2f} {stats.get('median', 0):>10.2f} {stats.get('std', 0):>10.2f} {stats.get('min', 0):>10.2f} {stats.get('max', 0):>10.2f}")
    
    # Breakdown by source and plan type
    print(f"\n📊 Breakdown by Plan Type:")
    
    suggested_results = []
    accepted_results = []
    day_plan_results = []
    week_plan_results = []
    
    for i, result in enumerate(results):
        plan = output_plans[i] if i < len(output_plans) else {}
        if plan.get("source") == "MealLogEntry":
            accepted_results.append(result)
        else:
            suggested_results.append(result)
            plan_type = plan.get("plan_type", "day")
            # Week plans đã được expand thành day plans, nên không còn week_plan_results
            # Tất cả đều là day plans bây giờ
            day_plan_results.append(result)
    
    if suggested_results:
        suggested_agg = evaluator.aggregate_results(suggested_results)
        print(f"   Suggested Plans (MealPlan) - {len(suggested_results)} plans:")
        print(f"      Overall Score: {suggested_agg['overall_score']['mean']:.2f} ± {suggested_agg['overall_score']['std']:.2f}")
        if day_plan_results:
            day_agg = evaluator.aggregate_results(day_plan_results)
            print(f"      - Day Plans ({len(day_plan_results)}): {day_agg['overall_score']['mean']:.2f}")
            # Đếm số day plans từ week plans
            week_day_count = sum(1 for i, p in enumerate(output_plans[:len(results)]) 
                               if i < len(results) and p.get("original_plan_id"))
            if week_day_count > 0:
                print(f"        (including {week_day_count} days from week plans)")
    
    if accepted_results:
        accepted_agg = evaluator.aggregate_results(accepted_results)
        print(f"   Accepted/Actual Plans (MealLogEntry) - {len(accepted_results)} plans:")
        print(f"      Overall Score: {accepted_agg['overall_score']['mean']:.2f} ± {accepted_agg['overall_score']['std']:.2f}")
    
    # Performance distribution
    if results:
        overall_scores = [r.overall_score for r in results]
        excellent = sum(1 for s in overall_scores if s >= 80)
        good = sum(1 for s in overall_scores if 70 <= s < 80)
        fair = sum(1 for s in overall_scores if 60 <= s < 70)
        poor = sum(1 for s in overall_scores if s < 60)
        
        print(f"\n📈 Performance Distribution:")
        print(f"   Excellent (≥80):    {excellent:3d} ({excellent/len(results)*100:5.1f}%)")
        print(f"   Good (70-80):       {good:3d} ({good/len(results)*100:5.1f}%)")
        print(f"   Fair (60-70):       {fair:3d} ({fair/len(results)*100:5.1f}%)")
        print(f"   Poor (<60):         {poor:3d} ({poor/len(results)*100:5.1f}%)")
    
    # Save results with detailed metadata (similar to nutrition_error)
    def serialize_datetime(obj):
        """Convert datetime objects to ISO format strings for JSON serialization."""
        if isinstance(obj, datetime):
            return obj.isoformat()
        raise TypeError(f"Object of type {type(obj)} is not JSON serializable")
    
    output = {
        "method": "llm_judge",
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
    
    # Add individual results with detailed metadata
    # Sử dụng output_plans và output_profiles (đã được expand)
    for i, result in enumerate(results):
        result_dict = result.to_dict()
        plan = output_plans[i] if i < len(output_plans) else {}
        profile = output_profiles[i] if i < len(output_profiles) else {}
        
        # Convert datetime to string if present
        plan_date = plan.get("start_date")
        if plan_date and isinstance(plan_date, datetime):
            plan_date = plan_date.isoformat()
        elif plan_date and isinstance(plan_date, str):
            pass
        else:
            plan_date = None
        
        # Extract meal plan details - phân biệt MealPlan vs MealLogEntry
        source = plan.get("source", "MealPlan")
        total_macros = plan.get("total_macros", {})
        meal_list = []
        
        if source == "MealPlan":
            # MealPlan: lấy từ meals structure (đã được reconstruct từ MealPlanItem)
            meals = plan.get("meals", {})
            
            for meal_type, meal_data in meals.items():
                meal_info = {
                    "meal_type": meal_type,
                    "main_dish": None,
                    "servings": meal_data.get("servings", 1.0),
                    "accompaniments": [],
                    "macros": meal_data.get("macros", {})
                }
                
                # Main dish
                recipe = meal_data.get("recipe", {})
                if recipe:
                    meal_info["main_dish"] = {
                        "dish_name": recipe.get("dish_name", "Unknown"),
                        "food_id": recipe.get("food_id"),
                    }
                
                # Accompaniments
                accompaniments = meal_data.get("accompaniments", [])
                for acc in accompaniments:
                    acc_recipe = acc.get("recipe", {})
                    if acc_recipe:
                        meal_info["accompaniments"].append({
                            "dish_name": acc_recipe.get("dish_name", "Unknown"),
                            "food_id": acc_recipe.get("food_id"),
                            "servings": acc.get("servings", 1.0),
                            "type": acc.get("type", "main"),
                        })
                
                meal_list.append(meal_info)
        
        elif source == "MealLogEntry":
            # MealLogEntry: dữ liệu đã có sẵn trong thuộc tính
            # Có thể có meal_description, parsed_dish, ingredients
            meal_description = plan.get("meal_description")
            parsed_dish = plan.get("parsed_dish")
            ingredients = plan.get("ingredients", [])
            
            # Nếu có parsed_dish, tạo meal info từ đó
            if parsed_dish:
                if isinstance(parsed_dish, str):
                    try:
                        parsed_dish = json.loads(parsed_dish)
                    except:
                        parsed_dish = {"dish_name": parsed_dish}
                
                meal_info = {
                    "meal_type": "unknown",  # MealLogEntry không có meal_type rõ ràng
                    "main_dish": {
                        "dish_name": parsed_dish.get("dish_name", meal_description or "Unknown"),
                        "food_id": parsed_dish.get("food_id"),
                    },
                    "servings": parsed_dish.get("servings", plan.get("portion_size", 1.0)),
                    "accompaniments": [],
                    "macros": {}  # Sẽ lấy từ calculated_macros tổng
                }
                meal_list.append(meal_info)
            elif meal_description:
                # Fallback: chỉ có description
                meal_info = {
                    "meal_type": "unknown",
                    "main_dish": {
                        "dish_name": meal_description,
                        "food_id": None,
                    },
                    "servings": plan.get("portion_size", 1.0),
                    "accompaniments": [],
                    "macros": {}
                }
                meal_list.append(meal_info)
            
            # Nếu có ingredients, thêm vào accompaniments
            if ingredients and meal_list:
                if isinstance(ingredients, str):
                    try:
                        ingredients = json.loads(ingredients)
                    except:
                        ingredients = [ingredients] if ingredients else []
                
                for ing in ingredients:
                    if isinstance(ing, dict):
                        meal_list[0]["accompaniments"].append({
                            "dish_name": ing.get("name", str(ing)),
                            "food_id": ing.get("food_id"),
                            "servings": ing.get("servings", 1.0),
                            "type": "ingredient",
                        })
                    else:
                        meal_list[0]["accompaniments"].append({
                            "dish_name": str(ing),
                            "food_id": None,
                            "servings": 1.0,
                            "type": "ingredient",
                        })
        
        # Extract user profile targets
        target_macros = {
            "kcal": profile.get("tdee_kcal", 0),
            "protein_g": profile.get("protein_g", 0),
            "carb_g": profile.get("carb_g", 0),
            "fat_g": profile.get("fat_g", 0),
        }
        
        # Calculate actual macros (normalize week plans to daily)
        actual_macros = {
            "kcal": total_macros.get("kcal", 0),
            "protein_g": total_macros.get("protein_g", 0),
            "carb_g": total_macros.get("carb_g", 0),
            "fat_g": total_macros.get("fat_g", 0),
        }
        
        plan_type = plan.get("plan_type", "day")
        # Không normalize week plans - week plans đã được expand thành day plans trong evaluate_batch
        # Nếu vẫn là week plan ở đây, giữ nguyên macros (có thể là tổng của cả tuần)
        
        # Calculate differences
        macro_differences = {
            "kcal": actual_macros["kcal"] - target_macros["kcal"],
            "protein_g": actual_macros["protein_g"] - target_macros["protein_g"],
            "carb_g": actual_macros["carb_g"] - target_macros["carb_g"],
            "fat_g": actual_macros["fat_g"] - target_macros["fat_g"],
        }
        
        result_dict["metadata"] = {
            "user_id": profile.get("user_id"),
            "plan_id": plan.get("plan_id"),
            "source": plan.get("source", "MealPlan"),
            "plan_type": plan_type,
            "plan_date": plan_date,
        }
        
        # Add detailed plan log
        result_dict["plan_details"] = {
            "target_macros": target_macros,
            "actual_macros": actual_macros,
            "macro_differences": macro_differences,
            "meals": meal_list,
            "user_profile": {
                "age": profile.get("age"),
                "gender": profile.get("gender"),
                "activity_level": profile.get("activity_level"),
                "dietary_preferences": profile.get("dietary_preferences", []),
                "allergies": profile.get("allergies", []),
            }
        }
        
        output["individual_results"].append(result_dict)
    
    output_file = Path("evaluation/results/llm_judge_test.json")
    output_file.parent.mkdir(parents=True, exist_ok=True)
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False, default=serialize_datetime)
    
    print(f"\n💾 Results saved to: {output_file}")
    print("=" * 80)
    
    return output



    """Chạy test BERTScore."""
    print("=" * 80)
    print("BERTScore Evaluation Test")
    print("=" * 80)
    
    if BERTScoreEvaluator is None:
        print("❌ BERTScore not available. Install with: pip install bert-score")
        return None
    
    try:
        evaluator = BERTScoreEvaluator()
    except Exception as e:
        print(f"❌ Failed to initialize BERTScore: {e}")
        return None
    
    # Get test data from Weaviate
    print("\n📥 Loading data from Weaviate...")
    try:
        client_manager = create_client_manager()
        if not client_manager.is_client:
            print("❌ Weaviate client not available. Cannot run BERTScore test without data.")
            return None
        
        # Load a small sample for BERTScore evaluation
        user_ids = get_all_user_ids_from_weaviate(client_manager, limit=3)
        if not user_ids:
            print("❌ No users found in Weaviate.")
            return None
        
        meal_plans, user_profiles = load_evaluation_data_from_weaviate(
            user_ids, client_manager, plan_type="day", use_latest=True
        )
        print(f"✅ Loaded: {len(meal_plans)} meal plans, {len(user_profiles)} profiles")
    except Exception as e:
        print(f"❌ Error loading from Weaviate: {e}")
        return None
    
    if not meal_plans or not user_profiles:
        print("❌ No data available for evaluation.")
        return None
    
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
        asyncio.run(run_llm_judge_test(
            use_weaviate=not args.use_mock,
            user_ids=args.user_ids,
            use_meal_logs=args.use_meal_logs,
            date=date,
            load_all=args.load_all
        ))
    


if __name__ == "__main__":
    main()

