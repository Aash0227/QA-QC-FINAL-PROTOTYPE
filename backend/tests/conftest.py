import sys
from pathlib import Path

import pytest

# Make the backend package importable as `app.*`.
BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


@pytest.fixture(autouse=True)
def _unshadow_artifact_dir():
    """Keep ``config.ARTIFACT_DIR`` resolving through ``config.__getattr__``.

    ``ARTIFACT_DIR`` is not a real module attribute — PEP 562 ``__getattr__``
    computes it per access from the request-scoped project ContextVar. Seventeen
    test modules do ``monkeypatch.setattr(config, "ARTIFACT_DIR", tmp_path)``.
    That call succeeds (``getattr`` works), but monkeypatch first records the
    value ``__getattr__`` returned — a path inside the LIVE artifacts directory —
    and on undo writes it back as a **real** attribute. From that moment the
    dynamic resolution is shadowed for the rest of the session, and any later
    test that writes through ``config.artifact_path()`` without monkeypatching
    lands in the developer's real workspace instead of ``tmp_path``.

    That is not hypothetical: it overwrote a real project_manifest.json during
    development (recovered with scripts/repair_manifest.py). Clearing the
    shadowing attribute around every test restores dynamic resolution. Done at
    setup as well as teardown because finalizer order relative to monkeypatch's
    own undo is not guaranteed.
    """
    from app import config

    # ARTIFACT_DIR and the dirs derived from it (NOT PROJECTS_DIR, which is a
    # real module attribute): any of them left as a real attr by a previous
    # test's monkeypatch undo shadows the ContextVar resolution and redirects
    # later writes into another test's tmp dir (or the live workspace).
    for name in ("ARTIFACT_DIR", "EVIDENCE_DIR", "UPLOAD_DIR", "PAGES_DIR"):
        config.__dict__.pop(name, None)
    yield
    for name in ("ARTIFACT_DIR", "EVIDENCE_DIR", "UPLOAD_DIR", "PAGES_DIR"):
        config.__dict__.pop(name, None)


# production-plan §9: `revit_live` tests need Revit open with the Nonica AI
# Connector answering. Probe the bridge once per session (only if such a test
# was actually collected — the probe spawns the MCP exe, so normal runs never
# pay for it) and skip them all when the connector is silent. The marker itself
# is registered in pytest.ini, so unmarked runs emit no warning.
_revit_live_status: dict | None = None


def _connector_answers() -> bool:
    global _revit_live_status
    if _revit_live_status is None:
        try:
            from app import revit_bridge as rb
            _revit_live_status = rb.status()
        except Exception as exc:  # import/spawn failure reads as disconnected
            _revit_live_status = {"connected": False, "reason": str(exc)}
    return bool(_revit_live_status.get("connected"))


def pytest_collection_modifyitems(config: pytest.Config, items: list) -> None:
    live = [it for it in items if it.get_closest_marker("revit_live")]
    if not live or _connector_answers():
        return
    skip = pytest.mark.skip(reason="Revit connector not answering (revit_live).")
    for it in live:
        it.add_marker(skip)
