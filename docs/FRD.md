# Functional Requirements Document (FRD)

## Goals

1. Ingest public GitHub repositories via webhooks into a PostgreSQL knowledge base with full-text search indexing.
2. Expose a `/chat` endpoint that answers questions about indexed code with cited, verifiable responses powered by Gemini 2.5 Flash-Lite.
3. Run on GCP Cloud Run with scale-to-zero economics and automated CI/CD deployment.
4. Provide admin endpoints for manual repository syncing, bulk backfill, and web page ingestion.

## Non-Goals

- Frontend UI (handled by a separate Next.js personal-brand repository).
- Nightly resync or scheduled re-indexing.
- Conversation memory or multi-turn chat context.
- Vector embeddings or semantic search (Postgres FTS with trigram fallback is the retrieval strategy).
- Private repository support.
- Fine-tuning the LLM.
- Streaming responses (deferred to v2).

## User Persona

**Primary: Portfolio Website Visitor**
A recruiter, hiring manager, or fellow developer visiting a personal brand website who wants to ask questions about the site owner's code projects. They expect accurate, concise answers grounded in actual source code with verifiable citations. They have low tolerance for hallucinated or fabricated responses.

**Secondary: Site Owner (Admin)**
The developer who owns the portfolio. They need to seed the knowledge base by syncing their public GitHub repos, backfill multiple repos at once, and ingest supplementary content from web pages for private or non-GitHub sources.

---

## Scenarios

### S1: Automatic Indexing via GitHub Webhook

A developer pushes code to a public GitHub repository that has a webhook configured to point at this service. The push event triggers automatic indexing of added/modified files and deletion of removed files, keeping the knowledge base current without manual intervention.

### S2: Answering a Code Question

A website visitor asks "How does the chunking engine work?" via the chat interface. The system retrieves relevant code chunks from the knowledge base using full-text search, builds context for the LLM, calls Gemini, and returns a cited answer with confidence scoring.

### S3: Empty Knowledge Base

A visitor asks a question before any repositories have been indexed. The system detects an empty knowledge base and returns a helpful message directing the admin to sync a repository.

### S4: Manual Repository Sync

The site owner uses the admin endpoint to sync a public GitHub repository. The service lists all files via the GitHub Tree API, filters out denied files, and enqueues indexing tasks for each eligible file.

### S5: Bulk Backfill

The site owner backfills multiple repositories at once via the admin backfill endpoint. Each repo is processed independently, with per-repo status and error reporting.

### S6: Web Page Ingestion

The site owner ingests content from a web page (e.g., documentation for a private repo that cannot be accessed via the GitHub API). The service fetches the page, extracts text from HTML, chunks it, and stores it in the knowledge base under a synthetic repo identity.

### S7: Webhook Signature Rejection

A malicious actor sends a forged webhook payload. The HMAC-SHA256 signature verification fails, and the request is rejected with a 401 response before any processing occurs.

### S8: Low-Confidence Response

A visitor asks a vague question. The retrieval returns few or low-scoring chunks. The system returns the LLM's answer but downgrades confidence to "low" based on retrieval signals, not LLM self-assessment.

---

## End-to-End Workflows

### Webhook Indexing Flow

1. GitHub sends a push webhook to `POST /webhooks/github`.
2. Service verifies HMAC-SHA256 signature against configured secret.
3. Service parses push payload to extract added, modified, and removed files.
4. For each added/modified file: enqueue an `index-file` task via Cloud Tasks.
5. For each removed file: enqueue a `delete-file` task via Cloud Tasks.
6. Return `202 Accepted` with task count.
7. Cloud Tasks delivers each task to the task handler endpoints.
8. `POST /tasks/index-file`: fetch content from GitHub, check denylist, compute hash, chunk, upsert to DB.
9. `POST /tasks/delete-file`: find and remove the file and its chunks from DB.

### Chat Flow

1. Visitor sends `POST /chat` with a question (1-1000 characters).
2. Service runs full-text search (AND semantics via `websearch_to_tsquery`).
3. If zero FTS-AND results, falls back to OR-based FTS.
4. If still fewer than 3 results, augments with trigram similarity search on file paths.
5. Computes confidence from retrieval signals (chunk count + top score).
6. Builds context string from retrieved chunks with metadata headers.
7. Calls Gemini with system prompt and context.
8. Parses structured LLM response (answer, citations, needs_clarification).
9. Mechanically verifies citations against actually-retrieved chunks (drops hallucinated citations).
10. Returns `ChatResponse` with answer, verified citations, and confidence level.

### Admin Sync Flow

1. Admin sends `POST /admin/sync-repo` with owner, repo, and optional ref.
2. Service fetches repo metadata and file list from GitHub API.
3. Filters files through denylist.
4. Enqueues index-file tasks for each eligible file.
5. Returns summary with file counts and task count.

---

## Requirements

### API Requirements

| ID | Requirement | Status |
|----|-------------|--------|
| API-01 | `GET /health` returns status and database connectivity check | Done |
| API-02 | `POST /webhooks/github` validates HMAC-SHA256 signature and rejects invalid requests with 401 | Done |
| API-03 | `POST /webhooks/github` parses push payload and enqueues index/delete tasks, returns 202 | Done |
| API-04 | `POST /tasks/index-file` fetches file content, checks denylist, chunks, and upserts to DB | Done |
| API-05 | `POST /tasks/delete-file` removes file and its chunks from DB | Done |
| API-06 | `POST /chat` accepts a question (1-1000 chars) and returns answer + citations + confidence | Done |
| API-07 | `POST /admin/sync-repo` lists repo files and enqueues index tasks for eligible files | Done |
| API-08 | `POST /admin/backfill` processes multiple repos with per-repo status reporting | Done |
| API-09 | `POST /admin/ingest-url` fetches a web page, extracts text, chunks, and stores in KB | Done |
| API-10 | CORS middleware configurable via `CORS_ORIGINS` environment variable | Done |
| API-11 | Global exception handler returns JSON 500 for unhandled exceptions | Done |

### Retrieval Requirements

| ID | Requirement | Status |
|----|-------------|--------|
| RAG-01 | Primary retrieval uses `websearch_to_tsquery` with AND semantics | Done |
| RAG-02 | OR-based FTS fallback when AND search returns zero results | Done |
| RAG-03 | Trigram similarity fallback on file paths when FTS returns fewer than 3 results | Done |
| RAG-04 | Results capped at 12 chunks maximum | Done |
| RAG-05 | Confidence scoring derived from retrieval signals only (never LLM self-assessment) | Done |
| RAG-06 | Confidence levels: high (enough chunks + high score), medium (one condition), low (neither) | Done |

### Ingestion Requirements

| ID | Requirement | Status |
|----|-------------|--------|
| ING-01 | Denylist filters by directory patterns (node_modules, dist, .git, etc.) | Done |
| ING-02 | Denylist filters by file extension (binaries, images, lock files, etc.) | Done |
| ING-03 | Denylist filters by exact filename (package-lock.json, yarn.lock, etc.) | Done |
| ING-04 | Denylist rejects files larger than 500 KB | Done |
| ING-05 | Content hashing (SHA-256) for change detection and deduplication | Done |
| ING-06 | Markdown files split at ATX heading boundaries | Done |
| ING-07 | Code files split at function/class boundaries for supported languages | Done |
| ING-08 | Fallback to fixed-size line-based chunks (200-400 lines) for unknown extensions | Done |
| ING-09 | Supported code boundary languages: Python, JavaScript, TypeScript, TSX, Go, Rust, Java | Done |
| ING-10 | Small code files (under max_lines) returned as single chunk | Done |

### Chat Requirements

| ID | Requirement | Status |
|----|-------------|--------|
| CHAT-01 | LLM system prompt constrains answers to provided context only | Done |
| CHAT-02 | Citation format: `owner/repo/path@sha:start_line-end_line` | Done |
| CHAT-03 | Mechanical citation verification drops hallucinated citations | Done |
| CHAT-04 | Empty knowledge base returns helpful guidance message | Done |
| CHAT-05 | No relevant results returns rephrasing suggestion | Done |
| CHAT-06 | LLM errors return graceful fallback message | Done |
| CHAT-07 | LLM `needs_clarification` flag downgrades confidence to low | Done |
| CHAT-08 | No verified citations downgrades confidence to low | Done |

### Database Requirements

| ID | Requirement | Status |
|----|-------------|--------|
| DB-01 | `repos` table with unique constraint on (owner, name) | Done |
| DB-02 | `kb_files` table with unique constraint on (repo_id, path) | Done |
| DB-03 | `kb_chunks` table with computed tsvector column (`content_tsv`) | Done |
| DB-04 | GIN index on `content_tsv` for full-text search | Done |
| DB-05 | GIN trigram index on `kb_files.path` for fuzzy filename search | Done |
| DB-06 | CASCADE deletes from repos to files and chunks | Done |
| DB-07 | Alembic migration for initial schema with pg_trgm extension | Done |
| DB-08 | Async database sessions with auto-commit/rollback | Done |

### Infrastructure Requirements

| ID | Requirement | Status |
|----|-------------|--------|
| INFRA-01 | Multi-stage Docker build with python:3.12-slim | Done |
| INFRA-02 | Cloud Run deployment with scale-to-zero | Done |
| INFRA-03 | GitHub Actions CI/CD: lint, test, build, deploy on push to main | Done |
| INFRA-04 | Workload Identity Federation for keyless GitHub Actions auth to GCP | Done |
| INFRA-05 | Secrets managed via GCP Secret Manager | Done |
| INFRA-06 | Database migrations run automatically on container startup | Done |
| INFRA-07 | Structured JSON logging in production, console logging in development | Done |

---

## Coverage

All requirements from phases 1-4 of the project specification are implemented. The following items from the spec are deferred to future phases:

- Streaming responses (SSE)
- Reconciliation job (scheduled webhook catch-up)
- Rate limiting on chat endpoint
- Conversation memory / multi-turn context
- Hybrid search with vector embeddings
