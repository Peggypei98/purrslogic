#!/usr/bin/env bash
# Deploy Purrslogic to Google Cloud Run.
#
# Prerequisites:
#   gcloud auth login
#   gcloud config set project YOUR_PROJECT_ID
#
# Usage:
#   export GCP_PROJECT_ID=your-project
#   export GCP_REGION=us-central1
#   export SERVICE_NAME=purrslogic
#   ./scripts/deploy-cloud-run.sh
#
# After deploy, add OAuth redirect URI in Google Cloud Console:
#   https://SERVICE_URL/api/v1/calendar/oauth/callback
# Then update the service env GOOGLE_OAUTH_REDIRECT_URI to match.

set -euo pipefail

PROJECT_ID="${GCP_PROJECT_ID:-}"
REGION="${GCP_REGION:-us-central1}"
SERVICE="${SERVICE_NAME:-purrslogic}"
IMAGE="gcr.io/${PROJECT_ID}/${SERVICE}"

if [[ -z "${PROJECT_ID}" ]]; then
  echo "Set GCP_PROJECT_ID (your Google Cloud project id)."
  exit 1
fi

if [[ ! -f .env ]]; then
  echo "Missing purrslogic-backend/.env — need at least MONGODB_URL and GEMINI_API_KEY."
  exit 1
fi

# shellcheck disable=SC1091
set -a
source .env
set +a

if [[ -z "${MONGODB_URL:-}" && -z "${MONGODB_URI:-}" ]]; then
  echo "MONGODB_URL or MONGODB_URI required in .env"
  exit 1
fi

if [[ -z "${GEMINI_API_KEY:-}" && -z "${GOOGLE_API_KEY:-}" ]]; then
  echo "GEMINI_API_KEY or GOOGLE_API_KEY required in .env"
  exit 1
fi

echo "==> Enabling APIs..."
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com \
  secretmanager.googleapis.com storage.googleapis.com \
  --project="${PROJECT_ID}"

echo "==> Building image (Cloud Build)..."
gcloud builds submit --tag "${IMAGE}" --project="${PROJECT_ID}" .

ENV_VARS="MONGODB_URL=${MONGODB_URL:-${MONGODB_URI}}"
if [[ -n "${GEMINI_API_KEY:-}" ]]; then
  ENV_VARS="${ENV_VARS},GEMINI_API_KEY=${GEMINI_API_KEY}"
fi
if [[ -n "${GOOGLE_API_KEY:-}" ]]; then
  ENV_VARS="${ENV_VARS},GOOGLE_API_KEY=${GOOGLE_API_KEY}"
fi

GCS_BUCKET="${GCS_UPLOAD_BUCKET:-purrslogic-health-uploads}"
ENV_VARS="${ENV_VARS},GCS_UPLOAD_BUCKET=${GCS_BUCKET}"

echo "==> Ensuring GCS upload bucket..."
if ! gcloud storage buckets describe "gs://${GCS_BUCKET}" --project="${PROJECT_ID}" &>/dev/null; then
  gcloud storage buckets create "gs://${GCS_BUCKET}" \
    --project="${PROJECT_ID}" \
    --location="${REGION}" \
    --uniform-bucket-level-access
fi
CORS_FILE="$(cd "$(dirname "$0")/.." && pwd)/config/gcs-cors.json"
if [[ -f "${CORS_FILE}" ]]; then
  gcloud storage buckets update "gs://${GCS_BUCKET}" \
    --project="${PROJECT_ID}" \
    --cors-file="${CORS_FILE}"
fi
PROJECT_NUMBER="$(gcloud projects describe "${PROJECT_ID}" --format='value(projectNumber)')"
RUN_SA="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"
gcloud storage buckets add-iam-policy-binding "gs://${GCS_BUCKET}" \
  --project="${PROJECT_ID}" \
  --member="serviceAccount:${RUN_SA}" \
  --role="roles/storage.objectAdmin" \
  --quiet >/dev/null || true
gcloud iam service-accounts add-iam-policy-binding "${RUN_SA}" \
  --project="${PROJECT_ID}" \
  --member="serviceAccount:${RUN_SA}" \
  --role="roles/iam.serviceAccountTokenCreator" \
  --quiet >/dev/null || true

EXISTING_URL="$(gcloud run services describe "${SERVICE}" \
  --region "${REGION}" --project "${PROJECT_ID}" \
  --format='value(status.url)' 2>/dev/null || true)"
if [[ -n "${EXISTING_URL}" ]]; then
  ENV_VARS="${ENV_VARS},GOOGLE_OAUTH_REDIRECT_URI=${EXISTING_URL}/api/v1/calendar/oauth/callback"
fi

SECRET_ARGS=()
if [[ -f config/calendar-client-secret.json ]]; then
  echo "==> Mounting calendar OAuth client secret..."
  SECRET_ARGS+=(--set-secrets="GOOGLE_OAUTH_CLIENT_JSON=calendar-oauth-client:latest")
  if ! gcloud secrets describe calendar-oauth-client --project="${PROJECT_ID}" &>/dev/null; then
    gcloud secrets create calendar-oauth-client --project="${PROJECT_ID}" \
      --data-file=config/calendar-client-secret.json
  else
    gcloud secrets versions add calendar-oauth-client --project="${PROJECT_ID}" \
      --data-file=config/calendar-client-secret.json
  fi
  PROJECT_NUMBER="$(gcloud projects describe "${PROJECT_ID}" --format='value(projectNumber)')"
  RUN_SA="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"
  gcloud secrets add-iam-policy-binding calendar-oauth-client \
    --project="${PROJECT_ID}" \
    --member="serviceAccount:${RUN_SA}" \
    --role="roles/secretmanager.secretAccessor" \
    --quiet >/dev/null || true
fi

echo "==> Deploying to Cloud Run..."
gcloud run deploy "${SERVICE}" \
  --image "${IMAGE}" \
  --platform managed \
  --region "${REGION}" \
  --project "${PROJECT_ID}" \
  --allow-unauthenticated \
  --port 8080 \
  --memory 8Gi \
  --cpu 4 \
  --timeout 900 \
  --max-instances 5 \
  --set-env-vars "${ENV_VARS}" \
  "${SECRET_ARGS[@]}"

SERVICE_URL="$(gcloud run services describe "${SERVICE}" \
  --region "${REGION}" --project "${PROJECT_ID}" \
  --format='value(status.url)')"

echo ""
echo "Deployed: ${SERVICE_URL}"
echo "Health UI: ${SERVICE_URL}/health"
echo ""
echo "Next steps:"
echo "  1. Google Cloud Console → OAuth client → add redirect URI:"
echo "     ${SERVICE_URL}/api/v1/calendar/oauth/callback"
echo "  2. Update Cloud Run env GOOGLE_OAUTH_REDIRECT_URI to that URL:"
echo "     gcloud run services update ${SERVICE} --region ${REGION} \\"
echo "       --update-env-vars GOOGLE_OAUTH_REDIRECT_URI=${SERVICE_URL}/api/v1/calendar/oauth/callback"
