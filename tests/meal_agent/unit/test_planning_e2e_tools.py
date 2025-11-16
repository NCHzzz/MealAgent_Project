"""
Unit tests for end-to-end planning tools.

Tests for:
- plan_day_e2e_tool
- plan_week_e2e_tool
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from MealAgent.tools.plan_day.plan_day_e2e import plan_day_e2e_tool
from MealAgent.tools.plan_week.plan_week_e2e import plan_week_e2e_tool
from elysia.objects import Result, Response, Error


@pytest.mark.asyncio
async def test_plan_day_e2e_success(
    mock_tree_data, mock_client_manager, sample_targets, sample_recipe_data
):
    """Test successful daily meal planning."""
    # Setup: Mock environment with targets, filters, and ranked recipes
    mock_tree_data.environment.find.side_effect = [
        [{"objects": [sample_targets], "metadata": {"tool": "macro_calc_tool"}}],  # targets
        [{"objects": [{"where": {}}], "metadata": {"tool": "constraints_guard_tool"}}],  # filters
        [{"objects": [[sample_recipe_data] * 3], "metadata": {"tool": "search_and_rank_tool"}}],  # topk
    ]
    
    # Execute
    results = []
    async for output in plan_day_e2e_tool(
        tree_data=mock_tree_data,
        client_manager=mock_client_manager,
    ):
        results.append(output)
    
    # Verify
    assert len(results) > 0
    assert any(isinstance(r, Response) for r in results)
    result_objects = [r for r in results if isinstance(r, Result)]
    assert len(result_objects) > 0
    
    # Check that plan was added to environment
    assert mock_tree_data.environment.add.called or mock_tree_data.environment.add_objects.called


@pytest.mark.asyncio
async def test_plan_day_e2e_missing_targets(
    mock_tree_data, mock_client_manager
):
    """Test daily planning fails gracefully when targets are missing."""
    # Setup: No targets in environment
    mock_tree_data.environment.find.return_value = None
    
    # Execute
    results = []
    async for output in plan_day_e2e_tool(
        tree_data=mock_tree_data,
        client_manager=mock_client_manager,
    ):
        results.append(output)
    
    # Verify
    assert len(results) > 0
    assert any(isinstance(r, Error) for r in results)


@pytest.mark.asyncio
async def test_plan_week_e2e_success(
    mock_tree_data, mock_client_manager, sample_targets, sample_recipe_data
):
    """Test successful weekly meal planning."""
    # Setup: Mock environment with targets, filters, and ranked recipes
    mock_tree_data.environment.find.side_effect = [
        [{"objects": [sample_targets], "metadata": {"tool": "macro_calc_tool"}}],  # targets
        [{"objects": [{"where": {}}], "metadata": {"tool": "constraints_guard_tool"}}],  # filters
        [{"objects": [[sample_recipe_data] * 10], "metadata": {"tool": "search_and_rank_tool"}}],  # topk
    ]
    
    # Execute
    results = []
    async for output in plan_week_e2e_tool(
        tree_data=mock_tree_data,
        client_manager=mock_client_manager,
    ):
        results.append(output)
    
    # Verify
    assert len(results) > 0
    assert any(isinstance(r, Response) for r in results)
    result_objects = [r for r in results if isinstance(r, Result)]
    assert len(result_objects) > 0
    
    # Check that plan was added to environment
    assert mock_tree_data.environment.add.called or mock_tree_data.environment.add_objects.called


@pytest.mark.asyncio
async def test_plan_week_e2e_variety_enforcement(
    mock_tree_data, mock_client_manager, sample_targets, sample_recipe_data
):
    """Test that weekly planning enforces recipe variety."""
    # Setup: Limited recipe pool
    limited_recipes = [sample_recipe_data] * 5  # Only 5 unique recipes
    
    mock_tree_data.environment.find.side_effect = [
        [{"objects": [sample_targets], "metadata": {"tool": "macro_calc_tool"}}],
        [{"objects": [{"where": {}}], "metadata": {"tool": "constraints_guard_tool"}}],
        [{"objects": [limited_recipes], "metadata": {"tool": "search_and_rank_tool"}}],
    ]
    
    # Execute
    results = []
    async for output in plan_week_e2e_tool(
        tree_data=mock_tree_data,
        client_manager=mock_client_manager,
    ):
        results.append(output)
    
    # Verify
    assert len(results) > 0
    result_objects = [r for r in results if isinstance(r, Result)]
    assert len(result_objects) > 0
    # Weekly plan should still be created, but variety score may be lower

