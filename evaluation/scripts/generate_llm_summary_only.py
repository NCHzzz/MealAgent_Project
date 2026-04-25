import json
from pathlib import Path
from datetime import datetime
import numpy as np

def calculate_stats(values):
    if not values:
        return {"mean": 0, "median": 0, "std": 0, "min": 0, "max": 0}
    return {
        "mean": float(np.mean(values)),
        "median": float(np.median(values)),
        "std": float(np.std(values)),
        "min": float(np.min(values)),
        "max": float(np.max(values)),
    }

def main():
    print("🔄 Generating Detailed LLM Judge Summary...")
    results_dir = Path("evaluation/results")
    
    # 1. Tìm các file test results (chứa chi tiết từng plan)
    # File test chứa individual_results đầy đủ
    test_files = list(results_dir.glob("llm_judge_test__*.json"))
    
    if not test_files:
        print("❌ No test result files found.")
        return

    model_reports = []
    
    for test_file in test_files:
        try:
            with open(test_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                
            model_name = data.get("model_name", "Unknown")
            results = data.get("individual_results", [])
            
            if not results:
                print(f"⚠️ No results in {test_file.name}")
                continue

            # --- Calculate Metrics ---
            scores = {
                "overall": [r.get("overall_score", 0) for r in results],
                "nutrition": [r.get("nutrition_score", 0) for r in results],
                "variety": [r.get("variety_score", 0) for r in results],
                "balance": [r.get("balance_score", 0) for r in results],
                "feasibility": [r.get("feasibility_score", 0) for r in results],
            }
            
            stats = {k: calculate_stats(v) for k, v in scores.items()}
            
            # --- Distribution ---
            excellent = [s for s in scores["overall"] if s >= 80]
            good = [s for s in scores["overall"] if 70 <= s < 80]
            fair = [s for s in scores["overall"] if 60 <= s < 70]
            poor = [s for s in scores["overall"] if s < 60]
            
            total = len(results)
            dist = {
                "excellent": len(excellent),
                "good": len(good),
                "fair": len(fair),
                "poor": len(poor),
                "total": total
            }
            
            # --- Top/Worst Plans ---
            sorted_results = sorted(results, key=lambda x: x.get("overall_score", 0), reverse=True)
            top_5 = sorted_results[:5]
            # Worst 5: sort ascending
            worst_5_asc = sorted(results, key=lambda x: x.get("overall_score", 0))[:5]

            report = {
                "model_name": model_name,
                "stats": stats,
                "dist": dist,
                "top_5": top_5,
                "worst_5": worst_5_asc,
                "count": total
            }
            model_reports.append(report)
            print(f"✅ Processed {model_name}")
            
        except Exception as e:
            print(f"❌ Error processing {test_file}: {e}")

    # Sort reports by Overall Mean
    model_reports.sort(key=lambda x: x["stats"]["overall"]["mean"], reverse=True)

    # --- Generate Markdown ---
    lines = [
        "# Detailed LLM Judge Summary Report\n",
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n",
        "This report provides a detailed breakdown for each model, reflecting the structure of the Nutrition Error Summary.\n"
    ]
    
    for r in model_reports:
        m_name = r["model_name"]
        stats = r["stats"]
        dist = r["dist"]
        total = dist["total"]
        
        lines.append(f"\n# Model: {m_name}\n")
        lines.append("## Overview\n")
        lines.append(f"- **Total Evaluations**: {total}\n")
        
        lines.append("\n## Performance Distribution\n")
        pct_exc = dist['excellent']/total*100 if total else 0
        pct_good = dist['good']/total*100 if total else 0
        pct_fair = dist['fair']/total*100 if total else 0
        pct_poor = dist['poor']/total*100 if total else 0
        
        lines.append(f"- **Excellent (≥80)**: {dist['excellent']} ({pct_exc:.1f}%)\n")
        lines.append(f"- **Good (70-79)**: {dist['good']} ({pct_good:.1f}%)\n")
        lines.append(f"- **Fair (60-69)**: {dist['fair']} ({pct_fair:.1f}%)\n")
        lines.append(f"- **Poor (<60)**: {dist['poor']} ({pct_poor:.1f}%)\n")
        
        lines.append("\n## Aggregated Metrics\n")
        for metric in ["overall", "nutrition", "variety", "balance", "feasibility"]:
            s = stats[metric]
            metric_name = metric.replace("_", " ").title()
            lines.append(f"### {metric_name} Score\n")
            lines.append(f"- Mean: {s['mean']:.2f}\n")
            lines.append(f"- Median: {s['median']:.2f}\n")
            lines.append(f"- Std: {s['std']:.2f}\n")
            lines.append(f"- Range: {s['min']:.2f} - {s['max']:.2f}\n")
            
        lines.append("\n## Top 5 Best Plans (Highest Score)\n")
        for i, plan in enumerate(r["top_5"], 1):
            pid = plan.get("metadata", {}).get("plan_id", "Unknown")
            score = plan.get("overall_score", 0)
            source = plan.get("metadata", {}).get("source", "Unknown")
            lines.append(f"{i}. Plan ID: `{pid}` - Score: {score:.2f} ({source})\n")
            
        lines.append("\n## Top 5 Worst Plans (Lowest Score)\n")
        for i, plan in enumerate(r["worst_5"], 1):
            pid = plan.get("metadata", {}).get("plan_id", "Unknown")
            score = plan.get("overall_score", 0)
            source = plan.get("metadata", {}).get("source", "Unknown")
            lines.append(f"{i}. Plan ID: `{pid}` - Score: {score:.2f} ({source})\n")
            
        lines.append("\n" + "-"*50 + "\n")

    output_file = results_dir / "llm_judge_detailed_summary.md"
    with open(output_file, "w", encoding="utf-8") as f:
        f.writelines(lines)
    
    print(f"\n💾 Saved detailed report: {output_file}")

if __name__ == "__main__":
    main()
