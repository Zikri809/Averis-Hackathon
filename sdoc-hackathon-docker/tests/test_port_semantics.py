from __future__ import annotations

from app.stage3_normalize import port_name


def test_trailing_five_letter_locode_is_ignored():
    assert port_name("PYEONGTAEK, SOUTH KOREA (KRPTK)") == port_name(
        "PYEONGTAEK, SOUTH KOREA"
    )


def test_qualifier_parentheses_are_ignored_for_compare():
    assert port_name("PORT KLANG (WESTPORT), MALAYSIA") == port_name("PORT KLANG, MALAYSIA")


def test_non_locode_parenthetical_is_also_removed_as_qualifier():
    assert port_name("SINGAPORE (TERMINAL)") == port_name("SINGAPORE")
