"""
Generate an English, academically styled evaluation report for LLM Judge.

The report is intended to be dropped directly into the *Evaluation* section
of an academic or technical report.

Data source:
- Per-model summary JSON files produced by the LLM Judge pipeline, e.g.:
  - evaluation/results/llm_judge_summary__google_gemini_3_flash_preview.json
  - evaluation/results/llm_judge_summary__x_ai_grok_4_1_fast.json
  - evaluation/results/llm_judge_summary__xiaomi_mimo_v2_flash_free.json
  - evaluation/results/llm_judge_summary__openai_gpt_5_mini.json

Output:
- evaluation/results/llm_judge_academic_evaluation.md
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List


@dataclass
class ModelSummary:
    name: str
    file: Path
    summary: Dict[str, Any]


def _load_model_summaries(results_dir: Path) -> List[ModelSummary]:
    """Load all per-model llm_judge_summary__*.json files in results_dir."""
    summaries: List[ModelSummary] = []

    for path in sorted(results_dir.glob("llm_judge_summary__*.json")):
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)

        # Derive model name from filename if not explicitly stored
        # e.g. llm_judge_summary__google_gemini_3_flash_preview.json
        stem = path.stem.replace("llm_judge_summary__", "")
        model_name = data.get("model_name", stem)

        summaries.append(ModelSummary(name=model_name, file=path, summary=data))

    return summaries


def _overall_mean(summary: Dict[str, Any]) -> float:
    agg = summary.get("aggregated_scores", {}) or {}
    return float(agg.get("overall_score", {}).get("mean", 0.0) or 0.0)


def _format_issues_english(common_issues: Dict[str, Any]) -> str:
    """Turn common_issues counts into a short English phrase."""
    if not common_issues:
        return "No dominant issues were consistently flagged across plans."

    labels: List[str] = []
    if common_issues.get("low_protein_count", 0):
        labels.append("insufficient protein")
    if common_issues.get("high_calories_count", 0):
        labels.append("excessive total energy intake")
    if common_issues.get("high_fat_count", 0):
        labels.append("excessive fat intake")
    if common_issues.get("low_variety_count", 0):
        labels.append("limited variety")
    if common_issues.get("poor_balance_count", 0):
        labels.append("imbalanced distribution across meals")

    if not labels:
        return "No dominant issues were consistently flagged across plans."

    if len(labels) == 1:
        return f"The most common issue flagged was {labels[0]}."
    if len(labels) == 2:
        return f"The most common issues flagged were {labels[0]} and {labels[1]}."

    # Oxford comma style for 3+ labels
    return (
        "The most common issues flagged were "
        + ", ".join(labels[:-1])
        + f", and {labels[-1]}."
    )


def generate_academic_report(
    results_dir: Path, output_file: Path
) -> None:
    """Generate an English academic-style markdown report."""
    model_summaries = _load_model_summaries(results_dir)
    if not model_summaries:
        print("❌ No llm_judge_summary__*.json files found in evaluation/results/")
        return

    # Sort models by overall mean (high → low)
    model_summaries.sort(
        key=lambda ms: _overall_mean(ms.summary), reverse=True
    )

    # Assume all models share the same evaluation set; use the first one for dataset description
    first = model_summaries[0].summary
    ds = first.get("summary", {}) or {}
    total_evals = int(ds.get("total_evaluations", 0) or 0)
    meal_plan_cnt = int(ds.get("meal_plan_count", 0) or 0)
    meal_log_cnt = int(ds.get("meal_log_count", 0) or 0)

    lines: List[str] = []

    # Title and high-level description
    lines.append("## LLM-as-a-Judge Evaluation of Meal Planning System\n\n")
    lines.append(
        "This section reports an LLM-as-a-Judge evaluation of the meal planning "
        "system using multiple large language models (LLMs) as independent judges. "
        "Each judge rates daily meal plans along four dimensions: **Nutrition**, "
        "**Variety**, **Balance**, and **Feasibility**, and provides an overall "
        "score as the average of these criteria.\n\n"
    )

    # Dataset description
    lines.append("### Evaluation Dataset\n\n")
    lines.append(
        f"The evaluation dataset consists of **{total_evals} daily plans**, "
        f"including **{meal_plan_cnt} AI-generated meal plans** and "
        f"**{meal_log_cnt} real meal logs** collected from users. "
        "Weekly meal plans are expanded into individual days before scoring, "
        "and extreme caloric outliers (e.g., multi-day logs collapsed into a single entry) "
        "are filtered out to avoid distorting the results.\n\n"
    )

    # Quantitative comparison table
    lines.append("### Quantitative Results Across Models\n\n")
    lines.append(
        "| Rank | Model | Overall Mean | Nutrition Mean | Variety Mean | Balance Mean | Feasibility Mean |\n"
    )
    lines.append(
        "|-----:|-------|-------------:|---------------:|-------------:|-------------:|-----------------:|\n"
    )

    for rank, ms in enumerate(model_summaries, start=1):
        agg = ms.summary.get("aggregated_scores", {}) or {}
        overall = float(agg.get("overall_score", {}).get("mean", 0.0) or 0.0)
        nutrition = float(agg.get("nutrition_score", {}).get("mean", 0.0) or 0.0)
        variety = float(agg.get("variety_score", {}).get("mean", 0.0) or 0.0)
        balance = float(agg.get("balance_score", {}).get("mean", 0.0) or 0.0)
        feasibility = float(
            agg.get("feasibility_score", {}).get("mean", 0.0) or 0.0
        )

        lines.append(
            f"| {rank} | {ms.name} | {overall:11.2f} | {nutrition:13.2f} | "
            f"{variety:11.2f} | {balance:11.2f} | {feasibility:17.2f} |\n"
        )

    lines.append("\n")

    # Per-model narrative
    lines.append("### Model-wise Analysis\n\n")
    for rank, ms in enumerate(model_summaries, start=1):
        s = ms.summary
        agg = s.get("aggregated_scores", {}) or {}
        perf = s.get("performance_distribution", {}) or {}
        common = s.get("common_issues", {}) or {}

        overall = agg.get("overall_score", {}) or {}
        nutrition = agg.get("nutrition_score", {}) or {}
        variety = agg.get("variety_score", {}) or {}
        balance = agg.get("balance_score", {}) or {}
        feasibility = agg.get("feasibility_score", {}) or {}

        overall_mean = float(overall.get("mean", 0.0) or 0.0)
        overall_std = float(overall.get("std", 0.0) or 0.0)

        nutrition_mean = float(nutrition.get("mean", 0.0) or 0.0)
        variety_mean = float(variety.get("mean", 0.0) or 0.0)
        balance_mean = float(balance.get("mean", 0.0) or 0.0)
        feasibility_mean = float(feasibility.get("mean", 0.0) or 0.0)

        excellent = int(perf.get("excellent", 0) or 0)
        good = int(perf.get("good", 0) or 0)
        fair = int(perf.get("fair", 0) or 0)
        poor = int(perf.get("poor", 0) or 0)
        total = max(excellent + good + fair + poor, 1)
        good_ratio = (excellent + good) / total * 100.0

        lines.append(f"#### {rank}. {ms.name}\n\n")
        lines.append(
            f"{ms.name} achieved an average overall score of "
            f"**{overall_mean:.1f} ± {overall_std:.1f}** across {total_evals} daily plans. "
            f"Approximately **{good_ratio:.1f}%** of plans were rated *Excellent* or *Good* "
            f"(Excellent: {excellent}, Good: {good}, Fair: {fair}, Poor: {poor}). "
            f"The model's mean sub-scores were **{nutrition_mean:.1f}** for Nutrition, "
            f"**{variety_mean:.1f}** for Variety, **{balance_mean:.1f}** for Balance, and "
            f"**{feasibility_mean:.1f}** for Feasibility.\n\n"
        )

        lines.append(_format_issues_english(common) + "\n\n")

    # Cross-model interpretation
    lines.append("### Cross-model Interpretation\n\n")
    if len(model_summaries) >= 2:
        best = model_summaries[0]
        worst = model_summaries[-1]
        best_mean = _overall_mean(best.summary)
        worst_mean = _overall_mean(worst.summary)
        gap = best_mean - worst_mean

        lines.append(
            f"Overall, the best-performing judge was **{best.name}** "
            f"(mean overall score ≈ {best_mean:.1f}), while **{worst.name}** "
            f"was the most conservative (mean overall score ≈ {worst_mean:.1f}). "
            f"The absolute gap in average overall scores across judges is "
            f"approximately **{gap:.1f} points**, indicating a moderate but not "
            "extreme level of inter-model variation.\n\n"
        )

    lines.append(
        "Across all judges, the system's meal plans are typically rated in the "
        "high *Good* to low *Excellent* range on average, with feasibility scores "
        "generally higher than nutrition scores. The most frequently raised concerns "
        "relate to excessive total calories and fat, and, to a lesser extent, "
        "insufficient protein. These findings suggest that future iterations of the "
        "meal planning system should focus on tighter calorie control and improved "
        "macronutrient balance, while maintaining the strong feasibility and variety "
        "currently observed.\n"
    )

    output_file.parent.mkdir(parents=True, exist_ok=True)
    with output_file.open("w", encoding="utf-8") as f:
        f.writelines(lines)

    print(f"💾 Academic evaluation report saved to: {output_file}")


def main() -> None:
    results_dir = Path("evaluation/results")
    output_file = results_dir / "llm_judge_academic_evaluation.md"

    print("=" * 80)
    print("Generating academic-style LLM Judge evaluation report (English)")
    print("=" * 80)

    generate_academic_report(results_dir, output_file)

    print("\n✅ Done.")
    print("=" * 80)


if __name__ == "__main__":
    main()



