"""
Swap ingredient in plan with substitute.
"""
from typing import AsyncGenerator, Dict, Any

from elysia.tree.objects import TreeData
from elysia.objects import Result, Error, Response
from elysia.util.client import ClientManager
from elysia import tool
from elysia.MealAgent.tools.nutrition.calculate_recipe_macros import calculate_recipe_macros_tool


@tool
async def apply_substitute_tool(
    tree_data: TreeData,
    client_manager: ClientManager,
    original_fdc_id: int,
    substitute_fdc_id: int,
    recipe_food_id: str | None = None,
    recalculate_macros: bool = True,
    base_lm=None,
    **kwargs,
) -> AsyncGenerator[Result | str | Error, None]:
    """
    Swap ingredient in plan with substitute.

    This updates the recipe's ingredient_fdc_map to replace the original
    ingredient with the substitute, and recalculates macros.

    Environment reads:
      - environment["plan_assemble_day_tool"]["plan"] or
      - environment["plan_assemble_weekly_tool"]["plan"]
      - environment["suggest_substitutes_tool"]["substitutes"] (optional)
    Environment writes:
      - environment["apply_substitute_tool"]["updated_plan"]
    """
    yield Response("Applying ingredient substitute...")

    # Read plan
    weekly_results = tree_data.environment.find("plan_assemble_weekly_tool", "plan")
    daily_results = tree_data.environment.find("plan_assemble_day_tool", "plan")

    plan = None
    if weekly_results and weekly_results[0].objects:
        plan = weekly_results[0].objects[0]
    elif daily_results and daily_results[0].objects:
        plan = daily_results[0].objects[0]
    else:
        yield Error("No plan found. Run plan_assemble_day_tool or plan_assemble_weekly_tool first.")
        return

    try:
        client = client_manager.get_client()
        recipe_collection = client.collections.get("Recipe")
        fdc_collection = client.collections.get("FdcFood")

        # Get substitute macros
        sub_results = fdc_collection.query.fetch_objects(
            where={"path": ["fdc_id"], "operator": "Equal", "valueInt": int(substitute_fdc_id)},
            limit=1,
        )
        if not sub_results.objects:
            yield Error(f"Substitute FDC ID {substitute_fdc_id} not found")
            return

        substitute_fdc = sub_results.objects[0].properties

        # Find recipes in plan that use original ingredient
        updated_recipes = []
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

        # Update recipes that contain the original ingredient
        for recipe, meal_data in recipes_to_update:
            food_id = recipe.get("food_id")
            ingredient_map = recipe.get("ingredient_fdc_map", [])

            # Check if recipe uses original ingredient
            uses_original = False
            updated_map = []
            for ing_entry in ingredient_map:
                if isinstance(ing_entry, dict) and ing_entry.get("fdc_id") == original_fdc_id:
                    uses_original = True
                    # Replace with substitute
                    updated_map.append({
                        **ing_entry,
                        "fdc_id": substitute_fdc_id,
                        "ingredient_en": substitute_fdc.get("description", ing_entry.get("ingredient_en", "")),
                    })
                else:
                    updated_map.append(ing_entry)

            if uses_original:
                # Update recipe in Weaviate
                recipe_results = recipe_collection.query.fetch_objects(
                    where={"path": ["food_id"], "operator": "Equal", "valueString": food_id},
                    limit=1,
                )
                if recipe_results.objects:
                    recipe_obj = recipe_results.objects[0]
                    recipe_obj.properties["ingredient_fdc_map"] = updated_map
                    recipe_collection.data.update(uuid=recipe_obj.uuid, properties=recipe_obj.properties)

                    # Update recipe in plan
                    recipe["ingredient_fdc_map"] = updated_map
                    updated_recipes.append(food_id)

            if not updated_recipes:
                yield Error(f"No recipes found using ingredient with FDC ID {original_fdc_id}")
                return

            # Recalculate macros if requested and base_lm is available
            macros_recalculated = False
            if recalculate_macros and base_lm:
                yield Response("Recalculating recipe macros after substitution...")
                for food_id in updated_recipes:
                    try:
                        async for result in calculate_recipe_macros_tool(
                            tree_data=tree_data,
                            client_manager=client_manager,
                            recipe_id=food_id,
                            base_lm=base_lm,
                        ):
                            if isinstance(result, Error):
                                yield Response(f"Warning: Failed to recalculate macros for recipe {food_id}: {result.message}")
                                break
                        macros_recalculated = True
                    except Exception as e:
                        yield Response(f"Warning: Error recalculating macros for recipe {food_id}: {str(e)}")
            elif recalculate_macros and not base_lm:
                yield Response("Warning: base_lm not provided. Macros not recalculated. Run calculate_recipe_macros_tool manually.")

            # Stream response first for immediate feedback
            if macros_recalculated:
                yield Response(f"Substitute applied to {len(updated_recipes)} recipe(s). Macros recalculated.")
            else:
                yield Response(f"Substitute applied to {len(updated_recipes)} recipe(s). Run calculate_recipe_macros_tool to update macros.")
            
            # Then yield Result for data consistency
            yield Result(
                name="updated_plan",
                objects=[plan],
                metadata={
                    "plan_type": plan.get("plan_type"),
                    "recipes_updated": len(updated_recipes),
                    "original_fdc_id": original_fdc_id,
                    "substitute_fdc_id": substitute_fdc_id,
                    "macros_recalculated": macros_recalculated,
                },
                payload_type="generic",
            )

    except Exception as e:
        yield Error(f"Substitute application failed: {str(e)}")
        return

