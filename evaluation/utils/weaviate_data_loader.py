"""
Utility module để load meal plans và user profiles từ Weaviate database.

Module này cung cấp các hàm để:
- Kết nối với Weaviate
- Load meal plans từ MealPlan collection
- Load meal logs từ MealLogEntry collection
- Load user profiles từ UserProfile collection
- Chuyển đổi dữ liệu từ Weaviate format sang format phù hợp cho evaluation
"""

import os
import sys
import logging
from typing import List, Dict, Any, Optional
from pathlib import Path

# Add parent directories to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from elysia.util.client import ClientManager
from MealAgent.tools.utils.plan_loader import load_plan_from_weaviate, load_latest_plan_from_weaviate
from MealAgent.tools.utils.weaviate_filters import build_filters_from_where
from datetime import datetime, timedelta, timezone
import json

logger = logging.getLogger(__name__)


def create_client_manager(
    wcd_url: Optional[str] = None,
    wcd_api_key: Optional[str] = None,
    weaviate_is_local: Optional[bool] = None,
) -> ClientManager:
    """
    Tạo ClientManager để kết nối với Weaviate.
    
    Args:
        wcd_url: Weaviate cluster URL (từ env WCD_URL nếu None)
        wcd_api_key: Weaviate API key (từ env WCD_API_KEY nếu None)
        weaviate_is_local: Có phải local Weaviate không (từ env WEAVIATE_IS_LOCAL nếu None)
    
    Returns:
        ClientManager instance
    """
    # Lấy từ environment variables nếu không được cung cấp
    if wcd_url is None:
        wcd_url = os.getenv("WCD_URL")
    if wcd_api_key is None:
        wcd_api_key = os.getenv("WCD_API_KEY")
    if weaviate_is_local is None:
        weaviate_is_local = os.getenv("WEAVIATE_IS_LOCAL", "false").lower() == "true"
    
    return ClientManager(
        wcd_url=wcd_url,
        wcd_api_key=wcd_api_key,
        weaviate_is_local=weaviate_is_local,
    )


def load_user_profile_from_weaviate(
    user_id: str,
    client_manager: ClientManager
) -> Optional[Dict[str, Any]]:
    """
    Load user profile từ Weaviate UserProfile collection.
    
    Args:
        user_id: User ID
        client_manager: ClientManager instance
    
    Returns:
        User profile dictionary hoặc None nếu không tìm thấy
    """
    if not user_id:  # Skip None or empty user_ids
        logger.warning(f"Cannot load profile: user_id is None or empty")
        return None
    
    if not user_id:  # Skip None or empty user_ids
        logger.warning(f"Cannot load profile: user_id is None or empty")
        return None
    
    try:
        client = client_manager.get_client()
        collection = client.collections.get("UserProfile")
        
        profile_filter = build_filters_from_where(
            {"path": ["user_id"], "operator": "Equal", "valueString": str(user_id)}
        )
        
        results = collection.query.fetch_objects(filters=profile_filter, limit=1)
        
        if not results.objects:
            logger.warning(f"User profile {user_id} not found in Weaviate")
            return None
        
        profile = results.objects[0].properties
        
        # Chuyển đổi sang format phù hợp cho evaluation
        # Đảm bảo có các trường cần thiết: protein_g, carb_g, fat_g, tdee_kcal
        result_profile = {
            "user_id": profile.get("user_id"),
            "age": profile.get("age"),
            "gender": profile.get("gender"),
            "weight_kg": profile.get("weight_kg"),
            "height_cm": profile.get("height_cm"),
            "activity_level": profile.get("activity_level"),
            "goal": profile.get("goal"),
            "diet_type": profile.get("diet_type"),
            "allergens": profile.get("allergens", []),
            "preferences": profile.get("preferences", []),
            # Nutrition targets
            "tdee_kcal": float(profile.get("tdee_kcal", 0.0)),
            "protein_g": float(profile.get("protein_g", 0.0)),
            "fat_g": float(profile.get("fat_g", 0.0)),
            "carb_g": float(profile.get("carb_g", 0.0)),
        }
        
        # Verify user_id is present
        if not result_profile.get("user_id"):
            logger.warning(f"Profile loaded but missing user_id")
            return None
        
        return result_profile
    except Exception as e:
        logger.error(f"Failed to load user profile {user_id} from Weaviate: {e}", exc_info=True)
        return None


def load_meal_plan_from_weaviate(
    plan_id: str,
    client_manager: ClientManager,
    user_id: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """
    Load meal plan từ Weaviate bằng plan_id.
    
    Args:
        plan_id: Plan ID
        client_manager: ClientManager instance
        user_id: Optional user_id để validate
    
    Returns:
        Meal plan dictionary hoặc None nếu không tìm thấy
    """
    try:
        plan = load_plan_from_weaviate(plan_id, client_manager, user_id)
        return plan
    except Exception as e:
        logger.error(f"Failed to load meal plan {plan_id} from Weaviate: {e}", exc_info=True)
        return None


def load_latest_meal_plan_from_weaviate(
    user_id: str,
    client_manager: ClientManager,
    plan_type: str = "day"
) -> Optional[Dict[str, Any]]:
    """
    Load meal plan mới nhất của user từ Weaviate.
    
    Args:
        user_id: User ID
        client_manager: ClientManager instance
        plan_type: "day" hoặc "week"
    
    Returns:
        Meal plan dictionary hoặc None nếu không tìm thấy
    """
    try:
        plan = load_latest_plan_from_weaviate(user_id, client_manager, plan_type)
        return plan
    except Exception as e:
        logger.error(f"Failed to load latest {plan_type} plan for user {user_id} from Weaviate: {e}", exc_info=True)
        return None


def load_meal_plans_by_user_ids(
    user_ids: List[str],
    client_manager: ClientManager,
    plan_type: str = "day",
    use_latest: bool = True
) -> List[Dict[str, Any]]:
    """
    Load meal plans cho nhiều users.
    
    Args:
        user_ids: List of user IDs
        client_manager: ClientManager instance
        plan_type: "day" hoặc "week"
        use_latest: Nếu True, load plan mới nhất của mỗi user. Nếu False, cần cung cấp plan_ids
    
    Returns:
        List of meal plan dictionaries
    """
    meal_plans = []
    
    for user_id in user_ids:
        if use_latest:
            plan = load_latest_meal_plan_from_weaviate(user_id, client_manager, plan_type)
        else:
            # Nếu không dùng latest, cần có plan_ids - implement sau nếu cần
            logger.warning(f"use_latest=False not implemented, skipping user {user_id}")
            continue
        
        if plan:
            meal_plans.append(plan)
        else:
            logger.warning(f"No {plan_type} plan found for user {user_id}")
    
    return meal_plans


def load_user_profiles_from_weaviate(
    user_ids: List[str],
    client_manager: ClientManager
) -> List[Dict[str, Any]]:
    """
    Load user profiles cho nhiều users.
    
    Args:
        user_ids: List of user IDs
        client_manager: ClientManager instance
    
    Returns:
        List of user profile dictionaries
    """
    profiles = []
    
    for user_id in user_ids:
        profile = load_user_profile_from_weaviate(user_id, client_manager)
        if profile:
            profiles.append(profile)
        else:
            logger.warning(f"User profile {user_id} not found")
    
    return profiles


def load_evaluation_data_from_weaviate(
    user_ids: List[str],
    client_manager: Optional[ClientManager] = None,
    plan_type: str = "day",
    use_latest: bool = True
) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Load cả meal plans và user profiles từ Weaviate cho evaluation.
    
    Args:
        user_ids: List of user IDs
        client_manager: ClientManager instance (tạo mới nếu None)
        plan_type: "day" hoặc "week"
        use_latest: Load plan mới nhất của mỗi user
    
    Returns:
        Tuple of (meal_plans, user_profiles)
        Cả hai lists có cùng length và cùng thứ tự theo user_ids
    """
    if client_manager is None:
        client_manager = create_client_manager()
    
    if not client_manager.is_client:
        raise ValueError(
            "Weaviate client is not available. "
            "Please check your Weaviate configuration (WCD_URL, WCD_API_KEY, WEAVIATE_IS_LOCAL)."
        )
    
    # Load meal plans và profiles
    meal_plans = load_meal_plans_by_user_ids(user_ids, client_manager, plan_type, use_latest)
    user_profiles = load_user_profiles_from_weaviate(user_ids, client_manager)
    
    # Đảm bảo cả hai lists có cùng length và match với nhau
    # Chỉ giữ lại các pairs có đủ cả plan và profile
    matched_pairs = []
    for i, user_id in enumerate(user_ids):
        if i < len(meal_plans) and i < len(user_profiles):
            if meal_plans[i] and user_profiles[i]:
                # Verify user_id matches
                plan_user_id = meal_plans[i].get("user_id")
                profile_user_id = user_profiles[i].get("user_id")
                if plan_user_id == profile_user_id == user_id:
                    matched_pairs.append((meal_plans[i], user_profiles[i]))
                else:
                    logger.warning(
                        f"User ID mismatch: plan user_id={plan_user_id}, "
                        f"profile user_id={profile_user_id}, expected={user_id}"
                    )
    
    if not matched_pairs:
        raise ValueError("No matching meal plans and profiles found for the provided user_ids")
    
    meal_plans_matched, user_profiles_matched = zip(*matched_pairs)
    
    return list(meal_plans_matched), list(user_profiles_matched)


def get_all_user_ids_from_weaviate(
    client_manager: Optional[ClientManager] = None,
    limit: int = 100
) -> List[str]:
    """
    Lấy tất cả user IDs từ Weaviate UserProfile collection.
    
    Args:
        client_manager: ClientManager instance (tạo mới nếu None)
        limit: Số lượng users tối đa để lấy
    
    Returns:
        List of user IDs
    """
    if client_manager is None:
        client_manager = create_client_manager()
    
    if not client_manager.is_client:
        raise ValueError(
            "Weaviate client is not available. "
            "Please check your Weaviate configuration (WCD_URL, WCD_API_KEY, WEAVIATE_IS_LOCAL)."
        )
    
    try:
        client = client_manager.get_client()
        collection = client.collections.get("UserProfile")
        
        # Fetch all user profiles
        results = collection.query.fetch_objects(limit=limit)
        
        user_ids = []
        for obj in results.objects:
            user_id = obj.properties.get("user_id")
            if user_id:
                user_ids.append(str(user_id))
        
        return user_ids
    except Exception as e:
        logger.error(f"Failed to get user IDs from Weaviate: {e}", exc_info=True)
        return []


def load_meal_logs_from_weaviate(
    user_id: str,
    client_manager: ClientManager,
    date: Optional[datetime] = None,
    limit: int = 100
) -> List[Dict[str, Any]]:
    """
    Load meal logs từ Weaviate MealLogEntry collection cho một user.
    
    Args:
        user_id: User ID
        client_manager: ClientManager instance
        date: Date để filter (nếu None, lấy tất cả)
        limit: Số lượng logs tối đa
    
    Returns:
        List of meal log entry dictionaries
    """
    try:
        client = client_manager.get_client()
        collection = client.collections.get("MealLogEntry")
        
        # Build filter
        filter_conditions = [
            {"path": ["user_id"], "operator": "Equal", "valueString": str(user_id)}
        ]
        
        if date:
            # Filter by date (same day)
            date_start = date.replace(hour=0, minute=0, second=0, microsecond=0)
            date_end = date_start + timedelta(days=1)
            filter_conditions.extend([
                {"path": ["logged_at"], "operator": "GreaterThanEqual", "valueDate": date_start.isoformat().replace("+00:00", "Z")},
                {"path": ["logged_at"], "operator": "LessThan", "valueDate": date_end.isoformat().replace("+00:00", "Z")},
            ])
        
        if len(filter_conditions) > 1:
            log_filter = build_filters_from_where({
                "operator": "And",
                "operands": filter_conditions
            })
        else:
            log_filter = build_filters_from_where(filter_conditions[0])
        
        results = collection.query.fetch_objects(filters=log_filter, limit=limit)
        
        meal_logs = []
        for obj in results.objects:
            props = obj.properties
            meal_logs.append({
                "log_id": props.get("log_id"),
                "user_id": props.get("user_id"),
                "logged_at": props.get("logged_at"),
                "meal_description": props.get("meal_description"),
                "parsed_dish": props.get("parsed_dish"),
                "ingredients": props.get("ingredients"),
                "portion_size": props.get("portion_size"),
                "calculated_macros": props.get("calculated_macros"),
                "calculated_micros": props.get("calculated_micros"),
                "validation_status": props.get("validation_status"),
                "parsing_method": props.get("parsing_method"),
            })
        
        return meal_logs
    except Exception as e:
        logger.error(f"Failed to load meal logs for user {user_id} from Weaviate: {e}", exc_info=True)
        return []


def aggregate_meal_logs_to_plan(
    meal_logs: List[Dict[str, Any]],
    user_id: str,
    date: Optional[datetime] = None
) -> Optional[Dict[str, Any]]:
    """
    Aggregate meal logs thành meal plan format để đánh giá.
    
    MealLogEntry đại diện cho plans đã được user chấp nhận hoặc thực sự ăn,
    khác với MealPlan là suggested plans (chưa được user chấp nhận).
    
    Args:
        meal_logs: List of meal log entries (accepted/actual plans)
        user_id: User ID
        date: Date của meal plan
    
    Returns:
        Meal plan dictionary với total_macros được tính từ meal logs
        và source="MealLogEntry" để phân biệt với suggested plans
    """
    if not meal_logs:
        return None
    
    # Validate: Tất cả logs phải cùng 1 ngày
    log_dates = []
    for log in meal_logs:
        logged_at = log.get("logged_at")
        if logged_at:
            try:
                if isinstance(logged_at, str):
                    log_date = datetime.fromisoformat(logged_at.replace("Z", "+00:00"))
                else:
                    log_date = logged_at
                # Normalize về UTC và lấy date
                if log_date.tzinfo is None:
                    log_date = log_date.replace(tzinfo=timezone.utc)
                log_dates.append(log_date.date())
            except Exception as e:
                logger.warning(f"Failed to parse logged_at for log {log.get('log_id')}: {e}")
                continue
    
    if not log_dates:
        logger.warning(f"No valid dates found in meal logs for user {user_id}")
        return None
    
    # Kiểm tra xem tất cả logs có cùng 1 ngày không
    unique_dates = set(log_dates)
    if len(unique_dates) > 1:
        logger.warning(
            f"Meal logs for user {user_id} contain multiple dates: {unique_dates}. "
            f"Only aggregating logs from the first date: {log_dates[0]}"
        )
        # Chỉ lấy logs từ ngày đầu tiên
        target_date = log_dates[0]
        filtered_logs = []
        for log in meal_logs:
            logged_at = log.get("logged_at")
            if logged_at:
                try:
                    if isinstance(logged_at, str):
                        log_date = datetime.fromisoformat(logged_at.replace("Z", "+00:00"))
                    else:
                        log_date = logged_at
                    if log_date.tzinfo is None:
                        log_date = log_date.replace(tzinfo=timezone.utc)
                    if log_date.date() == target_date:
                        filtered_logs.append(log)
                except Exception:
                    continue
        meal_logs = filtered_logs
    
    # Xác định plan_date
    plan_date = date
    if not plan_date:
        plan_date = datetime.combine(log_dates[0], datetime.min.time()).replace(tzinfo=timezone.utc)
    
    # Aggregate macros từ tất cả meal logs (đã được filter để cùng 1 ngày)
    total_macros = {"kcal": 0.0, "protein_g": 0.0, "fat_g": 0.0, "carb_g": 0.0}
    
    for log in meal_logs:
        macros_str = log.get("calculated_macros", "{}")
        if isinstance(macros_str, str):
            try:
                macros = json.loads(macros_str)
            except json.JSONDecodeError:
                macros = {}
        else:
            macros = macros_str
        
        if isinstance(macros, dict):
            total_macros["kcal"] += float(macros.get("kcal", 0.0))
            total_macros["protein_g"] += float(macros.get("protein_g", 0.0))
            total_macros["fat_g"] += float(macros.get("fat_g", 0.0))
            total_macros["carb_g"] += float(macros.get("carb_g", 0.0))
    
    return {
        "plan_id": f"meal_logs_{user_id}_{plan_date.date().isoformat()}",
        "user_id": user_id,
        "plan_type": "day",  # MealLogEntry luôn là day plan
        "start_date": plan_date.isoformat(),
        "created_at": plan_date.isoformat(),
        "meals": {},  # Meal logs không có structure meals chi tiết
        "total_macros": total_macros,
        "source": "MealLogEntry",  # Đánh dấu: đây là accepted/actual plan (khác với suggested plan)
    }


def load_all_meal_plans_from_weaviate(
    client_manager: ClientManager,
    plan_type: Optional[str] = None,
    limit: int = 1000
) -> List[Dict[str, Any]]:
    """
    Load TẤT CẢ meal plans từ Weaviate MealPlan collection.
    
    Args:
        client_manager: ClientManager instance
        plan_type: "day" hoặc "week" hoặc None (load tất cả)
        limit: Số lượng plans tối đa
    
    Returns:
        List of meal plan dictionaries
    """
    try:
        client = client_manager.get_client()
        plan_collection = client.collections.get("MealPlan")
        
        # Build filter
        if plan_type:
            plan_filter = build_filters_from_where(
                {"path": ["plan_type"], "operator": "Equal", "valueString": plan_type}
            )
        else:
            plan_filter = None
        
        # Fetch all meal plans
        results = plan_collection.query.fetch_objects(
            filters=plan_filter,
            limit=limit
        )
        
        meal_plans = []
        total_objects = len(results.objects)
        loaded_count = 0
        skipped_count = 0
        
        for idx, obj in enumerate(results.objects, 1):
            props = obj.properties
            plan_id = props.get("plan_id")
            user_id = props.get("user_id")
            
            if not plan_id or not user_id:
                skipped_count += 1
                continue
            
            try:
                plan = load_plan_from_weaviate(plan_id, client_manager, user_id)
                if plan and plan.get("user_id"):
                    meal_plans.append(plan)
                    loaded_count += 1
                else:
                    skipped_count += 1
            except Exception as e:
                skipped_count += 1
                logger.warning(f"Error loading plan {plan_id}: {e}")
        
        return meal_plans
    except Exception as e:
        logger.error(f"Failed to load all meal plans from Weaviate: {e}", exc_info=True)
        return []


def load_all_meal_logs_from_weaviate(
    client_manager: ClientManager,
    date: Optional[datetime] = None,
    limit: int = 1000
) -> List[Dict[str, Any]]:
    """
    Load TẤT CẢ meal logs từ Weaviate MealLogEntry collection và aggregate theo user và date.
    
    Args:
        client_manager: ClientManager instance
        date: Date để filter (nếu None, load tất cả)
        limit: Số lượng logs tối đa
    
    Returns:
        List of aggregated meal plan dictionaries (từ meal logs)
    """
    try:
        client = client_manager.get_client()
        log_collection = client.collections.get("MealLogEntry")
        
        # Build filter
        if date:
            date_start = date.replace(hour=0, minute=0, second=0, microsecond=0)
            date_end = date_start + timedelta(days=1)
            log_filter = build_filters_from_where({
                "operator": "And",
                "operands": [
                    {"path": ["logged_at"], "operator": "GreaterThanEqual", "valueDate": date_start.isoformat().replace("+00:00", "Z")},
                    {"path": ["logged_at"], "operator": "LessThan", "valueDate": date_end.isoformat().replace("+00:00", "Z")},
                ]
            })
        else:
            log_filter = None
        
        # Fetch all meal logs
        results = log_collection.query.fetch_objects(
            filters=log_filter,
            limit=limit
        )
        
        total_logs = len(results.objects)
        
        # Group logs by user_id and date
        logs_by_user_date: Dict[tuple[str, str], List[Dict[str, Any]]] = {}
        
        for obj in results.objects:
            props = obj.properties
            user_id = props.get("user_id")
            logged_at = props.get("logged_at")
            
            if not user_id or not logged_at:
                continue
            
            # Parse date - đảm bảo normalize về UTC và lấy đúng date
            try:
                if isinstance(logged_at, str):
                    log_date = datetime.fromisoformat(logged_at.replace("Z", "+00:00"))
                else:
                    log_date = logged_at
                
                # Normalize về UTC nếu chưa có timezone
                if log_date.tzinfo is None:
                    log_date = log_date.replace(tzinfo=timezone.utc)
                elif log_date.tzinfo != timezone.utc:
                    # Convert về UTC
                    log_date = log_date.astimezone(timezone.utc)
                
                # Lấy date (bỏ time)
                date_key = log_date.date().isoformat()
            except Exception as e:
                logger.warning(f"Failed to parse logged_at for log: {e}")
                continue
            
            key = (str(user_id), date_key)
            if key not in logs_by_user_date:
                logs_by_user_date[key] = []
            
            logs_by_user_date[key].append({
                "log_id": props.get("log_id"),
                "user_id": user_id,
                "logged_at": logged_at,
                "meal_description": props.get("meal_description"),
                "parsed_dish": props.get("parsed_dish"),
                "ingredients": props.get("ingredients"),
                "portion_size": props.get("portion_size"),
                "calculated_macros": props.get("calculated_macros"),
                "calculated_micros": props.get("calculated_micros"),
                "validation_status": props.get("validation_status"),
                "parsing_method": props.get("parsing_method"),
            })
        
        # Aggregate logs into meal plans
        meal_plans = []
        for (user_id, date_key), logs in logs_by_user_date.items():
            try:
                plan_date = datetime.fromisoformat(f"{date_key}T00:00:00+00:00")
            except Exception:
                plan_date = datetime.now(timezone.utc)
            
            plan = aggregate_meal_logs_to_plan(logs, user_id, plan_date)
            if plan:
                meal_plans.append(plan)
        
        return meal_plans
    except Exception as e:
        logger.error(f"Failed to load all meal logs from Weaviate: {e}", exc_info=True)
        return []


def load_all_evaluation_data_from_weaviate(
    client_manager: Optional[ClientManager] = None,
    include_meal_plans: bool = True,
    include_meal_logs: bool = True,
    plan_type: Optional[str] = None,
    date: Optional[datetime] = None,
    limit: int = 1000
) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Load TẤT CẢ meal plans và meal logs từ Weaviate để đánh giá toàn diện.
    
    Args:
        client_manager: ClientManager instance (tạo mới nếu None)
        include_meal_plans: Load từ MealPlan collection
        include_meal_logs: Load từ MealLogEntry collection
        plan_type: "day" hoặc "week" hoặc None (load tất cả) - chỉ dùng với meal plans
        date: Date để filter meal logs (nếu None, load tất cả)
        limit: Số lượng items tối đa mỗi collection
    
    Returns:
        Tuple of (meal_plans, user_profiles)
        - meal_plans: Bao gồm cả plans từ MealPlan và aggregated plans từ MealLogEntry
        - user_profiles: Tất cả user profiles với nutrition targets
    """
    if client_manager is None:
        client_manager = create_client_manager()
    
    if not client_manager.is_client:
        raise ValueError(
            "Weaviate client is not available. "
            "Please check your Weaviate configuration (WCD_URL, WCD_API_KEY, WEAVIATE_IS_LOCAL)."
        )
    
    all_meal_plans = []
    user_ids_set = set()
    
    # Load từ MealPlan collection
    if include_meal_plans:
        meal_plans = load_all_meal_plans_from_weaviate(client_manager, plan_type, limit)
        all_meal_plans.extend(meal_plans)
        for plan in meal_plans:
            user_id = plan.get("user_id")
            if user_id:
                user_ids_set.add(str(user_id))
    
    # Load từ MealLogEntry collection
    if include_meal_logs:
        meal_log_plans = load_all_meal_logs_from_weaviate(client_manager, date, limit)
        all_meal_plans.extend(meal_log_plans)
        for plan in meal_log_plans:
            user_id = plan.get("user_id")
            if user_id:
                user_ids_set.add(str(user_id))
    
    # Load tất cả user profiles
    user_ids = list(user_ids_set)
    user_profiles = load_user_profiles_from_weaviate(user_ids, client_manager)
    
    # Match meal plans với profiles
    # Tạo dict để lookup nhanh
    profile_dict = {p.get("user_id"): p for p in user_profiles if p.get("user_id")}
    
    matched_plans = []
    matched_profiles = []
    
    for plan in all_meal_plans:
        user_id = plan.get("user_id")
        if not user_id:
            logger.warning(f"Plan {plan.get('plan_id', 'unknown')} has no user_id, skipping")
            continue
        
        # Convert to string for lookup
        user_id_str = str(user_id)
        profile = profile_dict.get(user_id_str)
        if profile:
            matched_plans.append(plan)
            matched_profiles.append(profile)
        else:
            logger.warning(f"No profile found for user {user_id}, skipping plan {plan.get('plan_id')}")
    
    if not matched_plans:
        raise ValueError("No matching meal plans/logs and profiles found")
    
    return matched_plans, matched_profiles


def load_evaluation_data_from_weaviate_with_logs(
    user_ids: List[str],
    client_manager: Optional[ClientManager] = None,
    use_meal_logs: bool = False,
    date: Optional[datetime] = None,
    plan_type: str = "day",
    use_latest: bool = True
) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Load meal plans (từ MealPlan hoặc MealLogEntry) và user profiles từ Weaviate cho evaluation.
    
    Args:
        user_ids: List of user IDs
        client_manager: ClientManager instance (tạo mới nếu None)
        use_meal_logs: Nếu True, load từ MealLogEntry. Nếu False, load từ MealPlan
        date: Date để filter meal logs (nếu None, dùng today)
        plan_type: "day" hoặc "week" (chỉ dùng khi use_meal_logs=False)
        use_latest: Load plan mới nhất của mỗi user (chỉ dùng khi use_meal_logs=False)
    
    Returns:
        Tuple of (meal_plans, user_profiles)
    """
    if client_manager is None:
        client_manager = create_client_manager()
    
    if not client_manager.is_client:
        raise ValueError(
            "Weaviate client is not available. "
            "Please check your Weaviate configuration (WCD_URL, WCD_API_KEY, WEAVIATE_IS_LOCAL)."
        )
    
    # Load user profiles
    user_profiles = load_user_profiles_from_weaviate(user_ids, client_manager)
    
    # Load meal plans hoặc meal logs
    meal_plans = []
    if use_meal_logs:
        # Load từ MealLogEntry
        if date is None:
            date = datetime.now(timezone.utc)
        
        for user_id in user_ids:
            meal_logs = load_meal_logs_from_weaviate(user_id, client_manager, date)
            if meal_logs:
                plan = aggregate_meal_logs_to_plan(meal_logs, user_id, date)
                if plan:
                    meal_plans.append(plan)
            else:
                logger.warning(f"No meal logs found for user {user_id} on {date.date()}")
    else:
        # Load từ MealPlan
        meal_plans = load_meal_plans_by_user_ids(user_ids, client_manager, plan_type, use_latest)
    
    # Match meal plans với profiles
    matched_pairs = []
    for i, user_id in enumerate(user_ids):
        # Tìm profile
        profile = next((p for p in user_profiles if p.get("user_id") == user_id), None)
        
        # Tìm meal plan
        plan = next((p for p in meal_plans if p.get("user_id") == user_id), None)
        
        if plan and profile:
            matched_pairs.append((plan, profile))
        else:
            if not plan:
                logger.warning(f"No meal plan/logs found for user {user_id}")
            if not profile:
                logger.warning(f"No profile found for user {user_id}")
    
    if not matched_pairs:
        raise ValueError("No matching meal plans/logs and profiles found for the provided user_ids")
    
    meal_plans_matched, user_profiles_matched = zip(*matched_pairs)
    
    return list(meal_plans_matched), list(user_profiles_matched)

