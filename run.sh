#!/usr/bin/env bash
# ==============================================================================
# Synaptia Runner & Process Orchestrator
# ==============================================================================
# Usage:
#   ./run.sh              # Start Cognitive Training Platform (Flask, port 5002)
#   ./run.sh --frontend   # Start AR Glasses Frontend (Next.js, port 3000)
#   ./run.sh --inference  # Start AR Glasses Inference Backend (FastAPI, port 8002)
#   ./run.sh --all        # Start all services concurrently with clean Ctrl+C shutdown
#   ./run.sh --test       # Run test suite
#   ./run.sh --cli        # Run interactive CLI puzzle mode
# ==============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Colors for terminal output
BOLD="\033[1m"
GREEN="\033[0;32m"
BLUE="\033[0;34m"
PURPLE="\033[0;35m"
CYAN="\033[0;36m"
YELLOW="\033[1;33m"
RESET="\033[0m"

echo -e "${PURPLE}${BOLD}"
echo "  🧠  S Y N A P T I A  🧠"
echo "  Cognitive AI & Assistive AR Memory Platform"
echo -e "${RESET}"

# 1. Ensure Python Virtual Environment
if [ ! -d ".venv" ]; then
    echo -e "${YELLOW}Creating Python virtual environment in .venv...${RESET}"
    python3 -m venv .venv
    source .venv/bin/activate
    pip install --upgrade pip
    pip install -r requirements.txt
    pip install fastapi "uvicorn[standard]" sse-starlette pymongo openai pytest
else
    source .venv/bin/activate
fi

# 2. Ensure .env exists
if [ ! -f ".env" ]; then
    echo -e "${YELLOW}Generating .env from .env.example...${RESET}"
    cp .env.example .env
fi

MODE="${1:-cognitive}"

case "$MODE" in
    --frontend|-f)
        echo -e "${CYAN}Starting SynaptiaV2 AR Glasses Frontend (Next.js)...${RESET}"
        cd SynaptiaV2-main/frontend
        if [ ! -d "node_modules" ]; then
            echo -e "${YELLOW}Installing frontend node dependencies...${RESET}"
            npm install
        fi
        echo -e "${GREEN}AR Glasses HUD available at: http://localhost:3000${RESET}"
        npm run dev
        ;;

    --inference|-i)
        echo -e "${CYAN}Starting SynaptiaV2 Inference Backend (FastAPI)...${RESET}"
        cd SynaptiaV2-main/inference
        echo -e "${GREEN}Inference service running at: http://localhost:8002 (Docs: http://localhost:8002/docs)${RESET}"
        python3 -m uvicorn main:app --host 0.0.0.0 --port 8002 --reload
        ;;

    --all|-a)
        echo -e "${CYAN}Starting ALL Synaptia services concurrently...${RESET}"
        
        # Array to track PIDs
        PIDS=()
        
        cleanup() {
            echo -e "\n${YELLOW}Shutting down all Synaptia processes...${RESET}"
            for pid in "${PIDS[@]}"; do
                if kill -0 "$pid" 2>/dev/null; then
                    kill "$pid" 2>/dev/null || true
                fi
            done
            wait 2>/dev/null || true
            echo -e "${GREEN}All services stopped cleanly.${RESET}"
            exit 0
        }
        trap cleanup SIGINT SIGTERM EXIT

        # Start Flask Cognitive Server
        echo -e "${BLUE}[1/3] Launching Flask Cognitive Platform on :5002...${RESET}"
        python3 app.py &
        PIDS+=($!)
        sleep 1

        # Start FastAPI Inference Backend
        echo -e "${BLUE}[2/3] Launching FastAPI Inference Backend on :8002...${RESET}"
        (cd SynaptiaV2-main/inference && python3 -m uvicorn main:app --host 0.0.0.0 --port 8002) &
        PIDS+=($!)
        sleep 1

        # Start Next.js Frontend
        echo -e "${BLUE}[3/3] Launching Next.js AR Frontend on :3000...${RESET}"
        (cd SynaptiaV2-main/frontend && npm run dev) &
        PIDS+=($!)

        echo -e "\n${GREEN}${BOLD}✨ All Synaptia services are now running:${RESET}"
        echo -e "   • Cognitive Training Web App:  ${CYAN}http://localhost:5002${RESET}"
        echo -e "   • AR Glasses Next.js HUD:       ${CYAN}http://localhost:3000${RESET}"
        echo -e "   • Memory Inference API:        ${CYAN}http://localhost:8002/docs${RESET}"
        echo -e "\n${YELLOW}Press Ctrl+C to stop all servers.${RESET}\n"

        wait
        ;;

    --test|-t)
        echo -e "${CYAN}Running Synaptia Automated Test Suite...${RESET}"
        pytest tests/ -v
        ;;

    --cli|-c)
        echo -e "${CYAN}Starting Synaptia Interactive CLI...${RESET}"
        python3 cli.py
        ;;

    --help|-h)
        echo "Usage: ./run.sh [OPTIONS]"
        echo ""
        echo "Options:"
        echo "  (none)        Start Flask Cognitive Training Platform (http://localhost:5002)"
        echo "  --all, -a     Start Cognitive App, AR Frontend, and Inference Server concurrently"
        echo "  --frontend, -f Start Next.js AR Glasses Frontend on :3000"
        echo "  --inference, -i Start FastAPI Inference Backend on :8002"
        echo "  --cli, -c     Run interactive CLI logic puzzle session"
        echo "  --test, -t    Run pytest test suite"
        echo "  --help, -h    Show this help message"
        ;;

    cognitive|*)
        echo -e "${GREEN}Starting Cognitive Training Platform on http://localhost:5002...${RESET}"
        echo -e "${CYAN}Tip: Run './run.sh --all' to also launch the Next.js AR HUD & inference server.${RESET}\n"
        python3 app.py
        ;;
esac
