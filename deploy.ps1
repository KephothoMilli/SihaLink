#Requires -Version 5.1
<#
.SYNOPSIS
    SihaLink — Deploy to Google Agent Runtime + Firebase Hosting (Windows)

.DESCRIPTION
    Mirrors deploy.sh for Windows PowerShell environments.
    Deploys the Orchestrator container to Google Agent Runtime (Cloud Run)
    and the Angular frontend to Firebase Hosting.

.PARAMETER Environment
    Target environment: dev | prod  (default: dev)

.PARAMETER ProjectId
    GCP project ID. Defaults to current gcloud project.

.PARAMETER Region
    GCP region (default: us-central1)

.EXAMPLE
    .\deploy.ps1 -Environment prod -ProjectId my-gcp-project
    .\deploy.ps1                          # dev, current project
#>
param(
    [ValidateSet("dev","prod","staging")]
    [string]$Environment = "dev",

    [string]$ProjectId = (gcloud config get-value project 2>$null),

    [string]$Region = "us-central1"
)

$ErrorActionPreference = "Stop"
$AgentName   = "sihalink-orchestrator"
$Image       = "gcr.io/$ProjectId/$AgentName`:latest"
$SaEmail     = "$AgentName@$ProjectId.iam.gserviceaccount.com"

# ── Helpers ───────────────────────────────────────────────────────────────────
function Step   { param($n,$t) Write-Host "`n$n — $t" -ForegroundColor Cyan }
function Ok     { param($m)    Write-Host "  ✓ $m"    -ForegroundColor Green }
function Warn   { param($m)    Write-Host "  ⚠ $m"    -ForegroundColor Yellow }
function Fail   { param($m)    Write-Host "  ✗ $m"    -ForegroundColor Red; exit 1 }

function Invoke-Gcloud {
    $result = & gcloud @args 2>&1
    if ($LASTEXITCODE -ne 0) { throw "gcloud $args failed: $result" }
    return $result
}

Write-Host "`n╔══════════════════════════════════════════════════════════╗" -ForegroundColor Green
Write-Host "║          SihaLink — Deployment Script (Windows)       ║" -ForegroundColor Green
Write-Host "╚══════════════════════════════════════════════════════════╝`n" -ForegroundColor Green
Write-Host "  Project   : $ProjectId"
Write-Host "  Region    : $Region"
Write-Host "  Env       : $Environment"
Write-Host "  Image     : $Image`n"

if (-not $ProjectId) { Fail "ProjectId is empty. Run: gcloud config set project YOUR_PROJECT" }

# ─────────────────────────────────────────────────────────────────────────────
# STEP 1 — GCP auth
# ─────────────────────────────────────────────────────────────────────────────
Step "1/8" "GCP authentication"
Invoke-Gcloud config set project $ProjectId | Out-Null
Ok "Project set to $ProjectId"

# ─────────────────────────────────────────────────────────────────────────────
# STEP 2 — Enable APIs
# ─────────────────────────────────────────────────────────────────────────────
Step "2/8" "Enabling GCP APIs"
$Apis = @(
    "run.googleapis.com",
    "secretmanager.googleapis.com",
    "containerregistry.googleapis.com",
    "aiplatform.googleapis.com",
    "firebase.googleapis.com"
)
foreach ($api in $Apis) {
    try {
        Invoke-Gcloud services enable $api --quiet | Out-Null
        Ok $api
    } catch {
        Warn "$api (may already be enabled)"
    }
}

# ─────────────────────────────────────────────────────────────────────────────
# STEP 3 — Secrets
# ─────────────────────────────────────────────────────────────────────────────
Step "3/8" "Google Secret Manager"

$RequiredSecrets = @(
    "GEMINI_API_KEY",
    "GOOGLE_MAPS_API_KEY",
    "MONGODB_ATLAS_URI",
    "TELEGRAM_BOT_TOKEN",
    "FACILITY_TELEGRAM_ID",
    "VOYAGE_API_KEY"          # Required — Voyage AI RAG embeddings
)
# TELEGRAM_WEBHOOK_URL — only needed for webhook mode, not long-polling.
# DYNATRACE_API_TOKEN  — optional observability.
# Both are auto-created with an empty placeholder so --set-secrets never errors.
$OptionalSecrets = @("TELEGRAM_WEBHOOK_URL", "DYNATRACE_API_TOKEN")

foreach ($secret in $RequiredSecrets) {
    $exists = gcloud secrets describe $secret --project=$ProjectId 2>$null
    if ($exists) {
        Ok "Secret $secret exists"
    } else {
        Warn "Secret $secret missing"
        $val = Read-Host "Enter value for $secret" -AsSecureString
        $plain = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
            [Runtime.InteropServices.Marshal]::SecureStringToBSTR($val)
        )
        $plain | gcloud secrets create $secret --data-file=- --project=$ProjectId
        Ok "Secret $secret created"
    }
}

foreach ($secret in $OptionalSecrets) {
    $exists = gcloud secrets describe $secret --project=$ProjectId 2>$null
    if ($exists) {
        Ok "Optional secret $secret exists"
    } else {
        # Auto-create with empty string so Secret Manager references don't fail
        Write-Host "  Creating $secret with empty placeholder..." -ForegroundColor Gray
        "" | gcloud secrets create $secret --data-file=- --project=$ProjectId --quiet 2>$null
        if ($LASTEXITCODE -eq 0) {
            Ok "Optional secret $secret created (empty placeholder)"
        } else {
            Warn "Optional secret $secret skipped (using default)"
        }
    }
}

# ─────────────────────────────────────────────────────────────────────────────
# STEP 4 — Service account & IAM
# ─────────────────────────────────────────────────────────────────────────────
Step "4/8" "Service account & IAM"

$saExists = gcloud iam service-accounts describe $SaEmail --project=$ProjectId 2>$null
if (-not $saExists) {
    Invoke-Gcloud iam service-accounts create $AgentName `
        --display-name="SihaLink Orchestrator" `
        --project=$ProjectId | Out-Null
    Ok "Service account created: $SaEmail"
} else {
    Ok "Service account exists: $SaEmail"
}

$Roles = @(
    "roles/secretmanager.secretAccessor",
    "roles/run.invoker",
    "roles/logging.logWriter",
    "roles/aiplatform.user",
    "roles/storage.objectViewer"
)
foreach ($role in $Roles) {
    gcloud projects add-iam-policy-binding $ProjectId `
        --member="serviceAccount:$SaEmail" `
        --role=$role `
        --quiet 2>$null | Out-Null
    Ok "Role $role granted"
}

# ─────────────────────────────────────────────────────────────────────────────
# STEP 5 — Container build & push
# ─────────────────────────────────────────────────────────────────────────────
Step "5/8" "Container build & push"

Invoke-Gcloud auth configure-docker gcr.io --quiet | Out-Null

$gitHash = (git rev-parse --short HEAD 2>$null) ?? "latest"

# ── Detect whether Docker daemon is reachable ────────────────────────────────
$dockerRunning = $false
try {
    $dockerInfo = docker info 2>&1
    if ($LASTEXITCODE -eq 0) { $dockerRunning = $true }
} catch { }

if ($dockerRunning) {
    # Local Docker build + push
    Write-Host "  Docker Desktop detected — building locally" -ForegroundColor Gray

    docker build `
        --tag $Image `
        --label "git-commit=$gitHash" `
        --label "build-env=$Environment" `
        .
    if ($LASTEXITCODE -ne 0) { Fail "docker build failed" }
    Ok "Image built: $Image"

    docker push $Image
    if ($LASTEXITCODE -ne 0) { Fail "docker push failed" }
    Ok "Image pushed to GCR"

} else {
    # Docker not available — use Cloud Build (no local Docker needed)
    Warn "Docker Desktop is not running — using Cloud Build instead (no local Docker needed)"
    Write-Host "  Submitting source to Cloud Build..." -ForegroundColor Gray

    $cloudbuildConfig = Join-Path (Split-Path $PSScriptRoot) "deploy\cloudbuild.yaml"
    if (-not (Test-Path $cloudbuildConfig)) {
        $cloudbuildConfig = "deploy\cloudbuild.yaml"
    }

    $ServiceUrl = (gcloud run services describe $AgentName `
        --region=$Region --format="value(status.url)" 2>$null)
    $ViteUrl = if ($ServiceUrl) { $ServiceUrl } else { "https://$AgentName-$ProjectId-uc.a.run.app" }

    & gcloud builds submit `
        --config $cloudbuildConfig `
        --project $ProjectId `
        --substitutions "_PROJECT_ID=$ProjectId,_REGION=$Region,_SERVICE_NAME=$AgentName,_SA_EMAIL=$SaEmail,_SERVICE_URL=$ViteUrl,_FIREBASE_PROJECT=$ProjectId" `
        .
    if ($LASTEXITCODE -ne 0) { Fail "Cloud Build failed — check logs at https://console.cloud.google.com/cloud-build/builds?project=$ProjectId" }
    Ok "Cloud Build complete — image built and pushed via GCP"

    # Cloud Build already deploys to Cloud Run and Firebase, skip steps 6 & 7
    Write-Host "`n  Cloud Build ran the full pipeline (build → push → deploy → firebase)" -ForegroundColor Cyan
    Write-Host "  Skipping steps 6 and 7 (already done by Cloud Build)" -ForegroundColor Gray

    $AgentUrl = (gcloud run services describe $AgentName `
        --region=$Region --format="value(status.url)" 2>$null) ?? $ViteUrl
    $FirebaseUrl = "https://$ProjectId.web.app"

    # Jump to health check
    Step "8/8" "Health verification"
    Start-Sleep -Seconds 10
    try {
        $token = (gcloud auth print-identity-token 2>$null)
        $headers = @{ Authorization = "Bearer $token" }
        $resp = Invoke-WebRequest -Uri "$AgentUrl/health" -Headers $headers -UseBasicParsing -TimeoutSec 15
        Ok "Orchestrator /health → $($resp.StatusCode) OK"
    } catch {
        Warn "Orchestrator /health not yet ready — service may still be starting"
    }

    Write-Host "`n╔══════════════════════════════════════════════════════════╗" -ForegroundColor Green
    Write-Host "║              Deployment Complete ✅                     ║" -ForegroundColor Green
    Write-Host "╚══════════════════════════════════════════════════════════╝`n" -ForegroundColor Green
    Write-Host "  📱 Frontend          : $FirebaseUrl"
    Write-Host "  🤖 Agent Runtime     : $AgentUrl"
    Write-Host "  🔍 Health check      : $AgentUrl/health"
    Write-Host ""
    Write-Host "  Useful commands:"
    Write-Host "    Logs    : gcloud run services logs read $AgentName --region=$Region --follow"
    Write-Host "    Rollback: gcloud run services update-traffic $AgentName --to-revisions=PREV=100 --region=$Region"
    Write-Host ""
    exit 0
}

# ─────────────────────────────────────────────────────────────────────────────
# STEP 6 — Deploy to Google Agent Runtime / Cloud Run
# ─────────────────────────────────────────────────────────────────────────────
Step "6/8" "Google Agent Runtime deployment"

# Build --set-secrets flags
$SecretFlags = @()
foreach ($s in $RequiredSecrets) { $SecretFlags += "--set-secrets=${s}=${s}:latest" }
foreach ($s in $OptionalSecrets) {
    $ex = gcloud secrets describe $s --project=$ProjectId 2>$null
    if ($ex) { $SecretFlags += "--set-secrets=${s}=${s}:latest" }
}

$adkAvailable = Get-Command adk -ErrorAction SilentlyContinue
if ($adkAvailable) {
    try {
        adk deploy cloud_run `
            --project=$ProjectId `
            --region=$Region `
            --service_name=$AgentName `
            agents/orchestrator `
            -- --service-account=$SaEmail
        Ok "Deployed via ADK CLI"
    } catch {
        Warn "ADK deploy failed — falling back to Cloud Run"
        $adkAvailable = $null
    }
}

if (-not $adkAvailable) {
    $deployArgs = @(
        "run", "deploy", $AgentName,
        "--image=$Image",
        "--region=$Region",
        "--platform=managed",
        "--service-account=$SaEmail",
        "--port=8080",
        "--memory=2Gi",
        "--cpu=2",
        "--min-instances=1",
        "--max-instances=10",
        "--timeout=300",
        "--set-env-vars=ENVIRONMENT=$Environment,NOTIFY_AGENT_URL=http://localhost:3001",
        "--allow-unauthenticated",
        "--quiet"
    ) + $SecretFlags

    & gcloud @deployArgs
    if ($LASTEXITCODE -ne 0) { Fail "Cloud Run deployment failed" }
    Ok "Deployed to Cloud Run"
}

$AgentUrl = (gcloud run services describe $AgentName `
    --region=$Region --format="value(status.url)" 2>$null) ?? `
    "https://$Region-$ProjectId.run.app"
Ok "Agent Runtime URL: $AgentUrl"

# ─────────────────────────────────────────────────────────────────────────────
# STEP 7 — Frontend build & Firebase Hosting
# ─────────────────────────────────────────────────────────────────────────────
Step "7/8" "Frontend build & Firebase Hosting"

Push-Location frontend

$env:VITE_API_URL = $AgentUrl

npm install --legacy-peer-deps --silent
if ($LASTEXITCODE -ne 0) { Fail "npm install failed" }

# Write production environment file
$timestamp = (Get-Date -Format "yyyy-MM-ddTHH:mm:ssZ")
$envContent = @"
/**
 * Auto-generated by deploy.ps1 — do not edit manually.
 * Generated: $timestamp
 */
export const environment = {
  production: true,
  apiUrl: "$AgentUrl",
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
"@
Set-Content -Path "src/environments/environment.prod.ts" -Value $envContent -Encoding UTF8

npm run build:prod
if ($LASTEXITCODE -ne 0) { Fail "npm run build:prod failed" }
Ok "Frontend built (dist/)"

firebase deploy --only hosting --project=$ProjectId
if ($LASTEXITCODE -ne 0) { Fail "firebase deploy failed" }
$FirebaseUrl = "https://$ProjectId.web.app"
Ok "Frontend deployed: $FirebaseUrl"

Pop-Location

# ─────────────────────────────────────────────────────────────────────────────
# STEP 8 — Health check
# ─────────────────────────────────────────────────────────────────────────────
Step "8/8" "Health verification"

Start-Sleep -Seconds 5
try {
    $resp = Invoke-WebRequest -Uri "$AgentUrl/health" -UseBasicParsing -TimeoutSec 10
    Ok "Orchestrator /health → $($resp.StatusCode) OK"
} catch {
    Warn "Orchestrator /health not yet ready (may still be starting)"
}

# ─────────────────────────────────────────────────────────────────────────────
# Summary
# ─────────────────────────────────────────────────────────────────────────────
Write-Host "`n╔══════════════════════════════════════════════════════════╗" -ForegroundColor Green
Write-Host "║              Deployment Complete ✅                     ║" -ForegroundColor Green
Write-Host "╚══════════════════════════════════════════════════════════╝`n" -ForegroundColor Green
Write-Host "  📱 Frontend          : $FirebaseUrl"
Write-Host "  🤖 Agent Runtime     : $AgentUrl"
Write-Host "  🔍 Health check      : $AgentUrl/health"
Write-Host ""
Write-Host "  Useful commands:"
Write-Host "    Logs    : gcloud run services logs read $AgentName --region=$Region --follow"
Write-Host "    Secrets : gcloud secrets list --project=$ProjectId"
Write-Host "    Rollback: gcloud run services update-traffic $AgentName --to-revisions=PREV=100"
Write-Host ""

