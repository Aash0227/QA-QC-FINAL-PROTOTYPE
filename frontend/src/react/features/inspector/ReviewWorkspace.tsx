import { useEffect, useRef, useState } from "react";

import { api } from "../../../api";
import { select } from "../../../store";
import { toast } from "../../../util";

interface ReviewElement {
  id: string;
  mark?: string;
  category: string;
  sheet?: string;
  status: string;
  distance_pdf_points?: number;
  reason?: string;
  resolution?: { action: string; author?: string; comment?: string; original_status: string; distance_ft?: number };
}
interface Comment {
  author: string;
  comment: string;
  ai_reply?: string;
  derived_rule_id?: string;
  derived_rule_kind?: string;
}
interface ReviewItem {
  element: ReviewElement;
  disposition?: string;
  comments: Comment[];
}
interface ReviewQueue {
  reviewed: number;
  total: number;
  items: ReviewItem[];
}

let queueCache: { promise: Promise<ReviewQueue>; at: number } | null = null;
function fetchQueue(): Promise<ReviewQueue> {
  if (queueCache && Date.now() - queueCache.at < 10000) return queueCache.promise;
  const promise = api<ReviewQueue>("/api/review/queue").catch((e) => {
    queueCache = null;
    throw e;
  });
  queueCache = { promise, at: Date.now() };
  return promise;
}

function setRevCount(n: number) {
  const el = document.getElementById("rev-count");
  if (el) el.textContent = String(n);
}

// Boot badge — shares fetchQueue() with the workspace so a boot followed by
// opening the drawer doesn't hit /api/review/queue twice.
fetchQueue()
  .then((q) => setRevCount(q.total - q.reviewed))
  .catch(() => {});

function QueueList({ queue, onOpen }: { queue: ReviewQueue; onOpen: (i: number) => void }) {
  if (!queue.items.length) {
    return <span style={{ color: "var(--dim)" }}>Nothing needs review — no LOCATION_MISMATCH or NEEDS_REVIEW elements. 🎉</span>;
  }
  return (
    <div>
      {queue.items.map((it, i) => {
        const e = it.element;
        const d = e.distance_pdf_points ? ` · ${e.distance_pdf_points.toFixed(1)}pt off` : "";
        return (
          <div className="row" style={{ cursor: "pointer" }} key={i} onClick={() => onOpen(i)}>
            <b>{e.mark || "?"}</b> {e.category.replace("_", " ")} · {e.sheet || "—"} ·{" "}
            <span style={{ color: e.status === "LOCATION_MISMATCH" ? "var(--warn)" : "#94a3b8" }}>{e.status}</span>
            {d}
            {it.disposition && <span className="badge"> ✓ {it.disposition}</span>}
            {it.comments.length > 0 && ` · 💬${it.comments.length}`}
          </div>
        );
      })}
    </div>
  );
}

function AiAnalysis({ e }: { e: ReviewElement }) {
  const [html, setHtml] = useState<string | null>(null);

  useEffect(() => {
    if (e.resolution) return;
    let live = true;
    api<{
      analysis_available: boolean;
      finding?: string;
      distance_ft?: number;
      direction?: string;
      systematic?: boolean;
      aligned_peers?: number;
      peer_count?: number;
      sheets?: string[];
      note?: string;
    }>(`/api/review/${encodeURIComponent(e.id)}/analysis`)
      .then((a) => {
        if (!live) return;
        setHtml(
          a.analysis_available
            ? `<b class="sys">🤖 AI analysis (deterministic)</b><br>${a.finding}
               <div style="margin-top:6px;color:var(--dim)">offset ${a.distance_ft} ft ${a.direction}
                 · ${a.systematic ? `systematic (${a.aligned_peers}/${a.peer_count} peers move together)` : "isolated"}
                 · sheets: ${(a.sheets || []).join(", ")}</div>
               <div style="margin-top:6px;color:#94a3b8">Add your reasoning below — the AI will check it against these numbers, then you accept or reject.</div>`
            : a.note || "No analysis for this element.",
        );
      })
      .catch(() => setHtml(""));
    return () => {
      live = false;
    };
  }, [e.id, e.resolution]);

  if (e.resolution) {
    return (
      <>
        <span className="resolved-chip">
          ✓ {e.resolution.action === "accept" ? "Accepted as MATCH" : "Rejected"} by {e.resolution.author || "reviewer"}
        </span>
        <div style={{ fontSize: 11, color: "var(--dim)", marginTop: 4 }}>
          {e.resolution.comment || ""} · was {e.resolution.original_status} ({e.resolution.distance_ft ?? "?"} ft)
        </div>
      </>
    );
  }
  if (html === null) return <div className="ai-card">🤖 analyzing…</div>;
  if (!html) return null;
  return <div className="ai-card" dangerouslySetInnerHTML={{ __html: html }} />;
}

function ItemDetail({
  item,
  onBack,
  onDispositioned,
}: {
  item: ReviewItem;
  onBack: () => void;
  onDispositioned: (d: string) => void;
}) {
  const e = item.element;
  const [comments, setComments] = useState(item.comments);
  const [commentText, setCommentText] = useState("");
  const [verdictHtml, setVerdictHtml] = useState<string | null>(null);
  const cropRef = useRef<HTMLImageElement>(null);
  const showRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    select(e.id, "review");
    import("../../../panels/revit_live.js").then(({ showInRevitBtn, wireRevitLive }) => {
      if (showRef.current) {
        showRef.current.innerHTML = showInRevitBtn(e);
        wireRevitLive(showRef.current as unknown as Document);
      }
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [e.id]);

  const dist = e.distance_pdf_points
    ? `The two positions are <b>${e.distance_pdf_points.toFixed(1)} pt apart</b> (MATCH needs ≤16pt). `
    : "";

  const disposition = async (disp: string) => {
    try {
      await api(`/api/review/${encodeURIComponent(e.id)}/disposition`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ disposition: disp }),
      });
      toast(`Marked ${e.mark} as ${disp}. Status stays honest — the punch list shows both.`);
      onDispositioned(disp);
    } catch (err) {
      toast((err as Error).message, true);
    }
  };

  const decide = async (action: "accept" | "reject", text: string) => {
    setVerdictHtml(`<div class="ai-card">applying…</div>`);
    try {
      const out = await api<{ updated_element_ids: string[] }>(`/api/review/${encodeURIComponent(e.id)}/resolve`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action, comment: text }),
      });
      toast(
        action === "accept"
          ? `✅ Accepted — ${out.updated_element_ids.length} appearance(s) now MATCH in the list, PDF and 3D. Rule saved to memory.`
          : "Rejected — stays a real mismatch on the punch list.",
      );
      // Original vanilla behavior: reload the whole app + reopen the review
      // drawer (a fresh queue after a resolution changes downstream statuses).
      const { loadAll } = await import("../../../app.js");
      await loadAll();
      window.dispatchEvent(new CustomEvent("open-review-drawer"));
    } catch (err) {
      toast("Evaluate failed: " + (err as Error).message, true);
    }
  };

  const send = async () => {
    const text = commentText.trim();
    if (!text) return;
    if (e.status === "LOCATION_MISMATCH" && !e.resolution) {
      setCommentText("");
      setVerdictHtml(`<div class="ai-card">🤖 checking your logic against the measurements…</div>`);
      try {
        const r = await api<{ verdict: { agrees: boolean | null; reasoning?: string } }>(
          `/api/review/${encodeURIComponent(e.id)}/evaluate`,
          { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ comment: text }) },
        );
        const v = r.verdict;
        setVerdictHtml(
          `<b class="sys">🤖 AI on your reasoning:</b> ${
            v.agrees === true ? "✅ consistent with the numbers" : v.agrees === false ? "⚠ tension with the numbers" : "ℹ"
          }<br>${v.reasoning || ""}`,
        );
        (window as any).__reviewDecide = (action: "accept" | "reject") => decide(action, text);
      } catch (err) {
        setVerdictHtml(null);
        toast("Evaluate failed: " + (err as Error).message, true);
      }
      return;
    }
    setCommentText("");
    try {
      const r = await api<{ comment: Comment }>(`/api/review/${encodeURIComponent(e.id)}/comment`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ comment: text }),
      });
      setComments((c) => [...c, r.comment]);
      if (r.comment.derived_rule_id && r.comment.derived_rule_kind !== "note")
        toast("🧠 Rule saved to global memory — re-run Extract to apply it (works on future projects too).");
    } catch (err) {
      toast("Comment failed: " + (err as Error).message, true);
    }
  };

  return (
    <div>
      <button className="mini" id="rev-back" onClick={onBack}>
        ← Back to queue
      </button>
      <div style={{ margin: "12px 0" }}>
        <b style={{ fontSize: 15 }}>
          {e.mark} · {e.status}
        </b>
        <br />
        <span style={{ color: "var(--dim)", fontSize: 12 }}>
          {e.category.replace("_", " ")} · sheet {e.sheet || "—"} · id {e.id}
        </span>
        <div style={{ marginTop: 8 }} ref={showRef} />
      </div>
      <div style={{ display: "flex", gap: 8, alignItems: "flex-start" }}>
        <div style={{ flex: 1 }}>
          <div style={{ fontSize: 11, color: "var(--dim)", marginBottom: 4 }}>
            PDF evidence — <span style={{ color: "#4ade80" }}>● PDF</span> vs{" "}
            <span style={{ color: "#f87171" }}>◌ Revit</span>
          </div>
          <img
            ref={cropRef}
            src={`/api/review/${encodeURIComponent(e.id)}/evidence.png?t=${Math.random()}`}
            style={{ width: "100%", borderRadius: 8, border: "1px solid #263349" }}
            onError={() => {
              if (cropRef.current) cropRef.current.style.display = "none";
            }}
          />
        </div>
      </div>
      <div style={{ margin: "10px 0", fontSize: 12, color: "#cbd5e1" }} dangerouslySetInnerHTML={{ __html: dist + (e.reason || "") }} />
      <AiAnalysis e={e} />
      {verdictHtml && (
        <div style={{ margin: "10px 0" }}>
          <div className="ai-card" dangerouslySetInnerHTML={{ __html: verdictHtml }} />
          {(window as any).__reviewDecide && !e.resolution && (
            <div className="resolve-row">
              <button className="resolve-btn resolve-accept" onClick={() => (window as any).__reviewDecide("accept")}>
                ✓ Accept — mark MATCH everywhere
              </button>
              <button className="resolve-btn resolve-reject" onClick={() => (window as any).__reviewDecide("reject")}>
                ✕ Reject — keep as mismatch
              </button>
            </div>
          )}
        </div>
      )}
      <div style={{ display: "flex", gap: 6, margin: "10px 0", flexWrap: "wrap" }}>
        <button className="mini" onClick={() => disposition("confirmed-issue")}>
          🔴 Confirmed issue
        </button>
        <button className="mini" onClick={() => disposition("false-alarm")}>
          🟢 False alarm
        </button>
        <button className="mini" onClick={() => disposition("fixed-in-model")}>
          🔧 Fixed in model
        </button>
      </div>
      <h4>Comments — teach the AI while you review</h4>
      <div>
        {comments.length ? (
          comments.map((c, i) => (
            <div style={{ margin: "8px 0", fontSize: 12 }} key={i}>
              <div>
                <b>{c.author}</b>: {c.comment}
              </div>
              <div style={{ color: "#7dd3fc", marginTop: 3 }}>
                🤖 {c.ai_reply || ""}
                {c.derived_rule_id && c.derived_rule_kind !== "note" && <span className="badge"> 🧠 rule saved to memory</span>}
              </div>
            </div>
          ))
        ) : (
          <span style={{ color: "var(--dim)", fontSize: 12 }}>No comments yet.</span>
        )}
      </div>
      <div style={{ display: "flex", gap: 6, marginTop: 8 }}>
        <input
          id="rev-comment"
          type="text"
          style={{ flex: 1 }}
          placeholder='e.g. "tag sits on a leader, real anchor is 2ft left"'
          value={commentText}
          onChange={(ev) => setCommentText(ev.target.value)}
          onKeyDown={(ev) => {
            if (ev.key === "Enter") send();
          }}
        />
        <button id="rev-send" className="primary mini" onClick={send}>
          Send
        </button>
      </div>
    </div>
  );
}

/** React port of panels/inspector.js's human review workspace
 *  (initReview/openReviewItem/renderThread/sendReviewComment). Mounted
 *  directly into #rev-body, replacing the old separate #rev-list/#rev-detail
 *  toggle-by-style.display with real component state (list vs detail view)
 *  -- this component renders #rev-back/#rev-comment/#rev-send itself as
 *  real JSX (same ids, for CSS/compatibility) rather than reusing static
 *  HTML siblings, since it owns the whole #rev-body subtree. */
export function ReviewWorkspace() {
  const [queue, setQueue] = useState<ReviewQueue | "loading" | "error">("loading");
  const [openIndex, setOpenIndex] = useState<number | null>(null);

  const load = () => {
    setQueue("loading");
    setOpenIndex(null);
    fetchQueue()
      .then((q) => {
        setQueue(q);
        setRevCount(q.total - q.reviewed);
        const progress = document.getElementById("rev-progress");
        if (progress) progress.textContent = `${q.reviewed} of ${q.total} reviewed`;
      })
      .catch(() => setQueue("error"));
  };

  useEffect(() => {
    load();
    window.addEventListener("open-review-drawer", load);
    return () => window.removeEventListener("open-review-drawer", load);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (queue === "loading") return null;
  if (queue === "error") return <span style={{ color: "var(--dim)" }}>Could not load the review queue.</span>;

  if (openIndex != null) {
    const item = queue.items[openIndex];
    return (
      <ItemDetail
        item={item}
        onBack={() => setOpenIndex(null)}
        onDispositioned={(d) => {
          const items = queue.items.slice();
          items[openIndex] = { ...items[openIndex], disposition: d };
          setQueue({ ...queue, items });
        }}
      />
    );
  }
  return <QueueList queue={queue} onOpen={setOpenIndex} />;
}
