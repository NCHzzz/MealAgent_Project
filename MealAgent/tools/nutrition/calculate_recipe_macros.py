from typing import AsyncGenerator, Dict, Any, List, Optional
import json
import logging
import re

from elysia.tree.objects import TreeData
from elysia.objects import Result, Error, Response
from elysia.util.client import ClientManager
from elysia import tool
import dspy
from elysia.util.elysia_chain_of_thought import ElysiaChainOfThought

from MealAgent.tools.utils.weaviate_filters import build_filters_from_where

logger = logging.getLogger(__name__)


PIECE_UNIT_DEFAULT_G = {
    "củ": 80.0,
    "quả": 80.0,
    "trái": 80.0,
    "piece": 80.0,
    "muỗng": 15.0,
    "muỗng canh": 15.0,
    "muỗng cà phê": 5.0,
    "thìa": 5.0,
    "thìa cà phê": 5.0,
    "tablespoon": 15.0,
    "teaspoon": 5.0,
}


def _normalise_unit(unit: str) -> str:
    """Collapse common Vietnamese measurement units into canonical names."""
    if not unit:
        return "g"
    unit = unit.strip().lower()
    mapping = {
        "gr": "g",
        "gram": "g",
        "grams": "g",
        "kg": "kg",
        "kilogram": "kg",
        "kilograms": "kg",
        "ml": "ml",
        "milliliter": "ml",
        "milliliters": "ml",
        "l": "l",
        "liter": "l",
        "liters": "l",
        "quả": "piece",
        "trái": "piece",
        "củ": "piece",
        "miếng": "piece",
        "muỗng": "tablespoon",
        "muỗng canh": "tablespoon",
        "thìa": "teaspoon",
        "thìa cà phê": "teaspoon",
    }
    return mapping.get(unit, unit or "g")


def _parse_number(value: str) -> Optional[float]:
    """Convert common numeric formats (including fractions) to float."""
    if not value:
        return None
    value = value.strip().replace(",", ".")
    if "/" in value:
        parts = value.split("/")
        if len(parts) == 2:
            try:
                numerator = float(parts[0])
                denominator = float(parts[1])
                if denominator != 0:
                    return numerator / denominator
            except ValueError:
                return None
    try:
        return float(value)
    except ValueError:
        return None


def _extract_quantity_from_text(text: str) -> tuple[Optional[float], str]:
    """
    Extract approximate quantity (in grams) and cleaned ingredient name from raw text.
    Returns (quantity_g, name_without_measurements).
    """
    if not text:
        return None, ""

    normalized = text.strip()
    pattern = re.compile(
        r"(?P<num>[\d.,/]+)\s*(?P<unit>kg|kilogram|grams?|gram|gr|g|ml|milliliter|l|liter|muỗng\s*cánh?|muỗng|muong|thìa|thia|củ|quả|trái|piece)",
        re.IGNORECASE,
    )
    match = pattern.search(normalized)

    quantity_g = None
    cleaned_name = normalized

    if match:
        raw_num = match.group("num")
        raw_unit = match.group("unit").lower().strip()
        parsed = _parse_number(raw_num)
        unit = _normalise_unit(raw_unit)

        if parsed is not None:
            if unit == "kg":
                quantity_g = parsed * 1000.0
            elif unit in {"g", "gram"}:
                quantity_g = parsed
            elif unit in {"l", "ml"}:
                # Approximate 1 ml == 1 g for water-based ingredients
                multiplier = 1000.0 if unit == "l" else 1.0
                quantity_g = parsed * multiplier
            else:
                default_weight = PIECE_UNIT_DEFAULT_G.get(unit, 80.0)
                quantity_g = parsed * default_weight

        cleaned_name = pattern.sub("", normalized).strip(" ,.-")

    cleaned_name = re.sub(r"\d+", "", cleaned_name).strip(" ,.-")
    return quantity_g, cleaned_name or normalized


def _sanitize_ingredient_query(text: str) -> str:
    """Remove numeric tokens and measurement terms from search query."""
    if not text:
        return ""
    text = re.sub(r"[\d.,/]+", " ", text)
    text = re.sub(
        r"\b(kg|kilogram|grams?|gram|gr|g|ml|milliliter|l|liter|muỗng\s*cánh?|muỗng|muong|thìa|thia|củ|quả|trái|piece)\b",
        " ",
        text,
        flags=re.IGNORECASE,
    )
    return re.sub(r"\s+", " ", text).strip()


async def _translate_ingredients_vn_to_en(
    ingredients_vn: List[str],
    base_lm,
    tree_data: TreeData | None = None,
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
            tree_data=tree_data,
            reasoning=False,
            impossible=False,
            message_update=True,
        )
        # Call the prediction - pass raw list; dspy will serialize
        pred = await cot.aforward(lm=base_lm, ingredients_vn=ingredients_vn)
        translations = pred.translations
        if isinstance(translations, str):
            try:
                translations = json.loads(translations)
            except json.JSONDecodeError as exc:
                logger.warning("Ingredient translation returned invalid JSON: %s", exc)
                translations = []

        if not isinstance(translations, list):
            raise ValueError("Invalid translation output")

        cleaned: List[Dict[str, Any]] = []
        for raw in translations:
            if not isinstance(raw, dict):
                continue
            vn = str(raw.get("vn", "")).strip()
            en = str(raw.get("en") or vn).strip()
            quantity_raw = raw.get("quantity")
            unit = _normalise_unit(str(raw.get("unit", "g")))

            quantity = None
            if quantity_raw is not None:
                parsed = _parse_number(str(quantity_raw))
                if parsed is not None and parsed > 0:
                    quantity = parsed

            if quantity is None or quantity <= 0:
                fallback_qty, cleaned_name = _extract_quantity_from_text(vn)
                quantity = fallback_qty or 100.0
                if cleaned_name:
                    vn = cleaned_name
                cleaned_en = _sanitize_ingredient_query(en)
                en = cleaned_en or en

            if vn:
                cleaned.append(
                    {
                        "vn": vn,
                        "en": _sanitize_ingredient_query(en) or en or vn,
                        "quantity": quantity,
                        "unit": unit,
                    }
                )

        if cleaned:
            return cleaned
        logger.warning("Ingredient translation returned no structured rows, using fallback.")
    except Exception as exc:
        logger.warning("Ingredient translation failed (%s), using fallback.", exc)

    # Fallback: return original names as English
    fallback_entries: List[Dict[str, Any]] = []
    for ing in ingredients_vn:
        qty, cleaned_name = _extract_quantity_from_text(str(ing))
        fallback_entries.append(
            {
                "vn": cleaned_name or str(ing),
                "en": _sanitize_ingredient_query(cleaned_name or str(ing)),
                "quantity": qty or 100.0,
                "unit": "g",
            }
        )
    return fallback_entries


def _pick_best_fdc_match(objects: List[Any], ingredient_clean: str, threshold: float) -> Optional[Dict[str, Any]]:
    """Pick the best matching FDC food entry from a list of candidates."""
    best_obj = None
    best_score = 0.0
    tokens = [tok for tok in ingredient_clean.split() if len(tok) > 2]

    for obj in objects or []:
        props = getattr(obj, "properties", None)
        if not props:
            continue
        score = 1.0
        metadata = getattr(obj, "metadata", None)
        if metadata:
            score = float(getattr(metadata, "score", getattr(metadata, "distance", 1.0)))
        description = str(props.get("description", "")).lower()
        if ingredient_clean in description:
            score = max(score, 0.9)
        elif any(tok in description for tok in tokens):
            score = max(score, 0.7)
        if score > best_score and score >= threshold:
            best_score = score
            best_obj = props
    return best_obj


async def _find_fdc_food(
    ingredient_en: str,
    client,
    threshold: float = 0.55,
    limit: int = 3,
) -> Optional[Dict[str, Any]]:
    """Search FDC for ingredient and return best match if score > threshold."""
    ingredient_clean = _sanitize_ingredient_query(ingredient_en or "").lower()
    if not ingredient_clean:
        return None

    try:
        collection = client.collections.get("FdcFood")
    except Exception as exc:
        logger.error("Unable to access FdcFood collection: %s", exc)
        return None

    # Strategy 1: Hybrid search
    try:
        results = collection.query.hybrid(query=ingredient_clean, limit=limit, alpha=0.5)
        match = _pick_best_fdc_match(results.objects, ingredient_clean, threshold)
        if match:
            return match
    except Exception as exc:
        logger.debug("Hybrid FDC search failed for '%s': %s", ingredient_clean, exc)

    # Strategy 2: BM25 fallback
    try:
        bm25_results = collection.query.bm25(query=ingredient_clean, limit=limit)
        match = _pick_best_fdc_match(bm25_results.objects, ingredient_clean, threshold * 0.9)
        if match:
            return match
    except Exception as exc:
        logger.debug("BM25 FDC search failed for '%s': %s", ingredient_clean, exc)

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


def _record_status(tree_data: TreeData, status: str, payload: Dict[str, Any]) -> None:
    """Persist status info to the Elysia environment for downstream tools."""
    try:
        tree_data.environment.add_objects(
            "calculate_recipe_macros_tool",
            status,
            [payload],
        )
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("Failed to write nutrition status to environment: %s", exc)


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
    Translate Vietnamese recipes to English ingredients, map to FDC foods, and cache macros per serving.

    Workflow:
      1. Resolve the Recipe object (either by `recipe_id` or direct payload).
      2. Short-circuit if `macros_per_serving.kcal > 0` (cached case).
      3. Translate `ingredients_with_qty` / `ingredients` via `base_lm`.
      4. Hybrid + BM25 search against `FdcFood`, compute macros per ingredient, sum, divide by servings.
      5. Persist `macros_per_serving` + `ingredient_fdc_map` back to Weaviate (with dedupe).

    Environment contract:
      Reads
        • Recipe records via Weaviate client (no intermediate environment dependency).
      Writes
        • `calculate_recipe_macros_tool.success` / `.error` status entries (for orchestration).
        • Result `macros` payload (used by search/planning tools).

    Decision hints:
      • Presence of `calculate_recipe_macros_tool.macros` means nutrition is ready.
      • `calculate_recipe_macros_tool.error` entries describe blocking ingredients; nutrition branch should review before retrying.
    """
    yield Response("🧮 Calculating recipe nutrition (macros per serving)...")

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
            yield Response("✅ Nutrition data retrieved from cache")
            return

        # Need to calculate: translate ingredients
        ingredients_vn = recipe_obj.get("ingredients_with_qty", []) or recipe_obj.get("ingredients", [])
        if not ingredients_vn:
            yield Error("Recipe has no ingredients to calculate macros from")
            return

        translated = await _translate_ingredients_vn_to_en(ingredients_vn, base_lm, tree_data)

        # Find FDC foods and calculate macros
        total_macros = {"kcal": 0.0, "protein_g": 0.0, "fat_g": 0.0, "carb_g": 0.0}
        ingredient_map = []
        found_count = 0
        not_found_ingredients = []

        for item in translated:
            ingredient_en = item.get("en", "")
            ingredient_vn = item.get("vn", "")
            quantity_g = float(item.get("quantity", 100.0))

            fdc_food = await _find_fdc_food(ingredient_en, client)
            if fdc_food:
                ingredient_macros = _calculate_macros_from_fdc(fdc_food, quantity_g)
                for key in total_macros:
                    total_macros[key] += ingredient_macros[key]

                ingredient_map.append({
                    "ingredient_vn": ingredient_vn,
                    "ingredient_en": ingredient_en,
                    "fdc_id": int(fdc_food.get("fdc_id", 0)),
                    "quantity_g": quantity_g,
                    "confidence": 0.8,  # Could be improved with actual match score
                })
                found_count += 1
            else:
                not_found_ingredients.append(ingredient_vn or ingredient_en)

        # Check if we found any FDC foods - if not, don't update with zeros
        if found_count == 0:
            message = (
                "Could not find nutrition data for any ingredients. "
                "Please ensure ingredients are in English or check FDC database. "
                f"Ingredients tried: {', '.join(not_found_ingredients[:5])}"
            )
            _record_status(
                tree_data,
                "error",
                {
                    "recipe_id": recipe_obj.get("food_id"),
                    "reason": "no_fdc_match",
                    "ingredients": not_found_ingredients[:10],
                },
            )
            yield Error(message)
            return

        # Warn if some ingredients were not found
        if not_found_ingredients:
            yield Response(
                f"⚠️ Could not find nutrition data for {len(not_found_ingredients)} ingredient(s): "
                f"{', '.join(not_found_ingredients[:3])}. "
                f"Calculated macros may be incomplete."
            )

        # Divide by serving_size to get per-serving macros
        serving_size = float(recipe_obj.get("serving_size", 1.0))
        if serving_size > 0:
            macros_per_serving = {k: v / serving_size for k, v in total_macros.items()}
        else:
            macros_per_serving = total_macros

        # Only update if macros are non-zero (at least kcal > 0)
        if macros_per_serving.get("kcal", 0) <= 0:
            message = (
                "Calculated macros are zero or invalid. "
                f"Found FDC data for {found_count}/{len(translated)} ingredients. "
                "Please check ingredient names and FDC database."
            )
            _record_status(
                tree_data,
                "error",
                {
                    "recipe_id": recipe_obj.get("food_id"),
                    "reason": "zero_macros",
                    "found_count": found_count,
                    "ingredient_count": len(translated),
                },
            )
            yield Error(message)
            return

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
                "not_found": len(not_found_ingredients),
            },
            payload_type="generic",
            display=True,
        )
        _record_status(
            tree_data,
            "success",
            {
                "recipe_id": recipe_obj.get("food_id"),
                "ingredients_mapped": len(ingredient_map),
                "missing": len(not_found_ingredients),
                "kcal": macros_per_serving.get("kcal"),
            },
        )
        yield Response(
            f"✅ Calculated nutrition: {macros_per_serving['kcal']:.0f} kcal/serving | "
            f"{macros_per_serving['protein_g']:.0f}g protein | "
            f"{macros_per_serving['carb_g']:.0f}g carbs"
        )

    except Exception as e:
        _record_status(
            tree_data,
            "error",
            {
                "recipe_id": recipe_id or (recipe or {}).get("food_id"),
                "reason": "exception",
                "message": str(e),
            },
        )
        yield Error(f"Macro calculation failed: {str(e)}")
        return

