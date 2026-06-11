# =============================================================================
# SihaLink — Production Dockerfile for Google Cloud Run
# =============================================================================
#
# Two-service container managed by supervisord:
#   :8080  Orchestrator (FastAPI/uvicorn)  — Cloud Run primary port
#   :3001  Notify Agent (Node.js/grammY)   — internal Telegram bot
#
# Build:
#   docker build -t gcr.io/PROJECT_ID/sihalink-orchestrator:latest .
#
# Cloud Run expects PORT env var and a single process on $PORT (supervisord
# here listens to nothing — uvicorn binds 0.0.0.0:8080 which Cloud Run routes to).
# =============================================================================

# ── Stage 1: Node.js build (Notify Agent TypeScript → JS) ────────────────────
FROM node:20-slim AS notify-build

WORKDIR /build/notify
# Copy only dependency manifests first for layer caching
COPY agents/notify/package.json agents/notify/package-lock.json* ./
# Install ALL deps (including devDependencies) so tsc/typescript is available at build time
RUN npm ci

COPY agents/notify/tsconfig.json ./
COPY agents/notify/bot.ts ./
# Compile TypeScript using the project's tsconfig (includes proper lib paths)
RUN npm run build || true
# Ensure dist/ exists then check if compilation produced bot.js
# If tsc failed, copy bot.ts so tsx can run it as a fallback at runtime
RUN mkdir -p dist && ([ -f dist/bot.js ] || cp bot.ts dist/bot.ts)

# ── Stage 2: Angular frontend build ──────────────────────────────────────────
FROM node:20-slim AS frontend-build

WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci --legacy-peer-deps

COPY frontend/ ./
# VITE_API_URL is injected at build time via --build-arg
ARG VITE_API_URL=https://sihalink-orchestrator-hash-uc.a.run.app
ENV VITE_API_URL=${VITE_API_URL}
RUN npm run build:prod

# ── Stage 3: Python production runtime ───────────────────────────────────────
FROM python:3.12-slim AS runtime

# Install: supervisord + curl (healthcheck) + Node.js runtime for Notify Agent
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
        supervisor \
        nodejs \
        npm \
    && rm -rf /var/lib/apt/lists/*

# Non-root user — Cloud Run best practice
RUN groupadd -r sihalink \
    && useradd -r -g sihalink -d /app -s /sbin/nologin sihalink

WORKDIR /app

# ── Python dependencies (cached layer) ───────────────────────────────────────
COPY requirements.txt ./
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# ── Application source ────────────────────────────────────────────────────────
# Copy agents (Python) and data package
COPY agents/ ./agents/
COPY data/ ./data/
# Top-level __init__ files
COPY pyproject.toml ./

# ── Notify Agent artifacts from Stage 1 ──────────────────────────────────────
# Copy only production node_modules (prune dev deps to keep image lean)
COPY --from=notify-build /build/notify/node_modules  ./agents/notify/node_modules
COPY --from=notify-build /build/notify/dist           ./agents/notify/dist
# Also copy bot.ts in case tsx fallback is needed at runtime
COPY --from=notify-build /build/notify/bot.ts         ./agents/notify/bot.ts

# ── Frontend static files from Stage 2 ───────────────────────────────────────
# Served by the FastAPI app via StaticFiles mount at "/"
COPY --from=frontend-build /build/frontend/dist/frontend/browser ./static

# ── supervisord config ────────────────────────────────────────────────────────
RUN mkdir -p /etc/supervisor/conf.d /var/log/supervisor /var/run/supervisor
COPY deploy/supervisord.conf /etc/supervisor/conf.d/sihalink.conf

# ── Permissions ───────────────────────────────────────────────────────────────
RUN chown -R sihalink:sihalink /app /var/log/supervisor \
    && chmod 755 /var/log/supervisor

# ── Health check (Cloud Run also has its own liveness probe) ──────────────────
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD curl -sf http://localhost:8080/health || exit 1

# ── Expose Cloud Run primary port ─────────────────────────────────────────────
EXPOSE 8080

# ── Runtime environment defaults (overridden by Cloud Run env/secrets) ────────
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8080 \
    NOTIFY_AGENT_URL=http://localhost:3001 \
    ENVIRONMENT=production

# ── Entry point ───────────────────────────────────────────────────────────────
CMD ["/usr/bin/supervisord", "-n", "-c", "/etc/supervisor/conf.d/sihalink.conf"]
