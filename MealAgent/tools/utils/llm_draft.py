"""
LLM Draft helper functions for Phase 2.1.

Generates meal framework suggestions using LLM, with fallback to rule-based selection.
"""

import json
import logging
from typing import Dict, Any, List, Optional

try:
    import dspy
    from elysia.util.elysia_chain_of_thought import ElysiaChainOfThought
    DSPY_AVAILABLE = True
except ImportError:
    DSPY_AVAILABLE = False

from MealAgent.schemas.llm_draft import LLMDraftResponse, MealSlotDraft, MealDraftSuggestion

logger = logging.getLogger(__name__)


async def _llm_draft_meal_suggestions(
    base_lm,
    meal_history: List[str],
    constraints: Dict[str, Any],
    meal_slot: str,  # "breakfast", "lunch", "dinner"
    user_preferences: Optional[str] = None,
    tree_data=None,  # TreeData for ElysiaChainOfThought
) -> Optional[MealSlotDraft]:
    """
    Use LLM to suggest meal framework for a specific meal slot.
    
    Args:
        base_lm: LLM client (optional, can be None for fallback)
        meal_history: List of recently used dish names to avoid
        constraints: Dictionary with diet_types, exclude_allergens, etc.
        meal_slot: "breakfast", "lunch", or "dinner"
        user_preferences: Optional user preferences text
    
    Returns:
        MealSlotDraft with 2-3 suggestions, or None if LLM fails
    """
    if not base_lm:
        logger.debug("No LLM available, skipping LLM draft")
        return None
    
    # Build prompt
    meal_history_text = ", ".join(meal_history[:10]) if meal_history else "không có"
    
    diet_types = constraints.get("diet_types", [])
    allergens = constraints.get("exclude_allergens", [])
    
    diet_text = f"Chế độ ăn: {', '.join(diet_types)}" if diet_types else "Không có chế độ ăn đặc biệt"
    allergen_text = f"Tránh: {', '.join(allergens)}" if allergens else "Không có dị ứng"
    
    # Vietnamese meal pattern guidelines
    if meal_slot == "breakfast":
        pattern_guide = """
Bữa sáng Việt Nam thường nhẹ, gồm:
- Bánh mì, xôi, phở, bún, hủ tiếu, bánh cuốn
- Bánh ngọt, croissant, brioche (nếu không cấm)
- Cơm tấm, xôi mặn (ít phổ biến hơn)
"""
        roles_needed = ["breakfast"]
    elif meal_slot == "lunch":
        pattern_guide = """
Bữa trưa Việt Nam thường gồm:
- Cơm hoặc món nước (phở, bún, mì) làm carb chính
- Món mặn (thịt, cá, tôm, gà) làm main
- Rau xanh làm vegetable
- Trái cây làm fruit
"""
        roles_needed = ["carb", "main", "vegetable", "fruit"]
    else:  # dinner
        pattern_guide = """
Bữa tối Việt Nam thường gồm:
- Cơm hoặc món nước (phở, bún, mì) làm carb chính
- Món mặn (thịt, cá, tôm, gà) làm main
- Rau xanh làm vegetable
- Trái cây làm fruit
"""
        roles_needed = ["carb", "main", "vegetable", "fruit"]
    
    prompt = f"""Bạn là chuyên gia ẩm thực Việt Nam. Hãy đề xuất 2-3 món ăn cho bữa {meal_slot} theo khẩu vị Việt Nam.

Yêu cầu:
{pattern_guide}

Ràng buộc:
- Tránh các món đã dùng gần đây: {meal_history_text}
- {diet_text}
- {allergen_text}
- KHÔNG được ước lượng kcal/protein/carb - chỉ đưa ra tên món và phân loại

Cho mỗi món, trả về JSON với format:
{{
  "dish_name": "Tên món (tiếng Việt)",
  "general_term": "tên-chuan-hoa-khong-dau",
  "role": "breakfast|carb|main|vegetable|fruit",
  "meal_type": "{meal_slot}",
  "category": "rice|noodle|soup|bread|bakery|main_dish|vegetable|fruit",
  "note": "Ghi chú ngắn (tùy chọn)"
}}

Trả về JSON array với 2-3 món, đảm bảo đủ các role cần thiết cho bữa {meal_slot}.
"""
    
    if user_preferences:
        prompt += f"\nSở thích người dùng: {user_preferences}"
    
    try:
        # Call LLM - try different interfaces
        response_text = None
        
        # Method 1: Try dspy/ElysiaChainOfThought (most common in this codebase)
        if DSPY_AVAILABLE and base_lm is not None:
            try:
                class MealDraftSignature(dspy.Signature):
                    """Generate meal suggestions for a meal slot."""
                    meal_slot = dspy.InputField(desc="Meal slot: breakfast, lunch, or dinner")
                    meal_history = dspy.InputField(desc="Recently used dish names to avoid")
                    constraints = dspy.InputField(desc="Dietary constraints and preferences")
                    suggestions = dspy.OutputField(desc="JSON array of meal suggestions with dish_name, general_term, role, category")
                
                # Use tree_data from parameter (passed from plan_day_e2e_tool)
                # ElysiaChainOfThought requires tree_data to have user_prompt attribute
                # If tree_data is None, skip this method and try others
                if tree_data is None:
                    raise ValueError("tree_data is required for ElysiaChainOfThought")
                
                cot = ElysiaChainOfThought(
                    MealDraftSignature,
                    tree_data=tree_data,  # Use tree_data from parameter
                    reasoning=False,
                    impossible=False,
                    message_update=False,
                )
                
                # Build input dict
                input_dict = {
                    "meal_slot": meal_slot,
                    "meal_history": ", ".join(meal_history) if meal_history else "None",
                    "constraints": json.dumps(constraints) if constraints else "None",
                }
                
                # Call with await if it's async, otherwise sync
                import inspect
                if inspect.iscoroutinefunction(cot.aforward):
                    pred = await cot.aforward(lm=base_lm, **input_dict)
                else:
                    pred = cot.forward(lm=base_lm, **input_dict)
                
                # Extract suggestions from prediction
                suggestions_str = getattr(pred, "suggestions", "")
                if suggestions_str:
                    response_text = suggestions_str
                    logger.debug("LLM draft: Used ElysiaChainOfThought (dspy)")
            except Exception as e:
                logger.debug(f"LLM dspy/ElysiaChainOfThought failed: {e}")
        
        # Method 2: Try generate() method
        if not response_text and hasattr(base_lm, "generate"):
            try:
                response_text = base_lm.generate(prompt)
                if response_text:
                    logger.debug("LLM draft: Used generate() method")
            except Exception as e:
                logger.debug(f"LLM generate() failed: {e}")
        
        # Method 3: Try __call__ (dspy-style)
        if not response_text and callable(base_lm):
            try:
                result = base_lm(prompt)
                if isinstance(result, str):
                    response_text = result
                elif hasattr(result, "content"):
                    response_text = result.content
                elif hasattr(result, "text"):
                    response_text = result.text
                elif hasattr(result, "generations") and result.generations:
                    # Handle dspy-style response
                    response_text = result.generations[0].text if hasattr(result.generations[0], "text") else str(result.generations[0])
                if response_text:
                    logger.debug("LLM draft: Used __call__ method")
            except Exception as e:
                logger.debug(f"LLM __call__ failed: {e}")
        
        # Method 4: Try invoke() (LangChain-style)
        if not response_text and hasattr(base_lm, "invoke"):
            try:
                result = base_lm.invoke(prompt)
                if isinstance(result, str):
                    response_text = result
                elif hasattr(result, "content"):
                    response_text = result.content
                if response_text:
                    logger.debug("LLM draft: Used invoke() method")
            except Exception as e:
                logger.debug(f"LLM invoke() failed: {e}")
        
        if not response_text:
            logger.warning("LLM client does not have recognized interface, skipping LLM draft")
            return None
        
        # Parse JSON response
        # Try to extract JSON from markdown code blocks if present
        response_text = response_text.strip()
        if "```json" in response_text:
            json_start = response_text.find("```json") + 7
            json_end = response_text.find("```", json_start)
            response_text = response_text[json_start:json_end].strip()
        elif "```" in response_text:
            json_start = response_text.find("```") + 3
            json_end = response_text.find("```", json_start)
            response_text = response_text[json_start:json_end].strip()
        
        # Clean response text: remove control characters and normalize
        import re
        # Remove control characters except newlines and tabs (which might be in JSON)
        response_text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]', '', response_text)
        # Normalize whitespace
        response_text = response_text.strip()
        
        # Try to parse as JSON
        suggestions_data = None
        try:
            suggestions_data = json.loads(response_text)
        except json.JSONDecodeError as e:
            # If parsing fails, try to handle common LLM response formats
            logger.debug(f"Initial JSON parse failed: {e}, trying alternative formats...")
            
            # Case 1: LLM returns a string containing multiple JSON objects (not an array)
            # Example: '{"dish_name": "A"}, {"dish_name": "B"}' -> should be '[{"dish_name": "A"}, {"dish_name": "B"}]'
            if response_text.startswith('{') and not response_text.startswith('['):
                # Try to wrap in array if it looks like multiple objects
                if response_text.count('{') > 1:
                    try:
                        # Wrap in array brackets
                        normalized = '[' + response_text + ']'
                        suggestions_data = json.loads(normalized)
                        logger.debug("Successfully parsed as multiple objects wrapped in array")
                    except json.JSONDecodeError:
                        # If that fails, try to split by '}, {' pattern
                        try:
                            # Split by '}, {' or '},\n{' or '}, \n{'
                            import re
                            # Find all JSON objects separated by commas
                            objects_str = re.split(r'\},\s*\{', response_text)
                            objects = []
                            for i, obj_str in enumerate(objects_str):
                                if i == 0:
                                    obj_str = obj_str + '}'
                                elif i == len(objects_str) - 1:
                                    obj_str = '{' + obj_str
                                else:
                                    obj_str = '{' + obj_str + '}'
                                try:
                                    obj = json.loads(obj_str)
                                    objects.append(obj)
                                except json.JSONDecodeError:
                                    continue
                            if objects:
                                suggestions_data = objects
                                logger.debug(f"Successfully parsed {len(objects)} objects by splitting")
                        except Exception:
                            pass
            
            # Case 2: Try to extract JSON array from text
            if suggestions_data is None:
                # Look for array pattern [...]
                array_match = re.search(r'\[.*\]', response_text, re.DOTALL)
                if array_match:
                    try:
                        array_str = array_match.group(0)
                        suggestions_data = json.loads(array_str)
                        # Check if array contains JSON strings instead of objects
                        if isinstance(suggestions_data, list) and suggestions_data and isinstance(suggestions_data[0], str):
                            # Parse each string as JSON
                            parsed_objects = []
                            for item in suggestions_data:
                                try:
                                    obj = json.loads(item)
                                    if isinstance(obj, dict):
                                        parsed_objects.append(obj)
                                except json.JSONDecodeError:
                                    continue
                            if parsed_objects:
                                suggestions_data = parsed_objects
                                logger.debug(f"Successfully parsed array of JSON strings: {len(parsed_objects)} objects")
                        else:
                            logger.debug("Successfully extracted array from text")
                    except json.JSONDecodeError:
                        pass
            
            # Case 3: Try to find and parse individual JSON objects using balanced braces
            if suggestions_data is None:
                objects = []
                i = 0
                while i < len(response_text):
                    if response_text[i] == '{':
                        # Find matching closing brace
                        brace_count = 0
                        start = i
                        j = i
                        while j < len(response_text):
                            if response_text[j] == '{':
                                brace_count += 1
                            elif response_text[j] == '}':
                                brace_count -= 1
                                if brace_count == 0:
                                    # Found complete object
                                    obj_str = response_text[start:j+1]
                                    try:
                                        obj = json.loads(obj_str)
                                        if isinstance(obj, dict):
                                            objects.append(obj)
                                    except json.JSONDecodeError:
                                        pass
                                    i = j + 1
                                    break
                            j += 1
                        else:
                            # No matching closing brace found
                            i += 1
                    else:
                        i += 1
                
                if objects:
                    suggestions_data = objects
                    logger.debug(f"Successfully parsed {len(objects)} individual JSON objects using balanced braces")
            
            # If still failed, log and return None
            if suggestions_data is None:
                logger.warning(f"Failed to parse LLM JSON response after all attempts: {e}")
                logger.debug(f"Response text (first 500 chars): {response_text[:500]}")
                return None
        
        # Handle case where LLM returns {'suggestions': [...]} instead of list directly
        if isinstance(suggestions_data, dict) and "suggestions" in suggestions_data:
            suggestions_data = suggestions_data["suggestions"]
        
        # Validate and create MealSlotDraft
        if isinstance(suggestions_data, list):
            suggestions = []
            # Limit to max 3 suggestions (schema requirement)
            items_to_process = suggestions_data[:3] if len(suggestions_data) > 3 else suggestions_data
            if len(suggestions_data) > 3:
                logger.debug(f"LLM returned {len(suggestions_data)} suggestions, limiting to 3")
            
            for item in items_to_process:
                # Handle case where item might be a string (JSON string)
                if isinstance(item, str):
                    try:
                        item = json.loads(item)
                    except json.JSONDecodeError:
                        logger.warning(f"Failed to parse item as JSON: {item}")
                        continue
                # Ensure item is a dict before unpacking
                if isinstance(item, dict):
                    try:
                        # Normalize LLM response fields to match schema
                        normalized_item = {}
                        # Map common LLM field names to schema fields
                        field_mapping = {
                            "dish_name": "dish_name",
                            "name": "dish_name",
                            "general_term": "general_term",
                            "term": "general_term",
                            "role": "role",
                            "meal_type": "meal_type",
                            "meal": "meal_type",
                            "category": "category",
                            "note": "note",
                            "description": "note"
                        }
                        
                        # Map role values (comprehensive mapping for Vietnamese and English)
                        role_mapping = {
                            "main_course": "main",
                            "main dish": "main",
                            "món chính": "main",
                            "món mặn": "main",
                            "món ăn chính": "main",
                            "carb": "carb",
                            "carbohydrate": "carb",
                            "món tinh bột": "carb",
                            "cơm": "carb",
                            "mì": "carb",
                            "vegetable": "vegetable",
                            "món phụ": "vegetable",
                            "món rau": "vegetable",
                            "rau": "vegetable",
                            "fruit": "fruit",
                            "trái cây": "fruit",
                            "breakfast": "breakfast",
                            "bữa sáng": "breakfast"
                        }
                        
                        # Map category values (comprehensive mapping for Vietnamese and English)
                        category_mapping = {
                            # Main dish categories
                            "seafood": "main_dish",
                            "italian": "main_dish",
                            "asian": "main_dish",
                            "main_dish": "main_dish",
                            "món mặn": "main_dish",
                            "đồ ăn nhanh": "main_dish",
                            "đồ ăn lành": "main_dish",
                            "đồ ăn chăn nuôi": "main_dish",
                            "thịt": "main_dish",
                            "cá": "main_dish",
                            "protein": "main_dish",
                            # Carb categories
                            "rice": "rice",
                            "cơm": "rice",
                            "noodle": "noodle",
                            "mì": "noodle",
                            "bún": "noodle",
                            # Soup categories
                            "soup": "soup",
                            "canh": "soup",
                            # Bread/Bakery
                            "bread": "bread",
                            "bánh mì": "bread",
                            "bakery": "bakery",
                            "bánh": "bakery",
                            # Vegetable
                            "vegetable": "vegetable",
                            "rau": "vegetable",
                            # Fruit
                            "fruit": "fruit",
                            "trái cây": "fruit"
                        }
                        
                        for key, value in item.items():
                            mapped_key = field_mapping.get(key.lower(), key)
                            # Normalize value (convert to string and lowercase for comparison)
                            value_str = str(value).lower().strip() if value else ""
                            
                            if mapped_key == "role":
                                # Try exact match first, then partial match
                                if value_str in role_mapping:
                                    normalized_item[mapped_key] = role_mapping[value_str]
                                else:
                                    # Try partial matching (e.g., "món chính" contains "chính")
                                    matched = False
                                    for role_key, role_value in role_mapping.items():
                                        if role_key in value_str or value_str in role_key:
                                            normalized_item[mapped_key] = role_value
                                            matched = True
                                            break
                                    if not matched:
                                        # Default to "main" if unclear
                                        normalized_item[mapped_key] = "main"
                            elif mapped_key == "category":
                                # Try exact match first, then partial match
                                if value_str in category_mapping:
                                    normalized_item[mapped_key] = category_mapping[value_str]
                                else:
                                    # Try partial matching
                                    matched = False
                                    for cat_key, cat_value in category_mapping.items():
                                        if cat_key in value_str or value_str in cat_key:
                                            normalized_item[mapped_key] = cat_value
                                            matched = True
                                            break
                                    # If still not matched, will be handled by smart inference below
                                    if not matched:
                                        normalized_item[mapped_key] = value_str  # Keep original for inference
                            else:
                                normalized_item[mapped_key] = value
                        
                        # Set default meal_type if missing
                        if "meal_type" not in normalized_item:
                            normalized_item["meal_type"] = meal_slot
                        
                        # Smart category inference from role if category is invalid
                        final_category = normalized_item.get("category", "")
                        if not final_category or final_category not in ["rice", "noodle", "soup", "bread", "bakery", "main_dish", "vegetable", "fruit"]:
                            # Try to infer category from role
                            role_value = normalized_item.get("role", "").lower()
                            if role_value in ["main", "món chính", "món mặn"]:
                                final_category = "main_dish"
                            elif role_value in ["carb", "cơm", "mì"]:
                                final_category = "rice"  # Default to rice for carbs
                            elif role_value in ["vegetable", "món phụ", "rau"]:
                                final_category = "vegetable"
                            elif role_value in ["fruit", "trái cây"]:
                                final_category = "fruit"
                            elif role_value in ["breakfast", "bữa sáng"]:
                                final_category = "bread"  # Default to bread for breakfast
                            else:
                                # Try to infer from dish_name
                                dish_name = str(normalized_item.get("dish_name", "")).lower()
                                if any(kw in dish_name for kw in ["cơm", "com", "rice"]):
                                    final_category = "rice"
                                elif any(kw in dish_name for kw in ["mì", "mi", "bún", "bun", "noodle"]):
                                    final_category = "noodle"
                                elif any(kw in dish_name for kw in ["canh", "soup"]):
                                    final_category = "soup"
                                elif any(kw in dish_name for kw in ["bánh mì", "banh mi", "bread"]):
                                    final_category = "bread"
                                elif any(kw in dish_name for kw in ["rau", "salad", "vegetable"]):
                                    final_category = "vegetable"
                                elif any(kw in dish_name for kw in ["trái cây", "trai cay", "fruit"]):
                                    final_category = "fruit"
                                else:
                                    # Default fallback
                                    final_category = "main_dish"
                            normalized_item["category"] = final_category
                        
                        suggestions.append(MealDraftSuggestion(**normalized_item))
                    except Exception as e:
                        logger.warning(f"Failed to create MealDraftSuggestion from {item}: {e}")
                        continue
                else:
                    logger.warning(f"Item is not a dict: {item}")
            if suggestions:
                return MealSlotDraft(meal_type=meal_slot, suggestions=suggestions)
            else:
                logger.warning("No valid suggestions created from LLM response")
                return None
        else:
            logger.warning("LLM returned invalid format, expected list")
            return None
            
    except json.JSONDecodeError as e:
        logger.warning(f"Failed to parse LLM JSON response: {e}")
        return None
    except Exception as e:
        logger.warning(f"LLM draft failed: {e}")
        return None


async def generate_llm_draft(
    base_lm,
    meal_history: List[str],
    constraints: Dict[str, Any],
    user_preferences: Optional[str] = None,
    tree_data=None,  # TreeData for ElysiaChainOfThought
) -> Optional[LLMDraftResponse]:
    """
    Generate complete LLM draft for all meal slots (breakfast, lunch, dinner).
    
    Args:
        base_lm: LLM client (optional)
        meal_history: List of recently used dish names
        constraints: Dictionary with diet_types, exclude_allergens
        user_preferences: Optional user preferences
    
    Returns:
        LLMDraftResponse with suggestions for all meals, or None if LLM fails
    """
    if not base_lm:
        logger.debug("No LLM available, skipping LLM draft")
        return None
    
    try:
        breakfast_draft = await _llm_draft_meal_suggestions(
            base_lm, meal_history, constraints, "breakfast", user_preferences, tree_data
        )
        lunch_draft = await _llm_draft_meal_suggestions(
            base_lm, meal_history, constraints, "lunch", user_preferences, tree_data
        )
        dinner_draft = await _llm_draft_meal_suggestions(
            base_lm, meal_history, constraints, "dinner", user_preferences, tree_data
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

