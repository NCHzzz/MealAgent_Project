# Logic Fix: Read Recipes from Weaviate Database

## Vấn đề Phát hiện

Code hiện tại đọc recipes từ **environment cache** thay vì từ **Weaviate database**, dẫn đến:
- Dữ liệu có thể cũ (stale data)
- Không sync với database
- Vi phạm nguyên tắc: Database là source of truth

## Phân tích Logic Cũ

### Logic Cũ (SAI):
```python
# Step 1: Đọc từ environment cache (có thể cũ)
sr = tree_data.environment.find("search_and_rank_tool", "topk")
recipes = []
if sr:
    recipes = sr[0]["objects"]  # Dùng cached data

# Step 2: Chỉ search từ Weaviate nếu không có trong cache
if not recipes:
    # Mới search từ Weaviate
    async for result in search_and_rank_tool(...):
        recipes = result.objects
```

**Vấn đề:**
- Ưu tiên cache (có thể cũ) thay vì database (luôn mới)
- Chỉ search từ Weaviate khi cache trống
- Không đảm bảo data freshness

## Logic Mới (ĐÚNG)

### Logic Mới:
```python
# Step 1: LUÔN search từ Weaviate database (source of truth)
yield Response("🔍 Searching recipes from database...")
async for result in search_and_rank_tool(...):
    recipes = result.objects  # Lấy từ Weaviate

# Step 2: Fallback về cache chỉ khi database search fails
if not recipes:
    # Fallback: try environment cache
    sr = tree_data.environment.find("search_and_rank_tool", "topk")
    if sr:
        recipes = sr[0]["objects"]  # Dùng cache như fallback
```

**Ưu điểm:**
- ✅ Luôn đọc từ Weaviate (source of truth)
- ✅ Đảm bảo data freshness
- ✅ Cache chỉ là fallback, không phải primary source
- ✅ Đúng với flow design: "Map & Search Recipe" = search từ database

## Thay đổi Code

### File: `MealAgent/tools/plan_day/plan_day_e2e.py`

**Trước:**
- Đọc từ environment cache trước
- Chỉ search từ Weaviate nếu cache trống

**Sau:**
- Luôn gọi `search_and_rank_tool()` để search từ Weaviate
- Environment cache chỉ là fallback khi database search fails
- Thêm logging để rõ ràng về nguồn dữ liệu

### Changes:
1. **Line 540-645**: Refactor logic để luôn search từ Weaviate trước
2. **Line 445-459**: Update docstring để phản ánh behavior mới
3. **Comments**: Thêm comments giải thích tại sao luôn search từ database

## Cập nhật Documentation

### File: `docs/ai/design/meal_planning_flow.md`

**Section 2) Map & Search Recipe:**
- Thêm note: "IMPORTANT: Always search recipes from Weaviate database"
- Giải thích: Weaviate là source of truth
- Environment cache chỉ là fallback

## Test Updates

### File: `tests/meal_agent/integration/test_meal_planning_flow_comprehensive.py`

**Changes:**
- Tất cả tests giờ mock `search_and_rank_tool` để simulate Weaviate search
- Tests verify rằng code gọi `search_and_rank_tool()` (đọc từ Weaviate)
- Tests không còn expect recipes từ environment cache

**Test Results:**
- ✅ 8/8 comprehensive tests passing
- ✅ 59/59 total tests passing

## Rationale

### Tại sao phải đọc từ Weaviate?

1. **Data Freshness**: Database luôn có data mới nhất
2. **Consistency**: Đảm bảo sync với database
3. **Correctness**: Theo đúng flow design - "Map & Search Recipe" = search từ database
4. **Reliability**: Không phụ thuộc vào cache có thể không tồn tại

### Khi nào dùng Environment Cache?

- **Chỉ khi**: Database search fails hoàn toàn
- **Mục đích**: Fallback để không fail hoàn toàn
- **Warning**: Phải cảnh báo user rằng đang dùng cached data

## Impact

### Positive:
- ✅ Data luôn fresh từ database
- ✅ Đúng với flow design
- ✅ Code rõ ràng hơn về nguồn dữ liệu

### Considerations:
- ⚠️ Có thể chậm hơn một chút (phải query database)
- ✅ Nhưng đảm bảo correctness quan trọng hơn performance ở đây
- ✅ `search_and_rank_tool` đã được optimize với caching internally

## Verification

### Tests Verify:
1. ✅ Code gọi `search_and_rank_tool()` (đọc từ Weaviate)
2. ✅ Plan được tạo với recipes từ database
3. ✅ Macros được tính đúng từ latest data
4. ✅ Fallback hoạt động khi database search fails

### Manual Verification:
- Code luôn gọi `search_and_rank_tool()` trước
- Environment cache chỉ được dùng khi database search fails
- Logging rõ ràng về nguồn dữ liệu

---

**Date**: 2024  
**Status**: ✅ Fixed and Tested  
**Tests**: 59/59 passing


