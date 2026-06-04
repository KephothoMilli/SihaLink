#!/bin/bash
# Start both backend and frontend servers for development testing

echo "╔════════════════════════════════════════════════════════════════╗"
echo "║     SihaLink Development Environment Startup                 ║"
echo "╚════════════════════════════════════════════════════════════════╝"
echo ""

# Get the script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_PATH="$SCRIPT_DIR/venv"
VENV_ACTIVATE="$VENV_PATH/bin/activate"

# Check if virtual environment exists
if [ ! -f "$VENV_ACTIVATE" ]; then
    echo "❌ Virtual environment not found at: $VENV_PATH"
    echo "Please run: python3 -m venv venv"
    exit 1
fi

# Activate virtual environment
echo "🔧 Activating virtual environment..."
source "$VENV_ACTIVATE"
echo "✅ Virtual environment activated"
echo ""

# Check required environment variables
echo "🔍 Checking environment variables..."
REQUIRED_VARS=("GEMINI_API_KEY" "MONGODB_ATLAS_URI")
MISSING_VARS=()

for var in "${REQUIRED_VARS[@]}"; do
    if [ -z "${!var}" ]; then
        MISSING_VARS+=("$var")
    fi
done

if [ ${#MISSING_VARS[@]} -gt 0 ]; then
    echo "⚠️  Missing environment variables: ${MISSING_VARS[*]}"
    echo "Please set them or the application may not work correctly."
else
    echo "✅ All required environment variables are set"
fi
echo ""

# Start backend server
echo "🚀 Starting Backend Server (FastAPI/Uvicorn)..."
echo "   Command: uvicorn agents.orchestrator.agent:app --reload --port 8000"

cd "$SCRIPT_DIR"
python -m uvicorn agents.orchestrator.agent:app --reload --port 8000 &
BACKEND_PID=$!

echo "✅ Backend Server started (PID: $BACKEND_PID)"
echo "   📍 Available at: http://localhost:8000"
echo "   📍 API Docs: http://localhost:8000/docs"
echo ""

# Give backend a moment to start
sleep 2

# Check if frontend directory exists
FRONTEND_DIR="$SCRIPT_DIR/frontend"
if [ ! -d "$FRONTEND_DIR" ]; then
    echo "❌ Frontend directory not found at: $FRONTEND_DIR"
    kill $BACKEND_PID
    exit 1
fi

# Start frontend server
echo "🚀 Starting Frontend Server (Angular)..."
echo "   Command: npm start"

cd "$FRONTEND_DIR"
npm start &
FRONTEND_PID=$!

echo "✅ Frontend Server started (PID: $FRONTEND_PID)"
echo "   📍 Available at: http://localhost:4200"
echo ""

echo "╔════════════════════════════════════════════════════════════════╗"
echo "║ ✅ Both servers are running!                                  ║"
echo "╠════════════════════════════════════════════════════════════════╣"
echo "║ Backend:   http://localhost:8000                               ║"
echo "║ Frontend:  http://localhost:4200                               ║"
echo "║                                                                ║"
echo "║ Press Ctrl+C to stop the servers                               ║"
echo "╚════════════════════════════════════════════════════════════════╝"
echo ""

# Trap Ctrl+C to cleanup
trap cleanup INT
cleanup() {
    echo ""
    echo "🛑 Shutting down servers..."
    kill $BACKEND_PID 2>/dev/null
    kill $FRONTEND_PID 2>/dev/null
    echo "✅ Servers stopped"
    exit 0
}

# Wait for both processes
wait
