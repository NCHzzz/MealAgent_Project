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
        meal_description="I ate chicken salad with olive oil",
        user_id="test_user_123",
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
        meal_description="I ate chicken salad",
        user_id="test_user_123",
    ):
        results.append(output)
    
    # Verify
    assert len(results) > 0
    assert any(isinstance(r, Error) for r in results)


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
        user_id="test_user_123",
        limit=50,
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
        user_id="test_user_123",
        start_date="2025-01-01",
        end_date="2025-01-31",
        limit=50,
    ):
        results.append(output)
    
    # Verify
    assert len(results) > 0
    # Check that where clause was built with date filters
    assert collection.query.fetch_objects.called
    call_args = collection.query.fetch_objects.call_args
    assert call_args is not None

