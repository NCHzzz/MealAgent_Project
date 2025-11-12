from typing import AsyncGenerator, Dict, Any
from datetime import datetime, timedelta
import json

from elysia.tree.objects import TreeData
from elysia.objects import Result, Error, Response
from elysia.util.client import ClientManager
from elysia import tool


@tool
async def profile_update_tool(
    tree_data: TreeData,
    client_manager: ClientManager,
    user_id: str = "",
    **kwargs,
) -> AsyncGenerator[Result | str | Error, None]:
    """
    Update UserProfile with consumed nutrition and calculate remaining targets.

    Code-Based Tool: Updates profile and saves MealLogEntry.

    Environment reads:
      - environment["meal_parser_tool"]["parsed_meal"]
      - environment["nutrition_calc_tool"]["calculated"]
    Environment writes:
      - environment["profile_update_tool"]["updated_profile"]
    """
    yield Response("Updating profile with consumed nutrition...")

    if not user_id:
        yield Error("user_id is required")
        return

    # Read parsed meal and calculated nutrition
    parsed_results = tree_data.environment.find("meal_parser_tool", "parsed_meal")
    nutrition_results = tree_data.environment.find("nutrition_calc_tool", "calculated")

    if not parsed_results or not parsed_results[0].objects:
        yield Error("Parsed meal not found")
        return

    if not nutrition_results or not nutrition_results[0].objects:
        yield Error("Calculated nutrition not found")
        return

    parsed_meal = parsed_results[0].objects[0]
    calculated_nutrition = nutrition_results[0].objects[0]

    try:
        client = client_manager.get_client()
        profile_collection = client.collections.get("UserProfile")
        log_collection = client.collections.get("MealLogEntry")

        # Read current profile
        profile_results = profile_collection.query.fetch_objects(
            where={"path": ["user_id"], "operator": "Equal", "valueString": user_id},
            limit=1,
        )

        if not profile_results.objects:
            yield Error(f"Profile not found for user {user_id}")
            return

        profile = profile_results.objects[0].properties
        profile_uuid = profile_results.objects[0].uuid

        # Get today's consumed nutrition (aggregate from MealLogEntry)
        # Use date range query for accurate filtering
        today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        today_end = today_start + timedelta(days=1)
        
        today_logs = log_collection.query.fetch_objects(
            where={
                "operator": "And",
                "operands": [
                    {"path": ["user_id"], "operator": "Equal", "valueString": user_id},
                    {"path": ["logged_at"], "operator": "GreaterThanEqual", "valueDate": today_start.isoformat()},
                    {"path": ["logged_at"], "operator": "LessThan", "valueDate": today_end.isoformat()},
                ],
            },
        )

        # Aggregate today's consumed
        today_consumed = {"kcal": 0.0, "protein_g": 0.0, "fat_g": 0.0, "carb_g": 0.0}
        for log_obj in today_logs.objects:
            log_macros_str = log_obj.properties.get("calculated_macros", "{}")
            # Deserialize JSON string if needed
            if isinstance(log_macros_str, str):
                try:
                    log_macros = json.loads(log_macros_str)
                except json.JSONDecodeError:
                    log_macros = {}
            else:
                log_macros = log_macros_str
            
            if isinstance(log_macros, dict):
                today_consumed["kcal"] += float(log_macros.get("kcal", 0.0))
                today_consumed["protein_g"] += float(log_macros.get("protein_g", 0.0))
                today_consumed["fat_g"] += float(log_macros.get("fat_g", 0.0))
                today_consumed["carb_g"] += float(log_macros.get("carb_g", 0.0))

        # Add current meal
        consumed_macros = calculated_nutrition.get("calculated_macros", {})
        today_consumed["kcal"] += float(consumed_macros.get("kcal", 0.0))
        today_consumed["protein_g"] += float(consumed_macros.get("protein_g", 0.0))
        today_consumed["fat_g"] += float(consumed_macros.get("fat_g", 0.0))
        today_consumed["carb_g"] += float(consumed_macros.get("carb_g", 0.0))

        # Calculate remaining targets
        target_macros = {
            "kcal": float(profile.get("tdee_kcal", 2000)),
            "protein_g": float(profile.get("protein_g", 150)),
            "fat_g": float(profile.get("fat_g", 67)),
            "carb_g": float(profile.get("carb_g", 200)),
        }

        remaining_targets = {
            "kcal": max(0.0, target_macros["kcal"] - today_consumed["kcal"]),
            "protein_g": max(0.0, target_macros["protein_g"] - today_consumed["protein_g"]),
            "fat_g": max(0.0, target_macros["fat_g"] - today_consumed["fat_g"]),
            "carb_g": max(0.0, target_macros["carb_g"] - today_consumed["carb_g"]),
        }

        # Save MealLogEntry
        # Serialize JSON fields as required by schema (TEXT fields)
        log_entry = {
            "log_id": f"log_{user_id}_{int(datetime.now().timestamp())}",
            "user_id": user_id,
            "logged_at": datetime.now().isoformat(),
            "meal_description": parsed_meal.get("original_description", ""),
            "parsed_dish": parsed_meal.get("dish", ""),
            "ingredients": json.dumps(parsed_meal.get("ingredients", [])),
            "portion_size": parsed_meal.get("portion_size", 1.0),
            "calculated_macros": json.dumps(consumed_macros),
            "calculated_micros": json.dumps(calculated_nutrition.get("calculated_micros", {})),
            "validation_status": parsed_meal.get("validation_status", "complete"),
            "parsing_method": "llm",
        }

        log_collection.data.insert(log_entry)

        # Update profile timestamp
        profile["updated_at"] = datetime.now().isoformat()
        profile_collection.data.update(uuid=profile_uuid, properties=profile)

        updated_data = {
            "remaining_targets": remaining_targets,
            "consumed_today": today_consumed,
            "consumed_this_meal": consumed_macros,
            "log_entry": log_entry,
        }

        # Stream response first for immediate feedback
        yield Response(f"Meal logged successfully. Remaining: {remaining_targets['kcal']:.0f} kcal | {remaining_targets['protein_g']:.0f}g P")
        
        # Then yield Result for data consistency
        yield Result(
            name="updated_profile",
            objects=[updated_data],
            metadata={"user_id": user_id, "logged_at": log_entry["logged_at"]},
            payload_type="generic",
        )

    except Exception as e:
        yield Error(f"Profile update failed for user {user_id}: {str(e)}")
        return

