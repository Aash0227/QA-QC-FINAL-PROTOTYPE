"""Hold-down name normalization and mark<->core-token mapping.

The mark<->core-token vocabulary is never built in: it comes entirely from
this project's own project_config.json ("holdown_vocabulary"). A project
with no config gets an empty map (normalize_holdown_type/expected_core_token
then report "unknown" rather than guessing). These tests prove the mechanism
works for an arbitrary vocabulary, not a specific project's mark family.
"""
import json

import pytest

from app import config
from app.normalization import (
    expected_core_token_for_mark,
    mapped_mark_for_core_token,
    normalize_holdown_type,
)

SAMPLE_VOCAB = {"HDU6": "H1", "HDU11": "H2", "HD10S": "H3", "HD15B": "H4"}


@pytest.fixture
def project_vocab(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "ARTIFACT_DIR", tmp_path)
    (tmp_path / "project_config.json").write_text(
        json.dumps({"holdown_vocabulary": SAMPLE_VOCAB}), encoding="utf-8"
    )
    return SAMPLE_VOCAB


def test_no_project_config_gives_empty_vocabulary(tmp_path, monkeypatch):
    """No project_config.json -> nothing is 'known'; the system never falls
    back to a built-in mark family."""
    monkeypatch.setattr(config, "ARTIFACT_DIR", tmp_path)
    assert expected_core_token_for_mark("H1") is None
    assert mapped_mark_for_core_token("HDU6") is None
    assert normalize_holdown_type("HDU6").known is False


@pytest.mark.parametrize(
    "raw",
    ["S/HDU6", "SHDU6", "HDU6", "S-HDU6", "SHDU6-With Bolt", "s hdu6", "S_HDU6 offset"],
)
def test_variants_normalize_to_hdu6(raw, project_vocab):
    """Slash/hyphen/space/case/suffix variants all reduce to the configured
    core token, driven by this project's own vocabulary."""
    assert normalize_holdown_type(raw).core_token == "HDU6"


def test_mark_to_core_token_mappings_from_project_config(project_vocab):
    assert expected_core_token_for_mark("H1") == "HDU6"
    assert expected_core_token_for_mark("H2") == "HDU11"
    assert expected_core_token_for_mark("H3") == "HD10S"
    assert expected_core_token_for_mark("H4") == "HD15B"


def test_core_token_to_mark_roundtrip(project_vocab):
    assert mapped_mark_for_core_token("HDU6") == "H1"
    assert mapped_mark_for_core_token("HDU11") == "H2"
    assert mapped_mark_for_core_token("HD10S") == "H3"
    assert mapped_mark_for_core_token("HD15B") == "H4"


def test_bolt_suffix_ignored(project_vocab):
    assert normalize_holdown_type("SHDU11-With Bolt").core_token == "HDU11"
    assert normalize_holdown_type("SHD15B-WITH BOLT").core_token == "HD15B"


def test_a_different_projects_vocabulary_works_identically(tmp_path, monkeypatch):
    """A completely different mark family (not H1-H4/HDU) must normalize the
    same way -- proves the mechanism is generic, not tuned to one project."""
    monkeypatch.setattr(config, "ARTIFACT_DIR", tmp_path)
    (tmp_path / "project_config.json").write_text(
        json.dumps({"holdown_vocabulary": {"STRONGTIEA": "PA1", "STRONGTIEB": "PA2"}}),
        encoding="utf-8",
    )
    assert expected_core_token_for_mark("PA1") == "STRONGTIEA"
    assert normalize_holdown_type("STRONGTIEA").core_token == "STRONGTIEA"
    assert normalize_holdown_type("STRONGTIEA").known is True
