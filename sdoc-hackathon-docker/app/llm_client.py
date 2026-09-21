"""GLM-flash client with a frozen response cache (plan 01, C5).

Contract:

* OpenAI-compatible ``POST {base}/chat/completions``, temperature 0, 5-shot.
* Every response is cached in ``state/llm_cache.json`` keyed by
  ``sha256(subject + body)`` — the same key the frozen run replays.
* On the frozen run (``SCORED_RUN=1``) **no network call is ever made**: a
  cache miss returns ``None`` and the rules/sim decision stands.
* Fenced or truncated JSON is extracted with a regex and retried once; a
  second failure returns ``None`` (the caller falls back to ``GENERAL``).
* Only successful parses are cached.

The client is dependency-free (stdlib ``urllib``) and has no import side
effects, so ``run.py`` can gate it behind ``SCORED_RUN``.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import urllib.error
import urllib.request
from typing import Any

from . import state
from .categories import CATEGORIES

#: Kenari OpenAI-compatible gateway, GLM flash model (plan 01 C5).
DEFAULT_BASE_URL = "https://kenari.id/v1"
DEFAULT_MODEL = "glm-5-3-flash"
DEFAULT_TIMEOUT = 20.0

#: Environment names consulted for the API key, in order. The key is never
#: read from or written to the repository.
API_KEY_ENV_VARS = ("KENARI_API_KEY", "GLM_API_KEY", "ZHIPUAI_API_KEY")

#: Cache key namespace: sha256(subject + body).
_JSON_RX = re.compile(r"\{[^{}]*\}", re.DOTALL)

FEW_SHOT: list[tuple[str, str]] = [
    (
        "Subject: TO CONFIRM DOCS _ 5RSG-00133 _ CALLAO_PERU _ MOORIM SP CO., LTD _ MEDUUD104332\n"
        "Body: Attached are the SI and draft BL. Please check the details and confirm.",
        "BL_COMPARISON",
    ),
    (
        "Subject: SI - SIN706562729 - DIRECT(PIL) - 5RCY-72046 - MERSIN_TURKEY\n"
        "Body: Please find Shipping instruction for 5RCY-72046. POL: ... Documents Required: ... "
        "Please revert with draft BL once available.",
        "SI_REQUEST",
    ),
    (
        "Subject: 2199 RAK BILLING 5070146123 MISSING GR\n"
        "Body: We note the GR is still missing for invoice 5250070084. Kindly arrange to post the GR "
        "so we can proceed with billing.",
        "INVOICE_QUERY",
    ),
    (
        "Subject: daily Berthing Report - 07 JAN 2026\n"
        "Body: Kindly find the daily berthing report attached. Vessel berthed on schedule.",
        "GENERAL",
    ),
    (
        "Subject: Congratulations! You have WON a $1,000 Gift Card - CLAIM NOW\n"
        "Body: Your email address has been selected. Click here to claim now.",
        "SPAM",
    ),
]

SYSTEM_PROMPT = (
    "You classify shipping-documentation emails into exactly one category: "
    "BL_COMPARISON, SI_REQUEST, INVOICE_QUERY, GENERAL, SPAM. "
    "Reply with JSON only: {\"category\": \"<CATEGORY>\", \"confidence\": <0-1>}."
)


def cache_key(subject: str, body: str) -> str:
    """The frozen-cache key: ``sha256(subject + body)`` (plan 01 C5)."""
    return hashlib.sha256((str(subject) + str(body)).encode("utf-8")).hexdigest()


def load_cache(path=None) -> dict[str, Any]:
    target = path or state.llm_cache_path()
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def save_cache(cache: dict[str, Any], path=None) -> None:
    target = path or state.llm_cache_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".tmp")
    tmp.write_text(json.dumps(cache, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(target)


def extract_json(text: str) -> dict | None:
    """Pull the first JSON object out of a fenced/chatty/truncated response."""
    if not text:
        return None
    candidate = text.strip()
    if candidate.startswith("```"):
        candidate = candidate.strip("`")
        candidate = re.sub(r"^json\s*", "", candidate, flags=re.IGNORECASE)
    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError:
        match = _JSON_RX.search(text)
        if match is None:
            return None
        try:
            parsed = json.loads(match.group())
        except json.JSONDecodeError:
            return None
    return parsed if isinstance(parsed, dict) else None


def _post(url: str, payload: dict, api_key: str, timeout: float) -> dict:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read())


def api_key() -> str | None:
    """The Kenari/GLM key from the environment (never hard-coded)."""
    for name in API_KEY_ENV_VARS:
        value = os.environ.get(name)
        if value:
            return value
    return None


def _live_call(email: dict, timeout: float = DEFAULT_TIMEOUT) -> str | None:
    """One real GLM-flash call; ``None`` when no key is configured or it fails."""
    key = api_key()
    if not key:
        return None
    base_url = os.environ.get("GLM_BASE_URL", DEFAULT_BASE_URL).rstrip("/")
    model = os.environ.get("GLM_MODEL", DEFAULT_MODEL)

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    for user, assistant in FEW_SHOT:
        messages.append({"role": "user", "content": user})
        messages.append({"role": "assistant", "content": json.dumps({"category": assistant, "confidence": 1.0})})
    messages.append(
        {
            "role": "user",
            "content": f"Subject: {email.get('subject', '')}\nBody: {email.get('body', '')}",
        }
    )
    payload = {"model": model, "temperature": 0, "messages": messages}
    try:
        response = _post(f"{base_url}/chat/completions", payload, key, timeout)
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError):
        return None
    try:
        return response["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        return None


def classify(email: dict, *, live: bool | None = None, cache_path=None) -> dict | None:
    """Classify via cache, or live when allowed.

    Returns ``{"category", "confidence"}`` or ``None``. Under ``SCORED_RUN=1``
    only the cache is consulted (a miss is a miss, never a network call).
    """
    subject = str(email.get("subject") or "")
    body = str(email.get("body") or "")
    key = cache_key(subject, body)

    cache = load_cache(cache_path)
    cached = cache.get(key)
    if isinstance(cached, dict) and cached.get("category") in CATEGORIES:
        return {"category": cached["category"], "confidence": float(cached.get("confidence", 1.0))}

    if state.SCORED_RUN or live is False:
        return None

    for attempt in range(2):
        raw = _live_call(email)
        if raw is None:
            return None
        parsed = extract_json(raw)
        if parsed is not None and parsed.get("category") in CATEGORIES:
            cache[key] = {
                "category": parsed["category"],
                "confidence": float(parsed.get("confidence", 1.0)),
            }
            save_cache(cache, cache_path)
            return {
                "category": parsed["category"],
                "confidence": float(parsed.get("confidence", 1.0)),
            }
        # one retry on malformed JSON; cache only successful parses
        if attempt == 1:
            return None
    return None


def record_cache(emails: list[dict], *, cache_path=None) -> dict:
    """Calibration helper: resolve every email and persist the frozen cache."""
    cache = load_cache(cache_path)
    for email in emails:
        classify(email, cache_path=cache_path)
        cache = load_cache(cache_path)
    return cache
