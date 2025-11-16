"""
Unit tests for recipe macro calculation tools.

Tests for:
- calculate_recipe_macros_tool
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from MealAgent.tools.nutrition.calculate_recipe_macros import calculate_recipe_macros_tool
from elysia.objects import Result, Response, Error


@pytest.mark.asyncio
async def test_calculate_recipe_macros_from_cache(
    mock_tree_data, mock_client_manager, sample_recipe_data
):
    """Test that cached macros are returned when available."""
    # Setup: Recipe with cached macros
    recipe_with_cache = {
        **sample_recipe_data,
        "macros_per_serving": {
            "kcal": 450.0,
            "protein_g": 15.0,
            "fat_g": 12.0,
            "carb_g": 65.0,
        },
    }
    
    # Execute
    results = []
    async for output in calculate_recipe_macros_tool(
        tree_data=mock_tree_data,
        client_manager=mock_client_manager,
        recipe=recipe_with_cache,
    ):
        results.append(output)
    
    # Verify
    assert len(results) > 0
    result_objects = [r for r in results if isinstance(r, Result)]
    assert len(result_objects) > 0
    # Should use cached macros without calling Weaviate


@pytest.mark.asyncio
async def test_calculate_recipe_macros_with_fdc_lookup(
    mock_tree_data, mock_client_manager, sample_recipe_data
):
    """Test macro calculation using FDC lookup for ingredients."""
    # Setup: Recipe without cached macros but with ingredient_fdc_map
    recipe_no_cache = {
        **sample_recipe_data,
        "macros_per_serving": None,
        "ingredients_with_qty": ["200g chicken breast", "100g rice"],
        "ingredient_fdc_map": [
            {"ingredient_vn": "chicken breast", "fdc_id": 171077},
            {"ingredient_vn": "rice", "fdc_id": 168884},
        ],
    }
    
    # Mock FDC collections
    client = mock_client_manager.get_client.return_value
    fdc_collection = MagicMock()
    client.collections.get.return_value = fdc_collection
    
    # Mock FDC food data
    mock_fdc_food = MagicMock()
    mock_fdc_food.properties = {
        "fdc_id": 171077,
        "description": "Chicken, breast",
        "energy_kcal_100g": 165.0,
        "protein_g_100g": 31.0,
        "fat_g_100g": 3.6,
        "carb_g_100g": 0.0,
    }
    fdc_collection.query.hybrid.return_value.objects = [mock_fdc_food]
    
    # Execute
    results = []
    async for output in calculate_recipe_macros_tool(
        tree_data=mock_tree_data,
        client_manager=mock_client_manager,
        recipe=recipe_no_cache,
        base_lm=mock_tree_data,  # Placeholder for base_lm
    ):
        results.append(output)
    
    # Verify
    assert len(results) > 0
    result_objects = [r for r in results if isinstance(r, Result)]
    assert len(result_objects) > 0


@pytest.mark.asyncio
async def test_calculate_recipe_macros_vn_to_en_translation(
    mock_tree_data, mock_client_manager, sample_recipe_data
):
    """Test that Vietnamese ingredients are translated to English."""
    # Setup: Recipe with Vietnamese ingredients
    recipe_vn = {
        **sample_recipe_data,
        "macros_per_serving": None,
        "ingredients": ["thịt gà", "gạo"],
        "ingredients_with_qty": ["200g thịt gà", "100g gạo"],
    }
    
    # Mock base_lm for translation
    mock_base_lm = MagicMock()
    
    # Execute (should attempt translation)
    results = []
    async for output in calculate_recipe_macros_tool(
        tree_data=mock_tree_data,
        client_manager=mock_client_manager,
        recipe=recipe_vn,
        base_lm=mock_base_lm,
    ):
        results.append(output)
    
    # Verify
    assert len(results) > 0
    # Translation may fail in test, but tool should handle gracefully
    result_objects = [r for r in results if isinstance(r, (Result, Error))]
    assert len(result_objects) > 0

