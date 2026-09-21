"""Compose guard (plan 07 O2) — pins the harness facts that bit v2.

The organizers' service is `inbox`, published on host 8080 -> container 8000.
The participant app must *attach* to it, never re-declare it, and must not
collide on port 8080.
"""
from __future__ import annotations

from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

PROJECT_DIR = Path(__file__).resolve().parent.parent


def load(name: str) -> dict:
    return yaml.safe_load((PROJECT_DIR / name).read_text(encoding="utf-8"))


def test_inbox_service_is_declared_by_the_organizers():
    compose = load("docker-compose.yml")
    inbox = compose["services"]["inbox"]
    assert inbox["ports"] == ["8080:8000"]
    assert "./data_v2:/data:ro" in inbox["volumes"]
    assert inbox["environment"]["DATA_DIR"] == "/data"


def test_app_overlay_does_not_redeclare_inbox():
    app = load("docker-compose.app.yml")["services"]
    assert "inbox" not in app, "the app overlay must not duplicate the inbox service"
    assert set(app) == {"app"}


def test_app_uses_inbox_service_name_not_localhost():
    app = load("docker-compose.app.yml")["services"]["app"]
    assert app["environment"]["INBOX_URL"] == "http://inbox:8000"


def test_app_port_does_not_collide_with_the_inbox():
    app = load("docker-compose.app.yml")["services"]["app"]
    published = [str(port) for port in app["ports"]]
    assert published == ["${APP_PORT:-8001}:8001"]
    assert not any("8080" in port for port in published)


def test_app_mounts_state_and_outbox_on_the_host():
    app = load("docker-compose.app.yml")["services"]["app"]
    volumes = app["volumes"]
    assert "./state:/state" in volumes
    assert "./outbox:/outbox" in volumes
    assert "./data_v2:/data:ro" in volumes


def test_app_never_enables_reveal_gt():
    app = load("docker-compose.app.yml")["services"]["app"]
    assert "REVEAL_GT" not in app["environment"]
    inbox = load("docker-compose.yml")["services"]["inbox"]
    assert "REVEAL_GT" not in inbox.get("environment", {})


def test_app_dockerfile_adds_the_parser_deps():
    text = (PROJECT_DIR / "Dockerfile.app").read_text(encoding="utf-8")
    for dependency in ("openpyxl", "python-docx", "pymupdf"):
        assert dependency in text
    requirements = (PROJECT_DIR / "requirements-app.txt").read_text(encoding="utf-8")
    for dependency in ("openpyxl", "python-docx", "pymupdf"):
        assert dependency in requirements


def test_app_runs_on_its_own_port():
    text = (PROJECT_DIR / "Dockerfile.app").read_text(encoding="utf-8")
    assert "8001" in text
    assert "APP_PORT=8001" in text
