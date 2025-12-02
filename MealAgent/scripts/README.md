# MealAgent Scripts

Scripts for maintaining and processing MealAgent data.

## precompute_recipe_macros.py

Precomputes nutrition macros for all recipes in Weaviate to improve system performance.

### Usage

```bash
# Process all recipes missing macros
python -m MealAgent.scripts.precompute_recipe_macros

# Process only first 50 recipes
python -m MealAgent.scripts.precompute_recipe_macros --limit 50

# Process in smaller batches (default: 10)
python -m MealAgent.scripts.precompute_recipe_macros --batch-size 5

# Skip recipes that already have macros (recommended)
python -m MealAgent.scripts.precompute_recipe_macros --resume

# Dry run to see what would be done
python -m MealAgent.scripts.precompute_recipe_macros --dry-run

# Specify LM model + API key (overrides env/settings)
python -m MealAgent.scripts.precompute_recipe_macros --resume --lm-model gpt-4o-mini --lm-api-key <YOUR_KEY>

# Combine options
python -m MealAgent.scripts.precompute_recipe_macros --limit 100 --batch-size 5 --resume --lm-model gpt-4o-mini
```

### Options

- `--limit N`: Maximum number of recipes to process (default: all)
- `--batch-size N`: Number of recipes to process in each batch (default: 10)
- `--resume`: Skip recipes that already have `macros_per_serving` (recommended)
- `--dry-run`: Show what would be done without actually updating Weaviate
- `--lm-model`: Override the LM model used for ingredient translation
- `--lm-api-key`: Provide the API key for the LM (if not already set via environment)

### Requirements

- Weaviate must be running and accessible
- `OPENAI_API_KEY` or `ANTHROPIC_API_KEY` environment variable set (for ingredient translation)
- Recipes must have `ingredients_with_qty` or `ingredients` fields populated

### Output

- Progress logs to console
- Detailed log file: `precompute_macros_YYYYMMDD_HHMMSS.log`
- Summary statistics at the end

### Example Output

```text
2025-12-02 12:00:00 - INFO - Recipe Macros Precomputation Script
2025-12-02 12:00:01 - INFO - Fetched 150 recipes to process
2025-12-02 12:00:02 - INFO - Processing batch 1/15 (10 recipes)
2025-12-02 12:00:05 - INFO - [1/150] Processing: Phở Bò (ID: 3257)
2025-12-02 12:00:08 - INFO -   ✅ Success! Macros: 450 kcal, 25.5g protein
...
2025-12-02 12:15:00 - INFO - FINAL SUMMARY
2025-12-02 12:15:00 - INFO - Total recipes: 150
2025-12-02 12:15:00 - INFO - Successfully processed: 142
2025-12-02 12:15:00 - INFO - Failed: 5
2025-12-02 12:15:00 - INFO - Skipped: 3
2025-12-02 12:15:00 - INFO - Time taken: 900.0 seconds (15.0 minutes)
```

### Notes

- The script processes recipes sequentially to avoid overwhelming the API
- Recipes without ingredients are automatically skipped
- Failed calculations are logged but don't stop the process
- Use `--resume` to safely re-run the script and only process new recipes

## validate_recipe_macros.py

Audits existing `macros_per_serving` entries with Gemini (or whichever base model Elysia is using). When the LLM flags a recipe as unrealistic, it proposes updated macros and the script writes them back to Weaviate.

### Usage

```bash
# Review all recipes with cached macros
python -m MealAgent.scripts.validate_recipe_macros

# Limit to 25 recipes, 5 at a time
python -m MealAgent.scripts.validate_recipe_macros --limit 25 --batch-size 5

# Dry run (only reports issues, no updates)
python -m MealAgent.scripts.validate_recipe_macros --dry-run

# Override LM if needed
python -m MealAgent.scripts.validate_recipe_macros --lm-model gpt-4o-mini --lm-api-key <YOUR_KEY>
```

### Options

- `--limit N`: Max recipes to inspect (default: all recipes with macros)
- `--batch-size N`: Recipes per batch (default: 10)
- `--dry-run`: Only log proposed changes
- `--lm-model`, `--lm-api-key`: Optional overrides; by default the script reuses the same LM configuration as MealAgent

### What it does

1. Fetches recipes that already have `macros_per_serving`.
2. Sends dish name, ingredients, macros, and cooking notes to the LLM.
3. If the verdict is `adjust`, the script writes the LLM-proposed macros back to Weaviate (unless `--dry-run`).
4. Adds `macro_validation_note` and `macro_validated_at` metadata so you can track why/when an adjustment took place.

### Logs

- Output is streamed to console and stored in `validate_macros_YYYYMMDD_HHMMSS.log`.
- Final summary includes token usage so you can track how expensive a validation pass was.
