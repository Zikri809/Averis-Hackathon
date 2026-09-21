"""Participant app: run the pipeline, serve the review queue and drafts (plan 07 O3).

Endpoints:

======================  =====================================================
``POST /run``           run the pipeline, write ``$STATE_DIR/submission.json``
``GET  /submission``    the last complete submission (404 before the first run)
``GET  /review``        the review queue projection (empty until plan 05 lands)
``POST /review/resolve``record a reviewer resolution (proxied to plan 05)
``GET  /outbox``        draft ``.eml`` files written by the draft extension
``GET  /outbox/{name}`` one draft's text
``GET  /ui``            static review dashboard
``GET  /health``        liveness + inbox reachability
======================  =====================================================

The app **consumes** the organizers' inbox service; it never re-declares it.
``REVEAL_GT`` is never set and there is no ground-truth route (G9).
"""
from __future__ import annotations

import json
import os
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse

from . import state
from .loader_client import LoaderClient

APP_PORT = int(os.environ.get("APP_PORT", "8001"))
INBOX_URL = os.environ.get("INBOX_URL", "").rstrip("/")
HEALTH_TIMEOUT = float(os.environ.get("INBOX_HEALTH_TIMEOUT", "3"))
STARTUP_WAIT_SECONDS = float(os.environ.get("INBOX_STARTUP_WAIT_SECONDS", "60"))

app = FastAPI(
    title="SDOC Participant App",
    version="1.0",
    description="Runs the verification pipeline against the organizers' inbox service.",
)

#: Serialises runs so two POST /run calls cannot interleave writes.
_run_lock = threading.Lock()

#: Last run summary, for the dashboard.
_last_run: dict = {}


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _data_source() -> str:
    """Prefer the HTTP inbox service; fall back to the mounted dataset."""
    return INBOX_URL or str(state.DATA_DIR)


def _client() -> LoaderClient:
    return LoaderClient(_data_source())


def _inbox_health() -> dict:
    if not INBOX_URL:
        return {"reachable": False, "note": "INBOX_URL not set; using the local dataset"}
    try:
        with urllib.request.urlopen(f"{INBOX_URL}/health", timeout=HEALTH_TIMEOUT) as response:
            return {"reachable": True, **json.loads(response.read())}
    except Exception as exc:
        return {"reachable": False, "error": str(exc)}


def _wait_for_inbox() -> None:
    """Fail loudly if the app starts before the organizers' inbox is ready."""
    if not INBOX_URL:
        return
    deadline = time.monotonic() + STARTUP_WAIT_SECONDS
    last_error = "not checked"
    while time.monotonic() < deadline:
        health = _inbox_health()
        if health.get("reachable"):
            return
        last_error = str(health.get("error") or health)
        time.sleep(1)
    raise RuntimeError(f"inbox health check failed after {STARTUP_WAIT_SECONDS:.0f}s: {last_error}")


def _submission_payload() -> dict:
    path = state.submission_path()
    if not path.is_file():
        raise HTTPException(404, "no submission yet — POST /run first")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise HTTPException(500, f"submission file is incomplete: {exc}")


def _extension(name: str):
    """Import an extensions module when it exists (plan 05 is not landed yet)."""
    import importlib

    if state.SCORED_RUN:
        return None
    try:
        return importlib.import_module(f"app.extensions.{name}")
    except Exception:
        return None


# ---------------------------------------------------------------------------
# endpoints
# ---------------------------------------------------------------------------
@app.on_event("startup")
def startup_wait_for_inbox():
    _wait_for_inbox()


@app.get("/health")
def health():
    return {
        "status": "ok",
        "app_port": APP_PORT,
        "scored_run": state.SCORED_RUN,
        "inbox": _inbox_health(),
        "submission_present": state.submission_path().is_file(),
    }


@app.post("/run")
def run_pipeline(request: Request):
    """Run the pipeline and write the submission atomically (idempotent)."""
    from . import run as run_module

    if not _run_lock.acquire(blocking=False):
        raise HTTPException(409, "a run is already in progress")
    try:
        state.ensure_dirs()
        source = _data_source()
        out_path = state.submission_path()
        try:
            submission = run_module.run(data_dir=source, out_path=out_path)
        except Exception as exc:
            raise HTTPException(500, f"run failed: {exc}")
        _last_run.clear()
        _last_run.update({"n_records": len(submission), "source": source})
        return {"status": "ok", "n_records": len(submission), "out": str(out_path)}
    finally:
        _run_lock.release()


@app.get("/submission")
def get_submission():
    return JSONResponse(_submission_payload())


@app.get("/review")
def get_review():
    """Review queue projection; empty until the extensions land (plan 05 X2)."""
    module = _extension("review_queue")
    if module is None:
        return {"items": [], "note": "review queue extension not installed"}
    builder = getattr(module, "queue_from_submission", None)
    if builder is None:
        return {"items": [], "note": "review queue extension has no projection yet"}
    try:
        return {"items": builder(_submission_payload())}
    except HTTPException:
        return {"items": [], "note": "no submission yet"}


@app.post("/review/resolve")
async def resolve_review(request: Request):
    """Forward a reviewer resolution to the alias-learning extension."""
    module = _extension("alias_learning")
    if module is None:
        raise HTTPException(501, "alias learning extension not installed")
    resolve = getattr(module, "resolve", None)
    if resolve is None:
        raise HTTPException(501, "alias learning extension has no resolve()")
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(400, "body must be JSON")
    try:
        return resolve(payload)
    except Exception as exc:
        raise HTTPException(400, f"resolution rejected: {exc}")


@app.get("/outbox")
def list_outbox():
    state.ensure_dirs()
    return {
        "items": sorted(path.name for path in state.OUTBOX_DIR.glob("*.eml")),
        "note": "drafts only — nothing is ever sent",
    }


@app.get("/outbox/{name}")
def get_draft(name: str):
    state.ensure_dirs()
    target = (state.OUTBOX_DIR / name).resolve()
    if target.parent != state.OUTBOX_DIR.resolve() or not target.is_file():
        raise HTTPException(404, f"no such draft: {name}")
    return PlainTextResponse(target.read_text(encoding="utf-8", errors="replace"))


@app.get("/ui")
def ui():
    index = Path(__file__).resolve().parent / "ui" / "index.html"
    if not index.is_file():
        return PlainTextResponse("review UI not installed", status_code=404)
    return FileResponse(index)


if __name__ == "__main__":  # pragma: no cover - container entry point
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=APP_PORT)
