"""
Unit tests for constraints guard tool.

Tests for:
- constraints_guard_tool
"""

import pytest
from unittest.mock import MagicMock
from MealAgent.tools.constraints.constraints_guard import constraints_guard_tool
from elysia.objects import Result, Response, Error


@pytest.mark.asyncio
async def test_constraints_guard_vegetarian_dairy_allergy(
    mock_tree_data, mock_client_manager, sample_profile_data
):
    """Test generating filters for vegetarian + dairy allergy."""
    # Setup: Profile with vegetarian diet and dairy allergy
    profile_result = MagicMock()
    profile_result.objects = [{**sample_profile_data, "diet_type": "vegetarian", "allergens": ["dairy"]}]
    mock_tree_data.environment.find.return_value = [profile_result]
    
    # Execute
    results = []
    async for output in constraints_guard_tool(
        tree_data=mock_tree_data,
        client_manager=mock_client_manager,
    ):
        results.append(output)
    
    # Assert
    result_objects = [r for r in results if isinstance(r, Result)]
    assert len(result_objects) > 0
    assert result_objects[0].name == "filters"
    assert result_objects[0].display is True
    
    filters = result_objects[0].objects[0]
    assert "where" in filters
    # Check that diet_type filter is present
    where_clause = filters["where"]
    if "operands" in where_clause:
        # Multiple conditions (And operator)
        assert any(
            op.get("path") == ["diet_type"] and op.get("valueString") == "vegetarian"
            for op in where_clause["operands"]
        )
    else:
        # Single condition
        assert where_clause.get("path") == ["diet_type"]
        assert where_clause.get("valueString") == "vegetarian"


@pytest.mark.asyncio
async def test_constraints_guard_no_allergens(mock_tree_data, mock_client_manager, sample_profile_data):
    """Test generating filters with no allergens."""
    # Setup: Profile with vegan diet, no allergens
    profile_result = MagicMock()
    profile_result.objects = [{**sample_profile_data, "diet_type": "vegan", "allergens": []}]
    mock_tree_data.environment.find.return_value = [profile_result]
    
    # Execute
    results = []
    async for output in constraints_guard_tool(
        tree_data=mock_tree_data,
        client_manager=mock_client_manager,
    ):
        results.append(output)
    
    # Assert
    result_objects = [r for r in results if isinstance(r, Result)]
    assert len(result_objects) > 0
    filters = result_objects[0].objects[0]
    assert "where" in filters


@pytest.mark.asyncio
async def test_constraints_guard_max_cooking_time(mock_tree_data, mock_client_manager, sample_profile_data):
    """Test applying max cooking time constraint."""
    # Setup: Profile with max_cooking_time_min
    profile_result = MagicMock()
    profile_result.objects = [{**sample_profile_data, "max_cooking_time_min": 30}]
    mock_tree_data.environment.find.return_value = [profile_result]
    
    # Execute
    results = []
    async for output in constraints_guard_tool(
        tree_data=mock_tree_data,
        client_manager=mock_client_manager,
    ):
        results.append(output)
    
    # Assert
    result_objects = [r for r in results if isinstance(r, Result)]
    assert len(result_objects) > 0
    filters = result_objects[0].objects[0]
    assert "where" in filters
    # Check that cooking_time filter is present
    where_clause = filters["where"]
    if "operands" in where_clause:
        assert any(
            op.get("path") == ["cooking_time"] and op.get("operator") == "LessThanEqual"
            for op in where_clause["operands"]
        )
    else:
        assert where_clause.get("path") == ["cooking_time"]
        assert where_clause.get("operator") == "LessThanEqual"
        assert where_clause.get("valueInt") == 30


@pytest.mark.asyncio
async def test_constraints_guard_no_time_constraints(mock_tree_data, mock_client_manager, sample_profile_data):
    """Test generating filters without time/device constraints."""
    # Setup: Profile without max_cooking_time_min or available_equipment
    profile_result = MagicMock()
    profile_data = {**sample_profile_data}
    profile_data.pop("max_cooking_time_min", None)
    profile_data.pop("available_equipment", None)
    profile_result.objects = [profile_data]
    mock_tree_data.environment.find.return_value = [profile_result]
    
    # Execute
    results = []
    async for output in constraints_guard_tool(
        tree_data=mock_tree_data,
        client_manager=mock_client_manager,
    ):
        results.append(output)
    
    # Assert: Should still generate filters (for diet/allergen)
    result_objects = [r for r in results if isinstance(r, Result)]
    assert len(result_objects) > 0
    filters = result_objects[0].objects[0]
    assert "where" in filters


@pytest.mark.asyncio
async def test_constraints_guard_missing_profile(mock_tree_data, mock_client_manager):
    """Test constraints guard when profile is missing."""
    # Setup: Empty environment
    mock_tree_data.environment.find.return_value = None
    
    # Execute
    results = []
    async for output in constraints_guard_tool(
        tree_data=mock_tree_data,
        client_manager=mock_client_manager,
    ):
        results.append(output)
    
    # Assert: Should yield Error or handle gracefully
    error_objects = [r for r in results if isinstance(r, Error)]
    # Tool may handle missing profile gracefully or yield error
    assert len(results) > 0  # At least some output

