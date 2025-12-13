---
phase: design
title: Module Architectures
description: Detailed architecture diagrams for each module in the MealAgent system
---

# Module Architectures

Tài liệu này cung cấp các sơ đồ chi tiết cho từng module trong hệ thống MealAgent.

> 📖 **Xem tổng quan hệ thống**: [System Architecture](./system_architecture.md)  
> 📖 **Xem chi tiết MealAgent**: [MealAgent Architecture](./mealagent_architecture.md)

## 1. Frontend Module

### Architecture Diagram

```mermaid
graph TB
    subgraph Frontend["1️⃣ Frontend Module"]
        Browser["🌐 Web Browser"]
        NextJS["⚛️ Next.js 14<br/>Static Export"]
        
        subgraph Pages["Pages Layer"]
            ChatPage["💬 ChatPage<br/>Main chat interface"]
            DataPage["📊 DataPage<br/>Data exploration"]
            SettingsPage["⚙️ SettingsPage<br/>Configuration"]
            ProfilePage["👤 ProfilePage<br/>User profile"]
            MealHistoryPage["📝 MealHistoryPage<br/>Meal logs"]
            EvalPage["📈 EvalPage<br/>Evaluation"]
        end
        
        subgraph Contexts["React Contexts"]
            AuthContext["🔐 AuthContext<br/>Authentication"]
            ChatContext["💬 ChatContext<br/>Messages"]
            SocketContext["🔌 SocketContext<br/>WebSocket"]
            CollectionContext["📚 CollectionContext<br/>Metadata"]
            ConversationContext["💭 ConversationContext<br/>History"]
            DisplayContext["🖼️ DisplayContext<br/>Rendering"]
            ProcessingContext["⚙️ ProcessingContext<br/>Status"]
        end
        
        subgraph Components["UI Components"]
            RadixUI["♿ Radix UI<br/>Primitives"]
            Shadcn["🎨 Shadcn<br/>Components"]
            Charts["📊 Recharts<br/>Visualization"]
            ThreeJS["🎮 Three.js<br/>3D Graphics"]
        end
        
        APIClient["🔌 API Client<br/>REST + WebSocket"]
    end
    
    Browser -->|"HTTPS"| NextJS
    NextJS --> Pages
    Pages --> ChatPage
    Pages --> DataPage
    Pages --> SettingsPage
    Pages --> ProfilePage
    Pages --> MealHistoryPage
    Pages --> EvalPage
    Pages --> Contexts
    Contexts --> AuthContext
    Contexts --> ChatContext
    Contexts --> SocketContext
    Contexts --> CollectionContext
    Contexts --> ConversationContext
    Contexts --> DisplayContext
    Contexts --> ProcessingContext
    Pages --> Components
    Components --> RadixUI
    Components --> Shadcn
    Components --> Charts
    Components --> ThreeJS
    Contexts --> APIClient
    APIClient -->|"HTTP/WS"| Backend["Backend API"]
    
    style Frontend fill:#0070f3,stroke:#0051cc,stroke-width:2px,color:#fff
    style NextJS fill:#0070f3,stroke:#0051cc,stroke-width:2px,color:#fff
```

### Key Components

- **Pages**: ChatPage, DataPage, SettingsPage, ProfilePage, MealHistoryPage, EvalPage
- **Contexts**: AuthContext, ChatContext, SocketContext, CollectionContext, ConversationContext, DisplayContext, ProcessingContext
- **API Client**: REST API và WebSocket communication
- **Components**: Radix UI, Shadcn, Recharts, Three.js

---

## 2. Backend API Module

### Architecture Diagram

```mermaid
graph TB
    subgraph Backend["2️⃣ Backend API Module"]
        FastAPI["⚡ FastAPI<br/>Uvicorn ASGI"]
        
        subgraph Routes["API Routes"]
            RouteQuery["🔌 /ws/query<br/>WebSocket query"]
            RouteProcessor["⚙️ /ws/process_collection<br/>Preprocessing"]
            RouteInit["🚀 /init/*<br/>Initialization"]
            RouteAuth["🔐 /auth/*<br/>Authentication"]
            RouteCollections["📚 /collections/*<br/>CRUD operations"]
            RouteUserConfig["⚙️ /user/config/*<br/>User config"]
            RouteTreeConfig["🌳 /tree/config/*<br/>Tree config"]
            RouteFeedback["💬 /feedback/*<br/>Feedback"]
            RouteTools["🛠️ /tools/*<br/>Tool management"]
            RouteDB["🗄️ /db/*<br/>Database utils"]
        end
        
        subgraph Services["Services Layer"]
            UserManager["📦 UserManager<br/>Sessions & Trees"]
            TreeManager["🌳 TreeManager<br/>Tree Lifecycle"]
            ClientManager["🔌 ClientManager<br/>Weaviate Pool"]
        end
        
        subgraph Middleware["Middleware"]
            CORSMiddleware["🌐 CORS"]
            ErrorHandlers["⚠️ Error Handlers"]
        end
        
        Preprocessor["📊 Preprocessor<br/>Schema Analysis"]
        StaticFiles["📁 Static Files<br/>Frontend Export"]
    end
    
    FastAPI --> Middleware
    Middleware --> CORSMiddleware
    Middleware --> ErrorHandlers
    FastAPI --> StaticFiles
    FastAPI --> Routes
    Routes --> RouteQuery
    Routes --> RouteProcessor
    Routes --> RouteInit
    Routes --> RouteAuth
    Routes --> RouteCollections
    Routes --> RouteUserConfig
    Routes --> RouteTreeConfig
    Routes --> RouteFeedback
    Routes --> RouteTools
    Routes --> RouteDB
    
    RouteQuery --> UserManager
    RouteProcessor --> UserManager
    RouteInit --> UserManager
    RouteAuth --> UserManager
    RouteCollections --> UserManager
    RouteUserConfig --> UserManager
    RouteTreeConfig --> UserManager
    RouteFeedback --> UserManager
    
    UserManager --> TreeManager
    UserManager --> ClientManager
    UserManager --> Preprocessor
    
    TreeManager --> Tree["Agent Framework"]
    ClientManager --> Weaviate[("Weaviate")]
    Preprocessor --> Weaviate
    
    style Backend fill:#009688,stroke:#00695c,stroke-width:2px,color:#fff
    style UserManager fill:#9c27b0,stroke:#6a1b9a,stroke-width:2px,color:#fff
    style TreeManager fill:#9c27b0,stroke:#6a1b9a,stroke-width:2px,color:#fff
    style ClientManager fill:#9c27b0,stroke:#6a1b9a,stroke-width:2px,color:#fff
```

### Key Components

- **API Routes**: `/ws/query`, `/ws/process_collection`, `/init/*`, `/auth/*`, `/collections/*`, `/user/config/*`, `/tree/config/*`, `/feedback/*`, `/tools/*`, `/db/*`
- **Services**: UserManager (sessions, trees), TreeManager (tree lifecycle), ClientManager (Weaviate connection pool)
- **Middleware**: CORS, Error Handlers
- **Preprocessor**: Collection schema analysis và metadata generation
- **Static Files**: Serves exported Next.js frontend

---

## 3. Agent Framework Module (Elysia Core)

### Architecture Diagram

```mermaid
graph TB
    subgraph Agent["3️⃣ Agent Framework Module (Elysia Core)"]
        Tree["🌲 Tree Class<br/>Main Orchestrator"]
        TreeData["📝 TreeData<br/>Query & State"]
        Environment["📝 Environment<br/>Shared State"]
        Branches["🌿 Branches<br/>Branch Routing"]
        DecisionNode["🌿 DecisionNode<br/>DSPy Router"]
        
        subgraph Tools["Built-in Tools"]
            ToolQuery["🔍 Query Tool<br/>Weaviate query"]
            ToolAggregate["📊 Aggregate Tool<br/>Aggregations"]
            ToolObjects["📦 Objects Tool<br/>Object retrieval"]
            ToolChunk["✂️ Chunk Tool<br/>Text chunking"]
            ToolCitedSummarizer["📝 CitedSummarizer<br/>Explanations"]
            ToolTextResponse["💬 TextResponse<br/>Text generation"]
            ToolVisualize["📊 Visualize Tool<br/>Charts"]
            ToolRegression["📈 Linear Regression<br/>Analysis"]
            ToolSummarise["🔄 SummariseItems<br/>Postprocessing"]
        end
        
        ToolExecutor["⚙️ Tool Executor"]
        ToolDecorator["@tool<br/>Decorator"]
    end
    
    Tree --> TreeData
    TreeData --> Environment
    Tree --> Branches
    Tree --> DecisionNode
    DecisionNode -->|"selects"| Tools
    Tools --> ToolQuery
    Tools --> ToolAggregate
    Tools --> ToolObjects
    Tools --> ToolChunk
    Tools --> ToolCitedSummarizer
    Tools --> ToolTextResponse
    Tools --> ToolVisualize
    Tools --> ToolRegression
    Tools --> ToolSummarise
    Tools -->|"executes via"| ToolExecutor
    ToolExecutor -->|"updates"| Environment
    Environment -->|"read by"| DecisionNode
    DecisionNode -->|"uses"| LLM["LLM Providers<br/>via LiteLLM"]
    ToolQuery -->|"queries"| Weaviate[("Weaviate")]
    ToolAggregate -->|"queries"| Weaviate
    
    style Agent fill:#ff6b6b,stroke:#c92a2a,stroke-width:2px,color:#fff
    style DecisionNode fill:#ff9800,stroke:#f57c00,stroke-width:2px,color:#fff
    style Tree fill:#ff6b6b,stroke:#c92a2a,stroke-width:3px,color:#fff
    style ToolDecorator fill:#ff9800,stroke:#f57c00,stroke-width:2px,color:#fff
```

### Key Components

- **Tree**: Main orchestrator với branch routing và tool execution
- **DecisionNode**: DSPy-based tool selection using base_lm/complex_lm
- **Environment**: Shared state giữa tools (read/write via `find()` và `add_objects()`)
- **Branches**: Route queries to specialized branches
- **Built-in Tools**: Query, Aggregate, Objects, Chunk, CitedSummarizer, TextResponse, Visualize, Regression, SummariseItems
- **@tool Decorator**: Decorator để đăng ký tools vào Tree
- **Tool Executor**: Executes tools và updates Environment

---

## 4. MealAgent Module (Extends Elysia Core)

> 📖 **Xem chi tiết**: [MealAgent Architecture](./mealagent_architecture.md)

### Integration with Elysia Core

```mermaid
graph TB
    subgraph ElysiaCore["Elysia Core Framework"]
        TreeClass["🌲 Tree Class"]
        TreeData["📝 TreeData"]
        Environment["📝 Environment"]
        DecisionNode["🌿 DecisionNode"]
        ToolDecorator["@tool Decorator"]
        BuiltInTools["🛠️ Built-in Tools"]
    end
    
    subgraph MealAgent["MealAgent Module (Extends Elysia)"]
        TreeBuilder["🔧 build_meal_agent_tree()<br/>Creates Tree instance"]
        MealAgentTools["🛠️ 15 MealAgent Tools<br/>Uses @tool decorator"]
        Branches["🌿 9 Custom Branches"]
        Schemas["📋 Data Schemas"]
        Utils["⚙️ Utility Functions"]
    end
    
    TreeClass -->|"inherits from"| TreeBuilder
    TreeBuilder -->|"creates instance"| TreeClass
    TreeBuilder -->|"adds"| Branches
    ToolDecorator -->|"decorates"| MealAgentTools
    MealAgentTools -->|"uses"| TreeData
    MealAgentTools -->|"uses"| Environment
    MealAgentTools -->|"uses"| ClientManager["ClientManager<br/>from Elysia"]
    TreeBuilder -->|"registers"| MealAgentTools
    DecisionNode -->|"can select"| BuiltInTools
    DecisionNode -->|"can select"| MealAgentTools
    MealAgentTools --> Schemas
    MealAgentTools --> Utils
    
    style ElysiaCore fill:#ff6b6b,stroke:#c92a2a,stroke-width:2px,color:#fff
    style MealAgent fill:#4ecdc4,stroke:#26a69a,stroke-width:2px,color:#fff
    style TreeBuilder fill:#4ecdc4,stroke:#26a69a,stroke-width:3px,color:#fff
```

### Architecture Diagram

```mermaid
graph TB
    subgraph MealAgent["4️⃣ MealAgent Module"]
        TreeBuilder["🔧 build_meal_agent_tree()<br/>Tree Builder Function"]
        Config["⚙️ MEAL_AGENT_TOOLS<br/>15 Tools Registry"]
        
        subgraph Branches["9 Custom Branches"]
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
        
        subgraph Tools["15 Custom Tools"]
            ProfileTools["👤 Profile (2)"]
            SearchTools["🔍 Search (2)"]
            NutritionTools["🥗 Nutrition (2)"]
            PlanningTools["📅 Planning (2)"]
            OptimizationTools["⚡ Optimization (3)"]
            PantryTools["🏪 Pantry (2)"]
            LoggingTools["📝 Logging (2)"]
            CookingTool["👨‍🍳 Cooking (1)"]
        end
        
        Schemas["📋 Data Schemas<br/>Pydantic models"]
        Utils["⚙️ Utility Functions<br/>Helpers"]
    end
    
    subgraph ElysiaCore["Elysia Core"]
        TreeClass["🌲 Tree Class"]
        ToolDecorator["@tool"]
        TreeData["TreeData"]
        Environment["Environment"]
    end
    
    Config -->|"provides"| TreeBuilder
    TreeBuilder -->|"creates"| TreeClass
    TreeBuilder -->|"adds"| Branches
    TreeBuilder -->|"registers"| Tools
    ToolDecorator -->|"decorates"| Tools
    Tools -->|"uses"| TreeData
    Tools -->|"uses"| Environment
    Tools --> Schemas
    Tools --> Utils
    
    style MealAgent fill:#4ecdc4,stroke:#26a69a,stroke-width:2px,color:#fff
    style TreeBuilder fill:#4ecdc4,stroke:#26a69a,stroke-width:3px,color:#fff
    style ElysiaCore fill:#ff6b6b,stroke:#c92a2a,stroke-width:2px,color:#fff
```

### Key Components

- **Tree Builder**: `build_meal_agent_tree()` function creates Elysia Tree instance with custom configuration
- **9 Custom Branches**: profile, search, nutrition, planning, optimization, pantry, logging, cooking, explain
- **15 Custom Tools**: Domain-specific meal planning tools using Elysia's `@tool` decorator
- **Elysia Integration**: 
  - Uses `TreeData`, `Environment`, `ClientManager` from Elysia
  - Tools decorated with `@tool` from Elysia
  - Tools registered to Tree via `tree.add_tool()`
  - DecisionNode can select both built-in and custom tools
- **Schemas**: Pydantic data models (UserProfile, MealPlan, Recipe, etc.)
- **Utils**: Nutrition, planning, recipe utilities

---

## 5. Data Layer Module

### Architecture Diagram

```mermaid
graph TB
    subgraph Data["5️⃣ Data Layer Module"]
        Weaviate[("🗄️ Weaviate<br/>Vector Database")]
        
        subgraph Collections["MealAgent Collections"]
            ColRecipe["📖 Recipe<br/>food_id, name, ingredients"]
            ColFDC["🥗 FDC Data<br/>Food, Nutrient, Portion"]
            ColProfile["👤 UserProfile<br/>user_id, goals, preferences"]
            ColMealPlan["📅 MealPlan<br/>plan_id, date, meals"]
            ColMealPlanItem["📋 MealPlanItem<br/>plan items"]
            ColMealLog["📝 MealLogEntry<br/>log_id, timestamp, nutrition"]
            ColPantry["🏪 Pantry<br/>pantry_id, items, quantities"]
            ColShopping["🛒 ShoppingList<br/>list_id, items needed"]
        end
        
        subgraph ElysiaCollections["Elysia Metadata"]
            ColElysiaMetadata["📊 ELYSIA_*<br/>Summaries, Mappings"]
        end
        
        subgraph Search["Search Features"]
            VectorSearch["🔍 Vector Search<br/>Semantic Similarity"]
            HybridSearch["🔎 Hybrid Search<br/>Vector + Keyword"]
            Filters["🛡️ Filters<br/>Where Clauses"]
        end
        
        EmbeddingAPI["🔤 Embedding API<br/>OpenAI, Cohere, Voyage"]
    end
    
    Weaviate --> Collections
    Collections --> ColRecipe
    Collections --> ColFDC
    Collections --> ColProfile
    Collections --> ColMealPlan
    Collections --> ColMealPlanItem
    Collections --> ColMealLog
    Collections --> ColPantry
    Collections --> ColShopping
    Weaviate --> ElysiaCollections
    ElysiaCollections --> ColElysiaMetadata
    
    Weaviate --> Search
    Search --> VectorSearch
    Search --> HybridSearch
    Search --> Filters
    
    Weaviate -->|"generates"| EmbeddingAPI
    EmbeddingAPI -->|"stores"| VectorSearch
    
    Tools["MealAgent Tools"] -->|"read/write"| Weaviate
    ElysiaTools["Elysia Tools"] -->|"query"| Weaviate
    Preprocessor["Preprocessor"] -->|"analyze"| Weaviate
    
    style Data fill:#795548,stroke:#5d4037,stroke-width:2px,color:#fff
    style Weaviate fill:#795548,stroke:#5d4037,stroke-width:3px,color:#fff
```

### Key Collections

- **Recipe**: Recipe data với ingredients và instructions
- **FDC_Food, FDC_Nutrient, FDC_Portion**: Food Data Central data
- **UserProfile**: User profiles với goals và preferences
- **MealPlan**: Daily và weekly meal plans
- **MealPlanItem**: Individual meal items in plans
- **MealLogEntry**: Logged meals với nutrition
- **Pantry**: Pantry inventory
- **ShoppingList**: Generated shopping lists
- **ELYSIA_***: Collection metadata, summaries, mappings

---

## 6. External Services Module

### Architecture Diagram

```mermaid
graph TB
    subgraph External["6️⃣ External Services Module"]
        subgraph LLM["LLM Providers"]
            LiteLLM["🔌 LiteLLM<br/>Unified Interface"]
            OpenAI["🤖 OpenAI<br/>GPT-4, GPT-3.5"]
            OpenRouter["🌐 OpenRouter<br/>Multi-model"]
            Ollama["🦙 Ollama<br/>Local Models"]
        end
        
        subgraph Embeddings["Embedding Providers"]
            OpenAIEmbed["🤖 OpenAI<br/>text-embedding-*"]
            CohereEmbed["🔵 Cohere"]
            VoyageEmbed["🚢 Voyage AI"]
        end
    end
    
    LiteLLM --> OpenAI
    LiteLLM --> OpenRouter
    LiteLLM --> Ollama
    
    DecisionNode["DecisionNode"] -->|"uses base_lm/complex_lm"| LiteLLM
    TextTools["Text Tools"] -->|"uses"| LiteLLM
    Preprocessor["Preprocessor"] -->|"uses"| LiteLLM
    PlanningTools["Planning Tools"] -->|"uses"| LiteLLM
    
    Weaviate[("Weaviate")] -->|"requests"| Embeddings
    Embeddings --> OpenAIEmbed
    Embeddings --> CohereEmbed
    Embeddings --> VoyageEmbed
    
    style External fill:#ff9800,stroke:#f57c00,stroke-width:2px,color:#fff
    style LiteLLM fill:#ffc107,stroke:#f9a825,stroke-width:2px,color:#000
```

### Key Services

- **LLM Providers**: OpenAI (GPT-4, GPT-3.5), OpenRouter (multi-model), Ollama (local models)
- **Unified Interface**: LiteLLM provides unified API cho multiple providers
- **Embeddings**: OpenAI (text-embedding-3-small, text-embedding-3-large), Cohere, Voyage AI
- **Usage**: 
  - DecisionNode uses LLM for tool selection
  - Text tools use LLM for generation
  - Preprocessor uses LLM for schema analysis
  - Planning tools use LLM for draft generation
  - Weaviate uses embeddings for vectorization
