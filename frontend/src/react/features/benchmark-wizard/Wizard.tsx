import { useEffect, useRef, useState } from "react";

import { api } from "../../../api";
import { onStep } from "../../../sse";
import { tokenized } from "../../../shared/api";
import { toast } from "../../../util";

import type {
  GridPointsResponse,
  HistoryEntry,
  Proposal,
  RevitStatus,
  Verification,
  Workflow,
} from "./types";
import {
  action,
  ensureLiveSubscription,
  maybeCheckRevit,
  setPickOn,
  setPicks,
  startPick,
  subscribeWizard,
  wizardState,
} from "./wizardStore";

const BM_STEPS: [string, string][] = [
  ["proposing", "Propose"],
  ["awaiting_pdf_approval", "PDF approval"],
  ["stamping", "Stamp PDF"],
  ["awaiting_revit", "Revit connect"],
  ["placing_markers", "Place markers"],
  ["awaiting_revit_approval", "Revit approval"],
  ["awaiting_export", "Fresh export"],
  ["calibrating", "Calibrate"],
  ["done", "Done"],
];

/** React port of panels/wizard.js -- the Benchmark Autopilot (2-point
 *  registration) state machine. Mounted into the existing #bm-rail/#bm-cards/
 *  #bm-log containers (#bmwizard's open/close class toggle stays vanilla --
 *  see the slim panels/wizard.js shim -- same pattern used for #table-panel
 *  in Stage 2). */

function Rail({ state }: { state: string }) {
  const idx = BM_STEPS.findIndex(([s]) => s === state);
  return (
    <>
      {BM_STEPS.map(([s, lbl], i) => {
        const cls = state === "failed" ? (i === 0 ? "failed" : "") : i < idx ? "past" : i === idx ? "active" : "";
        return (
          <div className={`bw-tick ${cls}`} key={s}>
            <span className="bw-dot" />
            <span className="bw-lbl">{lbl}</span>
          </div>
        );
      })}
      {state === "failed" && (
        <div className="bw-tick failed">
          <span className="bw-dot" />
          <span className="bw-lbl">FAILED</span>
        </div>
      )}
    </>
  );
}

function ProposalCard({ p }: { p: Proposal }) {
  return (
    <div className="bw-card">
      <h2>
        Proposal · {p.sheet_number} (page {p.page_index + 1})
      </h2>
      <div className="bw-crops">
        {p.benchmarks.map((b, i) => (
          <div className="bw-crop" key={i}>
            {b.evidence_url ? (
              <img src={tokenized(`${b.evidence_url}?t=${Date.now()}`)} alt={`${b.mark} evidence`} />
            ) : (
              <div style={{ aspectRatio: "1", display: "grid", placeItems: "center", color: "var(--bw-dim)", fontSize: 11 }}>
                no crop
              </div>
            )}
            <span className="bw-x" />
            <span className="bw-ring" />
            <span className="bw-tag">
              {b.mark} · {b.grid_label}
            </span>
          </div>
        ))}
      </div>
      <table>
        <thead>
          <tr>
            <th>Mark</th>
            <th>Grid</th>
            <th>PDF point</th>
            <th>Revit point</th>
          </tr>
        </thead>
        <tbody>
          {p.benchmarks.map((b, i) => (
            <tr key={i}>
              <td>{b.mark}</td>
              <td>{b.grid_label}</td>
              <td className="num">
                ({b.pdf_point_pt.x.toFixed(1)}, {b.pdf_point_pt.y.toFixed(1)}) pt
              </td>
              <td className="num">
                ({b.revit_point_ft.x.toFixed(3)}, {b.revit_point_ft.y.toFixed(3)}) ft
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="mono" style={{ color: "var(--bw-dim)", fontSize: 12, margin: "10px 0 0" }}>
        Separation {p.separation_pdf_pt} pt · {p.separation_revit_ft} ft · {p.candidates_considered} labeled
        intersections considered
      </p>
    </div>
  );
}

function ReadbackCard({ wf }: { wf: Workflow }) {
  const placed = [...(wf.history || [])].reverse().find((h) => h.to === "awaiting_revit_approval");
  const rb = placed?.payload?.readback;
  const p = wf.proposal;
  if (!p) return null;
  const unverified = placed && placed.payload?.verified === false;
  return (
    <div className="bw-card">
      <h2>Revit read-back vs intended</h2>
      <table>
        <thead>
          <tr>
            <th>Mark</th>
            <th>Intended (ft)</th>
            <th>Read-back (ft)</th>
            <th>Δ</th>
          </tr>
        </thead>
        <tbody>
          {p.benchmarks.map((b, i) => {
            const got = rb?.[b.mark];
            const d = got ? Math.hypot(got.x - b.revit_point_ft.x, got.y - b.revit_point_ft.y) : null;
            return (
              <tr key={i}>
                <td>{b.mark}</td>
                <td className="num">
                  ({b.revit_point_ft.x.toFixed(3)}, {b.revit_point_ft.y.toFixed(3)})
                </td>
                <td className="num">{got ? `(${got.x.toFixed(3)}, ${got.y.toFixed(3)})` : "— not reported —"}</td>
                <td className={`num ${d != null && d < 0.05 ? "bw-delta-ok" : "bw-delta-bad"}`}>
                  {d != null ? `${d.toFixed(4)} ft` : "?"}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      {unverified && (
        <div className="bw-unverified">
          ⚠ Agent-reported placement — not server-verified. Confirm against Revit before approving.
        </div>
      )}
    </div>
  );
}

function VerificationTable({ v }: { v: Verification }) {
  return (
    <table>
      <thead>
        <tr>
          <th>Mark</th>
          <th>Expected</th>
          <th>Found</th>
          <th>Δ</th>
        </tr>
      </thead>
      <tbody>
        {v.checks.map((c, i) => (
          <tr key={i}>
            <td>{c.mark}</td>
            <td className="num">
              ({c.expected.x.toFixed(1)}, {c.expected.y.toFixed(1)})
            </td>
            <td className="num">{c.found ? `(${c.found.x.toFixed(1)}, ${c.found.y.toFixed(1)})` : "— not found —"}</td>
            <td className={`num ${c.ok ? "bw-delta-ok" : "bw-delta-bad"}`}>{c.delta_pt ?? "?"} pt</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function RevitPill({ status }: { status: RevitStatus | null }) {
  const cls = !status ? "" : status.connected ? "on" : "off";
  const txt = !status
    ? "checking connection…"
    : status.connected
      ? `Revit connected${status.model_title ? ` · ${status.model_title}` : ""}`
      : status.reason || "Revit not connected";
  return (
    <div id="bw-revit-status" className={`bw-revit-status ${cls}`}>
      {txt}
    </div>
  );
}

interface GridPick {
  grid_id: string;
  mark: string;
  label?: string;
}

function PickCard({
  gp,
  picks,
  onPick,
  onClear,
  onCancel,
  onPropose,
}: {
  gp: GridPointsResponse | null;
  picks: GridPick[];
  onPick: (ev: React.MouseEvent<SVGSVGElement>) => void;
  onClear: () => void;
  onCancel: () => void;
  onPropose: () => void;
}) {
  if (!gp) {
    return (
      <div className="bw-card">
        <h2>Pick manually</h2>
        <p style={{ color: "var(--bw-dim)", fontSize: 13 }}>Loading detected grid intersections…</p>
      </div>
    );
  }
  const [w, h] = gp.page_size;
  const labels = picks.length
    ? picks.map((k) => `${k.mark} · ${k.label}`).join("   ·   ")
    : "Click two intersections — first snaps to BM-1, second to BM-2.";
  const ready = picks.length === 2;
  return (
    <div className="bw-card">
      <h2>
        Pick manually · {gp.sheet_number} (page {gp.page_index + 1})
      </h2>
      <p style={{ color: "var(--bw-dim)", fontSize: 13 }}>
        {(gp.points || []).length} labeled intersections detected — clicks snap to the nearest. Evidence crops +
        approval gate are identical to auto-propose.
      </p>
      <div className="bw-pick" style={{ aspectRatio: `${w}/${h}` }}>
        <img src={tokenized(`/api/sheets/${encodeURIComponent(gp.sheet_number)}/page.png?dpi=150`)} alt={gp.sheet_number} />
        <svg id="bm-pick-svg" viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" onClick={onPick}>
          {(gp.points || []).map((p) => {
            const picked = picks.find((k) => k.grid_id === p.id);
            const col = picked ? "var(--bw-signal)" : "var(--bw-dim)";
            return (
              <g key={p.id}>
                <circle cx={p.point.x} cy={p.point.y} r={picked ? 10 : 5} fill="none" stroke={col} strokeWidth={picked ? 3 : 1.5} />
                {picked && (
                  <text x={p.point.x + 14} y={p.point.y - 12} fill="var(--bw-signal)" fontSize={20} fontFamily="'IBM Plex Mono',monospace">
                    {picked.mark}
                  </text>
                )}
              </g>
            );
          })}
        </svg>
      </div>
      <p className="mono" style={{ color: "var(--bw-signal)", fontSize: 13, margin: "10px 0 0" }}>
        {labels}
      </p>
      <div className="bw-actions">
        <button className="bw-btn" disabled={!ready} onClick={onPropose}>
          ◎ Propose these 2
        </button>
        <button className="resolve-btn resolve-reject" onClick={onClear}>
          Clear
        </button>
        <button className="resolve-btn resolve-reject" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </div>
  );
}

/** Forces a re-render whenever wizardStore's shared state changes -- needed
 *  because WizardRail/WizardCards/WizardLog are three separate React roots
 *  (three separate DOM containers) that must all stay in sync. */
function useWizardSubscription(): void {
  const [, setTick] = useState(0);
  useEffect(() => {
    wizardStoreEnsure();
    return subscribeWizard(() => setTick((t) => t + 1));
  }, []);
}
function wizardStoreEnsure() {
  ensureLiveSubscription();
}

export function WizardRail() {
  useWizardSubscription();
  return <Rail state={wizardState.wf?.state || "idle"} />;
}

export function WizardLog() {
  useWizardSubscription();
  const logBoxRef = useRef<HTMLDivElement>(null);
  const logs = wizardState.logs;
  useEffect(() => {
    if (logBoxRef.current) logBoxRef.current.scrollTop = logBoxRef.current.scrollHeight;
  }, [logs]);
  return (
    <div ref={logBoxRef}>
      {logs.length === 0 ? (
        <div style={{ opacity: 0.5 }}>— waiting for events —</div>
      ) : (
        logs.map((e, i) => (
          <div className={`ev-${e.kind}`} key={i}>
            {new Date(e.ts * 1000).toLocaleTimeString()} · {e.message}
          </div>
        ))
      )}
    </div>
  );
}

export function WizardCards() {
  useWizardSubscription();
  const [rejectComment, setRejectComment] = useState("");
  const { wf, pickOn, gp, picks, revitStatus } = wizardState;
  const state = wf?.state || "idle";
  const needsRevitPill = state === "awaiting_revit" || state === "placing_markers";

  useEffect(() => {
    if (needsRevitPill) maybeCheckRevit();
  }, [needsRevitPill, wf]);

  const onPickClick = (ev: React.MouseEvent<SVGSVGElement>) => {
    if (!gp || picks.length >= 2) return;
    const svg = ev.currentTarget;
    const pt = svg.createSVGPoint();
    pt.x = ev.clientX;
    pt.y = ev.clientY;
    const loc = pt.matrixTransform(svg.getScreenCTM()!.inverse());
    let best: (typeof gp.points)[number] | null = null;
    let bd = Infinity;
    for (const p of gp.points || []) {
      const d = Math.hypot(p.point.x - loc.x, p.point.y - loc.y);
      if (d < bd) {
        bd = d;
        best = p;
      }
    }
    if (!best) return;
    if (picks.some((k) => k.grid_id === best!.id)) {
      toast("Already picked that intersection.", true);
      return;
    }
    setPicks([...picks, { grid_id: best!.id, mark: picks.length === 0 ? "BM-1" : "BM-2", label: best!.label }]);
  };

  const doReject = () => {
    action("/api/benchmark-workflow/approve", {
      approved: false,
      comment: rejectComment.trim() || "Rejected from wizard.",
      actor: "human_ui",
    });
    setRejectComment("");
  };
  const doApprove = () => {
    action("/api/benchmark-workflow/approve", { approved: true, comment: rejectComment.trim(), actor: "human_ui" });
    setRejectComment("");
  };

  const failNote = state === "failed" ? [...(wf?.history || [])].reverse().find((h) => h.to === "failed")?.note : null;
  const doneEntry = state === "done" ? [...(wf?.history || [])].reverse().find((h) => h.to === "done") : null;
  const verification =
    wf?.verification || [...(wf?.history || [])].reverse().find((h: HistoryEntry) => h.to === "awaiting_revit")?.payload?.verification;

  return (
    <>
      <div id="bm-cards-inner">
        {["idle", "failed", "done"].includes(state) &&
          (pickOn ? (
            <PickCard gp={gp} picks={picks} onPick={onPickClick} onClear={() => setPicks([])} onCancel={() => { setPickOn(false); setPicks([]); }} onPropose={() => {
              const points = picks.map((k) => ({ grid_id: k.grid_id, mark: k.mark }));
              setPickOn(false);
              setPicks([]);
              action("/api/benchmark-workflow/propose", { points, actor: "human_ui" });
            }} />
          ) : (
            <div className="bw-card">
              <h2>Start</h2>
              {state === "failed" && (
                <p style={{ color: "var(--bw-markup)" }} className="mono">
                  Run failed: {failNote || ""}
                </p>
              )}
              {state === "done" && (
                <p style={{ color: "var(--bw-signal)" }} className="mono">
                  Calibration is benchmark-verified. Re-run any time.
                </p>
              )}
              <p style={{ color: "var(--bw-dim)", fontSize: 13 }}>
                Scans the plan sheet for labeled grid intersections and proposes the two with maximum diagonal
                separation. No transform needed — works on unregistered projects.
              </p>
              <div className="bw-actions">
                <button className="bw-btn" onClick={() => action("/api/benchmark-workflow/propose", { actor: "human_ui" })}>
                  ◎ Propose benchmarks
                </button>
                <button className="bw-btn" onClick={startPick}>
                  ✎ Pick manually
                </button>
              </div>
            </div>
          ))}
        {wf?.proposal && state !== "idle" && <ProposalCard p={wf.proposal} />}
        {state === "awaiting_pdf_approval" && (
          <div className="bw-card">
            <h2>Approval · PDF stamps</h2>
            <p style={{ color: "var(--bw-dim)", fontSize: 13 }}>
              Approve to let the agent stamp BM-1/BM-2 circle annotations at these exact points (original PDF backed
              up first).
            </p>
            <input
              className="bw-reject-comment"
              placeholder="reason if rejecting (audit-logged, optional)"
              value={rejectComment}
              onChange={(ev) => setRejectComment(ev.target.value)}
            />
            <div className="bw-actions">
              <button className="resolve-btn resolve-accept" onClick={doApprove}>
                ✓ Approve — stamp the PDF
              </button>
              <button className="resolve-btn resolve-reject" onClick={doReject}>
                ✕ Reject
              </button>
            </div>
          </div>
        )}
        {state === "stamping" && (
          <div className="bw-card">
            <h2>Stamp PDF</h2>
            <p style={{ color: "var(--bw-dim)", fontSize: 13 }}>
              Writes BM-1/BM-2 circle annotations at the approved points (PDF backed up first), then reads them back
              to verify before advancing.
            </p>
            <div className="bw-actions">
              <button className="bw-btn" onClick={() => action("/api/benchmark-workflow/stamp", { actor: "human_ui" })}>
                ◎ Stamp PDF
              </button>
            </div>
            {verification && <VerificationTable v={verification} />}
          </div>
        )}
        {state === "awaiting_revit" && (
          <div className="bw-card">
            <h2>Connect Revit</h2>
            <p style={{ color: "var(--bw-dim)", fontSize: 13 }}>
              The backend drives Revit directly through the Nonica MCP bridge — open Revit with the model and enable
              the NonicaTab PRO AI Connector.
            </p>
            <RevitPill status={revitStatus} />
            <div className="bw-actions">
              <button className="bw-btn" disabled={!revitStatus?.connected} onClick={() => action("/api/benchmark-workflow/advance", { step: "revit_connected", actor: "human_ui" })}>
                Revit connected — continue
              </button>
            </div>
          </div>
        )}
        {state === "placing_markers" && (
          <div className="bw-card">
            <h2>Place markers in Revit</h2>
            <p style={{ color: "var(--bw-dim)", fontSize: 13 }}>
              The backend copies the benchmark family to each approved point, sets its Mark, and reads the placement
              back — no Claude in the loop. Server-verified before advancing.
            </p>
            <RevitPill status={revitStatus} />
            <div className="bw-actions">
              <button className="bw-btn" onClick={() => action("/api/benchmark-workflow/place-markers", { actor: "human_ui" })}>
                ◆ Place BM-1 / BM-2
              </button>
            </div>
          </div>
        )}
        {state === "awaiting_revit_approval" && wf && (
          <>
            <ReadbackCard wf={wf} />
            <div className="bw-card">
              <h2>Approval · Revit markers</h2>
              <p style={{ color: "var(--bw-dim)", fontSize: 13 }}>
                Markers are placed session-only. Approve if read-back matches intended; then save the model and
                re-export.
              </p>
              <input
                className="bw-reject-comment"
                placeholder="reason if rejecting (audit-logged, optional)"
                value={rejectComment}
                onChange={(ev) => setRejectComment(ev.target.value)}
              />
              <div className="bw-actions">
                <button className="resolve-btn resolve-accept" onClick={doApprove}>
                  ✓ Approve placement
                </button>
                <button className="resolve-btn resolve-reject" onClick={doReject}>
                  ✕ Reject
                </button>
              </div>
            </div>
          </>
        )}
        {state === "awaiting_export" && (
          <div className="bw-card">
            <h2>Waiting for fresh export</h2>
            <div className="bw-wait">
              Save the Revit model (Ctrl+S), run the Livio exporter — dialog must show "Benchmarks: 2" — then upload
              the JSON. This auto-detects and advances once both benchmarks are present; no manual step needed.
            </div>
          </div>
        )}
        {state === "calibrating" && (
          <div className="bw-card">
            <h2>Calibrating</h2>
            <div className="bw-wait">Extract stamps → gated 2-point solve. Saved only if quality gates pass.</div>
          </div>
        )}
        {state === "done" && doneEntry?.payload && (
          <div className="bw-card">
            <h2>Calibration verified</h2>
            <p className="mono" style={{ color: "var(--bw-signal)" }}>
              source: {doneEntry.payload.calibration_source} · scale {doneEntry.payload.scale ?? "?"} pt/ft
            </p>
          </div>
        )}
      </div>
    </>
  );
}

/** Approval banner -- surfaced above #main so nobody has to know the wizard
 *  exists. "Approve to continue" text is asserted verbatim by
 *  tests/smoke.spec.js -- kept identical. Independently subscribed to the
 *  same SSE stream as Wizard (not the modal's state) so a proposal parked by
 *  an upload's auto-benchmark surfaces here even if the wizard was never
 *  opened -- matches the original's always-on module-scope subscription. */
export function WizardBanner() {
  const [wf, setWf] = useState<Workflow | null>(null);

  useEffect(() => {
    return onStep("benchmark_workflow", () => {
      api<Workflow>("/api/benchmark-workflow").then(setWf).catch(() => {});
    });
  }, []);

  const bms = wf?.proposal?.benchmarks || [];
  if (wf?.state !== "awaiting_pdf_approval" || bms.length < 2) return null;

  const approve = async () => {
    try {
      await api("/api/benchmark-workflow/approve", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ approved: true, actor: "human_ui", comment: "Approved from banner." }),
      });
      setWf(null);
    } catch (e) {
      toast("Autopilot: " + (e as Error).message, true);
    }
  };

  return (
    <div
      className="glass"
      style={{
        margin: "8px 12px",
        padding: "10px 14px",
        display: "flex",
        gap: 12,
        alignItems: "center",
        flexWrap: "wrap",
        borderLeft: "3px solid var(--bw-signal, #22c55e)",
      }}
    >
      <span style={{ flex: 1, minWidth: 280 }}>
        The system picked two reference points on this sheet — <b>{bms[0].grid_label || bms[0].grid_id}</b> &amp;{" "}
        <b>{bms[1].grid_label || bms[1].grid_id}</b> — to line the drawing up with the Revit model. Approve to
        continue.
      </span>
      <button className="mini primary" onClick={approve}>
        ✓ Approve
      </button>
      <button className="mini" onClick={() => (document.getElementById("btn-autopilot") as HTMLElement)?.click()}>
        Review the points
      </button>
    </div>
  );
}
