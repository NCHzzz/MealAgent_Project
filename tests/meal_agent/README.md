# MealAgent Test Suite

This directory contains unit and integration tests for MealAgent tools and workflows.

## Test Structure

```
tests/meal_agent/
├── __init__.py
├── conftest.py              # Shared fixtures and test configuration
├── unit/                    # Unit tests for individual tools
│   ├── test_profile_tools.py
│   ├── test_constraints_tools.py
│   ├── test_search_tools.py
│   ├── test_planning_tools.py
│   ├── test_logging_tools.py
│   ├── test_pantry_tools.py
│   ├── test_optimization_tools.py
│   └── test_cook_mode_tools.py
└── integration/             # Integration tests for workflows
    ├── test_daily_planning_workflow.py
    ├── test_weekly_planning_workflow.py
    ├── test_meal_logging_workflow.py
    └── test_cooking_workflow.py
```

## Running Tests

```bash
# Run all MealAgent tests
pytest tests/meal_agent/

# Run unit tests only
pytest tests/meal_agent/unit/

# Run integration tests only
pytest tests/meal_agent/integration/

# Run with coverage
pytest tests/meal_agent/ --cov=MealAgent --cov-report=html
```

## Test Coverage Goals

- **Unit Test Coverage**: 100% of MealAgent tools
- **Integration Test Coverage**: All critical workflows
- **Performance Tests**: Validate latency requirements from design doc

## Fixtures

See `conftest.py` for available fixtures:
- `mock_tree_data` - Mock TreeData with environment
- `mock_client_manager` - Mock ClientManager
- `mock_base_lm` - Mock LLM client
- `sample_profile_data` - Sample user profile
- `sample_recipe_data` - Sample recipe
- `sample_targets` - Sample macro targets

## Writing Tests

### Unit Test Example

```python
import pytest
from MealAgent.tools.profile.profile_crud import profile_crud_tool

@pytest.mark.asyncio
async def test_profile_crud_create(mock_tree_data, mock_client_manager, sample_profile_data):
    """Test creating a new profile."""
    # Setup
    collection = MagicMock()
    mock_client_manager.get_client.return_value.collections.get.return_value = collection
    collection.query.fetch_objects.return_value.objects = []  # No existing profile
    
    # Execute
    results = []
    async for result in profile_crud_tool(
        tree_data=mock_tree_data,
        client_manager=mock_client_manager,
        action="create",
        profile_data=sample_profile_data,
    ):
        results.append(result)
    
    # Assert
    assert len(results) > 0
    # Check that Result was yielded with correct data
    # Check that profile was saved to Weaviate
```

### Integration Test Example

```python
import pytest
from MealAgent.tree.meal_tree import process_daily_planning_workflow

@pytest.mark.asyncio
async def test_daily_planning_workflow(mock_tree_data, mock_client_manager, mock_base_lm):
    """Test complete daily planning workflow."""
    # Setup: Mock environment with profile and targets
    # Execute workflow
    # Assert: Plan created, validated, shopping list generated
```

## Notes

- All tests should use async/await patterns
- Mock external dependencies (Weaviate, LLM)
- Test both happy paths and error cases
- Verify Result objects have `display=True`
- Verify environment keys match design doc

