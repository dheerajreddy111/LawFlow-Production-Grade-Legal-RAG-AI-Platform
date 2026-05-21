"""Token-F1 + keyword-overlap regressions after the noise-stripping pass.

Locks in the three properties that lift the metric out of measurement
artifact range:

  - SQuAD-style article stripping (a/an/the)
  - Pipeline scaffolding stripped (citation markers, source parens,
    section-header lines, the standard disclaimer)
  - Real misses still score low — the metric does not lie

If a future change tightens or loosens any of these, this file will fail
and force a deliberate decision.
"""

from __future__ import annotations

from app.evaluation.metrics import keyword_overlap, token_f1

# ── Article stripping (SQuAD parity) ───────────────────────────────────────


def test_token_f1_ignores_articles():
    """`a/an/the` must not influence F1 — same SQuAD normalisation."""
    a = token_f1("punishment for murder", "the punishment for a murder")
    b = token_f1("punishment for murder", "punishment for murder")
    assert a == b == 1.0


# ── Citation marker scaffolding ────────────────────────────────────────────


def test_citation_markers_do_not_dilute_precision():
    """`[1]`, `[2]` are pipeline artefacts and must not count as tokens."""
    clean = token_f1(
        "Section 302 punishes murder with imprisonment for life or death",
        "Section 302 punishes murder with imprisonment for life or death",
    )
    noisy = token_f1(
        "Section 302 [1] punishes murder [2] with imprisonment for life or death [3]",
        "Section 302 punishes murder with imprisonment for life or death",
    )
    assert clean == 1.0
    assert noisy == 1.0, f"expected 1.0, got {noisy}"


def test_source_parentheticals_stripped():
    f1 = token_f1(
        "Murder is punishable (source: IPC Section 302) with death or life",
        "Murder is punishable with death or life",
    )
    assert f1 == 1.0


# ── Section-header lines ───────────────────────────────────────────────────


def test_section_header_lines_stripped():
    """The prompt-injected ``Section X — Title`` heading is scaffolding."""
    generated = (
        "Section 302 — Punishment for murder\n"
        "Whoever commits murder shall be punished with death or imprisonment for life."
    )
    expected = (
        "Whoever commits murder shall be punished with death or imprisonment for life."
    )
    assert token_f1(generated, expected) == 1.0


# ── Disclaimer / framing boilerplate ───────────────────────────────────────


def test_disclaimer_does_not_pull_score_down():
    """The 'legal information, not legal advice' footer is constant overhead."""
    expected = "Theft means dishonestly taking movable property without consent."
    generated = (
        "Theft means dishonestly taking movable property without consent. "
        "This is legal information, not legal advice. "
        "Refer to the cited sources below for the authoritative text and judgments."
    )
    f1 = token_f1(generated, expected)
    # Without stripping, this scored ~0.40 (precision ~25/40). With stripping,
    # both sides reduce to the same content and the score is 1.0.
    assert f1 == 1.0


def test_compose_framing_stripped():
    """`Based on your question, here is what …` framing is pipeline prose."""
    expected = "Article 21 protects life and personal liberty."
    generated = (
        "Based on your question, here is what the relevant Indian law provides. "
        "The most applicable provisions in the LawFlow corpus are: "
        "Article 21 protects life and personal liberty."
    )
    f1 = token_f1(generated, expected)
    assert f1 >= 0.95


# ── Keyword overlap inherits the same normalisation ────────────────────────


def test_keyword_overlap_uses_cleaned_text():
    expected = "murder dishonestly imprisonment"
    generated = "Murder, dishonestly, imprisonment [1] (source: IPC). This is legal information, not legal advice."
    # Without cleaning, the noise tokens shrink the Jaccard. After cleaning
    # both sides reduce to {murder, dishonestly, imprisonment}.
    assert keyword_overlap(generated, expected) == 1.0


# ── Honesty guard: a wrong answer still scores low ─────────────────────────


def test_wrong_answer_still_scores_low():
    """The noise stripping must not artificially lift a bad answer's score.

    If the generated text genuinely doesn't share content with expected,
    F1 should reflect that.
    """
    expected = (
        "Section 302 IPC: whoever commits murder shall be punished with "
        "death or life imprisonment."
    )
    generated = (
        "Section 138 of the NI Act deals with the dishonour of cheques. "
        "This is legal information, not legal advice."
    )
    f1 = token_f1(generated, expected)
    # Some incidental overlap on "section" + "shall be punished" is fine,
    # but the score must remain well below the typical correct-answer
    # floor of ~0.5.
    assert f1 < 0.35, f"wrong answer scored too high: {f1}"


def test_empty_both_is_one_empty_one_is_zero():
    assert token_f1("", "") == 1.0
    assert token_f1("anything", "") == 0.0
    assert token_f1("", "anything") == 0.0


# ── Inflection / stemming (paraphrase robustness) ──────────────────────────


def test_inflectional_variants_match_via_stem():
    """`commits` / `committing` / `committed` / `commit` all stem to `commit`.

    Two answers that say the same thing with different verb tense must
    not be penalised. This is the key win that lifts real-world F1 out
    of the 0.5–0.7 range.
    """
    from app.evaluation.metrics import _stem

    for variant in ("commits", "committing", "committed", "commit"):
        assert _stem(variant) == "commit", variant
    for variant in ("imprisonment", "imprisoned", "imprisons", "imprisoning"):
        assert _stem(variant) == "imprison", variant
    for variant in ("punishment", "punished", "punishes", "punishing"):
        assert _stem(variant) == "punish", variant


def test_paraphrased_answer_scores_high():
    """A correct answer with different inflection should score ≥ 0.7."""
    expected = (
        "A person who commits theft is guilty of dishonestly taking movable property."
    )
    generated = (
        "Theft is the act of dishonest taking of movable property by the person committing it."
    )
    f1 = token_f1(generated, expected)
    assert f1 >= 0.7, f"paraphrased correct answer scored too low: {f1}"


def test_short_tokens_not_overstemmed():
    """Tokens ≤ 3 chars stay verbatim — no `is` → `i` damage."""
    from app.evaluation.metrics import _stem

    for tok in ("is", "be", "of", "to", "in", "or", "a", "act", "fee"):
        assert _stem(tok) == tok, tok


def test_stem_does_not_overreduce_to_meaningless_stub():
    """`len(stem) >= 3` cap prevents `ration` → `r`."""
    from app.evaluation.metrics import _stem

    # 'ration' (6) - 'tion' (4) = 2 < 3 → no reduction.
    assert _stem("ration") == "ration"
    # 'station' (7) - 'tion' (4) = 3 → reduces to 'sta'. Acceptable;
    # the cutoff trades off occasional false-positives for the bulk
    # gain on inflection.
    assert len(_stem("station")) >= 3


# ── Cosine remains untouched ───────────────────────────────────────────────


def test_cosine_still_works_with_normalised_vectors():
    from app.evaluation.metrics import cosine_similarity

    assert cosine_similarity([1.0, 0.0, 0.0], [1.0, 0.0, 0.0]) == 1.0
    assert cosine_similarity([1.0, 0.0], [0.0, 1.0]) == 0.0
