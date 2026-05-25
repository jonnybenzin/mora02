/* ═══════════════════════════════════════════════════════════════
   MORA02 PILOT — PixelText Tool
   3D pixel-cube typography rendered via blender-worker (port 8097).
   Init: initPixelText() called from tools.js initToolPage().
   ═══════════════════════════════════════════════════════════════ */

const PX_API = (typeof window !== 'undefined' && window.location)
  ? `${window.location.protocol}//${window.location.hostname}:8097`
  : 'http://mora02.local:8097';
const PX_ASSETS = (typeof window !== 'undefined' && window.location)
  ? `${window.location.protocol}//${window.location.hostname}:8092/pixeltext`
  : 'http://mora02.local:8092/pixeltext';

const PX_ALPHABET = {
  A:["#####","#...#","#####","#...#","#...#"],
  B:["#####","#...#","####.","#...#","#####"],
  C:["#####","#....","#....","#....","#####"],
  D:["####.","#...#","#...#","#...#","####."],
  E:["#####","#....","#####","#....","#####"],
  F:["#####","#....","#####","#....","#...."],
  G:["#####","#....","#..##","#...#","#####"],
  H:["#...#","#...#","#####","#...#","#...#"],
  I:[".#.",".#.",".#.",".#.",".#."],
  J:["....#","....#","....#","#...#","#####"],
  K:["#...#","#..#.","###..","#..#.","#...#"],
  L:["#....","#....","#....","#....","#####"],
  M:["#####","#.#.#","#.#.#","#.#.#","#.#.#"],
  N:["#####","#...#","#...#","#...#","#...#"],
  O:["#####","#...#","#...#","#...#","#####"],
  P:["#####","#...#","#####","#....","#...."],
  Q:["#####","#...#","#...#","#.#.#","#####"],
  R:["#####","#...#","####.","#...#","#...#"],
  S:["#####","#....","#####","....#","#####"],
  T:["#####","..#..","..#..","..#..","..#.."],
  U:["#...#","#...#","#...#","#...#","#####"],
  V:["#...#","#...#","#...#","#...#","####."],
  W:["#.#.#","#.#.#","#.#.#","#.#.#","#####"],
  X:["#...#","#...#",".###.","#...#","#...#"],
  Y:["#...#","#...#","#####","..#..","..#.."],
  Z:["#####","....#",".###.","#....","#####"],
  "0":[".###.","#...#","#...#","#...#",".###."],
  "1":["#####","....#","....#","....#","....#"],
  "2":["#####","....#","#####","#....","#####"],
  "3":["#####","....#","#####","....#","#####"],
  "4":["#...#","#...#","#####","....#","....#"],
  "5":["#####","#....","####.","....#","####."],
  "6":["#....","#....","#####","#...#","#####"],
  "7":["#####","....#","..###","....#","....#"],
  "8":["#####","#...#","#####","#...#","#####"],
  "9":["#####","#...#","#####","....#","....#"],
  " ":[".....",".....",".....",".....","....."],
  ".":[".....",".....",".....",".....","..#.."],
  "!":["..#..","..#..","..#..",".....","..#.."],
  "-":[".....",".....",".####",".....","....."],
  "+":[".....","..#..","#####","..#..","....."],
};

var pxState = {
  mode: 'multi',
  transition: 'shuffle',
  previewWordIdx: 0,
  previewImages: [],
  previewImgIdx: 0,
  initialised: false,
};

function initPixelText() {
  pxState = {
    mode: 'multi',
    transition: 'shuffle',
    previewWordIdx: 0,
    previewImages: [],
    previewImgIdx: 0,
    initialised: true,
  };

  // Wire input listeners that update the live canvas / timeline
  var inputs = [
    'px-words', 'px-single-text', 'px-cube-color', 'px-bg-color',
    'px-hold-sec', 'px-trans-sec', 'px-fps',
  ];
  inputs.forEach(function(id) {
    var el = document.getElementById(id);
    if (el) el.addEventListener('input', pxUpdatePreview);
  });

  // Slider value display + live preview
  var sliders = [
    ['px-emission', 'px-emission-val'],
    ['px-gap', 'px-gap-val'],
    ['px-pulse-min', 'px-pulse-min-val'],
    ['px-pulse-max', 'px-pulse-max-val'],
    ['px-float-amp', 'px-float-amp-val'],
    ['px-mblur-shutter', 'px-mblur-shutter-val'],
    ['px-spread', 'px-spread-val'],
  ];
  sliders.forEach(function(pair) {
    var slider = document.getElementById(pair[0]);
    var label = document.getElementById(pair[1]);
    if (slider && label) {
      slider.addEventListener('input', function() { label.textContent = slider.value; });
    }
  });

  // Color picker ↔ text input sync
  pxBindColor('px-cube-color-pick', 'px-cube-color');
  pxBindColor('px-bg-color-pick', 'px-bg-color');

  // Motion blur toggle → show/hide shutter slider
  var mblurCb = document.getElementById('px-motion-blur');
  if (mblurCb) {
    mblurCb.addEventListener('change', function() {
      pxToggle('px-mblur-shutter-group', mblurCb.checked);
    });
  }

  // Template dropdown: load list + toggle appearance section
  pxLoadTemplates();
  var tmplSel = document.getElementById('px-template');
  if (tmplSel) {
    tmplSel.addEventListener('change', function() {
      var hasTemplate = !!tmplSel.value;
      pxToggle('px-appearance-section', !hasTemplate);
    });
  }

  pxUpdatePreview();
  pxUpdateTimeline();
}

function pxBindColor(pickId, textId) {
  var pick = document.getElementById(pickId);
  var text = document.getElementById(textId);
  if (!pick || !text) return;
  pick.addEventListener('input', function() { text.value = pick.value; pxUpdatePreview(); });
  text.addEventListener('input', function() { pick.value = text.value; pxUpdatePreview(); });
}

/* ─── MODE / TRANSITION ──────────────────────────────────────── */

function pxSetMode(mode) {
  pxState.mode = mode;
  document.querySelectorAll('.px-mode-tab').forEach(function(t) {
    t.classList.toggle('px-active', t.dataset.mode === mode);
  });
  pxToggle('px-multi-input', mode === 'multi');
  pxToggle('px-single-input', mode === 'single');
  pxToggle('px-transition-section', mode === 'multi');
  pxToggle('px-single-duration-group', mode === 'single');
  pxToggle('px-shuffle-row', mode === 'single');
  var nav = document.getElementById('px-canvas-nav');
  if (nav) nav.style.display = mode === 'multi' ? 'flex' : 'none';
  pxState.previewWordIdx = 0;
  pxUpdatePreview();
  pxUpdateTimeline();
}

function pxSelectTransition(style) {
  pxState.transition = style;
  document.querySelectorAll('.px-trans-card').forEach(function(c) {
    c.classList.toggle('px-selected', c.dataset.style === style);
  });
}

function pxToggle(id, show) {
  var el = document.getElementById(id);
  if (!el) return;
  if (id === 'px-single-duration-group') {
    el.style.display = show ? '' : 'none';
  } else {
    el.style.display = show ? '' : 'none';
  }
}

/* ─── PREVIEW (canvas) ───────────────────────────────────────── */

function pxGetWords() {
  if (pxState.mode === 'multi') {
    var ta = document.getElementById('px-words');
    if (!ta) return [];
    return ta.value.split('\n').map(function(l) { return l.trim().toUpperCase(); }).filter(function(l) { return l.length > 0; });
  }
  var st = document.getElementById('px-single-text');
  return st ? [st.value.toUpperCase()] : [];
}

function pxPrevWord() {
  var words = pxGetWords();
  if (words.length === 0) return;
  pxState.previewWordIdx = (pxState.previewWordIdx - 1 + words.length) % words.length;
  pxUpdatePreview();
}

function pxNextWord() {
  var words = pxGetWords();
  if (words.length === 0) return;
  pxState.previewWordIdx = (pxState.previewWordIdx + 1) % words.length;
  pxUpdatePreview();
}

function pxDrawWord(ctx, word, cubeColor, bgColor, maxCanvasWidth) {
  var totalCols = 0;
  for (var i = 0; i < word.length; i++) {
    var ch = word[i];
    if (ch === ' ') { totalCols += 5; continue; }
    if (i > 0 && word[i-1] !== ' ') totalCols += 1;
    var g = PX_ALPHABET[ch];
    totalCols += (g && g[0]) ? g[0].length : 5;
  }
  if (totalCols === 0) totalCols = 5;

  var pixelSize = Math.max(3, Math.min(10, Math.floor(maxCanvasWidth / totalCols)));
  var w = totalCols * pixelSize;
  var h = 5 * pixelSize;

  ctx.canvas.width = w;
  ctx.canvas.height = h;

  ctx.fillStyle = bgColor;
  ctx.fillRect(0, 0, w, h);

  ctx.fillStyle = cubeColor;
  var cursorX = 0;
  for (var j = 0; j < word.length; j++) {
    var ch2 = word[j];
    if (ch2 === ' ') { cursorX += 5; continue; }
    if (j > 0 && word[j-1] !== ' ') cursorX += 1;
    var grid = PX_ALPHABET[ch2];
    if (!grid) { cursorX += 5; continue; }
    var charW = grid[0].length;
    for (var row = 0; row < 5; row++) {
      for (var col = 0; col < grid[row].length; col++) {
        if (grid[row][col] === '#') {
          ctx.fillRect((cursorX + col) * pixelSize, row * pixelSize, pixelSize - 1, pixelSize - 1);
        }
      }
    }
    cursorX += charW;
  }
}

function pxUpdatePreview() {
  if (!pxState.initialised) return;
  var words = pxGetWords();
  var canvas = document.getElementById('px-canvas');
  if (!canvas) return;
  var ctx = canvas.getContext('2d');
  if (words.length === 0) {
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    return;
  }
  var idx = Math.min(pxState.previewWordIdx, words.length - 1);
  var cubeColor = (document.getElementById('px-cube-color') || {}).value || '#FFFFFF';
  var bgColor = (document.getElementById('px-bg-color') || {}).value || '#000000';
  pxDrawWord(ctx, words[idx], cubeColor, bgColor, 560);
  var lbl = document.getElementById('px-canvas-label');
  if (lbl) lbl.textContent = (idx + 1) + '/' + words.length + ': ' + words[idx];
  pxUpdateTimeline();
}

function pxUpdateTimeline() {
  var el = document.getElementById('px-timeline');
  if (!el) return;
  if (pxState.mode === 'single') { el.style.display = 'none'; return; }
  el.style.display = '';
  var words = pxGetWords();
  var hold = parseFloat((document.getElementById('px-hold-sec') || {}).value) || 2;
  var trans = parseFloat((document.getElementById('px-trans-sec') || {}).value) || 1;
  var fps = parseInt((document.getElementById('px-fps') || {}).value) || 30;
  var perWord = trans + hold + trans;
  var totalSec = perWord * words.length;
  var totalFrames = Math.round(totalSec * fps);
  el.textContent = 'Timeline: ' + words.length + ' words × ' + perWord.toFixed(1) + 's = ' + totalSec.toFixed(1) + 's @ ' + fps + 'fps = ' + totalFrames + ' frames';
}

/* ─── BG UPLOAD ──────────────────────────────────────────────── */

/* ─── TEMPLATES ──────────────────────────────────────────────── */

async function pxLoadTemplates() {
  var sel = document.getElementById('px-template');
  if (!sel) return;
  try {
    var resp = await fetch(PX_API + '/templates');
    var data = await resp.json();
    if (data.templates) {
      data.templates.forEach(function(t) {
        var opt = document.createElement('option');
        opt.value = t.file;
        opt.textContent = t.name;
        sel.appendChild(opt);
      });
    }
  } catch (e) {
    console.warn('Could not load templates:', e);
  }
}

/* ─── CONFIG BUILDER ─────────────────────────────────────────── */

function pxBuildConfig() {
  var words = pxGetWords();
  function val(id) { var el = document.getElementById(id); return el ? el.value : ''; }
  function checked(id) { var el = document.getElementById(id); return !!(el && el.checked); }
  return {
    mode: pxState.mode,
    words: words,
    text: pxState.mode === 'single' ? words[0] : '',
    template: val('px-template'),
    transition_style: pxState.transition,
    hold_sec: parseFloat(val('px-hold-sec')) || 2,
    transition_sec: parseFloat(val('px-trans-sec')) || 1,
    single_duration_sec: parseInt(val('px-single-duration')) || 5,
    cube_color: val('px-cube-color'),
    bg_color: val('px-bg-color'),
    emission_strength: parseFloat(val('px-emission')),
    gap: parseFloat(val('px-gap')),
    camera_type: val('px-camera-type'),
    camera_distance: parseFloat(val('px-camera-dist')),
    spread: parseFloat(val('px-spread')) || 1.0,
    render_width: parseInt(val('px-render-w')),
    render_height: parseInt(val('px-render-h')),
    fps: parseInt(val('px-fps')),
    render_format: val('px-render-format'),
    quality: val('px-quality') || 'mid',
    motion_blur: checked('px-motion-blur'),
    motion_blur_shutter: parseFloat(val('px-mblur-shutter')) || 0.5,
    loop: checked('px-loop'),
    effect_pulse: checked('px-effect-pulse'),
    effect_float: checked('px-effect-float'),
    effect_shuffle: checked('px-effect-shuffle'),
    pulse_min: parseFloat(val('px-pulse-min')),
    pulse_max: parseFloat(val('px-pulse-max')),
    float_amplitude: parseFloat(val('px-float-amp')),
  };
}

/* ─── M2 LOADER ─────────────────────────────────────────────── */

function pxLoaderShow() {
  var existing = document.getElementById('px-m2-loader-wrap');
  if (existing) return;
  var status = document.getElementById('px-status');
  if (!status) return;
  var overlay = document.createElement('div');
  overlay.id = 'px-m2-loader-wrap';
  overlay.style.cssText = 'display:flex;width:100%;justify-content:center;padding:40px 0';
  overlay.innerHTML = '<div class="m2-loader-m" id="px-m2-loader"></div>';
  status.after(overlay);
  startM2(document.getElementById('px-m2-loader'), 9, 35);
}

function pxLoaderHide() {
  stopM2();
  var el = document.getElementById('px-m2-loader-wrap');
  if (el) { el.querySelector('.m2-loader-m').innerHTML = ''; el.remove(); }
}

/* ─── STATUS HELPERS ─────────────────────────────────────────── */

function pxStatus(text, kind) {
  var el = document.getElementById('px-status');
  if (!el) return;
  el.textContent = text;
  el.className = 'px-status px-status-active' + (kind ? ' px-status-' + kind : '');
  el.style.display = 'block';
}

function pxStatusHide() {
  var el = document.getElementById('px-status');
  if (el) el.style.display = 'none';
}

/* ─── PREVIEW RENDER (server-side single frames) ─────────────── */

async function pxStartPreview() {
  var btn = document.querySelector('[data-action="px-preview"]');
  var previewResult = document.getElementById('px-preview-result');
  if (btn) btn.disabled = true;
  pxStatus('Rendering preview (~5–15s)…');
  pxLoaderShow();
  if (previewResult) previewResult.style.display = 'none';

  var formData = new FormData();
  formData.append('config', JSON.stringify(pxBuildConfig()));


  try {
    var resp = await fetch(PX_API + '/preview', { method: 'POST', body: formData });
    var data = await resp.json();
    pxLoaderHide();
    if (data.success && data.previews && data.previews.length > 0) {
      pxState.previewImages = data.previews;
      pxState.previewImgIdx = 0;
      pxShowPreviewImage();
      if (previewResult) previewResult.style.display = '';
      var nav = document.getElementById('px-preview-nav');
      if (nav) nav.style.display = data.previews.length > 1 ? 'flex' : 'none';
      pxStatus('Preview ready in ' + data.render_time_sec + 's — ' + data.previews.length + ' image(s)', 'success');
    } else {
      pxStatus('Preview error: ' + (data.error || 'no images'), 'error');
    }
  } catch (err) {
    pxLoaderHide();
    pxStatus('Network error: ' + err.message, 'error');
  } finally {
    if (btn) btn.disabled = false;
  }
}

function pxShowPreviewImage() {
  if (pxState.previewImages.length === 0) return;
  var idx = pxState.previewImgIdx % pxState.previewImages.length;
  var img = document.getElementById('px-preview-img');
  if (img) img.src = pxState.previewImages[idx].data;
  var words = pxGetWords();
  var label = words[idx] || ('IMAGE ' + (idx + 1));
  var info = document.getElementById('px-preview-info');
  if (info) info.textContent = 'PREVIEW ' + (idx + 1) + '/' + pxState.previewImages.length + ' — ' + label;
}

function pxCyclePreview(delta) {
  if (pxState.previewImages.length === 0) return;
  pxState.previewImgIdx = (pxState.previewImgIdx + delta + pxState.previewImages.length) % pxState.previewImages.length;
  pxShowPreviewImage();
}

/* ─── RENDER TIMER ───────────────────────────────────────────── */

var pxTimerInterval = null;
var pxTimerStart = 0;
var pxRenderHistory = [];  // last 3 render times

function pxTimerBegin() {
  pxTimerStart = performance.now();
  var bar = document.getElementById('px-timer-bar');
  if (bar) bar.style.display = '';
  pxTimerInterval = setInterval(pxTimerTick, 10);
}

function pxTimerTick() {
  var elapsed = (performance.now() - pxTimerStart) / 1000;
  var clock = document.getElementById('px-timer-clock');
  if (clock) clock.textContent = pxFormatTime(elapsed);
}

function pxTimerEnd() {
  if (pxTimerInterval) clearInterval(pxTimerInterval);
  pxTimerInterval = null;
  var elapsed = (performance.now() - pxTimerStart) / 1000;
  var clock = document.getElementById('px-timer-clock');
  if (clock) clock.textContent = pxFormatTime(elapsed);
  // Add to history (keep last 3)
  pxRenderHistory.unshift(elapsed);
  if (pxRenderHistory.length > 3) pxRenderHistory.pop();
  pxTimerShowHistory();
  return elapsed;
}

function pxTimerCancel() {
  if (pxTimerInterval) clearInterval(pxTimerInterval);
  pxTimerInterval = null;
  var bar = document.getElementById('px-timer-bar');
  if (bar) bar.style.display = 'none';
}

function pxFormatTime(sec) {
  var m = Math.floor(sec / 60);
  var s = sec % 60;
  var mm = String(m).padStart(2, '0');
  var ss = String(Math.floor(s)).padStart(2, '0');
  var cs = String(Math.floor((s % 1) * 100)).padStart(2, '0');
  return mm + ':' + ss + '.' + cs;
}

function pxTimerShowHistory() {
  var el = document.getElementById('px-timer-history');
  if (!el) return;
  if (pxRenderHistory.length === 0) { el.style.display = 'none'; return; }
  el.style.display = '';
  el.textContent = pxRenderHistory.map(function(t, i) {
    return '#' + (i + 1) + ' ' + pxFormatTime(t);
  }).join('   ');
}

/* ─── FULL RENDER ────────────────────────────────────────────── */

async function pxStartRender() {
  var btn = document.querySelector('[data-action="px-render"]');
  var result = document.getElementById('px-render-result');
  if (btn) btn.disabled = true;
  pxStatus('Render started — this can take a few minutes…');
  pxLoaderShow();
  if (result) { result.innerHTML = ''; result.style.display = 'none'; }
  pxTimerBegin();

  var formData = new FormData();
  formData.append('config', JSON.stringify(pxBuildConfig()));

  try {
    var resp = await fetch(PX_API + '/render', { method: 'POST', body: formData });
    var data = await resp.json();
    pxLoaderHide();
    var elapsed = pxTimerEnd();
    if (data.success) {
      pxStatus('Render done in ' + pxFormatTime(elapsed) + ' — ' + data.files.length + ' file(s)', 'success');
      var html = '';
      var bucketUrl = '';
      for (var i = 0; i < data.files.length; i++) {
        var f = data.files[i];
        var url = PX_ASSETS + '/' + data.job_id + '/' + f;
        if (f.endsWith('.mp4')) {
          html += '<video src="' + url + '" controls autoplay loop muted></video>';
          if (!bucketUrl) bucketUrl = url;
        }
        html += '<a class="px-download" href="' + url + '" target="_blank" download>↓ ' + f + '</a>';
      }
      if (bucketUrl) {
        html += '<button class="tool-action-btn bucket-add-btn" data-bucket-add '
          + 'data-bucket-type="animation" data-bucket-url="' + bucketUrl + '" '
          + 'data-bucket-source="pixeltext" data-bucket-label="PixelText">BUCKET</button>';
      }
      if (result) { result.innerHTML = html; result.style.display = ''; }
    } else {
      pxStatus('Error: ' + (data.error || 'unknown'), 'error');
    }
  } catch (err) {
    pxLoaderHide();
    pxTimerCancel();
    pxStatus('Network error: ' + err.message, 'error');
  } finally {
    if (btn) btn.disabled = false;
  }
}
