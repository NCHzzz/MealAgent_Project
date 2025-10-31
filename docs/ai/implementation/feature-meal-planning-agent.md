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

# OpenAI (for embeddings and optional LLM features)
OPENAI_API_KEY=your_key_here
OPENAI_EMBEDDING_MODEL=text-embedding-3-small

# Elysia Settings
ELYSIA_ENV=development
ELYSIA_LOG_LEVEL=INFO

# MealAgent Specific
FDC_DATA_PATH=data/fdc/raw
RECIPE_DATA_PATH=data/recipes/raw
DEFAULT_TDEE_MULTIPLIER=1.2  # Sedentary activity level
```

## Code Structure
**How is the code organized?**

### Directory Structure
```
elysia/
├── MealAgent/
│   ├── __init__.py
│   ├── managers.py                 # UserManager, TreeManager, ClientManager
│   ├── config.py                   # MealAgent-specific settings
│   ├── schemas/                    # Weaviate collection schemas
│   │   ├── recipe.py
│   │   ├── fdc_food.py
│   │   ├── fdc_nutrient.py
│   │   ├── fdc_portion.py
│   │   └── user_profile.py
│   ├── preprocessing/              # Preprocessor for collections
│   │   ├── __init__.py
│   │   └── preprocessor.py
│   ├── tools/                      # All async generator tools
│   │   ├── __init__.py
│   │   ├── profile/
│   │   │   ├── __init__.py
│   │   │   ├── profile_crud.py     # ProfileCRUDTool
│   │   │   └── macro_calc.py       # MacroCalcTool
│   │   ├── constraints/
│   │   │   ├── __init__.py
│   │   │   ├── diet_allergen_guard.py
│   │   │   └── time_device_guard.py
│   │   ├── search/
│   │   │   ├── __init__.py
│   │   │   ├── query.py
│   │   │   ├── query_postprocessing.py
│   │   │   └── score_and_rank.py
│   │   ├── plan_day/
│   │   │   ├── __init__.py
│   │   │   ├── target_resolver.py
│   │   │   ├── plan_assemble.py
│   │   │   ├── plan_validate.py
│   │   │   └── build_shopping.py
│   │   ├── plan_week/
│   │   │   ├── __init__.py
│   │   │   ├── plan_assemble_weekly.py
│   │   │   └── variety_guard.py
│   │   ├── pantry/
│   │   │   ├── __init__.py
│   │   │   └── pantry_crud.py
│   │   ├── shopping/
│   │   │   ├── __init__.py
│   │   │   └── pantry_diff.py
│   │   ├── gap_fill/
│   │   │   ├── __init__.py
│   │   │   ├── gap_calc.py
│   │   │   ├── suggest_snack.py
│   │   │   └── apply_snack.py
│   │   ├── substitution/
│   │   │   ├── __init__.py
│   │   │   ├── suggest_substitutes.py
│   │   │   └── apply_substitute.py
│   │   ├── micros/
│   │   │   ├── __init__.py
│   │   │   ├── micronutrient_check.py
│   │   │   └── suggest_micros_foods.py
│   │   ├── cook_mode/
│   │   │   ├── __init__.py
│   │   │   └── cook_mode.py
│   │   └── explain/
│   │       ├── __init__.py
│   │       └── explain.py
│   ├── tree/
│   │   ├── __init__.py
│   │   ├── meal_tree.py            # Main decision tree
│   │   └── config.py               # Tool registration
│   ├── etl/                        # Data import scripts
│   │   ├── __init__.py
│   │   ├── fdc_import.py
│   │   └── recipe_import.py
│   ├── utils/                      # Helper utilities
│   │   ├── __init__.py
│   │   ├── nutrition.py            # TDEE, macro calculations
│   │   ├── unit_conversion.py      # Ingredient unit conversions
│   │   └── portion_mapping.py      # Recipe portion → FdcPortion
│   └── migrations/
│       ├── __init__.py
│       └── create_collections.py
```

### Module Organization

- **`schemas/`**: Weaviate collection class definitions (one file per collection)
- **`tools/`**: Organized by branch (feature area); each tool is an async generator
- **`tree/`**: Decision tree logic and configuration
- **`etl/`**: Data import pipelines (run once during setup)
- **`utils/`**: Shared helper functions (stateless, pure functions preferred)

### Naming Conventions

- **Tool files**: `snake_case.py` (e.g., `profile_crud.py`)
- **Tool classes**: `PascalCaseTool` (e.g., `ProfileCRUDTool`)
- **Environment keys**: `branch.tool.key` (e.g., `profile.profile_crud.profile`)
- **Collections**: `PascalCase` (e.g., `Recipe`, `FdcFood`)
- **Functions**: `snake_case` (e.g., `calculate_tdee`)

## Implementation Notes

### Core Features

#### 1. Profile Management (ProfileCRUDTool, MacroCalcTool)

**ProfileCRUDTool Implementation**:
```python
# elysia/MealAgent/tools/profile/profile_crud.py
from typing import AsyncGenerator
from elysia.util.return_types import Result, Text, Error

async def profile_crud_tool(
    environment: dict,
    user_manager: UserManager,
    action: str = "create",  # "create", "read", "update"
    profile_data: dict = None,
    **kwargs
) -> AsyncGenerator[Result | Text | Error, None]:
    """
    Create, read, or update user profile in UserProfile collection.
    
    Environment Keys:
        Writes: profile.profile_crud.profile
    """
    yield Text(f"Processing profile {action}...")
    
    client = user_manager.client_manager.get_client()
    
    try:
        if action == "create" or action == "update":
            # Validate profile_data
            required_fields = ["user_id", "age", "gender", "weight_kg", "height_cm", "activity_level"]
            if not all(field in profile_data for field in required_fields):
                yield Error(f"Missing required fields: {required_fields}")
                return
            
            # Upsert to Weaviate
            collection = client.collections.get("UserProfile")
            result = collection.data.insert(profile_data)
            
            yield Result(
                key="profile.profile_crud.profile",
                value=profile_data,
                display_type="json"
            )
            yield Text(f"Profile {action}d successfully for user {profile_data['user_id']}")
            
        elif action == "read":
            user_id = kwargs.get("user_id")
            collection = client.collections.get("UserProfile")
            result = collection.query.fetch_objects(
                filters={"user_id": user_id},
                limit=1
            )
            
            if result.objects:
                profile = result.objects[0].properties
                yield Result(
                    key="profile.profile_crud.profile",
                    value=profile,
                    display_type="json"
                )
            else:
                yield Error(f"Profile not found for user {user_id}")
                
    except Exception as e:
        yield Error(f"Profile operation failed: {str(e)}")
```

**MacroCalcTool Implementation**:
```python
# elysia/MealAgent/tools/profile/macro_calc.py
from elysia.MealAgent.utils.nutrition import calculate_harris_benedict_tdee

async def macro_calc_tool(
    environment: dict,
    user_manager: UserManager,
    **kwargs
) -> AsyncGenerator[Result | Text | Error, None]:
    """
    Calculate TDEE and macro targets using Harris-Benedict equation.
    
    Environment Keys:
        Reads: profile.profile_crud.profile
        Writes: profile.macro_calc.targets
    """
    yield Text("Calculating nutritional targets...")
    
    # Read profile from environment
    profile = environment.get("profile.profile_crud.profile")
    if not profile:
        yield Error("Profile not found in environment. Run ProfileCRUDTool first.")
        return
    
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
        key="profile.macro_calc.targets",
        value=targets,
        display_type="table"
    )
    yield Text(f"Target: {tdee:.0f} kcal | {protein_g:.0f}g P | {fat_g:.0f}g F | {carb_g:.0f}g C")
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

#### 2. Hybrid Search (query, ScoreAndRank)

**query Tool Implementation** (`tools/search/query.py`):
```python
async def query_tool(
    environment: dict,
    user_manager: UserManager,
    query_text: str = "",
    limit: int = 100,
    **kwargs
) -> AsyncGenerator[Result | Text | Error, None]:
    """
    Hybrid search on Recipe collection with hard filters.
    
    Environment Keys:
        Reads: constraints.filters.diet_allergen, constraints.filters.time_device
        Writes: search.query.results
    """
    yield Text(f"Searching recipes: '{query_text}'...")
    
    client = user_manager.client_manager.get_client()
    collection = client.collections.get("Recipe")
    
    # Build filters from constraints
    filters = {}
    diet_allergen_filters = environment.get("constraints.filters.diet_allergen", {})
    if diet_allergen_filters:
        # Example: {"diet_type": "vegetarian", "allergens_exclude": ["nuts", "dairy"]}
        if "diet_type" in diet_allergen_filters:
            filters["diet_type"] = diet_allergen_filters["diet_type"]
        if "allergens_exclude" in diet_allergen_filters:
            # Weaviate filter: none of the allergens should match
            filters["allergens"] = {"not_contains_any": diet_allergen_filters["allergens_exclude"]}
    
    time_device_filters = environment.get("constraints.filters.time_device", {})
    if time_device_filters and "max_time_min" in time_device_filters:
        filters["time_min"] = {"less_than_equal": time_device_filters["max_time_min"]}
    
    # Execute hybrid search
    results = collection.query.hybrid(
        query=query_text,
        alpha=0.5,  # 50% BM25, 50% vector
        filters=filters,
        limit=limit
    )
    
    recipes = [obj.properties for obj in results.objects]
    
    yield Result(
        key="search.query.results",
        value=recipes,
        display_type="table"
    )
    yield Text(f"Found {len(recipes)} matching recipes")
```

**ScoreAndRank Tool** (`tools/search/score_and_rank.py`):
```python
async def score_and_rank_tool(
    environment: dict,
    user_manager: UserManager,
    top_k: int = 20,
    **kwargs
) -> AsyncGenerator[Result | Text | Error, None]:
    """
    Multi-criteria scoring and ranking of recipes.
    
    Criteria:
        1. Macro fit (how close to targets per meal)
        2. Semantic relevance (from hybrid search score)
        3. Diversity (prefer varied ingredients/cuisines)
    
    Environment Keys:
        Reads: search.post.deduped, profile.macro_calc.targets
        Writes: search.rank.topk
    """
    yield Text("Ranking recipes by fit and diversity...")
    
    recipes = environment.get("search.post.deduped", [])
    targets = environment.get("profile.macro_calc.targets", {})
    
    if not recipes:
        yield Error("No recipes to rank")
        return
    
    # Calculate target per meal (assume 3 meals/day)
    target_per_meal = {
        "kcal": targets.get("tdee_kcal", 2000) / 3,
        "protein_g": targets.get("protein_g", 150) / 3,
        "fat_g": targets.get("fat_g", 67) / 3,
        "carb_g": targets.get("carb_g", 200) / 3
    }
    
    # Score each recipe
    scored_recipes = []
    for recipe in recipes:
        macros = recipe.get("macros_per_serving", {})
        
        # Calculate macro deviation (lower is better)
        kcal_dev = abs(macros.get("kcal", 0) - target_per_meal["kcal"]) / target_per_meal["kcal"]
        protein_dev = abs(macros.get("protein_g", 0) - target_per_meal["protein_g"]) / target_per_meal["protein_g"]
        
        # Composite score (0-100, higher is better)
        macro_score = max(0, 100 - (kcal_dev + protein_dev) * 50)
        
        # Semantic score from hybrid search (already 0-1, scale to 0-100)
        semantic_score = recipe.get("_additional", {}).get("score", 0.5) * 100
        
        # Weighted average
        total_score = 0.6 * macro_score + 0.4 * semantic_score
        
        scored_recipes.append({
            **recipe,
            "fit_score": total_score
        })
    
    # Sort and take top_k
    scored_recipes.sort(key=lambda x: x["fit_score"], reverse=True)
    top_recipes = scored_recipes[:top_k]
    
    yield Result(
        key="search.rank.topk",
        value=top_recipes,
        display_type="table"
    )
    yield Text(f"Top {len(top_recipes)} recipes ranked by fit")
```

#### 3. Plan Assembly (PlanAssembleDay)

**Implementation** (`tools/plan_day/plan_assemble.py`):
```python
async def plan_assemble_day_tool(
    environment: dict,
    user_manager: UserManager,
    **kwargs
) -> AsyncGenerator[Result | Text | Error, None]:
    """
    Assemble 3-meal daily plan from top-ranked recipes.
    
    Strategy:
        - Breakfast: Highest carb recipe (energy for day)
        - Lunch: Balanced macro recipe
        - Dinner: Highest protein recipe (recovery)
    
    Environment Keys:
        Reads: search.rank.topk, plan_day.target.resolved
        Writes: plan_day.assemble.plan
    """
    yield Text("Assembling daily meal plan...")
    
    recipes = environment.get("search.rank.topk", [])
    targets = environment.get("plan_day.target.resolved", {})
    
    if len(recipes) < 3:
        yield Error("Insufficient recipes for 3-meal plan")
        return
    
    # Separate into meal categories (simplified heuristic)
    breakfast_candidates = [r for r in recipes if "breakfast" in r.get("tags", [])]
    lunch_candidates = [r for r in recipes if "lunch" in r.get("tags", []) or "main" in r.get("tags", [])]
    dinner_candidates = [r for r in recipes if "dinner" in r.get("tags", []) or "main" in r.get("tags", [])]
    
    # Fallback: use top recipes if category filtering leaves empty
    if not breakfast_candidates:
        breakfast_candidates = recipes
    if not lunch_candidates:
        lunch_candidates = recipes
    if not dinner_candidates:
        dinner_candidates = recipes
    
    # Select meals
    plan = {
        "breakfast": breakfast_candidates[0],
        "lunch": lunch_candidates[0] if lunch_candidates[0] != breakfast_candidates[0] else lunch_candidates[1],
        "dinner": dinner_candidates[0] if dinner_candidates[0] not in [breakfast_candidates[0], lunch_candidates[0]] else dinner_candidates[1]
    }
    
    # Calculate total macros
    total_macros = {
        "kcal": sum(meal.get("macros_per_serving", {}).get("kcal", 0) for meal in plan.values()),
        "protein_g": sum(meal.get("macros_per_serving", {}).get("protein_g", 0) for meal in plan.values()),
        "fat_g": sum(meal.get("macros_per_serving", {}).get("fat_g", 0) for meal in plan.values()),
        "carb_g": sum(meal.get("macros_per_serving", {}).get("carb_g", 0) for meal in plan.values())
    }
    
    plan_output = {
        "meals": plan,
        "total_macros": total_macros
    }
    
    yield Result(
        key="plan_day.assemble.plan",
        value=plan_output,
        display_type="json"
    )
    yield Text(f"Daily plan: {total_macros['kcal']:.0f} kcal | {total_macros['protein_g']:.0f}g P")
```

### Patterns & Best Practices

#### Async Generator Pattern (All Tools)
```python
async def tool_function(
    environment: dict,
    user_manager: UserManager,
    **kwargs
) -> AsyncGenerator[Result | Text | Error, None]:
    # 1. Yield Text for progress updates
    yield Text("Starting operation...")
    
    # 2. Read from environment (upstream tool outputs)
    upstream_data = environment.get("branch.tool.key")
    
    # 3. Perform computation/query
    result_data = await perform_async_operation(upstream_data)
    
    # 4. Yield Result to store in environment
    yield Result(
        key="this_branch.this_tool.output",
        value=result_data,
        display_type="table"  # or "json", "chart", "text"
    )
    
    # 5. Handle errors gracefully
    if error_condition:
        yield Error("Descriptive error message")
        return
    
    # 6. Final Text for completion
    yield Text("Operation completed successfully")
```

#### Environment Key Conventions
- **Always use namespaced keys**: `branch.tool.key_name`
- **Tools write only to their namespace**: e.g., `profile.profile_crud.*`
- **Tools read from any namespace**: Check with `environment.get("other_branch.other_tool.key")`
- **Use descriptive key names**: `targets`, `results`, `plan`, `report`

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
# Always use UserManager to get client
client = user_manager.client_manager.get_client()
collection = client.collections.get("CollectionName")

# Queries with retry logic (implemented in ClientManager)
results = collection.query.hybrid(...)
```

## Integration Points
**How do pieces connect?**

### API Integration Details

**FastAPI Endpoints** (wrap Elysia Tree calls):
```python
# elysia/api/routes/meal_agent.py
from fastapi import APIRouter, WebSocket
from elysia.MealAgent.tree.meal_tree import MealTree

router = APIRouter(prefix="/api/v1/meal")

@router.post("/plan/day")
async def generate_daily_plan(user_id: str, query: str = ""):
    tree = MealTree(user_id=user_id)
    results = []
    
    async for output in tree.run(query):
        if isinstance(output, Result):
            results.append(output.value)
    
    return {"plan": results[-1]}  # Return final plan

@router.websocket("/ws/plan/{user_id}")
async def plan_stream(websocket: WebSocket, user_id: str):
    await websocket.accept()
    tree = MealTree(user_id=user_id)
    
    async for output in tree.run(await websocket.receive_text()):
        if isinstance(output, (Result, Text)):
            await websocket.send_json(output.to_dict())
```

### Database Connections

**Weaviate ClientManager** (`MealAgent/managers.py`):
```python
import weaviate
from weaviate.client import WeaviateClient

class MealAgentClientManager:
    def __init__(self, url: str, api_key: str = None):
        self.url = url
        self.api_key = api_key
        self._client = None
    
    def get_client(self) -> WeaviateClient:
        if not self._client:
            self._client = weaviate.connect_to_local(
                host=self.url,
                port=8080,
                auth_credentials=weaviate.auth.AuthApiKey(self.api_key) if self.api_key else None
            )
        return self._client
    
    def close(self):
        if self._client:
            self._client.close()
```

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
if "profile.macro_calc.targets" in environment:
    targets = environment["profile.macro_calc.targets"]
else:
    # Calculate and cache
    targets = calculate_targets()
    environment["profile.macro_calc.targets"] = targets
```

### Query Optimization
```python
# Use indexed filterable properties
collection.query.hybrid(
    query=query_text,
    filters={
        "diet_type": "vegetarian",  # Indexed field
        "time_min": {"less_than_equal": 30}  # Indexed field
    },
    limit=100  # Limit early to reduce processing
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

---

**Status**: Living document - Update as implementation progresses
**Last Updated**: 2025-10-28
**Owner**: [Your Name/Team]

