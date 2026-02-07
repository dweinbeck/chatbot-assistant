# Chatbot Assistant

## What This Is

A standalone backend service on GCP that ingests public GitHub repos via webhooks into Cloud SQL (Postgres) as a searchable knowledge base, and exposes a `/chat` endpoint that answers questions using retrieved code/content snippets with citations. Powered by Gemini 2.5 Flash-Lite via Vertex AI. Designed to serve the personal-brand Next.js frontend as a drop-in replacement for the current Vercel AI SDK + curated JSON chatbot.

## Core Value

When someone asks about my work, they get an accurate, cited answer drawn directly from my actual code — not a hallucinated summary.

## Requirements

### Validated

(None yet — ship to validate)

### Active

- [ ] GitHub webhook ingestion with signature verification
- [ ] Async file indexing via Cloud Tasks (add/modify/delete)
- [ ] Smart chunking (markdown by headings, code by function boundaries)
- [ ] Denylist filtering (binaries, junk dirs, large files)
- [ ] Postgres FTS retrieval (tsvector + GIN, ts_rank_cd scoring)
- [ ] Trigram fallback for symbol/filename queries (pg_trgm)
- [ ] Gemini 2.5 Flash-Lite chat generation via Vertex AI
- [ ] Citations in every response (repo/path@sha:line-range)
- [ ] Confidence scoring (low/med/high)
- [ ] Cloud Run deployment with scale-to-zero
- [ ] GitHub Actions CI/CD (lint/test/build/deploy on push to main)
- [ ] Health check endpoint

### Out of Scope

- Frontend — already exists in personal-brand repo
- Nightly resync / scheduler — not needed, webhooks handle updates
- Vector database / embeddings — Postgres FTS is sufficient and cheaper
- OAuth / user authentication — public chatbot, no user accounts
- Mobile app — web-only via existing frontend

## Context

- This service lives in its own repo (`chatbot-assistant`), separate from `personal-brand`
- The personal-brand Next.js frontend will call this service's `/chat` endpoint
- Designed to be reusable — can point at any GitHub account to index different repos
- Replaces the current Vercel AI SDK + curated JSON knowledge base approach
- Cost sensitivity is high — scale-to-zero Cloud Run, no vector DB, Flash-Lite model

## Constraints

- **Cloud Provider**: GCP only — Cloud Run, Cloud SQL, Secret Manager, Cloud Tasks, Vertex AI
- **LLM Model**: Gemini 2.5 Flash-Lite (`gemini-2.5-flash-lite`) via Vertex AI
- **Language/Framework**: Python / FastAPI
- **Database**: Cloud SQL Postgres with FTS + pg_trgm (no vector DB)
- **Cost**: Must stay low — scale-to-zero, skip junk files, use cheapest viable model
- **Security**: Webhook signature verification mandatory (`X-Hub-Signature-256`)
- **Secrets**: GitHub webhook secret, GitHub token, DB URL via Secret Manager

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Postgres FTS over vector DB | Lower cost, simpler ops, sufficient for code search | — Pending |
| Cloud Tasks for async indexing | Decouples webhook response from indexing work | — Pending |
| Gemini 2.5 Flash-Lite | Cheapest Gemini model, sufficient for RAG with good context | — Pending |
| Python / FastAPI | Fast to build, good Vertex AI SDK support | — Pending |
| Standalone repo | Clean separation from frontend, reusable for other sites | — Pending |

---
*Last updated: 2026-02-07 after initialization*
