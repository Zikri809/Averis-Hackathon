"""The single alias table (plan 02 T1).

Aliases are **data, not code** (E2): every literal in ``pools.LABELS`` for the
7 compared fields must resolve after normalization. Lookup is exact-match on
the whole normalized label with a longest-first tiebreak (v3-A4) — substring
matching is forbidden, because it is the only way
``Notify Party/Intermediate Consignee`` could be routed into ``consignee``.

The table is keyed by the *normalized* alias (``norm_label``), so
``Gross Weight毛重(KGS)`` and ``Gross Weight (KG)`` collapse to the same key.
``ALIAS_TABLE_HASH`` enters the checkpoint key (plan 00 F4).
"""
from __future__ import annotations

from ..normalize import compute_alias_table_hash, norm_label

#: Canonical alias literals, grouped by field. Source: ``data_v2/pools.py``
#: LABELS for the 7 compared fields (plus real-world synonyms seen in the
#: attachments and in the reference samples).
_ALIAS_LITERALS: dict[str, list[str]] = {
    "shipper": [
        "Shipper",
        "Shipper/Exporter",
        "Shipper (Principal or Seller)",
        "SHIPPER",
        "Shipper Name",
    ],
    "consignee": [
        "Consignee",
        "Consignee (Non-Negotiable)",
        "CONSIGNEE",
        "To the Order of",
    ],
    "notify_party": [
        "Notify Party",
        "Notify",
        "Notify Party/Intermediate Consignee",
        "NOTIFY PARTY",
    ],
    "port_of_loading": [
        "Port of Loading",
        "Port of Loading (POL)",
        "Load Port",
        "POL",
        "PORT OF LOADING",
    ],
    "port_of_discharge": [
        "Port of Discharge",
        "Port of Discharge (POD)",
        "Discharge Port",
        "POD",
        "PORT OF DISCHARGE",
    ],
    "container_count": [
        "No. of Containers",
        "Total Containers",
        "No. of Containers or Packages",
        "Container Count",
    ],
    "gross_weight_kg": [
        "Gross Weight (KG)",
        "Gross Wt (kgs)",
        "Gross Weight毛重(KGS)",
        "GROSS WEIGHT",
    ],
}

#: Labels that look like fields but are explicitly **not** compared. Kept so
#: the parser can record them as evidence and so tests can assert they are
#: never routed into one of the 7 fields.
NON_COMPARE_LITERALS: dict[str, list[str]] = {
    "vessel": ["Vessel", "Ocean Vessel", "Vessel Name", "Export Carrier (vessel, voyage)"],
    "voyage": ["Voyage No.", "Voy.", "Voy. No", "Voyage"],
    "commodity": [
        "Commodity",
        "Description of Goods",
        "Description",
        "Kinds of Packages; Description of Goods",
    ],
    "booking": ["Booking Reference", "Booking No.", "Booking Ref", "BOOKING NO."],
    "bl_no": ["B/L No.", "BL No.", "Bill of Lading No.", "B/L NUMBER"],
    "net_weight": ["NET WEIGHT"],
    "hs_code": ["HS Code"],
    "oc_no": ["OC No."],
    "freight": ["Freight"],
}

#: ``{normalized_alias: canonical_field}`` — the lookup the parser uses.
ALIASES: dict[str, str] = {}


def _build_table() -> dict[str, str]:
    table: dict[str, str] = {}
    for field_name, literals in _ALIAS_LITERALS.items():
        for literal in literals:
            key = norm_label(literal)
            if not key:
                continue
            existing = table.get(key)
            if existing is not None and existing != field_name:
                raise ValueError(
                    f"alias collision after normalization: {literal!r} -> "
                    f"{existing!r} / {field_name!r}"
                )
            table[key] = field_name
    return table


ALIASES = _build_table()

#: Normalized labels that are known non-compare fields (never mapped).
NON_COMPARE_ALIASES: dict[str, str] = {
    norm_label(literal): field_name
    for field_name, literals in NON_COMPARE_LITERALS.items()
    for literal in literals
}

#: sha256 of the sorted table; enters the checkpoint key (plan 00 F4).
ALIAS_TABLE_HASH: str = compute_alias_table_hash(ALIASES)


def canonical(label: str | None) -> str | None:
    """Exact-match a raw label to a compared field, or ``None``.

    ``Notify Party/Intermediate Consignee`` resolves to ``notify_party`` and
    never to ``consignee`` (v3-A4).
    """
    from ..normalize import canonical as _canonical

    return _canonical(label, ALIASES)


def is_known_non_compare(label: str | None) -> str | None:
    """Return the non-compare field name for labels like ``NET WEIGHT``."""
    key = norm_label(label)
    return NON_COMPARE_ALIASES.get(key)


def table_hash() -> str:
    return ALIAS_TABLE_HASH
