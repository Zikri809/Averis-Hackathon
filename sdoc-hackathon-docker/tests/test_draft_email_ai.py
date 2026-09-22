"""Unit tests for AI-powered draft clarification email generation and fallback."""
from __future__ import annotations

import importlib
import json
import urllib.error
from pathlib import Path

import pytest

PROJECT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_DIR / "data_v2"


def _setup_env(monkeypatch, tmp_path, **extra_env):
    from app import state, llm_client

    monkeypatch.setenv("OUTBOX_DIR", str(tmp_path / "outbox"))
    monkeypatch.setenv("STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("DATA_DIR", str(DATA_DIR))
    monkeypatch.delenv("SCORED_RUN", raising=False)
    monkeypatch.setenv("ENABLE_DRAFT_EMAIL", "1")
    for k, v in extra_env.items():
        if v is None:
            monkeypatch.delenv(k, raising=False)
        else:
            monkeypatch.setenv(k, v)

    importlib.reload(state)
    importlib.reload(llm_client)
    llm_client.reset_auth_state()
    import app.extensions.draft_email as draft_email

    return importlib.reload(draft_email)


def test_ai_draft_fallback_with_dummy_key(monkeypatch, tmp_path):
    """Pipeline resilience: dummy API key fails authentication, immediately falls back to template."""
    draft_email = _setup_env(monkeypatch, tmp_path, KENARI_API_KEY="dummy-key-xyz123")
    from app import llm_client

    def mock_post_auth_fail(*args, **kwargs):
        raise urllib.error.HTTPError(
            url="https://kenari.id/v1/chat/completions",
            code=401,
            msg="Unauthorized: Invalid API Key",
            hdrs={},
            fp=None,
        )

    monkeypatch.setattr(llm_client, "_post", mock_post_auth_fail)

    email = {
        "email_id": "email_313",
        "from": "carrier@line.test",
        "subject": "RE_ AFEMY - MSC(MEDUUD649837)",
        "status": "MISMATCH",
    }
    diff = {
        "container_count": {
            "outcome": "diff",
            "si_value": 5,
            "bl_value": 4,
            "si_raw": "Booking Ref: BK998877",
        },
        "gross_weight_kg": {
            "outcome": "diff",
            "si_value": 118270.0,
            "bl_value": 117770.0,
        },
    }

    path = draft_email.write_draft(email, diff)
    assert path.is_file()
    assert path.name == "email_313.eml"
    text = path.read_text(encoding="utf-8")

    # Verify standard template fallback took effect without throwing
    assert "DRAFT — NOT SENT" in text
    assert "To: carrier@line.test" in text
    assert "Subject: DRAFT - clarification needed: RE_ AFEMY - MSC(MEDUUD649837)" in text
    assert "Booking Ref: BK998877" in text
    assert "container_count: SI=5; BL=4" in text
    assert llm_client._KEY_AUTH_FAILED is True


def test_ai_draft_success_with_mocked_llm(monkeypatch, tmp_path):
    """When LLM returns a rich response, it is framed with headers and banners."""
    draft_email = _setup_env(monkeypatch, tmp_path, KENARI_API_KEY="valid-test-key")
    from app import llm_client

    ai_body = (
        "Dear Shipping Documentation Team,\n\n"
        "During automated verification for booking BK998877, we identified discrepancies between the "
        "Shipping Instruction (SI) and draft Bill of Lading (BL):\n"
        "- Container count: SI states 5 containers, while draft BL shows 4.\n"
        "- Gross weight: SI indicates 118,270.0 KG, while draft BL indicates 117,770.0 KG.\n\n"
        "Please confirm the intended figures and provide a revised draft BL at your earliest convenience."
    )

    def mock_post_success(*args, **kwargs):
        return {
            "choices": [
                {
                    "message": {
                        "content": ai_body,
                    }
                }
            ]
        }

    monkeypatch.setattr(llm_client, "_post", mock_post_success)

    email = {
        "email_id": "email_313",
        "from": "ops@shipping.test",
        "subject": "BL Verification BK998877",
        "status": "MISMATCH",
    }
    diff = {
        "container_count": {
            "outcome": "diff",
            "si_value": 5,
            "bl_value": 4,
            "si_raw": "Booking Ref: BK998877",
        }
    }

    path = draft_email.write_draft(email, diff)
    text = path.read_text(encoding="utf-8")

    assert "To: ops@shipping.test" in text
    assert "X-SDOC-Draft: DRAFT — NOT SENT" in text
    assert "DRAFT — NOT SENT" in text
    assert "Dear Shipping Documentation Team" in text
    assert "Booking Ref: BK998877" in text


def test_ai_draft_disabled_under_scored_run(monkeypatch, tmp_path):
    """Guardrail G1: Drafts are strictly disabled under SCORED_RUN=1."""
    from app import state, llm_client

    monkeypatch.setenv("OUTBOX_DIR", str(tmp_path / "outbox"))
    monkeypatch.setenv("SCORED_RUN", "1")
    importlib.reload(state)
    import app.extensions.draft_email as draft_email

    importlib.reload(draft_email)

    assert draft_email.is_enabled() is False
    with pytest.raises(RuntimeError, match="draft emails are disabled"):
        draft_email.write_draft({"email_id": "e1", "from": "a@b", "status": "MISMATCH"}, {})


def test_generate_drafts_batch_with_dummy_key(monkeypatch, tmp_path):
    """Batch draft generation handles dummy keys gracefully and writes outbox files."""
    draft_email = _setup_env(monkeypatch, tmp_path, KENARI_API_KEY="dummy-key")
    from app import llm_client

    def mock_post_fail(*args, **kwargs):
        raise urllib.error.URLError("dummy key network error")

    monkeypatch.setattr(llm_client, "_post", mock_post_fail)

    from app.loader_client import LoaderClient

    client = LoaderClient(DATA_DIR)
    submission = {
        "email_313": {
            "category": "BL_COMPARISON",
            "status": "MISMATCH",
            "defect_fields": ["container_count", "gross_weight_kg"],
            "has_defect": True,
        }
    }

    outbox_dir = tmp_path / "outbox"
    paths = draft_email.generate_drafts(submission, client=client, outbox_dir=outbox_dir)
    assert len(paths) >= 1
    assert any(p.name == "email_313.eml" for p in paths)
    target = outbox_dir / "email_313.eml"
    assert target.is_file()
    assert "DRAFT — NOT SENT" in target.read_text(encoding="utf-8")


def test_server_outbox_endpoints_with_dummy_key(tmp_path, monkeypatch):
    """FastAPI endpoints /outbox/generate and /outbox/draft/{email_id} work with dummy key."""
    monkeypatch.setenv("STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("OUTBOX_DIR", str(tmp_path / "outbox"))
    monkeypatch.setenv("DATA_DIR", str(DATA_DIR))
    monkeypatch.setenv("SCORED_RUN", "0")
    monkeypatch.setenv("KENARI_API_KEY", "dummy-key-test")

    from app import server, state, run, loader_client, llm_client
    for m in (state, llm_client, loader_client, run, server):
        importlib.reload(m)
    llm_client.reset_auth_state()

    from fastapi.testclient import TestClient
    client = TestClient(server.app)

    # First run the pipeline to create submission.json
    run_resp = client.post("/run")
    assert run_resp.status_code == 200

    # Test single draft endpoint
    draft_resp = client.post("/outbox/draft/email_313")
    assert draft_resp.status_code == 200
    data = draft_resp.json()
    assert data["status"] == "ok"
    assert data["path"] == "email_313.eml"
    assert "DRAFT — NOT SENT" in data["content"]

    # Verify draft is in /outbox listing
    outbox_resp = client.get("/outbox")
    assert outbox_resp.status_code == 200
    assert "email_313.eml" in outbox_resp.json()["items"]
