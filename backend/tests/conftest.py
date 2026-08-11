import sys
from pathlib import Path

import pytest

# Make the backend package importable as `app.*`.
BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


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
