"""
End-to-end substitution tool: suggest substitutes → optionally apply to plan.
"""
from typing import AsyncGenerator, Dict, Any, List
import copy
import logging

from elysia.tree.objects import TreeData
from elysia.objects import Result, Error, Response
from elysia.util.client import ClientManager
from elysia import tool
from MealAgent.tools.utils.weaviate_filters import build_filters_from_where
from MealAgent.tools.utils.planning_helpers import sync_plan_to_weaviate

from MealAgent.tools.nutrition.calculate_recipe_macros import calculate_recipe_macros_tool

logger = logging.getLogger(__name__)


def _macro_match_score(
    original_macros: Dict[str, float],
    substitute_macros: Dict[str, float],
    tolerance: float = 0.2,
) -> float:
    """
    Calculate how well substitute matches original macros (0-100, higher is better).
    Uses ±20% tolerance by default.
    """
    if not original_macros or not substitute_macros:
        return 0.0

    scores = []
    for macro in ["kcal", "protein_g", "fat_g", "carb_g"]:
        original_val = original_macros.get(macro, 0.0)
        substitute_val = substitute_macros.get(macro, 0.0)

        if original_val > 0:
            ratio = substitute_val / original_val
            # Score: 100 if exact match, decreases as ratio deviates from 1.0
            # Within tolerance (0.8-1.2), score is high
            if 1.0 - tolerance <= ratio <= 1.0 + tolerance:
                score = 100.0 - abs(ratio - 1.0) * 100.0 / tolerance
                scores.append(max(0.0, score))
            else:
                scores.append(0.0)
        elif substitute_val == 0:
            scores.append(100.0)  # Both zero = match
        else:
            scores.append(0.0)

    return sum(scores) / len(scores) if scores else 0.0


def _safe_float(value: Any, default: float = 0.0) -> float:
    """Convert to float, tolerating None/invalid values."""
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _to_int_or_none(val: Any) -> int | None:
    """Best-effort int conversion; returns None on failure."""
    try:
        return int(val)
    except (TypeError, ValueError):
        return None


@tool
async def substitute_tool(
    tree_data: TreeData,
    client_manager: ClientManager,
    ingredient_name: str = "",
    fdc_id: int | None = None,
    substitute_fdc_id: int | None = None,  # If provided, skip suggestion and apply directly
    tolerance: float = 0.2,
    top_k: int = 10,
    auto_apply: bool = False,  # If True, automatically apply best substitute
    recalculate_macros: bool = True,
    user_id: str | None = None,
    plan_id: str | None = None,
    base_lm=None,  # optional LM for macro recalculation; fallback to kwargs
    recipe_level: bool = False,  # if True, swap whole recipes instead of only ingredients
    **kwargs,
) -> AsyncGenerator[Result | Response | Error, None]:
    """
    Macro-aware ingredient substitution helper (suggest → optionally apply → recalc macros).

    Workflow:
      1. Identify the original ingredient via `ingredient_name` or `fdc_id`.
      2. Query FDC for nutritionally similar candidates within ±`tolerance`.
      3. Emit ranked substitutes table; optionally apply the best one to current plan.
      4. When `auto_apply` and `base_lm` are provided, trigger macro recalculation + plan sync.

    Environment contract:
      Reads
        • `plan_day_e2e_tool.plan` / `plan_week_e2e_tool.plan` (when auto-applying on the active plan).
      Writes
        • `substitute_tool.substitutes` (list + table variants for display).
        • `substitute_tool.updated_plan` when modifications are persisted.

    Decision hints:
      • If only `substitutes` is present, ask the user to pick or apply automatically.
      • Once `updated_plan` exists, downstream tools (gap fill, micros, pantry) should consume the new plan version.
    """
    logging.info("substitute_tool: start")
    yield Response("🔄 Finding ingredient substitutes with similar nutrition...")
    
    try:
        # Prefer explicit base_lm, but allow legacy kwargs path
        base_lm = base_lm or kwargs.get("base_lm")

        # Step 1: Identify ingredient to substitute
        original_fdc_id = fdc_id
        original_ingredient_name = ingredient_name
        # If ingredient not specified, try to extract from plan context
        if not original_ingredient_name and not original_fdc_id:
            yield Error("ingredient_name or fdc_id is required")
            return

        def _iter_plan_recipes(plan_obj: Dict[str, Any]) -> List[Dict[str, Any]]:
            """Yield all recipe dicts from a plan (meals + accompaniments)."""
            recipes: List[Dict[str, Any]] = []
            if not plan_obj:
                return recipes
            if plan_obj.get("plan_type") == "day":
                for meal_data in plan_obj.get("meals", {}).values():
                    if meal_data.get("recipe"):
                        recipes.append(meal_data["recipe"])
                    for acc in meal_data.get("accompaniments", []):
                        if isinstance(acc, dict) and acc.get("recipe"):
                            recipes.append(acc["recipe"])
            elif plan_obj.get("plan_type") == "week":
                for day_data in plan_obj.get("days", {}).values():
                    for meal_data in day_data.get("meals", {}).values():
                        if meal_data.get("recipe"):
                            recipes.append(meal_data["recipe"])
                        for acc in meal_data.get("accompaniments", []):
                            if isinstance(acc, dict) and acc.get("recipe"):
                                recipes.append(acc["recipe"])
            return recipes

        def _resolve_fdc_from_plan(name: str, plan_obj: Dict[str, Any]) -> tuple[int | None, Dict[str, Any] | None]:
            """Resolve an ingredient name to an FDC id using the plan's ingredient maps."""
            if not name or not plan_obj:
                return None, None
            needle = name.lower()
            for recipe in _iter_plan_recipes(plan_obj):
                ingredient_map = recipe.get("ingredient_fdc_map", []) or []
                for ing in ingredient_map:
                    if not isinstance(ing, dict):
                        continue
                    candidates = [
                        str(ing.get("ingredient_vn", "")),
                        str(ing.get("ingredient_en", "")),
                        str(ing.get("ingredient", "")),
                        str(ing.get("name", "")),
                        str(ing.get("description", "")),
                    ]
                    if any(needle in field.lower() for field in candidates if field):
                        fdc_val = ing.get("fdc_id")
                        try:
                            return int(fdc_val), ing
                        except (TypeError, ValueError):
                            return None, ing
            return None, None

        # Load plan early so we can resolve ingredient names to fdc_id before querying FDC
        exclude_allergens: List[str] = []
        plan: Dict[str, Any] | None = None
        plan_source: str | None = None

        if plan_id:
            from MealAgent.tools.utils.plan_loader import load_plan_from_weaviate
            plan = load_plan_from_weaviate(plan_id, client_manager, user_id)
            if plan:
                plan_source = plan.get("plan_type", "day") + "_plan"
        elif user_id:
            from MealAgent.tools.utils.plan_loader import load_latest_plan_from_weaviate
            plan = load_latest_plan_from_weaviate(user_id, client_manager, "day")
            if not plan:
                plan = load_latest_plan_from_weaviate(user_id, client_manager, "week")

        if not plan:
            logger.debug("substitute_tool: No plan from database, trying environment cache")
            day_plan_results = tree_data.environment.find("plan_day_e2e_tool", "plan")
            if day_plan_results and day_plan_results[0]["objects"]:
                plan = copy.deepcopy(day_plan_results[0]["objects"][0])
                plan_source = "plan_day_e2e_tool"
            else:
                week_plan_results = tree_data.environment.find("plan_week_e2e_tool", "plan")
                if week_plan_results and week_plan_results[0]["objects"]:
                    plan = copy.deepcopy(week_plan_results[0]["objects"][0])
                    plan_source = "plan_week_e2e_tool"

        plan_user_id = plan.get("user_id") if plan else user_id
        if plan and (plan.get("plan_id") or plan_id):
            plan["plan_id"] = plan.get("plan_id") or plan_id
        logger.debug(
            "substitute_tool: plan loaded | plan_id=%s | source=%s | user_id=%s",
            plan.get("plan_id") if plan else None,
            plan_source,
            plan_user_id,
        )

        matched_ing = None
        matched_names: List[str] = []
        # Attempt to resolve fdc_id from plan ingredient maps when only a name was given
        if not original_fdc_id and original_ingredient_name and plan:
            inferred_fdc_id, matched_ing = _resolve_fdc_from_plan(original_ingredient_name, plan)
            if inferred_fdc_id:
                original_fdc_id = inferred_fdc_id
                original_fdc_id_int = _to_int_or_none(original_fdc_id)
                original_ingredient_name = (
                    matched_ing.get("ingredient_en")
                    or matched_ing.get("ingredient_vn")
                    or matched_ing.get("name")
                    or original_ingredient_name
                )
                logger.debug(
                    "substitute_tool: resolved ingredient '%s' to fdc_id=%s from plan source=%s",
                    ingredient_name,
                    original_fdc_id,
                    plan_source,
                )
            elif matched_ing:
                # Keep candidate names for fallback search in FDC
                matched_names = [
                    matched_ing.get("ingredient_en", ""),
                    matched_ing.get("ingredient_vn", ""),
                    matched_ing.get("name", ""),
                    matched_ing.get("description", ""),
                ]
        
        # Normalize fdc_id to int if possible
        original_fdc_id_int = _to_int_or_none(original_fdc_id)

        # Step 2: Get original ingredient macros
        client = client_manager.get_client()
        try:
            fdc_collection = client.collections.get("FdcFood")
        except Exception as e:
            yield Error(f"FdcFood collection not found: {str(e)}. Please ensure collections are created.")
            return
        
        original_fdc = None
        if original_fdc_id_int is not None:
            original_filter = build_filters_from_where(
                {"path": ["fdc_id"], "operator": "Equal", "valueInt": original_fdc_id_int}
            )
            results = fdc_collection.query.fetch_objects(filters=original_filter, limit=1)
            logger.debug(
                "substitute_tool: query original by fdc_id=%s | results=%s",
                original_fdc_id_int,
                len(results.objects) if results and results.objects else 0,
            )
            if results.objects:
                original_fdc = results.objects[0].properties
        if not original_fdc and original_ingredient_name:
            # Search by description
            results = fdc_collection.query.bm25(
                query=original_ingredient_name,
                limit=1,
            )
            logger.debug(
                "substitute_tool: bm25 original | query=%s | results=%s",
                original_ingredient_name,
                len(results.objects) if results and results.objects else 0,
            )
            if results.objects:
                original_fdc = results.objects[0].properties
                original_fdc_id = original_fdc.get("fdc_id")
                original_fdc_id_int = _to_int_or_none(original_fdc_id)
        if not original_fdc and matched_ing and matched_names:
            # Fallback: try alternative names from plan ingredient map
            for alt_name in matched_names:
                if not alt_name:
                    continue
                results = fdc_collection.query.bm25(
                    query=alt_name,
                    limit=1,
                )
                logger.debug(
                    "substitute_tool: bm25 fallback | query=%s | results=%s",
                    alt_name,
                    len(results.objects) if results and results.objects else 0,
                )
                if results.objects:
                    original_fdc = results.objects[0].properties
                    original_fdc_id = original_fdc.get("fdc_id")
                    original_fdc_id_int = _to_int_or_none(original_fdc_id)
                    logger.debug(
                        "substitute_tool: resolved ingredient via fallback name '%s' -> fdc_id=%s",
                        alt_name,
                        original_fdc_id,
                    )
                    break
        
        if not original_fdc:
            logger.error(
                "substitute_tool: Ingredient not found after fallback | name=%s | fdc_id=%s | plan_id=%s | source=%s",
                original_ingredient_name,
                original_fdc_id,
                plan.get("plan_id") if plan else None,
                plan_source,
            )
            yield Error(f"Ingredient not found: {original_ingredient_name or original_fdc_id}")
            return
        
        # Get original macros (per 100g)
        original_macros = {
            "kcal": _safe_float(original_fdc.get("energy_kcal_100g")),
            "protein_g": _safe_float(original_fdc.get("protein_g_100g")),
            "fat_g": _safe_float(original_fdc.get("fat_g_100g")),
            "carb_g": _safe_float(original_fdc.get("carbohydrate_g_100g")),
        }
        
        # Step 3: Suggest substitutes (unless substitute_fdc_id provided)
        suggestions = []
        if substitute_fdc_id:
            # Direct apply mode - fetch substitute
            sub_filter = build_filters_from_where(
                {"path": ["fdc_id"], "operator": "Equal", "valueInt": int(substitute_fdc_id)}
            )
            sub_results = fdc_collection.query.fetch_objects(filters=sub_filter, limit=1)
            if not sub_results.objects:
                yield Error(f"Substitute FDC ID {substitute_fdc_id} not found")
                return
            substitute_fdc = sub_results.objects[0].properties
            suggestions = [{
                "fdc_id": substitute_fdc_id,
                "description": substitute_fdc.get("description", ""),
                "macros_per_100g": {
                    "kcal": _safe_float(substitute_fdc.get("energy_kcal_100g")),
                    "protein_g": _safe_float(substitute_fdc.get("protein_g_100g")),
                    "fat_g": _safe_float(substitute_fdc.get("fat_g_100g")),
                    "carb_g": _safe_float(substitute_fdc.get("carbohydrate_g_100g")),
                },
                "match_score": 100.0,  # Assume perfect match for direct apply
            }]
        else:
            # Search for similar foods
            search_query = original_ingredient_name if original_ingredient_name else original_fdc.get("description", "")
            search_results = fdc_collection.query.bm25(
                query=search_query,
                limit=100,
            )
            logger.debug(
                "substitute_tool: bm25 substitutes | query=%s | results=%s",
                search_query,
                len(search_results.objects) if search_results and search_results.objects else 0,
            )
            
            # Score and rank substitutes
            scored_substitutes = []
            for obj in search_results.objects:
                substitute = obj.properties
                sub_fdc_id = substitute.get("fdc_id")
                sub_fdc_id_int = _to_int_or_none(sub_fdc_id)
                if sub_fdc_id_int is None:
                    continue  # skip entries without valid FDC id
                if sub_fdc_id_int is not None and sub_fdc_id_int == original_fdc_id_int:
                    continue  # Skip original
                
                sub_macros = {
                    "kcal": _safe_float(substitute.get("energy_kcal_100g")),
                    "protein_g": _safe_float(substitute.get("protein_g_100g")),
                    "fat_g": _safe_float(substitute.get("fat_g_100g")),
                    "carb_g": _safe_float(substitute.get("carbohydrate_g_100g")),
                }
                
                match_score = _macro_match_score(original_macros, sub_macros, tolerance)
                if match_score > 0:
                    scored_substitutes.append({
                        "fdc_id": sub_fdc_id_int or sub_fdc_id,
                        "description": substitute.get("description", ""),
                        "macros_per_100g": sub_macros,
                        "match_score": match_score,
                    })
            
            # Sort by match score and take top_k
            scored_substitutes.sort(key=lambda x: x.get("match_score", 0.0), reverse=True)
            suggestions = scored_substitutes[:top_k]
        
        if not suggestions:
            yield Response("⚠️ No suitable substitutes found within ±20% macro tolerance")
            return
        
        # Step 4: Check allergens (if plan available)
        if plan:
            filters_results = tree_data.environment.find("constraints_guard_tool", "filters")
            if filters_results and filters_results[0]["objects"]:
                filters_metadata = filters_results[0].get("metadata") or {}
                exclude_allergens = filters_metadata.get("exclude_allergens", [])
        
        # Filter suggestions by allergens (if constraints available)
        if exclude_allergens:
            # Note: FdcFood doesn't have allergens field, so we can't filter here
            # This would require Recipe-level allergen checking
            pass
        
        # Yield suggestions
        substitutes_output = {
            "original_ingredient": {
                "name": original_ingredient_name or original_fdc.get("description", ""),
                "fdc_id": original_fdc_id,
                "macros_per_100g": original_macros,
            },
            "substitutes": suggestions,
            "count": len(suggestions),
            "tolerance": tolerance,
        }
        
        yield Result(
            name="substitutes",
            objects=[substitutes_output],
            metadata={
                "substitute_count": len(suggestions),
                "tolerance": tolerance,
            },
            payload_type="generic",
            display=True,
        )
        
        yield Result(
            name="substitutes_table",
            objects=suggestions,
            metadata={
                "substitute_count": len(suggestions),
                "tolerance": tolerance,
            },
            payload_type="table",
            display=True,
        )
        
        if suggestions:
            yield Response(f"✅ Found {len(suggestions)} substitute suggestion(s)")
        
        # Step 5: Optionally apply best substitute to plan
        if (auto_apply or substitute_fdc_id) and plan:
            best_substitute = suggestions[0]
            target_substitute_fdc_id = substitute_fdc_id or best_substitute.get("fdc_id")
            
            sub_name = best_substitute.get('description', 'Unknown')
            yield Response(f"🔄 Applying substitute: {sub_name}")
            
            # Apply substitute to recipes in plan
            try:
                recipe_collection = client.collections.get("Recipe")
            except Exception as e:
                yield Error(f"Recipe collection not found: {str(e)}. Please ensure collections are created.")
                return
            updated_recipes = []
            
            # Find recipes in plan that use original ingredient
            recipes_to_update = []
            if plan.get("plan_type") == "day":
                for meal_data in plan.get("meals", {}).values():
                    recipe = meal_data.get("recipe", {})
                    if recipe.get("food_id"):
                        recipes_to_update.append((recipe, meal_data))
            elif plan.get("plan_type") == "week":
                for day_data in plan.get("days", {}).values():
                    for meal_data in day_data.get("meals", {}).values():
                        recipe = meal_data.get("recipe", {})
                        if recipe.get("food_id"):
                            recipes_to_update.append((recipe, meal_data))

            # Helper: match ingredient by fdc_id or name when fdc_id missing
            def _uses_original(ing_entry: Dict[str, Any]) -> bool:
                if not isinstance(ing_entry, dict):
                    return False
                fdc_match = False
                name_match = False
                entry_fdc = _to_int_or_none(ing_entry.get("fdc_id"))
                if original_fdc_id_int is not None and entry_fdc is not None:
                    fdc_match = entry_fdc == original_fdc_id_int
                if not fdc_match and original_ingredient_name:
                    candidate_fields = [
                        str(ing_entry.get("ingredient_vn", "")),
                        str(ing_entry.get("ingredient_en", "")),
                        str(ing_entry.get("ingredient", "")),
                        str(ing_entry.get("name", "")),
                        str(ing_entry.get("description", "")),
                    ]
                    needle = original_ingredient_name.lower()
                    name_match = any(needle in field.lower() for field in candidate_fields if field)
                return fdc_match or name_match

            if recipe_level:
                # Replace whole recipes with beef recipes matched by macros/name
                from MealAgent.tools.utils.planning_helpers import _get_meal_macros

                def _recipe_match_score(original_recipe: Dict[str, Any], candidate: Dict[str, Any]) -> float:
                    orig_macros = _get_meal_macros(original_recipe)
                    cand_macros = _get_meal_macros(candidate)
                    return _macro_match_score(orig_macros, cand_macros, tolerance)

                for recipe, meal_data in recipes_to_update:
                    food_id = recipe.get("food_id")
                    ingredient_map = recipe.get("ingredient_fdc_map", [])
                    if not any(_uses_original(ing) for ing in ingredient_map):
                        continue
                    search_name = f"{recipe.get('dish_name', original_ingredient_name)} thịt bò"
                    candidate_results = recipe_collection.query.bm25(query=search_name, limit=50)
                    logger.debug(
                        "substitute_tool: recipe-level bm25 | query=%s | results=%s",
                        search_name,
                        len(candidate_results.objects) if candidate_results and candidate_results.objects else 0,
                    )
                    scored = []
                    for obj in candidate_results.objects:
                        cand = obj.properties
                        # Skip if not beef-ish
                        desc = (cand.get("dish_name") or cand.get("description") or "").lower()
                        if "bò" not in desc and "beef" not in desc:
                            continue
                        score = _recipe_match_score(recipe, cand)
                        if score > 0:
                            scored.append((score, cand))
                    if not scored:
                        continue
                    scored.sort(key=lambda x: x[0], reverse=True)
                    best_cand = scored[0][1]
                    meal_data["recipe"] = best_cand
                    updated_recipes.append(food_id)

                if not updated_recipes:
                    yield Response(f"ℹ️ No recipes in plan use ingredient with FDC ID {original_fdc_id}")
                    return
            else:
                # Ingredient-level replacement
                # Get substitute FDC data
                sub_filter = build_filters_from_where(
                    {"path": ["fdc_id"], "operator": "Equal", "valueInt": int(target_substitute_fdc_id)}
                )
                sub_results = fdc_collection.query.fetch_objects(filters=sub_filter, limit=1)
                if not sub_results.objects:
                    yield Error(f"Substitute FDC ID {target_substitute_fdc_id} not found")
                    return
                substitute_fdc = sub_results.objects[0].properties

                # Update recipes that contain the original ingredient
                for recipe, meal_data in recipes_to_update:
                    food_id = recipe.get("food_id")
                    ingredient_map = recipe.get("ingredient_fdc_map", [])
                    
                    # Check if recipe uses original ingredient
                    uses_original = False
                    updated_map = []
                    for ing_entry in ingredient_map:
                        if _uses_original(ing_entry):
                            uses_original = True
                            # Replace with substitute
                            updated_map.append({
                                **ing_entry,
                                "fdc_id": target_substitute_fdc_id,
                                "ingredient_en": substitute_fdc.get("description", ing_entry.get("ingredient_en", "")),
                            })
                        else:
                            updated_map.append(ing_entry)
                    
                    if uses_original:
                        # Update recipe in Weaviate
                        recipe_filter = build_filters_from_where(
                            {"path": ["food_id"], "operator": "Equal", "valueString": food_id}
                        )
                        recipe_results = recipe_collection.query.fetch_objects(filters=recipe_filter, limit=1)
                        if recipe_results.objects:
                            recipe_obj = recipe_results.objects[0]
                            recipe_obj.properties["ingredient_fdc_map"] = updated_map
                            recipe_collection.data.update(uuid=recipe_obj.uuid, properties=recipe_obj.properties)
                            
                            # Update recipe in plan
                            recipe["ingredient_fdc_map"] = updated_map
                            updated_recipes.append(food_id)

                if not updated_recipes:
                    yield Response(f"ℹ️ No recipes in plan use ingredient with FDC ID {original_fdc_id}")
                    return
            
            # Recalculate macros if requested
            macros_recalculated = False
            if recalculate_macros and base_lm:
                yield Response("Recalculating recipe macros after substitution...")
                for food_id in updated_recipes:
                    try:
                        async for result in calculate_recipe_macros_tool(
                            inputs={"recipe_id": str(food_id)},
                            complex_lm=None,
                            tree_data=tree_data,
                            client_manager=client_manager,
                            base_lm=base_lm,
                        ):
                            if isinstance(result, Error):
                                yield Response(f"Warning: Failed to recalculate macros for recipe {food_id}")
                                break
                        macros_recalculated = True
                    except Exception as e:
                        logging.warning(f"substitute_tool: Error recalculating macros for recipe {food_id}: {str(e)}")
                        yield Response(f"Warning: Error recalculating macros for recipe {food_id}")
            elif recalculate_macros and not base_lm:
                yield Response("Warning: base_lm not provided. Macros not recalculated.")
            
            # Recalculate plan totals
            from MealAgent.tools.utils.planning_helpers import _get_meal_macros
            total_macros = {"kcal": 0.0, "protein_g": 0.0, "fat_g": 0.0, "carb_g": 0.0}
            if plan.get("plan_type") == "day":
                for meal_data in plan.get("meals", {}).values():
                    recipe = meal_data.get("recipe", {})
                    servings = meal_data.get("servings", 1.0)
                    macros = _get_meal_macros(recipe)
                    for key in total_macros:
                        total_macros[key] += macros[key] * servings
            elif plan.get("plan_type") == "week":
                for day_data in plan.get("days", {}).values():
                    for meal_data in day_data.get("meals", {}).values():
                        recipe = meal_data.get("recipe", {})
                        servings = meal_data.get("servings", 1.0)
                        macros = _get_meal_macros(recipe)
                        for key in total_macros:
                            total_macros[key] += macros[key] * servings
                plan["average_daily_macros"] = {
                    "kcal": total_macros["kcal"] / 7.0,
                    "protein_g": total_macros["protein_g"] / 7.0,
                    "fat_g": total_macros["fat_g"] / 7.0,
                    "carb_g": total_macros["carb_g"] / 7.0,
                }
            plan["total_macros"] = total_macros

            persist_user_id = plan_user_id or user_id
            if persist_user_id:
                plan = sync_plan_to_weaviate(
                    plan,
                    user_id=persist_user_id,
                    client_manager=client_manager,
                    start_date=plan.get("start_date"),
                )
            
            yield Result(
                name="updated_plan",
                objects=[plan],
                metadata={
                    "plan_type": plan.get("plan_type"),
                    "recipes_updated": len(updated_recipes),
                    "original_fdc_id": original_fdc_id,
                    "substitute_fdc_id": target_substitute_fdc_id,
                    "macros_recalculated": macros_recalculated,
                    "plan_id": plan.get("plan_id"),
                },
                payload_type="meal_plan",  # Use meal_plan for frontend detection
                display=True,
            )
            
            if macros_recalculated:
                yield Response(
                    f"✅ Substitute applied to {len(updated_recipes)} recipe(s). "
                    f"Nutritional values updated."
                )
            else:
                yield Response(
                    f"✅ Substitute applied to {len(updated_recipes)} recipe(s). "
                    f"Note: Run calculate_recipe_macros_tool to update macros."
                )
        
    except ValueError as e:
        error_msg = f"Invalid input: {str(e)}"
        logging.error(f"substitute_tool: {error_msg}", exc_info=True)
        yield Error(error_msg)
        return
    except Exception as e:
        error_msg = f"substitute_tool failed: {str(e)}"
        logging.error(f"substitute_tool: {error_msg}", exc_info=True)
        yield Error(error_msg)
        return

