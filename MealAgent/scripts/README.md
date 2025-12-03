# MealAgent Scripts

## precompute_recipe_macros.py

Calculates macros for recipes stored in Weaviate, optionally enriches metadata, and can run a light LLM validation pass in the same run.

### Quick start

```bash
# Recompute macros for everything missing data (safe defaults)
python -m MealAgent.scripts.precompute_recipe_macros --resume

# Test on a small slice
python -m MealAgent.scripts.precompute_recipe_macros --limit 50 --resume

# Skip metadata calls
python -m MealAgent.scripts.precompute_recipe_macros --resume --no-enrich-metadata

# Validate macros every 50 recipes during the same run
python -m MealAgent.scripts.precompute_recipe_macros --resume --validate-every 50
```

### Options

- `--limit N`: cap how many recipes to fetch
- `--batch-size N`: recipes per batch (default 10)
- `--resume`: skip recipes that already have macros
- `--dry-run`: log actions without writing to Weaviate
- `--no-enrich-metadata`: avoid Gemini/OpenRouter calls for diet/allergen/device tags
- `--metadata-every N`: only enrich metadata every N recipes (default 50 to keep costs down)
- `--validate-every N`: automatically run the LLM macro audit after every N processed recipes (default: disabled)
- `--validate`: after calculation is done, run a separate LLM validation pass over cached macros

Everything else (parallelism, rate limiting, error handling) is fixed inside the script so you don’t have to tune dozens of flags.

### Rate-limit friendly workflow

1. Keep `--metadata-every 50` (or larger) so only every 50th recipe calls the LLM.
2. Use `--validate-every 50` (or 100) if you want inline validation without hammering the API.
3. Use `--no-enrich-metadata` when you only care about macros.
4. Let the script's built-in token report (every 100 recipes) tell you how expensive the run is.
5. Run with `--limit 50` first to confirm credentials and output.
6. Use `--resume` to continue later without reprocessing old recipes.

### Validation-only helper

`python -m MealAgent.scripts.validate_recipe_macros` is a standalone helper if you want to use the LLM to **audit and correct macros** without recalculating them via tools.

It:
- fetches recipes from Weaviate (kể cả các recipe đang thiếu hoặc macros_per_serving không hợp lý),
- gom mỗi batch (mặc định 100 recipe) và gọi LLM **một lần cho cả batch**,
- yêu cầu LLM trả về JSON chuẩn cho từng recipe (verdict, reason, macros_adjusted),
- và có thể cập nhật lại `macros_per_serving` theo đề xuất của LLM.

Flags chính:
- `--limit N`: giới hạn số recipe sẽ audit
- `--batch-size N`: số recipe cho mỗi lần gọi LLM (mặc định 100)
- `--dry-run`: chỉ log đề xuất, **không** ghi lại vào Weaviate
