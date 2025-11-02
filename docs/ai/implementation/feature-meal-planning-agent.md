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
- **Tool functions**: `snake_case_tool` (e.g., `profile_crud_tool`) when using `@tool` decorator
- **Environment keys**: `environment[tool_name][name]` where `tool_name` is function name and `name` is Result's name parameter (e.g., `environment["profile_crud_tool"]["profile"]`)
- **Collections**: `PascalCase` (e.g., `Recipe`, `FdcFood`)
- **Functions**: `snake_case` (e.g., `calculate_tdee`)

## Implementation Notes

### Core Features

#### 1. Profile Management (ProfileCRUDTool, MacroCalcTool)

**ProfileCRUDTool Implementation**:
```python
# elysia/MealAgent/tools/profile/profile_crud.py
from typing import AsyncGenerator
from elysia.tree.objects import TreeData, Result, Error
from elysia.util.client import ClientManager
from elysia import tool

@tool
async def profile_crud_tool(
    tree_data: TreeData,           # Automatically injected - access environment via tree_data.environment
    client_manager: ClientManager,  # Automatically injected - Weaviate client access
    action: str = "create",        # "create", "read", "update"
    profile_data: dict = None,      # LLM-chosen or user-provided parameter
    **kwargs
) -> AsyncGenerator[Result | str | Error, None]:
    """
    Create, read, or update user profile in UserProfile collection.
    
    Environment:
        Reads: None (first tool in workflow)
        Writes: environment["profile_crud_tool"]["profile"] - stores profile data
    """
    yield f"Processing profile {action}..."
    
    client = client_manager.get_client()
    collection = client.collections.get("UserProfile")
    
    try:
        if action == "create" or action == "update":
            # Validate profile_data
            required_fields = ["user_id", "age", "gender", "weight_kg", "height_cm", "activity_level"]
            if not profile_data or not all(field in profile_data for field in required_fields):
                yield Error(f"Missing required fields: {required_fields}")
                return
            
            # Upsert to Weaviate
            result = collection.data.insert(profile_data)
            
            # Yield Result to add to environment
            yield Result(
                name="profile",  # Environment key: environment["profile_crud_tool"]["profile"]
                objects=[profile_data],
                metadata={"action": action, "user_id": profile_data.get("user_id")}
            )
            yield f"Profile {action}d successfully for user {profile_data['user_id']}"
            
        elif action == "read":
            user_id = profile_data.get("user_id") if profile_data else kwargs.get("user_id")
            if not user_id:
                yield Error("user_id is required for read operation")
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
                    metadata={"action": "read"}
                )
            else:
                yield Error(f"Profile not found for user {user_id}")
                return
                
    except Exception as e:
        yield Error(f"Profile operation failed: {str(e)}")
        return
```

**MacroCalcTool Implementation**:
```python
# elysia/MealAgent/tools/profile/macro_calc.py
from typing import AsyncGenerator
from elysia.tree.objects import TreeData, Result, Error
from elysia.MealAgent.utils.nutrition import calculate_harris_benedict_tdee
from elysia import tool

@tool
async def macro_calc_tool(
    tree_data: TreeData,           # Automatically injected
    client_manager: ClientManager,  # Automatically injected
    **kwargs
) -> AsyncGenerator[Result | str | Error, None]:
    """
    Calculate TDEE and macro targets using Harris-Benedict equation.
    
    Environment:
        Reads: environment["profile_crud_tool"]["profile"]
        Writes: environment["macro_calc_tool"]["targets"]
    """
    yield "Calculating nutritional targets..."
    
    # Read profile from environment
    profile_results = tree_data.environment.find("profile_crud_tool", "profile")
    if not profile_results:
        yield Error("Profile not found in environment. Run profile_crud_tool first.")
        return
    
    profile = profile_results[0].objects[0] if profile_results and profile_results[0].objects else None
    if not profile:
        yield Error("Profile data is empty. Run profile_crud_tool first.")
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
        name="targets",
        objects=[targets],
        metadata={"calculated_from": profile.get("user_id")}
    )
    yield f"Target: {tdee:.0f} kcal | {protein_g:.0f}g P | {fat_g:.0f}g F | {carb_g:.0f}g C"
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
from typing import AsyncGenerator
from elysia.tree.objects import TreeData, Result, Error
from elysia.util.client import ClientManager
from elysia import tool

@tool
async def query_tool(
    tree_data: TreeData,
    client_manager: ClientManager,
    query_text: str = "",
    limit: int = 100,
    **kwargs
) -> AsyncGenerator[Result | str | Error, None]:
    """
    Hybrid search on Recipe collection with hard filters.
    
    Environment:
        Reads: environment["diet_allergen_guard_tool"]["filters"], 
               environment["time_device_guard_tool"]["filters"]
        Writes: environment["query_tool"]["results"]
    """
    yield f"Searching recipes: '{query_text}'..."
    
    client = client_manager.get_client()
    collection = client.collections.get("Recipe")
    
    # Build filters from constraints
    where_conditions = []
    
    # Read diet/allergen filters
    diet_filters = tree_data.environment.find("diet_allergen_guard_tool", "filters")
    if diet_filters and diet_filters[0].objects:
        filter_data = diet_filters[0].objects[0]
        if "diet_type" in filter_data:
            where_conditions.append({
                "path": ["diet_type"],
                "operator": "Equal",
                "valueString": filter_data["diet_type"]
            })
        if "allergens_exclude" in filter_data and filter_data["allergens_exclude"]:
            # Exclude recipes containing any of the allergens
            for allergen in filter_data["allergens_exclude"]:
                where_conditions.append({
                    "path": ["allergens"],
                    "operator": "NotEqual",
                    "valueString": allergen
                })
    
    # Read time/device filters
    time_filters = tree_data.environment.find("time_device_guard_tool", "filters")
    if time_filters and time_filters[0].objects:
        filter_data = time_filters[0].objects[0]
        if "max_time_min" in filter_data:
            where_conditions.append({
                "path": ["time_min"],
                "operator": "LessThanEqual",
                "valueInt": filter_data["max_time_min"]
            })
    
    # Build where clause (combine with AND)
    where_clause = None
    if len(where_conditions) == 1:
        where_clause = where_conditions[0]
    elif len(where_conditions) > 1:
        where_clause = {
            "operator": "And",
            "operands": where_conditions
        }
    
    # Execute hybrid search
    try:
    results = collection.query.hybrid(
        query=query_text,
        alpha=0.5,  # 50% BM25, 50% vector
            where=where_clause,
        limit=limit
    )
    
    recipes = [obj.properties for obj in results.objects]
    
    yield Result(
            name="results",
            objects=recipes,
            metadata={"query": query_text, "count": len(recipes)}
        )
        yield f"Found {len(recipes)} matching recipes"
    except Exception as e:
        yield Error(f"Search failed: {str(e)}")
        return
```

**ScoreAndRank Tool** (`tools/search/score_and_rank.py`):
```python
from typing import AsyncGenerator
from elysia.tree.objects import TreeData, Result, Error
from elysia.util.client import ClientManager
from elysia import tool

@tool
async def score_and_rank_tool(
    tree_data: TreeData,
    client_manager: ClientManager,
    top_k: int = 20,
    **kwargs
) -> AsyncGenerator[Result | str | Error, None]:
    """
    Multi-criteria scoring and ranking of recipes.
    
    Criteria:
        1. Macro fit (how close to targets per meal)
        2. Semantic relevance (from hybrid search score)
        3. Diversity (prefer varied ingredients/cuisines)
    
    Environment:
        Reads: environment["query_postprocessing_tool"]["deduped"], 
               environment["macro_calc_tool"]["targets"]
        Writes: environment["score_and_rank_tool"]["topk"]
    """
    yield "Ranking recipes by fit and diversity..."
    
    # Read recipes from environment
    recipes_results = tree_data.environment.find("query_postprocessing_tool", "deduped")
    if not recipes_results or not recipes_results[0].objects:
        recipes = []
    else:
        recipes = recipes_results[0].objects
    
    # Read targets from environment
    targets_results = tree_data.environment.find("macro_calc_tool", "targets")
    if not targets_results or not targets_results[0].objects:
        yield Error("Targets not found in environment. Run macro_calc_tool first.")
        return
    
    targets = targets_results[0].objects[0]
    
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
        kcal_dev = abs(macros.get("kcal", 0) - target_per_meal["kcal"]) / target_per_meal["kcal"] if target_per_meal["kcal"] > 0 else 1.0
        protein_dev = abs(macros.get("protein_g", 0) - target_per_meal["protein_g"]) / target_per_meal["protein_g"] if target_per_meal["protein_g"] > 0 else 1.0
        
        # Composite score (0-100, higher is better)
        macro_score = max(0, 100 - (kcal_dev + protein_dev) * 50)
        
        # Semantic score from hybrid search (if available in metadata)
        semantic_score = 50  # Default if not available
        if "_additional" in recipe:
            search_score = recipe.get("_additional", {}).get("score", 0.5)
            semantic_score = search_score * 100
        
        # Weighted average
        total_score = 0.6 * macro_score + 0.4 * semantic_score
        
        scored_recipes.append({
            **recipe,
            "fit_score": total_score
        })
    
    # Sort and take top_k
    scored_recipes.sort(key=lambda x: x.get("fit_score", 0), reverse=True)
    top_recipes = scored_recipes[:top_k]
    
    yield Result(
        name="topk",
        objects=top_recipes,
        metadata={"top_k": top_k, "total_scored": len(scored_recipes)}
    )
    yield f"Top {len(top_recipes)} recipes ranked by fit"
```

#### 3. Plan Assembly (PlanAssembleDay)

**Implementation** (`tools/plan_day/plan_assemble.py`):
```python
from typing import AsyncGenerator
from elysia.tree.objects import TreeData, Result, Error
from elysia.util.client import ClientManager
from elysia import tool

@tool
async def plan_assemble_day_tool(
    tree_data: TreeData,
    client_manager: ClientManager,
    **kwargs
) -> AsyncGenerator[Result | str | Error, None]:
    """
    Assemble 3-meal daily plan from top-ranked recipes.
    
    Strategy:
        - Breakfast: Highest carb recipe (energy for day)
        - Lunch: Balanced macro recipe
        - Dinner: Highest protein recipe (recovery)
    
    Environment:
        Reads: environment["score_and_rank_tool"]["topk"], 
               environment["target_resolver_tool"]["resolved"]
        Writes: environment["plan_assemble_day_tool"]["plan"]
    """
    yield "Assembling daily meal plan..."
    
    # Read recipes from environment
    recipes_results = tree_data.environment.find("score_and_rank_tool", "topk")
    if not recipes_results or not recipes_results[0].objects:
        yield Error("No ranked recipes found. Run score_and_rank_tool first.")
        return
    
    recipes = recipes_results[0].objects
    
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
    
    # Select meals (avoid duplicates)
    breakfast = breakfast_candidates[0]
    lunch = lunch_candidates[0] if lunch_candidates[0] != breakfast else lunch_candidates[1] if len(lunch_candidates) > 1 else breakfast
    dinner = dinner_candidates[0] if dinner_candidates[0] not in [breakfast, lunch] else dinner_candidates[1] if len(dinner_candidates) > 1 else breakfast
    
    plan = {
        "breakfast": breakfast,
        "lunch": lunch,
        "dinner": dinner
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
        name="plan",
        objects=[plan_output],
        metadata={"plan_type": "day", "meals_count": 3}
    )
    yield f"Daily plan: {total_macros['kcal']:.0f} kcal | {total_macros['protein_g']:.0f}g P"
```

#### 4. Meal Logging (MealParser, NutritionCalc, ProfileUpdate)

**MealParser Tool Implementation** (`tools/meal_logging/meal_parser.py`):
```python
from typing import AsyncGenerator
from elysia.tree.objects import TreeData, Result, Error
from elysia.util.client import ClientManager
from elysia import tool
import json

@tool
async def meal_parser_tool(
    tree_data: TreeData,
    client_manager: ClientManager,
    base_lm,                       # LLM for structured output
    meal_description: str = "",    # User input: "Tôi vừa ăn salad gà"
    **kwargs
) -> AsyncGenerator[Result | str | Error, None]:
    """
    Parse natural language meal description into structured data.
    
    LLM-Enhanced Tool: Uses base_lm to extract dish name and ingredients.
    
    Environment:
        Reads: None (first tool in meal logging workflow)
        Writes: environment["meal_parser_tool"]["parsed_meal"]
    """
    yield "Parsing meal description..."
    
    if not meal_description:
        yield Error("Meal description is required")
        return
    
    # Step 1: LLM Call - Parse meal description
    llm_prompt = f"""Parse this meal description into structured JSON:
"{meal_description}"

Return JSON with:
- dish: dish name (e.g., "Chicken Salad")
- ingredients: list of [{{"name": str, "amount": float, "unit": str}}]
- portion_size: number (default 1.0)

Example: {{"dish": "Chicken Salad", "ingredients": [{{"name": "chicken", "amount": 100, "unit": "g"}}, {{"name": "lettuce", "amount": 50, "unit": "g"}}], "portion_size": 1.0}}"""

    try:
        llm_response = await base_lm.generate_structured(
            prompt=llm_prompt,
            schema={
                "type": "object",
                "properties": {
                    "dish": {"type": "string"},
                    "ingredients": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "amount": {"type": "number"},
                                "unit": {"type": "string"}
                            }
                        }
                    },
                    "portion_size": {"type": "number"}
                }
            }
        )
        
        parsed_data = json.loads(llm_response) if isinstance(llm_response, str) else llm_response
        
    except Exception as e:
        yield Error(f"Failed to parse meal description: {str(e)}")
        return
    
    # Step 2: Code Validation - Check if ingredients exist in FDC
    client = client_manager.get_client()
    fdc_collection = client.collections.get("FdcFood")
    
    validated_ingredients = []
    for ing in parsed_data.get("ingredients", []):
        # Search for ingredient in FDC
        search_results = fdc_collection.query.hybrid(
            query=ing["name"],
            limit=1
        )
        
        if search_results.objects:
            fdc_food = search_results.objects[0].properties
            validated_ingredients.append({
                **ing,
                "fdc_id": fdc_food.get("fdc_id")
            })
        else:
            yield Error(f"Ingredient '{ing['name']}' not found in FDC database")
            return
    
    parsed_meal = {
        "dish": parsed_data.get("dish", ""),
        "ingredients": validated_ingredients,
        "portion_size": parsed_data.get("portion_size", 1.0),
        "original_description": meal_description,
        "validation_status": "complete"
    }
    
    # Step 3: Yield Result
    yield Result(
        name="parsed_meal",
        objects=[parsed_meal],
        metadata={"parsing_method": "llm", "ingredients_count": len(validated_ingredients)}
    )
    yield f"Parsed meal: {parsed_meal['dish']} with {len(validated_ingredients)} ingredients"
```

**NutritionCalc Tool Implementation** (`tools/meal_logging/nutrition_calc.py`):
```python
from typing import AsyncGenerator
from elysia.tree.objects import TreeData, Result, Error
from elysia.util.client import ClientManager
from elysia import tool

@tool
async def nutrition_calc_tool(
    tree_data: TreeData,
    client_manager: ClientManager,
    **kwargs
) -> AsyncGenerator[Result | str | Error, None]:
    """
    Calculate nutrition (macros/micros) from parsed meal ingredients.
    
    Code-Based Tool: Uses FdcNutrient + FdcPortion for calculations.
    
    Environment:
        Reads: environment["meal_parser_tool"]["parsed_meal"]
        Writes: environment["nutrition_calc_tool"]["calculated"]
    """
    yield "Calculating nutrition..."
    
    # Read parsed meal from environment
    parsed_results = tree_data.environment.find("meal_parser_tool", "parsed_meal")
    if not parsed_results or not parsed_results[0].objects:
        yield Error("Parsed meal not found. Run meal_parser_tool first.")
        return
    
    parsed_meal = parsed_results[0].objects[0]
    ingredients = parsed_meal.get("ingredients", [])
    portion_size = parsed_meal.get("portion_size", 1.0)
    
    client = client_manager.get_client()
    nutrient_collection = client.collections.get("FdcNutrient")
    portion_collection = client.collections.get("FdcPortion")
    
    total_macros = {"kcal": 0, "protein_g": 0, "fat_g": 0, "carb_g": 0}
    total_micros = {}
    
    # Calculate nutrition for each ingredient
    for ing in ingredients:
        fdc_id = ing.get("fdc_id")
        amount = ing.get("amount", 0)
        unit = ing.get("unit", "g")
        
        if not fdc_id:
            continue
        
        # Convert to grams using FdcPortion
        grams = amount
        if unit != "g":
            # Find portion conversion
            portion_results = portion_collection.query.fetch_objects(
                where={
                    "path": ["fdc_id"],
                    "operator": "Equal",
                    "valueInt": fdc_id
                },
                limit=10
            )
            
            # Find matching portion
            for portion_obj in portion_results.objects:
                portion = portion_obj.properties
                if portion.get("measure_unit") == unit and abs(portion.get("amount", 0) - amount) < 0.1:
                    grams = portion.get("gram_weight", amount)
                    break
        
        # Get nutrients for this FDC food
        nutrient_results = nutrient_collection.query.fetch_objects(
            where={
                "path": ["fdc_id"],
                "operator": "Equal",
                "valueInt": fdc_id
            }
        )
        
        # Calculate nutrition (per 100g basis)
        for nutrient_obj in nutrient_results.objects:
            nutrient = nutrient_obj.properties
            nutrient_id = nutrient.get("nutrient_id")
            nutrient_name = nutrient.get("nutrient_name", "").lower()
            amount_per_100g = nutrient.get("amount_per_100g", 0)
            
            # Calculate actual amount (proportional to grams)
            actual_amount = (amount_per_100g * grams * portion_size) / 100.0
            
            # Accumulate macros
            if nutrient_id == 1008:  # Energy (kcal)
                total_macros["kcal"] += actual_amount
            elif "protein" in nutrient_name:
                total_macros["protein_g"] += actual_amount
            elif "fat" in nutrient_name and "total" in nutrient_name:
                total_macros["fat_g"] += actual_amount
            elif "carbohydrate" in nutrient_name and "total" in nutrient_name:
                total_macros["carb_g"] += actual_amount
            else:
                # Micronutrients
                unit_key = f"{nutrient_name}_{nutrient.get('unit', '')}"
                total_micros[unit_key] = total_micros.get(unit_key, 0) + actual_amount
    
    calculated_nutrition = {
        "calculated_macros": total_macros,
        "calculated_micros": total_micros,
        "portion_size": portion_size
    }
    
    yield Result(
        name="calculated",
        objects=[calculated_nutrition],
        metadata={"ingredients_count": len(ingredients)}
    )
    yield f"Nutrition calculated: {total_macros['kcal']:.0f} kcal | {total_macros['protein_g']:.0f}g P"
```

**ProfileUpdate Tool Implementation** (`tools/meal_logging/profile_update.py`):
```python
from typing import AsyncGenerator
from elysia.tree.objects import TreeData, Result, Error
from elysia.util.client import ClientManager
from elysia import tool
from datetime import datetime

@tool
async def profile_update_tool(
    tree_data: TreeData,
    client_manager: ClientManager,
    user_id: str = "",
    **kwargs
) -> AsyncGenerator[Result | str | Error, None]:
    """
    Update UserProfile with consumed nutrition and calculate remaining targets.
    
    Code-Based Tool: Updates profile and saves MealLogEntry.
    
    Environment:
        Reads: environment["meal_parser_tool"]["parsed_meal"],
               environment["nutrition_calc_tool"]["calculated"]
        Writes: environment["profile_update_tool"]["updated_profile"]
    """
    yield "Updating profile with consumed nutrition..."
    
    if not user_id:
        yield Error("user_id is required")
        return
    
    # Read parsed meal and calculated nutrition
    parsed_results = tree_data.environment.find("meal_parser_tool", "parsed_meal")
    nutrition_results = tree_data.environment.find("nutrition_calc_tool", "calculated")
    
    if not parsed_results or not parsed_results[0].objects:
        yield Error("Parsed meal not found")
        return
    
    if not nutrition_results or not nutrition_results[0].objects:
        yield Error("Calculated nutrition not found")
        return
    
    parsed_meal = parsed_results[0].objects[0]
    calculated_nutrition = nutrition_results[0].objects[0]
    
    client = client_manager.get_client()
    profile_collection = client.collections.get("UserProfile")
    log_collection = client.collections.get("MealLogEntry")
    
    # Read current profile
    profile_results = profile_collection.query.fetch_objects(
        where={"path": ["user_id"], "operator": "Equal", "valueString": user_id},
        limit=1
    )
    
    if not profile_results.objects:
        yield Error(f"Profile not found for user {user_id}")
        return
    
    profile = profile_results.objects[0].properties
    
    # Calculate remaining targets
    consumed_macros = calculated_nutrition.get("calculated_macros", {})
    target_macros = {
        "kcal": profile.get("tdee_kcal", 2000),
        "protein_g": profile.get("protein_g", 150),
        "fat_g": profile.get("fat_g", 67),
        "carb_g": profile.get("carb_g", 200)
    }
    
    # Get today's consumed (would need to query MealLogEntry for today)
    # For simplicity, assume this is first meal logged today
    remaining_targets = {
        "kcal": max(0, target_macros["kcal"] - consumed_macros.get("kcal", 0)),
        "protein_g": max(0, target_macros["protein_g"] - consumed_macros.get("protein_g", 0)),
        "fat_g": max(0, target_macros["fat_g"] - consumed_macros.get("fat_g", 0)),
        "carb_g": max(0, target_macros["carb_g"] - consumed_macros.get("carb_g", 0))
    }
    
    # Save MealLogEntry
    log_entry = {
        "log_id": f"log_{user_id}_{int(datetime.now().timestamp())}",
        "user_id": user_id,
        "logged_at": datetime.now().isoformat(),
        "meal_description": parsed_meal.get("original_description", ""),
        "parsed_dish": parsed_meal.get("dish", ""),
        "ingredients": parsed_meal.get("ingredients", []),
        "portion_size": parsed_meal.get("portion_size", 1.0),
        "calculated_macros": consumed_macros,
        "calculated_micros": calculated_nutrition.get("calculated_micros", {}),
        "validation_status": "complete",
        "parsing_method": "llm"
    }
    
    log_collection.data.insert(log_entry)
    
    # Update profile (store remaining targets - would need to aggregate all today's meals)
    # For MVP, just update last_logged_at
    profile.update({
        "updated_at": datetime.now().isoformat()
    })
    
    profile_collection.data.update(
        uuid=profile_results.objects[0].uuid,
        properties=profile
    )
    
    updated_data = {
        "remaining_targets": remaining_targets,
        "consumed_macros": consumed_macros,
        "log_entry": log_entry
    }
    
    yield Result(
        name="updated_profile",
        objects=[updated_data],
        metadata={"user_id": user_id, "logged_at": log_entry["logged_at"]}
    )
    yield f"Meal logged successfully. Remaining: {remaining_targets['kcal']:.0f} kcal | {remaining_targets['protein_g']:.0f}g P"
```

### Patterns & Best Practices

#### Async Generator Pattern (All Tools)
```python
from typing import AsyncGenerator
from elysia.tree.objects import TreeData, Result, Error
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
) -> AsyncGenerator[Result | str | Error, None]:
    # 1. Yield string for progress updates (automatically becomes Text response)
    yield "Starting operation..."
    
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
        name="output",  # Creates environment["tool_function"]["output"]
        objects=[result_data],
        metadata={"operation": "example"}
    )
    
    # 5. Handle errors gracefully
    if error_condition:
        yield Error("Descriptive error message")
        return
    
    # 6. Final string for completion
    yield "Operation completed successfully"
```

#### Environment Key Conventions
- **Elysia Standard Pattern**: `environment[tool_name][name]` where:
  - `tool_name` = function name (e.g., "profile_crud_tool")
  - `name` = Result's `name` parameter (e.g., "profile", "targets")
- **Tools write only to their namespace**: Each tool writes to `environment[function_name][...]`
- **Tools read from any namespace**: Use `tree_data.environment.find(tool_name, name)`
- **Use descriptive name parameters**: `"profile"`, `"targets"`, `"results"`, `"plan"`, `"report"`

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

**FastAPI Endpoints** (wrap Elysia Tree calls):
```python
# elysia/api/routes/meal_agent.py
from fastapi import APIRouter, WebSocket, HTTPException
from elysia.api.services.user import UserManager
import uuid

router = APIRouter(prefix="/api/v1/meal")

# Global UserManager instance (or inject via dependency)
user_manager = UserManager()

@router.post("/plans/day")
async def generate_daily_plan(user_id: str, query: str = "", conversation_id: str = None):
    """Generate daily meal plan via REST endpoint."""
    if not conversation_id:
        conversation_id = f"conv_{uuid.uuid4().hex[:8]}"
    query_id = f"query_{uuid.uuid4().hex[:8]}"
    
    results = []
    errors = []
    
    async for payload in user_manager.process_tree(
        query=query,
        user_id=user_id,
        conversation_id=conversation_id,
        query_id=query_id
    ):
        # Payloads from process_tree are dictionaries
        if payload and payload.get("type") == "result":
            results.append(payload.get("data", {}))
        elif payload and payload.get("type") == "error":
            errors.append(payload.get("data", {}))
    
    if errors:
        raise HTTPException(status_code=400, detail=errors[-1])
    
    # Find plan result
    plan_result = next(
        (r for r in results if r.get("name") == "plan"),
        None
    )
    
    return {"plan": plan_result if plan_result else None, "conversation_id": conversation_id}

@router.websocket("/ws/plan/{user_id}")
async def plan_stream(websocket: WebSocket, user_id: str):
    """Stream daily meal plan generation via WebSocket."""
    await websocket.accept()
    
    conversation_id = f"conv_{uuid.uuid4().hex[:8]}"
    
    try:
        # Receive initial query
        data = await websocket.receive_json()
        query = data.get("query", "")
        
        query_id = f"query_{uuid.uuid4().hex[:8]}"
        
        async for payload in user_manager.process_tree(
            query=query,
            user_id=user_id,
            conversation_id=conversation_id,
            query_id=query_id
        ):
            # Send all payloads directly to client
            if payload and payload.get("type") != "timer" and payload.get("type") != "training_update":
                await websocket.send_json(payload)
                
    except Exception as e:
        await websocket.send_json({
            "type": "error",
            "data": {"error": str(e)}
        })
    finally:
        await websocket.close()

@router.post("/meals/log")
async def log_meal(user_id: str, meal_description: str, conversation_id: str = None):
    """Log consumed meal via natural language."""
    if not conversation_id:
        conversation_id = f"conv_{uuid.uuid4().hex[:8]}"
    query_id = f"query_{uuid.uuid4().hex[:8]}"
    
    query = f"Log meal: {meal_description}"
    results = []
    errors = []
    
    async for payload in user_manager.process_tree(
        query=query,
        user_id=user_id,
        conversation_id=conversation_id,
        query_id=query_id
    ):
        if payload and payload.get("type") == "result":
            results.append(payload.get("data", {}))
        elif payload and payload.get("type") == "error":
            errors.append(payload.get("data", {}))
    
    if errors:
        raise HTTPException(status_code=400, detail=errors[-1])
    
    # Find nutrition calculation result
    nutrition_result = next(
        (r for r in results if r.get("name") == "calculated"),
        None
    )
    profile_result = next(
        (r for r in results if r.get("name") == "updated_profile"),
        None
    )
    
    return {
        "calculated_macros": nutrition_result.get("objects", [{}])[0].get("calculated_macros") if nutrition_result and nutrition_result.get("objects") else {},
        "remaining_targets": profile_result.get("objects", [{}])[0].get("remaining_targets") if profile_result and profile_result.get("objects") else {},
        "conversation_id": conversation_id
    }
```

### Database Connections

**Note**: MealAgent uses Elysia's built-in `ClientManager` which is automatically injected into tools. No custom ClientManager needed unless you need MealAgent-specific configurations.

**Using ClientManager in Tools**:
```python
# ClientManager is automatically injected by Elysia
async def my_tool(
    tree_data: TreeData,
    client_manager: ClientManager,  # Auto-injected
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

---

**Status**: Living document - Update as implementation progresses
**Last Updated**: 2025-10-28
**Owner**: [Your Name/Team]

