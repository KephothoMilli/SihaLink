#!/usr/bin/env bash
# =============================================================================
# SihaLink — Push all secrets from local .env to Google Secret Manager
#
# Run once before first deploy:
#   chmod +x deploy/setup-secrets.sh
#   ./deploy/setup-secrets.sh
# =============================================================================
set -euo pipefail

PROJECT_ID="${1:-kephothoagenticai}"
ENV_FILE="${2:-.env}"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
ok()   { echo -e "  ${GREEN}✓ $*${NC}"; }
warn() { echo -e "  ${YELLOW}⚠ $*${NC}"; }
fail() { echo -e "  ${RED}✗ $*${NC}"; exit 1; }

[[ -f "$ENV_FILE" ]] || fail ".env file not found at $ENV_FILE"

echo "Pushing secrets from $ENV_FILE to project $PROJECT_ID..."

# Secrets to push (values read from .env)
SECRETS=(
  "GEMINI_API_KEY"
  "GOOGLE_MAPS_API_KEY"
  "MONGODB_ATLAS_URI"
  "TELEGRAM_BOT_TOKEN"
  "FACILITY_TELEGRAM_ID"
  "DYNATRACE_API_TOKEN"
)
OPTIONAL_SECRETS=(
  "VOYAGE_API_KEY"
  "TELEGRAM_WEBHOOK_URL"
)

_push_secret() {
  local name="$1"
  local required="${2:-true}"

  # Extract value from .env (skip comments and empty lines)
  local value
  value=$(grep -E "^${name}=" "$ENV_FILE" | head -1 | cut -d'=' -f2- | tr -d '"' | tr -d "'") || true

  if [[ -z "$value" ]]; then
    if [[ "$required" == "true" ]]; then
      warn "${name} not found in $ENV_FILE — skipping (set manually with: echo VALUE | gcloud secrets create ${name} --data-file=-)"
    else
      warn "Optional ${name} not set — skipping"
    fi
    return
  fi

  if gcloud secrets describe "${name}" --project="${PROJECT_ID}" &>/dev/null; then
    # Add a new version
    printf '%s' "${value}" | \
      gcloud secrets versions add "${name}" \
        --data-file=- \
        --project="${PROJECT_ID}" \
        --quiet
    ok "Updated secret: ${name}"
  else
    # Create new secret
    printf '%s' "${value}" | \
      gcloud secrets create "${name}" \
        --data-file=- \
        --project="${PROJECT_ID}" \
        --replication-policy=automatic \
        --quiet
    ok "Created secret: ${name}"
  fi
}

for s in "${SECRETS[@]}"; do
  _push_secret "${s}" "true"
done
for s in "${OPTIONAL_SECRETS[@]}"; do
  _push_secret "${s}" "false"
done

echo ""
echo -e "${GREEN}Done. List secrets with:${NC}"
echo "  gcloud secrets list --project=${PROJECT_ID}"
echo ""
echo -e "${GREEN}Grant Cloud Run service account access:${NC}"
echo "  gcloud projects add-iam-policy-binding ${PROJECT_ID} \\"
echo "    --member='serviceAccount:sihalink-orchestrator@${PROJECT_ID}.iam.gserviceaccount.com' \\"
echo "    --role='roles/secretmanager.secretAccessor'"
