"""
Agent Capability Matcher
Matches task specifications and capability requirements to the most appropriate
specialist agent among the 100 SWARM-100 agents.
"""

from typing import List, Optional
from backend.agents.definitions import AGENTS, AGENTS_BY_TEAM

# Team domain mapping keywords
TEAM_DOMAIN_KEYWORDS = {
    1: ["strategy", "planning", "decompose", "priority", "schedule", "resource", "feasibility", "decision", "roadmap", "project"],
    2: ["research", "web", "source", "literature", "competitive", "trend", "fact", "evidence", "synthesize", "dossier"],
    3: ["business", "market", "customer", "sales", "pricing", "monetization", "finance", "revenue", "cost", "growth", "cac", "ltv"],
    4: ["content", "write", "writing", "edit", "copy", "story", "social", "script", "seo", "documentation", "memo", "article"],
    5: ["development", "programming", "code", "software", "frontend", "backend", "database", "api", "bug", "deploy", "architecture"],
    6: ["data", "cleaning", "statistics", "analytics", "visualization", "forecast", "pattern", "anomaly", "experiment", "ab_test"],
    7: ["operations", "workflow", "execution", "file", "automation", "quality_control", "tracking", "checklist", "sop", "monitor"],
    8: ["security", "threat", "permissions", "rbac", "input_validation", "vulnerability", "privacy", "gdpr", "audit_log", "sandbox"],
    9: ["critic", "review", "adversarial", "assumption", "reasoning", "bias", "error", "audit", "acceptance", "validation"],
    10: ["optimization", "performance", "latency", "prompt", "memory", "efficiency", "routing", "continuous_learning"]
}

def match_agent_for_task(
    title: str,
    task_type: str,
    required_capabilities: Optional[List[str]] = None,
    preferred_team_id: Optional[int] = None
) -> str:
    """
    Finds the best matching agent ID from the 100 specialist agents based on:
    1. Exact capability tag match
    2. Role and description relevance
    3. Team domain alignment
    """
    req_caps = set(c.lower() for c in (required_capabilities or []))
    text_corpus = f"{title} {task_type}".lower()

    best_agent_id = None
    best_score = -1.0

    for agent in AGENTS:
        score = 0.0
        agent_caps = set(c.lower() for c in agent["capabilities"])

        # 1. Capability matches (+5 points each)
        common_caps = req_caps.intersection(agent_caps)
        score += len(common_caps) * 5.0

        # 2. Preferred team bonus (+4 points)
        if preferred_team_id and agent["team_id"] == preferred_team_id:
            score += 4.0

        # 3. Domain keyword match in agent role & prompt (+2 points)
        role_lower = agent["role"].lower()
        if any(word in role_lower for word in text_corpus.split()):
            score += 3.0

        team_keywords = TEAM_DOMAIN_KEYWORDS.get(agent["team_id"], [])
        for kw in team_keywords:
            if kw in text_corpus:
                score += 1.5

        # 4. Capability text substring matches (+1 point)
        for cap in agent_caps:
            if cap in text_corpus:
                score += 1.0

        if score > best_score:
            best_score = score
            best_agent_id = agent["id"]

    # Fallback to general strategy or team lead if no strong match
    if not best_agent_id:
        if preferred_team_id and preferred_team_id in AGENTS_BY_TEAM:
            return AGENTS_BY_TEAM[preferred_team_id][0]["id"]
        return "stratos-01"

    return best_agent_id
