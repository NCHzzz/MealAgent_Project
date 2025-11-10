"""
Unit tests for profile validation logic.
"""
import pytest
from elysia.MealAgent.tools.profile.profile_crud import _validate_profile_payload


class TestProfileValidation:
    """Test profile payload validation."""

    def test_valid_profile(self):
        """Test that a valid profile passes validation."""
        profile = {
            "user_id": "test_user",
            "age": 30,
            "gender": "male",
            "weight_kg": 75.5,
            "height_cm": 180,
            "activity_level": "moderate",
        }
        assert _validate_profile_payload(profile) is None

    def test_missing_required_fields(self):
        """Test that missing required fields are detected."""
        profile = {
            "user_id": "test_user",
            "age": 30,
            # Missing gender, weight_kg, height_cm, activity_level
        }
        error = _validate_profile_payload(profile)
        assert error is not None
        assert "Missing required fields" in error

    def test_invalid_age_too_low(self):
        """Test that age < 1 is rejected."""
        profile = {
            "user_id": "test_user",
            "age": 0,
            "gender": "male",
            "weight_kg": 75.5,
            "height_cm": 180,
            "activity_level": "moderate",
        }
        error = _validate_profile_payload(profile)
        assert error is not None
        assert "age must be an integer between 1 and 120" in error

    def test_invalid_age_too_high(self):
        """Test that age > 120 is rejected."""
        profile = {
            "user_id": "test_user",
            "age": 121,
            "gender": "male",
            "weight_kg": 75.5,
            "height_cm": 180,
            "activity_level": "moderate",
        }
        error = _validate_profile_payload(profile)
        assert error is not None
        assert "age must be an integer between 1 and 120" in error

    def test_invalid_age_type(self):
        """Test that non-integer age is rejected."""
        profile = {
            "user_id": "test_user",
            "age": "30",  # String instead of int
            "gender": "male",
            "weight_kg": 75.5,
            "height_cm": 180,
            "activity_level": "moderate",
        }
        error = _validate_profile_payload(profile)
        assert error is not None
        assert "age must be an integer" in error

    def test_invalid_gender(self):
        """Test that invalid gender is rejected."""
        profile = {
            "user_id": "test_user",
            "age": 30,
            "gender": "invalid",
            "weight_kg": 75.5,
            "height_cm": 180,
            "activity_level": "moderate",
        }
        error = _validate_profile_payload(profile)
        assert error is not None
        assert "gender must be" in error

    def test_valid_genders(self):
        """Test that all valid genders are accepted."""
        for gender in ["male", "female", "other", "Male", "FEMALE", "Other"]:
            profile = {
                "user_id": "test_user",
                "age": 30,
                "gender": gender,
                "weight_kg": 75.5,
                "height_cm": 180,
                "activity_level": "moderate",
            }
            assert _validate_profile_payload(profile) is None

    def test_invalid_weight_negative(self):
        """Test that negative weight is rejected."""
        profile = {
            "user_id": "test_user",
            "age": 30,
            "gender": "male",
            "weight_kg": -10,
            "height_cm": 180,
            "activity_level": "moderate",
        }
        error = _validate_profile_payload(profile)
        assert error is not None
        assert "weight_kg must be a positive number" in error

    def test_invalid_weight_too_high(self):
        """Test that weight > 500 is rejected."""
        profile = {
            "user_id": "test_user",
            "age": 30,
            "gender": "male",
            "weight_kg": 501,
            "height_cm": 180,
            "activity_level": "moderate",
        }
        error = _validate_profile_payload(profile)
        assert error is not None
        assert "weight_kg must be a positive number <= 500" in error

    def test_invalid_height_negative(self):
        """Test that negative height is rejected."""
        profile = {
            "user_id": "test_user",
            "age": 30,
            "gender": "male",
            "weight_kg": 75.5,
            "height_cm": -10,
            "activity_level": "moderate",
        }
        error = _validate_profile_payload(profile)
        assert error is not None
        assert "height_cm must be a positive number" in error

    def test_invalid_height_too_high(self):
        """Test that height > 300 is rejected."""
        profile = {
            "user_id": "test_user",
            "age": 30,
            "gender": "male",
            "weight_kg": 75.5,
            "height_cm": 301,
            "activity_level": "moderate",
        }
        error = _validate_profile_payload(profile)
        assert error is not None
        assert "height_cm must be a positive number <= 300" in error

    def test_invalid_activity_level(self):
        """Test that invalid activity level is rejected."""
        profile = {
            "user_id": "test_user",
            "age": 30,
            "gender": "male",
            "weight_kg": 75.5,
            "height_cm": 180,
            "activity_level": "invalid",
        }
        error = _validate_profile_payload(profile)
        assert error is not None
        assert "activity_level must be one of" in error

    def test_valid_activity_levels(self):
        """Test that all valid activity levels are accepted."""
        for activity in ["sedentary", "light", "moderate", "very_active", "extra_active"]:
            profile = {
                "user_id": "test_user",
                "age": 30,
                "gender": "male",
                "weight_kg": 75.5,
                "height_cm": 180,
                "activity_level": activity,
            }
            assert _validate_profile_payload(profile) is None

    def test_not_dict(self):
        """Test that non-dict input is rejected."""
        error = _validate_profile_payload("not a dict")
        assert error is not None
        assert "profile_data must be an object" in error

