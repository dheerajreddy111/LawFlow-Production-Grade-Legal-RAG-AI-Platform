"""
Regex-based intent classifier for Indian legal queries.

Classification is deterministic: each intent has compiled patterns with
a weight (0–1). The scorer picks the intent whose patterns produce the
highest aggregate score; ties are broken by the specificity priority list.

Supported intents (most → least specific):
    citation_lookup  – exact citation formats  (AIR 1978 SC 597, SCC)
    bare_act_query   – section / article / act references
    case_lookup      – judgment / case search
    document_summary – summarise / analyse this document
    legal_research   – open-ended legal questions
    unknown          – fallback when confidence < threshold

Example outputs:
    "Find AIR 1978 SC 597"
        → {"intent": "citation_lookup", "confidence": 0.95}
    "What does Section 25F of the Industrial Disputes Act say?"
        → {"intent": "bare_act_query", "confidence": 0.89}
    "Summarize this NDA"
        → {"intent": "document_summary", "confidence": 0.90}
    "What are the conditions for anticipatory bail?"
        → {"intent": "legal_research", "confidence": 0.65}
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

from pydantic import BaseModel

# ── Public types ──────────────────────────────────────────────────────────────

class Intent(str, Enum):
    BARE_ACT_QUERY   = "bare_act_query"
    CASE_LOOKUP      = "case_lookup"
    CITATION_LOOKUP  = "citation_lookup"
    DOCUMENT_SUMMARY = "document_summary"
    # Broad informational queries — "Tell me about the MV Act",
    # "Explain the IT Act", "What does the Consumer Protection Act
    # cover". Routed to RAG with overview-mode retrieval so the LLM
    # produces a grounded summary of the act rather than a section
    # lookup.
    LEGAL_OVERVIEW   = "legal_overview"
    LEGAL_RESEARCH   = "legal_research"
    CONVERSATION     = "conversation"
    UNKNOWN          = "unknown"


class ClassificationResult(BaseModel):
    intent: str
    confidence: float


# ── Internal pattern registry ─────────────────────────────────────────────────

@dataclass(frozen=True)
class _Pattern:
    regex: re.Pattern[str]
    weight: float  # contribution to the score when this pattern matches


# fmt: off
_RULES: dict[Intent, list[_Pattern]] = {

    # ── Conversation ───────────────────────────────────────────────────────
    # Pure greetings / pleasantries. Anchored to the WHOLE message (with a
    # short trailing allowance) so "Hi, what does Section 302 say?" still
    # routes to the legal intent, not conversation.
    # Trailing tail: up to 4 short *alphabetic* words (+ punctuation). No
    # digits — so "hi, what does section 420 say?" can never match here and
    # still routes to the legal intent.
    Intent.CONVERSATION: [
        # "hi", "hello there", "hey", "yo", "hiya", "namaste", "greetings"
        _Pattern(re.compile(
            r"^\s*(hi+|hey+|hello|hiya|yo|namaste|greetings)"
            r"(?:\s+[a-z]+){0,4}[\s,.!'-]*$",                       re.I), 0.96),
        # "thanks", "thank you so much", "thx", "ty", "much appreciated"
        _Pattern(re.compile(
            r"^\s*(thanks|thank\s*you|thanx|thx|ty|appreciate|cheers)"
            r"(?:\s+[a-z]+){0,4}[\s,.!'-]*$",                       re.I), 0.96),
        # "good morning lawflow", "good evening", "gm", "gn"
        _Pattern(re.compile(
            r"^\s*(good\s+(morning|afternoon|evening|night)|gm|gn)"
            r"(?:\s+[a-z]+){0,4}[\s,.!'-]*$",                       re.I), 0.96),
        # "ok", "okay", "cool", "great", "got it", "bye"
        _Pattern(re.compile(
            r"^\s*(ok(ay)?|k|cool|great|nice|awesome|got\s*it|"
            r"bye|goodbye|see\s+you)(?:\s+[a-z]+){0,3}[\s,.!'-]*$", re.I), 0.90),
        # "how are you", "who are you", "what can you do"
        _Pattern(re.compile(
            r"^\s*(how\s+are\s+you|who\s+are\s+you|what\s+can\s+you\s+do|"
            r"what\s+is\s+lawflow|are\s+you\s+a\s+(bot|ai|robot))"
            r"[\s,.!?'-]{0,10}$",                                   re.I), 0.93),
    ],

    # ── Citation lookup ────────────────────────────────────────────────────
    # Matches exact Indian citation formats; highest specificity.
    Intent.CITATION_LOOKUP: [
        # Full AIR  —  "AIR 1978 SC 597"
        _Pattern(re.compile(r'\bair\s+\d{4}\s+\w+\s+\d+',         re.I), 0.95),
        # Bare AIR year  —  "AIR 2020"
        _Pattern(re.compile(r'\bair\s+\d{4}\b',                    re.I), 0.80),
        # SCC  —  "(1990) 3 SCC 682"
        _Pattern(re.compile(r'\(\d{4}\)\s+\d+\s+scc\b',            re.I), 0.95),
        # SCC OnLine  —  "2023 SCC OnLine SC 1234"
        _Pattern(re.compile(r'\d{4}\s+scc\s+online\b',             re.I), 0.95),
        # SCR  —  "1990 SCR 1234"
        _Pattern(re.compile(r'\d{4}\s+scr\b',                      re.I), 0.80),
        # Criminal Law Journal  —  "2019 Cri LJ 500"
        _Pattern(re.compile(r'\d{4}\s+cri\s*lj\b',                 re.I), 0.80),
        # Madras / Bombay reporters
        _Pattern(re.compile(r'\d{4}\s+mlj\b',                      re.I), 0.75),
        _Pattern(re.compile(r'\d{4}\s+blr\b',                      re.I), 0.75),
        # Explicit fetch phrases
        _Pattern(re.compile(
            r'\b(find|fetch|get|show)\b.{0,30}\bcitation\b',        re.I), 0.70),
        _Pattern(re.compile(
            r'\bfull\s+text\b.{0,30}\b(judgment|judgement)\b',      re.I), 0.65),
    ],

    # ── Bare act query ─────────────────────────────────────────────────────
    # Section / article / named-act references.
    Intent.BARE_ACT_QUERY: [
        # "Section 25F",  "section 138A"
        _Pattern(re.compile(r'\bsection\s+\d+[a-z]?\b',            re.I), 0.85),
        # "s. 302",  "s.25"
        _Pattern(re.compile(r'\bs\s*\.\s*\d+[a-z]?\b',             re.I), 0.75),
        # "Article 226",  "Article 14"
        _Pattern(re.compile(r'\barticle\s+\d+[a-z]?\b',            re.I), 0.85),
        # "art. 21"
        _Pattern(re.compile(r'\bart\s*\.\s*\d+[a-z]?\b',           re.I), 0.75),
        # Named Acts with year  —  "Industrial Disputes Act, 1947"
        _Pattern(re.compile(
            r'\b\w[\w\s]{2,35}act\s*,?\s*\d{4}\b',                  re.I), 0.80),
        # Well-known Indian act abbreviations
        _Pattern(re.compile(
            r'\b(ipc|crpc|cpc|ibc|fema|pmla|rera|ndps|pocso|posh|'
            r'rti\s*act|tpa|ni\s*act|it\s*act|companies\s+act|'
            r'gst\s*act|arbitration\s+act)\b',                       re.I), 0.75),
        # "Schedule IV",  "Schedule VII"
        _Pattern(re.compile(r'\bschedule\s+[ivxIVX]{1,5}\b',        re.I), 0.70),
        # "clause (a)",  "sub-section (2)",  "proviso to section"
        _Pattern(re.compile(
            r'\b(clause|sub-?section|proviso)\s+\(?\w\)?',           re.I), 0.65),
    ],

    # ── Legal overview ─────────────────────────────────────────────────────
    # Broad informational queries about an Act / Code / Constitution that
    # are NOT section-specific. Distinct from BARE_ACT_QUERY (which is a
    # narrow lookup of a numbered provision) and from LEGAL_RESEARCH
    # (which is an open scenario question). The legal_service confirms an
    # act actually resolves before dispatching to overview retrieval; if
    # not, it falls back to standard RAG.
    Intent.LEGAL_OVERVIEW: [
        # "tell me about X"
        _Pattern(re.compile(
            r"\btell\s+me\s+(more\s+)?about\b", re.I), 0.83),
        # "give me an overview / introduction (of/to/on) X"
        _Pattern(re.compile(
            r"\b(overview|introduction|summary|brief)\s+(of|to|on|about)\b",
            re.I), 0.86),
        # "what does X cover / deal with / regulate / govern / contain"
        _Pattern(re.compile(
            r"\bwhat\s+does\b.{0,40}\b("
            r"cover|deal\s+with|regulate|govern|contain|provide|"
            r"address|include)\b",                                  re.I), 0.86),
        # "what is the X act / code / constitution"
        # The trailing keyword (act|code|constitution|sanhita) is the
        # signal that this is an Act-level question, not a section one.
        _Pattern(re.compile(
            r"\bwhat\s+is\s+(the\s+)?[\w\s]{0,40}\b"
            r"(act|code|constitution|sanhita|adhiniyam)\b",         re.I), 0.84),
        # "explain (the) X law/act/code"
        _Pattern(re.compile(
            r"\bexplain\s+(the\s+)?[\w\s]{0,40}\b"
            r"(act|code|constitution|sanhita|adhiniyam|law)\b",     re.I), 0.82),
        # "purpose / scope / aim / objective of (the) X act"
        _Pattern(re.compile(
            r"\b(purpose|scope|aim|objective|object|ambit)\s+"
            r"of\s+(the\s+)?[\w\s]{0,40}\b"
            r"(act|code|constitution|sanhita|adhiniyam)\b",         re.I), 0.84),
        # "main provisions / key provisions / important sections of X"
        # — distinct from "what does Section 302 say" because no
        # number is cited and the phrase is plural / overview-shaped.
        _Pattern(re.compile(
            r"\b(main|key|important|major)\s+"
            r"(provisions|sections|features|areas|topics|points)\b", re.I), 0.78),
    ],

    # ── Case lookup ────────────────────────────────────────────────────────
    # Searching for judgments or named cases.
    Intent.CASE_LOOKUP: [
        # "Maneka Gandhi v. Union of India"  (both sides capitalised)
        _Pattern(re.compile(
            r'\b[a-z]\w[\w\s]{1,30}\bv\.?\s+[a-z]\w[\w\s]{1,30}',  re.I), 0.85),
        # "landmark case / judgment"
        _Pattern(re.compile(r'\blandmark\s+(case|judgment|ruling)\b',re.I), 0.80),
        # "Supreme Court held / ruled / rule / say"
        _Pattern(re.compile(
            r'\b(supreme\s+court|high\s+court|\bsc\b|\bhc\b|nclat|nclt)'
            r'.{0,25}\b(held|hold|ruled|rule|decided|decide|observed|say|said)\b',
                                                                      re.I), 0.80),
        # "find / show cases / judgments on X"
        _Pattern(re.compile(
            r'\b(find|show|get|search|look\s+up)\b.{0,30}'
            r'\b(case|cases|judgments?|judgements?|ruling[s]?)\b',   re.I), 0.80),
        # "judgment on / ruling in"
        _Pattern(re.compile(
            r'\b(judgments?|judgements?|ruling[s]?|verdict|decision)\b'
            r'.{0,30}\b(on|in|about|regarding)\b',                   re.I), 0.75),
        # Writ petitions
        _Pattern(re.compile(
            r'\bwrit\s+(petition|of\s+'
            r'(mandamus|certiorari|prohibition|habeas\s+corpus|quo\s+warranto))',
                                                                      re.I), 0.70),
        # "precedent"
        _Pattern(re.compile(r'\bprecedent\b',                        re.I), 0.65),
    ],

    # ── Document summary ───────────────────────────────────────────────────
    # Requests to analyse or summarise an attached/described document.
    Intent.DOCUMENT_SUMMARY: [
        # Explicit summarise verbs
        _Pattern(re.compile(r'\b(summarize|summarise|summary)\b',    re.I), 0.90),
        # TL;DR
        _Pattern(re.compile(r'\btl[\s;:\-,]?dr\b',                   re.I), 0.90),
        # "analyze / review this contract"
        _Pattern(re.compile(
            r'\b(analyze|analyse|review|explain)\s+(this|the|my)\s+'
            r'(document|contract|agreement|notice|deed|letter|order|'
            r'nda|judgment|plaint|petition)',                          re.I), 0.85),
        # "give me the gist / overview"
        _Pattern(re.compile(
            r'\b(give\s+me|provide)\s+(a|the)\s+'
            r'(summary|gist|overview|brief)\b',                       re.I), 0.80),
        # "key clauses / provisions"
        _Pattern(re.compile(
            r'\b(key|important|critical|main)\s+'
            r'(clauses|points|provisions|terms|issues|obligations)\b', re.I), 0.75),
        # "what does this contract say?"
        _Pattern(re.compile(
            r'\bwhat\s+(does|is)\s+(this|the)\s+'
            r'(document|contract|agreement|notice|deed)\b',            re.I), 0.75),
        # "extract clauses"
        _Pattern(re.compile(
            r'\bextract\s+(clauses|provisions|terms|obligations)\b',   re.I), 0.75),
        # "highlight the key points"
        _Pattern(re.compile(
            r'\bhighlight\s+(the\s+)?(key|main|important|critical)\b', re.I), 0.70),
    ],

    # ── Legal research ─────────────────────────────────────────────────────
    # Open-ended legal questions; broadest patterns, lowest base weights.
    Intent.LEGAL_RESEARCH: [
        # ── Conversational / practical legal questions ──────────────────
        # How a non-lawyer actually phrases a legal question. Weighted high
        # enough to clear the UNKNOWN threshold (→ RAG), but below the
        # bare-act/citation specificity weights so an explicit "Section 302"
        # still wins a deterministic lookup.
        _Pattern(re.compile(r'\bwhat\s+happens\s+if\b',               re.I), 0.66),
        _Pattern(re.compile(
            r'\bwhat\s+if\s+(some\s?one|i|we|a|an|my|he|she|they|the)\b',
                                                                       re.I), 0.64),
        _Pattern(re.compile(r'\bcan\s+(the\s+)?police\b',             re.I), 0.68),
        _Pattern(re.compile(
            r'\bcan\s+(i|we|you|he|she|they|a|an|my|some\s?one)\b',    re.I), 0.60),
        _Pattern(re.compile(
            r'\b(is|are|was|were)\s+it\s+(legal|illegal|a\s+crime|'
            r'an\s+offen[cs]e|allowed|valid|mandatory|punishable)\b',  re.I), 0.66),
        _Pattern(re.compile(
            r'\bis\s+.{0,40}?\b(legal|illegal|valid|admissible|allowed|'
            r'mandatory|punishable|enforceable|a\s+crime|an\s+offen[cs]e)\b',
                                                                       re.I), 0.62),
        _Pattern(re.compile(
            r'\b(punishment|penalty|fine|sentence|jail|imprisonment)\s+for\b',
                                                                       re.I), 0.66),
        _Pattern(re.compile(r'\blegal\s+consequences?\b',             re.I), 0.66),
        _Pattern(re.compile(r'\bconsequences?\s+(of|for|if)\b',       re.I), 0.58),
        _Pattern(re.compile(
            r'\b(do\s+i\s+need|is\s+it\s+necessary|is\s+it\s+mandatory|'
            r'am\s+i\s+(allowed|required|liable|entitled|obligated)|'
            r'do\s+i\s+have\s+to)\b',                                  re.I), 0.62),
        _Pattern(re.compile(
            r'\b(my|our|the)\s+(legal\s+)?(rights|liabilit(y|ies)|'
            r'obligations|options|remed(y|ies))\b',                    re.I), 0.55),
        # Broad legal-vocabulary floor — any legal *topic*, even as a bare
        # noun phrase ("cheque bounce", "land grabbing"), clears UNKNOWN and
        # routes to RAG. Multi-word topics and word-stems (cyber\w*,
        # corrupt\w*) keep this resilient to phrasing rather than relying on
        # exact keywords.
        _Pattern(re.compile(
            r'\b(police|arrest|warrant|bail|anticipatory|fir|complaint|'
            r'evidence|witness|helmet|licen[cs]e|accident|divorce|tenant|'
            r'landlord|contract|breach|notice|harass\w*|dowry|defamation|'
            r'slander|libel|cheat\w*|fraud\w*|forgery|theft|robbery|'
            r'extortion|custody|maintenance|alimony|compensation|'
            r'negligence|liabilit(y|ies)|consumer|deficiency|'
            r'cyber\w*|hack\w*|phishing|trespass|nuisance|eviction|'
            r'patent|copyright|trademark|bankrupt\w*|insolvenc\w*|'
            r'sue|lawsuit|litigation|sedition|murder|homicide|assault|'
            r'kidnap\w*|rape|molestation|pocso|abuse|bribe\w*|corrupt\w*|'
            r'money\s*launder\w*|smuggl\w*|narcotic|ndps|'
            r'land\s*grab\w*|encroach\w*|propert(y|ies)|inheritance|'
            r'succession|will\s+dispute|partition|'
            r'che(que|ck)\s*(bounce|dishonou?r)|dishonou?r\s+of\s+che(que|ck)|'
            r'domestic\s+violence|workplace\s+harass\w*|'
            r'wrongful\s+(termination|dismissal|arrest|confinement)|'
            r'human\s+rights|constitutional|writ|pil|rti|'
            r'gst|income\s+tax|tax\s+evasion|gratuity|provident\s+fund|'
            r'retrenchment|wages|labour|employment|termination|'
            r'arbitration|injunction|specific\s+performance|'
            r'cognizable|non-?bailable|charge\s*sheet|remand|'
            r'acquittal|conviction|appeal|review\s+petition)\b',       re.I), 0.52),

        # "what are the conditions / grounds / requirements / procedure for ..."
        # High weight — even if a section reference co-occurs, the primary
        # intent is research, not a bare-act lookup.
        _Pattern(re.compile(
            r'\bwhat\s+are\s+(the\s+)?(conditions|grounds|requirements|'
            r'elements|procedure)\s+for\b',                            re.I), 0.87),
        _Pattern(re.compile(
            r'\b(conditions|grounds|requirements|elements|procedure)\s+for\b',
                                                                       re.I), 0.82),
        # "what are the X" (broader)
        _Pattern(re.compile(
            r'\bwhat\s+(are|is)\s+(the\s+)?(conditions|grounds|requirements|'
            r'elements|procedure|process|steps|rights|remedies|liabilities)',
                                                                       re.I), 0.65),
        # "how does / can X work / apply"
        _Pattern(re.compile(
            r'\bhow\s+(does|do|can|to)\s+.{3,60}'
            r'\b(work|apply|operate|function|enforce)\b',              re.I), 0.60),
        # "can I sue / file / appeal ..."
        _Pattern(re.compile(
            r'\b(can|may|could|should)\s+(i|we|one|a\s+\w+|an?\s+\w+)\s+'
            r'(sue|file|appeal|challenge|claim|approach|invoke|enforce)\b',
                                                                       re.I), 0.65),
        # "doctrine / principle of ..."
        _Pattern(re.compile(
            r'\b(doctrine|principle|maxim|rule|concept)\s+(of|that|known)\b',
                                                                       re.I), 0.65),
        # "under the / under Indian law"
        _Pattern(re.compile(
            r'\bunder\s+(the|indian)\s+(law|act|code)\b',              re.I), 0.60),
        # "meaning / scope / applicability of ..."
        _Pattern(re.compile(
            r'\b(explain|define|describe|elaborate\s+on|what\s+is)\s+'
            r'(the\s+)?(meaning|scope|ambit|applicability|purview)\b', re.I), 0.65),
        # Generic legal terms — weakest signals, provide a floor
        _Pattern(re.compile(
            r'\b(rights|obligations|liability|duties|remedies|reliefs)\b',
                                                                       re.I), 0.50),
        _Pattern(re.compile(r'\b(explain|define|describe)\b',          re.I), 0.50),
    ],
}
# fmt: on


# ── Scoring constants ─────────────────────────────────────────────────────────

# Each additional matched pattern beyond the first adds this bonus.
_MULTI_MATCH_BONUS: float = 0.04
# Bonus is capped so scores stay below 1.0.
_MAX_BONUS: float = 0.10
# Below this threshold the result is demoted to UNKNOWN.
_MIN_CONFIDENCE: float = 0.45

# Tie-breaking order: lower index wins when two intents score equally.
_PRIORITY: list[Intent] = [
    Intent.CITATION_LOOKUP,
    Intent.BARE_ACT_QUERY,
    # LEGAL_OVERVIEW sits below BARE_ACT_QUERY so an explicit section
    # citation ("Section 302") wins over an overview cue ("tell me
    # about Section 302"). Sits above CASE_LOOKUP / LEGAL_RESEARCH so a
    # clear overview phrase isn't pulled into broader research.
    Intent.LEGAL_OVERVIEW,
    Intent.CASE_LOOKUP,
    Intent.DOCUMENT_SUMMARY,
    Intent.LEGAL_RESEARCH,
    Intent.CONVERSATION,
]


# ── Classifier ────────────────────────────────────────────────────────────────

class IntentClassifier:
    """Stateless, regex-based intent classifier.

    Async interface is preserved for drop-in replacement with an
    LLM-based classifier once the corpus warrants it.
    """

    async def classify(self, query: str) -> ClassificationResult:
        scores: dict[Intent, float] = {}

        for intent, patterns in _RULES.items():
            matched = [p for p in patterns if p.regex.search(query)]
            if not matched:
                continue
            base = max(p.weight for p in matched)
            bonus = min(_MULTI_MATCH_BONUS * (len(matched) - 1), _MAX_BONUS)
            scores[intent] = min(base + bonus, 0.99)

        if not scores or max(scores.values()) < _MIN_CONFIDENCE:
            return ClassificationResult(intent=Intent.UNKNOWN, confidence=0.50)

        best_score = max(scores.values())
        # Stable tie-break: prefer the intent highest in the specificity list.
        candidates = [i for i, s in scores.items() if s == best_score]
        best = min(
            candidates,
            key=lambda i: _PRIORITY.index(i) if i in _PRIORITY else len(_PRIORITY),
        )

        return ClassificationResult(intent=best, confidence=round(best_score, 2))
