"""
MealAgent tool registration and configuration.

This module registers all MealAgent tools for use in the decision tree.
"""

# Profile tools
from elysia.MealAgent.tools.profile.profile_crud import profile_crud_tool
from elysia.MealAgent.tools.profile.macro_calc import macro_calc_tool

# Constraint tools (consolidated)
from elysia.MealAgent.tools.constraints.constraints_guard import constraints_guard_tool

# Search tools
from elysia.MealAgent.tools.search.query import query_tool
from elysia.MealAgent.tools.search.query_postprocessing import query_postprocessing_tool
from elysia.MealAgent.tools.search.score_and_rank import score_and_rank_tool
from elysia.MealAgent.tools.search.search_and_rank import search_and_rank_tool

# Nutrition tools
from elysia.MealAgent.tools.nutrition.calculate_recipe_macros import calculate_recipe_macros_tool

# Plan Day tools
from elysia.MealAgent.tools.plan_day.target_resolver import target_resolver_tool
from elysia.MealAgent.tools.plan_day.plan_assemble import plan_assemble_day_tool
from elysia.MealAgent.tools.plan_day.plan_validate import plan_validate_tool
from elysia.MealAgent.tools.plan_day.build_shopping import build_shopping_tool
from elysia.MealAgent.tools.plan_day.plan_day_e2e import plan_day_e2e_tool

# Meal Logging tools
from elysia.MealAgent.tools.meal_logging.meal_parser import meal_parser_tool
from elysia.MealAgent.tools.meal_logging.nutrition_calc import nutrition_calc_tool
from elysia.MealAgent.tools.meal_logging.profile_update import profile_update_tool
from elysia.MealAgent.tools.meal_logging.meal_history import meal_history_tool
from elysia.MealAgent.tools.meal_logging.log_meal_e2e import log_meal_e2e_tool

# Plan Week tools
from elysia.MealAgent.tools.plan_week.plan_assemble_weekly import plan_assemble_weekly_tool
from elysia.MealAgent.tools.plan_week.variety_guard import variety_guard_tool

# Pantry tools
from elysia.MealAgent.tools.pantry.pantry_crud import pantry_crud_tool

# Shopping tools
from elysia.MealAgent.tools.shopping.pantry_diff import pantry_diff_tool

# Gap Fill tools
from elysia.MealAgent.tools.gap_fill.gap_calc import gap_calc_tool
from elysia.MealAgent.tools.gap_fill.suggest_snack import suggest_snack_tool
from elysia.MealAgent.tools.gap_fill.apply_snack import apply_snack_tool

# Substitution tools
from elysia.MealAgent.tools.substitution.suggest_substitutes import suggest_substitutes_tool
from elysia.MealAgent.tools.substitution.apply_substitute import apply_substitute_tool

# Micronutrient tools
from elysia.MealAgent.tools.micros.micronutrient_check import micronutrient_check_tool
from elysia.MealAgent.tools.micros.suggest_micros_foods import suggest_micros_foods_tool

# Cooking & Explanation tools
from elysia.MealAgent.tools.cook_mode.cook_mode import cook_mode_tool
from elysia.MealAgent.tools.explain.explain import explain_tool

# Tool registry: maps tool names to tool functions
# Tools are registered by their function name (used by Elysia's @tool decorator)
MEAL_AGENT_TOOLS = {
    # Profile tools
    "profile_crud_tool": profile_crud_tool,
    "macro_calc_tool": macro_calc_tool,
    # Constraint tools
    "constraints_guard_tool": constraints_guard_tool,
    # Search tools
    "query_tool": query_tool,
    "query_postprocessing_tool": query_postprocessing_tool,
    "score_and_rank_tool": score_and_rank_tool,
    "search_and_rank_tool": search_and_rank_tool,
    # Nutrition tools
    "calculate_recipe_macros_tool": calculate_recipe_macros_tool,
    # Plan Day tools
    "target_resolver_tool": target_resolver_tool,
    "plan_assemble_day_tool": plan_assemble_day_tool,
    "plan_validate_tool": plan_validate_tool,
    "build_shopping_tool": build_shopping_tool,
    "plan_day_e2e_tool": plan_day_e2e_tool,
    # Meal Logging tools
    "meal_parser_tool": meal_parser_tool,
    "nutrition_calc_tool": nutrition_calc_tool,
    "profile_update_tool": profile_update_tool,
    "meal_history_tool": meal_history_tool,
    "log_meal_e2e_tool": log_meal_e2e_tool,
    # Plan Week tools
    "plan_assemble_weekly_tool": plan_assemble_weekly_tool,
    "variety_guard_tool": variety_guard_tool,
    # Pantry tools
    "pantry_crud_tool": pantry_crud_tool,
    # Shopping tools
    "pantry_diff_tool": pantry_diff_tool,
    # Gap Fill tools
    "gap_calc_tool": gap_calc_tool,
    "suggest_snack_tool": suggest_snack_tool,
    "apply_snack_tool": apply_snack_tool,
    # Substitution tools
    "suggest_substitutes_tool": suggest_substitutes_tool,
    "apply_substitute_tool": apply_substitute_tool,
    # Micronutrient tools
    "micronutrient_check_tool": micronutrient_check_tool,
    "suggest_micros_foods_tool": suggest_micros_foods_tool,
    # Cooking & Explanation tools
    "cook_mode_tool": cook_mode_tool,
    "explain_tool": explain_tool,
}


def get_meal_agent_tools() -> dict[str, callable]:
    """
    Return a dict of MealAgent tools suitable for Tree registration.
    Usage:
        tools = get_meal_agent_tools()
        # pass into Tree/TreeManager registration per Elysia docs
    """
    return dict(MEAL_AGENT_TOOLS)


def try_register_meal_agent_tools(tree_or_manager) -> int:
    """
    Best-effort registration of MealAgent tools into an Elysia Tree or TreeManager.
    This uses duck-typing so it won't fail if the target API differs.

    Returns: number of tools successfully registered.
    """
    tools = get_meal_agent_tools()
    registered = 0

    # Common patterns supported by Elysia:
    # - tree.register_tool(func) or tree.register_tools({name: func})
    # - manager.register_tool(func) or manager.register_tools({...})
    # - attribute 'tools' dict
    if hasattr(tree_or_manager, "register_tools") and callable(getattr(tree_or_manager, "register_tools")):
        try:
            tree_or_manager.register_tools(tools)
            return len(tools)
        except Exception:
            pass

    if hasattr(tree_or_manager, "register_tool") and callable(getattr(tree_or_manager, "register_tool")):
        for func in tools.values():
            try:
                tree_or_manager.register_tool(func)
                registered += 1
            except Exception:
                continue
        if registered:
            return registered

    # Fallback: attach to 'tools' mapping if present
    if hasattr(tree_or_manager, "tools") and isinstance(getattr(tree_or_manager, "tools"), dict):
        try:
            tree_or_manager.tools.update(tools)
            return len(tools)
        except Exception:
            pass

    return registered

