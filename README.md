# SWARM-100: Autonomous 100-Agent Orchestration Engine

> **A production-grade, local-first multi-agent orchestration architecture featuring exactly 100 logical agents divided across 10 autonomous teams, powered by local Ollama (`qwen3:4b`), three-tier persistent SQLite memory, independent adversarial critics, and a real-time dark editorial command dashboard.**

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110+-009688.svg)](https://fastapi.tiangolo.com)
[![Ollama](https://img.shields.io/badge/Ollama-qwen3:4b-black.svg)](https://ollama.ai)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Tests Passing](https://img.shields.io/badge/Tests-144%20Passed-brightgreen.svg)]()

---

## 🏛 System Architecture

SWARM-100 coordinates an entire 100-agent workforce across a 12-step autonomous lifecycle—from natural-language goal input to adversarial verification and deliverable synthesis.

```
                              User Goal / Objective
                                       │
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                       SWARM-100 CENTRAL ORCHESTRATOR                        │
├─────────────────────────────────────────────────────────────────────────────┤
│ 1. Goal Classification   4. Task DAG Decomposition   7. SQLite Queueing     │
│ 2. Capability Matching   5. Dependency Mapping       8. Worker Pool Dispatch│
│ 3. Agent Assignment      6. Priority Ordering        9. Concurrency Lock    │
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       │
                 ┌─────────────────────┴─────────────────────┐
                 ▼                                           ▼
┌─────────────────────────────────┐         ┌─────────────────────────────────┐
│     10 SPECIALIST TEAMS         │         │     THREE-TIER MEMORY SYSTEM    │
│     (100 Distinct Agents)       │         ├─────────────────────────────────┤
│ • Team 1:  Strategy (STRATOS)   │         │ Layer 1: Agent Memory           │
│ • Team 2:  Research (RECON)     │◄───────►│          Past tasks & lessons   │
│ • Team 3:  Business (VENTURE)   │         │ Layer 2: Project Memory         │
│ • Team 4:  Content (SCRIBE)     │         │          Milestones & artifacts │
│ • Team 5:  Development (FORGE)  │         │ Layer 3: Global Knowledge       │
│ • Team 6:  Data (METRIC)        │         │          Verified heuristics    │
│ • Team 7:  Operations (NEXUS)   │         └─────────────────────────────────┘
│ • Team 8:  Security (SENTINEL)  │                          │
│ • Team 9:  Critic (ARGUS)       │◄─────────────────────────┘
│ • Team 10: Optimization (APEX)  │
└────────────────┬────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                 ADVERSARIAL CRITIC AUDIT & VERIFICATION                     │
│ Audits Accuracy, Completeness, Logic, and Consistency before final delivery.│
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 👥 The 10 Teams (100 Logical Agents)

Each agent possesses an immutable system persona, distinct role, granular capability tags, performance scoring, and persistent memory reference.

| # | Team | Prefix | Domain Scope |
|:---:|---|:---:|---|
| **1** | **Strategy** | `stratos-01..10` | Goal decomposition, risk assessment, project planning, coordination |
| **2** | **Research** | `recon-01..10` | Information retrieval, literature analysis, competitive intelligence |
| **3** | **Business** | `venture-01..10` | Market sizing (TAM/SAM/SOM), customer personas, unit economics |
| **4** | **Content** | `scribe-01..10` | Technical documentation, copywriting, editorial synthesis |
| **5** | **Development** | `forge-01..10` | System architecture, backend APIs, clean code, debugging |
| **6** | **Data** | `metric-01..10` | Data cleaning, statistical modeling, insights, visualization |
| **7** | **Operations** | `nexus-01..10` | Task execution, workflow scheduling, process automation |
| **8** | **Security** | `sentinel-01..10` | Threat modeling (STRIDE), permissions audit, vulnerability review |
| **9** | **Critic** | `argus-01..10` | Adversarial review, hallucination detection, acceptance audits |
| **10** | **Optimization** | `apex-01..10` | Prompt improvement, workflow benchmarking, efficiency tuning |

---

## 🏭 Autonomous Product Foundry (Software Factory)

SWARM-100 transforms natural-language product visions into fully realized, tested, and certified codebases inside `workspace/projects/<slug>`:

```
[ Natural Language Product Intent ]
                 │
                 ▼
 01. SPECIFICATION & ARCHITECTURE MANIFEST (forge-02 Architect)
     Multi-file component graph, interfaces, schemas, and test expectations.
                 │
                 ▼
 02. MULTI-FILE CODE SYNTHESIS (Team 5 Development Engineers)
     app.py, storage.py, test_app.py, requirements.txt, and README.md.
                 │
                 ▼
 03. SAST SECURITY & THREAT AUDIT (cipher-04 Security Auditor)
     Scans for dynamic eval, command injection, and hardcoded credentials.
                 │
                 ▼
 04. SANDBOXED TESTING & AUTONOMOUS SELF-HEALING (forge-07 Debugger)
     Executes isolated subprocess pytest assertions; repairs defects up to 3 cycles.
                 │
                 ▼
 05. PACKAGING & LAUNCH CERTIFICATION (argus-01 Critic Lead)
     Weighted production scoring (Architecture, Quality, Security, Tests).
```

### Foundry API Endpoints
- `POST /api/v1/foundry/build`: Synthesizes and tests a complete software product.
- `GET /api/v1/foundry/projects`: Lists all synthesized workspace projects with file and test metrics.
- `GET /api/v1/foundry/projects/{slug}`: Returns the complete file tree, source code, and certification.
- `GET /api/v1/foundry/projects/{slug}/file`: Reads individual source files with path traversal security.
- `POST /api/v1/foundry/projects/{slug}/test`: Runs the automated test suite in an isolated subprocess.

---

## ⚡ Quickstart Guide

### 1. Prerequisites
- **Python**: Version 3.10 or higher
- **Ollama**: Download and install from [ollama.ai](https://ollama.ai)

### 2. Start & Prepare Ollama
In a terminal, verify that Ollama is running and pull the designated model:
```bash
# Verify Ollama is running
ollama serve

# Pull the lightweight Qwen3 4B reasoning model
ollama pull qwen3:4b
```

### 3. Clone & Install Dependencies
```bash
git clone https://github.com/Devsrinivas69/SWARM-100.git
cd SWARM-100

# Optional: Create a virtual environment
python -m venv venv
# On Windows:
.\venv\Scripts\activate
# On Linux/macOS:
source venv/bin/activate

# Install required packages
pip install -r requirements.txt
```

### 4. Seed Registry & Run the Server
The application automatically creates and migrates the SQLite schema in `data/swarm100.db`, and seeds all 100 agents:
```bash
python scripts/run_server.py
```
*Alternatively with Uvicorn:*
```bash
uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
```

---

## 🖥 Dashboard & API Access

Once running, navigate to:

- **Real-Time Command Dashboard**: [http://localhost:8000/](http://localhost:8000/)
- **Interactive OpenAPI Docs**: [http://localhost:8000/docs](http://localhost:8000/docs)
- **Live WebSocket Stream**: `ws://localhost:8000/ws`

### Dashboard Pages
1. **Command Center**: Real-time workforce telemetry, goal input form (Start, Pause, Resume, Stop), and live activity stream.
2. **Agent Workforce**: Filterable roster of all 100 agents with role details, system instructions, and task counts.
3. **Teams**: 10 domain team cards with member rosters.
4. **Task Board**: Real-time multi-column Kanban board (`Pending`, `Running`, `Reviewing`, `Completed`, `Failed`) with raw output inspector.
5. **Execution Timeline**: Chronological Gantt execution stream with token and latency telemetry.
6. **Agent Memory**: Three-tier memory inspector (Layer 1 Agent, Layer 2 Project, Layer 3 Global Knowledge).
7. **Critic Reviews**: Adversarial audit results by Team 9 Critic agents with dimension scores.
8. **Improvement History**: Prompt evolution history, benchmark comparisons, and safety verification results.
9. **Settings & Tool Registry**: Tool permissions and human-in-the-loop approval management.
10. **Product Foundry**: Autonomous software factory with live 5-stage progress stepper, project selector, split-pane file explorer, code viewer, and real-time pytest execution terminal.

---

## 🛠 General-Purpose Tool Sandbox

SWARM-100 includes a sandboxed tool registry with permission levels and audit logging:

| Tool | Permission Level | Description |
|---|:---:|---|
| `calculator` | `read_only` | Safe AST arithmetic evaluation |
| `datetime_tool` | `read_only` | Current time, date math, timestamps |
| `workspace_file_reader` | `read_only` | Confined file inspection in approved workspace |
| `workspace_file_creator` | `workspace_write` | Sandboxed file generation within project boundaries |
| `structured_data_analysis`| `read_only` | Schema analysis, statistical summaries |
| `csv_processor` | `read_only` | Delimited tabular querying and column filtering |
| `document_summarizer` | `read_only` | Text reduction and key-takeaway extraction |
| `project_inspector` | `read_only` | Workspace folder and code manifest inspection |
| `restricted_code_tester` | `restricted_execution`| Timeout-isolated subprocess code runner *(Requires approval)* |

---

## 🧪 Verification & Testing

SWARM-100 is backed by a full test suite with 100% test pass rates:

```bash
# Run the complete test suite (144 passing tests)
python -m pytest tests/

# Run the 17-point end-to-end system audit
python scripts/full_audit.py

# Run a live multi-agent pipeline execution test
python scripts/pipeline_test.py
```

### Audited Guarantees
- ✅ Exactly 100 logical agents exist.
- ✅ All 10 teams contain 10 agents.
- ✅ Agent identities and memory keys are unique.
- ✅ Live model calls execute through Ollama (`qwen3:4b`).
- ✅ Worker concurrency limits are strictly enforced.
- ✅ Tasks, memories, and prompt iterations persist across restarts.
- ✅ Zero fabricated activity or mock statistics; 100% genuine backend data.

---

## 📄 License

This project is licensed under the [MIT License](LICENSE).
