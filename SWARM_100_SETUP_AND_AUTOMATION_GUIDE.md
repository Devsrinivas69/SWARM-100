# SWARM-100: Complete Setup, Architecture & Automation Guide

> **GitHub Repository**: [https://github.com/Devsrinivas69/SWARM-100](https://github.com/Devsrinivas69/SWARM-100)  
> **Architecture**: Autonomous 100-Agent Workforce Command Center  
> **Target Runtimes**: Local Python 3.10+, Local Ollama LLM, SQLite WAL Persistence, Cloudflare Tunnel

---

## 1. What is SWARM-100?

**SWARM-100** is an enterprise-grade, local-first multi-agent orchestration architecture featuring **exactly 100 specialist agents** divided across **10 autonomous domain teams**. It coordinates complex real-world missions—from market research and financial modeling to autonomous software synthesis and adversarial quality assurance.

### Core Architecture Highlights
- **10 Autonomous Teams (100 Agents)**:
  1. **Team 1 (STRATOS - Strategy & Coordination)**: Agents 01–10 (Planning, DAG decomposition, project management, resource routing).
  2. **Team 2 (RECON - Market Research & Intelligence)**: Agents 11–20 (Web research, competitor intelligence, factual synthesis).
  3. **Team 3 (VENTURE - Business & Finance)**: Agents 21–30 (Unit economics, financial modeling, pricing, TAM/SAM/SOM).
  4. **Team 4 (SCRIBE - Marketing & Content)**: Agents 31–40 (Copywriting, positioning, user personas, brand strategies).
  5. **Team 5 (FORGE - Product & Development)**: Agents 41–50 (Software engineering, API architecture, code generation).
  6. **Team 6 (METRIC - Data & Analytics)**: Agents 51–60 (Statistical analysis, data cleaning, trend forecasting).
  7. **Team 7 (NEXUS - Operations & Workflow)**: Agents 61–70 (Process optimization, standard operating procedures, execution tracking).
  8. **Team 8 (SENTINEL - Security & Risk)**: Agents 71–80 (Threat modeling, permissions audits, SAST security review).
  9. **Team 9 (ARGUS - Independent Adversarial Critics)**: Agents 81–90 (Dimensional scoring across Accuracy, Completeness, Logic, Clarity, and Safety; rejection & revision directives).
  10. **Team 10 (APEX - Continuous Optimization)**: Agents 91–100 (Prompt tuning, workflow benchmarking, efficiency improvements).

- **Three-Tier Persistent Memory System**:
  - **Layer 1 (Agent Memory)**: Individual execution memories, successful strategies, and failure patterns.
  - **Layer 2 (Project Memory)**: Goal-specific shared deliverables, task dependencies, and milestones.
  - **Layer 3 (Global Knowledge)**: Cross-mission verified heuristics, proven design patterns, and anti-patterns.
- **Autonomous ReAct Tool Loop**: Specialist agents dynamically invoke search tools, web scrapers, calculators, and sandboxed python execution.
- **Real-Time Web Dashboard**: Dark editorial UI with live WebSocket telemetry, 5-stage Product Foundry, interactive Kanban board, and Critic Audit modals.

---

## 2. Prerequisites

Before installing SWARM-100, ensure your environment has:
1. **Operating System**: Windows 10/11, macOS, or Linux.
2. **Python**: Python 3.10 or higher (`python --version`).
3. **Git**: Installed and configured (`git --version`).
4. **Ollama**: Download and install from [https://ollama.ai](https://ollama.ai).

---

## 3. Step-by-Step Installation & Setup

### Step 1: Clone the Repository
Open a terminal (PowerShell, Command Prompt, or Bash) and clone the repository:
```bash
git clone https://github.com/Devsrinivas69/SWARM-100.git
cd "SWARM 100"
```

### Step 2: Set Up Python Virtual Environment
Creating an isolated virtual environment is recommended:
```bash
# Create virtual environment
python -m venv venv

# Activate on Windows (PowerShell):
.\venv\Scripts\Activate.ps1
# Activate on Windows (Command Prompt):
.\venv\Scripts\activate.bat
# Activate on Linux/macOS:
source venv/bin/activate
```

### Step 3: Install Required Dependencies
Install all project requirements:
```bash
pip install -r requirements.txt
```

### Step 4: Configure and Start Ollama
Ensure Ollama is running and pull the desired local reasoning model:
```bash
# Verify Ollama service is active
ollama list

# Pull the lightweight model (default configuration)
ollama pull qwen2.5:3b
# Or pull other supported models:
ollama pull qwen2.5:7b
ollama pull llama3.2:3b
```

---

## 4. Running SWARM-100

### Option A: One-Click Local Launcher (Windows)
Double-click `START_SWARM.bat` in the project root, or run:
```bat
.\START_SWARM.bat
```
This script automatically:
1. Verifies that Ollama is running.
2. Reclaims port 8000.
3. Initializes the SQLite database (`data/swarm100.db`) and seeds all 100 agent personas.
4. Opens the dashboard at `http://localhost:8000/`.

### Option B: Python CLI Launch
```bash
python scripts/run_server.py --no-reload
```

### Option C: Public Access via Cloudflare Tunnel
To share the dashboard externally or access it remotely:
```bat
.\START_SWARM_PUBLIC.bat
```
This launches the backend and spins up an authenticated Cloudflare Tunnel, generating a secure public HTTPS URL (e.g., `https://random-name.trycloudflare.com`).

---

## 5. Setting Up Automation for SWARM-100

You can automate SWARM-100 missions and audits using three methods:

### Method 1: Scheduled Batch Automation (Windows Task Scheduler / Cron)
You can run automated missions on a schedule using a script or curl trigger.

#### Automated Python Script (`scripts/run_scheduled_mission.py`):
```python
import requests
import json

GOAL_PAYLOAD = {
    "title": "Daily Autonomous Market & Competitor Intelligence Sweep",
    "description": "Team 2 RECON and Team 3 VENTURE will analyze current trends, quantify opportunities, and pass findings to Team 9 ARGUS for QA verification.",
    "concurrency_limit": 1
}

resp = requests.post("http://localhost:8000/api/v1/goals", json=GOAL_PAYLOAD)
if resp.status_code == 200:
    data = resp.json()
    print(f"[OK] Scheduled Goal Created: {data['goal_id']}")
else:
    print(f"[FAIL] Error starting goal: {resp.text}")
```

#### Windows Task Scheduler Setup:
1. Open **Windows Task Scheduler** (`taskschd.msc`).
2. Click **Create Basic Task** -> Name: `SWARM-100 Daily Sweep`.
3. Trigger: Select **Daily** (e.g., at 09:00 AM).
4. Action: **Start a program**.
   - Program/script: `python` (or path to `venv\Scripts\python.exe`).
   - Add arguments: `scripts\run_scheduled_mission.py`.
   - Start in: `C:\Users\srinivas\OneDrive\Desktop\SWARM 100`.

#### Linux/macOS Cron Setup:
```bash
# Run daily at 9:00 AM
0 9 * * * cd /path/to/SWARM-100 && ./venv/bin/python scripts/run_scheduled_mission.py >> logs/cron.log 2>&1
```

---

### Method 2: REST API Webhook Automation
Any external workflow tool (n8n, Make, Zapier, GitHub Actions, or custom webhooks) can trigger SWARM-100 missions:

- **Endpoint**: `POST http://localhost:8000/api/v1/goals`
- **Headers**: `Content-Type: application/json`
- **Body**:
  ```json
  {
    "title": "Autonomous Security & Dependency Audit",
    "description": "Team 8 SENTINEL will run threat modeling and security audits on workspace repositories.",
    "concurrency_limit": 1
  }
  ```
- **Goal Status Polling**: `GET http://localhost:8000/api/v1/goals/{goal_id}`
- **Critic Reviews API**: `GET http://localhost:8000/api/v1/dashboard/critic-reviews`

---

### Method 3: Antigravity Scheduled Automation (`/automation`)
You can use Antigravity's built-in background scheduler to monitor, audit, or trigger SWARM-100 tasks on a recurring schedule without keeping an active terminal open.
Simply type `/automation` in chat to configure a recurring background sidecar (daily, hourly, or weekly).

---

## 6. Verification and Health Check

Run the automated test suite to verify system integrity:
```bash
# Run all unit tests (182+ tests)
pytest tests/

# Run end-to-end audit
python scripts/full_audit.py
```

### Audited Metrics
- **100 Specialist Personas**: Verified distinct capabilities and memory spaces.
- **10 Domain Teams**: Full DAG task routing and priority decomposition.
- **Critic QA Review**: 5-dimension scoring (Accuracy, Completeness, Logic, Clarity, Safety).
- **Zero Mock Data**: Real local LLM generation and SQLite persistence.
