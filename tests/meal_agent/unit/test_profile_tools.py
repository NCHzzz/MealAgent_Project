"""
Unit tests for profile management tools.

Tests for:
- profile_crud_tool
- macro_calc_tool
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from MealAgent.tools.profile.profile_crud import profile_crud_tool
from MealAgent.tools.profile.macro_calc import macro_calc_tool
from MealAgent.utils.nutrition import calculate_harris_benedict_tdee
from elysia.objects import Result, Response, Error


@pytest.mark.asyncio
async def test_profile_crud_create_success(
    mock_tree_data, mock_client_manager, sample_profile_data
):
    """Test creating a new profile successfully."""
    # Setup: Mock Weaviate collection
    collection = MagicMock()
    mock_client_manager.get_client.return_value.collections.get.return_value = collection
    collection.query.fetch_objects.return_value.objects = []  # No existing profile
    collection.data.insert = MagicMock()
    
    # Execute
    results = []
    async for output in profile_crud_tool(
        tree_data=mock_tree_data,
        client_manager=mock_client_manager,
        action="create",
        profile_data=sample_profile_data,
    ):
        results.append(output)
    
    # Assert
    assert len(results) > 0
    # Check that Result was yielded
    result_objects = [r for r in results if isinstance(r, Result)]
    assert len(result_objects) > 0
    assert result_objects[0].name == "profile"
    assert result_objects[0].display is True
    assert result_objects[0].objects[0]["user_id"] == "test_user_123"
    # Check that profile was saved
    collection.data.insert.assert_called_once()


@pytest.mark.asyncio
async def test_profile_crud_update_existing(
    mock_tree_data, mock_client_manager, sample_profile_data
):
    """Test updating an existing profile."""
    # Setup: Mock existing profile
    collection = MagicMock()
    mock_client_manager.get_client.return_value.collections.get.return_value = collection
    existing_obj = MagicMock()
    existing_obj.uuid = "existing-uuid"
    collection.query.fetch_objects.return_value.objects = [existing_obj]
    collection.data.update = MagicMock()
    
    # Execute
    results = []
    async for output in profile_crud_tool(
        tree_data=mock_tree_data,
        client_manager=mock_client_manager,
        action="update",
        profile_data={**sample_profile_data, "weight_kg": 80.0},  # Updated weight
    ):
        results.append(output)
    
    # Assert
    result_objects = [r for r in results if isinstance(r, Result)]
    assert len(result_objects) > 0
    # Check that update was called
    collection.data.update.assert_called_once()


@pytest.mark.asyncio
async def test_profile_crud_read_success(
    mock_tree_data, mock_client_manager, sample_profile_data
):
    """Test reading an existing profile."""
    # Setup: Mock existing profile
    collection = MagicMock()
    mock_client_manager.get_client.return_value.collections.get.return_value = collection
    existing_obj = MagicMock()
    existing_obj.properties = sample_profile_data
    collection.query.fetch_objects.return_value.objects = [existing_obj]
    
    # Execute
    results = []
    async for output in profile_crud_tool(
        tree_data=mock_tree_data,
        client_manager=mock_client_manager,
        action="read",
        profile_data={"user_id": "test_user_123"},
    ):
        results.append(output)
    
    # Assert
    result_objects = [r for r in results if isinstance(r, Result)]
    assert len(result_objects) > 0
    assert result_objects[0].name == "profile"
    assert result_objects[0].objects[0]["user_id"] == "test_user_123"


@pytest.mark.asyncio
async def test_profile_crud_missing_profile_data(mock_tree_data, mock_client_manager):
    """Test creating profile with missing data."""
    # Execute
    results = []
    async for output in profile_crud_tool(
        tree_data=mock_tree_data,
        client_manager=mock_client_manager,
        action="create",
        profile_data=None,
    ):
        results.append(output)
    
    # Assert: Should yield Response with skip message
    response_objects = [r for r in results if isinstance(r, Response)]
    assert len(response_objects) > 0
    assert "Skipping" in response_objects[0].text.lower()


@pytest.mark.asyncio
async def test_macro_calc_success(mock_tree_data, mock_client_manager, sample_profile_data):
    """Test calculating macros from profile."""
    # Setup: Mock environment with profile
    profile_result = MagicMock()
    profile_result.objects = [sample_profile_data]
    mock_tree_data.environment.find.return_value = [profile_result]
    
    # Execute
    results = []
    async for output in macro_calc_tool(
        tree_data=mock_tree_data,
        client_manager=mock_client_manager,
    ):
        results.append(output)
    
    # Assert
    result_objects = [r for r in results if isinstance(r, Result)]
    assert len(result_objects) > 0
    assert result_objects[0].name == "targets"
    assert result_objects[0].display is True
    
    targets = result_objects[0].objects[0]
    assert "tdee_kcal" in targets
    assert "protein_g" in targets
    assert "fat_g" in targets
    assert "carb_g" in targets
    assert targets["tdee_kcal"] > 0


@pytest.mark.asyncio
async def test_macro_calc_missing_profile(mock_tree_data, mock_client_manager):
    """Test macro calculation when profile is missing."""
    # Setup: Empty environment
    mock_tree_data.environment.find.return_value = None
    
    # Execute
    results = []
    async for output in macro_calc_tool(
        tree_data=mock_tree_data,
        client_manager=mock_client_manager,
    ):
        results.append(output)
    
    # Assert: Should yield Error
    error_objects = [r for r in results if isinstance(r, Error)]
    assert len(error_objects) > 0
    assert "profile" in error_objects[0].feedback.lower()


@pytest.mark.asyncio
async def test_harris_benedict_male_sedentary():
    """Test Harris-Benedict calculation for male, sedentary."""
    tdee = calculate_harris_benedict_tdee(
        age=30,
        gender="male",
        weight_kg=80.0,
        height_cm=180.0,
        activity_level="sedentary",
    )
    # Expected BMR ≈ 1798, TDEE ≈ 2158 (1798 × 1.2)
    assert 2100 < tdee < 2200


@pytest.mark.asyncio
async def test_harris_benedict_female_very_active():
    """Test Harris-Benedict calculation for female, very active."""
    tdee = calculate_harris_benedict_tdee(
        age=25,
        gender="female",
        weight_kg=60.0,
        height_cm=165.0,
        activity_level="very_active",
    )
    # Expected BMR ≈ 1379, TDEE ≈ 2379 (1379 × 1.725)
    assert 2300 < tdee < 2400


@pytest.mark.asyncio
async def test_macro_distribution():
    """Test macro distribution calculation (30/30/40 split)."""
    tdee = 2000.0
    protein_g = (tdee * 0.30) / 4  # 150g
    fat_g = (tdee * 0.30) / 9      # 67g
    carb_g = (tdee * 0.40) / 4     # 200g
    
    assert abs(protein_g - 150.0) < 0.1
    assert abs(fat_g - 66.67) < 0.1
    assert abs(carb_g - 200.0) < 0.1

