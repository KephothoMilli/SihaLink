#!/usr/bin/env bash
# =============================================================================
# SihaLink — Google Cloud Run deploy script
#
# Usage:
#   ./deploy/deploy.sh [--project PROJECT_ID] [--region REGION] [--tag TAG]
#
# Examples:
#   ./deploy/deploy.sh
#   ./deploy/deploy.sh --project kephothoagenticai --region us-central1
#   ./deploy/deploy.sh --tag v1.2.3
#
# Prerequisites:
#   gcloud CLI authenticated  (gcloud auth login)
#   ADC configured            (gcloud auth application-default login)
#   Docker running
#   firebase CLI (npm i -g firebase-tools)  — only for frontend deploy
# =============================================================================
set -euo pipefail

# ── Defaults ──────────────────────────────────────────────────────────────────
PROJECT_ID="kephothoagenticai"
REGION="us-central1"
SERVICE_NAME="sihalink-orchestrator"
SA_NAME="${SERVICE_NAME}"
SA_EMAIL="${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"
REGISTRY="gcr.io"
TAG="${TAG:-$(git rev-parse --short HEAD 2>/dev/null || echo latest)}"
IMAGE="${REGISTRY}/${PROJECT_ID}/${SERVICE_NAME}:${TAG}"
IMAGE_LATEST="${REGISTRY}/${PROJECT_ID}/${SERVICE_NAME}:latest"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "${SCRIPT_DIR}")"

# ── Parse args ────────────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
  case "$1" in
    --project) PROJECT_ID="$2"; shift 2 ;;
    --region)  REGION="$2";     shift 2 ;;
    --tag)     TAG="$2";        shift 2 ;;
    *) echo "Unknown arg: $1"; exit 1 ;;
  esac
done

# ── Colors ────────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'
step()  { echo -e "\n${CYAN}${BOLD}▶ $*${NC}"; }
ok()    { echo -e "  ${GREEN}✓ $*${NC}"; }
warn()  { echo -e "  ${YELLOW}⚠ $*${NC}"; }
fail()  { echo -e "  ${RED}✗ $*${NC}"; exit 1; }

# ── Banner ────────────────────────────────────────────────────────────────────
echo -e "\n${GREEN}${BOLD}"
echo "  ███████╗██╗██╗  ██╗ █████╗ ██╗     ██╗███╗   ██╗██╗  ██╗"
echo "  ██╔════╝██║██║  ██║██╔══██╗██║     ██║████╗  ██║██║ ██╔╝"
echo "  ███████╗██║███████║███████║██║     ██║██╔██╗ ██║█████╔╝ "
echo "  ╚════██║██║██╔══██║██╔══██║██║     ██║██║╚██╗██║██╔═██╗ "
echo "  ███████║██║██║  ██║██║  ██║███████╗██║██║ ╚████║██║  ██╗"
echo "  ╚══════╝╚═╝╚═╝  ╚═╝╚═╝  ╚═╝╚══════╝╚═╝╚═╝  ╚═══╝╚═╝  ╚═╝"
echo -e "${NC}"
printf "  %-18s %s\n" "Project:"   "${PROJECT_ID}"
printf "  %-18s %s\n" "Region:"    "${REGION}"
printf "  %-18s %s\n" "Service:"   "${SERVICE_NAME}"
printf "  %-18s %s\n" "Image:"     "${IMAGE}"
printf "  %-18s %s\n" "Git tag:"   "${TAG}"
echo ""

cd "${ROOT_DIR}"

# ─────────────────────────────────────────────────────────────────────────────
# STEP 1 — Authenticate & set project
# ─────────────────────────────────────────────────────────────────────────────
step "1/9 — GCP authentication"
gcloud config set project "${PROJECT_ID}" --quiet
ok "Active project: ${PROJECT_ID}"

# Verify credentials
gcloud auth print-identity-token --quiet > /dev/null 2>&1 \
  || fail "Not authenticated. Run: gcloud auth login && gcloud auth application-default login"
ok "Credentials valid"

# ─────────────────────────────────────────────────────────────────────────────
# STEP 2 — Enable required APIs
# ─────────────────────────────────────────────────────────────────────────────
step "2/9 — Enabling GCP APIs"
APIS=(
  "run.googleapis.com"
  "secretmanager.googleapis.com"
  "containerregistry.googleapis.com"
  "artifactregistry.googleapis.com"
  "aiplatform.googleapis.com"
  "iam.googleapis.com"
  "cloudresourcemanager.googleapis.com"
)
for api in "${APIS[@]}"; do
  gcloud services enable "${api}" --project="${PROJECT_ID}" --quiet 2>/dev/null \
    && ok "${api}" || warn "${api} (already enabled or no permission)"
done

# ─────────────────────────────────────────────────────────────────────────────
# STEP 3 — Service account & IAM
# ─────────────────────────────────────────────────────────────────────────────
step "3/9 — Service account & IAM"

if ! gcloud iam service-accounts describe "${SA_EMAIL}" \
     --project="${PROJECT_ID}" &>/dev/null; then
  gcloud iam service-accounts create "${SA_NAME}" \
    --display-name="SihaLink Orchestrator" \
    --project="${PROJECT_ID}"
  ok "Created service account: ${SA_EMAIL}"
else
  ok "Service account exists: ${SA_EMAIL}"
fi

ROLES=(
  "roles/secretmanager.secretAccessor"   # read secrets at runtime
  "roles/run.invoker"                    # allow self-invocation if needed
  "roles/logging.logWriter"             # write structured logs
  "roles/aiplatform.user"               # Vertex AI / Gemini
  "roles/storage.objectViewer"          # read GCS (model artifacts)
  "roles/monitoring.metricWriter"       # Cloud Monitoring custom metrics
)
for ROLE in "${ROLES[@]}"; do
  gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
    --member="serviceAccount:${SA_EMAIL}" \
    --role="${ROLE}" \
    --quiet 2>/dev/null && ok "${ROLE}" || warn "${ROLE} (may already exist)"
done

# ─────────────────────────────────────────────────────────────────────────────
# STEP 4 — Secrets in Secret Manager
# ─────────────────────────────────────────────────────────────────────────────
step "4/9 — Secret Manager"

REQUIRED_SECRETS=(
  "GEMINI_API_KEY"
  "GOOGLE_MAPS_API_KEY"
  "MONGODB_ATLAS_URI"
  "TELEGRAM_BOT_TOKEN"
  "FACILITY_TELEGRAM_ID"
)
OPTIONAL_SECRETS=(
  "VOYAGE_API_KEY"
  "DYNATRACE_API_TOKEN"
  "TELEGRAM_WEBHOOK_URL"
)

_ensure_secret() {
  local name="$1"
  local required="${2:-true}"
  if gcloud secrets describe "${name}" --project="${PROJECT_ID}" &>/dev/null; then
    ok "Secret ${name} exists"
  else
    if [[ "$required" == "true" ]]; then
      printf "\n  ${YELLOW}Enter value for secret ${name}: ${NC}"
      read -rs SECRET_VALUE; echo
      if [[ -z "${SECRET_VALUE}" ]]; then
        fail "Secret ${name} is required but was empty"
      fi
      printf '%s' "${SECRET_VALUE}" | \
        gcloud secrets create "${name}" \
          --data-file=- \
          --project="${PROJECT_ID}" \
          --replication-policy=automatic
      ok "Created secret: ${name}"
    else
      warn "Optional secret ${name} not set — skipping"
    fi
  fi
}

for s in "${REQUIRED_SECRETS[@]}"; do
  _ensure_secret "${s}" "true"
done
for s in "${OPTIONAL_SECRETS[@]}"; do
  _ensure_secret "${s}" "false"
done

# ─────────────────────────────────────────────────────────────────────────────
# STEP 5 — Build Docker image
# ─────────────────────────────────────────────────────────────────────────────
step "5/9 — Build container image"

# Read the Cloud Run service URL if it already exists (for VITE_API_URL)
EXISTING_URL=$(gcloud run services describe "${SERVICE_NAME}" \
  --region="${REGION}" --format="value(status.url)" 2>/dev/null || echo "")
VITE_API_URL="${EXISTING_URL:-https://${SERVICE_NAME}-$(gcloud config get-value project 2>/dev/null)-uc.a.run.app}"

gcloud auth configure-docker "${REGISTRY}" --quiet

docker build \
  --tag "${IMAGE}" \
  --tag "${IMAGE_LATEST}" \
  --build-arg "VITE_API_URL=${VITE_API_URL}" \
  --label "git-commit=${TAG}" \
  --label "build-date=$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  --cache-from "${IMAGE_LATEST}" \
  --file Dockerfile \
  .

ok "Image built: ${IMAGE}"

# ─────────────────────────────────────────────────────────────────────────────
# STEP 6 — Push image
# ─────────────────────────────────────────────────────────────────────────────
step "6/9 — Push image to GCR"
docker push "${IMAGE}"
docker push "${IMAGE_LATEST}"
ok "Pushed: ${IMAGE}"

# ─────────────────────────────────────────────────────────────────────────────
# STEP 7 — Deploy to Cloud Run
# ─────────────────────────────────────────────────────────────────────────────
step "7/9 — Deploy to Cloud Run"

# Build --set-secrets flag
SECRET_FLAGS=""
for s in "${REQUIRED_SECRETS[@]}"; do
  SECRET_FLAGS="${SECRET_FLAGS} --set-secrets=${s}=${s}:latest"
done
for s in "${OPTIONAL_SECRETS[@]}"; do
  if gcloud secrets describe "${s}" --project="${PROJECT_ID}" &>/dev/null; then
    SECRET_FLAGS="${SECRET_FLAGS} --set-secrets=${s}=${s}:latest"
  fi
done

# shellcheck disable=SC2086
gcloud run deploy "${SERVICE_NAME}" \
  --image="${IMAGE}" \
  --region="${REGION}" \
  --platform=managed \
  --service-account="${SA_EMAIL}" \
  --port=8080 \
  --memory=2Gi \
  --cpu=2 \
  --min-instances=1 \
  --max-instances=10 \
  --timeout=3600 \
  --concurrency=80 \
  --execution-environment=gen2 \
  --no-cpu-throttling \
  --set-env-vars="ENVIRONMENT=production,PORT=8080,NOTIFY_AGENT_URL=http://localhost:3001,GOOGLE_CLOUD_PROJECT=${PROJECT_ID},GOOGLE_CLOUD_LOCATION=${REGION},GOOGLE_GENAI_USE_VERTEXAI=TRUE,DYNATRACE_ENV_ID=xjn51780" \
  ${SECRET_FLAGS} \
  --allow-unauthenticated \
  --quiet

SERVICE_URL=$(gcloud run services describe "${SERVICE_NAME}" \
  --region="${REGION}" --format="value(status.url)")
ok "Deployed: ${SERVICE_URL}"

# ─────────────────────────────────────────────────────────────────────────────
# STEP 8 — Frontend: rebuild with real URL + Firebase deploy
# ─────────────────────────────────────────────────────────────────────────────
step "8/9 — Frontend build & Firebase Hosting"

cd frontend
export VITE_API_URL="${SERVICE_URL}"

npm install --legacy-peer-deps --silent

# Write the production environment file with the real Cloud Run URL
cat > src/environments/environment.prod.ts << ENVEOF
/**
 * Auto-generated by deploy/deploy.sh — do not edit manually.
 * Generated: $(date -u +"%Y-%m-%dT%H:%M:%SZ")
 */
export const environment = {
  production: true,
  apiUrl: "${SERVICE_URL}",
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

npm run build:prod
ok "Frontend built (dist/)"

firebase deploy --only hosting --project="${PROJECT_ID}" --non-interactive
FIREBASE_URL="https://${PROJECT_ID}.web.app"
ok "Frontend deployed: ${FIREBASE_URL}"

cd "${ROOT_DIR}"

# ─────────────────────────────────────────────────────────────────────────────
# STEP 9 — Health check
# ─────────────────────────────────────────────────────────────────────────────
step "9/9 — Health verification"

echo "  Waiting 10s for container to warm up…"
sleep 10

HTTP=$(curl -sf -o /dev/null -w "%{http_code}" \
  -H "Authorization: Bearer $(gcloud auth print-identity-token 2>/dev/null)" \
  "${SERVICE_URL}/health" 2>/dev/null || echo "000")

if [[ "$HTTP" == "200" ]]; then
  ok "Health check passed: ${SERVICE_URL}/health → 200"
  # Print swarm status
  curl -sf \
    -H "Authorization: Bearer $(gcloud auth print-identity-token 2>/dev/null)" \
    "${SERVICE_URL}/swarm/status" 2>/dev/null | python3 -m json.tool 2>/dev/null | head -20 || true
else
  warn "Health check returned ${HTTP} — service may still be initialising"
  echo "  Check logs: gcloud run services logs read ${SERVICE_NAME} --region=${REGION} --follow"
fi

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}${BOLD}"
echo "  ╔═══════════════════════════════════════════════════════╗"
echo "  ║        SihaLink Deployment Complete ✅                ║"
echo "  ╚═══════════════════════════════════════════════════════╝"
echo -e "${NC}"
printf "  %-22s ${CYAN}%s${NC}\n" "🌍 Frontend:"        "${FIREBASE_URL:-not deployed}"
printf "  %-22s ${CYAN}%s${NC}\n" "🤖 Orchestrator:"   "${SERVICE_URL}"
printf "  %-22s ${CYAN}%s${NC}\n" "🏥 Health check:"   "${SERVICE_URL}/health"
printf "  %-22s ${CYAN}%s${NC}\n" "🐛 Logs:"           "gcloud run services logs read ${SERVICE_NAME} --region=${REGION} --follow"
printf "  %-22s ${CYAN}%s${NC}\n" "↩ Rollback:"        "gcloud run services update-traffic ${SERVICE_NAME} --to-revisions=PREV=100 --region=${REGION}"
echo ""
