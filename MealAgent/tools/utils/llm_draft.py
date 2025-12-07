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
    
    # Build role-specific examples
    if meal_slot == "breakfast":
        example_output = """[
  {
    "dish_name": "Bánh mì thịt nướng",
    "general_term": "banh-mi-thit-nuong",
    "role": "breakfast",
    "meal_type": "breakfast",
    "category": "bread"
  },
  {
    "dish_name": "Phở bò",
    "general_term": "pho-bo",
    "role": "breakfast",
    "meal_type": "breakfast",
    "category": "noodle"
  }
]"""
    elif meal_slot == "lunch":
        example_output = """[
  {
    "dish_name": "Cơm trắng",
    "general_term": "com-trang",
    "role": "carb",
    "meal_type": "lunch",
    "category": "rice"
  },
  {
    "dish_name": "Thịt kho tàu",
    "general_term": "thit-kho-tau",
    "role": "main",
    "meal_type": "lunch",
    "category": "main_dish"
  },
  {
    "dish_name": "Rau muống xào tỏi",
    "general_term": "rau-muong-xao-toi",
    "role": "vegetable",
    "meal_type": "lunch",
    "category": "vegetable"
  }
]"""
    else:  # dinner
        example_output = """[
  {
    "dish_name": "Cơm trắng",
    "general_term": "com-trang",
    "role": "carb",
    "meal_type": "dinner",
    "category": "rice"
  },
  {
    "dish_name": "Cá kho tộ",
    "general_term": "ca-kho-to",
    "role": "main",
    "meal_type": "dinner",
    "category": "main_dish"
  },
  {
    "dish_name": "Canh chua cá",
    "general_term": "canh-chua-ca",
    "role": "main",
    "meal_type": "dinner",
    "category": "soup"
  }
]"""
    
    prompt = f"""Bạn là chuyên gia ẩm thực Việt Nam. Nhiệm vụ của bạn là đề xuất 2-3 món ăn cho bữa {meal_slot} theo khẩu vị Việt Nam.

## YÊU CẦU VỀ MÓN ĂN:
{pattern_guide}

## RÀNG BUỘC:
- Tránh các món đã dùng gần đây: {meal_history_text}
- {diet_text}
- {allergen_text}
- KHÔNG được ước lượng kcal/protein/carb - chỉ đưa ra tên món và phân loại

## FORMAT OUTPUT (BẮT BUỘC - ĐỌC KỸ):

BẠN PHẢI TRẢ VỀ MỘT JSON ARRAY TRỰC TIẾP, KHÔNG CÓ WRAPPER OBJECT, KHÔNG CÓ KEY "suggestions".

### ✅ FORMAT ĐÚNG (Copy format này):
{example_output}

### ❌ FORMAT SAI (KHÔNG ĐƯỢC LÀM THẾ NÀY):
```json
{{"suggestions": [...]}}  // SAI - không được có wrapper object
```
```json
"[{{...}}]"  // SAI - không được là string chứa JSON
```
```json
[{{...}}, {{...}}, {{...}}, {{...}}]  // SAI - không được nhiều hơn 3 items
```

## QUY TẮC BẮT BUỘC:

1. **Số lượng**: Trả về ĐÚNG 2-3 món (KHÔNG được 1, 4, 5, hoặc nhiều hơn)
2. **Format**: JSON array trực tiếp `[...]`, KHÔNG có wrapper `{{"suggestions": [...]}}`
3. **Fields bắt buộc**: Mỗi object PHẢI có đầy đủ:
   - `dish_name`: Tên món bằng tiếng Việt (VD: "Phở bò", "Cơm trắng")
   - `general_term`: Tên không dấu, dùng dấu gạch ngang (VD: "pho-bo", "com-trang")
   - `role`: Một trong các giá trị: "breakfast", "carb", "main", "vegetable", "fruit"
   - `meal_type`: "{meal_slot}"
   - `category`: Một trong các giá trị: "rice", "noodle", "soup", "bread", "bakery", "main_dish", "vegetable", "fruit"

4. **Role values (CHỈ được dùng các giá trị này)**:
   - Bữa sáng: role = "breakfast" (KHÔNG được dùng "main_course", "main dish", v.v.)
   - Bữa trưa/tối: 
     * role = "carb" (cho cơm/phở/bún/mì)
     * role = "main" (cho món mặn - KHÔNG được dùng "main_course", "main dish")
     * role = "vegetable" (cho rau)
     * role = "fruit" (cho trái cây)

5. **Category values (CHỈ được dùng các giá trị này)**:
   - "rice" (cho cơm)
   - "noodle" (cho phở, bún, mì)
   - "soup" (cho canh)
   - "bread" (cho bánh mì)
   - "main_dish" (cho món mặn - KHÔNG được dùng "healthy", "protein", "seafood", v.v.)
   - "vegetable" (cho rau)
   - "fruit" (cho trái cây)
   
   ⚠️ QUAN TRỌNG: KHÔNG được dùng các giá trị như "healthy", "protein", "main_course", "salad" - chỉ dùng các giá trị trên.

6. **JSON hoàn chỉnh**: 
   - Đảm bảo JSON hoàn chỉnh, không bị cắt cụt
   - Mỗi object phải có đầy đủ dấu đóng ngoặc `}}`
   - Không có control characters
   - Không có trailing commas
   - Tất cả string values phải có dấu đóng ngoặc kép `"`

7. **Validation**: Trước khi trả về, kiểm tra lại:
   - JSON có thể parse được không?
   - Tất cả fields có đầy đủ không?
   - Role và category có đúng giá trị cho phép không?

## VÍ DỤ OUTPUT ĐÚNG:

Cho bữa {meal_slot}, bạn nên trả về format giống như ví dụ trên, với các món phù hợp với bữa {meal_slot}.

⚠️ LƯU Ý CUỐI CÙNG: 
- Trả về JSON array trực tiếp, không có text thêm, không có markdown code blocks
- Đảm bảo JSON hoàn chỉnh, không bị cắt cụt
- Chỉ dùng role và category values đã liệt kê ở trên
- Kiểm tra lại JSON trước khi trả về
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
            
            # Case 0: LLM returns plain text with JSON embedded - extract JSON objects using balanced braces
            # This handles cases like "Đây là gợi ý bữa sáng cho hôm nay: {...}"
            if "Expecting value" in str(e) or (not response_text.startswith('{') and not response_text.startswith('[')):
                logger.debug("Response appears to be plain text, trying to extract JSON objects...")
                objects = []
                brace_count = 0
                start_idx = None
                for idx, char in enumerate(response_text):
                    if char == '{':
                        if brace_count == 0:
                            start_idx = idx
                        brace_count += 1
                    elif char == '}':
                        brace_count -= 1
                        if brace_count == 0 and start_idx is not None:
                            # Found complete object
                            obj_str = response_text[start_idx:idx+1]
                            try:
                                obj = json.loads(obj_str)
                                if isinstance(obj, dict):
                                    objects.append(obj)
                            except json.JSONDecodeError:
                                pass
                            start_idx = None
                
                if objects:
                    suggestions_data = objects
                    logger.debug(f"Successfully extracted {len(objects)} JSON objects from plain text response")
            
            # Case 1: LLM returns a string containing multiple JSON objects (not an array)
            # Example: '{"dish_name": "A"}, {"dish_name": "B"}' -> should be '[{"dish_name": "A"}, {"dish_name": "B"}]'
            if suggestions_data is None and response_text.startswith('{') and not response_text.startswith('['):
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
                # CRITICAL: Clean control characters from response_text BEFORE extracting array pattern
                # This fixes "Invalid control character" errors
                cleaned_response = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]', '', response_text)
                
                # First, try to find JSON array pattern [...]
                array_match = re.search(r'\[.*\]', cleaned_response, re.DOTALL)
                if array_match:
                    try:
                        array_str = array_match.group(0)
                        # Try to parse the array
                        try:
                            suggestions_data = json.loads(array_str)
                        except json.JSONDecodeError as array_parse_err:
                            # If parsing fails, try to handle case where array contains JSON strings
                            # Pattern: ["{...}"] or ['{...}'] - array with single JSON string
                            logger.debug(f"Array parse failed: {array_parse_err}, trying to extract JSON string from array...")
                            
                            # Try to match: ["..."] or ['...']
                            string_array_match = re.match(r'^\s*\[\s*"([^"]*(?:\\.[^"]*)*)"\s*\]\s*$', array_str, re.DOTALL)
                            if not string_array_match:
                                string_array_match = re.match(r"^\s*\[\s*'([^']*(?:\\.[^']*)*)'\s*\]\s*$", array_str, re.DOTALL)
                            
                            if string_array_match:
                                # Extract the string content (with proper unescaping)
                                inner_str = string_array_match.group(1)
                                # Unescape JSON escape sequences properly
                                try:
                                    # Use json.loads to properly unescape the string
                                    inner_str = json.loads('"' + inner_str + '"')
                                except:
                                    # Fallback: manual unescaping
                                    inner_str = inner_str.replace('\\"', '"').replace("\\'", "'").replace('\\n', '\n').replace('\\t', '\t').replace('\\\\', '\\')
                                
                                # Clean any remaining control characters
                                inner_str = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]', '', inner_str)
                                
                                # Try to parse as JSON
                                try:
                                    inner_obj = json.loads(inner_str)
                                    # Handle {"suggestions": [...]} case
                                    if isinstance(inner_obj, dict) and "suggestions" in inner_obj:
                                        suggestions_data = inner_obj["suggestions"]
                                        logger.debug(f"Extracted {len(suggestions_data)} suggestions from nested structure")
                                    elif isinstance(inner_obj, dict):
                                        suggestions_data = [inner_obj]
                                        logger.debug("Extracted single object from array string")
                                    elif isinstance(inner_obj, list):
                                        suggestions_data = inner_obj
                                        logger.debug(f"Extracted {len(inner_obj)} items from nested array")
                                except json.JSONDecodeError as inner_err:
                                    logger.debug(f"Failed to parse inner JSON string: {inner_err}")
                                    # suggestions_data remains None, will continue to existing logic below
                            # If string_array_match failed or parsing failed, suggestions_data is still None
                            # Continue to existing logic below
                        
                        # Check if array contains JSON strings instead of objects
                        # This handles cases like: ["{...}", "{...}"] or ['{...}', '{...}'] or ["[{...}]"]
                        # Only process if suggestions_data was successfully parsed as a list
                        if suggestions_data is not None and isinstance(suggestions_data, list) and suggestions_data:
                            # Check if first element is a string that looks like JSON
                            first_item = suggestions_data[0] if suggestions_data else None
                            if isinstance(first_item, str):
                                first_clean = first_item.strip()
                                # Remove quotes if present
                                if (first_clean.startswith('"') and first_clean.endswith('"')) or \
                                   (first_clean.startswith("'") and first_clean.endswith("'")):
                                    first_clean = first_clean[1:-1]
                                
                                # Check if it looks like JSON (object or array)
                                if first_clean.startswith('{') or first_clean.startswith('['):
                                    # Parse each string as JSON
                                    parsed_objects = []
                                    for item in suggestions_data:
                                        try:
                                            # Skip empty items
                                            if not item or (isinstance(item, str) and not item.strip()):
                                                continue
                                            
                                            # Handle case where item is already a list (empty or not)
                                            if isinstance(item, list):
                                                # If it's a list, extract dicts from it
                                                parsed_objects.extend([x for x in item if isinstance(x, dict)])
                                                continue
                                            
                                            # If item is not a string, skip
                                            if not isinstance(item, str):
                                                continue
                                            
                                            # Remove quotes if present (handle both " and ')
                                            item_clean = item.strip()
                                            if not item_clean:
                                                continue
                                                
                                            # Remove outer quotes if present
                                            if (item_clean.startswith('"') and item_clean.endswith('"')) or \
                                               (item_clean.startswith("'") and item_clean.endswith("'")):
                                                item_clean = item_clean[1:-1]
                                            
                                            # Skip if empty after removing quotes
                                            if not item_clean.strip():
                                                continue
                                            
                                            # Remove any remaining control characters that might interfere with parsing
                                            # But preserve newlines and tabs as they might be part of JSON structure
                                            item_clean = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]', '', item_clean)
                                            
                                            # Try to parse as JSON
                                            # json.loads will automatically handle escape sequences like \n, \t, \", etc.
                                            try:
                                                obj = json.loads(item_clean)
                                                if isinstance(obj, dict):
                                                    # CRITICAL: Handle case where obj is {"suggestions": [...]}
                                                    if "suggestions" in obj and isinstance(obj["suggestions"], list):
                                                        # Extract suggestions array
                                                        parsed_objects.extend([x for x in obj["suggestions"] if isinstance(x, dict)])
                                                        logger.debug(f"Extracted {len(obj['suggestions'])} suggestions from wrapper object")
                                                    else:
                                                        # Regular dict, add it
                                                        parsed_objects.append(obj)
                                                elif isinstance(obj, list):
                                                    # If it's a list, extract dicts from it (skip empty lists)
                                                    if obj:  # Only process non-empty lists
                                                        parsed_objects.extend([x for x in obj if isinstance(x, dict)])
                                            except json.JSONDecodeError as json_err:
                                                # If parsing fails, try to extract JSON objects using balanced braces
                                                # This handles truncated or malformed JSON
                                                logger.debug(f"JSON parse failed for item, trying balanced braces: {json_err}")
                                                # Try to find complete JSON objects in the string
                                                brace_count = 0
                                                start_idx = None
                                                for idx, char in enumerate(item_clean):
                                                    if char == '{':
                                                        if brace_count == 0:
                                                            start_idx = idx
                                                        brace_count += 1
                                                    elif char == '}':
                                                        brace_count -= 1
                                                        if brace_count == 0 and start_idx is not None:
                                                            # Found a complete object
                                                            obj_str = item_clean[start_idx:idx+1]
                                                            try:
                                                                obj = json.loads(obj_str)
                                                                if isinstance(obj, dict):
                                                                    parsed_objects.append(obj)
                                                            except json.JSONDecodeError:
                                                                pass
                                                            start_idx = None
                                        except (json.JSONDecodeError, AttributeError, TypeError, ValueError) as parse_err:
                                            logger.debug(f"Failed to parse item in array: {parse_err}, item: {str(item)[:100]}")
                                            continue
                                    if parsed_objects:
                                        suggestions_data = parsed_objects
                                        logger.debug(f"Successfully parsed array of JSON strings: {len(parsed_objects)} objects")
                        else:
                            logger.debug("Successfully extracted array from text")
                    except json.JSONDecodeError as array_err:
                        logger.debug(f"Failed to parse array: {array_err}")
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
                # Last resort: try to extract any JSON objects using balanced braces
                objects = []
                brace_count = 0
                start_idx = None
                for idx, char in enumerate(response_text):
                    if char == '{':
                        if brace_count == 0:
                            start_idx = idx
                        brace_count += 1
                    elif char == '}':
                        brace_count -= 1
                        if brace_count == 0 and start_idx is not None:
                            obj_str = response_text[start_idx:idx+1]
                            try:
                                obj = json.loads(obj_str)
                                if isinstance(obj, dict):
                                    objects.append(obj)
                            except json.JSONDecodeError:
                                pass
                            start_idx = None
                
                if objects:
                    suggestions_data = objects
                    logger.debug(f"Last resort: extracted {len(objects)} JSON objects using balanced braces")
                else:
                    return None
        
        # Handle case where LLM returns {'suggestions': [...]} instead of list directly
        # Also handle case where suggestions_data is a dict that should be treated as a single suggestion
        if isinstance(suggestions_data, dict):
            if "suggestions" in suggestions_data:
                # Extract suggestions array
                suggestions_data = suggestions_data["suggestions"]
            else:
                # If it's a single dict (not wrapped in suggestions), wrap it in a list
                # But first check if it looks like a valid suggestion object
                if any(key in suggestions_data for key in ["dish_name", "name", "general_term", "role"]):
                    suggestions_data = [suggestions_data]
                else:
                    # Invalid format, try to find suggestions in nested structure
                    logger.warning(f"Unexpected dict format from LLM: {list(suggestions_data.keys())[:5]}")
                    suggestions_data = None
        
        # Validate and create MealSlotDraft
        if isinstance(suggestions_data, list):
            suggestions = []
            # Limit to max 3 suggestions (schema requirement)
            items_to_process = suggestions_data[:3] if len(suggestions_data) > 3 else suggestions_data
            if len(suggestions_data) > 3:
                logger.debug(f"LLM returned {len(suggestions_data)} suggestions, limiting to 3")
            
            # Helper function to process a single item dict
            def process_item_dict(item_dict):
                """Process a dict item and return normalized MealDraftSuggestion or None"""
                if not isinstance(item_dict, dict):
                    return None
                
                # Handle case where item is {'suggestions': [...]}
                if "suggestions" in item_dict and isinstance(item_dict["suggestions"], list):
                    # Extract and process all suggestions
                    results = []
                    for sub_item in item_dict["suggestions"]:
                        if isinstance(sub_item, dict):
                            result = process_item_dict(sub_item)
                            if result:
                                results.append(result)
                        elif isinstance(sub_item, list):
                            for sub_sub_item in sub_item:
                                if isinstance(sub_sub_item, dict):
                                    result = process_item_dict(sub_sub_item)
                                    if result:
                                        results.append(result)
                    return results if results else None
                
                # Normal process for regular dict
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
                        "main course": "main",
                        "main dish": "main",
                        "main": "main",
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
                        "healthy": "main_dish",  # Fallback for "healthy" category
                        "high_protein": "main_dish",  # Fallback for "high_protein" category
                        "high protein": "main_dish",  # Fallback for "high protein" category
                        "salad": "vegetable",  # Salad is usually vegetable
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
                    
                    for key, value in item_dict.items():
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
                    
                    return MealDraftSuggestion(**normalized_item)
                except Exception as e:
                    logger.warning(f"Failed to create MealDraftSuggestion from {item_dict}: {e}")
                    return None
            
            for item in items_to_process:
                # Early exit if we already have 3 suggestions (schema limit)
                if len(suggestions) >= 3:
                    logger.debug(f"Already have {len(suggestions)} suggestions, stopping processing")
                    break
                
                # Skip empty items
                if not item:
                    continue
                
                # Handle case where item might be a string (JSON string)
                if isinstance(item, str):
                    try:
                        item = json.loads(item)
                    except json.JSONDecodeError as e:
                        # Try to fix various JSON issues
                        item_str = item.strip()
                        error_msg = str(e).lower()
                        logger.debug(f"JSON parse failed: {e}, trying to fix...")
                        
                        # Case 1: "Extra data" - multiple JSON objects in one string
                        # Example: '{"a":1}{"b":2}' or '{"a":1}, {"b":2}'
                        if "extra data" in error_msg:
                            logger.debug("Detected 'Extra data' error, trying to split multiple JSON objects...")
                            # Try to split by '}{' or '}, {'
                            import re
                            # Find all complete JSON objects using balanced braces
                            objects = []
                            brace_count = 0
                            start_idx = None
                            for idx, char in enumerate(item_str):
                                if char == '{':
                                    if brace_count == 0:
                                        start_idx = idx
                                    brace_count += 1
                                elif char == '}':
                                    brace_count -= 1
                                    if brace_count == 0 and start_idx is not None:
                                        # Found complete object
                                        obj_str = item_str[start_idx:idx+1]
                                        try:
                                            obj = json.loads(obj_str)
                                            if isinstance(obj, dict):
                                                objects.append(obj)
                                        except json.JSONDecodeError:
                                            pass
                                        start_idx = None
                            
                            if objects:
                                # Process all extracted objects
                                if len(objects) == 1:
                                    item = objects[0]
                                    logger.debug(f"Successfully extracted 1 JSON object from 'Extra data' error")
                                else:
                                    # Multiple objects - process them all by setting item to list
                                    # This will be caught by the isinstance(item, list) check below
                                    item = objects
                                    logger.debug(f"Successfully extracted {len(objects)} JSON objects from 'Extra data' error")
                                # Break out of the error handling and continue to process item
                                # (item is now either a dict or list, which will be handled below)
                            else:
                                # If extraction failed, continue to truncated JSON handling below
                                logger.debug("Failed to extract objects from 'Extra data', trying truncated JSON fix...")
                                # item remains a string, will continue to Case 2 handling
                        
                        # Case 2: Truncated JSON object (missing closing brace)
                        # Only process if item is still a string (not already parsed)
                        if isinstance(item, str) and item_str.startswith('{') and not item_str.endswith('}'):
                            # Try to find and close missing braces
                            open_braces = item_str.count('{')
                            close_braces = item_str.count('}')
                            missing_braces = open_braces - close_braces
                            
                            if missing_braces > 0:
                                # Try to fix by closing braces and quotes
                                fixed_str = item_str
                                
                                # Close any unclosed string values
                                # Check if the string ends with an unclosed value
                                # Pattern: "key": "value (missing closing quote)
                                if not fixed_str.rstrip().endswith('"'):
                                    # Try to find the last colon to see if there's an unclosed value
                                    last_colon_idx = fixed_str.rfind(':')
                                    if last_colon_idx > 0:
                                        after_colon = fixed_str[last_colon_idx+1:].strip()
                                        # If after colon doesn't end with quote or }, it's likely unclosed
                                        if after_colon and not after_colon.endswith('"') and not after_colon.endswith('}'):
                                            # Try to close the string value
                                            # Remove any trailing whitespace and add quote
                                            fixed_str = fixed_str.rstrip()
                                            # If it doesn't end with quote, add it
                                            if not fixed_str.endswith('"'):
                                                fixed_str += '"'
                                
                                # Add missing closing braces
                                fixed_str += '}' * missing_braces
                                
                                try:
                                    item = json.loads(fixed_str)
                                    logger.debug("Successfully fixed truncated JSON")
                                except json.JSONDecodeError:
                                    # If still fails, try balanced brace extraction
                                    brace_count = 0
                                    start_idx = None
                                    for idx, char in enumerate(item_str):
                                        if char == '{':
                                            if brace_count == 0:
                                                start_idx = idx
                                            brace_count += 1
                                        elif char == '}':
                                            brace_count -= 1
                                            if brace_count == 0 and start_idx is not None:
                                                obj_str = item_str[start_idx:idx+1]
                                                try:
                                                    item = json.loads(obj_str)
                                                    logger.debug("Extracted complete JSON object from truncated string")
                                                    break
                                                except json.JSONDecodeError:
                                                    pass
                                    else:
                                        logger.warning(f"Failed to parse or fix truncated JSON: {item[:100] if len(item) > 100 else item}")
                                        continue
                            else:
                                # No missing braces but still failed - might be other issue
                                logger.warning(f"Failed to parse item as JSON (no missing braces): {item[:100] if len(item) > 100 else item}")
                                continue
                        else:
                            # Not a truncated JSON object, and not Extra data - try one more time to extract JSON
                            if isinstance(item, str) and not isinstance(item, (dict, list)):
                                # Try to extract JSON objects from the string using balanced braces
                                objects = []
                                brace_count = 0
                                start_idx = None
                                for idx, char in enumerate(item_str):
                                    if char == '{':
                                        if brace_count == 0:
                                            start_idx = idx
                                        brace_count += 1
                                    elif char == '}':
                                        brace_count -= 1
                                        if brace_count == 0 and start_idx is not None:
                                            obj_str = item_str[start_idx:idx+1]
                                            try:
                                                obj = json.loads(obj_str)
                                                if isinstance(obj, dict):
                                                    objects.append(obj)
                                            except json.JSONDecodeError:
                                                pass
                                            start_idx = None
                                
                                if objects:
                                    # If we found objects, process them
                                    if len(objects) == 1:
                                        item = objects[0]
                                        logger.debug(f"Extracted 1 JSON object from text string")
                                    else:
                                        item = objects
                                        logger.debug(f"Extracted {len(objects)} JSON objects from text string")
                                else:
                                    # No JSON found in the string
                                    logger.warning(f"Failed to parse item as JSON (no JSON objects found): {item[:100] if len(item) > 100 else item}")
                                    continue
                            elif not isinstance(item, (dict, list)):
                                logger.warning(f"Failed to parse item as JSON: {item[:100] if len(item) > 100 else item}")
                                continue
                
                # Skip if item is empty list/array
                if isinstance(item, list):
                    if not item:  # Empty list
                        logger.debug("Skipping empty list item")
                        continue
                    # If it's a non-empty list, extract dicts and process them
                    for sub_item in item:
                        # Early exit if we already have 3 suggestions
                        if len(suggestions) >= 3:
                            break
                        result = process_item_dict(sub_item) if isinstance(sub_item, dict) else None
                        if result:
                            if isinstance(result, list):
                                # Limit the list to not exceed 3 total
                                remaining_slots = 3 - len(suggestions)
                                if remaining_slots > 0:
                                    suggestions.extend(result[:remaining_slots])
                            else:
                                suggestions.append(result)
                    continue
                
                # Process dict item
                result = process_item_dict(item)
                if result:
                    if isinstance(result, list):
                        # Limit the list to not exceed 3 total
                        remaining_slots = 3 - len(suggestions)
                        if remaining_slots > 0:
                            suggestions.extend(result[:remaining_slots])
                    else:
                        suggestions.append(result)
                else:
                    logger.debug(f"Item could not be processed as dict: {type(item)}")
            
            # Filter out None values and ensure we have valid suggestions
            valid_suggestions = [s for s in suggestions if s is not None]
            
            # CRITICAL: Limit to max 3 suggestions (schema requirement)
            # This prevents validation errors when LLM returns too many suggestions
            if len(valid_suggestions) > 3:
                logger.warning(f"LLM returned {len(valid_suggestions)} suggestions, limiting to 3 for schema compliance")
                valid_suggestions = valid_suggestions[:3]
            
            if valid_suggestions:
                try:
                    return MealSlotDraft(meal_type=meal_slot, suggestions=valid_suggestions)
                except Exception as e:
                    logger.warning(f"Failed to create MealSlotDraft: {e}, suggestions count: {len(valid_suggestions)}")
                    # Try with first 3 if still fails
                    if len(valid_suggestions) > 3:
                        try:
                            return MealSlotDraft(meal_type=meal_slot, suggestions=valid_suggestions[:3])
                        except Exception as e2:
                            logger.warning(f"Failed to create MealSlotDraft even with 3 suggestions: {e2}")
                            return None
                    return None
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

