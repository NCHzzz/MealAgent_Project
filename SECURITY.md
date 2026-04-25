# Security Policy

## Reporting a vulnerability

Please do not open public issues that contain API keys, credentials, personal data, or private meal/health information.

For now, report security issues privately to the repository owner/maintainer. Include:

- affected component or file path
- reproduction steps
- expected impact
- any suggested fix

## Secret handling

- Never commit `.env`, `.env.local`, API keys, model provider tokens, Weaviate credentials, or generated logs containing secrets.
- Use `.env.example`, `elysia/.env.example`, and `elysia-frontend/.env.example` as templates.
- Rotate any credentials that were exposed in chat, logs, commits, or screenshots.
- Backend config APIs should return redacted secret placeholders instead of plaintext credentials.

## Supported environments

This repository is research/prototype software intended for local development and public demonstration. Review deployment, authentication, CORS, and data-retention settings before using it with real user data.
