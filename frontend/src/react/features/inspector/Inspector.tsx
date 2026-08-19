import { useEffect, useRef, useState } from "react";

import { api } from "../../../api";
import { store, subscribe } from "../../../store";
import { CAT_LABEL, COL, rowVerdict } from "../../../util";
import { VerdictBadge } from "../verdict/VerdictBadge";

const LABELS = CAT_LABEL as Record<string, string>;
const COLORS = COL as Record<string, string>;

interface NearestCandidate {
  id?: string;
  revit_assembly_id?: string;
  pdf_holdown_id?: string;
  distance_pdf_points?: number;
  distance?: number;
}

interface ElementDetail {
  id: string;
  mark?: string;
  status: string;
  category: string;
  sheet?: string;
  pdf_point?: { x: number; y: number };
  distance_pdf_points?: number;
  revit_ref?: { kind: string; id: string };
  schedule_listed?: boolean;
  taught_by?: string;
  spec?: { row_text?: string } | Record<string, string>;
  reason?: string;
  nearest_revit_candidates?: NearestCandidate[];
  nearest_pdf_candidates?: NearestCandidate[];
}

/** "⟳ fetch live ID" button -- ported as real React state (simple enough:
 *  one API call + three render states) rather than reused via the vanilla
 *  island, unlike showInRevitBtn/whyBlock below which stay reused as-is. */
function LiveRevitId({ asmId }: { asmId: string }) {
  const [state, setState] = useState<"idle" | "loading" | { html: string }>("idle");

  const fetchId = async () => {
    setState("loading");
    try {
      const r = await api<{
        live?: { cached?: boolean; age_s?: number; connected?: boolean; element_ids: string[]; distance_ft: number };
        export?: { creation_element_ids?: string[] };
      }>(`/api/revit/element-ids/${encodeURIComponent(asmId)}`);
      const age = r.live?.cached ? ` · as of ${Math.round(r.live.age_s ?? 0)}s ago` : "";
      const exportId = r.export?.creation_element_ids?.[0] ?? "?";
      if (r.live?.connected && r.live.element_ids.length) {
        setState({
          html: `id:${r.live.element_ids[0]}|${r.live.distance_ft}|${age}`,
        });
      } else if (r.live?.connected) {
        setState({ html: `nolive|${exportId}|${age}` });
      } else {
        setState({ html: `off|${exportId}` });
      }
    } catch {
      setState({ html: "error" });
    }
  };

  if (state === "idle") {
    return (
      <button className="btn" style={{ fontSize: 11, padding: "2px 8px" }} onClick={fetchId}>
        ⟳ fetch live ID
      </button>
    );
  }
  if (state === "loading") {
    return <span style={{ color: "var(--dim)" }}>querying live model…</span>;
  }
  const [kind, a, b] = state.html.split("|");
  if (kind === "error") return <span style={{ color: "var(--revitonly)" }}>lookup failed</span>;
  if (kind === "off") return <span style={{ color: "var(--dim)" }}>connector off · export id: {a}</span>;
  if (kind === "nolive")
    return (
      <>
        <span style={{ color: "var(--locmis)" }}>no live device within 0.75 ft</span>{" "}
        <small style={{ color: "var(--dim)" }}>
          export id: {a}
          {b}
        </small>
      </>
    );
  const id = a;
  return (
    <>
      <b style={{ color: "var(--match)" }}>{id}</b>{" "}
      <button className="btn" style={{ fontSize: 11, padding: "2px 8px" }} onClick={() => navigator.clipboard.writeText(id)}>
        copy
      </button>{" "}
      <small style={{ color: "var(--dim)" }}>
        {b} ft from export pt · Select by ID in Revit
      </small>
    </>
  );
}

/** "Show in Revit" button + "Why this verdict?" block -- reused as-is from
 *  panels/revit_live.js (connector-status caching, lazy-loaded geometric
 *  analysis) via a small DOM-ref island rather than reimplemented, to avoid
 *  introducing new bugs into the review workflow under time pressure. */
function RevitLiveFragments({ el }: { el: ElementDetail }) {
  const showRef = useRef<HTMLSpanElement>(null);
  const whyRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    import("../../../panels/revit_live.js").then(({ showInRevitBtn, whyBlock, wireRevitLive }) => {
      if (showRef.current) {
        showRef.current.innerHTML = showInRevitBtn(el);
        wireRevitLive(showRef.current as unknown as Document);
      }
      if (whyRef.current) {
        whyRef.current.innerHTML = whyBlock(el);
        wireRevitLive(whyRef.current as unknown as Document);
      }
    });
  }, [el]);

  return (
    <>
      <b>Live model</b>
      <span ref={showRef} />
      <div ref={whyRef} style={{ gridColumn: "1 / -1" }} />
    </>
  );
}

/** React port of panels/inspector.js's renderInspector()/renderCC(). Mounted
 *  into the existing #insp-body / #cc-table containers. */
export function Inspector() {
  const [el, setEl] = useState<ElementDetail | null>(null);

  useEffect(() => {
    return subscribe("select", ({ element }: { element?: ElementDetail }) => {
      setEl(element || null);
    });
  }, []);

  if (!el) {
    return <span style={{ color: "var(--dim)" }}>Click any element in the list, drawing or 3D model.</span>;
  }

  const spec = el.spec ? ((el.spec as { row_text?: string }).row_text || Object.values(el.spec).join(" · ")) : "—";
  const near = (el.nearest_revit_candidates || el.nearest_pdf_candidates || []).slice(0, 3);

  return (
    <>
      <h3 style={{ margin: 0, display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
        {el.mark ?? ""}{" "}
        {/* The inspector is where a reviewer decides. It leads with the same
            verdict the list and the table show, then keeps the internal
            engine status beside it as supporting detail -- the evidence
            behind the answer is never hidden, it is just no longer first. */}
        <VerdictBadge verdict={rowVerdict(el)} />
        <span className="status-pill"
              style={{ background: `${COLORS[el.status]}22`, color: COLORS[el.status] }}>
          {el.status.replaceAll("_", " ")}
        </span>
      </h3>
      <div className="kv">
        <b>ID</b>
        <span style={{ wordBreak: "break-all" }}>{el.id}</span>
        <b>Category</b>
        <span>{LABELS[el.category] || el.category}</span>
        <b>Sheet</b>
        <span>{el.sheet || "—"}</span>
        <b>PDF point</b>
        <span>{el.pdf_point ? `(${el.pdf_point.x.toFixed(1)}, ${el.pdf_point.y.toFixed(1)}) pt` : "—"}</span>
        <b>Distance</b>
        <span>{el.distance_pdf_points != null ? `${el.distance_pdf_points} pt` : "—"}</span>
        <b>Revit ref</b>
        <span style={{ wordBreak: "break-all" }}>
          {el.revit_ref ? `${el.revit_ref.kind} · ${el.revit_ref.id}` : "none"}
        </span>
        {el.revit_ref?.kind === "holdown_assembly" && (
          <>
            <b>Revit ID</b>
            <span id="insp-revit-id">
              <LiveRevitId asmId={el.revit_ref.id} />
            </span>
            <RevitLiveFragments el={el} />
          </>
        )}
        <b>In schedule</b>
        <span>{el.schedule_listed ? "yes" : "NO"}</span>
        {el.taught_by && (
          <>
            <b>Taught</b>
            <span>🧠 rule {el.taught_by}</span>
          </>
        )}
        <b>Spec</b>
        <span>{spec}</span>
        <b>Reason</b>
        <span>{el.reason || "—"}</span>
      </div>
      {near.length > 0 && (
        <div style={{ marginTop: 10 }}>
          <b style={{ color: "var(--dim)" }}>Nearest candidates</b>
          {near.map((n, i) => (
            <div style={{ color: "var(--dim)" }} key={i}>
              ↳ {n.id || n.revit_assembly_id || n.pdf_holdown_id || "?"} ·{" "}
              {n.distance_pdf_points ?? n.distance ?? "?"} pt
            </div>
          ))}
        </div>
      )}
    </>
  );
}

interface CcRow {
  category: string;
  mark: string;
  plan_count: number;
  schedule_listed: boolean;
}

/** React port of panels/inspector.js's renderCC(). Mounted into #cc-table. */
export function CountConsistency() {
  const [rows, setRows] = useState<CcRow[]>([]);

  useEffect(() => {
    const refresh = () => {
      const activeSheet = store.activeSheet as unknown as string;
      const r = ((store.cc as Record<string, CcRow[]>)[activeSheet] || []).filter(
        (row) => row.category !== "wall_type",
      );
      setRows(r);
    };
    refresh();
    return subscribe("select", refresh);
  }, []);

  return (
    <>
      <tr>
        <th>Cat</th>
        <th>Mark</th>
        <th>Plan</th>
        <th>Sched</th>
      </tr>
      {rows.map((r, i) => (
        <tr key={i}>
          <td>{r.category.replace("_", " ")}</td>
          <td>{r.mark}</td>
          <td>{r.plan_count}</td>
          <td style={{ color: r.schedule_listed ? "var(--match)" : "var(--revitonly)" }}>
            {r.schedule_listed ? "✓" : "MISSING"}
          </td>
        </tr>
      ))}
    </>
  );
}
