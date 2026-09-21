from __future__ import annotations

import json
from pathlib import Path

from app import run as run_module
from app.loader_client import LoaderClient

PROJECT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_DIR / "data_v2"


def test_stage3_produces_expected_fields_for_ready_pairs():
    client = LoaderClient(DATA_DIR)
    submission = run_module.run(data_dir=DATA_DIR, out_path=None, use_checkpoint=False)
    truth = json.loads((DATA_DIR / "ground_truth.json").read_text(encoding="utf-8"))

    for email in client.emails():
        email_id = email["email_id"]
        expected = truth[email_id]
        category, _decided_by = run_module.classify_email(email)
        extraction = run_module.extract_email(email, category, client)
        if not extraction.ready or not extraction.has_docs:
            continue

        got = submission[email_id]
        if expected["category"] != "BL_COMPARISON":
            continue
        if expected["status"] == "MISMATCH":
            assert got["status"] == "MISMATCH", email_id
            assert set(got["defect_fields"]) == set(expected["defect_fields"]), email_id
        elif expected["status"] == "OK":
            assert got["defect_fields"] == [], email_id
