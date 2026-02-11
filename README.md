# Chatbot Assistant

> RAG chatbot backend that ingests GitHub repos via webhooks, indexes them with Postgres full-text search, and answers questions with cited responses powered by Gemini.

## Description

Chatbot Assistant is a production-ready Retrieval-Augmented Generation (RAG) backend service built on GCP. It automatically ingests public GitHub repositories through webhook-driven indexing, stores code and documentation as searchable chunks in PostgreSQL using full-text search (tsvector + GIN indexes) and trigram similarity (pg_trgm), and exposes a `/chat` endpoint that answers questions about the indexed codebase with verified citations.

The service is designed as a standalone backend for a personal brand website chatbot. A Next.js frontend (in a separate repository) calls the `/chat` endpoint. The architecture intentionally avoids vector databases and embedding pipelines, relying instead on Postgres FTS with trigram fallback to keep operational complexity and costs low. Google Cloud Tasks handles async indexing jobs, and Cloud Run provides scale-to-zero hosting.

Every response includes mechanically-verified citations in `owner/repo/path@sha:start_line-end_line` format, with confidence scoring derived purely from retrieval signals (chunk count and ts_rank_cd scores) rather than LLM self-assessment. The chunking engine splits code at function/class boundaries and markdown at heading boundaries, preserving semantic structure for higher retrieval quality.

## Tech Stack

| Category | Technology |
|----------|------------|
| Language | Python 3.12 |
| Framework | FastAPI, Pydantic v2, Uvicorn |
| Database | PostgreSQL 16 (Cloud SQL), SQLAlchemy 2.0 + asyncpg |
| Search | Postgres FTS (tsvector + GIN), pg_trgm trigram similarity |
| AI/LLM | Google Gemini 2.5 Flash-Lite via Vertex AI (google-genai SDK) |
| Task Queue | Google Cloud Tasks |
| Hosting | Google Cloud Run (scale-to-zero) |
| Secrets | Google Secret Manager |
| Container | Docker (multi-stage build, python:3.12-slim) |
| CI/CD | GitHub Actions (lint, test, build, deploy) |
| Tooling | uv (package manager), Ruff (linter/formatter), Alembic (migrations) |
| Testing | pytest, pytest-asyncio, httpx (async test client) |

## Documentation

- [Functional Requirements (FRD)](docs/FRD.md)
- [Technical Design](docs/TECHNICAL_DESIGN.md)
- [Deployment Guide](docs/DEPLOYMENT.md)

## Development

### Prerequisites

- Python 3.12
- [uv](https://docs.astral.sh/uv/) (package manager)
- PostgreSQL 16 (or Docker for local DB)

### Setup

```bash
# Clone the repository
git clone <repo-url>
cd chatbot-assistant

# Install dependencies
uv sync --frozen --dev

# Start local Postgres
docker compose up -d

# Copy and configure environment
cp .env.example .env

# Run database migrations
uv run alembic upgrade head

# Start the development server
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8080
```

### Quality Gates

```bash
# Run tests
uv run pytest tests/

# Lint
uv run ruff check .

# Format check
uv run ruff format --check .
```

## License

MIT
