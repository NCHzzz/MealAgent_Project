# MealAgent Evaluation Framework

Hệ thống đánh giá toàn diện cho MealAgent với 3 phương pháp đánh giá chính.

## 📋 Mục lục

1. [Setup và Cài đặt](#setup-và-cài-đặt)
2. [Các phương pháp đánh giá](#các-phương-pháp-đánh-giá)
3. [Cách chạy Tests](#cách-chạy-tests)
4. [Sử dụng Weaviate Data](#sử-dụng-weaviate-data)
5. [Sử dụng trong Code](#sử-dụng-trong-code)
6. [Troubleshooting](#troubleshooting)

---

## Setup và Cài đặt

### 1. Cài đặt Dependencies

#### Cài đặt cơ bản (tối thiểu)

```bash
pip install numpy pandas
```

#### Cài đặt đầy đủ

```bash
pip install -r evaluation/requirements.txt
```

#### Cài đặt từng package (nếu cần)

```bash
# Cho BERTScore
pip install bert-score transformers torch

# Cho LLM Judge (không cần cài thêm, dùng Gemini API)
```

### 2. Cấu hình API Keys

#### Gemini API Key (cho LLM Judge)

```bash
# Linux/Mac
export GEMINI_API_KEY="your-api-key-here"

# Windows PowerShell
$env:GEMINI_API_KEY="your-api-key-here"

# Windows CMD
set GEMINI_API_KEY=your-api-key-here
```

Hoặc tạo file `.env` trong thư mục gốc:

```env
GEMINI_API_KEY=your-api-key-here
```

#### Weaviate Configuration (nếu dùng Weaviate data)

```bash
# Cho Weaviate Cloud
export WCD_URL="https://your-weaviate-cluster.weaviate.network"
export WCD_API_KEY="your-api-key"

# Cho Local Weaviate
export WCD_URL="localhost"  # hoặc "http://localhost:8080"
export WEAVIATE_IS_LOCAL="true"
```

### 3. Kiểm tra Cài đặt

```bash
# Kiểm tra imports
python -c "from evaluation.metrics.nutrition_error import NutritionErrorEvaluator; print('OK')"
```

---

## Các phương pháp đánh giá

### 1. Nutrition Error (MAE & % Error)

**Mục đích:** Đo lường độ chính xác của meal plan hoặc meal logs so với mục tiêu dinh dưỡng.

**Metrics:**
- **MAE (Mean Absolute Error)**: Sai số tuyệt đối trung bình cho:
  - Protein (grams)
  - Carb (grams)
  - Fat (grams)
  - Calories (kcal)
- **% Error**: Phần trăm sai số tương đối cho từng metric
- **Overall metrics**: Trung bình của tất cả metrics

**Nguồn dữ liệu (load từ Weaviate):**
- **MealPlan collection**: Tất cả **suggested meal plans** (plans được hệ thống đưa ra nhưng **chưa được user chấp nhận**)
- **MealPlanItem collection**: Tất cả meal plan items (loaded via MealPlan)
- **MealLogEntry collection**: Tất cả **accepted/actual plans** (plans đã được **user chấp nhận hoặc thực sự ăn**)
- **UserProfile collection**: Tất cả user profiles với nutrition targets (protein_g, carb_g, fat_g, tdee_kcal)

**Ưu điểm:**
- ✅ Không cần API key
- ✅ Chạy nhanh
- ✅ Dễ hiểu và giải thích
- ✅ Hỗ trợ cả MealPlan và MealLogEntry

**Hạn chế:**
- Chỉ đánh giá về mặt số lượng, không đánh giá chất lượng món ăn

**Cách hoạt động:**
1. Load TẤT CẢ dữ liệu từ Weaviate:
  - **MealPlan collection**: Load tất cả **suggested plans** (chưa được user chấp nhận)
  - **MealPlanItem collection**: Load tất cả items (via MealPlan)
  - **MealLogEntry collection**: Load tất cả **accepted/actual plans** (đã được user chấp nhận hoặc thực sự ăn) và aggregate theo user + date
   - **UserProfile collection**: Load tất cả profiles với nutrition targets
2. Match meal plans/logs với user profiles (theo user_id)
3. Với mỗi pair (meal_plan/log, user_profile):
   - Lấy `total_macros` từ meal plan/log (actual values)
   - Lấy nutrition targets từ user profile (target values: protein_g, carb_g, fat_g, tdee_kcal)
   - Tính MAE và % Error cho từng metric
4. Aggregate tất cả kết quả để có statistics tổng thể

### 2. LLM-as-a-Judge

**Mục đích:** Sử dụng LLM (Gemini 3) đóng vai trò chuyên gia dinh dưỡng để đánh giá meal plan.

**Metrics:**
- **Overall Score**: Điểm tổng thể (0-100)
- **Nutrition Score**: Điểm về dinh dưỡng (0-100)
- **Variety Score**: Điểm về tính đa dạng (0-100)
- **Balance Score**: Điểm về sự cân bằng (0-100)
- **Feasibility Score**: Điểm về tính khả thi (0-100)
- **Feedback**: Nhận xét chi tiết
- **Strengths**: Điểm mạnh
- **Suggestions**: Gợi ý cải thiện

**Yêu cầu:**
- Cần Gemini API key: `export GEMINI_API_KEY="your-key"`
- Cần internet connection

**Ưu điểm:**
- Đánh giá toàn diện và có insight
- Có feedback chi tiết

**Hạn chế:**
- Cần API key (có thể tốn phí)
- Chạy chậm hơn (API calls)
- Phụ thuộc vào chất lượng LLM

### 3. BERTScore (Semantic Similarity)

**Mục đích:** Đo lường độ tương đồng ngữ nghĩa giữa meal plan và reference plans.

**Metrics:**
- **Precision**: Độ chính xác (0-1)
- **Recall**: Độ thu hồi (0-1)
- **F1 Score**: Trung bình điều hòa của Precision và Recall (0-1)

**Yêu cầu:**
- Cần cài đặt: `pip install bert-score transformers torch`
- Lần đầu chạy sẽ download BERT model (có thể mất vài phút)
- Cần GPU hoặc nhiều RAM cho tốc độ tốt

**Ưu điểm:**
- Đánh giá semantic similarity chính xác
- So sánh với reference plans

**Hạn chế:**
- Cần reference plans để so sánh
- Tốn memory và thời gian

---

## Cách chạy Tests

### Quick Start (5 phút)

```bash
# 1. Cài đặt dependencies cơ bản
pip install numpy pandas

# 2. Chạy test đơn giản nhất (không cần API key)
python -m evaluation.scripts.run_single_method nutrition_error

# 3. Xem kết quả
cat evaluation/results/nutrition_error_test.json
```

### Chạy từng phương pháp riêng lẻ

#### 1. Nutrition Error

```bash
# Mặc định load TẤT CẢ từ tất cả collections:
# - MealPlan collection (tất cả suggested plans)
# - MealPlanItem collection (via MealPlan)
# - MealLogEntry collection (tất cả actual consumed meals)
# - UserProfile collection (nutrition targets)
python -m evaluation.scripts.run_single_method nutrition_error

# Filter meal logs theo ngày cụ thể
python -m evaluation.scripts.run_single_method nutrition_error --date 2024-01-15

# Chỉ load cho specific users (disable load-all)
python -m evaluation.scripts.run_single_method nutrition_error --no-load-all --user-ids user1 user2 user3

# Nếu muốn dùng mock data thay vì Weaviate
python -m evaluation.scripts.run_single_method nutrition_error --use-mock
```

**Kết quả:** `evaluation/results/nutrition_error_test.json`

**Lưu ý:** 
- **Mặc định load TẤT CẢ dữ liệu** từ Weaviate database:
  - **MealPlan collection**: Tất cả **suggested meal plans** (plans được hệ thống đưa ra nhưng **chưa được user chấp nhận**)
  - **MealPlanItem collection**: Tất cả meal plan items (loaded via MealPlan)
  - **MealLogEntry collection**: Tất cả **accepted/actual plans** (plans đã được **user chấp nhận hoặc thực sự ăn**, aggregated by user and date)
  - **UserProfile collection**: Tất cả user profiles với nutrition targets
- Đánh giá sẽ so sánh tất cả meal plans/logs với nutrition targets từ UserProfile
- Nếu Weaviate không khả dụng, sẽ tự động fallback về mock data
- Không cần API key, chạy nhanh

#### 2. LLM-as-a-Judge

```bash
# Set API key trước
export GEMINI_API_KEY="your-api-key"

# Chạy test
python -m evaluation.scripts.run_single_method llm_judge
```

**Kết quả:** `evaluation/results/llm_judge_test.json`

**Lưu ý:**
- Cần internet connection
- Có thể tốn phí API calls
- Chạy chậm hơn các phương pháp khác

#### 3. BERTScore

```bash
# Cần cài đặt BERTScore trước
pip install bert-score transformers torch

# Chạy test
python -m evaluation.scripts.run_single_method bertscore
```

**Kết quả:** `evaluation/results/bertscore_test.json`

**Lưu ý:**
- Lần đầu chạy sẽ download BERT model (có thể mất vài phút)
- Cần GPU hoặc nhiều RAM cho tốc độ tốt

### Chạy tất cả evaluations

```bash
# Với mock data (nhanh, để test)
python -m evaluation.scripts.run_evaluation --use-mock

# Với MealAgent thực tế (cần setup MealAgent)
python -m evaluation.scripts.run_evaluation

# Chỉ chạy methods cụ thể
python -m evaluation.scripts.run_evaluation --methods nutrition_error llm_judge

# Chỉ chạy scenarios cụ thể
python -m evaluation.scripts.run_evaluation --scenarios scenario_1 scenario_2
```

**Lưu ý:** Hiện tại chỉ hỗ trợ 3 phương pháp: `nutrition_error`, `llm_judge`, `bertscore`

**Kết quả:**
- `evaluation/results/evaluation_results_YYYYMMDD_HHMMSS.json` - Kết quả chi tiết JSON
- `evaluation/results/evaluation_results_YYYYMMDD_HHMMSS_summary.csv` - Tóm tắt CSV

---

## Sử dụng Weaviate Data

Evaluation framework hỗ trợ load dữ liệu trực tiếp từ Weaviate database thay vì chỉ sử dụng mock data.

### Cấu hình Weaviate

```bash
# Cho Weaviate Cloud
export WCD_URL="https://your-weaviate-cluster.weaviate.network"
export WCD_API_KEY="your-api-key"

# Cho Local Weaviate
export WCD_URL="localhost"
export WEAVIATE_IS_LOCAL="true"
```

### Chạy với Weaviate Data

```bash
# Load tất cả users từ Weaviate
python -m evaluation.scripts.run_single_method nutrition_error --use-weaviate

# Load specific users
python -m evaluation.scripts.run_single_method nutrition_error --use-weaviate --user-ids user1 user2 user3
```

### Fallback Behavior

Nếu Weaviate không khả dụng hoặc có lỗi khi load dữ liệu, các script sẽ tự động fallback về mock data và hiển thị warning message.

---

## Sử dụng trong Code

### Sử dụng EvaluationRunner

```python
from evaluation.runners.evaluation_runner import EvaluationRunner
from evaluation.test_cases.test_profiles import get_test_profiles

# Khởi tạo runner
runner = EvaluationRunner(
    results_dir="evaluation/results",
    gemini_api_key=os.getenv("GEMINI_API_KEY")
)

# Chuẩn bị dữ liệu
meal_plans = [plan1, plan2, plan3]
user_profiles = [profile1, profile2, profile3]
user_queries = ["query1", "query2", "query3"]  # Optional

# Chạy tất cả evaluations
results = runner.run_all_evaluations(
    meal_plans=meal_plans,
    user_profiles=user_profiles,
    user_queries=user_queries,
    reference_plans=None  # Optional, cho BERTScore
)

# Lưu kết quả
runner.save_results(results)
```

### Chạy từng phương pháp riêng

```python
# Chỉ chạy Nutrition Error
nutrition_results = runner.run_nutrition_evaluation(
    meal_plans=meal_plans,
    user_profiles=user_profiles
)


# Chỉ chạy LLM Judge
llm_judge_results = runner.run_llm_judge_evaluation(
    meal_plans=meal_plans,
    user_profiles=user_profiles
)

# Chỉ chạy BERTScore
bertscore_results = runner.run_bertscore_evaluation(
    meal_plans=meal_plans,
    user_profiles=user_profiles,
    reference_plans=reference_plans  # Optional
)
```

### Load dữ liệu từ Weaviate

```python
from evaluation.runners.evaluation_runner import EvaluationRunner

# Load dữ liệu từ Weaviate
meal_plans, user_profiles = EvaluationRunner.load_data_from_weaviate(
    user_ids=["user1", "user2"],  # hoặc None để lấy tất cả
    plan_type="day",  # hoặc "week"
    use_latest=True
)

# Chạy evaluation
runner = EvaluationRunner()
results = runner.run_all_evaluations(
    meal_plans=meal_plans,
    user_profiles=user_profiles
)
```

### Sử dụng trực tiếp với weaviate_data_loader

```python
from evaluation.utils.weaviate_data_loader import (
    load_evaluation_data_from_weaviate,
    get_all_user_ids_from_weaviate,
    create_client_manager,
)

# Tạo client manager
client_manager = create_client_manager()

# Lấy tất cả user IDs
user_ids = get_all_user_ids_from_weaviate(client_manager, limit=10)

# Load meal plans và profiles
meal_plans, user_profiles = load_evaluation_data_from_weaviate(
    user_ids, 
    client_manager, 
    plan_type="day",
    use_latest=True
)
```

---

## Troubleshooting

### Lỗi Import

**Vấn đề:** `ModuleNotFoundError: No module named 'evaluation'`

**Giải pháp:**
```bash
# Đảm bảo đang ở thư mục gốc của project
cd /path/to/Elysia_cursor

# Hoặc thêm vào PYTHONPATH
export PYTHONPATH="${PYTHONPATH}:$(pwd)"
```

### Lỗi MealAgent không tìm thấy

**Vấn đề:** `ImportError: cannot import name 'plan_day_e2e_tool'`

**Giải pháp:**
```bash
# Sử dụng mock data thay vì generate thực tế
python -m evaluation.scripts.run_evaluation --use-mock
```


### Lỗi Gemini API

**Vấn đề:** `ValueError: GEMINI_API_KEY must be provided`

**Giải pháp:**
```bash
# Set API key
export GEMINI_API_KEY="your-api-key"

# Hoặc bỏ qua LLM Judge
python -m evaluation.scripts.run_evaluation --methods nutrition_error llm_judge bertscore
```

### Lỗi BERTScore

**Vấn đề:** `ImportError: cannot import name 'bert_score'`

**Giải pháp:**
```bash
pip install bert-score transformers torch

# Hoặc bỏ qua BERTScore
python -m evaluation.scripts.run_evaluation --methods nutrition_error llm_judge bertscore
```

### Lỗi Memory (BERTScore)

**Vấn đề:** `RuntimeError: CUDA out of memory` hoặc `MemoryError`

**Giải pháp:**
- Giảm số lượng test cases
- Chạy từng phương pháp riêng lẻ
- Sử dụng CPU thay vì GPU cho BERTScore

### Lỗi Weaviate

**Vấn đề:** `Weaviate client is not available`

**Giải pháp:**
- Kiểm tra environment variables: `WCD_URL`, `WCD_API_KEY`, `WEAVIATE_IS_LOCAL`
- Đảm bảo Weaviate server đang chạy và có thể kết nối được
- Script sẽ tự động fallback về mock data

**Vấn đề:** `No users found in Weaviate`

**Giải pháp:**
- Kiểm tra xem có user profiles trong Weaviate UserProfile collection không
- Thử chỉ định user_ids cụ thể: `--user-ids user1 user2`

**Vấn đề:** `No matching meal plans and profiles found`

**Giải pháp:**
- Đảm bảo mỗi user có ít nhất một meal plan trong Weaviate
- Kiểm tra `plan_type` có đúng không ("day" hoặc "week")

### Kết quả không chính xác

**Kiểm tra:**
1. Đảm bảo meal plans có đúng format
2. Đảm bảo user profiles có đầy đủ thông tin (protein_g, carb_g, fat_g, tdee_kcal)
3. Kiểm tra logs để xem có lỗi nào không

---

## Cấu trúc thư mục

```
evaluation/
├── README.md                    # File này - Tài liệu tổng hợp
├── requirements.txt             # Dependencies
├── example_usage.py            # Ví dụ sử dụng
│
├── metrics/                     # Các phương pháp đánh giá
│   ├── nutrition_error.py      # MAE & % Error
│   ├── llm_judge.py            # LLM-as-a-judge
│   └── bertscore_eval.py       # BERTScore
│
├── test_cases/                  # Test data
│   ├── test_profiles.py        # User profiles
│   └── test_scenarios.py       # Test scenarios
│
├── runners/                     # Evaluation runners
│   └── evaluation_runner.py   # Main runner
│
├── scripts/                     # Scripts để chạy tests
│   ├── run_evaluation.py       # Chạy tất cả
│   └── run_single_method.py    # Chạy từng phương pháp
│
├── utils/                       # Utilities
│   └── weaviate_data_loader.py # Load data từ Weaviate
│
└── results/                     # Kết quả (tự động tạo)
    └── *.json, *.csv
```

---

## Best Practices

1. **Bắt đầu với mock data**: Dùng `--use-mock` hoặc không set `--use-weaviate` để test nhanh trước
2. **Chạy từng phương pháp**: Test từng phương pháp riêng để debug dễ hơn
3. **Lưu kết quả**: Luôn kiểm tra kết quả trong `evaluation/results/`
4. **Kiểm tra logs**: Xem console output để phát hiện lỗi
5. **Giảm test cases**: Nếu chạy chậm, giảm số lượng scenarios hoặc users

---

## Ví dụ Workflow

### Workflow 1: Quick test với mock data

```bash
# 1. Cài đặt dependencies cơ bản
pip install numpy pandas

# 2. Chạy nutrition error test (nhanh nhất)
python -m evaluation.scripts.run_single_method nutrition_error

# 3. Xem kết quả
cat evaluation/results/nutrition_error_test.json
```

### Workflow 2: Full evaluation với Weaviate

```bash
# 1. Setup environment
export GEMINI_API_KEY="your-key"
export WCD_URL="localhost"
export WEAVIATE_IS_LOCAL="true"
pip install -r evaluation/requirements.txt

# 2. Chạy với Weaviate data
python -m evaluation.scripts.run_single_method nutrition_error --use-weaviate

# 3. Xem kết quả
ls -lh evaluation/results/
```

### Workflow 3: Test từng phương pháp

```bash
# Test 1: Nutrition Error với MealPlan (không cần API key)
python -m evaluation.scripts.run_single_method nutrition_error

# Test 1b: Nutrition Error với MealLogEntry
python -m evaluation.scripts.run_single_method nutrition_error --use-meal-logs

# Test 2: LLM Judge (cần API key)
export GEMINI_API_KEY="your-key"
python -m evaluation.scripts.run_single_method llm_judge

# Test 3: BERTScore (cần cài bert-score)
pip install bert-score
python -m evaluation.scripts.run_single_method bertscore
```

---

## Hỗ trợ

Nếu gặp vấn đề:
1. Kiểm tra logs trong console output
2. Xem file kết quả để biết phương pháp nào fail
3. Thử chạy từng phương pháp riêng để isolate vấn đề
4. Kiểm tra dependencies đã được cài đặt đầy đủ chưa
