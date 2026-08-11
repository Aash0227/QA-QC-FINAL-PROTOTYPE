from __future__ import annotations

import re
from dataclasses import dataclass

CORE_TOKEN_TO_MARK = {
    "HDU6": "H1",
    "HDU11": "H2",
    "HD10S": "H3",
    "HD15B": "H4",
}
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
    known = core_token in CORE_TOKEN_TO_MARK

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


def normalize_holdown_mark(value: str) -> HoldownNormalization:
    raw = str(value or "")
    cleaned = re.sub(r"[^A-Z0-9]", "", raw.upper())
    match = re.fullmatch(r"H[1-4]", cleaned)
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
    return CORE_TOKEN_TO_MARK.get(str(core_token or "").upper())


def expected_core_token_for_mark(mark: str) -> str | None:
    cleaned = re.sub(r"[^A-Z0-9]", "", str(mark or "").upper())
    return MARK_TO_CORE_TOKEN.get(cleaned)


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
        for token in KNOWN_CORE_TOKENS:
            if candidate == token or candidate.startswith(token):
                return token
            if candidate == f"S{token}" or candidate.startswith(f"S{token}"):
                return token
    for token in KNOWN_CORE_TOKENS:
        if token in cleaned or f"S{token}" in cleaned:
            return token
    return ""


def _strip_known_suffixes(cleaned: str) -> str:
    value = cleaned
    for suffix in (
        "WITHANCHOR",
        "WITHBOLT1",
        "WITHBOLT2",
        "WITHBOLT",
        "BOLT1",
        "BOLT2",
        "ANCHOR",
    ):
        value = value.replace(suffix, "")
    return value


def _extract_bolt_variant(cleaned: str) -> str:
    match = re.search(r"BOLT([12])", cleaned)
    return f"BOLT{match.group(1)}" if match else ""
