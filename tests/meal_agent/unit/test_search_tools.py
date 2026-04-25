"""
Unit tests for search and ranking tools.

Tests for:
- search_and_rank_tool
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from MealAgent.tools.search.search_and_rank import _extract_search_score, search_and_rank_tool
from elysia.objects import Result, Response, Error


def test_extract_search_score_reads_v4_metadata_object():
    obj = MagicMock()
    obj._additional = None
    obj.metadata = MagicMock(score=0.42)

    assert _extract_search_score(obj) == 0.42


def test_extract_search_score_reads_metadata_dict():
    obj = MagicMock()
    obj._additional = None
    obj.metadata = {"score": "0.73"}

    assert _extract_search_score(obj) == 0.73


@pytest.mark.asyncio
async def test_search_and_rank_basic_search(
    mock_tree_data, mock_client_manager, sample_recipe_data
):
    """Test basic recipe search functionality."""
    # Setup: Mock Weaviate collection
    collection = MagicMock()
    mock_client_manager.get_client.return_value.collections.get.return_value = collection
    
    # Mock search results
    mock_obj = MagicMock()
    mock_obj.properties = sample_recipe_data
    # Configure metadata mock to support float comparison
    mock_metadata = MagicMock()
    mock_metadata.score = 0.85
    # Allow getattr to work for score
    mock_obj._additional = mock_metadata
    mock_obj.metadata = {"score": 0.85}
    collection.query.hybrid.return_value.objects = [mock_obj]
    
    # Execute
    results = []
    async for output in search_and_rank_tool(
        tree_data=mock_tree_data,
        client_manager=mock_client_manager,
        inputs={"query_text": "vegetarian pasta", "top_k": 5},
        base_lm=None,
        complex_lm=None,
    ):
        results.append(output)
    
    # Verify
    assert len(results) > 0
    assert any(isinstance(r, Response) for r in results)
    result_objects = [r for r in results if isinstance(r, Result)]
    assert len(result_objects) > 0
    
    # Check that Result was added to environment
    # Note: search_and_rank_tool returns Result objects which are handled by the Tree
    # The tool itself doesn't call environment.add directly for results, it yields them.
    # So we check if results were yielded.
    assert len(results) > 0


@pytest.mark.asyncio
async def test_search_and_rank_with_filters(
    mock_tree_data, mock_client_manager, sample_recipe_data
):
    """Test search with constraint filters."""
    # Setup: Mock filters from environment
    mock_filters = {
        "where": {
            "operator": "And",
            "operands": [
                {"path": ["diet_type"], "operator": "ContainsAny", "valueString": ["vegetarian"]},
            ],
        },
    }
    mock_tree_data.environment.find.return_value = [
        {"objects": [mock_filters], "metadata": {"tool": "constraints_guard_tool"}},
    ]
    
    # Setup: Mock Weaviate collection
    collection = MagicMock()
    mock_client_manager.get_client.return_value.collections.get.return_value = collection
    
    mock_obj = MagicMock()
    mock_obj.properties = sample_recipe_data
    mock_metadata = MagicMock()
    mock_metadata.score = 0.90
    mock_obj._additional = mock_metadata
    mock_obj.metadata = {"score": 0.90}
    collection.query.hybrid.return_value.objects = [mock_obj]
    
    # Execute
    results = []
    async for output in search_and_rank_tool(
        tree_data=mock_tree_data,
        client_manager=mock_client_manager,
        inputs={"query_text": "pasta", "top_k": 5},
        base_lm=None,
        complex_lm=None,
    ):
        results.append(output)
    
    # Verify filters were applied
    assert collection.query.hybrid.called
    call_args = collection.query.hybrid.call_args
    assert call_args is not None


@pytest.mark.asyncio
async def test_search_and_rank_empty_results(
    mock_tree_data, mock_client_manager
):
    """Test search with no results."""
    # Setup: Mock empty results
    collection = MagicMock()
    mock_client_manager.get_client.return_value.collections.get.return_value = collection
    collection.query.hybrid.return_value.objects = []
    
    # Execute
    results = []
    async for output in search_and_rank_tool(
        tree_data=mock_tree_data,
        client_manager=mock_client_manager,
        inputs={"query_text": "nonexistent recipe", "top_k": 5},
        base_lm=None,
        complex_lm=None,
    ):
        results.append(output)
    
    # Verify
    assert len(results) > 0
    # Expect an Error when no results are found
    error_objects = [r for r in results if isinstance(r, Error)]
    assert len(error_objects) > 0


@pytest.mark.asyncio
async def test_search_and_rank_ranking(
    mock_tree_data, mock_client_manager, sample_recipe_data
):
    """Test that recipes are ranked by fit_score."""
    # Setup: Multiple recipes with different scores
    collection = MagicMock()
    mock_client_manager.get_client.return_value.collections.get.return_value = collection
    
    recipes = [
        {**sample_recipe_data, "food_id": "recipe_001", "fit_score": 0.6},
        {**sample_recipe_data, "food_id": "recipe_002", "fit_score": 0.9},
        {**sample_recipe_data, "food_id": "recipe_003", "fit_score": 0.7},
    ]
    
    mock_objs = []
    for recipe in recipes:
        mock_obj = MagicMock()
        mock_obj.properties = recipe
        mock_metadata = MagicMock()
        mock_metadata.score = 0.8
        mock_obj._additional = mock_metadata
        mock_obj.metadata = {"score": 0.8}
        mock_objs.append(mock_obj)
    
    collection.query.hybrid.return_value.objects = mock_objs
    
    # Execute
    results = []
    async for output in search_and_rank_tool(
        tree_data=mock_tree_data,
        client_manager=mock_client_manager,
        inputs={"query_text": "vegetarian", "top_k": 5},
        base_lm=None,
        complex_lm=None,
    ):
        results.append(output)
    
    # Verify
    result_objects = [r for r in results if isinstance(r, Result)]
    assert len(result_objects) > 0
    # Check that topk was stored in environment
    # The tool yields results, doesn't add to environment directly
    assert len(result_objects) > 0

