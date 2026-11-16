"""
SWARM-100 Goal Planning & Decomposition Engine
Transforms natural-language user goals into structured, dependency-aware task graphs
and assigns each subtask to optimal specialist agents among the 100 registered agents.
"""

import re
from typing import List, Optional, Tuple
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

def create_task_plan(title: str, description: str) -> GoalAnalysis:
    """
    Analyzes goal, classifies domain, extracts capabilities, and constructs a multi-phase
    directed acyclic graph (DAG) of independent and dependent subtasks assigned to specialist agents.
    """
    full_text = f"{title} {description}"
    task_type = classify_task_type(full_text, title=title)
    required_caps = extract_required_capabilities(full_text, task_type)

    subtasks: List[TaskPlanItem] = []

    # -------------------------------------------------------------------------
    # DOMAIN-SPECIFIC DAG DECOMPOSITION TEMPLATES
    # -------------------------------------------------------------------------
    if task_type == "Software Development":
        # Phase 1: Architecture & Requirements (Independent)
        agent_arch = match_agent_for_task("Software Architecture Specification", "Architecture", ["software_architecture"], preferred_team_id=5)
        agent_sec = match_agent_for_task("Security & Threat Assessment", "Security", ["threat_modeling"], preferred_team_id=8)
        
        subtasks.append(TaskPlanItem(
            title=f"Architectural Specification: {title}",
            task_type="System Architecture",
            required_capabilities=["software_architecture", "system_design"],
            assigned_agent_id=agent_arch,
            priority=8,
            dependencies=[], # Independent
            input=f"Analyze software requirements and design component interfaces for:\n{title}\n\nContext:\n{description}"
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

        # Phase 2: Implementation & API Design (Dependent on Phase 1)
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
        # Phase 1: Data Audit & Cleaning (Independent)
        agent_clean = match_agent_for_task("Data Sanitization & Cleaning", "Data", ["data_cleaning"], preferred_team_id=6)
        subtasks.append(TaskPlanItem(
            title=f"Data Validation & Cleaning: {title}",
            task_type="Data Sanitization",
            required_capabilities=["data_cleaning", "data_validation"],
            assigned_agent_id=agent_clean,
            priority=8,
            dependencies=[],
            input=f"Audit schema, detect anomalies, missing values, and normalize data for:\n{title}\n\nContext:\n{description}"
        ))

        # Phase 2: Statistical Modeling (Dependent on Phase 1)
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

        # Phase 3: Visual Reporting (Dependent on Phase 2)
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
        # Phase 1: Web & Academic Research (Independent in parallel)
        agent_web = match_agent_for_task("Deep Web Research", "Research", ["web_research"], preferred_team_id=2)
        agent_comp = match_agent_for_task("Competitive & Literature Analysis", "Research", ["competitive_intelligence", "literature_review"], preferred_team_id=2)

        subtasks.append(TaskPlanItem(
            title=f"Web & Primary Fact Research: {title}",
            task_type="Information Retrieval",
            required_capabilities=["web_research", "information_retrieval"],
            assigned_agent_id=agent_web,
            priority=8,
            dependencies=[],
            input=f"Gather primary evidence, documentation, and data points regarding:\n{title}\n\nContext:\n{description}"
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

        # Phase 2: Evidence Synthesis (Dependent on both research streams)
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
        # Phase 1: Market & Customer Sizing (Independent)
        agent_mkt = match_agent_for_task("Market Sizing & Segmentation", "Business", ["market_research", "tam_sam_som"], preferred_team_id=3)
        agent_cust = match_agent_for_task("Customer Persona & Journey", "Business", ["customer_analysis", "buyer_personas"], preferred_team_id=3)

        subtasks.append(TaskPlanItem(
            title=f"Market Sizing & Landscape Analysis: {title}",
            task_type="Market Research",
            required_capabilities=["market_research", "tam_sam_som"],
            assigned_agent_id=agent_mkt,
            priority=8,
            dependencies=[],
            input=f"Quantify market opportunity, TAM/SAM/SOM, and macro dynamics for:\n{title}\n\nContext:\n{description}"
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

        # Phase 2: Commercial Model & Financial Projections (Dependent on Phase 1)
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
        # General / Multi-Domain Strategy Plan
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
            input=f"Define core scope, success metrics, and constraints for:\n{title}\n\nDetails:\n{description}"
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
