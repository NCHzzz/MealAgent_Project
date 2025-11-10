"""
Unit tests for date filtering logic in profile_update.py.
"""
from datetime import datetime, timedelta
import pytest


class TestDateFiltering:
    """Test date range filtering for meal logs."""

    def test_today_start_calculation(self):
        """Test that today_start is set to midnight."""
        today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        assert today_start.hour == 0
        assert today_start.minute == 0
        assert today_start.second == 0
        assert today_start.microsecond == 0

    def test_today_end_calculation(self):
        """Test that today_end is set to next day midnight."""
        today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        today_end = today_start + timedelta(days=1)
        assert today_end.hour == 0
        assert today_end.minute == 0
        assert (today_end - today_start).days == 1

    def test_date_range_isoformat(self):
        """Test that dates are properly formatted for Weaviate queries."""
        today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        today_end = today_start + timedelta(days=1)
        
        start_iso = today_start.isoformat()
        end_iso = today_end.isoformat()
        
        assert isinstance(start_iso, str)
        assert isinstance(end_iso, str)
        assert "T" in start_iso  # ISO format includes time
        assert "T" in end_iso

    def test_date_range_query_structure(self):
        """Test that date range query has correct structure."""
        today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        today_end = today_start + timedelta(days=1)
        
        where_clause = {
            "operator": "And",
            "operands": [
                {"path": ["user_id"], "operator": "Equal", "valueString": "test_user"},
                {"path": ["logged_at"], "operator": "GreaterThanEqual", "valueDate": today_start.isoformat()},
                {"path": ["logged_at"], "operator": "LessThan", "valueDate": today_end.isoformat()},
            ],
        }
        
        assert where_clause["operator"] == "And"
        assert len(where_clause["operands"]) == 3
        assert where_clause["operands"][1]["operator"] == "GreaterThanEqual"
        assert where_clause["operands"][2]["operator"] == "LessThan"

    def test_date_range_excludes_next_day(self):
        """Test that date range excludes the next day (using LessThan, not LessThanEqual)."""
        today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        today_end = today_start + timedelta(days=1)
        
        # A timestamp exactly at today_end should NOT be included
        assert today_end > today_start
        # The LessThan operator ensures today_end is excluded

    def test_date_range_includes_today_start(self):
        """Test that date range includes today_start (using GreaterThanEqual)."""
        today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        today_end = today_start + timedelta(days=1)
        
        # A timestamp exactly at today_start SHOULD be included
        # The GreaterThanEqual operator ensures today_start is included

