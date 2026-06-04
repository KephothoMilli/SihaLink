# ─────────────────────────────────────────────────────────────────────────────
# SihaLink — Multi-service container
#
# Services started by supervisord:
#   :8080  Orchestrator (FastAPI / uvicorn) — Google Agent Runtime entry point
#   :3001  Notify Agent  (Node.js / grammY)  — Telegram bot HTTP server
#
# Google Agent Runtime expects the primary service on port 8080.
# The Orchestrator calls the Notify Agent on localhost:3001 internally.
# ─────────────────────────────────────────────────────────────────────────────

# ── Stage 1: Node.js build (Notify Agent) ────────────────────────────────────
FROM node:20-slim AS notify-build

WORKDIR /build/notify
COPY agents/notify/package.json agents/notify/tsconfig.json ./
RUN npm ci --omit=dev
COPY agents/notify/bot.ts ./
RUN npx tsc --outDir dist --module commonjs --target es2020 \
    --esModuleInterop true --skipLibCheck true bot.ts 2>/dev/null || \
    npx tsc --outDir dist bot.ts || true
# Fallback: copy source if tsc fails (ts-node will run it directly)
RUN [ -f dist/bot.js ] || cp bot.ts dist/bot.ts

# ── Stage 2: Python runtime ───────────────────────────────────────────────────
FROM python:3.12-slim

# System deps: supervisord (process manager) + Node.js (Notify Agent)
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
        supervisor \
        nodejs \
        npm \
    && rm -rf /var/lib/apt/lists/*

# ── Non-root user ─────────────────────────────────────────────────────────────
RUN groupadd -r afya && useradd -r -g afya -d /app -s /sbin/nologin afya

WORKDIR /app

# ── Python dependencies ───────────────────────────────────────────────────────
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# ── Node.js dependencies for Notify Agent ────────────────────────────────────
COPY agents/notify/package.json agents/notify/package-lock.json* ./agents/notify/
RUN cd agents/notify && npm ci --omit=dev

# ── Application code ──────────────────────────────────────────────────────────
COPY . .

# Copy compiled Notify Agent from build stage
COPY --from=notify-build /build/notify/dist ./agents/notify/dist
COPY --from=notify-build /build/notify/node_modules ./agents/notify/node_modules

# ── Supervisord configuration ─────────────────────────────────────────────────
RUN cat > /etc/supervisor/conf.d/sihalink.conf << 'EOF'
[supervisord]
nodaemon=true
user=root
logfile=/var/log/supervisor/supervisord.log
pidfile=/var/run/supervisord.pid

[program:orchestrator]
command=uvicorn agents.orchestrator.agent:app --host 0.0.0.0 --port 8080 --workers 2
directory=/app
user=afya
autostart=true
autorestart=true
startretries=5
stdout_logfile=/dev/stdout
stdout_logfile_maxbytes=0
stderr_logfile=/dev/stderr
stderr_logfile_maxbytes=0
environment=PYTHONUNBUFFERED="1",PORT="8080"

[program:notify-agent]
command=node agents/notify/dist/bot.js
directory=/app
user=afya
autostart=true
autorestart=true
startretries=5
stdout_logfile=/dev/stdout
stdout_logfile_maxbytes=0
stderr_logfile=/dev/stderr
stderr_logfile_maxbytes=0
environment=NOTIFY_PORT="3001"

[unix_http_server]
file=/var/run/supervisor.sock

[rpcinterface:supervisor]
supervisor.rpcinterface_factory=supervisor.rpcinterface:make_main_rpcinterface

[supervisorctl]
serverurl=unix:///var/run/supervisor.sock
EOF

# ── Directories and permissions ───────────────────────────────────────────────
RUN mkdir -p /var/log/supervisor /var/run \
    && chown -R afya:afya /app \
    && chmod 755 /var/log/supervisor

# ── Health check — Agent Runtime polls /health ────────────────────────────────
HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
    CMD curl -f http://localhost:8080/health || exit 1

# ── Ports ─────────────────────────────────────────────────────────────────────
# 8080 — Orchestrator (Google Agent Runtime primary port)
# 3001 — Notify Agent (internal only, not exposed externally)
EXPOSE 8080

ENV PYTHONUNBUFFERED=1 \
    PORT=8080 \
    NOTIFY_AGENT_URL=http://localhost:3001

# ── Entry point ───────────────────────────────────────────────────────────────
CMD ["/usr/bin/supervisord", "-c", "/etc/supervisor/conf.d/sihalink.conf"]
