/* ═══════════════════════════════════════════════════════════════
   MORA02 PILOT — Interactive Pixel Logo
   ═══════════════════════════════════════════════════════════════
   Self-contained animation. Call initLogo() to start/restart.
   Pixels push away from cursor and return to home position.
   ═══════════════════════════════════════════════════════════════ */

const LOGO_GRIDS = {
  M: ['#####','#.#.#','#.#.#','#.#.#','#.#.#'],
  O: ['#####','#...#','#...#','#...#','#####'],
  R: ['#####','#...#','####.','#...#','#...#'],
  A: ['#####','#...#','#####','#...#','#...#'],
  0: ['.###.','#...#','#...#','#...#','.###.'],
  2: ['#####','....#','#####','#....','#####'],
};
const LOGO_LETTERS = ['M','O','R','A','0','2'];
const LOGO_CONFIG = { pixelSize: 12, color: '#666666', radius: 100, push: 4, speed: 80 };

let logoFrame = null;  // animation frame ID for cleanup

function initLogo() {
  const cv = document.getElementById('lc');
  const ct = document.getElementById('hero');
  if (!cv || !ct) return;

  // Cancel previous animation if re-initing
  if (logoFrame) cancelAnimationFrame(logoFrame);

  const cx = cv.getContext('2d');
  const ps = LOGO_CONFIG.pixelSize;
  let px = [], gW = 0, gH = 5;
  let mX = -9e3, mY = -9e3, hov = false;
  let oX = 0, oY = 0, bMnX = 0, bMnY = 0, bMxX = 0, bMxY = 0;
  let occ = {};

  function ok(x, y) { return x + ',' + y; }

  function build() {
    px = []; occ = {}; let c = 0;
    LOGO_LETTERS.forEach(l => {
      const g = LOGO_GRIDS[l];
      for (let r = 0; r < 5; r++)
        for (let k = 0; k < 5; k++)
          if (g[r][k] === '#') {
            const gx = c + k, gy = r;
            px.push({ hx: gx, hy: gy, gx, gy, mv: false, mf: [gx, gy], mt: [gx, gy], ms: 0, md: 0 });
            occ[ok(gx, gy)] = px.length - 1;
          }
      c += 6;
    });
    gW = c - 1;
  }

  function layout() {
    const r = ct.getBoundingClientRect();
    const w = Math.floor(r.width), h = Math.floor(r.height);
    cv.width = w; cv.height = h;
    oX = (w - gW * ps) / 2; oY = (h - gH * ps) / 2;
    bMnX = Math.floor(-oX / ps); bMnY = Math.floor(-oY / ps);
    bMxX = Math.floor((w - oX) / ps) - 1; bMxY = Math.floor((h - oY) / ps) - 1;
  }

  function go(i, tx, ty) {
    const p = px[i], d = Math.abs(tx - p.gx) + Math.abs(ty - p.gy);
    if (!d) return;
    delete occ[ok(p.gx, p.gy)];
    p.mf = [p.gx, p.gy]; p.mt = [tx, ty]; p.mv = true;
    p.ms = performance.now(); p.md = LOGO_CONFIG.speed * d;
    occ[ok(tx, ty)] = i;
  }

  function free(x, y, ii) { const k = ok(x, y); return occ[k] === undefined || occ[k] === ii; }
  function inB(x, y) { return x >= bMnX && x <= bMxX && y >= bMnY && y <= bMxY; }
  function s2g(sx, sy) { return { gx: (sx - oX) / ps, gy: (sy - oY) / ps }; }

  function pushC() {
    const mg = s2g(mX, mY), rg = LOGO_CONFIG.radius / ps;
    px.map((p, i) => ({ i, d: Math.sqrt((p.gx - mg.gx) ** 2 + (p.gy - mg.gy) ** 2) }))
      .filter(e => !px[e.i].mv && e.d <= rg && e.d > 0.3)
      .sort((a, b) => a.d - b.d)
      .forEach(e => {
        const p = px[e.i];
        const dx = p.gx - mg.gx, dy = p.gy - mg.gy;
        const dd = Math.sqrt(dx * dx + dy * dy);
        let dX = 0, dY = 0;
        if (Math.abs(dx) >= Math.abs(dy)) dX = dx >= 0 ? 1 : -1;
        else dY = dy >= 0 ? 1 : -1;
        const f = 1 - (dd / rg), mp = Math.max(1, Math.round(f * LOGO_CONFIG.push));
        let bx = p.gx, by = p.gy;
        for (let s = 1; s <= mp; s++) {
          const tx = p.gx + dX * s, ty = p.gy + dY * s;
          if (!inB(tx, ty) || !free(tx, ty, e.i)) break;
          bx = tx; by = ty;
        }
        if (bx !== p.gx || by !== p.gy) go(e.i, bx, by);
      });
  }

  function ret() {
    const mg = s2g(mX, mY), rg = hov ? LOGO_CONFIG.radius / ps : 0;
    px.map((p, i) => ({
      i, hd: Math.abs(p.gx - p.hx) + Math.abs(p.gy - p.hy),
      cd: Math.sqrt((p.gx - mg.gx) ** 2 + (p.gy - mg.gy) ** 2)
    }))
      .filter(e => !px[e.i].mv && e.hd > 0)
      .filter(e => !hov || e.cd > rg * 1.2)
      .sort((a, b) => b.hd - a.hd)
      .forEach(e => {
        const p = px[e.i];
        const dx = p.hx - p.gx, dy = p.hy - p.gy;
        let ax;
        if (Math.abs(dx) >= Math.abs(dy)) { ax = [[dx > 0 ? 1 : -1, 0]]; if (dy) ax.push([0, dy > 0 ? 1 : -1]); }
        else { ax = [[0, dy > 0 ? 1 : -1]]; if (dx) ax.push([dx > 0 ? 1 : -1, 0]); }
        for (const a of ax) {
          const nx = p.gx + a[0], ny = p.gy + a[1];
          if (inB(nx, ny) && free(nx, ny, e.i)) { go(e.i, nx, ny); return; }
        }
      });
  }

  function ease(t) { return t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2; }

  let lP = 0, lR = 0, pMX = -9e3, pMY = -9e3;

  function frame() {
    const n = performance.now();
    px.forEach(p => { if (p.mv && n >= p.ms + p.md) { p.gx = p.mt[0]; p.gy = p.mt[1]; p.mv = false; } });

    const mv = Math.abs(mX - pMX) > 2 || Math.abs(mY - pMY) > 2;
    if (hov && mv && n - lP > 50) { pushC(); lP = n; pMX = mX; pMY = mY; }
    if (n - lR > 100) { ret(); lR = n; }

    cx.clearRect(0, 0, cv.width, cv.height);
    cx.fillStyle = LOGO_CONFIG.color;
    px.forEach(p => {
      let gx, gy;
      if (p.mv) {
        const t = ease(Math.min((n - p.ms) / p.md, 1));
        gx = p.mf[0] + (p.mt[0] - p.mf[0]) * t;
        gy = p.mf[1] + (p.mt[1] - p.mf[1]) * t;
      } else { gx = p.gx; gy = p.gy; }
      cx.fillRect(oX + gx * ps, oY + gy * ps, ps, ps);
    });

    logoFrame = requestAnimationFrame(frame);
  }

  // Events
  cv.addEventListener('mousemove', e => { const r = cv.getBoundingClientRect(); mX = e.clientX - r.left; mY = e.clientY - r.top; hov = true; });
  cv.addEventListener('mouseleave', () => { hov = false; });
  cv.addEventListener('touchmove', e => { const r = cv.getBoundingClientRect(); mX = e.touches[0].clientX - r.left; mY = e.touches[0].clientY - r.top; hov = true; e.preventDefault(); }, { passive: false });
  cv.addEventListener('touchend', () => { hov = false; });

  // Resize handler
  const resizeHandler = () => layout();
  window.removeEventListener('resize', resizeHandler); // prevent duplicates
  window.addEventListener('resize', resizeHandler);

  build();
  layout();
  frame();
}

// Auto-init on load
initLogo();
