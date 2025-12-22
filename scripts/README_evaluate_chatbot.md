# Hướng Dẫn Đánh Giá Chất Lượng Chatbot - Từng Bước

Script này đánh giá chất lượng câu trả lời của chatbot MealAgent với các metrics chi tiết.

## 📋 Mục Lục

1. [Chuẩn Bị](#chuẩn-bị)
2. [Hướng Dẫn Test Từng Bước](#hướng-dẫn-test-từng-bước)
3. [Kiểm Tra Kết Quả](#kiểm-tra-kết-quả)
4. [Troubleshooting](#troubleshooting)
5. [Metrics Chi Tiết](#metrics-chi-tiết)

---

## Chuẩn Bị

### Bước 1: Kiểm Tra Prerequisites

Trước khi bắt đầu, đảm bảo bạn có:

- ✅ Python 3.8+ đã cài đặt
- ✅ Virtual environment đã được activate (nếu có)
- ✅ Tất cả dependencies đã được cài đặt
- ✅ Weaviate database đang chạy (nếu muốn test với real data)
- ✅ API keys đã được setup (nếu cần)

**Kiểm tra Python version:**
```bash
python --version
# Output: Python 3.8.x hoặc cao hơn
```

**Kiểm tra dependencies:**
```bash
python -c "import elysia; import MealAgent; print('✅ Dependencies OK')"
```

### Bước 2: Setup Environment Variables

#### Option A: Sử dụng Environment Variables (Recommended)

**Trên Windows (PowerShell):**
```powershell
$env:WCD_URL="https://your-cluster.weaviate.network"
$env:WCD_API_KEY="your_api_key_here"
$env:OPENAI_API_KEY="sk-your_openai_key"
```

**Trên Linux/Mac:**
```bash
export WCD_URL="https://your-cluster.weaviate.network"
export WCD_API_KEY="your_api_key_here"
export OPENAI_API_KEY="sk-your_openai_key"
```

#### Option B: Sử dụng .env file

Tạo file `.env` trong thư mục root của project:

```bash
# .env
WCD_URL=https://your-cluster.weaviate.network
WCD_API_KEY=your_api_key_here
OPENAI_API_KEY=sk-your_openai_key
```

**Verify environment variables:**
```bash
# Windows PowerShell
echo $env:WCD_URL

# Linux/Mac
echo $WCD_URL
```

### Bước 3: Verify Weaviate Connection (Optional)

Nếu bạn muốn test với real data, verify Weaviate connection:

```bash
python -c "
import os
import weaviate
from weaviate.classes.init import Auth

wcd_url = os.getenv('WCD_URL')
wcd_api_key = os.getenv('WCD_API_KEY')

if wcd_url and wcd_api_key:
    try:
        client = weaviate.connect_to_weaviate_cloud(
            cluster_url=wcd_url,
            auth_credentials=Auth.api_key(wcd_api_key)
        )
        print('✅ Weaviate connection successful')
        client.close()
    except Exception as e:
        print(f'❌ Weaviate connection failed: {e}')
else:
    print('⚠️ WCD_URL or WCD_API_KEY not set')
"
```

---

## Hướng Dẫn Test Từng Bước

### 🎯 Test Case 1: Quick Test (5 phút)

**Mục đích**: Kiểm tra script hoạt động cơ bản

#### Bước 1.1: Tạo Test Dataset Mẫu

```bash
cd d:\meal_agent_dev\meal_agent_dev
python scripts/evaluate_chatbot_quality.py --create-sample
```

**Expected Output:**
```
✅ Sample test dataset đã được tạo: test_cases_chatbot.json
```

**Verify file được tạo:**
```bash
# Windows PowerShell
Test-Path test_cases_chatbot.json
# Output: True

# Linux/Mac
ls -lh test_cases_chatbot.json
```

#### Bước 1.2: Xem Nội Dung Test Dataset

```bash
# Windows PowerShell
Get-Content test_cases_chatbot.json | ConvertFrom-Json | ConvertTo-Json -Depth 10

# Linux/Mac
cat test_cases_chatbot.json | python -m json.tool
```

**Expected**: File chứa 10 test cases với các queries khác nhau

#### Bước 1.3: Chạy Test Với 1 Query Đơn Giản

Tạo file test nhỏ để test nhanh:

```bash
# Tạo file test_single.json
cat > test_single.json << 'EOF'
[
  {
    "query": "Tạo kế hoạch bữa ăn hôm nay cho tôi",
    "expected_topics": ["meal plan", "daily plan", "breakfast", "lunch", "dinner"],
    "expected_actions": ["plan_day_e2e_tool"],
    "category": "meal_planning",
    "ground_truth": {
      "should_have": ["breakfast", "lunch", "dinner"],
      "should_include": ["macros", "nutrition"]
    }
  }
]
EOF
```

Chạy test:
```bash
python scripts/evaluate_chatbot_quality.py --test-dataset test_single.json --user-id test_user_001
```

**Expected Output:**
```
🔍 Đang đánh giá 1 test cases...

[1/1] Query: Tạo kế hoạch bữa ăn hôm nay cho tôi...
  ⏱️  Response time: X.XXs
  📝 Response length: XXX chars
  🔧 Tools called: plan_day_e2e_tool
  ✅ Tools match: 1.00 (expected: plan_day_e2e_tool)
  📊 Relevance: 0.XX
  📊 Accuracy: 0.XX
  📊 Completeness: 0.XX
  📊 Clarity: 0.XX
  📊 Overall: 0.XX

📊 TÓM TẮT ĐÁNH GIÁ CHẤT LƯỢNG CHATBOT
============================================================
...
```

**✅ Success Criteria:**
- Script chạy không có lỗi
- Response được generate
- Scores được tính toán
- File kết quả được tạo

---

### 🎯 Test Case 2: Full Evaluation (15-30 phút)

**Mục đích**: Đánh giá đầy đủ với test dataset

#### Bước 2.1: Chuẩn Bị Test Dataset

```bash
# Sử dụng test dataset mẫu đã tạo
# Hoặc tạo custom dataset
python scripts/evaluate_chatbot_quality.py --create-sample
```

#### Bước 2.2: Chạy Full Evaluation

```bash
python scripts/evaluate_chatbot_quality.py \
    --test-dataset test_cases_chatbot.json \
    --user-id eval_user_$(date +%Y%m%d) \
    --output-dir evaluation_results_$(date +%Y%m%d)
```

**Expected Progress:**
```
🔍 Đang đánh giá 10 test cases...

[1/10] Query: Tạo kế hoạch bữa ăn hôm nay cho tôi...
  ⏱️  Response time: 3.45s
  📝 Response length: 1250 chars
  🔧 Tools called: plan_day_e2e_tool
  ✅ Tools match: 1.00
  📊 Relevance: 0.85
  📊 Accuracy: 0.92
  📊 Completeness: 0.88
  📊 Clarity: 0.82
  📊 Overall: 0.87

[2/10] Query: Tôi muốn kế hoạch bữa ăn cho cả tuần...
  ...
```

**⏱️ Expected Time:**
- Mỗi query: 3-10 giây (tùy vào complexity)
- 10 queries: ~30-100 giây
- Với LLM calls: có thể lâu hơn

#### Bước 2.3: Monitor Progress

Script sẽ hiển thị progress real-time. Nếu muốn log vào file:

```bash
python scripts/evaluate_chatbot_quality.py \
    --test-dataset test_cases_chatbot.json \
    --user-id eval_user \
    2>&1 | tee evaluation_log.txt
```

---

### 🎯 Test Case 3: Phân Tích User Feedback

**Mục đích**: Phân tích feedback từ database

#### Bước 3.1: Verify Weaviate Connection

```bash
# Verify environment variables
echo $WCD_URL
echo $WCD_API_KEY

# Test connection
python -c "
import os
import weaviate
from weaviate.classes.init import Auth

client = weaviate.connect_to_weaviate_cloud(
    cluster_url=os.getenv('WCD_URL'),
    auth_credentials=Auth.api_key(os.getenv('WCD_API_KEY'))
)
print('✅ Connected')
client.close()
"
```

#### Bước 3.2: Chạy Feedback Analysis

```bash
python scripts/evaluate_chatbot_quality.py --analyze-feedback
```

**Expected Output:**
```
📊 Đang phân tích user feedback...

📈 Tổng số feedback: 150

📊 Phân bố Feedback:
  - negative: 5 (3.3%)
  - positive: 120 (80.0%)
  - superpositive: 25 (16.7%)

📊 Average Feedback Score: 0.87
📊 Satisfaction Rate: 96.7%
📊 Recent Average (7 days): 0.92
```

---

### 🎯 Test Case 4: Comprehensive Evaluation

**Mục đích**: Chạy tất cả đánh giá

#### Bước 4.1: Chạy All-in-One

```bash
python scripts/evaluate_chatbot_quality.py --all \
    --user-id comprehensive_test \
    --output-dir comprehensive_results
```

**Expected Output:**
```
🚀 Bắt đầu đánh giá hệ thống...
📅 Thời gian: 2025-01-27 10:30:00

📊 Đang phân tích user feedback...
...

🔍 Đang đánh giá 10 test cases...
...
```

#### Bước 4.2: Verify All Outputs

```bash
# List files trong output directory
ls -lh chatbot_evaluation_results/

# Expected files:
# - chatbot_evaluation_YYYYMMDD_HHMMSS.json
# - summary_YYYYMMDD_HHMMSS.json
```

---

## Kiểm Tra Kết Quả

### Bước 1: Xem Summary Report

```bash
# Tìm file summary mới nhất
ls -t chatbot_evaluation_results/summary_*.json | head -1

# Xem nội dung (Windows PowerShell)
Get-Content chatbot_evaluation_results/summary_*.json | ConvertFrom-Json | ConvertTo-Json -Depth 10

# Xem nội dung (Linux/Mac)
cat chatbot_evaluation_results/summary_*.json | python -m json.tool
```

**Expected Structure:**
```json
{
  "total_evaluated": 10,
  "average_scores": {
    "relevance": 0.85,
    "accuracy": 0.92,
    "completeness": 0.88,
    "clarity": 0.82,
    "helpfulness": 0.80,
    "overall": 0.85
  },
  "weak_areas": [],
  "performance_metrics": {
    "average_response_time": 3.45,
    "average_response_length": 1250,
    "error_rate": 0.0
  },
  "tool_usage": {
    "plan_day_e2e_tool": 3,
    "cook_mode_tool": 2
  }
}
```

### Bước 2: Phân Tích Weak Areas

Nếu có weak areas (< 0.8), xem chi tiết:

```bash
# Extract weak areas từ summary
python -c "
import json
with open('chatbot_evaluation_results/summary_*.json') as f:
    data = json.load(f)
    print('Weak Areas:', data.get('weak_areas', []))
    print('Worst Queries:')
    for q in data.get('worst_queries', [])[:3]:
        print(f\"  - {q['query'][:60]}... (Score: {q['overall_score']:.2f})\")
"
```

### Bước 3: So Sánh Với Previous Runs

```bash
# Compare 2 summary files
python -c "
import json
import glob

files = sorted(glob.glob('chatbot_evaluation_results/summary_*.json'))[-2:]
if len(files) == 2:
    with open(files[0]) as f1, open(files[1]) as f2:
        old = json.load(f1)
        new = json.load(f2)
        print('Overall Quality Change:')
        print(f\"  Old: {old['average_scores']['overall']:.2f}\")
        print(f\"  New: {new['average_scores']['overall']:.2f}\")
        print(f\"  Change: {(new['average_scores']['overall'] - old['average_scores']['overall']):.2f}\")
"
```

---

## Troubleshooting Chi Tiết

### ❌ Lỗi: "Could not import required modules"

**Nguyên nhân**: Dependencies chưa được cài đặt

**Giải pháp:**

```bash
# 1. Activate virtual environment (nếu có)
# Windows
.\venv\Scripts\activate

# Linux/Mac
source venv/bin/activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Verify installation
python -c "import elysia; import MealAgent; print('✅ OK')"
```

### ❌ Lỗi: "WCD_URL or WCD_API_KEY not set"

**Nguyên nhân**: Environment variables chưa được set

**Giải pháp:**

```bash
# Windows PowerShell
$env:WCD_URL="your_url"
$env:WCD_API_KEY="your_key"

# Verify
echo $env:WCD_URL

# Linux/Mac
export WCD_URL="your_url"
export WCD_API_KEY="your_key"

# Verify
echo $WCD_URL
```

**Note**: Script vẫn chạy được nếu không có Weaviate, chỉ bỏ qua feedback analysis.

### ❌ Lỗi: "No tools available to use!"

**Nguyên nhân**: Tree không có tools được register

**Giải pháp:**

```bash
# Verify MealAgent tools có thể import
python -c "
from MealAgent.tree.meal_tree import build_meal_agent_tree
from elysia.config import Settings
tree = build_meal_agent_tree(settings=Settings())
print(f'✅ Tree created with {len(tree.tools)} tools')
"
```

### ❌ Lỗi: Response Time Quá Lâu (>30s)

**Nguyên nhân**: 
- Network latency
- LLM API slow
- Weaviate query chậm

**Giải pháp:**

```bash
# 1. Test network connection
ping your-weaviate-cluster.weaviate.network

# 2. Test với smaller dataset
python scripts/evaluate_chatbot_quality.py \
    --test-dataset test_single.json

# 3. Check LLM API status
# (tùy vào provider bạn dùng)

# 4. Use timeout
python scripts/evaluate_chatbot_quality.py \
    --test-dataset test_cases_chatbot.json \
    --user-id test_user
    # Script sẽ timeout sau một khoảng thời gian
```

### ❌ Lỗi: "Empty Response"

**Nguyên nhân**: 
- Query không được process đúng
- Tree không yield results
- Error trong tool execution

**Giải pháp:**

```bash
# 1. Check logs
python scripts/evaluate_chatbot_quality.py \
    --test-dataset test_single.json \
    2>&1 | tee debug.log

# 2. Test với simple query
python -c "
import asyncio
from scripts.evaluate_chatbot_quality import create_chatbot_processor
from elysia.config import Settings

async def test():
    processor = await create_chatbot_processor(Settings())
    result = await processor('Xin chào', 'test_user', 'test_conv')
    print('Response:', result['response'][:100])
    print('Tools:', result['tools_called'])

asyncio.run(test())
"

# 3. Check Tree execution
python -c "
from MealAgent.tree.meal_tree import build_meal_agent_tree
from elysia.config import Settings
import asyncio

async def test_tree():
    tree = build_meal_agent_tree(
        settings=Settings(),
        user_id='test',
        conversation_id='test'
    )
    count = 0
    async for result in tree.async_run('Xin chào'):
        count += 1
        if count > 5:
            break
    print(f'✅ Tree yielded {count} results')

asyncio.run(test_tree())
"
```

### ❌ Lỗi: "ModuleNotFoundError: No module named 'MealAgent'"

**Nguyên nhân**: Python path không đúng

**Giải pháp:**

```bash
# 1. Chạy từ project root
cd d:\meal_agent_dev\meal_agent_dev

# 2. Verify Python path
python -c "import sys; print('\n'.join(sys.path))"

# 3. Add project root to PYTHONPATH
# Windows PowerShell
$env:PYTHONPATH="$PWD;$env:PYTHONPATH"

# Linux/Mac
export PYTHONPATH="${PWD}:${PYTHONPATH}"

# 4. Verify import
python -c "import MealAgent; print('✅ OK')"
```

---

## Metrics Chi Tiết

### 1. Relevance (Liên quan)
- **Cách tính**: Keyword overlap + semantic matching
- **Target**: >0.8 (80%)
- **Cải thiện**: 
  - Đảm bảo response đề cập đến keywords trong query
  - Response phải liên quan đến intent của user

### 2. Accuracy (Chính xác)
- **Cách tính**: So sánh với ground truth, kiểm tra contradictions
- **Target**: >0.95 (95%)
- **Cải thiện**:
  - Verify facts trong response
  - Check không có contradictions
  - Đảm bảo numbers và data chính xác

### 3. Completeness (Đầy đủ)
- **Cách tính**: % expected topics được đề cập
- **Target**: >0.85 (85%)
- **Cải thiện**:
  - Đảm bảo tất cả expected topics được cover
  - Response đầy đủ thông tin cần thiết

### 4. Clarity (Rõ ràng)
- **Cách tính**: Sentence length, structure, readability
- **Target**: >0.8 (80%)
- **Cải thiện**:
  - Sử dụng structure (headings, bullets)
  - Câu ngắn gọn (<25 words)
  - Response length hợp lý (20-500 words)

### 5. Helpfulness (Hữu ích)
- **Cách tính**: Dựa trên user feedback hoặc heuristic
- **Target**: >0.8 (80%)
- **Cải thiện**:
  - Response giải quyết được vấn đề của user
  - Cung cấp actionable information

### 6. Overall Quality (Tổng thể)
- **Cách tính**: Weighted average của tất cả metrics
- **Target**: >0.85 (85%)
- **Weights**:
  - Relevance: 25%
  - Accuracy: 25%
  - Completeness: 20%
  - Helpfulness: 20%
  - Clarity: 10%

---

## Best Practices

### 1. Test Dataset Design

**Tốt:**
```json
{
  "query": "Tạo kế hoạch bữa ăn hôm nay cho tôi",
  "expected_topics": ["meal plan", "daily plan", "breakfast", "lunch", "dinner"],
  "expected_actions": ["plan_day_e2e_tool"],
  "category": "meal_planning",
  "ground_truth": {
    "should_have": ["breakfast", "lunch", "dinner"],
    "should_include": ["macros", "nutrition"]
  }
}
```

**Không tốt:**
```json
{
  "query": "test",
  "expected_topics": [],
  "expected_actions": []
}
```

### 2. Regular Evaluation Schedule

- **Daily**: Quick test với 5 queries
- **Weekly**: Full evaluation với test dataset
- **Monthly**: Comprehensive evaluation + feedback analysis

### 3. Track Quality Trends

```bash
# Tạo script để track trends
cat > track_quality.sh << 'EOF'
#!/bin/bash
DATE=$(date +%Y%m%d)
python scripts/evaluate_chatbot_quality.py --all --output-dir "evaluation_${DATE}"
# Compare với previous run
# Generate trend report
EOF
```

### 4. Action Items từ Results

1. **Weak Areas**: Prioritize fixes cho metrics < 0.8
2. **Worst Queries**: Investigate và improve
3. **Error Rate**: Fix bugs nếu error rate > 5%
4. **Response Time**: Optimize nếu > 10s average

---

## Output Example Chi Tiết

```
🚀 Bắt đầu đánh giá hệ thống...
📅 Thời gian: 2025-01-27 10:30:00

📊 Đang phân tích user feedback...

📈 Tổng số feedback: 150

📊 Phân bố Feedback:
  - negative: 5 (3.3%)
  - positive: 120 (80.0%)
  - superpositive: 25 (16.7%)

📊 Average Feedback Score: 0.87
📊 Satisfaction Rate: 96.7%

🔍 Đang đánh giá 10 test cases...

[1/10] Query: Tạo kế hoạch bữa ăn hôm nay cho tôi...
  ⏱️  Response time: 3.45s
  📝 Response length: 1250 chars
  🔧 Tools called: plan_day_e2e_tool
  ✅ Tools match: 1.00 (expected: plan_day_e2e_tool)
  📊 Relevance: 0.85
  📊 Accuracy: 0.92
  📊 Completeness: 0.88
  📊 Clarity: 0.82
  📊 Overall: 0.87

[2/10] Query: Tôi muốn kế hoạch bữa ăn cho cả tuần...
  ...

📊 TÓM TẮT ĐÁNH GIÁ CHẤT LƯỢNG CHATBOT
============================================================

📈 Tổng số đánh giá: 10

📊 Điểm Trung Bình:
  ✅ Relevance: 0.85
  ✅ Accuracy: 0.92
  ✅ Completeness: 0.88
  ✅ Clarity: 0.82
  ✅ Helpfulness: 0.80
  ✅ Overall: 0.85

⏱️  Performance Metrics:
  - Average Response Time: 3.45s
  - Average Response Length: 1250 chars
  - Average Tools Match: 0.95
  - Error Rate: 0.0% (0/10 queries)

🔧 Tool Usage:
  - plan_day_e2e_tool: 3 times
  - cook_mode_tool: 2 times
  - search_and_rank_tool: 2 times
  - macro_calc_tool: 2 times

📂 Điểm theo Category:
  ✅ meal_planning: 0.88
  ✅ cooking: 0.85
  ✅ nutrition: 0.82
  ✅ constraints: 0.90

🔴 Top 5 Queries Kém Nhất:
  1. Query example...
     Overall Score: 0.72
     Tools: tool1, tool2
     Response Time: 5.2s

🟢 Top 5 Queries Tốt Nhất:
  1. Query example...
     Overall Score: 0.95
     Tools: plan_day_e2e_tool
     Response Time: 2.1s

============================================================

✅ Kết quả đã được lưu vào: chatbot_evaluation_results/chatbot_evaluation_20250127_103045.json
✅ Summary đã được lưu vào: chatbot_evaluation_results/summary_20250127_103045.json
```

---

## Quick Reference

### Commands Cheat Sheet

```bash
# Quick test
python scripts/evaluate_chatbot_quality.py --create-sample
python scripts/evaluate_chatbot_quality.py --test-dataset test_cases_chatbot.json

# Full evaluation
python scripts/evaluate_chatbot_quality.py --all

# Feedback analysis
python scripts/evaluate_chatbot_quality.py --analyze-feedback

# Custom user/conversation
python scripts/evaluate_chatbot_quality.py \
    --test-dataset test_cases_chatbot.json \
    --user-id my_user \
    --conversation-id my_conv \
    --output-dir my_results
```

### File Locations

- **Test Dataset**: `test_cases_chatbot.json` (root directory)
- **Results**: `chatbot_evaluation_results/` (root directory)
- **Logs**: Console output hoặc redirect to file

---

## Liên Hệ & Tài Liệu

- **Chi tiết**: `docs/ai/testing/chatbot_quality_evaluation.md`
- **Test Strategy**: `docs/ai/testing/feature-meal-planning-agent.md`
- **Script Source**: `scripts/evaluate_chatbot_quality.py`

## Kết Quả

Kết quả sẽ được lưu trong thư mục `chatbot_evaluation_results/`:

1. **Full Results**: `chatbot_evaluation_YYYYMMDD_HHMMSS.json`
   - Chứa tất cả chi tiết đánh giá từng query
   - Scores, responses, tools called, response times

2. **Summary**: `summary_YYYYMMDD_HHMMSS.json`
   - Tóm tắt metrics tổng thể
   - Average scores, weak areas, best/worst queries

## Metrics Được Đánh Giá

### 1. Relevance (Liên quan)
- Đo độ liên quan giữa query và response
- Target: >0.8 (80%)

### 2. Accuracy (Chính xác)
- Kiểm tra thông tin có chính xác không
- So sánh với ground truth
- Target: >0.95 (95%)

### 3. Completeness (Đầy đủ)
- Response có đề cập đến expected topics không
- Target: >0.85 (85%)

### 4. Clarity (Rõ ràng)
- Độ dài câu, structure, readability
- Target: >0.8 (80%)

### 5. Helpfulness (Hữu ích)
- Dựa trên user feedback hoặc heuristic
- Target: >0.8 (80%)

### 6. Overall Quality (Tổng thể)
- Tổng hợp tất cả metrics với weights
- Target: >0.85 (85%)

## Tùy Chỉnh Test Dataset

Tạo file JSON với format:

```json
[
  {
    "query": "Câu hỏi của người dùng",
    "expected_topics": ["topic1", "topic2"],
    "expected_actions": ["tool1", "tool2"],
    "category": "meal_planning",
    "ground_truth": {
      "should_have": ["content1", "content2"],
      "should_include": ["info1", "info2"]
    }
  }
]
```

## Troubleshooting

### Lỗi: "Could not import required modules"
- Đảm bảo đã cài đặt tất cả dependencies
- Check Python path và virtual environment

### Lỗi: "Client không có"
- Set environment variables WCD_URL và WCD_API_KEY
- Hoặc bỏ qua feedback analysis nếu không cần

### Response Time Quá Lâu
- Check network connection
- Verify Weaviate và API services đang hoạt động
- Consider using smaller test dataset

## Tips

1. **Test Dataset**: Tạo test dataset đa dạng với các use cases thực tế
2. **Regular Evaluation**: Chạy evaluation định kỳ để track quality trends
3. **Compare Results**: So sánh kết quả giữa các versions để detect regressions
4. **Focus on Weak Areas**: Prioritize improvements dựa trên weak areas được identify

## Output Example

```
📊 TÓM TẮT ĐÁNH GIÁ CHẤT LƯỢNG CHATBOT
============================================================

📈 Tổng số đánh giá: 10

📊 Điểm Trung Bình:
  ✅ Relevance: 0.85
  ✅ Accuracy: 0.92
  ✅ Completeness: 0.88
  ✅ Clarity: 0.82
  ✅ Helpfulness: 0.80
  ✅ Overall: 0.85

⏱️  Average Response Time: 3.45s

🔧 Tool Usage:
  - plan_day_e2e_tool: 3 times
  - cook_mode_tool: 2 times
  - search_and_rank_tool: 2 times

📂 Điểm theo Category:
  ✅ meal_planning: 0.88
  ✅ cooking: 0.85
  ✅ nutrition: 0.82

🔴 Top 5 Queries Kém Nhất:
  1. Query example...
     Overall Score: 0.72
     Tools: tool1, tool2

🟢 Top 5 Queries Tốt Nhất:
  1. Query example...
     Overall Score: 0.95
```

## Liên Hệ

Nếu có vấn đề hoặc câu hỏi, xem tài liệu chi tiết tại:
- `docs/ai/testing/chatbot_quality_evaluation.md`

