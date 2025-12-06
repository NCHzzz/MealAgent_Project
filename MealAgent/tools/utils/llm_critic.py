"""
LLM Critic helper functions for Phase 2.2.

Provides optional async LLM-based critique of meal plans.
"""

import json
import logging
from typing import Dict, Any, Optional, List
import asyncio

logger = logging.getLogger(__name__)


async def _llm_critic_plan(
    base_lm,
    plan: Dict[str, Any],
    targets: Dict[str, float],
    validation: Dict[str, Any],
) -> Optional[str]:
    """
    Use LLM to critique a meal plan and provide suggestions.
    
    Args:
        base_lm: LLM client (optional, can be None)
        plan: Plan dictionary with meals and macros
        targets: Target macros
        validation: Validation results
    
    Returns:
        Critic note as string, or None if LLM unavailable/fails
    """
    if not base_lm:
        return None
    
    # Only run critic if there are warnings or violations
    macro_validation = validation.get("macro_validation", {})
    has_violations = len(macro_validation.get("violations", [])) > 0
    has_warnings = len(macro_validation.get("warnings", [])) > 0
    
    if not (has_violations or has_warnings):
        # Plan is good, no need for critic
        return None
    
    # Build plan summary for LLM
    meals_summary = []
    for meal_key, meal_data in plan.get("meals", {}).items():
        recipe = meal_data.get("recipe", {})
        dish_name = recipe.get("dish_name", "Unknown")
        macros = meal_data.get("macros", {})
        
        meal_info = f"- {meal_key}: {dish_name} ({macros.get('kcal', 0):.0f} kcal, {macros.get('protein_g', 0):.0f}g protein)"
        meals_summary.append(meal_info)
    
    total_macros = plan.get("total_macros", {})
    
    # Build violations/warnings summary
    violations_text = ""
    if has_violations:
        violations = macro_validation.get("violations", [])
        violations_text = "\nCảnh báo:\n"
        for v in violations[:3]:  # Limit to 3
            macro = v.get("macro", "")
            target = v.get("target", 0)
            actual = v.get("actual", 0)
            deviation = v.get("deviation_percent", 0)
            violations_text += f"- {macro}: {actual:.0f} (mục tiêu: {target:.0f}, lệch {deviation:.1f}%)\n"
    
    warnings_text = ""
    if has_warnings:
        warnings = macro_validation.get("warnings", [])
        warnings_text = "\nLưu ý:\n"
        for w in warnings[:2]:  # Limit to 2
            macro = w.get("macro", "")
            target = w.get("target", 0)
            actual = w.get("actual", 0)
            deviation = w.get("deviation_percent", 0)
            warnings_text += f"- {macro}: {actual:.0f} (mục tiêu: {target:.0f}, lệch {deviation:.1f}%)\n"
    
    prompt = f"""Bạn là chuyên gia dinh dưỡng. Hãy đánh giá kế hoạch bữa ăn sau và đưa ra nhận xét ngắn gọn (2-3 câu).

Kế hoạch bữa ăn:
{chr(10).join(meals_summary)}

Tổng macros:
- Kcal: {total_macros.get('kcal', 0):.0f} (mục tiêu: {targets.get('tdee_kcal', 0):.0f})
- Protein: {total_macros.get('protein_g', 0):.0f}g (mục tiêu: {targets.get('protein_g', 0):.0f}g)
- Carb: {total_macros.get('carb_g', 0):.0f}g (mục tiêu: {targets.get('carb_g', 0):.0f}g)
- Fat: {total_macros.get('fat_g', 0):.0f}g (mục tiêu: {targets.get('fat_g', 0):.0f}g)
{violations_text}{warnings_text}

Yêu cầu:
- Đưa ra nhận xét ngắn gọn về cân bằng dinh dưỡng (2-3 câu)
- Nếu có lệch lớn, gợi ý cách cải thiện (ví dụ: "Có thể giảm món X hoặc tăng món Y")
- KHÔNG được đưa ra số cụ thể về kcal/protein/carb - chỉ gợi ý chung
- Viết bằng tiếng Việt, thân thiện và dễ hiểu

Trả về chỉ text nhận xét, không cần format đặc biệt.
"""
    
    try:
        # Call LLM - try different interfaces
        response_text = None
        
        if hasattr(base_lm, "generate"):
            response_text = base_lm.generate(prompt)
        elif callable(base_lm):
            result = base_lm(prompt)
            if isinstance(result, str):
                response_text = result
            elif hasattr(result, "content"):
                response_text = result.content
            elif hasattr(result, "text"):
                response_text = result.text
        
        if response_text:
            # Clean up response (remove markdown, extra whitespace)
            response_text = response_text.strip()
            # Remove markdown code blocks if present
            if "```" in response_text:
                lines = response_text.split("\n")
                response_text = "\n".join(
                    line for line in lines 
                    if not line.strip().startswith("```")
                ).strip()
            
            return response_text[:500]  # Limit length
        
        return None
        
    except Exception as e:
        logger.warning(f"LLM critic failed: {e}")
        return None


async def generate_llm_critic_async(
    base_lm,
    plan: Dict[str, Any],
    targets: Dict[str, float],
    validation: Dict[str, Any],
) -> Optional[str]:
    """
    Generate LLM critic note asynchronously (non-blocking).
    
    This function is designed to run in background without blocking the main response.
    
    Args:
        base_lm: LLM client
        plan: Plan dictionary
        targets: Target macros
        validation: Validation results
    
    Returns:
        Critic note or None
    """
    if not base_lm:
        return None
    
    try:
        # Run in background task (non-blocking)
        critic_note = await _llm_critic_plan(base_lm, plan, targets, validation)
        return critic_note
    except Exception as e:
        logger.debug(f"LLM critic async failed: {e}")
        return None


def create_critic_task(
    base_lm,
    plan: Dict[str, Any],
    targets: Dict[str, float],
    validation: Dict[str, Any],
) -> Optional[asyncio.Task]:
    """
    Create an async task for LLM critic (non-blocking).
    
    Args:
        base_lm: LLM client
        plan: Plan dictionary
        targets: Target macros
        validation: Validation results
    
    Returns:
        asyncio.Task or None if LLM unavailable
    """
    if not base_lm:
        return None
    
    try:
        task = asyncio.create_task(
            generate_llm_critic_async(base_lm, plan, targets, validation)
        )
        return task
    except Exception as e:
        logger.debug(f"Failed to create LLM critic task: {e}")
        return None


