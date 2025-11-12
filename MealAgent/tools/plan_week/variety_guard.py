"""
Detect repetition and score variety in meal plans.
"""
from typing import AsyncGenerator, Dict, Any, List, Set
from collections import Counter

from elysia.tree.objects import TreeData
from elysia.objects import Result, Error, Response
from elysia.util.client import ClientManager
from elysia import tool


def _count_recipe_repetitions(plan: Dict[str, Any]) -> Dict[str, int]:
    """Count how many times each recipe appears in the plan."""
    recipe_counts = Counter()
    
    if plan.get("plan_type") == "day":
        # Single day plan
        for meal_data in plan.get("meals", {}).values():
            recipe = meal_data.get("recipe", {})
            food_id = recipe.get("food_id")
            if food_id:
                recipe_counts[food_id] += 1
    elif plan.get("plan_type") == "week":
        # Weekly plan
        for day_data in plan.get("days", {}).values():
            for meal_data in day_data.get("meals", {}).values():
                recipe = meal_data.get("recipe", {})
                food_id = recipe.get("food_id")
                if food_id:
                    recipe_counts[food_id] += 1
    
    return dict(recipe_counts)


def _calculate_variety_score(plan: Dict[str, Any]) -> float:
    """
    Calculate variety score (0-100, higher is better).
    
    Score based on:
    - Number of unique recipes
    - Repetition penalty (recipes used more than once get penalty)
    - Ingredient diversity (unique ingredients across all meals)
    """
    recipe_counts = _count_recipe_repetitions(plan)
    
    if not recipe_counts:
        return 0.0
    
    total_meals = sum(recipe_counts.values())
    unique_recipes = len(recipe_counts)
    
    # Base score: percentage of unique recipes
    uniqueness_ratio = unique_recipes / total_meals if total_meals > 0 else 0.0
    
    # Repetition penalty: reduce score for repeated recipes
    repetition_penalty = 0.0
    for count in recipe_counts.values():
        if count > 1:
            # Penalty increases with repetition count
            repetition_penalty += (count - 1) * 0.1
    
    # Normalize penalty (max penalty if all recipes repeated)
    max_penalty = (total_meals - unique_recipes) * 0.1
    penalty_ratio = repetition_penalty / max_penalty if max_penalty > 0 else 0.0
    
    # Calculate ingredient diversity
    all_ingredients: Set[str] = set()
    if plan.get("plan_type") == "day":
        for meal_data in plan.get("meals", {}).values():
            recipe = meal_data.get("recipe", {})
            ingredients = recipe.get("ingredients", [])
            for ing in ingredients:
                if isinstance(ing, str):
                    all_ingredients.add(ing.lower().strip())
                elif isinstance(ing, dict):
                    all_ingredients.add(str(ing.get("name", "")).lower().strip())
    elif plan.get("plan_type") == "week":
        for day_data in plan.get("days", {}).values():
            for meal_data in day_data.get("meals", {}).values():
                recipe = meal_data.get("recipe", {})
                ingredients = recipe.get("ingredients", [])
                for ing in ingredients:
                    if isinstance(ing, str):
                        all_ingredients.add(ing.lower().strip())
                    elif isinstance(ing, dict):
                        all_ingredients.add(str(ing.get("name", "")).lower().strip())
    
    # Ingredient diversity score (normalized)
    ingredient_diversity = min(1.0, len(all_ingredients) / (total_meals * 3))  # Assume ~3 ingredients per meal
    
    # Composite score
    variety_score = (
        uniqueness_ratio * 0.5 +  # 50% weight on recipe uniqueness
        (1.0 - penalty_ratio) * 0.3 +  # 30% weight on avoiding repetition
        ingredient_diversity * 0.2  # 20% weight on ingredient diversity
    ) * 100.0
    
    return max(0.0, min(100.0, variety_score))


@tool
async def variety_guard_tool(
    tree_data: TreeData,
    client_manager: ClientManager,
    **kwargs,
) -> AsyncGenerator[Result | str | Error, None]:
    """
    Detect repetition and score variety in meal plans.

    Environment reads:
      - environment["plan_assemble_weekly_tool"]["plan"] or
      - environment["plan_assemble_day_tool"]["plan"]
    Environment writes:
      - environment["variety_guard_tool"]["report"]

    Decision hints:
      - If variety_guard_tool.report.variety_score is high (>70), the plan has good variety.
      - If variety_guard_tool.report.repeated_recipes is not empty, consider suggesting alternatives.
    """
    yield Response("Analyzing plan variety...")

    # Try weekly plan first, then daily plan
    weekly_results = tree_data.environment.find("plan_assemble_weekly_tool", "plan")
    daily_results = tree_data.environment.find("plan_assemble_day_tool", "plan")

    plan = None
    plan_source = None

    if weekly_results and weekly_results[0].objects:
        plan = weekly_results[0].objects[0]
        plan_source = "plan_assemble_weekly_tool"
    elif daily_results and daily_results[0].objects:
        plan = daily_results[0].objects[0]
        plan_source = "plan_assemble_day_tool"
    else:
        yield Error("No plan found. Run plan_assemble_weekly_tool or plan_assemble_day_tool first.")
        return

    # Count repetitions
    recipe_counts = _count_recipe_repetitions(plan)
    
    # Calculate variety score
    variety_score = _calculate_variety_score(plan)
    
    # Identify repeated recipes and fetch their names
    repeated_recipes = []
    if recipe_counts:
        try:
            client = client_manager.get_client()
            recipe_collection = client.collections.get("Recipe")
            for food_id, count in recipe_counts.items():
                if count > 1:
                    recipe_name = ""
                    try:
                        # Fetch recipe name
                        recipe_results = recipe_collection.query.fetch_objects(
                            where={"path": ["food_id"], "operator": "Equal", "valueString": food_id},
                            limit=1,
                        )
                        if recipe_results.objects:
                            recipe_name = recipe_results.objects[0].properties.get("dish_name", "")
                    except Exception:
                        pass  # Keep empty name if fetch fails
                    repeated_recipes.append({
                        "food_id": food_id,
                        "count": count,
                        "recipe_name": recipe_name,
                    })
        except Exception:
            # Fallback: create without names if client access fails
            repeated_recipes = [
                {"food_id": food_id, "count": count, "recipe_name": ""}
                for food_id, count in recipe_counts.items()
                if count > 1
            ]
    
    # Generate warnings
    warnings = []
    if variety_score < 50.0:
        warnings.append("Low variety detected. Consider adding more diverse recipes.")
    if repeated_recipes:
        warnings.append(f"{len(repeated_recipes)} recipes are repeated in the plan.")
    
    report = {
        "variety_score": variety_score,
        "unique_recipes": len(recipe_counts),
        "total_meals": sum(recipe_counts.values()),
        "repeated_recipes": repeated_recipes,
        "warnings": warnings,
        "plan_source": plan_source,
    }

    yield Result(
        name="report",
        objects=[report],
        metadata={"variety_score": variety_score, "repetitions": len(repeated_recipes)},
        payload_type="generic",
    )
    
    if warnings:
        yield Response(f"Variety score: {variety_score:.1f}/100. Warnings: {', '.join(warnings)}")
    else:
        yield Response(f"Variety score: {variety_score:.1f}/100. Good variety!")

