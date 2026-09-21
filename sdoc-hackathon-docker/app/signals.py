"""Signal extraction for Stage 1 (plan 01, C1).

Metadata only — this module never opens an attachment (D3/D9). Everything it
returns is derived from ``{from, subject, body, attachments[]}`` where the
attachments are *filenames*, not contents.

The rules in :mod:`app.stage1_classify` consume these signals; keeping them in
one table-driven module makes the traps from ``Stage 1 Classification.md``
explicit and testable.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

#: Internal staff domain (the mailbox's own organisation).
INTERNAL_DOMAINS = frozenset({"aprilasia.com", "april.com.my"})

#: Spam sender domains seen in the dataset (and the pattern family).
SPAM_DOMAINS = frozenset(
    {
        "prize-claims.info",
        "parcel-track.co",
        "webmail-verify.co",
        "logistics-deals.biz",
        "crypto-invest.net",
        "secure-mailbox.org",
    }
)

#: ``RE_``/``Re:``/``RE:`` reply prefix.
_REPLY_RX = re.compile(r"^\s*RE[_:]", re.IGNORECASE)

#: A draft-BL mention anywhere (subject or body).
DRAFT_BL_RX = re.compile(r"draft\s*(?:bl|bill\s+of\s+lading)", re.IGNORECASE)

#: "check/confirm/verify/compare" paired with "BL" in either order. Real
#: emails put the ask in the sentence *after* the document mention
#: ("…draft BL for OC ….\nPlease check the details and confirm."), so the
#: window may cross sentence boundaries; it stays bounded and the SI-template
#: hard rule runs first, which is what keeps this from over-firing.
CHECK_BL_RX = re.compile(
    r"\b(?:bl|bill\s+of\s+lading)\b[\s\S]{0,150}?"
    r"(?:check|confirm|verify|compare|revert|discrepan)"
    r"|(?:check|confirm|verify|compare|revert|discrepan)[\s\S]{0,150}?"
    r"\b(?:bl|bill\s+of\s+lading)\b",
    re.IGNORECASE,
)

#: "SI" and "BL" mentioned together in the same clause.
SI_BL_PAIR_RX = re.compile(
    r"\bsi\b[^.\n]{0,50}\bbl\b|\bbl\b[^.\n]{0,50}\bsi\b",
    re.IGNORECASE,
)

#: A request/need to produce, issue, submit or send an SI.
REQUEST_SI_RX = re.compile(
    r"(?:request|cust|need|submit|latest|provide|issue|send|prepare)[^.\n]{0,25}\bsi\b"
    r"|\bsi\b[^.\n]{0,25}(?:needed|required|request)",
    re.IGNORECASE,
)

#: "Shipping instruction for <ref>" — the SI body template's opening.
SI_FOR_RX = re.compile(r"shipping\s+instruction\s+for", re.IGNORECASE)

#: The SI body template's field labels (present in the body, not as attachment).
SI_DETAIL_RX = re.compile(
    r"^\s*(?:POL|POD|Shipper|Consignee|Notify\s+Party|Description\s+of\s+Goods"
    r"|Documents\s+Required|H\.S\.CODE|Shipping\s+line)\s*:",
    re.IGNORECASE | re.MULTILINE,
)

#: Billing / invoice vocabulary (wins over weak doc intent).
BILLING_RX = re.compile(
    r"invoice|billing|\bgr\b|local\s+charges|d\s*&\s*d|detention|freight|\bpgi\b",
    re.IGNORECASE,
)

#: Subject shapes that are broadcast reminders, never a directed request.
REMINDER_SUBJECT_RX = re.compile(
    r"_reminder_|pending\s+bl\s+release|outstanding\s+bl|update\s+summary"
    r"|berthing\s+report|_rpa_|miss\s+connection|delivery\s+planning"
    r"|^welcoming\s+the\s+new\s+year|^_approval\s+required_",
    re.IGNORECASE,
)

#: "Reminder: Please submit SI …" bodies are broadcast SLA notices.
REMINDER_BODY_RX = re.compile(r"^reminder:\s*please\s+submit\s+si", re.IGNORECASE | re.MULTILINE)

#: Automated notifications ("No action required").
AUTOMATED_RX = re.compile(r"automated\s+notification|no\s+action\s+required", re.IGNORECASE)

#: Spam vocabulary.
SPAM_WORDS_RX = re.compile(
    r"\bwon\b|winner|prize|gift\s+card|parcel|storage\s+limit|bitcoin"
    r"|bank\s+officer|90%\s*off|iphone|survey|claim\s+now|congratulations",
    re.IGNORECASE,
)

#: Spam URL shapes.
SPAM_URL_RX = re.compile(r"https?://", re.IGNORECASE)

#: The external-sender warning banner (boilerplate, never intent).
EXTERNAL_BANNER_RX = re.compile(r"originated\s+outside\s+of\s+our\s+organisation", re.IGNORECASE)

#: v3-A1 — the only body phrase that escalates a zero-attachment BL request.
#: The escalation gate itself lives in ``run.py`` (Foundation); this is the
#: shared signal so Stage 1 and the gate can never disagree.
MISSING_ATTACHMENT_RX = re.compile(r"dropped|still missing", re.IGNORECASE)


def missing_attachment_phrase(body: str) -> bool:
    return bool(MISSING_ATTACHMENT_RX.search(body or ""))


@dataclass
class Signals:
    """All Stage-1 signals for one email (metadata only)."""

    email_id: str = ""
    has_SI: bool = False
    has_BL: bool = False
    n_att: int = 0
    is_reply: bool = False
    sender: str = ""
    sender_domain: str = ""
    is_internal_sender: bool = False

    draft_bl: bool = False
    check_bl: bool = False
    si_bl_pair: bool = False
    request_si: bool = False
    si_for: bool = False
    si_detail: bool = False

    billing_terms: bool = False
    reminder: bool = False
    automated: bool = False

    spam_score: float = 0.0
    spam_hits: list[str] = field(default_factory=list)
    external_banner: bool = False

    @property
    def spam(self) -> bool:
        return self.spam_score >= 1.0


def _domain(address: str) -> str:
    return address.rsplit("@", 1)[-1].strip().lower() if "@" in address else ""


def has_si(attachments: list[str]) -> bool:
    """True when an attachment filename marks an SI (``_SI``)."""
    return any("_SI" in str(name) for name in attachments)


def has_bl(attachments: list[str]) -> bool:
    """True when an attachment filename marks a BL (``_BL``)."""
    return any("_BL" in str(name) for name in attachments)


def is_reply(subject: str) -> bool:
    """True for ``RE_``/``Re:``/``RE:`` prefixed subjects."""
    return bool(_REPLY_RX.match(subject or ""))


def extract(email: dict) -> Signals:
    """Build the signal record for one email record."""
    subject = str(email.get("subject") or "")
    body = str(email.get("body") or "")
    sender = str(email.get("from") or "")
    attachments = list(email.get("attachments") or [])
    domain = _domain(sender)
    blob = subject + "\n" + body

    spam_hits: list[str] = []
    if SPAM_WORDS_RX.search(blob):
        spam_hits.append("vocabulary")
    if SPAM_URL_RX.search(body):
        spam_hits.append("url")
    if domain in SPAM_DOMAINS:
        spam_hits.append("domain")

    return Signals(
        email_id=str(email.get("email_id") or ""),
        has_SI=has_si(attachments),
        has_BL=has_bl(attachments),
        n_att=len(attachments),
        is_reply=is_reply(subject),
        sender=sender,
        sender_domain=domain,
        is_internal_sender=domain in INTERNAL_DOMAINS,
        draft_bl=bool(DRAFT_BL_RX.search(blob)),
        check_bl=bool(CHECK_BL_RX.search(blob)),
        si_bl_pair=bool(SI_BL_PAIR_RX.search(blob)),
        request_si=bool(REQUEST_SI_RX.search(blob)),
        si_for=bool(SI_FOR_RX.search(body)),
        si_detail=bool(SI_DETAIL_RX.search(body)),
        billing_terms=bool(BILLING_RX.search(blob)),
        reminder=bool(REMINDER_SUBJECT_RX.search(subject) or REMINDER_BODY_RX.search(body)),
        automated=bool(AUTOMATED_RX.search(body)),
        spam_score=float(len(spam_hits)),
        spam_hits=spam_hits,
        external_banner=bool(EXTERNAL_BANNER_RX.search(body)),
    )


def intent_check(signals: Signals) -> bool:
    """Body intent: compare/confirm/check a draft BL against the SI."""
    return signals.check_bl and (signals.draft_bl or signals.si_bl_pair)


def intent_create(signals: Signals) -> bool:
    """Body intent: produce/issue/request an SI."""
    return signals.request_si or (signals.si_for and signals.si_detail)
