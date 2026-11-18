"""
SWARM-100 Goal Planning & Decomposition Engine
Transforms natural-language user goals into structured, dependency-aware task graphs
and assigns each subtask to optimal specialist agents among the 100 registered agents.
Supports dynamic multi-team fanning out across all 10 teams and up to 100 agents with
customizable workforce density.
"""

import re
from typing import Dict, List, Optional, Tuple, Union
from backend.agents.definitions import AGENTS, AGENTS_BY_TEAM, TEAMS
from backend.core.matcher import match_agent_for_task
from backend.models.schemas import GoalAnalysis, TaskPlanItem

DOMAIN_PATTERNS = [
    ("Software Development", [
        "code", "software", "api", "backend", "frontend", "database", "program", "app",
        "react", "python", "bug", "architecture", "microservice", "microservices", "git",
        "devops", "docker", "services", "system"
    ]),
    ("Data Analysis", [
        "data", "dataset", "statistics", "analytics", "visualization", "forecast", "forecasting",
        "sql", "chart", "metrics", "eda", "regression", "ab test", "outlier"
    ]),
    ("Research", [
        "research", "investigate", "study", "literature", "competitive analysis", "fact check",
        "sources", "paper", "trends", "market study", "evidence", "findings"
    ]),
    ("Business Strategy", [
        "business", "strategy", "market", "pricing", "monetization", "revenue", "competitor",
        "tam", "sam", "som", "business model", "sales", "cac", "ltv", "gtm"
    ]),
    ("Content Creation", [
        "write", "article", "blog", "copy", "content", "script", "social media", "story",
        "newsletter", "seo", "editing", "memo", "press release"
    ]),
    ("Security & Risk", [
        "security", "threat", "vulnerability", "audit", "rbac", "permissions", "cve",
        "penetration", "input validation", "privacy", "gdpr", "compliance"
    ]),
    ("Project Planning", [
        "project plan", "schedule", "milestone", "roadmap", "timeline", "resource allocation",
        "work breakdown", "gantt", "wbs", "coordination", "pmo"
    ]),
    ("Problem Solving", [
        "solve", "problem", "root cause", "troubleshoot", "optimize", "bottleneck",
        "failure mode", "fmea", "constraint", "diagnosis"
    ])
]

CAPABILITY_KEYWORDS = {
    "web_research": ["web", "search", "browse", "source", "find", "online"],
    "fact_checking": ["fact", "verify", "claim", "accurate", "truth"],
    "business_analysis": ["business", "market", "commercial", "enterprise"],
    "financial_modeling": ["finance", "financial", "revenue", "cost", "pro forma", "margin"],
    "software_architecture": ["architecture", "system design", "distributed", "component", "microservices"],
    "programming": ["code", "implement", "script", "program", "algorithm"],
    "api_design": ["api", "rest", "endpoint", "contract", "schema"],
    "data_cleaning": ["clean", "normalize", "sanitize", "nulls", "outliers"],
    "statistics": ["statistical", "anova", "hypothesis", "significance", "distribution"],
    "threat_modeling": ["threat", "attack", "stride", "vulnerability", "security"],
    "independent_review": ["review", "audit", "adversarial", "critique", "validate"]
}

def classify_task_type(text: str, title: Optional[str] = None) -> str:
    """Classifies the natural-language goal into a recognized domain, weighting title heavily."""
    text_lower = text.lower()
    title_lower = (title or "").lower()

    scores = {}
    for domain, keywords in DOMAIN_PATTERNS:
        score = 0.0
        for kw in keywords:
            pattern = r'\b' + re.escape(kw) + r'\b'
            # 2.5x weight if keyword occurs in title
            if title_lower and re.search(pattern, title_lower):
                score += 2.5
            elif re.search(pattern, text_lower):
                score += 1.0

        if score > 0:
            scores[domain] = score

    if not scores:
        return "General Problem Solving"

    return max(scores.items(), key=lambda x: x[1])[0]

def extract_required_capabilities(text: str, task_type: str) -> List[str]:
    """Identifies the required skills and capabilities from goal text."""
    text_lower = text.lower()
    capabilities = set()

    for cap, keywords in CAPABILITY_KEYWORDS.items():
        if any(kw in text_lower for kw in keywords):
            capabilities.add(cap)

    # Ensure baseline capabilities according to domain
    if task_type == "Software Development":
        capabilities.update(["software_architecture", "programming", "api_design"])
    elif task_type == "Data Analysis":
        capabilities.update(["data_cleaning", "statistics", "data_analysis"])
    elif task_type == "Research":
        capabilities.update(["web_research", "source_verification", "summarisation"])
    elif task_type == "Business Strategy":
        capabilities.update(["business_analysis", "market_research", "financial_modeling"])
    elif task_type == "Security & Risk":
        capabilities.update(["threat_modeling", "input_validation", "vulnerability_assessment"])

    return sorted(list(capabilities))

def extract_team_directives(text: str) -> Dict[int, str]:
    """
    Parses user prompt for explicit STAGE <N> or TEAM <N> assignment headers.
    Returns a mapping of team_id (1-10) -> explicit directive chunk.
    """
    directives: Dict[int, str] = {}
    pattern = r'(?im)^(?:[-#* ]*)\s*(?:STAGE|TEAM)\s*(\d+)\s*[:\-\—\.\(]'
    matches = list(re.finditer(pattern, text))

    for i, m in enumerate(matches):
        team_num = int(m.group(1))
        start_idx = m.end()
        end_idx = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        chunk = text[start_idx:end_idx].strip()
        if chunk and 1 <= team_num <= 10:
            directives[team_num] = chunk

    return directives

def resolve_workforce_density(text: str, requested_density: Union[str, int] = "adaptive") -> Tuple[str, int]:
    """
    Resolves the execution density mode and number of agents per team (1 to 10).
    Returns (mode_name, agents_per_team).
    - 'focused': 0 (uses targeted 3-5 subtask templates)
    - 'balanced': 1 agent per team = 10 subtasks across all 10 teams
    - 'comprehensive': 3 agents per team = 30 subtasks across all 10 teams
    - 'full_swarm': 10 agents per team = 100 subtasks across all 100 agents
    """
    if isinstance(requested_density, int):
        clamped = max(1, min(100, requested_density))
        if clamped >= 90:
            return ("full_swarm", 10)
        elif clamped <= 5:
            return ("focused", 0)
        else:
            per_team = max(1, min(10, round(clamped / 10)))
            return ("custom", per_team)

    density_str = str(requested_density).lower().strip()
    if density_str in ("focused", "minimal", "fast", "single_team"):
        return ("focused", 0)
    elif density_str in ("balanced", "standard"):
        return ("balanced", 1)
    elif density_str in ("comprehensive", "deep", "multi_team"):
        return ("comprehensive", 3)
    elif density_str in ("full_swarm", "all_100", "all_teams", "100"):
        return ("full_swarm", 10)

    # Adaptive mode: Inspect prompt content and directives
    full_text_lower = text.lower()
    full_swarm_pattern = r"\b(all 100|100 agents|all teams|every team|complete workforce|full workforce|all specialist agents|all 10 teams|workforce:?\s*all)\b"
    if re.search(full_swarm_pattern, full_text_lower):
        return ("full_swarm", 10)

    team_directives = extract_team_directives(text)
    if len(team_directives) >= 7:
        return ("full_swarm", 10)
    elif len(team_directives) >= 3:
        return ("comprehensive", 3)

    if re.search(r"\b(multi-team|cross-team|comprehensive|deep analysis|enterprise|full scale)\b", full_text_lower):
        return ("comprehensive", 3)

    # By default, single-domain concise prompts use focused templates for fast execution
    return ("focused", 0)

def build_multi_team_plan(
    title: str,
    description: str,
    task_type: str,
    required_caps: List[str],
    agents_per_team: int,
    team_directives: Dict[int, str]
) -> GoalAnalysis:
    """
    Constructs a multi-stage, multi-team DAG spanning all 10 teams according to agents_per_team.
    Enforces clean stage-by-stage DAG dependencies:
    - Stage 1: Team 1 (Strategy) -> Roots (deps: [])
    - Stage 2: Team 2 (Research) & Team 6 (Data) -> Depends on Stage 1
    - Stage 3: Team 3 (Business) & Team 5 (Development) -> Depends on Stage 2
    - Stage 4: Team 4 (Content) & Team 7 (Operations) -> Depends on Stage 3
    - Stage 5: Team 8 (Security) -> Depends on Stage 3 & 4
    - Stage 6: Team 9 (Critic) -> Depends on Stages 3, 4, 5
    - Stage 7: Team 10 (Optimization) -> Depends on Stage 6
    """
    subtasks: List[TaskPlanItem] = []
    task_counter = 0

    # Budget context snippet per task to avoid local CPU prompt bloat while preserving core directives
    context_snippet = description.strip()
    if len(context_snippet) > 800:
        context_snippet = context_snippet[:800].rstrip() + "\n...[Additional context indexed in shared memory]..."

    stages = [
        {"stage": 1, "teams": [1], "name": "Strategic Formulation & Governance"},
        {"stage": 2, "teams": [2, 6], "name": "Market Research & Quantitative Data Intelligence"},
        {"stage": 3, "teams": [3, 5], "name": "Commercial Architecture & Product Engineering"},
        {"stage": 4, "teams": [4, 7], "name": "Brand Communications & Operational SOPs"},
        {"stage": 5, "teams": [8], "name": "Security, Threat Modeling & Regulatory Compliance"},
        {"stage": 6, "teams": [9], "name": "Adversarial Critique & Verification"},
        {"stage": 7, "teams": [10], "name": "System Optimization & Master Synthesis"}
    ]

    stage_task_indices: Dict[int, List[int]] = {s["stage"]: [] for s in stages}

    for s_info in stages:
        s_num = s_info["stage"]
        s_teams = s_info["teams"]

        # Determine upstream dependencies for this stage
        deps: List[str] = []
        if s_num == 1:
            deps = [] # Independent root
        elif s_num == 2:
            # Stage 2 depends on Stage 1 Strategy
            if stage_task_indices[1]:
                deps = [f"task_{stage_task_indices[1][0]}"]
        elif s_num == 3:
            # Stage 3 depends on Stage 2 Research & Data
            d_pool = stage_task_indices[2]
            deps = [f"task_{d_pool[0]}"] if d_pool else []
            if len(d_pool) > 1:
                deps.append(f"task_{d_pool[1]}")
        elif s_num == 4:
            # Stage 4 depends on Stage 3 Business & Tech
            d_pool = stage_task_indices[3]
            deps = [f"task_{d_pool[0]}"] if d_pool else []
        elif s_num == 5:
            # Stage 5 Security depends on Tech (Stage 3) and Operations (Stage 4)
            deps = []
            if stage_task_indices[3]:
                deps.append(f"task_{stage_task_indices[3][-1]}")
            if stage_task_indices[4]:
                deps.append(f"task_{stage_task_indices[4][0]}")
        elif s_num == 6:
            # Stage 6 Critic audits commercial, tech, and security
            deps = []
            for prior_stage in (3, 5):
                if stage_task_indices[prior_stage]:
                    deps.append(f"task_{stage_task_indices[prior_stage][0]}")
        elif s_num == 7:
            # Stage 7 Optimization synthesizes all verified deliverables after Critic review
            if stage_task_indices[6]:
                deps = [f"task_{stage_task_indices[6][0]}"]

        # Instantiate tasks for each team in this stage
        for tid in s_teams:
            team_agents = AGENTS_BY_TEAM.get(tid, [])
            selected_agents = team_agents[:agents_per_team]
            custom_team_directive = team_directives.get(tid, "")

            for agent in selected_agents:
                curr_idx = task_counter
                stage_task_indices[s_num].append(curr_idx)

                # Compose task title
                t_title = f"{agent['name']} ({agent['role']}): {title}"
                if len(t_title) > 90:
                    t_title = t_title[:87] + "..."

                # Compose tailored input directive
                directive_body = custom_team_directive if custom_team_directive else context_snippet
                task_input = (
                    f"Specialist Assignment for {agent['name']} ({agent['role']}) - Team {tid}:\n"
                    f"Mission: {title}\n\n"
                    f"Directives:\n{directive_body}\n\n"
                    f"Your Mandate:\nExecute your specialist role ({agent['role']}). Focus strictly on your designated capabilities: {', '.join(agent['capabilities'][:4])}. "
                    f"Deliver structured, rigorous output in clear markdown."
                )

                subtasks.append(TaskPlanItem(
                    title=t_title,
                    task_type=agent["role"],
                    required_capabilities=agent["capabilities"][:3],
                    assigned_agent_id=agent["id"],
                    priority=max(1, 9 - s_num),
                    dependencies=list(deps),
                    input=task_input
                ))
                task_counter += 1

    density_label = f"all 100 agents" if agents_per_team == 10 else f"{len(subtasks)} agents across 10 teams"
    return GoalAnalysis(
        goal_summary=f"Full Multi-Team Mission Plan activating {density_label} across 7 staged phases.",
        task_type=task_type,
        required_capabilities=required_caps,
        subtasks=subtasks
    )

def create_task_plan(
    title: str,
    description: str,
    workforce_density: Union[str, int] = "adaptive"
) -> GoalAnalysis:
    """
    Analyzes goal, classifies domain, extracts capabilities, and constructs a multi-phase
    directed acyclic graph (DAG) of independent and dependent subtasks assigned to specialist agents.
    
    Supports customizable workforce density:
    - 'focused': 3-5 core specialist tasks for rapid CPU execution.
    - 'balanced': 10 tasks (1 agent per team across all 10 teams).
    - 'comprehensive': 30 tasks (3 agents per team across all 10 teams).
    - 'full_swarm': 100 tasks (activating all 10 teams and all 100 agents).
    - 'adaptive': Auto-detects density based on prompt signals and explicit stage directives.
    """
    full_text = f"{title} {description}"
    task_type = classify_task_type(full_text, title=title)
    required_caps = extract_required_capabilities(full_text, task_type)

    mode, agents_per_team = resolve_workforce_density(full_text, requested_density=workforce_density)

    # If workforce density requests multi-team deployment or full swarm, construct multi-team DAG
    if agents_per_team > 0:
        team_directives = extract_team_directives(description)
        return build_multi_team_plan(
            title=title,
            description=description,
            task_type=task_type,
            required_caps=required_caps,
            agents_per_team=agents_per_team,
            team_directives=team_directives
        )

    # -------------------------------------------------------------------------
    # FOCUSED DOMAIN-SPECIFIC DAG DECOMPOSITION TEMPLATES (3-5 Subtasks)
    # -------------------------------------------------------------------------
    context_snippet = description.strip()
    if len(context_snippet) > 1200:
        context_snippet = context_snippet[:1200].rstrip() + "\n...[Additional context indexed in shared memory]..."

    subtasks: List[TaskPlanItem] = []

    if task_type == "Software Development":
        agent_arch = match_agent_for_task("Software Architecture Specification", "Architecture", ["software_architecture"], preferred_team_id=5)
        agent_sec = match_agent_for_task("Security & Threat Assessment", "Security", ["threat_modeling"], preferred_team_id=8)
        
        subtasks.append(TaskPlanItem(
            title=f"Architectural Specification: {title}",
            task_type="System Architecture",
            required_capabilities=["software_architecture", "system_design"],
            assigned_agent_id=agent_arch,
            priority=8,
            dependencies=[], # Independent
            input=f"Analyze software requirements and design component interfaces for:\n{title}\n\nContext:\n{context_snippet}"
        ))
        subtasks.append(TaskPlanItem(
            title=f"Security & Threat Model: {title}",
            task_type="Security Review",
            required_capabilities=["threat_modeling", "permissions_review"],
            assigned_agent_id=agent_sec,
            priority=7,
            dependencies=[], # Independent
            input=f"Model attack surfaces, trust boundaries, and authorization controls for:\n{title}"
        ))

        agent_api = match_agent_for_task("API Contract Implementation", "Backend", ["api_design", "backend_engineering"], preferred_team_id=5)
        agent_code = match_agent_for_task("Core Implementation", "Development", ["programming", "clean_code"], preferred_team_id=5)

        subtasks.append(TaskPlanItem(
            title=f"API Contract & Interfaces: {title}",
            task_type="API Design",
            required_capabilities=["api_design", "restful_conventions"],
            assigned_agent_id=agent_api,
            priority=6,
            dependencies=["task_0"], # Depends on Architecture
            input=f"Construct API endpoints, payload schemas, and response contracts for {title}."
        ))
        subtasks.append(TaskPlanItem(
            title=f"Core Logic Implementation: {title}",
            task_type="Backend Programming",
            required_capabilities=["programming", "python", "clean_code"],
            assigned_agent_id=agent_code,
            priority=6,
            dependencies=["task_0", "task_1"], # Depends on Architecture & Security
            input=f"Implement core logic, error handling, and business rules for {title}."
        ))

    elif task_type == "Data Analysis":
        agent_clean = match_agent_for_task("Data Sanitization & Cleaning", "Data", ["data_cleaning"], preferred_team_id=6)
        subtasks.append(TaskPlanItem(
            title=f"Data Validation & Cleaning: {title}",
            task_type="Data Sanitization",
            required_capabilities=["data_cleaning", "data_validation"],
            assigned_agent_id=agent_clean,
            priority=8,
            dependencies=[],
            input=f"Audit schema, detect anomalies, missing values, and normalize data for:\n{title}\n\nContext:\n{context_snippet}"
        ))

        agent_stat = match_agent_for_task("Statistical Analysis", "Data", ["statistics", "data_analysis"], preferred_team_id=6)
        subtasks.append(TaskPlanItem(
            title=f"Statistical Modeling & Analysis: {title}",
            task_type="Statistical Analysis",
            required_capabilities=["statistics", "hypothesis_testing"],
            assigned_agent_id=agent_stat,
            priority=7,
            dependencies=["task_0"],
            input=f"Execute quantitative analysis, distribution checks, and hypothesis tests for {title}."
        ))

        agent_viz = match_agent_for_task("Data Visualisation & Narrative", "Data", ["data_visualization", "data_reporting"], preferred_team_id=6)
        subtasks.append(TaskPlanItem(
            title=f"Visualization & Insights Dashboard: {title}",
            task_type="Data Visualization",
            required_capabilities=["data_visualization", "insight_extraction"],
            assigned_agent_id=agent_viz,
            priority=6,
            dependencies=["task_1"],
            input=f"Synthesize statistical insights into executive charts and actionable takeaways for {title}."
        ))

    elif task_type == "Research":
        agent_web = match_agent_for_task("Deep Web Research", "Research", ["web_research"], preferred_team_id=2)
        agent_comp = match_agent_for_task("Competitive & Literature Analysis", "Research", ["competitive_intelligence", "literature_review"], preferred_team_id=2)

        subtasks.append(TaskPlanItem(
            title=f"Web & Primary Fact Research: {title}",
            task_type="Information Retrieval",
            required_capabilities=["web_research", "information_retrieval"],
            assigned_agent_id=agent_web,
            priority=8,
            dependencies=[],
            input=f"Gather primary evidence, documentation, and data points regarding:\n{title}\n\nContext:\n{context_snippet}"
        ))
        subtasks.append(TaskPlanItem(
            title=f"Comparative Literature & Market Review: {title}",
            task_type="Literature Review",
            required_capabilities=["literature_review", "competitive_intelligence"],
            assigned_agent_id=agent_comp,
            priority=7,
            dependencies=[],
            input=f"Analyze existing solutions, competitive landscapes, and literature related to {title}."
        ))

        agent_synth = match_agent_for_task("Comprehensive Synthesis", "Research", ["research_synthesis"], preferred_team_id=2)
        subtasks.append(TaskPlanItem(
            title=f"Dossier Synthesis & Fact Checking: {title}",
            task_type="Evidence Synthesis",
            required_capabilities=["research_synthesis", "fact_checking"],
            assigned_agent_id=agent_synth,
            priority=6,
            dependencies=["task_0", "task_1"],
            input=f"Reconcile findings, verify citations, and assemble complete synthesized research dossier for {title}."
        ))

    elif task_type == "Business Strategy":
        agent_mkt = match_agent_for_task("Market Sizing & Segmentation", "Business", ["market_research", "tam_sam_som"], preferred_team_id=3)
        agent_cust = match_agent_for_task("Customer Persona & Journey", "Business", ["customer_analysis", "buyer_personas"], preferred_team_id=3)

        subtasks.append(TaskPlanItem(
            title=f"Market Sizing & Landscape Analysis: {title}",
            task_type="Market Research",
            required_capabilities=["market_research", "tam_sam_som"],
            assigned_agent_id=agent_mkt,
            priority=8,
            dependencies=[],
            input=f"Quantify market opportunity, TAM/SAM/SOM, and macro dynamics for:\n{title}\n\nContext:\n{context_snippet}"
        ))
        subtasks.append(TaskPlanItem(
            title=f"Customer Profiles & Willingness-To-Pay: {title}",
            task_type="Customer Analysis",
            required_capabilities=["customer_analysis", "buyer_personas"],
            assigned_agent_id=agent_cust,
            priority=7,
            dependencies=[],
            input=f"Model customer pain points, buying journey, and value drivers for {title}."
        ))

        agent_fin = match_agent_for_task("Financial & Unit Economics Modeling", "Business", ["financial_modeling", "unit_economics"], preferred_team_id=3)
        subtasks.append(TaskPlanItem(
            title=f"Financial Model & Unit Economics: {title}",
            task_type="Financial Modeling",
            required_capabilities=["financial_modeling", "pricing_strategy"],
            assigned_agent_id=agent_fin,
            priority=6,
            dependencies=["task_0", "task_1"],
            input=f"Develop monetization pricing, unit economics (CAC/LTV), and P&L forecast for {title}."
        ))

    else:
        agent_strat = match_agent_for_task("Goal Decomposition", "Strategy", ["goal_planning", "task_decomposition"], preferred_team_id=1)
        agent_exec = match_agent_for_task("Execution Plan", "Operations", ["workflow_planning", "task_execution"], preferred_team_id=7)
        agent_writer = match_agent_for_task("Executive Deliverable Synthesis", "Content", ["longform_writing"], preferred_team_id=4)

        subtasks.append(TaskPlanItem(
            title=f"Strategic Objective Formulation: {title}",
            task_type="Strategic Planning",
            required_capabilities=["goal_planning", "strategic_planning"],
            assigned_agent_id=agent_strat,
            priority=8,
            dependencies=[],
            input=f"Define core scope, success metrics, and constraints for:\n{title}\n\nDetails:\n{context_snippet}"
        ))
        subtasks.append(TaskPlanItem(
            title=f"Operational Execution Architecture: {title}",
            task_type="Operational Planning",
            required_capabilities=["workflow_planning", "task_execution"],
            assigned_agent_id=agent_exec,
            priority=7,
            dependencies=["task_0"],
            input=f"Design step-by-step operational workflows and execution protocol for {title}."
        ))
        subtasks.append(TaskPlanItem(
            title=f"Executive Solution Synthesis: {title}",
            task_type="Deliverable Synthesis",
            required_capabilities=["longform_writing", "corporate_communications"],
            assigned_agent_id=agent_writer,
            priority=6,
            dependencies=["task_1"],
            input=f"Consolidate operational plan into complete, actionable executive deliverable for {title}."
        ))

    return GoalAnalysis(
        goal_summary=f"{task_type} plan with {len(subtasks)} subtasks spanning independent and dependent phases.",
        task_type=task_type,
        required_capabilities=required_caps,
        subtasks=subtasks
    )
