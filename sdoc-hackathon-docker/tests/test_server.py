"""Participant app endpoint smoke tests (plan 07 O3)."""
from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest

PROJECT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_DIR / "data_v2"

pytest.importorskip("fastapi")


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """A TestClient whose state/data dirs are isolated per test."""
    monkeypatch.setenv("STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("OUTBOX_DIR", str(tmp_path / "outbox"))
    monkeypatch.setenv("DATA_DIR", str(DATA_DIR))
    monkeypatch.setenv("INBOX_URL", "")
    monkeypatch.setenv("SCORED_RUN", "0")

    from app import loader_client, run, state, server

    for module in (state, loader_client, run, server):
        importlib.reload(module)

    from fastapi.testclient import TestClient

    yield TestClient(server.app)

    monkeypatch.delenv("SCORED_RUN", raising=False)
    for module in (state, loader_client, run, server):
        importlib.reload(module)


def test_health_reports_local_mode(client):
    payload = client.get("/health").json()
    assert payload["status"] == "ok"
    assert payload["scored_run"] is False
    assert payload["submission_present"] is False
    assert payload["inbox"]["reachable"] is False


def test_submission_is_404_before_a_run(client):
    assert client.get("/submission").status_code == 404


def test_run_writes_520_keys(client):
    response = client.post("/run")
    assert response.status_code == 200
    assert response.json()["n_records"] == 520

    submission = client.get("/submission").json()
    assert len(submission) == 520
    assert all("category" in record for record in submission.values())


def test_run_prefers_the_mounted_dataset_over_http(client, monkeypatch):
    """O2/O3: with both configured, /run reads the /data mount (seconds),
    while /health still reports the inbox service reachability."""
    from app import server

    monkeypatch.setattr(server, "INBOX_URL", "http://localhost:8000")
    assert server._data_source() == str(server.state.DATA_DIR)

    response = client.post("/run")
    assert response.status_code == 200
    assert response.json()["n_records"] == 520


def test_review_queue_reports_no_submission_before_a_run(client):
    """Plan 05 is landed: the queue projection exists but there is no data yet."""
    payload = client.get("/review").json()
    assert payload["items"] == []
    assert payload["note"] == "no submission yet"


def test_review_queue_lists_needs_review_after_a_run(client):
    """O3: after POST /run the queue projects the NEEDS_REVIEW records."""
    assert client.post("/run").status_code == 200
    payload = client.get("/review").json()
    assert len(payload["items"]) > 0
    assert {item["email_id"] for item in payload["items"]} <= set(
        client.get("/submission").json()
    )
    assert all(item["review_reason"] for item in payload["items"])


def test_resolve_rejects_an_empty_payload(client):
    """Plan 05 is landed: unknown actions are 400, not 501."""
    response = client.post("/review/resolve", json={})
    assert response.status_code == 400
    assert "unknown resolution action" in response.text


def test_resolve_confirms_an_escalation(client):
    response = client.post(
        "/review/resolve",
        json={"action": "confirm-escalation", "email_id": "email_506"},
    )
    assert response.status_code == 200
    assert response.json() == {
        "status": "confirmed-escalation",
        "email_id": "email_506",
    }


def test_outbox_lists_and_serves_drafts(client, tmp_path):
    outbox = tmp_path / "outbox"
    outbox.mkdir(parents=True, exist_ok=True)
    (outbox / "email_313.eml").write_text("Subject: DRAFT\n\nDRAFT — NOT SENT\n", encoding="utf-8")

    listing = client.get("/outbox").json()
    assert listing["items"] == ["email_313.eml"]
    assert "ever sent" in listing["note"].lower()

    draft = client.get("/outbox/email_313.eml")
    assert draft.status_code == 200
    assert "DRAFT — NOT SENT" in draft.text


def test_outbox_rejects_path_traversal(client, tmp_path):
    outside = tmp_path / "secret.txt"
    outside.write_text("nope", encoding="utf-8")
    assert client.get("/outbox/../secret.txt").status_code == 404


def test_ui_is_served_and_never_references_ground_truth(client):
    response = client.get("/ui")
    assert response.status_code == 200
    body = response.text
    assert "DRAFT" in body
    assert "ground_truth" not in body.lower()


def test_no_ground_truth_route_exists(client):
    for path in ("/ground_truth", "/secrets", "/gt"):
        assert client.get(path).status_code == 404
