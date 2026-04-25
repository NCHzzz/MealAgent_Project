# Local development

This project runs three local services during development:

1. Weaviate and transformer inference via Docker Compose.
2. FastAPI backend from `elysia/`.
3. Next.js frontend from `elysia-frontend/`.

## One-command setup

```powershell
Copy-Item .env.example .env
Copy-Item elysia-frontend\.env.example elysia-frontend\.env.local
powershell -ExecutionPolicy Bypass -File scripts/setup-dev.ps1
powershell -ExecutionPolicy Bypass -File scripts/start-system.ps1
powershell -ExecutionPolicy Bypass -File scripts/status-system.ps1
```

## URLs

- Frontend: <http://127.0.0.1:3000>
- Backend health: <http://127.0.0.1:8000/api/health>
- Weaviate readiness: <http://localhost:8078/v1/.well-known/ready>

## Logs and process IDs

Runtime logs are written to `.runlogs/` and process IDs to `.runpids/`. Both directories are local-only and ignored by Git.

## Stopping services

```powershell
powershell -ExecutionPolicy Bypass -File scripts/stop-system.ps1
```
