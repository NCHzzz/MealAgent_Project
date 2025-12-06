# Fix: Tools Must Read from Database, Not Environment

> **Xem thêm**: [Elysia Environment Understanding](./elysia_environment_understanding.md) để hiểu rõ về cách Environment hoạt động.

## Vấn đề Phát hiện

Nhiều tools đang đọc dữ liệu từ **environment cache** thay vì từ **Weaviate database**, vi phạm nguyên tắc:
- **Database (Weaviate) là source of truth** - luôn có data mới nhất
- **Environment chỉ để hỗ trợ LLM agent điều hướng** và phục vụ hoạt động hệ thống
- Environment không phải là nguồn dữ liệu chính

**Theo tài liệu Elysia**: Environment là persistent object để lưu trữ kết quả từ tools và metadata, **KHÔNG phải** để lưu trữ business data chính. Business data phải được lưu trong database (Weaviate).

## Phân loại Tools

### ✅ Tools ĐÚNG (đã có refresh logic):
- `profile_targets.py`: Đọc từ environment nhưng có **hard refresh từ Weaviate**
- `macro_calc.py`: Đọc từ environment nhưng có **hard refresh từ Weaviate**
- `log_meal_e2e.py`: Đọc từ environment nhưng có **fallback fetch từ Weaviate**
- `meal_history.py`: Đọc profile từ environment nhưng query logs từ Weaviate

### ❌ Tools SAI (đã sửa):
1. **plan_week_e2e.py**: Đọc recipes từ environment → Sửa: Luôn search từ Weaviate
2. **gap_fill.py**: Đọc plan từ environment → Sửa: Load từ Weaviate bằng plan_id
3. **substitute.py**: Đọc plan từ environment → Sửa: Load từ Weaviate bằng plan_id
4. **pantry_diff.py**: Đọc plan và pantry từ environment → Sửa: Load từ Weaviate
5. **auto_calculate_macros.py**: Đọc recipes từ environment → Sửa: Load từ Weaviate
6. **micros.py**: Đọc plan từ environment → Sửa: Load từ Weaviate bằng plan_id
7. **cook_mode.py**: Đọc recipes từ environment → Sửa: Load từ Weaviate nếu có food_id

## Thay đổi Chi tiết

### 1. plan_week_e2e.py

**Trước:**
```python
# Đọc từ environment cache
sr = tree_data.environment.find("search_and_rank_tool", "topk")
recipes = sr[0]["objects"] if sr else []
```

**Sau:**
```python
# Luôn search từ Weaviate database
async for result in search_and_rank_tool(...):
    recipes = result.objects  # Lấy từ Weaviate
# Fallback về cache chỉ khi database search fails
```

### 2. gap_fill.py, substitute.py, micros.py, pantry_diff.py

**Trước:**
```python
# Đọc plan từ environment
day_plan_results = tree_data.environment.find("plan_day_e2e_tool", "plan")
plan = day_plan_results[0]["objects"][0] if day_plan_results else None
```

**Sau:**
```python
# Load plan từ Weaviate database
if plan_id:
    plan = load_plan_from_weaviate(plan_id, client_manager, user_id)
elif user_id:
    plan = load_latest_plan_from_weaviate(user_id, client_manager, "day")
# Fallback về environment cache chỉ khi không có plan_id/user_id
```

### 3. auto_calculate_macros.py

**Trước:**
```python
# Đọc recipes từ environment
topk_results = tree_data.environment.find("search_and_rank_tool", "topk")
candidates = _extract_objects(topk_results)
```

**Sau:**
```python
# Load recipes từ Weaviate database
if missing_ids:
    for recipe_id in missing_ids:
        recipe = fetch_from_weaviate(recipe_id)  # Load từ database
        candidates.append(recipe)
# Fallback về environment cache chỉ khi database fails
```

### 4. cook_mode.py

**Trước:**
```python
# Đọc recipe từ environment
res = tree_data.environment.find("search_and_rank_tool", "topk")
recipe = find_in_results(res, food_id)
```

**Sau:**
```python
# Load recipe từ Weaviate nếu có food_id
if food_id and client_manager:
    recipe = _find_recipe_from_weaviate(food_id, client_manager)
# Fallback về environment cache nếu không có food_id
```

### 5. pantry_diff.py

**Trước:**
```python
# Đọc pantry từ environment
pantry_results = tree_data.environment.find("pantry_crud_tool", "state")
pantry_state = pantry_results[0]["objects"][0]
```

**Sau:**
```python
# Load pantry từ Weaviate database
pantry_filter = build_filters_from_where({
    "path": ["user_id"], "operator": "Equal", "valueString": user_id
})
pantry_results = pantry_collection.query.fetch_objects(filters=pantry_filter)
pantry_state = pantry_results.objects[0].properties
# Fallback về environment cache chỉ khi database fails
```

## Helper Functions Created

### `MealAgent/tools/utils/plan_loader.py`

**Functions:**
- `load_plan_from_weaviate(plan_id, client_manager, user_id)`: Load plan by plan_id
- `load_latest_plan_from_weaviate(user_id, client_manager, plan_type)`: Load latest plan for user

**Purpose:**
- Centralized logic để load plans từ Weaviate
- Reconstruct plan structure từ MealPlan + MealPlanItem collections
- Handle both day and week plans

## Environment Usage Guidelines

### ✅ ĐÚNG - Environment dùng cho:
1. **LLM Agent Navigation**: Metadata để agent biết tool nào đã chạy
2. **System Operations**: Temporary state, flags, hints
3. **Fallback**: Chỉ khi database access fails
4. **Constraints/Filters**: Metadata về user preferences (không phải data chính)

### ❌ SAI - Environment KHÔNG dùng cho:
1. **Primary Data Source**: Recipes, plans, profiles, pantry
2. **Data Storage**: Bất kỳ data nào cần persistence
3. **Source of Truth**: Database là source of truth, không phải environment

## Pattern cho Tools Mới

### Pattern Đúng:
```python
# 1. Try database first (source of truth)
if plan_id:
    plan = load_plan_from_weaviate(plan_id, client_manager, user_id)
elif user_id:
    plan = load_latest_plan_from_weaviate(user_id, client_manager)

# 2. Fallback to environment cache (only as last resort)
if not plan:
    plan_results = tree_data.environment.find("plan_day_e2e_tool", "plan")
    if plan_results:
        plan = plan_results[0]["objects"][0]
        yield Response("⚠️ Using cached plan (please provide plan_id for database access)")
```

### Pattern SAI (tránh):
```python
# ❌ Đọc từ environment trước
plan_results = tree_data.environment.find("plan_day_e2e_tool", "plan")
plan = plan_results[0]["objects"][0] if plan_results else None

# ❌ Chỉ load từ database nếu environment trống
if not plan:
    plan = load_from_weaviate(...)
```

## Verification

### Tests Updated:
- All integration tests now mock `search_and_rank_tool` to simulate Weaviate search
- Tests verify tools call database functions, not just environment.find
- Fallback behavior tested

### Manual Verification:
- ✅ plan_week_e2e.py: Calls search_and_rank_tool() (reads from Weaviate)
- ✅ gap_fill.py: Calls load_plan_from_weaviate() if plan_id provided
- ✅ substitute.py: Calls load_plan_from_weaviate() if plan_id provided
- ✅ pantry_diff.py: Queries Pantry collection from Weaviate
- ✅ micros.py: Calls load_plan_from_weaviate() if plan_id provided
- ✅ auto_calculate_macros.py: Fetches recipes from Weaviate Recipe collection
- ✅ cook_mode.py: Calls _find_recipe_from_weaviate() if food_id provided

## Impact

### Positive:
- ✅ Data luôn fresh từ database
- ✅ Đúng với architecture: Database = source of truth
- ✅ Code rõ ràng về nguồn dữ liệu
- ✅ Consistent behavior across all tools

### Considerations:
- ⚠️ Tools cần plan_id hoặc user_id để load từ database
- ✅ Fallback về environment cache khi không có plan_id/user_id
- ✅ Warning messages khi dùng cached data

## Files Changed

### New Files:
- `MealAgent/tools/utils/plan_loader.py`: Helper functions to load plans from Weaviate

### Modified Files:
1. `MealAgent/tools/plan_week/plan_week_e2e.py`
2. `MealAgent/tools/gap_fill/gap_fill.py`
3. `MealAgent/tools/substitution/substitute.py`
4. `MealAgent/tools/shopping/pantry_diff.py`
5. `MealAgent/tools/nutrition/auto_calculate_macros.py`
6. `MealAgent/tools/micros/micros.py`
7. `MealAgent/tools/cook_mode/cook_mode.py`

---

**Date**: 2024  
**Status**: ✅ Fixed and Verified  
**Principle**: Database is source of truth, Environment is for navigation only

