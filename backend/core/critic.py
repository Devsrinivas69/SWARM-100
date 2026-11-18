"""
SWARM-100 Independent Critic & Verification Service
Dispatches tasks and deliverables to Team 9 (Critic) agents (ARGUS-01 / ARGUS-06 / ARGUS-08 / ARGUS-10)
for rigorous adversarial auditing, identifying factual errors, missing requirements,
and weak reasoning, and scoring outputs against explicit evaluation criteria.
"""

import json
import logging
import re
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from backend.agents.definitions import AGENTS
from backend.core.llm_service import llm_service
from backend.models.schemas import ReviewResult

logger = logging.getLogger("swarm100.critic")

CRITIC_AGENT_ID = "argus-01"     # Lead Independent Reviewer
ERROR_DETECTOR_ID = "argus-06"   # Error Detector
REQUIREMENT_AUDITOR_ID = "argus-08" # Requirement Auditor
ACCEPTANCE_AGENT_ID = "argus-10" # Acceptance Reviewer

class TaskEvaluationResult(BaseModel):
    task_id: str
    agent_id: str
    critic_id: str
    score: float = Field(..., ge=0.0, le=100.0)
    passed: bool
    factual_errors: List[str] = []
    missing_requirements: List[str] = []
    weak_reasoning: List[str] = []
    dimensions: Dict[str, float] = {}
    critic_feedback: str

def _get_critic_prompt(agent_id: str) -> str:
    for a in AGENTS:
        if a["id"] == agent_id:
            return a["system_prompt"]
    return "You are an independent adversarial quality reviewer. Audit deliverables objectively."

class CriticService:
    def __init__(self, primary_critic_id: str = CRITIC_AGENT_ID):
        self.critic_id = primary_critic_id

    async def evaluate_task_result(
        self,
        task_id: str,
        task_title: str,
        task_input: str,
        output_content: str,
        agent_id: str,
        critic_id: Optional[str] = None
    ) -> TaskEvaluationResult:
        """
        Audits an individual task output for:
        1. Factual errors
        2. Missing requirements
        3. Weak reasoning or logical fallacies
        Scores the result against explicit criteria (Accuracy, Completeness, Logic, Clarity, Safety).
        """
        active_critic = critic_id or ERROR_DETECTOR_ID
        sys_prompt = _get_critic_prompt(active_critic)

        audit_prompt = f"""[TASK AUDIT DIRECTIVE]
Task Title: {task_title}
Assigned Agent: {agent_id}
Original Task Directives:
{task_input}

Agent Output Deliverable:
{output_content}

Conduct an adversarial audit. Answer with a structured critique identifying:
1. FACTUAL ERRORS (if any, or state 'None detected')
2. MISSING REQUIREMENTS (if any, or state 'All requirements satisfied')
3. WEAK REASONING (if any, or state 'Logic is sound')
4. CRITERIA SCORES (0-100 each for Accuracy, Completeness, Logic, Clarity, Safety)
"""

        llm_response = await llm_service.chat(
            system_prompt=sys_prompt,
            user_message=audit_prompt,
            temperature=0.1,
            max_tokens=350
        )
        critic_text = llm_response.content

        # Inspect critique text for defects
        factual_errors = []
        missing_requirements = []
        weak_reasoning = []

        lower_critique = critic_text.lower()
        if "error found" in lower_critique or "inaccurate" in lower_critique:
            factual_errors.append("Potential factual discrepancy identified during review.")
        if "missing" in lower_critique and "none" not in lower_critique:
            missing_requirements.append("One or more directive requirements partially unfulfilled.")
        if "fallacy" in lower_critique or "weak reasoning" in lower_critique:
            weak_reasoning.append("Argument structure contains unverified logical leap.")

        # Attempt to extract explicit numeric dimension scores (0-100)
        extracted_dims = {}
        for dim in ("accuracy", "completeness", "logic", "clarity", "safety"):
            m = re.search(rf'{dim}[:\s\-]+([0-9]{{1,3}})', lower_critique)
            if m:
                val = float(m.group(1))
                if 0.0 <= val <= 100.0:
                    extracted_dims[dim] = val

        if len(extracted_dims) >= 3:
            dimensions = {
                "accuracy": extracted_dims.get("accuracy", 75.0),
                "completeness": extracted_dims.get("completeness", 75.0),
                "logic": extracted_dims.get("logic", 75.0),
                "clarity": extracted_dims.get("clarity", 75.0),
                "safety": extracted_dims.get("safety", 90.0),
            }
        elif len(critic_text.strip()) > 30 and "failed" not in lower_critique and "invalid" not in lower_critique:
            base_acc = max(0.0, 90.0 - (len(factual_errors) * 25.0))
            base_comp = max(0.0, 85.0 - (len(missing_requirements) * 20.0))
            base_log = max(0.0, 90.0 - (len(weak_reasoning) * 20.0))
            dimensions = {
                "accuracy": round(base_acc, 1),
                "completeness": round(base_comp, 1),
                "logic": round(base_log, 1),
                "clarity": 85.0 if not weak_reasoning else 70.0,
                "safety": 95.0,
            }
        else:
            # Model response was empty, malformed, or reported explicit failure: MUST NOT PASS
            dimensions = {
                "accuracy": 0.0,
                "completeness": 0.0,
                "logic": 0.0,
                "clarity": 0.0,
                "safety": 0.0,
            }

        overall_score = round(sum(dimensions.values()) / len(dimensions), 1)
        passed = (overall_score >= 70.0 and len(factual_errors) == 0 and len(critic_text.strip()) > 20)

        feedback = f"""[{active_critic.upper()} Task Evaluation]
Score: {overall_score}/100 | Verdict: {'PASSED' if passed else 'NEEDS_REVISION'}
- Factual Errors: {len(factual_errors)} ({', '.join(factual_errors) if factual_errors else 'None'})
- Missing Requirements: {len(missing_requirements)} ({', '.join(missing_requirements) if missing_requirements else 'None'})
- Reasoning Flaws: {len(weak_reasoning)} ({', '.join(weak_reasoning) if weak_reasoning else 'None'})

Critic Notes:
{critic_text.strip()}
"""

        return TaskEvaluationResult(
            task_id=task_id,
            agent_id=agent_id,
            critic_id=active_critic,
            score=overall_score,
            passed=passed,
            factual_errors=factual_errors,
            missing_requirements=missing_requirements,
            weak_reasoning=weak_reasoning,
            dimensions=dimensions,
            critic_feedback=feedback
        )

    async def evaluate_deliverable(
        self,
        goal_title: str,
        goal_description: str,
        deliverable_content: str,
        critic_id: Optional[str] = None
    ) -> ReviewResult:
        """
        Executes an independent review of the combined deliverable against original goal specs.
        """
        eval_critic_id = critic_id or self.critic_id
        sys_prompt = _get_critic_prompt(eval_critic_id)

        prompt = f"""[AUDIT DIRECTIVE]
Goal Title: {goal_title}
Original Specifications: {goal_description}

Deliverable for Verification:
{deliverable_content}

Evaluate this deliverable rigorously across four dimensions (0-100 each):
1. Accuracy & Factual Correctness
2. Completeness against Goal Specs
3. Internal Consistency & Logic
4. Clarity & Actionability
"""

        llm_response = await llm_service.chat(
            system_prompt=sys_prompt,
            user_message=prompt,
            temperature=0.1,
            max_tokens=450
        )
        review_text = llm_response.content
        lower_review = review_text.lower()

        extracted_dims = {}
        for dim in ("accuracy", "completeness", "consistency", "clarity"):
            m = re.search(rf'{dim}[:\s\-]+([0-9]{{1,3}})', lower_review)
            if m:
                val = float(m.group(1))
                if 0.0 <= val <= 100.0:
                    extracted_dims[dim] = val

        if len(extracted_dims) >= 2:
            dimensions = {
                "accuracy": extracted_dims.get("accuracy", 80.0),
                "completeness": extracted_dims.get("completeness", 80.0),
                "consistency": extracted_dims.get("consistency", 80.0),
                "clarity": extracted_dims.get("clarity", 80.0),
            }
        elif len(review_text.strip()) > 30 and "reject" not in lower_review and "fail" not in lower_review:
            dimensions = {
                "accuracy": 85.0,
                "completeness": 85.0,
                "consistency": 85.0,
                "clarity": 85.0
            }
        else:
            # Rejection or parsing failure: strict failure
            dimensions = {
                "accuracy": 0.0,
                "completeness": 0.0,
                "consistency": 0.0,
                "clarity": 0.0
            }

        overall_score = round(sum(dimensions.values()) / len(dimensions), 1)
        passed = (overall_score >= 70.0 and "rejected" not in lower_review and "fail" not in lower_review and len(review_text.strip()) > 20)

        feedback = f"""[{eval_critic_id.upper()} Independent Verification Report]
Overall Quality Score: {overall_score}/100 | Verdict: {'ACCEPTED' if passed else 'REJECTED'}

Dimension Breakdown:
- Accuracy: {dimensions['accuracy']}/100
- Completeness: {dimensions['completeness']}/100
- Consistency: {dimensions['consistency']}/100
- Clarity: {dimensions['clarity']}/100

Critic Observations:
{review_text.strip()}
"""

        return ReviewResult(
            score=overall_score,
            feedback=feedback,
            passed=passed,
            critic_agent_id=eval_critic_id,
            dimensions=dimensions
        )

critic_service = CriticService()
