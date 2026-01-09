"""
Unit tests for pantry management tools.

Tests for:
- pantry_crud_tool
- pantry_diff_tool
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from MealAgent.tools.pantry.pantry_crud import pantry_crud_tool
from MealAgent.tools.shopping.pantry_diff import pantry_diff_tool
from elysia.objects import Result, Response, Error


@pytest.mark.asyncio
async def test_pantry_crud_create(
    mock_tree_data, mock_client_manager
):
    """Test creating a pantry item."""
    # Setup: Mock Weaviate collection
    collection = MagicMock()
    mock_client_manager.get_client.return_value.collections.get.return_value = collection
    collection.data.insert = MagicMock()
    
    # Execute
    results = []
    async for output in pantry_crud_tool(
        tree_data=mock_tree_data,
        client_manager=mock_client_manager,
        inputs={
            "action": "create",
            "user_id": "test_user_123",
                "pantry_items": [{"ingredient_name": "chicken breast", "quantity": 500.0, "unit": "g"}]
        },
        base_lm=None,
        complex_lm=None,
    ):
        results.append(output)
    
    # Verify
    assert len(results) > 0
    assert any(isinstance(r, Response) for r in results)
    # The tool yields a Result only if show_list is True, which defaults to True?
    # No, for create it might just update and confirm.
    
    # In pantry_crud.py, it yields Result(name="pantry_list", ...) if action causes updates and then lists items.
    # We should check if collection.data.insert was called.

        # NOTE: If we mock 'collection', we must ensure get_client() returns the SAME mock instance
        # that the tool uses. The fixture or setup might be returning different instances?

        # mock_client_manager.get_client.return_value.collections.get.return_value = collection
        # This seems correct.

        # However, check if the tool actually calls insert.
        # Maybe it fails before insert?

        # Let's inspect the results to see if there are any Errors.
    errors = [r for r in results if isinstance(r, Error)]
    if errors:
        print(f"Tool errors: {errors[0].feedback}")

    assert collection.data.insert.called


@pytest.mark.asyncio
async def test_pantry_crud_read(
    mock_tree_data, mock_client_manager
):
    """Test reading pantry items."""
    # Setup: Mock Weaviate collection with existing items
    collection = MagicMock()
    mock_client_manager.get_client.return_value.collections.get.return_value = collection
    
    mock_obj = MagicMock()
    mock_obj.properties = {
        "user_id": "test_user_123",
        "ingredient_name": "chicken breast",
        "quantity": 500.0,
        "unit": "g",
    }
    collection.query.fetch_objects.return_value.objects = [mock_obj]
    
    # Execute
    results = []
    async for output in pantry_crud_tool(
        tree_data=mock_tree_data,
        client_manager=mock_client_manager,
        inputs={
            "action": "read",
            "user_id": "test_user_123"
        },
        base_lm=None,
        complex_lm=None,
    ):
        results.append(output)
    
    # Verify
    assert len(results) > 0
    result_objects = [r for r in results if isinstance(r, Result)]
    assert len(result_objects) > 0


@pytest.mark.asyncio
async def test_pantry_crud_update(
    mock_tree_data, mock_client_manager
):
    """Test updating a pantry item."""
    # Setup: Mock Weaviate collection
    collection = MagicMock()
    mock_client_manager.get_client.return_value.collections.get.return_value = collection
    
    # Mock existing item
    mock_obj = MagicMock()
    mock_obj.properties = {
        "user_id": "test_user_123",
        "ingredient_name": "chicken breast",
        "quantity": 500.0,
        "unit": "g",
    }
    collection.query.fetch_objects.return_value.objects = [mock_obj]
    collection.data.update = MagicMock()
    
    # Execute
    results = []
    async for output in pantry_crud_tool(
        tree_data=mock_tree_data,
        client_manager=mock_client_manager,
        inputs={
            "action": "update",
            "user_id": "test_user_123",
                "pantry_items": [{"ingredient_name": "chicken breast", "quantity": 750.0}]
        },
        base_lm=None,
        complex_lm=None,
    ):
        results.append(output)
    
    # Verify
    assert len(results) > 0
    # The tool calls fetch_objects to find uuid to update.
    # If fetch returns objects, it should call update.
        # Wait, delete_by_id? No, this is update test.
        # It calls collection.data.update(uuid=item_obj.uuid, properties=item_obj.properties)

    assert collection.data.update.called


@pytest.mark.asyncio
async def test_pantry_crud_delete(
    mock_tree_data, mock_client_manager
):
    """Test deleting a pantry item."""
    # Setup: Mock Weaviate collection
    collection = MagicMock()
    mock_client_manager.get_client.return_value.collections.get.return_value = collection
    
    # Mock existing item
    mock_obj = MagicMock()
    mock_obj.uuid = "test-uuid-123"
    mock_obj.properties = {
        "user_id": "test_user_123",
        "ingredient_name": "chicken breast",
    }
    collection.query.fetch_objects.return_value.objects = [mock_obj]
    collection.data.delete = MagicMock()
    
    # Execute
    results = []
    async for output in pantry_crud_tool(
        tree_data=mock_tree_data,
        client_manager=mock_client_manager,
        inputs={
            "action": "delete",
            "user_id": "test_user_123",
                "pantry_items": [{"ingredient_name": "chicken breast"}]
        },
        base_lm=None,
        complex_lm=None,
    ):
        results.append(output)
    
    # Verify
    assert len(results) > 0
    # In delete action, it calls item_collection.data.delete_by_id(uuid)
    # The mock setup has collection.data.delete = MagicMock()
    # But delete_by_id is a different method?
    # Let's check Weaviate client mock.

    # If the code calls delete_by_id, we should mock that.
    # collection.data is likely a wrapper that has both delete and delete_by_id.
    # We mocked collection.data.delete, but maybe code calls delete_by_id?

    # Looking at pantry_crud.py: item_collection.data.delete_by_id(item_results.objects[0].uuid)
    # So we should check delete_by_id.called.

    assert collection.data.delete_by_id.called


@pytest.mark.asyncio
async def test_pantry_diff_calculate_shopping_list(
    mock_tree_data, mock_client_manager, sample_meal_plan
):
    """Test calculating shopping list from meal plan minus pantry."""
    # Setup: Mock plan in environment
    mock_tree_data.environment.find.return_value = [
        {"objects": [sample_meal_plan], "metadata": {"tool": "plan_day_e2e_tool"}},
    ]
    
    # Setup: Mock pantry items
    collection = MagicMock()
    mock_client_manager.get_client.return_value.collections.get.return_value = collection
    
    mock_pantry_obj = MagicMock()
    mock_pantry_obj.properties = {
        "user_id": "test_user_123",
        "ingredient_name": "pasta",
        "quantity": 200.0,
        "unit": "g",
    }
    collection.query.fetch_objects.return_value.objects = [mock_pantry_obj]
    
    # Execute
    results = []
    async for output in pantry_diff_tool(
        tree_data=mock_tree_data,
        client_manager=mock_client_manager,
        inputs={
            "user_id": "test_user_123"
        },
        base_lm=None,
        complex_lm=None,
    ):
        results.append(output)
    
    # Verify
    assert len(results) > 0
    assert any(isinstance(r, Response) for r in results)
    result_objects = [r for r in results if isinstance(r, Result)]
    assert len(result_objects) > 0

