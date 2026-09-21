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


def test_review_queue_is_empty_without_the_extension(client):
    payload = client.get("/review").json()
    assert payload["items"] == []
    assert "not installed" in payload["note"]


def test_resolve_is_501_without_the_extension(client):
    assert client.post("/review/resolve", json={}).status_code == 501


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
