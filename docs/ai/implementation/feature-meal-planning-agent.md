---
phase: implementation
title: Implementation Guide - Meal Planning Agent
description: Technical implementation notes, patterns, and code guidelines for MealAgent
---

# Implementation Guide - Meal Planning Agent

## Development Setup
**How do we get started?**

### Prerequisites and Dependencies
- Python 3.11+ (for async generator and type hints)
- Node.js 18+ (for Next.js frontend)
- Docker & Docker Compose (for Weaviate)
- Git

### Environment Setup Steps

1. **Clone Repository**
   ```bash
   git clone <repository-url>
   cd Elysia_cursor
   ```

2. **Backend Setup**
   ```bash
   cd elysia
   python -m venv venv
   source venv/bin/activate  # Windows: venv\Scripts\activate
   pip install -e .  # Installs elysia package in editable mode
   ```

3. **Frontend Setup**
   ```bash
   cd elysia-frontend
   npm install
   ```

4. **Weaviate Setup**
   ```bash
   cd Docker
   docker-compose up -d weaviate
   ```

5. **Create Environment File**
   ```bash
   cp .env.example .env
   # Edit .env with your configuration
   ```

### Configuration Needed

**`.env` File**:
```env
# Weaviate Configuration
WEAVIATE_URL=http://localhost:8080
WEAVIATE_API_KEY=  # Optional for local dev

# OpenAI (optional – used for LLM features; embeddings default to Weaviate text2vec-transformers)
OPENAI_API_KEY=your_key_here
# If you explicitly choose OpenAI embeddings, set a model, otherwise leave unset
# OPENAI_EMBEDDING_MODEL=text-embedding-3-small

# Elysia Settings (see https://weaviate.github.io/elysia/Reference/Settings/)
# Model Configuration
BASE_MODEL=gpt-4o-mini                    # Base model for structured output
COMPLEX_MODEL=gpt-4o                      # Complex model for reasoning
BASE_PROVIDER=openai                      # Provider for base model (e.g., "openai", "openrouter/openai", "anthropic", "gemini")
COMPLEX_PROVIDER=openai                   # Provider for complex model
MODEL_API_BASE=                            # Optional: API base URL (required for ollama/local models)

# Weaviate Configuration (can also be set via Settings.configure())
WCD_URL=http://localhost:8080              # Weaviate Cloud Database URL
WCD_API_KEY=                               # Optional API key for Weaviate
WEAVIATE_IS_LOCAL=True                     # Whether Weaviate is local
LOCAL_WEAVIATE_PORT=8080                   # Local Weaviate HTTP port
LOCAL_WEAVIATE_GRPC_PORT=50051             # Local Weaviate gRPC port

# Custom Weaviate Connection (optional)
WEAVIATE_IS_CUSTOM=False                   # Use custom connection parameters
CUSTOM_HTTP_HOST=                          # Custom HTTP host
CUSTOM_HTTP_PORT=8080                      # Custom HTTP port
CUSTOM_HTTP_SECURE=False                   # Use HTTPS
CUSTOM_GRPC_HOST=                          # Custom gRPC host
CUSTOM_GRPC_PORT=50051                     # Custom gRPC port
CUSTOM_GRPC_SECURE=False                   # Use secure gRPC

# Logging
LOGGING_LEVEL=INFO                         # DEBUG, INFO, WARNING, ERROR, CRITICAL

# API Keys (can also be set via Settings.configure(openai_apikey="..."))
OPENAI_APIKEY=your_key_here                # OpenAI API key
# ANTHROPIC_APIKEY=                        # Anthropic API key (if using Claude)
# GEMINI_APIKEY=                           # Google Gemini API key (if using Gemini)

# Experimental Features
USE_FEEDBACK=False                         # EXPERIMENTAL: Use feedback from previous runs
BASE_USE_REASONING=True                    # Use reasoning output for base model
COMPLEX_USE_REASONING=True                 # Use reasoning output for complex model

# MealAgent Specific
FDC_DATA_PATH=data/fdc/raw
RECIPE_DATA_PATH=data/recipes/raw
DEFAULT_TDEE_MULTIPLIER=1.2  # Sedentary activity level
```

## Code Structure
**How is the code organized?**

### Directory Structure (complete)
```
elysia/
└── elysia/
    ├── MealAgent/
    │   ├── __init__.py
    │   ├── config.py                       # MealAgent-specific settings (optional)
    │   ├── preprocessing/
    │   │   └── preprocessor.py             # Phase 1 warmup/verification
    │   ├── schemas/                        # Weaviate collections
    │   │   ├── recipe.py                   # + macros_per_serving, ingredient_fdc_map
    │   │   ├── fdc_food.py
    │   │   ├── fdc_nutrient.py
    │   │   └── fdc_portion.py
    │   ├── etl/
    │   │   ├── ingest_fdc.py               # Load FdcFood/FdcNutrient/FdcPortion
    │   │   └── ingest_recipes.py           # Load Recipe CSV-aligned fields
    │   ├── tools/                          # Async generator tools
    │   │   ├── profile/
    │   │   │   ├── __init__.py
    │   │   │   ├── profile_crud.py         # Task 2.1.1
    │   │   │   └── macro_calc.py           # Task 2.1.2
    │   │   ├── constraints/
    │   │   │   ├── __init__.py
    │   │   │   └── constraints_guard.py    # Consolidated constraint filtering
    │   │   ├── search/
    │   │   │   ├── __init__.py
    │   │   │   └── search_and_rank.py      # Uses Elysia `query` internally
    │   │   ├── nutrition/
    │   │   │   ├── __init__.py
    │   │   │   └── calculate_recipe_macros.py # VN→EN on-demand + cache
    │   │   ├── plan_day/
    │   │   │   ├── __init__.py
    │   │   │   └── plan_day_e2e.py         # End-to-end daily planning
    │   │   ├── plan_week/
    │   │   │   ├── __init__.py
    │   │   │   └── plan_week_e2e.py        # End-to-end weekly planning (includes variety)
    │   │   ├── pantry/
    │   │   │   ├── __init__.py
    │   │   │   └── pantry_crud.py          # Pantry management
    │   │   ├── shopping/
    │   │   │   ├── __init__.py
    │   │   │   └── pantry_diff.py          # Shopping list with pantry subtraction
    │   │   ├── gap_fill/
    │   │   │   ├── __init__.py
    │   │   │   └── gap_fill.py             # Merged: calc + suggest + apply
    │   │   ├── substitution/
    │   │   │   ├── __init__.py
    │   │   │   └── substitute.py           # Merged: suggest + apply
    │   │   ├── micros/
    │   │   │   ├── __init__.py
    │   │   │   └── micros.py               # Merged: check + suggest
    │   │   ├── meal_logging/
    │   │   │   ├── __init__.py
    │   │   │   ├── log_meal_e2e.py         # End-to-end meal logging
    │   │   │   └── meal_history.py         # View meal history
    │   │   └── cook_mode/
    │   │       ├── __init__.py
    │   │       └── cook_mode.py            # Cooking instructions
    │   ├── tree/
    │   │   ├── __init__.py
    │   │   ├── meal_tree.py                # Task 2.5.1
    │   │   └── config.py                   # Task 2.5.2 tool registration
    │   └── migrations/
    │       └── create_collections.py       # + --drop-only/--create-only
    │
    ├── api/
    │   └── services/                       # UserManager, TreeManager (Elysia built-in)
    │       ├── user.py                     # UserManager
    │       └── tree.py                     # TreeManager
    │
    └── util/
        └── client.py                       # ClientManager

elysia-frontend/
└── app/
    ├── pages/                              # ProfilePage, RecipeExplorer, PlannerPage, etc.
    ├── components/                         # PlanView, ShoppingListView, dialogs
    └── api/                                # Frontend API layer
```

### Module Organization

- **`schemas/`**: Weaviate collection class definitions (one file per collection)
- **`tools/`**: Organized by branch (feature area); each tool is an async generator
- **`tree/`**: Decision tree logic and configuration
- **`etl/`**: Data import pipelines (run once during setup)
- **`utils/`**: Shared helper functions (stateless, pure functions preferred)

### Cooking & Explanation (Phase 4.3)

- `cook_mode_tool` (`elysia/MealAgent/tools/cook_mode/cook_mode.py`)
  - Inputs: optional `food_id`; otherwise reads from `plan_day_e2e_tool.plan` / `plan_week_e2e_tool.plan` / `search_and_rank_tool.topk`
  - Outputs (Environment): `environment["cook_mode_tool"]["steps"]` with fields `index`, `instruction`, `estimated_seconds`
  - Streaming: yields text per step
  - Notes: deterministic from `cooking_method_array`; fallback to `ingredients`

- `cited_summarize` (Elysia built-in from `elysia.tools.text.text.CitedSummarizer`)
  - Inputs: reads context from entire Environment (profile, targets, constraints, ranking, plan, deficits, snacks, substitutes, variety)
  - Outputs: Summary with citations from environment data
  - Notes: Replaces `explain_tool`; provides better citations and is well-tested

API Integration:
- **No custom endpoints needed**: All functionality flows through Elysia's standard `/ws/query` WebSocket endpoint.
- **Natural language queries**: Frontend sends natural language queries like "Show me how to cook recipe_001" or "Why did you choose these recipes?" through the standard WebSocket message format.
- **Tree orchestration**: The Elysia decision tree automatically selects and executes `cook_mode_tool` or `cited_summarize` based on the user's query. No explicit action parameters are needed.
- **WebSocket format**: Use standard Elysia WebSocket message format: `{user_id, conversation_id, query_id, query, collection_names, ...}` (see design doc for full format).

### Naming Conventions

- **Tool files**: `snake_case.py` (e.g., `profile_crud.py`)
- **Tool functions**: `snake_case_tool` (e.g., `profile_crud_tool`) when using `@tool` decorator
- **Environment keys**: `environment[tool_name][name]` where `tool_name` is function name and `name` is Result's name parameter (e.g., `environment["profile_crud_tool"]["profile]")`. See `docs/ai/design/environment_keys.md` for the quick reference of actual keys by tool.
- **Collections**: `PascalCase` (e.g., `Recipe`, `FdcFood`)
- **Functions**: `snake_case` (e.g., `calculate_tdee`)

## Implementation Notes

### Core Features

#### 1. Profile Management (ProfileCRUDTool, MacroCalcTool)
#### Recipe ETL Mapping (demo dataset)
```text
Input CSV columns:
- food_id, dish_name, dish_type, serving_size, cooking_time,
  ingredients_with_qty (text[]), ingredients (text[]),
  cooking_method_array (text[]), image_link

Mapping to Weaviate Recipe properties:
- food_id → Recipe.food_id (text, indexed)
- dish_name → Recipe.dish_name (text) and also copied to Recipe.title for search
- dish_type → Recipe.dish_type (text)
- serving_size → Recipe.serving_size (int)
- cooking_time → Recipe.cooking_time (int)
- ingredients_with_qty → Recipe.ingredients_with_qty (text[])
- ingredients → Recipe.ingredients (text[])
- cooking_method_array → Recipe.cooking_method_array (text[]), and optionally Recipe.directions
- image_link → Recipe.image_link (text)

Vectorization uses Weaviate `text2vec-transformers` (see `ingest_fdc.py` example). Sources should include: dish_name, ingredients_with_qty, ingredients, cooking_method_array.

Cached fields on Recipe (per Design):
- `macros_per_serving` (object with nested properties `kcal`, `protein_g`, `fat_g`, `carb_g`)
- `ingredient_fdc_map` (object[] with nested properties `ingredient_vn`, `ingredient_en`, `fdc_id`, `quantity_g`, `confidence`)
```

#### CalculateRecipeMacrosTool (VN→EN on-demand)
```python
# Purpose: Compute macros_per_serving when missing on Recipe objects
# Strategy: Translate Vietnamese ingredient names to English, find FDC foods, compute and cache macros

async def calculate_recipe_macros_tool(recipe_id: str, client_manager, llm_client) -> Dict[str, float]:
    # 1) Fetch recipe; return cached if present
    # 2) Translate ingredients_with_qty (VN→EN) using LLM JSON mode
    # 3) Search FdcFood via hybrid query; pick best match > threshold
    # 4) Sum kcal/protein/fat/carb using per-100g fields scaled by quantity; divide by serving_size
    # 5) Update Recipe.macros_per_serving and return value
    # 6) Persist ingredient_fdc_map entries for resolved ingredients to speed up next runs
```

Integration points:
- In `search_and_rank_tool`: before ranking, if a recipe lacks `macros_per_serving`, call this tool and enrich the recipe object in-memory.
- In `plan_day_e2e_tool`: ensure selected recipes have macros; call tool if missing.

Performance:
- Cache hit: read from Recipe in Weaviate
- Cache miss: LLM + FDC search; optimize via batching and result caching per ingredient

Ingredient mapping cache:
- Field: `Recipe.ingredient_fdc_map` (object[]: ingredient_vn, ingredient_en, fdc_id, quantity_g, confidence)
- On each resolution, upsert entry; reuse on later calculations to bypass LLM/search.

API contract note:
- Responses that include recipes may return objects without `macros_per_serving` on first read; backend will compute and persist on-demand via this tool when needed.

**ProfileCRUDTool Implementation** (Actual Code Pattern):
```python
# MealAgent/tools/profile/profile_crud.py
from typing import AsyncGenerator, Optional
from elysia.tree.objects import TreeData
from elysia.objects import Result, Error, Response
from elysia.util.client import ClientManager
from elysia import tool

@tool
async def profile_crud_tool(
    tree_data: TreeData,
    client_manager: ClientManager,
    action: str = "create",
    profile_data: dict | None = None,
    **kwargs,
) -> AsyncGenerator[Result | Response | Error, None]:
    """
    Create, read, or update user profile in UserProfile collection.
    
    Environment:
        Reads: None (first tool in workflow)
        Writes: environment["profile_crud_tool"]["profile"] - stores profile data
    """
    # Use Response() for user-visible text (not plain strings)
    yield Response(f"Processing profile {action}...")
    
    client = client_manager.get_client()
    collection = client.collections.get("UserProfile")
    
    try:
        if action in {"create", "update"}:
            # Validate profile_data (validation function omitted for brevity)
            if not profile_data:
                yield Response("Skipping profile operation: missing profile_data")
                return
            
            # Upsert by user_id
            user_id = profile_data["user_id"]
            existing = collection.query.fetch_objects(
                where={"path": ["user_id"], "operator": "Equal", "valueString": user_id},
                limit=1
            )
            
            if existing.objects:
                collection.data.update(uuid=existing.objects[0].uuid, properties=profile_data)
            else:
                collection.data.insert(profile_data)
            
            # Yield Result to add to environment
            yield Result(
                objects=[profile_data],  # Required: list of dict objects
                metadata={"action": action, "user_id": user_id},  # Optional: metadata
                payload_type="generic",  # Optional: result type identifier
                name="profile",  # Optional: creates environment["profile_crud_tool"]["profile"]
                display=True  # Optional: whether to display on frontend
            )
            yield Response(f"Profile {action}d successfully for user {user_id}")
            
        elif action == "read":
            user_id = profile_data.get("user_id") if profile_data else kwargs.get("user_id")
            if not user_id:
                yield Response("Skipping profile read: user_id is required")
                return
                
            result = collection.query.fetch_objects(
                where={"path": ["user_id"], "operator": "Equal", "valueString": user_id},
                limit=1
            )
            
            if result.objects:
                profile = result.objects[0].properties
                yield Result(
                    name="profile",
                    objects=[profile],
                    metadata={"action": "read", "user_id": user_id},
                    payload_type="generic"
                )
                yield Response(f"Profile read successfully for user {user_id}")
            else:
                yield Response(f"Profile not found for user {user_id}")
                return
                
    except Exception as e:
        yield Error(f"Profile operation failed: {str(e)}")
        return
```

**MacroCalcTool Implementation** (Actual Code Pattern):
```python
# MealAgent/tools/profile/macro_calc.py
from typing import AsyncGenerator
from elysia.tree.objects import TreeData
from elysia.objects import Result, Error, Response
from elysia.util.client import ClientManager
from MealAgent.utils.nutrition import calculate_harris_benedict_tdee
from elysia import tool

@tool
async def macro_calc_tool(
    tree_data: TreeData,
    client_manager: ClientManager,
    **kwargs
) -> AsyncGenerator[Result | Response | Error, None]:
    """
    Calculate TDEE and macro targets using Harris-Benedict equation.
    
    Environment:
        Reads: environment["profile_crud_tool"]["profile"]
        Writes: environment["macro_calc_tool"]["targets"]
    """
    yield Response("Calculating nutritional targets...")
    
    # Read profile from environment
    profile_results = tree_data.environment.find("profile_crud_tool", "profile")
    if not profile_results or not profile_results[0].objects:
        yield Error("Profile not found in environment. Run profile_crud_tool first.")
        return
    
    profile = profile_results[0].objects[0]
    
    # Calculate TDEE
    tdee = calculate_harris_benedict_tdee(
        age=profile["age"],
        gender=profile["gender"],
        weight_kg=profile["weight_kg"],
        height_cm=profile["height_cm"],
        activity_level=profile["activity_level"]
    )
    
    # Calculate macros (example: 30% protein, 30% fat, 40% carbs)
    protein_g = (tdee * 0.30) / 4  # 4 kcal per gram
    fat_g = (tdee * 0.30) / 9      # 9 kcal per gram
    carb_g = (tdee * 0.40) / 4     # 4 kcal per gram
    
    targets = {
        "tdee_kcal": tdee,
        "protein_g": protein_g,
        "fat_g": fat_g,
        "carb_g": carb_g
    }
    
    yield Result(
        objects=[targets],  # Required: list of dict objects
        metadata={"calculated_from": profile.get("user_id")},  # Optional: metadata
        payload_type="generic",  # Optional: result type identifier
        name="targets",  # Optional: creates environment["macro_calc_tool"]["targets"]
        display=True  # Optional: whether to display on frontend
    )
    yield Response(f"Target: {tdee:.0f} kcal | {protein_g:.0f}g P | {fat_g:.0f}g F | {carb_g:.0f}g C")
```

**Harris-Benedict Utility** (`utils/nutrition.py`):
```python
def calculate_harris_benedict_tdee(
    age: int,
    gender: str,
    weight_kg: float,
    height_cm: float,
    activity_level: str
) -> float:
    """
    Calculate Total Daily Energy Expenditure using Harris-Benedict equation.
    
    Activity levels:
        - sedentary: BMR × 1.2
        - light: BMR × 1.375
        - moderate: BMR × 1.55
        - very_active: BMR × 1.725
        - extra_active: BMR × 1.9
    """
    # Calculate BMR
    if gender.lower() == "male":
        bmr = 88.362 + (13.397 * weight_kg) + (4.799 * height_cm) - (5.677 * age)
    else:  # female
        bmr = 447.593 + (9.247 * weight_kg) + (3.098 * height_cm) - (4.330 * age)
    
    # Apply activity multiplier
    activity_multipliers = {
        "sedentary": 1.2,
        "light": 1.375,
        "moderate": 1.55,
        "very_active": 1.725,
        "extra_active": 1.9
    }
    
    multiplier = activity_multipliers.get(activity_level.lower(), 1.2)
    tdee = bmr * multiplier
    
    return tdee
```

#### 2. Hybrid Search (search_and_rank_tool)

**search_and_rank_tool Implementation** (`tools/search/search_and_rank.py`) — uses Elysia `query` internally:
```python
from typing import AsyncGenerator
from elysia.tree.objects import TreeData, Result, Error, Response
from elysia.util.client import ClientManager
from elysia.tools.retrieval.query import Query  # Elysia built-in
from elysia import tool

@tool
async def search_and_rank_tool(
    tree_data: TreeData,
    client_manager: ClientManager,
    query_text: str = "",
    collection_name: str = "Recipe",
    limit: int = 100,
    top_k: int = 20,
    **kwargs
) -> AsyncGenerator[Result | Response | Error, None]:
    """
    End-to-end search → postprocess → rank using Elysia query internally.
    
    Environment:
        Reads: constraints_guard_tool.filters, macro_calc_tool.targets
        Writes: search_and_rank_tool.topk
    """
    yield Response("Searching and ranking recipes...")
    
    # Use Elysia Query tool internally
    elysia_query = Query()
    
    # Get constraints from environment
    constraints_results = tree_data.environment.find("constraints_guard_tool", "filters")
    where_clause = None
    if constraints_results and constraints_results[0].objects:
        where_clause = constraints_results[0].objects[0].get("where")
    
    # Execute Elysia query
    async for result in elysia_query(
        tree_data=tree_data,
        base_lm=kwargs.get("base_lm"),
        complex_lm=kwargs.get("complex_lm"),
        client_manager=client_manager,
        inputs={"collection_names": [collection_name]},
    **kwargs
    ):
        if isinstance(result, Error):
            yield result
        return
        # Elysia query yields Retrieval objects - extract results
        if hasattr(result, "objects"):
            recipes = [obj.properties for obj in result.objects]
    
            # Rank by macro fit (read targets from environment)
            targets_results = tree_data.environment.find("macro_calc_tool", "targets")
            if targets_results and targets_results[0].objects:
    targets = targets_results[0].objects[0]
                # Score and rank recipes...
                ranked = rank_recipes(recipes, targets, top_k)
    
    yield Result(
                    objects=ranked,
                    metadata={"query": query_text, "top_k": top_k},
                    payload_type="generic",
        name="topk",
                    display=True
    )
                yield Response(f"Top {len(ranked)} recipes ranked by fit")
                return
```

**Note**: This is a simplified example. The actual `search_and_rank_tool` should handle Elysia Query's output format properly and include ranking logic internally.

#### 3. Plan Assembly (plan_day_e2e_tool)

**Implementation** (`tools/plan_day/plan_day_e2e.py`) — end-to-end daily planning:
```python
from typing import AsyncGenerator
from elysia.tree.objects import TreeData, Result, Error, Response
from elysia.util.client import ClientManager
from elysia import tool

@tool
async def plan_day_e2e_tool(
    tree_data: TreeData,
    client_manager: ClientManager,
    **kwargs
) -> AsyncGenerator[Result | Response | Error, None]:
    """
    End-to-end daily planning: resolve targets → search → rank → assemble → validate.
    
    This tool orchestrates the full daily planning workflow internally:
    1. Resolve targets (from profile or query override)
    2. Apply constraints (diet/allergen/time)
    3. Search and rank recipes
    4. Assemble 3-meal plan
    5. Validate constraints and macros
    6. Generate shopping list (optional)
    
    Environment:
        Reads: macro_calc_tool.targets, constraints_guard_tool.filters, search_and_rank_tool.topk
        Writes: plan_day_e2e_tool.plan
    """
    yield Response("Planning daily meals...")
    
    # Internal steps (simplified - actual implementation would be more detailed)
    # Step 1: Resolve targets
    targets = await _resolve_targets(tree_data, kwargs)
    
    # Step 2: Apply constraints
    filters = await _apply_constraints(tree_data, kwargs)
    
    # Step 3: Search and rank (uses search_and_rank_tool or calls it internally)
    recipes = await _search_and_rank(tree_data, client_manager, filters, targets, kwargs)
    
    # Step 4: Assemble plan
    plan = await _assemble_plan(recipes, targets)
    
    # Step 5: Validate
    validation = await _validate_plan(plan, targets, filters)
    
    yield Result(
        objects=[plan],
        metadata={"plan_type": "day", "validation": validation},
        payload_type="generic",
        name="plan",
        display=True
    )
    yield Response(f"Daily plan created: {plan.get('total_macros', {}).get('kcal', 0):.0f} kcal")
```

**Note**: Internal functions `_resolve_targets`, `_apply_constraints`, `_search_and_rank`, `_assemble_plan`, `_validate_plan` are private helpers within the tool.

#### 4. Meal Logging (log_meal_e2e_tool)

**log_meal_e2e_tool Implementation** (`tools/meal_logging/log_meal_e2e.py`) — end-to-end meal logging:
```python
from typing import AsyncGenerator
from elysia.tree.objects import TreeData, Result, Error, Response
from elysia.util.client import ClientManager
from elysia import tool

@tool
async def log_meal_e2e_tool(
    tree_data: TreeData,
    client_manager: ClientManager,
    base_lm,                       # LLM for structured output
    meal_description: str = "",    # User input: "Tôi vừa ăn salad gà"
    user_id: str = "",
    **kwargs
) -> AsyncGenerator[Result | Response | Error, None]:
    """
    End-to-end meal logging: parse → calculate nutrition → update profile.
    
    This tool orchestrates the full meal logging workflow internally:
    1. Parse meal description (LLM-assisted)
    2. Calculate nutrition from FDC
    3. Update UserProfile and save MealLogEntry
    
    Environment:
        Reads: user_id (from kwargs or tree_data)
        Writes: log_meal_e2e_tool.updated_profile
    """
    yield Response("Logging meal...")
    
    # Step 1: Parse meal (internal function)
    parsed_meal = await _parse_meal(meal_description, base_lm, client_manager)
    if not parsed_meal:
        yield Error("Failed to parse meal description")
        return
    
    # Step 2: Calculate nutrition (internal function)
    calculated_nutrition = await _calculate_nutrition(parsed_meal, client_manager)
    if not calculated_nutrition:
        yield Error("Failed to calculate nutrition")
        return
    
    # Step 3: Update profile (internal function)
    updated_profile = await _update_profile(user_id, parsed_meal, calculated_nutrition, client_manager)
    
    yield Result(
        objects=[updated_profile],
        metadata={"user_id": user_id, "meal": parsed_meal.get("dish", "")},
        payload_type="generic",
        name="updated_profile",
        display=True
    )
    yield Response(f"Meal logged: {calculated_nutrition.get('calculated_macros', {}).get('kcal', 0):.0f} kcal")
```

**Note**: Internal functions `_parse_meal`, `_calculate_nutrition`, `_update_profile` are private helpers within the tool. The `log_meal_e2e_tool` handles all three steps (parse, calculate, update) internally to reduce tool calls and improve performance.

### Patterns & Best Practices

#### Async Generator Pattern (All Tools)
```python
from typing import AsyncGenerator
from elysia.tree.objects import TreeData
from elysia.objects import Result, Error, Response, Status
from elysia.util.client import ClientManager
from elysia import tool

@tool
async def tool_function(
    tree_data: TreeData,           # Automatically injected
    client_manager: ClientManager,  # Automatically injected
    base_lm,                       # Optional - LLM for structured output
    complex_lm,                    # Optional - More powerful LLM if needed
    param1: str = "default",
    param2: dict = None,
    **kwargs
) -> AsyncGenerator[Result | Response | Status | Error, None]:
    # 1. Yield Response/Status for progress updates (not plain strings)
    yield Response("Starting operation...")
    # or
    yield Status("Processing...")
    
    # 2. Read from environment (upstream tool outputs)
    upstream_results = tree_data.environment.find("upstream_tool_name", "output_name")
    if not upstream_results or not upstream_results[0].objects:
        yield Error("Required data not found in environment")
        return
    
    upstream_data = upstream_results[0].objects[0]
    
    # 3. Perform computation/query
    client = client_manager.get_client()
    result_data = await perform_async_operation(upstream_data, client)
    
    # 4. Yield Result to store in environment
    yield Result(
        objects=[result_data],  # Required: list of dict objects
        metadata={"operation": "example"},  # Optional: metadata
        payload_type="generic",  # Optional: result type identifier (default: "default")
        name="output",  # Optional: creates environment["tool_function"]["output"]
        display=True  # Optional: whether to display on frontend (default: True)
    )
    
    # 5. Handle errors gracefully
    if error_condition:
        yield Error("Descriptive error message")
        return
    
    # 6. Final Response for completion
    yield Response("Operation completed successfully")
```

#### Environment Key Conventions
- **Elysia Standard Pattern**: `environment[tool_name][name]` where:
  - `tool_name` = function name (e.g., "profile_crud_tool")
  - `name` = Result's `name` parameter (e.g., "profile", "targets")
- **Automatic Adding**: When you `yield Result(...)`, the Tree automatically calls `environment.add(tool_name, result)`. No manual `.add()` needed.
- **Tools write only to their namespace**: Each tool writes to `environment[function_name][...]` via yielding Result objects
- **Tools read from any namespace**: Use `tree_data.environment.find(tool_name, name)` to read data from any tool
- **Use descriptive name parameters**: `"profile"`, `"targets"`, `"results"`, `"plan"`, `"report"`
- **Automatic _REF_ID**: Each object in environment gets a unique `_REF_ID` attribute automatically
- **Hidden Environment**: Use `tree_data.environment.hidden_environment` (dict) to store data not shown to LLM (e.g., temporary processing state)

**Advanced Environment Methods** (for manual manipulation if needed):
```python
# Manual adding (usually not needed - yielding Result auto-adds)
tree_data.environment.add(tool_name, result)
tree_data.environment.add_objects(tool_name, name, objects, metadata)

# Replacing existing data
tree_data.environment.replace(tool_name, name, objects, metadata, index=None)

# Removing data
tree_data.environment.remove(tool_name, name, index=None)  # index=None removes all

# Finding data (most common)
results = tree_data.environment.find(tool_name, name, index=None)  # Returns list or None
```

#### Error Handling (No Exceptions)
```python
# ❌ DON'T: Raise exceptions
if invalid_data:
    raise ValueError("Invalid data")

# ✅ DO: Yield Error objects
if invalid_data:
    yield Error("Invalid data provided. Please check input format.")
    return
```

#### Weaviate Client Access
```python
# Always use ClientManager (auto-injected) to get client
client = client_manager.get_client()
collection = client.collections.get("CollectionName")

# Queries with retry logic (implemented in ClientManager)
# Use 'where' parameter (not 'filters') for Weaviate v1.25+
results = collection.query.hybrid(
    query="search text",
    where={"path": ["field"], "operator": "Equal", "valueString": "value"},
    limit=100
)

# For fetch operations
results = collection.query.fetch_objects(
    where={"path": ["user_id"], "operator": "Equal", "valueString": user_id},
    limit=10
)
```

## Integration Points
**How do pieces connect?**

### API Integration Details

- MealAgent **không thêm** REST/WS endpoint mới; mọi workflow chạy qua WebSocket `/query` mặc định của Elysia.
- Client gửi payload tiêu chuẩn của Elysia với các trường `user_id`, `conversation_id`, `query_id`, `query`, tùy chọn `collection_names`, `training_route`, `mimick`. Không có trường `action`; Tree quyết định tool chain dựa vào nội dung `query` và trạng thái `environment`.

**WebSocket Handler Flow** (see [User and Tree Managers](https://weaviate.github.io/elysia/API/user_and_tree_managers/)):
```python
# In elysia/api/routes/query.py (Elysia's built-in route)
async def websocket_handler(websocket, user_manager: UserManager):
    message = await websocket.receive_json()
    
    # Extract required fields
    query = message["query"]
    user_id = message["user_id"]
    conversation_id = message["conversation_id"]
    query_id = message["query_id"]
    collection_names = message.get("collection_names", [])
    training_route = message.get("training_route", "")
    
    # UserManager.process_tree() automatically:
    # 1. Checks if user/tree has timed out → sends error payload if so
    # 2. Gets or creates TreeManager for user
    # 3. Calls tree_manager.process_tree() which calls tree.async_run()
    # 4. Streams all yielded payloads via WebSocket
    async for payload in user_manager.process_tree(
        query=query,
        user_id=user_id,
        conversation_id=conversation_id,
        query_id=query_id,
        training_route=training_route,
        collection_names=collection_names,
        save_trees_to_weaviate=None,  # Optional: save trees after completion
        wcd_url=None,  # Optional: Weaviate Cloud Database URL for saving trees
        wcd_api_key=None,  # Optional: API key for WCD
    ):
        await websocket.send_json(payload)
```

**Client Payload Example**:
```json
{
  "user_id": "user_123",
  "conversation_id": "demo",
  "query_id": "q-001",
  "query": "healthy breakfast options for today",
  "collection_names": ["Recipe", "UserProfile"],
  "training_route": "",  // Optional
  "mimick": false       // Optional
}
```

**Server Response Payload** (see [Payload Formats](https://weaviate.github.io/elysia/API/payload_formats/)):
All payloads have consistent outer structure:
```json
{
  "type": "result",  // or "text", "error", "status", "completed", "title", "ner"
  "id": "uuid",
  "user_id": "user_123",
  "conversation_id": "demo",
  "query_id": "q-001",
  "payload": {
    "type": "generic",  // or tool-specific type
    "metadata": {...},
    "objects": [
      {
        "plan": {...},
        "_REF_ID": "ref_123"  // Automatically added
      }
    ]
  }
}
```

**Key Points**:
- `Result` objects automatically call `.to_frontend()` to generate payload format
- `Update` classes (`Status`, `Error`) do NOT add to Environment but still stream via `.to_frontend()`
- All objects in `payload.objects` automatically include `_REF_ID` for environment tracking
- UserManager automatically handles timeout checks and sends error payloads if timed out

### Database Connections

**Note**: MealAgent uses Elysia's built-in `ClientManager` which is automatically injected into tools. Each user has their own ClientManager instance managed by UserManager.

**Using ClientManager in Tools**:
```python
# ClientManager is automatically injected by Elysia
async def my_tool(
    tree_data: TreeData,
    client_manager: ClientManager,  # Auto-injected (per-user instance)
    **kwargs
):
    client = client_manager.get_client()
    collection = client.collections.get("CollectionName")
    
    # Query with Weaviate v1.25+ syntax
    results = collection.query.hybrid(
        query="search text",
        where={"path": ["field"], "operator": "Equal", "valueString": "value"},
        limit=100
    )
```

**ClientManager Configuration**: Set in Elysia settings via environment variables:
```env
WEAVIATE_URL=http://localhost:8080
WEAVIATE_API_KEY=optional_api_key
```

**ClientManager Configuration** (see [Client Reference](https://weaviate.github.io/elysia/Reference/Client/)):
- **Initialization**: `ClientManager(wcd_url=None, wcd_api_key=None, weaviate_is_local=None, weaviate_is_custom=None, client_timeout=timedelta(minutes=3), query_timeout=60, insert_timeout=120, init_timeout=5, **kwargs)`
  - Default `client_timeout`: 3 minutes (or `CLIENT_TIMEOUT` env var)
  - Default `query_timeout`: 60 seconds (Weaviate default: 30 seconds)
  - Default `insert_timeout`: 120 seconds (Weaviate default: 90 seconds)
  - Default `init_timeout`: 5 seconds (Weaviate default: 2 seconds)
- **Client Methods**: `get_client()`, `get_async_client()`, `start_clients()`, `restart_client()`, `restart_async_client()`
- **Thread Safety**: ClientManager uses threading and asyncio locks for concurrent access

**Client Timeout Management** (see [User and Tree Managers](https://weaviate.github.io/elysia/API/user_and_tree_managers/)):
- UserManager automatically manages ClientManager instances per user
- Call `user_manager.check_restart_clients()` periodically to restart inactive clients (configurable via `client_timeout`)
- Default timeout: 3 minutes (or `CLIENT_TIMEOUT` env var)

## Error Handling
**How do we handle failures?**

### Error Handling Strategy
1. **Tool-level**: Yield `Error` objects with descriptive messages
2. **Tree-level**: Catch Error yields and decide next action (retry, fallback, abort)
3. **API-level**: Convert Error objects to HTTP error responses

### Logging Approach
```python
import logging

logger = logging.getLogger("elysia.meal_agent")

async def tool_function(...):
    logger.info("Starting tool execution")
    
    try:
        result = perform_operation()
        logger.debug(f"Operation result: {result}")
    except Exception as e:
        logger.error(f"Operation failed: {e}", exc_info=True)
        yield Error(f"Operation failed: {str(e)}")
        return
```

### Retry/Fallback Mechanisms
```python
# In Weaviate queries
MAX_RETRIES = 3
for attempt in range(MAX_RETRIES):
    try:
        results = collection.query.hybrid(...)
        break
    except WeaviateException as e:
        if attempt == MAX_RETRIES - 1:
            yield Error(f"Query failed after {MAX_RETRIES} attempts")
            return
        await asyncio.sleep(2 ** attempt)  # Exponential backoff
```

## Performance Considerations
**How do we keep it fast?**

### Optimization Strategies
1. **Batch Embeddings**: Generate embeddings in batches of 100 (not one-by-one)
2. **Filter Before Vector Search**: Apply hard constraints (diet/allergen) before semantic search
3. **Limit Search Results**: Retrieve top 100 candidates, rank top 20
4. **Cache User Profiles**: Store in Redis with 1-hour TTL

### Caching Approach
```python
# Cache user targets in environment (avoid recalculating)
# Note: In Elysia, environment access is via tree_data.environment.find()
targets_results = tree_data.environment.find("macro_calc_tool", "targets")
if targets_results and targets_results[0].objects:
    targets = targets_results[0].objects[0]
else:
    # Calculate and cache (via yielding Result)
    targets = calculate_targets()
    yield Result(
        name="targets",
        objects=[targets],
        metadata={"cached": True}
    )
```

### Query Optimization
```python
# Use indexed filterable properties with Weaviate v1.25+ syntax
collection.query.hybrid(
    query=query_text,
    where={
        "path": ["diet_type"],
        "operator": "Equal",
        "valueString": "vegetarian"
    },
    limit=100  # Limit early to reduce processing
)

# For multiple conditions, use And operator
collection.query.hybrid(
    query=query_text,
    where={
        "operator": "And",
        "operands": [
            {"path": ["diet_type"], "operator": "Equal", "valueString": "vegetarian"},
            {"path": ["time_min"], "operator": "LessThanEqual", "valueInt": 30}
        ]
    },
    limit=100
)
```

## Security Notes
**What security measures are in place?**

### Authentication/Authorization
- **v1 (MVP)**: Session-based; `user_id` stored in session cookie
- **User Isolation**: All Weaviate queries filtered by `user_id`
- **Future (v2)**: Migrate to JWT with OAuth2

### Input Validation
```python
from pydantic import BaseModel, validator

class ProfileInput(BaseModel):
    user_id: str
    age: int
    weight_kg: float
    
    @validator('age')
    def age_must_be_positive(cls, v):
        if v <= 0 or v > 120:
            raise ValueError('Age must be between 1 and 120')
        return v
```

### Data Encryption
- **At Rest**: Weaviate encryption enabled in production
- **In Transit**: HTTPS/WSS for all API and WebSocket connections

### Secrets Management
```python
import os
from dotenv import load_dotenv

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
WEAVIATE_API_KEY = os.getenv("WEAVIATE_API_KEY")

# Never log secrets
logger.info(f"Using API key: {OPENAI_API_KEY[:8]}...")  # ❌ DON'T
logger.info("OpenAI API key loaded")  # ✅ DO
```

## Operations

### Managing Collections (targeted)
Use targeted flags to drop/create specific collections without touching others:
```bash
# Drop only Recipe
python -m elysia.MealAgent.migrations.create_collections --drop-only Recipe

# Create only Recipe
python -m elysia.MealAgent.migrations.create_collections --create-only Recipe
```

### Weaviate schema gotcha (OBJECT types)
- In Weaviate, `object` / `object[]` properties require `nestedProperties` to be defined.
- Examples used:
  - `Recipe.macros_per_serving` → nested: `kcal`, `protein_g`, `fat_g`, `carb_g`
  - `Recipe.ingredient_fdc_map[]` → nested: `ingredient_vn`, `ingredient_en`, `fdc_id`, `quantity_g`, `confidence`

### Preprocessor (Phase 1 warmup)
Use Elysia's official Preprocessor API to generate collection summaries and mappings and save to `ELYSIA_METADATA__`.

Commands:
```bash
# Activate venv and install backend (required for dspy/litellm, etc.)
cd elysia
python -m venv venv
venv\Scripts\activate  # Windows; use source venv/bin/activate on Unix
pip install -U pip
pip install -e .

# Run preprocessor over target collections (defaults: Recipe,FdcFood,FdcNutrient,FdcPortion)
python -m elysia.MealAgent.preprocessing.preprocessor

# Override target collections (comma-separated)
$env:MEAL_AGENT_PREPROCESS_COLLECTIONS="Recipe,FdcFood"   # Windows PowerShell
export MEAL_AGENT_PREPROCESS_COLLECTIONS="Recipe,FdcFood" # Unix

# Optional knobs
export PREPROCESS_MIN_SAMPLE=10
export PREPROCESS_MAX_SAMPLE=50
export PREPROCESS_NUM_TOKENS=30000
export PREPROCESS_FORCE=true
```

Reference: [Preprocessor]

## Tool Registration (MealAgent/tree/config.py)

Tools are registered in `MealAgent/tree/config.py` via the `MEAL_AGENT_TOOLS` dictionary. Tools are then added to the Tree using `tree.add_tool()`.

**Registration Pattern:**
```python
# MealAgent/tree/config.py
from MealAgent.tools.profile.profile_crud import profile_crud_tool
from MealAgent.tools.profile.macro_calc import macro_calc_tool
# ... import all tools

MEAL_AGENT_TOOLS = {
    "profile_crud_tool": profile_crud_tool,
    "macro_calc_tool": macro_calc_tool,
    # ... all tools
}

def get_meal_agent_tools() -> dict[str, callable]:
    """Return dict of MealAgent tools for Tree registration."""
    return dict(MEAL_AGENT_TOOLS)
```

**Adding Tools to Tree** (see [Tree Reference](https://weaviate.github.io/elysia/Reference/Tree/)):
```python
# In meal_tree.py or tree initialization
from MealAgent.tree.config import get_meal_agent_tools
from elysia.tree.tree import Tree
from elysia.config import Settings

# Create tree with empty branch initialization
tree = Tree(
    branch_initialisation="empty",  # Start with no branches
    style="Friendly and helpful meal planning assistant",
    agent_description="Meal planning agent that helps users create personalized meal plans",
    end_goal="Generate meal plans that meet user's nutritional targets and preferences",
    user_id="user_123",
    conversation_id="conv_abc",
    low_memory=False,  # Set True to reduce memory usage
    use_elysia_collections=True,  # Use Elysia-processed collections
    settings=Settings()  # Optional: custom settings
)

# Create root branch (required - this is the starting point)
tree.add_branch(
    branch_id="root",
    instruction="Choose an action based on the user's request",
    root=True  # This is the root branch
)

# Create feature branches
tree.add_branch(
    branch_id="profile",
    instruction="Manage user profile and calculate nutritional targets",
    description="When user wants to create, update, or view their profile",
    from_branch_id="root",
    from_tool_ids=[],
    status="Managing profile..."
)

tree.add_branch(
    branch_id="logging",
    instruction="Log meals and view meal history",
    description="When user wants to log what they ate or view meal history",
    from_branch_id="root",
    from_tool_ids=[],
    status="Logging meal..."
)

tree.add_branch(
    branch_id="pantry",
    instruction="Manage pantry items and generate shopping lists",
    description="When user wants to manage pantry or view shopping list",
    from_branch_id="root",
    from_tool_ids=[],
    status="Managing pantry..."
)

tree.add_branch(
    branch_id="cooking",
    instruction="Show step-by-step cooking instructions",
    description="When user wants cooking instructions for a recipe",
    from_branch_id="root",
    from_tool_ids=[],
    status="Preparing cooking instructions..."
)

tree.add_branch(
    branch_id="explain",
    instruction="Explain meal planning decisions",
    description="When user wants to understand why certain meals were recommended",
    from_branch_id="root",
    from_tool_ids=[],
    status="Generating explanation..."
)

tree.add_branch(
    branch_id="search",
    instruction="Search and rank recipes based on user preferences",
    description="When user wants to find recipes",
    from_branch_id="root",
    from_tool_ids=[],
    status="Searching recipes..."
)

tree.add_branch(
    branch_id="planning",
    instruction="Plan daily or weekly meals from ranked recipes",
    description="When user wants daily or weekly meal plan",
    from_branch_id="root",
    from_tool_ids=[],
    status="Planning meals..."
)

tree.add_branch(
    branch_id="optimization",
    instruction="Optimize meal plans: fill gaps, substitute ingredients, check micronutrients",
    description="When user wants to optimize their meal plan",
    from_branch_id="planning",
    from_tool_ids=[],
    status="Optimizing plan..."
)

# Register tools to branches
tools = get_meal_agent_tools()

# Add tools to profile branch
tree.add_tool(tools["profile_crud_tool"], branch_id="profile")
tree.add_tool(tools["macro_calc_tool"], branch_id="profile")

# Add tools to search branch
tree.add_tool(tools["search_and_rank_tool"], branch_id="search")

# Add tools to planning branch (merged from plan_day + plan_week)
tree.add_tool(tools["plan_day_e2e_tool"], branch_id="planning")
tree.add_tool(tools["plan_week_e2e_tool"], branch_id="planning")

# Alternative: Add tool to root branch
# tree.add_tool(tools["some_tool"], root=True)
```

**Important Notes**:
- The `@tool` decorator automatically converts functions to `Tool` instances, so they can be passed directly to `tree.add_tool()`
- Tools must be async generators (`async def ... -> AsyncGenerator[...]`)
- `branch_id=None` in `add_tool()` adds tool to root branch
- `from_tool_ids=[]` adds tool after specified tools (creates new decision nodes if needed)
- `root=True` in `add_tool()` adds tool to root branch (ignores `branch_id`)
- Non-root branches require `description` and `from_branch_id` parameters

---

**Status**: Living document - Updated with tool optimization (v0.5)
**Last Updated**: 2025-01-27
**Owner**: MealAgent Development Team

**Changelog:**
- v0.5: **Tool Optimization** - Updated directory structure and tool examples to reflect optimized tool list (15 MealAgent tools + 3 Elysia tools). Removed intermediate tools, consolidated into E2E tools. Updated branch structure to 8 branches.

