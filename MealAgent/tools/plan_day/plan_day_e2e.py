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


def _matches_meal_slot(recipe: Dict[str, Any], slot: str) -> bool:
    dish_type = recipe.get("dish_type")
    slot = slot.lower()

    if isinstance(dish_type, str):
        return slot in dish_type.lower()
    if isinstance(dish_type, list):
        return any(slot in str(entry).lower() for entry in dish_type)

    # fallback to meal_type field if present
    meal_type = recipe.get("meal_type")
    if isinstance(meal_type, str):
        return slot in meal_type.lower()
    return False


def _select_meal_by_strategy(
    recipes: List[Dict[str, Any]],
    strategy: str,
    exclude: List[Dict[str, Any]] | None = None,
    preferred_meal_type: str | None = None,
) -> Dict[str, Any] | None:
    """
    Select recipe based on strategy (highest_carb, highest_protein, balanced).

    This helper works purely on `Recipe.macros_per_serving` as defined in the
    design doc. It intentionally does **not** try to infer macros directly
    from `FdcFood` by treating `food_id` as an FDC identifier, because:

    - `Recipe.food_id` is an internal recipe identifier (0..N), not an FDC id
    - The only supported path from Recipe → FdcFood is via ingredient-level
      mappings (`ingredient_fdc_map`) computed by `calculate_recipe_macros_tool`
    """
    if not recipes:
        return None
    exclude_ids = {r.get("food_id") for r in (exclude or []) if r.get("food_id")}
    candidates = [r for r in recipes if r.get("food_id") not in exclude_ids]
    if not candidates:
        return None

    if preferred_meal_type:
        typed_candidates = [r for r in candidates if _matches_meal_slot(r, preferred_meal_type)]
        if typed_candidates:
            candidates = typed_candidates

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
            tree_data=tree_data,
            client_manager=client_manager,
            recipe_id=str(food_id),
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
    End-to-end daily planning: resolve targets → search → rank → assemble → validate.
    
    This tool orchestrates the full daily planning workflow:
    1. Resolve targets (from profile or query override)
    2. Read constraints filters (from constraints_guard_tool)
    3. Read ranked recipes (from search_and_rank_tool)
    4. Assemble 3-meal plan
    5. Validate constraints and macros
    
    Environment reads:
      - macro_calc_tool.targets - for macro validation
      - constraints_guard_tool.filters - for constraint validation
      - search_and_rank_tool.topk - ranked recipes
    Environment writes:
      - plan_day_e2e_tool.plan: [{ plan_type: "day", meals: {...}, total_macros: {...}, validation: {...} }]

    Decision hints:
      - If plan_day_e2e_tool.plan is present, a daily meal plan has been assembled successfully.
      - Check plan.validation.valid to see if plan meets targets and constraints.
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
            if kwargs.get("base_lm"):
                yield Response(f"🧮 Calculating nutrition for {len(missing_macros)} recipe(s)...")
                calculated_count = 0
                for recipe in missing_macros:
                    macros = await _ensure_recipe_macros_cached(
                        recipe, tree_data, client_manager, kwargs.get("base_lm")
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

        # Step 4: Assemble plan
        yield Response("🔍 Selecting meals for breakfast, lunch, and dinner...")
        
        breakfast = _select_meal_by_strategy(
            recipes, "highest_carb", preferred_meal_type="breakfast"
        )
        if not breakfast:
            yield Error("Could not select breakfast meal")
            return
        
        lunch = _select_meal_by_strategy(
            recipes, "balanced", exclude=[breakfast], preferred_meal_type="lunch"
        )
        if not lunch:
            # Fallback to second highest carb if balanced selection fails
            lunch = _select_meal_by_strategy(recipes, "highest_carb", exclude=[breakfast])
        if not lunch:
            yield Error("Could not select lunch meal")
            return
        
        dinner = _select_meal_by_strategy(
            recipes, "highest_protein", exclude=[breakfast, lunch], preferred_meal_type="dinner"
        )
        if not dinner:
            # Fallback to any remaining recipe
            exclude_ids = {breakfast.get("food_id"), lunch.get("food_id")}
            remaining = [r for r in recipes if r.get("food_id") not in exclude_ids]
            if remaining:
                dinner = remaining[0]
            else:
                yield Error("Could not select dinner meal")
                return

        plan = {
            "breakfast": {"recipe": breakfast, "servings": 1.0, "meal_type": "breakfast"},
            "lunch": {"recipe": lunch, "servings": 1.0, "meal_type": "lunch"},
            "dinner": {"recipe": dinner, "servings": 1.0, "meal_type": "dinner"},
        }

        for meal_data in plan.values():
            await _ensure_recipe_macros_cached(
                meal_data.get("recipe", {}),
                tree_data=tree_data,
                client_manager=client_manager,
                base_lm=base_lm,
            )

        # Calculate total macros
        total_macros = {"kcal": 0.0, "protein_g": 0.0, "fat_g": 0.0, "carb_g": 0.0}
        for meal_data in plan.values():
            recipe = meal_data["recipe"]
            servings = meal_data["servings"]
            macros = _get_meal_macros(recipe)
            for k in total_macros:
                total_macros[k] += macros[k] * servings

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


