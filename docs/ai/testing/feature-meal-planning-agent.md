---
phase: testing
title: Testing Strategy - Meal Planning Agent
description: Define testing approach, test cases, and quality assurance for MealAgent
---

# Testing Strategy - Meal Planning Agent

## Test Coverage Goals
**What level of testing do we aim for?**

- **Unit Test Coverage**: 100% of new code in `elysia/MealAgent/` (tools, utilities, ETL)
- **Integration Test Scope**: All critical workflows (profile → plan → shop → cook) plus error handling paths
- **End-to-End Test Scenarios**: Complete user journeys (onboarding → daily plan → weekly plan → cooking mode)
- **Performance Benchmarks**: Validate latency requirements (see design doc)
- **Alignment**: All test cases map to acceptance criteria in requirements doc

## Unit Tests

### Component: Profile Tools

#### ProfileCRUDTool (`tools/profile/profile_crud.py`)
- [ ] **Test: Create new profile with valid data**
  - Input: Complete profile data (user_id, age, gender, weight, height, activity_level)
  - Expected: Profile saved to Weaviate; Result yielded with `environment["profile_crud_tool"]["profile"]` key
  - Coverage: Happy path

- [ ] **Test: Create profile with missing required field**
  - Input: Profile data missing `age`
  - Expected: Error yielded with message listing required fields
  - Coverage: Input validation

- [ ] **Test: Update existing profile**
  - Input: Existing user_id with updated weight_kg
  - Expected: Profile updated in Weaviate; Result yielded
  - Coverage: Update operation

- [ ] **Test: Read non-existent profile**
  - Input: user_id that doesn't exist
  - Expected: Error yielded with "Profile not found"
  - Coverage: Error handling

- [ ] **Test: Weaviate connection failure**
  - Setup: Mock Weaviate client to raise connection error
  - Expected: Error yielded with descriptive message (not exception)
  - Coverage: External dependency failure

#### MacroCalcTool (`tools/profile/macro_calc.py`)
- [ ] **Test: Calculate TDEE for male, sedentary**
  - Input: age=30, gender=male, weight_kg=80, height_cm=180, activity_level=sedentary
  - Expected: TDEE ≈ 1958 kcal (Harris-Benedict formula)
  - Coverage: Male BMR calculation

- [ ] **Test: Calculate TDEE for female, very_active**
  - Input: age=25, gender=female, weight_kg=60, height_cm=165, activity_level=very_active
  - Expected: TDEE ≈ 2380 kcal
  - Coverage: Female BMR calculation, high activity multiplier

- [ ] **Test: Macro distribution (30/30/40)**
  - Input: TDEE=2000 kcal
  - Expected: protein_g=150, fat_g=67, carb_g=200
  - Coverage: Macro ratio calculation

- [ ] **Test: Missing profile in environment**
  - Setup: Empty environment (no `environment["profile_crud_tool"]["profile"]`)
  - Expected: Error yielded prompting to run ProfileCRUDTool first
  - Coverage: Dependency check

### Component: Constraint Tools

#### constraints_guard_tool (`tools/constraints/constraints_guard.py`) - Consolidated
- [ ] **Test: Generate filters for vegetarian + dairy allergy**
  - Input: profile with diet_type=vegetarian, allergens=[dairy]
  - Expected: Result with filters `{"where": {"operator": "And", "operands": [{"path": ["diet_type"], "operator": "Equal", "valueString": "vegetarian"}, {"path": ["allergens"], "operator": "NotEqual", "valueString": "dairy"}]}}`
  - Coverage: Multiple constraints (diet + allergen)

- [ ] **Test: Generate filters with no allergens**
  - Input: profile with diet_type=vegan, allergens=[]
  - Expected: Result with filters `{"where": {"path": ["diet_type"], "operator": "Equal", "valueString": "vegan"}}`
  - Coverage: Empty allergen list

- [ ] **Test: Union of multiple allergens**
  - Input: allergens=[nuts, shellfish, gluten]
  - Expected: All three in allergens_exclude (using NotEqual or NotContainsAny)
  - Coverage: Multiple allergen filtering

- [ ] **Test: Apply max cooking time constraint**
  - Input: profile with max_cooking_time_min=30
  - Expected: Result with filters including `{"path": ["cooking_time"], "operator": "LessThanEqual", "valueInt": 30}`
  - Coverage: Time constraint

- [ ] **Test: No time/device constraints declared**
  - Input: profile without max_cooking_time_min or available_equipment
  - Expected: Result with filters only for diet/allergen (no time/device filters)
  - Coverage: Optional constraint handling

### Component: Search Tools

#### search_and_rank_tool (`tools/search/search_and_rank.py`) - Uses Elysia query internally
- Note: This tool uses Elysia `query` tool internally for hybrid search, then applies ranking logic. The demo `Recipe` schema includes `diet_type`, `allergens`, and `cooking_time` as filterable properties.
- [ ] **Test: Search and rank with diet filter**
  - Setup: Mock Weaviate with 100 recipes (50 vegetarian, 50 not)
  - Input: query_text="pasta", constraints from `constraints_guard_tool.filters`
  - Expected: Results contain only vegetarian recipes, ranked by macro fit and semantic relevance
  - Coverage: Hard filter enforcement + ranking

- [ ] **Test: Allergen exclusion filter**
  - Setup: Mock recipes with allergens=[nuts], [dairy], []
  - Input: constraints from `constraints_guard_tool.filters` with allergens_exclude
  - Expected: Only recipes with allergens=[] returned, ranked appropriately
  - Coverage: Allergen filtering + ranking

- [ ] **Test: Time constraint filter**
  - Setup: Recipes with cooking_time=[15, 30, 45, 60]
  - Input: constraints from `constraints_guard_tool.filters` with max_cooking_time_min=30
  - Expected: Only recipes with cooking_time <= 30 returned, ranked appropriately
  - Coverage: Time filtering + ranking

- [ ] **Test: Ranking by macro fit**
  - Setup: Recipes with varying macros_per_serving
  - Input: targets from `macro_calc_tool.targets`
  - Expected: Recipes ranked by how well they fit target macros per meal
  - Coverage: Multi-criteria ranking

- [ ] **Test: Empty search results**
  - Setup: Filters so restrictive no recipes match
  - Expected: Empty results list (not error)
  - Coverage: No-match scenario

**Note**: Ranking logic is now part of `search_and_rank_tool` (see Search Tools section above). Tests for ranking are included in the `search_and_rank_tool` test cases.

### Component: Meal Logging Tools

#### log_meal_e2e_tool (`tools/meal_logging/log_meal_e2e.py`) - End-to-end meal logging
- [ ] **Test: Parse meal description (LLM-assisted)**
  - Input: meal_description="I ate chicken salad with olive oil"
  - Expected: Parsed meal with dish name and ingredients (internal step)
  - Coverage: LLM parsing

- [ ] **Test: Calculate nutrition from FDC**
  - Input: Parsed meal with ingredients and quantities
  - Expected: Calculated macros and micros (internal step)
  - Coverage: Nutrition calculation

- [ ] **Test: Update profile and save MealLogEntry**
  - Input: Calculated nutrition
  - Expected: MealLogEntry saved, UserProfile updated with remaining targets
  - Coverage: Profile update

- [ ] **Test: Invalid meal description**
  - Input: meal_description=""
  - Expected: Error yielded
  - Coverage: Input validation

- [ ] **Test: Ingredient not found in FDC**
  - Input: meal_description="I ate unknown food"
  - Expected: Error or warning with suggestion
  - Coverage: Missing data handling

**Note**: Meal parsing, nutrition calculation, and profile update are now handled by a single `log_meal_e2e_tool` to reduce tool calls.

### Component: Plan Day Tools

#### plan_day_e2e_tool (`tools/plan_day/plan_day_e2e.py`) - End-to-end daily planning
- [ ] **Test: Assemble 3-meal plan from 20 candidates**
  - Input: 20 ranked recipes
  - Expected: Plan with breakfast, lunch, dinner (all different recipes)
  - Coverage: Meal selection logic

- [ ] **Test: Calculate total macros for plan**
  - Input: breakfast=500 kcal, lunch=600 kcal, dinner=700 kcal
  - Expected: total_macros.kcal=1800
  - Coverage: Macro aggregation

- [ ] **Test: Insufficient recipes (only 2 available)**
  - Input: 2 recipes in topk
  - Expected: Error yielded
  - Coverage: Insufficient data

- [ ] **Test: Plan validation (handled internally by plan_day_e2e_tool)**
  - Input: Plan with macros within ±10% of target
  - Expected: Validation passes (internal step)
  - Coverage: Macro tolerance

- [ ] **Test: Detect allergen violation (handled internally)**
  - Input: plan contains recipe with nuts, user has nut allergy
  - Expected: Validation fails with allergen warning (internal step)
  - Coverage: Constraint violation detection

- [ ] **Test: Detect diet type violation (handled internally)**
  - Input: user is vegetarian, plan contains chicken recipe
  - Expected: Validation fails (internal step)
  - Coverage: Diet constraint

**Note**: Plan validation is now handled internally by `plan_day_e2e_tool`. The tool validates constraints and macros as part of its workflow before yielding the final plan.

### Component: Plan Week Tools

#### plan_week_e2e_tool (`tools/plan_week/plan_week_e2e.py`) - End-to-end weekly planning with variety
- [ ] **Test: Assemble 21-meal plan (7 days × 3 meals)**
  - Input: 50+ ranked recipes
  - Expected: Plan with 21 meals, all different recipes where possible
  - Coverage: Weekly meal selection

- [ ] **Test: Variety enforcement**
  - Input: Weekly plan
  - Expected: Variety score >70, <3 repetitions of primary protein/cuisine per week
  - Coverage: Variety detection and scoring (handled internally)

- [ ] **Test: Calculate total and average daily macros**
  - Input: 21 meals with varying macros
  - Expected: Total macros for week and average per day calculated
  - Coverage: Macro aggregation

- [ ] **Test: Insufficient recipes for weekly plan**
  - Input: Only 10 recipes available
  - Expected: Error or plan with recipe reuse (with variety penalty)
  - Coverage: Data insufficiency

**Note**: Weekly planning and variety enforcement are now handled by a single `plan_week_e2e_tool` to reduce tool calls.

### Component: Pantry & Shopping Tools

#### PantryDiff (`tools/shopping/pantry_diff.py`)
- [ ] **Test: Subtract pantry items from shopping list**
  - Input: shopping needs 2 cups flour, pantry has 1 cup
  - Expected: Diff shows 1 cup flour needed
  - Coverage: Partial coverage

- [ ] **Test: Full coverage in pantry**
  - Input: All shopping items in pantry with sufficient quantity
  - Expected: Empty diff list
  - Coverage: No shopping needed

- [ ] **Test: Unit conversion (cups to grams)**
  - Input: shopping needs 200g flour, pantry has 1 cup (≈120g)
  - Expected: Diff shows 80g flour needed
  - Coverage: Unit conversion

- [ ] **Test: Mismatched units without conversion**
  - Input: shopping needs "1 large onion", pantry has "100g onion"
  - Expected: Cannot subtract (add to diff as is, or flag for manual review)
  - Coverage: Edge case handling

### Component: Gap Fill Tools

#### gap_fill_tool (`tools/gap_fill/gap_fill.py`) - Merged: calc + suggest + apply
- [ ] **Test: Calculate protein deficit**
  - Input: target=150g protein, plan=120g protein
  - Expected: deficit=30g protein (internal step)
  - Coverage: Single nutrient deficit

- [ ] **Test: Calculate multiple deficits**
  - Input: target={kcal:2000, protein:150, carb:200}, plan={kcal:1800, protein:140, carb:220}
  - Expected: deficits={kcal:200, protein:10, carb:-20} (internal step)
  - Coverage: Mixed deficits and surplus

- [ ] **Test: Suggest high-protein snack for protein deficit**
  - Input: deficit={protein:30g}, candidates=[protein_bar:25g, apple:1g]
  - Expected: protein_bar suggested (internal step)
  - Coverage: Deficit-driven selection

- [ ] **Test: Apply snack to plan**
  - Input: snack suggestion and plan
  - Expected: Updated plan with snack added, total macros recalculated
  - Coverage: Snack application

- [ ] **Test: No deficits (plan meets all targets)**
  - Input: plan equals or exceeds all targets
  - Expected: All deficits ≤ 0, no snack suggestions
  - Coverage: Target met scenario

- [ ] **Test: No suitable snack available**
  - Input: deficit={protein:30g}, candidates all have <5g protein
  - Expected: Text warning or best available option
  - Coverage: Insufficient options

**Note**: Gap calculation, snack suggestion, and application are now handled by a single `gap_fill_tool` to reduce tool calls.

### Component: Micronutrient Tools

#### micros_tool (`tools/micros/micros.py`) - Merged: check + suggest
- [ ] **Test: Aggregate vitamin C from 3 meals**
  - Setup: breakfast=20mg, lunch=30mg, dinner=40mg
  - Expected: total_vitamin_c=90mg (internal step)
  - Coverage: Micronutrient summation

- [ ] **Test: FdcPortion conversion (1 cup → grams → nutrients)**
  - Setup: Recipe uses "1 cup broccoli", FdcPortion maps to 91g, FdcNutrient has per-100g values
  - Expected: Correct proportional calculation (internal step)
  - Coverage: Portion conversion accuracy

- [ ] **Test: Suggest foods rich in deficient nutrients**
  - Input: deficit={vitamin_c: 50mg}
  - Expected: Foods high in vitamin C suggested (internal step)
  - Coverage: Nutrient-driven suggestions

- [ ] **Test: Missing FdcPortion data**
  - Setup: Ingredient without FdcPortion entry
  - Expected: Warning logged; skip or use approximation
  - Coverage: Missing data handling

**Note**: Micronutrient checking and suggestion are now handled by a single `micros_tool` to reduce tool calls.

### Component: Substitution Tools

#### substitute_tool (`tools/substitution/substitute.py`) - Merged: suggest + apply
- [ ] **Test: Find ingredient substitutes with macro matching**
  - Input: ingredient="chicken breast", tolerance=±20%
  - Expected: Substitutes with similar macros (protein, fat, carb) suggested
  - Coverage: Macro equivalence matching

- [ ] **Test: Apply substitute to plan**
  - Input: substitute suggestion and plan
  - Expected: Updated plan with ingredient replaced, macros recalculated
  - Coverage: Substitution application

- [ ] **Test: No suitable substitute found**
  - Input: ingredient with unique macro profile, tolerance too strict
  - Expected: Warning or best available option
  - Coverage: Insufficient options

- [ ] **Test: Allergen violation check**
  - Input: Substitute contains allergen (e.g., nuts)
  - Expected: Substitute rejected or flagged
  - Coverage: Constraint enforcement

**Note**: Substitution suggestion and application are now handled by a single `substitute_tool` to reduce tool calls.

### Component: Utilities

#### Harris-Benedict TDEE (`utils/nutrition.py`)
- [ ] **Test: Male BMR calculation**
  - Input: age=30, gender=male, weight_kg=80, height_cm=180
  - Expected: BMR ≈ 1798 kcal
  - Coverage: Male formula

- [ ] **Test: Female BMR calculation**
  - Input: age=25, gender=female, weight_kg=60, height_cm=165
  - Expected: BMR ≈ 1379 kcal
  - Coverage: Female formula

- [ ] **Test: Activity multiplier (sedentary)**
  - Input: BMR=1500, activity_level=sedentary
  - Expected: TDEE=1800 (1500 × 1.2)
  - Coverage: Multiplier application

#### Unit Conversion (`utils/unit_conversion.py`)
- [ ] **Test: Convert cups to grams (flour)**
  - Input: 1 cup flour
  - Expected: ≈120 grams
  - Coverage: Volume to weight

- [ ] **Test: Convert tablespoons to milliliters**
  - Input: 2 tbsp
  - Expected: ≈30 ml
  - Coverage: Volume to volume

- [ ] **Test: Unsupported conversion**
  - Input: "1 large onion" to grams (no standard conversion)
  - Expected: None or error indicator
  - Coverage: Limitation handling

## Integration Tests

### Workflow: Profile Setup → Daily Plan

#### Integration Test 1: Complete Daily Plan Generation (Optimized)
```python
async def test_daily_plan_workflow():
    """
    End-to-end workflow: Create profile → Calculate macros → Apply constraints → Search and rank → Assemble plan (E2E)
    Note: plan_day_e2e_tool handles all planning steps internally (resolve targets, search, rank, assemble, validate)
    """
    # Setup
    # Note: In Elysia, tools receive tree_data and client_manager automatically
    tree_data = TreeData(...)
    client_manager = MockClientManager()
    
    # Step 1: Create profile
    async for output in profile_crud_tool(
        tree_data=tree_data,
        client_manager=client_manager,
        action="create",
        profile_data={...}
    ):
        if isinstance(output, Result):
            assert output.name == "profile"
            # Check environment: environment["profile_crud_tool"]["profile"]
            profile_results = tree_data.environment.find("profile_crud_tool", "profile")
            assert profile_results and len(profile_results[0].objects) > 0
    
    # Step 2: Calculate macros
    async for output in macro_calc_tool(
        tree_data=tree_data,
        client_manager=client_manager
    ):
        if isinstance(output, Result):
            assert output.name == "targets"
            # Check environment: environment["macro_calc_tool"]["targets"]
            targets_results = tree_data.environment.find("macro_calc_tool", "targets")
            assert targets_results and targets_results[0].objects[0]["tdee_kcal"] > 0
    
    # Step 3: Apply constraints
    async for output in constraints_guard_tool(
        tree_data=tree_data,
        client_manager=client_manager
    ):
        if isinstance(output, Result):
            assert output.name == "filters"
            # Check environment: environment["constraints_guard_tool"]["filters"]
            filters_results = tree_data.environment.find("constraints_guard_tool", "filters")
            assert filters_results and filters_results[0].objects[0].get("where")
    
    # Step 4: Search and rank recipes (optimized - single tool using Elysia query)
    async for output in search_and_rank_tool(
        tree_data=tree_data,
        client_manager=client_manager,
        query_text="healthy meals",
        top_k=20
    ):
        if isinstance(output, Result):
            # Check environment: environment["search_and_rank_tool"]["topk"]
            topk_results = tree_data.environment.find("search_and_rank_tool", "topk")
            assert topk_results and len(topk_results[0].objects) == 20
    
    # Step 5: Assemble daily plan (optimized - E2E tool handles all steps internally)
    async for output in plan_day_e2e_tool(
        tree_data=tree_data,
        client_manager=client_manager
    ):
        if isinstance(output, Result):
            # Check environment: environment["plan_day_e2e_tool"]["plan"]
            plan_results = tree_data.environment.find("plan_day_e2e_tool", "plan")
            plan = plan_results[0].objects[0] if plan_results else {}
            assert "breakfast" in plan.get("meals", {})
            assert "lunch" in plan.get("meals", {})
            assert "dinner" in plan.get("meals", {})
            # Plan validation is handled internally by plan_day_e2e_tool
            assert plan.get("validation", {}).get("valid") == True
```

### Tree-Based Execution (Elysia)
For tests that execute via the Elysia Tree (instead of calling tools directly), instantiate a MealAgent Tree and register tools as per docs:

```python
from elysia.MealAgent.tree.meal_tree import build_meal_agent_tree
from elysia.config import Settings

def test_tree_based_daily_plan():
    # Build a dedicated MealAgent Tree with branches & tools registered
    tree = build_meal_agent_tree(settings=Settings(), user_id="test_user")
    # Run process_tree or specific workflows depending on your test harness
    # e.g., via UserManager/TreeManager in API layer
```

- [ ] **Test: Profile → Plan workflow (vegetarian user)**
  - Coverage: Full happy path with diet constraint

- [ ] **Test: Profile → Plan workflow (user with nut allergy)**
  - Coverage: Allergen filtering across entire pipeline

- [ ] **Test: Profile → Plan with gap fill**
  - Setup: Initial plan has protein deficit
  - Expected: Gap fill triggered, snack added, plan re-validated
  - Coverage: Gap fill integration

### Workflow: Weekly Plan → Shopping List

- [ ] **Test: Generate weekly plan (21 meals)**
  - Coverage: Weekly assembly + variety enforcement

- [ ] **Test: Extract shopping list from weekly plan**
  - Expected: All ingredients aggregated with quantities
  - Coverage: Shopping list generation

- [ ] **Test: Subtract pantry from shopping list**
  - Setup: Pantry has 50% of needed ingredients
  - Expected: Diff contains only missing ingredients
  - Coverage: Pantry integration

### Workflow: Cooking Mode

- [ ] **Test: Parse recipe into steps**
  - Input: Recipe with multi-paragraph directions
  - Expected: Structured steps with time estimates
  - Coverage: CookMode parsing

- [ ] **Test: Stream cooking steps via WebSocket**
  - Expected: Steps yielded progressively (not all at once)
  - Coverage: Streaming behavior

### Workflow: Meal Logging with Confirmation (Optimized)

- [ ] **Test: Log meal requires confirmation before save**
  - Flow: `log_meal_e2e_tool` handles parse → calculate nutrition internally → show preview → confirm=false → no `MealLogEntry` persisted
  - Then confirm=true → `MealLogEntry` created and profile updated
  - Coverage: UX confirmation gate per requirements
  - Note: `log_meal_e2e_tool` orchestrates all steps (parse, calculate, update) internally to reduce tool calls

### Error Handling Integration

- [ ] **Test: Weaviate connection failure during search**
  - Setup: Disconnect Weaviate mid-workflow
  - Expected: Error yielded, workflow stops gracefully (no crash)
  - Coverage: External service failure

- [ ] **Test: Insufficient recipes after filtering**
  - Setup: Constraints so strict only 1 recipe matches
  - Expected: Error in `plan_day_e2e_tool` (need 3 for daily plan)
  - Coverage: Data insufficiency

## End-to-End Tests

### User Journey 1: First-Time User Onboarding
- [ ] **Scenario**: New user creates profile and generates first daily plan
  - Step 1: User navigates to ChatPage, sends query "Create my profile: age 30, weight 75kg, vegetarian, no peanuts"
  - Step 2: TDEE displayed on form (preview)
  - Step 3: User clicks "Generate Daily Plan"
  - Step 4: Streaming progress displayed (searching, ranking, assembling)
  - Step 5: Plan displayed with 3 meals and macro totals
  - Step 6: User clicks "View Shopping List"
  - Step 7: Shopping list displayed with ingredient totals
  - **Expected**: All steps complete without errors; plan meets constraints

### User Journey 2: Weekly Planning with Pantry
- [ ] **Scenario**: Returning user generates weekly plan with pantry awareness
  - Step 1: User navigates to PantryManager, adds items (flour: 2 cups, chicken: 500g)
  - Step 2: User requests weekly plan (21 meals)
  - Step 3: Plan generated with variety report (no protein repeated >2x)
  - Step 4: Shopping list generated, pantry items subtracted
  - Step 5: User exports shopping list as PDF
  - **Expected**: Shopping list excludes pantry items; variety enforced

### User Journey 3: Cooking Mode
- [ ] **Scenario**: User follows step-by-step cooking instructions
  - Step 1: User selects recipe from plan
  - Step 2: Clicks "Start Cooking"
  - Step 3: Steps stream in order with timers
  - Step 4: User completes recipe
  - **Expected**: All steps delivered; timers functional

### Regression Tests
- [ ] **Test: Existing profiles still load after schema updates**
  - Coverage: Backward compatibility

- [ ] **Test: Old plans still render in UI**
  - Coverage: Data migration

## Test Data

### Test Fixtures and Mocks

#### Mock Weaviate Client
```python
# tests/mocks/weaviate_mock.py
class MockWeaviateClient:
    def __init__(self, recipes=None):
        self.recipes = recipes or []
    
    def query_hybrid(self, query, filters, limit):
        # Filter recipes based on filters
        results = [r for r in self.recipes if self._matches_filters(r, filters)]
        return MockQueryResult(results[:limit])
```

#### Test Recipe Data
```python
# tests/fixtures/recipes.py
VEGETARIAN_PASTA = {
    "recipe_id": "test_001",
    "title": "Vegetable Pasta",
    "diet_type": "vegetarian",
    "allergens": ["gluten"],
    "macros_per_serving": {"kcal": 450, "protein_g": 15, "fat_g": 12, "carb_g": 70},
    "ingredients": [{"name": "pasta", "amount": 200, "unit": "g"}],
    "directions": ["Boil water", "Cook pasta", "Add vegetables"],
    "cooking_time": 25
}

VEGAN_SMOOTHIE = {
    "recipe_id": "test_002",
    "title": "Green Smoothie",
    "diet_type": "vegan",
    "allergens": [],
    "macros_per_serving": {"kcal": 200, "protein_g": 5, "fat_g": 3, "carb_g": 40},
    "ingredients": [{"name": "spinach", "amount": 100, "unit": "g"}],
    "directions": ["Blend ingredients"],
    "cooking_time": 5
}
```

#### Test User Profiles
```python
# tests/fixtures/profiles.py
STANDARD_USER = {
    "user_id": "test_user_001",
    "age": 30,
    "gender": "male",
    "weight_kg": 75,
    "height_cm": 175,
    "activity_level": "moderate",
    "diet_type": "vegetarian",
    "allergens": ["dairy"],
    "max_cooking_time_min": 45
}
```

### Seed Data Requirements
- **Weaviate Test Collections**: Populated with 100 test recipes covering all diet types and common allergens
- **FDC Test Data**: Subset of 50 common foods with nutrients and portions
- **Test Database**: SQLite or in-memory Weaviate for CI/CD

## Test Reporting & Coverage

### Coverage Commands and Thresholds
```bash
# Backend (Python)
cd elysia
pytest --cov=MealAgent --cov-report=html --cov-report=term
# Threshold: 100% for new code in MealAgent/

# Frontend (TypeScript)
cd elysia-frontend
npm run test -- --coverage
# Threshold: 90% for new components
```

### Coverage Gaps (To Be Filled)
- **Complex ETL Logic**: Recipe normalization script (low priority for MVP; manual QA sufficient)
- **Preprocessor**: Metadata generation (integration tests cover; unit tests deferred)
- **LLM-based Features**: Elysia `cited_summarize` tool (hard to unit test; rely on integration tests)

### Links to Test Reports
- CI/CD Pipeline: [GitHub Actions workflow badge]
- Coverage Dashboard: [Codecov.io link - TBD]

### Manual Testing Outcomes
- **Accessibility Audit**: WCAG 2.1 AA compliance checked with axe DevTools (Week 11)
- **Browser Compatibility**: Tested on Chrome, Firefox, Safari, Edge (Week 11)
- **Mobile Responsiveness**: Tested on iOS Safari, Android Chrome (Week 11)

## Manual Testing

### UI/UX Testing Checklist
- [ ] **ChatPage - Profile Creation**: Form validation works (invalid age shows error via Error object)
- [ ] **ChatPage - Recipe Search**: Filters (diet, allergen, time) update results via natural language queries
- [ ] **ChatPage - Meal Planning**: Streaming progress visible (not frozen) - tool yields Response/Status objects
- [ ] **PlanView**: Macro charts render correctly
- [ ] **CookingMode**: Step transitions smooth; timers accurate
- [ ] **PantryManager**: CRUD operations update immediately
- [ ] **ShoppingListView**: Print/export generates correct format
- [ ] **ExplainDialog**: Explanation text references actual data

### Accessibility (WCAG 2.1 AA)
- [ ] **Keyboard Navigation**: All interactive elements reachable via Tab
- [ ] **Screen Reader**: NVDA/JAWS can read all content
- [ ] **Color Contrast**: Text meets 4.5:1 ratio
- [ ] **Focus Indicators**: Visible focus rings on all inputs/buttons
- [ ] **Alt Text**: All images/charts have descriptive alt text

### Browser/Device Compatibility
- [ ] **Chrome 120+** (Windows, macOS, Linux)
- [ ] **Firefox 120+** (Windows, macOS)
- [ ] **Safari 17+** (macOS, iOS)
- [ ] **Edge 120+** (Windows)
- [ ] **Mobile**: iOS Safari 17+, Android Chrome 120+

### Smoke Tests After Deployment
- [ ] **Health Check**: `/api/health` returns 200
- [ ] **Weaviate Connection**: `/api/v1/status` shows Weaviate connected
- [ ] **Generate Plan**: Create profile → generate daily plan end-to-end
- [ ] **WebSocket**: Streaming endpoint accepts connections

## Performance Testing

### Load Testing Scenarios
1. **Concurrent Users**: 100 users generating daily plans simultaneously
   - Tool: Locust or k6
   - Expected: 95th percentile response time <8 seconds

2. **Search Query Load**: 1000 search requests/minute
   - Expected: P95 latency <3 seconds

3. **Sustained Load**: 50 concurrent users for 1 hour
   - Expected: No memory leaks; CPU <80%

### Stress Testing Approach
- **Weaviate Limits**: Test with 1M recipes to find breaking point
- **Tree Execution**: Deep workflows (10+ tools in sequence)
- **WebSocket Connections**: 500 concurrent streaming sessions

### Performance Benchmarks
| Operation | Target | Measured | Status |
|-----------|--------|----------|--------|
| Hybrid Search (100k recipes) | <2s | TBD | Pending |
| Daily Plan Generation | <5s | TBD | Pending |
| Weekly Plan Generation | <15s | TBD | Pending |
| Micronutrient Aggregation (21 meals) | <3s | TBD | Pending |
| Streaming First Yield | <500ms | TBD | Pending |

## Bug Tracking

### Issue Tracking Process
1. **Report**: File issue in GitHub with template (steps to reproduce, expected, actual)
2. **Triage**: Label severity (critical, major, minor) and priority
3. **Fix**: Assign to sprint; link PR to issue
4. **Verify**: QA re-tests on staging before closing
5. **Regression**: Add test case to prevent recurrence

### Bug Severity Levels
- **Critical**: Data corruption, security vulnerability, complete feature failure → Fix immediately
- **Major**: Feature unusable, incorrect calculations, broken workflow → Fix within 1 sprint
- **Minor**: UI glitch, typo, non-critical edge case → Fix within 2 sprints or backlog

### Regression Testing Strategy
- **Automated Regression Suite**: All integration tests run on every PR
- **Manual Regression**: Smoke tests run before each release
- **Continuous**: Coverage metrics tracked; new bugs require new tests

---

**Status**: ✅ **In Progress** - Test structure created, initial unit and integration tests implemented
**Last Updated**: 2025-01-27
**Owner**: MealAgent Development Team

## Test Implementation Status

### Unit Tests Created ✅
- **test_profile_tools.py**: Tests for `profile_crud_tool` (create, update, read, error cases) and `macro_calc_tool` (TDEE calculation, macro distribution, missing profile). Includes tests for `calculate_harris_benedict_tdee` utility function.
- **test_constraints_tools.py**: Tests for `constraints_guard_tool` (vegetarian + allergy, no allergens, max cooking time, missing profile).
- **test_planning_helpers.py**: Tests for `_get_meal_macros`, `_validate_macro_targets`, `_validate_constraints` helper functions.

### Integration Tests Created ✅
- **test_daily_planning_workflow.py**: Complete daily planning workflow test (profile → macros → constraints → search → plan). Includes test for allergen filtering workflow.

### Test Coverage Status
- **Profile Tools**: ✅ Unit tests created (create, update, read, error cases)
- **Macro Calculation**: ✅ Unit tests created (TDEE, macro distribution, missing profile)
- **Constraints Guard**: ✅ Unit tests created (diet, allergens, time constraints)
- **Planning Helpers**: ✅ Unit tests created (macros extraction, validation)
- **Search Tools**: ✅ Unit tests created (basic search, filters, ranking, empty results)
- **Recipe Macros**: ✅ Unit tests created (cached macros, FDC lookup, VN→EN translation)
- **Planning E2E**: ✅ Unit tests created (daily/weekly planning, variety enforcement)
- **Meal Logging**: ✅ Unit tests created (log meal, meal history, date filtering)
- **Pantry Tools**: ✅ Unit tests created (CRUD operations, shopping list calculation)
- **Daily Planning Workflow**: ✅ Integration test created
- **Optimization Tools**: ⏳ Pending (gap_fill, substitute, micros)
- **Cook Mode**: ⏳ Pending

### Running Tests
```bash
# Run all MealAgent tests
pytest tests/meal_agent/ -v

# Run unit tests only
pytest tests/meal_agent/unit/ -v

# Run integration tests only
pytest tests/meal_agent/integration/ -v

# Run with coverage
pytest tests/meal_agent/ --cov=MealAgent --cov-report=html --cov-report=term
```

