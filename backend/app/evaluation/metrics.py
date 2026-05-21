"""
Metric functions for the LawFlow RAG evaluation harness.

Everything here is pure and synchronous so it stays trivially unit-testable.
Embedding generation (the only async/IO part of cosine similarity) lives in
the evaluation service; this module only does the vector math.

Metrics
-------
    token_f1          SQuAD-style token-level F1 of generated vs expected.
    keyword_overlap   Jaccard overlap of content-word (keyword) sets.
    cosine_similarity Cosine of two (already L2-normalised) embeddings.

The per-row container and the aggregator are deliberately schema-stable so a
future benchmark dashboard can chart trends over many runs without code
changes — add fields, don't rename.
"""

from __future__ import annotations

import re
import statistics
from collections import Counter

from pydantic import BaseModel, Field

# Small, domain-neutral stopword list. Kept short on purpose: legal answers
# are dense, and over-aggressive filtering throws away meaningful terms.
_STOPWORDS: frozenset[str] = frozenset(
    """
    a an the and or but if then else of to in on at by for with without from
    is are was were be been being it its this that these those as not no nor
    do does did have has had will shall may might can could would should
    """.split()
)

# SQuAD-style F1 normalisation strips only articles (a/an/the), not the full
# stopword set — over-aggressive stripping makes the metric lie. The richer
# stopword filter above is reserved for ``keyword_overlap`` where coverage,
# not precision, is the question.
_ARTICLES: frozenset[str] = frozenset({"a", "an", "the"})

_WORD_RE = re.compile(r"[a-z0-9]+")

# ── Pipeline-artifact stripping ───────────────────────────────────────────────
#
# The generated answer always carries scaffolding the ground-truth
# expected_answer does not: numbered citation markers (``[1]``), parenthetical
# source attributions (``(source: IPC Section 302)``), one-line section
# headers our prompt template injects, and the disclaimer the system message
# appends. None of these reflect answer quality — they're constant overhead
# the prompt adds. Stripping them before tokenisation lifts F1 to a more
# honest range (the disclaimer alone is ~10 tokens, ~25% of a typical short
# expected_answer).
#
# Each pattern is added individually so the entries stay auditable; a
# future evaluation dataset that DOES include disclaimers in
# expected_answer can drop entries here without other changes.

_CITATION_MARKER = re.compile(r"\[\d{1,3}\]")
_SOURCE_PAREN = re.compile(r"\(source:\s*[^)]+\)", re.IGNORECASE)
_SECTION_HEADER_LINE = re.compile(
    r"^\*{0,2}(?:section|article|clause)\s+\d+[A-Za-z]?\s*[—\-:].*$",
    re.MULTILINE | re.IGNORECASE,
)
_FANCY_DASH = re.compile(r"[–—‒]")

_BOILERPLATE_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE | re.DOTALL)
    for p in (
        r"this is legal information,?\s*not legal advice\.?",
        r"refer to the cited sources below[^.]*\.",
        r"key authority:[^\n]*",
        # Common framing the LLM picks up from the system prompt — these
        # appear in every answer regardless of content.
        r"based on your question[^.]*\.",
        r"here is what the relevant indian law provides[^.]*\.",
        r"the most applicable provisions in the lawflow corpus are:?",
        r"primary provisions? matching your query:?",
        # The "I could not find …" fallback is content-relevant only when
        # the expected_answer is also a "not found" string. In every other
        # case stripping it makes a no-retrieval row score 0 rather than
        # confusing the F1 with disclaimer tokens.
        r"i could not find any relevant passages[^.]*\.",
    )
)


def _strip_pipeline_noise(text: str) -> str:
    """Remove RAG-pipeline scaffolding before tokenising.

    Citation markers, source-attribution parens, section-header lines,
    and the standard disclaimer are constant overhead the prompt adds
    on top of the answer's actual content. They taint F1 / keyword
    overlap because they always appear in ``generated`` but never in
    ``expected``. Stripping is idempotent and safe for the
    ``expected_answer`` side too.
    """
    if not text:
        return text
    text = _CITATION_MARKER.sub(" ", text)
    text = _SOURCE_PAREN.sub(" ", text)
    text = _SECTION_HEADER_LINE.sub(" ", text)
    for pat in _BOILERPLATE_PATTERNS:
        text = pat.sub(" ", text)
    text = _FANCY_DASH.sub(" ", text)
    return text


# ── Suffix-stripping stemmer ─────────────────────────────────────────────────
#
# Token-level F1 punishes paraphrase aggressively. A correct legal answer that
# reads "imprisonment for life" will mismatch an expected "imprisoned for
# life" on every token despite identical meaning. Light suffix stripping
# folds inflectional variants onto a shared stem:
#
#     imprisonment / imprisoned / imprisons / imprisoning  → imprison
#     punishment / punished / punishes / punishing         → punish
#     commits / committed / committing                     → commit
#
# The cutoff ``len(stem) >= 3`` prevents over-reduction (e.g. "ration" →
# "r"). Suffixes are tried longest-first so a four-letter suffix is
# matched before a one-letter one. This is deliberately simpler than
# Porter; pure Python, no extra deps, and behaviour is auditable in
# tests.
#
# Side-effect: occasional false merges like "states" → "stat" (collides
# with "static" → "stat"). Acceptable trade-off — both metrics are
# already approximate, and the noise-reduction win on inflection
# dominates the rare false positive in legal English.

_SUFFIXES: tuple[str, ...] = (
    "ities", "ments", "sions", "tions",
    "iest", "ally", "edly", "ment", "ness", "sion", "tion",
    "ies", "ing", "ity",
    "ed", "er", "es", "ly", "s",
)


def _stem(token: str) -> str:
    """Strip a common English suffix while preserving meaningful stems.

    Handles the doubled-consonant case ("committing" → "committ" → "commit",
    "stopped" → "stopp" → "stop") so inflectional variants land on the
    same stem.
    """
    if len(token) <= 3:
        return token
    for sfx in _SUFFIXES:
        if token.endswith(sfx) and len(token) - len(sfx) >= 3:
            stem = token[: -len(sfx)]
            # Gemination undo — applies only to verbal-inflection suffixes
            # where English routinely doubles the final consonant
            # (-ed/-ing/-er). Skip the vowels + y so "ball" / "puzzle"
            # are unaffected.
            if sfx in ("ed", "ing", "er") and len(stem) >= 4:
                if stem[-1] == stem[-2] and stem[-1] not in "aeiouy":
                    stem = stem[:-1]
            return stem
    return token


def _normalize(text: str) -> str:
    return _strip_pipeline_noise(text).lower().strip()


def _tokens(text: str) -> list[str]:
    """Lowercase alphanumeric stems with articles removed.

    SQuAD's normalize_answer drops a/an/the and punctuation. We do the
    same plus:

    - pipeline-artifact strip so legal-RAG scaffolding (citation
      markers, disclaimer) doesn't pollute the multiset
    - light suffix stemming so inflectional paraphrase
      ("imprisons" vs "imprisoned") doesn't score as a miss

    The combination lifts F1 on paraphrased-but-correct legal answers
    while preserving the honesty guard — wrong answers don't share
    stems either.
    """
    return [
        _stem(t)
        for t in _WORD_RE.findall(_normalize(text))
        if t not in _ARTICLES
    ]


def _keywords(text: str) -> set[str]:
    """Content stems: keyword tokens (≥ 3 chars, non-stopword), stemmed.

    Operates on the same noise-stripped + stemmed pipeline as ``_tokens``
    so both metrics agree on what counts as content.
    """
    return {
        _stem(t)
        for t in _WORD_RE.findall(_normalize(text))
        if len(t) >= 3 and t not in _STOPWORDS
    }


def token_f1(generated: str, expected: str) -> float:
    """SQuAD-style token-level F1 (multiset overlap).

    Precision = shared / len(generated); Recall = shared / len(expected);
    F1 is their harmonic mean. Returns 0.0 when either side is empty (unless
    both are empty, which scores 1.0).
    """
    g, e = _tokens(generated), _tokens(expected)
    if not g and not e:
        return 1.0
    if not g or not e:
        return 0.0

    shared = sum((Counter(g) & Counter(e)).values())
    if shared == 0:
        return 0.0

    precision = shared / len(g)
    recall = shared / len(e)
    return round(2 * precision * recall / (precision + recall), 4)


def keyword_overlap(generated: str, expected: str) -> float:
    """Jaccard overlap of keyword sets: |G∩E| / |G∪E|.

    1.0 when both have no keywords (vacuously identical); 0.0 when only one
    side has keywords.
    """
    g, e = _keywords(generated), _keywords(expected)
    if not g and not e:
        return 1.0
    union = g | e
    if not union:
        return 0.0
    return round(len(g & e) / len(union), 4)


def cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
    """Cosine similarity of two equal-length vectors.

    EmbeddingService returns L2-normalised vectors, so this is just the dot
    product; we still divide by norms defensively for non-normalised input.
    Clamped to [0.0, 1.0] for dashboard-friendly scoring.
    """
    if not vec_a or not vec_b or len(vec_a) != len(vec_b):
        return 0.0
    dot = sum(a * b for a, b in zip(vec_a, vec_b))
    na = sum(a * a for a in vec_a) ** 0.5
    nb = sum(b * b for b in vec_b) ** 0.5
    if na == 0.0 or nb == 0.0:
        return 0.0
    return round(max(0.0, min(1.0, dot / (na * nb))), 4)


# ── Result schemas (dashboard-stable) ─────────────────────────────────────────

class RowResult(BaseModel):
    """One evaluated test-set row."""

    question: str
    expected_answer: str
    generated_answer: str
    f1_score: float
    cosine_similarity: float
    keyword_overlap: float
    retrieval_confidence: float
    intent: str | None = None
    route: str | None = None
    error: str | None = None  # populated if this row failed to run


class MetricSummary(BaseModel):
    """Mean / min / max of one metric across all scored rows."""

    mean: float
    min: float
    max: float


class EvaluationSummary(BaseModel):
    dataset: str
    total_rows: int
    scored_rows: int
    failed_rows: int
    f1_score: MetricSummary
    cosine_similarity: MetricSummary
    keyword_overlap: MetricSummary
    retrieval_confidence: MetricSummary


def _summarise(values: list[float]) -> MetricSummary:
    if not values:
        return MetricSummary(mean=0.0, min=0.0, max=0.0)
    return MetricSummary(
        mean=round(statistics.fmean(values), 4),
        min=round(min(values), 4),
        max=round(max(values), 4),
    )


def aggregate(dataset: str, rows: list[RowResult]) -> EvaluationSummary:
    """Roll per-row results up into a dashboard-ready summary."""
    scored = [r for r in rows if r.error is None]

    def col(attr: str) -> list[float]:
        return [getattr(r, attr) for r in scored]

    return EvaluationSummary(
        dataset=dataset,
        total_rows=len(rows),
        scored_rows=len(scored),
        failed_rows=len(rows) - len(scored),
        f1_score=_summarise(col("f1_score")),
        cosine_similarity=_summarise(col("cosine_similarity")),
        keyword_overlap=_summarise(col("keyword_overlap")),
        retrieval_confidence=_summarise(col("retrieval_confidence")),
    )


class EvaluationReport(BaseModel):
    """Full evaluation response: summary + per-row breakdown."""

    summary: EvaluationSummary
    results: list[RowResult] = Field(default_factory=list)
