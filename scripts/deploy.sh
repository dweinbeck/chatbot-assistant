#!/usr/bin/env bash
set -euo pipefail

# =============================================================================
# Manual deployment script for chatbot-assistant
# Builds, pushes, and deploys to Cloud Run.
# =============================================================================

# --- Configuration ---
PROJECT_ID="${PROJECT_ID:?PROJECT_ID must be set}"
REGION="${REGION:-us-central1}"
TAG="${TAG:-latest}"
TASK_HANDLER_BASE_URL="${TASK_HANDLER_BASE_URL:-}"

SERVICE="chatbot-assistant"
REPO="chatbot-assistant"
IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO}/${SERVICE}"
SERVICE_ACCOUNT="${SERVICE}@${PROJECT_ID}.iam.gserviceaccount.com"
CLOUD_SQL_INSTANCE=$(gcloud sql instances describe "${SERVICE}" \
  --format='value(connectionName)' \
  --project="${PROJECT_ID}")
SHA=$(git rev-parse --short HEAD)

echo "=== Deploying ${SERVICE} ==="
echo "Project:  ${PROJECT_ID}"
echo "Region:   ${REGION}"
echo "Image:    ${IMAGE}:${SHA}"
echo "Tag:      ${TAG}"
echo ""

# --- Configure Docker auth ---
echo "=== Configuring Docker Authentication ==="
gcloud auth configure-docker "${REGION}-docker.pkg.dev" --quiet

# --- Build Docker image ---
echo "=== Building Docker Image ==="
docker build \
  -t "${IMAGE}:${SHA}" \
  -t "${IMAGE}:${TAG}" \
  .

# --- Push Docker image ---
echo "=== Pushing Docker Image ==="
docker push "${IMAGE}:${SHA}"
docker push "${IMAGE}:${TAG}"

# --- Deploy to Cloud Run ---
echo "=== Deploying to Cloud Run ==="
gcloud run deploy "${SERVICE}" \
  --image="${IMAGE}:${SHA}" \
  --region="${REGION}" \
  --platform=managed \
  --port=8080 \
  --memory=512Mi \
  --cpu=1 \
  --min-instances=0 \
  --max-instances=4 \
  --concurrency=80 \
  --timeout=300 \
  --ingress=internal-and-cloud-load-balancing \
  --service-account="${SERVICE_ACCOUNT}" \
  --add-cloudsql-instances="${CLOUD_SQL_INSTANCE}" \
  --set-secrets="DATABASE_URL=database-url:latest,GITHUB_WEBHOOK_SECRET=github-webhook-secret:latest,GITHUB_TOKEN=github-token:latest,API_KEY=chatbot-api-key:latest" \
  --set-env-vars="GCP_PROJECT=${PROJECT_ID},GCP_LOCATION=${REGION},CLOUD_TASKS_QUEUE=indexing,GEMINI_MODEL=gemini-2.5-flash-lite,TASK_HANDLER_BASE_URL=${TASK_HANDLER_BASE_URL},CORS_ORIGINS=https://dan-weinbeck.com" \
  --allow-unauthenticated \
  --project="${PROJECT_ID}"

# --- Print service URL ---
echo ""
echo "=== Deployment Complete ==="
SERVICE_URL=$(gcloud run services describe "${SERVICE}" \
  --region="${REGION}" \
  --format='value(status.url)' \
  --project="${PROJECT_ID}")
echo "Service URL: ${SERVICE_URL}"

# --- Warn if TASK_HANDLER_BASE_URL is empty ---
if [[ -z "${TASK_HANDLER_BASE_URL}" ]]; then
  echo ""
  echo "=========================================="
  echo "  ACTION REQUIRED: TASK_HANDLER_BASE_URL  "
  echo "=========================================="
  echo ""
  echo "TASK_HANDLER_BASE_URL was not set. Cloud Tasks will not be able to"
  echo "deliver tasks back to the service until this is configured."
  echo ""
  echo "Set it to the service URL printed above and re-deploy, or run:"
  echo "  gcloud run services update ${SERVICE} \\"
  echo "    --region=${REGION} \\"
  echo "    --set-env-vars=TASK_HANDLER_BASE_URL=${SERVICE_URL}"
  echo ""
fi
