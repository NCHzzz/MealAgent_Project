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
    _calculate_plan_micronutrients,
)
from MealAgent.tools.nutrition.calculate_recipe_macros import calculate_recipe_macros_tool
from MealAgent.utils.nutrition import build_default_macro_targets

# Import macro fit calculation from plan_day for consistency
def _calculate_recipe_fit_score(
    recipe: Dict[str, Any],
    target_macros: Dict[str, float] | None = None,
    meal_type: str | None = None,
) -> float:
    """
    Calculate how well a recipe fits the target macros for a specific meal.
    Higher score = better fit.
    """
    if not target_macros:
        return recipe.get("fit_score", 50.0)
    
    recipe_macros = _get_meal_macros(recipe)
    if not recipe_macros.get("kcal"):
        return 0.0
    
    # Calculate per-meal targets (divide daily by 3)
    meal_targets = {
        "kcal": target_macros.get("tdee_kcal", 2000) / 3.0,
        "protein_g": target_macros.get("protein_g", 150) / 3.0,
        "fat_g": target_macros.get("fat_g", 67) / 3.0,
        "carb_g": target_macros.get("carb_g", 200) / 3.0,
    }
    
    # Adjust targets by meal type
    if meal_type == "breakfast":
        meal_targets = {k: v * 0.75 for k, v in meal_targets.items()}
    elif meal_type in ["lunch", "dinner"]:
        meal_targets = {k: v * 1.1 for k, v in meal_targets.items()}
    
    # Calculate fit score
    # Weights: protein (30%), carbs (25%), fat (20%), kcal (25%) - prioritize protein and carbs
    # Consistent with plan_day_e2e_tool for consistency
    macro_weights = {"protein_g": 0.30, "carb_g": 0.25, "kcal": 0.25, "fat_g": 0.20}
    weighted_scores = []
    for macro in ["kcal", "protein_g", "fat_g", "carb_g"]:
        recipe_val = recipe_macros.get(macro, 0.0)
        target_val = meal_targets.get(macro, 1.0)
        weight = macro_weights.get(macro, 0.25)
        
        if target_val > 0:
            ratio = recipe_val / target_val
            if 0.7 <= ratio <= 1.3:
                score = 100.0 - abs(ratio - 1.0) * 50.0
            elif 0.5 <= ratio < 0.7 or 1.3 < ratio <= 1.5:
                score = 60.0 - abs(ratio - 1.0) * 20.0
            else:
                score = max(0.0, 30.0 - abs(ratio - 1.0) * 10.0)
            weighted_scores.append(score * weight)
        else:
            weighted_scores.append(0.0)
    
    total_score = sum(weighted_scores) / sum(macro_weights.values()) if weighted_scores else 0.0
    original_fit = recipe.get("fit_score", 50.0)
    return (total_score * 0.7) + (original_fit * 0.3)


def _record_missing_macro_state(tree_data: TreeData, recipe_ids: List[str]) -> None:
    try:
        tree_data.environment.add_objects(
            "plan_week_e2e_tool",
            "missing_macros",
            [
                {
                    "recipe_ids": recipe_ids,
                    "timestamp": datetime.now().isoformat(),
                }
            ],
        )
    except Exception:
        logging.debug("plan_week_e2e_tool: failed to record missing macros in environment.")


def _clear_missing_macro_state(tree_data: TreeData) -> None:
    """Signal to the tree that nutrition blockers have been resolved."""
    try:
        tree_data.environment.add_objects(
            "plan_week_e2e_tool",
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
        logging.debug("plan_week_e2e_tool: failed to clear missing macros state.")


def _is_vietnamese_breakfast(recipe: Dict[str, Any]) -> bool:
    """Check if recipe is a Vietnamese breakfast dish."""
    dish_name = str(recipe.get("dish_name", "")).lower()
    dish_type = str(recipe.get("dish_type", "")).lower()
    
    breakfast_keywords = [
        "phở", "pho", "banh mi", "bánh mì", "bun bo", "bún bò", 
        "hu tieu", "hủ tiếu", "banh cuon", "bánh cuốn",
        "bun rieu", "bún riêu", "banh canh", "bánh canh",
        "xoi", "xôi", "chao", "cháo", "banh bao", "bánh bao", "cơm tấm", "com tam", "sandwich"
    ]
    
    if any(keyword in dish_name for keyword in breakfast_keywords):
        return True
    if any(keyword in dish_type for keyword in breakfast_keywords):
        return True
    
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


def _select_meal_by_strategy(
    recipes: List[Dict[str, Any]], 
    strategy: str, 
    exclude: List[Dict[str, Any]] | None = None,
    used_recipe_ids: set[str] | None = None,
    preferred_meal_type: str | None = None,
    dish_category: str | None = None,
    target_macros: Dict[str, float] | None = None,
) -> Dict[str, Any] | None:
    """
    Select recipe based on strategy with improved macro-aware selection.
    Prioritizes variety (avoids recently used recipes) while maintaining macro fit.
    """
    if not recipes:
        return None
    
    exclude_ids = {r.get("food_id") for r in (exclude or []) if r.get("food_id")}
    if used_recipe_ids:
        exclude_ids.update(used_recipe_ids)
    
    candidates = [r for r in recipes if r.get("food_id") not in exclude_ids]
    if not candidates:
        candidates = recipes
    
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
        slot = preferred_meal_type.lower()
        typed_candidates = []
        for r in candidates:
            dish_type = r.get("dish_type")
            meal_type = r.get("meal_type")
            
            if isinstance(meal_type, str) and slot in meal_type.lower():
                typed_candidates.append(r)
            elif isinstance(dish_type, str) and slot in dish_type.lower():
                typed_candidates.append(r)
            elif isinstance(dish_type, list) and any(slot in str(e).lower() for e in dish_type):
                typed_candidates.append(r)
            elif slot == "breakfast" or slot == "sáng":
                if _is_vietnamese_breakfast(r):
                    typed_candidates.append(r)
            elif slot in ["lunch", "dinner", "trưa", "tối"]:
                if not _is_vietnamese_breakfast(r):
                    typed_candidates.append(r)
        
        if typed_candidates:
            candidates = typed_candidates
    
    # Apply strategy with macro-aware selection
    if strategy == "highest_carb":
        candidates.sort(key=lambda r: _get_meal_macros(r).get("carb_g", 0.0), reverse=True)
    elif strategy == "highest_protein":
        candidates.sort(key=lambda r: _get_meal_macros(r).get("protein_g", 0.0), reverse=True)
    elif strategy == "macro_fit" and target_macros:
        # Macro-aware selection for better quality
        for r in candidates:
            r["_macro_fit_score"] = _calculate_recipe_fit_score(r, target_macros, preferred_meal_type)
        candidates.sort(key=lambda r: r.get("_macro_fit_score", 0.0), reverse=True)
    elif strategy == "balanced":
        # Use macro_fit if targets available, otherwise use fit_score
        if target_macros:
            for r in candidates:
                r["_macro_fit_score"] = _calculate_recipe_fit_score(r, target_macros, preferred_meal_type)
            candidates.sort(key=lambda r: r.get("_macro_fit_score", r.get("fit_score", 0.0)), reverse=True)
        else:
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
    base_lm=None,
    query_text: str = "",
    start_date: str | None = None,
    macro_tolerance_percent: float = 0.15,
    min_variety_score: float = 50.0,
    user_id: str | None = None,
    plan_id: str | None = None,
    **kwargs,
) -> AsyncGenerator[Result | Response | Error, None]:
    """
    Weekly end-to-end planner: combine ranked recipes and targets into a 7‑day (21‑meal) plan.

    Environment contract:
      Reads
        • `macro_calc_tool.targets` – daily macros (multiplied internally ×7 for validation).
        • `constraints_guard_tool.filters` – guardrail filters.
        • `search_and_rank_tool.topk` – ranked recipes with macros.
      Writes
        • `plan_week_e2e_tool.plan` – normalized weekly payload used by downstream tooling/UI.
        • `plan_week_e2e_tool.missing_macros` – blocking recipe IDs (emptied via `_clear_missing_macro_state` once solved).

    Decision hints:
      • Use this tool when the user asks for a **weekly meal plan** (e.g. “lên thực đơn cả tuần”), not for ad‑hoc recipe lists.
      • `plan_week_e2e_tool.plan` existing implies success; consult metadata.valid & variety_score.
      • Non-empty `missing_macros` tells the agent to call nutrition tools before retrying planning.
    """
    logging.info("plan_week_e2e_tool: start")
    yield Response("📅 Planning your weekly meals (21 meals over 7 days)...")
    
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
                f"📊 Using your daily targets: {targets.get('tdee_kcal', 0):.0f} kcal/day | "
                f"{targets.get('protein_g', 0):.0f}g protein/day"
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
            yield Error(
                "No recipes found. Please search for recipes first using search_and_rank_tool, "
                "or check that your search query and constraints are not too restrictive."
            )
            return
        recipes = sr[0]["objects"]
        
        # IMPROVED VARIETY: Exclude recently used recipes to avoid repetition
        # Check for recent plans and exclude their recipes
        try:
            client = client_manager.get_client()
            plan_collection = client.collections.get("MealPlan")
            item_collection = client.collections.get("MealPlanItem")
            
            # Get recent plans (last 14 days) for this user
            if user_id:
                from MealAgent.tools.utils.weaviate_filters import build_filters_from_where
                
                recent_date = (datetime.now() - timedelta(days=14)).isoformat()
                plan_filter = build_filters_from_where({
                    "operator": "And",
                    "operands": [
                        {"path": ["user_id"], "operator": "Equal", "valueString": user_id},
                        {"path": ["created_at"], "operator": "GreaterThan", "valueDate": recent_date}
                    ]
                })
                
                recent_plans = plan_collection.query.fetch_objects(filters=plan_filter, limit=20)
                if recent_plans.objects:
                    # Collect all recipe IDs from recent plans
                    recent_recipe_ids = set()
                    for plan_obj in recent_plans.objects:
                        plan_id = plan_obj.properties.get("plan_id")
                        if plan_id:
                            item_filter = build_filters_from_where(
                                {"path": ["plan_id"], "operator": "Equal", "valueString": plan_id}
                            )
                            items = item_collection.query.fetch_objects(filters=item_filter, limit=200)
                            for item_obj in items.objects:
                                recipe_id = item_obj.properties.get("recipe_id")
                                if recipe_id:
                                    recent_recipe_ids.add(str(recipe_id))
                    
                    # Filter out recently used recipes (but keep at least 21 recipes for weekly plan)
                    if recent_recipe_ids and len(recipes) > 21:
                        original_count = len(recipes)
                        recipes = [r for r in recipes if str(r.get("food_id", "")) not in recent_recipe_ids]
                        if len(recipes) < 21:
                            # If filtering too aggressively, keep some recent recipes
                            recipes = sr[0]["objects"][:max(21, len(recipes))]
                        if original_count > len(recipes):
                            yield Response(
                                f"🔄 Excluded {original_count - len(recipes)} recently used recipe(s) "
                                f"to ensure variety across your weekly meal plan"
                            )
        except Exception as e:
            logging.debug(f"plan_week_e2e_tool: Could not check recent plans for variety: {e}")
            # Continue with all recipes if check fails
        
        if len(recipes) < 7:
            yield Response(f"⚠️ Warning: Only {len(recipes)} recipes available. Some recipes will be reused for 21 meals.")
        
        # Check for missing macros and auto-calculate if base_lm is available
        # OPTIMIZATION: Only check recipes that will actually be used (limit to reasonable count)
        missing_macros = [
            r for r in recipes[:30]  # Limit check to first 30 recipes for speed
            if not r.get("macros_per_serving") or not isinstance(r.get("macros_per_serving"), dict)
            or not r.get("macros_per_serving", {}).get("kcal")
        ]
        if missing_macros:
            effective_base_lm = base_lm or kwargs.get("base_lm")
            if effective_base_lm and len(missing_macros) <= 15:  # Only auto-calculate if reasonable count
                yield Response(f"🧮 Calculating nutrition for {len(missing_macros)} recipe(s)...")
                calculated_count = 0
                # Process in batches to avoid blocking
                for recipe in missing_macros[:15]:  # Limit to 15 to avoid blocking
                    food_id = recipe.get("food_id")
                    if food_id:
                        try:
                            async for result in calculate_recipe_macros_tool(
                                inputs={"recipe_id": str(food_id)},
                                complex_lm=None,
                                tree_data=tree_data,
                                client_manager=client_manager,
                                base_lm=effective_base_lm,
                            ):
                                if isinstance(result, Result) and result.name == "macros" and result.objects:
                                    recipe["macros_per_serving"] = result.objects[0]
                                    calculated_count += 1
                                    break
                                elif isinstance(result, Error):
                                    break
                        except Exception as exc:
                            logging.warning(
                                f"plan_week_e2e_tool: calculate_recipe_macros_tool failed for {food_id}: {exc}"
                            )
                            continue
                if calculated_count > 0:
                    yield Response(f"✅ Calculated nutrition for {calculated_count} recipe(s).")
                if calculated_count < len(missing_macros):
                    yield Response(f"⚠️ {len(missing_macros) - calculated_count} recipe(s) still missing nutrition data.")
            else:
                if len(missing_macros) > 15:
                    logging.warning(f"plan_week_e2e_tool: {len(missing_macros)} recipes missing macros_per_serving (too many to auto-calculate)")
                    yield Response(f"Warning: {len(missing_macros)} recipes missing macros. Some will be calculated during planning.")
                else:
                    logging.warning(f"plan_week_e2e_tool: {len(missing_macros)} recipes missing macros_per_serving")
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
                f"Cannot build weekly plan because {len(missing_macros)} recipe(s) still lack nutrition data "
                f"(e.g. {missing_ids}). Please calculate macros before planning."
            )
            return

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
        
        # Step 5: Assemble 21-meal plan with Vietnamese meal patterns
        # Use macro_fit strategy if targets available for better quality
        selection_strategy = "macro_fit" if targets else "balanced"
        yield Response("🔍 Selecting 21 meals following Vietnamese meal patterns and your nutritional targets...")
        
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
                available_recipes = recipes
            
            # Breakfast: Vietnamese breakfast dishes
            breakfast = _select_meal_by_strategy(
                available_recipes, selection_strategy if targets else "highest_carb", 
                used_recipe_ids=used_recipe_ids,
                preferred_meal_type="breakfast",
                dish_category="breakfast",
                target_macros=targets
            )
            if not breakfast:
                breakfast = _select_meal_by_strategy(
                    available_recipes, "highest_carb",
                    used_recipe_ids=used_recipe_ids,
                    preferred_meal_type="breakfast",
                    target_macros=targets
                )
            if not breakfast:
                breakfast = available_recipes[0] if available_recipes else None
            
            # Lunch: Rice + Main + Vegetable + Fruit
            excluded = [breakfast] if breakfast else []
            lunch_rice = _select_meal_by_strategy(
                available_recipes, selection_strategy if targets else "highest_carb",
                exclude=excluded, used_recipe_ids=used_recipe_ids,
                preferred_meal_type="lunch", dish_category="rice",
                target_macros=targets
            )
            if not lunch_rice:
                lunch_rice = _select_meal_by_strategy(
                    available_recipes, "highest_carb",
                    exclude=excluded, used_recipe_ids=used_recipe_ids,
                    preferred_meal_type="lunch",
                    target_macros=targets
                )
            
            if lunch_rice:
                excluded.append(lunch_rice)
            lunch_main = _select_meal_by_strategy(
                available_recipes, selection_strategy if targets else "highest_protein",
                exclude=excluded, used_recipe_ids=used_recipe_ids,
                preferred_meal_type="lunch", dish_category="main",
                target_macros=targets
            )
            if not lunch_main:
                lunch_main = _select_meal_by_strategy(
                    available_recipes, "highest_protein",
                    exclude=excluded, used_recipe_ids=used_recipe_ids,
                    preferred_meal_type="lunch",
                    target_macros=targets
                )
            
            if lunch_main:
                excluded.append(lunch_main)
            lunch_veg = _select_meal_by_strategy(
                available_recipes, "balanced",
                exclude=excluded, used_recipe_ids=used_recipe_ids,
                preferred_meal_type="lunch", dish_category="vegetable",
                target_macros=targets
            )
            
            if lunch_veg:
                excluded.append(lunch_veg)
            lunch_fruit = _select_meal_by_strategy(
                available_recipes, "balanced",
                exclude=excluded, used_recipe_ids=used_recipe_ids,
                preferred_meal_type="lunch", dish_category="fruit",
                target_macros=targets
            )
            
            # Fallback: if no rice/main, use any available recipe
            if not lunch_rice or not lunch_main:
                if not lunch_rice:
                    lunch_rice = _select_meal_by_strategy(
                        available_recipes, "highest_carb",
                        exclude=[breakfast] if breakfast else [],
                        used_recipe_ids=used_recipe_ids
                    ) or (available_recipes[0] if available_recipes else None)
                if not lunch_main:
                    exclude_ids = {r.get("food_id") for r in [breakfast, lunch_rice] if r}
                    remaining = [r for r in available_recipes if r.get("food_id") not in exclude_ids]
                    lunch_main = remaining[0] if remaining else lunch_rice
            
            # Dinner: Rice + Main + Vegetable + Fruit
            excluded = [breakfast, lunch_rice, lunch_main] if breakfast and lunch_rice and lunch_main else [breakfast] if breakfast else []
            if lunch_veg:
                excluded.append(lunch_veg)
            if lunch_fruit:
                excluded.append(lunch_fruit)
            
            dinner_rice = _select_meal_by_strategy(
                available_recipes, selection_strategy if targets else "highest_carb",
                exclude=excluded, used_recipe_ids=used_recipe_ids,
                preferred_meal_type="dinner", dish_category="rice",
                target_macros=targets
            )
            if not dinner_rice:
                dinner_rice = _select_meal_by_strategy(
                    available_recipes, "highest_carb",
                    exclude=excluded, used_recipe_ids=used_recipe_ids,
                    preferred_meal_type="dinner",
                    target_macros=targets
                )
            
            if dinner_rice:
                excluded.append(dinner_rice)
            dinner_main = _select_meal_by_strategy(
                available_recipes, selection_strategy if targets else "highest_protein",
                exclude=excluded, used_recipe_ids=used_recipe_ids,
                preferred_meal_type="dinner", dish_category="main",
                target_macros=targets
            )
            if not dinner_main:
                dinner_main = _select_meal_by_strategy(
                    available_recipes, "highest_protein",
                    exclude=excluded, used_recipe_ids=used_recipe_ids,
                    preferred_meal_type="dinner",
                    target_macros=targets
                )
            
            if dinner_main:
                excluded.append(dinner_main)
            dinner_veg = _select_meal_by_strategy(
                available_recipes, "balanced",
                exclude=excluded, used_recipe_ids=used_recipe_ids,
                preferred_meal_type="dinner", dish_category="vegetable",
                target_macros=targets
            )
            
            if dinner_veg:
                excluded.append(dinner_veg)
            dinner_fruit = _select_meal_by_strategy(
                available_recipes, "balanced",
                exclude=excluded, used_recipe_ids=used_recipe_ids,
                preferred_meal_type="dinner", dish_category="fruit",
                target_macros=targets
            )
            
            # Fallback for dinner
            if not dinner_rice or not dinner_main:
                if not dinner_rice:
                    exclude_ids = {r.get("food_id") for r in [breakfast, lunch_rice, lunch_main] if r}
                    remaining = [r for r in available_recipes if r.get("food_id") not in exclude_ids]
                    dinner_rice = remaining[0] if remaining else lunch_rice
                if not dinner_main:
                    exclude_ids = {r.get("food_id") for r in [breakfast, lunch_rice, lunch_main, dinner_rice] if r}
                    remaining = [r for r in available_recipes if r.get("food_id") not in exclude_ids]
                    dinner_main = remaining[0] if remaining else lunch_main
            
            if not breakfast or not lunch_rice or not lunch_main or not dinner_rice or not dinner_main:
                yield Error(f"Could not assemble meals for day {day_index + 1}")
                return
            
            # Track used recipes
            all_meals = [breakfast, lunch_rice, lunch_main, dinner_rice, dinner_main]
            if lunch_veg:
                all_meals.append(lunch_veg)
            if lunch_fruit:
                all_meals.append(lunch_fruit)
            if dinner_veg:
                all_meals.append(dinner_veg)
            if dinner_fruit:
                all_meals.append(dinner_fruit)
            
            for meal in all_meals:
                if meal and meal.get("food_id"):
                    used_recipe_ids.add(meal.get("food_id"))
                    used_recipes.append(meal)
            
            # Build day plan with Vietnamese meal structure
            day_plan = {
                "breakfast": {"recipe": breakfast, "servings": 1.0, "meal_type": "breakfast"},
                "lunch": {
                    "recipe": lunch_rice,
                    "servings": 1.0,
                    "meal_type": "lunch",
                    "accompaniments": [
                        {"recipe": lunch_main, "servings": 1.0, "type": "main"},
                    ]
                },
                "dinner": {
                    "recipe": dinner_rice,
                    "servings": 1.0,
                    "meal_type": "dinner",
                    "accompaniments": [
                        {"recipe": dinner_main, "servings": 1.0, "type": "main"},
                    ]
                },
            }
            
            # Add vegetables and fruits if available
            if lunch_veg:
                day_plan["lunch"]["accompaniments"].append({"recipe": lunch_veg, "servings": 1.0, "type": "vegetable"})
            if lunch_fruit:
                day_plan["lunch"]["accompaniments"].append({"recipe": lunch_fruit, "servings": 1.0, "type": "fruit"})
            if dinner_veg:
                day_plan["dinner"]["accompaniments"].append({"recipe": dinner_veg, "servings": 1.0, "type": "vegetable"})
            if dinner_fruit:
                day_plan["dinner"]["accompaniments"].append({"recipe": dinner_fruit, "servings": 1.0, "type": "fruit"})
            
            # Calculate day macros (including accompaniments)
            day_macros = {"kcal": 0.0, "protein_g": 0.0, "fat_g": 0.0, "carb_g": 0.0}
            for meal_key, meal_data in day_plan.items():
                # Main recipe
                recipe = meal_data["recipe"]
                servings = meal_data.get("servings", 1.0)
                macros = _get_meal_macros(recipe)
                for key in day_macros:
                    day_macros[key] += macros[key] * servings
                    total_macros[key] += macros[key] * servings
                
                # Accompaniments (for lunch/dinner Vietnamese meals)
                accompaniments = meal_data.get("accompaniments", [])
                for acc in accompaniments:
                    acc_recipe = acc.get("recipe")
                    acc_servings = acc.get("servings", 1.0)
                    if acc_recipe:
                        acc_macros = _get_meal_macros(acc_recipe)
                        for key in day_macros:
                            day_macros[key] += acc_macros[key] * acc_servings
                            total_macros[key] += acc_macros[key] * acc_servings
            
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
            yield Response("✅ Checking weekly nutritional balance...")
            # Validate against weekly targets (7x daily targets)
            weekly_targets = {
                "tdee_kcal": targets.get("tdee_kcal", 2000) * 7.0,
                "protein_g": targets.get("protein_g", 150) * 7.0,
                "fat_g": targets.get("fat_g", 67) * 7.0,
                "carb_g": targets.get("carb_g", 200) * 7.0,
            }
            macro_validation = _validate_macro_targets(total_macros, weekly_targets, macro_tolerance_percent)
            validation["macro_validation"] = macro_validation
            
            # Calculate macro accuracy percentage for better feedback
            macro_accuracy = 100.0
            if total_macros.get("kcal", 0) > 0:
                kcal_deviation = abs(total_macros.get("kcal", 0) - weekly_targets.get("tdee_kcal", 14000)) / weekly_targets.get("tdee_kcal", 14000)
                macro_accuracy = max(0.0, 100.0 - (kcal_deviation * 100.0))
            
            if not macro_validation["valid"]:
                validation["valid"] = False
                violations = len(macro_validation.get('violations', []))
                warnings = len(macro_validation.get('warnings', []))
                if violations > 0:
                    yield Response(f"⚠️ Weekly macros: {violations} deviation(s) from targets (Accuracy: {macro_accuracy:.1f}%)")
                if warnings > 0:
                    yield Response(f"ℹ️ {warnings} minor deviation(s) detected (Accuracy: {macro_accuracy:.1f}%)")
            else:
                yield Response(f"✅ Weekly macros within target range (Accuracy: {macro_accuracy:.1f}%)")
        
        if filters_metadata:
            yield Response("✅ Verifying dietary constraints across all meals...")
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
                violations = len(constraint_validation.get('violations', []))
                yield Response(f"⚠️ {violations} constraint violation(s) found")
            else:
                yield Response("✅ All dietary constraints satisfied")
        
        # Variety validation
        variety_validation = {
            "valid": variety_score >= min_variety_score,
            "score": variety_score,
            "min_required": min_variety_score,
        }
        validation["variety_validation"] = variety_validation
        if not variety_validation["valid"]:
            validation["valid"] = False
            yield Response(f"⚠️ Variety score {variety_score:.1f}/100 (minimum: {min_variety_score:.1f})")
        else:
            yield Response(f"✅ Variety score: {variety_score:.1f}/100 (excellent variety!)")
        
        # Step 6: Calculate micronutrients
        yield Response("🔬 Calculating micronutrients (vitamins & minerals)...")
        profile_results = tree_data.environment.find("profile_crud_tool", "profile")
        gender = None
        if profile_results and profile_results[0]["objects"]:
            gender = profile_results[0]["objects"][0].get("gender")
        
        try:
            micronutrients = await _calculate_plan_micronutrients(
                {"plan_type": "week", "days": weekly_plan},
                client_manager=client_manager,
                gender=gender,
            )
        except Exception as e:
            logging.warning(f"plan_week_e2e_tool: Failed to calculate micronutrients: {e}")
            micronutrients = {
                "total_micros": {},
                "average_daily_micros": {},
                "rdas": {},
                "deficits": {},
                "has_deficits": False,
            }
        
        plan_output = {
            "plan_type": "week",
            "start_date": start.date().isoformat(),
            "days": weekly_plan,
            "total_macros": total_macros,
            "average_daily_macros": average_daily_macros,
            "micronutrients": micronutrients,
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
            yield Response(f"💾 Weekly plan saved (ID: {plan_output.get('plan_id', 'N/A')})")
        else:
            yield Response("ℹ️ Plan stored in memory (create profile to save permanently)")
        
        # Stream response first for immediate feedback
        status_icon = "✅" if validation["valid"] else "⚠️"
        yield Response(
            f"{status_icon} Weekly meal plan ready! "
            f"Total: {total_macros['kcal']:.0f} kcal | "
            f"Daily avg: {average_daily_macros['kcal']:.0f} kcal | "
            f"Variety: {variety_score:.1f}/100"
        )
        
        # Show micronutrient summary
        if micronutrients.get("average_daily_micros"):
            micros_summary = []
            avg_micros = micronutrients.get("average_daily_micros", {})
            rdas = micronutrients.get("rdas", {})
            
            # Show key vitamins and minerals
            key_micros = ["vitamin_c_mg", "vitamin_a_rae_ug", "calcium_mg", "iron_mg", "potassium_mg"]
            for key in key_micros:
                if key in avg_micros:
                    value = avg_micros[key]
                    rda = rdas.get(key, 0)
                    if rda > 0:
                        percent = (value / rda) * 100
                        micros_summary.append(f"{key.replace('_', ' ').title()}: {value:.1f} ({percent:.0f}% RDA)")
            
            if micros_summary:
                yield Response(f"💊 Daily avg micronutrients: {', '.join(micros_summary[:3])}...")
            
            # Show deficits if any
            if micronutrients.get("has_deficits"):
                deficits = micronutrients.get("deficits", {})
                deficit_list = []
                for nutrient, data in list(deficits.items())[:3]:
                    nutrient_name = nutrient.replace("_mg", "").replace("_ug", "").replace("_", " ").title()
                    deficit_list.append(f"{nutrient_name} ({data['deficit_percent']:.0f}% below RDA)")
                if deficit_list:
                    yield Response(f"⚠️ Micronutrient gaps: {', '.join(deficit_list)}")
            else:
                yield Response("✅ All key micronutrients meet RDA requirements!")
        
        # Then yield Result for data consistency
        # Use "meal_plan" payload_type for explicit frontend detection
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
            payload_type="meal_plan",
            display=True,
        )
        _clear_missing_macro_state(tree_data)
    
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

