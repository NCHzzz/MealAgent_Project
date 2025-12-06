"""
Unit tests for LLM Critic functionality (Phase 2.2).
"""

import pytest
from unittest.mock import MagicMock, AsyncMock
from MealAgent.tools.utils.llm_critic import (
    _llm_critic_plan,
    generate_llm_critic_async,
    create_critic_task,
)


@pytest.mark.asyncio
async def test_llm_critic_plan_no_llm():
    """Test that function returns None when no LLM is provided."""
    plan = {
        "meals": {
            "breakfast": {
                "recipe": {"dish_name": "Phở bò"},
                "macros": {"kcal": 500.0, "protein_g": 20.0},
            },
        },
        "total_macros": {"kcal": 2000.0, "protein_g": 150.0},
    }
    targets = {"tdee_kcal": 2000.0, "protein_g": 150.0}
    validation = {"macro_validation": {"violations": []}}
    
    result = await _llm_critic_plan(None, plan, targets, validation)
    assert result is None


@pytest.mark.asyncio
async def test_llm_critic_plan_no_violations():
    """Test that function returns None when plan has no violations."""
    plan = {
        "meals": {
            "breakfast": {
                "recipe": {"dish_name": "Phở bò"},
                "macros": {"kcal": 500.0, "protein_g": 20.0},
            },
        },
        "total_macros": {"kcal": 2000.0, "protein_g": 150.0},
    }
    targets = {"tdee_kcal": 2000.0, "protein_g": 150.0}
    validation = {
        "macro_validation": {
            "valid": True,
            "violations": [],
            "warnings": [],
        }
    }
    
    mock_llm = MagicMock()
    result = await _llm_critic_plan(mock_llm, plan, targets, validation)
    assert result is None
    # LLM should not be called
    assert not mock_llm.called


@pytest.mark.asyncio
async def test_llm_critic_plan_with_violations():
    """Test that function calls LLM when there are violations."""
    plan = {
        "meals": {
            "breakfast": {
                "recipe": {"dish_name": "Phở bò"},
                "macros": {"kcal": 500.0, "protein_g": 20.0},
            },
        },
        "total_macros": {"kcal": 2500.0, "protein_g": 150.0},
    }
    targets = {"tdee_kcal": 2000.0, "protein_g": 150.0}
    validation = {
        "macro_validation": {
            "valid": False,
            "violations": [
                {
                    "macro": "kcal",
                    "target": 2000.0,
                    "actual": 2500.0,
                    "deviation_percent": 25.0,
                }
            ],
            "warnings": [],
        }
    }
    
    mock_llm = MagicMock()
    mock_llm.generate.return_value = "Kế hoạch có lượng calo cao hơn mục tiêu. Nên giảm một số món hoặc giảm khẩu phần."
    
    result = await _llm_critic_plan(mock_llm, plan, targets, validation)
    
    assert result is not None
    assert "calo" in result.lower() or "kcal" in result.lower()
    assert mock_llm.generate.called


@pytest.mark.asyncio
async def test_llm_critic_plan_with_warnings():
    """Test that function calls LLM when there are warnings."""
    plan = {
        "meals": {
            "breakfast": {
                "recipe": {"dish_name": "Phở bò"},
                "macros": {"kcal": 500.0, "protein_g": 20.0},
            },
        },
        "total_macros": {"kcal": 2100.0, "protein_g": 150.0},
    }
    targets = {"tdee_kcal": 2000.0, "protein_g": 150.0}
    validation = {
        "macro_validation": {
            "valid": True,
            "violations": [],
            "warnings": [
                {
                    "macro": "kcal",
                    "target": 2000.0,
                    "actual": 2100.0,
                    "deviation_percent": 5.0,
                }
            ],
        }
    }
    
    mock_llm = MagicMock()
    mock_llm.generate.return_value = "Kế hoạch gần đạt mục tiêu, có thể điều chỉnh nhẹ."
    
    result = await _llm_critic_plan(mock_llm, plan, targets, validation)
    
    assert result is not None
    assert mock_llm.generate.called


@pytest.mark.asyncio
async def test_llm_critic_plan_llm_fail():
    """Test that function returns None when LLM call fails."""
    plan = {
        "meals": {
            "breakfast": {
                "recipe": {"dish_name": "Phở bò"},
                "macros": {"kcal": 500.0, "protein_g": 20.0},
            },
        },
        "total_macros": {"kcal": 2500.0, "protein_g": 150.0},
    }
    targets = {"tdee_kcal": 2000.0, "protein_g": 150.0}
    validation = {
        "macro_validation": {
            "valid": False,
            "violations": [{"macro": "kcal", "target": 2000.0, "actual": 2500.0, "deviation_percent": 25.0}],
            "warnings": [],
        }
    }
    
    mock_llm = MagicMock()
    mock_llm.generate.side_effect = Exception("LLM error")
    
    result = await _llm_critic_plan(mock_llm, plan, targets, validation)
    assert result is None


@pytest.mark.asyncio
async def test_generate_llm_critic_async():
    """Test async LLM critic generation."""
    plan = {
        "meals": {
            "breakfast": {
                "recipe": {"dish_name": "Phở bò"},
                "macros": {"kcal": 500.0, "protein_g": 20.0},
            },
        },
        "total_macros": {"kcal": 2500.0, "protein_g": 150.0},
    }
    targets = {"tdee_kcal": 2000.0, "protein_g": 150.0}
    validation = {
        "macro_validation": {
            "valid": False,
            "violations": [{"macro": "kcal", "target": 2000.0, "actual": 2500.0, "deviation_percent": 25.0}],
            "warnings": [],
        }
    }
    
    mock_llm = MagicMock()
    mock_llm.generate.return_value = "Test critic note"
    
    result = await generate_llm_critic_async(mock_llm, plan, targets, validation)
    assert result is not None
    assert "test" in result.lower()


@pytest.mark.asyncio
async def test_create_critic_task():
    """Test creating async critic task."""
    plan = {
        "meals": {
            "breakfast": {
                "recipe": {"dish_name": "Phở bò"},
                "macros": {"kcal": 500.0, "protein_g": 20.0},
            },
        },
        "total_macros": {"kcal": 2500.0, "protein_g": 150.0},
    }
    targets = {"tdee_kcal": 2000.0, "protein_g": 150.0}
    validation = {
        "macro_validation": {
            "valid": False,
            "violations": [{"macro": "kcal", "target": 2000.0, "actual": 2500.0, "deviation_percent": 25.0}],
            "warnings": [],
        }
    }
    
    mock_llm = MagicMock()
    mock_llm.generate.return_value = "Test critic note"
    
    task = create_critic_task(mock_llm, plan, targets, validation)
    assert task is not None
    
    # Wait for task to complete
    result = await task
    assert result is not None
    assert "test" in result.lower()


def test_create_critic_task_no_llm():
    """Test that creating task returns None when no LLM."""
    plan = {"meals": {}, "total_macros": {}}
    targets = {}
    validation = {"macro_validation": {"violations": []}}
    
    task = create_critic_task(None, plan, targets, validation)
    assert task is None


