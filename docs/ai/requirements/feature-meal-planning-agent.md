---
phase: requirements
title: Requirements & Problem Understanding - Meal Planning Agent
description: Clarify the problem space, gather requirements, and define success criteria for the MealAgent system
---

# Requirements & Problem Understanding - Meal Planning Agent

## Problem Statement
**What problem are we solving?**

- **Core Problem**: Users need personalized, nutrition-optimized meal plans that respect individual dietary constraints, preferences, and health goals while being practical to execute (shopping, cooking, pantry management)
- **Who is affected**: 
  - Individuals with specific nutritional goals (weight management, fitness, health conditions)
  - People with dietary restrictions (allergies, vegetarian/vegan, religious dietary laws)
  - Busy individuals seeking efficient meal prep and shopping
  - Anyone wanting transparency in nutritional recommendations
- **Current situation/workaround**: 
  - Manual meal planning is time-consuming and error-prone
  - Generic meal plans don't account for individual constraints
  - Nutritional calculations require specialized knowledge
  - No integration between planning, shopping, and cooking phases
  - Lack of transparency in why certain meals are recommended
  - Do not know how to calculate the nutrition, kcal in a dish

## Goals & Objectives
**What do we want to achieve?**

### Primary Goals
1. **Personalized Nutrition**: Generate day/week meal plans tailored to individual profiles, nutritional targets (TDEE-based), and constraints
2. **Comprehensive Nutrient Tracking**: Calculate both macronutrients (kcal, protein, fat, carbs) and micronutrients (vitamins, minerals) at portion and aggregate levels (meal/day/week)
3. **Constraint Enforcement**: Apply dietary restrictions (diet types, allergens) and time/equipment constraints (optional)
4. **Practical Execution**: Provide step-by-step cooking instructions with optional real-time streaming, shopping list generation with pantry awareness
5. **Transparency**: Explain meal selection decisions based on data and execution trace

### Secondary Goals
1. **Variety Optimization**: Minimize cuisine repetition within weekly plans
2. **Gap Filling**: Automatically suggest snacks to fill macro/micro deficits
3. **Substitution Support**: Enable ingredient substitution while maintaining nutritional equivalence (±20% macro tolerance)
4. **Family Planning**: Support multi-person meal planning with merged constraints

### Non-Goals ( unnecessary function, no need to implement )
- Recipe creation or modification (uses pre-existing recipe database)
- Direct integration with grocery delivery services (v1)
- Mobile app (v1 - web-based UI only)
- Social features (recipe sharing, community) (v1)
- Automated grocery ordering (v1)

## User Stories & Use Cases

### Core User Stories

1. **As a user**, I want to create a nutritional profile (age, gender, weight, height, activity level, allergens, diet preferences) so that meal plans match my TDEE and macro goals
   - Acceptance: Profile creation calculates TDEE using Harris-Benedict equation
   - Acceptance: Macro targets (P/C/F) are stored and reused

2. **As a user with dietary restrictions**, I want meal plans that respect my allergens and diet type (vegetarian, vegan, keto, etc.) so that I stay safe and aligned with my values
   - Acceptance: No recipes containing declared allergens appear in plans
   - Acceptance: All recipes match selected diet type constraints

3. **As a busy person**, I want weekly meal plans (21 meals: 3/day × 7 days) with shopping lists that account for my pantry inventory so that I minimize waste and shopping time
   - Acceptance: Weekly plan generated with variety enforcement
   - Acceptance: Shopping list subtracts existing pantry items
   - Acceptance: Portion scaling accounts for servings

4. **As a cook**, I want step-by-step cooking instructions with time estimates so that I can prepare meals efficiently
   - Acceptance: Recipes are parsed into sequential steps
   - Acceptance: Time estimates per step available
   - Acceptance: Optional streaming mode for real-time step delivery

5. **As a health-conscious user**, I want to understand why specific meals were recommended so that I trust the system's decisions
   - Acceptance: Explanation references profile data, constraints, and nutritional fit
   - Acceptance: Decision trace available through Environment history

### Key Workflows

1. **Initial Setup**: Create profile → Calculate TDEE/macros → Set constraints → Save to UserProfile collection
2. **Daily Planning**: Retrieve user targets → Search recipes (hybrid retrieval) → Rank by fit → Assemble 3-meal plan → Validate constraints → Generate shopping list
3. **Weekly Planning**: Same as daily but 21 meals with variety enforcement across days
4. **Gap Filling**: Calculate deficit (target - consumed) → Suggest snacks → Validate updated plan
5. **Cooking Mode**: Select recipe → Parse into steps → Stream instructions with timing
6. **Pantry Management**: Add/update/remove pantry items → Recalculate shopping list differential

### Edge Cases to Consider

1. **No viable recipes**: What if constraints eliminate all candidates? → Error with suggestion to relax constraints
2. **Partial pantry coverage**: How to handle fractional ingredient availability? → Subtract what's available, list remainder
3. **Micronutrient gaps**: What if no single recipe fills a vitamin deficit? → Suggest top 3 options ranked by deficit reduction
4. **Time/equipment not declared**: Tools should skip time/device validation if user hasn't specified
5. **Multi-allergen users**: Union of all allergens must be respected in retrieval filters
6. **Family with conflicting diets**: Intersection of diet types + union of allergens

## Success Criteria
**How will we know when we're done?**

### Functional Acceptance
- [ ] **Profile & Targets**: TDEE calculation matches Harris-Benedict formula; targets persist and load correctly
- [ ] **Constraint Enforcement**: Zero constraint violations in generated plans (diet/allergen/time/equipment when declared)
- [ ] **Daily Plan**: Total kcal within ±10% of target; macros within ±15% of targets; 3 meals assembled
- [ ] **Weekly Plan**: 21 meals assembled; variety report shows <3 repetitions of primary protein/cuisine per week; macro totals within ±10%
- [ ] **Pantry & Shopping**: Shopping list correctly subtracts pantry items with unit conversion consistency
- [ ] **Gap Fill**: Snack suggestions reduce largest deficit; updated plan passes validation
- [ ] **Substitution**: Replacement ingredients maintain ±20% macro equivalence; no allergen violations
- [ ] **Micronutrients**: Aggregation uses FDCPortion for unit conversion; deficit detection triggers suggestions
- [ ] **Cooking Instructions**: Steps parsed with time estimates; streaming mode yields step-by-step
- [ ] **Explanations**: Generated text references Environment data (profile, constraints, scores)

### Performance Benchmarks
- Hybrid retrieval (search + filter) completes in <2 seconds for 100k recipe corpus
- Daily plan generation (end-to-end) completes in <5 seconds
- Weekly plan generation completes in <15 seconds
- Micronutrient aggregation for 21 meals completes in <3 seconds

### Quality Metrics
- Unit test coverage: 100% of new code
- Integration test coverage: All key workflows (setup → plan → shop → cook)
- Zero security vulnerabilities in dependency scan
- API error rate <0.1% under normal load

## Constraints & Assumptions

### Technical Constraints
- **Elysia Framework**: All tools must be async generators yielding Result/Text objects
- **Weaviate**: Primary data store for Recipe, FdcFood, FdcNutrient, FDCPortion collections
- **Environment Key Convention**: Tools write to `<branch>.<tool>.<key>` namespace only
- **No LLM for Core Logic**: Macronutrient calculations, constraint validation, and retrieval must be deterministic (code-based); LLM optional only for ranking, substitutions, and explanations

### Business Constraints
- **Data Source**: USDA FoodData Central for nutritional data (public domain, no licensing fees)
- **Recipe Corpus**: Pre-existing recipe database (source TBD - scraped, licensed, or user-contributed)
- **User Privacy**: No sharing of user profiles or meal plans without explicit consent

### Time/Budget Constraints
- MVP delivery: 12 weeks (3-week sprints × 4)
- Team: 2 backend engineers, 1 frontend engineer, 1 data engineer (part-time)

### Assumptions
1. Recipe database contains at least 10k recipes with structured ingredients/directions
2. FDC data is pre-loaded into Weaviate with embeddings generated
3. Users will manually input initial pantry inventory (no barcode scanning in v1)
4. Serving size scaling is linear (no complex recipe adjustments)
5. Hybrid retrieval (BM25 + vector) is sufficient; no need for external reranker API in v1
6. Users can export shopping lists as text/PDF (no direct integration with grocery apps in v1)

## Questions & Open Items

### Unresolved Questions
1. **Recipe Source**: Where will the initial 10k+ recipe corpus come from? (Scraping terms-of-service compliance? Licensing? Community contribution?)
2. **Portion Mapping**: How to handle recipes with non-standard portions (e.g., "1 large onion" vs FDC's gram-based portions)? Auto-approximate or require manual mapping?
3. **Multi-language Support**: Should UI and recipe data support multiple languages in v1, or English-only initially?
4. **Offline Mode**: Should the frontend cache plans/recipes for offline access, or require always-on connectivity?

### Items Requiring Stakeholder Input
1. **Monetization Model**: Free tier with ads? Subscription-based? One-time purchase?
2. **Compliance**: Do we need HIPAA compliance for health-related data? (Likely not for v1 general wellness, but check with legal)
3. **Accessibility**: WCAG 2.1 AA compliance required? (Recommend yes for public-facing web app)

### Research Needed
1. **Portion Conversion Accuracy**: Benchmark FDCPortion-based conversions against known nutrition labels (sample 100 foods)
2. **Variety Metrics**: What threshold for repetition feels "monotonous" to users? (User survey or A/B test in beta)
3. **Reranker Performance**: Measure quality difference between code-based scoring vs. LLM-based reranking (precision@10 on test set)
4. **Streaming Latency**: Profile streaming cooking instructions to ensure <500ms delay between steps

---

**Status**: Draft - Awaiting stakeholder review on recipe sourcing and monetization model
**Last Updated**: 2025-10-28
**Owner**: [Your Name/Team]

