"""
Explain tool: generate a natural-language explanation of decisions from Environment.

Reads results (constraints, ranking, planning) and composes an explanation.
Optionally uses an LLM to polish the explanation if provided.
"""
from typing import AsyncGenerator, Dict, Any, List
import logging
import re

from elysia.tree.objects import TreeData
from elysia.objects import Result, Error, Response
from elysia.util.client import ClientManager
from elysia import tool
import dspy
from elysia.util.elysia_chain_of_thought import ElysiaChainOfThought

# Constants
MIN_TEXT_LENGTH_FOR_STREAMING = 50
INITIAL_SENTENCES_TO_STREAM = 2


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
        "combined": _safe_get(tree_data, "constraints_guard_tool", "report"),
    }

    # Get search results from query_tool
    search_results = tree_data.environment.find("query_tool", "results")
    search_objects = []
    search_metadata = {}
    if search_results and len(search_results) > 0:
        # Handle Result object format
        if hasattr(search_results[0], "objects"):
            search_objects = search_results[0].objects if search_results[0].objects else []
            search_metadata = search_results[0].metadata if hasattr(search_results[0], "metadata") else {}
        # Handle dict format
        elif isinstance(search_results[0], dict):
            search_objects = search_results[0].get("objects", [])
            search_metadata = search_results[0].get("metadata", {})
        # Handle list of Result objects
        elif isinstance(search_results, list) and len(search_results) > 0:
            first_item = search_results[0]
            if hasattr(first_item, "objects"):
                search_objects = first_item.objects if first_item.objects else []
                search_metadata = first_item.metadata if hasattr(first_item, "metadata") else {}

    search_info = {
        "query": search_metadata.get("query", ""),
        "collection": search_metadata.get("collection", ""),
        "count": search_metadata.get("count", len(search_objects)),
        "postprocessed": _safe_get(tree_data, "query_postprocessing_tool", "deduped"),
        "topk": _safe_get(tree_data, "score_and_rank_tool", "topk"),
    }

    plan_day = _safe_get(tree_data, "plan_assemble_day_tool", "plan")
    plan_week = _safe_get(tree_data, "plan_assemble_weekly_tool", "plan")
    gaps = _safe_get(tree_data, "gap_calc_tool", "deficits")
    snacks = _safe_get(tree_data, "suggest_snack_tool", "suggestions")
    substitutions = _safe_get(tree_data, "suggest_substitutes_tool", "substitutes")
    variety = _safe_get(tree_data, "variety_guard_tool", "report")

    explanation_lines: List[str] = []
    
    # Search results explanation (for simple queries without planning)
    if search_objects and search_info.get("count", 0) > 0:
        collection_name = search_info.get("collection", "items")
        query_text = search_info.get("query", "")
        count = search_info.get("count", len(search_objects))
        
        if query_text:
            explanation_lines.append(f"Searched {collection_name} collection for '{query_text}' and found {count} matching items.")
        else:
            explanation_lines.append(f"Retrieved {count} items from {collection_name} collection.")
        
        # Show sample items if available
        sample_items = []
        for item in search_objects[:5]:
            # Handle different collection types
            if "description" in item:
                sample_items.append(item.get("description", "Unknown"))
            elif "food_name" in item:
                sample_items.append(item.get("food_name", "Unknown"))
            elif "dish_name" in item:
                sample_items.append(item.get("dish_name", "Unknown"))
            elif "name" in item:
                sample_items.append(item.get("name", "Unknown"))
        
        if sample_items:
            explanation_lines.append(f"Sample items found: {', '.join(sample_items[:5])}.")
    
    if profile:
        explanation_lines.append(f"User profile loaded (age {profile.get('age')}, {profile.get('gender')}).")
    if target:
        explanation_lines.append(
            f"Daily targets set to ~{int(target.get('tdee_kcal', 0))} kcal, protein {int(target.get('protein_g', 0))} g, fat {int(target.get('fat_g', 0))} g, carb {int(target.get('carb_g', 0))} g.")
    if constraints_report.get("combined") and constraints_report["combined"].get("has_constraints"):
        explanation_lines.append("Combined constraints (diet/allergen, time/device) were applied.")
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


@tool(end=True)
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
    yield Response("Composing explanation...")

    try:
        data = _build_explanation(tree_data)
        text = data.get("explanation", "")
        final_text = text if text else "No explanation available."

        # Optional polishing with ElysiaChainOfThought when base_lm is available
        if base_lm and final_text and final_text != "No explanation available.":
            class ExplanationPolishPrompt(dspy.Signature):
                """
                Improve clarity and readability of an agent explanation while keeping facts unchanged.
                Output concise, user-facing text with light structure (headings/lists) if helpful.
                """
                input_text = dspy.InputField(description="The raw explanation text to polish for the user.")
                message_update = dspy.OutputField(description="One-sentence update describing the action performed.")
                improved_text = dspy.OutputField(description="The polished explanation text.")

            cot = ElysiaChainOfThought(
                ExplanationPolishPrompt,
                tree_data=tree_data,
                reasoning=False,
                impossible=False,
                message_update=True,
                environment=True,
                tasks_completed=True,
            )
            try:
                pred = await cot.aforward(lm=base_lm, input_text=final_text)
                if getattr(pred, "message_update", None):
                    yield Response(str(pred.message_update))
                if getattr(pred, "improved_text", None) and isinstance(pred.improved_text, str):
                    final_text = pred.improved_text.strip() or final_text
            except Exception as e:
                logging.warning(f"explain_tool: polishing skipped due to error: {str(e)}")

        # Always stream the text first for immediate feedback
        # Stream text immediately in chunks for better UX
        if final_text and len(final_text) > MIN_TEXT_LENGTH_FOR_STREAMING:
            # Split text into sentences for streaming
            sentences = re.split(r'(?<=[.!?])\s+', final_text)
            sentences = [s.strip() for s in sentences if s.strip()]
            
            # Stream first few sentences immediately
            for sentence in sentences[:INITIAL_SENTENCES_TO_STREAM]:
                yield Response(sentence + " ")
            
            # Stream remaining sentences
            for sentence in sentences[INITIAL_SENTENCES_TO_STREAM:]:
                yield Response(sentence + " ")
        else:
            # Short text: yield immediately
            if final_text:
                yield Response(final_text)
        
        # Always yield Result at the end for data consistency
        yield Result(
            name="explanation", 
            objects=[{"text": final_text}], 
            metadata={
                "length": len(final_text), 
                "tool": "explain_tool",
                "has_content": bool(final_text and final_text != "No explanation available.")
            },
            payload_type="document",
            mapping={
                "content": "text",
                "title": "",
                "author": "",
                "date": "",
                "category": "",
            },
        )
        
    except Exception as e:
        error_msg = f"Failed to build explanation: {str(e)}"
        logging.error(f"explain_tool: {error_msg}", exc_info=True)
        # Yield error message first, then Error object
        yield Response(error_msg)
        yield Error(error_msg)
        return
    
    logging.info("explain_tool: complete (length=%s)", len(final_text) if 'final_text' in locals() else 0)
