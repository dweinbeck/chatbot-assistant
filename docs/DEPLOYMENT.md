# Deployment Guide

## Overview

Chatbot Assistant deploys to Google Cloud Run as a containerized Python application backed by Cloud SQL (PostgreSQL 16). The CI/CD pipeline runs on GitHub Actions: pushes to `main` trigger lint, test, Docker build, and automatic deployment. Infrastructure provisioning is handled by a one-time setup script (`scripts/setup-gcp.sh`). Manual deployments can be performed via `scripts/deploy.sh`.

---

## Environment Variables

### Application Settings

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `DATABASE_URL` | Yes | `postgresql+asyncpg://postgres:postgres@localhost:5432/chatbot` | PostgreSQL connection string (asyncpg driver) |
| `APP_NAME` | No | `chatbot-assistant` | Application name used in FastAPI title |
| `DEBUG` | No | `false` | Enable debug mode (uses console logging instead of JSON) |
| `LOG_LEVEL` | No | `INFO` | Root log level (DEBUG, INFO, WARNING, ERROR) |
| `HOST` | No | `0.0.0.0` | Server bind host |
| `PORT` | No | `8080` | Server bind port |

### GitHub Integration

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `GITHUB_WEBHOOK_SECRET` | Yes | `dev-secret` | HMAC secret for webhook signature verification |
| `GITHUB_TOKEN` | Yes (prod) | `""` | GitHub personal access token for API calls |

### GCP Integration

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `GCP_PROJECT` | Yes (prod) | `""` | GCP project ID. When empty, uses in-memory test doubles. |
| `GCP_LOCATION` | No | `us-central1` | GCP region for Vertex AI and Cloud Tasks |
| `GEMINI_MODEL` | No | `gemini-2.5-flash-lite` | Gemini model ID for LLM generation |
| `CLOUD_TASKS_QUEUE` | No | `indexing` | Cloud Tasks queue name |
| `TASK_HANDLER_BASE_URL` | Yes (prod) | `http://localhost:8080` | Base URL for Cloud Tasks HTTP targets (Cloud Run service URL) |
| `CORS_ORIGINS` | No | `""` | Comma-separated allowed CORS origins (empty = no CORS) |

### GCP Secrets (via Secret Manager)

In production, the following are mounted from Secret Manager into environment variables:

| Secret Name | Maps To |
|-------------|---------|
| `database-url` | `DATABASE_URL` |
| `github-webhook-secret` | `GITHUB_WEBHOOK_SECRET` |
| `github-token` | `GITHUB_TOKEN` |

### GitHub Actions Variables

These are configured in the GitHub repository settings (Settings > Secrets and variables > Actions > Variables):

| Variable | Description |
|----------|-------------|
| `GCP_PROJECT_ID` | GCP project ID |
| `WIF_PROVIDER` | Workload Identity Federation provider resource name |
| `WIF_SERVICE_ACCOUNT` | CI deployer service account email |
| `CLOUD_SQL_INSTANCE` | Cloud SQL connection name |
| `TASK_HANDLER_BASE_URL` | Cloud Run service URL (set after first deployment) |

---

## Local Development

### Prerequisites

- Python 3.12
- [uv](https://docs.astral.sh/uv/) (package manager)
- Docker (for local PostgreSQL)

### Setup

```bash
# Install dependencies
uv sync --frozen --dev

# Start PostgreSQL
docker compose up -d

# Configure environment
cp .env.example .env
# Edit .env as needed

# Run database migrations
uv run alembic upgrade head

# Start development server with auto-reload
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8080
```

### Running Tests

```bash
# Full test suite
uv run pytest tests/

# Lint
uv run ruff check .

# Format check
uv run ruff format --check .
```

Note: Tests use in-memory test doubles (no database or GCP services required). The `conftest.py` overrides FastAPI dependencies with mock DB sessions, `InMemoryTaskQueue`, and `InMemoryLLMClient`.

---

## Docker Build

### Local Build

```bash
docker build -t chatbot-assistant .
```

### Run Container Locally

```bash
docker run -p 8080:8080 \
  -e DATABASE_URL=postgresql+asyncpg://postgres:postgres@host.docker.internal:5432/chatbot \
  chatbot-assistant
```

### Multi-Stage Build Details

The Dockerfile uses a two-stage build:

1. **Builder stage** (`python:3.12-slim`): Installs uv, copies dependency files, runs `uv sync --frozen --no-dev`, copies application code, syncs again to install the project.
2. **Runtime stage** (`python:3.12-slim`): Copies the virtual environment and application code from the builder. Adds venv to PATH. Runs `scripts/start.sh` which performs migrations then starts uvicorn.

---

## Cloud Build and Deploy

### CI/CD Pipeline (GitHub Actions)

```
Push to main
    │
    ├── check job (runs on all pushes + PRs)
    │   ├── Checkout code
    │   ├── Setup uv + Python 3.12
    │   ├── Install dev dependencies
    │   ├── Ruff lint
    │   ├── Ruff format check
    │   └── pytest
    │
    └── deploy job (only on push to main, after check passes)
        ├── Checkout code
        ├── Authenticate to GCP (Workload Identity Federation)
        ├── Setup Google Cloud SDK
        ├── Configure Docker for Artifact Registry
        ├── Build Docker image (tagged with commit SHA + latest)
        ├── Push image to Artifact Registry
        └── Deploy to Cloud Run
            ├── Image: <region>-docker.pkg.dev/<project>/<repo>/chatbot-assistant:<sha>
            ├── Port: 8080
            ├── Memory: 512Mi
            ├── CPU: 1
            ├── Min instances: 0 (scale-to-zero)
            ├── Max instances: 4
            ├── Concurrency: 80
            ├── Timeout: 300s
            ├── Secrets: DATABASE_URL, GITHUB_WEBHOOK_SECRET, GITHUB_TOKEN
            └── Env vars: GCP_PROJECT, GCP_LOCATION, CLOUD_TASKS_QUEUE,
                          GEMINI_MODEL, TASK_HANDLER_BASE_URL, CORS_ORIGINS
```

### One-Time GCP Infrastructure Setup

Run `scripts/setup-gcp.sh` once per project. It provisions:

1. Enables required GCP APIs (Cloud Run, Cloud SQL, Secret Manager, Artifact Registry, IAM, Cloud Tasks, Vertex AI).
2. Creates Cloud SQL instance (Postgres 15, db-f1-micro tier) with database `chatbot` and user `chatbot`.
3. Creates Artifact Registry Docker repository.
4. Creates Cloud Run service account with roles: `cloudsql.client`, `cloudtasks.enqueuer`, `aiplatform.user`.
5. Creates secrets in Secret Manager (database-url, github-webhook-secret, github-token).
6. Grants secret accessor role to service account.
7. Creates Workload Identity Federation pool and OIDC provider for GitHub Actions.
8. Creates CI deployer service account with roles: `run.admin`, `artifactregistry.writer`, `iam.serviceAccountUser`.
9. Binds WIF pool to CI deployer service account.

```bash
export PROJECT_ID=my-gcp-project
export GITHUB_ORG=myorg
export GITHUB_REPO=chatbot-assistant
./scripts/setup-gcp.sh
```

### Manual Deployment

For deployments outside CI/CD:

```bash
export PROJECT_ID=my-gcp-project
export TASK_HANDLER_BASE_URL=https://chatbot-assistant-abc123-uc.a.run.app
./scripts/deploy.sh
```

---

## Container Startup

The container entrypoint (`scripts/start.sh`) performs:

1. **Database migrations** with retry logic (up to 5 attempts, 3-second delay between retries).
2. **Application server** start via `uvicorn app.main:app --host 0.0.0.0 --port 8080`.

---

## Rollback

### Cloud Run Revision Rollback

Cloud Run maintains revision history. To roll back to a previous revision:

```bash
# List revisions
gcloud run revisions list --service=chatbot-assistant --region=us-central1

# Route 100% traffic to a previous revision
gcloud run services update-traffic chatbot-assistant \
  --to-revisions=chatbot-assistant-<revision-id>=100 \
  --region=us-central1
```

### Database Migration Rollback

```bash
# Downgrade one revision
uv run alembic downgrade -1

# Downgrade to a specific revision
uv run alembic downgrade <revision-id>
```

Note: The initial migration (`001`) drops all tables on downgrade and removes the pg_trgm extension. Use with caution in production.

---

## Troubleshooting

| Symptom | Likely Cause | Resolution |
|---------|-------------|------------|
| Health check returns 500 | Database not reachable | Verify `DATABASE_URL` is correct. Check Cloud SQL instance status. Ensure Cloud SQL proxy or connector is working. |
| Webhook returns 401 | Signature mismatch | Verify `GITHUB_WEBHOOK_SECRET` matches the secret configured in the GitHub webhook settings. |
| Tasks never execute | Cloud Tasks misconfigured | Verify `TASK_HANDLER_BASE_URL` is set to the Cloud Run service URL. Check Cloud Tasks queue exists in the correct region. |
| Chat returns "No repositories indexed" | Empty knowledge base | Use `POST /admin/sync-repo` to index a repository. |
| Chat returns LLM error fallback | Gemini API failure | Check `GCP_PROJECT` and `GCP_LOCATION` are set. Verify service account has `aiplatform.user` role. Check Vertex AI API is enabled. |
| Migrations fail on startup | Database not ready | The start script retries 5 times with 3s delay. If Cloud SQL is slow to start, increase retry count or delay. |
| Docker build fails at uv sync | Lock file mismatch | Run `uv lock` locally and commit `uv.lock`. The `--frozen` flag requires an exact lock file match. |
| GitHub API returns 403 | Rate limit or token issue | Verify `GITHUB_TOKEN` is set and has `repo` scope for public repos. Check GitHub API rate limit status. |
| Deploy fails with WIF auth error | WIF misconfiguration | Verify `WIF_PROVIDER` and `WIF_SERVICE_ACCOUNT` GitHub variables match the setup script output. IAM changes may take up to 5 minutes to propagate. |
| Cold start timeout on webhooks | Scale-to-zero latency | Consider setting `min-instances=1` for the Cloud Run service to avoid cold starts on webhook delivery. |
