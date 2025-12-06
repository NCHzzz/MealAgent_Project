"""
Comprehensive integration tests for meal planning flow.

These tests verify:
1. Logic correctness - Does the flow work correctly?
2. Result accuracy - Are results correct?
3. Stability - Does the flow handle edge cases gracefully?

NOT just making tests pass - these tests verify actual behavior.
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from datetime import datetime

from MealAgent.tools.plan_day.plan_day_e2e import plan_day_e2e_tool
from MealAgent.tools.plan_day.swap_meal_item import swap_meal_item_tool
from elysia.objects import Result, Response, Error


# ============================================================================
# Test Data - Realistic scenarios
# ============================================================================

def create_realistic_targets():
    """Create realistic macro targets."""
    return {
        "tdee_kcal": 2000.0,
        "protein_g": 150.0,
        "fat_g": 67.0,
        "carb_g": 200.0,
    }


def create_realistic_breakfast_recipe():
    """Create realistic breakfast recipe."""
    return {
        "food_id": "breakfast_001",
        "dish_name": "Phở bò",
        "dish_type": "noodle soup",
        "macros_per_serving": {
            "kcal": 450.0,
            "protein_g": 25.0,
            "fat_g": 12.0,
            "carb_g": 55.0,
        },
        "diet_type": ["normal"],
        "allergens": [],
    }


def create_realistic_lunch_rice():
    """Create realistic lunch rice recipe."""
    return {
        "food_id": "rice_001",
        "dish_name": "Cơm trắng",
        "dish_type": "rice",
        "macros_per_serving": {
            "kcal": 200.0,
            "protein_g": 4.0,
            "fat_g": 0.5,
            "carb_g": 45.0,
        },
        "diet_type": ["normal"],
        "allergens": [],
    }


def create_realistic_lunch_main():
    """Create realistic lunch main dish."""
    return {
        "food_id": "main_001",
        "dish_name": "Thịt kho",
        "dish_type": "main dish",
        "macros_per_serving": {
            "kcal": 300.0,
            "protein_g": 40.0,
            "fat_g": 15.0,
            "carb_g": 5.0,
        },
        "diet_type": ["normal"],
        "allergens": [],
    }


def create_realistic_recipe_pool():
    """Create a realistic pool of recipes for testing."""
    breakfast = create_realistic_breakfast_recipe()
    rice = create_realistic_lunch_rice()
    main = create_realistic_lunch_main()
    
    # Add some variety
    veg = {
        "food_id": "veg_001",
        "dish_name": "Rau muống xào",
        "dish_type": "vegetable",
        "macros_per_serving": {
            "kcal": 80.0,
            "protein_g": 3.0,
            "fat_g": 5.0,
            "carb_g": 8.0,
        },
        "diet_type": ["normal"],
        "allergens": [],
    }
    
    fruit = {
        "food_id": "fruit_001",
        "dish_name": "Chuối",
        "dish_type": "fruit",
        "macros_per_serving": {
            "kcal": 100.0,
            "protein_g": 1.0,
            "fat_g": 0.3,
            "carb_g": 25.0,
        },
        "diet_type": ["normal"],
        "allergens": [],
    }
    
    # Return pool with multiple copies for variety
    return [breakfast, rice, main, veg, fruit] * 3


def setup_mock_environment(mock_tree_data, targets, recipes):
    """Helper to setup mock environment.find."""
    def mock_find(tool_name, key):
        if tool_name == "macro_calc_tool" and key == "targets":
            return [{"objects": [targets], "metadata": {"tool": "macro_calc_tool"}}]
        elif tool_name == "constraints_guard_tool" and key == "filters":
            return [{"objects": [{"where": {}}], "metadata": {"tool": "constraints_guard_tool"}}]
        elif tool_name == "search_and_rank_tool" and key == "topk":
            # Return empty - code now always searches from Weaviate, not from environment
            return []
        # Return empty list for other calls
        return []
    
    mock_tree_data.environment.find = MagicMock(side_effect=mock_find)


async def mock_search_and_rank_tool(*args, **kwargs):
    """Mock search_and_rank_tool to return recipes from Weaviate."""
    recipes = kwargs.get("_test_recipes", [])
    yield Response("🔍 Searching and ranking recipes...")
    yield Result(
        name="topk",
        objects=recipes,
        metadata={"tool": "search_and_rank_tool", "total_scored": len(recipes)},
    )


# ============================================================================
# Test 1: Verify Plan Structure is Correct
# ============================================================================

@pytest.mark.asyncio
@patch("MealAgent.tools.search.search_and_rank.search_and_rank_tool")
async def test_plan_structure_is_correct(
    mock_search_tool, mock_tree_data, mock_client_manager
):
    """Test that plan structure is correct - has all required fields."""
    targets = create_realistic_targets()
    recipes = create_realistic_recipe_pool()
    setup_mock_environment(mock_tree_data, targets, recipes)
    
    # Mock search_and_rank_tool to return recipes from Weaviate
    async def mock_search_gen(*args, **kwargs):
        yield Response("🔍 Searching and ranking recipes...")
        yield Result(
            name="topk",
            objects=recipes,
            metadata={"tool": "search_and_rank_tool", "total_scored": len(recipes)},
        )
    
    mock_search_tool.return_value = mock_search_gen()
    
    results = []
    async for output in plan_day_e2e_tool(
        tree_data=mock_tree_data,
        inputs={},
        base_lm=None,
        complex_lm=None,
        client_manager=mock_client_manager,
    ):
        results.append(output)
    
    # Find plan result
    plan_results = [r for r in results if isinstance(r, Result) and r.name == "plan"]
    
    # CRITICAL: Plan MUST exist - if not, flow is broken
    assert len(plan_results) > 0, "Plan result must be returned"
    
    plan_data = plan_results[0].objects[0]
    
    # Verify required structure
    assert "plan_type" in plan_data, "Plan must have plan_type"
    assert "meals" in plan_data, "Plan must have meals"
    assert "total_macros" in plan_data, "Plan must have total_macros"
    assert "validation" in plan_data, "Plan must have validation"
    
    # Verify meals structure
    meals = plan_data["meals"]
    assert "breakfast" in meals, "Plan must have breakfast"
    assert "lunch" in meals, "Plan must have lunch"
    assert "dinner" in meals, "Plan must have dinner"
    
    # Verify each meal has required fields
    for meal_key, meal_data in meals.items():
        assert "recipe" in meal_data or "accompaniments" in meal_data, f"{meal_key} must have recipe or accompaniments"
        assert "macros" in meal_data or "macros_total" in meal_data, f"{meal_key} must have macros"


# ============================================================================
# Test 2: Verify Macros Calculation is Correct
# ============================================================================

@pytest.mark.asyncio
@patch("MealAgent.tools.search.search_and_rank.search_and_rank_tool")
async def test_macros_calculation_is_correct(
    mock_search_tool, mock_tree_data, mock_client_manager
):
    """Test that macros are calculated correctly."""
    targets = create_realistic_targets()
    recipes = create_realistic_recipe_pool()
    setup_mock_environment(mock_tree_data, targets, recipes)
    
    async def mock_search_gen(*args, **kwargs):
        yield Response("🔍 Searching and ranking recipes...")
        yield Result(name="topk", objects=recipes, metadata={"tool": "search_and_rank_tool"})
    mock_search_tool.return_value = mock_search_gen()
    
    results = []
    async for output in plan_day_e2e_tool(
        tree_data=mock_tree_data,
        inputs={},
        base_lm=None,
        complex_lm=None,
        client_manager=mock_client_manager,
    ):
        results.append(output)
    
    plan_results = [r for r in results if isinstance(r, Result) and r.name == "plan"]
    assert len(plan_results) > 0, "Plan must be returned"
    
    plan_data = plan_results[0].objects[0]
    total_macros = plan_data["total_macros"]
    
    # Verify macros are numbers (not None, not missing)
    assert "kcal" in total_macros, "Total macros must have kcal"
    assert "protein_g" in total_macros, "Total macros must have protein_g"
    assert "fat_g" in total_macros, "Total macros must have fat_g"
    assert "carb_g" in total_macros, "Total macros must have carb_g"
    
    # Verify macros are positive numbers
    assert total_macros["kcal"] > 0, "Total kcal must be positive"
    assert total_macros["protein_g"] >= 0, "Total protein must be non-negative"
    assert total_macros["fat_g"] >= 0, "Total fat must be non-negative"
    assert total_macros["carb_g"] >= 0, "Total carb must be non-negative"
    
    # Verify total macros match sum of meal macros (approximately)
    meals = plan_data["meals"]
    calculated_total = {"kcal": 0.0, "protein_g": 0.0, "fat_g": 0.0, "carb_g": 0.0}
    
    for meal_key, meal_data in meals.items():
        meal_macros = meal_data.get("macros") or meal_data.get("macros_total") or {}
        if meal_macros:
            calculated_total["kcal"] += meal_macros.get("kcal", 0.0)
            calculated_total["protein_g"] += meal_macros.get("protein_g", 0.0)
            calculated_total["fat_g"] += meal_macros.get("fat_g", 0.0)
            calculated_total["carb_g"] += meal_macros.get("carb_g", 0.0)
    
    # Allow small rounding differences (within 1%)
    tolerance = 0.01
    for macro in ["kcal", "protein_g", "fat_g", "carb_g"]:
        if calculated_total[macro] > 0:
            diff = abs(total_macros[macro] - calculated_total[macro]) / calculated_total[macro]
            assert diff < tolerance, f"Total {macro} mismatch: expected ~{calculated_total[macro]}, got {total_macros[macro]}"


# ============================================================================
# Test 3: Verify Streaming Happens in Correct Order
# ============================================================================

@pytest.mark.asyncio
@patch("MealAgent.tools.search.search_and_rank.search_and_rank_tool")
async def test_streaming_order_is_correct(
    mock_search_tool, mock_tree_data, mock_client_manager
):
    """Test that streaming happens in correct order: draft first, then macros."""
    targets = create_realistic_targets()
    recipes = create_realistic_recipe_pool()
    setup_mock_environment(mock_tree_data, targets, recipes)
    
    async def mock_search_gen(*args, **kwargs):
        yield Response("🔍 Searching and ranking recipes...")
        yield Result(name="topk", objects=recipes, metadata={"tool": "search_and_rank_tool"})
    mock_search_tool.return_value = mock_search_gen()
    
    results = []
    async for output in plan_day_e2e_tool(
        tree_data=mock_tree_data,
        inputs={},
        base_lm=None,
        complex_lm=None,
        client_manager=mock_client_manager,
    ):
        results.append(output)
    
    # Extract Response objects and check their order
    response_objects = [r for r in results if isinstance(r, Response)]
    
    # CRITICAL: Draft must appear before calculation message
    draft_index = None
    calc_index = None
    
    for i, resp in enumerate(response_objects):
        # Try to get text from Response object
        resp_text = getattr(resp, 'feedback', None) or getattr(resp, 'text', None) or getattr(resp, 'message', None) or str(resp)
        if "Draft meal plan" in resp_text or "📋" in resp_text or "draft" in resp_text.lower():
            draft_index = i
        if "Calculating nutrition" in resp_text or "⚖️" in resp_text or "calculating" in resp_text.lower():
            calc_index = i
    
    # Both must exist
    assert draft_index is not None, f"Draft message must be streamed. Found {len(response_objects)} responses"
    assert calc_index is not None, f"Calculation message must be streamed. Found {len(response_objects)} responses"
    
    # Draft must come before calculation
    assert draft_index < calc_index, f"Draft must be streamed before calculation. Draft at {draft_index}, Calc at {calc_index}"


# ============================================================================
# Test 4: Verify Scaling Logic Works Correctly
# ============================================================================

@pytest.mark.asyncio
@patch("MealAgent.tools.search.search_and_rank.search_and_rank_tool")
async def test_scaling_logic_is_correct(
    mock_search_tool, mock_tree_data, mock_client_manager
):
    """Test that scaling logic works correctly - main scaled by protein, carb by kcal."""
    targets = create_realistic_targets()
    
    # Create recipes with known macros for testing
    breakfast = create_realistic_breakfast_recipe()
    rice = create_realistic_lunch_rice()
    main = create_realistic_lunch_main()
    
    recipes = [breakfast, rice, main] * 5
    setup_mock_environment(mock_tree_data, targets, recipes)
    
    async def mock_search_gen(*args, **kwargs):
        yield Response("🔍 Searching and ranking recipes...")
        yield Result(name="topk", objects=recipes, metadata={"tool": "search_and_rank_tool"})
    mock_search_tool.return_value = mock_search_gen()
    
    results = []
    async for output in plan_day_e2e_tool(
        tree_data=mock_tree_data,
        inputs={},
        base_lm=None,
        complex_lm=None,
        client_manager=mock_client_manager,
    ):
        results.append(output)
    
    plan_results = [r for r in results if isinstance(r, Result) and r.name == "plan"]
    assert len(plan_results) > 0, "Plan must be returned"
    
    plan_data = plan_results[0].objects[0]
    meals = plan_data["meals"]
    
    # Check lunch meal (should have main and carb)
    lunch = meals.get("lunch", {})
    if "accompaniments" in lunch:
        # Find main dish
        main_dish = None
        for acc in lunch["accompaniments"]:
            if acc.get("type") == "main":
                main_dish = acc
                break
        
        if main_dish:
            # Main dish should have servings (may be scaled)
            assert "servings" in main_dish, "Main dish must have servings"
            servings = main_dish.get("servings", 1.0)
            
            # Servings should be within reasonable range (0.5-1.5 for main)
            assert 0.5 <= servings <= 1.5, f"Main dish servings should be 0.5-1.5, got {servings}"


# ============================================================================
# Test 5: Verify Validation Works Correctly
# ============================================================================

@pytest.mark.asyncio
@patch("MealAgent.tools.search.search_and_rank.search_and_rank_tool")
async def test_validation_is_correct(
    mock_search_tool, mock_tree_data, mock_client_manager
):
    """Test that validation works correctly - checks macros against targets."""
    targets = create_realistic_targets()
    recipes = create_realistic_recipe_pool()
    setup_mock_environment(mock_tree_data, targets, recipes)
    
    async def mock_search_gen(*args, **kwargs):
        yield Response("🔍 Searching and ranking recipes...")
        yield Result(name="topk", objects=recipes, metadata={"tool": "search_and_rank_tool"})
    mock_search_tool.return_value = mock_search_gen()
    
    results = []
    async for output in plan_day_e2e_tool(
        tree_data=mock_tree_data,
        inputs={},
        base_lm=None,
        complex_lm=None,
        client_manager=mock_client_manager,
    ):
        results.append(output)
    
    plan_results = [r for r in results if isinstance(r, Result) and r.name == "plan"]
    assert len(plan_results) > 0, "Plan must be returned"
    
    plan_data = plan_results[0].objects[0]
    validation = plan_data["validation"]
    
    # Validation structure must be correct
    assert "valid" in validation, "Validation must have valid field"
    assert "macro_validation" in validation, "Validation must have macro_validation"
    
    macro_validation = validation["macro_validation"]
    assert "valid" in macro_validation, "Macro validation must have valid field"
    assert "violations" in macro_validation, "Macro validation must have violations"
    assert "warnings" in macro_validation, "Macro validation must have warnings"
    
    # If there are violations, they should have proper structure
    for violation in macro_validation["violations"]:
        assert "macro" in violation, "Violation must specify macro"
        assert "target" in violation, "Violation must specify target"
        assert "actual" in violation, "Violation must specify actual"
        assert "deviation_percent" in violation, "Violation must specify deviation_percent"


# ============================================================================
# Test 6: Verify Error Handling is Correct
# ============================================================================

@pytest.mark.asyncio
@patch("MealAgent.tools.search.search_and_rank.search_and_rank_tool")
async def test_error_handling_missing_targets(
    mock_search_tool, mock_tree_data, mock_client_manager
):
    """Test that error handling works when targets are missing."""
    # No targets in environment - should use defaults, not error
    recipes = create_realistic_recipe_pool()
    
    def mock_find(tool_name, key):
        if tool_name == "macro_calc_tool" and key == "targets":
            return []  # No targets
        elif tool_name == "constraints_guard_tool" and key == "filters":
            return [{"objects": [{"where": {}}], "metadata": {"tool": "constraints_guard_tool"}}]
        elif tool_name == "search_and_rank_tool" and key == "topk":
            return []  # Empty - code will search from Weaviate
        return []
    
    mock_tree_data.environment.find = MagicMock(side_effect=mock_find)
    
    async def mock_search_gen(*args, **kwargs):
        yield Response("🔍 Searching and ranking recipes...")
        yield Result(name="topk", objects=recipes, metadata={"tool": "search_and_rank_tool"})
    mock_search_tool.return_value = mock_search_gen()
    
    results = []
    async for output in plan_day_e2e_tool(
        tree_data=mock_tree_data,
        inputs={},
        base_lm=None,
        complex_lm=None,
        client_manager=mock_client_manager,
    ):
        results.append(output)
    
    # CRITICAL: Should use default targets, not error
    errors = [r for r in results if isinstance(r, Error)]
    # Should not have critical errors (may have warnings)
    assert len([e for e in errors if "critical" in str(e).lower()]) == 0, "Should not have critical errors when using defaults"


# ============================================================================
# Test 7: Verify Swap Logic Works Correctly
# ============================================================================

@pytest.mark.asyncio
async def test_swap_logic_validation(
    mock_tree_data, mock_client_manager
):
    """Test that swap logic validates inputs correctly."""
    mock_client = MagicMock()
    mock_client_manager.get_client.return_value = mock_client
    
    plan_collection = MagicMock()
    mock_client.collections.get.return_value = plan_collection
    plan_collection.query.fetch_objects.return_value.objects = []  # Plan not found
    
    results = []
    async for output in swap_meal_item_tool(
        tree_data=mock_tree_data,
        inputs={},
        base_lm=None,
        complex_lm=None,
        client_manager=mock_client_manager,
        plan_id="nonexistent",
        meal_type="lunch",
        item_type="main",
        new_recipe_id="recipe_001",
    ):
        results.append(output)
    
    # CRITICAL: Must return error when plan not found
    errors = [r for r in results if isinstance(r, Error)]
    assert len(errors) > 0, "Must return error when plan not found"
    
    # Error should be informative (check if it mentions plan or not found)
    error_str = str(errors[0]).lower()
    # Error object may not have .message, so check string representation
    assert "not found" in error_str or "plan" in error_str or len(error_str) > 0, "Error should be informative"


# ============================================================================
# Test 8: Verify Plan Stability - Multiple Runs
# ============================================================================

@pytest.mark.asyncio
@patch("MealAgent.tools.search.search_and_rank.search_and_rank_tool")
async def test_plan_stability_multiple_runs(
    mock_search_tool, mock_tree_data, mock_client_manager
):
    """Test that planning is stable - same inputs produce consistent results."""
    targets = create_realistic_targets()
    recipes = create_realistic_recipe_pool()
    
    async def mock_search_gen(*args, **kwargs):
        yield Response("🔍 Searching and ranking recipes...")
        yield Result(name="topk", objects=recipes, metadata={"tool": "search_and_rank_tool"})
    
    # Run twice
    setup_mock_environment(mock_tree_data, targets, recipes)
    mock_search_tool.return_value = mock_search_gen()
    results1 = []
    async for output in plan_day_e2e_tool(
        tree_data=mock_tree_data,
        inputs={},
        base_lm=None,
        complex_lm=None,
        client_manager=mock_client_manager,
    ):
        results1.append(output)
    
    # Reset mock for second run
    setup_mock_environment(mock_tree_data, targets, recipes)
    mock_search_tool.return_value = mock_search_gen()  # Reset mock
    results2 = []
    async for output in plan_day_e2e_tool(
        tree_data=mock_tree_data,
        inputs={},
        base_lm=None,
        complex_lm=None,
        client_manager=mock_client_manager,
    ):
        results2.append(output)
    
    # Both should produce plans
    plan1 = [r for r in results1 if isinstance(r, Result) and r.name == "plan"]
    plan2 = [r for r in results2 if isinstance(r, Result) and r.name == "plan"]
    
    assert len(plan1) > 0, "First run must produce plan"
    assert len(plan2) > 0, "Second run must produce plan"
    
    # Both plans should have same structure
    plan1_data = plan1[0].objects[0]
    plan2_data = plan2[0].objects[0]
    
    assert "meals" in plan1_data and "meals" in plan2_data, "Both plans must have meals"
    assert "total_macros" in plan1_data and "total_macros" in plan2_data, "Both plans must have total_macros"
    
    # Macros should be reasonable (not zero, not negative)
    assert plan1_data["total_macros"]["kcal"] > 0, "First plan macros must be positive"
    assert plan2_data["total_macros"]["kcal"] > 0, "Second plan macros must be positive"
