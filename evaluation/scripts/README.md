# Evaluation Scripts

Các script để chạy evaluation tests cho MealAgent.

## Scripts có sẵn

### 1. `run_evaluation.py`

Script chính để chạy tất cả evaluations.

**Cách sử dụng:**

```bash
# Chạy tất cả evaluations với tất cả scenarios
python -m evaluation.scripts.run_evaluation

# Chạy với mock data (nhanh hơn)
python -m evaluation.scripts.run_evaluation --use-mock

# Chạy với scenarios cụ thể
python -m evaluation.scripts.run_evaluation --scenarios scenario_1 scenario_2

# Chạy với methods cụ thể
python -m evaluation.scripts.run_evaluation --methods nutrition_error llm_judge
```

**Options:**
- `--scenarios`: List of scenario IDs to run (default: all)
- `--methods`: List of methods to run (default: all)
- `--use-mock`: Use mock meal plans instead of generating real ones

### 2. `run_single_method.py`

Script để chạy từng phương pháp evaluation riêng lẻ.

**Cách sử dụng:**

```bash
# Nutrition Error
python -m evaluation.scripts.run_single_method nutrition_error

# RAGAS
python -m evaluation.scripts.run_single_method ragas

# LLM Judge
python -m evaluation.scripts.run_single_method llm_judge

# BERTScore
python -m evaluation.scripts.run_single_method bertscore
```

## Ví dụ

### Ví dụ 1: Quick test

```bash
# Chạy nutrition error test (nhanh nhất)
python -m evaluation.scripts.run_single_method nutrition_error
```

### Ví dụ 2: Full evaluation với mock data

```bash
# Chạy tất cả với mock data
python -m evaluation.scripts.run_evaluation --use-mock
```

### Ví dụ 3: Test LLM Judge

```bash
# Set API key
export GEMINI_API_KEY="your-api-key"

# Chạy test
python -m evaluation.scripts.run_single_method llm_judge
```

### Ví dụ 4: Custom evaluation

```bash
# Chỉ chạy nutrition_error và llm_judge cho scenario_1
python -m evaluation.scripts.run_evaluation \
    --scenarios scenario_1 \
    --methods nutrition_error llm_judge
```

## Kết quả

Kết quả được lưu trong `evaluation/results/`:
- `*_test.json` - Kết quả từng phương pháp
- `evaluation_results_*.json` - Kết quả full evaluation
- `*_summary.csv` - Tóm tắt CSV


