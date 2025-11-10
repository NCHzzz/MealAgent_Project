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
- Running via REST/WS and testing locally

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
- Initializes a Tree with MealAgent branches:
  `profile, constraints, search, nutrition, plan_day, plan_week, pantry, shopping, gap_fill, substitution, micros, logging, cooking, explain`
- Registers all MealAgent tools to the appropriate branch using `tree.add_tool(...)`.

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
- `plan_assemble_day_tool` writes `environment["plan_assemble_day_tool"]["plan"]`
- `cook_mode_tool` writes `environment["cook_mode_tool"]["steps"]`
- `explain_tool` writes `environment["explain_tool"]["explanation"]`

## 4) API Endpoints (FastAPI)
- Cooking:
  - `POST /api/v1/meal/cook` (non-stream) → returns steps
  - `WS /ws/meal/cook/{user_id}` → streams steps and Result
- Explain:
  - `POST /api/v1/meal/explain` (non-stream) → returns explanation text
Files:
- `elysia/elysia/api/routes/cooking.py`
- Included in `elysia/elysia/api/app.py`

## 5) Run Backend
```bash
cd elysia
venv\Scripts\activate
uvicorn elysia.api.app:app --host 0.0.0.0 --port 8000 --reload
```
Health:
- GET `http://localhost:8000/api/health` → {"status": "healthy"}

## 6) Quick Test (cURL)
```bash
# Cook (non-stream)
curl -X POST http://localhost:8000/api/v1/meal/cook ^
  -H "Content-Type: application/json" ^
  -d "{\"user_id\":\"demo\",\"food_id\":\"R123\"}"

# Explain (non-stream)
curl -X POST http://localhost:8000/api/v1/meal/explain ^
  -H "Content-Type: application/json" ^
  -d "{\"user_id\":\"demo\"}"
```

## 7) Workflows (Helpers)
- Daily Planning: `process_daily_planning_workflow(...)`
- Meal Logging: `process_meal_logging_workflow(...)`
- Cooking: `process_cooking_workflow(...)`
- Explain: `process_explanation_workflow(...)`
File: `elysia/elysia/MealAgent/tree/meal_tree.py`

## 8) Testing
- Unit: `pytest --cov=MealAgent --cov-report=term`
- Tree-based test snippet added to: `docs/ai/testing/feature-meal-planning-agent.md`

## 9) Alignment Checklist (per Elysia docs)
- [x] Tools are async generators with `@tool`
- [x] Use `TreeData` + `ClientManager` injection
- [x] Environment key convention followed
- [x] Registered tools to branches (Tree factory) or via helper registration
- [x] REST/WS endpoints wrap streaming Text/Result/Error



