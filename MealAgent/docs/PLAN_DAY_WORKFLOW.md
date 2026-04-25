# Quy trình Lập kế hoạch Bữa ăn trong Ngày (Plan Day Workflow)

## 1. Giới thiệu

Chức năng lập kế hoạch bữa ăn trong ngày (Plan Day) là thành phần cốt lõi của hệ thống MealAgent, cho phép tự động tạo kế hoạch ba bữa ăn (sáng, trưa, tối) được cá nhân hóa theo nhu cầu dinh dưỡng của người dùng. Quy trình này kết hợp ba công nghệ chính: Mô hình ngôn ngữ lớn (LLM) để sinh gợi ý thông minh, cơ sở dữ liệu vector Weaviate để truy xuất công thức nấu ăn, và thuật toán tối ưu hóa dinh dưỡng để cân bằng macronutrient.

Quy trình lập kế hoạch bữa ăn được thiết kế dựa trên các nguyên tắc sau:

- **Cá nhân hóa**: Mỗi kế hoạch được điều chỉnh theo hồ sơ dinh dưỡng cá nhân bao gồm tuổi, giới tính, cân nặng, chiều cao, mức độ hoạt động và mục tiêu sức khỏe.
- **Đa dạng hóa**: Hệ thống theo dõi lịch sử bữa ăn để tránh lặp lại món ăn trong khoảng thời gian 7 ngày.
- **Tuân thủ ràng buộc**: Kế hoạch tự động loại trừ các thực phẩm gây dị ứng hoặc không phù hợp với chế độ ăn kiêng của người dùng.
- **Tối ưu hóa dinh dưỡng**: Thuật toán điều chỉnh khẩu phần để đạt mục tiêu về calories, protein, carbohydrate và chất béo.

## 2. Kiến trúc Tổng thể

Quy trình lập kế hoạch bữa ăn được chia thành tám giai đoạn (phase) được thực hiện tuần tự, như minh họa trong Hình 1.

```mermaid
flowchart TB
    subgraph P1["Giai đoạn 1: Chuẩn bị dữ liệu"]
        A1[Tải hồ sơ người dùng]
        A2[Đọc lịch sử bữa ăn]
        A3[Tải ràng buộc ăn kiêng]
        A4[Tải nguyên liệu có sẵn]
    end
    
    subgraph P2["Giai đoạn 2: Sinh gợi ý từ LLM"]
        B1[Sinh khung gợi ý bữa ăn]
        B2[Xác thực cấu trúc dữ liệu]
    end
    
    subgraph P3["Giai đoạn 3: Ánh xạ và Tìm kiếm"]
        C1[Tìm kiếm hybrid trên Weaviate]
        C2[Lọc và kiểm tra ngưỡng]
        C3{Tìm thấy?}
        C4[Ánh xạ gợi ý LLM]
        C5[Tìm kiếm theo luật]
    end
    
    subgraph P4["Giai đoạn 4: Lắp ráp và Điều chỉnh"]
        D1[Ưu tiên protein cho món chính]
        D2[Cân bằng calories cho tinh bột]
        D3[Chuẩn hóa khẩu phần rau/trái cây]
        D4[Điều chỉnh lặp để đạt mục tiêu]
    end
    
    subgraph P5["Giai đoạn 5: Kiểm tra tính hợp lệ"]
        E1[Kiểm tra macronutrient]
        E2[Kiểm tra ràng buộc ăn kiêng]
    end
    
    subgraph P6["Giai đoạn 6: Đánh giá bằng LLM"]
        F1[Sinh nhận xét và gợi ý cải thiện]
    end
    
    subgraph P7["Giai đoạn 7: Phản hồi người dùng"]
        G1[Truyền phát kết quả sớm]
        G2[Cập nhật thông tin dinh dưỡng]
    end
    
    subgraph P8["Giai đoạn 8: Lưu trữ và Điều chỉnh"]
        H1[Lưu vào cơ sở dữ liệu]
        H2[Hỗ trợ thay đổi món ăn]
    end
    
    P1 --> P2 --> P3
    C3 -->|Có| C4
    C3 -->|Không| C5
    C4 & C5 --> P4
    P4 --> P5 --> P6 --> P7 --> P8
    
    LLM[(Dịch vụ LLM)]
    WV[(Weaviate)]
    
    B1 -.-> LLM
    C1 -.-> WV
    F1 -.-> LLM
    H1 -.-> WV
```

**Hình 1:** Kiến trúc tổng thể của quy trình lập kế hoạch bữa ăn trong ngày

## 3. Chi tiết các Giai đoạn

### 3.1. Giai đoạn 1: Chuẩn bị Dữ liệu (Data Preparation)

Giai đoạn này thu thập tất cả thông tin cần thiết từ hệ thống trước khi bắt đầu quá trình lập kế hoạch. Quá trình này được thực hiện qua bốn bước như minh họa trong Hình 2.

```mermaid
flowchart LR
    subgraph S1["Bước 1.1: Tải hồ sơ"]
        P1[Xác định ID người dùng]
        P2[Truy vấn hồ sơ từ Weaviate]
        P3[Tính toán mục tiêu dinh dưỡng]
        P1 --> P2 --> P3
    end
    
    subgraph S2["Bước 1.2: Lịch sử bữa ăn"]
        H1[Truy vấn MealLogEntry]
        H2[Lọc 30 ngày gần nhất]
        H3[Xây dựng danh sách loại trừ]
        H1 --> H2 --> H3
    end
    
    subgraph S3["Bước 1.3: Ràng buộc"]
        C1[Đọc từ environment]
        C2[Trích xuất diet_types và allergens]
        C3[Hợp nhất với hồ sơ]
        C1 --> C2 --> C3
    end
    
    subgraph S4["Bước 1.4: Nguyên liệu"]
        I1[Truy vấn PantryItem]
        I2[Phân tích từ câu hỏi người dùng]
        I3[Hợp nhất và loại bỏ trùng lặp]
        I1 --> I2 --> I3
    end
    
    S1 --> S2 --> S3 --> S4
```

**Hình 2:** Quy trình chi tiết của Giai đoạn 1 - Chuẩn bị dữ liệu

#### 3.1.1. Tải Hồ sơ và Mục tiêu Dinh dưỡng

Hệ thống truy xuất hồ sơ người dùng từ collection `UserProfile` trong Weaviate, bao gồm các thông tin nhân trắc học (tuổi, giới tính, cân nặng, chiều cao), mức độ hoạt động thể chất, và mục tiêu sức khỏe (giảm cân, tăng cơ, duy trì). Từ các thông tin này, hệ thống tính toán mục tiêu dinh dưỡng theo công thức Mifflin-St Jeor:

- **TDEE (Total Daily Energy Expenditure)**: Nhu cầu năng lượng hàng ngày
- **Protein (g)**: Dựa trên cân nặng và mục tiêu (0.8-2.2g/kg)
- **Carbohydrate (g)**: Phần còn lại sau khi trừ protein và chất béo
- **Fat (g)**: 20-35% tổng năng lượng

Trong trường hợp không có hồ sơ người dùng, hệ thống sử dụng giá trị mặc định: TDEE = 2000 kcal, Protein = 150g, Fat = 65g, Carb = 200g.

#### 3.1.2. Đọc Lịch sử Bữa ăn

Để đảm bảo tính đa dạng, hệ thống truy vấn collection `MealLogEntry` để lấy danh sách các bữa ăn đã được tiêu thụ trong 30 ngày gần nhất. Lưu ý rằng `MealLogEntry` lưu trữ các bữa ăn đã được người dùng chấp nhận hoặc ăn thực tế, khác với `MealPlan` chỉ lưu trữ các kế hoạch được gợi ý.

Từ lịch sử này, hệ thống xây dựng hai tập hợp loại trừ:
- Tập hợp ID công thức (`meal_history_recipe_ids`)
- Tập hợp tên món ăn (`meal_history_dish_names`)

#### 3.1.3. Tải Ràng buộc Ăn kiêng

Các ràng buộc ăn kiêng được tải từ hai nguồn và hợp nhất:
- **Từ công cụ constraints_guard_tool**: Các bộ lọc đã được phân tích từ yêu cầu người dùng
- **Từ hồ sơ người dùng**: Các thiết lập cố định như chế độ ăn chay, dị ứng thực phẩm

Kết quả là một cấu trúc dữ liệu chứa: loại chế độ ăn (`diet_types`), danh sách dị ứng (`exclude_allergens`), và mục tiêu sức khỏe (`goal`).

#### 3.1.4. Tải Nguyên liệu Có sẵn

Hệ thống thu thập thông tin về nguyên liệu có sẵn từ hai nguồn:
- **Collection PantryItem**: Danh sách nguyên liệu trong tủ lạnh/kho của người dùng
- **Phân tích câu hỏi**: Trích xuất nguyên liệu được đề cập trong yêu cầu (ví dụ: "tôi có thịt gà và rau cải")

Thông tin này được sử dụng để ưu tiên các công thức sử dụng nguyên liệu có sẵn trong giai đoạn tìm kiếm.

### 3.2. Giai đoạn 2: Sinh Gợi ý từ LLM (LLM Draft Generation)

Giai đoạn này sử dụng mô hình ngôn ngữ lớn để sinh khung gợi ý món ăn dựa trên ngữ cảnh đã thu thập. Quy trình được minh họa trong Hình 3.

```mermaid
flowchart TB
    subgraph INPUT["Đầu vào"]
        I1[Lịch sử bữa ăn]
        I2[Ràng buộc ăn kiêng]
        I3[Sở thích người dùng]
        I4[Nguyên liệu có sẵn]
    end
    
    subgraph PROCESS["Xử lý"]
        P1[Xây dựng prompt với ngữ cảnh]
        P2[Gọi LLM qua DSPy framework]
        P3[Phân tích đầu ra có cấu trúc]
    end
    
    subgraph VALIDATE["Xác thực"]
        V1[Kiểm tra schema với Pydantic]
        V2[Xác thực gợi ý cho bữa sáng]
        V3[Xác thực gợi ý cho bữa trưa]
        V4[Xác thực gợi ý cho bữa tối]
    end
    
    INPUT --> PROCESS --> VALIDATE
    
    LLM[(Dịch vụ LLM via OpenRouter)]
    P2 -.-> LLM
```

**Hình 3:** Quy trình sinh gợi ý từ LLM

#### 3.2.1. Sinh Khung Gợi ý Bữa ăn

Hàm `generate_llm_draft()` xây dựng prompt bao gồm:
- Danh sách món ăn gần đây (để tránh lặp lại)
- Các ràng buộc về chế độ ăn và dị ứng
- Sở thích ẩm thực của người dùng
- Danh sách nguyên liệu có sẵn

LLM được yêu cầu đề xuất nhiều lựa chọn cho mỗi bữa ăn, với thông tin về:
- Tên món ăn cụ thể (`dish_name`)
- Thuật ngữ chung (`general_term`)
- Vai trò trong bữa ăn (`role`: breakfast, main, vegetable, fruit)
- Phân loại (`category`: noodle, rice, main_dish, vegetable)

#### 3.2.2. Xác thực Cấu trúc Dữ liệu

Đầu ra từ LLM được xác thực bằng schema Pydantic `LLMDraftResponse`, đảm bảo cấu trúc dữ liệu nhất quán cho các giai đoạn tiếp theo. Schema bao gồm ba slot bữa ăn (breakfast, lunch, dinner), mỗi slot chứa danh sách các gợi ý với đầy đủ metadata.

### 3.3. Giai đoạn 3: Ánh xạ và Tìm kiếm Công thức (Recipe Mapping and Search)

Giai đoạn này chuyển đổi các gợi ý từ LLM thành công thức nấu ăn thực tế từ cơ sở dữ liệu, với cơ chế fallback khi không tìm thấy kết quả phù hợp. Quy trình được minh họa trong Hình 4.

```mermaid
flowchart TB
    subgraph SEARCH["Bước 3.1: Tìm kiếm Hybrid"]
        S1[Xây dựng truy vấn từ gợi ý LLM]
        S2[Thêm nguyên liệu có sẵn vào truy vấn]
        S3[Gọi search_and_rank_tool]
        S4[Tìm kiếm hybrid: Vector + BM25]
        S5[Trả về 300 công thức hàng đầu]
        S1 --> S2 --> S3 --> S4 --> S5
    end
    
    subgraph FILTER["Bước 3.2: Lọc và Kiểm tra"]
        F1[Áp dụng bộ lọc đa dạng]
        F2[Kiểm tra trùng lặp trong ngày]
        F3[So sánh tên mờ với ngưỡng 0.6]
        F4[Xáo trộn ngẫu nhiên]
        F1 --> F2 --> F3 --> F4
    end
    
    subgraph DECISION["Bước 3.3: Quyết định"]
        D1{Điểm khớp >= Ngưỡng?}
    end
    
    subgraph MAP["Bước 3.4a: Ánh xạ LLM"]
        M1[Tính điểm theo tên]
        M2[Tính điểm theo phân loại]
        M3[Tính điểm theo vai trò]
        M4[Chọn kết quả tốt nhất]
        M1 --> M2 --> M3 --> M4
    end
    
    subgraph FALLBACK["Bước 3.4b: Tìm kiếm theo Luật"]
        R1[Chiến lược: highest_protein]
        R2[Chiến lược: balanced]
        R3[Chiến lược: macro_fit]
        R4[Áp dụng bộ lọc min/max]
    end
    
    SEARCH --> FILTER --> DECISION
    DECISION -->|Có| MAP
    DECISION -->|Không| FALLBACK
```

**Hình 4:** Quy trình ánh xạ và tìm kiếm công thức

#### 3.3.1. Tìm kiếm Hybrid trên Weaviate

Hệ thống xây dựng truy vấn tìm kiếm bằng cách nối các tên món ăn từ gợi ý LLM và nguyên liệu có sẵn. Công cụ `search_and_rank_tool` thực hiện tìm kiếm hybrid trên Weaviate, kết hợp:
- **Tìm kiếm vector**: Sử dụng embedding để tìm công thức có ngữ nghĩa tương tự
- **Tìm kiếm BM25**: Khớp từ khóa trực tiếp trong tên và mô tả

Kết quả trả về tối đa 300 công thức được xếp hạng theo độ phù hợp.

#### 3.3.2. Lọc và Kiểm tra Ngưỡng

Danh sách công thức được lọc qua nhiều bước:
- **Bộ lọc đa dạng**: Loại bỏ công thức đã sử dụng trong 7 ngày gần nhất
- **Kiểm tra trùng lặp**: Loại bỏ công thức đã chọn trong kế hoạch hiện tại
- **So sánh tên mờ**: Sử dụng thuật toán similarity với ngưỡng 0.6 để phát hiện món ăn tương tự
- **Xáo trộn ngẫu nhiên**: Thực hiện 3 lần để tăng tính đa dạng

#### 3.3.3. Hệ thống Tính điểm Ánh xạ

Hàm `_map_llm_suggestion_to_recipe()` tính điểm cho từng công thức dựa trên:

| Tiêu chí | Điểm số |
|----------|---------|
| Khớp tên chính xác | +200 |
| Khớp chuỗi con | +100 |
| Khớp từ khóa | Lên đến +60 (tỷ lệ thuận) |
| Khớp thuật ngữ chung | +80-90 |
| Khớp phân loại | +50 |
| Khớp vai trò | +30 |

Một kết quả được chấp nhận khi đạt một trong các điều kiện:
- Khớp tên chính xác (200 điểm)
- Khớp chuỗi con (100 điểm)
- Khớp từ khóa ≥ 50% VÀ tổng điểm ≥ 70
- Khớp thuật ngữ chung VÀ tổng điểm ≥ 90

#### 3.3.4. Cơ chế Fallback theo Luật

Khi ánh xạ LLM thất bại, hệ thống sử dụng hàm `select_meal_by_strategy()` với ba chiến lược:

| Chiến lược | Mô tả | Trường hợp sử dụng |
|------------|-------|-------------------|
| `highest_protein` | Ưu tiên công thức có protein cao nhất | Bữa sáng, món chính khi thiếu protein |
| `balanced` | Cân bằng các macronutrient | Khi nhu cầu protein đã đủ |
| `macro_fit` | Phù hợp nhất với mục tiêu còn lại | Chọn món phù hợp với phần còn thiếu |

Các bộ lọc được áp dụng bao gồm: giới hạn calories tối thiểu/tối đa, protein tối thiểu, chất béo tối đa, và phân loại món ăn.

### 3.4. Giai đoạn 4: Lắp ráp và Điều chỉnh Khẩu phần (Assembly and Portion Scaling)

Giai đoạn này xây dựng cấu trúc bữa ăn theo mô hình bữa ăn Việt Nam và điều chỉnh khẩu phần để đạt mục tiêu dinh dưỡng. Quy trình được minh họa trong Hình 5.

```mermaid
flowchart TB
    subgraph PROTEIN["Bước 4.1: Ưu tiên Protein"]
        P1[Tính protein tối thiểu theo bữa]
        P2[Chọn món chính giàu protein]
        P3[Theo dõi protein còn thiếu]
    end
    
    subgraph KCAL["Bước 4.2: Cân bằng Calories"]
        K1[Đặt giới hạn calories theo bữa]
        K2[Chọn món tinh bột phù hợp]
        K3[Phát hiện món kết hợp/mì]
    end
    
    subgraph STANDARD["Bước 4.3: Khẩu phần Chuẩn"]
        ST1[Rau: 1 khẩu phần]
        ST2[Trái cây: 1 khẩu phần]
        ST3[Canh: 1 khẩu phần]
    end
    
    subgraph ITERATIVE["Bước 4.4: Điều chỉnh Lặp"]
        I1[Tính toán phần thiếu hụt]
        I2{Thiếu hụt > Ngưỡng?}
        I3[Thêm món bổ sung]
        I4[Kiểm tra giới hạn dư thừa]
        I5[Điều chỉnh khẩu phần nguyên]
        I6[Tính lại macronutrient]
        I1 --> I2
        I2 -->|Có| I3 --> I4 --> I5 --> I6 --> I1
        I2 -->|Không| DONE[Hoàn thành]
    end
    
    PROTEIN --> KCAL --> STANDARD --> ITERATIVE
```

**Hình 5:** Quy trình lắp ráp và điều chỉnh khẩu phần

#### 3.4.1. Ưu tiên Protein cho Món chính

Protein được ưu tiên cao nhất vì khó bù đắp nếu thiếu. Hệ thống tính toán protein tối thiểu cho mỗi bữa dựa trên mục tiêu hàng ngày:

| Bữa ăn | Mục tiêu Protein | Chiến lược |
|--------|------------------|------------|
| Bữa sáng | 20-30g (tùy mục tiêu ngày) | `highest_protein` |
| Bữa trưa (món chính) | 35-45g | `highest_protein` |
| Bữa tối (món chính) | 40-50g | `highest_protein` |

Giá trị protein tối thiểu được điều chỉnh động dựa trên phần còn thiếu:
- Nếu còn thiếu > 50% protein ngày: tăng yêu cầu tối thiểu lên 30g cho bữa sáng
- Nếu còn thiếu 30-50%: yêu cầu tối thiểu 25g
- Nếu đã đủ < 20%: chuyển sang chiến lược `balanced`

#### 3.4.2. Cân bằng Calories cho Tinh bột

Calories được phân bổ theo mô hình bữa ăn Việt Nam:

| Bữa ăn | Tỷ lệ TDEE | Giới hạn tối đa |
|--------|------------|-----------------|
| Bữa sáng | ~25% | 550 kcal |
| Bữa trưa | ~30% | 700 kcal |
| Bữa tối | ~40% | 950 kcal |

Hàm `_select_carb_with_validation()` phân loại món tinh bột thành ba loại:
- **Món kết hợp** (cơm chiên, mì trộn): Chứa cả tinh bột và protein, không cần món chính riêng
- **Món mì** (phở, bún): Bữa ăn độc lập, không cần món ăn kèm
- **Cơm trắng**: Cần món chính, rau, và canh ăn kèm

#### 3.4.3. Chuẩn hóa Khẩu phần Rau và Trái cây

Theo mô hình bữa ăn Việt Nam truyền thống:

**Bữa cơm:**
- Cơm: 1-4 khẩu phần (số nguyên)
- Món mặn: 1-2 khẩu phần
- Rau/Canh: 1 khẩu phần
- Trái cây: 1 khẩu phần (tùy chọn)

**Bữa mì/phở:**
- Món mì: 1 khẩu phần (bữa ăn độc lập)
- Trái cây: 1 khẩu phần (tùy chọn)

**Món kết hợp:**
- Món chính: 1 khẩu phần (bữa ăn độc lập)
- Trái cây: 1 khẩu phần (tùy chọn)

#### 3.4.4. Điều chỉnh Lặp để Đạt Mục tiêu

Thuật toán điều chỉnh lặp (tối đa 3-20 vòng) thực hiện:

1. **Tính toán thiếu hụt**: So sánh tổng macronutrient hiện tại với mục tiêu
2. **Kiểm tra điều kiện dừng**:
   - Thiếu hụt < 5%: Hoàn thành
   - Dư thừa chất béo > 15%: Dừng để tránh ăn quá nhiều
   - Dư thừa carbohydrate > 20%: Dừng
3. **Thêm món bổ sung**: Ưu tiên món giàu protein, ít chất béo, sử dụng nguyên liệu có sẵn
4. **Điều chỉnh khẩu phần nguyên**:
   - Cơm: +1 khẩu phần (tối đa 4)
   - Món chính: +1 khẩu phần (tối đa 2)

### 3.5. Giai đoạn 5: Kiểm tra Tính hợp lệ (Validation)

Giai đoạn này đảm bảo kế hoạch đáp ứng cả mục tiêu dinh dưỡng và ràng buộc ăn kiêng.

```mermaid
flowchart TB
    subgraph MACRO["Kiểm tra Macronutrient"]
        M1[Tính tổng macronutrient của kế hoạch]
        M2[So sánh với mục tiêu]
        M3[Áp dụng ngưỡng dung sai 15%]
        M4{Trong phạm vi?}
        M5[Ghi nhận vi phạm]
        M6[Ghi nhận cảnh báo]
        M1 --> M2 --> M3 --> M4
        M4 -->|Không| M5
        M4 -->|Có| M6
    end
    
    subgraph CONSTRAINT["Kiểm tra Ràng buộc"]
        C1[Kiểm tra loại chế độ ăn]
        C2[Kiểm tra dị ứng thực phẩm]
        C3[Kiểm tra nguyên liệu công thức]
        C4{Tất cả đạt?}
        C5[Ghi nhận vi phạm]
        C1 --> C2 --> C3 --> C4
        C4 -->|Không| C5
    end
    
    MACRO --> CONSTRAINT
```

**Hình 6:** Quy trình kiểm tra tính hợp lệ

#### 3.5.1. Kiểm tra Macronutrient

Hàm `_validate_macro_targets()` kiểm tra từng macronutrient với ngưỡng dung sai 15%:

| Macronutrient | Mục tiêu (VD) | Dung sai 15% | Phạm vi hợp lệ |
|---------------|---------------|--------------|----------------|
| Calories | 2400 kcal | ±360 | 2040 - 2760 kcal |
| Protein | 192g | ±28.8g | 163 - 221g |
| Fat | 64g | ±9.6g | 54 - 74g |
| Carbohydrate | 219g | ±32.9g | 186 - 252g |

Kết quả bao gồm:
- `valid`: Boolean cho biết tất cả đạt
- `violations`: Danh sách vi phạm ngoài phạm vi
- `warnings`: Danh sách cảnh báo gần biên

#### 3.5.2. Kiểm tra Ràng buộc Ăn kiêng

Hàm `_validate_constraints()` kiểm tra:
- **Tuân thủ chế độ ăn**: Ví dụ chế độ ăn chay không được chứa thịt
- **Không có dị ứng**: Ví dụ không có hải sản nếu người dùng dị ứng

Kết quả bao gồm danh sách vi phạm với thông tin chi tiết về món ăn và bữa ăn vi phạm.

### 3.6. Giai đoạn 6: Đánh giá bằng LLM (LLM Critic)

Giai đoạn này sử dụng mô hình ngôn ngữ để đánh giá kế hoạch và đưa ra gợi ý cải thiện khi có vi phạm hoặc cảnh báo.

```mermaid
flowchart TB
    CHECK{Có vi phạm hoặc cảnh báo?}
    
    subgraph GENERATE["Sinh Nhận xét"]
        G1[Tạo task bất đồng bộ]
        G2[Xây dựng ngữ cảnh: kế hoạch + mục tiêu + kết quả kiểm tra]
        G3[Gọi LLM]
        G4[Chờ tối đa 5 giây]
    end
    
    CHECK -->|Có| GENERATE
    CHECK -->|Không| SKIP[Bỏ qua]
    
    GENERATE --> OUTPUT[Gợi ý cải thiện]
```

**Hình 7:** Quy trình đánh giá bằng LLM

Hàm `create_critic_task()` tạo một task bất đồng bộ gọi LLM với ngữ cảnh đầy đủ về kế hoạch, mục tiêu dinh dưỡng, và kết quả kiểm tra. LLM được yêu cầu đưa ra gợi ý cụ thể để cải thiện kế hoạch.

Ví dụ output: "Kế hoạch thiếu 15% protein. Gợi ý: Thêm 1 khẩu phần thịt gà vào bữa tối hoặc thay đổi món sáng sang phở bò."

**Lưu ý quan trọng**: LLM Critic được gọi bất đồng bộ và sau khi đã trả kết quả cho người dùng, không làm chậm luồng chính.

### 3.7. Giai đoạn 7: Phản hồi Người dùng (Response Streaming)

Giai đoạn này cung cấp phản hồi nhanh cho người dùng trong khi vẫn đang tính toán các phần còn lại.

```mermaid
flowchart TB
    subgraph EARLY["Phản hồi Sớm"]
        E1[Thông báo đang lập kế hoạch]
        E2[Hiển thị tên món ăn dự kiến]
    end
    
    subgraph UPDATE["Cập nhật Chi tiết"]
        U1[Tính toán lại macronutrient theo bữa]
        U2[Tính tổng macronutrient kế hoạch]
        U3[Hiển thị thông tin dinh dưỡng]
        U4[Hiển thị vi chất dinh dưỡng]
    end
    
    EARLY --> UPDATE
```

**Hình 8:** Quy trình truyền phát phản hồi

Mô hình streaming cho phép:
1. **Phản hồi sớm**: Người dùng thấy tên món ăn ngay lập tức
2. **Cập nhật dần**: Thông tin dinh dưỡng chi tiết được bổ sung sau
3. **Trải nghiệm mượt mà**: Không cần chờ đợi toàn bộ quá trình tính toán

Chuỗi phản hồi điển hình:
1. "Đang lập kế hoạch bữa ăn..."
2. "Đã tải hồ sơ người dùng"
3. "Đang tìm kiếm công thức..."
4. "Kế hoạch dự kiến: Bữa sáng: Phở bò | Bữa trưa: Cơm tấm, Sườn nướng | Bữa tối: ..."
5. "Macronutrient: 2380 kcal | 185g protein | 62g fat | 215g carbs"
6. "Tất cả các macronutrient đạt mục tiêu (Độ chính xác: 95.2%)"

### 3.8. Giai đoạn 8: Lưu trữ và Điều chỉnh (Storage and Modification)

Giai đoạn này lưu kế hoạch vào cơ sở dữ liệu và hỗ trợ người dùng điều chỉnh nếu cần.

```mermaid
flowchart TB
    subgraph SAVE["Lưu vào Cơ sở dữ liệu"]
        S1[Gọi sync_plan_to_weaviate]
        S2[Tạo bản ghi MealPlan]
        S3[Tạo các bản ghi MealPlanItem]
        S4[Lưu plan_id vào environment]
        S1 --> S2 --> S3 --> S4
    end
    
    subgraph ACCEPT["Quy trình Chấp nhận"]
        A1[Người dùng nhấn Chấp nhận]
        A2[Gọi log_meal_e2e_tool]
        A3[Tạo các bản ghi MealLogEntry]
        A4[Cập nhật dinh dưỡng đã tiêu thụ trong ngày]
        A1 --> A2 --> A3 --> A4
    end
    
    subgraph SWAP["Quy trình Thay đổi"]
        W1[Người dùng yêu cầu thay đổi]
        W2[Gọi swap_meal_tool]
        W3[Chọn lại món ăn]
        W4[Lắp ráp lại với điều chỉnh khẩu phần]
        W5[Kiểm tra lại tính hợp lệ]
        W1 --> W2 --> W3 --> W4 --> W5
    end
    
    SAVE --> ACCEPT
    SAVE --> SWAP
```

**Hình 9:** Quy trình lưu trữ và điều chỉnh

#### 3.8.1. Cấu trúc Lưu trữ Dữ liệu

Hệ thống sử dụng ba collection trong Weaviate với mục đích khác nhau:

| Collection | Mục đích | Thời điểm tạo |
|------------|----------|---------------|
| `MealPlan` | Metadata của kế hoạch (plan_id, user_id, ngày) | Ngay sau khi sinh kế hoạch |
| `MealPlanItem` | Chi tiết từng bữa trong kế hoạch | Ngay sau khi sinh kế hoạch |
| `MealLogEntry` | Bữa ăn đã được tiêu thụ thực tế | Khi người dùng chấp nhận kế hoạch |

Sự phân tách này cho phép:
- Theo dõi tất cả kế hoạch đã gợi ý (cho phân tích và cải thiện hệ thống)
- Chỉ tính bữa ăn thực tế vào lịch sử (cho bộ lọc đa dạng)
- Hỗ trợ người dùng xem lại và chấp nhận kế hoạch sau

#### 3.8.2. Quy trình Chấp nhận Kế hoạch

Khi người dùng chấp nhận kế hoạch:
1. Hệ thống gọi `log_meal_e2e_tool` với `plan_id`
2. Tải kế hoạch từ `MealPlan` và `MealPlanItem`
3. Tạo các bản ghi `MealLogEntry` cho mỗi bữa ăn
4. Cập nhật tổng dinh dưỡng đã tiêu thụ trong ngày

#### 3.8.3. Quy trình Thay đổi Món ăn

Khi người dùng yêu cầu thay đổi một món ăn:
1. Công cụ `swap_meal_tool` nhận yêu cầu với thông tin món cần thay
2. Tìm kiếm món thay thế phù hợp với cùng vai trò và ràng buộc
3. Lắp ráp lại kế hoạch với món mới
4. Điều chỉnh khẩu phần để duy trì cân bằng dinh dưỡng
5. Kiểm tra lại tính hợp lệ của kế hoạch mới

## 4. Sơ đồ Tuần tự (Sequence Diagram)

Hình 10 minh họa luồng tương tác giữa các thành phần trong toàn bộ quy trình.

```mermaid
sequenceDiagram
    participant U as Người dùng
    participant PD as plan_day_e2e_tool
    participant ENV as Environment
    participant LLM as Dịch vụ LLM
    participant WV as Weaviate
    
    U->>PD: Yêu cầu lập kế hoạch bữa ăn
    
    rect rgb(240, 248, 255)
    Note over PD: Giai đoạn 1: Chuẩn bị dữ liệu
    PD->>WV: Tải hồ sơ người dùng
    WV-->>PD: Dữ liệu hồ sơ
    PD->>WV: Truy vấn MealLogEntry (30 ngày)
    WV-->>PD: Lịch sử bữa ăn
    PD->>ENV: Đọc constraints_guard_tool.filters
    ENV-->>PD: Ràng buộc
    PD->>WV: Truy vấn PantryItem
    WV-->>PD: Nguyên liệu có sẵn
    end
    
    rect rgb(255, 250, 240)
    Note over PD: Giai đoạn 2: Sinh gợi ý từ LLM
    PD->>LLM: Sinh khung gợi ý bữa ăn
    LLM-->>PD: LLMDraftResponse
    PD->>PD: Xác thực với Pydantic
    end
    
    rect rgb(240, 255, 240)
    Note over PD: Giai đoạn 3: Tìm kiếm và Ánh xạ
    PD->>WV: Tìm kiếm hybrid (300 công thức)
    WV-->>PD: Công thức được xếp hạng
    PD->>PD: Lọc và kiểm tra ngưỡng
    PD->>PD: Ánh xạ LLM hoặc Fallback
    end
    
    rect rgb(255, 245, 238)
    Note over PD: Giai đoạn 4: Lắp ráp
    PD->>PD: Chọn bữa sáng (ưu tiên protein)
    PD->>PD: Chọn bữa trưa (tinh bột + món chính + rau)
    PD->>PD: Chọn bữa tối
    PD->>PD: Điều chỉnh lặp khẩu phần
    end
    
    rect rgb(255, 240, 245)
    Note over PD: Giai đoạn 5-6: Kiểm tra và Đánh giá
    PD->>PD: Kiểm tra macronutrient
    PD->>PD: Kiểm tra ràng buộc
    PD-->>U: Truyền phát phản hồi (kế hoạch dự kiến)
    PD->>LLM: Đánh giá (bất đồng bộ)
    end
    
    rect rgb(245, 245, 255)
    Note over PD: Giai đoạn 7-8: Phản hồi và Lưu trữ
    PD->>WV: sync_plan_to_weaviate
    WV-->>PD: plan_id đã lưu
    PD-->>U: Trả kết quả (kế hoạch)
    PD-->>U: Truyền phát phản hồi (tóm tắt)
    LLM-->>PD: Gợi ý cải thiện
    PD-->>U: Truyền phát phản hồi (gợi ý)
    end
```

**Hình 10:** Sơ đồ tuần tự của quy trình lập kế hoạch bữa ăn trong ngày

## 5. Giao diện với Các Thành phần Khác

### 5.1. Đọc từ Environment

| Khóa | Nguồn | Mô tả |
|------|-------|-------|
| `macro_calc_tool.targets` | macro_calc_tool | Mục tiêu dinh dưỡng dựa trên TDEE |
| `constraints_guard_tool.filters` | constraints_guard_tool | Loại chế độ ăn, dị ứng |
| `search_and_rank_tool.topk` | search_and_rank_tool | Công thức đã cache (dự phòng) |

### 5.2. Ghi vào Environment

| Khóa | Đích | Mô tả |
|------|------|-------|
| `plan_day_e2e_tool.plan` | Result | Kế hoạch ngày hoàn chỉnh |
| `plan_day_e2e_tool.plan_id` | Environment | ID kế hoạch để tham chiếu |
| `plan_day_e2e_tool.missing_macros` | Result | Công thức thiếu dữ liệu macro |

## 6. Xử lý Lỗi

Hệ thống xử lý các tình huống lỗi như sau:

| Tình huống | Xử lý |
|------------|-------|
| Không tìm thấy công thức | Trả lỗi: "Vui lòng tìm kiếm công thức trước" |
| Không có món sáng phù hợp | Trả lỗi: "Vui lòng tìm kiếm công thức bữa sáng" |
| Tải hồ sơ thất bại | Sử dụng giá trị mặc định, tiếp tục |
| Sinh gợi ý LLM thất bại | Chuyển sang tìm kiếm theo luật |
| Lưu Weaviate thất bại | Ghi log cảnh báo, tiếp tục (kế hoạch vẫn hiển thị) |
| Kiểm tra macro thất bại | Trả kế hoạch kèm cảnh báo |


## 8. Tham số Cấu hình

| Tham số | Mặc định | Mô tả |
|---------|----------|-------|
| `macro_tolerance_percent` | 0.15 | Ngưỡng dung sai 15% cho kiểm tra macro |
| `recent_plan_window_minutes` | 10080 | Cửa sổ đa dạng 7 ngày (phút) |
| `collection_name` | "Recipe" | Tên collection Weaviate cho công thức |

## 9. Kết luận

Quy trình lập kế hoạch bữa ăn trong ngày của MealAgent kết hợp hiệu quả ba công nghệ then chốt: mô hình ngôn ngữ lớn cho sinh gợi ý thông minh, cơ sở dữ liệu vector cho truy xuất ngữ nghĩa, và thuật toán tối ưu hóa cho cân bằng dinh dưỡng. Thiết kế theo mô-đun với tám giai đoạn rõ ràng cho phép bảo trì và mở rộng dễ dàng, trong khi cơ chế fallback đảm bảo độ tin cậy cao trong nhiều tình huống khác nhau.
