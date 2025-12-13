---
phase: design
title: System Architecture
description: High-level system architecture for MealAgent platform
---

# System Architecture

## Overview

The MealAgent system is a comprehensive meal planning platform built on top of the Elysia agentic framework. It consists of six main modules:

1. **Frontend Module** - Next.js-based single-page application (SPA)
2. **Backend API Module** - FastAPI-based backend server
3. **Agent Framework Module** - Elysia decision tree engine
4. **MealAgent Module** - Custom meal planning tools
5. **Data Layer Module** - Weaviate vector database
6. **External Services Module** - LLM and embedding providers

> 📖 **Xem chi tiết từng module**: [Module Architectures](./module_architectures.md)  
> 📖 **Xem chi tiết MealAgent**: [MealAgent Architecture](./mealagent_architecture.md)

## System Architecture Diagram

```mermaid
graph TB
    subgraph Client["Client Layer"]
        Browser["🌐 Web Browser"]
    end
    
    subgraph Frontend["1️⃣ Frontend Module"]
        NextJS["⚛️ Next.js 14<br/>React 18, TypeScript"]
        Pages["📄 Pages<br/>Chat, Data, Settings"]
        Contexts["📦 React Contexts<br/>State Management"]
        APIClient["🔌 API Client<br/>REST + WebSocket"]
    end
    
    subgraph Backend["2️⃣ Backend API Module"]
        FastAPI["⚡ FastAPI<br/>Uvicorn ASGI"]
        Routes["🔌 API Routes<br/>/ws/query, /init/*"]
        Services["📦 Services<br/>UserManager, TreeManager<br/>ClientManager"]
        Middleware["🛡️ Middleware<br/>CORS, Error Handlers"]
    end
    
    subgraph Agent["3️⃣ Agent Framework"]
        Tree["🌲 Decision Tree<br/>Branch Routing"]
        DecisionNode["🌿 DecisionNode<br/>DSPy Router"]
        Environment["📝 Environment<br/>Shared State"]
        BuiltInTools["🛠️ Built-in Tools<br/>Query, Aggregate, Text"]
    end
    
    subgraph MealAgent["4️⃣ MealAgent Module"]
        TreeBuilder["🔧 build_meal_agent_tree()"]
        Branches["🌿 9 Branches<br/>profile, search, planning, etc."]
        Tools["🛠️ 15 Tools<br/>plan_day_e2e, log_meal_e2e, etc."]
        Schemas["📋 Data Schemas<br/>Pydantic models"]
        Utils["⚙️ Utility Functions<br/>Helpers"]
    end
    
    subgraph Data["5️⃣ Data Layer"]
        Weaviate[("🗄️ Weaviate<br/>Vector Database")]
        Collections["📚 Collections<br/>Recipe, Profile, Plan, Log"]
        VectorSearch["🔍 Vector Search<br/>Semantic Similarity"]
    end
    
    subgraph External["6️⃣ External Services"]
        LiteLLM["🔌 LiteLLM<br/>Unified Interface"]
        LLM["🧠 LLM Providers<br/>OpenAI, OpenRouter, Ollama"]
        Embeddings["🔤 Embeddings<br/>OpenAI, Cohere, Voyage"]
    end
    
    %% Client to Frontend
    Browser -->|"HTTPS"| NextJS
    NextJS --> Pages
    Pages --> Contexts
    Contexts --> APIClient
    
    %% Frontend to Backend
    APIClient -->|"WebSocket /ws/query"| Routes
    APIClient -->|"REST API"| Routes
    Routes --> Services
    FastAPI --> Routes
    FastAPI --> Middleware
    FastAPI -->|"serves"| NextJS
    
    %% Backend to Agent Framework
    Services -->|"creates"| Tree
    Services -->|"calls"| TreeBuilder
    TreeBuilder -->|"returns Tree with"| Branches
    TreeBuilder -->|"registers"| Tools
    Tree --> DecisionNode
    Tree --> Environment
    DecisionNode -->|"selects from"| BuiltInTools
    DecisionNode -->|"selects from"| Tools
    
    %% Agent to Data
    Tools -->|"uses client_manager"| Weaviate
    BuiltInTools -->|"queries"| Weaviate
    Weaviate --> Collections
    Weaviate --> VectorSearch
    
    %% Agent to External Services
    DecisionNode -->|"uses base_lm/complex_lm"| LiteLLM
    Tools -->|"uses LLM"| LiteLLM
    LiteLLM --> LLM
    Weaviate -->|"embeddings"| Embeddings
    
    %% Response Flow
    Tree -->|"yields results"| Services
    Services -->|"streams"| Routes
    Routes -->|"WebSocket stream"| APIClient
    APIClient -->|"updates UI"| Contexts
    Contexts -->|"renders"| Pages
    
    style Frontend fill:#0070f3,stroke:#0051cc,stroke-width:2px,color:#fff
    style Backend fill:#009688,stroke:#00695c,stroke-width:2px,color:#fff
    style Agent fill:#ff6b6b,stroke:#c92a2a,stroke-width:2px,color:#fff
    style MealAgent fill:#4ecdc4,stroke:#26a69a,stroke-width:2px,color:#fff
    style Data fill:#795548,stroke:#5d4037,stroke-width:2px,color:#fff
    style External fill:#ff9800,stroke:#f57c00,stroke-width:2px,color:#fff
    style TreeBuilder fill:#4ecdc4,stroke:#26a69a,stroke-width:3px,color:#fff
    style DecisionNode fill:#ff9800,stroke:#f57c00,stroke-width:2px,color:#fff
```

## System Flow

### Initialization Flow

```mermaid
sequenceDiagram
    participant User
    participant Frontend
    participant Backend
    participant UserManager
    participant TreeManager
    participant TreeBuilder
    participant Tree
    
    User->>Frontend: New Conversation
    Frontend->>Backend: POST /init/tree
    Backend->>UserManager: get_user_manager()
    UserManager->>TreeManager: initialise_tree()
    TreeManager->>TreeBuilder: build_meal_agent_tree()
    TreeBuilder->>TreeBuilder: Create Tree
    TreeBuilder->>TreeBuilder: Add 9 Branches
    TreeBuilder->>TreeBuilder: Register 15 Tools
    TreeBuilder-->>TreeManager: Tree instance
    TreeManager-->>UserManager: Tree ready
    UserManager-->>Backend: Tree structure
    Backend-->>Frontend: Tree initialized
```

## Module Descriptions

### 1. Frontend Module
- **Technology**: Next.js 14, React 18, TypeScript, Tailwind CSS
- **Features**: SPA with client-side routing, real-time chat, data visualization
- **Communication**: REST API and WebSocket connections
- **Components**: Pages, React Contexts, UI Components (Radix UI, Shadcn, Recharts, Three.js)

### 2. Backend API Module
- **Technology**: FastAPI, Uvicorn, Python
- **Components**: UserManager, TreeManager, ClientManager
- **Endpoints**: `/ws/query`, `/init/*`, `/collections/*`, `/auth/*`, `/user/config/*`, `/tree/config/*`, `/feedback/*`, `/tools/*`, `/db/*`
- **Middleware**: CORS, Error Handlers
- **Preprocessor**: Collection schema analysis

### 3. Agent Framework Module
- **Technology**: Elysia Tree, DSPy, LiteLLM
- **Components**: Decision Tree, DecisionNode, Environment, Built-in Tools
- **Function**: Routes queries to appropriate tools via LLM-based decision making
- **Built-in Tools**: Query, Aggregate, Objects, Chunk, CitedSummarizer, TextResponse, Visualize, Regression, SummariseItems

### 4. MealAgent Module
- **Technology**: Python 3.11+, Elysia Tree integration
- **Components**: Tree Builder (`build_meal_agent_tree()`), 15 Tools, 9 Branches, Schemas, Utils
- **Function**: Provides domain-specific meal planning capabilities
- **Tools**: Profile, Search, Nutrition, Planning, Optimization, Pantry, Logging, Cooking tools

### 5. Data Layer Module
- **Technology**: Weaviate Vector Database
- **Collections**: Recipe, UserProfile, MealPlan, MealPlanItem, MealLogEntry, Pantry, ShoppingList, FDC data, Elysia metadata
- **Features**: Vector search, hybrid search, semantic similarity
- **Embeddings**: OpenAI, Cohere, Voyage AI

### 6. External Services Module
- **LLM Providers**: OpenAI, OpenRouter, Ollama (via LiteLLM)
- **Embeddings**: OpenAI, Cohere, Voyage AI
- **Function**: Provides AI capabilities for decision making, text generation, and vectorization
- **Usage**: DecisionNode, Text Tools, Preprocessor, Planning Tools use LLM; Weaviate uses embeddings
