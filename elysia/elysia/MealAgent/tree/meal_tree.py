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

from typing import AsyncGenerator, Dict, Any, Optional
from elysia.tree.objects import TreeData
from elysia.objects import Result, Error
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
) -> AsyncGenerator[Result | str | Error, None]:
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
    yield "Starting daily meal planning workflow..."

    # Step 1: Ensure profile exists (read or create)
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

    # Step 3: Generate constraint filters
    diet_guard = MEAL_AGENT_TOOLS["diet_allergen_guard_tool"]
    async for result in diet_guard(
        tree_data=tree_data,
        client_manager=client_manager,
        **kwargs,
    ):
        if isinstance(result, Error):
            yield result
            return
        yield result

    time_guard = MEAL_AGENT_TOOLS["time_device_guard_tool"]
    async for result in time_guard(
        tree_data=tree_data,
        client_manager=client_manager,
        **kwargs,
    ):
        if isinstance(result, Error):
            yield result
            return
        yield result

    # Step 4: Search recipes
    query_tool = MEAL_AGENT_TOOLS["query_tool"]
    async for result in query_tool(
        tree_data=tree_data,
        client_manager=client_manager,
        query_text=query_text,
        **kwargs,
    ):
        if isinstance(result, Error):
            yield result
            return
        yield result

    # Step 5: Postprocess and rank
    postprocess_tool = MEAL_AGENT_TOOLS["query_postprocessing_tool"]
    async for result in postprocess_tool(
        tree_data=tree_data,
        client_manager=client_manager,
        **kwargs,
    ):
        if isinstance(result, Error):
            yield result
            return
        yield result

    score_tool = MEAL_AGENT_TOOLS["score_and_rank_tool"]
    async for result in score_tool(
        tree_data=tree_data,
        client_manager=client_manager,
        **kwargs,
    ):
        if isinstance(result, Error):
            yield result
            return
        yield result

    # Step 6: Resolve targets
    target_tool = MEAL_AGENT_TOOLS["target_resolver_tool"]
    async for result in target_tool(
        tree_data=tree_data,
        client_manager=client_manager,
        **kwargs,
    ):
        if isinstance(result, Error):
            yield result
            return
        yield result

    # Step 7: Assemble daily plan
    assemble_tool = MEAL_AGENT_TOOLS["plan_assemble_day_tool"]
    async for result in assemble_tool(
        tree_data=tree_data,
        client_manager=client_manager,
        **kwargs,
    ):
        if isinstance(result, Error):
            yield result
            return
        yield result

    # Step 8: Validate plan
    validate_tool = MEAL_AGENT_TOOLS["plan_validate_tool"]
    async for result in validate_tool(
        tree_data=tree_data,
        client_manager=client_manager,
        **kwargs,
    ):
        if isinstance(result, Error):
            yield result
            return
        yield result

    # Step 9: Build shopping list
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

    yield "Daily planning workflow completed successfully"


async def process_meal_logging_workflow(
    tree_data: TreeData,
    client_manager: ClientManager,
    base_lm,
    user_id: str,
    meal_description: str,
    **kwargs,
) -> AsyncGenerator[Result | str | Error, None]:
    """
    Orchestrate meal logging workflow.

    Workflow:
    1. Parse meal description (LLM)
    2. Calculate nutrition
    3. Update profile with consumed nutrition

    This is a helper function that can be called from a decision tree node.
    """
    yield "Starting meal logging workflow..."

    # Step 1: Parse meal
    parser_tool = MEAL_AGENT_TOOLS["meal_parser_tool"]
    async for result in parser_tool(
        tree_data=tree_data,
        client_manager=client_manager,
        base_lm=base_lm,
        meal_description=meal_description,
        **kwargs,
    ):
        if isinstance(result, Error):
            yield result
            return
        yield result

    # Step 2: Calculate nutrition
    calc_tool = MEAL_AGENT_TOOLS["nutrition_calc_tool"]
    async for result in calc_tool(
        tree_data=tree_data,
        client_manager=client_manager,
        **kwargs,
    ):
        if isinstance(result, Error):
            yield result
            return
        yield result

    # Step 3: Update profile
    update_tool = MEAL_AGENT_TOOLS["profile_update_tool"]
    async for result in update_tool(
        tree_data=tree_data,
        client_manager=client_manager,
        user_id=user_id,
        **kwargs,
    ):
        if isinstance(result, Error):
            yield result
            return
        yield result

    yield "Meal logging workflow completed successfully"


async def process_cooking_workflow(
    tree_data: TreeData,
    client_manager: ClientManager,
    base_lm,
    user_id: Optional[str] = None,
    food_id: Optional[str] = None,
    **kwargs,
) -> AsyncGenerator[Result | str | Error, None]:
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
    yield "Starting cooking workflow..."

    # Step 1 & 2: Cooking steps
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
            async for result in explain_tool(
                tree_data=tree_data,
                client_manager=client_manager,
                base_lm=base_lm,
                **kwargs,
            ):
                if isinstance(result, Error):
                    # Explanation is optional; warn and continue
                    yield f"Warning: explanation failed: {result.message}"
                    break
                yield result
    except Exception:
        # Explanation optional; ignore hard failures
        pass

    yield "Cooking workflow completed successfully"


async def process_explanation_workflow(
    tree_data: TreeData,
    client_manager: ClientManager,
    base_lm,
    **kwargs,
) -> AsyncGenerator[Result | str | Error, None]:
    """
    Orchestrate explanation workflow (summarize decisions made so far).

    Assumes previous tools (profile/targets/constraints/search/plan) have populated
    the environment. Uses explain_tool to compose a user-facing summary.
    """
    yield "Starting explanation workflow..."

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

    yield "Explanation workflow completed successfully"


def build_meal_agent_tree(
    settings: Settings | None = None,
    user_id: str | None = None,
) -> Tree:
    """
    Create a new Elysia Tree dedicated to MealAgent and attach tools
    to logical branches according to the MealAgent design.

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

    # Helper to add tool by name to a branch if exists
    def add_tool(branch_id: str, name: str):
        fn = MEAL_AGENT_TOOLS.get(name)
        if fn is not None:
            tree.add_tool(fn, branch_id=branch_id)

    # Register tools to branches
    # profile
    add_tool("profile", "profile_crud_tool")
    add_tool("profile", "macro_calc_tool")

    # constraints
    add_tool("constraints", "diet_allergen_guard_tool")
    add_tool("constraints", "time_device_guard_tool")

    # search + nutrition
    add_tool("search", "query_tool")
    add_tool("search", "query_postprocessing_tool")
    add_tool("search", "score_and_rank_tool")
    add_tool("nutrition", "calculate_recipe_macros_tool")

    # plan_day
    add_tool("plan_day", "target_resolver_tool")
    add_tool("plan_day", "plan_assemble_day_tool")
    add_tool("plan_day", "plan_validate_tool")
    add_tool("shopping", "build_shopping_tool")

    # plan_week
    add_tool("plan_week", "plan_assemble_weekly_tool")
    add_tool("plan_week", "variety_guard_tool")

    # pantry + shopping
    add_tool("pantry", "pantry_crud_tool")
    add_tool("shopping", "pantry_diff_tool")

    # gap fill
    add_tool("gap_fill", "gap_calc_tool")
    add_tool("gap_fill", "suggest_snack_tool")
    add_tool("gap_fill", "apply_snack_tool")

    # substitution
    add_tool("substitution", "suggest_substitutes_tool")
    add_tool("substitution", "apply_substitute_tool")

    # micros
    add_tool("micros", "micronutrient_check_tool")
    add_tool("micros", "suggest_micros_foods_tool")

    # logging
    add_tool("logging", "meal_parser_tool")
    add_tool("logging", "nutrition_calc_tool")
    add_tool("logging", "profile_update_tool")
    add_tool("logging", "meal_history_tool")

    # cooking & explain
    add_tool("cooking", "cook_mode_tool")
    add_tool("explain", "explain_tool")

    return tree
