#!/bin/bash
# ============================================================
# SihaLink — Local Development Setup
# ============================================================
# Usage: bash setup-dev.sh
# Requires: Python 3.12+, Node.js 20+, npm

set -e

# ── Colors ──────────────────────────────────────────────────
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
NC='\033[0m'

echo -e "${CYAN}"
echo "  ╔═══════════════════════════════════════╗"
echo "  ║   SihaLink — Dev Environment Setup   ║"
echo "  ║   Sauti ya Afya 🏥                    ║"
echo "  ╚═══════════════════════════════════════╝"
echo -e "${NC}"

# ── 1. Python backend ───────────────────────────────────────
echo -e "${YELLOW}[1/5] Setting up Python backend...${NC}"

if [ ! -d ".venv" ]; then
  python3 -m venv .venv
  echo -e "${GREEN}  ✓ Virtual environment created${NC}"
fi

# Activate venv (cross-platform)
if [[ "$OSTYPE" == "msys" || "$OSTYPE" == "cygwin" || "$OSTYPE" == "win32" ]]; then
  source .venv/Scripts/activate
else
  source .venv/bin/activate
fi

pip install --upgrade pip --quiet
pip install -r requirements.txt --quiet
echo -e "${GREEN}  ✓ Python dependencies installed${NC}"

# ── 2. Notify Agent (Node.js / grammY) ─────────────────────
echo -e "${YELLOW}[2/5] Setting up Notify Agent (grammY bot)...${NC}"
cd agents/notify
npm install --silent
cd ../..
echo -e "${GREEN}  ✓ Notify Agent dependencies installed${NC}"

# ── 3. Frontend (Angular) ───────────────────────────────────
echo -e "${YELLOW}[3/5] Setting up Angular frontend...${NC}"
cd frontend
npm install --legacy-peer-deps --silent
cd ..
echo -e "${GREEN}  ✓ Frontend dependencies installed${NC}"

# ── 4. Environment file ─────────────────────────────────────
echo -e "${YELLOW}[4/5] Configuring environment...${NC}"

if [ ! -f ".env" ]; then
  cp .env.example .env
  echo -e "${YELLOW}  ⚠  Created .env from .env.example — fill in your API keys!${NC}"
else
  echo -e "${GREEN}  ✓ .env already exists${NC}"
fi

# ── 5. MongoDB indexes bootstrap ────────────────────────────
echo -e "${YELLOW}[5/5] Checking MongoDB connection...${NC}"
if [ -f ".env" ]; then
  source .env 2>/dev/null || true
fi

if [ -n "$MONGODB_ATLAS_URI" ] && [ "$MONGODB_ATLAS_URI" != "mongodb+srv://username:password@cluster.mongodb.net/sihalink?retryWrites=true&w=majority" ]; then
  python3 -c "
from agents.data.mcp_client import DataAgent
try:
    agent = DataAgent()
    agent.create_vector_search_index()
    print('  ✓ MongoDB indexes verified')
except Exception as e:
    print(f'  ⚠  MongoDB setup skipped: {e}')
" 2>/dev/null || echo -e "${YELLOW}  ⚠  MongoDB bootstrap skipped (set MONGODB_ATLAS_URI in .env)${NC}"
else
  echo -e "${YELLOW}  ⚠  MongoDB bootstrap skipped (set MONGODB_ATLAS_URI in .env)${NC}"
fi

# ── Summary ─────────────────────────────────────────────────
echo ""
echo -e "${GREEN}╔═══════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║  ✅  SihaLink development environment ready!             ║${NC}"
echo -e "${GREEN}╚═══════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "${CYAN}Required API keys (edit .env):${NC}"
echo "  GEMINI_API_KEY       → https://aistudio.google.com/app/apikey"
echo "  GOOGLE_MAPS_API_KEY  → https://console.cloud.google.com/apis"
echo "  MONGODB_ATLAS_URI    → https://cloud.mongodb.com"
echo "  TELEGRAM_BOT_TOKEN   → https://t.me/BotFather"
echo ""
echo -e "${CYAN}Start services (run each in a separate terminal):${NC}"
echo ""
echo "  Terminal 1 — Orchestrator (Python):"
echo "    source .venv/bin/activate  # Linux/macOS"
echo "    .\.venv\Scripts\activate   # Windows"
echo "    uvicorn agents.orchestrator.agent:app --reload --port 8000"
echo ""
echo "  Terminal 2 — Notify Agent (Node.js):"
echo "    cd agents/notify && npm run dev"
echo ""
echo "  Terminal 3 — Frontend (Angular):"
echo "    cd frontend && npm run dev"
echo "    → Open http://localhost:5173"
echo ""
echo "  API Docs: http://localhost:8000/docs"
echo ""
