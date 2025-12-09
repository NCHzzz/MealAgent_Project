"""
End-to-end gap fill tool: calculate deficits → suggest snacks → apply to plan.
"""
from typing import AsyncGenerator, Dict, Any, List
import copy
import logging
import re
import random

from elysia.tree.objects import TreeData
from elysia.objects import Result, Error, Response
from elysia.util.client import ClientManager
from elysia import tool

from MealAgent.tools.utils.planning_helpers import _get_meal_macros, sync_plan_to_weaviate
from MealAgent.tools.utils.weaviate_filters import build_filters_from_where
from MealAgent.tools.utils.profile_targets import ensure_macro_targets

# Helper to extract image link from recipe object
def _get_image_link(recipe: Dict[str, Any]) -> str:
    return (
        recipe.get("image_link")
        or recipe.get("image_url")
        or recipe.get("thumbnail")
        or ""
    )


DEFAULT_TARGETS = {
    "tdee_kcal": 2000.0,
    "protein_g": 110.0,
    "fat_g": 67.0,
    "carb_g": 250.0,
}


def _calculate_plan_macros(plan: Dict[str, Any]) -> Dict[str, float]:
    """Calculate total macros from a plan (including accompaniments for Vietnamese meals)."""
    total = {"kcal": 0.0, "protein_g": 0.0, "fat_g": 0.0, "carb_g": 0.0}

    def _add_meal_macros(meal_data: Dict[str, Any]):
        """Add macros from main recipe and accompaniments."""
        # Main recipe
        recipe = meal_data.get("recipe", {})
        servings = float(meal_data.get("servings", 1.0))
        macros = _get_meal_macros(recipe)
        for key in total:
            total[key] += macros[key] * servings
        
        # Accompaniments (for Vietnamese meals)
        accompaniments = meal_data.get("accompaniments", [])
        for acc in accompaniments:
            acc_recipe = acc.get("recipe", {})
            acc_servings = float(acc.get("servings", 1.0))
            if acc_recipe:
                acc_macros = _get_meal_macros(acc_recipe)
                for key in total:
                    total[key] += acc_macros[key] * acc_servings

    if plan.get("plan_type") == "day":
        for meal_data in plan.get("meals", {}).values():
            _add_meal_macros(meal_data)
        # Include snacks if present
        for snack_data in plan.get("snacks", []):
            _add_meal_macros(snack_data)
    elif plan.get("plan_type") == "week":
        for day_data in plan.get("days", {}).values():
            for meal_data in day_data.get("meals", {}).values():
                _add_meal_macros(meal_data)
            # Include snacks if present
            for snack_data in day_data.get("snacks", []):
                _add_meal_macros(snack_data)

    return total


def _calculate_macro_fit(
    recipe_macros: Dict[str, float],
    deficit_macros: Dict[str, float],
) -> float:
    """Calculate how well recipe fits the deficit needs (0-100, higher is better)."""
    if not deficit_macros:
        return 0.0

    fit_scores = []
    for macro, deficit in deficit_macros.items():
        recipe_val = recipe_macros.get(macro, 0.0)
        if deficit > 0 and recipe_val > 0:
            # Score based on how close recipe is to deficit (without exceeding too much)
            ratio = min(1.0, recipe_val / deficit) if deficit > 0 else 0.0
            fit_scores.append(ratio)
        elif deficit > 0:
            fit_scores.append(0.0)

    return (sum(fit_scores) / len(fit_scores) * 100.0) if fit_scores else 0.0


def _extract_kcal_hint(text: str | None) -> float | None:
    """Extract calorie hint (in kcal) from arbitrary text."""
    if not text:
        return None
    lowered = text.lower()
    match = re.search(r"(\d+(?:[\.,]\d+)?)\s*(?:kcal|calo?|cal)", lowered)
    if match:
        try:
            return float(match.group(1).replace(",", "."))
        except ValueError:
            return None
    # fallback pattern for "thiếu 300" without unit
    match = re.search(r"(thiếu|bổ sung|thêm)\s+(\d+(?:[\.,]\d+)?)", lowered)
    if match:
        try:
            return float(match.group(2).replace(",", "."))
        except ValueError:
            return None
    return None


def _build_deficit_from_hint(kcal_hint: float, targets: Dict[str, Any] | None) -> Dict[str, float]:
    """Build a deficit macro dict from a calorie hint and optional targets."""
    if not targets:
        targets = DEFAULT_TARGETS
    tdee = float(targets.get("tdee_kcal") or DEFAULT_TARGETS["tdee_kcal"] or 2000.0)
    tdee = max(tdee, 1.0)

    def _ratio_from_targets(gram_value: float, kcal_per_gram: float) -> float:
        if gram_value is None:
            return 0.0
        return max(0.0, min(0.6, (float(gram_value) * kcal_per_gram) / tdee))

    protein_ratio = _ratio_from_targets(targets.get("protein_g"), 4.0) or 0.25
    fat_ratio = _ratio_from_targets(targets.get("fat_g"), 9.0) or 0.30
    carb_ratio = _ratio_from_targets(targets.get("carb_g"), 4.0) or 0.45

    total_ratio = protein_ratio + fat_ratio + carb_ratio
    if total_ratio == 0:
        protein_ratio, fat_ratio, carb_ratio = 0.25, 0.30, 0.45
        total_ratio = 1.0

    protein_ratio /= total_ratio
    fat_ratio /= total_ratio
    carb_ratio /= total_ratio

    return {
        "kcal": kcal_hint,
        "protein_g": (kcal_hint * protein_ratio) / 4.0,
        "fat_g": (kcal_hint * fat_ratio) / 9.0,
        "carb_g": (kcal_hint * carb_ratio) / 4.0,
    }


def _find_snack_suggestions(
    client_manager: ClientManager,
    deficit_macros: Dict[str, float],
    top_k: int,
) -> List[Dict[str, Any]]:
    """
    Query Recipe collection and score candidates against deficit macros.
    - Prefer dish_type=snack but fall back to full corpus
    - Shuffle to avoid the same repeated items
    - Score by macro fit, then by kcal closeness to the deficit target
    - Deduplicate by dish_name
    """
    client = client_manager.get_client()
    recipe_collection = client.collections.get("Recipe")

    kcal_target = max(0.0, float(deficit_macros.get("kcal", 0.0) or 0.0))
    if kcal_target <= 0:
        kcal_target = 300.0  # sensible default for a snack

    def _fetch_candidates(limit: int = 400, snack_only: bool = True):
        try:
            if snack_only:
                snack_filter = build_filters_from_where(
                    {"path": ["dish_type"], "operator": "Equal", "valueString": "snack"}
                )
                return recipe_collection.query.fetch_objects(filters=snack_filter, limit=limit)
            return recipe_collection.query.fetch_objects(limit=limit)
        except Exception:
            return recipe_collection.query.fetch_objects(limit=limit)

    results = _fetch_candidates(limit=400, snack_only=True)
    if not results.objects:
        results = _fetch_candidates(limit=400, snack_only=False)

    # Shuffle to avoid deterministic repetition, then cap to a workable set
    objs = list(results.objects)
    random.shuffle(objs)
    objs = objs[:200]

    scored_recipes = []
    seen_names = set()
    for obj in objs:
        recipe = obj.properties
        dish_name = recipe.get("dish_name", "").strip().lower()
        if dish_name in seen_names:
            continue
        macros = recipe.get("macros_per_serving", {})
        if isinstance(macros, dict) and macros.get("kcal"):
            fit_score = _calculate_macro_fit(macros, deficit_macros)
            if fit_score > 0:
                kcal = float(macros.get("kcal", 0.0) or 0.0)
                kcal_gap = abs(kcal_target - kcal)
                scored_recipes.append(
                    {
                        **recipe,
                        "fit_score": fit_score,
                        "kcal_gap": kcal_gap,
                        "image_link": _get_image_link(recipe),
                    }
                )
                seen_names.add(dish_name)

    # Sort: fit_score desc, then kcal_gap asc
    scored_recipes.sort(
        key=lambda x: (
            -x.get("fit_score", 0.0),
            x.get("kcal_gap", float("inf")),
        )
    )
    return scored_recipes[:top_k]


@tool
async def gap_fill_tool(
    tree_data: TreeData,
    client_manager: ClientManager,
    auto_apply: bool = False,  # If True, automatically apply best snack suggestion
    top_k: int = 5,  # Number of snack suggestions to generate
    user_id: str | None = None,
    plan_id: str | None = None,
    **kwargs,
) -> AsyncGenerator[Result | Response | Error, None]:
    """
    Automate macro deficit analysis and snack insertion for existing plans.

    Steps:
      1. Load the latest plan (`plan_day_e2e_tool.plan` or `plan_week_e2e_tool.plan`).
      2. Pull personalized targets from `macro_calc_tool.targets`.
      3. Sum total macros, compute deficits, suggest snacks ranked by fit.
      4. Optionally insert top snack and sync back to Weaviate.

    Environment contract:
      Reads – day/week plan, macro targets.
      Writes – `gap_fill_tool.deficits` and optionally `gap_fill_tool.updated_plan` / `suggestions`.

    Decision hints:
      • `deficits.has_deficits=False` ⇒ nothing to fill; move on.
      • `updated_plan` result indicates the snack has been persisted, so other optimization tools should consume that version.
    """
    logging.info("gap_fill_tool: start")
    yield Response("🔍 Analyzing your meal plan for nutritional gaps...")
    
    try:
        hidden_env = tree_data.environment.hidden_environment
        if not user_id:
            user_id = hidden_env.get("user_id") or hidden_env.get("profile_user_id")
        if not plan_id:
            plan_id = hidden_env.get("latest_plan_id")

        user_prompt = getattr(tree_data, "user_prompt", "") or kwargs.get("query", "")
        kcal_hint = _extract_kcal_hint(user_prompt)

        # If user explicitly mentions kcal to add, prefer direct snack search mode.
        force_snack_mode = kcal_hint is not None

        # Step 1: Load plan from Weaviate database (source of truth) only when not forcing snack mode
        plan = None
        plan_source = None

        if not force_snack_mode:
            if plan_id:
                from MealAgent.tools.utils.plan_loader import load_plan_from_weaviate
                plan = load_plan_from_weaviate(plan_id, client_manager, user_id)
                if plan:
                    plan_source = plan.get("plan_type", "day") + "_plan"
                else:
                    logging.warning(f"gap_fill_tool: Plan {plan_id} not found in database, attempting fallbacks.")
                    yield Response(f"⚠️ Plan {plan_id} not found in database, checking latest saved plans...")
            if not plan and user_id:
                from MealAgent.tools.utils.plan_loader import load_latest_plan_from_weaviate
                plan = load_latest_plan_from_weaviate(user_id, client_manager, "day")
                if plan:
                    plan_source = "day_plan"
                else:
                    plan = load_latest_plan_from_weaviate(user_id, client_manager, "week")
                    if plan:
                        plan_source = "week_plan"
            if not plan:
                logging.info("gap_fill_tool: No plan found via database, trying environment cache")
                try:
                    day_plan_results = tree_data.environment.find("plan_day_e2e_tool", "plan")
                    if day_plan_results and len(day_plan_results) > 0 and day_plan_results[0].get("objects"):
                        plan = copy.deepcopy(day_plan_results[0]["objects"][0])
                        plan_source = "plan_day_e2e_tool"
                        yield Response("⚠️ Using cached plan (please provide plan_id or user_id for database access)")
                    else:
                        week_plan_results = tree_data.environment.find("plan_week_e2e_tool", "plan")
                        if week_plan_results and len(week_plan_results) > 0 and week_plan_results[0].get("objects"):
                            plan = copy.deepcopy(week_plan_results[0]["objects"][0])
                            plan_source = "plan_week_e2e_tool"
                            yield Response("⚠️ Using cached plan (please provide plan_id or user_id for database access)")
                except (IndexError, KeyError, TypeError) as e:
                    logging.warning(f"gap_fill_tool: Error accessing environment cache: {str(e)}")
                    plan = None

        plan_user_id = plan.get("user_id") if plan else user_id
        effective_plan_id = plan.get("plan_id") if plan else plan_id

        targets = None
        targets_refreshed = False

        if plan and not plan_user_id:
            yield Error("Plan loaded but missing user_id; please ensure plans are saved correctly.")
            return

        if plan_user_id:
            targets, targets_refreshed = await ensure_macro_targets(
                tree_data=tree_data,
                client_manager=client_manager,
                user_id=plan_user_id,
                **kwargs,
            )

        # If user asked for a specific kcal top-up, bypass plan deficits and search snacks around that hint
        if force_snack_mode:
            if not targets:
                targets = DEFAULT_TARGETS
            yield Response(
                f"🎯 Searching snacks around ~{kcal_hint:.0f} kcal (user request)."
            )
            deficit_macros = _build_deficit_from_hint(kcal_hint, targets)
            try:
                suggestions = _find_snack_suggestions(client_manager, deficit_macros, top_k)
            except Exception as exc:
                logging.error(f"gap_fill_tool: snack suggestion fallback failed: {exc}", exc_info=True)
                yield Error(f"Snack suggestion failed: {exc}")
                return

            if not suggestions:
                yield Error("No snack suggestions found for the requested calories. Please try a different description.")
                return

            logging.info(
                "gap_fill_tool: snack_mode hint=%.1f kcal, suggestions=%d",
                kcal_hint,
                len(suggestions),
            )

            suggestions_output = {
                "deficit_macros": deficit_macros,
                "suggestions": suggestions,
                "count": len(suggestions),
                "mode": "direct_snack_lookup",
                "kcal_hint": kcal_hint,
            }
            yield Result(
                name="suggestions",
                objects=[suggestions_output],
                metadata={
                    "suggestion_count": len(suggestions),
                    "deficit_count": len([k for k, v in deficit_macros.items() if v > 0]),
                    "plan_available": False,
                    "kcal_hint": kcal_hint,
                },
                payload_type="generic",
                display=True,
            )
            yield Response("✅ Returned snack suggestions based on your requested calories.")
            return

        if plan:
            if not targets:
                yield Error("Targets not found and could not be calculated from profile. Please create or complete your profile first.")
                return
            if effective_plan_id:
                tree_data.environment.hidden_environment["latest_plan_id"] = effective_plan_id

        # No plan and no hint → cannot proceed
        if not plan:
            yield Error("No plan found and no calorie hint detected. Please provide plan_id/user_id or specify calories to add.")
            return

        plan_id = effective_plan_id

        # Step 3: Calculate plan macros and deficits
        yield Response("📊 Calculating macro deficits...")
        plan_macros = _calculate_plan_macros(plan)
        
        # Get target macros (adjust for weekly if needed)
        if plan.get("plan_type") == "week":
            target_macros = {
                "kcal": float(targets.get("tdee_kcal", 2000)) * 7.0,
                "protein_g": float(targets.get("protein_g", 150)) * 7.0,
                "fat_g": float(targets.get("fat_g", 67)) * 7.0,
                "carb_g": float(targets.get("carb_g", 200)) * 7.0,
            }
        else:
            target_macros = {
                "kcal": float(targets.get("tdee_kcal", 2000)),
                "protein_g": float(targets.get("protein_g", 150)),
                "fat_g": float(targets.get("fat_g", 67)),
                "carb_g": float(targets.get("carb_g", 200)),
            }
        
        # Calculate deficits (negative = deficit, positive = surplus)
        deficits = {
            "kcal": target_macros["kcal"] - plan_macros["kcal"],
            "protein_g": target_macros["protein_g"] - plan_macros["protein_g"],
            "fat_g": target_macros["fat_g"] - plan_macros["fat_g"],
            "carb_g": target_macros["carb_g"] - plan_macros["carb_g"],
        }
        
        # Identify which macros have deficits
        deficit_macros = {k: v for k, v in deficits.items() if v > 0}
        
        deficits_output = {
            "plan_type": plan.get("plan_type"),
            "plan_macros": plan_macros,
            "target_macros": target_macros,
            "deficits": deficits,
            "deficit_macros": deficit_macros,
            "has_deficits": len(deficit_macros) > 0,
        }
        
        # Yield deficits result
        yield Result(
            name="deficits",
            objects=[deficits_output],
            metadata={
                "plan_type": plan.get("plan_type"),
                "has_deficits": len(deficit_macros) > 0,
                "deficit_count": len(deficit_macros),
            },
            payload_type="generic",
            display=True,
        )
        
        if not deficit_macros:
            yield Response("✅ No deficits found - your plan meets or exceeds all targets!")
            return
        
        deficit_list = []
        for k, v in deficit_macros.items():
            macro_name = k.replace("_g", "").replace("kcal", "calories").title()
            deficit_list.append(f"{macro_name}: {v:.1f}")
        deficit_str = ", ".join(deficit_list)
        yield Response(f"⚠️ Deficits detected: {deficit_str}")
        
        # Step 4: Suggest snacks
        yield Response("🍎 Searching for snacks to fill nutritional gaps...")
        
        try:
            suggestions = _find_snack_suggestions(client_manager, deficit_macros, top_k)

            if not suggestions:
                yield Response("⚠️ No suitable snacks found to fill deficits")
                return

            yield Response(f"✅ Found {len(suggestions)} snack suggestion(s)")
            
            # Step 5: Optionally apply best snack
            if auto_apply and suggestions:
                best_snack = suggestions[0]
                snack_name = best_snack.get('dish_name', 'Unknown')
                yield Response(f"➕ Adding snack to plan: {snack_name}")
                
                # Add snack to plan
                snack_meal = {
                    "recipe": best_snack,
                    "servings": 1.0,
                    "meal_type": "snack",
                }
                
                if plan.get("plan_type") == "day":
                    if "snacks" not in plan:
                        plan["snacks"] = []
                    plan["snacks"].append(snack_meal)
                elif plan.get("plan_type") == "week":
                    sorted_days = sorted(plan.get("days", {}).keys())
                    if sorted_days:
                        target_day_key = sorted_days[0]
                        if "snacks" not in plan["days"][target_day_key]:
                            plan["days"][target_day_key]["snacks"] = []
                        plan["days"][target_day_key]["snacks"].append(snack_meal)
                
                # Recalculate totals
                updated_macros = _calculate_plan_macros(plan)
                plan["total_macros"] = updated_macros
                
                if plan.get("plan_type") == "week":
                    plan["average_daily_macros"] = {
                        "kcal": updated_macros["kcal"] / 7.0,
                        "protein_g": updated_macros["protein_g"] / 7.0,
                        "fat_g": updated_macros["fat_g"] / 7.0,
                        "carb_g": updated_macros["carb_g"] / 7.0,
                    }
                
                if plan_user_id:
                    plan = sync_plan_to_weaviate(
                        plan,
                        user_id=plan_user_id,
                        client_manager=client_manager,
                        start_date=plan.get("start_date"),
                    )

                yield Result(
                    name="updated_plan",
                    objects=[plan],
                    metadata={
                        "plan_type": plan.get("plan_type"),
                        "snack_added": True,
                        "snack_name": best_snack.get("dish_name", ""),
                        "plan_id": plan.get("plan_id"),
                    },
                    payload_type="meal_plan",  # Use meal_plan for frontend detection
                    display=True,
                )
                yield Response(
                    f"✅ Snack added! Updated plan totals: {updated_macros['kcal']:.0f} kcal | "
                    f"{updated_macros['protein_g']:.0f}g protein"
                )
            else:
                # Just yield suggestions without applying
                suggestions_output = {
                    "deficit_macros": deficit_macros,
                    "suggestions": suggestions,
                    "count": len(suggestions),
                }
                yield Result(
                    name="suggestions",
                    objects=[suggestions_output],
                    metadata={
                        "suggestion_count": len(suggestions),
                        "deficit_count": len(deficit_macros),
                    },
                    payload_type="generic",
                    display=True,
                )
        
        except Exception as e:
            logging.error(f"gap_fill_tool: snack suggestion failed: {str(e)}", exc_info=True)
            yield Error(f"Snack suggestion failed: {str(e)}")
            return
    
    except ValueError as e:
        error_msg = f"Invalid input: {str(e)}"
        logging.error(f"gap_fill_tool: {error_msg}", exc_info=True)
        yield Error(error_msg)
        return
    except Exception as e:
        error_msg = f"gap_fill_tool failed: {str(e)}"
        logging.error(f"gap_fill_tool: {error_msg}", exc_info=True)
        yield Error(error_msg)
        return

