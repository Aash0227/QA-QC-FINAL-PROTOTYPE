"""Tests 1-5: hold-down name normalization and mark<->core-token mapping."""
import pytest

from app.normalization import (
    expected_core_token_for_mark,
    mapped_mark_for_core_token,
    normalize_holdown_type,
)


@pytest.mark.parametrize(
    "raw",
    ["S/HDU6", "SHDU6", "HDU6", "S-HDU6", "SHDU6-With Bolt", "s hdu6", "S_HDU6 offset"],
)
def test_variants_normalize_to_hdu6(raw):
    """Test 1: slash/hyphen/space/case/suffix variants all reduce to HDU6."""
    assert normalize_holdown_type(raw).core_token == "HDU6"


def test_mark_to_core_token_mappings():
    """Tests 2-5: H1->HDU6, H2->HDU11, H3->HD10S, H4->HD15B."""
    assert expected_core_token_for_mark("H1") == "HDU6"
    assert expected_core_token_for_mark("H2") == "HDU11"
    assert expected_core_token_for_mark("H3") == "HD10S"
    assert expected_core_token_for_mark("H4") == "HD15B"


def test_core_token_to_mark_roundtrip():
    assert mapped_mark_for_core_token("HDU6") == "H1"
    assert mapped_mark_for_core_token("HDU11") == "H2"
    assert mapped_mark_for_core_token("HD10S") == "H3"
    assert mapped_mark_for_core_token("HD15B") == "H4"


def test_bolt_suffix_ignored():
    assert normalize_holdown_type("SHDU11-With Bolt").core_token == "HDU11"
    assert normalize_holdown_type("SHD15B-WITH BOLT").core_token == "HD15B"
