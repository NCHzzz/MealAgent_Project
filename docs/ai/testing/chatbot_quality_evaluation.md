---
phase: testing
title: Đánh Giá Chất Lượng Câu Trả Lời Chatbot
description: Hướng dẫn đánh giá chất lượng câu trả lời của hệ thống chatbot MealAgent
---

# Đánh Giá Chất Lượng Câu Trả Lời Chatbot

Tài liệu này mô tả các phương pháp đánh giá chất lượng câu trả lời của chatbot MealAgent.

## 📋 Tổng Quan

Đánh giá chất lượng chatbot bao gồm:
1. **Relevance** - Câu trả lời có liên quan đến câu hỏi không?
2. **Accuracy** - Thông tin có chính xác không?
3. **Completeness** - Câu trả lời có đầy đủ thông tin không?
4. **Helpfulness** - Câu trả lời có hữu ích không?
5. **Clarity** - Câu trả lời có rõ ràng, dễ hiểu không?
6. **Tone & Politeness** - Giọng điệu có phù hợp không?

---

## 1. Phương Pháp Đánh Giá

### 1.1 Human Evaluation (Đánh Giá Bởi Con Người)

**Ưu điểm**: Chính xác nhất, hiểu được ngữ cảnh và ý định người dùng

**Cách làm**:
1. Chuẩn bị test dataset với các câu hỏi đa dạng
2. Cho chatbot trả lời các câu hỏi
3. Người đánh giá (evaluators) rate từng câu trả lời theo các tiêu chí
4. Tính toán metrics từ ratings

**Rating Scale**:
- **Relevance**: 1-5 (1=không liên quan, 5=rất liên quan)
- **Accuracy**: 1-5 (1=sai hoàn toàn, 5=hoàn toàn chính xác)
- **Completeness**: 1-5 (1=thiếu nhiều, 5=đầy đủ)
- **Helpfulness**: 1-5 (1=không hữu ích, 5=rất hữu ích)
- **Clarity**: 1-5 (1=khó hiểu, 5=rất rõ ràng)
- **Overall**: 1-5 (tổng thể)

### 1.2 Automated Evaluation (Đánh Giá Tự Động)

**Ưu điểm**: Nhanh, có thể chạy tự động, scalable

**Metrics tự động**:
- **BLEU Score**: So sánh với reference answers
- **ROUGE Score**: Đo độ overlap với reference
- **Semantic Similarity**: Đo độ tương đồng ngữ nghĩa (cosine similarity)
- **Response Length**: Độ dài câu trả lời
- **Response Time**: Thời gian phản hồi

### 1.3 User Feedback Analysis (Phân Tích Feedback Người Dùng)

**Ưu điểm**: Dữ liệu thực tế từ người dùng, phản ánh trải nghiệm thực

**Cách làm**:
1. Thu thập feedback từ người dùng (đã có trong hệ thống: -2, -1, 1, 2)
2. Phân tích feedback patterns
3. Xác định các vấn đề phổ biến
4. Cải thiện dựa trên feedback

---

## 2. Test Dataset

### 2.1 Tạo Test Dataset

Test dataset nên bao gồm các loại câu hỏi:

#### A. Câu Hỏi Về Meal Planning
```python
test_cases = [
    {
        "query": "Tạo kế hoạch bữa ăn hôm nay cho tôi",
        "expected_topics": ["meal plan", "daily plan", "breakfast", "lunch", "dinner"],
        "expected_actions": ["plan_day_e2e_tool"],
        "category": "meal_planning"
    },
    {
        "query": "Tôi muốn kế hoạch bữa ăn cho cả tuần",
        "expected_topics": ["weekly plan", "7 days", "variety"],
        "expected_actions": ["plan_week_e2e_tool"],
        "category": "meal_planning"
    }
]
```

#### B. Câu Hỏi Về Nutrition
```python
{
    "query": "Tôi cần bao nhiêu calo mỗi ngày?",
    "expected_topics": ["TDEE", "calories", "macros"],
    "expected_actions": ["macro_calc_tool"],
    "category": "nutrition"
}
```

#### C. Câu Hỏi Về Cooking
```python
{
    "query": "Hướng dẫn tôi nấu phở bò",
    "expected_topics": ["cooking", "steps", "recipe"],
    "expected_actions": ["cook_mode_tool"],
    "category": "cooking"
}
```

#### D. Câu Hỏi Về Constraints
```python
{
    "query": "Tôi ăn chay, không ăn đậu phộng",
    "expected_topics": ["vegetarian", "allergen", "constraints"],
    "expected_actions": ["constraints_guard_tool"],
    "category": "constraints"
}
```

#### E. Câu Hỏi Phức Tạp
```python
{
    "query": "Tôi muốn giảm cân, tạo kế hoạch bữa ăn và hướng dẫn nấu",
    "expected_topics": ["weight loss", "meal plan", "cooking"],
    "expected_actions": ["plan_day_e2e_tool", "cook_mode_tool"],
    "category": "complex"
}
```

### 2.2 Ground Truth Answers

Với mỗi test case, cần có:
- **Expected Response Structure**: Các tools nào nên được gọi
- **Expected Content**: Nội dung chính nên có trong response
- **Expected Format**: Format của response (có steps không, có plan không, etc.)

---

## 3. Evaluation Metrics

### 3.1 Relevance Score

**Định nghĩa**: Câu trả lời có liên quan đến câu hỏi không?

**Cách tính**:
```python
def calculate_relevance_score(query, response, evaluator_rating=None):
    """
    Tính relevance score.
    
    Nếu có human rating: sử dụng rating (1-5)
    Nếu không: tính semantic similarity
    """
    if evaluator_rating:
        return evaluator_rating / 5.0  # Normalize to 0-1
    
    # Automated: semantic similarity
    query_embedding = get_embedding(query)
    response_embedding = get_embedding(response)
    similarity = cosine_similarity(query_embedding, response_embedding)
    return similarity
```

**Target**: >0.8 (80% relevant)

### 3.2 Accuracy Score

**Định nghĩa**: Thông tin trong câu trả lời có chính xác không?

**Cách tính**:
- Kiểm tra facts (nutrition values, recipe steps, etc.)
- So sánh với ground truth data
- Verify không có contradictions

```python
def calculate_accuracy_score(response, ground_truth):
    """
    Tính accuracy bằng cách so sánh với ground truth.
    """
    # Extract facts từ response
    facts = extract_facts(response)
    
    # So sánh với ground truth
    correct_facts = 0
    for fact in facts:
        if fact_matches_ground_truth(fact, ground_truth):
            correct_facts += 1
    
    return correct_facts / len(facts) if facts else 0.0
```

**Target**: >0.95 (95% accurate)

### 3.3 Completeness Score

**Định nghĩa**: Câu trả lời có đầy đủ thông tin cần thiết không?

**Cách tính**:
```python
def calculate_completeness_score(response, expected_topics):
    """
    Kiểm tra response có đề cập đến tất cả expected topics không.
    """
    mentioned_topics = extract_topics(response)
    
    covered_topics = set(mentioned_topics) & set(expected_topics)
    completeness = len(covered_topics) / len(expected_topics) if expected_topics else 1.0
    
    return completeness
```

**Target**: >0.85 (85% complete)

### 3.4 Helpfulness Score

**Định nghĩa**: Câu trả lời có hữu ích, giải quyết được vấn đề của người dùng không?

**Cách tính**:
- Human evaluation (1-5 rating)
- Hoặc dựa trên user feedback (nếu có)

**Target**: >4.0/5.0

### 3.5 Clarity Score

**Định nghĩa**: Câu trả lời có rõ ràng, dễ hiểu không?

**Cách tính**:
```python
def calculate_clarity_score(response):
    """
    Tính clarity dựa trên:
    - Độ dài câu (không quá dài)
    - Cấu trúc (có headings, bullets không)
    - Readability score
    """
    # Average sentence length
    sentences = response.split('.')
    avg_sentence_length = sum(len(s.split()) for s in sentences) / len(sentences)
    
    # Có structure không (headings, bullets)
    has_structure = bool(re.search(r'^[-*•]|^#', response, re.MULTILINE))
    
    # Readability (Flesch Reading Ease approximation)
    readability = calculate_readability(response)
    
    # Combine scores
    clarity = (
        (1.0 if avg_sentence_length < 20 else 0.7) * 0.4 +
        (1.0 if has_structure else 0.5) * 0.3 +
        readability * 0.3
    )
    
    return clarity
```

**Target**: >0.8

### 3.6 Overall Quality Score

**Định nghĩa**: Tổng hợp tất cả các metrics

**Cách tính**:
```python
def calculate_overall_quality(relevance, accuracy, completeness, helpfulness, clarity):
    """
    Tính overall quality score với weights.
    """
    weights = {
        "relevance": 0.25,
        "accuracy": 0.25,
        "completeness": 0.20,
        "helpfulness": 0.20,
        "clarity": 0.10
    }
    
    overall = (
        relevance * weights["relevance"] +
        accuracy * weights["accuracy"] +
        completeness * weights["completeness"] +
        helpfulness * weights["helpfulness"] +
        clarity * weights["clarity"]
    )
    
    return overall
```

**Target**: >0.85 (85% overall quality)

---

## 4. Evaluation Process

### 4.1 Chuẩn Bị

1. **Tạo Test Dataset**: 
   - 50-100 câu hỏi đa dạng
   - Cover tất cả các use cases chính
   - Bao gồm edge cases

2. **Setup Evaluation Environment**:
   - Kết nối với chatbot API
   - Setup logging để lưu responses
   - Chuẩn bị evaluation tools

### 4.2 Thu Thập Responses

```python
async def collect_responses(test_cases):
    """
    Gửi queries đến chatbot và thu thập responses.
    """
    results = []
    
    for test_case in test_cases:
        query = test_case["query"]
        
        # Gửi query đến chatbot
        response = await chatbot.process_query(query)
        
        results.append({
            "query": query,
            "response": response,
            "test_case": test_case,
            "timestamp": datetime.now()
        })
    
    return results
```

### 4.3 Đánh Giá

#### A. Human Evaluation
```python
def human_evaluate(response_data):
    """
    Người đánh giá rate response theo các tiêu chí.
    """
    print(f"Query: {response_data['query']}")
    print(f"Response: {response_data['response']}")
    
    ratings = {
        "relevance": int(input("Relevance (1-5): ")),
        "accuracy": int(input("Accuracy (1-5): ")),
        "completeness": int(input("Completeness (1-5): ")),
        "helpfulness": int(input("Helpfulness (1-5): ")),
        "clarity": int(input("Clarity (1-5): "))
    }
    
    return ratings
```

#### B. Automated Evaluation
```python
def automated_evaluate(response_data):
    """
    Đánh giá tự động.
    """
    query = response_data["query"]
    response = response_data["response"]
    test_case = response_data["test_case"]
    
    scores = {
        "relevance": calculate_relevance_score(query, response),
        "accuracy": calculate_accuracy_score(response, test_case.get("ground_truth")),
        "completeness": calculate_completeness_score(response, test_case.get("expected_topics", [])),
        "clarity": calculate_clarity_score(response)
    }
    
    return scores
```

### 4.4 Phân Tích Kết Quả

```python
def analyze_results(evaluation_results):
    """
    Phân tích kết quả đánh giá.
    """
    # Tính average scores
    avg_scores = {
        "relevance": statistics.mean([r["relevance"] for r in evaluation_results]),
        "accuracy": statistics.mean([r["accuracy"] for r in evaluation_results]),
        "completeness": statistics.mean([r["completeness"] for r in evaluation_results]),
        "helpfulness": statistics.mean([r["helpfulness"] for r in evaluation_results]),
        "clarity": statistics.mean([r["clarity"] for r in evaluation_results])
    }
    
    # Overall quality
    avg_scores["overall"] = calculate_overall_quality(**avg_scores)
    
    # Identify weak areas
    weak_areas = [k for k, v in avg_scores.items() if v < 0.8]
    
    # Category breakdown
    category_scores = {}
    for category in ["meal_planning", "nutrition", "cooking", "constraints"]:
        category_results = [r for r in evaluation_results if r["category"] == category]
        if category_results:
            category_scores[category] = statistics.mean([r["overall"] for r in category_results])
    
    return {
        "average_scores": avg_scores,
        "weak_areas": weak_areas,
        "category_scores": category_scores
    }
```

---

## 5. User Feedback Analysis

### 5.1 Phân Tích Feedback Từ Database

Hệ thống đã có feedback collection (`ELYSIA_FEEDBACK__`) với feedback values: -2, -1, 1, 2

```python
async def analyze_user_feedback(client):
    """
    Phân tích feedback từ người dùng.
    """
    feedback_collection = client.collections.get("ELYSIA_FEEDBACK__")
    
    # Aggregate feedback
    all_feedback = await feedback_collection.aggregate.over_all(
        return_metrics=[Metrics("feedback").number(mean=True, count=True)]
    )
    
    # Feedback by value
    feedback_by_value = {}
    for value in [-2, -1, 1, 2]:
        filters = Filter.by_property("feedback").equal(value)
        count = await feedback_collection.aggregate.over_all(
            filters=filters,
            return_metrics=[Metrics("feedback").number(count=True)]
        )
        feedback_by_value[value] = count.properties["feedback"].count
    
    # Identify patterns in negative feedback
    negative_feedback = await feedback_collection.query.fetch_objects(
        filters=Filter.by_property("feedback").less_than(0),
        limit=100
    )
    
    # Analyze common issues
    common_issues = analyze_negative_feedback_patterns(negative_feedback)
    
    return {
        "average_feedback": all_feedback.properties["feedback"].mean,
        "total_feedback": all_feedback.properties["feedback"].count,
        "feedback_distribution": feedback_by_value,
        "common_issues": common_issues
    }
```

### 5.2 Xác Định Vấn Đề Phổ Biến

```python
def analyze_negative_feedback_patterns(negative_feedback):
    """
    Phân tích patterns trong negative feedback để tìm vấn đề.
    """
    issues = {
        "incorrect_information": 0,
        "incomplete_response": 0,
        "wrong_tool_called": 0,
        "unclear_response": 0,
        "irrelevant_response": 0
    }
    
    for feedback_obj in negative_feedback.objects:
        user_prompt = feedback_obj.properties["user_prompt"]
        route = feedback_obj.properties.get("route", [])
        
        # Analyze based on route and user prompt
        # (Cần implement logic cụ thể)
        
    return issues
```

---

## 6. Continuous Evaluation

### 6.1 Automated Evaluation Pipeline

Chạy evaluation tự động định kỳ:

```python
# scripts/evaluate_chatbot_quality.py
async def run_continuous_evaluation():
    """
    Chạy evaluation tự động hàng tuần.
    """
    # Load test dataset
    test_cases = load_test_dataset("test_cases.json")
    
    # Collect responses
    responses = await collect_responses(test_cases)
    
    # Evaluate
    results = []
    for response_data in responses:
        scores = automated_evaluate(response_data)
        results.append(scores)
    
    # Analyze
    analysis = analyze_results(results)
    
    # Save report
    save_evaluation_report(analysis)
    
    # Alert if quality drops
    if analysis["average_scores"]["overall"] < 0.85:
        send_alert("Chatbot quality below threshold!")
```

### 6.2 Evaluation Dashboard

Tạo dashboard để track quality metrics theo thời gian:

**Metrics to Track**:
- Overall Quality Score (trend)
- Relevance Score (trend)
- Accuracy Score (trend)
- User Feedback Distribution
- Common Issues

---

## 7. Best Practices

### 7.1 Test Dataset
- **Diversity**: Cover tất cả use cases
- **Real-world**: Sử dụng queries thực tế từ users
- **Edge Cases**: Bao gồm các trường hợp khó

### 7.2 Evaluation Frequency
- **Weekly**: Automated evaluation với test dataset
- **Monthly**: Human evaluation với sample
- **Continuous**: Monitor user feedback

### 7.3 Action Items
- **Quality Drop**: Investigate và fix ngay
- **Common Issues**: Prioritize fixes
- **User Feedback**: Address negative feedback patterns

---

## 8. Evaluation Checklist

### Setup
- [ ] Tạo test dataset (50-100 queries)
- [ ] Setup evaluation environment
- [ ] Chuẩn bị evaluation tools

### Evaluation
- [ ] Thu thập responses từ chatbot
- [ ] Human evaluation (nếu có)
- [ ] Automated evaluation
- [ ] Phân tích user feedback

### Analysis
- [ ] Tính toán metrics
- [ ] Xác định weak areas
- [ ] Tạo evaluation report
- [ ] Đề xuất improvements

### Action
- [ ] Fix issues được xác định
- [ ] Update chatbot dựa trên findings
- [ ] Re-evaluate sau khi fix

---

**Last Updated**: 2025-01-27
**Owner**: MealAgent Development Team

