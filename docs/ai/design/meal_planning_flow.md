# Daily Meal Planning Flow - Complete Documentation

## Mục tiêu

- Kết hợp LLM để chọn khung món đa dạng, nhưng mọi tính toán dinh dưỡng dựa trên dữ liệu Recipe (macros_per_serving)
- Đảm bảo phù hợp khẩu vị Việt Nam (bữa sáng nhẹ, trưa/tối cơm hoặc món nước + món mặn + rau + trái cây)
- Giữ tổng macro gần mục tiêu, hỗ trợ swap và giảm latency

---

## Kiến trúc Tổng quan

```
┌─────────────────────────────────────────────────────────────┐
│                    Meal Planning Flow                        │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  0. Chuẩn bị                                                │
│     ├─ Load Profile & Targets                              │
│     ├─ Read Meal History                                    │
│     └─ Load Constraints                                     │
│                                                              │
│  1. LLM Draft (Optional)                                    │
│     ├─ Generate meal framework suggestions                 │
│     └─ Validate with Pydantic schemas                      │
│                                                              │
│  2. Map & Search Recipe                                     │
│     ├─ Hybrid search (vector 0.7, keyword 0.3)            │
│     ├─ Threshold filtering (0.6)                            │
│     └─ Fallback to rule-based                              │
│                                                              │
│  3. Assemble & Portion Scaling                              │
│     ├─ Protein-first scaling (main)                        │
│     ├─ Kcal-scaling (carb)                                 │
│     ├─ Standard servings (veg/fruit)                       │
│     └─ Iterative adjust (if deviation > 20%)               │
│                                                              │
│  4. Validation                                              │
│     ├─ Macro validation                                    │
│     └─ Constraint validation                                │
│                                                              │
│  5. LLM Critic (Optional, Async)                           │
│     └─ Generate critique if violations/warnings            │
│                                                              │
│  6. Response → Frontend                                     │
│     ├─ Stream draft early (tên món)                        │
│     └─ Update with macros after calculation                │
│                                                              │
│  7. Accept / Swap                                           │
│     ├─ Accept → Save to database                           │
│     └─ Swap → Re-assemble with scaling                     │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

---

## Chi tiết các Bước

### 0) Chuẩn bị

**Inputs:**
- User profile (age, gender, weight, height, activity level)
- Meal history (recent 10-20 dishes)
- Constraints (diet types, allergens, devices)

**Outputs:**
- Macro targets (TDEE-based)
- Meal targets per slot (breakfast: 25%, lunch: 37.5%, dinner: 37.5%)
- Filtered recipe pool

**Implementation:**
- `ensure_profile_loaded()` - Load user profile
- `ensure_macro_targets()` - Calculate macro targets
- `_calculate_meal_targets()` - Calculate per-meal targets

---

### 1) LLM Draft (Optional)

**Mục đích:** LLM suggests meal framework before recipe search for better diversity.

**Inputs:**
- Meal history (dish names to avoid)
- Constraints (diet types, allergens)
- User preferences (optional)

**Outputs:**
- `LLMDraftResponse` với suggestions cho breakfast, lunch, dinner
- Mỗi suggestion: `dish_name`, `general_term`, `role`, `meal_type`, `category`, `note`

**Constraints:**
- Tránh trùng meal_history
- Tuân thủ allergen/diet
- Khẩu vị VN (sáng: bánh mì/xôi/phở/mì; trưa/tối: cơm + main + rau + trái cây)
- **Cấm ước lượng kcal** - chỉ đưa tên món và phân loại

**Validation:**
- Pydantic schemas (`MealDraftSuggestion`, `MealSlotDraft`, `LLMDraftResponse`)
- Fallback to rule-based nếu LLM unavailable/fails

**Implementation:**
- `generate_llm_draft()` - Generate complete draft
- `_llm_draft_meal_suggestions()` - Generate for single meal slot

---

### 2) Map & Search Recipe

**Mục đích:** Map LLM suggestions to actual recipes in database.

**IMPORTANT:** Always search recipes from Weaviate database, not from environment cache.
- Weaviate is the source of truth - ensures latest recipes with up-to-date macros
- Environment cache is only used as fallback if database search fails
- This prevents stale data issues

**Process:**
1. **Always call `search_and_rank_tool()`** to search from Weaviate database
2. Vector search Recipe với `general_term` hoặc `dish_name`
3. Hybrid search (vector 0.7, keyword 0.3)
4. Threshold check (0.6) - filter low-score results
5. Fallback BM25 nếu vector search fails
6. Fallback to environment cache only if database search fails completely

**Priority:**
- Recipes với `macros_per_serving` đầy đủ
- Nếu `role` LLM khác tag DB, ưu tiên tag DB và log "role corrected"
- Lấy top 1-3 recipes per slot

**Implementation:**
- `search_and_rank_tool()` - Hybrid search với threshold, reads from Weaviate
- `DEFAULT_HYBRID_ALPHA = 0.7` (vector 0.7, keyword 0.3)
- `DEFAULT_SEARCH_THRESHOLD = 0.6`
- Code in `plan_day_e2e.py` always calls `search_and_rank_tool()` first

---

### 3) Assemble & Portion Scaling

**Mục đích:** Assemble meals với proper scaling để match macro targets.

**Selection Order:**
1. Main (protein dish) - highest priority
2. Carb (rice/noodle; fallback noodle/soup)
3. Veg (vegetable dish)
4. Fruit (fruit dish)

**Scaling Logic:**

**Main (protein dish):**
```
scale = target_protein_slot / recipe_protein
scale = clamp(scale, 0.5, 1.5)  # Prevent extreme scaling
```
- Ưu tiên protein để đảm bảo dinh dưỡng
- Nếu scale vượt giới hạn, thử main khác

**Carb (rice/noodle/soup):**
```
kcal_missing = target_kcal_slot - main_kcal_scaled - veg_fruit_kcal
scale = kcal_missing / recipe_kcal
scale = clamp(scale, 0.5, 2.0)  # Wider range for carbs
```
- Scale sau khi main đã được scale
- Nếu scale vượt giới hạn, chọn carb khác

**Veg/Fruit:**
```
servings = 1.0  # Standard serving
# Hoặc: servings = min(1.0, kcal_missing / 200)  # If needed
```
- Giữ serving chuẩn để tránh quá tải

**Iterative Adjust:**
- Nếu deviation > 20% sau scaling đầu tiên:
  - Thử swap 1-2 main/carb alternatives
  - Recalculate macros
  - Chọn best fit
- Maximum 2 swaps per plan

**Implementation:**
- `_scale_main_by_protein()` - Protein-first scaling
- `_scale_carb_by_kcal()` - Kcal-scaling
- `_try_swap_alternatives()` - Iterative adjust
- `_calculate_total_deviation_score()` - Calculate fit score

---

### 4) Validation

**Macro Validation:**
- So sánh với targets ± tolerance (default 15%)
- Violations: deviation > tolerance
- Warnings: deviation > tolerance * 0.7

**Constraint Validation:**
- Diet type matching
- Allergen exclusion
- Device compatibility

**Fallback:**
- Nếu thiếu slot do search fail → fallback món mặc định (cơm/rau/trái cây)
- Đảm bảo không trả bữa trống

**Implementation:**
- `_validate_macro_targets()` - Macro validation
- `_validate_constraints()` - Constraint validation

---

### 5) LLM Critic (Optional, Async)

**Mục đích:** LLM provides critique and suggestions for meal plans.

**Trigger:**
- Chỉ chạy nếu có violations hoặc warnings
- Async, non-blocking (5-second timeout)

**Inputs:**
- Plan (tên món + macros thực tế)
- Targets
- Validation results

**Outputs:**
- Critic note (2-3 câu, tiếng Việt)
- Suggestions for improvement (không đưa số cụ thể)

**Constraints:**
- **Không cho LLM sửa số** - chỉ gợi ý chung
- Chạy nền, không chặn response
- Timeout protection

**Implementation:**
- `_llm_critic_plan()` - Generate critic note
- `create_critic_task()` - Create async task
- `generate_llm_critic_async()` - Async wrapper

---

### 6) Response → Frontend

**Streaming Flow:**
1. **Early Draft** (ngay sau khi chọn món):
   ```
   📋 Draft meal plan:
     🌅 Breakfast: Phở bò
     🍽️ Lunch: Cơm gà, Thịt kho, Rau muống, Chuối
     🌙 Dinner: Cơm cá, Cá kho, Canh chua, Cam
   ```

2. **Macro Details** (sau khi tính toán):
   ```
   ⚖️ Calculating nutrition details...
   📊 Plan macros: 2000 kcal | 150g protein | 67g fat | 200g carbs
   ```

3. **Final Plan** (sau validation):
   ```
   ✅ Daily meal plan ready!
   ```

**Plan Structure:**
```json
{
  "plan_type": "day",
  "meals": {
    "breakfast": {
      "recipe": {...},
      "servings": 1.0,
      "macros": {...}
    },
    "lunch": {
      "recipe": {...},
      "servings": 1.0,
      "macros_main": {...},
      "macros_total": {...},
      "accompaniments": [
        {"recipe": {...}, "servings": 1.0, "type": "main", "macros": {...}},
        {"recipe": {...}, "servings": 1.0, "type": "vegetable", "macros": {...}}
      ]
    }
  },
  "total_macros": {...},
  "validation": {...},
  "critic_note": "..." // Optional
}
```

---

### 7) Accept / Swap

**Accept:**
- User accepts plan → Save to `MealPlan` and `MealPlanItem` collections
- Log to meal_history
- Plan becomes part of user's meal history

**Swap:**
- User swaps main/carb → Call `swap_meal_item_tool`
- Re-assemble meal với proper scaling:
  - Scale main by protein target
  - Scale carb by remaining kcal
  - Keep veg/fruit at standard serving
- Recalculate meal macros and total day macros
- Update database

**Implementation:**
- `swap_meal_item_tool()` - Swap and re-assemble
- `sync_plan_to_weaviate()` - Save plan to database

---

## Implementation Details

### Helper Functions

**Scaling:**
- `_calculate_meal_targets()` - Calculate targets per meal slot
- `_scale_main_by_protein()` - Protein-first scaling (0.5-1.5x)
- `_scale_carb_by_kcal()` - Kcal-scaling (0.5-2.0x)

**Iterative Adjust:**
- `_calculate_macro_deviation()` - Calculate deviation per macro
- `_calculate_total_deviation_score()` - Weighted total deviation
- `_try_swap_alternatives()` - Try swapping recipes

**LLM Integration:**
- `generate_llm_draft()` - Generate LLM draft
- `_llm_draft_meal_suggestions()` - Generate for single slot
- `_llm_critic_plan()` - Generate critic note
- `create_critic_task()` - Create async task

**Validation:**
- `_validate_macro_targets()` - Macro validation
- `_validate_constraints()` - Constraint validation

### Schemas

**LLM Draft:**
- `MealDraftSuggestion` - Single suggestion
- `MealSlotDraft` - Draft for meal slot
- `LLMDraftResponse` - Complete draft

### Configuration

**Search:**
- `DEFAULT_HYBRID_ALPHA = 0.7` (vector 0.7, keyword 0.3)
- `DEFAULT_SEARCH_THRESHOLD = 0.6`

**Scaling:**
- Main: 0.5-1.5x
- Carb: 0.5-2.0x
- Veg/Fruit: 1.0x (standard)

**Iterative Adjust:**
- Trigger: deviation > 20%
- Max swaps: 2 per plan

**LLM Critic:**
- Timeout: 5 seconds
- Only runs if violations/warnings exist

---

## Error Handling & Fallbacks

### LLM Draft Failures
- Fallback: Skip LLM draft, use rule-based selection
- Log warning, continue with normal flow

### Search Failures
- Fallback: Use rule-based selection from available recipes
- Log search misses for debugging

### Scaling Failures
- Fallback: Use 1.0 serving if scaling fails
- Log warning, continue with plan

### LLM Critic Failures
- Fallback: Skip critic, continue without note
- Non-blocking, doesn't affect main response

---

## Performance Considerations

### Latency Optimization
- Stream draft early (tên món) before calculations
- LLM Critic runs async, non-blocking
- Progressive updates to user

### Database Optimization
- Batch operations where possible
- Cache frequently accessed data
- Efficient queries with proper filters

### LLM Cost Optimization
- LLM Draft: Optional, only if `base_lm` available
- LLM Critic: Only runs if violations/warnings exist
- Timeout protection prevents hanging

---

## Testing Strategy

### Unit Tests
- Helper functions (scaling, validation, etc.)
- Schema validation
- Error handling

### Integration Tests
- End-to-end planning flow
- Swap operations
- LLM integration (with mocks)

### Edge Cases
- Missing macros
- Search failures
- LLM failures
- Extreme scaling scenarios

---

## Future Enhancements

1. **Enhanced LLM Draft:**
   - Map LLM suggestions to recipes automatically
   - Use `general_term` for better search matching

2. **Improved Swap:**
   - Store `item_type` in MealPlanItem schema
   - Support batch swaps
   - Better item identification

3. **Advanced Streaming:**
   - Stream individual selections as they're chosen
   - Real-time macro updates
   - Progress indicators

---

## References

- Original Design: `docs/ai/design/planning_flow.md`
- Implementation: `MealAgent/tools/plan_day/plan_day_e2e.py`
- Helpers: `MealAgent/tools/utils/planning_helpers.py`
- LLM Integration: `MealAgent/tools/utils/llm_draft.py`, `llm_critic.py`
- Swap Tool: `MealAgent/tools/plan_day/swap_meal_item.py`

---

**Last Updated**: 2024  
**Status**: ✅ Implemented and Tested

