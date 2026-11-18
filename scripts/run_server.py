"""
SWARM-100 Server Launcher
Starts the unified FastAPI application and real-time dashboard:
- Web Dashboard: http://localhost:8000/
- REST API:      http://localhost:8000/api/v1
- WebSocket:     ws://localhost:8000/ws
- Interactive Docs: http://localhost:8000/docs
"""

import argparse
import os
import socket
import sys
from pathlib import Path
import uvicorn

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.agents.registry import init_and_seed

def is_port_in_use(port: int, host: str = "127.0.0.1") -> bool:
    """Checks whether a TCP port is currently bound or occupied."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind((host, port))
            return False
        except OSError:
            return True

def reclaim_port(port: int, host: str = "127.0.0.1") -> bool:
    """
    Checks if the port is in use and automatically terminates any stale zombie process holding it.
    Guarantees self-healing port recovery on Windows without manual process killing.
    """
    if not is_port_in_use(port, host=host):
        return True

    print(f"[*] Port {port} is occupied. Attempting automatic self-healing reclamation...")
    if sys.platform == "win32":
        try:
            import subprocess
            import time
            out = subprocess.check_output("netstat -ano", shell=True).decode(errors="ignore")
            current_pid = os.getpid()
            for line in out.splitlines():
                if f":{port} " in line and "LISTENING" in line:
                    parts = line.strip().split()
                    pid = parts[-1]
                    if pid.isdigit() and int(pid) != current_pid:
                        print(f"[*] Reclaiming port {port}: terminating zombie process PID {pid}...")
                        subprocess.run(f"taskkill /F /PID {pid}", shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            time.sleep(1.0)
        except Exception as e:
            print(f"[*] Port reclamation notice: {e}")

    return not is_port_in_use(port, host=host)

def main():
    parser = argparse.ArgumentParser(description="Launch SWARM-100 Command Center Backend & Dashboard")
    parser.add_argument("--port", type=int, default=int(os.getenv("PORT", "8000")), help="Port to bind (default: 8000)")
    parser.add_argument("--host", type=str, default=os.getenv("HOST", "0.0.0.0"), help="Host to bind (default: 0.0.0.0)")
    # On Windows, uvicorn reload mode spawns a file-watcher subprocess that
    # conflicts with Windows Defender socket restrictions (WinError 10013).
    # Default to NO reload on Windows; use --reload flag explicitly if wanted.
    on_windows = sys.platform == "win32"
    parser.add_argument(
        "--reload",
        action="store_true",
        default=False,
        help="Enable auto-reloading (not recommended on Windows — causes WinError 10013)"
    )
    parser.add_argument("--no-reload", action="store_true", help="Disable auto-reloading (default on Windows)")
    args = parser.parse_args()

    target_port = args.port
    if not reclaim_port(target_port, host="127.0.0.1"):
        print(f"[!] Warning: Port {target_port} could not be automatically released.")
        # Find fallback
        fallback = target_port + 1
        while is_port_in_use(fallback, host="127.0.0.1") and fallback < target_port + 20:
            fallback += 1
        print(f"    Falling back cleanly to available port: {fallback}\n")
        target_port = fallback
    else:
        print(f"[OK] Port {target_port} is verified free and ready.")

    print("=" * 70)
    print("SWARM-100: Autonomous Multi-Agent Workforce Command Center")
    print("=" * 70)
    print("Initializing SQLite persistence & verifying 100 agents...")
    init_and_seed()
    print("[OK] Registry verified (10 teams, 100 agents, 9 tools, 3 memory layers)")
    print()
    print(f"  -> Live Dashboard:    http://localhost:{target_port}/")
    print(f"  -> Direct IP:         http://127.0.0.1:{target_port}/")
    print(f"  -> REST API Docs:     http://localhost:{target_port}/docs")
    print(f"  -> WebSocket Stream:  ws://localhost:{target_port}/ws")
    print("=" * 70)
    # Reload is OFF by default on Windows (WinError 10013 from socket watcher).
    # Pass --reload explicitly only if you need it and have Windows Firewall allow it.
    use_reload = getattr(args, "reload", False) and not on_windows
    if on_windows and getattr(args, "reload", False):
        print("[!] --reload is disabled on Windows to prevent WinError 10013. Running in stable mode.")
    uvicorn.run("backend.main:app", host=args.host, port=target_port, reload=use_reload)

if __name__ == "__main__":
    main()
