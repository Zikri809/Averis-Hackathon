from __future__ import annotations

import importlib


def _reload(monkeypatch, tmp_path):
    from app import state

    monkeypatch.setenv("OUTBOX_DIR", str(tmp_path))
    monkeypatch.delenv("SCORED_RUN", raising=False)
    importlib.reload(state)
    import app.extensions.draft_email as draft_email

    return importlib.reload(draft_email)


def test_writes_draft_only_eml_with_banner_and_recipient(monkeypatch, tmp_path):
    draft_email = _reload(monkeypatch, tmp_path)
    email = {"email_id": "email_313", "from": "sender@example.test", "status": "MISMATCH"}
    diff = {
        "shipper": {
            "outcome": "diff",
            "si_value": "A",
            "bl_value": "B",
            "si_raw": "Booking Ref: ABC123",
        }
    }

    path = draft_email.write_draft(email, diff)
    text = path.read_text(encoding="utf-8")

    assert path.name == "email_313.eml"
    assert "To: sender@example.test" in text
    assert "DRAFT — NOT SENT" in text
    assert "Booking Ref: ABC123" in text


def test_rejects_needs_review_draft(monkeypatch, tmp_path):
    draft_email = _reload(monkeypatch, tmp_path)

    try:
        draft_email.write_draft({"email_id": "email_001", "from": "a@b", "status": "NEEDS_REVIEW"}, {})
    except ValueError as exc:
        assert "MISMATCH" in str(exc)
    else:
        raise AssertionError("expected ValueError")
