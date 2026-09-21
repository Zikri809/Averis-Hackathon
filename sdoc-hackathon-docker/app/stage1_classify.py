"""Stage 1 — classification cascade (plan 01).

Layers, in order:

1. **Stage 0 hard rules** (precision-first): spam, broadcast reminders, the SI
   body template, attached SI+BL pairs, draft-BL comparison intent.
2. **Stage 1 weighted evidence** with ACCEPT/MARGIN and a conflict guard.
3. **Stage 2 TF-IDF similarity** over hand-read centroids.
4. **Stage 3 GLM flash** (bounded, cached, disabled on the frozen run).

The category is always one of the 5; this stage never escalates —
``NEEDS_REVIEW`` is an extraction status, not a category (plan 01 contract).

Trap handling that lives here:

* subject keywords are never decision signals — only the body intent rules are;
* zero-attachment BL bodies ("send the draft BL … for checking") still classify
  ``BL_COMPARISON`` because ``intent_check`` looks for a draft-BL mention;
* broadcast reminders (``_Reminder_Paper - Submit SI & AED``, ``Pending BL
  Release``, ``Outstanding BL``) stay ``GENERAL`` because they lack a directed
  compare/confirm request;
* the 23 INVOICE_QUERY bodies matching ``dropped|still missing`` stay
  INVOICE_QUERY — billing terms win and the escalation gate is category-gated;
* the 2 SPAM "bank details" mails are caught at the rules layer.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Callable

from . import state
from .categories import CATEGORIES, CATEGORY_ORDER, CENTROIDS, SIM_MARGIN, SIM_THRESHOLD
from .signals import Signals, extract, intent_check, intent_create

#: Weighted-evidence votes per category. Values are tuned on the calibration
#: set; they only decide when the hard rules abstain.
EVIDENCE_WEIGHTS: dict[str, dict[str, float]] = {
    "BL_COMPARISON": {
        "has_pair": 3.0,
        "draft_bl": 2.0,
        "check_bl": 1.5,
        "si_bl_pair": 1.0,
        "zero_att_bl_intent": 2.5,
    },
    "SI_REQUEST": {
        "si_detail": 3.0,
        "request_si": 2.0,
        "si_for": 1.0,
    },
    "INVOICE_QUERY": {
        "billing": 2.5,
    },
    "GENERAL": {
        "reminder": 2.0,
        "automated": 2.0,
        "no_doc_signal": 0.5,
    },
    "SPAM": {
        "spam_vocab": 2.0,
        "spam_url": 1.0,
        "spam_domain": 3.0,
    },
}

#: Evidence must beat the runner-up by this margin to be accepted.
ACCEPT_MARGIN = 1.0

#: Below this confidence the LLM layer may be consulted (never on a frozen run).
LLM_CONFIDENCE_THRESHOLD = 0.85


@dataclass
class Classification:
    """Stage-1 output contract: ``{"category", "decided_by"}``."""

    category: str = "GENERAL"
    decided_by: str | None = None
    confidence: float = 0.0
    evidence: dict[str, float] = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {"category": self.category, "decided_by": self.decided_by}


# ---------------------------------------------------------------------------
# Stage 0 — hard rules
# ---------------------------------------------------------------------------
def hard_rule(signals: Signals) -> str | None:
    """Precision-first rules; ``None`` means "abstain"."""
    if signals.spam:
        return "SPAM"
    if signals.reminder or signals.automated:
        return "GENERAL"
    # The SI body template is unambiguous: the email *is* the instruction.
    if signals.si_for and signals.si_detail:
        return "SI_REQUEST"
    # Attachments are decisive for a comparison pair.
    if signals.has_SI and signals.has_BL:
        return "BL_COMPARISON"
    # A draft-BL mention plus a directed compare/check request.
    if signals.draft_bl and (signals.check_bl or signals.si_bl_pair):
        return "BL_COMPARISON"
    if signals.draft_bl and signals.request_si and signals.check_bl:
        return "BL_COMPARISON"
    return None


# ---------------------------------------------------------------------------
# Stage 1 — weighted evidence
# ---------------------------------------------------------------------------
def evidence_votes(signals: Signals) -> dict[str, float]:
    """Score every category from the signal record."""
    votes: dict[str, float] = {category: 0.0 for category in CATEGORIES}

    if signals.has_SI and signals.has_BL:
        votes["BL_COMPARISON"] += EVIDENCE_WEIGHTS["BL_COMPARISON"]["has_pair"]
    if signals.draft_bl:
        votes["BL_COMPARISON"] += EVIDENCE_WEIGHTS["BL_COMPARISON"]["draft_bl"]
    if signals.check_bl:
        votes["BL_COMPARISON"] += EVIDENCE_WEIGHTS["BL_COMPARISON"]["check_bl"]
    if signals.si_bl_pair:
        votes["BL_COMPARISON"] += EVIDENCE_WEIGHTS["BL_COMPARISON"]["si_bl_pair"]
    if signals.n_att == 0 and intent_check(signals):
        votes["BL_COMPARISON"] += EVIDENCE_WEIGHTS["BL_COMPARISON"]["zero_att_bl_intent"]

    if signals.si_detail:
        votes["SI_REQUEST"] += EVIDENCE_WEIGHTS["SI_REQUEST"]["si_detail"]
    if signals.request_si:
        votes["SI_REQUEST"] += EVIDENCE_WEIGHTS["SI_REQUEST"]["request_si"]
    if signals.si_for:
        votes["SI_REQUEST"] += EVIDENCE_WEIGHTS["SI_REQUEST"]["si_for"]

    if signals.billing_terms:
        votes["INVOICE_QUERY"] += EVIDENCE_WEIGHTS["INVOICE_QUERY"]["billing"]

    if signals.reminder:
        votes["GENERAL"] += EVIDENCE_WEIGHTS["GENERAL"]["reminder"]
    if signals.automated:
        votes["GENERAL"] += EVIDENCE_WEIGHTS["GENERAL"]["automated"]
    if not (signals.draft_bl or signals.check_bl or signals.si_bl_pair or intent_create(signals)):
        votes["GENERAL"] += EVIDENCE_WEIGHTS["GENERAL"]["no_doc_signal"]

    if "vocabulary" in signals.spam_hits:
        votes["SPAM"] += EVIDENCE_WEIGHTS["SPAM"]["spam_vocab"]
    if "url" in signals.spam_hits:
        votes["SPAM"] += EVIDENCE_WEIGHTS["SPAM"]["spam_url"]
    if "domain" in signals.spam_hits:
        votes["SPAM"] += EVIDENCE_WEIGHTS["SPAM"]["spam_domain"]

    return votes


def decide_by_evidence(votes: dict[str, float]) -> Classification | None:
    """Accept the top vote when it clears the margin and no conflict blocks it."""
    ranked = sorted(votes.items(), key=lambda item: (-item[1], CATEGORY_ORDER.index(item[0])))
    top_category, top_score = ranked[0]
    runner_up_category, runner_up_score = ranked[1]
    if top_score <= 0:
        return None
    if top_score - runner_up_score < ACCEPT_MARGIN:
        return None
    total = sum(votes.values()) or 1.0
    return Classification(
        category=top_category,
        decided_by="rule",
        confidence=top_score / total,
        evidence=dict(votes),
    )


# ---------------------------------------------------------------------------
# Stage 2 — TF-IDF similarity
# ---------------------------------------------------------------------------
_TOKEN_RX = re.compile(r"[a-z0-9]+")

_STOPWORDS = frozenset(
    {
        "the", "and", "for", "you", "your", "with", "this", "that", "from", "have",
        "are", "was", "were", "will", "would", "please", "kindly", "dear", "team",
        "all", "our", "can", "not", "but", "any", "has", "had", "they", "them",
        "their", "there", "here", "been", "being", "into", "than", "then", "when",
        "which", "who", "whom", "what", "how", "why", "its", "it's", "as", "at",
        "by", "on", "in", "of", "to", "is", "be", "or", "an", "we", "us", "i",
        "am", "do", "does", "did", "if", "so", "no", "yes", "up", "out", "about",
        "over", "after", "before", "more", "most", "some", "such", "only", "also",
        "very", "just", "now", "new", "one", "two", "may", "shall", "should",
    }
)


def tokenize(text: str) -> list[str]:
    return [
        token
        for token in _TOKEN_RX.findall((text or "").lower())
        if token not in _STOPWORDS and len(token) > 1
    ]


class _TfidfIndex:
    """Minimal TF-IDF cosine index over the centroid documents."""

    def __init__(self, documents: dict[str, list[str]]):
        self.categories = list(documents)
        self.docs: list[tuple[str, dict[str, float], float]] = []
        document_frequency: dict[str, int] = {}
        tokenized = [
            (category, tokenize(doc))
            for category, docs in documents.items()
            for doc in docs
        ]
        for _category, tokens in tokenized:
            for token in set(tokens):
                document_frequency[token] = document_frequency.get(token, 0) + 1
        total_docs = max(len(tokenized), 1)
        for category, tokens in tokenized:
            counts: dict[str, float] = {}
            for token in tokens:
                counts[token] = counts.get(token, 0.0) + 1.0
            vector = {
                token: (1.0 + math.log(count))
                * (math.log((1.0 + total_docs) / (1.0 + document_frequency[token])) + 1.0)
                for token, count in counts.items()
            }
            norm = math.sqrt(sum(value * value for value in vector.values())) or 1.0
            self.docs.append((category, vector, norm))

    def _vectorize(self, text: str) -> tuple[dict[str, float], float]:
        counts: dict[str, float] = {}
        for token in tokenize(text):
            counts[token] = counts.get(token, 0.0) + 1.0
        if not counts:
            return {}, 1.0
        total = len(counts)
        document_frequency = {
            token: sum(1 for _category, vector, _norm in self.docs if token in vector)
            for token in counts
        }
        total_docs = max(len(self.docs), 1)
        vector = {
            token: (1.0 + math.log(count))
            * (math.log((1.0 + total_docs) / (1.0 + document_frequency[token])) + 1.0)
            for token, count in counts.items()
        }
        norm = math.sqrt(sum(value * value for value in vector.values())) or 1.0
        return vector, norm

    def scores(self, text: str) -> dict[str, float]:
        vector, norm = self._vectorize(text)
        best: dict[str, float] = {}
        for category, doc_vector, doc_norm in self.docs:
            dot = sum(value * doc_vector.get(token, 0.0) for token, value in vector.items())
            similarity = dot / (norm * doc_norm) if dot else 0.0
            if similarity > best.get(category, 0.0):
                best[category] = similarity
        return best


_INDEX: _TfidfIndex | None = None


def similarity_index() -> _TfidfIndex:
    global _INDEX
    if _INDEX is None:
        _INDEX = _TfidfIndex(CENTROIDS)
    return _INDEX


def classify_by_similarity(signals: Signals, body: str, subject: str = "") -> Classification | None:
    """Decide by centroid similarity when a category clears threshold + margin."""
    scores = similarity_index().scores(f"{subject}\n{body}")
    if not scores:
        return None
    ranked = sorted(scores.items(), key=lambda item: (-item[1], CATEGORY_ORDER.index(item[0])))
    top_category, top_score = ranked[0]
    runner_up_score = ranked[1][1] if len(ranked) > 1 else 0.0
    if top_score < SIM_THRESHOLD or top_score - runner_up_score < SIM_MARGIN:
        return None
    return Classification(
        category=top_category,
        decided_by="sim",
        confidence=top_score,
        evidence=dict(scores),
    )


# ---------------------------------------------------------------------------
# Stage 3 — bounded LLM (cache-only on the frozen run)
# ---------------------------------------------------------------------------
#: Optional hook: ``app.llm_client.classify(email) -> {"category", "confidence"}``.
LLM_HOOK = "classify"


def _llm_classify(email: dict) -> Classification | None:
    from . import llm_client

    hook: Callable[..., dict] | None = getattr(llm_client, LLM_HOOK, None)
    if hook is None:
        return None
    try:
        result = hook(email)
    except Exception:
        return None
    if not isinstance(result, dict) or result.get("category") not in CATEGORIES:
        return None
    return Classification(
        category=str(result["category"]),
        decided_by="llm",
        confidence=float(result.get("confidence") or 0.0),
    )


# ---------------------------------------------------------------------------
# public entry point
# ---------------------------------------------------------------------------
def classify(email: dict) -> dict:
    """Classify one email record; always returns a valid category.

    The return value is the Stage-1 contract: ``{"category", "decided_by"}``.
    Extra diagnostics are attached under ``_stage1`` for the calibration tool.
    """
    signals = extract(email)
    subject = str(email.get("subject") or "")
    body = str(email.get("body") or "")

    rule_category = hard_rule(signals)
    if rule_category is not None:
        return Classification(
            category=rule_category,
            decided_by="rule",
            confidence=1.0,
            evidence={"hard_rule": rule_category},
        ).as_dict() | {"_stage1": {"layer": "hard_rule", "signals": signals}}

    evidence = decide_by_evidence(evidence_votes(signals))
    if evidence is not None and evidence.confidence >= LLM_CONFIDENCE_THRESHOLD:
        return evidence.as_dict() | {"_stage1": {"layer": "evidence", "signals": signals}}

    similarity = classify_by_similarity(signals, body, subject)
    if similarity is not None:
        return similarity.as_dict() | {"_stage1": {"layer": "similarity", "signals": signals}}

    # Everything below is "low confidence": the frozen cache gets a look first
    # (``llm_client.classify`` never makes a live call under ``SCORED_RUN=1``,
    # so this is cache replay there), then the best local guess is the final
    # fallback. This is the plan-01 contract — never escalate here.
    llm_result = _llm_classify(email)
    if llm_result is not None:
        return llm_result.as_dict() | {"_stage1": {"layer": "llm", "signals": signals}}

    if evidence is not None:
        return evidence.as_dict() | {"_stage1": {"layer": "evidence_low_conf", "signals": signals}}

    return Classification(category="GENERAL", decided_by="rule").as_dict() | {
        "_stage1": {"layer": "default", "signals": signals}
    }


def classify_category(email: dict) -> str:
    """Convenience wrapper returning only the category string."""
    return classify(email)["category"]
