# Daily Meal Planning Flow (LLM + Rule-Based + Scaling)

## Mục tiêu
- Kết hợp LLM để chọn khung món đa dạng, nhưng mọi tính toán dinh dưỡng dựa trên dữ liệu Recipe (macros_per_serving).
- Đảm bảo phù hợp khẩu vị Việt Nam (bữa sáng nhẹ, trưa/tối cơm hoặc món nước + món mặn + rau + trái cây).
- Giữ tổng macro gần mục tiêu, hỗ trợ swap và giảm latency.

## Các bước

### 0) Chuẩn bị
- Nạp Profile & Targets (`macro_calc_tool`).
- Đọc meal_history gần (10 - 20 món) để tránh trùng.
- Nạp constraints/allergens/diet nếu có.
- Xác định mục tiêu theo bữa (kcal/P/F/C), ví dụ chia 3 hoặc tỉ lệ breakfast:lunch:dinner.

### 1) LLM Draft (khung món, không ước lượng kcal)
- Prompt LLM trả 2–3 gợi ý/slot (breakfast, lunch: carb/main/veg/fruit, dinner: carb/main/veg/fruit).
- Mỗi gợi ý gồm: `dish_name`, `general_term` (tên chuẩn hóa), `role` (carb/main/vegetable/fruit/breakfast), `meal_type`, `category` (rice/noodle/soup/bread/bakery), `note`.
- Ràng buộc: tránh trùng meal_history, tuân thủ allergen/diet, khẩu vị VN (sáng: bánh mì/xôi/phở/mì/bánh ngọt nhẹ; trưa/tối: cơm hoặc món nước + main + rau + trái cây; cho phép pizza/beefsteak nếu không cấm). Cấm ước lượng kcal.
- Output JSON, validate schema (Pydantic/Zod).

### 2) Map & Search Recipe (hybrid + fallback)
- Với mỗi gợi ý: vector search Recipe; nếu rỗng/score thấp, search bằng `general_term`; fallback BM25 nếu cần.
- Dùng hybrid (vector 0.7, keyword 0.3) và threshold (vd 0.6); dưới ngưỡng coi như không tìm thấy → fallback rule-based.
- Ưu tiên recipe có macros_per_serving đầy đủ. Nếu `role` LLM khác tag DB, ưu tiên tag DB và log “role corrected”.
- Lấy top 1–3 recipe/slot.

### 3) Assemble & Portion Scaling (rule-based)
- Chọn theo thứ tự: Main (protein) → Carb (rice/noodle; fallback noodle/soup) → Veg → Fruit.
- Scaling:
  - Main (protein dish): `scale = target_protein_slot / recipe_protein`; giới hạn 0.5–1.5; nếu vượt, thử main khác.
  - Carb: sau khi chốt main, `scale = kcal_missing_slot / recipe_kcal`; giới hạn 0.5–2.0; nếu vượt, chọn carb khác.
  - Veg/Fruit: giữ serving chuẩn (hoặc min(1.0, kcal_missing/200)) để tránh quá tải.
- Meal macros = sum(main_scaled + carb_scaled + veg/fruit). Day macros = sum meal macros.
- Iterative adjust: nếu lệch lớn, thử 1–2 hoán đổi main/carb để giảm lệch.

### 4) Validation
- So sánh với targets ± tolerance; nếu vi phạm, gắn cảnh báo (validation.macro_validation).
- Nếu thiếu slot do search fail, fallback món mặc định (cơm/rau/trái cây) để không trả bữa trống.

### 5) LLM Critic (tùy chọn, async)
- Gửi plan (tên + macros thực tế) + targets cho LLM nhận xét ngắn, không cho LLM sửa số.
- Nếu cảnh báo (lệch >20% kcal hoặc P/F/C), hiển thị badge hoặc gợi ý swap. Chạy nền, không chặn response.

### 6) Response → Frontend
- Trả plan với:
  - `macros_main` (món chính đã scale),
  - `macros_total` (cả bữa, gồm accompaniments),
  - accompaniments kèm `macros` và `servings_scaled`,
  - `total_macros` ngày, `validation`, (tùy chọn) critic note.
- Stream sớm draft (tên món); cập nhật macros sau khi map/scale xong.

### 7) Accept / Swap
- FE hiển thị macros_main cho món chính, macros_total cho bữa; badge cảnh báo nếu có.
- Nút Accept → log/lưu MealPlan/MealPlanItem + meal_history.
- Swap: khi user đổi main/carb, BE chạy lại Assemble cho slot (scale lại main/carb, giữ/điều chỉnh veg/fruit) và tính lại macros slot + day.

## Ghi chú triển khai nhanh
- Prompt Draft: bắt buộc `general_term`, `role`, `meal_type`, `category`; cấm kcal; tránh trùng meal_history; khẩu vị VN theo slot.
- Search: hybrid (vector 0.7, keyword 0.3), threshold 0.6, fallback `general_term`/BM25, log miss.
- Assemble: protein-scaling cho main, kcal-scaling cho carb, veg/fruit cố định; iterative adjust tối đa 1–2 lần.
- Critic: async, không chặn.***

