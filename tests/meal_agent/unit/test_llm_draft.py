"""
Unit tests for LLM draft functionality (Phase 2.1).
"""

import pytest
from unittest.mock import AsyncMock, MagicMock
from MealAgent.schemas.llm_draft import (
    MealDraftSuggestion,
    MealSlotDraft,
    LLMDraftResponse,
)
from MealAgent.tools.utils.llm_draft import (
    _llm_draft_meal_suggestions,
    generate_llm_draft,
)


def test_meal_draft_suggestion_validation():
    """Test MealDraftSuggestion schema validation."""
    suggestion = MealDraftSuggestion(
        dish_name="Phở bò",
        general_term="pho bo",
        role="breakfast",
        meal_type="breakfast",
        category="soup",
        note="Món ăn sáng phổ biến",
    )
    
    assert suggestion.dish_name == "Phở bò"
    assert suggestion.general_term == "pho bo"
    assert suggestion.role == "breakfast"
    assert suggestion.meal_type == "breakfast"
    assert suggestion.category == "soup"


def test_meal_draft_suggestion_normalize_general_term():
    """Test that general_term is normalized to lowercase."""
    suggestion = MealDraftSuggestion(
        dish_name="Cơm Gà",
        general_term="COM GA",
        role="main",
        meal_type="lunch",
        category="main_dish",
    )
    
    assert suggestion.general_term == "com ga"


def test_meal_draft_suggestion_empty_dish_name():
    """Test that empty dish_name raises error."""
    with pytest.raises(ValueError):
        MealDraftSuggestion(
            dish_name="",
            general_term="test",
            role="breakfast",
            meal_type="breakfast",
            category="soup",
        )


def test_meal_slot_draft_validation():
    """Test MealSlotDraft schema validation."""
    suggestions = [
        MealDraftSuggestion(
            dish_name="Phở bò",
            general_term="pho bo",
            role="breakfast",
            meal_type="breakfast",
            category="soup",
        ),
        MealDraftSuggestion(
            dish_name="Bánh mì",
            general_term="banh mi",
            role="breakfast",
            meal_type="breakfast",
            category="bread",
        ),
    ]
    
    draft = MealSlotDraft(meal_type="breakfast", suggestions=suggestions)
    assert len(draft.suggestions) == 2
    assert draft.meal_type == "breakfast"


def test_meal_slot_draft_too_many_suggestions():
    """Test that more than 3 suggestions raises error."""
    suggestions = [
        MealDraftSuggestion(
            dish_name=f"Dish {i}",
            general_term=f"dish-{i}",
            role="breakfast",
            meal_type="breakfast",
            category="soup",
        )
        for i in range(4)
    ]
    
    with pytest.raises(ValueError):
        MealSlotDraft(meal_type="breakfast", suggestions=suggestions)


def test_llm_draft_response_validation():
    """Test LLMDraftResponse schema validation."""
    breakfast_draft = MealSlotDraft(
        meal_type="breakfast",
        suggestions=[
            MealDraftSuggestion(
                dish_name="Phở bò",
                general_term="pho bo",
                role="breakfast",
                meal_type="breakfast",
                category="soup",
            ),
        ],
    )
    
    lunch_draft = MealSlotDraft(
        meal_type="lunch",
        suggestions=[
            MealDraftSuggestion(
                dish_name="Cơm gà",
                general_term="com ga",
                role="carb",
                meal_type="lunch",
                category="rice",
            ),
        ],
    )
    
    dinner_draft = MealSlotDraft(
        meal_type="dinner",
        suggestions=[
            MealDraftSuggestion(
                dish_name="Cơm cá",
                general_term="com ca",
                role="carb",
                meal_type="dinner",
                category="rice",
            ),
        ],
    )
    
    response = LLMDraftResponse(
        breakfast=breakfast_draft,
        lunch=lunch_draft,
        dinner=dinner_draft,
    )
    
    assert response.breakfast.meal_type == "breakfast"
    assert response.lunch.meal_type == "lunch"
    assert response.dinner.meal_type == "dinner"


def test_llm_draft_response_meal_type_mismatch():
    """Test that meal_type mismatch raises error."""
    breakfast_draft = MealSlotDraft(
        meal_type="lunch",  # Wrong!
        suggestions=[
            MealDraftSuggestion(
                dish_name="Phở bò",
                general_term="pho bo",
                role="breakfast",
                meal_type="breakfast",
                category="soup",
            ),
        ],
    )
    
    lunch_draft = MealSlotDraft(
        meal_type="lunch",
        suggestions=[
            MealDraftSuggestion(
                dish_name="Cơm gà",
                general_term="com ga",
                role="carb",
                meal_type="lunch",
                category="rice",
            ),
        ],
    )
    
    dinner_draft = MealSlotDraft(
        meal_type="dinner",
        suggestions=[
            MealDraftSuggestion(
                dish_name="Cơm cá",
                general_term="com ca",
                role="carb",
                meal_type="dinner",
                category="rice",
            ),
        ],
    )
    
    with pytest.raises(ValueError):
        LLMDraftResponse(
            breakfast=breakfast_draft,
            lunch=lunch_draft,
            dinner=dinner_draft,
        )


@pytest.mark.asyncio
async def test_llm_draft_meal_suggestions_no_llm():
    """Test that function returns None when no LLM is provided."""
    result = await _llm_draft_meal_suggestions(
        base_lm=None,
        meal_history=[],
        constraints={},
        meal_slot="breakfast",
    )
    
    assert result is None


@pytest.mark.asyncio
async def test_llm_draft_meal_suggestions_llm_fail():
    """Test that function returns None when LLM call fails."""
    mock_llm = MagicMock()
    mock_llm.generate.side_effect = Exception("LLM error")
    
    result = await _llm_draft_meal_suggestions(
        base_lm=mock_llm,
        meal_history=[],
        constraints={},
        meal_slot="breakfast",
    )
    
    assert result is None


@pytest.mark.asyncio
async def test_generate_llm_draft_no_llm():
    """Test that generate_llm_draft returns None when no LLM."""
    result = await generate_llm_draft(
        base_lm=None,
        meal_history=[],
        constraints={},
    )
    
    assert result is None


