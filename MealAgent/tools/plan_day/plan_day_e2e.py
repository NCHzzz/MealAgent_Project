from typing import AsyncGenerator, Dict, Any, List
import logging
from datetime import datetime

from elysia.tree.objects import TreeData
from elysia.objects import Result, Error, Response
from elysia.util.client import ClientManager
from elysia import tool

from MealAgent.tools.utils.planning_helpers import (
    _get_meal_macros,
    _validate_macro_targets,
    _validate_constraints,
    sync_plan_to_weaviate,
)
from MealAgent.tools.nutrition.calculate_recipe_macros import calculate_recipe_macros_tool
from MealAgent.utils.nutrition import build_default_macro_targets


def _record_missing_macro_state(tree_data: TreeData, recipe_ids: List[str]) -> None:
    """Persist the list of recipe IDs lacking macros for other tools."""
    try:
        tree_data.environment.add_objects(
            "plan_day_e2e_tool",
            "missing_macros",
            [
                {
                    "recipe_ids": recipe_ids,
                    "timestamp": datetime.now().isoformat(),
                }
            ],
        )
    except Exception:
        logging.debug("plan_day_e2e_tool: failed to record missing macros in environment.")


def _clear_missing_macro_state(tree_data: TreeData) -> None:
    """Publish a resolved signal so the decision agent stops re-running nutrition tools."""
    try:
        tree_data.environment.add_objects(
            "plan_day_e2e_tool",
            "missing_macros",
            [
                {
                    "recipe_ids": [],
                    "status": "resolved",
                    "timestamp": datetime.now().isoformat(),
                }
            ],
        )
    except Exception:
        logging.debug("plan_day_e2e_tool: failed to clear missing macros state.")


def _is_vietnamese_breakfast(recipe: Dict[str, Any]) -> bool:
    """Check if recipe is a Vietnamese breakfast dish."""
    dish_name = str(recipe.get("dish_name", "")).lower()
    dish_type = str(recipe.get("dish_type", "")).lower()
    
    # Vietnamese breakfast keywords
    breakfast_keywords = [
        "phở", "pho", "banh mi", "bánh mì", "bun bo", "bún bò", 
        "hu tieu", "hủ tiếu", "banh cuon", "bánh cuốn",
        "bun rieu", "bún riêu", "banh canh", "bánh canh",
        "xoi", "xôi", "chao", "cháo", "banh bao", "bánh bao", "cơm tấm", "com tam", "sandwich"
    ]
    
    # Check dish_name
    if any(keyword in dish_name for keyword in breakfast_keywords):
        return True
    
    # Check dish_type
    if any(keyword in dish_type for keyword in breakfast_keywords):
        return True
    
    # Check meal_type field
    meal_type = str(recipe.get("meal_type", "")).lower()
    if "breakfast" in meal_type or "sáng" in meal_type:
        return True
    
    return False


def _is_rice_dish(recipe: Dict[str, Any]) -> bool:
    """Check if recipe is a rice dish (cơm)."""
    dish_name = str(recipe.get("dish_name", "")).lower()
    dish_type = str(recipe.get("dish_type", "")).lower()
    
    rice_keywords = ["cơm", "com", "rice"]
    return any(keyword in dish_name or keyword in dish_type for keyword in rice_keywords)


def _is_main_dish(recipe: Dict[str, Any]) -> bool:
    """Check if recipe is a main dish (món mặn)."""
    dish_name = str(recipe.get("dish_name", "")).lower()
    dish_type = str(recipe.get("dish_type", "")).lower()
    
    # Exclude breakfast, rice, vegetables, fruits
    if _is_vietnamese_breakfast(recipe) or _is_rice_dish(recipe):
        return False
    
    main_keywords = [
        "thịt", "thit", "cá", "ca", "tôm", "tom", "gà", "ga",
        "heo", "bò", "bo", "meat", "fish", "chicken", "pork", "beef",
        "kho", "nướng", "nuong", "rang", "xào", "xao", "chiên", "chien"
    ]
    
    return any(keyword in dish_name or keyword in dish_type for keyword in main_keywords)


def _is_vegetable_dish(recipe: Dict[str, Any]) -> bool:
    """Check if recipe is a vegetable dish (rau)."""
    dish_name = str(recipe.get("dish_name", "")).lower()
    dish_type = str(recipe.get("dish_type", "")).lower()
    
    veg_keywords = [
        "rau", "cải", "cai", "xà lách", "xa lach", "salad",
        "vegetable", "greens", "cucumber", "dưa chuột", "dua chuot"
    ]
    
    return any(keyword in dish_name or keyword in dish_type for keyword in veg_keywords)


def _is_fruit(recipe: Dict[str, Any]) -> bool:
    """Check if recipe is a fruit (trái cây)."""
    dish_name = str(recipe.get("dish_name", "")).lower()
    dish_type = str(recipe.get("dish_type", "")).lower()
    
    fruit_keywords = [
        "trái cây", "trai cay", "fruit", "chuối", "chuoi", "táo", "tao",
        "cam", "ổi", "oi", "dưa hấu", "dua hau", "watermelon", "apple", "orange"
    ]
    
    return any(keyword in dish_name or keyword in dish_type for keyword in fruit_keywords)


def _matches_meal_slot(recipe: Dict[str, Any], slot: str) -> bool:
    """Check if recipe matches meal slot (breakfast/lunch/dinner)."""
    slot = slot.lower()
    dish_type = recipe.get("dish_type")
    meal_type = recipe.get("meal_type")

    # Check explicit meal_type field
    if isinstance(meal_type, str):
        if slot in meal_type.lower():
            return True
    
    # Check dish_type field
    if isinstance(dish_type, str):
        if slot in dish_type.lower():
            return True
    if isinstance(dish_type, list):
        if any(slot in str(entry).lower() for entry in dish_type):
            return True

    # Vietnamese breakfast detection
    if slot == "breakfast" or slot == "sáng":
        return _is_vietnamese_breakfast(recipe)
    
    # For lunch/dinner, exclude breakfast dishes
    if slot in ["lunch", "dinner", "trưa", "tối"]:
        return not _is_vietnamese_breakfast(recipe)
    
    return False


def _select_meal_by_strategy(
    recipes: List[Dict[str, Any]],
    strategy: str,
    exclude: List[Dict[str, Any]] | None = None,
    preferred_meal_type: str | None = None,
    dish_category: str | None = None,
) -> Dict[str, Any] | None:
    """
    Select recipe based on strategy (highest_carb, highest_protein, balanced).
    
    Args:
        recipes: List of recipe candidates
        strategy: Selection strategy
        exclude: Recipes to exclude
        preferred_meal_type: Preferred meal type (breakfast/lunch/dinner)
        dish_category: Specific dish category (rice/main/vegetable/fruit/breakfast)
    """
    if not recipes:
        return None
    exclude_ids = {r.get("food_id") for r in (exclude or []) if r.get("food_id")}
    candidates = [r for r in recipes if r.get("food_id") not in exclude_ids]
    if not candidates:
        return None

    # Filter by dish category if specified
    if dish_category:
        if dish_category == "breakfast":
            category_candidates = [r for r in candidates if _is_vietnamese_breakfast(r)]
        elif dish_category == "rice":
            category_candidates = [r for r in candidates if _is_rice_dish(r)]
        elif dish_category == "main":
            category_candidates = [r for r in candidates if _is_main_dish(r)]
        elif dish_category == "vegetable":
            category_candidates = [r for r in candidates if _is_vegetable_dish(r)]
        elif dish_category == "fruit":
            category_candidates = [r for r in candidates if _is_fruit(r)]
        else:
            category_candidates = candidates
        
        if category_candidates:
            candidates = category_candidates

    # Filter by meal type
    if preferred_meal_type:
        typed_candidates = [r for r in candidates if _matches_meal_slot(r, preferred_meal_type)]
        if typed_candidates:
            candidates = typed_candidates

    # Apply strategy
    if strategy == "highest_carb":
        candidates.sort(key=lambda r: _get_meal_macros(r).get("carb_g", 0.0), reverse=True)
    elif strategy == "highest_protein":
        candidates.sort(key=lambda r: _get_meal_macros(r).get("protein_g", 0.0), reverse=True)
    elif strategy == "balanced":
        candidates.sort(key=lambda r: r.get("fit_score", 0.0), reverse=True)
    
    return candidates[0] if candidates else None


async def _ensure_recipe_macros_cached(
    recipe: Dict[str, Any],
    tree_data: TreeData,
    client_manager: ClientManager,
    base_lm,
) -> Dict[str, float] | None:
    macros = recipe.get("macros_per_serving")
    if isinstance(macros, dict) and macros.get("kcal"):
        return macros

    food_id = recipe.get("food_id") or recipe.get("fdc_id")
    if not food_id:
        return macros

    # Try full VN→EN macro calculation first
    try:
        async for result in calculate_recipe_macros_tool(
            inputs={"recipe_id": str(food_id)},
            complex_lm=None,
            tree_data=tree_data,
            client_manager=client_manager,
            base_lm=base_lm,
        ):
            if isinstance(result, Error):
                break
            if isinstance(result, Result) and result.name == "macros" and result.objects:
                recipe["macros_per_serving"] = result.objects[0]
                return recipe["macros_per_serving"]
    except Exception as exc:
        logging.warning(
            "plan_day_e2e_tool: calculate_recipe_macros_tool failed for %s (%s)",
            food_id,
            exc,
        )

    # If the VN→EN tool failed or macros are still missing, we do **not**
    # attempt to guess macros from a single FDC row. That would violate the
    # design contract where Recipe ↔ FdcFood links only via ingredient-level
    # mappings. In that case we simply return whatever is on the recipe
    # (which may still be zeros) and let validation/reporting surface it.
    return recipe.get("macros_per_serving")


@tool
async def plan_day_e2e_tool(
    tree_data: TreeData,
    client_manager: ClientManager,
    base_lm=None,
    query_text: str = "",
    collection_name: str = "Recipe",
    macro_tolerance_percent: float = 0.15,
    user_id: str | None = None,
    plan_id: str | None = None,
    start_date: str | None = None,
    **kwargs,
) -> AsyncGenerator[Result | Response | Error, None]:
    """
    End-to-end daily planning (profile → targets → constraints → search → plan → validation).

    Environment contract:
      Reads
        • `macro_calc_tool.targets` for individualized macro goals.
        • `constraints_guard_tool.filters` for merged diet/allergen/time filters.
        • `search_and_rank_tool.topk` for ranked candidate recipes (must include macros).
      Writes
        • `plan_day_e2e_tool.plan` – canonical day plan payload rendered in the UI.
        • `plan_day_e2e_tool.missing_macros` – list of recipe IDs that blocked planning (empty when resolved).

    Decision hints:
      • Presence of `plan_day_e2e_tool.plan` means planning succeeded; inspect metadata.valid for status.
      • Non-empty `plan_day_e2e_tool.missing_macros` instructs the agent to call nutrition tools first.
    """
    logging.info("plan_day_e2e_tool: start")
    yield Response("🍽️ Planning your daily meals (breakfast, lunch, dinner)...")

    try:
        if not user_id:
            profile_results = tree_data.environment.find("profile_crud_tool", "profile")
            if profile_results and profile_results[0]["objects"]:
                user_id = profile_results[0]["objects"][0].get("user_id")

        # Step 1: Resolve targets (for validation)
        targets = None
        macro_results = tree_data.environment.find("macro_calc_tool", "targets")
        if macro_results and macro_results[0]["objects"]:
            targets = macro_results[0]["objects"][0]
        
        if targets:
            yield Response(
                f"📊 Using your targets: {targets.get('tdee_kcal', 0):.0f} kcal | "
                f"{targets.get('protein_g', 0):.0f}g protein | "
                f"{targets.get('carb_g', 0):.0f}g carbs"
            )
        else:
            targets = build_default_macro_targets()
            yield Response(
                f"📊 Using default targets: {targets['tdee_kcal']:.0f} kcal/day "
                "(create a profile for personalized targets)"
            )

        # Step 2: Read constraints filters (for validation)
        filters_results = tree_data.environment.find("constraints_guard_tool", "filters")
        filters_metadata: Dict[str, Any] | None = None
        if filters_results and filters_results[0]["objects"]:
            filters_metadata = filters_results[0].get("metadata") or {}
            diet_types = filters_metadata.get("diet_types", [])
            allergens = filters_metadata.get("exclude_allergens", [])
            constraint_msg = "✅ Applying your dietary preferences"
            if diet_types:
                constraint_msg += f" ({', '.join(diet_types)})"
            if allergens:
                constraint_msg += f" (excluding: {', '.join(allergens)})"
            yield Response(constraint_msg)
        else:
            yield Response("ℹ️ No dietary constraints specified")

        # Step 3: Read ranked recipes
        sr = tree_data.environment.find("search_and_rank_tool", "topk")
        if not sr or not sr[0]["objects"]:
            yield Error("No ranked items available. Run search_and_rank_tool first.")
            return
        recipes = sr[0]["objects"]

        if len(recipes) < 3:
            yield Error("Insufficient recipes for 3-meal plan. Need at least 3 recipes.")
            return

        # Check for missing macros and auto-calculate if base_lm is available
        missing_macros = [
            r for r in recipes
            if not r.get("macros_per_serving") or not isinstance(r.get("macros_per_serving"), dict)
            or not r.get("macros_per_serving", {}).get("kcal")
        ]
        if missing_macros:
            effective_base_lm = base_lm or kwargs.get("base_lm")
            if effective_base_lm:
                yield Response(f"🧮 Calculating nutrition for {len(missing_macros)} recipe(s)...")
                calculated_count = 0
                for recipe in missing_macros:
                    macros = await _ensure_recipe_macros_cached(
                        recipe,
                        tree_data,
                        client_manager,
                        effective_base_lm,
                    )
                    if macros and macros.get("kcal"):
                        calculated_count += 1
                if calculated_count > 0:
                    yield Response(f"✅ Calculated nutrition for {calculated_count} recipe(s).")
                if calculated_count < len(missing_macros):
                    yield Response(f"⚠️ {len(missing_macros) - calculated_count} recipe(s) still missing nutrition data.")
            else:
                logging.warning(f"plan_day_e2e_tool: {len(missing_macros)} recipes missing macros_per_serving")
                yield Response(f"Warning: {len(missing_macros)} recipes missing macros. Consider running calculate_recipe_macros_tool for accurate planning.")
        
        # Re-check for missing macros after auto-calculation attempt
        missing_macros = [
            r for r in recipes
            if not r.get("macros_per_serving") or not isinstance(r.get("macros_per_serving"), dict)
            or not r.get("macros_per_serving", {}).get("kcal")
        ]

        if missing_macros:
            missing_ids = ", ".join(str(r.get("food_id")) for r in missing_macros[:5])
            _record_missing_macro_state(
                tree_data,
                [str(r.get("food_id")) for r in missing_macros if r.get("food_id")],
            )
            yield Error(
                f"Unable to build meal plan because {len(missing_macros)} recipe(s) still lack nutrition data "
                f"(e.g. {missing_ids}). Please calculate macros before planning."
            )
            return

        # Step 4: Assemble plan (Vietnamese meal pattern)
        yield Response("🔍 Selecting meals following Vietnamese meal patterns...")
        
        # Breakfast: Vietnamese breakfast dishes (phở, bánh mì, bún, hủ tiếu, etc.)
        breakfast = _select_meal_by_strategy(
            recipes, "highest_carb", 
            preferred_meal_type="breakfast",
            dish_category="breakfast"
        )
        if not breakfast:
            # Fallback: try any breakfast-type dish
            breakfast = _select_meal_by_strategy(
                recipes, "highest_carb", preferred_meal_type="breakfast"
            )
        if not breakfast:
            yield Error("Could not select breakfast meal. Need Vietnamese breakfast dishes (phở, bánh mì, bún, etc.)")
            return
        
        # Lunch: Rice + Main dish + Vegetable + Fruit (Vietnamese lunch pattern)
        excluded = [breakfast]
        lunch_rice = _select_meal_by_strategy(
            recipes, "highest_carb", exclude=excluded, 
            preferred_meal_type="lunch", dish_category="rice"
        )
        if not lunch_rice:
            # Fallback: any high-carb dish for rice
            lunch_rice = _select_meal_by_strategy(
                recipes, "highest_carb", exclude=excluded, preferred_meal_type="lunch"
            )
        
        if lunch_rice:
            excluded.append(lunch_rice)
        lunch_main = _select_meal_by_strategy(
            recipes, "highest_protein", exclude=excluded,
            preferred_meal_type="lunch", dish_category="main"
        )
        if not lunch_main:
            # Fallback: any protein-rich dish
            lunch_main = _select_meal_by_strategy(
                recipes, "highest_protein", exclude=excluded, preferred_meal_type="lunch"
            )
        
        if lunch_main:
            excluded.append(lunch_main)
        lunch_veg = _select_meal_by_strategy(
            recipes, "balanced", exclude=excluded,
            preferred_meal_type="lunch", dish_category="vegetable"
        )
        
        if lunch_veg:
            excluded.append(lunch_veg)
        lunch_fruit = _select_meal_by_strategy(
            recipes, "balanced", exclude=excluded,
            preferred_meal_type="lunch", dish_category="fruit"
        )
        
        # Combine lunch components (at minimum need rice + main)
        if not lunch_rice or not lunch_main:
            yield Error("Could not select lunch meal. Need rice and main dish for Vietnamese lunch.")
            return
        
        # Dinner: Rice + Main dish + Vegetable + Fruit (Vietnamese dinner pattern)
        excluded = [breakfast, lunch_rice, lunch_main]
        if lunch_veg:
            excluded.append(lunch_veg)
        if lunch_fruit:
            excluded.append(lunch_fruit)
        
        dinner_rice = _select_meal_by_strategy(
            recipes, "highest_carb", exclude=excluded,
            preferred_meal_type="dinner", dish_category="rice"
        )
        if not dinner_rice:
            dinner_rice = _select_meal_by_strategy(
                recipes, "highest_carb", exclude=excluded, preferred_meal_type="dinner"
            )
        
        if dinner_rice:
            excluded.append(dinner_rice)
        dinner_main = _select_meal_by_strategy(
            recipes, "highest_protein", exclude=excluded,
            preferred_meal_type="dinner", dish_category="main"
        )
        if not dinner_main:
            dinner_main = _select_meal_by_strategy(
                recipes, "highest_protein", exclude=excluded, preferred_meal_type="dinner"
            )
        
        if dinner_main:
            excluded.append(dinner_main)
        dinner_veg = _select_meal_by_strategy(
            recipes, "balanced", exclude=excluded,
            preferred_meal_type="dinner", dish_category="vegetable"
        )
        
        if dinner_veg:
            excluded.append(dinner_veg)
        dinner_fruit = _select_meal_by_strategy(
            recipes, "balanced", exclude=excluded,
            preferred_meal_type="dinner", dish_category="fruit"
        )
        
        if not dinner_rice or not dinner_main:
            yield Error("Could not select dinner meal. Need rice and main dish for Vietnamese dinner.")
            return

        # Build plan with Vietnamese meal structure
        plan = {
            "breakfast": {"recipe": breakfast, "servings": 1.0, "meal_type": "breakfast"},
            "lunch": {
                "recipe": lunch_rice,  # Primary dish (rice)
                "servings": 1.0,
                "meal_type": "lunch",
                "accompaniments": [
                    {"recipe": lunch_main, "servings": 1.0, "type": "main"},
                ]
            },
            "dinner": {
                "recipe": dinner_rice,  # Primary dish (rice)
                "servings": 1.0,
                "meal_type": "dinner",
                "accompaniments": [
                    {"recipe": dinner_main, "servings": 1.0, "type": "main"},
                ]
            },
        }
        
        # Add vegetables and fruits if available
        if lunch_veg:
            plan["lunch"]["accompaniments"].append({"recipe": lunch_veg, "servings": 1.0, "type": "vegetable"})
        if lunch_fruit:
            plan["lunch"]["accompaniments"].append({"recipe": lunch_fruit, "servings": 1.0, "type": "fruit"})
        if dinner_veg:
            plan["dinner"]["accompaniments"].append({"recipe": dinner_veg, "servings": 1.0, "type": "vegetable"})
        if dinner_fruit:
            plan["dinner"]["accompaniments"].append({"recipe": dinner_fruit, "servings": 1.0, "type": "fruit"})

        for meal_data in plan.values():
            recipe_obj = meal_data.get("recipe", {})
            await _ensure_recipe_macros_cached(
                recipe_obj,
                tree_data=tree_data,
                client_manager=client_manager,
                base_lm=base_lm,
            )
            macros = meal_data.get("recipe", {}).get("macros_per_serving", {})
            if not macros or not macros.get("kcal"):
                yield Error(
                    f"Cannot include {meal_data.get('recipe', {}).get('dish_name', 'a recipe')} because nutrition data is missing."
                )
                return

        # Calculate total macros (including accompaniments for Vietnamese meals)
        total_macros = {"kcal": 0.0, "protein_g": 0.0, "fat_g": 0.0, "carb_g": 0.0}
        for meal_key, meal_data in plan.items():
            # Main recipe
            recipe = meal_data["recipe"]
            servings = meal_data.get("servings", 1.0)
            macros = _get_meal_macros(recipe)
            for k in total_macros:
                total_macros[k] += macros[k] * servings
            
            # Accompaniments (for lunch/dinner Vietnamese meals)
            accompaniments = meal_data.get("accompaniments", [])
            for acc in accompaniments:
                acc_recipe = acc.get("recipe")
                acc_servings = acc.get("servings", 1.0)
                if acc_recipe:
                    acc_macros = _get_meal_macros(acc_recipe)
                    for k in total_macros:
                        total_macros[k] += acc_macros[k] * acc_servings

        # Step 5: Validate
        validation = {"valid": True, "macro_validation": {}, "constraint_validation": {}}
        
        if targets:
            yield Response("✅ Checking nutritional balance...")
            macro_validation = _validate_macro_targets(total_macros, targets, macro_tolerance_percent)
            validation["macro_validation"] = macro_validation
            if not macro_validation["valid"]:
                validation["valid"] = False
                violations = len(macro_validation.get('violations', []))
                warnings = len(macro_validation.get('warnings', []))
                if violations > 0:
                    yield Response(f"⚠️ Macro balance: {violations} deviation(s) from targets")
                if warnings > 0:
                    yield Response(f"ℹ️ {warnings} minor deviation(s) detected")
            else:
                yield Response("✅ All macros within target range")
        
        if filters_metadata:
            yield Response("✅ Verifying dietary constraints...")
            diet_types = filters_metadata.get("diet_types", [])
            exclude_allergens = filters_metadata.get("exclude_allergens", [])
            constraint_validation = _validate_constraints(
                {"meals": plan},
                diet_types if diet_types else None,
                exclude_allergens if exclude_allergens else None,
            )
            validation["constraint_validation"] = constraint_validation
            if not constraint_validation["valid"]:
                validation["valid"] = False
                violations = len(constraint_validation.get('violations', []))
                yield Response(f"⚠️ {violations} constraint violation(s) found")
            else:
                yield Response("✅ All dietary constraints satisfied")

        plan_output = {
            "plan_type": "day",
            "meals": plan,
            "total_macros": total_macros,
            "validation": validation,
            "created_at": datetime.utcnow().isoformat(),
        }
        if plan_id:
            plan_output["plan_id"] = plan_id
        if start_date:
            plan_output["start_date"] = start_date

        if user_id:
            plan_output = sync_plan_to_weaviate(
                plan_output,
                user_id=user_id,
                client_manager=client_manager,
                start_date=plan_output.get("start_date"),
            )
            yield Response(f"💾 Plan saved (ID: {plan_output.get('plan_id', 'N/A')})")
        else:
            yield Response("ℹ️ Plan stored in memory (create profile to save permanently)")

        # Stream response first for immediate feedback
        status_icon = "✅" if validation["valid"] else "⚠️"
        yield Response(
            f"{status_icon} Daily meal plan ready! "
            f"Total: {total_macros['kcal']:.0f} kcal | "
            f"{total_macros['protein_g']:.0f}g protein | "
            f"{total_macros['fat_g']:.0f}g fat | "
            f"{total_macros['carb_g']:.0f}g carbs"
        )
        
        # Then yield Result for data consistency
        # Use "meal_plan" payload_type for explicit frontend detection
        yield Result(
            name="plan",
            objects=[plan_output],
            metadata={
                "plan_type": "day",
                "meals_count": 3,
                "valid": validation["valid"],
                "macro_violations": len(validation.get("macro_validation", {}).get("violations", [])),
                "constraint_violations": len(validation.get("constraint_validation", {}).get("violations", [])),
                "plan_id": plan_output.get("plan_id"),
            },
            payload_type="meal_plan",
            display=True,
        )
        _clear_missing_macro_state(tree_data)

    except ValueError as e:
        error_msg = f"Invalid input: {str(e)}"
        logging.error(f"plan_day_e2e_tool: {error_msg}", exc_info=True)
        yield Error(error_msg)
        return
    except Exception as e:
        error_msg = f"plan_day_e2e_tool failed: {str(e)}"
        logging.error(f"plan_day_e2e_tool: {error_msg}", exc_info=True)
        yield Error(error_msg)
        return


