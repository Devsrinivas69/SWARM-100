"""
SWARM-100 Autonomous ReAct (Reason + Act) Tool Loop Engine
Empowers specialist agents to execute multi-step analytical reasoning:
Thought -> Action -> Action Input -> Observation -> Thought -> Final Answer.
Integrates directly with ToolRegistry and WebSocket real-time telemetry.
"""

import asyncio
import json
import logging
import re
from typing import Any, Callable, Dict, List, Optional, Tuple

from backend.config import settings
from backend.core.llm_service import LLMResponse, llm_service
from backend.core.tools.base import PermissionLevel
from backend.core.tools.registry import tool_registry
from backend.core.websocket_manager import ws_manager

logger = logging.getLogger("swarm100.react")

REACT_SYSTEM_INSTRUCTION = """
You have access to the following autonomous tools:
{tool_catalog}

To use a tool, you MUST use this exact format:
Thought: Describe your step-by-step reasoning and what specific fact or calculation you need.
Action: <tool_id>
Action Input: {{"parameter_name": "parameter_value"}}

After you invoke a tool, an Observation will be returned to you.
When you have collected all required information to complete the task, output:
Thought: I have collected all necessary facts and can now deliver the complete final deliverable.
Final Answer:
<Your complete, comprehensive, high-quality specialist deliverable in structured Markdown>

IMPORTANT:
- If no tool is needed, proceed directly to providing the complete specialist deliverable.
- Never invent imaginary tool names. Use only tools listed in the catalog.
- Action Input must be valid JSON matching the tool's input schema.
"""


def format_tool_catalog() -> str:
    """Formats safe and registered tools into a concise specification for the LLM."""
    catalog_lines = []
    for tool_meta in tool_registry.list_tools():
        if tool_meta.get("permission_level") == PermissionLevel.RESTRICTED_EXECUTION.value:
            continue  # Exclude dangerous tools requiring human approvals from autonomous loop
        tid = tool_meta.get("id", "")
        name = tool_meta.get("name", "")
        desc = tool_meta.get("description", "")
        schema = tool_meta.get("input_schema", {}).get("properties", {})
        param_desc = ", ".join([f"{k} ({v.get('type', 'any')})" for k, v in schema.items()])
        catalog_lines.append(f"- {tid}: {name} — {desc} | Parameters: [{param_desc}]")
    return "\n".join(catalog_lines)


def parse_action_and_input(text: str) -> Optional[Tuple[str, Dict[str, Any]]]:
    """
    Extracts 'Action: <tool_id>' and 'Action Input: <json>' from agent response.
    Returns (tool_id, parameters_dict) or None if no valid action block found.
    """
    if "Action:" not in text:
        return None

    action_match = re.search(r'Action:\s*([a-zA-Z0-9_\-]+)', text, re.IGNORECASE)
    if not action_match:
        return None
    tool_id = action_match.group(1).strip().lower()

    # Match Action Input block
    input_match = re.search(r'Action Input:\s*(\{.*?\}|\[.*?\]|"[^"\n]*")', text, re.DOTALL | re.IGNORECASE)
    params = {}
    if input_match:
        raw_input = input_match.group(1).strip()
        try:
            params = json.loads(raw_input)
            if not isinstance(params, dict):
                params = {"query": str(params)}
        except Exception:
            # Fallback for simple key:value unquoted patterns
            kv_match = re.search(r'Action Input:\s*\{\s*["\']?([a-zA-Z0-9_]+)["\']?\s*:\s*["\']?([^"\'\n\}]+)["\']?\s*\}', text)
            if kv_match:
                params = {kv_match.group(1): kv_match.group(2)}
            else:
                params = {"query": raw_input}

    return (tool_id, params)


def extract_final_answer(text: str) -> str:
    """Extracts content following 'Final Answer:' or strips Thought/Action markers."""
    if "Final Answer:" in text:
        parts = text.split("Final Answer:", 1)
        answer = parts[1].strip()
        if answer:
            return answer

    # If no Final Answer tag, clean any remaining Thought/Action scratchpad lines
    cleaned = re.sub(r'Thought:.*?(?=(Action:|Observation:|\n\n|$))', '', text, flags=re.DOTALL)
    cleaned = re.sub(r'Action:\s*[a-zA-Z0-9_\-]+', '', cleaned)
    cleaned = re.sub(r'Action Input:.*?(\n|$)', '', cleaned)
    cleaned = re.sub(r'Observation:.*?(\n\n|$)', '', cleaned, flags=re.DOTALL)
    return cleaned.strip() or text.strip()


class ReActEngine:
    """
    Autonomous multi-turn tool reasoning engine.
    Orchestrates iterative tool calls within task safety bounds.
    """
    def __init__(self, max_turns: int = 3):
        self.max_turns = max_turns

    async def execute_react_task(
        self,
        agent_id: str,
        system_prompt: str,
        task_title: str,
        task_directives: str,
        upstream_context: Optional[str] = None,
        task_id: Optional[str] = None,
        goal_id: Optional[str] = None,
        on_token: Optional[Callable[[str], Any]] = None
    ) -> Tuple[str, List[Dict[str, Any]], Dict[str, Any]]:
        """
        Runs the ReAct loop:
        Returns (final_deliverable, list_of_tool_invocations, total_telemetry).
        """
        tool_catalog = format_tool_catalog()
        augmented_sys_prompt = f"{system_prompt.strip()}\n\n{REACT_SYSTEM_INSTRUCTION.format(tool_catalog=tool_catalog)}"

        conversation_history: List[Dict[str, str]] = []
        user_message = f"Task Title: {task_title}\n\nDirectives:\n{task_directives}"
        if upstream_context:
            user_message += f"\n\nPrerequisite Context:\n{upstream_context}"

        conversation_history.append({"role": "user", "content": user_message})

        tools_invoked: List[Dict[str, Any]] = []
        cumulative_tokens = 0
        cumulative_latency_ms = 0.0
        final_deliverable = ""

        for turn in range(1, self.max_turns + 1):
            logger.info(f"ReAct Turn {turn}/{self.max_turns} for agent {agent_id} on task {task_id}")

            # Assemble rolling dialog
            combined_user_content = ""
            for msg in conversation_history:
                if msg["role"] == "user":
                    combined_user_content += f"\n{msg['content']}"
                elif msg["role"] == "assistant":
                    combined_user_content += f"\n\n[Previous Assistant Response]:\n{msg['content']}"

            # Invoke LLM
            llm_response: LLMResponse = await llm_service.chat(
                system_prompt=augmented_sys_prompt,
                user_message=combined_user_content.strip(),
                max_tokens=settings.default_max_tokens
            )

            raw_text = llm_response.content.strip()
            cumulative_tokens += llm_response.telemetry.total_tokens
            cumulative_latency_ms += llm_response.telemetry.total_latency_ms

            # Check for tool call
            action_data = parse_action_and_input(raw_text)

            if not action_data:
                # No tool called or Final Answer reached
                logger.info(f"Agent {agent_id} concluded ReAct reasoning in turn {turn}.")
                final_deliverable = extract_final_answer(raw_text)
                break

            tool_id, parameters = action_data
            logger.info(f"Agent {agent_id} requested tool '{tool_id}' with parameters: {parameters}")

            # Notify WebSocket of tool invocation
            try:
                ws_manager.emit_event("tool_invoked", {
                    "task_id": task_id,
                    "agent_id": agent_id,
                    "goal_id": goal_id,
                    "tool_id": tool_id,
                    "parameters": parameters,
                    "turn": turn
                })
            except Exception:
                pass

            # Execute tool safely
            try:
                tool_res = await tool_registry.execute_tool(
                    tool_id=tool_id,
                    agent_id=agent_id,
                    parameters=parameters,
                    task_id=task_id,
                    goal_id=goal_id
                )
                obs_data = tool_res.get("result", {})
                obs_summary = json.dumps(obs_data) if isinstance(obs_data, (dict, list)) else str(obs_data)
                if len(obs_summary) > 1500:
                    obs_summary = obs_summary[:1500] + "... [observation truncated]"
                observation_text = f"Observation: {obs_summary}"
                tools_invoked.append({
                    "turn": turn,
                    "tool_id": tool_id,
                    "parameters": parameters,
                    "success": True,
                    "output_preview": obs_summary[:200]
                })
            except Exception as e:
                observation_text = f"Observation: Error executing tool '{tool_id}': {type(e).__name__} - {str(e)}"
                tools_invoked.append({
                    "turn": turn,
                    "tool_id": tool_id,
                    "parameters": parameters,
                    "success": False,
                    "error": str(e)
                })

            # Append to history for next turn
            conversation_history.append({"role": "assistant", "content": raw_text})
            conversation_history.append({"role": "user", "content": observation_text})

            # Check if text already included a final answer alongside tool
            if "Final Answer:" in raw_text:
                final_deliverable = extract_final_answer(raw_text)
                break
        else:
            # Reached max turns without explicit exit: synthesize accumulated content
            final_deliverable = extract_final_answer(raw_text)

        telemetry_summary = {
            "total_tokens": cumulative_tokens,
            "total_latency_ms": round(cumulative_latency_ms, 2),
            "turns_used": len(tools_invoked) + 1,
            "tools_count": len(tools_invoked)
        }

        return final_deliverable, tools_invoked, telemetry_summary


react_engine = ReActEngine()
