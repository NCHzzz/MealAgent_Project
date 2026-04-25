# Configuration

Copy `.env.example` to `.env` before running the backend. Copy `elysia-frontend/.env.example` to `elysia-frontend/.env.local` before running the frontend in dev mode.

## Backend variables

| Variable | Required | Notes |
| --- | --- | --- |
| `BASE_MODEL` / `BASE_PROVIDER` | Recommended | Base model used by the decision tree. |
| `COMPLEX_MODEL` / `COMPLEX_PROVIDER` | Recommended | Stronger model for complex decisions. |
| `OPENROUTER_API_KEY`, `GEMINI_API_KEY`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY` | One provider key required | Fill only the providers you use. |
| `WEAVIATE_IS_LOCAL` | Yes for Docker | Use `True` with `Docker/docker-compose.yml`. |
| `LOCAL_WEAVIATE_PORT` | Yes for Docker | Defaults to `8078` in this repo. |
| `LOCAL_WEAVIATE_GRPC_PORT` | Yes for Docker | Defaults to `50051`. |
| `WCD_URL`, `WCD_API_KEY` | Cloud only | Use for Weaviate Cloud instead of local Docker. |
| `CORS_ALLOW_ORIGINS` | Yes | Comma-separated browser origins allowed by FastAPI. |

## Frontend variables

| Variable | Notes |
| --- | --- |
| `NEXT_PUBLIC_BACKEND_URL` | Browser-visible backend URL in development. |
| `NEXT_PUBLIC_IS_STATIC` | Set to `true` for static export builds. |

## Secret safety

- Never commit `.env` or `.env.local`.
- API responses redact secret fields with `***REDACTED***`.
- If a credential appears in a committed file or public log, rotate it immediately.
