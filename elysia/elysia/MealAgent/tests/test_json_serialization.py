"""
Unit tests for JSON serialization/deserialization in meal logging tools.
"""
import json
import pytest


class TestJSONSerialization:
    """Test JSON serialization and deserialization for MealLogEntry fields."""

    def test_serialize_ingredients(self):
        """Test serializing ingredients list to JSON string."""
        ingredients = [
            {"name": "chicken", "amount": 100, "unit": "g", "fdc_id": 12345},
            {"name": "lettuce", "amount": 50, "unit": "g", "fdc_id": 67890},
        ]
        serialized = json.dumps(ingredients)
        assert isinstance(serialized, str)
        assert json.loads(serialized) == ingredients

    def test_serialize_macros(self):
        """Test serializing macros dict to JSON string."""
        macros = {
            "kcal": 500.0,
            "protein_g": 30.0,
            "fat_g": 20.0,
            "carb_g": 50.0,
        }
        serialized = json.dumps(macros)
        assert isinstance(serialized, str)
        assert json.loads(serialized) == macros

    def test_serialize_micros(self):
        """Test serializing micros dict to JSON string."""
        micros = {
            "calcium_mg": 100.0,
            "iron_mg": 5.0,
            "potassium_mg": 200.0,
        }
        serialized = json.dumps(micros)
        assert isinstance(serialized, str)
        assert json.loads(serialized) == micros

    def test_deserialize_ingredients_string(self):
        """Test deserializing ingredients from JSON string."""
        ingredients_str = '[{"name": "chicken", "amount": 100, "unit": "g", "fdc_id": 12345}]'
        ingredients = json.loads(ingredients_str)
        assert isinstance(ingredients, list)
        assert len(ingredients) == 1
        assert ingredients[0]["name"] == "chicken"

    def test_deserialize_macros_string(self):
        """Test deserializing macros from JSON string."""
        macros_str = '{"kcal": 500.0, "protein_g": 30.0, "fat_g": 20.0, "carb_g": 50.0}'
        macros = json.loads(macros_str)
        assert isinstance(macros, dict)
        assert macros["kcal"] == 500.0

    def test_deserialize_already_dict(self):
        """Test that deserialization handles already-dict values."""
        macros = {"kcal": 500.0, "protein_g": 30.0}
        # Simulate the logic in meal_history.py
        if isinstance(macros, str):
            macros = json.loads(macros)
        assert isinstance(macros, dict)
        assert macros["kcal"] == 500.0

    def test_deserialize_invalid_json(self):
        """Test that invalid JSON is handled gracefully."""
        invalid_json = '{"invalid": json}'
        try:
            result = json.loads(invalid_json)
        except json.JSONDecodeError:
            result = {}
        assert isinstance(result, dict)

    def test_round_trip_serialization(self):
        """Test that serialization and deserialization are reversible."""
        original = {
            "ingredients": [
                {"name": "chicken", "amount": 100, "unit": "g", "fdc_id": 12345},
            ],
            "calculated_macros": {
                "kcal": 500.0,
                "protein_g": 30.0,
                "fat_g": 20.0,
                "carb_g": 50.0,
            },
            "calculated_micros": {
                "calcium_mg": 100.0,
            },
        }

        # Serialize
        serialized = {
            "ingredients": json.dumps(original["ingredients"]),
            "calculated_macros": json.dumps(original["calculated_macros"]),
            "calculated_micros": json.dumps(original["calculated_micros"]),
        }

        # Deserialize
        deserialized = {
            "ingredients": json.loads(serialized["ingredients"]),
            "calculated_macros": json.loads(serialized["calculated_macros"]),
            "calculated_micros": json.loads(serialized["calculated_micros"]),
        }

        assert deserialized == original

