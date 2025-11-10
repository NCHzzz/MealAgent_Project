import asyncio

from elysia.MealAgent.tools.cook_mode.cook_mode import _extract_steps_from_recipe, _estimate_duration_seconds
from elysia.MealAgent.tools.explain.explain import _build_explanation


def test_cook_mode_extracts_steps_from_cooking_method_array():
    recipe = {
        "dish_name": "Grilled Chicken",
        "cooking_method_array": [
            "Preheat the grill for 10 minutes.",
            "Grill chicken for 8 minutes per side.",
        ],
    }
    steps = _extract_steps_from_recipe(recipe)
    assert len(steps) == 2
    assert steps[0]["index"] == 1
    assert steps[0]["estimated_seconds"] >= 600  # 10 minutes detected


def test_cook_mode_extracts_steps_from_ingredients_fallback():
    recipe = {
        "ingredients": ["200g chicken", "1 tsp salt"],
    }
    steps = _extract_steps_from_recipe(recipe)
    # gather + 2 ingredients + cook step => >= 4
    assert len(steps) >= 4
    assert any("Gather all ingredients" in s["instruction"] for s in steps)


def test_duration_estimation_minutes_and_seconds():
    assert _estimate_duration_seconds("Bake 15 minutes") == 900
    assert _estimate_duration_seconds("Stir 30 seconds") == 30


class DummyResult:
    def __init__(self, objects):
        self.objects = objects


class DummyEnv:
    def __init__(self, data):
        self._data = data

    def find(self, tool_name, name):
        return [DummyResult(self._data.get((tool_name, name), []))]


class DummyTreeData:
    def __init__(self, env):
        self.environment = env


def test_build_explanation_compiles_environment_context():
    env_data = {
        ("profile_crud_tool", "profile"): [{"age": 30, "gender": "male"}],
        ("macro_calc_tool", "targets"): [{"tdee_kcal": 2200, "protein_g": 150, "fat_g": 70, "carb_g": 250}],
        ("diet_allergen_guard_tool", "report"): [{"applied": True}],
        ("time_device_guard_tool", "report"): [{"applied": True}],
        ("score_and_rank_tool", "topk"): [[{"food_id": "R1", "dish_name": "Salad"}]],
        ("plan_assemble_day_tool", "plan"): [{"plan_type": "day", "meals": {"breakfast": {"recipe": {"dish_name": "Oats"}}}}],
        ("gap_calc_tool", "deficits"): [{"has_deficits": True}],
        ("suggest_snack_tool", "suggestions"): [{"count": 2}],
        ("variety_guard_tool", "report"): [{"variety_score": 72.5}],
    }
    tree_data = DummyTreeData(DummyEnv(env_data))
    data = _build_explanation(tree_data)
    assert data["explanation"]
    assert data["has_plan"] is True
    assert data["constraints"]["diet_allergen"] is True
    assert data["constraints"]["time_device"] is True
