import { useEffect, useRef, useState } from "react";

import { api, setProjectHeader } from "../../../api";
import { toast } from "../../../util";

import type { ProjectDetail, ProjectSummary } from "./types";
import { VerdictRing } from "./VerdictRing";

/** React port of panels/projects.js (Stage 1 of the frontend migration).
 *
 *  A project here is a workspace directory on the backend, not a row in a
 *  database. This is a thin renderer over /api/projects: it never derives a
 *  verdict, a count or a status of its own — everything on a card comes from
 *  the backend verbatim.
 *
 *  Switching projects reloads the page on purpose (unchanged from the
 *  vanilla version): every panel caches project-scoped state, and a reload
 *  is the one swap path that cannot leave a stale pane behind.
 *
 *  Opened via the "open-project-manager" window event, dispatched by the
 *  vanilla app.js header button (#btn-projects) — see src/app.js and
 *  src/react-dashboard-entry.tsx. This is the bridge pattern used throughout
 *  the migration: vanilla code that hasn't moved yet can still trigger
 *  React features without either side importing the other's internals. */

function fmtBytes(n?: number): string {
  if (!n) return "0 B";
  const u = ["B", "KB", "MB", "GB"];
  const i = Math.min(Math.floor(Math.log(n) / Math.log(1024)), u.length - 1);
  return `${(n / 1024 ** i).toFixed(i ? 1 : 0)} ${u[i]}`;
}

function fmtDate(iso?: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return isNaN(d.getTime())
    ? "—"
    : d.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

function Facts({ p }: { p: ProjectSummary }) {
  const bits: string[] = [];
  if (p.sheet_count) bits.push(`${p.sheet_count} sheet${p.sheet_count === 1 ? "" : "s"}`);
  if (p.page_count) bits.push(`${p.page_count} pages`);
  if (p.counts?.total) bits.push(`${p.counts.total} elements`);
  bits.push(p.has_pdf ? "PDF ✓" : "no PDF");
  bits.push(p.has_revit ? "Revit ✓" : "no Revit export");
  return (
    <div className="pm-facts">
      {bits.map((b, i) => (
        <span className="pm-fact" key={i}>
          {b}
        </span>
      ))}
    </div>
  );
}

interface CardViewProps {
  p: ProjectSummary;
  onOpen: () => void;
  onEdit: () => void;
  onDelete: () => void;
  /** Re-fetch the list after an input is attached, so the card's
   *  "no Revit export" fact and the Open affordance update immediately. */
  onChanged: () => void;
}

function CardView({ p, onOpen, onEdit, onDelete, onChanged }: CardViewProps) {
  const sub = [p.client, p.revision].filter(Boolean).join(" · ");
  return (
    <>
      <div className="pm-card-hd">
        <VerdictRing counts={p.counts} />
        <div className="pm-card-id">
          <h3 title={p.display_name}>{p.display_name}</h3>
          <div className="pm-sub">
            {sub || <span className="pm-muted">no client or revision set</span>}
          </div>
          <div className="pm-slug" title="workspace folder">
            {p.slug}
          </div>
        </div>
        <span className={`pm-status pm-status-${p.status}`}>{p.status}</span>
      </div>
      <Facts p={p} />
      <div className="pm-meta">Updated {fmtDate(p.updated_at)}</div>
      <div className="pm-actions">
        <button className="primary mini" data-act="open" disabled={p.active} onClick={onOpen}>
          {p.active ? "✓ Open now" : "Open"}
        </button>
        <button className="mini" data-act="edit" onClick={onEdit}>
          Edit
        </button>
        {!p.has_pdf && <AttachInput slug={p.slug} kind="pdf" onDone={onChanged} />}
        {!p.has_revit && <AttachInput slug={p.slug} kind="revit_json" onDone={onChanged} />}
        <span style={{ flex: 1 }} />
        <button className="mini pm-danger" data-act="delete" onClick={onDelete}>
          Delete
        </button>
      </div>
    </>
  );
}

interface CardEditProps {
  p: ProjectSummary;
  onSave: (payload: Record<string, string | null>) => void;
  onCancel: () => void;
}

function CardEdit({ p, onSave, onCancel }: CardEditProps) {
  const submit = (ev: React.FormEvent<HTMLFormElement>) => {
    ev.preventDefault();
    const form = ev.currentTarget;
    const payload: Record<string, string | null> = {};
    for (const k of ["display_name", "client", "revision", "status", "notes"]) {
      const el = form.elements.namedItem(k) as HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement;
      payload[k] = el.value.trim() || null;
    }
    if (!payload.display_name) return toast("A project name is required.", true);
    onSave(payload);
  };

  return (
    <form className="pm-form" data-act="save" onSubmit={submit}>
      <label>
        Project name
        <input name="display_name" maxLength={120} defaultValue={p.display_name} required />
      </label>
      <div className="pm-row">
        <label>
          Client
          <input name="client" maxLength={120} defaultValue={p.client || ""} />
        </label>
        <label>
          Revision
          <input
            name="revision"
            maxLength={60}
            defaultValue={p.revision || ""}
            placeholder="e.g. PC2 2026-05-26"
          />
        </label>
      </div>
      <label>
        Status
        <select name="status" defaultValue={p.status}>
          <option value="active">active</option>
          <option value="archived">archived</option>
        </select>
      </label>
      <label>
        Notes
        <textarea name="notes" rows={2} maxLength={2000} defaultValue={p.notes || ""} />
      </label>
      <div className="pm-actions">
        <button type="submit" className="primary mini">
          Save
        </button>
        <button type="button" className="mini" data-act="cancel" onClick={onCancel}>
          Cancel
        </button>
        <span style={{ flex: 1 }} />
        <span className="pm-muted">
          Renaming never touches results — the folder stays <code>{p.slug}</code>.
        </span>
      </div>
    </form>
  );
}

function Skeleton() {
  return (
    <>
      {Array.from({ length: 3 }, (_, i) => (
        <article className="pm-card glass" aria-hidden="true" key={i}>
          <div className="pm-card-hd">
            <div className="skeleton" style={{ width: 56, height: 56, borderRadius: "50%", flex: "none" }} />
            <div className="pm-card-id">
              <div className="skeleton" style={{ height: 15, width: "70%" }} />
              <div className="skeleton" style={{ height: 12, width: "45%", marginTop: 7 }} />
            </div>
          </div>
          <div className="skeleton" style={{ height: 20, width: "85%" }} />
          <div className="skeleton" style={{ height: 28, width: "60%" }} />
        </article>
      ))}
    </>
  );
}

interface DeleteConfirmState {
  slug: string;
  displayName: string;
  scale: string;
  switchTo: string | null;
}

function DeleteConfirm({
  state,
  onCancel,
  onConfirm,
}: {
  state: DeleteConfirmState;
  onCancel: () => void;
  onConfirm: () => Promise<void>;
}) {
  const [value, setValue] = useState("");
  const [busy, setBusy] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  const go = async () => {
    setBusy(true);
    try {
      await onConfirm();
    } catch {
      setBusy(false);
    }
  };

  return (
    <div className="glass" id="pm-confirm-body">
      <h3>Delete "{state.displayName}"?</h3>
      <p>
        This permanently removes <strong>{state.scale}</strong> — the uploaded drawing set, the
        Revit export, every calibration, and all review comments and resolutions.
      </p>
      {state.switchTo && (
        <p className="pm-warn">
          This is the project you have open. Deleting it will switch you to{" "}
          <strong>{state.switchTo}</strong> and reload.
        </p>
      )}
      <label>
        Type <code>{state.slug}</code> to confirm
        <input
          id="pm-confirm-input"
          ref={inputRef}
          autoComplete="off"
          spellCheck={false}
          value={value}
          onChange={(e) => setValue(e.target.value)}
        />
      </label>
      <div className="pm-actions">
        <button
          className="mini pm-danger"
          id="pm-confirm-go"
          disabled={busy || value.trim() !== state.slug}
          onClick={go}
        >
          Delete permanently
        </button>
        <button className="mini" id="pm-confirm-cancel" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </div>
  );
}

/** Attach a missing input to an EXISTING project.
 *
 *  A project whose PDF is uploaded but whose Revit export is not can never
 *  produce a result: revit_convert, ransac, compare and match all skip, and
 *  the run still reports "completed". Before this, the only way out was to
 *  delete the project and recreate it, because nothing in the product could
 *  supply the missing file. POST /api/upload has always accepted both. */
function AttachInput({ slug, kind, onDone }: {
  slug: string;
  kind: "pdf" | "revit_json";
  onDone: () => void;
}) {
  const ref = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const label = kind === "pdf" ? "Add PDF" : "Add Revit export";

  const pick = async (ev: React.ChangeEvent<HTMLInputElement>) => {
    const f = ev.target.files?.[0];
    if (!f) return;
    setBusy(true);
    try {
      const fd = new FormData();
      fd.append(kind, f);
      await api(`/api/upload?project=${encodeURIComponent(slug)}`, { method: "POST", body: fd });
      toast(`Uploaded ${f.name} to ${slug}.`);
      onDone();
    } catch (e) {
      toast(`Could not upload ${f.name}: ` + (e as Error).message, true);
    } finally {
      setBusy(false);
      if (ref.current) ref.current.value = "";
    }
  };

  return (
    <>
      <button
        type="button"
        className="mini"
        data-act={kind === "pdf" ? "attach-pdf" : "attach-revit"}
        disabled={busy}
        onClick={() => ref.current?.click()}
      >
        {busy ? "Uploading…" : label}
      </button>
      <input
        ref={ref}
        type="file"
        accept={kind === "pdf" ? ".pdf" : ".json,application/json"}
        style={{ display: "none" }}
        onChange={pick}
      />
    </>
  );
}


function NewProjectForm({ onDone }: { onDone: () => void }) {
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");

  const submit = async (ev: React.FormEvent<HTMLFormElement>) => {
    ev.preventDefault();
    const form = ev.currentTarget;
    const name = (form.elements.namedItem("name") as HTMLInputElement).value.trim();
    if (!name) return toast("A project name is required.", true);
    const client = (form.elements.namedItem("client") as HTMLInputElement).value.trim() || null;
    const revision = (form.elements.namedItem("revision") as HTMLInputElement).value.trim() || null;
    const file = (form.elements.namedItem("pdf") as HTMLInputElement).files?.[0];
    const revitFile = (form.elements.namedItem("revit_json") as HTMLInputElement).files?.[0];
    setBusy(true);
    try {
      setMsg("Creating workspace…");
      const created = await api<{ slug: string }>("/api/projects", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, client, revision }),
      });
      // Both inputs go up in ONE request. POST /api/upload has always
      // accepted `revit_json` alongside `pdf`; the UI simply never sent it,
      // which is why a project could be created that could never produce a
      // result -- the pipeline needs the Revit export and nothing in the
      // product could supply it.
      if (file || revitFile) {
        const names = [file?.name, revitFile?.name].filter(Boolean).join(" + ");
        setMsg(`Uploading ${names}…`);
        const fd = new FormData();
        if (file) fd.append("pdf", file);
        if (revitFile) fd.append("revit_json", revitFile);
        await api(`/api/upload?project=${encodeURIComponent(created.slug)}`, { method: "POST", body: fd });
        toast(`Created ${created.slug} and uploaded ${names}.`);
      } else {
        toast(`Created ${created.slug}.`);
      }
      onDone();
    } catch (e) {
      setBusy(false);
      setMsg("");
      toast("Could not create the project: " + (e as Error).message, true);
    }
  };

  return (
    <form className="pm-card glass pm-newform" id="pm-new-form" onSubmit={submit}>
      <h3>New project</h3>
      <p className="pm-muted">
        Name it now and add the drawing set whenever you have it — an empty project is a valid
        state, not a half-finished one.
      </p>
      <label>
        Project name
        <input name="name" maxLength={120} required autoFocus placeholder="e.g. My Project" />
      </label>
      <div className="pm-row">
        <label>
          Client
          <input name="client" maxLength={120} placeholder="optional" />
        </label>
        <label>
          Revision
          <input name="revision" maxLength={60} placeholder="optional, e.g. PC2 2026-05-26" />
        </label>
      </div>
      <label>
        Drawing set (PDF)
        <input name="pdf" type="file" accept=".pdf" className="pm-file" />
      </label>
      <label>
        Revit export (JSON)
        <input name="revit_json" type="file" accept=".json,application/json" className="pm-file" />
      </label>
      <p className="pm-muted pm-hint">
        Both are needed before the pipeline can compare drawings to the model. Either can be
        added later from the project card.
      </p>
      <div className="pm-actions">
        <button type="submit" className="primary mini" disabled={busy}>
          Create project
        </button>
        <button type="button" className="mini" id="pm-new-cancel" onClick={onDone}>
          Cancel
        </button>
        <span className="pm-status-msg" id="pm-new-msg">{msg}</span>
      </div>
    </form>
  );
}

export function ProjectManager() {
  const [isOpen, setIsOpen] = useState(false);
  const [projects, setProjects] = useState<ProjectSummary[] | null>(null);
  const [editingSlug, setEditingSlug] = useState<string | null>(null);
  const [showNewForm, setShowNewForm] = useState(false);
  const [confirmState, setConfirmState] = useState<DeleteConfirmState | null>(null);
  const lastFocus = useRef<HTMLElement | null>(null);
  const closeBtnRef = useRef<HTMLButtonElement>(null);
  // requestDelete() awaits a fetch before setConfirmState() lands, so a key
  // handler reading confirmState (or even the DOM class it drives) can see a
  // stale "not open" view in that window. This ref flips true SYNCHRONOUSLY
  // the instant Delete is clicked -- no async gap -- and is kept in sync with
  // the real state afterward, so it's always an accurate "is a delete flow
  // pending or showing" signal for the keydown handler below.
  const confirmOpenRef = useRef(false);
  // Mirrors isOpen for the same reason: the keydown effect below is
  // registered once (empty deps, so its closure never goes stale on its
  // own), and reading a ref instead of the isOpen state directly keeps it
  // consistent with how confirmOpenRef must be read.
  const isOpenRef = useRef(false);

  useEffect(() => {
    confirmOpenRef.current = !!confirmState;
  }, [confirmState]);

  useEffect(() => {
    isOpenRef.current = isOpen;
  }, [isOpen]);

  const refresh = async () => {
    try {
      const r = await api<{ projects: ProjectSummary[] }>("/api/projects");
      setProjects(r.projects || []);
    } catch (e) {
      setProjects([]);
      toast("Could not load projects: " + (e as Error).message, true);
    }
  };

  useEffect(() => {
    const open = () => {
      lastFocus.current = document.activeElement as HTMLElement;
      setShowNewForm(false);
      setEditingSlug(null);
      setProjects(null); // triggers skeleton
      setIsOpen(true);
      refresh();
    };
    window.addEventListener("open-project-manager", open);
    return () => window.removeEventListener("open-project-manager", open);
  }, []);

  useEffect(() => {
    if (isOpen) closeBtnRef.current?.focus();
  }, [isOpen]);

  const close = () => {
    setIsOpen(false);
    setConfirmState(null);
    lastFocus.current?.focus?.();
  };

  // Capture phase, same priority as the vanilla version: confirm dialog closes
  // first, then the overlay, and this runs before app.js's own Escape handler
  // (which clears the element selection) via stopPropagation. Checks
  // confirmOpenRef (see its comment) rather than confirmState/isOpen
  // directly, since that ref is immune to the requestDelete() fetch-timing
  // gap that a state/DOM read would otherwise be racing.
  useEffect(() => {
    const onKeydown = (ev: KeyboardEvent) => {
      if (ev.key !== "Escape") return;
      if (confirmOpenRef.current) {
        ev.stopPropagation();
        confirmOpenRef.current = false;
        setConfirmState(null);
        return;
      }
      if (isOpenRef.current) {
        ev.stopPropagation();
        close();
      }
    };
    document.addEventListener("keydown", onKeydown, true);
    return () => document.removeEventListener("keydown", onKeydown, true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const openProject = async (slug: string) => {
    try {
      await api("/api/projects/activate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ slug }),
      });
      // Pin THIS tab to the project before reloading. Without it every
      // request fell through to the one global active_project.json, so two
      // tabs on different projects silently fought and the loser kept
      // rendering stale data. Setting it before the reload also removes the
      // race the 500ms delay was papering over: whatever fetches fire after
      // the reload are already scoped.
      setProjectHeader(slug);
      toast(`Opening ${slug}…`);
      setTimeout(() => location.reload(), 500);
    } catch (e) {
      toast("Could not open that project: " + (e as Error).message, true);
    }
  };

  const saveProject = async (slug: string, payload: Record<string, string | null>) => {
    try {
      await api(`/api/projects/${encodeURIComponent(slug)}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      setEditingSlug(null);
      await refresh();
      toast("Project details saved.");
    } catch (e) {
      toast("Save failed: " + (e as Error).message, true);
    }
  };

  const requestDelete = async (slug: string) => {
    confirmOpenRef.current = true; // set before the await below -- see the ref's comment
    const p = (projects || []).find((x) => x.slug === slug);
    let detail: ProjectDetail = {} as ProjectDetail;
    try {
      detail = await api<ProjectDetail>(`/api/projects/${encodeURIComponent(slug)}`);
    } catch {
      /* fall back to no numbers */
    }
    const others = (projects || []).filter((x) => x.slug !== slug);
    if (p?.active && !others.length) {
      confirmOpenRef.current = false;
      toast("This is the only project — create another one before deleting it.", true);
      return;
    }
    setConfirmState({
      slug,
      displayName: p?.display_name || slug,
      scale: detail.file_count
        ? `${detail.file_count} file${detail.file_count === 1 ? "" : "s"} (${fmtBytes(detail.size_bytes)})`
        : "this workspace",
      switchTo: p?.active ? others[0]?.display_name || null : null,
    });
  };

  const confirmDelete = async () => {
    if (!confirmState) return;
    const { slug } = confirmState;
    const p = (projects || []).find((x) => x.slug === slug);
    const others = (projects || []).filter((x) => x.slug !== slug);
    const wasActive = p?.active;
    try {
      if (wasActive) {
        await api("/api/projects/activate", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ slug: others[0].slug }),
        });
        // Deleting the open project moves this tab to the fallback; the
        // pinned slug must follow or the tab keeps requesting a project that
        // no longer exists.
        setProjectHeader(others[0].slug);
      }
      await api(`/api/projects/${encodeURIComponent(slug)}`, { method: "DELETE" });
      setConfirmState(null);
      toast(`Deleted ${slug}.`);
      if (wasActive) {
        setTimeout(() => location.reload(), 600);
        return;
      }
      await refresh();
    } catch (e) {
      toast("Delete failed: " + (e as Error).message, true);
      throw e; // lets DeleteConfirm re-enable its button
    }
  };

  // #projects is always in the DOM (never conditionally unmounted): app.css
  // gates visibility with `#projects{display:none} #projects.open{display:block}`,
  // the same show/hide-by-class contract the vanilla version used and that
  // tests/projects.spec.js asserts against directly.
  return (
    <div
      id="projects"
      className={isOpen ? "open" : ""}
      role="dialog"
      aria-modal="true"
      aria-labelledby="pm-title"
      aria-hidden={!isOpen}
    >
      <div id="pm-inner">
        <div className="glass pm-head">
          <h2 id="pm-title">Projects</h2>
          <span className="badge" id="pm-count">
            {projects === null
              ? "loading…"
              : projects.length
                ? `${projects.length} project${projects.length === 1 ? "" : "s"}`
                : "none yet"}
          </span>
          <span style={{ flex: 1 }} />
          <button className="primary" id="pm-new" onClick={() => setShowNewForm(true)}>
            ＋ New project
          </button>
          <button className="mini" id="pm-close" ref={closeBtnRef} onClick={close}>
            ✕ Close
          </button>
        </div>
        <div id="pm-form-slot">
          {showNewForm && <NewProjectForm onDone={() => { setShowNewForm(false); refresh(); }} />}
        </div>
        <div id="pm-grid">
          {projects === null ? (
            <Skeleton />
          ) : projects.length === 0 ? (
            <p className="pm-empty">
              No projects yet. Create one to get started — you can add the drawing set now or
              later.
            </p>
          ) : (
            projects.map((p) => (
              <article
                className={`pm-card glass ${p.active ? "pm-active" : ""} ${p.status === "archived" ? "pm-archived" : ""}`}
                data-slug={p.slug}
                key={p.slug}
              >
                {editingSlug === p.slug ? (
                  <CardEdit p={p} onSave={(payload) => saveProject(p.slug, payload)} onCancel={() => setEditingSlug(null)} />
                ) : (
                  <CardView
                    p={p}
                    onOpen={() => openProject(p.slug)}
                    onEdit={() => setEditingSlug(p.slug)}
                    onDelete={() => requestDelete(p.slug)}
                    onChanged={refresh}
                  />
                )}
              </article>
            ))
          )}
        </div>
      </div>
      <div id="pm-confirm" className={confirmState ? "open" : ""} role="alertdialog" aria-modal="true">
        {confirmState && (
          <DeleteConfirm state={confirmState} onCancel={() => setConfirmState(null)} onConfirm={confirmDelete} />
        )}
      </div>
    </div>
  );
}
