# MealAgent

MealAgent contains the meal-planning domain layer used by this repository's Elysia backend. It provides tools, schemas, migrations, and scripts for generating nutrition-aware meal plans, resolving recipes, managing pantry data, logging meals, and evaluating outputs.

## Key areas

- `tools/plan_day/` - day-level planning workflow.
- `tools/cook_mode/` - recipe/cooking workflow helpers.
- `tools/nutrition/` - macro and nutrition calculations.
- `schemas/` - Weaviate collection definitions.
- `migrations/` - explicit, guarded schema/data migrations.
- `scripts/` - macro precomputation, validation, and collection export helpers.
- `docs/` - data pipeline and planning workflow documentation.

## Setup

From the repository root:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".\elysia[dev]" -e ".\MealAgent"
```

## Weaviate collections

Start local Weaviate first:

```powershell
docker compose -f Docker\docker-compose.yml up -d
```

Create missing collections without dropping existing data:

```powershell
.\.venv\Scripts\python.exe MealAgent\migrations\create_collections.py --create
```

Destructive operations require explicit confirmation:

```powershell
.\.venv\Scripts\python.exe MealAgent\migrations\create_collections.py --drop --yes
```

## Documentation

- [Data pipeline](docs/DATA_PIPELINE.md)
- [Plan-day workflow](docs/PLAN_DAY_WORKFLOW.md)
- [Scripts reference](scripts/README.md)
