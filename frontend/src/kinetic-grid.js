/* Vanilla kinetic grid — the atmospheric animated background for the vanilla
   dashboard (index.html). Mirrors the React KineticGrid's canvas math so the
   dashboard and pipeline pages feel like ONE product.

   Design rules:
   - pointer-events: none — never blocks a click on holdowns/buttons/panels.
   - Always animating. Clicking the dashboard fires a ripple but the grid
     NEVER pauses on interaction (the user asked for it to keep working
     everywhere). Pauses only on document.hidden + prefers-reduced-motion.
   - Translucent: the canvas sits at z-index 0, dashboard content at z>=1,
     so panels show through as a subtle live layer.
*/

(function () {
  const canvas = document.getElementById("kinetic-bg");
  if (!canvas) return;
  const ctx = canvas.getContext("2d", { alpha: true });
  if (!ctx) return;

  const CELL_SIZE = 55, INFLUENCE_RADIUS = 260, MAX_WARP = 24;
  const DOT_SPACING = 28, LERP_SPEED = 0.08;
  const LINE_BASE = { r: 255, g: 255, b: 255, a: 0.10 };
  const ACTIVE = { r: 74, g: 158, b: 255, a: 0.85 };

  const mouse = { x: -9999, y: -9999 };
  const target = { x: -9999, y: -9999 };
  const ripples = [];
  let W = 0, H = 0, raf = 0, reduced = false;

  function lerp(a, b, t) { return a + (b - a) * t; }
  function lerpColor(base, act, t) {
    return `rgba(${Math.round(lerp(base.r, act.r, t))},${Math.round(lerp(base.g, act.g, t))},${Math.round(lerp(base.b, act.b, t))},${lerp(base.a, act.a, t).toFixed(3)})`;
  }

  function resize() {
    canvas.width = window.innerWidth;
    canvas.height = window.innerHeight;
    W = canvas.width; H = canvas.height;
  }

  function draw(now) {
    ctx.clearRect(0, 0, W, H);
    // faint static dot texture
    ctx.fillStyle = "rgba(255,255,255,0.045)";
    for (let x = DOT_SPACING / 2; x < W; x += DOT_SPACING)
      for (let y = DOT_SPACING / 2; y < H; y += DOT_SPACING) {
        ctx.beginPath(); ctx.arc(x, y, 0.7, 0, Math.PI * 2); ctx.fill();
      }
    // ripples
    for (let i = ripples.length - 1; i >= 0; i--) {
      const r = ripples[i];
      r.radius = Math.max(0, ((now - r.born) / 1000) * 400);
      r.opacity = Math.max(0, 1 - ((now - r.born) / 1000) * 1.2);
      if (r.opacity <= 0) ripples.splice(i, 1);
    }
    const cols = Math.max(2, Math.ceil(W / CELL_SIZE)) + 1;
    const rows = Math.max(2, Math.ceil(H / CELL_SIZE)) + 1;
    const cw = W / (cols - 1), ch = H / (rows - 1);
    const pts = [], prox = [];
    for (let row = 0; row < rows; row++) {
      pts[row] = []; prox[row] = [];
      for (let col = 0; col < cols; col++) {
        const gx = col * cw, gy = row * ch;
        const edgeMargin = 1.5;
        const pin = Math.min(col / edgeMargin, (cols - 1 - col) / edgeMargin, 1)
                  * Math.min(row / edgeMargin, (rows - 1 - row) / edgeMargin, 1);
        const pinFactor = pin * pin * pin * pin;
        const dx = gx - mouse.x, dy = gy - mouse.y;
        const dist = Math.sqrt(dx * dx + dy * dy);
        const proximity = Math.max(0, 1 - dist / INFLUENCE_RADIUS) * pinFactor;
        let rx = 0, ry = 0;
        for (const r of ripples) {
          const rdx = gx - r.x, rdy = gy - r.y;
          const rd = Math.sqrt(rdx * rdx + rdy * rdy);
          const diff = rd - r.radius;
          if (Math.abs(diff) < 55) {
            const str = (1 - Math.abs(diff) / 55) * r.opacity * 18 * pinFactor;
            const a = Math.atan2(rdy, rdx);
            const s = diff < 0 ? -1 : 1;
            rx += Math.cos(a) * str * s * -1;
            ry += Math.sin(a) * str * s * -1;
          }
        }
        let px = gx + rx, py = gy + ry;
        if (dist < INFLUENCE_RADIUS && dist > 0 && pinFactor > 0) {
          const t = dist / INFLUENCE_RADIUS;
          const eased = t < 0.01 ? 0 : (1 - t) * (1 - t) * Math.min(1, dist / 60);
          const warp = eased * MAX_WARP * pinFactor;
          const a = Math.atan2(dy, dx);
          px = gx - Math.cos(a) * warp + rx;
          py = gy - Math.sin(a) * warp + ry;
        }
        pts[row][col] = { x: px, y: py };
        prox[row][col] = proximity;
      }
    }
    const seg = (p1, p2, pr1, pr2) => {
      const t = (pr1 + pr2) / 2; const s = t * t * (3 - 2 * t);
      ctx.beginPath(); ctx.moveTo(p1.x, p1.y); ctx.lineTo(p2.x, p2.y);
      ctx.strokeStyle = lerpColor(LINE_BASE, ACTIVE, s);
      ctx.lineWidth = lerp(0.8, 1.5, s); ctx.stroke();
    };
    for (let r = 0; r < rows; r++) for (let c = 0; c < cols - 1; c++) seg(pts[r][c], pts[r][c+1], prox[r][c], prox[r][c+1]);
    for (let c = 0; c < cols; c++) for (let r = 0; r < rows - 1; r++) seg(pts[r][c], pts[r+1][c], prox[r][c], prox[r+1][c]);
    for (let r = 0; r < rows; r++) for (let c = 0; c < cols; c++) {
      const p = pts[r][c], pr = prox[r][c], t = pr * pr * (3 - 2 * pr);
      const rad = lerp(1.8, 3.2, t);
      if (t > 0.3) {
        const gr = rad + lerp(0, 6, (t - 0.3) / 0.7);
        const g = ctx.createRadialGradient(p.x, p.y, rad * 0.5, p.x, p.y, gr);
        // Matches --signal (#22D3EE = 34,211,238). The grid was on a third
        // blue (74,158,255) while the two pages used teal and Livio blue, so
        // the background subtly fought whatever sat on top of it.
        g.addColorStop(0, `rgba(34,211,238,${(t * 0.3).toFixed(3)})`);
        g.addColorStop(1, "rgba(34,211,238,0)");
        ctx.beginPath(); ctx.arc(p.x, p.y, gr, 0, Math.PI * 2); ctx.fillStyle = g; ctx.fill();
      }
      ctx.beginPath(); ctx.arc(p.x, p.y, rad, 0, Math.PI * 2);
      ctx.fillStyle = lerpColor({ r: 255, g: 255, b: 255, a: 0.18 }, ACTIVE, t);
      ctx.fill();
    }
    for (const r of ripples) {
      ctx.beginPath(); ctx.arc(r.x, r.y, Math.max(0, r.radius), 0, Math.PI * 2);
      ctx.strokeStyle = `rgba(100,180,255,${(r.opacity * 0.28).toFixed(3)})`;
      ctx.lineWidth = 1.5; ctx.stroke();
    }
  }

  function animate(now) {
    mouse.x = lerp(mouse.x, target.x, LERP_SPEED);
    mouse.y = lerp(mouse.y, target.y, LERP_SPEED);
    draw(now);
    raf = requestAnimationFrame(animate);
  }

  function start() { if (!raf && !reduced) raf = requestAnimationFrame(animate); }
  function stop() { if (raf) { cancelAnimationFrame(raf); raf = 0; } }

  resize();
  window.addEventListener("resize", resize);
  window.addEventListener("mousemove", (e) => { target.x = e.clientX; target.y = e.clientY; });
  window.addEventListener("click", (e) => { ripples.push({ x: e.clientX, y: e.clientY, radius: 0, opacity: 1, born: performance.now() }); });
  document.addEventListener("visibilitychange", () => document.hidden ? stop() : start());
  const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
  reduced = mq.matches;
  mq.addEventListener("change", () => { reduced = mq.matches; reduced ? stop() : start(); });
  start();
})();
