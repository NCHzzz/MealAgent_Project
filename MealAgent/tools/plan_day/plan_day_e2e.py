from typing import AsyncGenerator, Dict, Any, List
import logging
import random
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
from MealAgent.utils.nutrition import build_default_macro_targets
from MealAgent.tools.utils.profile_targets import (
    ensure_macro_targets,
    ensure_profile_loaded,
    resolve_user_id,
)
from MealAgent.tools.utils.weaviate_filters import build_filters_from_where
from MealAgent.tools.utils.recipe_refresh import refresh_recipes, fetch_latest_recipe


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
        "phở", "pho", "bun", "bún", "bun bo", "bún bò", "bun rieu", "bún riêu", "bun cha", "bún chả",
        "hu tieu", "hủ tiếu", "banh mi", "bánh mì", "banh cuon", "bánh cuốn",
        "banh canh", "bánh canh", "banh bao", "bánh bao",
        "xoi", "xôi", "chao", "cháo", "sandwich", "bánh ngọt", "banh ngot", "croissant", "brioche",
        "cơm tấm", "com tam", "xoi man", "xôi mặn", "xoi ngo", "xôi ngô"
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


def _is_noodle_soup(recipe: Dict[str, Any]) -> bool:
    """Check if recipe is a noodle/soup dish (phở, bún, mì, canh)."""
    dish_name = str(recipe.get("dish_name", "")).lower()
    dish_type = str(recipe.get("dish_type", "")).lower()
    noodle_keywords = [
        "phở", "pho", "bún", "bun", "bún bò", "bun bo", "bún riêu", "bun rieu",
        "bún chả", "bun cha", "hủ tiếu", "hu tieu", "mì", "mi ", "miến", "mien",
        "canh", "soup", "cháo", "chao"
    ]
    return any(kw in dish_name or kw in dish_type for kw in noodle_keywords)


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
    require_macros: bool = False,
    min_kcal: float = 30.0,
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
    if require_macros:
        filtered = []
        for r in candidates:
            macros = r.get("macros_per_serving", {})
            if isinstance(macros, dict) and macros.get("kcal", 0) >= min_kcal:
                filtered.append(r)
        if filtered:
            candidates = filtered
    if not candidates:
        candidates = recipes

    # Filter by dish category if specified
    if dish_category:
        if dish_category == "breakfast":
            category_candidates = [r for r in candidates if _is_vietnamese_breakfast(r)]
        elif dish_category == "rice":
            category_candidates = [r for r in candidates if _is_rice_dish(r)]
            if not category_candidates:
                # Fallback to noodle/soup dishes for Vietnamese-style main carb
                category_candidates = [r for r in candidates if _is_noodle_soup(r)]
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
    base_lm=None,  # Not used anymore, kept for compatibility
) -> Dict[str, float] | None:
    """
    Read recipe macros from Weaviate if not already in memory.
    
    IMPORTANT: This function ONLY reads from Weaviate, does NOT calculate macros.
    Macros should be pre-calculated when recipes are added to the database.
    Only use calculate_recipe_macros_tool explicitly for new recipes.
    """
    recipe_id = recipe.get("food_id") or recipe.get("recipe_id") or recipe.get("id")
    macros = recipe.get("macros_per_serving")
    if isinstance(macros, dict) and macros.get("kcal"):
        return macros
    logging.debug(
        "plan_day_e2e_tool: macros missing in-memory for recipe %s, fetching latest",
        recipe_id,
    )

    food_id = recipe.get("food_id") or recipe.get("fdc_id") or recipe.get("recipe_id") or recipe.get("id")
    if not food_id:
        return macros

    # Read from Weaviate to get latest macros (recipes should already have macros)
    try:
        client = client_manager.get_client()
        fresh_recipe = fetch_latest_recipe(
            str(food_id),
            client,
            collection_name="Recipe",
            candidate_fields=["food_id", "recipe_id", "id"],
        )
        if fresh_recipe:
            fresh_macros = fresh_recipe.get("macros_per_serving")
            if fresh_macros and isinstance(fresh_macros, dict) and fresh_macros.get("kcal"):
                # Update recipe object in memory with fresh data from Weaviate
                recipe["macros_per_serving"] = fresh_macros
                # Also sync other fields that might have been updated
                if "ingredient_fdc_map" in fresh_recipe:
                    recipe["ingredient_fdc_map"] = fresh_recipe["ingredient_fdc_map"]
                # Sync meal typing fields if present
                for key in ("dish_name", "dish_type", "meal_type"):
                    if key in fresh_recipe:
                        recipe[key] = fresh_recipe[key]
                return fresh_macros
            logging.debug(
                "plan_day_e2e_tool: fetched recipe %s but macros still missing",
                food_id,
            )
    except Exception as weaviate_exc:
        logging.debug(
            "plan_day_e2e_tool: Failed to read recipe from Weaviate for %s (%s)",
            food_id,
            weaviate_exc,
        )

    # Return whatever is on the recipe (may be None or empty dict)
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
    recent_plan_window_minutes: int = 10,  # for testing; set to 10080 (7 days) in production
    **kwargs,
) -> AsyncGenerator[Result | Response | Error, None]:
    """
    End-to-end **daily planner**: consume ranked recipes and nutritional targets to build a 3-meal plan.

    IMPORTANT: Recipes should have macros pre-calculated in the database.
    This tool only reads macros from Weaviate, it does NOT calculate macros automatically.
    Use `calculate_recipe_macros_tool` explicitly for new recipes that are missing macros.

    Environment contract:
      Reads
        • `macro_calc_tool.targets` – individualized macro goals (TDEE-based).
        • `constraints_guard_tool.filters` (optional) – used only for validation/explanation, not retrieval.
        • `search_and_rank_tool.topk` – ranked candidate recipes (should have `macros_per_serving` pre-calculated).
      Writes
        • `plan_day_e2e_tool.plan`
            - canonical day-plan payload used by the UI and downstream tools.
        • `plan_day_e2e_tool.missing_macros`
            - list of `recipe_ids` that are missing macros (for manual calculation if needed).

    Behaviour:
      • Does **not** own profile CRUD; it expects profile/targets/search results to be present (or will fall back to defaults).
      • Reads recipes from Weaviate to get latest macros (recipes should be pre-processed).
      • When `missing_macros` is non-empty, planning still returns a best-effort plan but warns about missing nutrition data.

    Decision hints:
      • Use this tool when the user asks for a **daily meal plan** (e.g. "Gợi ý bữa ăn ngày hôm nay cho tôi"),
        not just a list of recipes.
      • Presence of `plan_day_e2e_tool.plan` with `metadata.valid=True` means planning succeeded.
      • Non-empty `plan_day_e2e_tool.missing_macros` indicates recipes need macro calculation (run `calculate_recipe_macros_tool`).
    """
    logging.info(
        "plan_day_e2e_tool: start query='%s' collection=%s user_id=%s macro_tol=%.2f recent_window_min=%s",
        (query_text or "").strip(),
        collection_name,
        user_id,
        macro_tolerance_percent,
        recent_plan_window_minutes,
    )
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
        logging.debug(
            "plan_day_e2e_tool: profile_loaded=%s user_id=%s profile_fields=%s",
            profile_loaded,
            resolved_user_id,
            list(profile.keys()) if isinstance(profile, dict) else None,
        )

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
        logging.debug(
            "plan_day_e2e_tool: recipes from search results count=%d query='%s'",
            len(recipes),
            query_text,
        )

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
        
        # IMPROVED VARIETY: Shuffle recipes and exclude recent plans to ensure better variety
        # Shuffle recipes to randomize selection
        random.shuffle(recipes)
        
        # Check for recent plans and exclude their recipes (configurable minutes, default 10 minutes for testing)
        recent_recipe_ids = set()
        try:
            client = client_manager.get_client()
            plan_collection = client.collections.get("MealPlan")
            item_collection = client.collections.get("MealPlanItem")
            
            # Get recent plans within configured window (minutes) for this user
            if user_id:
                window_minutes = max(1, int(recent_plan_window_minutes or 10))
                recent_date = ensure_rfc3339_datetime(
                    datetime.now(timezone.utc) - timedelta(minutes=window_minutes)
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
                    for plan_obj in recent_plans.objects:
                        plan_id = plan_obj.properties.get("plan_id")
                        if plan_id:
                            item_filter = build_filters_from_where(
                                {"path": ["plan_id"], "operator": "Equal", "valueString": plan_id}
                            )
                            items = item_collection.query.fetch_objects(filters=item_filter, limit=50)
                            for item_obj in items.objects:
                                recipe_id = item_obj.properties.get("recipe_id")
                                if recipe_id:
                                    recent_recipe_ids.add(str(recipe_id))
                    
                    # Filter out recently used recipes (but keep at least 20 recipes for better variety)
                    if recent_recipe_ids and len(recipes) > 20:
                        original_count = len(recipes)
                        recipes = [r for r in recipes if str(r.get("food_id", "")) not in recent_recipe_ids]
                        # Shuffle again after filtering
                        random.shuffle(recipes)
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

        # Refresh recipes from Weaviate to ensure we have latest macros
        # Recipes should already have macros pre-calculated in the database
        def _count_missing_macros(items: list[Dict[str, Any]]) -> int:
            return sum(
                1
                for r in items
                if not r.get("macros_per_serving")
                or not isinstance(r.get("macros_per_serving"), dict)
                or not r.get("macros_per_serving", {}).get("kcal")
            )

        missing_before_refresh = _count_missing_macros(recipes)
        try:
            client = client_manager.get_client()
            recipes = refresh_recipes(recipes, client, collection_name="Recipe", hydrate_fields=True)
            missing_after_refresh = _count_missing_macros(recipes)
            missing_ids = [
                str(r.get("food_id") or r.get("recipe_id") or r.get("id"))
                for r in recipes
                if not r.get("macros_per_serving")
                or not isinstance(r.get("macros_per_serving"), dict)
                or not r.get("macros_per_serving", {}).get("kcal")
            ][:5]
            logging.debug(
                "plan_day_e2e_tool: refreshed %d recipes (missing macros before=%d, after=%d, sample_missing=%s)",
                len(recipes),
                missing_before_refresh,
                missing_after_refresh,
                missing_ids or "none",
            )
            logging.debug(
                "plan_day_e2e_tool: recipe sample after refresh %s",
                [
                    (
                        str(r.get("food_id") or r.get("recipe_id") or r.get("id")),
                        (r.get("macros_per_serving") or {}).get("kcal"),
                    )
                    for r in recipes[:5]
                ],
            )
        except Exception as refresh_exc:
            logging.debug(f"Failed to refresh recipes from Weaviate: {refresh_exc}")
            # Continue with existing recipes if refresh fails
        
        # Check for missing macros (should be rare if recipes are pre-processed)
        missing_macros = [
            r for r in recipes
            if not r.get("macros_per_serving") or not isinstance(r.get("macros_per_serving"), dict)
            or not r.get("macros_per_serving", {}).get("kcal")
        ]
        
        if missing_macros:
            missing_ids = [str(r.get("food_id")) for r in missing_macros[:5] if r.get("food_id")]
            _record_missing_macro_state(tree_data, missing_ids)
            yield Response(
                f"⚠️ {len(missing_macros)} recipe(s) missing nutrition data. "
                f"Run calculate_recipe_macros_tool for these recipes if needed. "
                f"Continuing with available recipes..."
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
                f"Please ensure recipes have macros calculated before planning."
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
        
        # Use the recent_recipe_ids set already collected above (or empty set if not collected)
        recent_recipe_ids_set = recent_recipe_ids if 'recent_recipe_ids' in locals() else set()
        
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
            # Fallback: noodle/soup dishes for Vietnamese lunch
            lunch_rice = _select_meal_by_strategy(
                recipes, "highest_carb", 
                exclude=excluded, 
                used_recipe_ids=recent_recipe_ids_set,
                preferred_meal_type="lunch", 
                dish_category="rice",
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
            target_macros=targets,
            require_macros=True,
            min_kcal=50.0,
        )
        if not lunch_main:
            # Fallback: any protein-rich dish
            lunch_main = _select_meal_by_strategy(
                recipes, "highest_protein", 
                exclude=excluded, 
                used_recipe_ids=recent_recipe_ids_set,
                preferred_meal_type="lunch", 
                target_macros=targets,
                require_macros=True,
                min_kcal=50.0,
            )
        
        if lunch_main:
            excluded.append(lunch_main)
        lunch_veg = _select_meal_by_strategy(
            recipes, "balanced", 
            exclude=excluded,
            used_recipe_ids=recent_recipe_ids_set,
            preferred_meal_type="lunch", 
            dish_category="vegetable", 
            target_macros=targets,
            require_macros=True,
            min_kcal=30.0,
        )
        
        if lunch_veg:
            excluded.append(lunch_veg)
        lunch_fruit = _select_meal_by_strategy(
            recipes, "balanced", 
            exclude=excluded,
            used_recipe_ids=recent_recipe_ids_set,
            preferred_meal_type="lunch", 
            dish_category="fruit", 
            target_macros=targets,
            require_macros=True,
            min_kcal=30.0,
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
            # Fallback: noodle/soup dishes for Vietnamese dinner
            dinner_rice = _select_meal_by_strategy(
                recipes, "highest_carb", 
                exclude=excluded, 
                used_recipe_ids=recent_recipe_ids_set,
                preferred_meal_type="dinner", 
                dish_category="rice",
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
            target_macros=targets,
            require_macros=True,
            min_kcal=50.0,
        )
        if not dinner_main:
            dinner_main = _select_meal_by_strategy(
                recipes, "highest_protein", 
                exclude=excluded, 
                used_recipe_ids=recent_recipe_ids_set,
                preferred_meal_type="dinner", 
                target_macros=targets,
                require_macros=True,
                min_kcal=50.0,
            )
        
        if dinner_main:
            excluded.append(dinner_main)
        dinner_veg = _select_meal_by_strategy(
            recipes, "balanced", 
            exclude=excluded,
            used_recipe_ids=recent_recipe_ids_set,
            preferred_meal_type="dinner", 
            dish_category="vegetable", 
            target_macros=targets,
            require_macros=True,
            min_kcal=30.0,
        )
        
        if dinner_veg:
            excluded.append(dinner_veg)
        dinner_fruit = _select_meal_by_strategy(
            recipes, "balanced", 
            exclude=excluded,
            used_recipe_ids=recent_recipe_ids_set,
            preferred_meal_type="dinner", 
            dish_category="fruit", 
            target_macros=targets,
            require_macros=True,
            min_kcal=30.0,
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
        logging.debug(
            "plan_day_e2e_tool: selected dishes breakfast=%s lunch_rice=%s lunch_main=%s lunch_veg=%s lunch_fruit=%s dinner_rice=%s dinner_main=%s dinner_veg=%s dinner_fruit=%s",
            breakfast.get("dish_name") if breakfast else None,
            lunch_rice.get("dish_name") if lunch_rice else None,
            lunch_main.get("dish_name") if lunch_main else None,
            lunch_veg.get("dish_name") if lunch_veg else None,
            lunch_fruit.get("dish_name") if lunch_fruit else None,
            dinner_rice.get("dish_name") if dinner_rice else None,
            dinner_main.get("dish_name") if dinner_main else None,
            dinner_veg.get("dish_name") if dinner_veg else None,
            dinner_fruit.get("dish_name") if dinner_fruit else None,
        )
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
        
        # Add vegetables and fruits if available (only if they have macros)
        if lunch_veg:
            lunch_veg_macros = _get_meal_macros(lunch_veg)
            if lunch_veg_macros.get("kcal", 0) > 0:  # Only add if has macros
                plan["lunch"]["accompaniments"].append({
                    "recipe": lunch_veg,
                    "servings": 1.0,
                    "type": "vegetable",
                    "macros": _calculate_meal_macros(lunch_veg, 1.0),
                })
        if lunch_fruit:
            lunch_fruit_macros = _get_meal_macros(lunch_fruit)
            if lunch_fruit_macros.get("kcal", 0) > 0:  # Only add if has macros
                plan["lunch"]["accompaniments"].append({
                    "recipe": lunch_fruit,
                    "servings": 1.0,
                    "type": "fruit",
                    "macros": _calculate_meal_macros(lunch_fruit, 1.0),
                })
        if dinner_veg:
            dinner_veg_macros = _get_meal_macros(dinner_veg)
            if dinner_veg_macros.get("kcal", 0) > 0:  # Only add if has macros
                plan["dinner"]["accompaniments"].append({
                    "recipe": dinner_veg,
                    "servings": 1.0,
                    "type": "vegetable",
                    "macros": _calculate_meal_macros(dinner_veg, 1.0),
                })
        if dinner_fruit:
            dinner_fruit_macros = _get_meal_macros(dinner_fruit)
            if dinner_fruit_macros.get("kcal", 0) > 0:  # Only add if has macros
                plan["dinner"]["accompaniments"].append({
                    "recipe": dinner_fruit,
                    "servings": 1.0,
                    "type": "fruit",
                    "macros": _calculate_meal_macros(dinner_fruit, 1.0),
                })
        
        # Calculate macros for lunch and dinner (including accompaniments)
        lunch_macros = _calculate_meal_macros(lunch_rice, plan["lunch"]["servings"])
        for acc in plan["lunch"]["accompaniments"]:
            acc_macros = _calculate_meal_macros(acc["recipe"], acc["servings"])
            for k in lunch_macros:
                lunch_macros[k] += acc_macros[k]
        plan["lunch"]["macros"] = lunch_macros
        
        # Keep both main-only macros and total (with accompaniments) for FE display vs validation
        plan["lunch"]["macros_main"] = _calculate_meal_macros(lunch_rice, plan["lunch"]["servings"])
        plan["lunch"]["macros_total"] = lunch_macros

        dinner_macros = _calculate_meal_macros(dinner_rice, plan["dinner"]["servings"])
        for acc in plan["dinner"]["accompaniments"]:
            acc_macros = _calculate_meal_macros(acc["recipe"], acc["servings"])
            for k in dinner_macros:
                dinner_macros[k] += acc_macros[k]
        plan["dinner"]["macros"] = dinner_macros
        plan["dinner"]["macros_main"] = _calculate_meal_macros(dinner_rice, plan["dinner"]["servings"])
        plan["dinner"]["macros_total"] = dinner_macros

        # Ensure all recipes in plan have macros (refresh from Weaviate if needed)
        for meal_data in plan.values():
            recipe_obj = meal_data.get("recipe", {})
            if recipe_obj:
                await _ensure_recipe_macros_cached(
                    recipe_obj,
                    tree_data=tree_data,
                    client_manager=client_manager,
                )
            
            # Check accompaniments too
            for acc in meal_data.get("accompaniments", []):
                acc_recipe = acc.get("recipe", {})
                if acc_recipe:
                    await _ensure_recipe_macros_cached(
                        acc_recipe,
                        tree_data=tree_data,
                        client_manager=client_manager,
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

        logging.debug(
            "plan_day_e2e_tool: plan macros totals kcal=%.1f protein=%.1f fat=%.1f carb=%.1f | targets=%s",
            total_macros["kcal"],
            total_macros["protein_g"],
            total_macros["fat_g"],
            total_macros["carb_g"],
            targets,
        )
        logging.debug(
            "plan_day_e2e_tool: meal macros breakfast=%s lunch_main=%s lunch_total=%s dinner_main=%s dinner_total=%s accompaniments_lunch=%s accompaniments_dinner=%s",
            plan["breakfast"]["macros"],
            plan["lunch"]["macros_main"],
            plan["lunch"]["macros_total"],
            plan["dinner"]["macros_main"],
            plan["dinner"]["macros_total"],
            [(acc.get('type'), acc.get('macros')) for acc in plan['lunch'].get('accompaniments', [])],
            [(acc.get('type'), acc.get('macros')) for acc in plan['dinner'].get('accompaniments', [])],
        )
        # Emit response so frontend can compare calculations
        yield Response(
            f"📊 Plan macros: {total_macros['kcal']:.0f} kcal | "
            f"{total_macros['protein_g']:.0f}g protein | "
            f"{total_macros['fat_g']:.0f}g fat | "
            f"{total_macros['carb_g']:.0f}g carbs"
        )

        # Step 4.5: Optimize servings to better match targets (if targets available)
        if targets and total_macros.get("kcal", 0) > 0:
            target_kcal = targets.get("tdee_kcal", 2000)
            current_kcal = total_macros.get("kcal", 1)
            
            # Calculate adjustment factor (only if deviation is significant)
            if abs(current_kcal - target_kcal) / target_kcal > 0.1:  # More than 10% deviation
                adjustment_factor = target_kcal / current_kcal
                # Allow wider adjustment range (0.5x to 1.5x) to handle larger deviations
                # This ensures we can adjust even when calories are way off target
                adjustment_factor = max(0.5, min(1.5, adjustment_factor))
                
                # Apply adjustment to servings (only if adjustment is meaningful)
                if abs(adjustment_factor - 1.0) > 0.05:  # At least 5% change
                    yield Response(f"⚖️ Adjusting servings to better match your targets...")
                    for meal_key, meal_data in plan.items():
                        # Adjust main recipe servings (min 1.0 serving)
                        current_servings = meal_data.get("servings", 1.0)
                        meal_data["servings"] = max(1.0, round(current_servings * adjustment_factor, 2))
                        
                        # Adjust accompaniments servings (min 1.0 serving)
                        accompaniments = meal_data.get("accompaniments", [])
                        for acc in accompaniments:
                            acc_current = acc.get("servings", 1.0)
                            acc["servings"] = max(1.0, round(acc_current * adjustment_factor, 2))
                    
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
                    
                    # If still significantly off after first adjustment, do a second pass
                    # This helps when the initial adjustment was limited
                    new_kcal = total_macros.get("kcal", 0)
                    if new_kcal > 0 and abs(new_kcal - target_kcal) / target_kcal > 0.15:
                        # Second adjustment pass with remaining deviation
                        second_adjustment = target_kcal / new_kcal
                        # More conservative second pass (0.7x to 1.3x)
                        second_adjustment = max(0.7, min(1.3, second_adjustment))
                        
                        if abs(second_adjustment - 1.0) > 0.05:
                            for meal_key, meal_data in plan.items():
                                current_servings = meal_data.get("servings", 1.0)
                                meal_data["servings"] = max(1.0, round(current_servings * second_adjustment, 2))
                                
                                accompaniments = meal_data.get("accompaniments", [])
                                for acc in accompaniments:
                                    acc_current = acc.get("servings", 1.0)
                                    acc["servings"] = max(1.0, round(acc_current * second_adjustment, 2))
                            
                            # Recalculate one more time
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
                                
                                meal_data["macros"] = meal_macros
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
        # Suggest next action: ask user to accept and log meal history
        yield Response("👍 Kế hoạch đã sẵn sàng. Nếu bạn chấp nhận, tôi sẽ lưu vào lịch sử bữa ăn.")
        yield Result(
            name="next_action_hint",
            objects=[
                {
                    "suggested_action": "log_meal",
                    "reason": "Plan ready; log meal history after user accepts",
                    "plan_id": plan_output.get("plan_id"),
                    "user_id": user_id,
                }
            ],
            metadata={
                "suggested_action": "log_meal",
                "task_complete": False,
                "plan_id": plan_output.get("plan_id"),
            },
            payload_type="generic",
            display=False,
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


