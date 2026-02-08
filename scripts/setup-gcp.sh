#!/usr/bin/env bash
set -euo pipefail

# =============================================================================
# GCP Infrastructure Setup for chatbot-assistant
# One-time provisioning script. Run once per project.
# =============================================================================

# --- Configuration (edit these) ---
PROJECT_ID="${PROJECT_ID:?PROJECT_ID must be set}"
REGION="${REGION:-us-central1}"
GITHUB_ORG="${GITHUB_ORG:?GITHUB_ORG must be set}"
GITHUB_REPO="${GITHUB_REPO:?GITHUB_REPO must be set}"

SERVICE="chatbot-assistant"
SERVICE_ACCOUNT="${SERVICE}@${PROJECT_ID}.iam.gserviceaccount.com"
CI_SERVICE_ACCOUNT="ci-deployer@${PROJECT_ID}.iam.gserviceaccount.com"

# --- Confirmation prompt ---
echo "=== GCP Infrastructure Setup ==="
echo "Project:     ${PROJECT_ID}"
echo "Region:      ${REGION}"
echo "GitHub Org:  ${GITHUB_ORG}"
echo "GitHub Repo: ${GITHUB_REPO}"
echo ""
echo "This will create GCP resources in ${PROJECT_ID}. Continue? [y/N]"
read -r CONFIRM
if [[ "${CONFIRM}" != "y" && "${CONFIRM}" != "Y" ]]; then
  echo "Aborted."
  exit 0
fi

# --- 1. Enable required APIs ---
echo ""
echo "=== Enabling GCP APIs ==="
gcloud services enable \
  run.googleapis.com \
  sqladmin.googleapis.com \
  secretmanager.googleapis.com \
  artifactregistry.googleapis.com \
  iam.googleapis.com \
  cloudtasks.googleapis.com \
  aiplatform.googleapis.com \
  --project="${PROJECT_ID}"
echo "APIs enabled."

# --- 2. Create Cloud SQL instance, database, and user ---
echo ""
echo "=== Creating Cloud SQL Instance ==="
ROOT_PASSWORD=$(openssl rand -base64 18)
gcloud sql instances create "${SERVICE}" \
  --database-version=POSTGRES_15 \
  --tier=db-f1-micro \
  --region="${REGION}" \
  --root-password="${ROOT_PASSWORD}" \
  --project="${PROJECT_ID}"
echo "Cloud SQL instance created. Root password: ${ROOT_PASSWORD}"

echo ""
echo "=== Creating Database ==="
gcloud sql databases create chatbot \
  --instance="${SERVICE}" \
  --project="${PROJECT_ID}"
echo "Database 'chatbot' created."

echo ""
echo "=== Creating Database User ==="
echo "Enter password for database user 'chatbot':"
read -s -r -p "Password: " DB_PASSWORD
echo ""
gcloud sql users create chatbot \
  --instance="${SERVICE}" \
  --password="${DB_PASSWORD}" \
  --project="${PROJECT_ID}"
echo "Database user 'chatbot' created."

CLOUD_SQL_INSTANCE=$(gcloud sql instances describe "${SERVICE}" \
  --format='value(connectionName)' \
  --project="${PROJECT_ID}")
echo "Connection name: ${CLOUD_SQL_INSTANCE}"
echo ""
echo "DATABASE_URL format:"
echo "  postgresql+asyncpg://chatbot:<password>@/chatbot?host=/cloudsql/${CLOUD_SQL_INSTANCE}"

# --- 3. Create Artifact Registry repository ---
echo ""
echo "=== Creating Artifact Registry Repository ==="
gcloud artifacts repositories create "${SERVICE}" \
  --repository-format=docker \
  --location="${REGION}" \
  --description="Chatbot assistant Docker images" \
  --project="${PROJECT_ID}"
echo "Artifact Registry repository created."

# --- 4. Create Cloud Run service account ---
echo ""
echo "=== Creating Cloud Run Service Account ==="
gcloud iam service-accounts create "${SERVICE}" \
  --display-name="Chatbot Assistant Cloud Run" \
  --project="${PROJECT_ID}"

gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
  --member="serviceAccount:${SERVICE_ACCOUNT}" \
  --role="roles/cloudsql.client"

gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
  --member="serviceAccount:${SERVICE_ACCOUNT}" \
  --role="roles/cloudtasks.enqueuer"

gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
  --member="serviceAccount:${SERVICE_ACCOUNT}" \
  --role="roles/aiplatform.user"
echo "Cloud Run service account created with roles: cloudsql.client, cloudtasks.enqueuer, aiplatform.user"

# --- 5. Create secrets in Secret Manager ---
echo ""
echo "=== Creating Secrets ==="

echo "Enter DATABASE_URL (e.g., postgresql+asyncpg://chatbot:<pass>@/chatbot?host=/cloudsql/${CLOUD_SQL_INSTANCE}):"
read -s -r -p "DATABASE_URL: " SECRET_DATABASE_URL
echo ""
echo -n "${SECRET_DATABASE_URL}" | gcloud secrets create database-url \
  --data-file=- \
  --project="${PROJECT_ID}"

echo "Enter GITHUB_WEBHOOK_SECRET:"
read -s -r -p "GITHUB_WEBHOOK_SECRET: " SECRET_WEBHOOK
echo ""
echo -n "${SECRET_WEBHOOK}" | gcloud secrets create github-webhook-secret \
  --data-file=- \
  --project="${PROJECT_ID}"

echo "Enter GITHUB_TOKEN:"
read -s -r -p "GITHUB_TOKEN: " SECRET_TOKEN
echo ""
echo -n "${SECRET_TOKEN}" | gcloud secrets create github-token \
  --data-file=- \
  --project="${PROJECT_ID}"
echo "Secrets created."

# --- 6. Grant secret access to Cloud Run service account ---
echo ""
echo "=== Granting Secret Access ==="
for secret in database-url github-webhook-secret github-token; do
  gcloud secrets add-iam-policy-binding "${secret}" \
    --member="serviceAccount:${SERVICE_ACCOUNT}" \
    --role="roles/secretmanager.secretAccessor" \
    --project="${PROJECT_ID}"
done
echo "Secret access granted."

# --- 7. Create Workload Identity Pool and OIDC Provider ---
echo ""
echo "=== Creating Workload Identity Federation ==="
gcloud iam workload-identity-pools create github \
  --location="global" \
  --display-name="GitHub Actions Pool" \
  --project="${PROJECT_ID}"

gcloud iam workload-identity-pools providers create-oidc github-provider \
  --location="global" \
  --workload-identity-pool="github" \
  --display-name="GitHub Actions Provider" \
  --attribute-mapping="google.subject=assertion.sub,attribute.actor=assertion.actor,attribute.repository=assertion.repository,attribute.repository_owner=assertion.repository_owner" \
  --attribute-condition="assertion.repository_owner == '${GITHUB_ORG}'" \
  --issuer-uri="https://token.actions.githubusercontent.com" \
  --project="${PROJECT_ID}"
echo "WIF pool and provider created."

# --- 8. Create CI deployer service account ---
echo ""
echo "=== Creating CI Deployer Service Account ==="
gcloud iam service-accounts create ci-deployer \
  --display-name="CI/CD Deployer" \
  --project="${PROJECT_ID}"

gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
  --member="serviceAccount:${CI_SERVICE_ACCOUNT}" \
  --role="roles/run.admin"

gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
  --member="serviceAccount:${CI_SERVICE_ACCOUNT}" \
  --role="roles/artifactregistry.writer"

gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
  --member="serviceAccount:${CI_SERVICE_ACCOUNT}" \
  --role="roles/iam.serviceAccountUser"
echo "CI deployer service account created with roles: run.admin, artifactregistry.writer, iam.serviceAccountUser"

# --- 9. Bind WIF pool to CI deployer service account ---
echo ""
echo "=== Binding WIF to CI Deployer ==="
POOL_ID=$(gcloud iam workload-identity-pools describe github \
  --location="global" \
  --format="value(name)" \
  --project="${PROJECT_ID}")

gcloud iam service-accounts add-iam-policy-binding "${CI_SERVICE_ACCOUNT}" \
  --role="roles/iam.workloadIdentityUser" \
  --member="principalSet://iam.googleapis.com/${POOL_ID}/attribute.repository/${GITHUB_ORG}/${GITHUB_REPO}" \
  --project="${PROJECT_ID}"
echo "WIF binding created."

# --- 10. Summary ---
WIF_PROVIDER=$(gcloud iam workload-identity-pools providers describe github-provider \
  --location="global" \
  --workload-identity-pool="github" \
  --format="value(name)" \
  --project="${PROJECT_ID}")

echo ""
echo "============================================="
echo "=== GCP Infrastructure Setup Complete ==="
echo "============================================="
echo ""
echo "Resources created:"
echo "  Cloud SQL instance:    ${SERVICE} (${CLOUD_SQL_INSTANCE})"
echo "  Database:              chatbot"
echo "  Database user:         chatbot"
echo "  Artifact Registry:     ${REGION}-docker.pkg.dev/${PROJECT_ID}/${SERVICE}"
echo "  Service account:       ${SERVICE_ACCOUNT}"
echo "  CI deployer:           ${CI_SERVICE_ACCOUNT}"
echo "  Secrets:               database-url, github-webhook-secret, github-token"
echo "  WIF pool:              github"
echo "  WIF provider:          github-provider"
echo ""
echo "Configure these GitHub repository variables (Settings > Secrets and variables > Actions > Variables):"
echo "  GCP_PROJECT_ID:        ${PROJECT_ID}"
echo "  WIF_PROVIDER:          ${WIF_PROVIDER}"
echo "  WIF_SERVICE_ACCOUNT:   ${CI_SERVICE_ACCOUNT}"
echo "  CLOUD_SQL_INSTANCE:    ${CLOUD_SQL_INSTANCE}"
echo "  TASK_HANDLER_BASE_URL: (set after first deployment -- use the Cloud Run service URL)"
echo ""
echo "Note: IAM changes may take up to 5 minutes to propagate."
