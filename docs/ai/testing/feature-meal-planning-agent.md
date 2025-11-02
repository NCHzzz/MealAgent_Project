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

#### DietAllergenGuard (`tools/constraints/diet_allergen_guard.py`)
- [ ] **Test: Generate filters for vegetarian + dairy allergy**
  - Input: profile with diet_type=vegetarian, allergens=[dairy]
  - Expected: Result with filters `{"diet_type": "vegetarian", "allergens_exclude": ["dairy"]}`
  - Coverage: Multiple constraints

- [ ] **Test: Generate filters with no allergens**
  - Input: profile with diet_type=vegan, allergens=[]
  - Expected: Result with filters `{"diet_type": "vegan", "allergens_exclude": []}`
  - Coverage: Empty allergen list

- [ ] **Test: Union of multiple allergens**
  - Input: allergens=[nuts, shellfish, gluten]
  - Expected: All three in allergens_exclude
  - Coverage: Multiple allergen filtering

#### TimeDeviceGuard (`tools/constraints/time_device_guard.py`)
- [ ] **Test: Apply max cooking time constraint**
  - Input: profile with max_cooking_time_min=30
  - Expected: Result with filters `{"max_time_min": 30}`
  - Coverage: Time constraint

- [ ] **Test: No time/device constraints declared**
  - Input: profile without max_cooking_time_min or available_equipment
  - Expected: Result with empty filters or skip entirely
  - Coverage: Optional constraint handling

### Component: Search Tools

#### query (`tools/search/query.py`)
- [ ] **Test: Hybrid search with diet filter**
  - Setup: Mock Weaviate with 100 recipes (50 vegetarian, 50 not)
  - Input: query_text="pasta", filters={"diet_type": "vegetarian"}
  - Expected: Results contain only vegetarian recipes
  - Coverage: Hard filter enforcement

- [ ] **Test: Allergen exclusion filter**
  - Setup: Mock recipes with allergens=[nuts], [dairy], []
  - Input: filters={"allergens_exclude": ["nuts", "dairy"]}
  - Expected: Only recipes with allergens=[] returned
  - Coverage: Allergen filtering

- [ ] **Test: Time constraint filter**
  - Setup: Recipes with time_min=[15, 30, 45, 60]
  - Input: filters={"max_time_min": 30}
  - Expected: Only recipes with time_min <= 30 returned
  - Coverage: Time filtering

- [ ] **Test: Empty search results**
  - Setup: Filters so restrictive no recipes match
  - Expected: Empty results list (not error)
  - Coverage: No-match scenario

#### ScoreAndRank (`tools/search/score_and_rank.py`)
- [ ] **Test: Rank recipes by macro fit**
  - Setup: 3 recipes with kcal=[300, 600, 900]; target_per_meal=600
  - Expected: Recipe with 600 kcal ranked first
  - Coverage: Macro scoring

- [ ] **Test: Diversity bonus (not yet implemented in basic version)**
  - Placeholder for future enhancement
  - Coverage: Diversity scoring

- [ ] **Test: Top-k selection**
  - Setup: 100 recipes
  - Input: top_k=20
  - Expected: Exactly 20 recipes in output
  - Coverage: Limit enforcement

### Component: Plan Day Tools

#### PlanAssembleDay (`tools/plan_day/plan_assemble.py`)
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

#### PlanValidate (`tools/plan_day/plan_validate.py`)
- [ ] **Test: Validate plan within ±10% kcal target**
  - Input: target=2000 kcal, plan=1900 kcal
  - Expected: Validation passes
  - Coverage: Macro tolerance

- [ ] **Test: Detect allergen violation**
  - Input: plan contains recipe with nuts, user has nut allergy
  - Expected: Validation fails with allergen warning
  - Coverage: Constraint violation detection

- [ ] **Test: Detect diet type violation**
  - Input: user is vegetarian, plan contains chicken recipe
  - Expected: Validation fails
  - Coverage: Diet constraint

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

#### GapCalc (`tools/gap_fill/gap_calc.py`)
- [ ] **Test: Calculate protein deficit**
  - Input: target=150g protein, plan=120g protein
  - Expected: deficit=30g protein
  - Coverage: Single nutrient deficit

- [ ] **Test: Calculate multiple deficits**
  - Input: target={kcal:2000, protein:150, carb:200}, plan={kcal:1800, protein:140, carb:220}
  - Expected: deficits={kcal:200, protein:10, carb:-20}
  - Coverage: Mixed deficits and surplus

- [ ] **Test: No deficits (plan meets all targets)**
  - Input: plan equals or exceeds all targets
  - Expected: All deficits ≤ 0
  - Coverage: Target met scenario

#### SuggestSnack (`tools/gap_fill/suggest_snack.py`)
- [ ] **Test: Suggest high-protein snack for protein deficit**
  - Input: deficit={protein:30g}, candidates=[protein_bar:25g, apple:1g]
  - Expected: protein_bar suggested
  - Coverage: Deficit-driven selection

- [ ] **Test: No suitable snack available**
  - Input: deficit={protein:30g}, candidates all have <5g protein
  - Expected: Text warning or best available option
  - Coverage: Insufficient options

### Component: Micronutrient Tools

#### MicronutrientCheck (`tools/micros/micronutrient_check.py`)
- [ ] **Test: Aggregate vitamin C from 3 meals**
  - Setup: breakfast=20mg, lunch=30mg, dinner=40mg
  - Expected: total_vitamin_c=90mg
  - Coverage: Micronutrient summation

- [ ] **Test: FdcPortion conversion (1 cup → grams → nutrients)**
  - Setup: Recipe uses "1 cup broccoli", FdcPortion maps to 91g, FdcNutrient has per-100g values
  - Expected: Correct proportional calculation
  - Coverage: Portion conversion accuracy

- [ ] **Test: Missing FdcPortion data**
  - Setup: Ingredient without FdcPortion entry
  - Expected: Warning logged; skip or use approximation
  - Coverage: Missing data handling

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

#### Integration Test 1: Complete Daily Plan Generation
```python
async def test_daily_plan_workflow():
    """
    End-to-end workflow: Create profile → Calculate macros → Search → Rank → Assemble → Validate
    """
    # Setup
    environment = {}
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
    async for output in diet_allergen_guard_tool(
        tree_data=tree_data,
        client_manager=client_manager
    ):
        if isinstance(output, Result):
            assert output.name == "filters"
            # Check environment: environment["diet_allergen_guard_tool"]["filters"]
    
    # Step 4: Search recipes
    async for output in query_tool(
        tree_data=tree_data,
        client_manager=client_manager,
        query_text="healthy meals"
    ):
        if isinstance(output, Result):
            # Check environment: environment["query_tool"]["results"]
            results = tree_data.environment.find("query_tool", "results")
            assert results and len(results[0].objects) > 0
    
    # Step 5: Rank recipes
    async for output in score_and_rank_tool(
        tree_data=tree_data,
        client_manager=client_manager,
        top_k=20
    ):
        if isinstance(output, Result):
            # Check environment: environment["score_and_rank_tool"]["topk"]
            topk_results = tree_data.environment.find("score_and_rank_tool", "topk")
            assert topk_results and len(topk_results[0].objects) == 20
    
    # Step 6: Assemble plan
    async for output in plan_assemble_day_tool(
        tree_data=tree_data,
        client_manager=client_manager
    ):
        if isinstance(output, Result):
            # Check environment: environment["plan_assemble_day_tool"]["plan"]
            plan_results = tree_data.environment.find("plan_assemble_day_tool", "plan")
            plan = plan_results[0].objects[0] if plan_results else {}
            assert "breakfast" in plan.get("meals", {})
            assert "lunch" in plan.get("meals", {})
            assert "dinner" in plan.get("meals", {})
    
    # Step 7: Validate plan
    async for output in plan_validate_tool(
        tree_data=tree_data,
        client_manager=client_manager
    ):
        if isinstance(output, Result):
            # Check environment: environment["plan_validate_tool"]["report"]
            report_results = tree_data.environment.find("plan_validate_tool", "report")
            report = report_results[0].objects[0] if report_results else {}
            assert report.get("valid") == True
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

### Error Handling Integration

- [ ] **Test: Weaviate connection failure during search**
  - Setup: Disconnect Weaviate mid-workflow
  - Expected: Error yielded, workflow stops gracefully (no crash)
  - Coverage: External service failure

- [ ] **Test: Insufficient recipes after filtering**
  - Setup: Constraints so strict only 1 recipe matches
  - Expected: Error in PlanAssemble (need 3 for daily plan)
  - Coverage: Data insufficiency

## End-to-End Tests

### User Journey 1: First-Time User Onboarding
- [ ] **Scenario**: New user creates profile and generates first daily plan
  - Step 1: User navigates to ProfilePage, enters data (age, weight, diet, allergens)
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
    "time_min": 25
}

VEGAN_SMOOTHIE = {
    "recipe_id": "test_002",
    "title": "Green Smoothie",
    "diet_type": "vegan",
    "allergens": [],
    "macros_per_serving": {"kcal": 200, "protein_g": 5, "fat_g": 3, "carb_g": 40},
    "ingredients": [{"name": "spinach", "amount": 100, "unit": "g"}],
    "directions": ["Blend ingredients"],
    "time_min": 5
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
- **LLM-based Features**: Explain tool (hard to unit test; rely on integration tests)

### Links to Test Reports
- CI/CD Pipeline: [GitHub Actions workflow badge]
- Coverage Dashboard: [Codecov.io link - TBD]

### Manual Testing Outcomes
- **Accessibility Audit**: WCAG 2.1 AA compliance checked with axe DevTools (Week 11)
- **Browser Compatibility**: Tested on Chrome, Firefox, Safari, Edge (Week 11)
- **Mobile Responsiveness**: Tested on iOS Safari, Android Chrome (Week 11)

## Manual Testing

### UI/UX Testing Checklist
- [ ] **ProfilePage**: Form validation works (invalid age shows error)
- [ ] **RecipeExplorer**: Filters (diet, allergen, time) update results
- [ ] **PlannerPage**: Streaming progress visible (not frozen)
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

**Status**: Draft - Update with test results as implementation progresses
**Last Updated**: 2025-10-28
**Owner**: [Your Name/Team]

