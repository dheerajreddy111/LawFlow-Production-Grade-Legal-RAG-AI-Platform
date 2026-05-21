"""
Regex-based legal entity extractor for Indian legal text.

Five entity types, each with compiled patterns ordered from most to least
specific.  Overlapping spans are resolved by (confidence desc, length desc),
so a full "AIR 1978 SC 597" always wins over a bare "AIR 1978".

Entity types:
    ACT             – "IPC", "Industrial Disputes Act, 1947", "CrPC"
    SECTION         – "Section 25F", "Sec. 138", "Section 302(1)"
    ARTICLE         – "Article 226", "Art. 21"
    LEGAL_CITATION  – "AIR 1978 SC 597", "(1990) 3 SCC 682"
    COURT           – "Supreme Court of India", "Delhi High Court", "NCLAT"

Example output:
    extract("IPC Section 420 — Delhi High Court, AIR 1973 SC 1461")

    {
      "entities": [
        {"type": "ACT",            "value": "IPC",                  "confidence": 0.93, "start": 0,  "end": 3},
        {"type": "SECTION",        "value": "Section 420",          "confidence": 0.93, "start": 4,  "end": 15},
        {"type": "COURT",          "value": "Delhi High Court",     "confidence": 0.95, "start": 18, "end": 34},
        {"type": "LEGAL_CITATION", "value": "AIR 1973 SC 1461",     "confidence": 0.97, "start": 36, "end": 53}
      ]
    }
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Callable

from pydantic import BaseModel

# ── Public types ──────────────────────────────────────────────────────────────

class EntityType(str, Enum):
    ACT            = "ACT"
    SECTION        = "SECTION"
    ARTICLE        = "ARTICLE"
    LEGAL_CITATION = "LEGAL_CITATION"
    COURT          = "COURT"


class LegalEntity(BaseModel):
    type: str
    value: str
    confidence: float
    start: int
    end: int


class ExtractionResult(BaseModel):
    entities: list[LegalEntity]


# ── Internal rule type ────────────────────────────────────────────────────────

@dataclass(frozen=True)
class _Rule:
    entity_type: EntityType
    pattern: re.Pattern[str]
    confidence: float
    # Optional post-match normalization (raw span text → canonical value)
    normalizer: Callable[[str], str] | None = None


# ── Normalizers ───────────────────────────────────────────────────────────────

def _norm_section(raw: str) -> str:
    """'section 25f' → 'Section 25F',  'Sec. 138A(1)' → 'Section 138A(1)'"""
    m = re.match(
        r'(?:section|sec\.?)\s*(\d+)([a-zA-Z]?)\s*(\(\w\))?',
        raw.strip(), re.I,
    )
    if m:
        num    = m.group(1)
        suffix = m.group(2).upper() if m.group(2) else ""
        clause = m.group(3) or ""
        return f"Section {num}{suffix}{clause}"
    return raw.strip()


def _norm_act_section(raw: str) -> str:
    """'IPC 420' / '420 IPC' / 'CrPC 41' → 'Section 420'."""
    m = re.search(r'(\d+)([a-zA-Z]?)', raw)
    if m:
        return f"Section {m.group(1)}{(m.group(2) or '').upper()}"
    return raw.strip()


def _norm_article(raw: str) -> str:
    """'article 226' → 'Article 226',  'Art. 21A' → 'Article 21A'"""
    m = re.match(
        r'(?:article|art\.?)\s*(\d+)([a-zA-Z]?)\s*(\(\w\))?',
        raw.strip(), re.I,
    )
    if m:
        num    = m.group(1)
        suffix = m.group(2).upper() if m.group(2) else ""
        clause = m.group(3) or ""
        return f"Article {num}{suffix}{clause}"
    return raw.strip()


def _norm_citation(raw: str) -> str:
    return re.sub(r'\s+', ' ', raw.strip())


_LEADING_ARTICLE = re.compile(r'^(?:the|an?)\s+', re.I)

def _norm_act(raw: str) -> str:
    cleaned = re.sub(r'\s+', ' ', raw.strip())
    return _LEADING_ARTICLE.sub('', cleaned)


_COURT_CANONICAL: dict[str, str] = {
    "supreme court":          "Supreme Court of India",
    "supreme court of india": "Supreme Court of India",
    "high court":             "High Court",
    "nclat":  "NCLAT",  "nclt":  "NCLT",
    "sat":    "SAT",    "tdsat": "TDSAT",
    "ngt":    "NGT",    "itat":  "ITAT",
    "cestat": "CESTAT", "drt":   "DRT",
    "drat":   "DRAT",   "bifr":  "BIFR",
}

def _norm_court(raw: str) -> str:
    cleaned = re.sub(r'\s+', ' ', raw.strip())
    return _COURT_CANONICAL.get(cleaned.lower(), cleaned)


# ── Pattern registry (compiled once at import) ────────────────────────────────
# fmt: off
_RULES: tuple[_Rule, ...] = (

    # ── LEGAL_CITATION ────────────────────────────────────────────────────
    # Full AIR  —  "AIR 1978 SC 597"
    _Rule(EntityType.LEGAL_CITATION,
          re.compile(r'\bAIR\s+\d{4}\s+'
                     r'(?:SC|Bom|Cal|Mad|All|Del|AP|Raj|Ori|Pat|Ker|'
                     r'MP|Guj|HP|Goa|Sik|Gau|Jhr|Utr)\s+\d+', re.I),
          0.97, _norm_citation),

    # SCC volume + page  —  "(1990) 3 SCC 682"
    _Rule(EntityType.LEGAL_CITATION,
          re.compile(r'\(\d{4}\)\s+\d+\s+SCC\s+\d+', re.I),
          0.97, _norm_citation),

    # SCC OnLine  —  "2023 SCC OnLine SC 1234"
    _Rule(EntityType.LEGAL_CITATION,
          re.compile(r'\d{4}\s+SCC\s+OnLine\s+\w+\s+\d+', re.I),
          0.95, _norm_citation),

    # SCR  —  "1990 SCR 1234"
    _Rule(EntityType.LEGAL_CITATION,
          re.compile(r'\d{4}\s+SCR\s+\d+', re.I),
          0.88, _norm_citation),

    # Criminal Law Journal  —  "2019 Cri LJ 500" / "CriLJ 500"
    _Rule(EntityType.LEGAL_CITATION,
          re.compile(r'\d{4}\s+Cri\s*L\.?\s*J\.?\s+\d+', re.I),
          0.88, _norm_citation),

    # Regional reporters  —  MLJ, BLR, ILR, KLT, ALT
    _Rule(EntityType.LEGAL_CITATION,
          re.compile(r'\d{4}\s+(?:MLJ|BLR|ILR|KLT|ALT|BomCR|CLT)\s+\d+', re.I),
          0.85, _norm_citation),

    # Bare AIR year  —  "AIR 1978"  (less specific, lower confidence)
    _Rule(EntityType.LEGAL_CITATION,
          re.compile(r'\bAIR\s+\d{4}\b', re.I),
          0.72, _norm_citation),

    # ── COURT ─────────────────────────────────────────────────────────────
    # Named state High Courts  —  "Delhi High Court", "Bombay High Court"
    _Rule(EntityType.COURT,
          re.compile(
              r'\b(?:Allahabad|Bombay|Calcutta|Madras|Delhi|Gujarat|Rajasthan|'
              r'Karnataka|Kerala|Punjab\s+and\s+Haryana|Gauhati|Orissa|Patna|'
              r'Andhra\s+Pradesh|Telangana|Jharkhand|Chhattisgarh|'
              r'Himachal\s+Pradesh|Madhya\s+Pradesh|Uttarakhand|Manipur|'
              r'Meghalaya|Tripura|Sikkim)\s+High\s+Court\b', re.I),
          0.95, _norm_court),

    # "High Court of Delhi" / "High Court of Judicature at Bombay"
    _Rule(EntityType.COURT,
          re.compile(
              r'\bHigh\s+Court\s+of\s+(?:Judicature\s+at\s+)?'
              r'[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?\b', re.I),
          0.90, _norm_court),

    # Supreme Court (with or without "of India")
    _Rule(EntityType.COURT,
          re.compile(r'\bSupreme\s+Court(?:\s+of\s+India)?\b', re.I),
          0.95, _norm_court),

    # Full tribunal names
    _Rule(EntityType.COURT,
          re.compile(
              r'\bNational\s+Company\s+Law\s+(?:Appellate\s+)?Tribunal\b'
              r'|\bNational\s+Green\s+Tribunal\b'
              r'|\bIncome\s+Tax\s+Appellate\s+Tribunal\b'
              r'|\bDebt\s+Recovery\s+(?:Appellate\s+)?Tribunal\b', re.I),
          0.93, _norm_court),

    # Tribunal abbreviations
    _Rule(EntityType.COURT,
          re.compile(r'\b(?:NCLAT|NCLT|SAT|TDSAT|NGT|ITAT|CESTAT|DRT|DRAT|BIFR)\b'),
          0.92, _norm_court),

    # Generic "High Court"
    _Rule(EntityType.COURT,
          re.compile(r'\bHigh\s+Court\b', re.I),
          0.75, _norm_court),

    # ── ACT ───────────────────────────────────────────────────────────────
    # Core abbreviations — unambiguous, high confidence
    _Rule(EntityType.ACT,
          re.compile(r'\b(?:IPC|CrPC|Cr\.P\.C\.|CPC|C\.P\.C\.|IBC)\b'),
          0.93, _norm_act),

    # Secondary abbreviations
    _Rule(EntityType.ACT,
          re.compile(
              r'\b(?:FEMA|PMLA|RERA|NDPS|POCSO|POSH|TPA|SEBI\s+Act|'
              r'RTI\s+Act|NI\s+Act|IT\s+Act|GST\s+Act|MV\s+Act|'
              r'EPF\s+Act|ESIC\s+Act|SARFAESI)\b', re.I),
          0.90, _norm_act),

    # Named Codes  —  "Indian Penal Code", "Code of Criminal Procedure"
    _Rule(EntityType.ACT,
          re.compile(
              r'\b(?:Indian\s+Penal\s+Code'
              r'|Code\s+of\s+Criminal\s+Procedure'
              r'|Code\s+of\s+Civil\s+Procedure'
              r'|Insolvency\s+and\s+Bankruptcy\s+Code)\b', re.I),
          0.92, _norm_act),

    # Named Act with year  —  "Industrial Disputes Act, 1947"
    # No re.I: first letter must be uppercase, preventing "the Act" false matches.
    _Rule(EntityType.ACT,
          re.compile(
              r'\b[A-Z][a-z]{2,}'
              r'(?:\s+(?:and\s+|of\s+|for\s+|on\s+)?[A-Za-z]{2,}){1,5}'
              r'\s+Act\s*,\s*\d{4}\b'),
          0.90, _norm_act),

    # Named Act without year  —  "Companies Act", "Consumer Protection Act"
    _Rule(EntityType.ACT,
          re.compile(
              r'\b[A-Z][a-z]{2,}'
              r'(?:\s+(?:and\s+|of\s+|for\s+|on\s+)?[A-Za-z]{2,}){1,5}'
              r'\s+Act\b'),
          0.78, _norm_act),

    # ── SECTION ───────────────────────────────────────────────────────────
    # "Section 25F(1)" — with sub-clause (most specific)
    _Rule(EntityType.SECTION,
          re.compile(r'\bSection\s+\d+[A-Za-z]?\s*\(\w\)', re.I),
          0.95, _norm_section),

    # "Section 25F" / "Section 138"
    _Rule(EntityType.SECTION,
          re.compile(r'\bSection\s+\d+[A-Za-z]?\b', re.I),
          0.93, _norm_section),

    # "Sec. 302" / "Sec 302"
    _Rule(EntityType.SECTION,
          re.compile(r'\bSec\.?\s+\d+[A-Za-z]?\b', re.I),
          0.85, _norm_section),

    # Bare code-and-number — "IPC 420", "CrPC 41", "BNSS 35"
    _Rule(EntityType.SECTION,
          re.compile(
              r'\b(?:IPC|CrPC|Cr\.?P\.?C\.?|CPC|BNSS|BNS|NI\s*Act|'
              r'IT\s*Act|MV\s*Act)\s+\d+[A-Za-z]?\b', re.I),
          0.94, _norm_act_section),

    # Reversed — "420 IPC", "41 CrPC"
    _Rule(EntityType.SECTION,
          re.compile(
              r'\b\d+[A-Za-z]?\s+(?:IPC|CrPC|Cr\.?P\.?C\.?|CPC|BNSS|'
              r'BNS|NI\s*Act|IT\s*Act|MV\s*Act)\b', re.I),
          0.94, _norm_act_section),

    # ── ARTICLE ───────────────────────────────────────────────────────────
    # "Article 226(1)" — with sub-clause
    _Rule(EntityType.ARTICLE,
          re.compile(r'\bArticle\s+\d+[A-Za-z]?\s*\(\w\)', re.I),
          0.95, _norm_article),

    # "Article 226" / "Article 21"
    _Rule(EntityType.ARTICLE,
          re.compile(r'\bArticle\s+\d+[A-Za-z]?\b', re.I),
          0.93, _norm_article),

    # "Art. 21" / "Art 14"
    _Rule(EntityType.ARTICLE,
          re.compile(r'\bArt\.?\s+\d+[A-Za-z]?\b', re.I),
          0.85, _norm_article),
)
# fmt: on


# ── Extractor ─────────────────────────────────────────────────────────────────

class EntityExtractor:
    """Stateless regex-based entity extractor.

    All patterns are pre-compiled at module load; instances are cheap
    to create and safe to share across async tasks.
    """

    async def extract(self, text: str) -> ExtractionResult:
        matches  = self._match_all(text)
        resolved = self._resolve_overlaps(matches)
        return ExtractionResult(entities=resolved)

    # ── private helpers ───────────────────────────────────────────────────

    @staticmethod
    def _match_all(text: str) -> list[LegalEntity]:
        entities: list[LegalEntity] = []
        for rule in _RULES:
            for m in rule.pattern.finditer(text):
                raw   = m.group(0)
                value = rule.normalizer(raw) if rule.normalizer else raw.strip()
                entities.append(LegalEntity(
                    type=rule.entity_type,
                    value=value,
                    confidence=rule.confidence,
                    start=m.start(),
                    end=m.end(),
                ))
        return entities

    @staticmethod
    def _resolve_overlaps(matches: list[LegalEntity]) -> list[LegalEntity]:
        """Keep the best non-overlapping set of entities.

        Greedy selection ordered by (confidence desc, span length desc):
        a full "AIR 1978 SC 597" (0.97, 16 chars) beats a bare "AIR 1978"
        (0.72, 8 chars) even though they share the same start position.
        """
        candidates = sorted(
            matches,
            key=lambda e: (-e.confidence, -(e.end - e.start)),
        )
        accepted: list[LegalEntity] = []
        occupied: list[tuple[int, int]] = []  # accepted (start, end) intervals

        for entity in candidates:
            overlaps = any(
                entity.start < end and entity.end > start
                for start, end in occupied
            )
            if not overlaps:
                accepted.append(entity)
                occupied.append((entity.start, entity.end))

        return sorted(accepted, key=lambda e: e.start)
