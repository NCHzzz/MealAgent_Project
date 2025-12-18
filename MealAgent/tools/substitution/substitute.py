"""
End-to-end substitution tool: suggest substitutes → optionally apply to plan.
"""
from typing import AsyncGenerator, Dict, Any, List
import copy
import logging
import random
from difflib import SequenceMatcher

from elysia.tree.objects import TreeData
from elysia.objects import Result, Error, Response
from elysia.util.client import ClientManager
from elysia import tool
from MealAgent.tools.utils.weaviate_filters import build_filters_from_where
from MealAgent.tools.utils.planning_helpers import sync_plan_to_weaviate, _get_meal_macros

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
    original_dish_name: str | None = None,  # NEW: dish name to replace (e.g., "bún thang")
    **kwargs,
) -> AsyncGenerator[Result | Response | Error, None]:
    """
    Purpose (tree-friendly):
      Swap entire dishes in the current plan with new dishes that actually contain the user-requested ingredient
      (e.g., replace fish dish → beef dish), while keeping meal type and macros close.

    Behavior:
      - Always recipe-level; no ingredient-level edits.
      - Candidate recipes must mention/contain the desired ingredient (name or ingredient map).
      - Supports selecting the dish to replace by name via `original_dish_name` (e.g., "bún thang").
      - Prefers plan from DB (plan_id if given, else latest day/week); validates user_id if present.
      - Recomputes per-meal macros (including accompaniments) and plan totals after swap.
      - Optionally recalculates recipe macros via base_lm, then syncs plan to Weaviate.

    Key inputs:
      - ingredient_name (or desired_ingredient): ingredient that must appear in the new dish (e.g., "thịt bò").
      - original_dish_name (optional): dish name in the plan to replace (e.g., "bún thang").
      - fdc_id / replace_ingredient (optional): helps detect which dishes to replace; if missing, seafood dishes are targeted.
      - tolerance: macro similarity tolerance (default 0.2).
      - auto_apply: if True, apply and persist changes.
      - base_lm: LM for macro recalculation (optional; without it, recipe macros are not recomputed).

    Outputs:
      - Result `updated_plan` (payload_type="meal_plan") when changes applied.
      - Responses/errors guiding next actions.
    """
    logging.info("substitute_tool: start (recipe-level only)")
    yield Response("🔄 Đang tìm món thay thế chứa nguyên liệu bạn yêu cầu...")

    try:
        # Normalise user_id early and try to recover from hidden environment if missing/invalid
        normalized_user_id: str | None = None
        if user_id is not None:
            uid_str = str(user_id).strip()
            if uid_str and uid_str.lower() not in {"none", "null"}:
                normalized_user_id = uid_str
        if normalized_user_id is None:
            # Try to read from hidden environment where build_meal_agent_tree stores it
            try:
                hidden_uid = tree_data.environment.hidden_environment.get("user_id")
                if hidden_uid:
                    normalized_user_id = str(hidden_uid).strip()
            except Exception:
                normalized_user_id = None
        user_id = normalized_user_id

        # Desired ingredient for the NEW dish (e.g., "thịt bò", "cơm trắng")
        desired_ingredient = kwargs.get("desired_ingredient") or kwargs.get("substitute_ingredient") or ingredient_name
        if not desired_ingredient:
            yield Error("Bạn cần cung cấp nguyên liệu mong muốn cho món thay thế (vd: 'thịt bò').")
            return
        desired_ingredient = str(desired_ingredient).strip()

        # Original ingredient/FDC used to detect dishes to replace (optional)
        original_fdc_id = fdc_id
        replace_keyword = (
            kwargs.get("replace_ingredient")
            or kwargs.get("original_ingredient")
            or original_dish_name
            or ""
        )
        replace_kw = str(replace_keyword).lower().strip()
        if not original_dish_name:
            original_dish_name = kwargs.get("original_dish") or kwargs.get("target_dish_name") or None

        # Always recipe-level
        recipe_level = True

        # Prefer explicit base_lm, but allow legacy kwargs path
        base_lm = base_lm or kwargs.get("base_lm")

        # Helpers
        def _iter_plan_recipes(
            plan_obj: Dict[str, Any]
        ) -> List[tuple[Dict[str, Any], Dict[str, Any], str, int | None]]:
            """
            Yield (recipe, meal_data, role, acc_index) tuples from a plan.

            - role: "main" or "accompaniment"
            - acc_index: index in accompaniments list when role == "accompaniment", else None
            """
            recipes: List[tuple[Dict[str, Any], Dict[str, Any], str, int | None]] = []
            if not plan_obj:
                return recipes
            if plan_obj.get("plan_type") == "day":
                for meal_data in plan_obj.get("meals", {}).values():
                    if meal_data.get("recipe"):
                        recipes.append((meal_data["recipe"], meal_data, "main", None))
                    for idx, acc in enumerate(meal_data.get("accompaniments", []) or []):
                        if isinstance(acc, dict) and acc.get("recipe"):
                            recipes.append((acc["recipe"], meal_data, "accompaniment", idx))
            elif plan_obj.get("plan_type") == "week":
                for day_data in plan_obj.get("days", {}).values():
                    for meal_data in day_data.get("meals", {}).values():
                        if meal_data.get("recipe"):
                            recipes.append((meal_data["recipe"], meal_data, "main", None))
                        for idx, acc in enumerate(meal_data.get("accompaniments", []) or []):
                            if isinstance(acc, dict) and acc.get("recipe"):
                                recipes.append((acc["recipe"], meal_data, "accompaniment", idx))
            return recipes

        def _meal_type_hint(meal_data: Dict[str, Any]) -> str:
            return str(meal_data.get("meal_type") or meal_data.get("type") or "").lower()

        def _is_seafood_word(text: str) -> bool:
            txt = text.lower()
            seafood_keywords = ["cá", "fish", "tôm", "shrimp", "mực", "squid", "cua", "crab", "seafood"]
            return any(k in txt for k in seafood_keywords)

        def _recipe_contains_fdc(recipe: Dict[str, Any], fdc: int | None, name_kw: str | None) -> bool:
            ing_map = recipe.get("ingredient_fdc_map", []) or []
            needle = (name_kw or "").lower()
            for ing in ing_map:
                if not isinstance(ing, dict):
                    continue
                fdc_val = _to_int_or_none(ing.get("fdc_id"))
                if fdc is not None and fdc_val == fdc:
                    return True
                if needle:
                    for field in [
                        str(ing.get("ingredient_vn", "")),
                        str(ing.get("ingredient_en", "")),
                        str(ing.get("ingredient", "")),
                        str(ing.get("name", "")),
                        str(ing.get("description", "")),
                    ]:
                        if field and needle in field.lower():
                            return True
            return False

        def _recipe_mentions_desired(recipe: Dict[str, Any]) -> bool:
            ing_map = recipe.get("ingredient_fdc_map", []) or []
            needle = desired_ingredient.lower()
            for ing in ing_map:
                if not isinstance(ing, dict):
                    continue
                for field in [
                    str(ing.get("ingredient_vn", "")),
                    str(ing.get("ingredient_en", "")),
                    str(ing.get("ingredient", "")),
                    str(ing.get("name", "")),
                    str(ing.get("description", "")),
                ]:
                    if field and needle in field.lower():
                        return True
            # also check dish_name/description
            for field in [recipe.get("dish_name", ""), recipe.get("description", "")]:
                if field and needle in str(field).lower():
                    return True
            return False

        # Load plan
        # Priority:
        #   1) Explicit plan_id (most precise)
        #   2) Plan objects already in this tree's environment (from plan_day/plan_week)
        #   3) Latest saved day/week plan from Weaviate for this user
        exclude_allergens: List[str] = []
        plan: Dict[str, Any] | None = None
        plan_source: str | None = None

        def _plan_has_meals(p: Dict[str, Any] | None) -> bool:
            if not p:
                return False
            if p.get("plan_type") == "day":
                return any(
                    isinstance(md, dict) and md.get("recipe") for md in p.get("meals", {}).values()
                )
            if p.get("plan_type") == "week":
                for day_data in p.get("days", {}).values():
                    for md in day_data.get("meals", {}).values():
                        if isinstance(md, dict) and md.get("recipe"):
                            return True
            return False

        if plan_id:
            # Hard preference for an explicit plan_id if the agent/tool caller provided one
            from MealAgent.tools.utils.plan_loader import load_plan_from_weaviate

            plan = load_plan_from_weaviate(plan_id, client_manager, user_id)
            if plan:
                plan_source = (plan.get("plan_type", "day") or "day") + "_plan_db"

        if plan is None:
            # Prefer the plan that was just generated in this conversation (environment cache)
            day_plan_results = tree_data.environment.find("plan_day_e2e_tool", "plan")
            if day_plan_results and day_plan_results[0].get("objects"):
                plan = copy.deepcopy(day_plan_results[0]["objects"][0])
                plan_source = "plan_day_e2e_tool_env"
            else:
                week_plan_results = tree_data.environment.find("plan_week_e2e_tool", "plan")
                if week_plan_results and week_plan_results[0].get("objects"):
                    plan = copy.deepcopy(week_plan_results[0]["objects"][0])
                    plan_source = "plan_week_e2e_tool_env"

        if plan is None and user_id:
            # Fallback to latest persisted plan for this user (day first, then week)
            from MealAgent.tools.utils.plan_loader import load_latest_plan_from_weaviate

            plan = load_latest_plan_from_weaviate(user_id, client_manager, "day")
            if plan:
                plan_source = "latest_day_plan_db"
            if not plan:
                plan = load_latest_plan_from_weaviate(user_id, client_manager, "week")
                if plan:
                    plan_source = "latest_week_plan_db"

        # If plan loaded but contains no meals (e.g., failed item sync), fallback to environment cache
        if plan and not _plan_has_meals(plan):
            env_day = tree_data.environment.find("plan_day_e2e_tool", "plan")
            env_week = tree_data.environment.find("plan_week_e2e_tool", "plan")
            if env_day and env_day[0]["objects"]:
                plan = copy.deepcopy(env_day[0]["objects"][0])
                plan_source = "plan_day_e2e_tool_env_fallback"
            elif env_week and env_week[0]["objects"]:
                plan = copy.deepcopy(env_week[0]["objects"][0])
                plan_source = "plan_week_e2e_tool_env_fallback"

        if not plan:
            yield Error("Không tìm thấy kế hoạch để thay món.")
            return

        plan_user_id = plan.get("user_id") or user_id
        if user_id and plan_user_id and plan_user_id != user_id:
            yield Error(f"Plan {plan.get('plan_id')} không thuộc user {user_id}")
            return

        if plan and (plan.get("plan_id") or plan_id):
            plan["plan_id"] = plan.get("plan_id") or plan_id
        logger.debug(
            "substitute_tool: plan loaded | plan_id=%s | source=%s | user_id=%s | original_dish_name=%s | replace_kw=%s",
            plan.get("plan_id"),
            plan_source,
            plan_user_id,
            original_dish_name,
            replace_kw,
        )

        # ------------------------------------------------------------------
        # SPECIAL CASE: User wants to *add* white rice (cơm trắng) to dinner
        # rather than replace the entire dish. This is a very common pattern:
        #   - "thêm cơm trắng vào bữa tối"
        #   - "thêm cơm trắng ăn kèm với thịt bò"
        #
        # For this specific ingredient, we interpret the request as:
        #   "giữ món chính hiện tại và thêm một side 'Cơm Trắng'"
        # instead of substituting the whole dinner with a different rice dish.
        # ------------------------------------------------------------------
        def _is_white_rice_phrase(text: str | None) -> bool:
            if not text:
                return False
            lowered = str(text).lower()
            return "cơm trắng" in lowered or "com trang" in lowered or "white rice" in lowered

        if _is_white_rice_phrase(desired_ingredient) and plan.get("plan_type") == "day":
            # Try to locate the dinner meal – prefer the one whose main dish
            # matches original_dish_name (if provided).
            target_name = (original_dish_name or "").strip().lower()
            dinner_meal: Dict[str, Any] | None = None

            for meal_data in plan.get("meals", {}).values():
                if not isinstance(meal_data, dict):
                    continue
                meal_type = str(meal_data.get("meal_type") or meal_data.get("type") or "").lower()
                if meal_type != "dinner":
                    continue
                recipe = meal_data.get("recipe") or {}
                dish_name = str(recipe.get("dish_name", "")).lower()
                if target_name and target_name in dish_name:
                    dinner_meal = meal_data
                    break

            # Fallback: if we didn't find by name, pick the first dinner meal
            if dinner_meal is None:
                for meal_data in plan.get("meals", {}).values():
                    if not isinstance(meal_data, dict):
                        continue
                    meal_type = str(meal_data.get("meal_type") or meal_data.get("type") or "").lower()
                    if meal_type == "dinner":
                        dinner_meal = meal_data
                        break

            if dinner_meal is None:
                logger.debug("substitute_tool: no dinner meal found to add white rice to, continuing with normal substitution flow")
            else:
                # Check if dinner already has a rice accompaniment to avoid duplicates
                accompaniments = list(dinner_meal.get("accompaniments") or [])
                has_rice = False
                for acc in accompaniments:
                    if not isinstance(acc, dict):
                        continue
                    acc_recipe = acc.get("recipe") or {}
                    rid = str(acc_recipe.get("food_id") or acc_recipe.get("recipe_id") or "")
                    acc_name = str(acc_recipe.get("dish_name", "")).lower()
                    if rid == "default_white_rice" or "cơm trắng" in acc_name or "com trang" in acc_name or "white rice" in acc_name:
                        has_rice = True
                        break

                if not has_rice:
                    try:
                        from MealAgent.tools.plan_day.plan_day_e2e import _create_default_white_rice_recipe

                        rice_recipe = _create_default_white_rice_recipe()
                        accompaniments.append(
                            {
                                "recipe": rice_recipe,
                                "servings": 1.0,
                                "type": "carb",
                            }
                        )
                        dinner_meal["accompaniments"] = accompaniments
                        logger.debug(
                            "substitute_tool: added default white rice accompaniment to dinner for plan_id=%s",
                            plan.get("plan_id"),
                        )
                    except Exception as e:
                        logger.warning(f"substitute_tool: failed to create default white rice recipe: {e}")

                # Recompute macros for dinner only and then for the whole plan
                # using the same helper logic as the standard substitution path.
                from math import isfinite

                def _recompute_meal_macros_for_rice(meal_obj: Dict[str, Any]) -> Dict[str, float]:
                    recipe = meal_obj.get("recipe", {}) if isinstance(meal_obj, dict) else {}
                    servings = meal_obj.get("servings", 1.0) if isinstance(meal_obj, dict) else 1.0
                    macros = _get_meal_macros(recipe)
                    total = {k: macros.get(k, 0.0) * servings for k in ["kcal", "protein_g", "fat_g", "carb_g"]}
                    for acc in meal_obj.get("accompaniments", []):
                        if not isinstance(acc, dict):
                            continue
                        acc_recipe = acc.get("recipe", {})
                        acc_serv = acc.get("servings", 1.0)
                        acc_macros = _get_meal_macros(acc_recipe)
                        for k in total:
                            total[k] += acc_macros.get(k, 0.0) * acc_serv
                    meal_obj["macros"] = macros
                    meal_obj["macros_total"] = total
                    return total

                total_macros = {"kcal": 0.0, "protein_g": 0.0, "fat_g": 0.0, "carb_g": 0.0}
                if plan.get("plan_type") == "day":
                    for meal_data in plan.get("meals", {}).values():
                        if not isinstance(meal_data, dict):
                            continue
                        meal_tot = _recompute_meal_macros_for_rice(meal_data)
                        for k in total_macros:
                            # Guard against NaNs from malformed recipes
                            val = meal_tot.get(k, 0.0)
                            total_macros[k] += val if isfinite(val) else 0.0
                plan["total_macros"] = total_macros

                # Persist updated plan back to Weaviate
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
                        "recipes_updated": 0,
                        "original_fdc_id": original_fdc_id,
                        "desired_ingredient": desired_ingredient,
                        "macros_recalculated": False,
                        "plan_id": plan.get("plan_id"),
                        "note": "added_default_white_rice_to_dinner",
                    },
                    payload_type="meal_plan",
                    display=True,
                )

                yield Result(
                    name="optimization_done",
                    objects=[{"message": "optimization_complete"}],
                    metadata={
                        "stop_calling_tool": True,
                        "end_conversation": False,
                        "task_complete": True,
                        "plan_id": plan.get("plan_id"),
                    },
                    payload_type="generic",
                    display=False,
                )

                yield Response("✅ Đã thêm cơm trắng vào bữa tối của bạn (không thay đổi món chính hiện tại).")
                return

        # Constraints (allergens)
        filters_results = tree_data.environment.find("constraints_guard_tool", "filters")
        if filters_results and filters_results[0]["objects"]:
            filters_metadata = filters_results[0].get("metadata") or {}
            exclude_allergens = filters_metadata.get("exclude_allergens", [])

        # Build list of recipes to replace (score, recipe, meal_data, role, acc_idx)
        original_fdc_id_int = _to_int_or_none(original_fdc_id)
        recipes_to_replace: List[Dict[str, Any]] = []

        def _name_match_score(dish_name: str, keyword: str) -> float:
            dn = dish_name.lower()
            kw = keyword.lower()
            if not kw:
                return 0.0
            if dn == kw:
                return 3.0
            if kw in dn:
                return 2.0
            return 0.0

        def _collect_candidates(target_plan: Dict[str, Any]) -> List[Dict[str, Any]]:
            matches: List[Dict[str, Any]] = []
            for recipe, meal_data, role, acc_idx in _iter_plan_recipes(target_plan):
                dish_name = str(recipe.get("dish_name", "")).lower()
                ingredient_hit = _recipe_contains_fdc(recipe, original_fdc_id_int, replace_kw) if (original_fdc_id_int or replace_kw) else False
                seafood_hit = _is_seafood_word(dish_name)
                if not seafood_hit:
                    ing_map = recipe.get("ingredient_fdc_map", []) or []
                    for ing in ing_map:
                        if not isinstance(ing, dict):
                            continue
                        for field in [
                            ing.get("ingredient_vn"),
                            ing.get("ingredient_en"),
                            ing.get("ingredient"),
                            ing.get("name"),
                            ing.get("description"),
                        ]:
                            if field and _is_seafood_word(str(field).lower()):
                                seafood_hit = True
                                break
                        if seafood_hit:
                            break

                name_score = _name_match_score(dish_name, replace_kw) if replace_kw else 0.0

                select = False
                if original_fdc_id_int is not None:
                    select = ingredient_hit or seafood_hit
                else:
                    if replace_kw:
                        select = ingredient_hit or seafood_hit or name_score > 0
                    else:
                        select = seafood_hit

                if select:
                    if role == "accompaniment":
                        name_score += 0.2
                    matches.append(
                        {
                            "score": max(1e-6, name_score if replace_kw else 1.0),
                            "recipe": recipe,
                            "meal_data": meal_data,
                            "role": role,
                            "acc_idx": acc_idx,
                        }
                    )
            return matches

        recipes_to_replace = _collect_candidates(plan)

        if replace_kw and recipes_to_replace:
            best_score = max(m["score"] for m in recipes_to_replace)
            recipes_to_replace = [m for m in recipes_to_replace if m["score"] == best_score]
            logger.debug(
                "substitute_tool: selected replacements by name | count=%d | best_score=%.3f | dishes=%s",
                len(recipes_to_replace),
                best_score,
                [m["recipe"].get("dish_name") for m in recipes_to_replace],
            )
        else:
            logger.debug(
                "substitute_tool: replacements built | count=%d | replace_kw=%s | fdc_id=%s | dishes=%s",
                len(recipes_to_replace),
                replace_kw,
                original_fdc_id_int,
                [m["recipe"].get("dish_name") for m in recipes_to_replace],
            )

        if not recipes_to_replace:
            scanned = [str(r.get("dish_name", "")) for _, r, _, _, _ in _iter_plan_recipes(plan)]
            logger.debug(
                "substitute_tool: no recipes_to_replace from plan_id=%s | scanned=%s",
                plan.get("plan_id"),
                scanned,
            )

            env_day = tree_data.environment.find("plan_day_e2e_tool", "plan")
            env_week = tree_data.environment.find("plan_week_e2e_tool", "plan")
            fallback_plan = None
            if env_day and env_day[0]["objects"]:
                fallback_plan = copy.deepcopy(env_day[0]["objects"][0])
                plan_source = "plan_day_e2e_tool_env_retry"
            elif env_week and env_week[0]["objects"]:
                fallback_plan = copy.deepcopy(env_week[0]["objects"][0])
                plan_source = "plan_week_e2e_tool_env_retry"

            if fallback_plan:
                plan = fallback_plan
                recipes_to_replace = _collect_candidates(plan)
                if replace_kw and recipes_to_replace:
                    best_score_fb = max(m["score"] for m in recipes_to_replace)
                    recipes_to_replace = [m for m in recipes_to_replace if m["score"] == best_score_fb]
                    logger.debug(
                        "substitute_tool: env-fallback replacements by name | count=%d | best_score=%.3f | dishes=%s",
                        len(recipes_to_replace),
                        best_score_fb,
                        [m["recipe"].get("dish_name") for m in recipes_to_replace],
                    )
                if recipes_to_replace:
                    logger.debug(
                        "substitute_tool: recovered recipes_to_replace via env fallback | count=%d | source=%s",
                        len(recipes_to_replace),
                        plan_source,
                    )

            if not recipes_to_replace:
                yield Error("Không tìm thấy món nào cần thay trong kế hoạch.")
                return

        # Query recipe candidates that contain desired ingredient
        client = client_manager.get_client()
        try:
            recipe_collection = client.collections.get("Recipe")
        except Exception as e:
            yield Error(f"Recipe collection not found: {str(e)}. Please ensure collections are created.")
            return

        search_query = f"{desired_ingredient}"
        candidate_results = recipe_collection.query.bm25(query=search_query, limit=30)
        logger.debug(
            "substitute_tool: recipe-level bm25 | query=%s | results=%s",
            search_query,
            len(candidate_results.objects) if candidate_results and candidate_results.objects else 0,
        )

        candidates: List[Dict[str, Any]] = []
        for obj in candidate_results.objects:
            cand = obj.properties
            if not _recipe_mentions_desired(cand):
                continue
            # Allergen filter (best-effort)
            allergens = cand.get("allergens") or []
            if exclude_allergens and isinstance(allergens, list):
                if any(a.lower() in [al.lower() for al in exclude_allergens] for a in allergens if isinstance(a, str)):
                    continue
            candidates.append(cand)

        if not candidates:
            yield Error(f"Không tìm thấy món nào chứa '{desired_ingredient}'.")
            return

        # Pre-compute textual relevance of each candidate to the user's requested ingredient/dish
        desired_lower = desired_ingredient.lower()
        desired_tokens = [t for t in desired_lower.split() if len(t) > 1]

        def _text_relevance(candidate: Dict[str, Any]) -> float:
            dish = str(candidate.get("dish_name") or candidate.get("description") or "").lower()
            if not dish:
                return 0.0

            # Strong boost when all meaningful tokens from the user phrase appear in the dish name
            if desired_tokens and all(tok in dish for tok in desired_tokens):
                return 100.0

            # Fallback: fuzzy similarity between requested phrase and dish name
            try:
                return SequenceMatcher(None, desired_lower, dish).ratio() * 100.0
            except Exception:
                return 0.0

        for cand in candidates:
            cand["_sub_text_score"] = _text_relevance(cand)

        # Scoring
        def _recipe_match_score(original_recipe: Dict[str, Any], candidate: Dict[str, Any]) -> float:
            orig_macros = _get_meal_macros(original_recipe)
            cand_macros = _get_meal_macros(candidate)
            if not orig_macros or not cand_macros:
                return 0.0
            return _macro_match_score(orig_macros, cand_macros, tolerance)

        updated_recipes: List[str] = []
        used_candidate_ids: set[str] = set()
        recipes_needing_macro_recalc: List[str] = []

        for entry in recipes_to_replace:
            recipe = entry["recipe"]
            meal_data = entry["meal_data"]
            role = entry["role"]
            acc_idx = entry["acc_idx"]
            logger.debug(
                "substitute_tool: replacing candidate | dish=%s | role=%s | acc_idx=%s | score=%.3f",
                recipe.get("dish_name"),
                role,
                acc_idx,
                entry.get("score", 0.0),
            )
            food_id = recipe.get("food_id")
            meal_hint = _meal_type_hint(meal_data)

            scored: List[tuple[float, Dict[str, Any]]] = []
            for cand in candidates:
                cand_id = cand.get("food_id") or cand.get("recipe_id") or cand.get("id")
                if cand_id in used_candidate_ids:
                    continue
                desc = (cand.get("dish_name") or cand.get("description") or "").lower()
                # Rough meal-type alignment (soft)
                if meal_hint and meal_hint in ["main", "protein"] and "salad" in desc:
                    pass
                macro_score = _recipe_match_score(recipe, cand)
                text_score = float(cand.get("_sub_text_score", 0.0))
                # Combine macro similarity (keep nutrition close) with textual relevance
                combined_score = macro_score * 0.7 + text_score * 0.3
                if combined_score > 0:
                    scored.append((combined_score, cand))

            # Fallback when macros are missing (score=0): use name similarity so we still swap
            if not scored and candidates:
                for cand in candidates:
                    cand_id = cand.get("food_id") or cand.get("recipe_id") or cand.get("id")
                    if cand_id in used_candidate_ids:
                        continue
                    name_sim = SequenceMatcher(
                        None, str(recipe.get("dish_name", "")), str(cand.get("dish_name", ""))
                    ).ratio()
                    # Keep a small floor score so we always have at least one option
                    scored.append((max(name_sim * 50, 1.0), cand))
                logger.debug(
                    "substitute_tool: macro-based scoring empty; using name similarity fallback for recipe %s",
                    food_id,
                )

            if not scored:
                logger.debug(f"substitute_tool: no candidates for recipe {food_id}")
                continue

            scored.sort(key=lambda x: x[0], reverse=True)
            top_n = min(8, max(3, len(scored)))
            top_candidates = scored[:top_n]

            weights = [c[0] ** 1.3 for c in top_candidates]
            selected = random.choices(top_candidates, weights=weights, k=1)[0]
            selected_cand = selected[1]
            sel_id = selected_cand.get("food_id") or selected_cand.get("recipe_id") or selected_cand.get("id")
            if sel_id:
                used_candidate_ids.add(sel_id)

            logger.debug(
                "substitute_tool: recipe replacement | original=%s | selected=%s | score=%.2f",
                recipe.get("dish_name", "unknown"),
                selected_cand.get("dish_name", "unknown"),
                selected[0],
            )

            if role == "main":
                meal_data["recipe"] = selected_cand
            else:
                # Replace within accompaniments by index when possible
                acc_list = meal_data.get("accompaniments") or []
                if isinstance(acc_idx, int) and 0 <= acc_idx < len(acc_list):
                    if isinstance(acc_list[acc_idx], dict):
                        acc_list[acc_idx]["recipe"] = selected_cand
                else:
                    # Fallback: append as new accompaniment to avoid losing the selection
                    acc_list = list(acc_list)
                    acc_list.append({"recipe": selected_cand, "servings": 1.0, "type": "main"})
                    meal_data["accompaniments"] = acc_list
            updated_recipes.append(str(food_id))

            # Only trigger expensive macro recalculation later if the selected candidate lacks macros
            cand_macros = _get_meal_macros(selected_cand)
            if (not cand_macros) and sel_id:
                recipes_needing_macro_recalc.append(str(sel_id))

        # Recalculate per-meal macros (including accompaniments) and plan totals
        def _recompute_meal_macros(meal_obj: Dict[str, Any]) -> Dict[str, float]:
            recipe = meal_obj.get("recipe", {}) if isinstance(meal_obj, dict) else {}
            servings = meal_obj.get("servings", 1.0) if isinstance(meal_obj, dict) else 1.0
            macros = _get_meal_macros(recipe)
            total = {k: macros.get(k, 0.0) * servings for k in ["kcal", "protein_g", "fat_g", "carb_g"]}
            # accompaniments
            for acc in meal_obj.get("accompaniments", []):
                if not isinstance(acc, dict):
                    continue
                acc_recipe = acc.get("recipe", {})
                acc_serv = acc.get("servings", 1.0)
                acc_macros = _get_meal_macros(acc_recipe)
                for k in total:
                    total[k] += acc_macros.get(k, 0.0) * acc_serv
            meal_obj["macros"] = macros
            meal_obj["macros_total"] = total
            return total

        total_macros = {"kcal": 0.0, "protein_g": 0.0, "fat_g": 0.0, "carb_g": 0.0}
        if plan.get("plan_type") == "day":
            for meal_data in plan.get("meals", {}).values():
                if not isinstance(meal_data, dict):
                    continue
                meal_tot = _recompute_meal_macros(meal_data)
                for k in total_macros:
                    total_macros[k] += meal_tot[k]
        elif plan.get("plan_type") == "week":
            for day_data in plan.get("days", {}).values():
                if not isinstance(day_data, dict):
                    continue
                day_total = {"kcal": 0.0, "protein_g": 0.0, "fat_g": 0.0, "carb_g": 0.0}
                for meal_data in day_data.get("meals", {}).values():
                    if not isinstance(meal_data, dict):
                        continue
                    meal_tot = _recompute_meal_macros(meal_data)
                    for k in day_total:
                        day_total[k] += meal_tot[k]
                day_data["total_macros"] = day_total
                for k in total_macros:
                    total_macros[k] += day_total[k]
            plan["average_daily_macros"] = {k: total_macros[k] / 7.0 for k in total_macros}
        plan["total_macros"] = total_macros

        macros_recalculated = False
        if recipes_needing_macro_recalc:
            if recalculate_macros and base_lm:
                yield Response("Recalculating recipe macros after substitution...")
                for food_id in recipes_needing_macro_recalc:
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
                "desired_ingredient": desired_ingredient,
                "macros_recalculated": macros_recalculated,
                "plan_id": plan.get("plan_id"),
            },
            payload_type="meal_plan",  # Use meal_plan for frontend detection
            display=True,
        )

        # Hint to decision agent: optimization task is done, avoid further tool calls unless user asks.
        yield Result(
            name="optimization_done",
            objects=[{"message": "optimization_complete"}],
            metadata={
                "stop_calling_tool": True,
                "end_conversation": False,  # allow summarize if user asks
                "task_complete": True,
                "plan_id": plan.get("plan_id"),
            },
            payload_type="generic",
            display=False,
        )

        if macros_recalculated:
            yield Response(
                f"✅ Đã thay {len(updated_recipes)} món và cập nhật dinh dưỡng."
            )
        else:
            yield Response(
                f"✅ Đã thay {len(updated_recipes)} món. Lưu ý: macros_recipe có thể cần tính lại nếu chưa cung cấp base_lm."
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
