"""Text normalisation for benchmark scoring.

Applied to BOTH ``generated_answer`` and ``expected_answer`` immediately
before they reach the metric functions. The transformation is
symmetric — anything we strip from one side, we strip from the other —
so the F1 / keyword-overlap comparison stays fair.

What ``normalize_for_eval`` does
--------------------------------

1. Lowercase. Casing carries no signal for legal answers.
2. Strip the RAG-pipeline scaffolding the metrics module already
   knows about (citation markers, section header lines, the
   disclaimer, framing phrases). Centralised here so the eval
   service applies one explicit step rather than relying on the
   tokeniser to do it implicitly.
3. Strip punctuation. Periods, commas, semicolons, and the fancy
   dash characters Markdown likes to slip in.
4. Collapse whitespace. Repeated spaces / newlines / tabs from the
   markdown formatting fold into a single space.

What it does NOT do
-------------------

- No stemming. That's the metric's job — it preserves the original
  surface form for the row-detail view in the admin UI.
- No stopword removal. Stopwords stay so a future BERTScore-style
  variant has the full string to work with.
- No translation. The text is preserved verbatim aside from the
  removals listed above; an admin reading the normalised string
  should still see what the LLM actually said.

The raw, un-normalised text is what's stored in the ``RowResult`` —
this helper is invoked only when computing metrics so the admin UI
keeps the original answer for forensic inspection.
"""

from __future__ import annotations

import re

from app.evaluation.metrics import _strip_pipeline_noise

# Whitespace collapse — runs of spaces / newlines / tabs.
_WHITESPACE = re.compile(r"\s+")
# Punctuation we strip — keep the alnums + the few characters that
# carry meaning in legal text (``§``, ``%``).
_PUNCT = re.compile(r"[^\w\s§%]+")


def normalize_for_eval(text: str) -> str:
    """Return a comparable, normalised view of ``text`` for scoring.

    Idempotent — calling it twice produces the same result. The
    function is intentionally pure so unit tests can pin individual
    transformations without spinning up the pipeline.
    """
    if not text:
        return ""
    # Order matters: strip pipeline scaffolding first so its content
    # doesn't leave punctuation lingering in the output. Lowercase
    # after so the regex patterns can keep their case-aware boundaries
    # (the noise stripper is already case-insensitive internally).
    stripped = _strip_pipeline_noise(text)
    lowered = stripped.lower()
    no_punct = _PUNCT.sub(" ", lowered)
    collapsed = _WHITESPACE.sub(" ", no_punct).strip()
    return collapsed


__all__ = ["normalize_for_eval"]
