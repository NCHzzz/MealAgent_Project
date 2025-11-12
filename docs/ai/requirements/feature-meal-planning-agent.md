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

#### Data Retention
- User profiles: Retained indefinitely (or until user requests deletion)
- Meal plans: 360 days
- Shopping lists: 30 days
- Activity logs: 360 days

### Terminology & Definitions

| Term | Definition |
|------|------------|
| **TDEE** | Total Daily Energy Expenditure; calories burned per day including activity |
| **Harris-Benedict** | Formula for calculating BMR (Basal Metabolic Rate) based on age, gender, weight, height |
| **Macronutrients (Macros)** | Protein, Fat, Carbohydrates (measured in grams) |
| **Micronutrients (Micros)** | Vitamins and minerals (measured in mg/mcg/IU) |
| **FDC** | FoodData Central (USDA nutritional database) |
| **FdcPortion** | USDA portion conversion table (e.g., "1 cup" → grams) |
| **Hybrid Search** | BM25 (keyword) + vector (semantic) search combined |
| **Environment** | Elysia's shared state container where tool results are stored |
| **Pantry-aware** | Shopping list generation that accounts for existing inventory |

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

6. **As a user tracking my nutrition**, I want to log what I've eaten by chatting with the system so that it calculates my consumed nutrition and adjusts future meal recommendations
   - Acceptance: User can input meal via natural language chat (e.g., "I just ate a chicken salad")
   - Acceptance: System parses meal description and calculates kcal/macros/micros
   - Acceptance: Consumed nutrition saved to UserProfile meal history
   - Acceptance: Remaining daily targets updated (target - consumed)
   - Acceptance: Next meal recommendations adjusted based on remaining targets

### Key Workflows

1. **Initial Setup**: Create profile → Calculate TDEE/macros → Set constraints → Save to UserProfile collection
2. **Daily Planning**: Retrieve user targets → Search recipes (hybrid retrieval) → Rank by fit → Assemble 3-meal plan → Validate constraints → Generate shopping list
3. **Weekly Planning**: Same as daily but 21 meals with variety enforcement across days
4. **Meal Logging & Nutrition Tracking**: User inputs meal consumed via chat → Parse meal description (LLM-assisted) → Calculate nutrition/kcal for that meal → Save to UserProfile (meal history) → Update remaining daily targets → Adjust subsequent meal recommendations
5. **Gap Filling**: Calculate deficit (target - consumed from logged meals) → Suggest snacks → Validate updated plan
6. **Cooking Mode**: Select recipe → Parse into steps → Stream instructions with timing
7. **Pantry Management**: Add/update/remove pantry items → Recalculate shopping list differential

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
- [ ] **Meal Logging**: User can input consumed meal via chat; nutrition calculated and saved to UserProfile; remaining targets updated
- [ ] **Adaptive Planning**: After meal logging, subsequent meal recommendations adjust to remaining daily targets
- [ ] **Pantry & Shopping**: Shopping list correctly subtracts pantry items with unit conversion consistency
- [ ] **Gap Fill**: Snack suggestions reduce largest deficit (accounting for logged meals); updated plan passes validation
- [ ] **Substitution**: Replacement ingredients maintain ±20% macro equivalence; no allergen violations
- [ ] **Micronutrients**: Aggregation uses FdcPortion for unit conversion; deficit detection triggers suggestions
- [ ] **Cooking Instructions**: Steps parsed with time estimates; streaming mode yields step-by-step
- [ ] **Explanations**: Generated text references Environment data (profile, constraints, scores)

### Performance Benchmarks
- Hybrid retrieval (search + filter) completes in <2 seconds for 4k demo recipe corpus (<3s for 10k+ production)
- Daily plan generation (end-to-end) completes in <5 seconds
- Weekly plan generation completes in <15 seconds
- Micronutrient aggregation for 21 meals completes in <3 seconds
- Meal logging (parse + calculate + save) completes in <2 seconds

### Nutritional Accuracy
- **Macro Calculations**: ±5% accuracy when compared to manually calculated values from FDC raw data
- **Portion Conversions**: ±10% accuracy when benchmarked against USDA standard portions (FdcPortion table)
- **Micronutrient Aggregation**: ±15% accuracy (acceptable due to natural ingredient variability)
- **LLM Meal Parsing**: ≥85% accuracy on test set of 100 diverse meal descriptions (measured against human labeling)

### User Experience Metrics
- **User Satisfaction**: >85% of users rate generated plans as "helpful" or "very helpful" (post-plan survey)
- **Plan Acceptance Rate**: >70% of generated plans are saved by users (not regenerated immediately due to dissatisfaction)
- **Meal Logging Adoption**: >50% of users log at least one meal within first week of use
- **Retention**: >50% of users return within 7 days of first plan generation


### Quality Metrics
- Unit test coverage: 100% of new code
- Integration test coverage: All key workflows (setup → plan → shop → cook)
- Zero security vulnerabilities in dependency scan
- API error rate <0.1% under normal load

## Constraints & Assumptions

### Technical Constraints
- **Elysia Framework**: All tools must be async generators yielding Result/Text objects
- **Weaviate**: Primary data store for Recipe, FdcFood, FdcNutrient, FdcPortion collections
- **Environment Key Convention**: Tools write to `environment[tool_name][name]` where `tool_name` is the function name (for @tool decorator) and `name` is the Result's name parameter

#### LLM Usage Strategy (Elysia-Integrated Architecture)

**Design Principle**: LLM acts as a **cognitive enhancement layer** within Elysia's decision tree, where each LLM call is wrapped in a **Tool** that yields validated Results to the Environment. This ensures transparency, traceability, and deterministic fallbacks.

**Architecture Pattern**:
- User Input → Tree → LLM Tool (async generator) → Yield Text (streaming progress)
- LLM Tool → Yield Result (to Environment) → Code Validation Tool → Final Validated Result

--



---

**Performance Considerations**:
- **Caching**: Cache LLM responses for common queries (e.g., "healthy dinner") in Redis (TTL: 24h)
- **Batching**: Batch multiple LLM calls when possible (e.g., parse 3 meals at once)
- **Streaming**: Use LLM streaming API to yield Text progressively (improve perceived latency)

- **Rate Limiting**: LLM calls limited to 10/minute per user (prevent abuse and cost overrun)

### Business Constraints
- **Data Source**: 
  - **FDC Nutritional Data**: USDA FoodData Central (public domain, no licensing fees)
  - **Demo Recipe Corpus**: 4,000 sample recipes pre-loaded at `D:\Elysia_Dev\MealAgent\MealAgentDev\data`
- **User Privacy**: No sharing of user profiles or meal plans without explicit consent

### Regulatory Constraints
- **HIPAA Compliance**: **NOT REQUIRED** - System is classified as a "wellness and lifestyle application," not a medical device or covered healthcare entity
- **Legal Disclaimers**: Must include prominent disclaimer:
  - "This application provides nutritional information for educational and wellness purposes only"
  - "Not intended for medical diagnosis, treatment, or disease prevention"
  - "Consult healthcare provider before making significant dietary changes"
- **FDA Disclaimer**: Nutritional information presented "as-is" with standard FDA disclaimer


### Assumptions
1. **Recipe Corpus Availability**: Demo starts with 4k recipes (already stored); production will scale to 10k+
2. **FDC Data Pre-loaded**: FoodData Central nutritional data loaded into Weaviate with embeddings generated
3. **Manual Pantry Entry**: Users manually input initial pantry inventory (no barcode scanning in v1)
4. **Linear Portion Scaling**: Serving size adjustments are linear (no complex recipe chemistry adjustments for baking)
5. **Hybrid Search Sufficiency**: BM25 + vector retrieval adequate; no external reranker API needed in v1
6. **Export Capability**: Users can export shopping lists as text/PDF (no direct grocery app integration)
7. **Chat-based Meal Logging**: Users comfortable entering consumed meals via natural language chat interface
8. **LLM Availability**: OpenAI API or equivalent available for parsing, ranking, and explanation features
9. **Session-based Auth (MVP)**: Simplified session cookie approach; cross-origin access will require CORS + SameSite=None; Secure cookies in production

## Questions & Open Items


### Additional Requirements Clarifications
- **Data provenance & validation**: ETL must map source FDC data into collections as follows:
  - FdcFood: base macro/micro per 100g columns only
  - FdcNutrient: rows derived from source for (fdc_id, nutrient_id, amount_100g)
  - FdcPortion: rows derived from source for (fdc_id, amount, measure_unit, gram_weight)
  - Optional enrichment of nutrient name/unit via lookup table

- **Recipe CSV mapping (demo dataset)**:
  - Input columns: `food_id`, `dish_name`, `dish_type`, `serving_size`, `cooking_time`, `ingredients_with_qty` (text[]), `ingredients` (text[]), `cooking_method_array` (text[]), `image_link`
  - Mapped properties in `Recipe`:
    - `food_id` → `food_id` (text, indexed)
    - `dish_name` → `dish_name` (text) and `title` (duplicate for search)
    - `dish_type` → `dish_type` (text, filterable)
    - `serving_size` → `serving_size` (int)
    - `cooking_time` → `cooking_time` (int, filterable)
    - `ingredients_with_qty` → `ingredients_with_qty` (text[])
    - `ingredients` → `ingredients` (text[])
    - `cooking_method_array` → `cooking_method_array` (text[]); legacy alias `directions` kept
    - `image_link` → `image_link` (text); legacy alias `image_url` kept
- **Meal logging confirmation UX**: After parsing, show calculated nutrition for user confirmation before saving; allow edit/cancel.
- **LLM parsing metric definition**: ≥85% accuracy measured against a labeled test set of 100 meal descriptions (to be curated); report precision/recall for ingredient identification and macro error (MAE per meal).

### Items Requiring Stakeholder Input
1. **HIPAA Compliance**: ✅ **RESOLVED** - Not required (wellness app, not medical device)
2. **LLM Provider**: ✅ **RESOLVED** - Already configured and ready for use
3. **Recipe Expansion Budget**: Allocate funds for scaling from 4k (demo) to 10k+ recipes (licensing or data acquisition)

### Research Needed
1. **Portion Conversion Accuracy**: Benchmark FdcPortion-based conversions against known nutrition labels (sample 100 foods from demo dataset)
2. **Variety Metrics**: What threshold for repetition feels "monotonous" to users? (User survey or A/B test in beta)
3. **LLM Parsing Accuracy**: Test meal logging parser on 100 diverse meal descriptions; measure accuracy vs human labeling
4. **Reranker Performance**: Measure quality difference between code-based scoring vs. LLM-based reranking (precision@10 on test set)
5. **Streaming Latency**: Profile streaming cooking instructions to ensure <500ms delay between steps
6. **Meal Logging User Acceptance**: Do users prefer typing natural language vs structured forms? (UX testing)

---
## Appendix

### A. References & External Resources
- [USDA FoodData Central](https://fdc.nal.usda.gov/) - Nutritional database
- [Harris-Benedict Equation (Wikipedia)](https://en.wikipedia.org/wiki/Harris%E2%80%93Benedict_equation) - TDEE calculation
- [Elysia Documentation](https://weaviate.github.io/elysia) - Framework reference
- [Weaviate Hybrid Search](https://weaviate.io/developers/weaviate/search/hybrid) - Retrieval approach
- [LLM for Nutrition Research](https://pmc.ncbi.nlm.nih.gov/articles/PMC12367769/) - LLM applications in nutrition science
- [Nutrition Data Standards](https://www.mdpi.com/2072-6643/17/9/1492) - Best practices for nutritional databases

### B. Data Sources
- **Demo Dataset Location**: `D:\Elysia_Dev\MealAgent\MealAgentDev\data`
- **Demo Dataset Size**: 4,000 recipes with structured ingredients and nutritional information
- **FDC Data**: USDA FoodData Central (to be imported during setup phase)
- **FdcPortion Mappings**: Portion conversion table from USDA (part of FDC download)

### C. Related Documentation
- Design: `docs/ai/design/feature-meal-planning-agent.md`
- Planning: `docs/ai/planning/feature-meal-planning-agent.md`
- Implementation: `docs/ai/implementation/feature-meal-planning-agent.md`
- Testing: `docs/ai/testing/feature-meal-planning-agent.md`





---

**Last Updated**: 2025-10-29
