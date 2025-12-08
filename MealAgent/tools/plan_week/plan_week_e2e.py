from typing import AsyncGenerator, Dict, Any, List
import logging
from datetime import datetime, timedelta, timezone
from collections import Counter
import random

from elysia.tree.objects import TreeData
from elysia.objects import Result, Error, Response
from elysia.util.client import ClientManager
from elysia import tool

from MealAgent.tools.utils.planning_helpers import (
    _get_meal_macros,
    _validate_macro_targets,
    sync_plan_to_weaviate,
    _calculate_plan_micronutrients,
    ensure_rfc3339_datetime,
)
from MealAgent.tools.utils.recipe_classifiers import (
    _is_vietnamese_breakfast,
    _is_rice_dish,
    _is_noodle_soup,
    _is_soup,
    _is_main_dish,
    _is_vegetable_dish,
    _is_fruit,
    _is_combined_dish,
    _matches_meal_slot,
)
from MealAgent.tools.utils.meal_selection import (
    select_meal_by_strategy,
    calculate_recipe_fit_score,
)
from MealAgent.utils.nutrition import build_default_macro_targets
from MealAgent.tools.utils.weaviate_filters import build_filters_from_where
from MealAgent.tools.utils.recipe_refresh import refresh_recipes
from MealAgent.tools.utils.profile_targets import (
    ensure_macro_targets,
    ensure_profile_loaded,
    resolve_user_id,
)


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


def _strip_device_filters(filters_results: list[Dict[str, Any]] | None) -> tuple[Dict[str, Any] | None, Dict[str, Any] | None]:
    """
    Remove any device-related constraints from the cached constraints_guard_tool result.
    This ensures weekly planning does not depend on `devices` in Recipe collection.
    """
    if not filters_results or not filters_results[0].get("objects"):
        return None, None

    filters_entry = filters_results[0]
    metadata = dict(filters_entry.get("metadata") or {})
    where = filters_entry["objects"][0].get("where") or {}

    def _clean(node: Dict[str, Any] | None) -> Dict[str, Any] | None:
        if not isinstance(node, dict):
            return node
        path = node.get("path")
        if path and "devices" in path:
            return None
        if "operator" in node and "operands" in node:
            cleaned = [o for o in (_clean(op) for op in node.get("operands", [])) if o]
            if not cleaned:
                return {}
            if len(cleaned) == 1:
                return cleaned[0]
            return {k: v for k, v in node.items() if k != "operands"} | {"operands": cleaned}
        return node

    cleaned_where = _clean(where) or {}
    filters_entry["objects"][0]["where"] = cleaned_where
    # Strip device metadata so downstream logic ignores it
    for key in ("required_device", "exclude_devices"):
        if key in metadata:
            metadata[key] = None if key == "required_device" else []
    filters_entry["metadata"] = metadata
    return cleaned_where, metadata


# Recipe classification functions imported from MealAgent.tools.utils.recipe_classifiers
# _calculate_recipe_fit_score moved to MealAgent.tools.utils.meal_selection.calculate_recipe_fit_score
# _select_meal_by_strategy moved to MealAgent.tools.utils.meal_selection.select_meal_by_strategy


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
    recent_plan_window_minutes: int = 10080,  # 7 days (7 * 24 * 60 = 10080 minutes) - recipes won't repeat within 7 days
    **kwargs,
) -> AsyncGenerator[Result | Response | Error, None]:
    """
    Weekly end-to-end planner: combine ranked recipes and targets into a 7‑day (21‑meal) plan.

    IMPORTANT: Recipes should have macros pre-calculated in the database.
    This tool only reads macros from Weaviate, it does NOT calculate macros automatically.
    Use `calculate_recipe_macros_tool` explicitly for new recipes that are missing macros.

    Environment contract:
      Reads
        • `macro_calc_tool.targets` – daily macros (multiplied internally ×7 for validation).
        • `constraints_guard_tool.filters` – guardrail filters.
        • `search_and_rank_tool.topk` – ranked recipes (should have `macros_per_serving` pre-calculated).
      Writes
        • `plan_week_e2e_tool.plan` – normalized weekly payload used by downstream tooling/UI.
        • `plan_week_e2e_tool.missing_macros` – list of recipe IDs missing macros (for manual calculation if needed).

    Decision hints:
      • Use this tool when the user asks for a **weekly meal plan** (e.g. "lên thực đơn cả tuần"), not for ad‑hoc recipe lists.
      • `plan_week_e2e_tool.plan` existing implies success; consult metadata.valid & variety_score.
      • Non-empty `missing_macros` indicates recipes need macro calculation (run `calculate_recipe_macros_tool`).
    """
    logging.info(
        "plan_week_e2e_tool: start query='%s' user_id=%s macro_tol=%.2f recent_window_min=%s variety_min=%.1f",
        (query_text or "").strip(),
        user_id,
        macro_tolerance_percent,
        recent_plan_window_minutes,
        min_variety_score,
    )
    yield Response("📅 Planning your weekly meals (21 meals over 7 days)...")
    
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
            complex_lm=None,
            **kwargs,
        )
        if profile_loaded and profile and resolved_user_id:
            yield Response(f"✅ Profile loaded for user {resolved_user_id}")
        logging.debug(
            "plan_week_e2e_tool: profile_loaded=%s user_id=%s profile_fields=%s",
            profile_loaded,
            resolved_user_id,
            list(profile.keys()) if isinstance(profile, dict) else None,
        )

        # Defer macro target calculation until after we have a candidate recipe list
        targets: Dict[str, Any] | None = None
        
        # Step 2: Read constraints filters (for validation)
        filters_results = tree_data.environment.find("constraints_guard_tool", "filters")
        filters_metadata: Dict[str, Any] | None = None
        if filters_results and filters_results[0]["objects"]:
            _strip_device_filters(filters_results)
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
        
        # Step 3: Search recipes from Weaviate database
        # IMPORTANT: Always search from Weaviate to get latest data, not from environment cache
        # Environment cache may be stale - Weaviate is the source of truth
        yield Response("🔍 Searching recipes from database...")
        try:
            from MealAgent.tools.search.search_and_rank import search_and_rank_tool

            # Search recipes from Weaviate database
            # This ensures we always get the latest recipes with up-to-date macros
            search_query = query_text if query_text else "Vietnamese recipes"
            recipes: list[Dict[str, Any]] = []
            
            async for result in search_and_rank_tool(
                tree_data=tree_data,
                inputs={},
                base_lm=base_lm,
                complex_lm=None,
                client_manager=client_manager,
                query_text=search_query,
                collection_name="Recipe",
                limit=100,  # Get more recipes for weekly planning
                top_k=50,  # Top 50 for planning
                **kwargs,
            ):
                if isinstance(result, Error):
                    error_msg = str(result) if hasattr(result, '__str__') else "Unknown error"
                    yield Error(
                        f"Failed to search recipes from database: {error_msg}. "
                        "Please check your search query or try a different query."
                    )
                    return
                if isinstance(result, Response):
                    # Forward progress messages to the user
                    yield result
                elif isinstance(result, Result) and result.objects:
                    # Capture the ranked recipes from Weaviate search
                    recipes = list(result.objects)

            # Fallback: If search returned no results, try reading from environment cache
            # This is only a fallback - primary source is always Weaviate
            if not recipes:
                logging.debug("plan_week_e2e_tool: No recipes from Weaviate search, trying environment cache...")
                sr = tree_data.environment.find("search_and_rank_tool", "topk")
                if sr:
                    for entry in reversed(sr):
                        objs = entry.get("objects") or []
                        if objs:
                            # Handle case where objs is a list containing a list of recipes
                            if len(objs) == 1 and isinstance(objs[0], list):
                                recipes = objs[0]
                            else:
                                recipes = objs
                            break
                    if recipes:
                        yield Response("⚠️ Using cached recipes (database search returned no results)")
            
            if not recipes:
                yield Error(
                    "No recipes found in database. "
                    "Please check your search query or ensure recipes are available in Weaviate."
                )
                return

            yield Response(f"✅ Found {len(recipes)} recipe(s) from database for planning.")
            logging.debug(
                "plan_week_e2e_tool: recipes from Weaviate search count=%d query='%s'",
                len(recipes),
                query_text,
            )
        except Exception as e:  # pragma: no cover - defensive
            logging.error("plan_week_e2e_tool: Failed to search recipes from Weaviate: %s", e)
            # Last resort: try environment cache
            sr = tree_data.environment.find("search_and_rank_tool", "topk")
            recipes = []
            if sr:
                for entry in reversed(sr):
                    objs = entry.get("objects") or []
                    if objs:
                        if len(objs) == 1 and isinstance(objs[0], list):
                            recipes = objs[0]
                        else:
                            recipes = objs
                        break
                if recipes:
                    yield Response("⚠️ Using cached recipes (database search failed)")
            
            if not recipes:
                yield Error(
                    f"Failed to search recipes from database: {str(e)}. "
                    "Please search for recipes first using search_and_rank_tool."
                )
                return
        
        # IMPROVED VARIETY: Exclude recently used recipes (by ID and name) to avoid repetition
        recent_recipe_ids = set()
        recent_recipe_names = set()
        try:
            client = client_manager.get_client()
            plan_collection = client.collections.get("MealPlan")
            item_collection = client.collections.get("MealPlanItem")
            meal_log_collection = client.collections.get("MealLogEntry")
            
            # Get recent plans within 7 days window for better variety
            if user_id:
                window_days = 7
                recent_date = ensure_rfc3339_datetime(
                    datetime.now(timezone.utc) - timedelta(days=window_days)
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
                            items = item_collection.query.fetch_objects(filters=item_filter, limit=100)
                            for item_obj in items.objects:
                                recipe_id = item_obj.properties.get("recipe_id")
                                if recipe_id:
                                    recent_recipe_ids.add(str(recipe_id))
                                dish_name = item_obj.properties.get("dish_name")
                                if dish_name:
                                    recent_recipe_names.add(str(dish_name).lower().strip())
                
                # Also get meal history recipe IDs (last 30 days)
                meal_history_date = ensure_rfc3339_datetime(
                    datetime.now(timezone.utc) - timedelta(days=30)
                )
                meal_filter = build_filters_from_where({
                    "operator": "And",
                    "operands": [
                        {"path": ["user_id"], "operator": "Equal", "valueString": user_id},
                        {"path": ["logged_at"], "operator": "GreaterThan", "valueDate": meal_history_date}
                    ]
                })
                
                meal_logs = meal_log_collection.query.fetch_objects(filters=meal_filter, limit=100)
                for log_obj in meal_logs.objects:
                    recipe_id = log_obj.properties.get("recipe_id")
                    if recipe_id:
                        recent_recipe_ids.add(str(recipe_id))
                    dish_name = log_obj.properties.get("dish_name")
                    if dish_name:
                        recent_recipe_names.add(str(dish_name).lower().strip())
                
                # Filter out recently used recipes (IDs) - keep at least 30 recipes
                if recent_recipe_ids and len(recipes) > 30:
                    original_count = len(recipes)
                    recipes = [r for r in recipes if str(r.get("food_id", "")) not in recent_recipe_ids]
                    if original_count > len(recipes):
                        yield Response(
                            f"🔄 Excluded {original_count - len(recipes)} recently used recipe(s) "
                            f"to ensure variety across your weekly meal plan"
                        )
                elif recent_recipe_ids and len(recipes) <= 30:
                    original_count = len(recipes)
                    recipes = [r for r in recipes if str(r.get("food_id", "")) not in recent_recipe_ids]
                    if len(recipes) < 10:
                        yield Response(
                            f"⚠️ Limited variety: only {len(recipes)} unique recipes after excluding "
                            f"{original_count - len(recipes)} recently used ones"
                        )

                # Additional safeguard: exclude by dish name (covers missing recipe_id cases)
                if recent_recipe_names:
                    name_blocklist = {name for name in recent_recipe_names if name}
                    if name_blocklist and len(recipes) > 30:
                        original_count = len(recipes)
                        recipes = [r for r in recipes if str(r.get("dish_name", "")).lower().strip() not in name_blocklist]
                        if original_count > len(recipes):
                            yield Response(
                                f"🔄 Excluded {original_count - len(recipes)} recently eaten dish(es) by name "
                                f"to avoid repetition in the weekly plan"
                            )
                    elif name_blocklist and len(recipes) <= 30:
                        original_count = len(recipes)
                        recipes = [r for r in recipes if str(r.get("dish_name", "")).lower().strip() not in name_blocklist]
                        if len(recipes) < 10:
                            yield Response(
                                f"⚠️ Limited variety after excluding recently eaten dishes by name; "
                                f"only {len(recipes)} recipes remain"
                            )
        except Exception as e:
            logging.debug(f"plan_week_e2e_tool: Could not check recent plans for variety: {e}")
            # Continue with all recipes if check fails
        
        if len(recipes) < 7:
            yield Response(f"⚠️ Warning: Only {len(recipes)} recipes available. Some recipes will be reused for 21 meals.")
        
        # Refresh recipes from Weaviate to ensure we have latest macros
        # Recipes should already have macros pre-calculated in the database
        try:
            client = client_manager.get_client()
            recipes = refresh_recipes(recipes, client, collection_name="Recipe", hydrate_fields=True)
            logging.debug(f"Refreshed {len(recipes)} recipes from Weaviate (hydrate macros + fields)")
        except Exception as refresh_exc:
            logging.debug(f"Failed to refresh recipes from Weaviate: {refresh_exc}")
            # Continue with existing recipes if refresh fails

        # Shuffle a few times to avoid clustered selections and improve variety
        for _ in range(3):
            random.shuffle(recipes)
        
        # Check for missing macros (should be rare if recipes are pre-processed)
        missing_macros = [
            r for r in recipes
            if not r.get("macros_per_serving") or not isinstance(r.get("macros_per_serving"), dict)
            or not r.get("macros_per_serving", {}).get("kcal")
        ]
        
        if missing_macros:
            missing_ids = [str(r.get("food_id")) for r in missing_macros[:10] if r.get("food_id")]
            if missing_ids:
                _record_missing_macro_state(tree_data, missing_ids)
                yield Response(
                    f"⚠️ {len(missing_macros)} recipe(s) missing nutrition data. "
                    f"Run calculate_recipe_macros_tool for these recipes if needed. "
                    f"Continuing with available recipes..."
                )
        
        # At this point we have candidate recipes. Now ensure nutritional targets are ready
        targets, targets_refreshed = await ensure_macro_targets(
            tree_data=tree_data,
            client_manager=client_manager,
            user_id=resolved_user_id,
            base_lm=base_lm,
            complex_lm=None,
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
        
        # Calculate max_kcal per meal to avoid selecting dishes that are too high
        # Align with daily planner: lighter lunch, heavier dinner for VN pattern
        if targets:
            breakfast_max_kcal = min(550.0, targets.get("tdee_kcal", 2000) * 0.25)
            lunch_max_kcal = min(700.0, targets.get("tdee_kcal", 2000) * 0.30)
            dinner_max_kcal = min(950.0, targets.get("tdee_kcal", 2000) * 0.40)
        else:
            breakfast_max_kcal = 550.0
            lunch_max_kcal = 700.0
            dinner_max_kcal = 950.0

        def _select_breakfast(
            recipes_pool: List[Dict[str, Any]],
            used_ids: set[str],
            remaining: Dict[str, float] | None,
        ) -> Dict[str, Any] | None:
            """
            Pick a Vietnamese breakfast with stronger nutrition guarantees (port from plan_day).
            Prioritizes protein, enforces kcal cap, and falls back to the best valid breakfast.
            """
            breakfast_targets = targets.copy() if targets else None
            if breakfast_targets and remaining:
                breakfast_targets["_remaining_targets"] = remaining.copy()

            daily_protein = breakfast_targets.get("protein_g", 150.0) if breakfast_targets else 150.0
            # Base protein floor (tighter than before)
            if daily_protein > 180:
                min_breakfast_protein = 22.0
            elif daily_protein > 150:
                min_breakfast_protein = 20.0
            else:
                min_breakfast_protein = 18.0

            if breakfast_targets and remaining:
                protein_remaining = remaining.get("protein_g", 0.0)
                protein_ratio = protein_remaining / daily_protein if daily_protein > 0 else 1.0
                if protein_ratio > 0.5:
                    min_breakfast_protein = max(min_breakfast_protein, 25.0)
                elif protein_ratio > 0.3:
                    min_breakfast_protein = max(min_breakfast_protein, 22.0)
                elif protein_ratio < 0.2:
                    min_breakfast_protein = max(16.0, min_breakfast_protein - 2.0)

            breakfast = select_meal_by_strategy(
                recipes_pool, "highest_protein",
                used_recipe_ids=used_ids,
                preferred_meal_type="breakfast",
                dish_category="breakfast",
                target_macros=breakfast_targets,
                require_macros=True,
                min_kcal=100.0,
                max_kcal=breakfast_max_kcal,
                min_protein=min_breakfast_protein,
            )

            # Fallback: balanced breakfast if protein-first failed
            if not breakfast:
                breakfast = select_meal_by_strategy(
                    recipes_pool, "balanced",
                    used_recipe_ids=used_ids,
                    preferred_meal_type="breakfast",
                    dish_category="breakfast",
                    target_macros=breakfast_targets,
                    require_macros=True,
                    min_kcal=100.0,
                    max_kcal=breakfast_max_kcal,
                )

            # Final safety: enforce Vietnamese breakfast + kcal/protein limits
            def _best_valid_breakfast() -> Dict[str, Any] | None:
                candidates = []
                for recipe in recipes_pool:
                    if str(recipe.get("food_id", "")) in used_ids:
                        continue
                    if not _is_vietnamese_breakfast(recipe):
                        continue
                    macros = _get_meal_macros(recipe)
                    kcal = macros.get("kcal", 0.0)
                    protein = macros.get("protein_g", 0.0)
                    if kcal and 100.0 <= kcal <= breakfast_max_kcal * 1.05:
                        candidates.append((protein, recipe))
                if not candidates:
                    return None
                candidates.sort(key=lambda x: x[0], reverse=True)
                return candidates[0][1]

            if breakfast and not _is_vietnamese_breakfast(breakfast):
                logging.warning(
                    "Selected breakfast '%s' is not Vietnamese breakfast; searching for valid alternative",
                    breakfast.get("dish_name", "Unknown"),
                )
                alt = _best_valid_breakfast()
                if alt:
                    breakfast = alt

            if breakfast:
                macros = _get_meal_macros(breakfast)
                kcal = macros.get("kcal", 0.0)
                protein = macros.get("protein_g", 0.0)
                if (protein is not None and protein < min_breakfast_protein) or kcal > breakfast_max_kcal * 1.1:
                    alt = _best_valid_breakfast()
                    if alt:
                        alt_macros = _get_meal_macros(alt)
                        alt_kcal = alt_macros.get("kcal", 0.0)
                        alt_protein = alt_macros.get("protein_g", 0.0)
                        if alt_protein >= min_breakfast_protein and alt_kcal <= breakfast_max_kcal * 1.1:
                            breakfast = alt
            else:
                breakfast = _best_valid_breakfast()

            return breakfast

        def _trim_excess_mains(accompaniments: List[Dict[str, Any]]) -> None:
            """
            Keep only the first main dish in accompaniments to avoid overcrowded meals.
            """
            main_seen = False
            trimmed = []
            for acc in accompaniments:
                if acc.get("type") == "main":
                    if main_seen:
                        # drop extra mains
                        continue
                    main_seen = True
                trimmed.append(acc)
            if len(trimmed) != len(accompaniments):
                logging.debug(
                    "plan_week_e2e_tool: trimmed %d extra main(s) from accompaniments",
                    len(accompaniments) - len(trimmed),
                )
            accompaniments[:] = trimmed

        def _calculate_day_macros(day_plan: Dict[str, Any]) -> Dict[str, float]:
            totals = {"kcal": 0.0, "protein_g": 0.0, "fat_g": 0.0, "carb_g": 0.0}
            for meal_data in day_plan.values():
                recipe = meal_data.get("recipe")
                if recipe:
                    macros = _get_meal_macros(recipe)
                    for k in totals:
                        totals[k] += macros.get(k, 0.0) * meal_data.get("servings", 1.0)
                for acc in meal_data.get("accompaniments", []):
                    acc_recipe = acc.get("recipe")
                    if acc_recipe:
                        acc_macros = _get_meal_macros(acc_recipe)
                        for k in totals:
                            totals[k] += acc_macros.get(k, 0.0) * acc.get("servings", 1.0)
            return totals

        def _maybe_add_supplementary(
            meal_slot: str,
            day_plan: Dict[str, Any],
            is_combined: bool,
            is_noodle: bool,
        ) -> None:
            """
            Lightweight supplementary step: add one more dish if daily deficit is large.
            Priority: protein > kcal. Adds to dinner first, then lunch.
            """
            if not targets:
                return
            daily_kcal = targets.get("tdee_kcal", 0.0)
            daily_protein = targets.get("protein_g", 0.0)
            daily_fat = targets.get("fat_g", 0.0) or 0.0
            daily_carb = targets.get("carb_g", 0.0) or 0.0
            if not daily_kcal or not daily_protein:
                return

            current = _calculate_day_macros(day_plan)
            kcal_deficit = daily_kcal - current["kcal"]
            protein_deficit = daily_protein - current["protein_g"]
            fat_excess_pct = (current["fat_g"] / daily_fat * 100) if daily_fat else 0.0
            carb_excess_pct = (current["carb_g"] / daily_carb * 100) if daily_carb else 0.0

            # Need a meaningful deficit to act
            if kcal_deficit < 350.0 and protein_deficit < 20.0:
                return

            # Avoid adding if fat/carb already too high
            if fat_excess_pct > 135.0 or carb_excess_pct > 145.0:
                return

            # Choose pool and placement
            target_meal = day_plan.get(meal_slot, {})
            if not target_meal:
                return

            accompaniments = target_meal.get("accompaniments", [])
            # Avoid overcrowding mains for combined/noodle dishes
            allowed_main = not is_combined and not is_noodle

            # Pick a supplementary dish
            supp = select_meal_by_strategy(
                recipes,
                "highest_protein",
                exclude=[acc.get("recipe") for acc in accompaniments if acc.get("recipe")] + [target_meal.get("recipe")],
                used_recipe_ids=used_recipe_ids,
                preferred_meal_type=meal_slot,
                target_macros=targets,
                require_macros=True,
                min_kcal=100.0,
                max_kcal=450.0,
                min_protein=15.0,
            )
            if not supp:
                return

            # Decide type
            dish_type = "main"
            if not allowed_main or _is_vegetable_dish(supp):
                dish_type = "vegetable"
            elif _is_fruit(supp):
                dish_type = "fruit"
            elif _is_soup(supp):
                dish_type = "soup"
            elif not _is_main_dish(supp):
                # fallback to vegetable if not a real main
                dish_type = "vegetable"

            accompaniments.append(
                {"recipe": supp, "servings": 1.0, "type": dish_type}
            )
            used_recipe_ids.add(str(supp.get("food_id", "")))
            # Re-trim mains if we added another main
            _trim_excess_mains(accompaniments)

        def _recompute_weekly_totals(plan: Dict[str, Any]) -> Dict[str, float]:
            totals = {"kcal": 0.0, "protein_g": 0.0, "fat_g": 0.0, "carb_g": 0.0}
            for day in plan.values():
                for meal_data in day.get("meals", {}).values():
                    recipe = meal_data.get("recipe")
                    if recipe:
                        macros = _get_meal_macros(recipe)
                        servings = meal_data.get("servings", 1.0)
                        for k in totals:
                            totals[k] += macros.get(k, 0.0) * servings
                    for acc in meal_data.get("accompaniments", []):
                        acc_recipe = acc.get("recipe")
                        if acc_recipe:
                            acc_macros = _get_meal_macros(acc_recipe)
                            acc_servings = acc.get("servings", 1.0)
                            for k in totals:
                                totals[k] += acc_macros.get(k, 0.0) * acc_servings
            return totals

        def _score_totals(totals: Dict[str, float], target_totals: Dict[str, float]) -> float:
            def rel_diff(k: str) -> float:
                tgt = target_totals.get(k, 0.0) or 0.0
                if tgt <= 0:
                    return 0.0
                return abs(totals.get(k, 0.0) - tgt) / tgt

            # Heavier weight on kcal and protein
            return (
                rel_diff("kcal") * 0.5
                + rel_diff("protein_g") * 0.4
                + rel_diff("fat_g") * 0.05
                + rel_diff("carb_g") * 0.05
            )

        def _try_optimize_macros(weekly_plan: Dict[str, Any], total_macros: Dict[str, float]) -> Dict[str, float]:
            """
            Lightweight swap optimizer: try swapping main accompaniments to improve weekly macro fit.
            Limits swaps to keep runtime low.
            """
            if not targets:
                return total_macros

            weekly_targets = {
                "kcal": targets.get("tdee_kcal", 0.0) * 7.0,
                "protein_g": targets.get("protein_g", 0.0) * 7.0,
                "fat_g": targets.get("fat_g", 0.0) * 7.0,
                "carb_g": targets.get("carb_g", 0.0) * 7.0,
            }
            best_score = _score_totals(total_macros, weekly_targets)
            swaps_made = 0
            max_swaps = 6

            for _ in range(max_swaps):
                improved = False
                # Iterate days and meals to find a better main replacement
                for day_data in weekly_plan.values():
                    meals = day_data.get("meals", {})
                    for meal_key in ("lunch", "dinner"):
                        meal_data = meals.get(meal_key, {})
                        accompaniments = meal_data.get("accompaniments", [])
                        # Find existing main accompaniment
                        main_idx = None
                        for idx, acc in enumerate(accompaniments):
                            if acc.get("type") == "main" and acc.get("recipe"):
                                main_idx = idx
                                break
                        if main_idx is None:
                            continue
                        current_main = accompaniments[main_idx]["recipe"]
                        current_id = str(current_main.get("food_id", ""))

                        # Candidate pool: main dishes with macros and not already used
                        candidates = [
                            r for r in recipes
                            if r.get("macros_per_serving")
                            and isinstance(r.get("macros_per_serving"), dict)
                            and r.get("macros_per_serving", {}).get("kcal")
                            and _is_main_dish(r)
                            and str(r.get("food_id", "")) not in used_recipe_ids
                        ]
                        # Try a few best protein-dense options
                        candidates = sorted(
                            candidates,
                            key=lambda r: _get_meal_macros(r).get("protein_g", 0.0),
                            reverse=True,
                        )[:8]

                        for cand in candidates:
                            cand_id = str(cand.get("food_id", ""))
                            if not cand_id:
                                continue
                            # Tentatively swap
                            accompaniments[main_idx] = {"recipe": cand, "servings": 1.0, "type": "main"}
                            new_totals = _recompute_weekly_totals(weekly_plan)
                            new_score = _score_totals(new_totals, weekly_targets)
                            if new_score + 0.005 < best_score:  # require a real improvement
                                # Accept swap
                                used_recipe_ids.discard(current_id)
                                used_recipe_ids.add(cand_id)
                                best_score = new_score
                                total_macros.update(new_totals)
                                swaps_made += 1
                                improved = True
                                break
                            # Revert
                            accompaniments[main_idx] = {"recipe": current_main, "servings": 1.0, "type": "main"}
                        if improved:
                            break
                    if improved:
                        break
                if not improved:
                    break

            if swaps_made > 0:
                logging.info("plan_week_e2e_tool: macro optimizer swapped %d main(s) (score=%.3f)", swaps_made, best_score)
            return total_macros
        
        for day_index in range(7):
            day_date = start + timedelta(days=day_index)
            day_key = day_date.date().isoformat()
            
            # Track remaining targets for this day (reset each day)
            remaining_targets = {
                "kcal": targets.get("tdee_kcal", 2000.0) if targets else 2000.0,
                "protein_g": targets.get("protein_g", 150.0) if targets else 150.0,
                "fat_g": targets.get("fat_g", 65.0) if targets else 65.0,
                "carb_g": targets.get("carb_g", 200.0) if targets else 200.0,
            } if targets else None
            
            # Get available recipes (prefer unused)
            available_recipes = [r for r in recipes if str(r.get("food_id", "")) not in used_recipe_ids]
            if not available_recipes:
                available_recipes = recipes
            
            # Breakfast: Vietnamese breakfast dishes with stronger nutrition guarantees (aligned with plan_day)
            breakfast = _select_breakfast(
                available_recipes,
                used_recipe_ids=used_recipe_ids,
                remaining=remaining_targets,
            )
            if not breakfast and available_recipes:
                breakfast = available_recipes[0]
            
            # Update remaining targets after breakfast
            if remaining_targets and breakfast:
                breakfast_macros = _get_meal_macros(breakfast)
                remaining_targets["kcal"] = max(0.0, remaining_targets["kcal"] - breakfast_macros.get("kcal", 0.0))
                remaining_targets["protein_g"] = max(0.0, remaining_targets["protein_g"] - breakfast_macros.get("protein_g", 0.0))
                remaining_targets["fat_g"] = max(0.0, remaining_targets["fat_g"] - breakfast_macros.get("fat_g", 0.0))
                remaining_targets["carb_g"] = max(0.0, remaining_targets["carb_g"] - breakfast_macros.get("carb_g", 0.0))
            
            # Lunch: Rice + Main + Vegetable + Fruit
            excluded = [breakfast] if breakfast else []
            
            # Prepare targets with remaining_targets for lunch
            lunch_targets = targets.copy() if targets else None
            if lunch_targets and remaining_targets:
                lunch_targets["_remaining_targets"] = remaining_targets.copy()
            
            # Calculate dynamic requirements based on remaining protein
            max_main_kcal = 500.0
            min_main_protein = 18.0
            if remaining_targets and targets:
                protein_remaining = remaining_targets.get("protein_g", 0.0)
                daily_protein = targets.get("protein_g", 150.0)
                protein_ratio = protein_remaining / daily_protein if daily_protein > 0 else 1.0
                if protein_ratio > 0.5:
                    max_main_kcal = 650.0
                    min_main_protein = 25.0
                elif protein_ratio > 0.4:
                    max_main_kcal = 600.0
                    min_main_protein = 22.0
                elif protein_ratio > 0.2:
                    min_main_protein = 18.0
            
            lunch_rice = select_meal_by_strategy(
                available_recipes, selection_strategy if targets else "highest_carb",
                exclude=excluded, used_recipe_ids=used_recipe_ids,
                preferred_meal_type="lunch", dish_category="rice",
                target_macros=lunch_targets,
                require_macros=True,
                max_kcal=lunch_max_kcal,
            )
            if not lunch_rice:
                lunch_rice = select_meal_by_strategy(
                    available_recipes, "highest_carb",
                    exclude=excluded, used_recipe_ids=used_recipe_ids,
                    preferred_meal_type="lunch",
                    target_macros=lunch_targets,
                    require_macros=True,
                )
            
            if lunch_rice:
                excluded.append(lunch_rice)
                # Validate lunch rice
                if not _is_rice_dish(lunch_rice) and not _is_noodle_soup(lunch_rice):
                    logging.warning(f"Selected lunch rice '{lunch_rice.get('dish_name', 'Unknown')}' is not rice/noodle")
                if _is_main_dish(lunch_rice):
                    logging.warning(f"Selected lunch rice '{lunch_rice.get('dish_name', 'Unknown')}' is a main dish")
            
            is_lunch_combined = _is_combined_dish(lunch_rice) if lunch_rice else False
            is_lunch_noodle = _is_noodle_soup(lunch_rice) if lunch_rice else False

            lunch_main = None
            lunch_veg = None
            lunch_fruit = None

            if not is_lunch_combined and not is_lunch_noodle:
                lunch_main = select_meal_by_strategy(
                    available_recipes, "highest_protein",
                    exclude=excluded, used_recipe_ids=used_recipe_ids,
                    preferred_meal_type="lunch", dish_category="main",
                    target_macros=lunch_targets,
                    require_macros=True,
                    min_kcal=50.0,
                    max_kcal=max_main_kcal,
                    min_protein=min_main_protein,
                )
                if not lunch_main:
                    lunch_main = select_meal_by_strategy(
                        available_recipes, "highest_protein",
                        exclude=excluded, used_recipe_ids=used_recipe_ids,
                        preferred_meal_type="lunch",
                        target_macros=lunch_targets,
                        require_macros=True,
                        min_kcal=50.0,
                        max_kcal=max_main_kcal,
                    )
                
                # Validate lunch main
                if lunch_main and not _is_main_dish(lunch_main):
                    logging.warning(f"Selected lunch main '{lunch_main.get('dish_name', 'Unknown')}' is not a main dish")
                    lunch_main = None
                
                if lunch_main:
                    excluded.append(lunch_main)
                
                lunch_veg = select_meal_by_strategy(
                    available_recipes, "balanced",
                    exclude=excluded, used_recipe_ids=used_recipe_ids,
                    preferred_meal_type="lunch", dish_category="vegetable",
                    target_macros=lunch_targets,
                    require_macros=True,
                    min_kcal=30.0,
                    max_kcal=150.0,
                )
                
                # Validate lunch vegetable
                if lunch_veg:
                    if not _is_vegetable_dish(lunch_veg):
                        logging.warning(f"Selected lunch vegetable '{lunch_veg.get('dish_name', 'Unknown')}' is not a vegetable dish")
                        lunch_veg = None
                    elif _is_main_dish(lunch_veg):
                        logging.warning(f"Selected lunch vegetable '{lunch_veg.get('dish_name', 'Unknown')}' is actually a main dish")
                        lunch_veg = None
                    else:
                        excluded.append(lunch_veg)

            # Fruit: always allowed, even for combined/noodle (keeps meal light)
            lunch_fruit = select_meal_by_strategy(
                available_recipes, "balanced",
                exclude=excluded, used_recipe_ids=used_recipe_ids,
                preferred_meal_type="lunch", dish_category="fruit",
                target_macros=lunch_targets,
                require_macros=True,
                min_kcal=30.0,
                max_kcal=150.0,
            )
            
            # Validate lunch fruit
            if lunch_fruit:
                if not _is_fruit(lunch_fruit):
                    logging.warning(f"Selected lunch fruit '{lunch_fruit.get('dish_name', 'Unknown')}' is not a fruit")
                    lunch_fruit = None
                else:
                    excluded.append(lunch_fruit)
            
            # Fallback: if no rice/main, use any available recipe
            if not lunch_rice or not lunch_main:
                if not lunch_rice:
                    lunch_rice = select_meal_by_strategy(
                        available_recipes, "highest_carb",
                        exclude=[breakfast] if breakfast else [],
                        used_recipe_ids=used_recipe_ids,
                        require_macros=True,
                    ) or (available_recipes[0] if available_recipes else None)
                if not lunch_main:
                    exclude_ids = {str(r.get("food_id", "")) for r in [breakfast, lunch_rice] if r}
                    remaining = [r for r in available_recipes if str(r.get("food_id", "")) not in exclude_ids]
                    lunch_main = remaining[0] if remaining else lunch_rice
            
            # Update remaining targets after lunch
            if remaining_targets:
                lunch_total_macros = _get_meal_macros(lunch_rice) if lunch_rice else {}
                if lunch_main:
                    main_macros = _get_meal_macros(lunch_main)
                    for k in lunch_total_macros:
                        lunch_total_macros[k] = lunch_total_macros.get(k, 0.0) + main_macros.get(k, 0.0)
                if lunch_veg:
                    veg_macros = _get_meal_macros(lunch_veg)
                    for k in lunch_total_macros:
                        lunch_total_macros[k] = lunch_total_macros.get(k, 0.0) + veg_macros.get(k, 0.0)
                if lunch_fruit:
                    fruit_macros = _get_meal_macros(lunch_fruit)
                    for k in lunch_total_macros:
                        lunch_total_macros[k] = lunch_total_macros.get(k, 0.0) + fruit_macros.get(k, 0.0)
                
                remaining_targets["kcal"] = max(0.0, remaining_targets["kcal"] - lunch_total_macros.get("kcal", 0.0))
                remaining_targets["protein_g"] = max(0.0, remaining_targets["protein_g"] - lunch_total_macros.get("protein_g", 0.0))
                remaining_targets["fat_g"] = max(0.0, remaining_targets["fat_g"] - lunch_total_macros.get("fat_g", 0.0))
                remaining_targets["carb_g"] = max(0.0, remaining_targets["carb_g"] - lunch_total_macros.get("carb_g", 0.0))
            
            # Dinner: Rice + Main + Vegetable + Fruit
            excluded = [breakfast, lunch_rice] if breakfast and lunch_rice else [breakfast] if breakfast else []
            if lunch_main:
                excluded.append(lunch_main)
            if lunch_veg:
                excluded.append(lunch_veg)
            if lunch_fruit:
                excluded.append(lunch_fruit)
            
            # Prepare targets with remaining_targets for dinner
            dinner_targets = targets.copy() if targets else None
            if dinner_targets and remaining_targets:
                dinner_targets["_remaining_targets"] = remaining_targets.copy()
            
            # Recalculate dynamic requirements for dinner
            if remaining_targets and targets:
                protein_remaining = remaining_targets.get("protein_g", 0.0)
                daily_protein = targets.get("protein_g", 150.0)
                protein_ratio = protein_remaining / daily_protein if daily_protein > 0 else 1.0
                if protein_ratio > 0.5:
                    max_main_kcal = 650.0
                    min_main_protein = 25.0
                elif protein_ratio > 0.4:
                    max_main_kcal = 600.0
                    min_main_protein = 22.0
                elif protein_ratio > 0.2:
                    min_main_protein = 18.0
                else:
                    max_main_kcal = 500.0
                    min_main_protein = 15.0
            
            dinner_rice = select_meal_by_strategy(
                available_recipes, selection_strategy if targets else "highest_carb",
                exclude=excluded, used_recipe_ids=used_recipe_ids,
                preferred_meal_type="dinner", dish_category="rice",
                target_macros=dinner_targets,
                require_macros=True,
                max_kcal=dinner_max_kcal,
            )
            if not dinner_rice:
                dinner_rice = select_meal_by_strategy(
                    available_recipes, "highest_carb",
                    exclude=excluded, used_recipe_ids=used_recipe_ids,
                    preferred_meal_type="dinner",
                    target_macros=dinner_targets,
                    require_macros=True,
                )
            
            # Validate dinner rice
            if dinner_rice:
                if not _is_rice_dish(dinner_rice) and not _is_noodle_soup(dinner_rice):
                    logging.warning(f"Selected dinner rice '{dinner_rice.get('dish_name', 'Unknown')}' is not rice/noodle")
                if _is_main_dish(dinner_rice):
                    logging.warning(f"Selected dinner rice '{dinner_rice.get('dish_name', 'Unknown')}' is a main dish")
                excluded.append(dinner_rice)
            
            is_dinner_combined = _is_combined_dish(dinner_rice) if dinner_rice else False
            is_dinner_noodle = _is_noodle_soup(dinner_rice) if dinner_rice else False

            dinner_main = None
            dinner_veg = None
            dinner_fruit = None

            if not is_dinner_combined and not is_dinner_noodle:
                dinner_main = select_meal_by_strategy(
                    available_recipes, "highest_protein",
                    exclude=excluded, used_recipe_ids=used_recipe_ids,
                    preferred_meal_type="dinner", dish_category="main",
                    target_macros=dinner_targets,
                    require_macros=True,
                    min_kcal=50.0,
                    max_kcal=max_main_kcal,
                    min_protein=min_main_protein,
                )
                if not dinner_main:
                    dinner_main = select_meal_by_strategy(
                        available_recipes, "highest_protein",
                        exclude=excluded, used_recipe_ids=used_recipe_ids,
                        preferred_meal_type="dinner",
                        target_macros=dinner_targets,
                        require_macros=True,
                        min_kcal=50.0,
                        max_kcal=max_main_kcal,
                    )
                
                # Validate dinner main
                if dinner_main and not _is_main_dish(dinner_main):
                    logging.warning(f"Selected dinner main '{dinner_main.get('dish_name', 'Unknown')}' is not a main dish")
                    dinner_main = None
                
                if dinner_main:
                    excluded.append(dinner_main)
                
                dinner_veg = select_meal_by_strategy(
                    available_recipes, "balanced",
                    exclude=excluded, used_recipe_ids=used_recipe_ids,
                    preferred_meal_type="dinner", dish_category="vegetable",
                    target_macros=dinner_targets,
                    require_macros=True,
                    min_kcal=30.0,
                    max_kcal=150.0,
                )
                
                # Validate dinner vegetable
                if dinner_veg:
                    if not _is_vegetable_dish(dinner_veg):
                        logging.warning(f"Selected dinner vegetable '{dinner_veg.get('dish_name', 'Unknown')}' is not a vegetable dish")
                        dinner_veg = None
                    elif _is_main_dish(dinner_veg):
                        logging.warning(f"Selected dinner vegetable '{dinner_veg.get('dish_name', 'Unknown')}' is actually a main dish")
                        dinner_veg = None
                    else:
                        excluded.append(dinner_veg)

            # Fruit: always allowed, even for combined/noodle (keeps meal light)
            dinner_fruit = select_meal_by_strategy(
                available_recipes, "balanced",
                exclude=excluded, used_recipe_ids=used_recipe_ids,
                preferred_meal_type="dinner", dish_category="fruit",
                target_macros=dinner_targets,
                require_macros=True,
                min_kcal=30.0,
                max_kcal=150.0,
            )
            
            # Validate dinner fruit
            if dinner_fruit:
                if not _is_fruit(dinner_fruit):
                    logging.warning(f"Selected dinner fruit '{dinner_fruit.get('dish_name', 'Unknown')}' is not a fruit")
                    dinner_fruit = None
                else:
                    excluded.append(dinner_fruit)
            
            # Fallback for dinner
            if not dinner_rice or not dinner_main:
                if not dinner_rice:
                    exclude_ids = {str(r.get("food_id", "")) for r in [breakfast, lunch_rice, lunch_main] if r}
                    remaining = [r for r in available_recipes if str(r.get("food_id", "")) not in exclude_ids]
                    dinner_rice = remaining[0] if remaining else lunch_rice
                if not dinner_main:
                    exclude_ids = {str(r.get("food_id", "")) for r in [breakfast, lunch_rice, lunch_main, dinner_rice] if r}
                    remaining = [r for r in available_recipes if str(r.get("food_id", "")) not in exclude_ids]
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
                    used_recipe_ids.add(str(meal.get("food_id")))
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

            # Prevent overcrowding: keep at most one main accompaniment per meal
            _trim_excess_mains(day_plan["lunch"]["accompaniments"])
            _trim_excess_mains(day_plan["dinner"]["accompaniments"])

            # If daily macros are far below target, add a supplementary dish to dinner first, then lunch
            if targets:
                _maybe_add_supplementary("dinner", day_plan, is_dinner_combined, is_dinner_noodle)
                _maybe_add_supplementary("lunch", day_plan, is_lunch_combined, is_lunch_noodle)
                # Re-trim after supplements
                _trim_excess_mains(day_plan["lunch"]["accompaniments"])
                _trim_excess_mains(day_plan["dinner"]["accompaniments"])
            
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
        
        # Optional optimization: swap some mains to improve weekly macro fit
        total_macros = _try_optimize_macros(weekly_plan, total_macros)

        # Calculate average daily macros
        average_daily_macros = {
            "kcal": total_macros["kcal"] / 7.0,
            "protein_g": total_macros["protein_g"] / 7.0,
            "fat_g": total_macros["fat_g"] / 7.0,
            "carb_g": total_macros["carb_g"] / 7.0,
        }
        # Quick coverage check vs targets to surface quality issues early
        if targets:
            target_kcal = targets.get("tdee_kcal", 0.0)
            target_protein = targets.get("protein_g", 0.0)
            kcal_cov = (average_daily_macros["kcal"] / target_kcal * 100) if target_kcal else 0.0
            protein_cov = (average_daily_macros["protein_g"] / target_protein * 100) if target_protein else 0.0
            if kcal_cov < 85.0 or protein_cov < 85.0:
                logging.warning(
                    "plan_week_e2e_tool: LOW_WEEKLY_COVERAGE kcal=%.1f%% protein=%.1f%%",
                    kcal_cov,
                    protein_cov,
                )
            if kcal_cov > 125.0 or protein_cov > 125.0:
                logging.warning(
                    "plan_week_e2e_tool: HIGH_WEEKLY_COVERAGE kcal=%.1f%% protein=%.1f%%",
                    kcal_cov,
                    protein_cov,
                )
        logging.debug(
            "plan_week_e2e_tool: weekly totals kcal=%.1f protein=%.1f fat=%.1f carb=%.1f | avg/day kcal=%.1f protein=%.1f fat=%.1f carb=%.1f",
            total_macros["kcal"],
            total_macros["protein_g"],
            total_macros["fat_g"],
            total_macros["carb_g"],
            average_daily_macros["kcal"],
            average_daily_macros["protein_g"],
            average_daily_macros["fat_g"],
            average_daily_macros["carb_g"],
        )
        
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

