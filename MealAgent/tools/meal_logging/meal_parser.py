from typing import AsyncGenerator, Dict, Any, List
import json

from elysia.tree.objects import TreeData
from elysia.objects import Result, Error, Response
from elysia.util.client import ClientManager
from elysia import tool


@tool
async def meal_parser_tool(
    tree_data: TreeData,
    client_manager: ClientManager,
    base_lm,  # LLM for structured output
    meal_description: str = "",
    **kwargs,
) -> AsyncGenerator[Result | str | Error, None]:
    """
    Parse natural language meal description into structured data.

    LLM-Enhanced Tool: Uses base_lm to extract dish name and ingredients.

    Environment writes:
      - environment["meal_parser_tool"]["parsed_meal"]
    """
    yield Response("Parsing meal description...")

    if not meal_description:
        yield Error("Meal description is required")
        return

    # Step 1: LLM Call - Parse meal description
    llm_prompt = f"""Parse this meal description into structured JSON:
"{meal_description}"

Return JSON with:
- dish: dish name (e.g., "Chicken Salad")
- ingredients: list of [{{"name": str, "amount": float, "unit": str}}]
- portion_size: number (default 1.0)

Example: {{"dish": "Chicken Salad", "ingredients": [{{"name": "chicken", "amount": 100, "unit": "g"}}, {{"name": "lettuce", "amount": 50, "unit": "g"}}], "portion_size": 1.0}}"""

    try:
        llm_response = await base_lm.generate_structured(
            prompt=llm_prompt,
            schema={
                "type": "object",
                "properties": {
                    "dish": {"type": "string"},
                    "ingredients": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "amount": {"type": "number"},
                                "unit": {"type": "string"},
                            },
                            "required": ["name"],
                        },
                    },
                    "portion_size": {"type": "number"},
                },
                "required": ["dish", "ingredients"],
            },
        )

        parsed_data = json.loads(llm_response) if isinstance(llm_response, str) else llm_response

    except Exception as e:
        yield Error(f"Failed to parse meal description '{meal_description}': {str(e)}")
        return

    # Step 2: Code Validation - Check if ingredients exist in FDC
    try:
        client = client_manager.get_client()
        fdc_collection = client.collections.get("FdcFood")

        validated_ingredients = []
        for ing in parsed_data.get("ingredients", []):
            ing_name = ing.get("name", "")
            if not ing_name:
                continue

            # Search for ingredient in FDC
            search_results = fdc_collection.query.hybrid(
                query=ing_name,
                limit=1,
            )

            if search_results.objects:
                fdc_food = search_results.objects[0].properties
                validated_ingredients.append({
                    **ing,
                    "fdc_id": fdc_food.get("fdc_id"),
                })
            else:
                # Partial validation: include ingredient but mark as unvalidated
                validated_ingredients.append({
                    **ing,
                    "fdc_id": None,
                    "validation_status": "not_found",
                })

        parsed_meal = {
            "dish": parsed_data.get("dish", ""),
            "ingredients": validated_ingredients,
            "portion_size": parsed_data.get("portion_size", 1.0),
            "original_description": meal_description,
            "validation_status": "complete" if all(ing.get("fdc_id") for ing in validated_ingredients) else "partial",
        }

        # Step 3: Yield Result
        yield Result(
            name="parsed_meal",
            objects=[parsed_meal],
            metadata={
                "parsing_method": "llm",
                "ingredients_count": len(validated_ingredients),
                "validated_count": sum(1 for ing in validated_ingredients if ing.get("fdc_id")),
            },
            payload_type="generic",
        )
        yield Response(f"Parsed meal: {parsed_meal['dish']} with {len(validated_ingredients)} ingredients")

    except Exception as e:
        yield Error(f"FDC validation failed for meal description '{meal_description}': {str(e)}")
        return

