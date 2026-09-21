from __future__ import annotations

from pathlib import Path


def test_app_contains_no_mail_sender_code():
    project = Path(__file__).resolve().parent.parent
    offenders = []
    forbidden = ["sm" + "tplib", "send" + "mail"]
    for path in (project / "app").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        lowered = text.lower()
        if any(term in lowered for term in forbidden):
            offenders.append(str(path.relative_to(project)))
    assert offenders == []
