"""
Registry for the multi-domain Indian legal knowledge base.

Three lookup tables drive dynamic corpus resolution in StatuteService:

    ACT_REGISTRY   canonical act-key → ActSpec (file, display name, unit)
    ACT_ALIASES    normalised alias  → canonical act-key
    TOPIC_SYNONYMS canonical topic   → expansion keywords for cross-act search

Adding a statute = drop a JSON file in app/data/acts/, add one ActSpec
row, and list its aliases. No StatuteService code change required.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass(frozen=True)
class ActSpec:
    key: str          # canonical key, e.g. "ipc"
    name: str         # display name, e.g. "Indian Penal Code, 1860"
    filename: str     # file under app/data/acts/
    unit: str         # "section" | "article"
    aliases: list[str] = field(default_factory=list)


# ── Act registry ──────────────────────────────────────────────────────────────

ACT_REGISTRY: dict[str, ActSpec] = {
    spec.key: spec
    for spec in (
        ActSpec("ipc", "Indian Penal Code, 1860", "ipc.json", "section",
                ["ipc", "indian penal code", "penal code"]),
        ActSpec("bns", "Bharatiya Nyaya Sanhita, 2023", "bns.json", "section",
                ["bns", "bharatiya nyaya sanhita", "nyaya sanhita"]),
        ActSpec("mv", "Motor Vehicles Act, 1988", "motor_vehicles_act.json",
                "section",
                ["mv act", "motor vehicles act", "motor vehicle act", "mva",
                 "mv", "motor act"]),
        ActSpec("constitution", "Constitution of India, 1950",
                "constitution.json", "article",
                ["constitution", "constitution of india", "coi",
                 "indian constitution"]),
        ActSpec("crpc", "Code of Criminal Procedure, 1973", "crpc.json",
                "section",
                ["crpc", "code of criminal procedure",
                 "criminal procedure code"]),
        ActSpec("bnss", "Bharatiya Nagarik Suraksha Sanhita, 2023",
                "bnss.json", "section",
                ["bnss", "bharatiya nagarik suraksha sanhita",
                 "nagarik suraksha sanhita"]),
        ActSpec("evidence", "Indian Evidence Act, 1872", "evidence_act.json",
                "section",
                ["evidence act", "indian evidence act", "iea",
                 "bharatiya sakshya adhiniyam", "bsa", "sakshya"]),
        ActSpec("consumer", "Consumer Protection Act, 2019",
                "consumer_protection_act.json", "section",
                ["consumer protection act", "consumer act", "cpa",
                 "consumer law"]),
        ActSpec("it", "Information Technology Act, 2000", "it_act.json",
                "section",
                ["it act", "information technology act", "ita",
                 "cyber law"]),
        # ── Tier 1 (additional) + Tier 2 + Tier 3 acts ─────────────────────
        ActSpec("contract", "Indian Contract Act, 1872", "contract_act.json",
                "section",
                ["contract act", "indian contract act", "ica",
                 "contract law", "law of contracts"]),
        ActSpec("ni", "Negotiable Instruments Act, 1881", "ni_act.json",
                "section",
                ["ni act", "negotiable instruments act", "negotiable act",
                 "nia", "cheque act"]),
        ActSpec("cpc", "Code of Civil Procedure, 1908", "cpc.json", "section",
                ["cpc", "code of civil procedure", "civil procedure code"]),
        ActSpec("arbitration",
                "Arbitration and Conciliation Act, 1996",
                "arbitration_act.json", "section",
                ["arbitration act", "arbitration and conciliation act",
                 "arbitration law"]),
        ActSpec("rti", "Right to Information Act, 2005", "rti_act.json",
                "section",
                ["rti", "rti act", "right to information",
                 "right to information act"]),
        ActSpec("companies", "Companies Act, 2013", "companies_act.json",
                "section",
                ["companies act", "company law", "company act"]),
        ActSpec("tpa", "Transfer of Property Act, 1882",
                "transfer_of_property_act.json", "section",
                ["tpa", "transfer of property act", "property act",
                 "transfer of property"]),
        ActSpec("sra", "Specific Relief Act, 1963",
                "specific_relief_act.json", "section",
                ["specific relief act", "sra", "specific performance act"]),
        ActSpec("copyright", "Copyright Act, 1957", "copyright_act.json",
                "section",
                ["copyright act", "copyright law", "indian copyright act"]),
        ActSpec("trademarks", "Trade Marks Act, 1999",
                "trade_marks_act.json", "section",
                ["trade marks act", "trademark act", "trademarks act",
                 "tma"]),
        ActSpec("patents", "Patents Act, 1970", "patents_act.json",
                "section",
                ["patents act", "patent act", "indian patents act"]),
        ActSpec("pwdva",
                "Protection of Women from Domestic Violence Act, 2005",
                "domestic_violence_act.json", "section",
                ["pwdva", "domestic violence act",
                 "protection of women from domestic violence act",
                 "domestic violence law", "dv act"]),
    )
}


# ── Alias index ───────────────────────────────────────────────────────────────

_PUNCT_RE = re.compile(r"[.,]")
_WS_RE = re.compile(r"\s+")
_YEAR_RE = re.compile(r"\b(1[89]\d{2}|20\d{2})\b")
_LEADING_ARTICLE = re.compile(r"^(?:the)\s+")


def normalise_alias(value: str) -> str:
    """'The Indian Penal Code, 1860' → 'indian penal code' (alias key form)."""
    s = _PUNCT_RE.sub("", value.lower())
    s = _YEAR_RE.sub("", s)
    s = _LEADING_ARTICLE.sub("", s)
    return _WS_RE.sub(" ", s).strip()


ACT_ALIASES: dict[str, str] = {
    normalise_alias(alias): spec.key
    for spec in ACT_REGISTRY.values()
    for alias in spec.aliases
}


def resolve_act(value: str | None) -> str | None:
    """Resolve an ACT entity value to a canonical act-key, or None."""
    if not value:
        return None
    norm = normalise_alias(value)
    if norm in ACT_ALIASES:
        return ACT_ALIASES[norm]
    # Substring fallback: "under the Indian Penal Code" → "ipc"
    for alias, key in ACT_ALIASES.items():
        if alias and alias in norm:
            return key
    return None


# ── Legal domain mapping ──────────────────────────────────────────────────────
# Coarse practice-area tag stored as chunk metadata for filtering / display.

ACT_DOMAINS: dict[str, str] = {
    "ipc": "Criminal Law",
    "bns": "Criminal Law",
    "crpc": "Criminal Procedure",
    "bnss": "Criminal Procedure",
    "constitution": "Constitutional Law",
    "evidence": "Evidence Law",
    "mv": "Motor Vehicles & Transport",
    "consumer": "Consumer Protection",
    "it": "Cyber & Information Technology",
    "contract": "Contract & Commercial Law",
    "ni": "Banking & Negotiable Instruments",
    "cpc": "Civil Procedure",
    "arbitration": "Arbitration & ADR",
    "rti": "Information & Transparency",
    "companies": "Corporate Law",
    "tpa": "Property & Real Estate",
    "sra": "Civil Remedies",
    "copyright": "Intellectual Property",
    "trademarks": "Intellectual Property",
    "patents": "Intellectual Property",
    "pwdva": "Family & Domestic Violence",
}


def domain_for(act_key: str) -> str:
    return ACT_DOMAINS.get(act_key, "General")


# Reverse index: SectionResult.act display name → canonical act key.
# Single source of truth (derived from ACT_REGISTRY, not a parallel map).
_NAME_TO_KEY: dict[str, str] = {
    spec.name: spec.key for spec in ACT_REGISTRY.values()
}


def act_key_for_name(name: str | None) -> str | None:
    """Resolve a resolved-provision's act display name to its act key.

    Falls back to alias resolution so this stays correct even if a corpus
    file's display string drifts slightly from the registry name.
    """
    if not name:
        return None
    return _NAME_TO_KEY.get(name) or resolve_act(name)


# ── Topic synonym mapping ─────────────────────────────────────────────────────
# canonical topic → expansion terms. Used for cross-act keyword retrieval when
# no section/article entity resolves. Terms should appear in corpus keywords.

TOPIC_SYNONYMS: dict[str, list[str]] = {
    "murder": ["murder", "homicide", "killing"],
    "cheating": ["cheating", "fraud", "deception", "online cheating"],
    "rape": ["rape", "sexual offence", "sexual assault"],
    "theft": ["theft", "stealing"],
    "defamation": ["defamation", "reputation"],
    "sedition": ["sedition", "sovereignty", "disaffection"],
    "bail": ["anticipatory bail", "pre-arrest bail", "bail"],
    "arrest": ["arrest", "arrest without warrant", "police powers"],
    "fir": ["fir", "first information report", "zero fir"],
    "quashing": ["quashing", "inherent powers", "abuse of process"],
    "privacy": ["privacy", "right to life", "dignity"],
    "free speech": ["freedom of speech", "expression", "reasonable restrictions"],
    "equality": ["equality", "equal protection"],
    "writ": ["writ", "habeas corpus", "mandamus", "certiorari"],
    "hacking": ["hacking", "unauthorised access", "cyber crime"],
    "identity theft": ["identity theft", "phishing", "personation"],
    "intermediary": ["intermediary liability", "safe harbour", "due diligence"],
    "obscenity": ["obscene material", "online obscenity"],
    "accident": ["accident compensation", "motor accident", "claims tribunal"],
    "drunk driving": ["drunk driving", "drink driving", "drink and drive",
                       "drinking and driving", "under influence", "dui"],
    "helmet": ["helmet", "protective headgear"],
    "licence": ["driving licence", "licence"],
    "consumer": ["consumer", "deficiency in service", "unfair trade practice"],
    "product liability": ["product liability", "defective product"],
    "electronic evidence": ["electronic evidence", "65b certificate",
                            "digital evidence", "admissibility", "screenshot",
                            "whatsapp", "email", "cctv", "recording",
                            "photograph"],
    "evidence": ["evidence", "admissibility", "electronic evidence",
                 "digital evidence", "expert opinion", "burden of proof"],
    "confession": ["confession", "confession to police"],
    "burden of proof": ["burden of proof", "onus"],
    "dowry": ["dowry", "dowry death", "cruelty"],
    "cybercrime": ["hacking", "unauthorised access", "cyber crime",
                   "identity theft", "online cheating", "obscene material",
                   "intermediary liability", "phishing"],
    "fraud": ["cheating", "fraud", "deception", "online cheating"],
    "property": ["right to property", "deprivation of property", "theft"],
    # ── Tier 2 / Tier 3 expansion ─────────────────────────────────────────
    "contract": ["contract", "agreement", "breach of contract",
                  "specific performance", "consideration"],
    "breach of contract": ["breach of contract", "specific performance",
                            "damages", "specific relief"],
    "negotiable instrument": ["cheque", "promissory note", "bill of exchange",
                                "cheque bounce", "dishonour of cheque",
                                "section 138"],
    "cheque bounce": ["cheque bounce", "section 138", "dishonour of cheque",
                       "negotiable instrument"],
    "arbitration": ["arbitration", "arbitral award", "arbitration agreement",
                     "arbitrator", "section 34", "section 11"],
    "civil suit": ["civil suit", "civil procedure", "plaint",
                    "written statement", "decree"],
    "rti": ["right to information", "rti application", "rti", "pio",
             "information commission"],
    "company law": ["company law", "director", "board of directors",
                     "shareholder", "incorporation"],
    "transfer of property": ["transfer of property", "sale deed", "lease",
                              "tenant", "landlord", "lis pendens",
                              "part performance"],
    "tenancy": ["tenancy", "lease", "rent", "landlord", "eviction"],
    "specific performance": ["specific performance", "specific relief",
                              "injunction", "mandatory injunction"],
    "injunction": ["injunction", "temporary injunction", "permanent injunction",
                    "stay order", "restraining order"],
    "copyright": ["copyright", "infringement", "fair use", "fair dealing",
                   "moral rights"],
    "trademark": ["trademark", "trade mark", "infringement", "passing off"],
    "patent": ["patent", "patent infringement", "compulsory licence",
                "patentability"],
    "intellectual property": ["intellectual property", "ip", "copyright",
                                "trademark", "patent"],
    "domestic violence": ["domestic violence", "shared household",
                           "protection order", "residence order"],
    "vehicle registration": ["vehicle registration", "registration",
                              "rc", "registration mark"],
    "driving licence": ["driving licence", "learner licence", "dl",
                         "learner's licence"],
    "insurance": ["insurance", "third party insurance", "motor insurance",
                   "no insurance"],
    "overloading": ["overloading", "excess load", "weight limit", "axle weight"],
    "traffic offence": ["traffic offence", "traffic rules", "speeding",
                         "dangerous driving"],
    "writ petition": ["writ petition", "writ", "habeas corpus", "mandamus",
                       "certiorari", "article 226", "article 32"],
}


# ── Topic → Act mapping ───────────────────────────────────────────────────────
# Scopes topical retrieval to the corpora that actually carry the topic, so a
# keyword shared across acts doesn't pull in an unrelated provision.

TOPIC_ACTS: dict[str, list[str]] = {
    "murder": ["ipc", "bns"],
    "cheating": ["ipc", "bns", "it"],
    "fraud": ["ipc", "bns", "it"],
    "rape": ["ipc", "bns"],
    "theft": ["ipc", "bns"],
    "defamation": ["ipc", "bns"],
    "sedition": ["ipc", "bns", "constitution"],
    "dowry": ["ipc", "bns"],
    "bail": ["crpc", "bnss"],
    "arrest": ["crpc", "bnss"],
    "fir": ["crpc", "bnss"],
    "quashing": ["crpc", "bnss"],
    "privacy": ["constitution"],
    "free speech": ["constitution"],
    "equality": ["constitution"],
    "writ": ["constitution"],
    "property": ["constitution", "ipc"],
    "hacking": ["it"],
    "cybercrime": ["it"],
    "identity theft": ["it"],
    "intermediary": ["it"],
    "obscenity": ["it"],
    "accident": ["mv"],
    "drunk driving": ["mv"],
    "helmet": ["mv"],
    "licence": ["mv"],
    "consumer": ["consumer"],
    "product liability": ["consumer"],
    "evidence": ["evidence"],
    "electronic evidence": ["evidence"],
    "confession": ["evidence", "crpc", "bnss"],
    "burden of proof": ["evidence"],
    # Tier 2 / Tier 3 mappings.
    "contract": ["contract"],
    "breach of contract": ["contract", "sra"],
    "negotiable instrument": ["ni"],
    "cheque bounce": ["ni"],
    "arbitration": ["arbitration"],
    "civil suit": ["cpc"],
    "rti": ["rti"],
    "company law": ["companies"],
    "transfer of property": ["tpa"],
    "tenancy": ["tpa"],
    "specific performance": ["sra", "contract"],
    "injunction": ["sra", "cpc"],
    "copyright": ["copyright"],
    "trademark": ["trademarks"],
    "patent": ["patents"],
    "intellectual property": ["copyright", "trademarks", "patents"],
    "domestic violence": ["pwdva", "ipc", "bns"],
    "vehicle registration": ["mv"],
    "driving licence": ["mv"],
    "insurance": ["mv"],
    "overloading": ["mv"],
    "traffic offence": ["mv"],
    "writ petition": ["constitution"],
}


def topic_acts(text: str) -> list[str]:
    """Preferred act-keys for any topic mentioned in *text* (precision scope)."""
    low = text.lower()
    keys: list[str] = []
    for topic, terms in TOPIC_SYNONYMS.items():
        if topic in low or any(t in low for t in terms):
            for k in TOPIC_ACTS.get(topic, []):
                if k not in keys:
                    keys.append(k)
    return keys


# ── Domain-aware suggested questions (right rail / fallback UX) ────────────────

DOMAIN_SUGGESTIONS: dict[str, list[str]] = {
    "Criminal Law": [
        "What is the punishment for cheating?",
        "What does Section 302 of the IPC say?",
        "Difference between murder and culpable homicide?",
    ],
    "Criminal Procedure": [
        "Can police arrest without a warrant?",
        "How do I get anticipatory bail?",
        "How is an FIR registered?",
    ],
    "Constitutional Law": [
        "Explain Article 21 of the Constitution",
        "What is the right to equality under Article 14?",
        "When can a writ petition be filed under Article 226?",
    ],
    "Evidence Law": [
        "Is a WhatsApp screenshot valid evidence?",
        "What is the requirement under Section 65B?",
        "Is a confession to police admissible?",
    ],
    "Motor Vehicles & Transport": [
        "Can I drink and drive?",
        "What is the penalty for not wearing a helmet?",
        "How is motor-accident compensation calculated?",
    ],
    "Consumer Protection": [
        "What is a deficiency in service?",
        "Where do I file a consumer complaint?",
        "What is product liability?",
    ],
    "Cyber & Information Technology": [
        "What is the punishment for identity theft?",
        "Is hacking a criminal offence in India?",
        "What is intermediary liability under Section 79?",
    ],
    "Contract & Commercial Law": [
        "What makes an agreement a valid contract?",
        "What is the remedy for breach of contract?",
        "Is an agreement without consideration valid?",
    ],
    "Banking & Negotiable Instruments": [
        "What happens when a cheque bounces?",
        "What is the punishment under Section 138 NI Act?",
        "Can a company director be liable for a cheque bounce?",
    ],
    "Civil Procedure": [
        "Where do I file a civil suit?",
        "What is res judicata?",
        "How do I obtain a temporary injunction?",
    ],
    "Arbitration & ADR": [
        "What makes an arbitration agreement valid?",
        "When can an arbitral award be set aside?",
        "How is an arbitrator appointed?",
    ],
    "Information & Transparency": [
        "How do I file an RTI application?",
        "What information is exempted under Section 8?",
        "Within how many days must an RTI be answered?",
    ],
    "Corporate Law": [
        "What are the duties of a director under Section 166?",
        "What is the minimum number of directors required?",
        "What is a related party transaction?",
    ],
    "Property & Real Estate": [
        "What is the doctrine of lis pendens?",
        "What is part performance under Section 53A?",
        "What is the notice period for terminating a monthly tenancy?",
    ],
    "Civil Remedies": [
        "When can specific performance be enforced?",
        "What is a perpetual injunction?",
        "How long do I have to recover dispossessed property?",
    ],
    "Intellectual Property": [
        "What is the term of copyright in a literary work?",
        "When is a trademark infringed?",
        "What is a compulsory licence under the Patents Act?",
    ],
    "Family & Domestic Violence": [
        "What constitutes domestic violence?",
        "What is a protection order under PWDVA?",
        "Can I claim residence in a shared household?",
    ],
    "General": [
        "What is the punishment for cheating?",
        "Can police arrest without a warrant?",
        "Explain Article 21 of the Constitution",
    ],
}


# ── Intent-aware suggestion shaping ──────────────────────────────────────────
# Each intent gets a tailored "ask-next" rephrasing of the domain suggestions.
# When an intent isn't covered, we fall back to the raw DOMAIN_SUGGESTIONS.

_INTENT_SUGGESTION_TEMPLATES: dict[str, list[str]] = {
    # Verbatim sections — user already knows the territory.
    "bare_act_query": [
        "What is the punishment under this section?",
        "What are the leading judgments on this provision?",
        "How does this section interact with related provisions?",
    ],
    # Open-ended research — broaden the lens.
    "legal_research": [
        "What are the leading cases on this issue?",
        "How have courts interpreted this in recent judgments?",
        "What procedure should I follow?",
    ],
    # Looking up a precedent — surface adjacent landmarks.
    "case_lookup": [
        "What other landmark cases shaped this doctrine?",
        "Has this judgment been overruled or distinguished?",
        "Which High Courts have followed this ruling?",
    ],
    # Specific citation lookups — point at companion materials.
    "citation_lookup": [
        "What was the ratio decidendi in this case?",
        "Are there subsequent judgments citing this?",
        "Which High Courts have followed this citation?",
    ],
    # Document summary — suggest deeper passes on the same document.
    "document_summary": [
        "Extract the key obligations from this document",
        "Highlight the indemnity and liability clauses",
        "Flag any unusual or aggressive terms",
    ],
}


# Domain → "what should I do next" — practical, action-oriented hints
# that complement the question-suggestions. Each list is short on purpose
# so the right rail doesn't overwhelm.
_DOMAIN_NEXT_ACTIONS: dict[str, list[str]] = {
    "Criminal Law": [
        "Consult a criminal-law practitioner before acting",
        "Preserve evidence (messages, photos, medical records) with timestamps",
        "If you are the victim, file an FIR at the nearest police station",
    ],
    "Criminal Procedure": [
        "Engage an advocate familiar with bail and remand practice",
        "Note all 24-hour deadlines from the moment of arrest",
        "Keep copies of every memo and panchnama signed",
    ],
    "Constitutional Law": [
        "Consider whether a writ lies under Article 32 (Supreme Court) or 226 (High Court)",
        "Identify the specific fundamental right alleged to be infringed",
        "Apply for free legal aid if you cannot afford counsel",
    ],
    "Evidence Law": [
        "If digital, retain the original device or storage media for §65B compliance",
        "Document the chain of custody from collection to production",
        "Obtain a §65B certificate from the proper authority before tendering",
    ],
    "Motor Vehicles & Transport": [
        "File the claim before the Motor Accidents Claims Tribunal (MACT) within the period of limitation",
        "Preserve the FIR, medical records and vehicle inspection report",
        "Notify your insurer in writing within the policy's intimation window",
    ],
    "Consumer Protection": [
        "File the complaint before the appropriate District / State / National Commission by pecuniary value",
        "Send a written notice to the trader / service provider before filing",
        "Keep all bills, receipts, and correspondence as evidence of deficiency",
    ],
    "Cyber & Information Technology": [
        "Lodge a complaint with the local cyber-crime cell or on the National Cyber Crime Reporting Portal",
        "Preserve screenshots, URLs, and original messages with their headers/timestamps",
        "Inform your bank/intermediary immediately when funds or accounts are involved",
    ],
    "General": [
        "Consult a qualified advocate before acting on legal information",
        "Keep dated copies of every relevant document",
        "Note the limitation period applicable to your claim",
    ],
}


# Adaptive example questions per domain — different from the suggestions
# list (which is for "what to ask next"). Examples are illustrative
# starter questions a new user can crib from.
_DOMAIN_EXAMPLES: dict[str, list[str]] = {
    "Criminal Law": [
        "What does Section 302 of the IPC say?",
        "Difference between murder and culpable homicide?",
        "What is the punishment for cheating?",
    ],
    "Criminal Procedure": [
        "Can the police arrest someone without a warrant?",
        "What is the procedure for anticipatory bail?",
        "How is an FIR registered?",
    ],
    "Constitutional Law": [
        "Explain Article 21 of the Constitution",
        "What is the doctrine of basic structure?",
        "When can a writ petition be filed under Article 226?",
    ],
    "Evidence Law": [
        "Is a WhatsApp screenshot valid evidence?",
        "What is the requirement under Section 65B?",
        "Is a confession to police admissible?",
    ],
    "Motor Vehicles & Transport": [
        "Can I drink and drive?",
        "What is the penalty for not wearing a helmet?",
        "How is motor-accident compensation calculated?",
    ],
    "Consumer Protection": [
        "What is a deficiency in service?",
        "Where do I file a consumer complaint?",
        "What is product liability?",
    ],
    "Cyber & Information Technology": [
        "What is the punishment for identity theft?",
        "Is hacking a criminal offence in India?",
        "What is intermediary liability under Section 79?",
    ],
    "General": [
        "What is the punishment for cheating?",
        "Can the police arrest someone without a warrant?",
        "Explain Article 21 of the Constitution",
    ],
}


# Per-domain one-line guidance shown above the suggestion list.
_DOMAIN_HELP_TEXT: dict[str, str] = {
    "Criminal Law": (
        "Indian criminal law spans the IPC (and BNS, 2023), with companion "
        "procedural rules in the CrPC / BNSS. Ask about a section, a "
        "scenario, or the difference between cognate offences."
    ),
    "Criminal Procedure": (
        "Procedural questions on arrest, bail, FIR and trial sit in the "
        "CrPC and the BNSS, 2023. Cite the section number when you have "
        "one — answers will be sharper."
    ),
    "Constitutional Law": (
        "Constitutional questions revolve around Articles 12–35 (rights), "
        "32 & 226 (writs), and structural provisions. Naming the Article "
        "narrows results."
    ),
    "Evidence Law": (
        "Evidence questions span the Indian Evidence Act, 1872 (BSA, "
        "2023). Pay close attention to §65B for any digital evidence."
    ),
    "Motor Vehicles & Transport": (
        "Driving offences, licensing, and accident-compensation claims "
        "are governed by the Motor Vehicles Act, 1988 and the MACT rules."
    ),
    "Consumer Protection": (
        "Consumer disputes fall under the Consumer Protection Act, 2019. "
        "Pecuniary value decides the forum (District / State / National)."
    ),
    "Cyber & Information Technology": (
        "Cyber-offences and intermediary obligations live primarily in the "
        "IT Act, 2000 (and the 2021/2023 Intermediary Rules)."
    ),
    "General": (
        "Tell me the area of law (criminal, constitutional, consumer, "
        "cyber, motor, evidence) or cite a section / article for a sharper "
        "answer."
    ),
}


def _intent_suggestions(intent: str | None, domain: str) -> list[str]:
    """Compose suggestions using intent shape + domain-specific examples.

    For intents that have shaping templates, return the templates first
    (they ask the *next* logical question for the user's current intent),
    followed by domain examples as concrete starter ideas. For other
    intents fall back to the raw domain examples.
    """
    base = list(DOMAIN_SUGGESTIONS.get(domain, DOMAIN_SUGGESTIONS["General"]))
    if not intent:
        return base
    shaped = _INTENT_SUGGESTION_TEMPLATES.get(intent)
    if not shaped:
        return base
    # Interleave: the first 2 intent-shaped prompts, then the domain examples.
    seen: set[str] = set()
    composed: list[str] = []
    for q in shaped[:2] + base:
        if q not in seen:
            seen.add(q)
            composed.append(q)
        if len(composed) >= 4:
            break
    return composed


def legal_context(
    act_keys: list[str],
    query: str,
    *,
    intent: str | None = None,
    route: str | None = None,
) -> dict:
    """Derive the dynamic right-rail context.

    Returns the existing keys (``domain``, ``related_acts``, ``suggestions``)
    plus three additive fields:

    - ``help_text``    one-line guidance scoped to the resolved domain
    - ``next_actions`` practical, action-oriented next steps
    - ``examples``     starter example questions for the current domain

    ``intent`` and ``route`` shape the suggestion list. Both are
    optional: when absent, the function returns the same suggestions it
    did before this enhancement (back-compat for legacy callers /
    tests).
    """
    keys = act_keys or topic_acts(query)
    domain = domain_for(keys[0]) if keys else "General"
    related = [ACT_REGISTRY[k].name for k in keys if k in ACT_REGISTRY]
    suggestions = _intent_suggestions(intent, domain)
    # On a deterministic route the user already named a specific section;
    # they're less likely to want "explore the domain" suggestions and
    # more likely to want logical follow-ups. Promote the intent-shaped
    # prompts above plain examples.
    if route == "deterministic" and intent in _INTENT_SUGGESTION_TEMPLATES:
        shaped = _INTENT_SUGGESTION_TEMPLATES[intent]
        suggestions = list(dict.fromkeys(shaped + suggestions))[:4]

    return {
        "domain": domain,
        "related_acts": related,
        "suggestions": suggestions,
        "help_text": _DOMAIN_HELP_TEXT.get(domain, _DOMAIN_HELP_TEXT["General"]),
        "next_actions": list(
            _DOMAIN_NEXT_ACTIONS.get(domain, _DOMAIN_NEXT_ACTIONS["General"])
        ),
        "examples": list(
            _DOMAIN_EXAMPLES.get(domain, _DOMAIN_EXAMPLES["General"])
        ),
    }


def expand_topics(text: str) -> list[str]:
    """Return expansion keywords for any topic whose synonyms occur in text."""
    low = text.lower()
    hits: list[str] = []
    for topic, terms in TOPIC_SYNONYMS.items():
        if topic in low or any(t in low for t in terms):
            hits.extend(terms)
    # de-dupe, preserve order
    seen: set[str] = set()
    return [k for k in hits if not (k in seen or seen.add(k))]
