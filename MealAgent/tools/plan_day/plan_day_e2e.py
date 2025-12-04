from typing import AsyncGenerator, Dict, Any, List
import logging
from datetime import datetime, timedelta, timezone

from elysia.tree.objects import TreeData
from elysia.objects import Result, Error, Response
from elysia.util.client import ClientManager
from elysia import tool

from MealAgent.tools.utils.planning_helpers import (
    _get_meal_macros,
    _validate_macro_targets,
    _validate_constraints,
    sync_plan_to_weaviate,
    _calculate_plan_micronutrients,
    ensure_rfc3339_datetime,
)
from MealAgent.tools.nutrition.calculate_recipe_macros import calculate_recipe_macros_tool
from MealAgent.utils.nutrition import build_default_macro_targets
from MealAgent.tools.utils.profile_targets import (
    ensure_macro_targets,
    ensure_profile_loaded,
    resolve_user_id,
)


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
        # Breakfast typically lighter (25% of daily)
        meal_targets = {k: v * 0.75 for k, v in meal_targets.items()}
    elif meal_type in ["lunch", "dinner"]:
        # Lunch/dinner typically heavier (35-40% of daily)
        meal_targets = {k: v * 1.1 for k, v in meal_targets.items()}
    
    # Calculate fit score with balanced nutrition weights (not just kcal)
    # Weights: protein (30%), carbs (25%), fat (20%), kcal (25%) - prioritize protein and carbs
    macro_weights = {
        "protein_g": 0.30,  # Highest priority - essential for muscle/health
        "carb_g": 0.25,     # High priority - energy source
        "kcal": 0.25,       # Important but not the only factor
        "fat_g": 0.20,      # Important but lower priority
    }
    
    weighted_scores = []
    for macro in ["kcal", "protein_g", "fat_g", "carb_g"]:
        recipe_val = recipe_macros.get(macro, 0.0)
        target_val = meal_targets.get(macro, 1.0)
        weight = macro_weights.get(macro, 0.25)
        
        if target_val > 0:
            ratio = recipe_val / target_val
            # Best fit is when ratio is close to 1.0 (within 0.7-1.3 range)
            if 0.7 <= ratio <= 1.3:
                score = 100.0 - abs(ratio - 1.0) * 50.0  # Max score when ratio = 1.0
            elif 0.5 <= ratio < 0.7 or 1.3 < ratio <= 1.5:
                score = 60.0 - abs(ratio - 1.0) * 20.0  # Medium score
            else:
                score = max(0.0, 30.0 - abs(ratio - 1.0) * 10.0)  # Low score
            
            # Penalize severely if protein is too low (critical for nutrition)
            if macro == "protein_g" and ratio < 0.5:
                score *= 0.5  # Heavy penalty for low protein
            
            weighted_scores.append(score * weight)
        else:
            weighted_scores.append(0.0)
    
    # Sum weighted scores (not average) to emphasize balanced nutrition
    total_fit = sum(weighted_scores) / sum(macro_weights.values()) if weighted_scores else 0.0
    
    # Combine with original fit_score if available (lower weight on original)
    original_fit = recipe.get("fit_score", 50.0)
    return (total_fit * 0.8) + (original_fit * 0.2)


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
    
    Args:
        recipes: List of recipe candidates
        strategy: Selection strategy (highest_carb, highest_protein, balanced, macro_fit)
        exclude: Recipes to exclude
        used_recipe_ids: Recently used recipe IDs to avoid for variety
        preferred_meal_type: Preferred meal type (breakfast/lunch/dinner)
        dish_category: Specific dish category (rice/main/vegetable/fruit/breakfast)
        target_macros: Target macros for better selection (optional)
    """
    if not recipes:
        return None
    exclude_ids = {r.get("food_id") for r in (exclude or []) if r.get("food_id")}
    if used_recipe_ids:
        exclude_ids.update(str(rid) for rid in used_recipe_ids)
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
        typed_candidates = [r for r in candidates if _matches_meal_slot(r, preferred_meal_type)]
        if typed_candidates:
            candidates = typed_candidates

    # Apply strategy with improved macro-aware selection
    if strategy == "highest_carb":
        candidates.sort(key=lambda r: _get_meal_macros(r).get("carb_g", 0.0), reverse=True)
    elif strategy == "highest_protein":
        candidates.sort(key=lambda r: _get_meal_macros(r).get("protein_g", 0.0), reverse=True)
    elif strategy == "macro_fit" and target_macros:
        # New strategy: Select based on macro fit score
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
    complex_lm=None,
    query_text: str = "",
    collection_name: str = "Recipe",
    macro_tolerance_percent: float = 0.15,
    user_id: str | None = None,
    plan_id: str | None = None,
    start_date: str | None = None,
    **kwargs,
) -> AsyncGenerator[Result | Response | Error, None]:
    """
    End-to-end **daily planner**: consume ranked recipes and nutritional targets to build a 3-meal plan.

    Environment contract:
      Reads
        • `macro_calc_tool.targets` – individualized macro goals (TDEE-based).
        • `constraints_guard_tool.filters` (optional) – used only for validation/explanation, not retrieval.
        • `search_and_rank_tool.topk` – ranked candidate recipes (ideally with `macros_per_serving`).
      Writes
        • `plan_day_e2e_tool.plan`
            - canonical day-plan payload used by the UI and downstream tools.
        • `plan_day_e2e_tool.missing_macros`
            - list of `recipe_ids` that blocked planning because macros were missing.

    Behaviour:
      • Does **not** own profile CRUD; it expects profile/targets/search results to be present (or will fall back to defaults).
      • When `missing_macros` is non-empty, planning still returns a best-effort plan but signals that nutrition tools
        (e.g. `calculate_recipe_macros_tool`) should be run before trusting macro accuracy.

    Decision hints:
      • Use this tool when the user asks for a **daily meal plan** (e.g. “Gợi ý bữa ăn ngày hôm nay cho tôi”),
        not just a list of recipes.
      • Presence of `plan_day_e2e_tool.plan` with `metadata.valid=True` means planning succeeded.
      • Non-empty `plan_day_e2e_tool.missing_macros` tells the agent to prioritize nutrition backfill on subsequent runs.
    """
    logging.info("plan_day_e2e_tool: start")
    yield Response("🍽️ Planning your daily meals (breakfast, lunch, dinner)...")

    try:
        hidden_store = tree_data.environment.hidden_environment
        resolved_user_id = resolve_user_id(tree_data, user_id)
        if resolved_user_id:
            hidden_store["user_id"] = resolved_user_id
        user_id = resolved_user_id

        profile, profile_loaded = await ensure_profile_loaded(
            tree_data=tree_data,
            client_manager=client_manager,
            user_id=resolved_user_id,
            base_lm=base_lm,
            complex_lm=complex_lm,
            **kwargs,
        )
        if profile_loaded and profile and resolved_user_id:
            yield Response(f"✅ Profile loaded for user {resolved_user_id}")

        # Defer macro target calculation until after we have a candidate recipe list.
        # This aligns the execution flow with:
        #   1) Fetch recipes from Weaviate
        #   2) Then assemble a plan that respects the user's nutritional targets.
        targets: Dict[str, Any] | None = None

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

        # Step 3: Read ranked recipes or auto-search if not available
        sr = tree_data.environment.find("search_and_rank_tool", "topk")
        recipes: list[Dict[str, Any]] = []
        if sr:
            # Prefer the most recent non-empty result
            for entry in reversed(sr):
                objs = entry.get("objects") or []
                if objs:
                    recipes = objs
                    break

        if not recipes:
            # Auto-search for recipes if not available
            yield Response("🔍 No recipes found. Searching for recipes automatically...")
            try:
                from MealAgent.tools.search.search_and_rank import search_and_rank_tool
                from MealAgent.tools.constraints.constraints_guard import constraints_guard_tool

                # First, ensure constraints are set up
                constraints_results = tree_data.environment.find("constraints_guard_tool", "filters")
                if not constraints_results or not constraints_results[0]["objects"]:
                    # Set up constraints (empty if no profile)
                    async for result in constraints_guard_tool(
                        tree_data=tree_data,
                        inputs={},
                        base_lm=base_lm,
                        complex_lm=complex_lm,
                        client_manager=client_manager,
                        **kwargs,
                    ):
                        if isinstance(result, Error):
                            logging.warning(
                                "plan_day_e2e_tool: constraints_guard_tool failed: %s",
                                result.message,
                            )
                            break

                # Now search for recipes. Note: internal tool calls do NOT automatically
                # persist Results into the environment, so we must capture them here.
                search_query = query_text if query_text else "Vietnamese recipes"
                auto_recipes: list[Dict[str, Any]] = []
                async for result in search_and_rank_tool(
                    tree_data=tree_data,
                    inputs={},
                    base_lm=base_lm,
                    complex_lm=complex_lm,
                    client_manager=client_manager,
                    query_text=search_query,
                    collection_name=collection_name,
                    limit=50,  # Get more recipes for better selection
                    top_k=30,  # Top 30 for planning
                    **kwargs,
                ):
                    if isinstance(result, Error):
                        yield Error(
                            f"Failed to search for recipes: {result.message}. "
                            "Please try searching manually first."
                        )
                        return
                    if isinstance(result, Response):
                        # Forward progress messages to the user
                        yield result
                    elif isinstance(result, Result) and result.objects:
                        # Capture the ranked recipes from this internal call
                        auto_recipes = list(result.objects)

                # Prefer recipes captured from the internal call; environment may not be updated
                if auto_recipes:
                    recipes = auto_recipes
                else:
                    # Fallback: try reading from environment in case the runtime persisted it
                    sr = tree_data.environment.find("search_and_rank_tool", "topk")
                    recipes = []
                    if sr:
                        for entry in reversed(sr):
                            objs = entry.get("objects") or []
                            if objs:
                                recipes = objs
                                break

                if not recipes:
                    yield Error(
                        "No recipes found after automatic search. "
                        "Please check your search query or try a different query."
                    )
                    return

                yield Response(f"✅ Found {len(recipes)} recipe(s) for planning.")
            except Exception as e:  # pragma: no cover - defensive
                logging.error("plan_day_e2e_tool: Auto-search failed: %s", e)
                yield Error(
                    f"Failed to automatically search for recipes: {str(e)}. "
                    "Please search for recipes first using search_and_rank_tool."
                )
                return

        # At this point, `recipes` must be non-empty
        
        # IMPROVED VARIETY: Exclude recently used recipes to avoid repetition
        # Check for recent plans and exclude their recipes
        try:
            client = client_manager.get_client()
            plan_collection = client.collections.get("MealPlan")
            item_collection = client.collections.get("MealPlanItem")
            
            # Get recent plans (last 7 days) for this user
            if user_id:
                from MealAgent.tools.utils.weaviate_filters import build_filters_from_where
                
                recent_date = ensure_rfc3339_datetime(
                    datetime.now(timezone.utc) - timedelta(days=7)
                )
                plan_filter = build_filters_from_where({
                    "operator": "And",
                    "operands": [
                        {"path": ["user_id"], "operator": "Equal", "valueString": user_id},
                        {"path": ["created_at"], "operator": "GreaterThan", "valueDate": recent_date}
                    ]
                })
                
                recent_plans = plan_collection.query.fetch_objects(filters=plan_filter, limit=10)
                if recent_plans.objects:
                    # Collect all recipe IDs from recent plans
                    recent_recipe_ids = set()
                    for plan_obj in recent_plans.objects:
                        plan_id = plan_obj.properties.get("plan_id")
                        if plan_id:
                            item_filter = build_filters_from_where(
                                {"path": ["plan_id"], "operator": "Equal", "valueString": plan_id}
                            )
                            items = item_collection.query.fetch_objects(filters=item_filter, limit=100)
                            for item_obj in items.objects:
                                recipe_id = item_obj.properties.get("recipe_id")
                                if recipe_id:
                                    recent_recipe_ids.add(str(recipe_id))
                    
                    # Filter out recently used recipes (but keep at least 10 recipes)
                    if recent_recipe_ids and len(recipes) > 10:
                        original_count = len(recipes)
                        recipes = [r for r in recipes if str(r.get("food_id", "")) not in recent_recipe_ids]
                        if len(recipes) < 10:
                            # If filtering too aggressively, keep some recent recipes
                            recipes = sr[0]["objects"][:max(10, len(recipes))]
                        if original_count > len(recipes):
                            yield Response(
                                f"🔄 Excluded {original_count - len(recipes)} recently used recipe(s) "
                                f"to ensure variety in your meal plan"
                            )
        except Exception as e:
            logging.debug(f"plan_day_e2e_tool: Could not check recent plans for variety: {e}")
            # Continue with all recipes if check fails

        if len(recipes) < 3:
            yield Error(
                "Not enough recipes found to create a daily plan. "
                "Need at least 3 recipes. Please try a broader search query or relax your constraints."
            )
            return

        # Check for missing macros and auto-calculate if base_lm is available
        # OPTIMIZATION: Only check recipes that will actually be used (first 20 for speed)
        # Calculate macros for recipes that will be used in planning (breakfast, lunch, dinner)
        missing_macros = [
            r for r in recipes[:20]  # Limit check to first 20 recipes for speed
            if not r.get("macros_per_serving") or not isinstance(r.get("macros_per_serving"), dict)
            or not r.get("macros_per_serving", {}).get("kcal")
        ]
        
        if missing_macros:
            effective_base_lm = base_lm or kwargs.get("base_lm")
            if effective_base_lm:
                # Calculate macros for missing recipes, but limit to avoid timeout
                # Priority: Calculate for recipes that will likely be used (first 10-15)
                max_calculate = min(len(missing_macros), 15)  # Limit to 15 to avoid blocking
                
                if max_calculate > 0:
                    yield Response(f"🧮 Calculating nutrition for {max_calculate} recipe(s) to ensure accurate planning...")
                    calculated_count = 0
                    failed_count = 0
                    
                    # Calculate macros one by one with error handling
                    # Limit calculation time to avoid blocking the request
                    for idx, recipe in enumerate(missing_macros[:max_calculate]):
                        food_id = recipe.get("food_id")
                        if food_id:
                            try:
                                # Use async generator with timeout protection
                                macros = await _ensure_recipe_macros_cached(
                                    recipe,
                                    tree_data,
                                    client_manager,
                                    effective_base_lm,
                                )
                                if macros and macros.get("kcal"):
                                    calculated_count += 1
                                    # Update progress every 3 recipes
                                    if (idx + 1) % 3 == 0:
                                        yield Response(f"📊 Calculated {calculated_count}/{max_calculate} recipes...")
                            except Exception as exc:
                                failed_count += 1
                                logging.warning(f"plan_day_e2e_tool: calculate macros failed for {food_id}: {exc}")
                                # Continue with next recipe instead of blocking
                                # Don't yield error here to avoid interrupting the flow
                                continue
                        
                        # Safety check: If we've calculated enough recipes, stop early
                        # This ensures we don't block too long
                        if calculated_count >= 10 and idx >= 10:
                            yield Response(f"📊 Calculated {calculated_count} recipes. Continuing with planning...")
                            break
                    
                    if calculated_count > 0:
                        yield Response(f"✅ Calculated nutrition for {calculated_count} recipe(s).")
                    if failed_count > 0:
                        yield Response(f"⚠️ Failed to calculate nutrition for {failed_count} recipe(s). Continuing with available data...")
                else:
                    yield Response(f"ℹ️ {len(missing_macros)} recipes missing macros. Creating plan with available nutrition data...")
            else:
                # No base_lm available - inform but continue
                yield Response(
                    f"ℹ️ {len(missing_macros)} recipe(s) missing nutrition data. "
                    f"Creating plan with available recipes. Some recipes may have estimated macros."
                )
        
        # Final check: Ensure we have at least some recipes with macros for planning
        recipes_with_macros = [
            r for r in recipes
            if r.get("macros_per_serving") and isinstance(r.get("macros_per_serving"), dict)
            and r.get("macros_per_serving", {}).get("kcal")
        ]
        
        if len(recipes_with_macros) < 3:
            yield Response(
                f"⚠️ Only {len(recipes_with_macros)} recipe(s) have complete nutrition data. "
                f"Plan may use estimated values for some recipes."
            )

        # At this point we have candidate recipes. Now ensure nutritional targets are ready,
        # so the actual plan assembly uses the latest UserProfile-based macros.
        targets, targets_refreshed = await ensure_macro_targets(
            tree_data=tree_data,
            client_manager=client_manager,
            user_id=resolved_user_id,
            base_lm=base_lm,
            complex_lm=complex_lm,
            **kwargs,
        )
        if targets_refreshed and targets:
            yield Response("🧮 Recalculating nutritional targets from your profile...")

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

        # Step 4: Assemble plan (Vietnamese meal pattern) with improved macro-aware selection
        yield Response("🔍 Selecting meals following Vietnamese meal patterns and your nutritional targets...")
        
        # Collect recently used recipe IDs for variety (already done above, but ensure we have the set)
        recent_recipe_ids_set = set()
        try:
            client = client_manager.get_client()
            plan_collection = client.collections.get("MealPlan")
            item_collection = client.collections.get("MealPlanItem")
            
            if user_id:
                from MealAgent.tools.utils.weaviate_filters import build_filters_from_where
                recent_date = ensure_rfc3339_datetime(
                    datetime.now(timezone.utc) - timedelta(days=7)
                )
                plan_filter = build_filters_from_where({
                    "operator": "And",
                    "operands": [
                        {"path": ["user_id"], "operator": "Equal", "valueString": user_id},
                        {"path": ["created_at"], "operator": "GreaterThan", "valueDate": recent_date}
                    ]
                })
                recent_plans = plan_collection.query.fetch_objects(filters=plan_filter, limit=10)
                if recent_plans.objects:
                    for plan_obj in recent_plans.objects:
                        plan_id = plan_obj.properties.get("plan_id")
                        if plan_id:
                            item_filter = build_filters_from_where(
                                {"path": ["plan_id"], "operator": "Equal", "valueString": plan_id}
                            )
                            items = item_collection.query.fetch_objects(filters=item_filter, limit=100)
                            for item_obj in items.objects:
                                recipe_id = item_obj.properties.get("recipe_id")
                                if recipe_id:
                                    recent_recipe_ids_set.add(str(recipe_id))
        except Exception:
            pass  # Continue if check fails
        
        # Use macro_fit strategy if targets available for better quality
        selection_strategy = "macro_fit" if targets else "balanced"
        
        # Breakfast: Vietnamese breakfast dishes (phở, bánh mì, bún, hủ tiếu, etc.)
        breakfast = _select_meal_by_strategy(
            recipes, selection_strategy if targets else "highest_carb", 
            used_recipe_ids=recent_recipe_ids_set,
            preferred_meal_type="breakfast",
            dish_category="breakfast",
            target_macros=targets
        )
        if not breakfast:
            # Fallback: try any breakfast-type dish
            breakfast = _select_meal_by_strategy(
                recipes, "highest_carb", 
                used_recipe_ids=recent_recipe_ids_set,
                preferred_meal_type="breakfast", 
                target_macros=targets
            )
        if not breakfast:
            yield Response("⚠️ No breakfast dish found. Selecting best available option...")
            breakfast = recipes[0] if recipes else None
            if not breakfast:
                yield Response("❌ No recipes available for planning. Please search for recipes first.")
                return
        
        # Lunch: Rice + Main dish + Vegetable + Fruit (Vietnamese lunch pattern)
        excluded = [breakfast]
        lunch_rice = _select_meal_by_strategy(
            recipes, selection_strategy if targets else "highest_carb", 
            exclude=excluded, 
            used_recipe_ids=recent_recipe_ids_set,
            preferred_meal_type="lunch", 
            dish_category="rice", 
            target_macros=targets
        )
        if not lunch_rice:
            # Fallback: any high-carb dish for rice
            lunch_rice = _select_meal_by_strategy(
                recipes, "highest_carb", 
                exclude=excluded, 
                used_recipe_ids=recent_recipe_ids_set,
                preferred_meal_type="lunch", 
                target_macros=targets
            )
        
        if lunch_rice:
            excluded.append(lunch_rice)
        lunch_main = _select_meal_by_strategy(
            recipes, selection_strategy if targets else "highest_protein", 
            exclude=excluded,
            used_recipe_ids=recent_recipe_ids_set,
            preferred_meal_type="lunch", 
            dish_category="main", 
            target_macros=targets
        )
        if not lunch_main:
            # Fallback: any protein-rich dish
            lunch_main = _select_meal_by_strategy(
                recipes, "highest_protein", 
                exclude=excluded, 
                used_recipe_ids=recent_recipe_ids_set,
                preferred_meal_type="lunch", 
                target_macros=targets
            )
        
        if lunch_main:
            excluded.append(lunch_main)
        lunch_veg = _select_meal_by_strategy(
            recipes, "balanced", 
            exclude=excluded,
            used_recipe_ids=recent_recipe_ids_set,
            preferred_meal_type="lunch", 
            dish_category="vegetable", 
            target_macros=targets
        )
        
        if lunch_veg:
            excluded.append(lunch_veg)
        lunch_fruit = _select_meal_by_strategy(
            recipes, "balanced", 
            exclude=excluded,
            used_recipe_ids=recent_recipe_ids_set,
            preferred_meal_type="lunch", 
            dish_category="fruit", 
            target_macros=targets
        )
        
        # Combine lunch components (at minimum need rice + main)
        if not lunch_rice or not lunch_main:
            yield Response("⚠️ Could not find complete lunch components. Using available options...")
            if not lunch_rice:
                # Use any available recipe as rice substitute
                exclude_list = [breakfast]
                if lunch_main:
                    exclude_list.append(lunch_main)
                remaining = [r for r in recipes if r not in exclude_list]
                lunch_rice = remaining[0] if remaining else breakfast
            if not lunch_main:
                # Use any available recipe as main substitute
                remaining = [r for r in recipes if r not in [breakfast, lunch_rice]]
                lunch_main = remaining[0] if remaining else lunch_rice
        
        # Dinner: Rice + Main dish + Vegetable + Fruit (Vietnamese dinner pattern)
        excluded = [breakfast, lunch_rice, lunch_main]
        if lunch_veg:
            excluded.append(lunch_veg)
        if lunch_fruit:
            excluded.append(lunch_fruit)
        
        dinner_rice = _select_meal_by_strategy(
            recipes, selection_strategy if targets else "highest_carb", 
            exclude=excluded,
            used_recipe_ids=recent_recipe_ids_set,
            preferred_meal_type="dinner", 
            dish_category="rice", 
            target_macros=targets
        )
        if not dinner_rice:
            dinner_rice = _select_meal_by_strategy(
                recipes, "highest_carb", 
                exclude=excluded, 
                used_recipe_ids=recent_recipe_ids_set,
                preferred_meal_type="dinner", 
                target_macros=targets
            )
        
        if dinner_rice:
            excluded.append(dinner_rice)
        dinner_main = _select_meal_by_strategy(
            recipes, selection_strategy if targets else "highest_protein", 
            exclude=excluded,
            used_recipe_ids=recent_recipe_ids_set,
            preferred_meal_type="dinner", 
            dish_category="main", 
            target_macros=targets
        )
        if not dinner_main:
            dinner_main = _select_meal_by_strategy(
                recipes, "highest_protein", 
                exclude=excluded, 
                used_recipe_ids=recent_recipe_ids_set,
                preferred_meal_type="dinner", 
                target_macros=targets
            )
        
        if dinner_main:
            excluded.append(dinner_main)
        dinner_veg = _select_meal_by_strategy(
            recipes, "balanced", 
            exclude=excluded,
            used_recipe_ids=recent_recipe_ids_set,
            preferred_meal_type="dinner", 
            dish_category="vegetable", 
            target_macros=targets
        )
        
        if dinner_veg:
            excluded.append(dinner_veg)
        dinner_fruit = _select_meal_by_strategy(
            recipes, "balanced", 
            exclude=excluded,
            used_recipe_ids=recent_recipe_ids_set,
            preferred_meal_type="dinner", 
            dish_category="fruit", 
            target_macros=targets
        )
        
        if not dinner_rice or not dinner_main:
            yield Response("⚠️ Could not find complete dinner components. Using available options...")
            if not dinner_rice:
                # Use any available recipe as rice substitute
                excluded = [breakfast, lunch_rice, lunch_main]
                remaining = [r for r in recipes if r not in excluded]
                dinner_rice = remaining[0] if remaining else lunch_rice
            if not dinner_main:
                # Use any available recipe as main substitute
                excluded = [breakfast, lunch_rice, lunch_main, dinner_rice]
                remaining = [r for r in recipes if r not in excluded]
                dinner_main = remaining[0] if remaining else lunch_main

        # Build plan with Vietnamese meal structure
        # Calculate macros per meal for frontend display
        def _calculate_meal_macros(recipe: Dict[str, Any], servings: float = 1.0) -> Dict[str, float]:
            """Calculate total macros for a recipe with servings."""
            macros = _get_meal_macros(recipe)
            return {
                "kcal": macros["kcal"] * servings,
                "protein_g": macros["protein_g"] * servings,
                "fat_g": macros["fat_g"] * servings,
                "carb_g": macros["carb_g"] * servings,
            }
        
        plan = {
            "breakfast": {
                "recipe": breakfast, 
                "servings": 1.0, 
                "meal_type": "breakfast",
                "macros": _calculate_meal_macros(breakfast, 1.0),
            },
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
        
        # Calculate macros for lunch and dinner (including accompaniments)
        lunch_macros = _calculate_meal_macros(lunch_rice, plan["lunch"]["servings"])
        for acc in plan["lunch"]["accompaniments"]:
            acc_macros = _calculate_meal_macros(acc["recipe"], acc["servings"])
            for k in lunch_macros:
                lunch_macros[k] += acc_macros[k]
        plan["lunch"]["macros"] = lunch_macros
        
        dinner_macros = _calculate_meal_macros(dinner_rice, plan["dinner"]["servings"])
        for acc in plan["dinner"]["accompaniments"]:
            acc_macros = _calculate_meal_macros(acc["recipe"], acc["servings"])
            for k in dinner_macros:
                dinner_macros[k] += acc_macros[k]
        plan["dinner"]["macros"] = dinner_macros

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
                # Try to calculate macros if missing
                recipe_obj = meal_data.get("recipe", {})
                try:
                    await _ensure_recipe_macros_cached(
                        recipe_obj,
                        tree_data=tree_data,
                        client_manager=client_manager,
                        base_lm=base_lm or kwargs.get("base_lm"),
                    )
                    macros = recipe_obj.get("macros_per_serving", {})
                    if not macros or not macros.get("kcal"):
                        yield Response(
                            f"ℹ️ Nutrition data for {recipe_obj.get('dish_name', 'a recipe')} is being calculated..."
                        )
                except Exception as e:
                    logging.warning(f"plan_day_e2e_tool: Could not calculate macros for {recipe_obj.get('food_id')}: {e}")
                    yield Response(
                        f"ℹ️ Using estimated nutrition for {recipe_obj.get('dish_name', 'a recipe')}..."
                    )

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

        # Step 4.5: Optimize servings to better match targets (if targets available)
        if targets and total_macros.get("kcal", 0) > 0:
            target_kcal = targets.get("tdee_kcal", 2000)
            current_kcal = total_macros.get("kcal", 1)
            
            # Calculate adjustment factor (only if deviation is significant)
            if abs(current_kcal - target_kcal) / target_kcal > 0.1:  # More than 10% deviation
                adjustment_factor = target_kcal / current_kcal
                # Limit adjustment to reasonable range (0.8x to 1.2x)
                adjustment_factor = max(0.8, min(1.2, adjustment_factor))
                
                # Apply adjustment to servings (only if adjustment is meaningful)
                if abs(adjustment_factor - 1.0) > 0.05:  # At least 5% change
                    yield Response(f"⚖️ Adjusting servings to better match your targets...")
                    for meal_key, meal_data in plan.items():
                        # Adjust main recipe servings
                        current_servings = meal_data.get("servings", 1.0)
                        meal_data["servings"] = round(current_servings * adjustment_factor, 2)
                        
                        # Adjust accompaniments servings
                        accompaniments = meal_data.get("accompaniments", [])
                        for acc in accompaniments:
                            acc_current = acc.get("servings", 1.0)
                            acc["servings"] = round(acc_current * adjustment_factor, 2)
                    
                    # Recalculate total macros and per-meal macros with adjusted servings
                    total_macros = {"kcal": 0.0, "protein_g": 0.0, "fat_g": 0.0, "carb_g": 0.0}
                    for meal_key, meal_data in plan.items():
                        recipe = meal_data["recipe"]
                        servings = meal_data.get("servings", 1.0)
                        macros = _get_meal_macros(recipe)
                        meal_macros = {k: macros[k] * servings for k in macros}
                        
                        accompaniments = meal_data.get("accompaniments", [])
                        for acc in accompaniments:
                            acc_recipe = acc.get("recipe")
                            acc_servings = acc.get("servings", 1.0)
                            if acc_recipe:
                                acc_macros = _get_meal_macros(acc_recipe)
                                for k in meal_macros:
                                    meal_macros[k] += acc_macros[k] * acc_servings
                        
                        # Update per-meal macros
                        meal_data["macros"] = meal_macros
                        
                        # Add to total
                        for k in total_macros:
                            total_macros[k] += meal_macros[k]

        # Step 5: Validate
        validation = {"valid": True, "macro_validation": {}, "constraint_validation": {}}
        
        if targets:
            yield Response("✅ Checking nutritional balance...")
            macro_validation = _validate_macro_targets(total_macros, targets, macro_tolerance_percent)
            validation["macro_validation"] = macro_validation
            
            # Calculate macro accuracy percentage for better feedback
            macro_accuracy = 100.0
            if total_macros.get("kcal", 0) > 0:
                kcal_deviation = abs(total_macros.get("kcal", 0) - targets.get("tdee_kcal", 2000)) / targets.get("tdee_kcal", 2000)
                macro_accuracy = max(0.0, 100.0 - (kcal_deviation * 100.0))
            
            if not macro_validation["valid"]:
                validation["valid"] = False
                violations = len(macro_validation.get('violations', []))
                warnings = len(macro_validation.get('warnings', []))
                if violations > 0:
                    yield Response(f"⚠️ Macro balance: {violations} deviation(s) from targets (Accuracy: {macro_accuracy:.1f}%)")
                if warnings > 0:
                    yield Response(f"ℹ️ {warnings} minor deviation(s) detected (Accuracy: {macro_accuracy:.1f}%)")
            else:
                yield Response(f"✅ All macros within target range (Accuracy: {macro_accuracy:.1f}%)")
        
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

        # Step 6: Calculate micronutrients
        yield Response("🔬 Calculating micronutrients (vitamins & minerals)...")
        gender = (profile or {}).get("gender")
        
        try:
            micronutrients = await _calculate_plan_micronutrients(
                {"plan_type": "day", "meals": plan},
                client_manager=client_manager,
                gender=gender,
            )
        except Exception as e:
            logging.warning(f"plan_day_e2e_tool: Failed to calculate micronutrients: {e}")
            micronutrients = {
                "total_micros": {},
                "average_daily_micros": {},
                "rdas": {},
                "deficits": {},
                "has_deficits": False,
            }
        
        now_utc = datetime.now(timezone.utc)
        plan_output = {
            "plan_type": "day",
            "meals": plan,
            "total_macros": total_macros,
            "micronutrients": micronutrients,
            "validation": validation,
            "created_at": ensure_rfc3339_datetime(now_utc),
        }
        if plan_id:
            plan_output["plan_id"] = plan_id

        normalized_start_date = (
            ensure_rfc3339_datetime(start_date, date_only=True)
            if start_date
            else ensure_rfc3339_datetime(now_utc, date_only=True)
        )
        plan_output["start_date"] = normalized_start_date

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
                yield Response(f"💊 Micronutrients: {', '.join(micros_summary[:3])}...")
            
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


