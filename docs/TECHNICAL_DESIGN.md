# Technical Design

## System Architecture

Chatbot Assistant follows a webhook-to-queue decoupling pattern with a thin service layer separation. GitHub push webhooks arrive at the webhook router, which verifies signatures and enqueues tasks to Google Cloud Tasks for async processing. Task handlers fetch file content from GitHub, run it through the denylist filter and chunking engine, then upsert chunks into PostgreSQL. The chat endpoint orchestrates retrieval (FTS + trigram fallback), context building, LLM generation via Gemini, and citation verification before returning a structured response. All database access is async via SQLAlchemy 2.0 with asyncpg, and dependencies are injected via FastAPI's Depends() system with protocol-based abstractions that swap between production (GCP) and test (in-memory) implementations.

```
                          +------------------+
                          |  GitHub Webhooks |
                          +--------+---------+
                                   |
                          HMAC-SHA256 verify
                                   |
                          +--------v---------+
                          |  Webhook Router  |
                          |  POST /webhooks  |
                          +--------+---------+
                                   |
                          Enqueue tasks (async)
                                   |
                    +--------------v--------------+
                    |    Google Cloud Tasks        |
                    +--------------+--------------+
                                   |
                    +--------------v--------------+
                    |      Task Router            |
                    |  POST /tasks/index-file     |
                    |  POST /tasks/delete-file    |
                    +--------------+--------------+
                                   |
                    +--------------v--------------+
                    |    Ingestion Pipeline        |
                    |  Denylist -> Fetch -> Hash   |
                    |  -> Chunk -> Upsert          |
                    +--------------+--------------+
                                   |
                    +--------------v--------------+
                    |     PostgreSQL (Cloud SQL)   |
                    |  repos | kb_files | kb_chunks|
                    |  FTS (tsvector + GIN)        |
                    |  Trigram (pg_trgm + GIN)     |
                    +--------------+--------------+
                                   ^
                                   |
                    +--------------+--------------+
                    |     Retrieval Service        |
                    |  FTS-AND -> FTS-OR -> Trgm   |
                    +--------------+--------------+
                                   |
                    +--------------v--------------+
                    |      Chat Router            |
                    |  POST /chat                  |
                    |  Retrieve -> LLM -> Verify   |
                    +--------------+--------------+
                                   |
                    +--------------v--------------+
                    | Gemini 2.5 Flash-Lite        |
                    | (Vertex AI / google-genai)   |
                    +------------------------------+

  +-------------------+       +-------------------+
  |   Admin Router    |       |   Health Router   |
  |  POST /admin/*    |       |  GET /health      |
  +-------------------+       +-------------------+
```

---

## Directory Structure

```
chatbot-assistant/
├── app/                          # Application package
│   ├── __init__.py
│   ├── main.py                   # FastAPI app factory, lifespan, CORS, exception handler
│   ├── config.py                 # Pydantic Settings (env var loading)
│   ├── dependencies.py           # Centralized FastAPI Depends() providers
│   ├── logging_config.py         # Structlog configuration (JSON/console)
│   ├── db/                       # Database layer
│   │   ├── engine.py             # Async engine + session factory init/dispose
│   │   ├── models.py             # SQLAlchemy ORM models (Repo, KBFile, KBChunk)
│   │   └── session.py            # DB session dependency (auto-commit/rollback)
│   ├── routers/                  # HTTP route handlers (thin adapters)
│   │   ├── health.py             # GET /health
│   │   ├── webhooks.py           # POST /webhooks/github (signature verify)
│   │   ├── tasks.py              # POST /tasks/index-file, /tasks/delete-file
│   │   ├── chat.py               # POST /chat (RAG orchestration)
│   │   └── admin.py              # POST /admin/sync-repo, /backfill, /ingest-url
│   ├── schemas/                  # Pydantic request/response models
│   │   ├── health.py             # HealthResponse
│   │   ├── webhooks.py           # PushWebhookPayload, Commit, Repository
│   │   ├── tasks.py              # IndexFilePayload, DeleteFilePayload
│   │   ├── chat.py               # ChatRequest, ChatResponse, Citation, LLMResponse
│   │   └── admin.py              # SyncRepoRequest/Response, BackfillRequest, IngestURLRequest
│   └── services/                 # Business logic (testable, router-agnostic)
│       ├── chunker.py            # Markdown + code chunking engine
│       ├── denylist.py           # File path/extension/size filtering
│       ├── gemini_client.py      # LLM protocol + GeminiClient + InMemoryLLMClient
│       ├── github_client.py      # GitHub REST API (fetch file, list tree, repo metadata)
│       ├── indexer.py            # Indexing orchestration (denylist -> fetch -> hash -> chunk -> upsert)
│       ├── repo_manager.py       # Repo row get-or-create for FK integrity
│       ├── retrieval.py          # FTS + trigram retrieval with ranking
│       └── task_queue.py         # TaskQueue protocol + CloudTasksQueue + InMemoryTaskQueue
├── migrations/                   # Alembic migration scripts
│   ├── env.py                    # Async migration environment
│   └── versions/
│       └── 001_initial_schema.py # Initial tables + GIN indexes + pg_trgm extension
├── scripts/
│   ├── start.sh                  # Container entrypoint (migrate + uvicorn)
│   ├── deploy.sh                 # Manual Cloud Run deployment script
│   └── setup-gcp.sh             # One-time GCP infrastructure provisioning
├── tests/                        # Test suite (pytest-asyncio)
│   ├── conftest.py               # Shared fixtures (mock DB, task queue, LLM client)
│   ├── test_*.py                 # Unit and integration tests
├── .github/workflows/
│   └── ci-cd.yml                 # GitHub Actions CI/CD pipeline
├── Dockerfile                    # Multi-stage build
├── docker-compose.yml            # Local Postgres for development
├── pyproject.toml                # Project metadata, dependencies, tool config
├── alembic.ini                   # Alembic configuration
└── .env.example                  # Environment variable template
```

---

## Data Flows

### Webhook Indexing Flow (Detailed)

1. GitHub sends HTTP POST to `/webhooks/github` with `X-Hub-Signature-256` header.
2. `verify_github_signature` dependency reads raw body, computes HMAC-SHA256 using `GITHUB_WEBHOOK_SECRET`, performs constant-time comparison.
3. If signature invalid, returns 401.
4. Parses raw body as `PushWebhookPayload` (Pydantic model).
5. If `payload.deleted` is true (branch deletion), skips processing.
6. Iterates over `payload.commits`, collecting added + modified + removed file paths.
7. For each added/modified file: creates `IndexFilePayload` and calls `task_queue.enqueue()` targeting `/tasks/index-file`.
8. For each removed file: creates `DeleteFilePayload` and calls `task_queue.enqueue()` targeting `/tasks/delete-file`.
9. Returns `{"status": "accepted", "tasks_enqueued": N}` with 202 status.
10. Cloud Tasks delivers each task payload to the task handler endpoints.

### Index File Flow (Detailed)

1. `POST /tasks/index-file` receives `IndexFilePayload`.
2. `get_or_create_repo()` ensures `repos` row exists (FK integrity).
3. `is_denied(path)` checks directory patterns, file extensions, exact filenames.
4. `fetch_file_content()` calls GitHub REST API at the specific commit SHA.
5. If file not found (404), returns `{"status": "skipped", "reason": "not_found"}`.
6. `is_denied(path, size_bytes)` checks file size (500 KB limit).
7. Computes SHA-256 hash of content.
8. Queries `kb_files` for existing record by (repo_id, path).
9. If exists and hash matches: updates commit_sha only, returns `{"status": "unchanged"}`.
10. If exists and hash differs: deletes old chunks, updates file record.
11. If new: creates `KBFile` record, flushes to get ID.
12. `chunk_file()` dispatches to `chunk_markdown()` or `chunk_code()` based on extension.
13. Creates `KBChunk` records for each chunk (tsvector computed automatically by Postgres).
14. Returns `{"status": "indexed", "chunks": N}`.

### Chat Retrieval Flow (Detailed)

1. `POST /chat` receives `ChatRequest` with question (1-1000 chars).
2. `retrieve_chunks()` runs three-tier search strategy:
   - Tier 1: `search_fts()` using `websearch_to_tsquery('english', query)` with AND semantics, ranked by `ts_rank_cd`.
   - Tier 2: If zero AND results, `search_fts_or()` joins individual words with OR via `to_tsquery`.
   - Tier 3: If fewer than 3 results, `search_trigram()` on `kb_files.path` with `similarity()` function (threshold 0.15).
3. Results deduplicated by chunk ID, capped at 12.
4. `compute_confidence()` evaluates: >= 3 chunks AND top score >= 0.1 = "high"; either condition = "medium"; neither = "low".
5. `build_context()` formats chunks with headers: `--- CHUNK: owner/repo/path@sha:start-end ---`.
6. `llm_client.generate()` sends system prompt + context + question to Gemini.
7. Response parsed as `LLMResponse` (answer, citations, needs_clarification, clarifying_question).
8. `verify_citations()` builds set of valid source strings from retrieved chunks, drops any LLM citation not in the set.
9. If needs_clarification or no verified citations: confidence forced to "low".
10. Returns `ChatResponse` with answer, verified citations, and confidence.

---

## API Contracts

### GET /health

**Response 200:**
```json
{
  "status": "ok",
  "database": "connected"
}
```

### POST /webhooks/github

**Headers:** `X-Hub-Signature-256: sha256=<hmac>`

**Request:** GitHub push webhook payload (see [GitHub docs](https://docs.github.com/en/webhooks/webhook-events-and-payloads#push))

**Response 202:**
```json
{
  "status": "accepted",
  "tasks_enqueued": 5
}
```

### POST /tasks/index-file

**Request:**
```json
{
  "repo_owner": "dweinbeck",
  "repo_name": "chatbot-assistant",
  "repo_id": 123456,
  "path": "app/main.py",
  "commit_sha": "abc123def456..."
}
```

**Response 200:**
```json
{
  "status": "indexed",
  "chunks": 3
}
```

### POST /tasks/delete-file

**Request:**
```json
{
  "repo_owner": "dweinbeck",
  "repo_name": "chatbot-assistant",
  "repo_id": 123456,
  "path": "app/old_module.py"
}
```

**Response 200:**
```json
{
  "status": "deleted"
}
```

### POST /chat

**Request:**
```json
{
  "question": "How does the chunking engine work?"
}
```

**Response 200:**
```json
{
  "answer": "The chunking engine splits files based on their type...",
  "citations": [
    {
      "source": "dweinbeck/chatbot-assistant/app/services/chunker.py@abc123:1-50",
      "relevance": "Defines the chunk_file dispatch function"
    }
  ],
  "confidence": "high"
}
```

### POST /admin/sync-repo

**Request:**
```json
{
  "owner": "dweinbeck",
  "repo": "chatbot-assistant",
  "ref": "main"
}
```

**Response 200:**
```json
{
  "status": "accepted",
  "repo_id": 123456,
  "files_found": 42,
  "tasks_enqueued": 35,
  "files_skipped_denylist": 7
}
```

### POST /admin/backfill

**Request:**
```json
{
  "repos": [
    { "owner": "dweinbeck", "repo": "project-a", "ref": "main" },
    { "owner": "dweinbeck", "repo": "project-b", "ref": "main" }
  ]
}
```

**Response 200:**
```json
{
  "results": [
    {
      "owner": "dweinbeck",
      "repo": "project-a",
      "status": "accepted",
      "files_found": 20,
      "tasks_enqueued": 18,
      "files_skipped_denylist": 2
    },
    {
      "owner": "dweinbeck",
      "repo": "project-b",
      "status": "error",
      "error": "404 Not Found"
    }
  ],
  "total_tasks_enqueued": 18
}
```

### POST /admin/ingest-url

**Request:**
```json
{
  "url": "https://example.com/docs/overview",
  "repo_owner": "dweinbeck",
  "repo_name": "private-project",
  "path": "docs/overview"
}
```

**Response 200:**
```json
{
  "status": "ingested",
  "chunks_created": 5
}
```

---

## Data Models

### repos

| Column | Type | Constraints |
|--------|------|-------------|
| id | Integer | Primary key |
| owner | String(255) | NOT NULL |
| name | String(255) | NOT NULL |
| default_branch | String(255) | NOT NULL, default "main" |
| updated_at | DateTime | server_default=now(), onupdate=now() |

**Unique:** (owner, name)

### kb_files

| Column | Type | Constraints |
|--------|------|-------------|
| id | Integer | Primary key |
| repo_id | Integer | FK repos.id ON DELETE CASCADE |
| path | String(1024) | NOT NULL |
| commit_sha | String(40) | NOT NULL |
| sha256 | String(64) | NOT NULL |
| updated_at | DateTime | server_default=now(), onupdate=now() |

**Unique:** (repo_id, path)
**Index:** GIN trigram on `path` (`ix_kb_files_path_trgm`)

### kb_chunks

| Column | Type | Constraints |
|--------|------|-------------|
| id | Integer | Primary key |
| repo_id | Integer | FK repos.id ON DELETE CASCADE |
| file_id | Integer | FK kb_files.id ON DELETE CASCADE |
| path | String(1024) | NOT NULL |
| commit_sha | String(40) | NOT NULL |
| start_line | Integer | NOT NULL |
| end_line | Integer | NOT NULL |
| content | Text | NOT NULL |
| content_tsv | TSVECTOR | Computed: `to_tsvector('english', content)`, persisted |
| updated_at | DateTime | server_default=now(), onupdate=now() |

**Index:** GIN on `content_tsv` (`ix_kb_chunks_content_tsv`)

---

## Error Handling

| Layer | Strategy |
|-------|----------|
| Global | `unhandled_exception_handler` catches all exceptions, logs with structlog, returns JSON 500 |
| Webhook signature | Returns 401 with "Invalid signature" on HMAC mismatch |
| Task processing | Catches exceptions per task, logs with structlog, returns 500 with file path in detail |
| Chat LLM errors | Returns graceful fallback message ("I encountered an error") with empty citations and "low" confidence |
| Chat empty KB | Detects via `has_any_chunks()`, returns guidance to sync a repo |
| Chat no results | Returns suggestion to rephrase with more specific terms |
| DB session | Auto-commit on success, auto-rollback on exception via `get_db_session()` generator |
| GitHub API 404 | Returns `{"status": "skipped", "reason": "not_found"}` (not treated as error) |
| Admin backfill | Per-repo error handling with status "error" and error message in response |

---

## Integration Points

| Integration | Protocol | Auth | Library |
|-------------|----------|------|---------|
| GitHub REST API | HTTPS | Bearer token (`GITHUB_TOKEN`) | httpx |
| GitHub Webhooks | HTTPS POST | HMAC-SHA256 (`GITHUB_WEBHOOK_SECRET`) | stdlib hmac |
| Google Cloud Tasks | gRPC | Service account (ADC) | google-cloud-tasks |
| Vertex AI (Gemini) | gRPC/HTTPS | Service account (ADC) | google-genai |
| PostgreSQL (Cloud SQL) | TCP/Unix socket | Connection string (`DATABASE_URL`) | asyncpg via SQLAlchemy |
| GCP Secret Manager | gRPC | Service account | Cloud Run native secret mounting |

---

## Architecture Decision Records

| ID | Decision | Rationale |
|----|----------|-----------|
| ADR-01 | Postgres FTS instead of vector embeddings | Reduces operational complexity and cost. No embedding pipeline or vector DB needed. Sufficient for code search where queries often match exact terms. |
| ADR-02 | Trigram (pg_trgm) as FTS fallback | Catches camelCase identifiers and file paths that FTS stemming destroys. Uses GIN index on `kb_files.path` for efficient similarity search. |
| ADR-03 | Three-tier retrieval (FTS-AND, FTS-OR, trigram) | AND semantics are precise but brittle. OR fallback catches partial matches. Trigram handles symbol/path queries. Layered approach balances precision and recall. |
| ADR-04 | Regex-based code boundary detection instead of tree-sitter AST | Simpler implementation with no native extension dependencies. Covers function/class boundaries for 7 languages. Falls back to line-based chunking for unsupported languages. |
| ADR-05 | Protocol-based dependency injection | `LLMClient` and `TaskQueue` are Python Protocols. Production uses GCP implementations; tests use in-memory doubles. No mocking framework needed for service tests. |
| ADR-06 | Lazy GCP SDK imports | `google-genai` and `google-cloud-tasks` are imported inside methods, not at module level. Allows the module to load without GCP SDKs installed (tests, local dev). |
| ADR-07 | Confidence from retrieval signals only | LLM self-assessment of confidence is unreliable. Confidence is derived from chunk count and ts_rank_cd scores. |
| ADR-08 | Mechanical citation verification | LLMs hallucinate citations. All LLM-returned citations are checked against the set of actually-retrieved chunk source strings. Unmatched citations are dropped silently. |
| ADR-09 | Webhook-to-queue decoupling | Webhook handler returns 202 immediately. Cloud Tasks handles async processing. Prevents GitHub's 10-second webhook timeout from causing failures. |
| ADR-10 | SHA-256 content hashing for dedup | Skips re-indexing when file content is unchanged between commits. Compares hash before deleting old chunks and creating new ones. |
| ADR-11 | google-genai SDK over deprecated vertexai SDK | `vertexai.generative_models` is deprecated (removal June 2026). `google-genai` is the official replacement with native async support. |
| ADR-12 | Structured JSON logging via structlog | Production uses JSON renderer for Cloud Logging compatibility. Development uses console renderer for readability. Single `configure_logging()` call controls both modes. |

---

## Limitations and Tradeoffs

| Limitation | Impact | Mitigation |
|------------|--------|------------|
| No semantic search | Conceptual queries ("how does auth work") may miss results if exact terms are absent | Trigram fallback on paths helps; OR-based FTS provides partial matching |
| No conversation memory | Each chat request is independent; no multi-turn context | Keeps architecture simple; sufficient for single-question lookups |
| Regex-based chunking (not AST) | May split code at incorrect boundaries for complex nested structures | Covers most common patterns for 7 languages; falls back to line-based for edge cases |
| No streaming responses | Users see a blank wait while LLM generates the full response | Deferred to v2; current latency is acceptable for Gemini Flash-Lite |
| Webhook-only ingestion | Missed webhooks cause silent data staleness | Idempotent design allows re-sync via admin endpoints; reconciliation deferred to v2 |
| Scale-to-zero cold starts | First request after idle period has higher latency | Acceptable for personal portfolio traffic patterns |
| 500 KB file size limit | Large generated files or data files are excluded from the knowledge base | Prevents bloated index; most source code files are well under this limit |
| Single-region deployment | No geographic redundancy | Sufficient for personal portfolio; Cloud SQL HA available if needed |
