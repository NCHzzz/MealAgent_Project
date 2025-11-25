"""
MealAgent tool registration and configuration.

This module registers all MealAgent tools for use in the decision tree.
"""

# Profile tools
from MealAgent.tools.profile.profile_crud import profile_crud_tool
from MealAgent.tools.profile.macro_calc import macro_calc_tool

# Constraint tools (consolidated)
from MealAgent.tools.constraints.constraints_guard import constraints_guard_tool

# Search tools
from MealAgent.tools.search.search_and_rank import search_and_rank_tool

# Nutrition tools
from MealAgent.tools.nutrition.calculate_recipe_macros import calculate_recipe_macros_tool
from MealAgent.tools.nutrition.auto_calculate_macros import auto_calculate_macros_tool

# Plan Day tools
from MealAgent.tools.plan_day.plan_day_e2e import plan_day_e2e_tool

# Meal Logging tools
from MealAgent.tools.meal_logging.meal_history import meal_history_tool
from MealAgent.tools.meal_logging.log_meal_e2e import log_meal_e2e_tool

# Plan Week tools
from MealAgent.tools.plan_week.plan_week_e2e import plan_week_e2e_tool

# Pantry tools
from MealAgent.tools.pantry.pantry_crud import pantry_crud_tool

# Shopping tools
from MealAgent.tools.shopping.pantry_diff import pantry_diff_tool

# Gap Fill tools
from MealAgent.tools.gap_fill.gap_fill import gap_fill_tool

# Substitution tools
from MealAgent.tools.substitution.substitute import substitute_tool

# Micronutrient tools
from MealAgent.tools.micros.micros import micros_tool

# Cooking tools
from MealAgent.tools.cook_mode.cook_mode import cook_mode_tool

# Tool registry: maps tool names to tool functions
# Tools are registered by their function name (used by Elysia's @tool decorator)
#
# According to design doc, MealAgent has 15 core tools (optimized from 28).
# Legacy tools have been removed in favor of E2E tools for better performance and simpler workflows.
# E2E tools (plan_day_e2e_tool, plan_week_e2e_tool, log_meal_e2e_tool, gap_fill_tool, substitute_tool, micros_tool)
# consolidate multiple steps into single tools.
MEAL_AGENT_TOOLS = {
    # ===== CORE TOOLS (15 tools per design doc) =====
    # Profile tools
    "profile_crud_tool": profile_crud_tool,
    "macro_calc_tool": macro_calc_tool,
    # Constraint tools
    "constraints_guard_tool": constraints_guard_tool,
    # Search tools
    "search_and_rank_tool": search_and_rank_tool,  # Main search tool (uses Elysia Query internally)
    # Nutrition tools
    "calculate_recipe_macros_tool": calculate_recipe_macros_tool,
    "auto_calculate_macros_tool": auto_calculate_macros_tool,
    # Plan Day tools
    "plan_day_e2e_tool": plan_day_e2e_tool,  # E2E daily planning (replaces target_resolver, plan_assemble, plan_validate)
    # Plan Week tools
    "plan_week_e2e_tool": plan_week_e2e_tool,  # E2E weekly planning with variety (replaces plan_assemble_weekly, variety_guard)
    # Meal Logging tools
    "log_meal_e2e_tool": log_meal_e2e_tool,  # E2E meal logging (replaces meal_parser, nutrition_calc, profile_update)
    "meal_history_tool": meal_history_tool,
    # Pantry tools
    "pantry_crud_tool": pantry_crud_tool,
    # Shopping tools
    "pantry_diff_tool": pantry_diff_tool,  # Reads from plan_day_e2e_tool.plan or plan_week_e2e_tool.plan
    # Cooking tools
    "cook_mode_tool": cook_mode_tool,
    # Optimization tools (E2E)
    "gap_fill_tool": gap_fill_tool,  # E2E gap fill (replaces gap_calc, suggest_snack, apply_snack)
    "substitute_tool": substitute_tool,  # E2E substitution (replaces suggest_substitutes, apply_substitute)
    "micros_tool": micros_tool,  # E2E micronutrient check (replaces micronutrient_check, suggest_micros_foods)
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

