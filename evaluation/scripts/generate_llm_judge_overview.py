"""
Script để tạo file tổng hợp LLM Judge từ các file kết quả của từng model.

Sử dụng khi bạn đã có sẵn:
- evaluation/results/llm_judge_test__*.json
và muốn tạo/cập nhật:
- evaluation/results/llm_judge_summary__<model>.{json,md}
- evaluation/results/llm_judge_all_models_summary.{json,md}
"""

import json
from pathlib import Path
from typing import Any, Dict, List
from datetime import datetime

# Add parent directories to path nếu chạy trực tiếp
import sys

project_root = Path(__file__).parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from evaluation.scripts.generate_evaluation_summary import (  # type: ignore
    analyze_results,
    generate_summary_report,
)


def load_model_results(results_dir: Path) -> List[Dict[str, Any]]:
    """Load tất cả các file llm_judge_test__*.json trong thư mục results."""
    model_results: List[Dict[str, Any]] = []

    for path in sorted(results_dir.glob("llm_judge_test__*.json")):
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        model_results.append(
            {
                "path": path,
                "data": data,
            }
        )

    return model_results


def generate_overview(results_dir: Path) -> Dict[str, Any]:
    """Tạo các file summary cho từng model và file tổng hợp tất cả models."""
    model_results = load_model_results(results_dir)
    if not model_results:
        print("❌ Không tìm thấy file llm_judge_test__*.json trong evaluation/results/")
        return {"models": []}

    all_model_summaries: List[Dict[str, Any]] = []

    for mr in model_results:
        path: Path = mr["path"]
        results: Dict[str, Any] = mr["data"]

        model_name = results.get("model_name", path.stem.replace("llm_judge_test__", ""))
        print(f"\n🔍 Processing model: {model_name} ({path})")

        # Phân tích kết quả để lấy aggregated_scores & performance_distribution
        analysis = analyze_results(results)

        model_suffix = path.stem.replace("llm_judge_test__", "")
        summary_md = results_dir / f"llm_judge_summary__{model_suffix}.md"
        summary_json = results_dir / f"llm_judge_summary__{model_suffix}.json"

        # Sinh markdown summary
        generate_summary_report(analysis, output_file=str(summary_md))

        # Lưu JSON summary
        with summary_json.open("w", encoding="utf-8") as f:
            json.dump(analysis, f, indent=2, ensure_ascii=False)

        print(f"✅ Summary markdown saved to: {summary_md}")
        print(f"✅ Summary JSON saved to: {summary_json}")

        all_model_summaries.append(
            {
                "model_name": model_name,
                "result_file": str(path),
                "summary_markdown": str(summary_md),
                "summary_json": str(summary_json),
                "aggregated_scores": analysis.get("aggregated_scores", {}),
                "performance_distribution": analysis.get(
                    "performance_distribution", {}
                ),
                "common_issues": analysis.get("common_issues", {}),
                "summary": analysis.get("summary", {}),
            }
        )

    # Tổng hợp tất cả models (sử dụng cùng logic như run_single_method.py)
    if all_model_summaries:
        # Sắp xếp theo overall mean (cao → thấp)
        def _overall_mean(m: Dict[str, Any]) -> float:
            agg = m.get("aggregated_scores", {}) or {}
            return float(agg.get("overall_score", {}).get("mean", 0.0) or 0.0)

        sorted_models = sorted(
            all_model_summaries, key=_overall_mean, reverse=True
        )

        # Bổ sung rank & summary ngắn cho JSON tổng hợp
        combined_payload: Dict[str, Any] = {"models": []}
        for rank, m in enumerate(sorted_models, start=1):
            agg = m.get("aggregated_scores", {}) or {}
            dist = m.get("performance_distribution", {}) or {}

            overall = float(agg.get("overall_score", {}).get("mean", 0.0) or 0.0)
            nutrition = float(agg.get("nutrition_score", {}).get("mean", 0.0) or 0.0)
            feasibility = float(
                agg.get("feasibility_score", {}).get("mean", 0.0) or 0.0
            )
            excellent = int(dist.get("excellent", 0) or 0)
            good = int(dist.get("good", 0) or 0)
            fair = int(dist.get("fair", 0) or 0)
            poor = int(dist.get("poor", 0) or 0)
            total = max(excellent + good + fair + poor, 1)

            summary_vi = (
                f"Model {m['model_name']} đứng hạng {rank} với điểm overall trung bình ~{overall:.1f}. "
                f"Tỷ lệ Excellent+Good chiếm khoảng "
                f"{(excellent + good) / total * 100:.1f}% "
                f"(Excellent: {excellent}, Good: {good}, Fair: {fair}, Poor: {poor}). "
                f"Nutrition trung bình ~{nutrition:.1f}, Feasibility ~{feasibility:.1f}."
            )

            extended = dict(m)
            extended["rank"] = rank
            extended["summary_vi"] = summary_vi
            combined_payload["models"].append(extended)

        combined_json_path = results_dir / "llm_judge_all_models_summary.json"
        with combined_json_path.open("w", encoding="utf-8") as f:
            json.dump(
                combined_payload,
                f,
                indent=2,
                ensure_ascii=False,
            )

        # Markdown comparison report chi tiết
        combined_md_path = results_dir / "llm_judge_all_models_summary.md"
        lines: List[str] = [
            "# LLM Judge - All Models Comparison\n",
            f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n",
            "## Models Overview (sorted by Overall Mean)\n",
            "| Rank | Model | Overall Mean | Nutrition Mean | Variety Mean | Balance Mean | Feasibility Mean |\n",
            "|-----:|-------|-------------:|---------------:|-------------:|-------------:|-----------------:|\n",
        ]

        rank_map = {m["model_name"]: m["rank"] for m in combined_payload["models"]}

        for m in sorted_models:
            agg = m.get("aggregated_scores", {}) or {}
            rank = rank_map.get(m["model_name"], "")
            overall = float(agg.get("overall_score", {}).get("mean", 0.0) or 0.0)
            nutrition = float(agg.get("nutrition_score", {}).get("mean", 0.0) or 0.0)
            variety = float(agg.get("variety_score", {}).get("mean", 0.0) or 0.0)
            balance = float(agg.get("balance_score", {}).get("mean", 0.0) or 0.0)
            feasibility = float(
                agg.get("feasibility_score", {}).get("mean", 0.0) or 0.0
            )
            lines.append(
                f"| {rank} | {m['model_name']} | {overall:11.2f} | {nutrition:13.2f} | "
                f"{variety:11.2f} | {balance:11.2f} | {feasibility:17.2f} |\n"
            )

        lines.append("\n## Model Notes\n\n")
        for m in combined_payload["models"]:
            lines.append(f"### {m['model_name']}\n\n")
            lines.append(f"- **Rank**: {m['rank']}\n")
            lines.append(f"- **Tóm tắt**: {m['summary_vi']}\n")

            summary = m.get("summary", {}) or {}
            total_evals = int(summary.get("total_evaluations", 0) or 0)
            meal_plan_cnt = int(summary.get("meal_plan_count", 0) or 0)
            meal_log_cnt = int(summary.get("meal_log_count", 0) or 0)
            lines.append(
                f"- **Dataset**: {total_evals} evaluations "
                f"({meal_plan_cnt} suggested plans, {meal_log_cnt} meal logs)\n"
            )

            ci = m.get("common_issues", {}) or {}
            issue_lines: List[str] = []
            if ci.get("low_protein_count", 0):
                issue_lines.append("thiếu protein")
            if ci.get("high_calories_count", 0):
                issue_lines.append("calo quá cao")
            if ci.get("high_fat_count", 0):
                issue_lines.append("chất béo quá cao")
            if ci.get("low_variety_count", 0):
                issue_lines.append("thiếu đa dạng")
            if ci.get("poor_balance_count", 0):
                issue_lines.append("mất cân bằng giữa các bữa")

            if issue_lines:
                issues_str = ", ".join(issue_lines)
                lines.append(f"- **Vấn đề phổ biến**: {issues_str}.\n")
            else:
                lines.append(
                    "- **Vấn đề phổ biến**: không có vấn đề nổi bật (đa số plans ở mức ổn).\n"
                )

            lines.append("\n")

        with combined_md_path.open("w", encoding="utf-8") as f:
            f.writelines(lines)

        print(f"\n💾 Combined JSON summary saved to: {combined_json_path}")
        print(f"💾 Combined markdown summary saved to: {combined_md_path}")

    return {"models": all_model_summaries}


def main() -> None:
    """Entry point: tạo tổng hợp LLM Judge từ các file model đã có."""
    results_dir = Path("evaluation/results")
    print("=" * 80)
    print("Generating LLM Judge Overview from existing model results")
    print("=" * 80)

    generate_overview(results_dir)

    print("\n✅ Done.")
    print("=" * 80)


if __name__ == "__main__":
    main()


