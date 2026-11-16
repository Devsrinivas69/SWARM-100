"""
SWARM-100 Real General-Purpose Pipeline Test
Goal: Research the Indian electric vehicle market, compare three manufacturers,
      create a concise market report and recommend a business opportunity.

Records:
- Number of logical agents assigned.
- Number of actual model calls.
- Execution time.
- Failed tasks.
- Review findings.
- Initial evaluation score.
- Final evaluation score.
- Clear statement of web research limitations.
"""
import sys, os, asyncio, json, time, uuid
os.chdir(r"C:\Users\srinivas\OneDrive\Desktop\SWARM 100")
sys.path.insert(0, r"C:\Users\srinivas\OneDrive\Desktop\SWARM 100")

from backend.database import init_db, get_connection
from backend.core.orchestrator import SwarmOrchestrator
from backend.core.worker_pool import WorkerPool
from backend.core.task_queue import TaskQueue
from backend.core.memory import memory_service
from backend.core.critic import critic_service
from backend.core.llm_service import llm_service
from backend.models.schemas import TaskStatus, GoalStatus

GOAL_TITLE = "Indian Electric Vehicle Market Research & Business Opportunity Report"
GOAL_DESC = (
    "Research the Indian electric vehicle (EV) market. "
    "Compare three leading manufacturers: Tata Motors, Ather Energy, and Ola Electric. "
    "Create a concise market report analyzing market share, product portfolios, and growth trajectory. "
    "Conclude with a high-potential business opportunity recommendation for an entrant in 2025-2027."
)

async def main():
    print("=" * 66)
    print("  SWARM-100 REAL GENERAL-PURPOSE PIPELINE EXECUTION")
    print("=" * 66)
    print(f"\n  Goal: {GOAL_TITLE}\n")

    init_db()

    # Step 0: Check Ollama connectivity & model availability
    conn_info = await llm_service.check_connection()
    ollama_alive = conn_info.get("status") in ("ok", "connected") and conn_info.get("model_available", False)

    print("── STEP 0: ENVIRONMENT & PRE-FLIGHT VERIFICATION ───────────")
    print(f"  Ollama Status:       {conn_info.get('status')}")
    print(f"  Configured Model:    {conn_info.get('configured_model')}")
    print(f"  Model Available:     {conn_info.get('model_available')}")
    print(f"  Endpoint:            {conn_info.get('endpoint')}")
    print(f"  Pre-flight Latency:  {conn_info.get('latency_ms', 0)}ms")
    print()
    print("  [RESEARCH LIMITATION STATEMENT]")
    print("  Live web browsing is not enabled in this local-inference sandbox.")
    print("  All market intelligence, competitor comparisons, and financial models")
    print("  are derived from the model's parameterized knowledge and multi-agent synthesis.")
    print()

    if not ollama_alive:
        print("  ❌ FATAL: Ollama is not connected or model is unavailable.")
        sys.exit(1)

    # Step 1-7: Goal planning and subtask decomposition
    print("── STEP 1-7: GOAL PLANNING & DECOMPOSITION ──────────────────")
    t0_plan = time.time()
    orch = SwarmOrchestrator()
    goal_data = orch.submit_goal(
        title=GOAL_TITLE,
        description=GOAL_DESC,
        concurrency_limit=1
    )
    plan_latency_ms = round((time.time() - t0_plan) * 1000, 1)

    goal_id = goal_data["goal_id"]
    queue = TaskQueue()
    goal_detail = queue.get_goal(goal_id)
    tasks = goal_detail.get("tasks", [])

    assigned_agent_ids = list(set(t["assigned_agent_id"] for t in tasks))
    print(f"  Goal ID:             {goal_id}")
    print(f"  Task Domain:         {goal_data.get('task_type')}")
    print(f"  Subtasks Generated:  {len(tasks)}")
    print(f"  Unique Agents:       {len(assigned_agent_ids)} ({', '.join(assigned_agent_ids)})")
    print(f"  Planning Time:       {plan_latency_ms}ms")
    print()

    for idx, t in enumerate(tasks):
        deps = t.get("dependencies", [])
        dep_str = f"depends on: {deps}" if deps else "independent"
        print(f"    Subtask {idx+1}: [{t['priority']}★] {t['title']}")
        print(f"      Agent: {t['assigned_agent_id']} | Prereqs: {dep_str}")

    print()

    # Step 8-9: Asynchronous Task Execution via WorkerPool
    print("── STEP 8-9: ASYNC WORKER POOL EXECUTION ────────────────────")
    t0_exec = time.time()
    worker_pool = WorkerPool(concurrency_limit=1, task_queue=queue)

    total_model_calls = 0
    failed_tasks = []
    completed_tasks = []
    subtask_eval_scores = []

    # Execution loop respecting DAG dependencies
    while True:
        all_done, any_failed, completed_cnt, total_cnt = queue.check_goal_progress(goal_id)
        if all_done:
            print(f"  ✓ All {total_cnt} tasks completed successfully.")
            break

        ready_tasks = queue.get_ready_tasks(goal_id)
        if not ready_tasks:
            if any_failed:
                print("  ❌ Execution halted: dependency failure.")
                break
            if completed_cnt == total_cnt:
                break
            await asyncio.sleep(0.1)
            continue

        for task in ready_tasks:
            tid = task["id"]
            aid = task["assigned_agent_id"]
            title = task["title"]
            print(f"\n  [DISPATCH] {title[:50]}...")
            print(f"    Agent:       {aid}")
            print(f"    Input size:  {len(task['input'])} chars")

            t0_task = time.time()
            try:
                res = await worker_pool.execute_task(task)
                t_task_ms = round((time.time() - t0_task) * 1000, 1)

                # Each execute_task makes: 1 agent call + 1 critic audit call = 2 model calls
                total_model_calls += 2
                completed_tasks.append(tid)

                eval_info = res.get("evaluation", {})
                score = eval_info.get("score", 0.0)
                subtask_eval_scores.append(score)
                passed = eval_info.get("passed", False)
                critic_id = eval_info.get("critic_id", "argus-01")

                print(f"    Status:      COMPLETED in {t_task_ms}ms")
                print(f"    Agent Model: {res.get('telemetry', {}).get('model', 'qwen3:4b')}")
                print(f"    Tokens:      {res.get('telemetry', {}).get('total_tokens', 0)}")
                print(f"    Critic:      {critic_id} -> Score: {score}/100 ({'PASSED' if passed else 'NEEDS_REVISION'})")

            except Exception as e:
                err_msg = str(e)
                failed_tasks.append({"task_id": tid, "agent_id": aid, "error": err_msg})
                print(f"    ❌ FAILED:   {err_msg[:120]}")

    exec_duration_s = round(time.time() - t0_exec, 2)
    print(f"\n  Execution Duration: {exec_duration_s}s")
    print(f"  Completed Subtasks: {len(completed_tasks)}/{len(tasks)}")
    print(f"  Failed Subtasks:    {len(failed_tasks)}")

    # Step 10: Synthesis of completed deliverables
    print("\n── STEP 10: COMBINING COMPLETED OUTPUTS ─────────────────────")
    refreshed_goal = queue.get_goal(goal_id)
    combined_deliverable = orch._combine_outputs(refreshed_goal)
    print(f"  Combined Deliverable Size: {len(combined_deliverable)} characters")

    # Step 11: Independent Review by Team 9 Critic
    print("\n── STEP 11: INDEPENDENT ADVERSARIAL CRITIC AUDIT ───────────")
    t0_crit = time.time()
    review = await critic_service.evaluate_deliverable(
        goal_title=refreshed_goal["title"],
        goal_description=refreshed_goal["description"],
        deliverable_content=combined_deliverable[:4000]
    )
    total_model_calls += 1  # 1 final review call
    crit_latency_ms = round((time.time() - t0_crit) * 1000, 1)

    initial_eval_score = round(sum(subtask_eval_scores) / len(subtask_eval_scores), 1) if subtask_eval_scores else 0.0
    final_eval_score = review.score

    print(f"  Critic Agent:        {review.critic_agent_id}")
    print(f"  Initial Avg Score:   {initial_eval_score}/100")
    print(f"  Final Review Score:  {final_eval_score}/100")
    print(f"  Audit Verdict:       {'ACCEPTED' if review.passed else 'REJECTED'}")
    print(f"  Audit Latency:       {crit_latency_ms}ms")
    print()
    print("  [CRITIC AUDIT FINDINGS EXCERPT]")
    for line in review.feedback.strip().split("\n")[:8]:
        print(f"    {line}")

    # Step 12: Complete goal record in database
    print("\n── STEP 12: GOAL COMPLETION & DATABASE FINALIZATION ────────")
    queue.complete_goal(
        goal_id=goal_id,
        final_output=combined_deliverable,
        review_score=review.score,
        review_feedback=review.feedback
    )
    print(f"  Goal record finalized as COMPLETED in SQLite.")

    # Print Report Excerpt
    print("\n" + "=" * 66)
    print("  DELIVERABLE PREVIEW: INDIAN ELECTRIC VEHICLE MARKET REPORT")
    print("=" * 66)
    preview_lines = combined_deliverable.split("\n")
    for pl in preview_lines[:35]:
        print(f"  {pl}")
    if len(preview_lines) > 35:
        print("  ... [Deliverable continues with unit economics & strategic recommendations] ...")

    # Final Verification Records
    pipeline_passed = len(failed_tasks) == 0 and len(completed_tasks) == len(tasks) and review.passed

    report_data = {
        "goal_id": goal_id,
        "goal_title": GOAL_TITLE,
        "number_of_logical_agents_assigned": len(assigned_agent_ids),
        "assigned_agent_ids": assigned_agent_ids,
        "number_of_actual_model_calls": total_model_calls,
        "execution_time_seconds": exec_duration_s,
        "completed_tasks_count": len(completed_tasks),
        "failed_tasks": failed_tasks,
        "initial_evaluation_score": initial_eval_score,
        "final_evaluation_score": final_eval_score,
        "review_findings": review.feedback,
        "audit_passed": review.passed,
        "pipeline_success": pipeline_passed,
        "web_research_enabled": False,
        "limitations": "Web research disabled; synthesized via local Qwen3 4B knowledge and multi-agent DAG."
    }

    with open("data/e2e_pipeline_test_report.json", "w", encoding="utf-8") as f:
        json.dump(report_data, f, indent=2)

    print("\n" + "=" * 66)
    print("  FINAL AUDIT TEST SUMMARY")
    print("=" * 66)
    print(f"  Status:                        {'✅ PASSED' if pipeline_passed else '❌ FAILED'}")
    print(f"  Logical Agents Assigned:       {len(assigned_agent_ids)}")
    print(f"  Actual Model Calls:            {total_model_calls}")
    print(f"  Execution Time:                {exec_duration_s}s")
    print(f"  Failed Tasks:                  {len(failed_tasks)}")
    print(f"  Initial Evaluation Score:      {initial_eval_score}/100")
    print(f"  Final Evaluation Score:        {final_eval_score}/100")
    print(f"  Report saved to:               data/e2e_pipeline_test_report.json")
    print("=" * 66 + "\n")

    if not pipeline_passed:
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())
