"""
SWARM-100 Server Launcher
Starts the unified FastAPI application and real-time dashboard:
- Web Dashboard: http://localhost:8000/
- REST API:      http://localhost:8000/api/v1
- WebSocket:     ws://localhost:8000/ws
- Interactive Docs: http://localhost:8000/docs
"""

import sys
from pathlib import Path
import uvicorn

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.agents.registry import init_and_seed

def main():
    print("=" * 70)
    print("SWARM-100: Autonomous Multi-Agent Workforce Command Center")
    print("=" * 70)
    print("Initializing SQLite persistence & verifying 100 agents...")
    init_and_seed()
    print("[OK] Registry verified (10 teams, 100 agents, 9 tools, 3 memory layers)")
    print()
    print("  -> Live Dashboard:    http://localhost:8000/")
    print("  -> REST API Docs:     http://localhost:8000/docs")
    print("  -> WebSocket Stream:  ws://localhost:8000/ws")
    print("=" * 70)
    uvicorn.run("backend.main:app", host="127.0.0.1", port=8000, reload=False)

if __name__ == "__main__":
    main()
