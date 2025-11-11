"""
MealAgent Tool Optimizer - Reduces token usage by intelligent tool loading.

This module provides:
1. Intent-based tool grouping
2. Conditional tool loading
3. Tool description optimization
4. Workflow-based execution hints
"""

from typing import Dict, List, Set, Optional
import logging

from elysia.MealAgent.tree.config import MEAL_AGENT_TOOLS

logger = logging.getLogger(__name__)

# Intent categories and their associated tools
INTENT_TOOLS: Dict[str, List[str]] = {
    "meal_planning": [
        "profile_crud_tool",
        "macro_calc_tool",
        "diet_allergen_guard_tool",
        "time_device_guard_tool",
        "query_tool",
        "query_postprocessing_tool",
        "score_and_rank_tool",
        "target_resolver_tool",
        "plan_assemble_day_tool",
        "plan_validate_tool",
        "build_shopping_tool",
    ],
    "meal_logging": [
        "meal_parser_tool",
        "nutrition_calc_tool",
        "profile_update_tool",
        "meal_history_tool",
    ],
    "recipe_search": [
        "query_tool",
        "query_postprocessing_tool",
        "score_and_rank_tool",
        "calculate_recipe_macros_tool",
    ],
    "cooking": [
        "cook_mode_tool",
        "explain_tool",
    ],
    "nutrition_tracking": [
        "profile_crud_tool",
        "macro_calc_tool",
        "nutrition_calc_tool",
        "gap_calc_tool",
        "suggest_snack_tool",
        "micronutrient_check_tool",
        "suggest_micros_foods_tool",
    ],
    "pantry_management": [
        "pantry_crud_tool",
        "pantry_diff_tool",
        "query_tool",
    ],
    "substitution": [
        "suggest_substitutes_tool",
        "apply_substitute_tool",
        "query_tool",
    ],
    "weekly_planning": [
        "profile_crud_tool",
        "macro_calc_tool",
        "query_tool",
        "plan_assemble_weekly_tool",
        "variety_guard_tool",
    ],
}

# Core tools that are always needed (minimal set)
CORE_TOOLS: Set[str] = {
    "profile_crud_tool",  # User profile is fundamental
    "query_tool",  # Recipe search is core
    "explain_tool",  # Explanation is always useful
}

# Tools that can be loaded on-demand (not in initial decision)
OPTIONAL_TOOLS: Set[str] = {
    "apply_snack_tool",
    "apply_substitute_tool",
    "meal_history_tool",
    "variety_guard_tool",
    "plan_validate_tool",
}


def detect_user_intent(user_prompt: str, conversation_history: List[Dict] = None) -> List[str]:
    """
    Detect user intent from prompt to determine which tools to load.
    
    Args:
        user_prompt: User's input prompt
        conversation_history: Previous conversation messages
        
    Returns:
        List of intent categories (can be multiple)
    """
    prompt_lower = user_prompt.lower()
    intents = []
    
    # Meal planning keywords
    if any(kw in prompt_lower for kw in ["plan", "meal plan", "daily plan", "weekly plan", "menu"]):
        intents.append("meal_planning")
    
    # Meal logging keywords
    if any(kw in prompt_lower for kw in ["log", "ate", "consumed", "track meal", "record meal"]):
        intents.append("meal_logging")
    
    # Recipe search keywords
    if any(kw in prompt_lower for kw in ["find recipe", "search recipe", "recipe", "dish", "food"]):
        intents.append("recipe_search")
    
    # Cooking keywords
    if any(kw in prompt_lower for kw in ["how to cook", "cooking", "steps", "instructions", "prepare"]):
        intents.append("cooking")
    
    # Nutrition tracking keywords
    if any(kw in prompt_lower for kw in ["nutrition", "calorie", "macro", "nutrient", "deficit", "gap"]):
        intents.append("nutrition_tracking")
    
    # Pantry keywords
    if any(kw in prompt_lower for kw in ["pantry", "inventory", "ingredient"]):
        intents.append("pantry_management")
    
    # Substitution keywords
    if any(kw in prompt_lower for kw in ["substitute", "replace", "alternative", "instead of"]):
        intents.append("substitution")
    
    # Weekly planning keywords
    if any(kw in prompt_lower for kw in ["weekly", "week plan", "7 days"]):
        intents.append("weekly_planning")
    
    # If no intent detected, default to core tools
    if not intents:
        intents = ["recipe_search"]  # Most common use case
    
    return intents


def get_tools_for_intents(intents: List[str], include_core: bool = True) -> Set[str]:
    """
    Get set of tools needed for given intents.
    
    Args:
        intents: List of intent categories
        include_core: Whether to include core tools
        
    Returns:
        Set of tool names to load
    """
    tools = set()
    
    if include_core:
        tools.update(CORE_TOOLS)
    
    # Add tools for each intent
    for intent in intents:
        if intent in INTENT_TOOLS:
            tools.update(INTENT_TOOLS[intent])
    
    return tools


def get_optimized_tool_set(
    user_prompt: str,
    conversation_history: List[Dict] = None,
    max_tools: int = 12,
) -> Dict[str, any]:
    """
    Get optimized set of tools to load based on user intent.
    
    Args:
        user_prompt: User's input prompt
        conversation_history: Previous conversation messages
        max_tools: Maximum number of tools to include (default 12, down from 27)
        
    Returns:
        Dictionary of tool_name -> tool_function
    """
    # Detect intent
    intents = detect_user_intent(user_prompt, conversation_history)
    logger.info(f"Detected intents: {intents}")
    
    # Get tools for intents
    tool_names = get_tools_for_intents(intents, include_core=True)
    
    # Limit to max_tools (prioritize core + intent-specific)
    if len(tool_names) > max_tools:
        # Keep core tools
        prioritized = CORE_TOOLS.copy()
        
        # Add intent-specific tools (excluding optional)
        for intent in intents:
            if intent in INTENT_TOOLS:
                for tool in INTENT_TOOLS[intent]:
                    if tool not in OPTIONAL_TOOLS and len(prioritized) < max_tools:
                        prioritized.add(tool)
        
        # Fill remaining slots with other intent tools if needed
        remaining = max_tools - len(prioritized)
        for intent in intents:
            if intent in INTENT_TOOLS:
                for tool in INTENT_TOOLS[intent]:
                    if tool not in prioritized and remaining > 0:
                        prioritized.add(tool)
                        remaining -= 1
        
        tool_names = prioritized
    
    # Build tool dictionary
    optimized_tools = {
        name: MEAL_AGENT_TOOLS[name]
        for name in tool_names
        if name in MEAL_AGENT_TOOLS
    }
    
    logger.info(f"Optimized tool set: {len(optimized_tools)} tools (from {len(MEAL_AGENT_TOOLS)} total)")
    logger.debug(f"Tools: {list(optimized_tools.keys())}")
    
    return optimized_tools


def get_workflow_hint(intents: List[str]) -> Optional[str]:
    """
    Get workflow hint to guide AI execution (reduces decision complexity).
    
    Args:
        intents: Detected intent categories
        
    Returns:
        Workflow hint string or None
    """
    if "meal_planning" in intents:
        return (
            "Workflow: profile_crud_tool → macro_calc_tool → diet_allergen_guard_tool → "
            "time_device_guard_tool → query_tool → query_postprocessing_tool → "
            "score_and_rank_tool → target_resolver_tool → plan_assemble_day_tool → "
            "build_shopping_tool → explain_tool"
        )
    elif "meal_logging" in intents:
        return (
            "Workflow: meal_parser_tool → nutrition_calc_tool → profile_update_tool → explain_tool"
        )
    elif "recipe_search" in intents:
        return (
            "Workflow: query_tool → query_postprocessing_tool → score_and_rank_tool → explain_tool"
        )
    elif "cooking" in intents:
        return "Workflow: query_tool → cook_mode_tool → explain_tool"
    elif "nutrition_tracking" in intents:
        return (
            "Workflow: profile_crud_tool → macro_calc_tool → gap_calc_tool → "
            "suggest_snack_tool → explain_tool"
        )
    
    return None











