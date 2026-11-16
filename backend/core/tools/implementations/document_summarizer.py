"""
Tool 7: Local Document Summarisation
Produces deterministic extractive summaries, executive bullet points, and key salience extraction.
Operates completely locally with zero network calls and zero external dependencies.
"""

import re
from pathlib import Path
from typing import List, Optional
from pydantic import BaseModel, Field

from backend.core.tools.base import (
    BaseTool,
    PermissionLevel,
    SecurityBoundaryError,
    ToolContext,
)

STOP_WORDS = {
    "a", "about", "above", "after", "again", "against", "all", "am", "an", "and", "any", "are",
    "as", "at", "be", "because", "been", "before", "being", "below", "between", "both", "but", "by",
    "can", "could", "did", "do", "does", "doing", "down", "during", "each", "few", "for", "from",
    "further", "had", "has", "have", "having", "he", "her", "here", "hers", "herself", "him", "himself",
    "his", "how", "i", "if", "in", "into", "is", "it", "its", "itself", "just", "me", "more", "most",
    "my", "myself", "no", "nor", "not", "now", "of", "off", "on", "once", "only", "or", "other", "our",
    "ours", "ourselves", "out", "over", "own", "s", "same", "she", "should", "so", "some", "such", "t",
    "than", "that", "the", "their", "theirs", "them", "themselves", "then", "there", "these", "they",
    "this", "those", "through", "to", "too", "under", "until", "up", "very", "was", "we", "were", "what",
    "when", "where", "which", "while", "who", "whom", "why", "will", "with", "would", "you", "your",
    "yours", "yourself", "yourselves"
}

class DocumentSummarizerInput(BaseModel):
    text: Optional[str] = Field(None, description="Raw text or markdown document to summarize")
    workspace_file_path: Optional[str] = Field(None, description="Relative path to text/markdown file within approved workspace")
    max_sentences: int = Field(4, ge=1, le=20, description="Target number of key sentences to select")

class DocumentSummarizerOutput(BaseModel):
    original_word_count: int
    summary_word_count: int
    compression_ratio: float
    executive_summary: str
    key_takeaways: List[str]
    salient_keywords: List[str]

class DocumentSummarizerTool(BaseTool):
    id = "document_summarizer"
    name = "Local Document Summarizer"
    description = (
        "Extracts salient sentences, key takeaways, and frequent conceptual entities from text or "
        "workspace documents without external API calls or network dependencies."
    )
    permission_level = PermissionLevel.SAFE
    timeout_seconds = 10.0
    input_schema = DocumentSummarizerInput
    output_schema = DocumentSummarizerOutput

    async def execute(self, params: DocumentSummarizerInput, context: ToolContext) -> DocumentSummarizerOutput:
        raw_text = params.text

        # If a workspace file path is given, read it safely
        if params.workspace_file_path:
            norm_rel = Path(params.workspace_file_path)
            if any(part == ".." for part in norm_rel.parts):
                raise SecurityBoundaryError("Security Boundary Violation: Path traversal '..' is forbidden in summarizer path.")

            workspace_root = context.workspace_path.resolve()
            target_file = (workspace_root / norm_rel).resolve()

            if not target_file.is_relative_to(workspace_root):
                raise SecurityBoundaryError("Security Boundary Violation: Target file escapes approved workspace.")

            if not target_file.exists():
                raise FileNotFoundError(f"File '{params.workspace_file_path}' not found in workspace.")

            raw_text = target_file.read_text(encoding="utf-8", errors="replace")

        if not raw_text or not raw_text.strip():
            raise ValueError("No text provided to summarize.")

        # Clean text
        words = re.findall(r"\b[A-Za-z0-9_-]{2,}\b", raw_text)
        orig_word_count = len(words)
        if orig_word_count == 0:
            raise ValueError("Document contains no valid lexical tokens.")

        # Calculate word frequency table (excluding stop words)
        freq_table = {}
        for w in words:
            w_lower = w.lower()
            if w_lower not in STOP_WORDS and len(w_lower) > 2:
                freq_table[w_lower] = freq_table.get(w_lower, 0) + 1

        if not freq_table:
            freq_table = {w.lower(): 1 for w in words}

        max_freq = max(freq_table.values()) if freq_table else 1
        normalized_freq = {w: count / max_freq for w, count in freq_table.items()}

        # Sentence segmentation
        raw_sentences = re.split(r"(?<=[.!?])\s+", raw_text.strip())
        sentences = [s.strip() for s in raw_sentences if len(s.strip()) > 15]

        if not sentences:
            sentences = [raw_text.strip()]

        # Score sentences
        sentence_scores = []
        for idx, sentence in enumerate(sentences):
            s_words = re.findall(r"\b[A-Za-z0-9_-]{2,}\b", sentence)
            score = 0.0
            for sw in s_words:
                score += normalized_freq.get(sw.lower(), 0.0)

            # Normalize by sentence length to prevent bias towards run-on sentences
            length_norm = max(len(s_words), 1)
            # Position bonus for first and last sentences
            pos_bonus = 1.2 if (idx == 0 or idx == len(sentences) - 1) else 1.0

            final_score = (score / length_norm) * pos_bonus
            sentence_scores.append((idx, sentence, final_score))

        # Select top sentences preserving original document order
        top_sentences = sorted(sentence_scores, key=lambda x: x[2], reverse=True)[:params.max_sentences]
        top_sentences.sort(key=lambda x: x[0])  # Restore document order

        selected_texts = [s[1] for s in top_sentences]
        summary_text = " ".join(selected_texts)
        summary_words = len(re.findall(r"\b[A-Za-z0-9_-]{2,}\b", summary_text))
        compression = round((summary_words / orig_word_count) * 100.0, 1)

        # Top salient keywords
        sorted_keywords = sorted(freq_table.items(), key=lambda x: x[1], reverse=True)[:7]
        keywords = [kw[0] for kw in sorted_keywords]

        return DocumentSummarizerOutput(
            original_word_count=orig_word_count,
            summary_word_count=summary_words,
            compression_ratio=compression,
            executive_summary=summary_text,
            key_takeaways=selected_texts,
            salient_keywords=keywords
        )
