"""
Pydantic schemas for LLM draft meal suggestions.

Used in Phase 2.1: LLM Draft Step to validate LLM output.
"""

from typing import List, Literal, Optional
from pydantic import BaseModel, Field, field_validator


class MealDraftSuggestion(BaseModel):
    """Single meal suggestion from LLM draft."""
    
    dish_name: str = Field(..., description="Tên món ăn (ví dụ: 'Phở bò', 'Cơm gà nướng')")
    general_term: str = Field(..., description="Tên chuẩn hóa để search (ví dụ: 'pho bo', 'com ga nuong')")
    role: Literal["carb", "main", "vegetable", "fruit", "breakfast"] = Field(
        ..., 
        description="Vai trò của món: carb (cơm/mì), main (món mặn), vegetable (rau), fruit (trái cây), breakfast (bữa sáng)"
    )
    meal_type: Literal["breakfast", "lunch", "dinner"] = Field(
        ...,
        description="Loại bữa: breakfast, lunch, hoặc dinner"
    )
    category: Literal["rice", "noodle", "soup", "bread", "bakery", "main_dish", "vegetable", "fruit"] = Field(
        ...,
        description="Danh mục món: rice (cơm), noodle (mì/bún), soup (canh/phở), bread (bánh mì), bakery (bánh ngọt), main_dish (món mặn), vegetable (rau), fruit (trái cây)"
    )
    note: Optional[str] = Field(
        None,
        description="Ghi chú về món (tùy chọn)"
    )
    
    @field_validator("general_term")
    @classmethod
    def validate_general_term(cls, v: str) -> str:
        """Ensure general_term is lowercase and normalized."""
        return v.lower().strip()
    
    @field_validator("dish_name")
    @classmethod
    def validate_dish_name(cls, v: str) -> str:
        """Ensure dish_name is not empty."""
        if not v or not v.strip():
            raise ValueError("dish_name cannot be empty")
        return v.strip()


class MealSlotDraft(BaseModel):
    """Draft suggestions for a single meal slot."""
    
    meal_type: Literal["breakfast", "lunch", "dinner"] = Field(
        ...,
        description="Loại bữa"
    )
    suggestions: List[MealDraftSuggestion] = Field(
        ...,
        min_length=1,
        max_length=3,
        description="2-3 gợi ý món cho bữa này"
    )
    
    @field_validator("suggestions")
    @classmethod
    def validate_suggestions_count(cls, v: List[MealDraftSuggestion]) -> List[MealDraftSuggestion]:
        """Ensure we have 1-3 suggestions."""
        if len(v) < 1:
            raise ValueError("Must have at least 1 suggestion")
        if len(v) > 3:
            raise ValueError("Cannot have more than 3 suggestions")
        return v


class LLMDraftResponse(BaseModel):
    """Complete LLM draft response for daily meal plan."""
    
    breakfast: MealSlotDraft = Field(..., description="Gợi ý cho bữa sáng")
    lunch: MealSlotDraft = Field(..., description="Gợi ý cho bữa trưa")
    dinner: MealSlotDraft = Field(..., description="Gợi ý cho bữa tối")
    
    @field_validator("breakfast", "lunch", "dinner")
    @classmethod
    def validate_meal_type_match(cls, v: MealSlotDraft, info) -> MealSlotDraft:
        """Ensure meal_type matches the field name."""
        field_name = info.field_name
        if v.meal_type != field_name:
            raise ValueError(f"meal_type '{v.meal_type}' does not match field name '{field_name}'")
        return v


