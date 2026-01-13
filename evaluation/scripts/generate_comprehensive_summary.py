"""
Script để tạo file tổng hợp so sánh tất cả models và file giải thích evaluation criteria.

Tạo 2 files:
1. llm_judge_comprehensive_summary.md - So sánh tất cả models (format giống llm_judge_summary.md)
2. llm_judge_evaluation_methodology.md - Giải thích ngắn gọn về evaluation criteria và prompt
"""

import json
from pathlib import Path
from typing import Dict, Any, List
from datetime import datetime


def load_all_model_summaries(results_dir: Path) -> List[Dict[str, Any]]:
    """Load tất cả các file summary JSON của từng model."""
    summaries = []
    
    # Tìm tất cả các file summary JSON
    for summary_file in results_dir.glob("llm_judge_summary__*.json"):
        try:
            with summary_file.open("r", encoding="utf-8") as f:
                data = json.load(f)
                # Extract model name from filename
                model_name = summary_file.stem.replace("llm_judge_summary__", "")
                data["model_name"] = model_name
                summaries.append(data)
        except Exception as e:
            print(f"⚠️  Failed to load {summary_file}: {e}")
            continue
    
    return summaries


def generate_comprehensive_summary(summaries: List[Dict[str, Any]], output_path: Path) -> None:
    """Tạo file tổng hợp so sánh tất cả models."""
    
    if not summaries:
        print("❌ No model summaries found!")
        return
    
    # Sắp xếp theo overall mean (cao → thấp)
    def get_overall_mean(s: Dict[str, Any]) -> float:
        agg = s.get("aggregated_scores", {}) or {}
        return float(agg.get("overall_score", {}).get("mean", 0.0) or 0.0)
    
    sorted_summaries = sorted(summaries, key=get_overall_mean, reverse=True)
    
    lines: List[str] = []
    lines.append("# LLM Judge Evaluation Summary Report - All Models Comparison\n")
    lines.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    
    # Overview - lấy từ model đầu tiên (tất cả models đều cùng dataset)
    first_summary = sorted_summaries[0]
    summary_info = first_summary.get("summary", {})
    total_eval = summary_info.get("total_evaluations", 0)
    meal_plan_count = summary_info.get("meal_plan_count", 0)
    meal_log_count = summary_info.get("meal_log_count", 0)
    
    lines.append("## Overview\n")
    lines.append(f"- **Total Evaluations**: {total_eval}\n")
    lines.append(f"- **Meal Plans (Suggested)**: {meal_plan_count}\n")
    lines.append(f"- **Meal Logs (Accepted/Actual)**: {meal_log_count}\n")
    lines.append(f"- **Models Evaluated**: {len(summaries)}\n")
    
    # Models comparison table
    lines.append("\n## Models Comparison\n")
    lines.append("| Model | Overall Mean | Nutrition | Variety | Balance | Feasibility | Excellent | Good | Fair | Poor |\n")
    lines.append("|-------|-------------:|----------:|--------:|--------:|------------:|----------:|-----:|-----:|-----:|\n")
    
    for s in sorted_summaries:
        agg = s.get("aggregated_scores", {}) or {}
        dist = s.get("performance_distribution", {}) or {}
        model_name = s.get("model_name", "unknown")
        
        overall = agg.get("overall_score", {}).get("mean", 0.0)
        nutrition = agg.get("nutrition_score", {}).get("mean", 0.0)
        variety = agg.get("variety_score", {}).get("mean", 0.0)
        balance = agg.get("balance_score", {}).get("mean", 0.0)
        feasibility = agg.get("feasibility_score", {}).get("mean", 0.0)
        
        excellent = dist.get("excellent", 0)
        good = dist.get("good", 0)
        fair = dist.get("fair", 0)
        poor = dist.get("poor", 0)
        
        lines.append(
            f"| {model_name} | {overall:.2f} | {nutrition:.2f} | {variety:.2f} | "
            f"{balance:.2f} | {feasibility:.2f} | {excellent} | {good} | {fair} | {poor} |\n"
        )
    
    # Aggregated scores across all models
    lines.append("\n## Aggregated Scores (Average Across All Models)\n")
    
    # Tính trung bình của tất cả models
    all_overall = []
    all_nutrition = []
    all_variety = []
    all_balance = []
    all_feasibility = []
    
    for s in sorted_summaries:
        agg = s.get("aggregated_scores", {}) or {}
        all_overall.append(agg.get("overall_score", {}).get("mean", 0.0))
        all_nutrition.append(agg.get("nutrition_score", {}).get("mean", 0.0))
        all_variety.append(agg.get("variety_score", {}).get("mean", 0.0))
        all_balance.append(agg.get("balance_score", {}).get("mean", 0.0))
        all_feasibility.append(agg.get("feasibility_score", {}).get("mean", 0.0))
    
    avg_overall = sum(all_overall) / len(all_overall) if all_overall else 0.0
    avg_nutrition = sum(all_nutrition) / len(all_nutrition) if all_nutrition else 0.0
    avg_variety = sum(all_variety) / len(all_variety) if all_variety else 0.0
    avg_balance = sum(all_balance) / len(all_balance) if all_balance else 0.0
    avg_feasibility = sum(all_feasibility) / len(all_feasibility) if all_feasibility else 0.0
    
    lines.append("### Overall Score\n")
    lines.append(f"- Mean: {avg_overall:.2f}\n")
    lines.append(f"- Range: {min(all_overall):.2f} - {max(all_overall):.2f}\n")
    
    lines.append("\n### Nutrition Score\n")
    lines.append(f"- Mean: {avg_nutrition:.2f}\n")
    lines.append(f"- Range: {min(all_nutrition):.2f} - {max(all_nutrition):.2f}\n")
    
    lines.append("\n### Variety Score\n")
    lines.append(f"- Mean: {avg_variety:.2f}\n")
    lines.append(f"- Range: {min(all_variety):.2f} - {max(all_variety):.2f}\n")
    
    lines.append("\n### Balance Score\n")
    lines.append(f"- Mean: {avg_balance:.2f}\n")
    lines.append(f"- Range: {min(all_balance):.2f} - {max(all_balance):.2f}\n")
    
    lines.append("\n### Feasibility Score\n")
    lines.append(f"- Mean: {avg_feasibility:.2f}\n")
    lines.append(f"- Range: {min(all_feasibility):.2f} - {max(all_feasibility):.2f}\n")
    
    # Common issues (tổng hợp từ tất cả models)
    lines.append("\n## Common Issues (Aggregated Across All Models)\n")
    
    total_low_protein = sum(s.get("common_issues", {}).get("low_protein_count", 0) for s in sorted_summaries)
    total_high_calories = sum(s.get("common_issues", {}).get("high_calories_count", 0) for s in sorted_summaries)
    total_high_fat = sum(s.get("common_issues", {}).get("high_fat_count", 0) for s in sorted_summaries)
    total_low_variety = sum(s.get("common_issues", {}).get("low_variety_count", 0) for s in sorted_summaries)
    total_poor_balance = sum(s.get("common_issues", {}).get("poor_balance_count", 0) for s in sorted_summaries)
    
    lines.append("### Low Protein (<50g below target)\n")
    lines.append(f"**Average Count**: {total_low_protein / len(sorted_summaries):.1f} plans\n")
    
    lines.append("\n### High Calories (>500kcal above target)\n")
    lines.append(f"**Average Count**: {total_high_calories / len(sorted_summaries):.1f} plans\n")
    
    lines.append("\n### High Fat (>50g above target)\n")
    lines.append(f"**Average Count**: {total_high_fat / len(sorted_summaries):.1f} plans\n")
    
    lines.append("\n### Low Variety (Score <40)\n")
    lines.append(f"**Average Count**: {total_low_variety / len(sorted_summaries):.1f} plans\n")
    
    lines.append("\n### Poor Balance (Score <40)\n")
    lines.append(f"**Average Count**: {total_poor_balance / len(sorted_summaries):.1f} plans\n")
    
    # Best and worst plans (lấy từ model tốt nhất)
    best_model = sorted_summaries[0]
    best_plans = best_model.get("best_plans", [])[:5]
    worst_plans = best_model.get("worst_plans", [])[:5]
    
    lines.append("\n## Top 5 Best Plans\n")
    for i, plan in enumerate(best_plans, 1):
        plan_id = plan.get("plan_id", "unknown")
        score = plan.get("overall_score", 0.0)
        source = plan.get("source", "unknown")
        lines.append(f"{i}. Plan ID: `{plan_id}` - Score: {score:.1f} ({source})\n")
    
    lines.append("\n## Top 5 Worst Plans\n")
    for i, plan in enumerate(worst_plans, 1):
        plan_id = plan.get("plan_id", "unknown")
        score = plan.get("overall_score", 0.0)
        source = plan.get("source", "unknown")
        lines.append(f"{i}. Plan ID: `{plan_id}` - Score: {score:.1f} ({source})\n")
    
    # Recommendations
    lines.append("\n## Recommendations\n")
    lines.append("\n### For Meal Plan Generation:\n")
    lines.append("1. **Increase Protein**: Many plans lack sufficient protein. Consider adding more lean protein sources.\n")
    lines.append("2. **Control Calories**: Many plans exceed calorie targets. Reduce portion sizes or choose lower-calorie options.\n")
    lines.append("3. **Reduce Fat**: High-fat plans are common. Use cooking methods that reduce fat (steaming, grilling).\n")
    lines.append("4. **Improve Variety**: Add more diverse dishes to avoid repetition.\n")
    lines.append("5. **Better Balance**: Distribute macros more evenly across meals.\n")
    
    lines.append("\n### For System Improvement:\n")
    lines.append("- Review and fix data quality issues (especially MealLogEntry with unrealistic macros)\n")
    lines.append("- Implement better macro validation before saving plans\n")
    lines.append("- Add variety constraints to meal plan generation\n")
    lines.append("- Improve portion size estimation\n")
    
    # Write file
    with output_path.open("w", encoding="utf-8") as f:
        f.writelines(lines)
    
    print(f"✅ Comprehensive summary saved to: {output_path}")


def generate_methodology_doc(output_path: Path) -> None:
    """Tạo file giải thích ngắn gọn về evaluation methodology."""
    
    lines: List[str] = []
    lines.append("# LLM-as-a-Judge Evaluation Methodology\n")
    lines.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    
    lines.append("\n## Overview\n")
    lines.append("This evaluation uses Large Language Models (LLMs) as judges to assess meal planning quality. ")
    lines.append("Each LLM acts as a nutrition expert and evaluates meal plans based on four key criteria.\n")
    
    lines.append("\n## Evaluation Criteria\n")
    lines.append("Each meal plan is scored on a scale of 0-100 for the following four dimensions:\n")
    
    lines.append("\n### 1. Nutrition Score\n")
    lines.append("**Definition**: Accuracy of nutritional content compared to user's target macros.\n")
    lines.append("- **85-100**: Very close to targets, or at least 2-3 macros are near target, easily adjustable\n")
    lines.append("- **75-85**: Some deviation but reasonable, at least 1 macro close to target\n")
    lines.append("- **65-75**: Deviation present but not severe, still has positive aspects\n")
    lines.append("- **<65**: Severe deviation (e.g., calories doubled/halved, protein <50% of target)\n")
    
    lines.append("\n### 2. Variety Score\n")
    lines.append("**Definition**: Diversity of dishes, ingredients, and cooking methods.\n")
    lines.append("- **85-100**: Clear diversity, at least 2-3 different dishes per day\n")
    lines.append("- **75-85**: Some variation between meals, at least 2 different dishes\n")
    lines.append("- **65-75**: Some repetition but still has differences in ingredients or cooking methods\n")
    lines.append("- **<65**: Almost completely identical, no diversity\n")
    
    lines.append("\n### 3. Balance Score\n")
    lines.append("**Definition**: Distribution of nutrients across meals throughout the day.\n")
    lines.append("- **85-100**: Reasonable distribution, clear structure with 3 main meals\n")
    lines.append("- **75-85**: Basic structure, meals not too imbalanced\n")
    lines.append("- **65-75**: Some imbalance (e.g., dinner heavier) but still acceptable\n")
    lines.append("- **<65**: Severe imbalance (e.g., all calories in one meal)\n")
    
    lines.append("\n### 4. Feasibility Score\n")
    lines.append("**Definition**: Practicality and realism of the meal plan for daily implementation.\n")
    lines.append("- **85-100**: Familiar dishes, easy-to-find ingredients, simple cooking, suitable for busy people\n")
    lines.append("- **75-85**: Achievable, only a few dishes slightly complex\n")
    lines.append("- **65-75**: Challenging (time-consuming, many steps) but still doable\n")
    lines.append("- **<65**: Clearly unrealistic (too many exotic dishes, hard-to-find ingredients, very long cooking time)\n")
    
    lines.append("\n### Overall Score\n")
    lines.append("The overall score is calculated as the **average of the four criteria** (Nutrition, Variety, Balance, Feasibility).\n")
    lines.append("- **Target Range**: Most plans should score 70-85 (Good to Excellent)\n")
    lines.append("- **Excellent (≥80)**: High-quality plans\n")
    lines.append("- **Good (70-80)**: Acceptable plans with minor issues\n")
    lines.append("- **Fair (60-70)**: Plans with noticeable problems but still acceptable\n")
    lines.append("- **Poor (<60)**: Plans with serious issues\n")
    
    lines.append("\n## Scoring Philosophy\n")
    lines.append("The evaluation follows a **positive and encouraging approach**:\n")
    lines.append("- **Baseline**: 70-80 points is considered \"normal/good\" for most practical meal plans\n")
    lines.append("- **High scores (80-100)**: Given for good plans or plans that can be easily improved with minor adjustments\n")
    lines.append("- **Low scores (<60)**: Only given when there are serious, unacceptable issues\n")
    lines.append("- **Focus on strengths**: The evaluation emphasizes what the plan does well, especially practicality and long-term sustainability\n")
    
    lines.append("\n## Prompt Structure\n")
    lines.append("The LLM judge receives a prompt containing:\n")
    lines.append("1. **User Profile**: Age, gender, activity level, dietary preferences, allergies, target macros (TDEE, protein, carb, fat)\n")
    lines.append("2. **Meal Plan Details**: Total macros, individual meals with dishes, servings, and macros per meal\n")
    lines.append("3. **Evaluation Instructions**: Detailed scoring guidelines for each criterion\n")
    lines.append("4. **Output Format**: Strict JSON format requirements\n")
    
    lines.append("\n## Models Used\n")
    lines.append("Multiple LLM models are used to ensure robust evaluation:\n")
    lines.append("- `google/gemini-3-flash-preview`\n")
    lines.append("- `x-ai/grok-4.1-fast`\n")
    lines.append("- `xiaomi/mimo-v2-flash:free`\n")
    lines.append("- `openai/gpt-5-mini`\n")
    
    lines.append("\n## Output Format\n")
    lines.append("Each evaluation returns a JSON object with:\n")
    lines.append("- `overall_score`: Float (0-100)\n")
    lines.append("- `nutrition_score`: Float (0-100)\n")
    lines.append("- `variety_score`: Float (0-100)\n")
    lines.append("- `balance_score`: Float (0-100)\n")
    lines.append("- `feasibility_score`: Float (0-100)\n")
    lines.append("- `feedback`: Overall comment in Vietnamese (2-3 sentences)\n")
    lines.append("- `strengths`: List of positive aspects\n")
    lines.append("- `suggestions`: List of improvement recommendations\n")
    
    lines.append("\n## Data Processing\n")
    lines.append("- **Week Plans**: Automatically expanded into individual day plans for evaluation\n")
    lines.append("- **Outlier Filtering**: Plans with extreme calorie values (>4x or <0.25x target) are excluded\n")
    lines.append("- **Batch Evaluation**: Multiple plans are evaluated together when possible to optimize API usage\n")
    
    # Write file
    with output_path.open("w", encoding="utf-8") as f:
        f.writelines(lines)
    
    print(f"✅ Methodology documentation saved to: {output_path}")


def main() -> None:
    """Entry point: tạo cả 2 files tổng hợp."""
    results_dir = Path("evaluation/results")
    
    print("=" * 80)
    print("Generating Comprehensive LLM Judge Summary and Methodology Documentation")
    print("=" * 80)
    
    # Load all model summaries
    print("\n📥 Loading model summaries...")
    summaries = load_all_model_summaries(results_dir)
    
    if not summaries:
        print("❌ No model summaries found!")
        return
    
    print(f"✅ Loaded {len(summaries)} model summaries")
    
    # Generate comprehensive summary
    print("\n📝 Generating comprehensive summary...")
    comprehensive_path = results_dir / "llm_judge_comprehensive_summary.md"
    generate_comprehensive_summary(summaries, comprehensive_path)
    
    # Generate methodology documentation
    print("\n📝 Generating methodology documentation...")
    methodology_path = results_dir / "llm_judge_evaluation_methodology.md"
    generate_methodology_doc(methodology_path)
    
    print("\n✅ Done.")
    print("=" * 80)


if __name__ == "__main__":
    main()


