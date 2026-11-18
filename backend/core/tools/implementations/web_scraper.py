"""
Tool: Web Scraper & Article Extractor
Fetches content from an external web page or documentation URL, strips advertising, scripts,
and navigation boilerplate, and returns clean, structured Markdown text.
"""

import logging
import re
from typing import Optional
from bs4 import BeautifulSoup
import httpx
from pydantic import BaseModel, Field

from backend.core.tools.base import BaseTool, PermissionLevel, ToolContext

logger = logging.getLogger("swarm100.tools.web_scraper")

class WebScraperInput(BaseModel):
    url: str = Field(..., min_length=8, max_length=1000, description="The HTTP or HTTPS URL to fetch and scrape (e.g. 'https://en.wikipedia.org/wiki/Namma_Metro')")
    max_length: int = Field(3000, ge=500, le=10000, description="Maximum characters of extracted text to return (default: 3000)")

class WebScraperOutput(BaseModel):
    url: str
    status: str
    title: str
    content: str
    word_count: int

class WebScraperTool(BaseTool):
    id = "web_scraper"
    name = "Webpage Content Scraper"
    description = (
        "Fetches external URLs and converts webpage HTML into clean, sanitized Markdown text. "
        "Strips navigation menus, scripts, stylesheets, and tracking cookies to return readable source text."
    )
    permission_level = PermissionLevel.SAFE
    timeout_seconds = 15.0
    input_schema = WebScraperInput
    output_schema = WebScraperOutput

    async def execute(self, params: WebScraperInput, context: ToolContext) -> WebScraperOutput:
        url = params.url.strip()

        if not (url.startswith("http://") or url.startswith("https://")):
            return WebScraperOutput(
                url=url,
                status="invalid_url",
                title="Invalid URL",
                content="Error: URL must begin with http:// or https://",
                word_count=0
            )

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
        }

        try:
            async with httpx.AsyncClient(timeout=10.0, follow_redirects=True, trust_env=False) as client:
                resp = await client.get(url, headers=headers)
                if resp.status_code != 200:
                    return WebScraperOutput(
                        url=url,
                        status=f"http_error_{resp.status_code}",
                        title="HTTP Fetch Error",
                        content=f"Failed to fetch {url}: HTTP {resp.status_code} {resp.reason_phrase}",
                        word_count=0
                    )

                html_doc = resp.text
                soup = BeautifulSoup(html_doc, "html.parser")

                # Remove non-content elements
                for elem in soup(["script", "style", "nav", "footer", "header", "noscript", "aside", "form"]):
                    elem.decompose()

                page_title = soup.title.string.strip() if (soup.title and soup.title.string) else "Untitled Webpage"

                # Extract main content
                main_elem = soup.find("main") or soup.find("article") or soup.find("div", class_=re.compile(r"content|body|main|article", re.I)) or soup.body
                if not main_elem:
                    text_content = soup.get_text(separator="\n", strip=True)
                else:
                    text_content = main_elem.get_text(separator="\n", strip=True)

                # Clean excessive linebreaks
                cleaned_text = re.sub(r'\n{3,}', '\n\n', text_content).strip()

                if len(cleaned_text) > params.max_length:
                    cleaned_text = cleaned_text[:params.max_length].rstrip() + "\n\n...[Content truncated to stay within token budget]..."

                word_count = len(cleaned_text.split())

                return WebScraperOutput(
                    url=url,
                    status="success",
                    title=page_title,
                    content=cleaned_text,
                    word_count=word_count
                )
        except Exception as e:
            logger.warning(f"Web scraper fetch failed for {url}: {e}")
            return WebScraperOutput(
                url=url,
                status="network_error",
                title="Connection Error",
                content=f"Unable to scrape URL {url}: {type(e).__name__} ({str(e)})",
                word_count=0
            )
