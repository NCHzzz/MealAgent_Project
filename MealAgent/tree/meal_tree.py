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
         from MealAgent.tree.meal_tree import process_daily_planning_workflow
         
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
from elysia.tools.text.text import CitedSummarizer, FakeTextResponse

# Import all tools
from MealAgent.tree.config import MEAL_AGENT_TOOLS


def _contains_any(needle: str, keywords: list[str]) -> bool:
    """Utility helper to check if any keyword is present in the string."""
    return any(keyword in needle for keyword in keywords)


def _detect_intent_hint(user_prompt: str | None) -> Optional[str]:
    """
    Lightweight heuristic router derived from requirements/design docs.
    Returns a hint string (e.g., 'optimization:deficit_gap_fill') that we expose
    to the tree environment so the decision agent can align with expectations.
    """
    if not user_prompt:
        return None

    lowered = user_prompt.lower()

    deficit_keywords = [
        "thiếu",  # Vietnamese "missing" / "deficit"
        "bổ sung",
        "còn thiếu",
        "còn thiếu khoảng",
        "thêm ",
        "+",
        "kcal",
        "calo",
        "cal",
        "gap fill",
        "đồ ăn nhẹ",
        "snack",
        "ăn thêm",
        "post workout",
    ]
    if _contains_any(lowered, deficit_keywords):
        return "optimization:deficit_gap_fill"

    plan_keywords = [
        "thực đơn",
        "kế hoạch",
        "meal plan",
        "plan cho",
        "plan tuần",
        "plan ngày",
        # Treat generic Vietnamese daily meal suggestion as a planning request,
        # since users almost always mean a full-day plan (bf/lunch/dinner),
        # not just 1–2 standalone recipes.
        "gợi ý bữa",
        "gợi ý bữa ăn hôm nay",
        "gợi ý bữa ăn cho hôm nay",
        "gợi ý bữa ăn trong ngày",
        "gợi ý thực đơn hôm nay",
        "gợi ý ăn hôm nay",
        "gợi ý hôm nay ăn gì",
        "hôm nay ăn gì",
        "gợi ý bữa hôm nay",
        "gợi ý bữa ngày hôm nay",
        "thực đơn hôm nay",
        "thực đơn cho hôm nay",
        "thực đơn ngày hôm nay",
    ]
    if _contains_any(lowered, plan_keywords):
        return "planning:new_plan"

    pantry_keywords = ["pantry", "tủ", "đồ khô", "shopping", "mua sắm", "chợ", "hết nguyên liệu"]
    if _contains_any(lowered, pantry_keywords):
        return "pantry:inventory"

    cooking_keywords = ["nấu", "cách làm", "cook", "recipe steps", "hướng dẫn", "làm sao", "cooking"]
    if _contains_any(lowered, cooking_keywords):
        return "cooking:steps"

    logging_keywords = ["đã ăn", "vừa ăn", "log", "ghi lại bữa", "nhập bữa", "ăn gì"]
    if _contains_any(lowered, logging_keywords):
        return "logging:meal_entry"

    return None


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

    # Step 6-8: Assemble plan in one step (plan_day_e2e_tool handles everything)
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

    # Note: Shopping list can be generated via pantry_diff_tool which reads from plan_day_e2e_tool.plan or plan_week_e2e_tool.plan

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
    3. (Optional) Use Elysia's cited_summarize tool to provide a short rationale.

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
            res = tree_data.environment.find("search_and_rank_tool", "topk")
            if res and res[0]["objects"]:
                first = res[0]["objects"][0]
                fid = str(first.get("food_id") or first.get("recipe_id") or "").strip()
                if fid:
                    # persist selection for future steps following environment_keys.md (cook_mode_tool.recipe_id)
                    try:
                        tree_data.environment.add_objects(
                            "cook_mode_tool",
                            "recipe_id",
                            [{"food_id": fid}],
                            metadata={"source": "search_and_rank_tool"},
                        )
                    except Exception:
                        pass
                    food_id = fid

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
    # Note: Use Elysia's cited_summarize tool for explanations (not a MealAgent tool)
    # This is handled by the Tree's decision agent, not manually here
    # If explanation is needed, the Tree will automatically select cited_summarize tool

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
    the environment. Uses Elysia's cited_summarize tool to compose a user-facing summary.
    
    Note: This workflow is handled by Elysia's built-in cited_summarize tool.
    The Tree's decision agent will automatically select cited_summarize when user requests explanation.
    """
    yield Status("Starting explanation workflow...")
    yield Status("Note: Use Elysia's cited_summarize tool for explanations. The Tree will automatically select it when needed.")
    yield Status("Explanation workflow completed successfully")


def build_meal_agent_tree(
    settings: Settings | None = None,
    user_id: str | None = None,
    conversation_id: str | None = None,
    style: str = "Friendly and helpful meal planning assistant",
    agent_description: str = "Meal planning agent that helps users create personalized meal plans",
    end_goal: str = "Generate meal plans that meet user's nutritional targets and preferences",
    low_memory: bool = False,
    use_elysia_collections: bool = True,
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
        conversation_id: Conversation ID for tracking conversations
        style: Style of agent responses
        agent_description: Description of agent's role and capabilities
        end_goal: Criteria for when the decision tree should end
        low_memory: If True, reduce memory usage
        use_elysia_collections: If True, use Elysia-processed collections
        user_prompt: Optional user prompt for intent-based tool optimization
        conversation_history: Optional conversation history for context
        optimize_tools: If True, only load tools relevant to user intent (default: True)

    Branch layout (nutrition-first flow - 9 branches):
      - profile: Profile management and macro calculation
      - search: Recipe/food search and ranking
      - nutrition: Nutrition calculation (per-recipe and batch)
      - planning: Daily/weekly meal planning (merged from plan_day + plan_week)
      - optimization: Gap fill, substitution, micros (merged from 3 branches)
      - pantry: Pantry and shopping list management (merged from pantry + shopping)
      - logging: Meal logging and history
      - cooking: Cooking mode
      - explain: Explanations (using Elysia cited_summarize)

    Note: This sets up branches and registers tools for each branch. You can still
    orchestrate execution order via workflows or tree node logic.
    """
    tree = Tree(
        branch_initialisation="empty",
        settings=settings,
        user_id=user_id,
        conversation_id=conversation_id,
        style=style,
        agent_description=agent_description,
        end_goal=end_goal,
        low_memory=low_memory,
        use_elysia_collections=use_elysia_collections,
    )

    logging.debug(
        "MealAgent: build_meal_agent_tree called with user_id=%r, conversation_id=%r",
        user_id,
        conversation_id,
    )

    # Persist identifiers for downstream tools (plan_day, logging, etc.)
    if user_id:
        tree.tree_data.environment.hidden_environment["user_id"] = user_id
        logging.debug(
            "MealAgent: hidden_environment user_id set to '%s' on tree creation", user_id
        )
    if conversation_id:
        tree.tree_data.environment.hidden_environment["conversation_id"] = conversation_id
    
    # Optimize tool loading based on user intent
    # Note: Tool optimization feature is planned for future enhancement.
    # Currently, all tools are loaded. When tool_optimizer module is implemented,
    # uncomment the code below to enable intent-based tool loading.
    tools_to_load = None
    if optimize_tools and user_prompt:
        # Future enhancement: Intent-based tool optimization
        # from MealAgent.tree.tool_optimizer import get_optimized_tool_set
        # optimized = get_optimized_tool_set(
        #     user_prompt=user_prompt,
        #     conversation_history=conversation_history,
        #     max_tools=12,
        # )
        # tools_to_load = set(optimized.keys())
        # logging.info(f"MealAgent: Optimized tool loading - {len(tools_to_load)} tools")
        logging.debug("MealAgent: Tool optimization not yet implemented, loading all tools")
        tools_to_load = None

    # Surface heuristic intent hints (derived from requirements/design)
    intent_hint = _detect_intent_hint(user_prompt)
    if intent_hint:
        try:
            tree.tree_data.environment.add_objects(
                "intent_router",
                "detected_intent",
                [
                    {
                        "intent": intent_hint,
                        "user_prompt": user_prompt,
                    }
                ],
                metadata={"source": "heuristic"},
            )
        except Exception as exc:
            logging.debug(f"MealAgent: unable to persist intent hint '{intent_hint}': {exc}")

    # Note: Do NOT hardcode intent keywords here. The decision agent should
    # infer completion based on environment signals written by tools (see
    # tool docstrings for reads/writes and completion hints).

    # Create root branch first (required - this is the starting point)
    root_id = "root"
    if root_id not in tree.decision_nodes:
        tree.add_branch(
            branch_id=root_id,
            instruction=(
                "Read the user's prompt AND any intent_router.detected_intent objects in the environment before acting. "
                "Follow the requirements/design docs mapping, and ALWAYS respect detected intent hints first: "
                "- If environment intent hint == planning:new_plan → prefer the planning branch (daily/weekly plan) even if the wording "
                "looks like a generic suggestion (e.g. 'gợi ý bữa ăn hôm nay', 'hôm nay ăn gì'). "
                "- If prompt mentions deficit keywords (\"thiếu\", \"bổ sung\", \"thêm\", \"+200 kcal\", \"snack\", \"ăn thêm\") "
                "or environment intent hint == optimization:deficit_gap_fill → go to optimization branch (gap_fill/substitute/micros). "
                "- If user explicitly requests a new plan ('thực đơn', 'kế hoạch', 'meal plan' cho ngày/tuần, 'gợi ý bữa ăn hôm nay', "
                "'hôm nay ăn gì', 'gợi ý bữa ăn cho hôm nay') OR environment intent hint == planning:new_plan → planning branch. "
                "- Pantry/shopping inventory → pantry branch. "
                "- Cooking steps/how to make for a specific dish name (e.g. 'cách nấu phở bò', 'công thức nấu phở bò viên', "
                "'cho tôi công thức nấu phở bò viên') OR environment intent hint == cooking:steps → DIRECTLY choose the cooking "
                "branch and call cook_mode_tool first. cook_mode_tool can search for the recipe itself from the user prompt using "
                "BM25 on the dish name; do NOT go to the search branch first in these cases. "
                "- Meal logging ('vừa ăn', 'log', 'ghi lại bữa') → logging branch. "
                "CRITICAL: After plan_day_e2e_tool OR plan_week_e2e_tool completes, they already stream a summary and set stop_calling_tool=True/end_conversation=True in Result metadata. "
                "When you see plan_week_e2e_tool.plan or plan_day_e2e_tool.plan in environment with metadata containing stop_calling_tool=True or end_conversation=True, "
                "the planning task is COMPLETE. Check if the user's initial prompt contained multiple requests (e.g. 'plan AND shopping list'). "
                "The planning tools now use 'Smart Stop' logic: they will automatically SIGNAL completion (stop_calling_tool=True) "
                "if only a plan was requested. If a shopping list is also needed, the tools will allow the flow to continue to 'pantry' branch. "
                "The planning tool already provides a complete summary - no additional explanation or text response is needed unless the user explicitly asks."
                "- Explicit requests for explanations/summary → explain branch. "
                "CRITICAL: DO NOT automatically call accept_plan_tool or log_meal_e2e_tool after plan_day_e2e_tool or plan_week_e2e_tool completes. "
                "plan_week_e2e_tool only saves to MealPlan/MealPlanItem (suggested plan), NOT to MealLogEntry. "
                "Only call accept_plan_tool or log_meal_e2e_tool when user explicitly accepts (via UI button, chat message like 'chấp nhận', 'accept', or when user logs actual consumed meals). "
                "CRITICAL: After accept_plan_tool completes successfully, the task is COMPLETE. "
                "DO NOT call profile_crud_tool, macro_calc_tool, or any other tools. "
                "Simply confirm to the user that the plan has been saved and END the conversation. "
                "- Recipe browsing without full plan (user wants a list or multiple suggestions, e.g. 'gợi ý món', 'các món với ức gà') → search branch. "
                "Do NOT use the search branch for single-dish 'cách nấu X' / 'công thức nấu X' style requests; use cooking instead. "
                "If none match, ask the user a clarifying question before selecting a branch."
            ),
            root=True,
        )
        logging.debug(f"MealAgent: successfully created root branch '{root_id}'")
    
    # Branch configurations (nutrition-first flow - 9 branches)
    BRANCH_CONFIGS = {
        "profile": {
            "instruction": "Capture or update user profile information and compute TDEE/targets.",
            "description": "Run when onboarding or adjusting personal data (age, weight, allergens).",
            "status": "Managing profile...",
        },
        "search": {
            "instruction": (
                "Discover candidate recipes using hybrid search and guardrails. "
                "Use this when the user wants to browse or compare multiple recipes (lists, suggestions, filters). "
                "If the prompt is a direct cooking request for a specific dish (contains phrases like 'cách nấu', 'công thức nấu', "
                "'cho tôi công thức nấu X'), DO NOT choose this branch – go to the cooking branch and let cook_mode_tool handle search."
            ),
            "description": "Recipe browsing and discovery (lists/suggestions). Not for single-dish 'cách nấu X' requests.",
            "status": "Searching recipes...",
        },
        "nutrition": {
            "instruction": "Ensure recipes have complete macro/micro data before planning.",
            "description": "Triggers per-recipe or batch nutrition calculations.",
            "status": "Calculating nutrition...",
        },
        "planning": {
            "instruction": (
                "Assemble NEW daily/weekly meal plans per requirements doc. "
                "Only choose this when the user explicitly requests a 'thực đơn/kế hoạch' cho ngày/tuần "
                "or asks for a comprehensive plan refresh. "
                "If the user only needs to add calories/snacks or tweak a current plan, DO NOT use this branch—go to optimization. "
                "CRITICAL: Both plan_day_e2e_tool and plan_week_e2e_tool stream their own summary and set stop_calling_tool=True/end_conversation=True. "
                "After they emit Result(name='plan') with stop_calling_tool=True, DO NOT call explain or cited_summarize unless the user explicitly asks for a recap. "
                "CRITICAL: plan_week_e2e_tool ONLY saves to MealPlan/MealPlanItem (suggested plan storage), NOT to MealLogEntry. "
                "DO NOT automatically call accept_plan_tool or log_meal_e2e_tool after planning completes. "
                "Only call accept_plan_tool or log_meal_e2e_tool when user explicitly accepts the plan (via UI button, chat message like 'chấp nhận'/'accept', or when user logs actual consumed meals). "
                "After planning completes, the planning tools will automatically SIGNAL completion (stop_calling_tool=True) "
                "if only a plan was requested. If a shopping list is also needed, the flow will automatically continue to the 'pantry' branch. "
                "Respect the metadata signals to avoid unnecessary tool calls or redundant explanations."
            ),
            "description": (
                "Runs plan_day_e2e_tool / plan_week_e2e_tool to build a fresh plan using profile, targets, constraints, and ranked recipes. "
                "Requires full planning workflow and typically yields `plan_day_e2e_tool.plan` objects. "
                "Planning tool already summarizes; avoid extra summarize/explain unless user asks."
            ),
            "status": "Planning meals...",
        },
        "optimization": {
            "instruction": (
                "Optimize EXISTING plans: gap fill snacks to cover deficits, substitute dishes, check micronutrients. "
                "Triggered by prompts like 'thiếu/bổ sung X kcal', 'ăn thêm snack', 'fill the gap', or any request to tweak today's plan. "
                "If intent_router hint == optimization:deficit_gap_fill, stay in this branch."
            ),
            "description": (
                "Requires an existing plan/log context (environment plan_day_e2e_tool.plan or plan_week_e2e_tool.plan). "
                "Prefer adding gap_fill_tool suggestions over rebuilding the full day."
            ),
            "status": "Optimizing plan...",
        },
        "pantry": {
            "instruction": "Update pantry inventory and derive shopping list diffs.",
            "description": "Uses active plan to figure out needed items.",
            "status": "Managing pantry...",
        },
        "logging": {
            "instruction": (
                "Log consumed meals and inspect meal history. "
                "CRITICAL: Use accept_plan_tool ONLY when: "
                "1. User explicitly accepts a plan via UI button (accept plan button), OR "
                "2. User chat message indicates acceptance ('chấp nhận', 'accept', 'đồng ý', 'ok'), OR "
                "3. User logs actual consumed meals ('vừa ăn', 'đã ăn', 'log meal'). "
                "DO NOT call accept_plan_tool automatically after plan_week_e2e_tool or plan_day_e2e_tool completes. "
                "plan_week_e2e_tool already saves to MealPlan/MealPlanItem; accept_plan_tool is only for logging to MealLogEntry when user accepts. "
                "After accept_plan_tool completes successfully, the task is COMPLETE - DO NOT call any additional tools. "
                "Simply confirm to the user and END the conversation."
            ),
            "description": "Updates remaining targets and feeds gap analysis. Use accept_plan_tool for plan acceptance.",
            "status": "Logging meal...",
        },
        "cooking": {
            "instruction": (
                "Provide step-by-step cooking instructions for selected recipes OR for a specific dish name directly from the user prompt. "
                "If the prompt clearly asks how to cook a particular dish (e.g. 'cách nấu phở bò', 'công thức nấu phở bò viên', "
                "'cho tôi công thức nấu X'), go to this branch FIRST and call cook_mode_tool – it can auto-search for the recipe "
                "by dish name without needing search_and_rank_tool. "
                "CRITICAL: Before calling cook_mode_tool, check if cook_mode_tool.completed "
                "already exists for ALL recipes in the plan (or the requested food_id). "
                "If ALL recipes are already completed, the task is ALREADY DONE - do NOT call "
                "cook_mode_tool again. If the user asks for a recap, you may go to 'explain'; "
                "otherwise END the conversation. "
                "After cook_mode_tool emits Result(name='task_complete') with "
                "metadata.task_complete=True, stop_calling_tool=True, and end_conversation=True, "
                "the user's cooking request is FULLY SATISFIED. "
                "You MUST either END the conversation or only go to 'explain' if the user explicitly asks. "
                "If cook_mode_tool has batch_processed=True or all_completed=True in metadata, "
                "ALL dishes have been processed - END unless the user requests a summary. "
                "Do NOT call cook_mode_tool multiple times for the same food_id. "
                "Do NOT automatically call the explain branch after cooking; only do so if the user explicitly asks."
            ),
            "description": "Handles both recipes selected from plans/search and direct 'cách nấu X' prompts via cook_mode_tool's auto-search. Cooking alone is usually enough to satisfy the request. Respect task_complete signals to avoid redundant calls. After completion, choose 'explain' branch or END conversation.",
            "status": "Cooking...",
        },
        "explain": {
            "instruction": (
                "Summarize decisions and provide rationale to the user. "
                "Use ONLY when the user explicitly requests explanation/summary/rationale. "
                "CRITICAL: Do NOT use this branch if plan_week_e2e_tool or plan_day_e2e_tool just completed. "
                "These tools already stream a complete summary and set stop_calling_tool=True/end_conversation=True in Result metadata. "
                "If you see plan_week_e2e_tool.plan or plan_day_e2e_tool.plan in environment, the planning is COMPLETE - END conversation instead of calling explain. "
                "Do NOT use this branch to re-list cooking steps when the user only asked "
                "for 'công thức nấu ăn' or 'hướng dẫn nấu' – cook_mode_tool already "
                "returns detailed instructions and a short summary. "
                "CRITICAL: After summarizing, END the conversation. Use end_actions=True in your final decision."
                "DO NOT call accept_plan_tool or log_meal_e2e_tool unless user explicitly accepts the plan."
            ),
            "description": "Use cited_summarize only when user asks for explanation/summary. Planning tool already summarizes inline.",
            "status": "Summarizing...",
        },
    }
    
    # Create branches (nutrition-first flow - 9 branches)
    for branch_id, config in BRANCH_CONFIGS.items():
        try:
            # Check if branch already exists
            if branch_id in tree.decision_nodes:
                logging.debug(f"MealAgent: branch '{branch_id}' already exists, skipping")
                continue
            tree.add_branch(
                branch_id=branch_id,
                instruction=config["instruction"],
                description=config["description"],
                from_branch_id=root_id,
                status=config["status"],
            )
            logging.debug(f"MealAgent: successfully added branch '{branch_id}'")
        except Exception as e:
            logging.warning(f"MealAgent: failed to add branch '{branch_id}': {e}")
            # Continue with other branches
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

            try:
                # Verify branch exists before adding tool
                if branch_id not in tree.decision_nodes:
                    logging.error(f"MealAgent: branch '{branch_id}' does not exist, cannot add tool '{name}'")
                    return
                
                tree.add_tool(fn, branch_id=branch_id, from_tool_ids=from_tool_ids)
                logging.debug(f"MealAgent: successfully added tool '{name}' to branch '{branch_id}'")

                after_tool_names = set(tree.tools.keys())
                new_names = list(after_tool_names - before_tool_names)

                if new_names:
                    added_tool_names[name] = new_names[0]
                else:
                    # Fallback: use tool's name attribute if available
                    tool_name = getattr(fn, "name", None) or getattr(fn, "_tool_name", name)
                    added_tool_names[name] = tool_name
                    logging.debug(f"MealAgent: tool '{name}' registered as '{tool_name}'")
            except Exception as e:
                # Log error but continue with other tools to ensure maximum tool registration
                logging.error(
                    f"MealAgent: failed to add tool '{name}' to branch '{branch_id}': {e}. "
                    f"Continuing with other tools..."
                )
                # Don't raise - allow other tools to register even if one fails

    # Register tools to branches (nutrition-first flow)

    # profile branch
    add_tool("profile", "profile_crud_tool")
    add_tool("profile", "macro_calc_tool", chain=["profile_crud_tool"])

    # search branch
    # constraints_guard_tool should run before search_and_rank_tool to provide filters
    add_tool("search", "constraints_guard_tool")
    add_tool("search", "search_and_rank_tool", chain=["constraints_guard_tool"])

    # nutrition branch
    add_tool("nutrition", "calculate_recipe_macros_tool")
    add_tool("nutrition", "auto_calculate_macros_tool")

    # planning branch (plan_day + plan_week)
    add_tool("planning", "plan_day_e2e_tool")
    add_tool("planning", "plan_week_e2e_tool")

    # logging branch
    add_tool("logging", "log_meal_e2e_tool")
    add_tool("logging", "accept_plan_tool")  # Preferred tool for accepting plans
    add_tool("logging", "meal_history_tool")

    # pantry branch (merged from pantry + shopping)
    # Note: pantry_diff_tool is NOT chained because it should only be called when user
    # explicitly wants a shopping list from a meal plan, not when just listing pantry items.
    add_tool("pantry", "pantry_crud_tool")
    add_tool("pantry", "pantry_diff_tool")  # Agent decides when to call based on user intent

    # optimization branch (merged from gap_fill + substitution + micros)
    add_tool("optimization", "gap_fill_tool")
    add_tool("optimization", "substitute_tool")
    add_tool("optimization", "micros_tool")

    # cooking branch
    add_tool("cooking", "cook_mode_tool")
    
    # explain branch: Register Elysia's built-in explanation tools
    # NOTE (performance): cited_summarize can be quite slow/expensive for large plans (e.g. weekly plans
    # with 21 meals). Since MealAgent tools (plan_day_e2e_tool / plan_week_e2e_tool) already stream
    # their own human‑readable explanations and summaries, we only register the lightweight
    # FakeTextResponse here to avoid an extra heavy LLM summarize step.
    #
    # If you ever want the old behaviour back (full cited_summarize), add CitedSummarizer() again.
    try:
        if "explain" in tree.decision_nodes:
            tree.add_tool(FakeTextResponse(), branch_id="explain")
            logging.debug(
                "MealAgent: successfully added lightweight text_response tool to 'explain' branch (cited_summarize disabled for speed)"
            )
        else:
            logging.warning(
                "MealAgent: 'explain' branch does not exist, cannot register explanation tools"
            )
    except Exception as e:
        logging.error(
            f"MealAgent: failed to register explanation tools to 'explain' branch: {e}"
        )

    return tree


def import_meal_agent_tree_from_json(json_data: dict) -> Tree:
    """
    Rehydrate a MealAgent-specific tree from saved JSON, ensuring all tools are registered.
    """

    settings = Settings.from_json(json_data["settings"])
    # IMPORTANT: Always use low_memory=False when loading tree from JSON/Weaviate
    # to ensure chat history and model cache are preserved for continued interaction.
    # The original low_memory value from JSON is ignored to prevent loss of interaction capability.
    tree = build_meal_agent_tree(
        settings=settings,
        user_id=json_data["user_id"],
        conversation_id=json_data["conversation_id"],
        style=json_data["tree_data"]["atlas"]["style"],
        agent_description=json_data["tree_data"]["atlas"]["agent_description"],
        end_goal=json_data["tree_data"]["atlas"]["end_goal"],
        low_memory=False,  # Always False to preserve chat interaction
        use_elysia_collections=json_data["use_elysia_collections"],
    )

    tree.returner.store = json_data["frontend_rebuild"]
    tree.tree_data = TreeData.from_json(json_data["tree_data"])
    tree.branch_initialisation = json_data["branch_initialisation"]
    tree.tree_index = json_data.get("tree_index", tree.tree_index)
    tree.store_retrieved_objects = json_data.get(
        "store_retrieved_objects", tree.store_retrieved_objects
    )

    return tree
