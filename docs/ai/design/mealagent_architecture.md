---
phase: design
title: MealAgent Architecture
description: Comprehensive architecture diagrams for MealAgent module
---

# MealAgent Architecture

Tài liệu này cung cấp các sơ đồ kiến trúc chi tiết cho module MealAgent, tập trung vào cách MealAgent hoạt động trong hệ thống, data pipeline, và cấu trúc tools.

> 📖 **Xem tổng quan hệ thống**: [System Architecture](./system_architecture.md)

## 1. MealAgent Overview

### 1.1. MealAgent trong Hệ Thống

```mermaid
graph TB
    subgraph System["Hệ Thống"]
        Backend["⚡ Backend API"]
        TreeManager["🌳 TreeManager"]
        Config["⚙️ Config<br/>tree_builder"]
        TreeBuilder["🔧 build_meal_agent_tree()"]
        Tree["🌲 Tree<br/>9 Branches"]
        Tools["🛠️ 15 Tools"]
    end
    
    subgraph Data["Data Layer"]
        Weaviate[("🗄️ Weaviate")]
    end
    
    Backend --> TreeManager
    TreeManager --> Config
    Config -->|"calls"| TreeBuilder
    TreeBuilder -->|"creates"| Tree
    Tree --> Tools
    Tools -->|"uses client_manager"| Weaviate
    
    style TreeBuilder fill:#4ecdc4,stroke:#26a69a,stroke-width:3px,color:#fff
    style Tree fill:#ff6b6b,stroke:#c92a2a,stroke-width:3px,color:#fff
    style Tools fill:#00bcd4,stroke:#0097a7,stroke-width:2px,color:#fff
```

### 1.2. MealAgent Tree Structure

```mermaid
graph TB
    Root["🌳 Root Branch<br/>Intent Detection"]
    
    Root --> Profile["👤 Profile<br/>2 Tools"]
    Root --> Search["🔍 Search<br/>2 Tools"]
    Root --> Nutrition["🥗 Nutrition<br/>2 Tools"]
    Root --> Planning["📅 Planning<br/>2 Tools"]
    Root --> Optimization["⚡ Optimization<br/>3 Tools"]
    Root --> Pantry["🏪 Pantry<br/>2 Tools"]
    Root --> Logging["📝 Logging<br/>2 Tools"]
    Root --> Cooking["👨‍🍳 Cooking<br/>1 Tool"]
    Root --> Explain["💬 Explain<br/>Elysia Tools"]
    
    style Root fill:#ff6b6b,stroke:#c92a2a,stroke-width:3px,color:#fff
    style Profile fill:#4ecdc4,stroke:#26a69a,stroke-width:2px,color:#fff
    style Search fill:#4ecdc4,stroke:#26a69a,stroke-width:2px,color:#fff
    style Nutrition fill:#4ecdc4,stroke:#26a69a,stroke-width:2px,color:#fff
    style Planning fill:#4ecdc4,stroke:#26a69a,stroke-width:2px,color:#fff
    style Optimization fill:#4ecdc4,stroke:#26a69a,stroke-width:2px,color:#fff
    style Pantry fill:#4ecdc4,stroke:#26a69a,stroke-width:2px,color:#fff
    style Logging fill:#4ecdc4,stroke:#26a69a,stroke-width:2px,color:#fff
    style Cooking fill:#4ecdc4,stroke:#26a69a,stroke-width:2px,color:#fff
    style Explain fill:#4ecdc4,stroke:#26a69a,stroke-width:2px,color:#fff
```

### 1.3. MealAgent Components

```mermaid
graph TB
    subgraph MealAgent["MealAgent Module"]
        TreeBuilder["🔧 Tree Builder<br/>build_meal_agent_tree()"]
        
        subgraph Branches["9 Branches"]
            ProfileBranch["👤 profile"]
            SearchBranch["🔍 search"]
            NutritionBranch["🥗 nutrition"]
            PlanningBranch["📅 planning"]
            OptimizationBranch["⚡ optimization"]
            PantryBranch["🏪 pantry"]
            LoggingBranch["📝 logging"]
            CookingBranch["👨‍🍳 cooking"]
            ExplainBranch["💬 explain"]
        end
        
        subgraph Tools["15 Tools"]
            ProfileTools["👤 Profile (2)"]
            SearchTools["🔍 Search (2)"]
            NutritionTools["🥗 Nutrition (2)"]
            PlanningTools["📅 Planning (2)"]
            OptimizationTools["⚡ Optimization (3)"]
            PantryTools["🏪 Pantry (2)"]
            LoggingTools["📝 Logging (2)"]
            CookingTool["👨‍🍳 Cooking (1)"]
        end
        
        subgraph Schemas["Data Schemas"]
            UserProfile["👤 UserProfile"]
            MealPlan["📅 MealPlan"]
            Recipe["📖 Recipe"]
            FDCData["🥗 FDC Data"]
            MealLog["📝 MealLogEntry"]
            Pantry["🏪 Pantry"]
            Shopping["🛒 ShoppingList"]
        end
        
        subgraph Utils["Utility Functions"]
            NutritionUtils["🥗 Nutrition Utils"]
            PlanningHelpers["📅 Planning Helpers"]
            RecipeClassifiers["📖 Recipe Classifiers"]
            WeaviateFilters["🔍 Weaviate Filters"]
            LLMUtils["🧠 LLM Utilities"]
            ProfileTargets["👤 Profile Targets"]
        end
    end
    
    TreeBuilder --> Branches
    Branches --> Tools
    Tools --> Schemas
    Tools --> Utils
    
    style MealAgent fill:#e0f7fa,stroke:#80deea,stroke-width:2px
    style TreeBuilder fill:#4ecdc4,stroke:#26a69a,stroke-width:3px,color:#fff
```

## 2. MealAgent Data Pipeline

### 2.1. Overall Data Flow

```mermaid
sequenceDiagram
    participant User
    participant Tree
    participant DecisionNode
    participant Tool
    participant Environment
    participant Weaviate
    
    User->>Tree: Query
    Tree->>DecisionNode: Analyze
    DecisionNode->>DecisionNode: Select Tool
    DecisionNode->>Tool: Execute
    Tool->>Environment: Read State
    Environment-->>Tool: Data
    Tool->>Weaviate: Query/Update
    Weaviate-->>Tool: Results
    Tool->>Environment: Write State
    Tool-->>Tree: Yield Results
    Tree-->>User: Stream Response
```

### 2.2. Environment State Flow

```mermaid
graph LR
    ProfileTool["👤 profile_crud_tool"] -->|"writes"| ProfileState["profile"]
    ProfileState -->|"read by"| MacroTool["📊 macro_calc_tool"]
    MacroTool -->|"writes"| TargetsState["targets"]
    TargetsState -->|"read by"| PlanTool["📅 plan_day_e2e_tool"]
    ConstraintsTool["🛡️ constraints_guard_tool"] -->|"writes"| FiltersState["filters"]
    FiltersState -->|"read by"| SearchTool["🔍 search_and_rank_tool"]
    SearchTool -->|"writes"| RecipesState["topk"]
    RecipesState -->|"read by"| PlanTool
    PlanTool -->|"writes"| PlanState["plan"]
    PlanState -->|"read by"| LogTool["📝 log_meal_e2e_tool"]
    PlanState -->|"read by"| GapFillTool["⚡ gap_fill_tool"]
    PlanState -->|"read by"| PantryDiffTool["🛒 pantry_diff_tool"]
    
    style ProfileTool fill:#4ecdc4,stroke:#26a69a,stroke-width:2px,color:#fff
    style MacroTool fill:#4ecdc4,stroke:#26a69a,stroke-width:2px,color:#fff
    style PlanTool fill:#ff6b6b,stroke:#c92a2a,stroke-width:3px,color:#fff
    style LogTool fill:#4ecdc4,stroke:#26a69a,stroke-width:2px,color:#fff
    style GapFillTool fill:#4ecdc4,stroke:#26a69a,stroke-width:2px,color:#fff
```

### 2.3. Tool-to-Weaviate Data Flow

```mermaid
graph TB
    subgraph Tools["MealAgent Tools"]
        ProfileTool["👤 profile_crud_tool"]
        PlanTool["📅 plan_day_e2e_tool"]
        LogTool["📝 log_meal_e2e_tool"]
        SearchTool["🔍 search_and_rank_tool"]
        PantryTool["🏪 pantry_crud_tool"]
    end
    
    subgraph Weaviate["Weaviate Collections"]
        UserProfile["👤 UserProfile"]
        MealPlan["📅 MealPlan"]
        MealPlanItem["📋 MealPlanItem"]
        MealLogEntry["📝 MealLogEntry"]
        Recipe["📖 Recipe"]
        Pantry["🏪 Pantry"]
        ShoppingList["🛒 ShoppingList"]
    end
    
    ProfileTool -->|"Read/Write"| UserProfile
    PlanTool -->|"Read"| UserProfile
    PlanTool -->|"Read"| MealLogEntry
    PlanTool -->|"Read"| MealPlan
    PlanTool -->|"Read"| Recipe
    PlanTool -->|"Write"| MealPlan
    PlanTool -->|"Write"| MealPlanItem
    LogTool -->|"Read"| Recipe
    LogTool -->|"Write"| MealLogEntry
    LogTool -->|"Update"| UserProfile
    SearchTool -->|"Query"| Recipe
    PantryTool -->|"CRUD"| Pantry
    
    style Tools fill:#00bcd4,stroke:#0097a7,stroke-width:2px,color:#fff
    style Weaviate fill:#795548,stroke:#5d4037,stroke-width:2px,color:#fff
```

## 3. Tool Architecture

### 3.1. Tools Organization

```mermaid
graph TB
    subgraph Tools["15 MealAgent Tools"]
        Profile["👤 Profile (2)<br/>profile_crud, macro_calc"]
        Search["🔍 Search (2)<br/>constraints_guard, search_and_rank"]
        Nutrition["🥗 Nutrition (2)<br/>calculate_macros, auto_calculate"]
        Planning["📅 Planning (2)<br/>plan_day_e2e, plan_week_e2e"]
        Optimization["⚡ Optimization (3)<br/>gap_fill, substitute, micros"]
        Pantry["🏪 Pantry (2)<br/>pantry_crud, pantry_diff"]
        Logging["📝 Logging (2)<br/>log_meal_e2e, meal_history"]
        Cooking["👨‍🍳 Cooking (1)<br/>cook_mode"]
    end
    
    style Profile fill:#e3f2fd,stroke:#1976d2,stroke-width:2px
    style Search fill:#e8f5e9,stroke:#388e3c,stroke-width:2px
    style Nutrition fill:#fff3e0,stroke:#f57c00,stroke-width:2px
    style Planning fill:#f3e5f5,stroke:#7b1fa2,stroke-width:2px
    style Optimization fill:#fce4ec,stroke:#c2185b,stroke-width:2px
    style Pantry fill:#e0f2f1,stroke:#00796b,stroke-width:2px
    style Logging fill:#fff9c4,stroke:#f9a825,stroke-width:2px
    style Cooking fill:#ffebee,stroke:#d32f2f,stroke-width:2px
```

### 3.2. Tool Dependencies

```mermaid
graph LR
    Profile["profile_crud"] -->|"provides"| Macro["macro_calc"]
    Constraints["constraints_guard"] -->|"provides"| Search["search_and_rank"]
    
    Profile -.->|"reads"| PlanDay["plan_day_e2e"]
    Macro -.->|"reads"| PlanDay
    Constraints -.->|"reads"| PlanDay
    Search -.->|"reads"| PlanDay
    
    PlanDay -.->|"reads"| GapFill["gap_fill"]
    PlanDay -.->|"reads"| Substitute["substitute"]
    PlanDay -.->|"reads"| LogMeal["log_meal_e2e"]
    PlanDay -.->|"reads"| PantryDiff["pantry_diff"]
    
    style PlanDay fill:#ff6b6b,stroke:#c92a2a,stroke-width:3px,color:#fff
```

### 3.3. Tool Registration Flow

```mermaid
graph TB
    TreeBuilder["🔧 build_meal_agent_tree()"]
    Config["⚙️ MEAL_AGENT_TOOLS<br/>15 Tools Registry"]
    
    TreeBuilder -->|"reads"| Config
    TreeBuilder -->|"creates"| RootBranch["🌳 Root Branch"]
    TreeBuilder -->|"adds"| ProfileBranch["👤 Profile Branch"]
    TreeBuilder -->|"adds"| SearchBranch["🔍 Search Branch"]
    TreeBuilder -->|"adds"| NutritionBranch["🥗 Nutrition Branch"]
    TreeBuilder -->|"adds"| PlanningBranch["📅 Planning Branch"]
    TreeBuilder -->|"adds"| OptimizationBranch["⚡ Optimization Branch"]
    TreeBuilder -->|"adds"| PantryBranch["🏪 Pantry Branch"]
    TreeBuilder -->|"adds"| LoggingBranch["📝 Logging Branch"]
    TreeBuilder -->|"adds"| CookingBranch["👨‍🍳 Cooking Branch"]
    TreeBuilder -->|"adds"| ExplainBranch["💬 Explain Branch"]
    
    TreeBuilder -->|"registers"| ProfileTools["👤 profile_crud_tool<br/>macro_calc_tool"]
    TreeBuilder -->|"registers"| SearchTools["🔍 constraints_guard_tool<br/>search_and_rank_tool"]
    TreeBuilder -->|"registers"| NutritionTools["🥗 calculate_recipe_macros_tool<br/>auto_calculate_macros_tool"]
    TreeBuilder -->|"registers"| PlanningTools["📅 plan_day_e2e_tool<br/>plan_week_e2e_tool"]
    TreeBuilder -->|"registers"| OptimizationTools["⚡ gap_fill_tool<br/>substitute_tool<br/>micros_tool"]
    TreeBuilder -->|"registers"| PantryTools["🏪 pantry_crud_tool<br/>pantry_diff_tool"]
    TreeBuilder -->|"registers"| LoggingTools["📝 log_meal_e2e_tool<br/>meal_history_tool"]
    TreeBuilder -->|"registers"| CookingTool["👨‍🍳 cook_mode_tool"]
    
    style TreeBuilder fill:#4ecdc4,stroke:#26a69a,stroke-width:3px,color:#fff
```

## 4. E2E Tools Data Pipeline

### 4.1. plan_day_e2e_tool Pipeline

```mermaid
graph TB
    subgraph Input["Input"]
        Query["💬 User Query"]
        Env["📝 Environment<br/>profile, targets, filters"]
    end
    
    subgraph Tool["plan_day_e2e_tool"]
        Step1["1. Read Environment<br/>profile, targets, constraints"]
        Step2["2. Query Weaviate<br/>UserProfile, MealLogEntry"]
        Step3["3. LLM Draft<br/>Generate suggestions"]
        Step4["4. Search Recipes<br/>From Weaviate database"]
        Step5["5. Calculate Nutrition<br/>Per-recipe macros"]
        Step6["6. Assemble Plan<br/>Select meals by strategy"]
        Step7["7. Validate Plan<br/>Check macros, constraints"]
        Step8["8. Write Weaviate<br/>Save MealPlan"]
        Step9["9. Update Environment<br/>plan_day_e2e_tool.plan"]
    end
    
    subgraph Output["Output"]
        Plan["📅 MealPlan"]
        Response["💬 Response"]
    end
    
    Query --> Step1
    Env --> Step1
    Step1 --> Step2
    Step2 --> Step3
    Step3 --> Step4
    Step4 --> Step5
    Step5 --> Step6
    Step6 --> Step7
    Step7 --> Step8
    Step8 --> Step9
    Step9 --> Plan
    Step9 --> Response
    
    style Tool fill:#f3e5f5,stroke:#7b1fa2,stroke-width:2px
    style Input fill:#e3f2fd,stroke:#1976d2,stroke-width:2px
    style Output fill:#e8f5e9,stroke:#388e3c,stroke-width:2px
```

### 4.2. log_meal_e2e_tool Pipeline

```mermaid
graph TB
    subgraph Input["Input"]
        Query["💬 User Query<br/>Meal description"]
        Env["📝 Environment<br/>plan (optional)"]
    end
    
    subgraph Tool["log_meal_e2e_tool"]
        Step1["1. Parse Input<br/>Extract meal info"]
        Step2["2. Query Weaviate<br/>Recipes, FDC Data"]
        Step3["3. Calculate Nutrition<br/>Meal macros"]
        Step4["4. Update Profile<br/>Remaining targets"]
        Step5["5. Write Weaviate<br/>Save MealLogEntry"]
        Step6["6. Update Environment<br/>log_meal_e2e_tool.log"]
    end
    
    subgraph Output["Output"]
        Log["📝 MealLogEntry"]
        Response["💬 Response"]
    end
    
    Query --> Step1
    Env --> Step1
    Step1 --> Step2
    Step2 --> Step3
    Step3 --> Step4
    Step4 --> Step5
    Step5 --> Step6
    Step6 --> Log
    Step6 --> Response
    
    style Tool fill:#fff9c4,stroke:#f9a825,stroke-width:2px
    style Input fill:#e3f2fd,stroke:#1976d2,stroke-width:2px
    style Output fill:#e8f5e9,stroke:#388e3c,stroke-width:2px
```

### 4.3. gap_fill_tool Pipeline

```mermaid
graph TB
    subgraph Input["Input"]
        Query["💬 User Query<br/>Fill calorie gap"]
        Env["📝 Environment<br/>plan_day_e2e_tool.plan"]
    end
    
    subgraph Tool["gap_fill_tool"]
        Step1["1. Read Environment<br/>plan_day_e2e_tool.plan"]
        Step2["2. Calculate Gap<br/>Calorie/nutrient deficit"]
        Step3["3. Search Snacks<br/>Filter by gap requirements"]
        Step4["4. Suggest Snacks<br/>Rank by fit score"]
        Step5["5. Update Plan<br/>Add snacks to plan"]
        Step6["6. Write Weaviate<br/>Update MealPlan"]
        Step7["7. Update Environment<br/>gap_fill_tool.snacks"]
    end
    
    subgraph Output["Output"]
        UpdatedPlan["📅 Updated MealPlan"]
        Response["💬 Response"]
    end
    
    Query --> Step1
    Env --> Step1
    Step1 --> Step2
    Step2 --> Step3
    Step3 --> Step4
    Step4 --> Step5
    Step5 --> Step6
    Step6 --> Step7
    Step7 --> UpdatedPlan
    Step7 --> Response
    
    style Tool fill:#fce4ec,stroke:#c2185b,stroke-width:2px
    style Input fill:#e3f2fd,stroke:#1976d2,stroke-width:2px
    style Output fill:#e8f5e9,stroke:#388e3c,stroke-width:2px
```

## 5. Individual Tool Details

### 5.1. Profile Tools

#### profile_crud_tool
- **Function**: CRUD operations cho UserProfile
- **Reads**: None
- **Writes**: `profile_crud_tool.profile`
- **Weaviate**: Read/Write UserProfile collection
- **Auto-triggers**: Calls `macro_calc_tool` after create/update

#### macro_calc_tool
- **Function**: Calculate TDEE và macro targets
- **Reads**: `profile_crud_tool.profile`
- **Writes**: `macro_calc_tool.targets`
- **Weaviate**: Read UserProfile

### 5.2. Search Tools

#### constraints_guard_tool
- **Function**: Generate filters từ user constraints
- **Reads**: UserProfile (allergens, diet types)
- **Writes**: `constraints_guard_tool.filters`
- **Weaviate**: Read UserProfile

#### search_and_rank_tool
- **Function**: Hybrid search với ranking
- **Reads**: `constraints_guard_tool.filters`
- **Writes**: `search_and_rank_tool.topk`
- **Weaviate**: Query Recipe collection (vector + keyword search)
- **Features**: Uses Elysia Query tool internally for LLM-driven optimization

### 5.3. Nutrition Tools

#### calculate_recipe_macros_tool
- **Function**: Per-recipe nutrition calculation
- **Reads**: Recipe from Weaviate
- **Writes**: Updates Recipe with calculated macros
- **Weaviate**: Read/Update Recipe collection

#### auto_calculate_macros_tool
- **Function**: Batch nutrition calculation
- **Reads**: Multiple recipes
- **Writes**: Updates multiple recipes with macros
- **Weaviate**: Read/Update Recipe collection

### 5.4. Planning Tools

#### plan_day_e2e_tool
- **Function**: End-to-end daily meal planning
- **Reads**: 
  - `macro_calc_tool.targets`
  - `constraints_guard_tool.filters`
  - `search_and_rank_tool.topk` (optional)
- **Writes**: 
  - `plan_day_e2e_tool.plan`
  - `plan_day_e2e_tool.missing_macros`
- **Weaviate**: 
  - Read UserProfile, MealLogEntry, MealPlan
  - Write MealPlan, MealPlanItem
- **Pipeline**: Xem section 4.1
- **Features**: LLM draft generation, variety filtering, macro validation

#### plan_week_e2e_tool
- **Function**: End-to-end weekly meal planning với variety
- **Reads**: Similar to plan_day_e2e_tool
- **Writes**: `plan_week_e2e_tool.plan`
- **Weaviate**: Similar to plan_day_e2e_tool
- **Features**: Weekly variety, meal distribution across days

### 5.5. Optimization Tools

#### gap_fill_tool
- **Function**: Fill calorie/nutrient gaps với snacks
- **Reads**: `plan_day_e2e_tool.plan` hoặc `plan_week_e2e_tool.plan`
- **Writes**: `gap_fill_tool.snacks`
- **Weaviate**: Read Recipe, Update MealPlan
- **Pipeline**: Xem section 4.3

#### substitute_tool
- **Function**: Recipe substitution suggestions
- **Reads**: `plan_day_e2e_tool.plan`
- **Writes**: `substitute_tool.substitutions`
- **Weaviate**: Read Recipe, Update MealPlan

#### micros_tool
- **Function**: Micronutrient analysis và suggestions
- **Reads**: `plan_day_e2e_tool.plan`
- **Writes**: `micros_tool.micros_analysis`
- **Weaviate**: Read Recipe, FDC data

### 5.6. Logging Tools

#### log_meal_e2e_tool
- **Function**: End-to-end meal logging
- **Reads**: `plan_day_e2e_tool.plan` (optional)
- **Writes**: `log_meal_e2e_tool.log`
- **Weaviate**: 
  - Read Recipe, FDC data
  - Write MealLogEntry
  - Update UserProfile (remaining targets)
- **Pipeline**: Xem section 4.2
- **Features**: LLM parsing, nutrition calculation, profile update

#### meal_history_tool
- **Function**: Meal history retrieval và display
- **Reads**: None
- **Writes**: `meal_history_tool.history`
- **Weaviate**: Read MealLogEntry

### 5.7. Pantry Tools

#### pantry_crud_tool
- **Function**: Pantry inventory management
- **Reads**: None
- **Writes**: `pantry_crud_tool.state`
- **Weaviate**: CRUD Pantry collection

#### pantry_diff_tool
- **Function**: Shopping list generation
- **Reads**: 
  - `plan_day_e2e_tool.plan` hoặc `plan_week_e2e_tool.plan`
  - `pantry_crud_tool.state`
- **Writes**: `pantry_diff_tool.shopping_list`
- **Weaviate**: Read Pantry, Write ShoppingList

### 5.8. Cooking Tools

#### cook_mode_tool
- **Function**: Step-by-step cooking instructions
- **Reads**: Recipe from environment hoặc query
- **Writes**: `cook_mode_tool.instructions`
- **Weaviate**: Read Recipe collection

## 6. Data Schemas

### 6.1. Schema Overview

```mermaid
graph TB
    subgraph Schemas["Pydantic Schemas"]
        UserProfile["👤 UserProfile<br/>demographics, goals, preferences"]
        MealPlan["📅 MealPlan<br/>date, meals, nutrition"]
        MealPlanItem["📋 MealPlanItem<br/>meal items"]
        Recipe["📖 Recipe<br/>ingredients, instructions"]
        FDCFood["🥗 FDC_Food<br/>food data"]
        FDCNutrient["💊 FDC_Nutrient<br/>nutrient data"]
        FDCPortion["⚖️ FDC_Portion<br/>portion data"]
        MealLogEntry["📝 MealLogEntry<br/>timestamp, nutrition"]
        Pantry["🏪 Pantry<br/>items, quantities"]
        ShoppingList["🛒 ShoppingList<br/>items needed"]
    end
    
    UserProfile -->|"used by"| ProfileTools
    MealPlan -->|"used by"| PlanningTools
    MealPlanItem -->|"used by"| PlanningTools
    Recipe -->|"used by"| SearchTools
    FDCFood -->|"used by"| NutritionTools
    FDCNutrient -->|"used by"| NutritionTools
    FDCPortion -->|"used by"| NutritionTools
    MealLogEntry -->|"used by"| LoggingTools
    Pantry -->|"used by"| PantryTools
    ShoppingList -->|"used by"| PantryTools
    
    style Schemas fill:#009688,stroke:#00695c,stroke-width:2px,color:#fff
```

## 7. Utility Functions

### 7.1. Utility Overview

```mermaid
graph TB
    subgraph Utils["Utility Functions"]
        NutritionUtils["🥗 Nutrition Utils<br/>Macro/micro calculations"]
        PlanningHelpers["📅 Planning Helpers<br/>Meal assembly, validation"]
        RecipeClassifiers["📖 Recipe Classifiers<br/>Meal type detection"]
        WeaviateFilters["🔍 Weaviate Filters<br/>Filter generation"]
        LLMUtils["🧠 LLM Utilities<br/>Draft generation, critic"]
        ProfileTargets["👤 Profile Targets<br/>Target resolution"]
        RecipeRefresh["🔄 Recipe Refresh<br/>Update recipes"]
    end
    
    NutritionUtils -->|"used by"| NutritionTools
    PlanningHelpers -->|"used by"| PlanningTools
    RecipeClassifiers -->|"used by"| PlanningTools
    WeaviateFilters -->|"used by"| SearchTools
    LLMUtils -->|"used by"| PlanningTools
    ProfileTargets -->|"used by"| ProfileTools
    RecipeRefresh -->|"used by"| SearchTools
    
    style Utils fill:#8bc34a,stroke:#689f38,stroke-width:2px,color:#fff
```

## 8. Key Design Patterns

### 8.1. E2E Tools Pattern
- **Rationale**: Consolidate multiple steps into single atomic operations
- **Benefits**: Reduced round-trips, better error handling, atomic operations
- **Examples**: `plan_day_e2e_tool`, `log_meal_e2e_tool`, `gap_fill_tool`

### 8.2. Environment-Based Communication
- **Pattern**: Tools communicate via shared Environment
- **Read**: `tree_data.environment.find(tool_name, key)`
- **Write**: `tree_data.environment.add_objects(tool_name, key, objects)`
- **Benefits**: Loose coupling, flexible ordering, easy extension

### 8.3. Branch-Based Organization
- **Pattern**: 9 specialized branches for different meal planning tasks
- **Benefits**: Clear separation, better routing, easier maintenance

### 8.4. Tool Chaining
- **Pattern**: Tools can be chained via `chain` parameter in `add_tool()`
- **Examples**: 
  - `macro_calc_tool` chains after `profile_crud_tool`
  - `search_and_rank_tool` chains after `constraints_guard_tool`
  - `pantry_diff_tool` chains after `pantry_crud_tool`
