/* panels/viewer3d.js — Three.js scene: walls, holdowns, framing, benchmarks,
   grids, the info-ball. Reacts to "select". */

import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { $, COL, toast, reduceMotion } from "../util.js";
import { store, select, subscribe } from "../store.js";
import { api } from "../api.js";
import { openDrawer } from "./inspector.js";


let three = null;

/* Hybrid load: the export SNAPSHOT renders immediately (fast, always there),
   then the LIVE model is fetched in the background and swapped in when Revit
   answers. Live-first would block the pane on a Nonica round trip that can
   take tens of seconds — or never come. */
export async function loadScene() {
  try { store.scene = await api("/api/scene3d"); build3D(); } catch { }
  loadLiveScene(false);
}

const LIVE_COL = { walls: "#8fa3bd", columns: "#64748b", connections: "#38bdf8" };

/* Live payload -> the SAME scene shape build3D already renders, so the camera,
   lights, picking, tooltip, isolate and legend code is reused untouched.
   ponytail: one converter beats a second renderer. */
function sceneFromLive(live) {
  const b = live.bounds || { min_x: 0, max_x: 1, min_y: 0, max_y: 1, min_z: 0 };
  const z0 = b.min_z || 0;
  const live_boxes = [], framing = [];
  for (const [cat, els] of Object.entries(live.categories || {})) {
    for (const e of els) {
      const [x0, y0, zlo, x1, y1, zhi] = e.bbox_ft;
      const c = [(x0 + x1) / 2, (y0 + y1) / 2, (zlo + zhi) / 2 - z0];
      const s = [Math.max(x1 - x0, .15), Math.max(y1 - y0, .15), Math.max(zhi - zlo, .15)];
      if (cat === "framing") { framing.push([c[0], c[1], c[2], s[0], s[1], s[2]]); continue; }
      live_boxes.push({ id: e.id, cat, status: e.status || null, assembly_id: e.assembly_id || null,
        center_ft: [c[0], c[1]], elevation_ft: c[2], size_ft: s });
    }
  }
  return { bounds: b, walls: [], holdowns: [], openings: [], grids: [],
    category_elements: [], benchmarks: [], framing, live_boxes,
    live: true, model_title: live.model_title, counts: live.counts,
    truncated: live.truncated || {}, status_joined: live.status_joined || 0 };
}

/* Fetch the live model and re-render. ``force`` busts the backend's 60s cache
   and reports failures out loud (it is a button press, not a page load). */
export async function loadLiveScene(force) {
  try {
    const live = force ? await api("/api/revit-live/refresh-3d", { method: "POST" })
                       : await api("/api/revit-live/scene");
    if (live && live.ok && live.bounds) {
      store.scene = sceneFromLive(live);
      build3D();
      if (force) toast(`Live model refreshed · ${live.model_title || "Revit"}`);
      return true;
    }
    if (force) toast(live?.reason || "Revit gave no live geometry.");
  } catch (e) {
    if (force) toast("Live model unavailable: " + e.message);
  }
  return false;
}

function makeLabelSprite(text) {
  const cv = document.createElement("canvas"); cv.width = 128; cv.height = 64;
  const ctx = cv.getContext("2d");
  ctx.font = "bold 44px sans-serif"; ctx.fillStyle = "#7da7d9";
  ctx.textAlign = "center"; ctx.textBaseline = "middle";
  ctx.fillText(text, 64, 32);
  const sp = new THREE.Sprite(new THREE.SpriteMaterial({ map: new THREE.CanvasTexture(cv), transparent: true, depthTest: false }));
  sp.scale.set(6, 3, 1);
  return sp;
}
let three3dState = null;   // {raf, renderer, scene} — dispose before rebuild
function build3D() {
  const sc = store.scene; if (!sc || !sc.bounds) return;
  const wrap = $("#three-wrap");
  if (three3dState) {     // kill old loop + free the GL context (leak fix)
    cancelAnimationFrame(three3dState.raf);
    three3dState.scene.traverse(o => {
      o.geometry?.dispose?.();
      (Array.isArray(o.material) ? o.material : [o.material]).forEach(m => m?.dispose?.());
    });
    three3dState.renderer.dispose();
    three3dState = null;
  }
  wrap.querySelectorAll("canvas").forEach(c => c.remove());
  const W = wrap.clientWidth || 600, H = wrap.clientHeight || 400;
  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
  renderer.setSize(W, H); renderer.setPixelRatio(devicePixelRatio);
  wrap.appendChild(renderer.domElement);
  const scene = new THREE.Scene();
  scene.fog = new THREE.Fog(0x080d18, 180, 520);
  const camera = new THREE.PerspectiveCamera(48, W / H, 0.1, 2000);
  const cx = (sc.bounds.min_x + sc.bounds.max_x) / 2, cy = (sc.bounds.min_y + sc.bounds.max_y) / 2;
  const span = Math.max(sc.bounds.max_x - sc.bounds.min_x, sc.bounds.max_y - sc.bounds.min_y);
  const HOME = { pos: new THREE.Vector3(span * .35, span * .72, span * .9), tgt: new THREE.Vector3(0, 4, 0) };
  camera.position.copy(HOME.pos);
  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true; controls.dampingFactor = .08; controls.maxDistance = span * 4;
  controls.target.copy(HOME.tgt);
  scene.add(new THREE.HemisphereLight(0xbcd4ff, 0x1a2333, 1.15));
  const dir = new THREE.DirectionalLight(0xffffff, 1.7); dir.position.set(60, 120, 40); scene.add(dir);
  const ground = new THREE.Mesh(new THREE.CircleGeometry(span * 1.4, 64),
    new THREE.MeshStandardMaterial({ color: 0x0c1526, roughness: 1, transparent: true, opacity: .85 }));
  ground.rotation.x = -Math.PI / 2; ground.position.y = -.02; scene.add(ground);
  scene.add(new THREE.GridHelper(span * 2.2, 44, 0x1e3a5f, 0x101c30));

  const meshes = new Map(); const wallGroup = new THREE.Group(), hdGroup = new THREE.Group(), opGroup = new THREE.Group();
  const el3d = {};
  for (const e of store.elements) if (e.revit_ref?.id) el3d[e.revit_ref.id] = e;
  const edgeMat = new THREE.LineBasicMaterial({ color: 0x0b1220, transparent: true, opacity: .55 });

  const wallById = {};
  for (const w of sc.walls) {
    const [[x1, y1], [x2, y2]] = w.centerline_ft;
    const L = Math.hypot(x2 - x1, y2 - y1); if (L < .05) continue;
    const h = w.height_ft;
    const geo = new THREE.BoxGeometry(L, h, Math.max(w.thickness_ft, .25));
    const isSW = w.is_shear_wall;
    const col = COL[w.status] && w.status !== "NOT_EVALUATED" ? COL[w.status] : (isSW ? "#7dd3fc" : "#2b3b55");
    const mat = new THREE.MeshStandardMaterial({ color: col, transparent: true,
      opacity: isSW ? .96 : .42, roughness: .55, metalness: .12 });
    const m = new THREE.Mesh(geo, mat);
    m.position.set((x1 + x2) / 2 - cx, (w.base_ft || 0) + h / 2, -(((y1 + y2) / 2) - cy));
    m.rotation.y = Math.atan2((y2 - y1), (x2 - x1));
    m.add(new THREE.LineSegments(new THREE.EdgesGeometry(geo), edgeMat.clone()));
    const eRef = el3d[w.id];
    m.userData = { kind: "wall", revitId: w.id, elementId: eRef?.id, status: w.status,
      token: w.sw_token, type: w.type_name, isSW, baseOpacity: isSW ? .96 : .42 };
    wallGroup.add(m); wallById[w.id] = m;
    if (eRef) meshes.set(eRef.id, m);
  }
  for (const hd of sc.holdowns) {
    const col = COL[hd.status] && hd.status !== "NOT_EVALUATED" ? COL[hd.status] : "#fbbf24";
    const m = new THREE.Mesh(new THREE.SphereGeometry(.75, 18, 14),
      new THREE.MeshStandardMaterial({ color: col, emissive: col, emissiveIntensity: .3 }));
    m.position.set(hd.x_ft - cx, Math.max(hd.elevation_ft, .5), -(hd.y_ft - cy));
    const eRef = el3d[hd.assembly_id];
    m.userData = { kind: "holdown", revitId: hd.assembly_id, elementId: eRef?.id, status: hd.status,
      mark: hd.mark, baseOpacity: 1 };
    hdGroup.add(m);
    if (eRef) meshes.set(eRef.id, m);
  }
  for (const o of (sc.openings || [])) {
    const host = wallById[o.host_wall_id];
    const col = o.kind === "door" ? 0x8b5cf6 : 0x22d3ee;
    const g = o.kind === "door" ? new THREE.BoxGeometry(3, 6.8, .6) : new THREE.BoxGeometry(3.4, 3.2, .6);
    const m = new THREE.Mesh(g, new THREE.MeshStandardMaterial({ color: col, transparent: true, opacity: .5, roughness: .4 }));
    const yBase = o.kind === "door" ? 3.4 : 4.6;
    m.position.set(o.center_ft[0] - cx, yBase, -(o.center_ft[1] - cy));
    if (host) m.rotation.y = host.rotation.y;
    m.userData = { kind: o.kind, revitId: o.id, status: "NOT_EVALUATED", type: o.type_name, baseOpacity: .5 };
    opGroup.add(m);
  }
  for (const g of sc.grids) {
    const [[x1, y1], [x2, y2]] = g.line_ft;
    const geo = new THREE.BufferGeometry().setFromPoints(
      [new THREE.Vector3(x1 - cx, .05, -(y1 - cy)), new THREE.Vector3(x2 - cx, .05, -(y2 - cy))]);
    scene.add(new THREE.Line(geo, new THREE.LineBasicMaterial({ color: 0x2b4a72 })));
    const lbl1 = makeLabelSprite(g.label || "");
    lbl1.position.set(x1 - cx, 2.2, -(y1 - cy));
    scene.add(lbl1);
    const lbl2 = makeLabelSprite(g.label || "");
    lbl2.position.set(x2 - cx, 2.2, -(y2 - cy));
    scene.add(lbl2);
  }
  const CAT3D = { "Structural Columns": "#f472b6", "Structural Connections": "#fbbf24",
                 "Structural Foundation": "#a3e635", "Stairs": "#c084fc", "Columns": "#f472b6" };
  const catGroup = new THREE.Group();
  for (const ce of (sc.category_elements || [])) {
    if (ce.category === "Structural Connections" && !ce.mark) continue; // panel hardware noise
    const col = COL[ce.status] && ce.status !== "NOT_EVALUATED" ? COL[ce.status] : (CAT3D[ce.category] || "#94a3b8");
    let sx = 1.1, sy = 1.6, sz = 1.1;
    if (ce.bbox_ft) {
      const planMax = ce.category === "Structural Foundation" ? 60 : 8;
      sx = Math.min(Math.max(ce.bbox_ft[1][0] - ce.bbox_ft[0][0], .6), planMax);
      sy = Math.min(Math.max(ce.bbox_ft[1][2] - ce.bbox_ft[0][2], .6), 14);
      sz = Math.min(Math.max(ce.bbox_ft[1][1] - ce.bbox_ft[0][1], .6), planMax);
    }
    const m = new THREE.Mesh(new THREE.BoxGeometry(sx, sy, sz),
      new THREE.MeshStandardMaterial({ color: col, transparent: true, opacity: .85, roughness: .5 }));
    m.position.set(ce.center_ft[0] - cx, Math.max(ce.elevation_ft, .3) + sy / 2, -(ce.center_ft[1] - cy));
    const eRef = el3d[ce.id];
    m.userData = { kind: "category_element", revitId: ce.id, elementId: eRef?.id,
      status: ce.status, mark: ce.mark, type: ce.category, baseOpacity: .85 };
    catGroup.add(m);
    if (eRef) meshes.set(eRef.id, m);
  }
  // LIVE model boxes (Revit bounding boxes, hybrid path). They join catGroup so
  // picking / isolate / tooltip / opacity reset all work with zero new wiring.
  for (const b of (sc.live_boxes || [])) {
    const col = (b.status && COL[b.status] && b.status !== "NOT_EVALUATED")
      ? COL[b.status] : (LIVE_COL[b.cat] || "#7dd3fc");
    const opacity = b.cat === "walls" ? .3 : .9;
    const m = new THREE.Mesh(
      new THREE.BoxGeometry(b.size_ft[0], b.size_ft[2], b.size_ft[1]),
      new THREE.MeshStandardMaterial({ color: col, transparent: true, opacity, roughness: .55 }));
    m.position.set(b.center_ft[0] - cx, b.elevation_ft, -(b.center_ft[1] - cy));
    // Selection sync survives in live mode ONLY through the joined assembly:
    // live ElementIds are not the export UniqueIds the element rows are keyed by.
    const eRef = b.assembly_id ? el3d[b.assembly_id] : null;
    m.userData = { kind: "live_" + b.cat, revitId: String(b.id), elementId: eRef?.id,
      status: b.status || "NOT_EVALUATED", mark: `${b.cat} ${b.id}`, type: b.cat,
      baseOpacity: opacity };
    catGroup.add(m);
    if (eRef) meshes.set(eRef.id, m);
  }
  // Structural framing: one InstancedMesh, so 28k members render in one call.
  const fr = sc.framing || [];
  let framingMesh = null;
  if (fr.length) {
    const frInst = new THREE.InstancedMesh(
      new THREE.BoxGeometry(1, 1, 1),
      new THREE.MeshStandardMaterial({ color: 0x62748c, transparent: true, opacity: .45,
        roughness: .75, metalness: .35 }),
      fr.length);
    const m4 = new THREE.Matrix4(), q = new THREE.Quaternion();
    const pos = new THREE.Vector3(), scl = new THREE.Vector3();
    fr.forEach((f, i) => {
      pos.set(f[0] - cx, f[2], -(f[1] - cy));
      scl.set(f[3], f[5], f[4]);
      m4.compose(pos, q, scl);
      frInst.setMatrixAt(i, m4);
    });
    frInst.instanceMatrix.needsUpdate = true;
    frInst.userData = { kind: "framing" };
    scene.add(frInst);
    framingMesh = frInst;
  }
  const bmGroup = new THREE.Group();
  for (const bm of (sc.benchmarks || [])) {
    const y = Math.max(bm.elevation_ft, .5);
    const m = new THREE.Mesh(new THREE.SphereGeometry(1.0, 18, 14),
      new THREE.MeshStandardMaterial({ color: 0xff6a00, emissive: 0xff6a00, emissiveIntensity: .9 }));
    m.position.set(bm.x_ft - cx, y, -(bm.y_ft - cy));
    m.userData = { kind: "benchmark", mark: bm.mark, baseOpacity: 1 };
    bmGroup.add(m);
    const lbl = makeLabelSprite(bm.mark || "BM");
    lbl.position.set(bm.x_ft - cx, y + 2.6, -(bm.y_ft - cy));
    bmGroup.add(lbl);
  }
  scene.add(wallGroup, hdGroup, opGroup, catGroup, bmGroup);
  if (wallGroup.children.length && !reduceMotion())
    gsap.from(wallGroup.children.map(m => m.scale), { y: 0.01, duration: 1.2, ease: "power3.out", stagger: .0025 });

  const infoBall = new THREE.Mesh(
    new THREE.SphereGeometry(1.15, 20, 16),
    new THREE.MeshStandardMaterial({ color: 0x5eead4, emissive: 0x5eead4, emissiveIntensity: 1.1,
      transparent: true, opacity: .95 }));
  infoBall.visible = false;
  infoBall.userData = { kind: "info_ball" };
  const ballRing = new THREE.Mesh(
    new THREE.TorusGeometry(1.8, .09, 10, 40),
    new THREE.MeshBasicMaterial({ color: 0x5eead4, transparent: true, opacity: .7 }));
  ballRing.rotation.x = Math.PI / 2;
  infoBall.add(ballRing);
  scene.add(infoBall);
  let ballTl = null;
  function flyBallTo(pos) {
    infoBall.visible = true;
    if (ballTl) ballTl.kill();
    // Reduced motion: the ball still appears at the element (functional — it is
    // how you find the thing), it just lands instantly and stops bobbing.
    const still = reduceMotion();
    if (still) { infoBall.position.set(pos.x + 2.5, pos.y + 4.5, pos.z + 2.5); return; }
    infoBall.position.set(pos.x + span * .25, pos.y + span * .5, pos.z + span * .25);
    ballTl = gsap.timeline();
    ballTl.to(infoBall.position, { x: pos.x + 2.5, y: pos.y + 4.5, z: pos.z + 2.5,
      duration: 1.1, ease: "bounce.out" });
    ballTl.to(infoBall.position, { y: "+=1.1", duration: .8, yoyo: true, repeat: -1, ease: "sine.inOut" });
    gsap.to(ballRing.rotation, { z: "+=6.28", duration: 3, repeat: -1, ease: "none" });
  }
  function hideBall() { if (ballTl) ballTl.kill(); infoBall.visible = false; }

  const ray = new THREE.Raycaster(), ptr = new THREE.Vector2();
  const pickables = () => [infoBall, ...wallGroup.children, ...hdGroup.children, ...opGroup.children, ...catGroup.children]
    .filter(m => m.visible);
  function pick(ev) {
    const r = renderer.domElement.getBoundingClientRect();
    ptr.set(((ev.clientX - r.left) / r.width) * 2 - 1, -((ev.clientY - r.top) / r.height) * 2 + 1);
    ray.setFromCamera(ptr, camera);
    return ray.intersectObjects(pickables())[0];
  }
  let hovered = null;
  renderer.domElement.addEventListener("pointermove", ev => {
    const hit = pick(ev);
    const tip = $("#three-tip");
    if (hovered && hovered !== hit?.object) { hovered.material.emissiveIntensity = hovered.userData.kind === "holdown" ? .3 : 0; hovered = null; }
    if (hit) {
      hovered = hit.object;
      if (hovered.material.emissive && hovered.userData.kind !== "info_ball") {
        hovered.material.emissive = new THREE.Color(0x5eead4); hovered.material.emissiveIntensity = .5;
      }
      const u = hovered.userData;
      tip.style.display = "block";
      const rr = renderer.domElement.getBoundingClientRect();
      tip.style.left = (ev.clientX - rr.left + 14) + "px";
      tip.style.top = (ev.clientY - rr.top + 10) + "px";
      if (u.kind === "info_ball") {
        tip.innerHTML = `<b>ℹ Click for details</b>`;
      } else {
        const name = u.mark || u.token || u.type || u.kind || "element";
        const st = u.status ? ` · <span style="color:${COL[u.status] || "#94a3b8"}">${u.status.replaceAll("_", " ")}</span>` : "";
        tip.innerHTML = `<b>${name}</b>${st}${u.type && u.type !== name ? `<br><span style="color:var(--dim)">${u.type}</span>` : ""}`;
      }
    } else tip.style.display = "none";
  });
  renderer.domElement.addEventListener("click", ev => {
    const hit = pick(ev);
    if (!hit) return;
    if (hit.object.userData.kind === "info_ball") { openDrawer("inspector"); return; }
    if (hit.object.userData.elementId) select(hit.object.userData.elementId, "3d");
    else toast(`${hit.object.userData.kind} …${(hit.object.userData.revitId || "").slice(-8)} · ${hit.object.userData.status || ""}`);
  });
  let isolated = null;
  renderer.domElement.addEventListener("dblclick", ev => {
    const hit = pick(ev);
    if (hit && isolated !== hit.object) {
      isolated = hit.object;
      pickables().forEach(m => m.material.opacity = m === isolated ? 1 : .06);
    } else {
      isolated = null;
      pickables().forEach(m => m.material.opacity = m.userData.baseOpacity);
    }
  });
  three3dState = { renderer, scene, raf: 0 };
  (function loop() { three3dState.raf = requestAnimationFrame(loop); controls.update(); renderer.render(scene, camera); })();

  // BUG-16: door/window chips only when the scene actually has openings.
  const hasOpenings = (sc.openings || []).length > 0;
  $("#three-legend").innerHTML =
    ["MATCH", "LOCATION_MISMATCH", "REVIT_ONLY", "NOT_EVALUATED"].map(s =>
      `<span class="chip" style="color:${COL[s]};border-color:${COL[s]}55">● ${s.replaceAll("_", " ")}</span>`).join("")
    + (hasOpenings
        ? `<span class="chip" style="color:#8b5cf6;border-color:#8b5cf655">● door</span>`
          + `<span class="chip" style="color:#22d3ee;border-color:#22d3ee55">● window</span>`
        : "");
  // Source badge: live model vs frozen export snapshot — never ambiguous.
  const badge = $("#three-live-badge");
  if (badge) {
    const c = sc.live ? "#22c55e" : "#94a3b8";
    const txt = sc.live ? `LIVE · ${sc.model_title || "Revit model"}` : "SNAPSHOT · last export";
    const swapped = badge.textContent !== txt;
    badge.textContent = txt;
    badge.style.color = c; badge.style.borderColor = c + "55";
    // M5 — SNAPSHOT→LIVE is a trust change; a one-shot crossfade marks it.
    if (swapped && !reduceMotion())
      gsap.fromTo(badge, { opacity: 0, y: -4 }, { opacity: 1, y: 0, duration: .28, ease: "power2.out" });
  }
  // BUG-11: only claim an assumed wall height when a rendered wall truly uses it.
  const anyAssumed = (sc.walls || []).some(w => w.height_assumed);
  const dropped = Object.entries(sc.truncated || {})
    .map(([k, v]) => `${k} ${v.kept ?? v.boxes ?? v.expanded}/${v.total ?? v.requested ?? v.reported}`);
  const note = $("#three-note");
  if (note) {
    // Honesty claims stay on screen; the telemetry (per-category counts, the
    // truncation cap, the registry-join count) moves into the tooltip — UI §1c.
    note.title = sc.live
      ? [Object.entries(sc.counts || {}).map(([k, v]) => `${k} ${v}`).join(" · "),
         dropped.length ? `capped: ${dropped.join(", ")}` : "",
         `${sc.status_joined || 0} connections matched to this project's registry`]
        .filter(Boolean).join("\n")
      : "";
    note.innerHTML =
      (sc.live ? `LIVE bounding-box massing — not exact geometry<br>` : "")
      + (anyAssumed ? `wall height ASSUMED ${sc.assumed_wall_height_ft || 10}ft (not model truth)<br>` : "")
      + "drag to orbit · click to select · double-click to isolate";
  }

  three = { renderer, scene, camera, controls, meshes, wallGroup, hdGroup, opGroup, catGroup,
    framing: framingMesh, span, HOME,
    flyBallTo, hideBall,
    reset() {
      hideBall();
      gsap.to(camera.position, { x: HOME.pos.x, y: HOME.pos.y, z: HOME.pos.z, duration: 1.1, ease: "power3.inOut" });
      gsap.to(controls.target, { x: HOME.tgt.x, y: HOME.tgt.y, z: HOME.tgt.z, duration: 1.1, ease: "power3.inOut" });
      pickables().forEach(m => m.material.opacity = m.userData.baseOpacity);
      isolated = null;
    },
    top() {
      gsap.to(camera.position, { x: 0, y: span * 1.35, z: 0.01, duration: 1.1, ease: "power3.inOut" });
      gsap.to(controls.target, { x: 0, y: 0, z: 0, duration: 1.1, ease: "power3.inOut" });
    },
    swOnly(on) {
      wallGroup.children.forEach(m => m.visible = !on || m.userData.isSW);
      opGroup.children.forEach(m => m.visible = !on);
    },
  };
}

export function resize3D() {
  if (!three) return;
  const wrap = $("#three-wrap"), W = wrap.clientWidth, H = wrap.clientHeight;
  if (W < 10 || H < 10) return;
  three.renderer.setSize(W, H);
  three.camera.aspect = W / H; three.camera.updateProjectionMatrix();
}
new ResizeObserver(() => resize3D()).observe($("#three-wrap"));

let pulseTl = null;
function highlight3D(e, origin) {
  if (!three) return;
  three.meshes.forEach(m => { m.material.emissiveIntensity = m.userData.kind === "holdown" ? .3 : 0; });
  if (pulseTl) pulseTl.kill();
  const m = three.meshes.get(e.id);
  if (!m) {
    three.flyBallTo(new THREE.Vector3(0, 6, 0));
    return;
  }
  three.flyBallTo(m.position);
  const good = e.status === "MATCH";
  m.material.emissive = new THREE.Color(good ? 0x22c55e : 0xef4444);
  const still = reduceMotion();
  // The emissive pulse is decoration; the highlight colour above is the signal.
  if (still) m.material.emissiveIntensity = 1.5;
  else pulseTl = gsap.to(m.material, { emissiveIntensity: 1.5, duration: .55, yoyo: true, repeat: -1, ease: "sine.inOut" });
  if (origin !== "3d") {
    const p = m.position, d = Math.max(14, three.span * .18);
    // Camera flight is functional (it frames the element) — made instant, not removed.
    const dur = still ? 0 : 1;
    gsap.to(three.controls.target, { x: p.x, y: p.y, z: p.z, duration: dur, ease: "power3.inOut" });
    gsap.to(three.camera.position, { x: p.x + d, y: p.y + d * .9, z: p.z + d, duration: still ? 0 : 1.1, ease: "power3.inOut" });
  }
}

/* Escape/global deselect helper (§8 keeps the reset path in the 3D module). */
export function resetView3D() {
  if (pulseTl) pulseTl.kill();
  if (three) three.reset();
}

/* ---- wiring ---- */
const liveBtn = $("#btn-3d-live");
if (liveBtn) liveBtn.onclick = async () => {
  liveBtn.disabled = true;
  try { await loadLiveScene(true); } finally { liveBtn.disabled = false; }
};
$("#btn-3d-reset").onclick = () => three && three.reset();
$("#btn-top").onclick = () => three && three.top();
$("#btn-sw-only").onclick = () => {
  store.swOnly = !store.swOnly;
  $("#btn-sw-only").classList.toggle("active", store.swOnly);
  three && three.swOnly(store.swOnly);
};

subscribe("select", ({ element: e, origin }) => {
  if (!e) return;
  highlight3D(e, origin);
});
