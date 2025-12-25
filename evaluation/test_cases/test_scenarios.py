"""
Test scenarios for evaluation.

Cung cấp các test scenarios với queries và expected behaviors.
"""

from typing import List, Dict, Any, Optional


def get_test_scenarios() -> List[Dict[str, Any]]:
    """
    Lấy danh sách test scenarios.
    
    Returns:
        List of test scenario dictionaries
    """
    scenarios = [
        {
            "scenario_id": "scenario_1",
            "user_id": "test_user_1",
            "query": "Tạo thực đơn cho tôi hôm nay",
            "plan_type": "day",
            "description": "Basic daily meal plan request",
        },
        {
            "scenario_id": "scenario_2",
            "user_id": "test_user_2",
            "query": "Tôi muốn thực đơn tuần này, ưu tiên món chay",
            "plan_type": "week",
            "description": "Weekly vegetarian meal plan",
        },
        {
            "scenario_id": "scenario_3",
            "user_id": "test_user_3",
            "query": "Thực đơn hôm nay với nhiều protein, nhanh gọn",
            "plan_type": "day",
            "description": "High protein, quick meals",
        },
        {
            "scenario_id": "scenario_4",
            "user_id": "test_user_4",
            "query": "Tạo thực đơn giảm cân cho tôi",
            "plan_type": "day",
            "description": "Weight loss meal plan",
        },
        {
            "scenario_id": "scenario_5",
            "user_id": "test_user_5",
            "query": "Thực đơn tuần này, tránh hải sản",
            "plan_type": "week",
            "description": "Weekly plan with allergen constraint",
        },
    ]
    
    return scenarios


def get_scenario_by_id(scenario_id: str) -> Optional[Dict[str, Any]]:
    """
    Lấy scenario theo scenario_id.
    
    Args:
        scenario_id: Scenario ID
    
    Returns:
        Test scenario dictionary or None if not found
    """
    scenarios = get_test_scenarios()
    for scenario in scenarios:
        if scenario["scenario_id"] == scenario_id:
            return scenario
    return None

