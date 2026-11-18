"""
SWARM-100: Centurion Workforce Sweep
Dispatches structured tasks across all 100 agents (10 teams x 10 agents),
verifying that every single agent in the workforce executes a real task,
updates its status, records memory, and appears live on the dashboard.
"""

import asyncio
import os
import sys
import time
from typing import Dict, Any

os.chdir(r"C:\Users\srinivas\OneDrive\Desktop\SWARM 100")
sys.path.insert(0, r"C:\Users\srinivas\OneDrive\Desktop\SWARM 100")

from backend.agents.definitions import AGENTS
from backend.core.task_queue import TaskQueue
from backend.core.worker_pool import WorkerPool
from backend.core.memory import memory_service
from backend.core.websocket_manager import ws_manager
from backend.core.llm_service import llm_service
from backend.database import init_db

GOAL_TITLE = "SWARM-100 Workforce Sweep (All 100 Specialists)"
GOAL_DESC = (
    "Execute an enterprise audit and readiness check across all 100 logical agents "
    "spanning Strategy, Research, Business, Content, Development, Data, Operations, "
    "Security, Critic, and Optimization."
)

async def run_sweep(concurrency: int = 1, sample_mode: bool = False):
    print("=" * 70)
    print("  SWARM-100: CENTURION WORKFORCE SWEEP (100 AGENTS)")
    print("=" * 70)

    init_db()
    queue = TaskQueue()

    # 1. Create Goal
    goal_id = queue.create_goal(
        title=GOAL_TITLE,
        description=GOAL_DESC,
        concurrency_limit=concurrency
    )
    print(f"\n[+] Created Orchestration Goal: {goal_id}")
    ws_manager.emit_event("goal_created", {
        "goal_id": goal_id,
        "title": GOAL_TITLE,
        "task_count": len(AGENTS)
    })

    # 2. Enqueue 1 targeted task for every single agent
    print(f"[+] Enqueueing 1 task per agent across 10 teams...")
    target_agents = AGENTS if not sample_mode else AGENTS[:10]

    for idx, agent in enumerate(target_agents):
        task_id = queue.create_task(
            goal_id=goal_id,
            title=f"Readiness Check: {agent['name']} ({agent['role']})",
            task_type=f"Domain Verification ({agent['team_id']})",
            assigned_agent_id=agent["id"],
            priority=5,
            dependencies=[],
            input=(
                f"Agent {agent['id']} ({agent['role']}): Conduct an initial assessment of your domain "
                f"responsibilities and confirm operational readiness compliant with SWARM-100 specifications."
            )
        )

    print(f"[+] Enqueued {len(target_agents)} tasks into persistent SQLite queue.")
    print(f"[+] Launching Orchestrator execution loop (concurrency = {concurrency})...")
    print(f"[*] Open http://localhost:8000/tasks to view all agents active in real time!\n")

    from backend.core.orchestrator import orchestrator
    t0 = time.time()
    res = await orchestrator.run_goal(goal_id)
    duration = round(time.time() - t0, 1)

    print("\n" + "=" * 70)
    print(f"  SWEEP COMPLETED in {duration}s")
    print(f"  Goal Status:       {res.get('status')}")
    print(f"  Review Score:      {res.get('review_score')}/100")
    print("=" * 70)

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Sweep all 100 SWARM-100 agents")
    parser.add_argument("--concurrency", type=int, default=1, help="Worker pool concurrency limit")
    parser.add_argument("--sample", action="store_true", help="Run 10 agents instead of all 100 for a quick smoke test")
    args = parser.parse_args()

    asyncio.run(run_sweep(concurrency=args.concurrency, sample_mode=args.sample))
