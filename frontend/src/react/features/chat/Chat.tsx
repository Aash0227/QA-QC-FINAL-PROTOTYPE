import { useEffect, useRef, useState } from "react";

import { api } from "../../../api";
import { store, select, emit } from "../../../store";
import { $, COL } from "../../../util";

import type { ChatApiResponse, ChatBlock, ChatMsg, ChatUiAction } from "./types";

const COLORS = COL as Record<string, string>;

function StatusPill({ status, n }: { status: string; n?: number }) {
  const c = COLORS[status] || "var(--dim)";
  return (
    <span className="status-pill" style={{ background: `${c}22`, color: c }}>
      {status.replaceAll("_", " ")}
      {n != null ? ` · ${n}` : ""}
    </span>
  );
}

function BlockView({ b, onRowClick }: { b: ChatBlock; onRowClick: (id: string) => void }) {
  if (b.type === "count_card") {
    const cats = Object.entries(b.by_category || {});
    return (
      <div className="chat-card">
        <div className="chat-card-num">{b.total}</div>
        <div className="chat-card-lbl">{b.label || "elements"}</div>
        {cats.length > 0 && (
          <div className="chat-card-sub">
            {cats.map(([k, v], i) => (
              <span key={k}>
                {i > 0 && " · "}
                {k.replace("_", " ")} <b>{v}</b>
              </span>
            ))}
          </div>
        )}
      </div>
    );
  }
  if (b.type === "status_breakdown") {
    const entries = Object.entries(b.by_status || {});
    return (
      <div className="chat-block">
        {b.title && (
          <>
            <b>{b.title}</b>
            <br />
          </>
        )}
        {entries.length ? (
          entries.map(([s, n]) => <StatusPill key={s} status={s} n={n} />)
        ) : (
          <span style={{ color: "var(--dim)" }}>no data</span>
        )}
      </div>
    );
  }
  if (b.type === "table") {
    const cols = b.columns || [];
    const rows = b.rows || [];
    const more = b.total != null && b.shown != null && b.total > b.shown;
    return (
      <div className="chat-block">
        {b.title && <b>{b.title}</b>}
        <table className="chat-table">
          <thead>
            <tr>
              {cols.map((c) => (
                <th key={c}>{c}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr
                key={i}
                data-el={r.id ? String(r.id) : undefined}
                style={r.id ? { cursor: "pointer" } : undefined}
                onClick={r.id ? () => onRowClick(String(r.id)) : undefined}
              >
                {cols.map((c) => {
                  const v = r[c];
                  if (c === "status" && typeof v === "string") {
                    return (
                      <td key={c}>
                        <StatusPill status={v} />
                      </td>
                    );
                  }
                  return <td key={c}>{v == null ? "—" : String(v)}</td>;
                })}
              </tr>
            ))}
          </tbody>
        </table>
        {more && (
          <div className="chat-card-sub">
            Showing {b.shown} of {b.total}.
          </div>
        )}
      </div>
    );
  }
  return null;
}

function openPanel(panel: string) {
  if (panel === "table") {
    const p = $("#table-panel");
    if (p && p.classList.contains("hidden")) ($("#btn-table") as HTMLElement)?.click();
    return;
  }
  const btnId: Record<string, string> = { review: "#btn-review", runs: "#btn-runs", autopilot: "#btn-autopilot" };
  const sel = btnId[panel];
  const el = sel && $(sel);
  (el as HTMLElement)?.click();
}

/** React port of panels/chat.js -- the agentic chat drawer. Mounted into the
 *  existing #chat-log div; #chat-input/#chat-send stay static HTML siblings
 *  (outside this mount point) wired via a ref-free DOM effect below, since
 *  restructuring that markup wasn't necessary to move the actual rendering
 *  to React. initChat() is still exported from panels/chat.js (now a thin
 *  bridge) because panels/inspector.js's still-vanilla drawer manager calls
 *  it by name on first open -- see that file's header comment. */
export function Chat() {
  const [messages, setMessages] = useState<ChatMsg[]>([]);
  const historyRef = useRef<{ role: string; content: string }[]>([]);
  const startedRef = useRef(false);
  const logRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (logRef.current) logRef.current.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [messages]);

  const applyUiAction = (a: ChatUiAction) => {
    if (!a?.type) return;
    if (a.type === "select" && a.element_id) {
      select(a.element_id, "chat");
    } else if (a.type === "filter" && a.filters) {
      Object.assign(store.filters, { search: "", status: "", sheet: "" }, a.filters);
      const map: Record<string, string> = { search: "#search", status: "#status-filter", sheet: "#sheet-filter" };
      for (const [k, sel] of Object.entries(map)) {
        const inp = $(sel) as HTMLInputElement | HTMLSelectElement | null;
        if (inp) inp.value = (store.filters as Record<string, string>)[k] || "";
      }
      emit("refresh");
    } else if (a.type === "open_panel" && a.panel) {
      openPanel(a.panel);
    }
  };

  const send = async () => {
    const inp = $("#chat-input") as HTMLInputElement | null;
    const msg = (inp?.value || "").trim();
    if (!msg || !inp) return;
    inp.value = "";
    setMessages((m) => [...m, { kind: "text", role: "me", text: msg }, { kind: "typing" }]);
    historyRef.current.push({ role: "user", content: msg });
    try {
      const r = await api<ChatApiResponse>("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: msg, history: historyRef.current.slice(-8) }),
      });
      historyRef.current.push({ role: "assistant", content: r.reply || "" });
      setMessages((m) => [
        ...m.slice(0, -1),
        { kind: "text", role: "ai", text: r.reply || "" },
        ...(r.blocks?.length ? [{ kind: "blocks" as const, blocks: r.blocks }] : []),
      ]);
      for (const a of r.ui_actions || []) applyUiAction(a);
    } catch (e) {
      setMessages((m) => [...m.slice(0, -1), { kind: "text", role: "ai", text: "Something went wrong: " + (e as Error).message }]);
    }
  };

  useEffect(() => {
    const sendBtn = $("#chat-send");
    const input = $("#chat-input") as HTMLInputElement | null;
    const onClick = () => send();
    const onKeydown = (ev: KeyboardEvent) => {
      if (ev.key === "Enter") send();
    };
    sendBtn?.addEventListener("click", onClick);
    input?.addEventListener("keydown", onKeydown);
    return () => {
      sendBtn?.removeEventListener("click", onClick);
      input?.removeEventListener("keydown", onKeydown);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const onInit = () => {
      if (startedRef.current) return;
      startedRef.current = true;
      setMessages([
        {
          kind: "text",
          role: "ai",
          text: 'Hi — I\'m the QA-QC copilot. Ask me things like "how many holdowns?", "what\'s PDF-only on the foundation plan?", or "highlight H2". I can re-run extract/match/compare and remember client conventions ("HD3 means H3").',
        },
      ]);
      api<{ items?: { hint?: string; type?: string }[] }>("/api/teach/unrecognized")
        .then((r) => {
          if (r.items?.length) setMessages((m) => [...m, { kind: "unknown-card", items: r.items! }]);
        })
        .catch(() => {});
    };
    window.addEventListener("chat-init", onInit);
    return () => window.removeEventListener("chat-init", onInit);
  }, []);

  return (
    <div ref={logRef}>
      {messages.map((msg, i) => {
        if (msg.kind === "text") {
          return (
            <div className={`msg ${msg.role}`} key={i}>
              {msg.text}
            </div>
          );
        }
        if (msg.kind === "typing") {
          return (
            <div className="msg ai" key={i}>
              <span className="typing">
                <i></i>
                <i></i>
                <i></i>
              </span>
            </div>
          );
        }
        if (msg.kind === "blocks") {
          return (
            <div className="msg ai" key={i}>
              {msg.blocks.map((b, bi) => (
                <BlockView key={bi} b={b} onRowClick={(id) => select(id, "chat")} />
              ))}
            </div>
          );
        }
        if (msg.kind === "unknown-card") {
          return <UnknownCard key={i} items={msg.items} />;
        }
        return null;
      })}
    </div>
  );
}

function UnknownCard({ items }: { items: { hint?: string; type?: string }[] }) {
  const [show, setShow] = useState(false);
  return (
    <div className="msg ai">
      <b>
        {items.length} thing{items.length !== 1 ? "s" : ""} I couldn't recognize
      </b>{" "}
      in this drawing set.{" "}
      <button className="mini" onClick={() => setShow((s) => !s)}>
        {show ? "Hide details" : "Show details"}
      </button>
      {show && (
        <div className="unk-detail" style={{ marginTop: 8 }}>
          {items.map((it, i) => (
            <div className="unk-row" key={i}>
              ⚠ {it.hint || it.type}
            </div>
          ))}
        </div>
      )}
      <div className="chat-card-sub">Teach me one ("HD3 means H3") and I'll re-extract.</div>
    </div>
  );
}
