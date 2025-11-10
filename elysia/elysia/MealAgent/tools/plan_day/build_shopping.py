from typing import AsyncGenerator, Dict, Any, List

from elysia.tree.objects import TreeData
from elysia.objects import Result, Error
from elysia.util.client import ClientManager
from elysia import tool


def _extract_ingredients_from_plan(plan: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Extract and aggregate ingredients from all meals in plan."""
    ingredient_map: Dict[str, Dict[str, Any]] = {}

    for meal_key, meal_data in plan.get("meals", {}).items():
        recipe = meal_data.get("recipe", {})
        servings = meal_data.get("servings", 1.0)

        # Get ingredients from recipe
        ingredients_with_qty = recipe.get("ingredients_with_qty", [])
        ingredients = recipe.get("ingredients", [])

        # Use ingredients_with_qty if available, otherwise fallback to ingredients
        if ingredients_with_qty:
            for ing_str in ingredients_with_qty:
                # Parse ingredient string (e.g., "200g thịt gà" or "1 cup rice")
                # For now, use the string as-is and aggregate by name
                ing_key = ing_str.lower().strip()
                if ing_key not in ingredient_map:
                    ingredient_map[ing_key] = {
                        "name": ing_str,
                        "quantity": 0.0,
                        "unit": "g",  # Default unit
                        "recipes": [],
                    }
                # Aggregate quantity (simplified - would need proper parsing)
                ingredient_map[ing_key]["quantity"] += servings
                ingredient_map[ing_key]["recipes"].append({
                    "meal": meal_key,
                    "recipe_id": recipe.get("food_id"),
                })
        elif ingredients:
            # Fallback: use simple ingredient names
            for ing in ingredients:
                ing_key = str(ing).lower().strip()
                if ing_key not in ingredient_map:
                    ingredient_map[ing_key] = {
                        "name": str(ing),
                        "quantity": 0.0,
                        "unit": "g",
                        "recipes": [],
                    }
                ingredient_map[ing_key]["quantity"] += servings
                ingredient_map[ing_key]["recipes"].append({
                    "meal": meal_key,
                    "recipe_id": recipe.get("food_id"),
                })

    return list(ingredient_map.values())


@tool
async def build_shopping_tool(
    tree_data: TreeData,
    client_manager: ClientManager,  # signature consistency
    **kwargs,
) -> AsyncGenerator[Result | str | Error, None]:
    """
    Extract ingredients from daily plan and build shopping list.

    Environment reads:
      - environment["plan_assemble_day_tool"]["plan"]
    Environment writes:
      - environment["build_shopping_tool"]["items"]
    """
    yield "Building shopping list from plan..."

    # Read plan
    plan_results = tree_data.environment.find("plan_assemble_day_tool", "plan")
    if not plan_results or not plan_results[0].objects:
        yield Error("Plan not found. Run plan_assemble_day_tool first.")
        return

    plan = plan_results[0].objects[0]

    # Extract ingredients
    items = _extract_ingredients_from_plan(plan)

    # Build shopping list structure
    shopping_list = {
        "plan_id": plan.get("plan_id"),
        "plan_type": plan.get("plan_type", "day"),
        "items": items,
        "total_items": len(items),
        "created_at": None,  # Can be set by caller
    }

    yield Result(
        name="items",
        objects=[shopping_list],
        metadata={"plan_type": plan.get("plan_type", "day"), "items_count": len(items)},
    )
    yield f"Shopping list built: {len(items)} items"

