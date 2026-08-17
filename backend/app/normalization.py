from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path


def _load_project_config() -> dict:
    """Load per-project config from ARTIFACT_DIR/project_config.json if it exists."""
    try:
        from . import config
        path = config.ARTIFACT_DIR / "project_config.json"
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


# The Madera H1-H4<->HDU vocabulary. Served ONLY behind the opt-in madera
# detection profile (project manifest declares detection_profile == "madera",
# see app/profile.py); every other project gets generic behavior — an empty
# map, learned from its own data.
MADERA_VOCAB: dict[str, str] = {
    "HDU6": "H1",
    "HDU11": "H2",
    "HD10S": "H3",
    "HD15B": "H4",
}


def _madera_profile_active() -> bool:
    """Opt-in gate: the Madera vocabulary is available only when the active
    project's manifest declares detection_profile == 'madera'."""
    try:
        from . import profile

        return profile.detection_profile() == "madera"
    except Exception:
        return False


def _build_core_token_map() -> dict[str, str]:
    """Build CORE_TOKEN_TO_MARK: project config wins; otherwise the Madera
    H1-H4<->HDU vocabulary is served only behind the opt-in madera detection
    profile. Every other project (including no project context at all) gets an
    EMPTY map — generic behavior, no Madera vocabulary leakage."""
    cfg = _load_project_config()
    vocab = cfg.get("holdown_vocabulary")
    if isinstance(vocab, dict) and vocab:
        return {str(k).upper(): str(v).upper() for k, v in vocab.items()}
    if _madera_profile_active():
        return dict(MADERA_VOCAB)
    return {}


def _core_token_map() -> dict[str, str]:
    """Call-time resolution — a long-lived server switches projects per request,
    so the map must follow the ACTIVE project, not the one at import time."""
    return _build_core_token_map()


def __getattr__(name: str):  # PEP 562 — live view for module-attr consumers
    # (pdf_convert.MARK_TO_CORE_TOKEN, revit_convert.CORE_TOKEN_TO_MARK, tests)
    if name == "CORE_TOKEN_TO_MARK":
        return _core_token_map()
    if name == "MARK_TO_CORE_TOKEN":
        return {mark: core for core, mark in _core_token_map().items()}
    if name == "KNOWN_CORE_TOKENS":
        return tuple(_core_token_map())
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


# Eager defaults so `from app.normalization import MARK_TO_CORE_TOKEN` (a real
# attr at import) still binds; the functions below always use _core_token_map().
CORE_TOKEN_TO_MARK: dict[str, str] = _core_token_map()
MARK_TO_CORE_TOKEN = {mark: core for core, mark in CORE_TOKEN_TO_MARK.items()}
KNOWN_CORE_TOKENS = tuple(CORE_TOKEN_TO_MARK)


@dataclass(frozen=True)
class HoldownNormalization:
    raw: str
    cleaned: str
    core_token: str
    structural_token: str
    bolt_variant: str
    mapped_mark: str | None
    confidence: float
    known: bool


def normalize_holdown_type(value: str) -> HoldownNormalization:
    raw = str(value or "")
    cleaned = re.sub(r"[^A-Z0-9]", "", raw.upper())
    bolt_variant = _extract_bolt_variant(cleaned)
    core_token = _extract_core_token(cleaned)
    structural_token = f"S{core_token}" if core_token and cleaned.startswith(f"S{core_token}") else ""
    mapped_mark = mapped_mark_for_core_token(core_token)
    known = core_token in _core_token_map()

    if known:
        confidence = 0.95
        if not structural_token and core_token != cleaned:
            confidence = 0.9
    elif cleaned:
        confidence = 0.15
    else:
        confidence = 0.0

    return HoldownNormalization(
        raw=raw,
        cleaned=cleaned,
        core_token=core_token,
        structural_token=structural_token,
        bolt_variant=bolt_variant,
        mapped_mark=mapped_mark,
        confidence=confidence,
        known=known,
    )


def _get_mark_pattern() -> str:
    """Configurable mark recognition pattern.
    
    Priority: project config > teach memory > broad generic fallback.
    Project config: {"holdown_mark_pattern": "^H[1-4]$"}
    Teach memory: entries with kind="mark_pattern" and category="holdown"
    Fallback: r"^[A-Z]+-?\\d{1,2}$" (any letter prefix + 1-2 digits)
    """
    cfg = _load_project_config()
    pattern = cfg.get("holdown_mark_pattern")
    if isinstance(pattern, str) and pattern:
        try:
            re.compile(pattern)
            return pattern
        except re.error:
            pass
    # Try teach memory
    try:
        from . import teach
        memory = teach.load_memory()
        overrides = teach.build_overrides(memory)
        patterns = overrides.get("mark_patterns", {}).get("holdown", [])
        if patterns:
            return patterns[0]
    except Exception:
        pass
    # Broad generic fallback
    return r"^[A-Z]+-?\d{1,2}$"


def _get_strip_suffixes() -> tuple[str, ...]:
    """Configurable suffix stripping list via env var or project config.
    
    Env var: QAQC_STRIP_SUFFIXES=WITHANCHOR,WITHBOLT1,WITHBOLT2,WITHBOLT,BOLT1,BOLT2,ANCHOR
    Project config: {"strip_suffixes": ["WITHANCHOR", "WITHBOLT1", ...]}
    Default: ("WITHANCHOR", "WITHBOLT1", "WITHBOLT2", "WITHBOLT", "BOLT1", "BOLT2", "ANCHOR")
    """
    env_val = os.environ.get("QAQC_STRIP_SUFFIXES", "").strip()
    if env_val:
        return tuple(s.strip() for s in env_val.split(",") if s.strip())
    cfg = _load_project_config()
    suffixes = cfg.get("strip_suffixes")
    if isinstance(suffixes, list) and suffixes:
        return tuple(str(s) for s in suffixes)
    return ("WITHANCHOR", "WITHBOLT1", "WITHBOLT2", "WITHBOLT", "BOLT1", "BOLT2", "ANCHOR")


def normalize_holdown_mark(value: str) -> HoldownNormalization:
    raw = str(value or "")
    cleaned = re.sub(r"[^A-Z0-9]", "", raw.upper())
    # Configurable mark pattern: from project config, teach memory, or broad generic fallback.
    _mark_pattern = _get_mark_pattern()
    match = re.fullmatch(_mark_pattern, cleaned)
    core_token = expected_core_token_for_mark(cleaned) if match else None
    if core_token:
        return HoldownNormalization(
            raw=raw,
            cleaned=cleaned,
            core_token=core_token,
            structural_token=f"S{core_token}",
            bolt_variant="",
            mapped_mark=cleaned,
            confidence=0.98,
            known=True,
        )
    return HoldownNormalization(
        raw=raw,
        cleaned=cleaned,
        core_token="",
        structural_token="",
        bolt_variant="",
        mapped_mark=None,
        confidence=0.15 if cleaned else 0.0,
        known=False,
    )


def holdown_types_equivalent(left: str, right: str) -> bool:
    left_result = normalize_holdown_type(left)
    right_result = normalize_holdown_type(right)
    return bool(
        left_result.known
        and right_result.known
        and left_result.core_token == right_result.core_token
    )


def mapped_mark_for_core_token(core_token: str) -> str | None:
    return _core_token_map().get(str(core_token or "").upper())


def expected_core_token_for_mark(mark: str) -> str | None:
    cleaned = re.sub(r"[^A-Z0-9]", "", str(mark or "").upper())
    return {m: c for c, m in _core_token_map().items()}.get(cleaned)


def _extract_core_token(cleaned: str) -> str:
    if not cleaned:
        return ""
    mark_core = expected_core_token_for_mark(cleaned)
    if mark_core:
        return mark_core
    candidates = [cleaned]
    if cleaned.startswith("S"):
        candidates.append(cleaned[1:])
    stripped = _strip_known_suffixes(cleaned)
    candidates.append(stripped)
    if stripped.startswith("S"):
        candidates.append(stripped[1:])
    for candidate in candidates:
        for token in _core_token_map():
            if candidate == token or candidate.startswith(token):
                return token
            if candidate == f"S{token}" or candidate.startswith(f"S{token}"):
                return token
    for token in _core_token_map():
        if token in cleaned or f"S{token}" in cleaned:
            return token
    return ""


def _strip_known_suffixes(cleaned: str) -> str:
    value = cleaned
    for suffix in _get_strip_suffixes():
        value = value.replace(suffix, "")
    return value


def _extract_bolt_variant(cleaned: str) -> str:
    match = re.search(r"BOLT([12])", cleaned)
    return f"BOLT{match.group(1)}" if match else ""
