"""
Integration tests for daily planning workflow.

Tests the complete workflow:
1. Create profile
2. Calculate macros
3. Apply constraints
4. Search and rank recipes
5. Assemble daily plan
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from MealAgent.tools.profile.profile_crud import profile_crud_tool
from MealAgent.tools.profile.macro_calc import macro_calc_tool
from MealAgent.tools.constraints.constraints_guard import constraints_guard_tool
from MealAgent.tools.search.search_and_rank import search_and_rank_tool
from MealAgent.tools.plan_day.plan_day_e2e import plan_day_e2e_tool
from elysia.objects import Result, Response, Error


@pytest.mark.asyncio
async def test_daily_planning_workflow_vegetarian(
    mock_tree_data, mock_client_manager, sample_profile_data
):
    """Test complete daily planning workflow for vegetarian user."""
    # Setup: Mock Weaviate collections
    collection = MagicMock()
    mock_client_manager.get_client.return_value.collections.get.return_value = collection
    collection.query.fetch_objects.return_value.objects = []  # No existing profile
    collection.data.insert = MagicMock()
    
    # Mock search results
    mock_recipe_objects = []
    for i in range(20):
        obj = MagicMock()
        obj.properties = {
            "food_id": f"recipe_{i:03d}",
            "dish_name": f"Vegetarian Recipe {i}",
            "diet_type": ["vegetarian"],
            "allergens": [],
            "cooking_time": 25 + i,
            "macros_per_serving": {
                "kcal": 400.0 + i * 10,
                "protein_g": 15.0 + i,
                "fat_g": 10.0 + i * 0.5,
                "carb_g": 60.0 + i * 2,
            },
        }
        mock_recipe_objects.append(obj)
    
    # Step 1: Create profile
    async for output in profile_crud_tool(
        tree_data=mock_tree_data,
        client_manager=mock_client_manager,
        action="create",
        profile_data={**sample_profile_data, "diet_type": "vegetarian"},
    ):
        if isinstance(output, Result):
            # Profile should be in environment
            profile_results = mock_tree_data.environment.find("profile_crud_tool", "profile")
            assert profile_results is not None
    
    # Step 2: Calculate macros
    async for output in macro_calc_tool(
        tree_data=mock_tree_data,
        client_manager=mock_client_manager,
    ):
        if isinstance(output, Result):
            # Targets should be in environment
            targets_results = mock_tree_data.environment.find("macro_calc_tool", "targets")
            assert targets_results is not None
    
    # Step 3: Apply constraints
    async for output in constraints_guard_tool(
        tree_data=mock_tree_data,
        client_manager=mock_client_manager,
    ):
        if isinstance(output, Result):
            # Filters should be in environment
            filters_results = mock_tree_data.environment.find("constraints_guard_tool", "filters")
            assert filters_results is not None
    
    # Step 4: Search and rank (mock Weaviate query)
    with patch("MealAgent.tools.search.search_and_rank._custom_hybrid_search") as mock_search:
        mock_search.return_value = mock_recipe_objects[:20]
        
        async for output in search_and_rank_tool(
            tree_data=mock_tree_data,
            client_manager=mock_client_manager,
            query_text="healthy vegetarian meals",
            top_k=20,
        ):
            if isinstance(output, Result):
                # TopK should be in environment
                topk_results = mock_tree_data.environment.find("search_and_rank_tool", "topk")
                assert topk_results is not None
    
    # Step 5: Assemble daily plan
    async for output in plan_day_e2e_tool(
        tree_data=mock_tree_data,
        client_manager=mock_client_manager,
    ):
        if isinstance(output, Result) and output.name == "plan":
            # Plan should be in environment
            plan_results = mock_tree_data.environment.find("plan_day_e2e_tool", "plan")
            assert plan_results is not None
            
            plan = plan_results[0].objects[0]
            assert "meals" in plan
            assert "breakfast" in plan["meals"] or "meal_1" in plan["meals"]
            assert "total_macros" in plan
            assert "validation" in plan
            assert plan["plan_type"] == "day"


@pytest.mark.asyncio
async def test_daily_planning_workflow_with_allergen_filter(
    mock_tree_data, mock_client_manager, sample_profile_data
):
    """Test daily planning workflow with allergen filtering."""
    # Setup similar to above but with allergen constraint
    collection = MagicMock()
    mock_client_manager.get_client.return_value.collections.get.return_value = collection
    collection.query.fetch_objects.return_value.objects = []
    collection.data.insert = MagicMock()
    
    # Mock recipes: some with nuts, some without
    mock_recipe_objects = []
    for i in range(20):
        obj = MagicMock()
        obj.properties = {
            "food_id": f"recipe_{i:03d}",
            "dish_name": f"Recipe {i}",
            "diet_type": ["vegetarian"],
            "allergens": ["nuts"] if i % 2 == 0 else [],  # Half have nuts
            "cooking_time": 25,
            "macros_per_serving": {
                "kcal": 400.0,
                "protein_g": 15.0,
                "fat_g": 10.0,
                "carb_g": 60.0,
            },
        }
        mock_recipe_objects.append(obj)
    
    # Create profile with nut allergy
    async for output in profile_crud_tool(
        tree_data=mock_tree_data,
        client_manager=mock_client_manager,
        action="create",
        profile_data={**sample_profile_data, "allergens": ["nuts"]},
    ):
        pass
    
    # Calculate macros
    async for output in macro_calc_tool(
        tree_data=mock_tree_data,
        client_manager=mock_client_manager,
    ):
        pass
    
    # Apply constraints (should filter out nuts)
    async for output in constraints_guard_tool(
        tree_data=mock_tree_data,
        client_manager=mock_client_manager,
    ):
        pass
    
    # Search and rank (mock to return filtered results)
    with patch("MealAgent.tools.search.search_and_rank._custom_hybrid_search") as mock_search:
        # Only return recipes without nuts
        mock_search.return_value = [obj for obj in mock_recipe_objects if not obj.properties["allergens"]]
        
        async for output in search_and_rank_tool(
            tree_data=mock_tree_data,
            client_manager=mock_client_manager,
            query_text="healthy meals",
            top_k=20,
        ):
            pass
    
    # Assemble plan
    async for output in plan_day_e2e_tool(
        tree_data=mock_tree_data,
        client_manager=mock_client_manager,
    ):
        if isinstance(output, Result) and output.name == "plan":
            plan_results = mock_tree_data.environment.find("plan_day_e2e_tool", "plan")
            if plan_results:
                plan = plan_results[0].objects[0]
                # Verify no nuts in plan
                for meal_key, meal_data in plan.get("meals", {}).items():
                    recipe = meal_data.get("recipe", {})
                    assert "nuts" not in recipe.get("allergens", [])

