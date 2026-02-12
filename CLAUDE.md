# Project Instructions

> Inherits from `~/.claude/CLAUDE.md` — only project-specific overrides below.

---

## Quick Reference
```bash
pip install -r requirements.txt  # Install deps
uvicorn app.main:app --reload    # Local dev
pytest                           # Run tests
ruff check app/ tests/           # Lint
ruff format app/ tests/          # Format
```

---

## Project-Specific Zones

### Safe Zones
- `app/routers/` — FastAPI route handlers
- `app/services/` — Business logic (retrieval, indexer, chunker, gemini_client)
- `app/schemas/` — Pydantic request/response models
- `tests/` — pytest tests

### Caution Zones
- `app/config.py` — pydantic_settings (env var definitions)
- `app/routers/webhooks.py` — GitHub webhook HMAC verification
- `alembic/` — Database migrations
- `scripts/` — Deployment and startup scripts

---

## Tech Stack Summary
| Category | Technology |
|----------|------------|
| Cloud | GCP Cloud Run, Cloud Tasks, Cloud SQL |
| Backend | Python 3.12, FastAPI, uvicorn |
| Database | PostgreSQL (SQLAlchemy async, alembic) |
| AI/LLM | Google Gemini 2.5 Flash Lite |
| Search | PostgreSQL Full-Text Search (FTS) |
| Validation | Pydantic v2 |
| Linting | ruff |
| CI/CD | GitHub Actions |

---

## Key Patterns (Reference)
- **Settings:** `pydantic_settings.BaseSettings` in `app/config.py` — single source for all env vars
- **Async throughout:** FastAPI-native async handlers, async SQLAlchemy with asyncpg
- **Service layer:** Retrieval, Indexer, GeminiClient as injectable dependencies
- **FTS with fallback:** AND-based FTS with OR fallback for broad queries
- **Cloud Tasks dispatch:** Async indexing via GCP Cloud Tasks queue

---

## Deployment
- **Target:** GCP Cloud Run (512Mi, 1 CPU, 0-4 instances)
- **CI/CD:** GitHub Actions — lint + test on PR, deploy on push to main
- **Startup:** `scripts/start.sh` (alembic migrate + uvicorn)
- **Required env vars:** DATABASE_URL, GITHUB_TOKEN, GITHUB_WEBHOOK_SECRET, GCP_PROJECT, GEMINI_MODEL
- **Smoke test:** `curl https://[URL]/health`

---

## Known Gotchas
| Gotcha | Details |
|--------|---------|
| Cloud Run /healthz | Use `/health` — Cloud Run intercepts `/healthz` |
| Session factory | Must access via module ref to pick up `init_engine()` changes |
| FTS AND semantics | Broad queries fail with AND — OR fallback handles this |
| Alembic + Cloud SQL | Start script has retry loop for proxy startup timing |
