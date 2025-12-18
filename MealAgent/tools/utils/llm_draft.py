"""
LLM Draft helper functions for Phase 2.1.

Generates meal framework suggestions using LLM, with fallback to rule-based selection.
"""

import json
import logging
import re
import random
from typing import Dict, Any, List, Optional

try:
    import dspy
    from elysia.util.elysia_chain_of_thought import ElysiaChainOfThought
    DSPY_AVAILABLE = True
except ImportError:
    DSPY_AVAILABLE = False

from MealAgent.schemas.llm_draft import LLMDraftResponse, MealSlotDraft, MealDraftSuggestion

logger = logging.getLogger(__name__)


def _clean_json_string(text: str) -> str:
    """Clean control characters and normalize text for JSON parsing."""
    if not text:
        return ""
    # Remove control characters (but keep newlines/tabs that are escaped)
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]', '', text)
    # Replace smart quotes with regular quotes
    text = text.replace('\u201c', '"').replace('\u201d', '"').replace('\u2018', "'").replace('\u2019', "'")
    return text.strip()


def _extract_json_objects(text: str) -> List[Dict[str, Any]]:
    """
    Extract JSON objects from text using balanced brace matching.
    Simple and robust fallback for malformed JSON.
    """
    if not text:
        return []
    
    text = _clean_json_string(text)
    objects = []
    brace_count = 0
    start_idx = None
    in_string = False
    escape_next = False
    
    for idx, char in enumerate(text):
        if escape_next:
            escape_next = False
            continue
        
        if char == '\\' and in_string:
            escape_next = True
            continue
        
        if char == '"' and not escape_next:
            in_string = not in_string
            continue
        
        if not in_string:
            if char == '{':
                if brace_count == 0:
                    start_idx = idx
                brace_count += 1
            elif char == '}':
                brace_count -= 1
                if brace_count == 0 and start_idx is not None:
                    obj_str = text[start_idx:idx+1]
                    try:
                        obj = json.loads(obj_str)
                        if isinstance(obj, dict):
                            objects.append(obj)
                    except json.JSONDecodeError:
                        pass
                    start_idx = None
    
    return objects


def _parse_json_response(response_text: str) -> Optional[List[Dict[str, Any]]]:
    """
    Parse LLM JSON response with simplified, robust logic.
    Returns list of dicts or None if parsing fails completely.
    """
    if not response_text or not isinstance(response_text, str):
        return None
    
    original_text = response_text
    response_text = _clean_json_string(response_text)
    
    # Remove markdown code blocks if present
    if "```json" in response_text:
        json_start = response_text.find("```json") + 7
        json_end = response_text.find("```", json_start)
        if json_end != -1:
            response_text = response_text[json_start:json_end].strip()
    elif "```" in response_text:
        json_start = response_text.find("```") + 3
        json_end = response_text.find("```", json_start)
        if json_end != -1:
            response_text = response_text[json_start:json_end].strip()
    
    # Try to parse as JSON
    try:
        data = json.loads(response_text)
        
        # Case 1: Already a list of dicts - perfect!
        if isinstance(data, list) and data and isinstance(data[0], dict):
            logger.debug(f"Successfully parsed {len(data)} objects directly")
            return data
        
        # Case 2: List of strings - could be JSON strings or plain dish names
        if isinstance(data, list) and data and isinstance(data[0], str):
            logger.debug(f"Detected array of {len(data)} strings, parsing each...")
            parsed_objects = []
            
            for idx, json_str in enumerate(data):
                if not isinstance(json_str, str):
                    continue
                
                clean_str = _clean_json_string(json_str)
                if not clean_str:
                    continue
                
                # Try to parse as JSON object first
                try:
                    obj = json.loads(clean_str)
                    if isinstance(obj, dict):
                        parsed_objects.append(obj)
                        logger.debug(f"Successfully parsed object {idx+1}/{len(data)}")
                    elif isinstance(obj, list):
                        parsed_objects.extend([x for x in obj if isinstance(x, dict)])
                    continue
                except json.JSONDecodeError:
                    pass
                
                # Try balanced brace extraction
                extracted = _extract_json_objects(clean_str)
                if extracted:
                    parsed_objects.extend(extracted)
                    logger.debug(f"Extracted {len(extracted)} object(s) from string {idx+1} using balanced braces")
                    continue
                
                # Fallback: If it's a plain string (dish name), convert to object
                # This handles cases where LLM returns ["Dish name 1", "Dish name 2", ...]
                if clean_str and not clean_str.startswith('{') and not clean_str.startswith('['):
                    # It's a plain dish name, create a basic object structure
                    # We'll let _normalize_suggestion handle the details
                    logger.debug(f"Detected plain string (dish name) at index {idx+1}: {clean_str[:50]}...")
                    parsed_objects.append({"dish_name": clean_str})
            
            if parsed_objects:
                logger.debug(f"Successfully parsed {len(parsed_objects)} objects from array of strings")
                return parsed_objects
            else:
                logger.warning(f"Failed to parse any objects from array of {len(data)} strings")
                return None
        
        # Case 3: Single dict
        if isinstance(data, dict):
            if "suggestions" in data and isinstance(data["suggestions"], list):
                return data["suggestions"]
            return [data]
            
    except json.JSONDecodeError as e:
        logger.debug(f"Initial JSON parse failed: {e}, trying extraction...")
    
    # Fallback: Try to extract JSON objects using balanced braces
    objects = _extract_json_objects(response_text)
    if objects:
        logger.debug(f"Extracted {len(objects)} object(s) using balanced braces")
        return objects
    
    # Final fallback - log and return None
    logger.warning(f"Failed to parse LLM JSON response. First 500 chars: {original_text[:500]}")
    return None


def _normalize_suggestion(item: Dict[str, Any], meal_slot: str) -> Optional[MealDraftSuggestion]:
    """Normalize a suggestion dict to MealDraftSuggestion schema."""
    if not isinstance(item, dict):
        return None
    
    # If item only has "dish_name" (from plain string fallback), generate other fields
    if "dish_name" in item and len(item) == 1:
        dish_name = str(item["dish_name"])
        # Generate general_term from dish_name
        general_term = dish_name.lower()
        # Remove Vietnamese diacritics and normalize
        try:
            import unicodedata
            general_term = unicodedata.normalize('NFD', general_term)
            general_term = ''.join(c for c in general_term if unicodedata.category(c) != 'Mn')
        except ImportError:
            pass
        general_term = re.sub(r'[^a-z0-9\s-]', '', general_term)
        general_term = re.sub(r'\s+', '-', general_term).strip('-')
        
        item["general_term"] = general_term
        item["meal_type"] = meal_slot
        
        # Infer role and category from dish_name
        dish_name_lower = dish_name.lower()
        if meal_slot == "breakfast":
            item["role"] = "breakfast"
            if any(kw in dish_name_lower for kw in ["bánh mì", "banh mi", "bread"]):
                item["category"] = "bread"
            elif any(kw in dish_name_lower for kw in ["phở", "pho", "bún", "bun", "mì", "mi", "noodle"]):
                item["category"] = "noodle"
            else:
                item["category"] = "bread"  # Default for breakfast
        else:
            # For lunch/dinner, infer role and category
            if any(kw in dish_name_lower for kw in ["cơm", "com", "rice"]):
                item["role"] = "carb"
                item["category"] = "rice"
            elif any(kw in dish_name_lower for kw in ["phở", "pho", "bún", "bun", "mì", "mi", "noodle"]):
                item["role"] = "carb"
                item["category"] = "noodle"
            elif any(kw in dish_name_lower for kw in ["rau", "salad", "vegetable"]):
                item["role"] = "vegetable"
                item["category"] = "vegetable"
            elif any(kw in dish_name_lower for kw in ["trái cây", "trai cay", "fruit", "quả", "qua"]):
                item["role"] = "fruit"
                item["category"] = "fruit"
            else:
                item["role"] = "main"
                item["category"] = "main_dish"
    
    # Field mapping
    field_mapping = {
        "dish_name": "dish_name",
        "name": "dish_name",
        # Some LLM templates return 'meal_name' instead of 'dish_name' – normalize it.
        "meal_name": "dish_name",
        "general_term": "general_term",
        "term": "general_term",
        "role": "role",
        "meal_type": "meal_type",
        "meal": "meal_type",
        "category": "category",
    }
    
    # Role mapping
    role_mapping = {
        "main_course": "main", "main course": "main", "main dish": "main", "main": "main",
        "món chính": "main", "món mặn": "main", "món ăn chính": "main",
        "carb": "carb", "carbohydrate": "carb", "món tinh bột": "carb", "cơm": "carb", "mì": "carb",
        "vegetable": "vegetable", "món phụ": "vegetable", "món rau": "vegetable", "rau": "vegetable",
        "fruit": "fruit", "trái cây": "fruit",
        "breakfast": "breakfast", "bữa sáng": "breakfast"
    }
    
    # Category mapping
    category_mapping = {
        "seafood": "main_dish", "italian": "main_dish", "asian": "main_dish",
        "main_dish": "main_dish", "món mặn": "main_dish", "thịt": "main_dish", "cá": "main_dish",
        "protein": "main_dish", "healthy": "main_dish", "high_protein": "main_dish", "high protein": "main_dish",
        "vegetarian": "main_dish", "balanced": "main_dish",
        "salad": "vegetable",
        "rice": "rice", "cơm": "rice",
        "noodle": "noodle", "mì": "noodle", "bún": "noodle",
        "soup": "soup", "canh": "soup",
        "bread": "bread", "bánh mì": "bread",
        "bakery": "bakery", "bánh": "bakery",
        "vegetable": "vegetable", "rau": "vegetable",
        "fruit": "fruit", "trái cây": "fruit"
    }
    
    normalized = {}
    
    # Map fields
    for key, value in item.items():
        mapped_key = field_mapping.get(key.lower(), key)
        value_str = str(value).lower().strip() if value else ""
        
        if mapped_key == "role":
            normalized[mapped_key] = role_mapping.get(value_str, "main")
        elif mapped_key == "category":
            normalized[mapped_key] = category_mapping.get(value_str, "main_dish")
        else:
            normalized[mapped_key] = value
    
    # Set defaults / infer missing fields
    # Ensure we always have meal_type aligned with the current slot
    normalized.setdefault("meal_type", meal_slot)

    # Ensure we always have a dish_name; otherwise this suggestion is unusable
    dish_name_raw = normalized.get("dish_name")
    if not dish_name_raw:
        logger.warning("LLM draft suggestion missing 'dish_name', skipping: %s", item)
        return None

    # Auto-generate general_term if missing using a Vietnamese‑aware slug
    if "general_term" not in normalized or not str(normalized["general_term"]).strip():
        dish_name = str(dish_name_raw)
        general_term = dish_name.lower()
        try:
            import unicodedata

            general_term = unicodedata.normalize("NFD", general_term)
            general_term = "".join(
                c for c in general_term if unicodedata.category(c) != "Mn"
            )
        except ImportError:
            pass
        general_term = re.sub(r"[^a-z0-9\s-]", "", general_term)
        general_term = re.sub(r"\s+", "-", general_term).strip("-")
        normalized["general_term"] = general_term or "mon-an"

    # If role is still missing, infer a sensible default from meal_slot
    if "role" not in normalized or not str(normalized["role"]).strip():
        if meal_slot == "breakfast":
            normalized["role"] = "breakfast"
        else:
            normalized["role"] = "main"
    
    # Infer category from role or dish_name if invalid
    category = normalized.get("category", "")
    valid_categories = ["rice", "noodle", "soup", "bread", "bakery", "main_dish", "vegetable", "fruit"]
    
    if category not in valid_categories:
        role = normalized.get("role", "").lower()
        dish_name = str(normalized.get("dish_name", "")).lower()
        
        if role in ["main", "món chính", "món mặn"]:
            category = "main_dish"
        elif role in ["carb", "cơm", "mì"]:
            category = "rice"
        elif role in ["vegetable", "món phụ", "rau"]:
            category = "vegetable"
        elif role in ["fruit", "trái cây"]:
            category = "fruit"
        elif role in ["breakfast", "bữa sáng"]:
            category = "bread"
        elif any(kw in dish_name for kw in ["cơm", "com", "rice"]):
            category = "rice"
        elif any(kw in dish_name for kw in ["mì", "mi", "bún", "bun", "noodle"]):
            category = "noodle"
        elif any(kw in dish_name for kw in ["canh", "soup"]):
            category = "soup"
        elif any(kw in dish_name for kw in ["bánh mì", "banh mi", "bread"]):
            category = "bread"
        elif any(kw in dish_name for kw in ["rau", "salad", "vegetable"]):
            category = "vegetable"
        elif any(kw in dish_name for kw in ["trái cây", "trai cay", "fruit"]):
            category = "fruit"
        else:
            category = "main_dish"
        
        normalized["category"] = category
    
    try:
        return MealDraftSuggestion(**normalized)
    except Exception as e:
        logger.warning(f"Failed to create MealDraftSuggestion: {e}")
        return None


def _dedup_suggestions_by_name(items: List[MealDraftSuggestion]) -> List[MealDraftSuggestion]:
    """Remove duplicate dish_name suggestions (case-insensitive)."""
    seen = set()
    deduped = []
    for s in items:
        name = getattr(s, "dish_name", "") or ""
        key = name.strip().lower()
        if key and key not in seen:
            seen.add(key)
            deduped.append(s)
    return deduped


async def _llm_draft_meal_suggestions(
    base_lm,
    meal_history: List[str],
    constraints: Dict[str, Any],
    meal_slot: str,
    user_preferences: Optional[str] = None,
    available_ingredients: Optional[List[str]] = None,
    tree_data=None,
) -> Optional[MealSlotDraft]:
    """
    Use LLM to suggest meal framework for a specific meal slot.
    
    Args:
        available_ingredients: List of ingredient names available in pantry or mentioned in query
    """
    if not base_lm:
        logger.debug("No LLM available, skipping LLM draft")
        return None
    
    # Build prompt
    meal_history_text = ", ".join(meal_history[:15]) if meal_history else "không có"
    diversity_note = (
        f"\n⚠️ QUAN TRỌNG: Đã có {len(meal_history)} món đã dùng gần đây. Bạn PHẢI chọn các món HOÀN TOÀN KHÁC, không được lặp lại: {meal_history_text}"
        if meal_history
        else "\n⚠️ QUAN TRỌNG: Cần đa dạng. Tránh lặp các combo quen thuộc (cháo yến mạch, sinh tố, bánh mì bơ, phở bò, bún chả). Ưu tiên xoay vùng miền Bắc/Trung/Nam và kiểu món khác nhau."
    )
    diversity_seed = random.randint(0, 10**9)
    
    diet_types = constraints.get("diet_types", []) or []
    allergens = constraints.get("exclude_allergens", []) or []
    goal = constraints.get("goal")

    diet_text = (
        f"Chế độ ăn: {', '.join(diet_types)}"
        if diet_types
        else "Không có chế độ ăn đặc biệt (có thể gợi ý đa dạng, ưu tiên món Việt cân bằng dinh dưỡng)"
    )
    allergen_text = (
        f"Tránh hoàn toàn các thành phần gây dị ứng: {', '.join(allergens)}"
        if allergens
        else "Không có dị ứng đã biết"
    )
    goal_text = (
        f"Mục tiêu sức khỏe/dinh dưỡng: {goal}"
        if goal
        else "Mục tiêu: ăn uống cân bằng, đủ năng lượng và đa dạng thực phẩm"
    )
    
    # Add pantry/ingredients context
    ingredients_text = ""
    if available_ingredients and len(available_ingredients) > 0:
        ingredients_list = ", ".join(available_ingredients[:20])  # Limit to 20 ingredients
        ingredients_text = (
            f"\n🍽️ QUAN TRỌNG - NGUYÊN LIỆU CÓ SẴN: "
            f"Người dùng hiện có các nguyên liệu sau trong pantry: {ingredients_list}. "
            f"Bạn PHẢI ưu tiên đề xuất các món ăn SỬ DỤNG các nguyên liệu này. "
            f"Nếu không thể dùng hết, ít nhất phải dùng một số nguyên liệu trong danh sách này. "
            f"Ví dụ: nếu có 'ức gà', hãy đề xuất các món như 'gà nướng', 'gà xào', 'phở gà', 'cơm gà', v.v. "
            f"Nếu có 'khoai tây', hãy đề xuất 'khoai tây chiên', 'khoai tây nghiền', 'thịt kho khoai tây', v.v."
        )
        logger.info(
            f"_llm_draft_meal_suggestions: PANTRY_CONTEXT_ADDED | meal_slot={meal_slot} | "
            f"ingredients_count={len(available_ingredients)} | "
            f"ingredients={', '.join(available_ingredients[:10])}"
        )
    else:
        logger.debug(f"_llm_draft_meal_suggestions: no pantry ingredients provided for meal_slot={meal_slot}")
    
    # Meal pattern guidelines
    if meal_slot == "breakfast":
        pattern_guide = "Bữa sáng Việt Nam: Bánh mì, xôi, phở, bún, hủ tiếu, bánh cuốn, bánh ngọt"
        roles_needed = ["breakfast"]
        example = """[
  {"dish_name": "Bánh mì thịt nướng", "general_term": "banh-mi-thit-nuong", "role": "breakfast", "meal_type": "breakfast", "category": "bread"},
  {"dish_name": "Phở bò", "general_term": "pho-bo", "role": "breakfast", "meal_type": "breakfast", "category": "noodle"}
]"""
    else:  # lunch or dinner
        pattern_guide = "Bữa trưa/tối Việt Nam: Cơm hoặc món nước (phở, bún, mì) + Món mặn (thịt, cá, tôm, gà) + Rau xanh + Trái cây"
        roles_needed = ["carb", "main", "vegetable", "fruit"]
        example = """[
  {"dish_name": "Cơm trắng", "general_term": "com-trang", "role": "carb", "meal_type": "lunch", "category": "rice"},
  {"dish_name": "Thịt kho tàu", "general_term": "thit-kho-tau", "role": "main", "meal_type": "lunch", "category": "main_dish"},
  {"dish_name": "Rau muống xào tỏi", "general_term": "rau-muong-xao-toi", "role": "vegetable", "meal_type": "lunch", "category": "vegetable"}
]"""
    
    prompt = f"""Bạn là chuyên gia ẩm thực Việt Nam. Đề xuất 4-8 món ăn cho bữa {meal_slot}.

## ⚠️ QUAN TRỌNG - ƯU TIÊN MÓN ĂN VIỆT NAM:
- PHẢI ưu tiên các món ăn Việt Nam 
- Chỉ đề xuất món Tây/ngoại nếu không có món Việt phù hợp
- Tên món PHẢI bằng tiếng Việt (VD: "Phở bò", "Cơm trắng", "Thịt kho tàu")
{ingredients_text}

## YÊU CẦU:
{pattern_guide}
{diversity_note}
- Mã đa dạng hóa: {diversity_seed} (hãy dùng mã này để tạo lựa chọn khác nhau giữa các lần gọi, không lặp lại những gợi ý quen thuộc)
- {diet_text}
- {allergen_text}
- {goal_text}

## FORMAT OUTPUT (BẮT BUỘC - ĐỌC KỸ):

BẠN PHẢI TRẢ VỀ JSON ARRAY TRỰC TIẾP CHỨA CÁC OBJECT, KHÔNG PHẢI ARRAY CỦA STRINGS HOẶC TÊN MÓN THUẦN TÚY.

### ✅ FORMAT ĐÚNG (Copy format này CHÍNH XÁC):
{example}

### ❌ FORMAT SAI - TUYỆT ĐỐI KHÔNG ĐƯỢC LÀM:
- ["Bánh mì trứng nướng", "Chía pudding", "Sinh tố trái cây"]  // SAI - chỉ là array of strings
- ["{{...}}", "{{...}}"]  // SAI - không được là array của JSON strings
- {{"suggestions": [...]}}  // SAI - không được có wrapper object
- ["Grilled Chicken Salad", "general_term": "salad", ...]  // SAI - không có key "dish_name"

## QUY TẮC:

1. **Số lượng**: TỪ 4 ĐẾN 8 món (KHÔNG được ít hơn 4 hoặc nhiều hơn 8)

2. **Format**: JSON array trực tiếp `[...]` chứa các OBJECT, KHÔNG phải strings
   - Mỗi item trong array PHẢI là một object `{{...}}`
   - KHÔNG được là string `"..."`

3. **Fields bắt buộc** (mỗi object PHẢI có đầy đủ):
   - `dish_name`: Tên món bằng tiếng Việt (VD: "Phở bò", "Cơm trắng", "Thịt kho tàu")
   - `general_term`: Tên không dấu, dùng dấu gạch ngang (VD: "pho-bo", "com-trang", "thit-kho-tau")
   - `role`: "breakfast" (cho bữa sáng) hoặc "carb", "main", "vegetable", "fruit" (cho bữa trưa/tối)
   - `meal_type`: "{meal_slot}"
   - `category`: "rice", "noodle", "soup", "bread", "bakery", "main_dish", "vegetable", hoặc "fruit"

4. **Role values** (CHỈ được dùng):
   - Bữa sáng: "breakfast"
   - Bữa trưa/tối: "carb", "main", "vegetable", "fruit"

5. **Category values** (CHỈ được dùng):
   - "rice", "noodle", "soup", "bread", "bakery", "main_dish", "vegetable", "fruit"
   - KHÔNG được dùng: "healthy", "protein", "high_protein", "balanced", "vegetarian", "salad"

6. **JSON hoàn chỉnh**: 
   - Đảm bảo JSON hoàn chỉnh, không bị cắt cụt
   - Mỗi object phải có đầy đủ dấu đóng ngoặc `}}`
   - Không có trailing commas
   - Tất cả string values phải có dấu đóng ngoặc kép `"`

⚠️ LƯU Ý CUỐI - ĐỌC KỸ: 
- Trả về JSON array trực tiếp chứa OBJECTS: `[{{"dish_name": "...", ...}}, {{"dish_name": "...", ...}}]`
- KHÔNG được trả về array của strings: `["Bánh mì", "Phở bò"]` - SAI!
- KHÔNG được trả về array của JSON strings: `["{{...}}", "{{...}}"]` - SAI!
- Mỗi object PHẢI có đầy đủ các fields: dish_name, general_term, role, meal_type, category
"""
    
    if user_preferences:
        prompt += f"\nSở thích người dùng: {user_preferences}"
    
    try:
        # Call LLM
        response_text = None
        
        # Method 1: Try dspy/ElysiaChainOfThought
        if DSPY_AVAILABLE and base_lm is not None and tree_data is not None:
            try:
                class MealDraftSignature(dspy.Signature):
                    """Generate 4-8 Vietnamese meal suggestions for a specific meal slot.

                    The model MUST:
                    - Return a JSON ARRAY (not a wrapped object) of 4-8 suggestions.
                    - Each suggestion is an object with fields:
                      dish_name, general_term, role, meal_type, category.
                    - Respect dietary constraints (diet_type), allergens and health goal.
                    """

                    meal_slot = dspy.InputField(
                        desc="Meal slot: 'breakfast', 'lunch', or 'dinner'."
                    )
                    meal_history = dspy.InputField(
                        desc=(
                            "Recently used dish names to AVOID repeating. "
                            "Use this to ensure high variety and do not suggest these again."
                        )
                    )
                    constraints = dspy.InputField(
                        desc=(
                            "JSON string with dietary constraints from user profile, e.g. "
                            "{'diet_types': [...], 'exclude_allergens': [...], 'goal': '...'}."
                            " Use this to avoid allergens and align with the user's diet_type and goal "
                            "(weight loss, muscle gain, health conditions, etc.)."
                        )
                    )
                    suggestions = dspy.OutputField(
                        desc=(
                            "JSON ARRAY of 4-8 meal suggestion objects. "
                            "Each object MUST include: dish_name (Vietnamese), general_term (slug), "
                            "role, meal_type and category; do NOT wrap in an outer object."
                        )
                    )
                
                cot = ElysiaChainOfThought(
                    MealDraftSignature,
                    tree_data=tree_data,
                    reasoning=False,
                    impossible=False,
                    message_update=False,
                )
                
                input_dict = {
                    "meal_slot": meal_slot,
                    "meal_history": ", ".join(meal_history) if meal_history else "None",
                    "constraints": json.dumps(constraints) if constraints else "None",
                }
                
                import inspect
                if inspect.iscoroutinefunction(cot.aforward):
                    pred = await cot.aforward(lm=base_lm, **input_dict)
                else:
                    pred = cot.forward(lm=base_lm, **input_dict)
                
                suggestions_str = getattr(pred, "suggestions", "")
                if suggestions_str:
                    response_text = suggestions_str
                    logger.debug("LLM draft: Used ElysiaChainOfThought (dspy)")
            except Exception as e:
                logger.debug(f"LLM dspy/ElysiaChainOfThought failed: {e}")
        
        # Method 2: Try other interfaces
        if not response_text:
            if hasattr(base_lm, "generate"):
                try:
                    response_text = base_lm.generate(prompt)
                    if response_text:
                        logger.debug("LLM draft: Used generate() method")
                except Exception:
                    pass
            
            if not response_text and callable(base_lm):
                try:
                    result = base_lm(prompt)
                    if isinstance(result, str):
                        response_text = result
                    elif hasattr(result, "content"):
                        response_text = result.content
                    elif hasattr(result, "text"):
                        response_text = result.text
                    if response_text:
                        logger.debug("LLM draft: Used __call__ method")
                except Exception:
                    pass
            
            if not response_text and hasattr(base_lm, "invoke"):
                try:
                    result = base_lm.invoke(prompt)
                    if isinstance(result, str):
                        response_text = result
                    elif hasattr(result, "content"):
                        response_text = result.content
                    if response_text:
                        logger.debug("LLM draft: Used invoke() method")
                except Exception:
                    pass
        
        if not response_text:
            logger.warning("LLM client does not have recognized interface, skipping LLM draft")
            return None
        
        # Parse JSON response
        suggestions_data = _parse_json_response(response_text)
        
        if suggestions_data is None:
            logger.warning(f"Failed to parse LLM JSON response. First 500 chars: {response_text[:500]}")
            return None
        
        # Handle wrapper dict
        if isinstance(suggestions_data, dict):
            if "suggestions" in suggestions_data:
                suggestions_data = suggestions_data["suggestions"]
            elif any(key in suggestions_data for key in ["dish_name", "name", "general_term", "role"]):
                suggestions_data = [suggestions_data]
            else:
                logger.warning(f"Unexpected dict format from LLM: {list(suggestions_data.keys())[:5]}")
                return None
        
        # Process suggestions
        if not isinstance(suggestions_data, list):
            logger.warning("LLM returned invalid format, expected list")
            return None
        
        # Limit to 10 suggestions for better variety while keeping mapping manageable
        items_to_process = suggestions_data[:10]
        if len(suggestions_data) > 10:
            logger.debug(f"LLM returned {len(suggestions_data)} suggestions, limiting to 10")
        
        suggestions = []
        for item in items_to_process:
            if len(suggestions) >= 10:
                break
            
            # Handle nested structures
            if isinstance(item, str):
                try:
                    item = json.loads(item)
                except json.JSONDecodeError:
                    extracted = _extract_json_objects(item)
                    if extracted:
                        for obj in extracted:
                            if len(suggestions) >= 10:
                                break
                            result = _normalize_suggestion(obj, meal_slot)
                            if result:
                                suggestions.append(result)
                    continue
            
            if isinstance(item, list):
                for sub_item in item:
                    if len(suggestions) >= 10:
                        break
                    if isinstance(sub_item, dict):
                        result = _normalize_suggestion(sub_item, meal_slot)
                        if result:
                            suggestions.append(result)
                continue
            
            if isinstance(item, dict):
                result = _normalize_suggestion(item, meal_slot)
                if result:
                    suggestions.append(result)
        
        # Filter and limit
        valid_suggestions = _dedup_suggestions_by_name([s for s in suggestions if s is not None])[:10]
        
        if valid_suggestions:
            try:
                return MealSlotDraft(meal_type=meal_slot, suggestions=valid_suggestions)
            except Exception as e:
                logger.warning(f"Failed to create MealSlotDraft: {e}")
                return None
        else:
            logger.warning("No valid suggestions created from LLM response")
            return None
            
    except Exception as e:
        logger.warning(f"LLM draft failed: {e}")
        return None


async def generate_llm_draft(
    base_lm,
    meal_history: List[str],
    constraints: Dict[str, Any],
    user_preferences: Optional[str] = None,
    available_ingredients: Optional[List[str]] = None,
    tree_data=None,
) -> Optional[LLMDraftResponse]:
    """
    Generate complete LLM draft for all meal slots (breakfast, lunch, dinner).
    
    Args:
        available_ingredients: List of ingredient names available in pantry or mentioned in query
    """
    if not base_lm:
        logger.debug("No LLM available, skipping LLM draft")
        return None
    
    try:
        breakfast_draft = await _llm_draft_meal_suggestions(
            base_lm, meal_history, constraints, "breakfast", user_preferences, available_ingredients, tree_data
        )
        lunch_draft = await _llm_draft_meal_suggestions(
            base_lm, meal_history, constraints, "lunch", user_preferences, available_ingredients, tree_data
        )
        dinner_draft = await _llm_draft_meal_suggestions(
            base_lm, meal_history, constraints, "dinner", user_preferences, available_ingredients, tree_data
        )
        
        if not all([breakfast_draft, lunch_draft, dinner_draft]):
            logger.warning("Some meal slots failed LLM draft, returning None")
            return None
        
        return LLMDraftResponse(
            breakfast=breakfast_draft,
            lunch=lunch_draft,
            dinner=dinner_draft,
        )
    except Exception as e:
        logger.warning(f"LLM draft generation failed: {e}")
        return None
