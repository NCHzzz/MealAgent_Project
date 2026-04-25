# Contributing

Thanks for improving MealAgent. This repo contains a Python backend, a Next.js frontend, Docker services, and evaluation tooling, so please keep changes focused and easy to review.

## Local setup

```powershell
Copy-Item .env.example .env
Copy-Item elysia-frontend\.env.example elysia-frontend\.env.local
powershell -ExecutionPolicy Bypass -File scripts/setup-dev.ps1
powershell -ExecutionPolicy Bypass -File scripts/start-system.ps1
```

## Before opening a pull request

Run the checks relevant to your change:

```powershell
# Backend / MealAgent
.\.venv\Scripts\python.exe -m pytest tests/meal_agent/unit

# Frontend
cd elysia-frontend
npm run lint
npm run typecheck
npm run build
```

## Guidelines

- Do not commit secrets, local `.env` files, generated results, `.runlogs/`, `.runpids/`, or large videos.
- Keep large thesis/demo artifacts in GitHub Releases or external hosting.
- Add tests or docs when changing behavior.
- Prefer small, focused pull requests.
- Follow existing Python and TypeScript style in the touched component.
