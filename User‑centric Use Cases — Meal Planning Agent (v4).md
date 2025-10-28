# **User‑Centric Use Cases — Meal Planning Agent (v4)**

Tài liệu mô tả use case theo góc nhìn người dùng (user‑centric), kèm Input/Output minh hoạ để dùng trình bày cho khách hàng. Mỗi UC có: Mục tiêu, Tác nhân, Tiền điều kiện, Kích hoạt, Luồng chính, Input, Output, Tiêu chí thành công, Ngoại lệ & ví dụ.

---

## **UC1 — Create/Update Profile & Compute Targets**

**Mục tiêu:** Người dùng tạo/cập nhật hồ sơ và nhận mục tiêu dinh dưỡng (macro target) tự động.

**Tác nhân:** Người dùng cuối.

**Tiền điều kiện:** Không.

**Kích hoạt:** Người dùng mở **Hồ sơ** và bấm **Tạo/Cập nhật**.

**Luồng chính:**

1. Nhập thông tin (tên, tuổi, giới tính, chiều cao, cân nặng, mức vận động, mục tiêu, diet, dị ứng…).

2. Nếu người dùng **chưa có macro target**, ấn **Tính Macro** → hệ thống chạy MacroCalcTool.

3. Hiển thị **NutrientTarget** (kcal, P/C/F); cho phép chỉnh nhẹ nếu muốn.

4. **Lưu** hồ sơ.

**User query (ví dụ, ngôn ngữ tự nhiên):**

* “Mình là **Minh Anh**, nữ 28 tuổi, cao **160cm**, nặng **55kg**, vận động **nhẹ**; mục tiêu **giảm mỡ**; ăn **pescetarian** và **dị ứng đậu phộng**. **Tính macro** và **lưu hồ sơ** giúp mình.”

* “**Cập nhật** cân nặng của mình lên **56kg** và **tính lại macro** nhé.”

**Output (ví dụ trên UI/API):**

* Thẻ **Mục tiêu ngày**: kcal≈1750, protein≈120g, carbs≈180g, fat≈55g.

* Thông báo: “Đã lưu hồ sơ và mục tiêu dinh dưỡng”.

**Tiêu chí thành công:** Có bản ghi UserProfile \+ NutrientTarget; màn hình xác nhận rõ ràng.

**Ngoại lệ:** Thiếu/giá trị không hợp lệ (vd. chiều cao \< 100\) → form highlight lỗi, hướng dẫn sửa.

---

## **UC2 — Daily Plan (khi người dùng không nhập macro)**

**Mục tiêu:** Tự động lập thực đơn 1 ngày (3 bữa), tôn trọng ràng buộc cá nhân.

**Tác nhân:** Người dùng cuối.

**Tiền điều kiện:** Có UserProfile; macro có thể được tính tự động.

**Kích hoạt:** Người dùng bấm **Lập kế hoạch ngày**.

**Luồng chính:**

1. Hệ thống (nếu cần) chạy **MacroCalcTool** để có target.

2. **Tìm món**: lọc theo diet/allergens; có thể thêm time\_max (tối đa thời gian nấu/bữa).

3. **Diet/Allergen Guard**: loại món vi phạm.

4. **PlanAssembleTool**: ghép 3 bữa đạt ±10% mục tiêu.

5. **Hiển thị**: tổng kcal/P/C/F, phân rã từng bữa, nguồn tham chiếu.

6. Người dùng **Chấp nhận** hoặc **Tạo lại**.

**Input (ví dụ):**

* time\_max: 30 phút/bữa, diet: pescetarian, allergens: peanut. **User query (ví dụ, ngôn ngữ tự nhiên):**

* “**Lên thực đơn 1 ngày** (3 bữa) theo **mục tiêu của mình**, mỗi bữa **≤30 phút**, **không đậu phộng**.”

* “Hôm nay mình **bận**, đề xuất kế hoạch **nhanh gọn ≤20′** giúp mình.”

**Output (ví dụ):**

* Kế hoạch 3 bữa với tổng kcal≈1750 (±10%), Protein ≈120g, Carbs ≈180g, Fat ≈55g.

* Nút **Chấp nhận** (persist \+ cập nhật Exposure) / **Tạo lại** (học sở thích, loại món trùng/lặp).

**Tiêu chí thành công:** Kế hoạch hợp lệ (đúng ràng buộc) và đạt mục tiêu ngày trong dải sai số.

**Ngoại lệ:** Không đủ món để đạt mục tiêu với time\_max quá chặt → hệ thống gợi ý nới điều kiện.

---

## **UC3 — Weekly Plan \+ Meal‑prep**

**Mục tiêu:** Lập kế hoạch 7 ngày, ưu tiên dùng chung nguyên liệu để tiết kiệm thời gian & chi phí.

**Tác nhân:** Người dùng cuối.

**Tiền điều kiện:** Có UserProfile \+ NutrientTarget.

**Kích hoạt:** Người dùng bấm **Lập kế hoạch tuần**.

**Luồng chính:**

1. Tạo kế hoạch như UC3 nhưng **×7 ngày**.

2. Share\_ingredients=true để ưu tiên món chung nguyên liệu (hỗ trợ meal‑prep).

3. Tính **ngân sách** tổng; nếu vượt, hệ thống chọn món rẻ hơn tương đương macro.

4. Xuất **Shopping List** (CSV/XLSX), gợi ý batch‑cook.

5. **Chấp nhận/Tạo lại** tương tự UC3.

**Input (ví dụ):**

* Tuần bắt đầu: 15/09; Budget: 700.000₫; share\_ingredients: true. **User query (ví dụ, ngôn ngữ tự nhiên):**

* “**Lên kế hoạch 7 ngày** từ **15/09**, **ưu tiên dùng chung nguyên liệu** để meal‑prep, **ngân sách tối đa 700k**, và **xuất shopping list**.”

**Output (ví dụ):**

* Lịch tuần, tổng chi dự kiến (± biên độ), file **ShoppingList.xlsx** tải về.

**Tiêu chí thành công:** Kế hoạch 7 ngày hợp lệ; danh sách mua sắm rõ ràng; ngân sách trong hạn mức (nếu được yêu cầu).

**Ngoại lệ:** Budget quá thấp → gợi ý điều chỉnh (đổi nguyên liệu/ưu tiên món rẻ/giảm món đắt).

---

## **UC4 — Fill Macro Gap (Bù thiếu trong ngày)**

**Mục tiêu:** Bổ sung món/snack để lấp khoảng thiếu macro từ MealLog trong ngày.

**Tác nhân:** Người dùng cuối.

**Tiền điều kiện:** Có MealLog trong ngày (đã ăn gì).

**Kích hoạt:** Người dùng mở **Bù thiếu**.

**Luồng chính:**

1. **Aggregate** tính chênh target − consumed.

2. **Tìm món bù** phù hợp (có thể thêm time\_max, thiết bị sẵn có).

3. **Guard** diet/allergens.

4. Gợi ý 3–5 lựa chọn, kèm macro & thời gian ước tính.

**Input (ví dụ):**

* Gap: \+22g protein, \+30g carbs, \+10g fat; time\_max: 10 phút. **User query (ví dụ, ngôn ngữ tự nhiên):**

* “Hôm nay mình còn **thiếu \~22g protein, 30g carbs, 10g fat**. Gợi ý **snack trong 10 phút** nhé.”

* “Mình còn **thiếu \~250 kcal**, có món nào **nhanh** không?”

**Output (ví dụ):**

* Danh sách snack: “Sữa chua Hy Lạp \+ trái cây”, “Bánh mì trứng \+ phô mai”… với macro từng món.

**Tiêu chí thành công:** Người dùng chọn được món bù làm gap → 0 ± cho phép.

**Ngoại lệ:** Gap quá nhỏ/không đáng kể → gợi ý bỏ qua hoặc điều chỉnh ngày hôm sau.

---

## **UC5 — Time Constraint (Ràng buộc thời gian)**

**Mục tiêu:** Tạo kế hoạch/phần gợi ý tôn trọng ràng buộc thời gian nấu/chuẩn bị.

**Tác nhân:** Người dùng cuối.

**Tiền điều kiện:** Có hồ sơ/diet/allergens.

**Kích hoạt:** Người dùng nhập **Tối đa X phút/bữa** trước khi tạo kế hoạch/gợi ý món.

**Luồng chính:**

1. Lọc món theo time\_max →

2. Lập kế hoạch như UC3/UC4 nhưng chỉ dùng món thỏa thời gian.

**Input (ví dụ):** time\_max \= 20 phút, thiết bị: “Air Fryer”. **User query (ví dụ, ngôn ngữ tự nhiên):**

* “Mình **chỉ có 20 phút/bữa** và có **Air Fryer**; hãy lên plan **phù hợp** nhé.”

**Output (ví dụ):** Kế hoạch/ngân sách như thường, nhưng tất cả món ≤20′, ưu tiên thiết bị có.

**Tiêu chí thành công:** 100% món trong kế hoạch đạt ràng buộc thời gian.

**Ngoại lệ:** Không đủ món → đề xuất nới thời gian \+5–10′ hoặc đổi thiết bị/loại món.

---

## **UC6 — Family / Multi‑profile**

**Mục tiêu:** Lập kế hoạch cho nhiều thành viên, hợp nhất ràng buộc và chia khẩu phần từng người.

**Tác nhân:** Chủ hộ gia đình / Người dùng cuối.

**Tiền điều kiện:** Có ≥2 UserProfile.

**Kích hoạt:** Người dùng chọn **Kế hoạch gia đình** và add thành viên.

**Luồng chính:**

1. Hợp nhất ràng buộc (diet/allergens/targets/servings).

2. **PlanAssemble** tạo thực đơn chung, kèm **khẩu phần riêng** theo mỗi người.

3. Xuất shopping list gộp, ghi chú khẩu phần.

**Input (ví dụ):**

* Thành viên A (adult), B (teen), C (child); B dị ứng hải sản; C cần cao năng lượng. **User query (ví dụ, ngôn ngữ tự nhiên):**

* “**Lập thực đơn gia đình** 3 người: **A (nữ 30\)**, **B (nam 32\)**, **C (8 tuổi)**; **B dị ứng hải sản**; **chia khẩu phần** từng người giúp mình.”

**Output (ví dụ):**

* Thực đơn gia đình, mỗi món hiển thị “A: 1 khẩu phần, B: 0.8, C: 0.6”; shopping list tổng.

**Tiêu chí thành công:** Không vi phạm dị ứng của bất kỳ ai; tổng macro tiệm cận mục tiêu của từng người.

**Ngoại lệ:** Ràng buộc xung đột (vd. vegan vs. carnivore) → đề xuất tách món hoặc menu song song.

---

## **UC7 — Pantry‑aware (Tận dụng nguyên liệu sẵn)**

**Mục tiêu:** Ưu tiên món dùng nguyên liệu đã có; giảm chi phí/lãng phí.

**Tác nhân:** Người dùng cuối.

**Tiền điều kiện:** Đã khai báo pantry (tủ bếp) hoặc quét từ lần mua trước.

**Kích hoạt:** Người dùng bật **Ưu tiên dùng hàng có sẵn** khi lập kế hoạch.

**Luồng chính:**

1. Máy tìm món sử dụng tối đa nguyên liệu trong pantry.

2. Gợi ý **swap** tương đương macro để tận dụng.

3. Shopping list chỉ bao gồm **thiếu**.

**Input (ví dụ):** Pantry: ức gà 500g, yến mạch 1kg, sữa tươi 1L. **User query (ví dụ, ngôn ngữ tự nhiên):**

* “Trong tủ có **ức gà 500g**, **yến mạch 1kg**, **sữa 1L** — **ưu tiên dùng trước** và **chỉ mua phần thiếu** giúp mình.”

**Output (ví dụ):** Kế hoạch có badge “Pantry‑used”; **ShoppingList** chỉ liệt kê phần còn thiếu.

**Tiêu chí thành công:** Tỷ lệ dùng pantry cao; chi phí mua mới giảm.

**Ngoại lệ:** Pantry hết hạn/không đủ → cảnh báo & tự động thay thế.

---

## **UC8 — Ingredient Substitution (Thay thế nguyên liệu)**

**Mục tiêu:** Thay 1 nguyên liệu trong món (vd. hết bơ → dầu ô liu) nhưng vẫn giữ macro gần nhất và qua guard.

**Tác nhân:** Người dùng cuối.

**Tiền điều kiện:** Đang xem chi tiết món trong kế hoạch hoặc trang Recipe.

**Kích hoạt:** Chọn nguyên liệu → **Thay thế**.

**Luồng chính:**

1. Hệ thống đề xuất 2–3 nguyên liệu tương đương về dinh dưỡng.

2. Hiển thị macro **trước/sau** đổi; cảnh báo vị/texture có thể khác.

3. Người dùng chọn **Áp dụng**.

**Input (ví dụ):** Butter 20g → gợi ý Olive Oil 15g (gần fat/kcal), hoặc Ghee 18g. **User query (ví dụ, ngôn ngữ tự nhiên):**

* “Trong món này mình **hết bơ 20g**; **thay bằng dầu ô liu** sao cho **macro gần nhất** và vẫn **đúng chế độ ăn** nhé.”

**Output (ví dụ):** Công thức cập nhật; macro món mới; plan được đồng bộ.

**Tiêu chí thành công:** Sai số macro trong ngưỡng chấp nhận; không vi phạm diet/allergens.

**Ngoại lệ:** Không có thay thế phù hợp → gợi ý đổi món khác.

---

## **UC9 — Micronutrient Gaps (Khoảng thiếu vi chất)**

**Mục tiêu:** Phát hiện thiếu hụt vi chất (so với DRI/DGA) và gợi ý món để bù.

**Tác nhân:** Người dùng cuối.

**Tiền điều kiện:** Có kế hoạch ngày/tuần.

**Kích hoạt:** Người dùng mở **Kiểm tra vi chất**.

**Luồng chính:**

1. Tính vi chất tổng so với chuẩn theo giới/tuổi.

2. Liệt kê **thiếu hụt** (vd. sắt, canxi, vitamin D…).

3. Gợi ý món giàu vi chất đó và cho phép **áp dụng** vào plan.

**Input (ví dụ):** Kế hoạch ngày hiện tại; ngưỡng cảnh báo \= thiếu \>15% DRI. **User query (ví dụ, ngôn ngữ tự nhiên):**

* “**Kiểm tra vi chất** của **kế hoạch tuần này**: mình có **thiếu canxi** hay **vitamin D** không? Nếu thiếu, hãy **gợi ý món bù** và **áp dụng** luôn.”

**Output (ví dụ):** Danh sách thiếu: Calcium −22%, Vitamin D −35%… \+ gợi ý món kèm vi chất.

**Tiêu chí thành công:** Sau khi áp dụng gợi ý, khoảng thiếu giảm rõ rệt; báo cáo **Before/After**.

**Ngoại lệ:** Thiếu dữ liệu vi chất ở vài món → cảnh báo và dùng ước lượng/nguồn thay thế.

---

## **UC10 — Cook‑mode (Chế độ nấu)**

**Mục tiêu:** Hướng dẫn nấu ăn dạng bước‑đến‑bước, có timer và lưu hoàn tất.

**Tác nhân:** Người dùng cuối.

**Tiền điều kiện:** Có món trong kế hoạch/người dùng mở Recipe.

**Kích hoạt:** Bấm **Cook‑mode.**

**Luồng chính:**

1. UI Stepper hiển thị từng bước (chuẩn bị, nấu, hoàn thiện), kèm thời gian gợi ý.

2. Nút **Start/Pause/Next**; đếm ngược; nhắc nhiệt độ an toàn nếu cần.

3. Kết thúc → đánh dấu **đã nấu** và ghi log vào MealLog.

**Input (ví dụ):** Chọn món “Salmon Air‑Fryer”, bật chế độ “Hands‑free” (đọc to bước). **User query (ví dụ, ngôn ngữ tự nhiên):**

* “**Bật Cook‑mode** cho món **Cá hồi Air Fryer**, **đọc từng bước** và **đặt timer 10 phút**; **đánh dấu hoàn tất** khi xong giúp mình.”

**Output (ví dụ):** UI đếm ngược 10′; thông báo “Hoàn tất”; MealLog \+1 lần cho món đó.

**Tiêu chí thành công:** Người dùng theo dõi được các bước rõ ràng, nấu xong đúng thời gian.

**Ngoại lệ:** Bước yêu cầu thiết bị không có → gợi ý thay thế (lò nướng ↔ chảo).

---

## 