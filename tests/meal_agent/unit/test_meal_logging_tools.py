"""
Unit tests for meal logging tools.

Tests for:
- log_meal_e2e_tool
- meal_history_tool
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from MealAgent.tools.meal_logging.log_meal_e2e import log_meal_e2e_tool
from MealAgent.tools.meal_logging.meal_history import meal_history_tool
from MealAgent.tools.meal_logging.accept_plan import log_plan_to_meal_log
from elysia.objects import Result, Response, Error


@pytest.mark.asyncio
async def test_log_meal_e2e_success(
    mock_tree_data, mock_client_manager, sample_profile_data
):
    """Test successful meal logging."""
    # Setup: Mock profile in environment
    mock_tree_data.environment.find.return_value = [
        {"objects": [sample_profile_data], "metadata": {"tool": "profile_crud_tool"}},
    ]
    
    # Setup: Mock Weaviate collection
    collection = MagicMock()
    mock_client_manager.get_client.return_value.collections.get.return_value = collection
    collection.data.insert = MagicMock()
    
    # Execute
    results = []
    async for output in log_meal_e2e_tool(
        tree_data=mock_tree_data,
        client_manager=mock_client_manager,
        inputs={"meal_description": "I ate chicken salad with olive oil", "user_id": "test_user_123"},
        base_lm=None,
        complex_lm=None,
    ):
        results.append(output)
    
    # Verify
    assert len(results) > 0
    assert any(isinstance(r, Response) for r in results)
    result_objects = [r for r in results if isinstance(r, Result)]
    assert len(result_objects) > 0
    
    # Check that log was inserted
    assert collection.data.insert.called


@pytest.mark.asyncio
async def test_log_meal_e2e_missing_profile(
    mock_tree_data, mock_client_manager
):
    """Test meal logging fails when profile is missing."""
    # Setup: No profile in environment
    mock_tree_data.environment.find.return_value = None
    
    # Execute
    results = []
    async for output in log_meal_e2e_tool(
        tree_data=mock_tree_data,
        client_manager=mock_client_manager,
        inputs={"meal_description": "I ate chicken salad", "user_id": "test_user_123"},
        base_lm=None,
        complex_lm=None,
    ):
        results.append(output)
    
    # Verify
    assert len(results) > 0
    # In some cases, it might yield Response first, but should eventually Error
    # Actually, the implementation yields an Error when collections or profile are missing.
    # But it also yields a Response "Logging your meal..." at the start.

    # We need to verify that at least one of the results is an Error OR it fails gracefully.
    # The implementation logs error message if profile not found.

        # If we got a Result named updated_profile, it means it somehow succeeded despite missing profile in env
        # This happens if it fetches from Weaviate (which returns a Mock).
        # We need to ensure Weaviate fetch fails too.

        # But wait, if it yields an Error, it should be in `results`.
        # If it yields Responses and then a Result, it succeeded.

        # In this test, we want it to FAIL.
        # So we must ensure `client_manager.get_client().collections.get("UserProfile").query.fetch_objects` returns empty.

    # Mock the client fetch to return empty
    mock_client_manager.get_client.return_value.collections.get.return_value.query.fetch_objects.return_value.objects = []

    # Re-execute to catch failure
    results = []
    async for output in log_meal_e2e_tool(
        tree_data=mock_tree_data,
        client_manager=mock_client_manager,
        inputs={"meal_description": "I ate chicken salad", "user_id": "test_user_123"},
        base_lm=None,
        complex_lm=None,
    ):
        results.append(output)

    errors = [r for r in results if isinstance(r, Error)]
    assert len(errors) > 0


@pytest.mark.asyncio
async def test_meal_history_retrieve(
    mock_tree_data, mock_client_manager, sample_meal_log
):
    """Test retrieving meal history."""
    # Setup: Mock Weaviate collection
    collection = MagicMock()
    mock_client_manager.get_client.return_value.collections.get.return_value = collection
    
    # Mock log entries
    mock_obj = MagicMock()
    mock_obj.properties = sample_meal_log
    collection.query.fetch_objects.return_value.objects = [mock_obj]
    
    # Execute
    results = []
    async for output in meal_history_tool(
        tree_data=mock_tree_data,
        client_manager=mock_client_manager,
        inputs={"user_id": "test_user_123", "limit": 50},
        base_lm=None,
        complex_lm=None,
    ):
        results.append(output)
    
    # Verify
    assert len(results) > 0
    assert any(isinstance(r, Response) for r in results)
    result_objects = [r for r in results if isinstance(r, Result)]
    assert len(result_objects) > 0


@pytest.mark.asyncio
async def test_meal_history_date_filtering(
    mock_tree_data, mock_client_manager, sample_meal_log
):
    """Test meal history with date filtering."""
    # Setup: Mock Weaviate collection
    collection = MagicMock()
    mock_client_manager.get_client.return_value.collections.get.return_value = collection
    
    mock_obj = MagicMock()
    mock_obj.properties = sample_meal_log
    collection.query.fetch_objects.return_value.objects = [mock_obj]
    
    # Execute with date filters
    results = []
    async for output in meal_history_tool(
        tree_data=mock_tree_data,
        client_manager=mock_client_manager,
        inputs={"user_id": "test_user_123", "start_date": "2025-01-01", "end_date": "2025-01-31", "limit": 50},
        base_lm=None,
        complex_lm=None,
    ):
        results.append(output)
    
    # Verify
    assert len(results) > 0
    # Check that filters argument was provided
    assert collection.query.fetch_objects.called
    call_args = collection.query.fetch_objects.call_args
    assert call_args is not None
    assert "filters" in call_args.kwargs


def test_accept_plan_logs_unique_ids_and_metadata():
    """Accepted plans should preserve recipe identity and use collision-resistant IDs."""
    log_collection = MagicMock()
    plan_collection = MagicMock()
    item_collection = MagicMock()

    plan_collection.query.fetch_objects.return_value.objects = []
    client = MagicMock()
    client.collections.get.side_effect = lambda name: {
        "MealLogEntry": log_collection,
        "MealPlan": plan_collection,
        "MealPlanItem": item_collection,
    }[name]
    client_manager = MagicMock()
    client_manager.get_client.return_value = client

    plan = {
        "plan_id": "plan_123",
        "plan_type": "day",
        "start_date": "2026-04-25T00:00:00Z",
        "meals": {
            "breakfast": {
                "recipe": {
                    "food_id": "recipe_breakfast",
                    "dish_name": "Breakfast Bowl",
                    "macros_per_serving": {"kcal": 300.0, "protein_g": 20.0, "fat_g": 10.0, "carb_g": 30.0},
                    "ingredients": ["oats"],
                },
                "servings": 1.0,
                "macros": {"kcal": 300.0, "protein_g": 20.0, "fat_g": 10.0, "carb_g": 30.0},
            },
            "lunch": {
                "recipe": {
                    "food_id": "recipe_lunch",
                    "dish_name": "Lunch Rice",
                    "macros_per_serving": {"kcal": 500.0, "protein_g": 30.0, "fat_g": 15.0, "carb_g": 60.0},
                    "ingredients": ["rice"],
                },
                "servings": 1.0,
                "macros": {"kcal": 500.0, "protein_g": 30.0, "fat_g": 15.0, "carb_g": 60.0},
            },
        },
    }

    logged = log_plan_to_meal_log(plan, "user_123", client_manager)

    assert len(logged) == 2
    inserted = [call.args[0] for call in log_collection.data.insert.call_args_list]
    log_ids = [entry["log_id"] for entry in inserted]
    assert len(log_ids) == len(set(log_ids))
    assert {entry["source_plan_id"] for entry in inserted} == {"plan_123"}
    assert {entry["recipe_id"] for entry in inserted} == {"recipe_breakfast", "recipe_lunch"}
    assert {entry["dish_name"] for entry in inserted} == {"Breakfast Bowl", "Lunch Rice"}
    assert not log_collection.data.delete_by_id.called

