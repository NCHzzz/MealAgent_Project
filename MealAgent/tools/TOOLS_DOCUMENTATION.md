# MealAgent Tools Documentation

Tài liệu này mô tả chi tiết dữ liệu **Input** và **Output** của từng tool trong hệ thống MealAgent.

---

## Mục Lục

1. [Profile Tools](#1-profile-tools)
   - [profile_crud_tool](#11-profile_crud_tool)
   - [macro_calc_tool](#12-macro_calc_tool)
2. [Search & Constraints Tools](#2-search--constraints-tools)
   - [search_and_rank_tool](#21-search_and_rank_tool)
   - [constraints_guard_tool](#22-constraints_guard_tool)
3. [Planning Tools](#3-planning-tools)
   - [plan_day_e2e_tool](#31-plan_day_e2e_tool)
   - [plan_week_e2e_tool](#32-plan_week_e2e_tool)
   - [swap_meal_item_tool](#33-swap_meal_item_tool)
4. [Nutrition Tools](#4-nutrition-tools)
   - [calculate_recipe_macros_tool](#41-calculate_recipe_macros_tool)
   - [auto_calculate_macros_tool](#42-auto_calculate_macros_tool)
   - [micros_tool](#43-micros_tool)
5. [Optimization Tools](#5-optimization-tools)
   - [gap_fill_tool](#51-gap_fill_tool)
   - [substitute_tool](#52-substitute_tool)
6. [Meal Logging Tools](#6-meal-logging-tools)
   - [log_meal_e2e_tool](#61-log_meal_e2e_tool)
   - [accept_plan_tool](#62-accept_plan_tool)
   - [meal_history_tool](#63-meal_history_tool)
7. [Pantry & Shopping Tools](#7-pantry--shopping-tools)
   - [pantry_crud_tool](#71-pantry_crud_tool)
   - [pantry_diff_tool](#72-pantry_diff_tool)
8. [Cooking Tools](#8-cooking-tools)
   - [cook_mode_tool](#81-cook_mode_tool)

---

## 1. Profile Tools

### 1.1 profile_crud_tool

**Mô tả:** Tạo, đọc, hoặc cập nhật hồ sơ người dùng (`UserProfile`) và lưu vào environment.

**File:** `MealAgent/tools/profile/profile_crud.py`

#### Input Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `tree_data` | `TreeData` | ✅ | - | Elysia tree data context |
| `client_manager` | `ClientManager` | ✅ | - | Weaviate client manager |
| `action` | `str` | ❌ | `"create"` | Hành động: `"create"`, `"read"`, `"update"` |
| `profile_data` | `dict \| None` | ❌ | `None` | Dữ liệu hồ sơ người dùng |

**Cấu trúc `profile_data`:**
```python
{
    "user_id": str,          # Required - ID người dùng duy nhất
    "age": int,              # Required - Tuổi (năm)
    "gender": str,           # Required - Giới tính ("male"/"female")
    "weight_kg": float,      # Required - Cân nặng (kg)
    "height_cm": float,      # Required - Chiều cao (cm)  
    "activity_level": str,   # Required - Mức độ vận động
    "diet_type": str,        # Optional - Loại chế độ ăn
    "allergens": list[str],  # Optional - Danh sách dị ứng
    "health_goal": str,      # Optional - Mục tiêu sức khỏe
    "tdee_kcal": float,      # Optional - Pre-computed TDEE
    "protein_g": float,      # Optional - Target protein
    "fat_g": float,          # Optional - Target fat
    "carb_g": float,         # Optional - Target carbs
}
```

#### Output (Environment Writes)

**Key:** `profile_crud_tool.profile`

```python
{
    "name": "profile",
    "objects": [profile_data],  # Dữ liệu hồ sơ đã lưu
    "metadata": {
        "action": str,      # "create" hoặc "update" hoặc "read"
        "user_id": str,     # ID người dùng
    },
    "payload_type": "generic",
    "display": True
}
```

**Auto-trigger:** Sau khi create/update thành công, tự động gọi `macro_calc_tool` để tính toán TDEE và macro targets.

---

### 1.2 macro_calc_tool

**Mô tả:** Tính toán TDEE và mục tiêu macros (mặc định tỷ lệ 30/30/40).

**File:** `MealAgent/tools/profile/macro_calc.py`

#### Input Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `tree_data` | `TreeData` | ✅ | - | Elysia tree data context |
| `client_manager` | `ClientManager` | ✅ | - | Weaviate client manager |
| `protein_share` | `float` | ❌ | `0.30` | Tỷ lệ protein (30%) |
| `fat_share` | `float` | ❌ | `0.30` | Tỷ lệ chất béo (30%) |
| `carb_share` | `float` | ❌ | `0.40` | Tỷ lệ carb (40%) |

#### Environment Reads

- `profile_crud_tool.profile` - Hồ sơ người dùng

#### Output (Environment Writes)

**Key:** `macro_calc_tool.targets`

```python
{
    "name": "targets",
    "objects": [{
        "tdee_kcal": float,     # Tổng năng lượng tiêu hao hàng ngày (kcal)
        "protein_g": float,     # Mục tiêu protein (g)
        "fat_g": float,         # Mục tiêu chất béo (g)
        "carb_g": float,        # Mục tiêu carbohydrate (g)
        "split": {
            "protein": float,   # Tỷ lệ protein thực tế
            "fat": float,       # Tỷ lệ fat thực tế
            "carb": float       # Tỷ lệ carb thực tế
        }
    }],
    "metadata": {
        "source": str,  # "profile" hoặc "defaults"
    },
    "payload_type": "generic",
    "display": True
}
```

---

## 2. Search & Constraints Tools

### 2.1 search_and_rank_tool

**Mô tả:** Tìm kiếm công thức hybrid với bộ lọc, xếp hạng đa dạng và phù hợp macros.

**File:** `MealAgent/tools/search/search_and_rank.py`

#### Input Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `tree_data` | `TreeData` | ✅ | - | Elysia tree data context |
| `client_manager` | `ClientManager` | ✅ | - | Weaviate client manager |
| `query_text` | `str` | ❌ | `""` | Truy vấn tìm kiếm |
| `collection_name` | `str` | ❌ | `"Recipe"` | Tên collection Weaviate |
| `limit` | `int` | ❌ | `100` | Giới hạn kết quả |
| `alpha` | `float` | ❌ | `0.7` | Hybrid alpha (Vector 0.7, BM25 0.3) |
| `top_k` | `int` | ❌ | `100` | Số kết quả top trả về |
| `use_elysia_query` | `bool` | ❌ | `False` | Sử dụng LLM-driven query |
| `user_id` | `str \| None` | ❌ | `None` | ID người dùng |
| `base_lm` | `any` | ❌ | `None` | Language model |
| `complex_lm` | `any` | ❌ | `None` | Complex language model |
| `recent_plan_window_minutes` | `int` | ❌ | `10` | Cửa sổ thời gian tránh lặp (phút) |

#### Environment Reads

- `constraints_guard_tool.filters` - Bộ lọc diet/allergen/time/device
- `macro_calc_tool.targets` - Mục tiêu macros

#### Output (Environment Writes)

**Key:** `search_and_rank_tool.topk`

```python
{
    "name": "topk",
    "objects": [
        {
            "food_id": str,              # ID công thức
            "dish_name": str,            # Tên món ăn
            "description": str,          # Mô tả
            "ingredients": list[str],    # Danh sách nguyên liệu
            "ingredients_with_qty": list[str],  # Nguyên liệu với số lượng
            "cooking_method": str,       # Phương pháp nấu
            "cooking_time": int,         # Thời gian nấu (phút)
            "diet_type": str,            # Loại chế độ ăn
            "allergens": list[str],      # Chất gây dị ứng
            "dish_type": str,            # Loại món (breakfast/lunch/dinner/snack)
            "macros_per_serving": {
                "kcal": float,
                "protein_g": float,
                "fat_g": float,
                "carb_g": float
            },
            "image_link": str,           # Link ảnh món ăn
            # ... thêm các fields khác
        },
        # ... nhiều recipes
    ],
    "metadata": {
        "top_k": int,
        "total_scored": int,
        "has_targets": bool,
        "collection": str,
        "query": str,
    },
    "payload_type": "recipe"
}
```

---

### 2.2 constraints_guard_tool

**Mô tả:** Gộp các ràng buộc diet/allergen/time/equipment thành một Weaviate `where` clause.

**File:** `MealAgent/tools/constraints/constraints_guard.py`

#### Input Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `tree_data` | `TreeData` | ✅ | - | Elysia tree data context |
| `client_manager` | `ClientManager` | ✅ | - | Weaviate client manager |
| `diet_types` | `List[str] \| None` | ❌ | `None` | Danh sách loại chế độ ăn |
| `exclude_allergens` | `List[str] \| None` | ❌ | `None` | Danh sách dị ứng cần loại trừ |
| `max_cooking_time` | `int \| None` | ❌ | `None` | Thời gian nấu tối đa (phút) |
| `required_device` | `str \| None` | ❌ | `None` | Thiết bị bắt buộc |
| `exclude_devices` | `list[str] \| None` | ❌ | `None` | Thiết bị cần loại trừ |
| `user_id` | `str \| None` | ❌ | `None` | ID người dùng |
| `base_lm` | `any` | ❌ | `None` | Language model |
| `complex_lm` | `any` | ❌ | `None` | Complex language model |

#### Environment Reads

- `profile_crud_tool.profile` - Để lấy defaults từ profile

#### Output (Environment Writes)

**Key:** `constraints_guard_tool.filters`

```python
{
    "name": "filters",
    "objects": [{
        "where": {
            # Weaviate where clause
            "operator": "And",
            "operands": [
                {"path": ["diet_type"], "operator": "ContainsAny", "valueTextArray": [...]},
                {"operator": "Not", "operands": [{"path": ["allergens"], ...}]},
                {"path": ["cooking_time"], "operator": "LessThanEqual", "valueInt": ...},
                # ... thêm filters
            ]
        }
    }],
    "metadata": {
        "has_filters": bool,
        "diet_types": list[str],
        "exclude_allergens": list[str],
        "max_cooking_time": int | None,
        "required_device": str | None,
        "exclude_devices": list[str],
    },
    "payload_type": "generic",
    "display": False
}
```

---

## 3. Planning Tools

### 3.1 plan_day_e2e_tool

**Mô tả:** Bộ lập kế hoạch End-to-end hàng ngày: tạo kế hoạch 3 bữa (sáng, trưa, tối).

**File:** `MealAgent/tools/plan_day/plan_day_e2e.py`

#### Input Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `tree_data` | `TreeData` | ✅ | - | Elysia tree data context |
| `client_manager` | `ClientManager` | ✅ | - | Weaviate client manager |
| `base_lm` | `any` | ❌ | `None` | Base language model |
| `complex_lm` | `any` | ❌ | `None` | Complex language model |
| `query_text` | `str` | ❌ | `""` | Truy vấn/yêu cầu |
| `collection_name` | `str` | ❌ | `"Recipe"` | Tên collection |
| `macro_tolerance_percent` | `float` | ❌ | `0.15` | Dung sai macro (±15%) |
| `user_id` | `str \| None` | ❌ | `None` | ID người dùng |
| `plan_id` | `str \| None` | ❌ | `None` | ID kế hoạch |
| `start_date` | `str \| None` | ❌ | `None` | Ngày bắt đầu (RFC3339) |
| `recent_plan_window_minutes` | `int` | ❌ | `10080` | Cửa sổ tránh lặp (7 ngày) |

#### Environment Reads

- `macro_calc_tool.targets` - Mục tiêu macros
- `constraints_guard_tool.filters` - Bộ lọc ràng buộc
- `search_and_rank_tool.topk` - Recipes đã xếp hạng (fallback)

#### Output (Environment Writes)

**Key:** `plan_day_e2e_tool.plan`

```python
{
    "name": "plan",
    "objects": [{
        "plan_id": str,          # UUID của plan
        "plan_type": "day",
        "user_id": str,
        "date": str,             # YYYY-MM-DD
        "created_at": str,       # ISO timestamp
        
        # Bữa sáng
        "breakfast": {
            "recipe": {
                "food_id": str,
                "dish_name": str,
                "image_link": str,
                "macros_per_serving": {...},
                "ingredients_with_qty": list[str],
                # ...
            },
            "servings": float,
            "macros": {
                "kcal": float,
                "protein_g": float,
                "fat_g": float,
                "carb_g": float
            },
            "accompaniments": []  # Chỉ có cho lunch/dinner
        },
        
        # Bữa trưa
        "lunch": {
            "recipe": {...},             # Món chính
            "servings": float,
            "macros": {...},
            "carb_dish": {               # Món nguồn tinh bột (cơm/bún/phở)
                "recipe": {...},
                "servings": float,
                "base_kcal": float
            },
            "accompaniments": [          # Món phụ (canh, rau, trái cây)
                {
                    "recipe": {...},
                    "servings": float,
                    "accompaniment_type": str  # "soup"/"vegetable"/"fruit"
                }
            ],
            "macros_total": {...}        # Tổng macros bữa ăn
        },
        
        # Bữa tối (cấu trúc tương tự lunch)
        "dinner": {...},
        
        # Tổng kết ngày
        "total_macros": {
            "kcal": float,
            "protein_g": float,
            "fat_g": float,
            "carb_g": float
        },
        "targets": {...},                # Mục tiêu macros
        "macro_adherence": {             # Độ tuân thủ macros (%)
            "kcal": float,
            "protein_g": float,
            "fat_g": float,
            "carb_g": float
        }
    }],
    "metadata": {
        "valid": bool,
        "plan_id": str,
        "user_id": str,
        "date": str,
    },
    "payload_type": "meal_plan",
    "display": True
}
```

**Key:** `plan_day_e2e_tool.missing_macros`

```python
{
    "name": "missing_macros",
    "objects": [{
        "recipe_ids": list[str]  # Danh sách recipe ID thiếu macros
    }],
}
```

---

### 3.2 plan_week_e2e_tool

**Mô tả:** Bộ lập kế hoạch End-to-end tuần: tạo kế hoạch 21 bữa (7 ngày × 3 bữa).

**File:** `MealAgent/tools/plan_week/plan_week_e2e.py`

#### Input Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `tree_data` | `TreeData` | ✅ | - | Elysia tree data context |
| `client_manager` | `ClientManager` | ✅ | - | Weaviate client manager |
| `base_lm` | `any` | ❌ | `None` | Base language model |
| `query_text` | `str` | ❌ | `""` | Truy vấn/yêu cầu |
| `start_date` | `str \| None` | ❌ | `None` | Ngày bắt đầu |
| `macro_tolerance_percent` | `float` | ❌ | `0.15` | Dung sai macro (±15%) |
| `min_variety_score` | `float` | ❌ | `50.0` | Điểm đa dạng tối thiểu |
| `user_id` | `str \| None` | ❌ | `None` | ID người dùng |
| `plan_id` | `str \| None` | ❌ | `None` | ID kế hoạch |
| `recent_plan_window_minutes` | `int` | ❌ | `10080` | Cửa sổ tránh lặp (7 ngày) |

#### Environment Reads

- `macro_calc_tool.targets` - Mục tiêu macros (×7 cho tuần)
- `constraints_guard_tool.filters` - Bộ lọc ràng buộc
- `search_and_rank_tool.topk` - Recipes đã xếp hạng

#### Output (Environment Writes)

**Key:** `plan_week_e2e_tool.plan`

```python
{
    "name": "plan",
    "objects": [{
        "plan_id": str,
        "plan_type": "week",
        "user_id": str,
        "start_date": str,
        "end_date": str,
        "created_at": str,
        
        "days": [
            {
                "day_index": int,        # 0-6
                "date": str,             # YYYY-MM-DD
                "breakfast": {...},      # Tương tự plan_day
                "lunch": {...},
                "dinner": {...},
                "total_macros": {...}
            },
            # ... 7 ngày
        ],
        
        "weekly_totals": {
            "kcal": float,
            "protein_g": float,
            "fat_g": float,
            "carb_g": float
        },
        "variety_score": float,          # Điểm đa dạng (0-100)
        "targets": {...},
    }],
    "metadata": {
        "valid": bool,
        "plan_id": str,
        "variety_score": float,
    },
    "payload_type": "meal_plan",
    "display": True
}
```

---

### 3.3 swap_meal_item_tool

**Mô tả:** Thay đổi món ăn (main hoặc carb) trong kế hoạch và tính toán lại macros.

**File:** `MealAgent/tools/plan_day/swap_meal_item.py`

#### Input Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `tree_data` | `TreeData` | ✅ | - | Elysia tree data context |
| `client_manager` | `ClientManager` | ✅ | - | Weaviate client manager |
| `plan_id` | `str` | ✅ | - | ID kế hoạch cần sửa |
| `meal_type` | `str` | ✅ | - | Loại bữa: `"breakfast"`, `"lunch"`, `"dinner"` |
| `item_type` | `str` | ✅ | - | Loại món: `"main"` hoặc `"carb"` |
| `new_recipe_id` | `str` | ✅ | - | ID công thức mới |
| `user_id` | `str \| None` | ❌ | `None` | ID người dùng (để validate) |

#### Output (Environment Writes)

**Key:** `swap_meal_item_tool.updated_plan`

```python
{
    "name": "updated_plan",
    "objects": [{...}],  # Kế hoạch đã cập nhật (cấu trúc như plan_day)
    "metadata": {
        "plan_id": str,
        "meal_type": str,
        "item_type": str,
        "new_recipe_id": str,
    },
    "payload_type": "meal_plan",
    "display": True
}
```

---

## 4. Nutrition Tools

### 4.1 calculate_recipe_macros_tool

**Mô tả:** Dịch nguyên liệu từ Vietnamese sang English, map với FDC foods, và tính toán macros per serving.

**File:** `MealAgent/tools/nutrition/calculate_recipe_macros.py`

#### Input Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `tree_data` | `TreeData` | ✅ | - | Elysia tree data context |
| `client_manager` | `ClientManager` | ✅ | - | Weaviate client manager |
| `base_lm` | `any` | ✅ | - | Language model cho VN→EN translation |
| `recipe_id` | `str \| None` | ❌ | `None` | ID công thức trong Weaviate |
| `recipe` | `Dict \| None` | ❌ | `None` | Payload công thức trực tiếp |
| `force_recalculate` | `bool` | ❌ | `False` | Bắt buộc tính lại dù đã có cache |

#### Output (Environment Writes)

**Key:** `calculate_recipe_macros_tool.macros`

```python
{
    "name": "macros",
    "objects": [{
        "kcal": float,
        "protein_g": float,
        "fat_g": float,
        "carb_g": float
    }],
    "metadata": {
        "source": str,       # "cached" hoặc "calculated"
        "recipe_id": str,
        "fdc_match_count": int,
        "fallback_used": bool
    },
    "payload_type": "generic",
    "display": True
}
```

**Key:** `calculate_recipe_macros_tool.success` / `.error`

```python
# Success
{
    "name": "success",
    "objects": [{
        "recipe_id": str,
        "macros": {...}
    }]
}

# Error
{
    "name": "error",
    "objects": [{
        "recipe_id": str,
        "reason": str,
        "missing_ingredients": list[str]
    }]
}
```

---

### 4.2 auto_calculate_macros_tool

**Mô tả:** Batch macro backfill orchestrator - tự động tính macros cho nhiều recipes cùng lúc.

**File:** `MealAgent/tools/nutrition/auto_calculate_macros.py`

#### Input Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `tree_data` | `TreeData` | ✅ | - | Elysia tree data context |
| `client_manager` | `ClientManager` | ✅ | - | Weaviate client manager |
| `base_lm` | `any` | ✅ | - | Language model (bắt buộc) |
| `max_recipes` | `int` | ❌ | `25` | Số recipes tối đa để xử lý |

#### Environment Reads

- `search_and_rank_tool.topk` - Recipes đã ranked
- `plan_day_e2e_tool.missing_macros` - Recipe IDs thiếu macros
- `plan_week_e2e_tool.missing_macros` - Recipe IDs thiếu macros

#### Output (Environment Writes)

**Key:** `auto_calculate_macros_tool.summary`

```python
{
    "name": "summary",
    "objects": [{
        "total_attempted": int,
        "successes": int,
        "failures": list[str],  # Recipe IDs thất bại
    }]
}
```

**Key:** `auto_calculate_macros_tool.resolved`

```python
{
    "name": "resolved",
    "objects": [{
        "recipe_ids": list[str]  # Recipe IDs đã tính xong
    }]
}
```

---

### 4.3 micros_tool

**Mô tả:** Phân tích micronutrients (vitamins & minerals), phát hiện thiếu hụt và đề xuất thực phẩm bổ sung.

**File:** `MealAgent/tools/micros/micros.py`

#### Input Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `tree_data` | `TreeData` | ✅ | - | Elysia tree data context |
| `client_manager` | `ClientManager` | ✅ | - | Weaviate client manager |
| `rda_overrides` | `Dict[str, float] \| None` | ❌ | `None` | Override RDA values |
| `top_k` | `int` | ❌ | `10` | Số gợi ý thực phẩm mỗi nutrient |
| `plan_id` | `str \| None` | ❌ | `None` | ID kế hoạch cụ thể |
| `user_id` | `str \| None` | ❌ | `None` | ID người dùng |

**RDA mặc định:**
```python
DEFAULT_RDAs = {
    "calcium_mg": 1000.0,
    "iron_mg": 18.0,
    "potassium_mg": 2600.0,
    "vitamin_c_mg": 90.0,
    "vitamin_a_rae_ug": 900.0,
}
```

#### Output (Environment Writes)

**Key:** `micros_tool.totals`

```python
{
    "name": "totals",
    "objects": [{
        "plan_totals": {
            "calcium_mg": float,
            "iron_mg": float,
            "potassium_mg": float,
            "vitamin_c_mg": float,
            "vitamin_a_rae_ug": float
        },
        "rda_targets": {...},
        "deficits": {
            "calcium_mg": float,  # Số âm = thiếu
            "iron_mg": float,
            # ...
        },
        "has_deficits": bool,
        "deficient_nutrients": list[str]
    }],
    "metadata": {...}
}
```

**Key:** `micros_tool.suggestions`

```python
{
    "name": "suggestions",
    "objects": [
        {
            "nutrient": str,         # Tên nutrient thiếu
            "deficit": float,        # Số lượng thiếu
            "foods": [
                {
                    "food_name": str,
                    "fdc_id": int,
                    "per_100g": float,
                    "suggested_amount_g": float
                }
            ]
        }
    ],
    "payload_type": "table"
}
```

---

## 5. Optimization Tools

### 5.1 gap_fill_tool

**Mô tả:** Phân tích thiếu hụt macro và đề xuất snacks để bổ sung.

**File:** `MealAgent/tools/gap_fill/gap_fill.py`

#### Input Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `tree_data` | `TreeData` | ✅ | - | Elysia tree data context |
| `client_manager` | `ClientManager` | ✅ | - | Weaviate client manager |
| `auto_apply` | `bool` | ❌ | `False` | Tự động áp dụng snack tốt nhất |
| `top_k` | `int` | ❌ | `5` | Số gợi ý snack |
| `user_id` | `str \| None` | ❌ | `None` | ID người dùng |
| `plan_id` | `str \| None` | ❌ | `None` | ID kế hoạch |

#### Environment Reads

- `plan_day_e2e_tool.plan` / `plan_week_e2e_tool.plan`
- `macro_calc_tool.targets`

#### Output (Environment Writes)

**Key:** `gap_fill_tool.deficits`

```python
{
    "name": "deficits",
    "objects": [{
        "plan_totals": {
            "kcal": float,
            "protein_g": float,
            "fat_g": float,
            "carb_g": float
        },
        "targets": {...},
        "deficits": {
            "kcal": float,
            "protein_g": float,
            "fat_g": float,
            "carb_g": float
        },
        "has_deficits": bool
    }]
}
```

**Key:** `gap_fill_tool.suggestions`

```python
{
    "name": "suggestions",
    "objects": [
        {
            "food_id": str,
            "dish_name": str,
            "macros_per_serving": {...},
            "fit_score": float,      # Điểm phù hợp (0-100)
            "image_link": str
        }
    ],
    "payload_type": "recipe"
}
```

**Key:** `gap_fill_tool.updated_plan` (khi `auto_apply=True`)

```python
{
    "name": "updated_plan",
    "objects": [{...}],  # Plan đã có snack
    "payload_type": "meal_plan"
}
```

---

### 5.2 substitute_tool

**Mô tả:** Thay thế toàn bộ món ăn trong plan bằng món chứa nguyên liệu mong muốn.

**File:** `MealAgent/tools/substitution/substitute.py`

#### Input Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `tree_data` | `TreeData` | ✅ | - | Elysia tree data context |
| `client_manager` | `ClientManager` | ✅ | - | Weaviate client manager |
| `ingredient_name` | `str` | ❌ | `""` | Nguyên liệu mong muốn trong món mới (vd: "thịt bò") |
| `fdc_id` | `int \| None` | ❌ | `None` | FDC ID nguyên liệu cần thay |
| `substitute_fdc_id` | `int \| None` | ❌ | `None` | FDC ID thay thế (áp dụng trực tiếp) |
| `tolerance` | `float` | ❌ | `0.2` | Dung sai macro (±20%) |
| `top_k` | `int` | ❌ | `10` | Số gợi ý thay thế |
| `auto_apply` | `bool` | ❌ | `False` | Tự động áp dụng |
| `recalculate_macros` | `bool` | ❌ | `True` | Tính lại macros |
| `user_id` | `str \| None` | ❌ | `None` | ID người dùng |
| `plan_id` | `str \| None` | ❌ | `None` | ID kế hoạch |
| `base_lm` | `any` | ❌ | `None` | LM cho macro recalculation |
| `recipe_level` | `bool` | ❌ | `False` | Thay toàn bộ recipe (luôn True) |
| `original_dish_name` | `str \| None` | ❌ | `None` | Tên món cần thay (vd: "bún thang") |

#### Output (Environment Writes)

**Key:** `substitute_tool.updated_plan`

```python
{
    "name": "updated_plan",
    "objects": [{...}],  # Plan đã được thay thế
    "metadata": {
        "replaced_dishes": list[str],
        "new_dishes": list[str],
        "macro_change": {...}
    },
    "payload_type": "meal_plan",
    "display": True
}
```

**Key:** `substitute_tool.suggestions` (khi `auto_apply=False`)

```python
{
    "name": "suggestions",
    "objects": [
        {
            "dish_name": str,
            "food_id": str,
            "match_score": float,    # Điểm macro match (0-100)
            "macros_per_serving": {...},
            "contains_ingredient": str
        }
    ],
    "payload_type": "recipe"
}
```

---

## 6. Meal Logging Tools

### 6.1 log_meal_e2e_tool

**Mô tả:** Luồng E2E log bữa ăn: LLM parsing → FDC validation → nutrition calc → persistence.

**File:** `MealAgent/tools/meal_logging/log_meal_e2e.py`

#### Input Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `tree_data` | `TreeData` | ✅ | - | Elysia tree data context |
| `client_manager` | `ClientManager` | ✅ | - | Weaviate client manager |
| `base_lm` | `any` | ✅ | - | Language model cho parsing |
| `user_id` | `str` | ✅ | - | ID người dùng |
| `meal_description` | `str` | ❌ | `""` | Mô tả bữa ăn (vd: "Phở bò") |
| `plan_id` | `str` | ❌ | `""` | ID plan để log toàn bộ |
| `user_accepted` | `bool` | ❌ | `False` | User đã xác nhận chấp nhận plan |

#### Environment Reads

- `profile_crud_tool.profile`
- `plan_day_e2e_tool.plan` (fallback khi không có plan_id)

#### Output (Environment Writes)

**Key:** `log_meal_e2e_tool.updated_profile`

```python
{
    "name": "updated_profile",
    "objects": [{
        "user_id": str,
        "logged_at": str,
        "meal_description": str,
        "calculated_macros": {
            "kcal": float,
            "protein_g": float,
            "fat_g": float,
            "carb_g": float
        },
        "remaining_targets": {
            "kcal": float,
            "protein_g": float,
            "fat_g": float,
            "carb_g": float
        },
        "consumed_today": {
            "kcal": float,
            "protein_g": float,
            "fat_g": float,
            "carb_g": float
        }
    }],
    "metadata": {
        "log_count": int,
        "source": str  # "description" hoặc "plan"
    },
    "payload_type": "meal_history"
}
```

---

### 6.2 accept_plan_tool

**Mô tả:** Chấp nhận kế hoạch và persist vào MealLogEntry.

**File:** `MealAgent/tools/meal_logging/accept_plan.py`

#### Input Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `tree_data` | `TreeData` | ✅ | - | Elysia tree data context |
| `client_manager` | `ClientManager` | ✅ | - | Weaviate client manager |
| `plan_id` | `str` | ✅ | - | ID kế hoạch cần accept |
| `user_id` | `str` | ❌ | `""` | ID người dùng |

#### Output (Environment Writes)

**Key:** `accept_plan_tool.plan_accepted`

```python
{
    "name": "plan_accepted",
    "objects": [{
        "plan_id": str,
        "user_id": str,
        "logged_meals": [
            {
                "meal_type": str,
                "dish_name": str,
                "macros": {...},
                "logged_at": str
            }
        ]
    }],
    "metadata": {
        "plan_id": str,
        "logged_count": int
    },
    "payload_type": "meal_history",
    "display": True
}
```

---

### 6.3 meal_history_tool

**Mô tả:** Truy xuất lịch sử log bữa ăn với filter theo ngày.

**File:** `MealAgent/tools/meal_logging/meal_history.py`

#### Input Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `tree_data` | `TreeData` | ✅ | - | Elysia tree data context |
| `client_manager` | `ClientManager` | ✅ | - | Weaviate client manager |
| `user_id` | `str` | ❌ | `""` | ID người dùng |
| `start_date` | `str \| None` | ❌ | `None` | Ngày bắt đầu (YYYY-MM-DD) |
| `end_date` | `str \| None` | ❌ | `None` | Ngày kết thúc (YYYY-MM-DD) |
| `limit` | `int` | ❌ | `50` | Số kết quả tối đa |

#### Output (Environment Writes)

**Key:** `meal_history_tool.history`

```python
{
    "name": "history",
    "objects": [{
        "user_id": str,
        "logs": [
            {
                "meal_description": str,
                "logged_at": str,
                "calculated_macros": {...},
                "ingredients": list,
            }
        ],
        "daily_totals": {
            "2024-01-15": {
                "kcal": float,
                "protein_g": float,
                "fat_g": float,
                "carb_g": float
            },
            # ... các ngày khác
        },
        "total_logs": int,
        "date_range": {
            "start": str,
            "end": str
        }
    }],
    "metadata": {
        "user_id": str,
        "logs_count": int,
        "days_count": int
    },
    "payload_type": "meal_history",
    "display": True
}
```

---

## 7. Pantry & Shopping Tools

### 7.1 pantry_crud_tool

**Mô tả:** CRUD operations cho Pantry và PantryItem collections.

**File:** `MealAgent/tools/pantry/pantry_crud.py`

#### Input Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `tree_data` | `TreeData` | ✅ | - | Elysia tree data context |
| `client_manager` | `ClientManager` | ✅ | - | Weaviate client manager |
| `action` | `str` | ❌ | `"read"` | Hành động: `"read"`, `"create"`, `"update"`, `"delete"` |
| `user_id` | `str` | ❌ | `""` | ID người dùng (auto-detect từ profile nếu trống) |
| `pantry_items` | `List[Dict] \| None` | ❌ | `None` | Items cho create/update/delete |

**Cấu trúc `pantry_items`:**
```python
[
    {
        "ingredient_name": str,       # Required - Tên nguyên liệu
        "quantity": float,            # Required - Số lượng
        "unit": str,                  # Required - Đơn vị (g, kg, ml, quả, ...)
        "fdc_id": int,                # Optional - FDC ID
        "expiry_date": str,           # Optional - Ngày hết hạn (YYYY-MM-DD)
        "category": str,              # Optional - Danh mục
    }
]
```

#### Output (Environment Writes)

**Key:** `pantry_crud_tool.state`

```python
{
    "name": "state",
    "objects": [{
        "user_id": str,
        "pantry_id": str,
        "updated_at": str,
        "items_count": int
    }],
    "metadata": {
        "action": str,
        "user_id": str
    }
}
```

**Key:** `pantry_crud_tool.items`

```python
{
    "name": "items",
    "objects": [
        {
            "ingredient_name": str,
            "quantity": float,
            "unit": str,
            "fdc_id": int,
            "expiry_date": str,
            "added_at": str
        }
    ],
    "payload_type": "table",
    "display": True
}
```

---

### 7.2 pantry_diff_tool

**Mô tả:** Tạo danh sách mua sắm bằng cách trừ inventory hiện có khỏi nguyên liệu cần cho plan.

**File:** `MealAgent/tools/shopping/pantry_diff.py`

#### Input Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `tree_data` | `TreeData` | ✅ | - | Elysia tree data context |
| `client_manager` | `ClientManager` | ✅ | - | Weaviate client manager |
| `user_id` | `str` | ❌ | `""` | ID người dùng |

#### Environment Reads

- `plan_day_e2e_tool.plan` / `plan_week_e2e_tool.plan`
- `pantry_crud_tool.state`

#### Output (Environment Writes)

**Key:** `pantry_diff_tool.diff`

```python
{
    "name": "diff",
    "objects": [{
        "plan_ingredients": [
            {
                "ingredient_name": str,
                "quantity_needed": float,
                "unit": str
            }
        ],
        "pantry_items": [...],
        "matched_items": [...],
        "unmatched_items": [...]
    }]
}
```

**Key:** `pantry_diff_tool.shopping_list`

```python
{
    "name": "shopping_list",
    "objects": [{
        "final_items": [
            {
                "ingredient_name": str,
                "quantity": float,
                "unit": str,
                "display_quantity": str,  # Định dạng đẹp (vd: "2 quả", "500g")
                "fdc_id": int | None,
                "category": str | None
            }
        ],
        "total_items": int,
        "plan_id": str,
        "user_id": str,
        "generated_at": str
    }],
    "metadata": {
        "total_items": int,
        "pantry_matched": int,
        "need_to_buy": int
    },
    "payload_type": "shopping_list",
    "display": True
}
```

---

## 8. Cooking Tools

### 8.1 cook_mode_tool

**Mô tả:** Tạo hướng dẫn nấu ăn từng bước và stream cho người dùng.

**File:** `MealAgent/tools/cook_mode/cook_mode.py`

#### Input Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `tree_data` | `TreeData` | ✅ | - | Elysia tree data context |
| `client_manager` | `ClientManager` | ✅ | - | Weaviate client manager |
| `food_id` | `str \| None` | ❌ | `None` | ID công thức (tự động lấy từ plan/search nếu không có) |
| `base_lm` | `any` | ❌ | `None` | Language model |
| `polish` | `bool` | ❌ | `False` | Tinh chỉnh bước nấu |
| `stream_steps` | `bool` | ❌ | `False` | Stream từng bước |

#### Environment Reads

- `cook_mode_tool.completed` - Kiểm tra đã hoàn thành chưa
- `plan_day_e2e_tool.plan` / `plan_week_e2e_tool.plan`
- `search_and_rank_tool.topk`

#### Output (Environment Writes)

**Key:** `cook_mode_tool.steps`

```python
{
    "name": "steps",
    "objects": [{
        "food_id": str,
        "dish_name": str,
        "total_time": int,           # Tổng thời gian (phút)
        "servings": int,
        "steps": [
            {
                "step_number": int,
                "instruction": str,
                "estimated_seconds": int,
                "ingredients_used": list[str] | None,
                "tips": str | None
            }
        ]
    }],
    "metadata": {
        "food_id": str,
        "steps_count": int
    },
    "payload_type": "cooking_steps",
    "display": True
}
```

**Key:** `cook_mode_tool.completed`

```python
{
    "name": "completed",
    "objects": [{
        "food_id": str,
        "timestamp": str
    }],
    "metadata": {
        "task_complete": True,
        "stop_calling_tool": True,
        "end_conversation": True
    }
}
```

**Key:** `cook_mode_tool.final_summary`

```python
{
    "name": "final_summary",
    "objects": [{
        "title": str,        # Tên món ăn
        "text": str,         # Tóm tắt cách nấu
        "cooking_time": int, # Thời gian nấu
        "difficulty": str    # Độ khó
    }],
    "display": True
}
```

---

## Tổng Kết Luồng Dữ Liệu

```
┌─────────────────────┐
│   profile_crud_tool │────► profile_crud_tool.profile
└─────────────────────┘
           │
           ▼
┌─────────────────────┐
│   macro_calc_tool   │────► macro_calc_tool.targets
└─────────────────────┘
           │
           ▼
┌─────────────────────┐
│constraints_guard_tool│───► constraints_guard_tool.filters
└─────────────────────┘
           │
           ▼
┌─────────────────────┐
│ search_and_rank_tool│────► search_and_rank_tool.topk
└─────────────────────┘
           │
           ├──────────────────┬──────────────────┐
           ▼                  ▼                  ▼
┌─────────────────────┐ ┌─────────────────────┐ ┌──────────────────┐
│  plan_day_e2e_tool  │ │plan_week_e2e_tool   │ │calculate_recipe_ │
│                     │ │                     │ │   macros_tool    │
└─────────────────────┘ └─────────────────────┘ └──────────────────┘
           │                  │
           ▼                  ▼
    plan_day_e2e_tool.plan    plan_week_e2e_tool.plan
           │                  │
           ├──────────────────┤
           ▼                  ▼
┌─────────────────────┐ ┌─────────────────────┐
│    gap_fill_tool    │ │  substitute_tool    │
│                     │ │                     │
└─────────────────────┘ └─────────────────────┘
           │
           ▼
┌─────────────────────┐
│  accept_plan_tool   │────► Lưu vào MealLogEntry
│  log_meal_e2e_tool  │
└─────────────────────┘
           │
           ▼
┌─────────────────────┐
│  meal_history_tool  │────► Truy vấn lịch sử
└─────────────────────┘

┌─────────────────────┐      ┌─────────────────────┐
│  pantry_crud_tool   │◄────►│   pantry_diff_tool  │
│                     │      │   (shopping list)   │
└─────────────────────┘      └─────────────────────┘

┌─────────────────────┐
│   cook_mode_tool    │────► Hướng dẫn nấu ăn
└─────────────────────┘
```

---

## Ghi Chú Quan Trọng

1. **Source of Truth**: Weaviate database là nguồn dữ liệu chính. Environment cache chỉ dùng làm fallback.

2. **Macros Pre-calculated**: Planning tools (`plan_day_e2e_tool`, `plan_week_e2e_tool`) yêu cầu recipes phải có macros đã tính sẵn trong database. Sử dụng `calculate_recipe_macros_tool` cho recipes mới.

3. **User Acceptance Flow**: 
   - `accept_plan_tool` / `log_meal_e2e_tool` CHỈ được gọi khi user explicitly accept plan
   - KHÔNG tự động log sau khi tạo plan

4. **Task Completion Signals**: Khi tool emits `task_complete=True` với `end_conversation=True`, agent PHẢI kết thúc conversation branch.

5. **Auto-detection**: Nhiều tools hỗ trợ auto-detect `user_id` từ profile hoặc hidden_environment nếu không được cung cấp explicitly.
