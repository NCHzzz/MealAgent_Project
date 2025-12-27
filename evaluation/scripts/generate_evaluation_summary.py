"""
Script để tạo file tổng hợp đánh giá từ kết quả LLM Judge evaluation.

File này phân tích kết quả evaluation và tạo báo cáo tổng hợp để cải thiện chất lượng meal plans.
"""

import json
from pathlib import Path
from typing import Dict, Any, List
from datetime import datetime


def load_evaluation_results(file_path: str = "evaluation/results/llm_judge_test.json") -> Dict[str, Any]:
    """Load kết quả evaluation từ JSON file."""
    with open(file_path, "r", encoding="utf-8") as f:
        return json.load(f)


def analyze_results(results: Dict[str, Any]) -> Dict[str, Any]:
    """Phân tích kết quả evaluation và tạo insights."""
    
    individual_results = results.get("individual_results", [])
    aggregated = results.get("aggregated", {})
    metadata = results.get("metadata", {})
    
    # Phân loại plans theo source
    meal_plan_results = [r for r in individual_results if r.get("metadata", {}).get("source") == "MealPlan"]
    meal_log_results = [r for r in individual_results if r.get("metadata", {}).get("source") == "MealLogEntry"]
    
    # Phân loại theo score ranges
    excellent = [r for r in individual_results if r.get("overall_score", 0) >= 80]
    good = [r for r in individual_results if 70 <= r.get("overall_score", 0) < 80]
    fair = [r for r in individual_results if 60 <= r.get("overall_score", 0) < 70]
    poor = [r for r in individual_results if r.get("overall_score", 0) < 60]
    
    # Phân tích các vấn đề phổ biến
    common_issues = {
        "low_protein": [],
        "high_calories": [],
        "high_fat": [],
        "low_variety": [],
        "poor_balance": [],
    }
    
    for result in individual_results:
        plan_details = result.get("plan_details", {})
        macro_diff = plan_details.get("macro_differences", {})
        scores = {
            "overall": result.get("overall_score", 0),
            "nutrition": result.get("nutrition_score", 0),
            "variety": result.get("variety_score", 0),
            "balance": result.get("balance_score", 0),
        }
        
        # Low protein
        if macro_diff.get("protein_g", 0) < -50:
            common_issues["low_protein"].append({
                "plan_id": result.get("metadata", {}).get("plan_id"),
                "protein_diff": macro_diff.get("protein_g"),
                "score": scores,
            })
        
        # High calories
        if macro_diff.get("kcal", 0) > 500:
            common_issues["high_calories"].append({
                "plan_id": result.get("metadata", {}).get("plan_id"),
                "calorie_diff": macro_diff.get("kcal"),
                "score": scores,
            })
        
        # High fat
        if macro_diff.get("fat_g", 0) > 50:
            common_issues["high_fat"].append({
                "plan_id": result.get("metadata", {}).get("plan_id"),
                "fat_diff": macro_diff.get("fat_g"),
                "score": scores,
            })
        
        # Low variety
        if result.get("variety_score", 0) < 40:
            common_issues["low_variety"].append({
                "plan_id": result.get("metadata", {}).get("plan_id"),
                "variety_score": result.get("variety_score", 0),
            })
        
        # Poor balance
        if result.get("balance_score", 0) < 40:
            common_issues["poor_balance"].append({
                "plan_id": result.get("metadata", {}).get("plan_id"),
                "balance_score": result.get("balance_score", 0),
            })
    
    # Tìm best và worst plans
    best_plans = sorted(individual_results, key=lambda x: x.get("overall_score", 0), reverse=True)[:5]
    worst_plans = sorted(individual_results, key=lambda x: x.get("overall_score", 0))[:5]
    
    # Phân tích suggestions phổ biến
    all_suggestions = []
    for result in individual_results:
        suggestions = result.get("suggestions", [])
        all_suggestions.extend(suggestions)
    
    # Đếm frequency của suggestions (simplified)
    suggestion_keywords = {}
    for suggestion in all_suggestions:
        if isinstance(suggestion, str):
            # Extract keywords
            keywords = ["protein", "calo", "carb", "fat", "tinh bột", "đạm", "chất béo", "rau"]
            for keyword in keywords:
                if keyword.lower() in suggestion.lower():
                    suggestion_keywords[keyword] = suggestion_keywords.get(keyword, 0) + 1
    
    return {
        "summary": {
            "total_evaluations": len(individual_results),
            "meal_plan_count": len(meal_plan_results),
            "meal_log_count": len(meal_log_results),
            "excellent_count": len(excellent),
            "good_count": len(good),
            "fair_count": len(fair),
            "poor_count": len(poor),
        },
        "aggregated_scores": aggregated,
        "performance_distribution": {
            "excellent": len(excellent),
            "good": len(good),
            "fair": len(fair),
            "poor": len(poor),
        },
        "common_issues": {
            "low_protein_count": len(common_issues["low_protein"]),
            "high_calories_count": len(common_issues["high_calories"]),
            "high_fat_count": len(common_issues["high_fat"]),
            "low_variety_count": len(common_issues["low_variety"]),
            "poor_balance_count": len(common_issues["poor_balance"]),
            "top_issues": common_issues,
        },
        "best_plans": [
            {
                "plan_id": r.get("metadata", {}).get("plan_id"),
                "overall_score": r.get("overall_score", 0),
                "source": r.get("metadata", {}).get("source"),
            }
            for r in best_plans
        ],
        "worst_plans": [
            {
                "plan_id": r.get("metadata", {}).get("plan_id"),
                "overall_score": r.get("overall_score", 0),
                "source": r.get("metadata", {}).get("source"),
            }
            for r in worst_plans
        ],
        "suggestion_insights": suggestion_keywords,
    }


def generate_summary_report(analysis: Dict[str, Any], output_file: str = "evaluation/results/llm_judge_summary.md"):
    """Tạo file markdown summary report."""
    
    summary = analysis["summary"]
    aggregated = analysis["aggregated_scores"]
    issues = analysis["common_issues"]
    
    report = f"""# LLM Judge Evaluation Summary Report

Generated: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

## Overview

- **Total Evaluations**: {summary['total_evaluations']}
- **Meal Plans (Suggested)**: {summary['meal_plan_count']}
- **Meal Logs (Accepted/Actual)**: {summary['meal_log_count']}

## Performance Distribution

- **Excellent (≥80)**: {summary['excellent_count']} ({summary['excellent_count']/summary['total_evaluations']*100:.1f}%)
- **Good (70-80)**: {summary['good_count']} ({summary['good_count']/summary['total_evaluations']*100:.1f}%)
- **Fair (60-70)**: {summary['fair_count']} ({summary['fair_count']/summary['total_evaluations']*100:.1f}%)
- **Poor (<60)**: {summary['poor_count']} ({summary['poor_count']/summary['total_evaluations']*100:.1f}%)

## Aggregated Scores

### Overall Score
- Mean: {aggregated.get('overall_score', {}).get('mean', 0):.2f}
- Median: {aggregated.get('overall_score', {}).get('median', 0):.2f}
- Std: {aggregated.get('overall_score', {}).get('std', 0):.2f}
- Range: {aggregated.get('overall_score', {}).get('min', 0):.1f} - {aggregated.get('overall_score', {}).get('max', 0):.1f}

### Nutrition Score
- Mean: {aggregated.get('nutrition_score', {}).get('mean', 0):.2f}
- Median: {aggregated.get('nutrition_score', {}).get('median', 0):.2f}
- Std: {aggregated.get('nutrition_score', {}).get('std', 0):.2f}

### Variety Score
- Mean: {aggregated.get('variety_score', {}).get('mean', 0):.2f}
- Median: {aggregated.get('variety_score', {}).get('median', 0):.2f}
- Std: {aggregated.get('variety_score', {}).get('std', 0):.2f}

### Balance Score
- Mean: {aggregated.get('balance_score', {}).get('mean', 0):.2f}
- Median: {aggregated.get('balance_score', {}).get('median', 0):.2f}
- Std: {aggregated.get('balance_score', {}).get('std', 0):.2f}

### Feasibility Score
- Mean: {aggregated.get('feasibility_score', {}).get('mean', 0):.2f}
- Median: {aggregated.get('feasibility_score', {}).get('median', 0):.2f}
- Std: {aggregated.get('feasibility_score', {}).get('std', 0):.2f}

## Common Issues

### Low Protein (<50g below target)
**Count**: {issues['low_protein_count']} plans

### High Calories (>500kcal above target)
**Count**: {issues['high_calories_count']} plans

### High Fat (>50g above target)
**Count**: {issues['high_fat_count']} plans

### Low Variety (Score <40)
**Count**: {issues['low_variety_count']} plans

### Poor Balance (Score <40)
**Count**: {issues['poor_balance_count']} plans

## Top 5 Best Plans

"""
    
    for i, plan in enumerate(analysis["best_plans"], 1):
        report += f"{i}. Plan ID: `{plan['plan_id']}` - Score: {plan['overall_score']:.1f} ({plan['source']})\n"
    
    report += "\n## Top 5 Worst Plans\n\n"
    
    for i, plan in enumerate(analysis["worst_plans"], 1):
        report += f"{i}. Plan ID: `{plan['plan_id']}` - Score: {plan['overall_score']:.1f} ({plan['source']})\n"
    
    report += "\n## Recommendations\n\n"
    report += "### For Meal Plan Generation:\n"
    report += "1. **Increase Protein**: Many plans lack sufficient protein. Consider adding more lean protein sources.\n"
    report += "2. **Control Calories**: Many plans exceed calorie targets. Reduce portion sizes or choose lower-calorie options.\n"
    report += "3. **Reduce Fat**: High-fat plans are common. Use cooking methods that reduce fat (steaming, grilling).\n"
    report += "4. **Improve Variety**: Add more diverse dishes to avoid repetition.\n"
    report += "5. **Better Balance**: Distribute macros more evenly across meals.\n"
    
    report += "\n### For System Improvement:\n"
    report += "- Review and fix data quality issues (especially MealLogEntry with unrealistic macros)\n"
    report += "- Implement better macro validation before saving plans\n"
    report += "- Add variety constraints to meal plan generation\n"
    report += "- Improve portion size estimation\n"
    
    # Save report
    output_path = Path(output_file)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(report)
    
    print(f"✅ Summary report saved to: {output_file}")


def main():
    """Main function."""
    print("=" * 80)
    print("Generating LLM Judge Evaluation Summary")
    print("=" * 80)
    
    # Load results
    results_file = "evaluation/results/llm_judge_test.json"
    print(f"\n📥 Loading results from: {results_file}")
    results = load_evaluation_results(results_file)
    
    # Analyze
    print("📊 Analyzing results...")
    analysis = analyze_results(results)
    
    # Generate summary
    print("📝 Generating summary report...")
    generate_summary_report(analysis)
    
    # Also save JSON summary
    summary_json = "evaluation/results/llm_judge_summary.json"
    with open(summary_json, "w", encoding="utf-8") as f:
        json.dump(analysis, f, indent=2, ensure_ascii=False)
    print(f"✅ JSON summary saved to: {summary_json}")
    
    print("\n" + "=" * 80)
    print("Summary Generation Complete!")
    print("=" * 80)


if __name__ == "__main__":
    main()

