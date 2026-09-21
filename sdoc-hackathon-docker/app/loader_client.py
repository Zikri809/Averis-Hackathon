"""Dataset access (plan 00, F3).

Wraps the organizers' ``loader.Inbox`` so the rest of the pipeline never
touches the filesystem or the network directly. Two modes, one API:

* local:  ``LoaderClient("data_v2")`` — ``DATA_DIR`` with ``inbox/``
* HTTP:   ``LoaderClient("http://localhost:8080")`` — the shipped inbox service

All text reads use ``encoding="utf-8", errors="replace"`` (win32 charmap trap).
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Iterator

PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = PACKAGE_DIR.parent
SERVER_DIR = PROJECT_DIR / "server"
DEFAULT_DATA_DIR = PROJECT_DIR / "data_v2"


def _load_organizers_inbox():
    """Import the organizers' ``loader.Inbox`` from ``server/`` (read-only)."""
    loader_path = SERVER_DIR / "loader.py"
    if not loader_path.is_file():
        raise FileNotFoundError(f"organizers' loader.py not found at {loader_path}")
    spec = importlib.util.spec_from_file_location("sdoc_organizers_loader", loader_path)
    if spec is None or spec.loader is None:  # pragma: no cover - import machinery
        raise ImportError(f"cannot load organizers' loader from {loader_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.Inbox


class LoaderClient:
    """Thin, deterministic facade over ``loader.Inbox``."""

    def __init__(self, source: str | Path | None = None):
        resolved = source if source is not None else DEFAULT_DATA_DIR
        self.source = str(resolved)
        self.is_http = self.source.startswith("http://") or self.source.startswith("https://")
        self._inbox = _load_organizers_inbox()(self.source)
        self._emails: list[dict] | None = None

    # -- listing ---------------------------------------------------------
    def emails(self) -> list[dict]:
        if self._emails is None:
            self._emails = list(self._inbox.emails())
        return self._emails

    def __iter__(self) -> Iterator[dict]:
        return iter(self.emails())

    def __len__(self) -> int:
        return len(self.emails())

    def email_ids(self) -> list[str]:
        return [str(email["email_id"]) for email in self.emails()]

    def get(self, email_id: str) -> dict:
        return self._inbox.get(email_id)

    # -- attachments -----------------------------------------------------
    def read_bytes(self, att_path: str) -> bytes:
        return self._inbox.read_bytes(att_path)

    def read_text(self, att_path: str) -> str:
        return self._inbox.read_text(att_path, encoding="utf-8")

    # -- submission ------------------------------------------------------
    def submit(self, submission: dict) -> dict:
        return self._inbox.submit(submission)

    def sample_submission(self) -> dict:
        return self._inbox.sample_submission()

    def health(self) -> dict:
        """``GET /health`` (HTTP mode only)."""
        if not self.is_http:
            raise RuntimeError("health() needs an HTTP source")
        return self._inbox._get_json("/health")

    def write_submission(self, submission: dict, out_path: str | Path) -> Path:
        """Atomic JSON write: temp file + ``os.replace`` (readers see a complete file)."""
        out = Path(out_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        tmp = out.with_name(out.name + ".tmp")
        tmp.write_text(json.dumps(submission, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(out)
        return out
