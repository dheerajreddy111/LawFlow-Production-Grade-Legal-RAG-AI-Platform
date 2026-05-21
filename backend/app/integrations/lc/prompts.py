"""LangChain ``ChatPromptTemplate`` for the RAG system+user prompts.

The static system instruction is imported from :mod:`app.rag.engine`
(single source of truth — drift between the two would silently change
generation behaviour). The user-message template assembles the numbered
context blocks the existing ``_build_prompt`` already produces.

Why a template at all?
----------------------
The current code composes prompts inline. A template doesn't change the
content — it lets LangChain track it as part of the trace (visible in
LangSmith), and lets the LangGraph RAG graph reuse the exact same
formatting deterministically across nodes.
"""

from __future__ import annotations

from langchain_core.documents import Document
from langchain_core.prompts import ChatPromptTemplate

from app.rag.engine import _EVAL_SYSTEM_PROMPT, _SYSTEM_PROMPT

# Use raw-string placeholders so curly braces in the literal text are
# escaped properly. Only ``{context}`` and ``{question}`` are templated.
_USER_TEMPLATE = (
    "Context passages:\n\n{context}\n\n"
    "Question: {question}\n\n"
    "Answer using only the passages above, citing them as [n]."
)

# Eval variant — drops the citation cue + closes with a benchmark hint.
# Wording must match ``app.rag.engine._build_prompt`` (eval branch) so
# the native + LangGraph paths exercise the same prompt.
_EVAL_USER_TEMPLATE = (
    "Context passages:\n\n{context}\n\n"
    "Question: {question}\n\n"
    "Answer in one short sentence using wording from the passages. "
    "No citations, markdown, or disclaimers."
)


rag_prompt: ChatPromptTemplate = ChatPromptTemplate.from_messages(
    [
        ("system", _SYSTEM_PROMPT),
        ("user", _USER_TEMPLATE),
    ]
)


eval_rag_prompt: ChatPromptTemplate = ChatPromptTemplate.from_messages(
    [
        ("system", _EVAL_SYSTEM_PROMPT),
        ("user", _EVAL_USER_TEMPLATE),
    ]
)


def format_context(docs: list[Document]) -> str:
    """Render retrieved Documents into the same numbered-block format
    :func:`app.rag.engine._build_prompt` already uses.

    Output:

        [1] (source: …)
        <text>

        [2] (source: …)
        <text>
    """
    blocks: list[str] = []
    for i, doc in enumerate(docs, 1):
        source = str((doc.metadata or {}).get("source", "")) or "unknown"
        blocks.append(f"[{i}] (source: {source})\n{doc.page_content.strip()}")
    return "\n\n".join(blocks)
