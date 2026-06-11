#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# SihaLink — Deploy to Google Agent Runtime + Firebase Hosting
#
# Usage:
#   ./deploy.sh [environment] [project-id]
#   ./deploy.sh prod my-gcp-project
#   ./deploy.sh dev                        # uses current gcloud project
#
# Prerequisites:
#   gcloud CLI authenticated
#   docker running
#   firebase CLI installed (npm i -g firebase-tools)
#   google-adk installed  (pip install google-adk)
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

ENVIRONMENT="${1:-dev}"
PROJECT_ID="${2:-$(gcloud config get-value project 2>/dev/null)}"
REGION="us-central1"
AGENT_NAME="afya-voice-orchestrator"
IMAGE="gcr.io/${PROJECT_ID}/${AGENT_NAME}:latest"
SA_EMAIL="${AGENT_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"

# ── Colours ───────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
step()    { echo -e "\n${CYAN}▶ $*${NC}"; }
ok()      { echo -e "${GREEN}  ✓ $*${NC}"; }
warn()    { echo -e "${YELLOW}  ⚠ $*${NC}"; }
fail()    { echo -e "${RED}  ✗ $*${NC}"; exit 1; }

echo -e "${GREEN}"
echo "╔══════════════════════════════════════════════════════════╗"
echo "║          SihaLink — Deployment Script                  ║"
echo "╚══════════════════════════════════════════════════════════╝${NC}"
echo "  Project   : ${PROJECT_ID}"
echo "  Region    : ${REGION}"
echo "  Env       : ${ENVIRONMENT}"
echo "  Image     : ${IMAGE}"
echo ""

[[ -z "$PROJECT_ID" ]] && fail "PROJECT_ID is empty. Run: gcloud config set project YOUR_PROJECT"

# ─────────────────────────────────────────────────────────────────────────────
# STEP 1 — GCP auth
# ─────────────────────────────────────────────────────────────────────────────
step "1/8 — GCP authentication"
gcloud config set project "${PROJECT_ID}"
ok "Project set to ${PROJECT_ID}"

# ─────────────────────────────────────────────────────────────────────────────
# STEP 2 — Enable required APIs
# ─────────────────────────────────────────────────────────────────────────────
step "2/8 — Enabling GCP APIs"
APIS=(
  "run.googleapis.com"
  "secretmanager.googleapis.com"
  "containerregistry.googleapis.com"
  "aiplatform.googleapis.com"
  "firebase.googleapis.com"
)
for api in "${APIS[@]}"; do
  gcloud services enable "${api}" --quiet 2>/dev/null && ok "${api}" || warn "${api} (may already be enabled)"
done

# ─────────────────────────────────────────────────────────────────────────────
# STEP 3 — Secrets
# ─────────────────────────────────────────────────────────────────────────────
step "3/8 — Google Secret Manager"

REQUIRED_SECRETS=(
  "GEMINI_API_KEY"
  "GOOGLE_MAPS_API_KEY"
  "MONGODB_ATLAS_URI"
  "TELEGRAM_BOT_TOKEN"
  "FACILITY_TELEGRAM_ID"
)
OPTIONAL_SECRETS=(
  "VOYAGE_API_KEY"
  "TELEGRAM_WEBHOOK_URL"
)

for SECRET in "${REQUIRED_SECRETS[@]}"; do
  if gcloud secrets describe "${SECRET}" --project="${PROJECT_ID}" &>/dev/null; then
    ok "Secret ${SECRET} exists"
  else
    warn "Secret ${SECRET} missing — creating (you will be prompted)"
    printf "Enter value for %s: " "${SECRET}"
    read -rs SECRET_VALUE
    echo
    printf '%s' "${SECRET_VALUE}" | \
      gcloud secrets create "${SECRET}" --data-file=- --project="${PROJECT_ID}"
    ok "Secret ${SECRET} created"
  fi
done

for SECRET in "${OPTIONAL_SECRETS[@]}"; do
  if gcloud secrets describe "${SECRET}" --project="${PROJECT_ID}" &>/dev/null; then
    ok "Optional secret ${SECRET} exists"
  else
    warn "Optional secret ${SECRET} not set (Voyage AI / Telegram webhook — skipping)"
  fi
done

# ─────────────────────────────────────────────────────────────────────────────
# STEP 4 — Service account
# ─────────────────────────────────────────────────────────────────────────────
step "4/8 — Service account & IAM"

if ! gcloud iam service-accounts describe "${SA_EMAIL}" --project="${PROJECT_ID}" &>/dev/null; then
  gcloud iam service-accounts create "${AGENT_NAME}" \
    --display-name="SihaLink Orchestrator" \
    --project="${PROJECT_ID}"
  ok "Service account created: ${SA_EMAIL}"
else
  ok "Service account exists: ${SA_EMAIL}"
fi

ROLES=(
  "roles/secretmanager.secretAccessor"
  "roles/run.invoker"
  "roles/logging.logWriter"
  "roles/aiplatform.user"
  "roles/storage.objectViewer"
)
for ROLE in "${ROLES[@]}"; do
  gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
    --member="serviceAccount:${SA_EMAIL}" \
    --role="${ROLE}" \
    --quiet 2>/dev/null
  ok "Role ${ROLE} granted"
done

# ─────────────────────────────────────────────────────────────────────────────
# STEP 5 — Build & push container
# ─────────────────────────────────────────────────────────────────────────────
step "5/8 — Container build & push"

gcloud auth configure-docker gcr.io --quiet
docker build \
  --tag "${IMAGE}" \
  --label "git-commit=$(git rev-parse --short HEAD 2>/dev/null || echo unknown)" \
  --label "build-env=${ENVIRONMENT}" \
  .
ok "Image built: ${IMAGE}"

docker push "${IMAGE}"
ok "Image pushed to GCR"

# ─────────────────────────────────────────────────────────────────────────────
# STEP 6 — Deploy to Google Agent Runtime (Cloud Run)
# ─────────────────────────────────────────────────────────────────────────────
step "6/8 — Google Agent Runtime deployment"

# Build the --set-secrets flag from required secrets
SECRET_FLAGS=""
for SECRET in "${REQUIRED_SECRETS[@]}"; do
  SECRET_FLAGS="${SECRET_FLAGS} --set-secrets=${SECRET}=${SECRET}:latest"
done
for SECRET in "${OPTIONAL_SECRETS[@]}"; do
  if gcloud secrets describe "${SECRET}" --project="${PROJECT_ID}" &>/dev/null; then
    SECRET_FLAGS="${SECRET_FLAGS} --set-secrets=${SECRET}=${SECRET}:latest"
  fi
done

# Fallback: deploy directly to Cloud Run (used when ADK deploy fails or ADK is absent)
_deploy_cloud_run() {
  # shellcheck disable=SC2086
  gcloud run deploy "${AGENT_NAME}" \
    --image="${IMAGE}" \
    --region="${REGION}" \
    --platform=managed \
    --service-account="${SA_EMAIL}" \
    --port=8080 \
    --memory=2Gi \
    --cpu=2 \
    --min-instances=1 \
    --max-instances=10 \
    --timeout=300 \
    --set-env-vars="ENVIRONMENT=${ENVIRONMENT},NOTIFY_AGENT_URL=http://localhost:3001" \
    ${SECRET_FLAGS} \
    --allow-unauthenticated \
    --quiet
}

# Try ADK deploy first; fall back to Cloud Run deploy
if command -v adk &>/dev/null; then
  adk deploy cloud_run \
    --project="${PROJECT_ID}" \
    --region="${REGION}" \
    --service_name="${AGENT_NAME}" \
    agents/orchestrator \
    -- --service-account="${SA_EMAIL}" \
    2>/dev/null && ok "Deployed via ADK CLI" || {
      warn "ADK deploy failed — falling back to Cloud Run"
      _deploy_cloud_run
      ok "Deployed to Cloud Run"
    }
else
  warn "ADK CLI not found — deploying directly to Cloud Run"
  _deploy_cloud_run
  ok "Deployed to Cloud Run"
fi

AGENT_URL=$(gcloud run services describe "${AGENT_NAME}" \
  --region="${REGION}" --format="value(status.url)" 2>/dev/null || \
  echo "https://${REGION}-${PROJECT_ID}.run.app")
ok "Agent Runtime URL: ${AGENT_URL}"

# ─────────────────────────────────────────────────────────────────────────────
# STEP 7 — Frontend build & Firebase deploy
# ─────────────────────────────────────────────────────────────────────────────
step "7/8 — Frontend build & Firebase Hosting"

cd frontend

# Inject the Agent Runtime URL into the build
export VITE_API_URL="${AGENT_URL}"

npm install --legacy-peer-deps --silent

# Write production environment file
cat > src/environments/environment.prod.ts << ENVEOF
/**
 * Auto-generated by deploy.sh — do not edit manually.
 * Generated: $(date -u +"%Y-%m-%dT%H:%M:%SZ")
 */
export const environment = {
  production: true,
  apiUrl: "${AGENT_URL}",
  apiTimeout: 30000,
  enableLogging: false,
  features: {
    silentPandemicScan: true,
    followUpTracking: true,
    protocolSearch: true,
    chwRegistry: true,
    referralTracking: true,
    crossCountySpread: true,
    offlineSync: true,
    liveAudio: true,
    tts: true,
  },
  surveillanceIntervalMs: 21600000,
  silentPandemicWeeks: 4,
  followUpPollIntervalMs: 300000,
  gateTimeoutMs: 60000,
};
ENVEOF

npm run build
ok "Frontend built (dist/)"

firebase deploy --only hosting --project="${PROJECT_ID}"
FIREBASE_URL="https://${PROJECT_ID}.web.app"
ok "Frontend deployed: ${FIREBASE_URL}"

cd ..

# ─────────────────────────────────────────────────────────────────────────────
# STEP 8 — Health check
# ─────────────────────────────────────────────────────────────────────────────
step "8/8 — Health verification"

sleep 5
HTTP=$(curl -s -o /dev/null -w "%{http_code}" "${AGENT_URL}/health" 2>/dev/null || echo "000")
if [[ "$HTTP" == "200" ]]; then
  ok "Orchestrator /health → 200 OK"
else
  warn "Orchestrator /health returned ${HTTP} (may still be starting)"
fi

# ─────────────────────────────────────────────────────────────────────────────
# Summary
# ─────────────────────────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}╔══════════════════════════════════════════════════════════╗"
echo -e "║              Deployment Complete ✅                     ║"
echo -e "╚══════════════════════════════════════════════════════════╝${NC}"
echo ""
echo "  📱 Frontend          : ${FIREBASE_URL}"
echo "  🤖 Agent Runtime     : ${AGENT_URL}"
echo "  🔍 Health check      : ${AGENT_URL}/health"
echo ""
echo "  Useful commands:"
echo "    Logs    : gcloud run services logs read ${AGENT_NAME} --region=${REGION} --follow"
echo "    Secrets : gcloud secrets list --project=${PROJECT_ID}"
echo "    Rollback: gcloud run services update-traffic ${AGENT_NAME} --to-revisions=PREV=100"
echo ""
