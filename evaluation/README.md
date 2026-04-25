# MealAgent Evaluation Framework

This folder contains the evaluation tooling currently maintained for MealAgent.

Supported methods:

- `nutrition_error`: compares meal-plan or meal-log macro totals against user nutrition targets.
- `llm_judge`: asks configured LLM judges to score plan quality, variety, balance, and feasibility.

Generated outputs are written to `evaluation/results/`, which is intentionally ignored by Git.

## Setup

From the repository root, install the development environment:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/setup-dev.ps1
```

For LLM Judge, configure an API key in `.env`:

```env
GEMINI_API_KEY=your-api-key
OPENROUTER_API_KEY=your-openrouter-key
```

For Weaviate-backed evaluation, use either local Docker Weaviate or Weaviate Cloud:

```env
WEAVIATE_IS_LOCAL=true
LOCAL_WEAVIATE_PORT=8078
LOCAL_WEAVIATE_GRPC_PORT=50051
```

or:

```env
WEAVIATE_IS_LOCAL=false
WCD_URL=https://your-cluster.weaviate.network
WCD_API_KEY=your-weaviate-cloud-key
```

## Run individual methods

### Nutrition Error

```powershell
# Load all available evaluation data from Weaviate, falling back to mock data if needed.
.\.venv\Scripts\python.exe -m evaluation.scripts.run_single_method nutrition_error

# Force mock data for a quick smoke test.
.\.venv\Scripts\python.exe -m evaluation.scripts.run_single_method nutrition_error --use-mock

# Load only selected users.
.\.venv\Scripts\python.exe -m evaluation.scripts.run_single_method nutrition_error --no-load-all --user-ids user1 user2
```

Output: `evaluation/results/nutrition_error_test.json` and `evaluation/results/nutrition_error_summary.md`.

### LLM Judge

```powershell
# Run all configured judge models.
.\.venv\Scripts\python.exe -m evaluation.scripts.run_single_method llm_judge

# Run a specific judge model.
.\.venv\Scripts\python.exe -m evaluation.scripts.run_single_method llm_judge --llm-model google/gemini-3-flash-preview
```

Outputs include per-model JSON/Markdown summaries and an all-model comparison in `evaluation/results/`.

## Run the scenario runner

```powershell
# Use generated plans when MealAgent is available.
.\.venv\Scripts\python.exe -m evaluation.scripts.run_evaluation

# Use mock plans for a faster smoke test.
.\.venv\Scripts\python.exe -m evaluation.scripts.run_evaluation --use-mock

# Limit methods and scenarios.
.\.venv\Scripts\python.exe -m evaluation.scripts.run_evaluation --methods nutrition_error llm_judge --scenarios scenario_1
```

## Metrics

### Nutrition Error

Nutrition Error computes absolute and percentage differences between actual plan/log macro totals and target user profile values:

- protein grams
- carbohydrate grams
- fat grams
- calories
- overall aggregate error

This metric is deterministic and does not require an LLM API key.

### LLM-as-a-Judge

LLM Judge scores plans on:

- overall quality
- nutrition
- variety
- balance
- feasibility
- strengths and improvement suggestions

This method requires provider credentials and internet access.

## Troubleshooting

### `ModuleNotFoundError`

Run commands from the repository root after `scripts/setup-dev.ps1` has completed.

### Weaviate is unavailable

Start local services with:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/start-system.ps1
```

The nutrition evaluator can also run with mock data:

```powershell
.\.venv\Scripts\python.exe -m evaluation.scripts.run_single_method nutrition_error --use-mock
```

### LLM Judge API errors

Check `.env` for the required provider key and verify that the selected model is available from your account.

## Folder layout

```text
evaluation/
├── metrics/
│   ├── llm_judge.py
│   └── nutrition_error.py
├── scripts/
│   ├── generate_llm_summary_only.py
│   ├── run_evaluation.py
│   └── run_single_method.py
├── utils/
│   └── weaviate_data_loader.py
└── results/        # generated, ignored by Git
```

## Notes

The public CLI and documentation only list the maintained methods above. Older internal experiments with additional semantic metrics are not included in the current repository.
