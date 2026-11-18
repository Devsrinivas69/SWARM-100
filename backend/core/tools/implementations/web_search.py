"""
Tool: Web Search
Executes internet information retrieval using open search gateways (Wikipedia & DuckDuckGo APIs).
Provides factual search results, snippets, and verified source URLs without requiring API keys.
"""

import json
import logging
import urllib.parse
from typing import Any, Dict, List, Optional
import httpx
from pydantic import BaseModel, Field

from backend.core.tools.base import BaseTool, PermissionLevel, ToolContext

logger = logging.getLogger("swarm100.tools.web_search")

class WebSearchResultItem(BaseModel):
    title: str
    snippet: str
    url: str

class WebSearchInput(BaseModel):
    query: str = Field(..., min_length=2, max_length=300, description="Search query keywords (e.g. 'Bengaluru Metro Purple line feeder bus')")
    max_results: int = Field(5, ge=1, le=10, description="Maximum number of search results to retrieve (default: 5)")

class WebSearchOutput(BaseModel):
    query: str
    status: str
    results: List[WebSearchResultItem] = []
    summary: str

class WebSearchTool(BaseTool):
    id = "web_search"
    name = "Live Web & Knowledge Search"
    description = (
        "Retrieves verified web snippets, primary sources, definitions, and URLs using open search gateways. "
        "Used by Research, Recon, and Data agents to gather real-world facts, market figures, and competitor intelligence."
    )
    permission_level = PermissionLevel.SAFE
    timeout_seconds = 12.0
    input_schema = WebSearchInput
    output_schema = WebSearchOutput

    async def execute(self, params: WebSearchInput, context: ToolContext) -> WebSearchOutput:
        results: List[WebSearchResultItem] = []
        query = params.query.strip()
        encoded_query = urllib.parse.quote(query)

        # 1. Primary Strategy: Query Wikipedia Search API (High reliability, open, rich facts)
        wiki_url = f"https://en.wikipedia.org/w/api.php?action=query&list=search&srsearch={encoded_query}&utf8=&format=json&srlimit={params.max_results}"

        try:
            async with httpx.AsyncClient(timeout=8.0, trust_env=False) as client:
                resp = await client.get(wiki_url, headers={"User-Agent": "SWARM-100-Agent/1.0"})
                if resp.status_code == 200:
                    data = resp.json()
                    search_items = data.get("query", {}).get("search", [])
                    for item in search_items:
                        # Clean raw HTML tags from Wikipedia snippets
                        raw_snippet = item.get("snippet", "")
                        clean_snippet = raw_snippet.replace('<span class="searchmatch">', '').replace('</span>', '')
                        title = item.get("title", "")
                        page_url = f"https://en.wikipedia.org/wiki/{urllib.parse.quote(title.replace(' ', '_'))}"
                        results.append(WebSearchResultItem(
                            title=title,
                            snippet=clean_snippet,
                            url=page_url
                        ))
        except Exception as e:
            logger.warning(f"Wikipedia search query encountered connection notice: {e}")

        # 2. Secondary Strategy: If Wikipedia returned few results, query DuckDuckGo Instant Answer API
        if len(results) < 2:
            ddg_url = f"https://api.duckduckgo.com/?q={encoded_query}&format=json&no_html=1&skip_disambig=1"
            try:
                async with httpx.AsyncClient(timeout=6.0, trust_env=False) as client:
                    resp = await client.get(ddg_url, headers={"User-Agent": "SWARM-100-Agent/1.0"})
                    if resp.status_code == 200:
                        ddg_data = resp.json()
                        abstract = ddg_data.get("AbstractText", "")
                        abstract_url = ddg_data.get("AbstractURL", "")
                        heading = ddg_data.get("Heading", query)
                        if abstract:
                            results.insert(0, WebSearchResultItem(
                                title=heading,
                                snippet=abstract,
                                url=abstract_url or f"https://duckduckgo.com/?q={encoded_query}"
                            ))

                        for topic in ddg_data.get("RelatedTopics", [])[:3]:
                            if isinstance(topic, dict) and "Text" in topic and "FirstURL" in topic:
                                results.append(WebSearchResultItem(
                                    title=topic.get("Text", "")[:60],
                                    snippet=topic.get("Text", ""),
                                    url=topic.get("FirstURL", "")
                                ))
            except Exception as e:
                logger.warning(f"DuckDuckGo API connection notice: {e}")

        # 3. Handle Sandbox / Offline Fallback gracefully
        if not results:
            summary = (
                f"Web search for '{query}' executed. Real-time internet query returned no external matches "
                f"or network access is restricted in the current sandbox environment. Refer to shared project memory."
            )
            return WebSearchOutput(
                query=query,
                status="no_external_results",
                results=[],
                summary=summary
            )

        summary_lines = [f"Found {len(results)} verified source(s) for '{query}':"]
        for idx, r in enumerate(results, 1):
            summary_lines.append(f"{idx}. [{r.title}] ({r.url}): {r.snippet[:140]}...")

        return WebSearchOutput(
            query=query,
            status="success",
            results=results[:params.max_results],
            summary="\n".join(summary_lines)
        )
