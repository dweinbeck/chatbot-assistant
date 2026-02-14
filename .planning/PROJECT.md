# Chatbot Assistant

## What This Is

A standalone backend service on GCP that ingests public GitHub repos via webhooks into Cloud SQL (Postgres) as a searchable knowledge base, and exposes a `/chat` endpoint that answers questions using retrieved code/content snippets with citations. Powered by Gemini 2.5 Flash-Lite via the `google-genai` SDK. Designed to serve the personal-brand Next.js frontend as a drop-in replacement for the current Vercel AI SDK + curated JSON chatbot.

## Core Value

When someone asks about my work, they get an accurate, cited answer drawn directly from my actual code — not a hallucinated summary.

## Requirements

### Validated

- GitHub webhook ingestion with signature verification — v1.0
- Async file indexing via Cloud Tasks (add/modify/delete) — v1.0
- Smart chunking (markdown by headings, code by function boundaries) — v1.0
- Denylist filtering (binaries, junk dirs, large files) — v1.0
- Postgres FTS retrieval (tsvector + GIN, ts_rank_cd scoring) — v1.0
- Trigram fallback for symbol/filename queries (pg_trgm) — v1.0
- Gemini 2.5 Flash-Lite chat generation via google-genai SDK — v1.0
- Citations in every response (repo/path@sha:line-range) — v1.0
- Confidence scoring (low/med/high) from retrieval signals — v1.0
- Cloud Run deployment with scale-to-zero — v1.0
- GitHub Actions CI/CD (lint/test/build/deploy on push to main) — v1.0
- Health check endpoint — v1.0

### Active

(None — define with `/gsd:new-milestone`)

### Out of Scope

- Frontend — already exists in personal-brand repo
- Nightly resync / scheduler — not needed, webhooks handle updates
- Vector database / embeddings — Postgres FTS is sufficient and cheaper
- OAuth / user authentication — public chatbot, no user accounts
- Mobile app — web-only via existing frontend
- Conversation memory / multi-turn — most interactions are single-question lookups
- Fine-tuning the LLM — RAG with good retrieval achieves the same goal cheaper
- Private repo indexing — public chatbot shouldn't surface private code

## Context

- Shipped v1.0 with 5,860 LOC Python across 52 source files
- Tech stack: Python / FastAPI / SQLAlchemy / Alembic / structlog / httpx / google-genai
- Infrastructure: GCP Cloud Run / Cloud SQL / Secret Manager / Cloud Tasks / GitHub Actions
- 165 tests passing (mock-based, no external dependencies)
- Designed to be reusable — can point at any GitHub account to index different repos
- Cost-optimized: scale-to-zero Cloud Run, no vector DB, Flash-Lite model

## Constraints

- **Cloud Provider**: GCP only — Cloud Run, Cloud SQL, Secret Manager, Cloud Tasks
- **LLM Model**: Gemini 2.5 Flash-Lite (`gemini-2.5-flash-lite`) via google-genai SDK
- **Language/Framework**: Python / FastAPI
- **Database**: Cloud SQL Postgres with FTS + pg_trgm (no vector DB)
- **Cost**: Must stay low — scale-to-zero, skip junk files, use cheapest viable model
- **Security**: Webhook signature verification mandatory (`X-Hub-Signature-256`)
- **Secrets**: GitHub webhook secret, GitHub token, DB URL via Secret Manager

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Postgres FTS over vector DB | Lower cost, simpler ops, sufficient for code search | ✓ Good — websearch_to_tsquery + ts_rank_cd + trigram fallback covers all query types |
| Cloud Tasks for async indexing | Decouples webhook response from indexing work | ✓ Good — Protocol + InMemory test double pattern enables full mock testing |
| Gemini 2.5 Flash-Lite | Cheapest Gemini model, sufficient for RAG with good context | ✓ Good — structured output via response_schema works well |
| Python / FastAPI | Fast to build, good SDK support | ✓ Good — async throughout, clean DI with Depends() |
| Standalone repo | Clean separation from frontend, reusable for other sites | ✓ Good — clean API boundary at /chat endpoint |
| google-genai SDK (not vertexai) | Modern SDK with native async support | ✓ Good — client.aio for non-blocking LLM calls |
| Mock-based tests | CI reliability without real DB/GCP | ✓ Good — 165 tests in ~0.6s, no external dependencies |
| structlog for logging | Structured JSON in production, console in dev | ✓ Good — clean observability pattern |
| Mechanical citation verification | Drop hallucinated citations from LLM output | ✓ Good — prevents false citations reaching users |
| Confidence from retrieval signals | Use chunk count + ts_rank_cd, not LLM self-assessment | ✓ Good — objective, reproducible scoring |

---
*Last updated: 2026-02-09 after v1.0 milestone completion*
