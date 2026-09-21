"""Alias table coverage and the v3-A3/A4 guards (plan 02 T1)."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from app.normalize import norm_label
from app.stage2 import aliases

DATA_DIR = Path(__file__).resolve().parent.parent / "data_v2"
COMPARE_FIELDS = [
    "shipper",
    "consignee",
    "notify_party",
    "port_of_loading",
    "port_of_discharge",
    "container_count",
    "gross_weight_kg",
]


def load_pools():
    """Import the generator's ``pools.py`` without touching ``sys.path``."""
    spec = importlib.util.spec_from_file_location("sdoc_pools", DATA_DIR / "pools.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["sdoc_pools"] = module
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("field_name", COMPARE_FIELDS)
def test_every_pools_label_resolves(field_name):
    pools = load_pools()
    for literal in pools.LABELS[field_name]:
        assert aliases.canonical(literal) == field_name, literal


def test_alias_table_hash_is_stable_and_exported():
    assert isinstance(aliases.ALIAS_TABLE_HASH, str)
    assert len(aliases.ALIAS_TABLE_HASH) == 64
    assert aliases.table_hash() == aliases.ALIAS_TABLE_HASH
    assert aliases.ALIAS_TABLE_HASH == aliases.ALIAS_TABLE_HASH


def test_notify_party_intermediate_consignee_is_not_consignee():
    """v3-A4: exact match, never substring."""
    assert aliases.canonical("Notify Party/Intermediate Consignee") == "notify_party"
    assert aliases.canonical("NOTIFY PARTY/INTERMEDIATE CONSIGNEE") == "notify_party"
    assert aliases.canonical("Consignee") == "consignee"
    assert aliases.canonical("NOTIFY PARTY") == "notify_party"


def test_cjk_label_normalizes_to_gross_weight():
    """v3-A3: non-ASCII strip happens before lookup."""
    assert aliases.canonical("Gross Weight毛重(KGS)") == "gross_weight_kg"
    assert aliases.canonical("Gross Weight (KG)") == "gross_weight_kg"
    assert aliases.canonical("GROSS WEIGHT") == "gross_weight_kg"


def test_unknown_labels_return_none():
    assert aliases.canonical("Loading Port") is None
    assert aliases.canonical("Origin Port") is None
    assert aliases.canonical("Vessel") is None
    assert aliases.canonical("") is None
    assert aliases.canonical(None) is None


def test_known_non_compare_labels_are_classified_as_such():
    assert aliases.is_known_non_compare("NET WEIGHT") == "net_weight"
    assert aliases.is_known_non_compare("Vessel") == "vessel"
    assert aliases.is_known_non_compare("HS Code") == "hs_code"
    assert aliases.is_known_non_compare("Consignee") is None


def test_no_alias_collisions_after_normalization():
    seen: dict[str, str] = {}
    for key, field_name in aliases.ALIASES.items():
        assert key == norm_label(key), f"table key not normalized: {key!r}"
        assert key not in seen or seen[key] == field_name
        seen[key] = field_name
