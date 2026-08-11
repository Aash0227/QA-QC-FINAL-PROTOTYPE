"""Revit UniqueId <-> ElementId decoding (BUG-05).

A Revit UniqueId is `<episode-GUID>-<8 hex>`, e.g.
``b640de49-6eda-4e8c-b2c0-bcb941f0c3f9-000ffe7f``. The trailing 8 hex is NOT
the ElementId directly — the naive ``int(suffix, 16)`` decode silently maps to
the WRONG element whenever the XOR component is non-zero (4 of 7 real Madera
elements failed this way during validation). The real ElementId is the trailing
8 hex XOR'd with the last 8 hex of the GUID's final group.

This helper is the ONE correct decode and must use it rather than any hex-suffix shortcut.
"""

from __future__ import annotations


def unique_id_to_element_id(unique_id: str) -> int:
    """Decode a Revit UniqueId string to its integer ElementId."""
    parts = unique_id.strip().split("-")
    if len(parts) < 2:
        raise ValueError(f"Not a Revit UniqueId: {unique_id!r}")
    element_hex = parts[-1]
    guid_tail = parts[-2][-8:]  # last 8 hex of the GUID's final 12-hex group
    return int(element_hex, 16) ^ int(guid_tail, 16)


def _make_unique_id(guid_last_group: str, element_id: int) -> str:
    """Inverse, for tests: build the trailing suffix from a known ElementId."""
    suffix = int(guid_last_group[-8:], 16) ^ element_id
    return f"aaaaaaaa-bbbb-cccc-dddd-{guid_last_group}-{suffix:08x}"


if __name__ == "__main__":
    # Round-trip: any ElementId encoded then decoded must come back exactly,
    # for both zero and non-zero XOR components.
    for guid_group, eid in (
        ("bcb941f0c3f9", 1048191),      # non-zero XOR (the real failing case)
        ("000000000000", 1048191),      # zero XOR (naive decode would agree)
        ("ffffffffffff", 12345),
    ):
        uid = _make_unique_id(guid_group, eid)
        got = unique_id_to_element_id(uid)
        assert got == eid, f"{uid} -> {got} != {eid}"
    # And confirm the naive decode really would have been wrong for a non-zero case
    uid = _make_unique_id("bcb941f0c3f9", 1048191)
    naive = int(uid.split("-")[-1], 16)
    assert naive != 1048191, "expected naive decode to differ (that's the bug)"
    print("revit_ids self-check OK")
