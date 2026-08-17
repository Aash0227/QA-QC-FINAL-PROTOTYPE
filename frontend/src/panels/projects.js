/* panels/projects.js — the Project Manager overlay: create, list, update, delete.

   A project here is a workspace directory on the backend, not a row in a
   database. This panel is a thin renderer over /api/projects: it never derives
   a verdict, a count or a status of its own. Everything on a card came from the
   backend verbatim — the ring is drawn from counts.by_status, the status pill
   from the human-set manifest field. If a number looks wrong, the fix belongs
   in the pipeline, not here.

   Switching projects reloads the page on purpose. Every panel caches
   project-scoped state (store.elements, the 3D scene, the sheet raster cache),
   and a reload is the one swap path that cannot leave a stale pane behind. */

import { $, esc, toast, COL, RUN_STATUSES } from "../util.js";
import { api } from "../api.js";

let projects = [];
let editing = null;          // slug currently in inline-edit mode
let lastFocus = null;        // element focus returns to when the overlay closes

/* ---------------- formatting ---------------- */

function fmtBytes(n) {
  if (!n) return "0 B";
  const u = ["B", "KB", "MB", "GB"];
  const i = Math.min(Math.floor(Math.log(n) / Math.log(1024)), u.length - 1);
  return `${(n / 1024 ** i).toFixed(i ? 1 : 0)} ${u[i]}`;
}

function fmtDate(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  return isNaN(d) ? "—" : d.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

/* ---------------- verdict ring ----------------
   One donut per project, segmented by the same statuses (and the same colours)
   the element list and table use, so the card reads as a summary of the screen
   behind it rather than a second opinion. */

const R = 26, CIRC = 2 * Math.PI * R;

function verdictRing(counts) {
  const total = counts?.total || 0;
  const by = counts?.by_status || {};
  const inner = total
    ? `${Math.round(100 * (by.MATCH || 0) / total)}%`
    : "—";
  let offset = 0;
  const segs = RUN_STATUSES
    .filter(s => by[s])
    .map(s => {
      const len = CIRC * by[s] / total;
      const seg = `<circle class="pm-seg" r="${R}" cx="32" cy="32" stroke="${COL[s] || "var(--dim)"}"
        stroke-dasharray="${len.toFixed(2)} ${(CIRC - len).toFixed(2)}"
        stroke-dashoffset="${(-offset).toFixed(2)}"><title>${esc(s)}: ${by[s]}</title></circle>`;
      offset += len;
      return seg;
    }).join("");

  return `<svg class="pm-ring" viewBox="0 0 64 64" role="img"
    aria-label="${total ? `${by.MATCH || 0} of ${total} elements verified` : "Not analysed yet"}">
    <g transform="rotate(-90 32 32)">
      <circle class="pm-seg pm-seg-bg" r="${R}" cx="32" cy="32"></circle>
      ${segs}
    </g>
    <text x="32" y="32" class="pm-ring-num">${inner}</text>
  </svg>`;
}

/* ---------------- cards ---------------- */

function facts(p) {
  const bits = [];
  if (p.sheet_count) bits.push(`${p.sheet_count} sheet${p.sheet_count === 1 ? "" : "s"}`);
  if (p.page_count) bits.push(`${p.page_count} pages`);
  if (p.counts?.total) bits.push(`${p.counts.total} elements`);
  // Inputs are stated positively AND negatively: a workspace with no Revit
  // export is a normal state that explains an all-PDF_ONLY result, and hiding
  // it would make that result look like a modelling problem.
  bits.push(p.has_pdf ? "PDF ✓" : "no PDF");
  bits.push(p.has_revit ? "Revit ✓" : "no Revit export");
  return bits.map(b => `<span class="pm-fact">${esc(b)}</span>`).join("");
}

function cardView(p) {
  const sub = [p.client, p.revision].filter(Boolean).map(esc).join(" · ");
  return `
    <div class="pm-card-hd">
      ${verdictRing(p.counts)}
      <div class="pm-card-id">
        <h3 title="${esc(p.display_name)}">${esc(p.display_name)}</h3>
        <div class="pm-sub">${sub || `<span class="pm-muted">no client or revision set</span>`}</div>
        <div class="pm-slug" title="workspace folder">${esc(p.slug)}</div>
      </div>
      <span class="pm-status pm-status-${esc(p.status)}">${esc(p.status)}</span>
    </div>
    <div class="pm-facts">${facts(p)}</div>
    <div class="pm-meta">Updated ${esc(fmtDate(p.updated_at))}</div>
    <div class="pm-actions">
      <button class="primary mini" data-act="open" ${p.active ? "disabled" : ""}>
        ${p.active ? "✓ Open now" : "Open"}</button>
      <button class="mini" data-act="edit">Edit</button>
      <span style="flex:1"></span>
      <button class="mini pm-danger" data-act="delete">Delete</button>
    </div>`;
}

function cardEdit(p) {
  return `
    <form class="pm-form" data-act="save">
      <label>Project name<input name="display_name" maxlength="120" value="${esc(p.display_name)}" required></label>
      <div class="pm-row">
        <label>Client<input name="client" maxlength="120" value="${esc(p.client || "")}"></label>
        <label>Revision<input name="revision" maxlength="60" value="${esc(p.revision || "")}"
          placeholder="e.g. PC2 2026-05-26"></label>
      </div>
      <label>Status
        <select name="status">
          <option value="active" ${p.status === "active" ? "selected" : ""}>active</option>
          <option value="archived" ${p.status === "archived" ? "selected" : ""}>archived</option>
        </select>
      </label>
      <label>Notes<textarea name="notes" rows="2" maxlength="2000">${esc(p.notes || "")}</textarea></label>
      <div class="pm-actions">
        <button type="submit" class="primary mini">Save</button>
        <button type="button" class="mini" data-act="cancel">Cancel</button>
        <span style="flex:1"></span>
        <span class="pm-muted">Renaming never touches results — the folder stays <code>${esc(p.slug)}</code>.</span>
      </div>
    </form>`;
}

function render() {
  const grid = $("#pm-grid");
  if (!grid) return;
  $("#pm-count").textContent = projects.length
    ? `${projects.length} project${projects.length === 1 ? "" : "s"}`
    : "none yet";

  grid.innerHTML = projects.map(p => `
    <article class="pm-card glass ${p.active ? "pm-active" : ""} ${p.status === "archived" ? "pm-archived" : ""}"
             data-slug="${esc(p.slug)}">
      ${editing === p.slug ? cardEdit(p) : cardView(p)}
    </article>`).join("")
    || `<p class="pm-empty">No projects yet. Create one to get started — you can add the drawing set now or later.</p>`;
}

/* ---------------- data ---------------- */

/* Placeholder cards while /api/projects is in flight. Uses the app's one
   skeleton pattern (components.css) rather than a spinner or a "loading…"
   string, so the grid does not reflow when the real cards land. */
function renderSkeleton() {
  $("#pm-grid").innerHTML = Array.from({ length: 3 }, () => `
    <article class="pm-card glass" aria-hidden="true">
      <div class="pm-card-hd">
        <div class="skeleton" style="width:56px;height:56px;border-radius:50%;flex:none"></div>
        <div class="pm-card-id">
          <div class="skeleton" style="height:15px;width:70%"></div>
          <div class="skeleton" style="height:12px;width:45%;margin-top:7px"></div>
        </div>
      </div>
      <div class="skeleton" style="height:20px;width:85%"></div>
      <div class="skeleton" style="height:28px;width:60%"></div>
    </article>`).join("");
  $("#pm-count").textContent = "loading…";
}

async function refresh({ skeleton = false } = {}) {
  if (skeleton) renderSkeleton();
  try {
    projects = (await api("/api/projects")).projects || [];
  } catch (e) {
    projects = [];
    toast("Could not load projects: " + e.message, true);
  }
  render();
}

/* ---------------- actions ---------------- */

async function openProject(slug) {
  try {
    await api("/api/projects/activate", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ slug }),
    });
    toast(`Opening ${slug}…`);
    setTimeout(() => location.reload(), 500);
  } catch (e) { toast("Could not open that project: " + e.message, true); }
}

async function saveProject(slug, form) {
  const payload = {};
  for (const k of ["display_name", "client", "revision", "status", "notes"]) {
    payload[k] = form.elements[k].value.trim() || null;
  }
  if (!payload.display_name) return toast("A project name is required.", true);
  try {
    await api(`/api/projects/${encodeURIComponent(slug)}`, {
      method: "PATCH", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    editing = null;
    await refresh();
    toast("Project details saved.");
  } catch (e) { toast("Save failed: " + e.message, true); }
}

/* Delete is gated on typing the folder name. The dialog quotes the real file
   count and size from GET /api/projects/{slug} rather than a generic warning:
   "this deletes 39 files (412 MB)" is a decision, "this cannot be undone" is
   a shrug. */
async function confirmDelete(slug) {
  const p = projects.find(x => x.slug === slug);
  let detail = {};
  try { detail = await api(`/api/projects/${encodeURIComponent(slug)}`); } catch { /* fall back to no numbers */ }

  const others = projects.filter(x => x.slug !== slug);
  if (p?.active && !others.length) {
    return toast("This is the only project — create another one before deleting it.", true);
  }

  const scale = detail.file_count
    ? `${detail.file_count} file${detail.file_count === 1 ? "" : "s"} (${fmtBytes(detail.size_bytes)})`
    : "this workspace";
  const switchNote = p?.active
    ? `<p class="pm-warn">This is the project you have open. Deleting it will switch you to
       <strong>${esc(others[0].display_name)}</strong> and reload.</p>` : "";

  $("#pm-confirm-body").innerHTML = `
    <h3>Delete “${esc(p?.display_name || slug)}”?</h3>
    <p>This permanently removes <strong>${esc(scale)}</strong> — the uploaded drawing set,
       the Revit export, every calibration, and all review comments and resolutions.</p>
    ${switchNote}
    <label>Type <code>${esc(slug)}</code> to confirm
      <input id="pm-confirm-input" autocomplete="off" spellcheck="false"></label>
    <div class="pm-actions">
      <button class="mini pm-danger" id="pm-confirm-go" disabled>Delete permanently</button>
      <button class="mini" id="pm-confirm-cancel">Cancel</button>
    </div>`;
  $("#pm-confirm").classList.add("open");

  const input = $("#pm-confirm-input");
  const go = $("#pm-confirm-go");
  input.focus();
  input.oninput = () => { go.disabled = input.value.trim() !== slug; };
  $("#pm-confirm-cancel").onclick = closeConfirm;
  go.onclick = async () => {
    go.disabled = true;
    try {
      // The backend refuses to delete the active workspace (409) because live
      // requests may still be bound to it. Switch away first, then delete.
      const wasActive = p?.active;
      if (wasActive) {
        await api("/api/projects/activate", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ slug: others[0].slug }),
        });
      }
      await api(`/api/projects/${encodeURIComponent(slug)}`, { method: "DELETE" });
      closeConfirm();
      toast(`Deleted ${slug}.`);
      if (wasActive) return setTimeout(() => location.reload(), 600);
      await refresh();
    } catch (e) {
      go.disabled = false;
      toast("Delete failed: " + e.message, true);
    }
  };
}

function closeConfirm() {
  $("#pm-confirm").classList.remove("open");
  $("#pm-confirm-body").innerHTML = "";
}

/* ---------------- create ---------------- */

function newForm() {
  $("#pm-form-slot").innerHTML = `
    <form class="pm-card glass pm-newform" id="pm-new-form">
      <h3>New project</h3>
      <p class="pm-muted">Name it now and add the drawing set whenever you have it —
        an empty project is a valid state, not a half-finished one.</p>
      <label>Project name<input name="name" maxlength="120" required autofocus
        placeholder="e.g. My Project"></label>
      <div class="pm-row">
        <label>Client<input name="client" maxlength="120" placeholder="optional"></label>
        <label>Revision<input name="revision" maxlength="60" placeholder="optional, e.g. PC2 2026-05-26"></label>
      </div>
      <label>Drawing set (PDF)<input name="pdf" type="file" accept=".pdf" class="pm-file"></label>
      <div class="pm-actions">
        <button type="submit" class="primary mini">Create project</button>
        <button type="button" class="mini" id="pm-new-cancel">Cancel</button>
        <span class="pm-status-msg" id="pm-new-msg"></span>
      </div>
    </form>`;
  const form = $("#pm-new-form");
  $("#pm-new-cancel").onclick = () => { $("#pm-form-slot").innerHTML = ""; };
  form.onsubmit = async ev => {
    ev.preventDefault();
    const btn = form.querySelector("button[type=submit]");
    const msg = $("#pm-new-msg");
    const name = form.elements.name.value.trim();
    if (!name) return toast("A project name is required.", true);
    btn.disabled = true;
    try {
      msg.textContent = "Creating workspace…";
      const created = await api("/api/projects", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name,
          client: form.elements.client.value.trim() || null,
          revision: form.elements.revision.value.trim() || null,
        }),
      });
      // Upload is a separate call so a failed PDF never orphans the project:
      // the workspace already exists and the file can be added again later.
      const file = form.elements.pdf.files[0];
      if (file) {
        msg.textContent = `Uploading ${file.name}…`;
        const fd = new FormData();
        fd.append("pdf", file);
        await api(`/api/upload?project=${encodeURIComponent(created.slug)}`, { method: "POST", body: fd });
      }
      $("#pm-form-slot").innerHTML = "";
      await refresh();
      toast(file ? `Created ${created.slug} and uploaded ${file.name}.` : `Created ${created.slug}.`);
    } catch (e) {
      btn.disabled = false;
      msg.textContent = "";
      toast("Could not create the project: " + e.message, true);
    }
  };
}

/* ---------------- open / close ---------------- */

export async function openProjects() {
  lastFocus = document.activeElement;
  const ov = $("#projects");
  ov.classList.add("open");
  ov.setAttribute("aria-hidden", "false");
  $("#pm-form-slot").innerHTML = "";
  editing = null;
  await refresh({ skeleton: true });
  $("#pm-close").focus();
}

export function closeProjects() {
  const ov = $("#projects");
  ov.classList.remove("open");
  ov.setAttribute("aria-hidden", "true");
  closeConfirm();
  lastFocus?.focus?.();
}

/* ---------------- wiring ---------------- */

$("#pm-close").onclick = closeProjects;
$("#pm-new").onclick = newForm;

/* One delegated listener for every card: cards are re-rendered on each refresh,
   so per-card handlers would have to be re-bound every time. */
$("#pm-grid").addEventListener("click", ev => {
  const btn = ev.target.closest("[data-act]");
  if (!btn || btn.tagName === "FORM") return;
  const slug = btn.closest(".pm-card")?.dataset.slug;
  if (!slug) return;
  const act = btn.dataset.act;
  if (act === "open") openProject(slug);
  else if (act === "edit") { editing = slug; render(); }
  else if (act === "cancel") { editing = null; render(); }
  else if (act === "delete") confirmDelete(slug);
});

$("#pm-grid").addEventListener("submit", ev => {
  const form = ev.target.closest("form[data-act=save]");
  if (!form) return;
  ev.preventDefault();
  saveProject(form.closest(".pm-card").dataset.slug, form);
});

document.addEventListener("keydown", ev => {
  if (ev.key !== "Escape") return;
  if ($("#pm-confirm")?.classList.contains("open")) { ev.stopPropagation(); return closeConfirm(); }
  if ($("#projects")?.classList.contains("open")) { ev.stopPropagation(); closeProjects(); }
}, true);   // capture: close the overlay before app.js's Escape clears the selection
