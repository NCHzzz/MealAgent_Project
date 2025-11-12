---
phase: reference
title: Elysia • MealAgent Integration Guide
description: Official integration checklist to wire MealAgent into Elysia Decision Tree (Tree/Managers) with setup, registration, and run instructions
---

## Overview
This document standardizes how MealAgent integrates with Elysia, aligning with the official Elysia docs:
- Setting up the environment (Settings, Client, Managers)
- Creating or attaching a MealAgent Tree
- Registering tools to branches
- Running via WebSocket and testing locally

Reference (local and web):
- Elysia docs (local): `elysia/docs/`
- Web: `https://weaviate.github.io/elysia/`

## 1) Setup
### 1.1 Dependencies
```bash
cd elysia
python -m venv venv
venv\Scripts\activate   # Windows (PowerShell)
pip install -U pip
pip install -e .
```

### 1.2 Environment (.env)
```env
# Weaviate
WEAVIATE_URL=http://localhost:8080
WEAVIATE_API_KEY=

# Elysia
ELYSIA_ENV=development
ELYSIA_LOG_LEVEL=INFO

# LLM (optional)
OPENAI_API_KEY=
# OPENAI_EMBEDDING_MODEL=text-embedding-3-small
```

### 1.3 Start Weaviate
```bash
cd Docker
docker-compose up -d weaviate
```

## 2) Create/Attach a MealAgent Tree
Two supported patterns (per Elysia docs):

### 2.1 Factory: Create a dedicated MealAgent Tree
File: `elysia/elysia/MealAgent/tree/meal_tree.py`
```python
from elysia.MealAgent.tree.meal_tree import build_meal_agent_tree
from elysia.config import Settings

tree = build_meal_agent_tree(settings=Settings(), user_id="demo-user")
```
- Initializes a Tree with MealAgent branches (optimized - 8 branches):
  `profile, planning, search, logging, pantry, optimization, cooking, explain`
- Registers all MealAgent tools (15 tools) and Elysia built-in tools (`query`, `cited_summarize`) to the appropriate branch using `tree.add_tool(...)`.

### 2.2 Attach to an existing Tree/TreeManager
File: `elysia/elysia/MealAgent/tree/config.py`
```python
from elysia.MealAgent.tree.config import try_register_meal_agent_tools
# tree_or_manager is an existing Elysia Tree or TreeManager
count = try_register_meal_agent_tools(tree_or_manager)
```
- Tries `register_tools({...})`, falls back to iterative `register_tool(fn)` or updating `tools` dict.
- Use this when Managers already construct the Tree per-session.

## 3) Environment Keys • Tool Contracts
All tools follow Elysia’s standard:
- Write: `yield Result(name="<key>", ...)` → `environment[<tool_fn_name>]["<key>"]`
- Read: `tree_data.environment.find("<tool_fn_name>", "<key>")`
- Stream: plain strings → Text; yield Error objects for graceful failures

Examples:
- `plan_day_e2e_tool` writes `environment["plan_day_e2e_tool"]["plan"]`
- `cook_mode_tool` writes `environment["cook_mode_tool"]["steps"]`
- `cited_summarize` (Elysia built-in) reads from entire Environment and generates summary with citations

## 4) Run Backend
```bash
cd elysia
venv\Scripts\activate
uvicorn elysia.api.app:app --host 0.0.0.0 --port 8000 --reload
```
Health:
- GET `http://localhost:8000/api/health` → {"status": "healthy"}

## 5) Quick Test (WebSocket)
All MealAgent functionality is accessed through Elysia's standard `/ws/query` WebSocket endpoint. The Tree automatically selects and executes tools based on natural language queries.

Example WebSocket message:
```json
{
  "user_id": "demo",
  "conversation_id": "conv_123",
  "query_id": "q_456",
  "query": "Show me how to cook recipe R123",
  "collection_names": ["Recipe"]
}
```

The Tree will automatically select `cook_mode_tool` and stream the cooking steps.

## 6) Workflows (Optimized)
All workflows are now handled by E2E tools:
- Daily Planning: `plan_day_e2e_tool` (handles all steps internally)
- Weekly Planning: `plan_week_e2e_tool` (handles all steps including variety)
- Meal Logging: `log_meal_e2e_tool` (handles parse → calculate → update internally)
- Cooking: `cook_mode_tool`
- Explanations: `cited_summarize` (Elysia built-in)

File: `elysia/elysia/MealAgent/tools/`

## 7) Testing
- Unit: `pytest --cov=MealAgent --cov-report=term`
- Tree-based test snippet added to: `docs/ai/testing/feature-meal-planning-agent.md`

## 8) Alignment Checklist (per Elysia docs)
- [x] Tools are async generators with `@tool`
- [x] Use `TreeData` + `ClientManager` injection
- [x] Environment key convention followed
- [x] Registered tools to branches (Tree factory) or via helper registration
- [x] All functionality accessed via standard `/ws/query` WebSocket endpoint
- [x] Tree automatically selects tools based on natural language queries



