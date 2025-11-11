"""
MealAgent decision tree workflow orchestration.

This module provides workflow functions that coordinate MealAgent tools
in the correct sequence for common use cases (daily planning, meal logging, etc.).

Usage:
    These workflow functions can be used in two ways:
    
    1. As reference for tree configuration:
       - Use the workflow steps as a guide when configuring decision tree nodes
       - Each step corresponds to a tool that should be registered in the tree
    
    2. As helper functions in custom tree nodes:
       - Import and call these functions from a decision tree node
       - They handle error propagation and tool sequencing automatically
       - Example:
         ```python
         from elysia.MealAgent.tree.meal_tree import process_daily_planning_workflow
         
         async def my_tree_node(tree_data, client_manager, base_lm, **kwargs):
             async for result in process_daily_planning_workflow(
                 tree_data=tree_data,
                 client_manager=client_manager,
                 base_lm=base_lm,
                 user_id=kwargs.get("user_id"),
                 query_text=kwargs.get("query_text", ""),
             ):
                 yield result
         ```
    
    Note: These functions are NOT automatically integrated into the Elysia Tree.
    They must be explicitly called from tree nodes or used as reference for tree configuration.
"""

from typing import AsyncGenerator, Dict, Any, Optional, List
import logging

from elysia.tree.objects import TreeData
from elysia.objects import Result, Error, Status, Response
from elysia.util.client import ClientManager
from elysia.tree.tree import Tree
from elysia.config import Settings

# Import all tools
from elysia.MealAgent.tree.config import MEAL_AGENT_TOOLS


async def process_daily_planning_workflow(
    tree_data: TreeData,
    client_manager: ClientManager,
    base_lm,
    user_id: str,
    query_text: str = "",
    **kwargs,
) -> AsyncGenerator[Result | Status | Error, None]:
    """
    Orchestrate daily meal planning workflow.

    Workflow:
    1. Read/validate user profile
    2. Calculate macro targets
    3. Generate constraint filters
    4. Search recipes
    5. Postprocess and rank
    6. Resolve targets
    7. Assemble daily plan
    8. Validate plan
    9. Build shopping list

    This is a helper function that can be called from a decision tree node
    or used as a reference for tree configuration.
    """
    yield Status("Starting daily meal planning workflow...")

    # Step 1: Ensure profile exists (read or create)
    yield Status("Loading user profile...")
    profile_tool = MEAL_AGENT_TOOLS["profile_crud_tool"]
    async for result in profile_tool(
        tree_data=tree_data,
        client_manager=client_manager,
        action="read",
        profile_data={"user_id": user_id},
        **kwargs,
    ):
        if isinstance(result, Error):
            yield result
            return
        yield result

    # Step 2: Calculate macro targets
    yield Status("Calculating macro targets...")
    macro_tool = MEAL_AGENT_TOOLS["macro_calc_tool"]
    async for result in macro_tool(
        tree_data=tree_data,
        client_manager=client_manager,
        **kwargs,
    ):
        if isinstance(result, Error):
            yield result
            return
        yield result

    # Step 3: Combined constraints
    yield Status("Generating combined constraints (diet/allergens/time/devices)...")
    constraints_tool = MEAL_AGENT_TOOLS["constraints_guard_tool"]
    async for result in constraints_tool(
        tree_data=tree_data,
        client_manager=client_manager,
        **kwargs,
    ):
        if isinstance(result, Error):
            yield result
            return
        yield result

    # Step 4-5: Search and rank in one step
    yield Status(f"Searching and ranking recipes for query: '{query_text}'...")
    sr_tool = MEAL_AGENT_TOOLS["search_and_rank_tool"]
    async for result in sr_tool(
        tree_data=tree_data,
        client_manager=client_manager,
        query_text=query_text,
        **kwargs,
    ):
        if isinstance(result, Error):
            yield result
            return
        yield result

    # Step 6-8: Assemble plan in one step
    yield Status("Assembling daily plan and validating against targets...")
    e2e_plan_tool = MEAL_AGENT_TOOLS["plan_day_e2e_tool"]
    async for result in e2e_plan_tool(
        tree_data=tree_data,
        client_manager=client_manager,
        **kwargs,
    ):
        if isinstance(result, Error):
            yield result
            return
        yield result

    # Step 7: Build shopping list
    yield Status("Building shopping list from plan and pantry...")
    shopping_tool = MEAL_AGENT_TOOLS["build_shopping_tool"]
    async for result in shopping_tool(
        tree_data=tree_data,
        client_manager=client_manager,
        **kwargs,
    ):
        if isinstance(result, Error):
            yield result
            return
        yield result

    yield Status("Daily planning workflow completed successfully")


async def process_meal_logging_workflow(
    tree_data: TreeData,
    client_manager: ClientManager,
    base_lm,
    user_id: str,
    meal_description: str,
    **kwargs,
) -> AsyncGenerator[Result | Status | Error, None]:
    """
    Orchestrate meal logging workflow.

    Workflow:
    1. Parse meal description (LLM)
    2. Calculate nutrition
    3. Update profile with consumed nutrition

    This is a helper function that can be called from a decision tree node.
    """
    yield Status("Starting meal logging workflow...")

    # One-step logging: parse → calc → update
    yield Status("Parsing meal description and calculating nutrition, then updating profile...")
    log_e2e_tool = MEAL_AGENT_TOOLS["log_meal_e2e_tool"]
    async for result in log_e2e_tool(
        tree_data=tree_data,
        client_manager=client_manager,
        base_lm=base_lm,
        user_id=user_id,
        meal_description=meal_description,
        **kwargs,
    ):
        if isinstance(result, Error):
            yield result
            return
        yield result

    yield Status("Meal logging workflow completed successfully")


async def process_cooking_workflow(
    tree_data: TreeData,
    client_manager: ClientManager,
    base_lm,
    user_id: Optional[str] = None,
    food_id: Optional[str] = None,
    **kwargs,
) -> AsyncGenerator[Result | Status | Error, None]:
    """
    Orchestrate cooking workflow (produce step-by-step guidance).

    Workflow:
    1. Ensure a plan/search result exists (caller should run planning or search).
    2. Run cook_mode_tool to extract steps.
    3. (Optional) Run explain_tool to provide a short rationale.

    Notes:
    - The tool will try to pick a recipe from daily/weekly plan or search topk.
    - Provide food_id to target a specific recipe.
    """
    yield Status("Starting cooking workflow...")

    # Resolve recipe_id from environment if not provided
    if food_id is None:
        # 1) prefer previously selected cook_mode_tool.recipe_id
        selected = tree_data.environment.find("cook_mode_tool", "recipe_id")
        if selected and selected[0]["objects"]:
            obj = selected[0]["objects"][0]
            food_id = str(obj.get("food_id") or obj.get("recipe_id") or "").strip() or None

        # 2) fallback to first item from search topk
        if food_id is None:
            for tool_name in ("search_and_rank_tool", "score_and_rank_tool"):
                res = tree_data.environment.find(tool_name, "topk")
                if res and res[0]["objects"]:
                    first = res[0]["objects"][0]
                    fid = str(first.get("food_id") or "").strip()
                    if fid:
                        # persist selection for future steps following environment_keys.md (cook_mode_tool.recipe_id)
                        try:
                            tree_data.environment.add_objects(
                                "cook_mode_tool",
                                "recipe_id",
                                [{"food_id": fid}],
                                metadata={"source": tool_name},
                            )
                        except Exception:
                            pass
                        food_id = fid
                        break

    # Step 1 & 2: Cooking steps
    yield Status("Preparing step-by-step cooking guidance...")
    cook_tool = MEAL_AGENT_TOOLS["cook_mode_tool"]
    async for result in cook_tool(
        tree_data=tree_data,
        client_manager=client_manager,
        food_id=food_id,
        **kwargs,
    ):
        if isinstance(result, Error):
            yield result
            return
        yield result

    # Step 3: Optional explanation
    try:
        explain_tool = MEAL_AGENT_TOOLS.get("explain_tool")
        if explain_tool:
            yield Status("Generating explanation (optional)...")
            async for result in explain_tool(
                tree_data=tree_data,
                client_manager=client_manager,
                base_lm=base_lm,
                **kwargs,
            ):
                if isinstance(result, Error):
                    # Explanation is optional; warn and continue
                    yield Status(f"Warning: explanation failed: {result.message}")
                    break
                yield result
    except Exception:
        # Explanation optional; ignore hard failures
        pass

    yield Status("Cooking workflow completed successfully")


async def process_explanation_workflow(
    tree_data: TreeData,
    client_manager: ClientManager,
    base_lm,
    **kwargs,
) -> AsyncGenerator[Result | Status | Error, None]:
    """
    Orchestrate explanation workflow (summarize decisions made so far).

    Assumes previous tools (profile/targets/constraints/search/plan) have populated
    the environment. Uses explain_tool to compose a user-facing summary.
    """
    yield Status("Starting explanation workflow...")

    explain_tool = MEAL_AGENT_TOOLS["explain_tool"]
    async for result in explain_tool(
        tree_data=tree_data,
        client_manager=client_manager,
        base_lm=base_lm,
        **kwargs,
    ):
        if isinstance(result, Error):
            yield result
            return
        yield result

    yield Status("Explanation workflow completed successfully")


def build_meal_agent_tree(
    settings: Settings | None = None,
    user_id: str | None = None,
    user_prompt: str | None = None,
    conversation_history: List[Dict] | None = None,
    optimize_tools: bool = True,
) -> Tree:
    """
    Create a new Elysia Tree dedicated to MealAgent and attach tools
    to logical branches according to the MealAgent design.

    Args:
        settings: Elysia settings
        user_id: User ID
        user_prompt: Optional user prompt for intent-based tool optimization
        conversation_history: Optional conversation history for context
        optimize_tools: If True, only load tools relevant to user intent (default: True)

    Branch layout (ids):
      - profile
      - constraints
      - search
      - nutrition
      - plan_day
      - plan_week
      - pantry
      - shopping
      - gap_fill
      - substitution
      - micros
      - logging
      - cooking
      - explain

    Note: This sets up branches and registers tools for each branch. You can still
    orchestrate execution order via workflows or tree node logic.
    """
    tree = Tree(branch_initialisation="empty", settings=settings, user_id=user_id)
    
    # Optimize tool loading based on user intent
    tools_to_load = None
    if optimize_tools and user_prompt:
        try:
            from elysia.MealAgent.tree.tool_optimizer import get_optimized_tool_set
            optimized = get_optimized_tool_set(
                user_prompt=user_prompt,
                conversation_history=conversation_history,
                max_tools=12,  # Reduce from 27 to 12
            )
            tools_to_load = set(optimized.keys())
            logging.info(f"MealAgent: Optimized tool loading - {len(tools_to_load)} tools (from 27 total)")
        except Exception as e:
            logging.warning(f"MealAgent: Tool optimization failed, loading all tools: {e}")
            tools_to_load = None

    # Note: Do NOT hardcode intent keywords here. The decision agent should
    # infer completion based on environment signals written by tools (see
    # tool docstrings for reads/writes and completion hints).

    # Create branches (stem from root)
    branch_ids = [
        "profile",
        "constraints",
        "search",
        "nutrition",
        "plan_day",
        "plan_week",
        "pantry",
        "shopping",
        "gap_fill",
        "substitution",
        "micros",
        "logging",
        "cooking",
        "explain",
    ]
    root_id = getattr(tree, "root", "base")
    for bid in branch_ids:
        try:
            tree.add_branch(
                bid,
                instruction=f"MealAgent {bid} branch",
                description=f"MealAgent {bid} tools",
                from_branch_id=root_id,
            )
        except Exception:
            # Branch may already exist
            pass

    # Track tool names that have been added so we can reference them in chains
    added_tool_names: dict[str, str] = {}

    def add_tool(branch_id: str, name: str, chain: list[str] | None = None):
        # Skip if tool optimization is enabled and tool not in optimized set
        if tools_to_load is not None and name not in tools_to_load:
            return
        fn = MEAL_AGENT_TOOLS.get(name)
        if fn is not None:
            # Resolve chain to actual tool names already added
            from_tool_ids: list[str] = []
            if chain:
                for chained_name in chain:
                    actual = added_tool_names.get(chained_name)
                    if actual:
                        from_tool_ids.append(actual)
                    else:
                        logging.debug(
                            f"MealAgent tree: chain reference '{chained_name}' not found for '{name}', "
                            "adding tool without chain."
                        )
                        from_tool_ids = []
                        break

            # Determine tool names before adding so we can detect the new entry
            before_tool_names = set(tree.tools.keys())

            tree.add_tool(fn, branch_id=branch_id, from_tool_ids=from_tool_ids)

            after_tool_names = set(tree.tools.keys())
            new_names = list(after_tool_names - before_tool_names)

            if new_names:
                added_tool_names[name] = new_names[0]
            else:
                # Fallback to metadata if diff failed
                added_tool_names[name] = getattr(fn, "_tool_name", name)

    # Register tools to branches with successive chains where appropriate

    # profile
    add_tool("profile", "profile_crud_tool")
    add_tool("profile", "macro_calc_tool", chain=["profile_crud_tool"])

    # constraints (combined)
    add_tool("constraints", "constraints_guard_tool")

    # search + nutrition
    add_tool("search", "search_and_rank_tool")
    add_tool("nutrition", "calculate_recipe_macros_tool")

    # plan_day
    add_tool("plan_day", "plan_day_e2e_tool")
    add_tool("shopping", "build_shopping_tool")

    # plan_week
    add_tool("plan_week", "plan_assemble_weekly_tool")
    add_tool(
        "plan_week",
        "variety_guard_tool",
        chain=["plan_assemble_weekly_tool"],
    )

    # pantry + shopping
    add_tool("pantry", "pantry_crud_tool")
    add_tool("shopping", "pantry_diff_tool")

    # gap fill
    add_tool("gap_fill", "gap_calc_tool")
    add_tool("gap_fill", "suggest_snack_tool", chain=["gap_calc_tool"])
    add_tool(
        "gap_fill",
        "apply_snack_tool",
        chain=["gap_calc_tool", "suggest_snack_tool"],
    )

    # substitution
    add_tool("substitution", "suggest_substitutes_tool")
    add_tool(
        "substitution",
        "apply_substitute_tool",
        chain=["suggest_substitutes_tool"],
    )

    # micros
    add_tool("micros", "micronutrient_check_tool")
    add_tool(
        "micros",
        "suggest_micros_foods_tool",
        chain=["micronutrient_check_tool"],
    )

    # logging
    add_tool("logging", "log_meal_e2e_tool")
    add_tool(
        "logging",
        "meal_history_tool",
    )

    # cooking & explain
    add_tool("cooking", "cook_mode_tool")
    add_tool("explain", "explain_tool")

    return tree
