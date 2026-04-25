
import json
from pathlib import Path
import sys
from collections import Counter

def analyze_poor_performance():
    # Load JSON data
    file_path = Path("evaluation/results/nutrition_error_test.json")
    if not file_path.exists():
        print("Error: Report file not found.")
        return

    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    poor_plans = []
    
    print("-" * 60)
    print("DETAILED ANALYSIS OF 'POOR' PLANS (Error >= 20%)")
    print("-" * 60)

    for item in data.get("individual_results", []):
        pct_err = item.get("percentage_error", {})
        overall_err = pct_err.get("overall", 0)
        
        if overall_err >= 20.0:
            # Identify the main culprit (highest error metric)
            metrics = {
                "Protein": pct_err.get("protein_g", 0),
                "Carb": pct_err.get("carb_g", 0),
                "Fat": pct_err.get("fat_g", 0),
                "Calories": pct_err.get("calories", 0)
            }
            
            # Find max error metric
            culprit_metric = max(metrics, key=metrics.get)
            max_val = metrics[culprit_metric]
            
            # Check context (Over or Under target?)
            target_vals = item.get("target_values", {})
            actual_vals = item.get("actual_values", {})
            
            is_over = actual_vals.get(culprit_metric.lower().replace("calories", "calories").replace("protein", "protein_g").replace("carb", "carb_g").replace("fat", "fat_g"), 0) > target_vals.get(culprit_metric.lower().replace("calories", "calories").replace("protein", "protein_g").replace("carb", "carb_g").replace("fat", "fat_g"), 0)
            direction = "Too High" if is_over else "Too Low"

            plan_id = item.get("metadata", {}).get("plan_id", "Unknown")[-20:]
            source = item.get("metadata", {}).get("source", "Unknown")
            
            poor_plans.append({
                "id": plan_id,
                "overall": overall_err,
                "culprit": culprit_metric,
                "culprit_val": max_val,
                "direction": direction,
                "source": source
            })

    # Summary
    total_poor = len(poor_plans)
    culprit_counts = Counter([p['culprit'] for p in poor_plans])
    direction_counts = Counter([f"{p['culprit']} ({p['direction']})" for p in poor_plans])
    source_counts = Counter([p['source'] for p in poor_plans])

    print(f"Total Poor Plans: {total_poor}")
    print("\n1. MAIN CULPRITS (Metric causing the most error):")
    for metric, count in culprit_counts.most_common():
        print(f"   - {metric}: {count} plans ({count/total_poor*100:.1f}%)")

    print("\n2. DETAILED ISSUES (Metric + Direction):")
    for issue, count in direction_counts.most_common():
        print(f"   - {issue}: {count} plans")
        
    print("\n3. SOURCE BREAKDOWN:")
    for src, count in source_counts.most_common():
        print(f"   - {src}: {count} plans")

if __name__ == "__main__":
    analyze_poor_performance()
