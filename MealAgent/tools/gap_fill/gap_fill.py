"""
End-to-end gap fill tool: calculate deficits → suggest snacks → apply to plan.
"""
from typing import AsyncGenerator, Dict, Any, List
import copy
import logging

from elysia.tree.objects import TreeData
from elysia.objects import Result, Error, Response
from elysia.util.client import ClientManager
from elysia import tool


from MealAgent.tools.utils.planning_helpers import _get_meal_macros, sync_plan_to_weaviate
from MealAgent.tools.utils.weaviate_filters import build_filters_from_where


def _calculate_plan_macros(plan: Dict[str, Any]) -> Dict[str, float]:
    """Calculate total macros from a plan."""
    total = {"kcal": 0.0, "protein_g": 0.0, "fat_g": 0.0, "carb_g": 0.0}

    if plan.get("plan_type") == "day":
        for meal_data in plan.get("meals", {}).values():
            recipe = meal_data.get("recipe", {})
            servings = float(meal_data.get("servings", 1.0))
            macros = _get_meal_macros(recipe)
            for key in total:
                total[key] += macros[key] * servings
        # Include snacks if present
        for snack_data in plan.get("snacks", []):
            recipe = snack_data.get("recipe", {})
            servings = float(snack_data.get("servings", 1.0))
            macros = _get_meal_macros(recipe)
            for key in total:
                total[key] += macros[key] * servings
    elif plan.get("plan_type") == "week":
        for day_data in plan.get("days", {}).values():
            for meal_data in day_data.get("meals", {}).values():
                recipe = meal_data.get("recipe", {})
                servings = float(meal_data.get("servings", 1.0))
                macros = _get_meal_macros(recipe)
                for key in total:
                    total[key] += macros[key] * servings
            # Include snacks if present
            for snack_data in day_data.get("snacks", []):
                recipe = snack_data.get("recipe", {})
                servings = float(snack_data.get("servings", 1.0))
                macros = _get_meal_macros(recipe)
                for key in total:
                    total[key] += macros[key] * servings

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
    End-to-end gap fill: calculate deficits → suggest snacks → optionally apply to plan.
    
    This tool orchestrates the full gap fill workflow:
    1. Read plan from environment (plan_day_e2e_tool.plan or plan_week_e2e_tool.plan)
    2. Read targets from environment
    3. Calculate macro deficits
    4. Suggest snacks to fill deficits
    5. Optionally apply best snack to plan (if auto_apply=True)
    
    Environment reads:
      - plan_day_e2e_tool.plan or plan_week_e2e_tool.plan
      - macro_calc_tool.targets
    Environment writes:
      - gap_fill_tool.deficits: calculated deficits
      - gap_fill_tool.updated_plan: plan with snack applied (if auto_apply=True)
    
    Decision hints:
      - If gap_fill_tool.deficits.has_deficits is True, the plan has macro gaps.
      - If auto_apply=True, gap_fill_tool.updated_plan contains the plan with snack added.
    """
    logging.info("gap_fill_tool: start")
    yield Response("Analyzing plan for macro gaps...")
    
    try:
        # Step 1: Read plan from E2E tools
        plan = None
        plan_source = None
        
        day_plan_results = tree_data.environment.find("plan_day_e2e_tool", "plan")
        if day_plan_results and day_plan_results[0]["objects"]:
            plan = copy.deepcopy(day_plan_results[0]["objects"][0])
            plan_source = "plan_day_e2e_tool"
        else:
            week_plan_results = tree_data.environment.find("plan_week_e2e_tool", "plan")
            if week_plan_results and week_plan_results[0]["objects"]:
                plan = copy.deepcopy(week_plan_results[0]["objects"][0])
                plan_source = "plan_week_e2e_tool"
            else:
                yield Error("No plan found. Run plan_day_e2e_tool or plan_week_e2e_tool first.")
                return
        plan_user_id = plan.get("user_id") or user_id
        if plan_id or plan.get("plan_id"):
            plan["plan_id"] = plan.get("plan_id") or plan_id
        else:
            plan_id = None
        
        # Step 2: Read targets
        macro_results = tree_data.environment.find("macro_calc_tool", "targets")
        if not macro_results or not macro_results[0]["objects"]:
            yield Error("Targets not found. Run macro_calc_tool first.")
            return
        targets = macro_results[0]["objects"][0]
        
        # Step 3: Calculate plan macros and deficits
        yield Response("Calculating macro deficits...")
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
            yield Response("No deficits - plan meets or exceeds targets")
            return
        
        deficit_str = ", ".join([f"{k}: {v:.1f}" for k, v in deficit_macros.items()])
        yield Response(f"Deficits found: {deficit_str}")
        
        # Step 4: Suggest snacks
        yield Response("Searching for snacks to fill deficits...")
        
        try:
            client = client_manager.get_client()
            recipe_collection = client.collections.get("Recipe")
            
            # Search for snack recipes
            try:
                snack_filter = build_filters_from_where(
                    {"path": ["dish_type"], "operator": "Equal", "valueString": "snack"}
                )
                results = recipe_collection.query.fetch_objects(filters=snack_filter, limit=100)
                if not results.objects:
                    results = recipe_collection.query.fetch_objects(limit=100)
            except Exception:
                results = recipe_collection.query.fetch_objects(limit=100)
            
            # Score recipes by how well they fit deficits
            scored_recipes = []
            for obj in results.objects:
                recipe = obj.properties
                macros = recipe.get("macros_per_serving", {})
                if isinstance(macros, dict) and macros.get("kcal"):
                    fit_score = _calculate_macro_fit(macros, deficit_macros)
                    if fit_score > 0:
                        scored_recipes.append({
                            **recipe,
                            "fit_score": fit_score,
                        })
            
            # Sort by fit score and take top_k
            scored_recipes.sort(key=lambda x: x.get("fit_score", 0.0), reverse=True)
            suggestions = scored_recipes[:top_k]
            
            if not suggestions:
                yield Response("No suitable snacks found to fill deficits")
                return
            
            yield Response(f"Found {len(suggestions)} snack suggestions")
            
            # Step 5: Optionally apply best snack
            if auto_apply and suggestions:
                best_snack = suggestions[0]
                yield Response(f"Auto-applying best snack: {best_snack.get('dish_name', 'Unknown')}")
                
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
                    payload_type="generic",
                    display=True,
                )
                yield Response(f"Snack added. Updated totals: {updated_macros['kcal']:.0f} kcal")
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

