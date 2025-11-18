from typing import AsyncGenerator, Dict, Any, List, Optional
import json
import logging

from elysia.tree.objects import TreeData
from elysia.objects import Result, Error, Response
from elysia.util.client import ClientManager
from elysia import tool
import dspy
from elysia.util.elysia_chain_of_thought import ElysiaChainOfThought

from MealAgent.tools.utils.weaviate_filters import build_filters_from_where

logger = logging.getLogger(__name__)


async def _translate_ingredients_vn_to_en(
    ingredients_vn: List[str],
    base_lm,
) -> List[Dict[str, Any]]:
    """Translate Vietnamese ingredients to English using LLM."""
    if not ingredients_vn:
        return []

    try:
        class TranslationPrompt(dspy.Signature):
            """
            Translate Vietnamese ingredient names to English and extract quantity/unit when present.
            Output a list of objects with fields: vn, en, quantity, unit.
            """
            ingredients_vn = dspy.InputField(description="Array of Vietnamese ingredient strings.")
            message_update = dspy.OutputField(description="One-sentence update describing the translation progress.")
            translations = dspy.OutputField(description="List of translated objects with vn, en, quantity, unit.")

        cot = ElysiaChainOfThought(
            TranslationPrompt,
            tree_data=TreeData,  # not used inside prompt content, placeholder for interface
            reasoning=False,
            impossible=False,
            message_update=True,
        )
        # Call the prediction - pass raw list; dspy will serialize
        pred = await cot.aforward(lm=base_lm, ingredients_vn=ingredients_vn)
        # Expect pred.translations to be JSON-like; enforce shape
        translations = pred.translations
        # Ensure type safety
        if isinstance(translations, str):
            translations = json.loads(translations)
        if not isinstance(translations, list):
            raise ValueError("Invalid translation output")
        cleaned = []
        for t in translations:
            if not isinstance(t, dict):
                continue
            cleaned.append({
                "vn": t.get("vn", ""),
                "en": t.get("en", t.get("vn", "")),
                "quantity": float(t.get("quantity", 100.0)) if isinstance(t.get("quantity", 100.0), (int, float)) else 100.0,
                "unit": t.get("unit", "g") if isinstance(t.get("unit", "g"), str) else "g",
            })
        return cleaned
    except Exception:
        # Fallback: return original names as English
        return [{"vn": ing, "en": ing, "quantity": 100, "unit": "g"} for ing in ingredients_vn]


async def _find_fdc_food(
    ingredient_en: str,
    client,
    threshold: float = 0.7,
) -> Optional[Dict[str, Any]]:
    """Search FDC for ingredient and return best match if score > threshold."""
    try:
        collection = client.collections.get("FdcFood")
        results = collection.query.hybrid(
            query=ingredient_en,
            limit=1,
        )

        if results.objects:
            obj = results.objects[0]
            # Check score if available
            score = getattr(obj, "metadata", {}).get("score", 1.0) if hasattr(obj, "metadata") else 1.0
            if score >= threshold:
                return obj.properties
    except Exception:
        pass
    return None


def _calculate_macros_from_fdc(
    fdc_food: Dict[str, Any],
    quantity_g: float,
) -> Dict[str, float]:
    """Calculate macros from FDC food per-100g values scaled by quantity."""
    # FDC stores per-100g values
    scale = quantity_g / 100.0

    return {
        "kcal": float(fdc_food.get("energy_kcal_100g", 0.0)) * scale,
        "protein_g": float(fdc_food.get("protein_g_100g", 0.0)) * scale,
        "fat_g": float(fdc_food.get("fat_g_100g", 0.0)) * scale,
        "carb_g": float(fdc_food.get("carbohydrate_g_100g", 0.0)) * scale,
    }


@tool
async def calculate_recipe_macros_tool(
    tree_data: TreeData,
    client_manager: ClientManager,
    base_lm,  # LLM for VN→EN translation
    recipe_id: Optional[str] = None,
    recipe: Optional[Dict[str, Any]] = None,
    **kwargs,
) -> AsyncGenerator[Result | Response | Error, None]:
    """
    Calculate macros_per_serving for Recipe (VN→EN translation + FDC lookup + cache).

    If Recipe lacks macros_per_serving:
    1. Translate ingredients (VN→EN) using LLM
    2. Search FDC for each ingredient
    3. Compute macros, update Recipe, return value
    4. Persist ingredient_fdc_map for faster subsequent runs

    Environment reads:
      - Recipe from Weaviate (by recipe_id) or passed as recipe parameter
    Environment writes:
      - Updates Recipe in Weaviate with macros_per_serving and ingredient_fdc_map
      - Returns calculated macros in Result

    Decision hints:
      - If calculate_recipe_macros_tool.macros is present, recipe macros have been calculated successfully.
      - Recipes with macros_per_serving can be used for accurate meal planning and macro tracking.
    """
    yield Response("Calculating recipe macros...")

    try:
        client = client_manager.get_client()
        collection = client.collections.get("Recipe")

        # Get recipe
        recipe_obj = recipe
        if not recipe_obj and recipe_id:
            recipe_filter = build_filters_from_where(
                {"path": ["food_id"], "operator": "Equal", "valueString": recipe_id}
            )
            results = collection.query.fetch_objects(filters=recipe_filter, limit=1)
            if not results.objects:
                yield Error(f"Recipe not found: {recipe_id}")
                return
            recipe_obj = results.objects[0].properties
            recipe_uuid = results.objects[0].uuid
        elif recipe_obj:
            # If recipe passed in, fetch UUID for update
            recipe_filter = build_filters_from_where(
                {"path": ["food_id"], "operator": "Equal", "valueString": recipe_obj.get("food_id")}
            )
            results = collection.query.fetch_objects(filters=recipe_filter, limit=1)
            recipe_uuid = results.objects[0].uuid if results.objects else None
        else:
            yield Error("Either recipe_id or recipe must be provided")
            return

        # Check if macros already cached
        macros = recipe_obj.get("macros_per_serving")
        if macros and isinstance(macros, dict) and macros.get("kcal"):
            yield Result(
                name="macros",
                objects=[macros],
                metadata={"source": "cached", "recipe_id": recipe_obj.get("food_id")},
                payload_type="generic",
                display=True,
            )
            yield Response("Macros retrieved from cache")
            return

        # Need to calculate: translate ingredients
        ingredients_vn = recipe_obj.get("ingredients_with_qty", []) or recipe_obj.get("ingredients", [])
        if not ingredients_vn:
            yield Error("Recipe has no ingredients to calculate macros from")
            return

        translated = await _translate_ingredients_vn_to_en(ingredients_vn, base_lm)

        # Find FDC foods and calculate macros
        total_macros = {"kcal": 0.0, "protein_g": 0.0, "fat_g": 0.0, "carb_g": 0.0}
        ingredient_map = []

        for item in translated:
            ingredient_en = item.get("en", "")
            quantity_g = float(item.get("quantity", 100.0))

            fdc_food = await _find_fdc_food(ingredient_en, client)
            if fdc_food:
                ingredient_macros = _calculate_macros_from_fdc(fdc_food, quantity_g)
                for key in total_macros:
                    total_macros[key] += ingredient_macros[key]

                ingredient_map.append({
                    "ingredient_vn": item.get("vn", ""),
                    "ingredient_en": ingredient_en,
                    "fdc_id": int(fdc_food.get("fdc_id", 0)),
                    "quantity_g": quantity_g,
                    "confidence": 0.8,  # Could be improved with actual match score
                })

        # Divide by serving_size to get per-serving macros
        serving_size = float(recipe_obj.get("serving_size", 1.0))
        if serving_size > 0:
            macros_per_serving = {k: v / serving_size for k, v in total_macros.items()}
        else:
            macros_per_serving = total_macros

        # Update Recipe in Weaviate with deduplicated ingredient_fdc_map
        if recipe_uuid:
            # Merge with existing ingredient_fdc_map, deduplicate by ingredient_vn
            existing_map = recipe_obj.get("ingredient_fdc_map", []) or []
            existing_by_vn = {item.get("ingredient_vn"): item for item in existing_map if isinstance(item, dict)}
            
            # Update or add new mappings
            for new_item in ingredient_map:
                vn = new_item.get("ingredient_vn", "")
                if vn in existing_by_vn:
                    # Check for mismatches (different fdc_id for same ingredient)
                    existing_fdc = existing_by_vn[vn].get("fdc_id")
                    new_fdc = new_item.get("fdc_id")
                    if existing_fdc != new_fdc:
                        logger.warning(
                            f"Recipe {recipe_obj.get('food_id')}: ingredient '{vn}' has FDC mismatch "
                            f"(existing: {existing_fdc}, new: {new_fdc}). Using new mapping."
                        )
                    # Update with new mapping (higher confidence or more recent)
                    existing_by_vn[vn] = new_item
                else:
                    existing_by_vn[vn] = new_item
            
            # Convert back to list
            deduplicated_map = list(existing_by_vn.values())
            
            # Persist to Weaviate
            collection.data.update(
                uuid=recipe_uuid,
                properties={
                    "macros_per_serving": macros_per_serving,
                    "ingredient_fdc_map": deduplicated_map,
                },
            )
            
            logger.info(
                f"Updated Recipe {recipe_obj.get('food_id')}: "
                f"macros_per_serving cached, {len(deduplicated_map)} ingredient mappings persisted"
            )

        yield Result(
            name="macros",
            objects=[macros_per_serving],
            metadata={
                "source": "calculated",
                "recipe_id": recipe_obj.get("food_id"),
                "ingredients_mapped": len(ingredient_map),
            },
            payload_type="generic",
            display=True,
        )
        yield Response(f"Calculated macros: {macros_per_serving['kcal']:.0f} kcal per serving")

    except Exception as e:
        yield Error(f"Macro calculation failed: {str(e)}")
        return

