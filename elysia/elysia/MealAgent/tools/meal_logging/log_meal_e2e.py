from typing import AsyncGenerator, Dict, Any, List
import json
from datetime import datetime, timedelta

from elysia.tree.objects import TreeData
from elysia.objects import Result, Error, Response
from elysia.util.client import ClientManager
from elysia import tool


@tool
async def log_meal_e2e_tool(
    tree_data: TreeData,
    client_manager: ClientManager,
    base_lm,
    user_id: str,
    meal_description: str,
    **kwargs,
) -> AsyncGenerator[Result | str | Error, None]:
    """
    End-to-end: parse → nutrition_calc → update profile → emit final result.
    """
    yield Response("Logging meal in one step...")

    if not user_id:
        yield Error("user_id is required")
        return
    if not meal_description:
        yield Error("meal_description is required")
        return

    # Parse with LLM
    llm_prompt = f"""Parse this meal description into structured JSON:
"{meal_description}"

Return JSON with:
- dish: dish name
- ingredients: list of [{{"name": str, "amount": float, "unit": str}}]
- portion_size: number (default 1.0)
"""
    try:
        llm_response = await base_lm.generate_structured(
            prompt=llm_prompt,
            schema={
                "type": "object",
                "properties": {
                    "dish": {"type": "string"},
                    "ingredients": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "amount": {"type": "number"},
                                "unit": {"type": "string"},
                            },
                            "required": ["name"],
                        },
                    },
                    "portion_size": {"type": "number"},
                },
                "required": ["dish", "ingredients"],
            },
        )
        parsed_data = json.loads(llm_response) if isinstance(llm_response, str) else llm_response
    except Exception as e:
        yield Error(f"Failed to parse meal: {str(e)}")
        return

    # Nutrition calc + profile update
    try:
        client = client_manager.get_client()
        fdc_collection = client.collections.get("FdcFood")
        portion_collection = client.collections.get("FdcPortion")
        profile_collection = client.collections.get("UserProfile")
        log_collection = client.collections.get("MealLogEntry")

        # Validate ingredients against FDC
        validated_ingredients = []
        for ing in parsed_data.get("ingredients", []):
            name = ing.get("name", "")
            if not name:
                continue
            sr = fdc_collection.query.hybrid(query=name, limit=1)
            if sr.objects:
                f = sr.objects[0].properties
                validated_ingredients.append({**ing, "fdc_id": f.get("fdc_id")})
            else:
                validated_ingredients.append({**ing, "fdc_id": None, "validation_status": "not_found"})

        # Calculate nutrition
        portion_size = float(parsed_data.get("portion_size", 1.0))
        total_macros = {"kcal": 0.0, "protein_g": 0.0, "fat_g": 0.0, "carb_g": 0.0}
        total_micros: Dict[str, float] = {}
        warnings: List[str] = []

        for ing in validated_ingredients:
            fdc_id = ing.get("fdc_id")
            if not fdc_id:
                continue
            amount = float(ing.get("amount", 0))
            unit = ing.get("unit", "g")
            fdc_results = fdc_collection.query.fetch_objects(
                where={"path": ["fdc_id"], "operator": "Equal", "valueInt": int(fdc_id)}, limit=1
            )
            if not fdc_results.objects:
                continue
            fdc_food = fdc_results.objects[0].properties
            grams = amount
            if unit != "g":
                pr = portion_collection.query.fetch_objects(
                    where={"path": ["fdc_id"], "operator": "Equal", "valueInt": int(fdc_id)}, limit=10
                )
                converted = False
                for po in pr.objects:
                    p = po.properties
                    if p.get("measure_unit", "").lower() == unit.lower():
                        gw = p.get("gram_weight", 0.0)
                        if gw > 0:
                            portion_amount = p.get("amount", 1.0)
                            grams = (amount / portion_amount) * gw
                            converted = True
                            break
                if not converted:
                    warnings.append(f"Could not convert {amount} {unit} to grams for '{ing.get('name', 'unknown')}', assuming grams")
            scale = (grams * portion_size) / 100.0
            total_macros["kcal"] += float(fdc_food.get("energy_kcal_100g", 0.0)) * scale
            total_macros["protein_g"] += float(fdc_food.get("protein_g_100g", 0.0)) * scale
            total_macros["fat_g"] += float(fdc_food.get("fat_g_100g", 0.0)) * scale
            total_macros["carb_g"] += float(fdc_food.get("carbohydrate_g_100g", 0.0)) * scale

        # Update profile + create log
        profile_results = profile_collection.query.fetch_objects(
            where={"path": ["user_id"], "operator": "Equal", "valueString": user_id}, limit=1
        )
        if not profile_results.objects:
            yield Error(f"Profile not found for user {user_id}")
            return
        profile = profile_results.objects[0].properties
        profile_uuid = profile_results.objects[0].uuid

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
        today_consumed = {"kcal": 0.0, "protein_g": 0.0, "fat_g": 0.0, "carb_g": 0.0}
        for obj in today_logs.objects:
            macros_str = obj.properties.get("calculated_macros", "{}")
            if isinstance(macros_str, str):
                try:
                    macros = json.loads(macros_str)
                except json.JSONDecodeError:
                    macros = {}
            else:
                macros = macros_str
            if isinstance(macros, dict):
                today_consumed["kcal"] += float(macros.get("kcal", 0.0))
                today_consumed["protein_g"] += float(macros.get("protein_g", 0.0))
                today_consumed["fat_g"] += float(macros.get("fat_g", 0.0))
                today_consumed["carb_g"] += float(macros.get("carb_g", 0.0))

        today_consumed["kcal"] += total_macros["kcal"]
        today_consumed["protein_g"] += total_macros["protein_g"]
        today_consumed["fat_g"] += total_macros["fat_g"]
        today_consumed["carb_g"] += total_macros["carb_g"]

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

        log_entry = {
            "log_id": f"log_{user_id}_{int(datetime.now().timestamp())}",
            "user_id": user_id,
            "logged_at": datetime.now().isoformat(),
            "meal_description": meal_description,
            "parsed_dish": parsed_data.get("dish", ""),
            "ingredients": json.dumps(validated_ingredients),
            "portion_size": parsed_data.get("portion_size", 1.0),
            "calculated_macros": json.dumps(total_macros),
            "calculated_micros": json.dumps({}),
            "validation_status": "complete" if all(ing.get("fdc_id") for ing in validated_ingredients) else "partial",
            "parsing_method": "llm",
        }
        log_collection.data.insert(log_entry)

        profile["updated_at"] = datetime.now().isoformat()
        profile_collection.data.update(uuid=profile_uuid, properties=profile)

        updated = {
            "remaining_targets": remaining_targets,
            "consumed_today": today_consumed,
            "consumed_this_meal": total_macros,
            "log_entry": log_entry,
            "warnings": warnings,
        }

        yield Result(
            name="updated_profile",
            objects=[updated],
            metadata={"user_id": user_id, "logged_at": log_entry["logged_at"]},
            payload_type="generic",
        )
        yield Response(f"Meal logged. Remaining: {remaining_targets['kcal']:.0f} kcal | {remaining_targets['protein_g']:.0f}g P")

    except Exception as e:
        yield Error(f"log_meal_e2e_tool failed: {str(e)}")
        return


