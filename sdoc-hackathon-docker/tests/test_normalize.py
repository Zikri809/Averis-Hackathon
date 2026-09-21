"""Contract test — normalization, including v3-A2/A3/A4 (plan 00 F2)."""
from __future__ import annotations

import pytest

from app.normalize import (
    canonical,
    compute_alias_table_hash,
    empty_hash,
    is_blank,
    norm_compare,
    norm_label,
    parse_count,
    parse_weight,
)


# ---------------------------------------------------------------------------
# v3-A3 — strip all non-ASCII before punctuation collapse
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Gross Weight毛重(KGS)", "GROSS WEIGHT"),
        ("TOTAL Gross WeightII(KGS)", "TOTAL GROSS WEIGHTII"),
        ("Gross Weight (KG)", "GROSS WEIGHT"),
        ("Shipper (发货人)", "SHIPPER"),
        ("Consignee (收货人)", "CONSIGNEE"),
        ("  Port of Loading (POL)  ", "PORT OF LOADING"),
        ("No. of Containers or Packages", "NO OF CONTAINERS OR PACKAGES"),
        ("Kinds of Packages; Description of Goods", "KINDS OF PACKAGES DESCRIPTION OF GOODS"),
        ("", ""),
        (None, ""),
    ],
)
def test_norm_label(raw, expected):
    assert norm_label(raw) == expected


def test_norm_label_strips_cjk_so_weight_label_matches():
    assert norm_label("Gross Weight毛重(KGS)") == "GROSS WEIGHT"
    assert norm_label("GROSS WEIGHT") == "GROSS WEIGHT"


def test_norm_compare_collapses_whitespace_and_punctuation():
    assert norm_compare("APRIL FINE PAPER TRADING (MIDDLE EAST) FZE") == (
        "APRIL FINE PAPER TRADING MIDDLE EAST FZE"
    )
    assert norm_compare("  a.b,c  ") == "A B C"
    assert norm_compare(None) == ""


# ---------------------------------------------------------------------------
# v3-A4 — exact match, longest-first tiebreak, never substring
# ---------------------------------------------------------------------------
ALIASES = {
    "SHIPPER": "shipper",
    "CONSIGNEE": "consignee",
    "NOTIFY PARTY": "notify_party",
    "NOTIFY PARTY INTERMEDIATE CONSIGNEE": "notify_party",
    "TO THE ORDER OF": "consignee",
    "GROSS WEIGHT": "gross_weight_kg",
    "GROSS WT": "gross_weight_kg",
}


def test_canonical_exact_match_not_substring():
    assert canonical("Notify Party/Intermediate Consignee", ALIASES) == "notify_party"
    assert canonical("CONSIGNEE", ALIASES) == "consignee"
    assert canonical("To the Order of", ALIASES) == "consignee"
    assert canonical("Gross Weight毛重(KGS)", ALIASES) == "gross_weight_kg"
    assert canonical("Notify Party", ALIASES) == "notify_party"


def test_canonical_rejects_substring_and_unmatched():
    assert canonical("NOTIFY PARTY SOMETHING ELSE", ALIASES) is None
    assert canonical("PORT OF LOADING", ALIASES) is None
    assert canonical("", ALIASES) is None
    assert canonical(None, ALIASES) is None


def test_canonical_tolerates_unnormalized_table():
    unnormalized = {"Gross Weight毛重(KGS)": "gross_weight_kg"}
    assert canonical("Gross Weight毛重(KGS)", unnormalized) == "gross_weight_kg"


def test_alias_table_hash_is_order_independent_and_stable():
    a = {"A": "x", "B": "y"}
    b = {"B": "y", "A": "x"}
    assert compute_alias_table_hash(a) == compute_alias_table_hash(b)
    assert compute_alias_table_hash(a) != compute_alias_table_hash({"A": "y", "B": "y"})
    assert empty_hash() == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"


# ---------------------------------------------------------------------------
# v3-A2 — unit rule for binary formats
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "raw,expected",
    [
        ("128.54 KG", 128.54),
        ("126,544 KGS", 126544.0),
        ("21,577 KG", 21577.0),
        ("117,770 KG", 117770.0),
        ("243,588 KGS", 243588.0),
    ],
)
def test_parse_weight_text_with_unit(raw, expected):
    assert parse_weight(raw, "txt") == expected
    assert parse_weight(raw, "pdf") == expected


@pytest.mark.parametrize("raw", ["341715", "243,588", "21,577"])
def test_parse_weight_binary_unitless_string(raw):
    assert parse_weight(raw, "xlsx") is not None
    assert parse_weight(raw, "docx") is not None


@pytest.mark.parametrize("raw", ["341715", "243,588", "21,577"])
def test_parse_weight_text_without_unit_is_null(raw):
    assert parse_weight(raw, "txt") is None
    assert parse_weight(raw, "pdf") is None


def test_parse_weight_numeric_cells_accepted_as_kg():
    assert parse_weight(341715, "xlsx") == 341715.0
    assert parse_weight(243588.0, "docx") == 243588.0
    assert parse_weight(0, "xlsx") == 0.0


@pytest.mark.parametrize("raw", ["N/A", "TBA", "???", "____MT", "_______", "", None, "NET WEIGHT"])
def test_parse_weight_blanks_and_junk(raw):
    assert parse_weight(raw, "txt") is None
    assert parse_weight(raw, "xlsx") is None


def test_parse_weight_never_guesses_a_unit():
    assert parse_weight("TOTAL 117770", "txt") is None
    assert parse_weight("21.5 MT", "txt") is None


# ---------------------------------------------------------------------------
# counts
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "raw,expected",
    [
        ("1 x 40'HC", 1),
        ("15 x 20'GP", 15),
        ("12", 12),
        (12, 12),
        (12.0, 12),
        ("3 x 40'HC", 3),
    ],
)
def test_parse_count(raw, expected):
    assert parse_count(raw) == expected


@pytest.mark.parametrize("raw", ["N/A", "TBA", "???", "____MT", "", None, "TOTAL"])
def test_parse_count_blanks(raw):
    assert parse_count(raw) is None


# ---------------------------------------------------------------------------
# blanks
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("raw", ["N/A", "n/a", "TBA", "TBC", "???", "___", "____MT", "", "   ", None, "-"])
def test_is_blank_true(raw):
    assert is_blank(raw) is True


@pytest.mark.parametrize("raw", ["SINGAPORE", 0, 1, 128.54, "0", "A"])
def test_is_blank_false(raw):
    assert is_blank(raw) is False
