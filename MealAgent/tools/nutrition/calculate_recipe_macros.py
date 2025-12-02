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
logger.setLevel(logging.INFO)


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


COOKING_METHOD_HEURISTICS = [
    {
        "label": "deep-fried",
        "keywords": [
            "chiên giòn",
            "rán",
            "deep fry",
            "deep-fry",
            "fried",
            "khoai lang chiên",
            "tempura",
        ],
        "oil_per_serving_g": 18.0,  # ≈160 kcal extra fat per serving
    },
    {
        "label": "pan-fried",
        "keywords": [
            "chiên",
            "áp chảo",
            "pan fry",
            "pan-fry",
            "seared",
            "rán áp chảo",
            "lá nướng chảo",
        ],
        "oil_per_serving_g": 12.0,
    },
    {
        "label": "stir-fried",
        "keywords": [
            "xào",
            "stir fry",
            "stir-fry",
            "sauté",
            "phi thơm",
            "rang",
        ],
        "oil_per_serving_g": 9.0,
    },
]


SAUCE_RICH_HEURISTICS = [
    {
        "label": "creamy/cheesy sauce",
        "keywords": [
            "sốt kem",
            "sốt phô mai",
            "cream sauce",
            "cheese sauce",
            "alfredo",
            "carbonara",
            "béo ngậy",
        ],
        "extra_fat_per_serving_g": 10.0,  # ≈90 kcal
    },
    {
        "label": "mayonnaise / rich dressing",
        "keywords": [
            "sốt mayo",
            "mayonnaise",
            "sốt trứng béo",
            "salad dressing",
            "ranch",
            "caesar",
        ],
        "extra_fat_per_serving_g": 8.0,
    },
]


SWEET_DESSERT_HEURISTICS = [
    {
        "label": "sweet dessert / chè",
        "keywords": [
            "chè",
            "tráng miệng",
            "dessert",
            "bánh ngọt",
            "bánh kem",
            "pudding",
            "mousse",
            "custard",
            "sữa đặc",
        ],
        "extra_carb_per_serving_g": 20.0,  # ≈80 kcal
    },
    {
        "label": "sweet drink / sữa / trà sữa",
        "keywords": [
            "trà sữa",
            "sữa tươi đường",
            "sinh tố",
            "smoothie",
            "frappe",
        ],
        "extra_carb_per_serving_g": 15.0,
    },
]


def _detect_cooking_method(
    recipe_obj: Dict[str, Any],
    translated: List[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Inspect recipe metadata and translated ingredients to infer cooking method."""
    text_blobs: List[str] = []

    for key in ("dish_name", "description", "cooking_method", "instructions"):
        value = recipe_obj.get(key)
        if isinstance(value, list):
            text_blobs.extend([str(item) for item in value])
        elif isinstance(value, str):
            text_blobs.append(value)

    for field in ("ingredients_with_qty", "ingredients"):
        value = recipe_obj.get(field)
        if isinstance(value, list):
            text_blobs.extend([str(item) for item in value])
        elif isinstance(value, str):
            text_blobs.append(value)

    for entry in translated:
        text_blobs.append(entry.get("vn", ""))
        text_blobs.append(entry.get("en", ""))

    merged_text = " ".join(text_blobs).lower()

    for heuristic in COOKING_METHOD_HEURISTICS:
        if any(keyword in merged_text for keyword in heuristic["keywords"]):
            return heuristic

    return None


def _detect_rich_sauce(
    recipe_obj: Dict[str, Any],
    translated: List[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Heuristically detect rich/creamy sauces that likely add extra fat."""
    text_blobs: List[str] = []

    for key in ("dish_name", "description", "cooking_method", "instructions"):
        value = recipe_obj.get(key)
        if isinstance(value, list):
            text_blobs.extend([str(item) for item in value])
        elif isinstance(value, str):
            text_blobs.append(value)

    for entry in translated:
        text_blobs.append(entry.get("vn", ""))
        text_blobs.append(entry.get("en", ""))

    merged_text = " ".join(text_blobs).lower()

    for heuristic in SAUCE_RICH_HEURISTICS:
        if any(keyword in merged_text for keyword in heuristic["keywords"]):
            return heuristic

    return None


def _detect_sugary_dessert(
    recipe_obj: Dict[str, Any],
    translated: List[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Heuristically detect very sweet desserts / drinks that likely under-report carbs."""
    text_blobs: List[str] = []

    for key in ("dish_name", "description", "cooking_method"):
        value = recipe_obj.get(key)
        if isinstance(value, list):
            text_blobs.extend([str(item) for item in value])
        elif isinstance(value, str):
            text_blobs.append(value)

    for entry in translated:
        text_blobs.append(entry.get("vn", ""))
        text_blobs.append(entry.get("en", ""))

    merged_text = " ".join(text_blobs).lower()

    for heuristic in SWEET_DESSERT_HEURISTICS:
        if any(keyword in merged_text for keyword in heuristic["keywords"]):
            return heuristic

    return None


async def _translate_ingredients_vn_to_en(
    ingredients_vn: List[str],
    base_lm,
    tree_data: TreeData | None = None,
) -> List[Dict[str, Any]]:
    """Translate Vietnamese ingredients to English using LLM."""
    if not ingredients_vn:
        return []

    if base_lm is None:
        logger.warning(
            "Ingredient translation: no base_lm configured, using rule-based fallback only "
            f"for {len(ingredients_vn)} ingredient(s)."
        )
    else:
        logger.warning(
            "Ingredient translation: using LM (%s) for %d ingredient(s).",
            getattr(getattr(base_lm, 'model', None), 'name', None) or getattr(base_lm, 'model', None) or "unknown-model",
            len(ingredients_vn),
        )

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
            logger.warning(
                "Ingredient translation: LM produced %d structured row(s), proceeding with FDC lookup.",
                len(cleaned),
            )
            return cleaned
        logger.warning("Ingredient translation returned no structured rows, using fallback.")
    except Exception as exc:
        logger.warning("Ingredient translation failed (%s), using fallback.", exc)

    # Fallback: return original names as English
    logger.warning(
        "Ingredient translation: falling back to heuristic parser for %d ingredient(s).",
        len(ingredients_vn),
    )
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
            raw_score = getattr(metadata, "score", None)
            if raw_score is None:
                raw_score = getattr(metadata, "distance", None)
            try:
                score = float(raw_score) if raw_score is not None else score
            except (TypeError, ValueError):
                score = 1.0
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


def _safe_float(value: Any, default: float = 0.0) -> float:
    """Convert value to float safely, falling back to default on None/invalid."""
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _calculate_macros_from_fdc(
    fdc_food: Dict[str, Any],
    quantity_g: float,
) -> Dict[str, float]:
    """Calculate macros from FDC food per-100g values scaled by quantity."""
    # FDC stores per-100g values
    scale = quantity_g / 100.0

    return {
        "kcal": _safe_float(fdc_food.get("energy_kcal_100g"), 0.0) * scale,
        "protein_g": _safe_float(fdc_food.get("protein_g_100g"), 0.0) * scale,
        "fat_g": _safe_float(fdc_food.get("fat_g_100g"), 0.0) * scale,
        "carb_g": _safe_float(fdc_food.get("carbohydrate_g_100g"), 0.0) * scale,
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


async def _estimate_recipe_macros_with_lm(
    recipe_obj: Dict[str, Any],
    translated_ingredients: List[Dict[str, Any]],
    base_lm,
    tree_data: TreeData | None = None,
) -> Optional[Dict[str, float]]:
    """
    Fallback: ask the LM (e.g. Gemini) to estimate macros per serving when FDC lookup fails.

    This is used when:
      - No ingredient could be mapped to FDC, or
      - Aggregated macros from FDC end up as zero/invalid.
    """
    if base_lm is None:
        return None

    dish_name = str(recipe_obj.get("dish_name") or recipe_obj.get("food_name") or "").strip()
    serving_size = float(recipe_obj.get("serving_size", 1.0) or 1.0)

    # Build a compact ingredient description for the prompt
    ing_summary = []
    for item in translated_ingredients:
        vn = item.get("vn") or ""
        en = item.get("en") or ""
        qty = item.get("quantity") or ""
        unit = item.get("unit") or ""
        label = en or vn
        ing_summary.append(f"- {label} ({vn}) ~ {qty} {unit}".strip())

    try:
        class MacroEstimateSignature(dspy.Signature):
            """
            Given a Vietnamese dish and its ingredients, estimate realistic nutrition per serving.

            Return a JSON-like object with numeric fields:
              - kcal: total kilocalories per serving
              - protein_g: grams of protein per serving
              - fat_g: grams of fat per serving
              - carb_g: grams of carbohydrates per serving

            Be conservative and avoid extreme values; use typical Vietnamese home-cooking portions.
            """

            dish_name = dspy.InputField(description="Name of the dish (Vietnamese).")
            servings = dspy.InputField(description="Number of servings for the recipe.")
            ingredients = dspy.InputField(description="List of ingredients with rough quantity and unit.")
            reasoning = dspy.OutputField(description="Short explanation of how the macros were estimated.")
            macros = dspy.OutputField(
                description=(
                    "Estimated macros per serving as an object: "
                    '{"kcal": float, "protein_g": float, "fat_g": float, "carb_g": float}'
                )
            )

        cot = ElysiaChainOfThought(
            MacroEstimateSignature,
            tree_data=tree_data,
            reasoning=True,
            impossible=False,
            message_update=False,
        )

        pred = await cot.aforward(
            lm=base_lm,
            dish_name=dish_name,
            servings=serving_size,
            ingredients="\n".join(ing_summary),
        )

        macros = getattr(pred, "macros", None)
        if isinstance(macros, str):
            try:
                macros = json.loads(macros)
            except json.JSONDecodeError as exc:
                logger.warning("LM macro estimate returned invalid JSON: %s", exc)
                macros = None

        if not isinstance(macros, dict):
            return None

        est = {
            "kcal": _safe_float(macros.get("kcal"), 0.0),
            "protein_g": _safe_float(macros.get("protein_g"), 0.0),
            "fat_g": _safe_float(macros.get("fat_g"), 0.0),
            "carb_g": _safe_float(macros.get("carb_g"), 0.0),
        }

        # Basic sanity check: require strictly positive kcal
        if est["kcal"] <= 0:
            return None

        logger.info(
            "LM macro fallback used for recipe %s: %.0f kcal, %.1fg protein",
            recipe_obj.get("food_id"),
            est["kcal"],
            est["protein_g"],
        )
        return est
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("LM macro fallback failed: %s", exc)
        return None


@tool
async def calculate_recipe_macros_tool(
    tree_data: TreeData,
    client_manager: ClientManager,
    base_lm,  # LLM for VN→EN translation
    recipe_id: Optional[str] = None,
    recipe: Optional[Dict[str, Any]] = None,
    force_recalculate: bool = False,
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
        try:
            collection = client.collections.get("Recipe")
        except Exception as e:
            yield Error(f"Recipe collection not found: {str(e)}. Please ensure collections are created.")
            return

        # Get recipe
        recipe_obj = recipe
        if not recipe_obj and recipe_id:
            recipe_filter = build_filters_from_where(
                {"path": ["food_id"], "operator": "Equal", "valueString": recipe_id}
            )
            results = collection.query.fetch_objects(filters=recipe_filter, limit=1)
            if not results.objects:
                yield Error(
                    f"Recipe not found: {recipe_id}. "
                    "Please check that the recipe exists in the Recipe collection."
                )
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

        # Check if macros already cached (unless caller explicitly forces recalculation)
        macros = recipe_obj.get("macros_per_serving")
        if (
            not force_recalculate
            and macros
            and isinstance(macros, dict)
            and macros.get("kcal")
        ):
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
            yield Error(
                "Cannot calculate nutrition: Recipe has no ingredients. "
                "Please ensure the recipe has ingredients_with_qty or ingredients fields populated."
            )
            return

        translated = await _translate_ingredients_vn_to_en(ingredients_vn, base_lm, tree_data)

        # Find FDC foods and calculate macros
        # OPTIMIZATION: Cache lookups to avoid duplicate searches
        fdc_cache: Dict[str, Optional[Dict[str, Any]]] = {}
        total_macros = {"kcal": 0.0, "protein_g": 0.0, "fat_g": 0.0, "carb_g": 0.0}
        ingredient_map = []
        found_count = 0
        not_found_ingredients = []

        for item in translated:
            ingredient_en = item.get("en", "")
            ingredient_vn = item.get("vn", "")
            quantity_raw = item.get("quantity")
            # Handle None explicitly - default to 100g if quantity is None or invalid
            try:
                quantity_g = float(quantity_raw) if quantity_raw is not None else 100.0
            except (TypeError, ValueError) as e:
                logger.warning(
                    f"Invalid quantity '{quantity_raw}' for ingredient '{ingredient_vn or ingredient_en}'. "
                    f"Using default 100g. Error: {str(e)}"
                )
                quantity_g = 100.0

            # Check cache first
            cache_key = ingredient_en.lower().strip()
            if cache_key in fdc_cache:
                fdc_food = fdc_cache[cache_key]
            else:
                fdc_food = await _find_fdc_food(ingredient_en, client)
                if fdc_food:
                    fdc_cache[cache_key] = fdc_food
            
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

        serving_size = float(recipe_obj.get("serving_size", 1.0) or 1.0)
        if serving_size <= 0:
            serving_size = 1.0

        # Check if we found any FDC foods - if not, don't update with zeros
        if found_count == 0:
            # Try LM-based fallback before giving up
            lm_macros = await _estimate_recipe_macros_with_lm(
                recipe_obj, translated, base_lm, tree_data
            )
            if not lm_macros:
                message = (
                    "Could not find nutrition data for any ingredients and LM fallback failed. "
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

            # Use LM-estimated macros directly per serving
            macros_per_serving = lm_macros
            ingredient_map = []  # no FDC mapping in this path
            not_found_ingredients = translated  # all ingredients effectively unmatched

        # Warn if some ingredients were not found
        if not_found_ingredients:
            yield Response(
                f"⚠️ Could not find nutrition data for {len(not_found_ingredients)} ingredient(s): "
                f"{', '.join(not_found_ingredients[:3])}. "
                f"Calculated macros may be incomplete."
            )

        if "macros_per_serving" not in locals():
            # Heuristic 1: cooking oil for fried / stir-fried dishes
            method_heuristic = _detect_cooking_method(recipe_obj, translated)
            if method_heuristic:
                oil_total_g = method_heuristic["oil_per_serving_g"] * serving_size
                if oil_total_g > 0:
                    total_macros["fat_g"] += oil_total_g
                    total_macros["kcal"] += oil_total_g * 9.0
                    yield Response(
                        f"ℹ️ Detected {method_heuristic['label']} preparation — "
                        f"adding ~{method_heuristic['oil_per_serving_g']:.0f}g cooking oil per serving "
                        "to better reflect calories/fats."
                    )

            # Heuristic 2: rich/creamy sauces (extra fat)
            sauce_heuristic = _detect_rich_sauce(recipe_obj, translated)
            if sauce_heuristic:
                extra_fat_total_g = sauce_heuristic["extra_fat_per_serving_g"] * serving_size
                if extra_fat_total_g > 0:
                    total_macros["fat_g"] += extra_fat_total_g
                    total_macros["kcal"] += extra_fat_total_g * 9.0
                    yield Response(
                        f"ℹ️ Detected {sauce_heuristic['label']} — "
                        f"adding ~{sauce_heuristic['extra_fat_per_serving_g']:.0f}g sauce fat per serving."
                    )

            # Heuristic 3: very sweet desserts / drinks (extra carbs)
            sweet_heuristic = _detect_sugary_dessert(recipe_obj, translated)
            if sweet_heuristic:
                extra_carb_total_g = sweet_heuristic["extra_carb_per_serving_g"] * serving_size
                if extra_carb_total_g > 0:
                    total_macros["carb_g"] += extra_carb_total_g
                    total_macros["kcal"] += extra_carb_total_g * 4.0
                    yield Response(
                        f"ℹ️ Detected {sweet_heuristic['label']} — "
                        f"adding ~{sweet_heuristic['extra_carb_per_serving_g']:.0f}g sugars per serving."
                    )

            macros_per_serving = {k: v / serving_size for k, v in total_macros.items()}

            # Only update if macros are non-zero (at least kcal > 0); otherwise fallback to LM
            if macros_per_serving.get("kcal", 0) <= 0:
                lm_macros = await _estimate_recipe_macros_with_lm(
                    recipe_obj, translated, base_lm, tree_data
                )
                if not lm_macros:
                    message = (
                        "Calculated macros are zero or invalid and LM fallback failed. "
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

                macros_per_serving = lm_macros

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

