"""
Explain tool: generate a natural-language explanation of decisions from Environment.

Reads results (constraints, ranking, planning) and composes an explanation.
Optionally uses an LLM to polish the explanation if provided.
"""
from typing import AsyncGenerator, Dict, Any, List
import logging

from elysia.tree.objects import TreeData
from elysia.objects import Result, Error
from elysia.util.client import ClientManager
from elysia import tool


def _safe_get(env: TreeData, tool_name: str, name: str) -> Any:
    res = env.environment.find(tool_name, name)
    if res and res[0].objects:
        return res[0].objects[0]
    return None


def _build_explanation(tree_data: TreeData) -> Dict[str, Any]:
    """Collects context and composes an explanation object."""
    profile = _safe_get(tree_data, "profile_crud_tool", "profile")
    target = _safe_get(tree_data, "target_resolver_tool", "resolved") or _safe_get(tree_data, "macro_calc_tool", "targets")
    constraints_report = {
        "diet_allergen": _safe_get(tree_data, "diet_allergen_guard_tool", "report"),
        "time_device": _safe_get(tree_data, "time_device_guard_tool", "report"),
    }

    search_info = {
        "query": _safe_get(tree_data, "query_tool", "query"),
        "postprocessed": _safe_get(tree_data, "query_postprocessing_tool", "results"),
        "topk": _safe_get(tree_data, "score_and_rank_tool", "topk"),
    }

    plan_day = _safe_get(tree_data, "plan_assemble_day_tool", "plan")
    plan_week = _safe_get(tree_data, "plan_assemble_weekly_tool", "plan")
    gaps = _safe_get(tree_data, "gap_calc_tool", "deficits")
    snacks = _safe_get(tree_data, "suggest_snack_tool", "suggestions")
    substitutions = _safe_get(tree_data, "suggest_substitutes_tool", "substitutes")
    variety = _safe_get(tree_data, "variety_guard_tool", "report")

    explanation_lines: List[str] = []
    if profile:
        explanation_lines.append(f"User profile loaded (age {profile.get('age')}, {profile.get('gender')}).")
    if target:
        explanation_lines.append(
            f"Daily targets set to ~{int(target.get('tdee_kcal', 0))} kcal, protein {int(target.get('protein_g', 0))} g, fat {int(target.get('fat_g', 0))} g, carb {int(target.get('carb_g', 0))} g.")
    if constraints_report.get("diet_allergen"):
        explanation_lines.append("Diet/allergen constraints were applied to filter recipes.")
    if constraints_report.get("time_device"):
        explanation_lines.append("Cooking time and available equipment constraints were applied.")
    if search_info.get("topk"):
        explanation_lines.append("Recipes were ranked by fit score and macro alignment.")
    if plan_day:
        explanation_lines.append("A 3-meal daily plan was assembled (breakfast/lunch/dinner).")
    if plan_week:
        explanation_lines.append("A 7-day weekly plan (21 meals) was assembled with variety checks.")
    if gaps and gaps.get("has_deficits"):
        explanation_lines.append("Macro deficits were detected; snack suggestions were generated to fill the gaps.")
    if snacks and snacks.get("count", 0) > 0:
        explanation_lines.append(f"Top {snacks.get('count')} snacks were suggested based on deficit fit.")
    if substitutions and substitutions.get("count"):
        explanation_lines.append("Ingredient substitutes were suggested based on ±20% macro matching.")
    if variety:
        explanation_lines.append(f"Variety score: {variety.get('variety_score', 0):.1f}/100.")

    # Compact summary of chosen meals (if present)
    chosen_titles: List[str] = []
    if plan_day:
        for meal_name, meal_data in plan_day.get("meals", {}).items():
            r = meal_data.get("recipe", {})
            if r.get("dish_name"):
                chosen_titles.append(r["dish_name"]) 
    elif plan_week:
        # List a few example dishes
        for day in list(plan_week.get("days", {}).values())[:2]:
            for meal_data in day.get("meals", {}).values():
                r = meal_data.get("recipe", {})
                if r.get("dish_name"):
                    chosen_titles.append(r["dish_name"]) 
            if len(chosen_titles) >= 5:
                break
    if chosen_titles:
        explanation_lines.append("Example dishes: " + ", ".join(chosen_titles[:5]))

    explanation_text = " ".join(explanation_lines) if explanation_lines else "No explanation available."

    return {
        "explanation": explanation_text,
        "profile": bool(profile),
        "targets": bool(target),
        "constraints": {k: v is not None for k, v in constraints_report.items()},
        "has_plan": bool(plan_day or plan_week),
    }


@tool
async def explain_tool(
    tree_data: TreeData,
    client_manager: ClientManager,
    base_lm=None,
    **kwargs,
) -> AsyncGenerator[Result | str | Error, None]:
    """
    Generate a natural-language explanation from the Environment.

    If an LLM client (base_lm) is provided, polish the explanation; otherwise return
    a deterministic, template-based explanation.

    Environment reads: various results (profile, targets, constraints, ranking, plans)
    Environment writes: explain_tool.explanation
    """
    logging.info("explain_tool: start")
    yield "Composing explanation..."

    data = _build_explanation(tree_data)
    text = data.get("explanation", "")

    # Optional LLM polish (non-blocking if fails)
    if base_lm and text:
        prompt = (
            "Polish the following technical summary into a concise, user-friendly explanation.\n"
            "Keep facts; avoid exaggeration; return plain text.\n\n"
            f"Summary: {text}"
        )
        try:
            improved = await base_lm.generate_text(prompt=prompt)
            if isinstance(improved, str) and len(improved.strip()) > 10:
                text = improved.strip()
        except Exception:
            logging.warning("explain_tool: LLM polish failed", exc_info=True)

    yield Result(name="explanation", objects=[{"text": text}], metadata={"length": len(text), "tool": "explain_tool"})
    logging.info("explain_tool: complete (length=%s)", len(text))
    yield text
