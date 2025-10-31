---
phase: planning
title: Project Planning & Task Breakdown - Meal Planning Agent
description: Break down work into actionable tasks and estimate timeline for MealAgent implementation
---

# Project Planning & Task Breakdown - Meal Planning Agent

## Milestones

- [ ] **Milestone 1: Foundation & Data Setup** (Week 1-3)
  - Weaviate schema design and deployment
  - FDC data import and preprocessing
  - Load demo recipe corpus (4k, local path)
  - Environment and Manager setup

- [ ] **Milestone 2: Core Planning Features** (Week 4-6)
  - Profile and target calculation
  - Constraint enforcement (diet/allergen)
  - Hybrid retrieval and ranking
  - Daily plan generation

- [ ] **Milestone 2.5: Meal Logging Feature** (Week 5-6)
  - Meal parsing (LLM-assisted) with validation and fallback
  - Nutrition calculation from FDC + FdcPortion
  - Profile updates (consumed_today, remaining targets)
  - REST + WebSocket endpoints and UI hooks

- [ ] **Milestone 3: Extended Features** (Week 7-9)
  - Weekly planning with variety
  - Pantry and shopping list
  - Gap filling and substitution
  - Micronutrient tracking

- [ ] **Milestone 4: UI & Polish** (Week 10-12)
  - Frontend integration (all pages)
  - Cooking mode with streaming
  - Explanation generation
  - Testing, bug fixes, and documentation

## Task Breakdown

### Phase 1: Foundation & Data Setup (Week 1-3)

#### 1.1 Weaviate Schema & Collections
- [ ] **Task 1.1.1**: Define Weaviate schemas for all 11 collections (Recipe, FdcFood, FdcNutrient, FdcPortion, UserProfile, NutrientTarget, MealPlan, MealPlanItem, MealLogEntry, Pantry/PantryItem, ShoppingList/ShoppingItem)
  - **Estimated Effort**: 2 days
  - **Owner**: Data Engineer
  - **Deliverables**: `elysia/MealAgent/schemas/` Python files defining schemas

- [ ] **Task 1.1.2**: Set up Weaviate instance (Docker Compose for dev, cloud for prod)
  - **Estimated Effort**: 1 day
  - **Owner**: Backend Engineer
  - **Deliverables**: `Docker/docker-compose.yml` with Weaviate service

- [ ] **Task 1.1.3**: Create collections in Weaviate with vectorizer configuration
  - **Estimated Effort**: 1 day
  - **Owner**: Data Engineer
  - **Deliverables**: Migration script `elysia/MealAgent/migrations/create_collections.py`

#### 1.2 FDC Data Import
- [ ] **Task 1.2.1**: Download FoodData Central CSV files (food, nutrient, portion tables)
  - **Estimated Effort**: 0.5 days
  - **Owner**: Data Engineer
  - **Deliverables**: Raw CSV files in `data/fdc/raw/`

- [ ] **Task 1.2.2**: Write ETL pipeline to parse and clean FDC data
  - **Estimated Effort**: 3 days
  - **Owner**: Data Engineer
  - **Deliverables**: `elysia/MealAgent/etl/fdc_import.py`

- [ ] **Task 1.2.3**: Generate embeddings for FdcFood descriptions
  - **Estimated Effort**: 2 days (includes batching and error handling)
  - **Owner**: Data Engineer
  - **Deliverables**: Embeddings stored in Weaviate FdcFood collection

- [ ] **Task 1.2.4**: Load FdcFood, FdcNutrient, FdcPortion into Weaviate
  - **Estimated Effort**: 1 day
  - **Owner**: Data Engineer
  - **Deliverables**: Populated collections; validation script confirms record counts

#### 1.3 Recipe Corpus Integration
- [ ] **Task 1.3.1**: Load demo recipe dataset (4k) from `D:\Elysia_cursor\elysia\elysia\MealAgent\data`
  - **Estimated Effort**: 1 day
  - **Owner**: Data Engineer
  - **Deliverables**: Imported recipes in Weaviate `Recipe` collection

- [ ] **Task 1.3.2**: Validate/normalize schema (ensure ingredients map to FDC ids where available)
  - **Estimated Effort**: 2 days
  - **Owner**: Data Engineer
  - **Deliverables**: `elysia/MealAgent/etl/recipe_import.py`

- [ ] **Task 1.3.3**: Ensure `macros_per_serving` is populated or backfilled where missing
  - **Estimated Effort**: 1 day
  - **Owner**: Data Engineer
  - **Deliverables**: Recipes with `macros_per_serving` populated

- [ ] **Task 1.3.4**: Generate embeddings for recipe descriptions and load into Weaviate
  - **Estimated Effort**: 1 day
  - **Owner**: Data Engineer
  - **Deliverables**: Populated Recipe collection with vectors

#### 1.4 Elysia Framework Setup
- [ ] **Task 1.4.1**: Configure Elysia Settings and environment variables
  - **Estimated Effort**: 1 day
  - **Owner**: Backend Engineer
  - **Deliverables**: `elysia/config.py` and `.env.example`

- [ ] **Task 1.4.2**: Implement UserManager, TreeManager, ClientManager for MealAgent
  - **Estimated Effort**: 2 days
  - **Owner**: Backend Engineer
  - **Deliverables**: `elysia/MealAgent/managers.py`

- [ ] **Task 1.4.3**: Create Preprocessor for metadata generation
  - **Estimated Effort**: 2 days
  - **Owner**: Backend Engineer
  - **Deliverables**: `elysia/MealAgent/preprocessing/preprocessor.py`

- [ ] **Task 1.4.4**: Set up Environment key namespacing conventions (documentation)
  - **Estimated Effort**: 0.5 days
  - **Owner**: Backend Engineer
  - **Deliverables**: `docs/ai/design/environment_keys.md`

### Phase 2: Core Planning Features (Week 4-6)

#### 2.1 Profile Branch Tools
- [ ] **Task 2.1.1**: Implement ProfileCRUDTool (create/update/read UserProfile)
  - **Estimated Effort**: 2 days
  - **Owner**: Backend Engineer
  - **Deliverables**: `elysia/MealAgent/tools/profile/profile_crud.py`
  - **Environment Keys**: Writes `profile.profile_crud.profile`

- [ ] **Task 2.1.2**: Implement MacroCalcTool (Harris-Benedict TDEE calculation)
  - **Estimated Effort**: 1 day
  - **Owner**: Backend Engineer
  - **Deliverables**: `elysia/MealAgent/tools/profile/macro_calc.py`
  - **Environment Keys**: Reads `profile.profile_crud.profile`, Writes `profile.macro_calc.targets`

#### 2.2 Constraint Branch Tools
- [ ] **Task 2.2.1**: Implement DietAllergenGuard (generate hard filters for Weaviate)
  - **Estimated Effort**: 2 days
  - **Owner**: Backend Engineer
  - **Deliverables**: `elysia/MealAgent/tools/constraints/diet_allergen_guard.py`
  - **Environment Keys**: Writes `constraints.filters.diet_allergen`

- [ ] **Task 2.2.2**: Implement TimeDeviceGuard (optional time/equipment constraints)
  - **Estimated Effort**: 1 day
  - **Owner**: Backend Engineer
  - **Deliverables**: `elysia/MealAgent/tools/constraints/time_device_guard.py`
  - **Environment Keys**: Writes `constraints.filters.time_device`

#### 2.3 Search Branch Tools
- [ ] **Task 2.3.1**: Implement query tool (hybrid search with filters)
  - **Estimated Effort**: 3 days (includes Weaviate client integration)
  - **Owner**: Backend Engineer
  - **Deliverables**: `elysia/MealAgent/tools/search/query.py`
  - **Environment Keys**: Reads `constraints.filters.*`, Writes `search.query.results`

- [ ] **Task 2.3.2**: Implement query_postprocessing (deduplication, normalization)
  - **Estimated Effort**: 1 day
  - **Owner**: Backend Engineer
  - **Deliverables**: `elysia/MealAgent/tools/search/query_postprocessing.py`
  - **Environment Keys**: Reads `search.query.results`, Writes `search.post.deduped`

- [ ] **Task 2.3.3**: Implement ScoreAndRank (multi-criteria scoring)
  - **Estimated Effort**: 3 days (includes scoring algorithm design)
  - **Owner**: Backend Engineer
  - **Deliverables**: `elysia/MealAgent/tools/search/score_and_rank.py`
  - **Environment Keys**: Reads `search.post.deduped`, `profile.macro_calc.targets`, Writes `search.rank.topk`

#### 2.4 Plan Day Branch Tools
- [ ] **Task 2.4.1**: Implement TargetResolver (resolve query vs profile targets)
  - **Estimated Effort**: 1 day
  - **Owner**: Backend Engineer
  - **Deliverables**: `elysia/MealAgent/tools/plan_day/target_resolver.py`
  - **Environment Keys**: Writes `plan_day.target.resolved`

- [ ] **Task 2.4.2**: Implement PlanAssembleDay (3-meal assembly)
  - **Estimated Effort**: 3 days (includes portion scaling logic)
  - **Owner**: Backend Engineer
  - **Deliverables**: `elysia/MealAgent/tools/plan_day/plan_assemble.py`
  - **Environment Keys**: Reads `search.rank.topk`, Writes `plan_day.assemble.plan`

- [ ] **Task 2.4.3**: Implement PlanValidate (constraint and macro validation)
  - **Estimated Effort**: 2 days
  - **Owner**: Backend Engineer
  - **Deliverables**: `elysia/MealAgent/tools/plan_day/plan_validate.py`
  - **Environment Keys**: Reads `plan_day.assemble.plan`, Writes `plan_day.validate.report`

- [ ] **Task 2.4.4**: Implement BuildShoppingList (extract ingredients from plan)
  - **Estimated Effort**: 2 days
  - **Owner**: Backend Engineer
  - **Deliverables**: `elysia/MealAgent/tools/plan_day/build_shopping.py`
  - **Environment Keys**: Reads `plan_day.assemble.plan`, Writes `shopping.list.items`

#### 2.5 Decision Tree Logic
- [ ] **Task 2.5.1**: Implement main decision tree for daily planning workflow
  - **Estimated Effort**: 3 days
  - **Owner**: Backend Engineer
  - **Deliverables**: `elysia/MealAgent/tree/meal_tree.py`

- [ ] **Task 2.5.2**: Create tree configuration and tool registration
  - **Estimated Effort**: 1 day
  - **Owner**: Backend Engineer
  - **Deliverables**: `elysia/MealAgent/tree/config.py`

#### 2.6 Meal Logging Branch Tools (Week 5-6)
- [ ] **Task 2.6.1**: Implement MealParser (LLM-assisted parsing with validation and fallback)
  - **Estimated Effort**: 2 days
  - **Owner**: Backend Engineer
  - **Deliverables**: `elysia/MealAgent/tools/meal_logging/meal_parser.py`
  - **Environment Keys**: Writes `meal_logging.parser.parsed_meal`

- [ ] **Task 2.6.2**: Implement NutritionCalc (calculate nutrition from FdcNutrient + FdcPortion)
  - **Estimated Effort**: 2 days
  - **Owner**: Backend Engineer
  - **Deliverables**: `elysia/MealAgent/tools/meal_logging/nutrition_calc.py`
  - **Environment Keys**: Writes `meal_logging.nutrition.calculated`

- [ ] **Task 2.6.3**: Implement ProfileUpdate (update consumed_today and remaining targets)
  - **Estimated Effort**: 1 day
  - **Owner**: Backend Engineer
  - **Deliverables**: `elysia/MealAgent/tools/meal_logging/profile_update.py`

- [ ] **Task 2.6.4**: Implement MealHistoryRetrieval (list/detail endpoints)
  - **Estimated Effort**: 1 day
  - **Owner**: Backend Engineer
  - **Deliverables**: `elysia/MealAgent/tools/meal_logging/meal_history.py`

- [ ] **Task 2.6.5**: Expose REST endpoints (log, history, consumed-today)
  - **Estimated Effort**: 1 day
  - **Owner**: Backend Engineer
  - **Deliverables**: API routes under `elysia/elysia/api/routes/`

- [ ] **Task 2.6.6**: Expose WebSocket endpoint `/ws/meals/log/{user_id}`
  - **Estimated Effort**: 1 day
  - **Owner**: Backend Engineer
  - **Deliverables**: WS route and streaming integration

### Phase 3: Extended Features (Week 7-9)

#### 3.1 Plan Week Branch Tools
- [ ] **Task 3.1.1**: Implement PlanAssembleWeekly (21-meal assembly)
  - **Estimated Effort**: 3 days
  - **Owner**: Backend Engineer
  - **Deliverables**: `elysia/MealAgent/tools/plan_week/plan_assemble_weekly.py`
  - **Environment Keys**: Writes `plan_week.assemble.plan`

- [ ] **Task 3.1.2**: Implement VarietyGuard (repetition detection and scoring)
  - **Estimated Effort**: 2 days
  - **Owner**: Backend Engineer
  - **Deliverables**: `elysia/MealAgent/tools/plan_week/variety_guard.py`
  - **Environment Keys**: Reads `plan_week.assemble.plan`, Writes `plan_week.variety.report`

#### 3.2 Pantry & Shopping Tools
- [ ] **Task 3.2.1**: Implement PantryCRUDTool (CRUD operations on PantryItem)
  - **Estimated Effort**: 2 days
  - **Owner**: Backend Engineer
  - **Deliverables**: `elysia/MealAgent/tools/pantry/pantry_crud.py`
  - **Environment Keys**: Writes `pantry.crud.state`

- [ ] **Task 3.2.2**: Implement PantryDiff (subtract pantry from shopping list)
  - **Estimated Effort**: 3 days (includes unit conversion logic)
  - **Owner**: Backend Engineer
  - **Deliverables**: `elysia/MealAgent/tools/shopping/pantry_diff.py`
  - **Environment Keys**: Reads `shopping.list.items`, `pantry.crud.state`, Writes `shopping.list.diff`

#### 3.3 Gap Fill Branch Tools
- [ ] **Task 3.3.1**: Implement GapCalc (calculate macro deficits)
  - **Estimated Effort**: 1 day
  - **Owner**: Backend Engineer
  - **Deliverables**: `elysia/MealAgent/tools/gap_fill/gap_calc.py`
  - **Environment Keys**: Reads `plan_*.assemble.plan`, Writes `gap_fill.calc.deficits`

- [ ] **Task 3.3.2**: Implement SuggestSnack (recommend deficit-filling snacks)
  - **Estimated Effort**: 2 days
  - **Owner**: Backend Engineer
  - **Deliverables**: `elysia/MealAgent/tools/gap_fill/suggest_snack.py`

- [ ] **Task 3.3.3**: Implement ApplySnack (add snack to plan and recalculate)
  - **Estimated Effort**: 1 day
  - **Owner**: Backend Engineer
  - **Deliverables**: `elysia/MealAgent/tools/gap_fill/apply_snack.py`

#### 3.4 Substitution Branch Tools
- [ ] **Task 3.4.1**: Implement SuggestSubstitutes (find ingredient alternatives)
  - **Estimated Effort**: 3 days (includes ±20% macro matching logic)
  - **Owner**: Backend Engineer
  - **Deliverables**: `elysia/MealAgent/tools/substitution/suggest_substitutes.py`

- [ ] **Task 3.4.2**: Implement ApplySubstitute (swap ingredient in plan)
  - **Estimated Effort**: 1 day
  - **Owner**: Backend Engineer
  - **Deliverables**: `elysia/MealAgent/tools/substitution/apply_substitute.py`

#### 3.5 Micronutrient Tools
- [ ] **Task 3.5.1**: Implement MicronutrientCheck (aggregate micros from FdcNutrient + FdcPortion)
  - **Estimated Effort**: 4 days (includes portion conversion logic)
  - **Owner**: Backend Engineer
  - **Deliverables**: `elysia/MealAgent/tools/micros/micronutrient_check.py`

- [ ] **Task 3.5.2**: Implement SuggestMicrosFoods (recommend foods rich in deficient nutrients)
  - **Estimated Effort**: 2 days
  - **Owner**: Backend Engineer
  - **Deliverables**: `elysia/MealAgent/tools/micros/suggest_micros_foods.py`

### Phase 4: UI & Polish (Week 10-12)

#### 4.1 Frontend - Core Pages
- [ ] **Task 4.1.1**: Build ProfilePage (create/edit user profile with TDEE preview)
  - **Estimated Effort**: 3 days
  - **Owner**: Frontend Engineer
  - **Deliverables**: `elysia-frontend/app/pages/ProfilePage.tsx`

- [ ] **Task 4.1.2**: Build RecipeExplorer (search with filters, card grid)
  - **Estimated Effort**: 4 days
  - **Owner**: Frontend Engineer
  - **Deliverables**: `elysia-frontend/app/pages/RecipeExplorer.tsx`

- [ ] **Task 4.1.3**: Build PlannerPage (daily/weekly plan generation with streaming)
  - **Estimated Effort**: 5 days (includes WebSocket integration)
  - **Owner**: Frontend Engineer
  - **Deliverables**: `elysia-frontend/app/pages/PlannerPage.tsx`

- [ ] **Task 4.1.4**: Build PlanView (display plan with macro breakdown)
  - **Estimated Effort**: 3 days
  - **Owner**: Frontend Engineer
  - **Deliverables**: `elysia-frontend/app/components/plan/PlanView.tsx`

#### 4.2 Frontend - Extended Features
- [ ] **Task 4.2.1**: Build CookingMode (step-by-step instructions with timer)
  - **Estimated Effort**: 4 days (includes WebSocket streaming)
  - **Owner**: Frontend Engineer
  - **Deliverables**: `elysia-frontend/app/pages/CookingMode.tsx`

- [ ] **Task 4.2.2**: Build PantryManager (CRUD UI for pantry items)
  - **Estimated Effort**: 3 days
  - **Owner**: Frontend Engineer
  - **Deliverables**: `elysia-frontend/app/pages/PantryManager.tsx`

- [ ] **Task 4.2.3**: Build ShoppingListView (checklist with print/export)
  - **Estimated Effort**: 2 days
  - **Owner**: Frontend Engineer
  - **Deliverables**: `elysia-frontend/app/components/shopping/ShoppingListView.tsx`

- [ ] **Task 4.2.4**: Build ExplainDialog (modal with decision explanation)
  - **Estimated Effort**: 2 days
  - **Owner**: Frontend Engineer
  - **Deliverables**: `elysia-frontend/app/components/dialog/ExplainDialog.tsx`

#### 4.3 Cooking & Explanation Tools
- [ ] **Task 4.3.1**: Implement CookMode (parse recipe into steps, stream via WebSocket)
  - **Estimated Effort**: 3 days
  - **Owner**: Backend Engineer
  - **Deliverables**: `elysia/MealAgent/tools/cook_mode/cook_mode.py`

- [ ] **Task 4.3.2**: Implement Explain (generate natural language explanation from Environment)
  - **Estimated Effort**: 3 days (may use LLM or template-based generation)
  - **Owner**: Backend Engineer
  - **Deliverables**: `elysia/MealAgent/tools/explain/explain.py`

#### 4.4 Testing & Quality Assurance
- [ ] **Task 4.4.1**: Write unit tests for all tools (100% coverage target)
  - **Estimated Effort**: 8 days (distributed across team)
  - **Owner**: All Engineers
  - **Deliverables**: `tests/meal_agent/`

- [ ] **Task 4.4.2**: Write integration tests for key workflows
  - **Estimated Effort**: 4 days
  - **Owner**: Backend Engineer
  - **Deliverables**: `tests/integration/meal_agent/`

- [ ] **Task 4.4.3**: Manual testing and bug fixes
  - **Estimated Effort**: 5 days
  - **Owner**: All Engineers
  - **Deliverables**: Bug tracker cleared

- [ ] **Task 4.4.4**: Performance testing and optimization
  - **Estimated Effort**: 3 days
  - **Owner**: Backend Engineer
  - **Deliverables**: Performance benchmarks documented in `docs/ai/testing/feature-meal-planning-agent.md`

#### 4.5 Documentation & Deployment
- [ ] **Task 4.5.1**: Update all ai-devkit phase docs with final implementation notes
  - **Estimated Effort**: 2 days
  - **Owner**: Backend Engineer
  - **Deliverables**: Updated `docs/ai/*/*.md`

- [ ] **Task 4.5.2**: Create user-facing documentation and help guides
  - **Estimated Effort**: 2 days
  - **Owner**: Frontend Engineer
  - **Deliverables**: `docs/user_guide/meal_agent.md`

- [ ] **Task 4.5.3**: Set up production deployment (Docker, K8s, monitoring)
  - **Estimated Effort**: 3 days
  - **Owner**: Backend Engineer
  - **Deliverables**: `Docker/docker-compose.prod.yml`, K8s manifests

## Dependencies

### Task Dependencies and Blockers
- **1.3.1 (Load demo corpus)** blocks **1.3.2, 1.3.3, 1.3.4** (can't normalize/load without data)
- **1.1.3 (Create collections)** blocks **1.2.4, 1.3.4** (can't load data without schema)
- **2.1.* (Profile tools)** blocks **2.4.* (Plan tools)** (need targets before planning)
- **2.3.* (Search tools)** blocks **2.4.2 (PlanAssemble)** (need ranked recipes before assembly)
- **2.4.* (Daily planning)** blocks **3.1.* (Weekly planning)** (weekly extends daily logic)
- **All backend tools** block **4.1.*, 4.2.* (Frontend)** (UI needs working API)
- **2.6.* (Meal logging)** requires **1.2.4 (FDC loaded)** and **FdcPortion** available

### External Dependencies
- **USDA FoodData Central**: CSV files publicly available; no API dependency
- **OpenAI API** (optional): For embeddings and LLM-based features; can use local models as fallback
- **Weaviate Cloud/Self-hosted**: Production deployment requires cloud instance or K8s cluster

### Team/Resource Dependencies
- **Data Engineer**: Required for Phases 1.2, 1.3 (80% utilization Weeks 1-3)
- **Backend Engineer**: Required for all tool development (100% utilization Weeks 1-12)
- **Frontend Engineer**: Required starting Week 4 (100% utilization Weeks 4-12)

## Timeline & Estimates

### Overall Timeline: 12 weeks (3 months)

| Phase | Duration | Key Deliverables |
|-------|----------|------------------|
| **Phase 1: Foundation** | Week 1-3 | Weaviate setup, FDC data loaded, Recipe corpus imported, Elysia framework configured |
| **Phase 2: Core Planning** | Week 4-6 | Profile/target calculation, constraint enforcement, daily plan generation working |
| **Phase 3: Extended Features** | Week 7-9 | Weekly planning, pantry/shopping, gap fill, substitution, micronutrients |
| **Phase 4: UI & Polish** | Week 10-12 | All frontend pages, cooking mode, explanations, testing complete, deployed |

### Buffer for Unknowns
- **2 weeks** additional buffer built into estimates for:
  - Recipe corpus acquisition delays (legal review, data quality issues)
  - Portion conversion complexity (FdcPortion edge cases)
  - Performance optimization (if initial implementation doesn't meet benchmarks)
  - Unexpected integration issues (Weaviate, WebSocket streaming)

## Risks & Mitigation

### Technical Risks

| Risk | Likelihood | Impact | Mitigation Strategy |
|------|------------|--------|---------------------|
| **Recipe corpus quality/availability** | High | High | Start scraping early (Week 1); have backup sources; accept smaller corpus (5k) for MVP if needed |
| **FdcPortion coverage gaps** | Medium | Medium | Build fallback unit conversion table for common ingredients; allow manual portion entry |
| **Hybrid search performance** | Medium | High | Benchmark early (Week 4); optimize filters; consider pre-filtering before vector search |
| **Portion scaling complexity** | Medium | Medium | Start with linear scaling; defer non-linear adjustments (e.g., baking) to v2 |
| **LLM cost/latency** | Low | Medium | Use LLM only for optional features (explanations); make code-based alternatives default |

### Resource Risks

| Risk | Likelihood | Impact | Mitigation Strategy |
|------|------------|--------|---------------------|
| **Data engineer availability** | Medium | High | Front-load data work (Weeks 1-3); document ETL pipelines for handoff |
| **OpenAI API quota** | Low | Low | Use local embedding models (sentence-transformers) as fallback |

### Dependency Risks

| Risk | Likelihood | Impact | Mitigation Strategy |
|------|------------|--------|---------------------|
| **Weaviate breaking changes** | Low | Medium | Pin Weaviate version (1.25.x); test upgrades in staging before prod |
| **FDC data structure changes** | Low | Low | Archive current FDC CSV files; monitor USDA announcements |

## Resources Needed

### Team Members and Roles
- **Backend Engineer (1 FTE)**: Python/Elysia tool development, API, decision tree logic
- **Frontend Engineer (1 FTE)**: Next.js UI, WebSocket integration, UX design
- **Data Engineer (0.5 FTE)**: FDC ETL, recipe corpus preparation, embeddings generation
- **QA/Tester (0.25 FTE)**: Manual testing, test case design (Weeks 10-12)

### Tools and Services
- **Weaviate Cloud**: Starter tier ($25/month) for dev; Growth tier ($100/month) for prod
- **OpenAI API**: $50/month budget for embeddings (can reduce with local models)
- **GitHub**: Version control and CI/CD
- **Vercel** (optional): Frontend hosting (free tier for MVP)

### Infrastructure
- **Development**: Docker Compose on local machines
- **Demo/Presentation**: Docker Compose single-node Weaviate (graduation project scope)
- **Production (later)**: K8s cluster or managed service (out of scope for MVP/demo)

### Documentation/Knowledge
- **Elysia Documentation**: [weaviate.github.io/elysia](https://weaviate.github.io/elysia)
- **Weaviate Docs**: Hybrid search, filters, schema design
- **FDC Documentation**: Field descriptions, data model
- **Harris-Benedict Equation**: Nutrition science reference

---

**Status**: Updated Draft - Aligned with requirements/design (incl. Meal Logging)
**Last Updated**: 2025-10-31
**Owner**: [Your Name/Team]

