from typing import AsyncGenerator, Dict, Any, List
import logging
from datetime import datetime, timedelta
from collections import Counter

from elysia.tree.objects import TreeData
from elysia.objects import Result, Error, Response
from elysia.util.client import ClientManager
from elysia import tool

from MealAgent.tools.utils.planning_helpers import (
    _get_meal_macros,
    _validate_macro_targets,
    sync_plan_to_weaviate,
)


def _select_meal_by_strategy(
    recipes: List[Dict[str, Any]], 
    strategy: str, 
    exclude: List[Dict[str, Any]] | None = None,
    used_recipe_ids: set[str] | None = None
) -> Dict[str, Any] | None:
    """Select recipe based on strategy, avoiding excluded and recently used recipes."""
    if not recipes:
        return None
    
    exclude_ids = {r.get("food_id") for r in (exclude or []) if r.get("food_id")}
    if used_recipe_ids:
        exclude_ids.update(used_recipe_ids)
    
    candidates = [r for r in recipes if r.get("food_id") not in exclude_ids]
    if not candidates:
        # If all recipes are excluded, allow reuse but prefer less recently used
        candidates = recipes
    
    if strategy == "highest_carb":
        candidates.sort(key=lambda r: _get_meal_macros(r).get("carb_g", 0.0), reverse=True)
    elif strategy == "highest_protein":
        candidates.sort(key=lambda r: _get_meal_macros(r).get("protein_g", 0.0), reverse=True)
    elif strategy == "balanced":
        candidates.sort(key=lambda r: r.get("fit_score", 0.0), reverse=True)
    
    return candidates[0] if candidates else None


def _validate_constraints_weekly(
    plan: Dict[str, Any],
    diet_types: List[str] | None = None,
    exclude_allergens: List[str] | None = None,
) -> Dict[str, Any]:
    """Validate that weekly plan meals respect diet/allergen constraints."""
    violations = []

    # Iterate through all days and meals
    for day_key, day_data in plan.get("days", {}).items():
        for meal_key, meal_data in day_data.get("meals", {}).items():
            recipe = meal_data.get("recipe", {})
            recipe_id = recipe.get("food_id", "")

            # Check diet type (if Recipe has diet_type field)
            if diet_types:
                recipe_diet = recipe.get("diet_type")
                if recipe_diet:
                    recipe_diets = [recipe_diet] if isinstance(recipe_diet, str) else recipe_diet
                    if not any(dt in recipe_diets for dt in diet_types):
                        violations.append({
                            "day": day_key,
                            "meal": meal_key,
                            "recipe_id": recipe_id,
                            "type": "diet_mismatch",
                            "expected": diet_types,
                            "actual": recipe_diets,
                        })

            # Check allergens (if Recipe has allergens field)
            if exclude_allergens:
                recipe_allergens = recipe.get("allergens", [])
                if recipe_allergens:
                    overlap = set(recipe_allergens) & set(exclude_allergens)
                    if overlap:
                        violations.append({
                            "day": day_key,
                            "meal": meal_key,
                            "recipe_id": recipe_id,
                            "type": "allergen_violation",
                            "forbidden_allergens": list(overlap),
                        })

    return {
        "valid": len(violations) == 0,
        "violations": violations,
    }


def _calculate_variety_score(plan: Dict[str, Any]) -> float:
    """
    Calculate variety score (0-100, higher is better).
    
    Score based on:
    - Number of unique recipes
    - Repetition penalty
    - Ingredient diversity
    """
    recipe_counts = Counter()
    
    for day_data in plan.get("days", {}).values():
        for meal_data in day_data.get("meals", {}).values():
            recipe = meal_data.get("recipe", {})
            food_id = recipe.get("food_id")
            if food_id:
                recipe_counts[food_id] += 1
    
    if not recipe_counts:
        return 0.0
    
    total_meals = sum(recipe_counts.values())
    unique_recipes = len(recipe_counts)
    
    # Base score: percentage of unique recipes
    uniqueness_ratio = unique_recipes / total_meals if total_meals > 0 else 0.0
    
    # Repetition penalty
    repetition_penalty = 0.0
    for count in recipe_counts.values():
        if count > 1:
            repetition_penalty += (count - 1) * 0.1
    
    max_penalty = (total_meals - unique_recipes) * 0.1
    penalty_ratio = repetition_penalty / max_penalty if max_penalty > 0 else 0.0
    
    # Ingredient diversity
    all_ingredients = set()
    for day_data in plan.get("days", {}).values():
        for meal_data in day_data.get("meals", {}).values():
            recipe = meal_data.get("recipe", {})
            ingredients = recipe.get("ingredients", [])
            for ing in ingredients:
                if isinstance(ing, str):
                    all_ingredients.add(ing.lower().strip())
                elif isinstance(ing, dict):
                    all_ingredients.add(str(ing.get("name", "")).lower().strip())
    
    ingredient_diversity = min(1.0, len(all_ingredients) / (total_meals * 3))
    
    # Composite score
    variety_score = (
        uniqueness_ratio * 0.5 +
        (1.0 - penalty_ratio) * 0.3 +
        ingredient_diversity * 0.2
    ) * 100.0
    
    return max(0.0, min(100.0, variety_score))


@tool
async def plan_week_e2e_tool(
    tree_data: TreeData,
    client_manager: ClientManager,
    query_text: str = "",
    start_date: str | None = None,
    macro_tolerance_percent: float = 0.15,
    min_variety_score: float = 50.0,
    user_id: str | None = None,
    plan_id: str | None = None,
    **kwargs,
) -> AsyncGenerator[Result | Response | Error, None]:
    """
    End-to-end weekly planning: resolve targets → search → rank → assemble → validate → enforce variety.
    
    This tool orchestrates the full weekly planning workflow:
    1. Resolve targets (from profile or query override)
    2. Read constraints filters (from constraints_guard_tool)
    3. Read ranked recipes (from search_and_rank_tool)
    4. Assemble 21-meal plan (7 days × 3 meals) with variety enforcement
    5. Validate constraints and macros
    6. Calculate variety score
    
    Environment reads:
      - macro_calc_tool.targets - for macro validation
      - constraints_guard_tool.filters - for constraint validation
      - search_and_rank_tool.topk - ranked recipes
    Environment writes:
      - plan_week_e2e_tool.plan: { plan_type: "week", days: {...}, total_macros: {...}, validation: {...}, variety_score: float }
    
    Decision hints:
      - If plan_week_e2e_tool.plan is present, a weekly meal plan has been assembled successfully.
      - Check plan.validation.valid to see if plan meets targets and constraints.
      - Check plan.variety_score to see variety quality (>=70 is good).
    """
    logging.info("plan_week_e2e_tool: start")
    yield Response("Planning weekly meals (21 meals over 7 days)...")
    
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
            yield Response(f"Using targets: {targets.get('tdee_kcal', 0):.0f} kcal/day")
        else:
            yield Response("No targets found; plan will be assembled without validation")
        
        # Step 2: Read constraints filters (for validation)
        filters_results = tree_data.environment.find("constraints_guard_tool", "filters")
        filters_metadata: Dict[str, Any] | None = None
        if filters_results and filters_results[0]["objects"]:
            filters_metadata = filters_results[0].get("metadata") or {}
            yield Response("Constraints filters found")
        else:
            yield Response("No constraints filters found; plan will be assembled without constraint validation")
        
        # Step 3: Read ranked recipes
        sr = tree_data.environment.find("search_and_rank_tool", "topk")
        if not sr or not sr[0]["objects"]:
            yield Error("No ranked items available. Run search_and_rank_tool first.")
            return
        recipes = sr[0]["objects"]
        
        if len(recipes) < 7:
            yield Response(f"Warning: Only {len(recipes)} recipes available. Some recipes will be reused for 21 meals.")
        
        # Check for missing macros
        missing_macros = [
            r for r in recipes
            if not r.get("macros_per_serving") or not isinstance(r.get("macros_per_serving"), dict)
            or not r.get("macros_per_serving", {}).get("kcal")
        ]
        if missing_macros:
            logging.warning(f"plan_week_e2e_tool: {len(missing_macros)} recipes missing macros_per_serving")
            yield Response(f"Warning: {len(missing_macros)} recipes missing macros. Consider running calculate_recipe_macros_tool for accurate planning.")
        
        # Step 4: Parse start_date or use today
        if start_date:
            try:
                date_str = start_date.replace("Z", "+00:00")
                try:
                    start = datetime.fromisoformat(date_str)
                except ValueError:
                    try:
                        start = datetime.fromisoformat(start_date)
                    except ValueError:
                        for fmt in ["%Y-%m-%d", "%Y/%m/%d", "%d-%m-%Y", "%d/%m/%Y"]:
                            try:
                                start = datetime.strptime(start_date, fmt)
                                break
                            except ValueError:
                                continue
                        else:
                            raise ValueError(f"Unsupported date format: {start_date}")
                start = start.replace(hour=0, minute=0, second=0, microsecond=0)
            except (ValueError, AttributeError) as e:
                yield Error(f"Invalid start_date format: {start_date}. Use ISO format (YYYY-MM-DD). Error: {str(e)}")
                return
        else:
            start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        
        # Step 5: Assemble 21-meal plan with variety enforcement
        yield Response("Assembling 21-meal plan with variety enforcement...")
        
        weekly_plan = {}
        total_macros = {"kcal": 0.0, "protein_g": 0.0, "fat_g": 0.0, "carb_g": 0.0}
        used_recipe_ids: set[str] = set()
        used_recipes: List[Dict[str, Any]] = []
        
        for day_index in range(7):
            day_date = start + timedelta(days=day_index)
            day_key = day_date.date().isoformat()
            
            # Get available recipes (prefer unused)
            available_recipes = [r for r in recipes if r.get("food_id") not in used_recipe_ids]
            if not available_recipes:
                # Allow reuse if we've exhausted all recipes
                available_recipes = recipes
            
            # Select meals for this day
            breakfast = _select_meal_by_strategy(available_recipes, "highest_carb", used_recipe_ids=used_recipe_ids)
            if not breakfast:
                breakfast = available_recipes[0] if available_recipes else None
            
            lunch = _select_meal_by_strategy(
                available_recipes, "balanced", 
                exclude=[breakfast] if breakfast else None,
                used_recipe_ids=used_recipe_ids
            )
            if not lunch:
                lunch = _select_meal_by_strategy(
                    available_recipes, "highest_carb", 
                    exclude=[breakfast] if breakfast else None,
                    used_recipe_ids=used_recipe_ids
                )
            if not lunch:
                exclude_ids = {breakfast.get("food_id")} if breakfast else set()
                remaining = [r for r in available_recipes if r.get("food_id") not in exclude_ids]
                lunch = remaining[0] if remaining else breakfast
            
            dinner = _select_meal_by_strategy(
                available_recipes, "highest_protein", 
                exclude=[breakfast, lunch] if breakfast and lunch else [],
                used_recipe_ids=used_recipe_ids
            )
            if not dinner:
                exclude_ids = {r.get("food_id") for r in [breakfast, lunch] if r}
                remaining = [r for r in available_recipes if r.get("food_id") not in exclude_ids]
                dinner = remaining[0] if remaining else breakfast
            
            if not breakfast or not lunch or not dinner:
                yield Error(f"Could not assemble meals for day {day_index + 1}")
                return
            
            # Track used recipes
            for meal in [breakfast, lunch, dinner]:
                if meal and meal.get("food_id"):
                    used_recipe_ids.add(meal.get("food_id"))
                    used_recipes.append(meal)
            
            # Build day plan
            day_plan = {
                "breakfast": {"recipe": breakfast, "servings": 1.0, "meal_type": "breakfast"},
                "lunch": {"recipe": lunch, "servings": 1.0, "meal_type": "lunch"},
                "dinner": {"recipe": dinner, "servings": 1.0, "meal_type": "dinner"},
            }
            
            # Calculate day macros
            day_macros = {"kcal": 0.0, "protein_g": 0.0, "fat_g": 0.0, "carb_g": 0.0}
            for meal_data in day_plan.values():
                recipe = meal_data["recipe"]
                servings = meal_data["servings"]
                macros = _get_meal_macros(recipe)
                for key in day_macros:
                    day_macros[key] += macros[key] * servings
                    total_macros[key] += macros[key] * servings
            
            weekly_plan[day_key] = {
                "day_index": day_index,
                "date": day_key,
                "meals": day_plan,
                "total_macros": day_macros,
            }
        
        # Calculate average daily macros
        average_daily_macros = {
            "kcal": total_macros["kcal"] / 7.0,
            "protein_g": total_macros["protein_g"] / 7.0,
            "fat_g": total_macros["fat_g"] / 7.0,
            "carb_g": total_macros["carb_g"] / 7.0,
        }
        
        # Step 6: Calculate variety score
        plan_for_variety = {
            "plan_type": "week",
            "days": weekly_plan,
        }
        variety_score = _calculate_variety_score(plan_for_variety)
        
        # Step 7: Validate
        validation = {"valid": True, "macro_validation": {}, "constraint_validation": {}, "variety_validation": {}}
        
        if targets:
            yield Response("Validating weekly macro balance...")
            # Validate against weekly targets (7x daily targets)
            weekly_targets = {
                "tdee_kcal": targets.get("tdee_kcal", 2000) * 7.0,
                "protein_g": targets.get("protein_g", 150) * 7.0,
                "fat_g": targets.get("fat_g", 67) * 7.0,
                "carb_g": targets.get("carb_g", 200) * 7.0,
            }
            macro_validation = _validate_macro_targets(total_macros, weekly_targets, macro_tolerance_percent)
            validation["macro_validation"] = macro_validation
            if not macro_validation["valid"]:
                validation["valid"] = False
                yield Response(f"Macro validation: {len(macro_validation['violations'])} violations, {len(macro_validation['warnings'])} warnings")
            else:
                yield Response("Macro validation passed")
        
        if filters_metadata:
            yield Response("Validating constraints...")
            diet_types = filters_metadata.get("diet_types", [])
            exclude_allergens = filters_metadata.get("exclude_allergens", [])
            constraint_validation = _validate_constraints_weekly(
                {"days": weekly_plan},
                diet_types if diet_types else None,
                exclude_allergens if exclude_allergens else None,
            )
            validation["constraint_validation"] = constraint_validation
            if not constraint_validation["valid"]:
                validation["valid"] = False
                yield Response(f"Constraint validation: {len(constraint_validation['violations'])} violations")
            else:
                yield Response("Constraint validation passed")
        
        # Variety validation
        variety_validation = {
            "valid": variety_score >= min_variety_score,
            "score": variety_score,
            "min_required": min_variety_score,
        }
        validation["variety_validation"] = variety_validation
        if not variety_validation["valid"]:
            validation["valid"] = False
            yield Response(f"Variety validation: Score {variety_score:.1f} below minimum {min_variety_score:.1f}")
        else:
            yield Response(f"Variety validation passed: Score {variety_score:.1f}/100")
        
        plan_output = {
            "plan_type": "week",
            "start_date": start.date().isoformat(),
            "days": weekly_plan,
            "total_macros": total_macros,
            "average_daily_macros": average_daily_macros,
            "validation": validation,
            "variety_score": variety_score,
            "created_at": datetime.now().isoformat(),
        }
        if plan_id:
            plan_output["plan_id"] = plan_id

        if user_id:
            plan_output = sync_plan_to_weaviate(
                plan_output,
                user_id=user_id,
                client_manager=client_manager,
                start_date=plan_output["start_date"],
            )
            yield Response(f"Persisted weekly plan {plan_output.get('plan_id')} for user {user_id}")
        else:
            yield Response("User ID missing – weekly plan stored in memory only.")
        
        # Stream response first for immediate feedback
        status_msg = "✓" if validation["valid"] else "⚠"
        yield Response(
            f"{status_msg} Weekly plan assembled: {total_macros['kcal']:.0f} kcal total | "
            f"{average_daily_macros['kcal']:.0f} kcal/day avg | Variety: {variety_score:.1f}/100"
        )
        
        # Then yield Result for data consistency
        yield Result(
            name="plan",
            objects=[plan_output],
            metadata={
                "plan_type": "week",
                "meals_count": 21,
                "days_count": 7,
                "valid": validation["valid"],
                "variety_score": variety_score,
                "macro_violations": len(validation.get("macro_validation", {}).get("violations", [])),
                "constraint_violations": len(validation.get("constraint_validation", {}).get("violations", [])),
                "plan_id": plan_output.get("plan_id"),
            },
            payload_type="generic",
            display=True,
        )
    
    except ValueError as e:
        error_msg = f"Invalid input: {str(e)}"
        logging.error(f"plan_week_e2e_tool: {error_msg}", exc_info=True)
        yield Error(error_msg)
        return
    except Exception as e:
        error_msg = f"plan_week_e2e_tool failed: {str(e)}"
        logging.error(f"plan_week_e2e_tool: {error_msg}", exc_info=True)
        yield Error(error_msg)
        return

