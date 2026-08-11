# ponytail: one-shot recovery script — replays Write/Edit tool calls for
# frontend/index.html from the Claude session transcript to rebuild the lost v3 UI.
import json
import sys
from pathlib import Path

TRANSCRIPT = Path(r"C:\Users\aashd\.claude\projects\c--QA-QC-FINAL-PROTOTYPE-bkp\64e270b0-2d89-4d3e-a110-c1b9cffcd8df.jsonl")

content = None
snapshots = []
applied, skipped = 0, 0

for line in TRANSCRIPT.read_text(encoding="utf-8").splitlines():
    try:
        rec = json.loads(line)
    except json.JSONDecodeError:
        continue
    msg = rec.get("message") or {}
    blocks = msg.get("content") if isinstance(msg.get("content"), list) else []
    for block in blocks:
        if not isinstance(block, dict) or block.get("type") != "tool_use":
            continue
        name = block.get("name")
        inp = block.get("input") or {}
        fp = str(inp.get("file_path", "")).replace("\\", "/").lower()
        if not fp.endswith("frontend/index.html"):
            continue
        if name == "Write":
            content = inp["content"]
            applied += 1
            snapshots.append(content)
            print(f"Write  #{applied}: {len(content)} chars")
        elif name == "Edit" and content is not None:
            old, new = inp.get("old_string", ""), inp.get("new_string", "")
            if old and old in content:
                count = None if inp.get("replace_all") else 1
                content = content.replace(old, new) if count is None else content.replace(old, new, 1)
                applied += 1
                snapshots.append(content)
                print(f"Edit   #{applied}: -{len(old)} +{len(new)} chars")
            else:
                skipped += 1
                print(f"skip Edit (old_string not found, {len(old)} chars) — likely a denied/duplicate retry")

if content is None:
    sys.exit("FATAL: no Write of frontend/index.html found in transcript")

# transcript has replayed/duplicated trailing writes — keep the last snapshot
# that actually contains the v3 features
best = None
for snap in snapshots:
    if "infoBall" in snap and "teach" in snap.lower():
        best = snap
if best is None:
    sys.exit("FATAL: no snapshot contains v3 markers (infoBall + teach)")
content = best

for marker in ("infoBall", "teach", "Pipeline"):
    print(f"marker {marker!r}: {'OK' if marker in content else 'MISSING'}")

out = Path(r"C:\QA-QC-FINAL-PROTOTYPE-bkp\frontend\index.html")
out.write_text(content, encoding="utf-8")
print(f"WROTE {out} ({len(content)} chars), applied={applied}, skipped={skipped}")
