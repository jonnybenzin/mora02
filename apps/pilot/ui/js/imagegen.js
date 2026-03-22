/* ═══════════════════════════════════════════════════════════════
   MORA02 PILOT — ImageGen Module v2 (Clean Rewrite 2026-03-19)
   ═══════════════════════════════════════════════════════════════
   ComfyUI: Prompt → 4 Variants → Select → Upscale/Revise/Download
   Settings stay visible. Variants + Preview appear below.
   Uses Pilot /chat/{sid} with /img commands.
   Images: mora02.local:8092/comfyui/wip/
   ───────────────────────────────────────────────────────────────
   Depends on: app.js (API_BASE, sessionId, initSession)
   ═══════════════════════════════════════════════════════════════ */

var IMG_BASE = 'http://mora02.local:8092';

var imgState = {
  images: [],
  selected: null,
  prompt: '',
  negative: '',
  flow: 'photo',
  format: '1024x1024',
  seed: null,
  generating: false,
};

/* ═══════════════════════════════════════════════════════════════
   INIT
   ═══════════════════════════════════════════════════════════════ */

function initImageGen() {
  imgState = { images: [], selected: null, prompt: '', negative: '', flow: 'photo', format: '1024x1024', seed: null, generating: false };
  imgHide('img-variants-section');
  imgHide('img-preview-section');
  imgHide('img-revision-section');
  imgShow('img-prompt-section');
  imgAutoResize('img-prompt');
  imgAutoResize('img-negative');
}

/* ═══════════════════════════════════════════════════════════════
   GENERATE
   ═══════════════════════════════════════════════════════════════ */

async function imgGenerate() {
  if (imgState.generating) return;
  if (!sessionId) {
    await initSession();
    if (!sessionId) return;
  }

  var promptEl = document.getElementById('img-prompt');
  var prompt = promptEl ? promptEl.value.trim() : '';
  if (!prompt) return;

  /* Read all settings */
  imgState.prompt = prompt;
  imgState.negative = (document.getElementById('img-negative') || {}).value || '';
  imgState.flow = (document.getElementById('img-flow') || {}).value || 'photo';
  imgState.format = (document.getElementById('img-format') || {}).value || '1024x1024';
  var steps = (document.getElementById('img-steps') || {}).value || '25';
  var cfg = (document.getElementById('img-cfg') || {}).value || '7.5';
  var seedVal = (document.getElementById('img-seed') || {}).value || '-1';

  /* Build /img command */
  var cmd = '/img ' + prompt + ' --flow ' + imgState.flow + ' --format ' + imgState.format;
  if (steps && steps !== '25') cmd += ' --steps ' + steps;
  if (cfg && cfg !== '7.5') cmd += ' --cfg ' + cfg;
  if (seedVal && seedVal !== '-1') cmd += ' --seed ' + seedVal;

  var btn = document.getElementById('img-generate-btn');
  if (btn) { btn.disabled = true; btn.textContent = 'GENERATING...'; }
  imgState.generating = true;

  try {
    var resp = await fetch(API_BASE + '/chat/' + sessionId, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: cmd }),
    });
    var data = await resp.json();

    if (data.type === 'image_variants' && data.images && data.images.length > 0) {
      imgState.images = data.images;
      imgState.seed = data.seed;
      imgState.selected = 0;

      /* Update seed field with actual seed used */
      var seedEl = document.getElementById('img-seed');
      if (seedEl) seedEl.value = data.seed;

      imgRenderVariants();
      imgRenderPreview(0);
      imgShow('img-variants-section');
      imgShow('img-preview-section');
      imgHide('img-revision-section');
    } else if (data.type === 'image_variants' && (!data.images || data.images.length === 0)) {
      imgShowStatus('No images generated — VRAM out of memory. Try restarting ComfyUI or use SD 1.5.', true);
    } else {
      imgShowStatus(data.result || data.data || 'Generation failed', true);
    }
  } catch (e) {
    imgShowStatus('Request failed: ' + e.message, true);
  }

  imgState.generating = false;
  if (btn) {
    btn.disabled = false;
    btn.innerHTML = '<svg fill="currentColor" width="16" height="16"><use href="icons/sprite.svg#i-image"/></svg> GENERATE';
  }
}

/* ═══════════════════════════════════════════════════════════════
   RENDER VARIANTS GRID
   ═══════════════════════════════════════════════════════════════ */

function imgRenderVariants() {
  var grid = document.getElementById('img-grid');
  if (!grid) return;

  var html = '';
  imgState.images.forEach(function(img, idx) {
    var url = IMG_BASE + img.url;
    html +=
      '<div class="img-thumb' + (idx === imgState.selected ? ' img-thumb-active' : '') + '" data-action="img-select" data-idx="' + idx + '">' +
        '<div class="img-thumb-num">' + (idx + 1) + '</div>' +
        '<div class="img-thumb-img" style="background:url(\'' + url + '\') center/cover"></div>' +
      '</div>';
  });
  grid.innerHTML = html;
}

/* ═══════════════════════════════════════════════════════════════
   RENDER PREVIEW
   ═══════════════════════════════════════════════════════════════ */

function imgRenderPreview(idx) {
  imgState.selected = idx;
  var img = imgState.images[idx];
  if (!img) return;

  var url = IMG_BASE + img.url;

  var preview = document.getElementById('img-preview-img');
  if (preview) preview.innerHTML = '<img src="' + url + '?t=' + Date.now() + '" data-action="img-open-lightbox" data-url="' + url + '" style="width:100%;border-radius:var(--sp-4);display:block;margin-bottom:var(--sp-16);cursor:pointer">';

  var badge = document.getElementById('img-preview-badge');
  if (badge) badge.textContent = 'v' + (idx + 1) + ' \u2014 ' + imgState.flow.toUpperCase() + ' \u2014 seed: ' + imgState.seed;

  imgClearStatus();

  /* Update grid active state */
  document.querySelectorAll('.img-thumb').forEach(function(th, i) {
    th.classList.toggle('img-thumb-active', i === idx);
  });

  /* Reset upscale button */
  var upBtn = document.getElementById('img-upscale-btn');
  if (upBtn) { upBtn.disabled = false; upBtn.style.opacity = ''; upBtn.textContent = 'UPSCALE'; }
}

/* ═══════════════════════════════════════════════════════════════
   SELECT VARIANT
   ═══════════════════════════════════════════════════════════════ */

function imgSelect(idx) {
  imgRenderPreview(idx);
  imgHide('img-revision-section');
}

/* ═══════════════════════════════════════════════════════════════
   UPSCALE
   ═══════════════════════════════════════════════════════════════ */

async function imgUpscale() {
  if (imgState.generating || !sessionId) return;
  var img = imgState.images[imgState.selected];
  if (!img) return;

  var btn = document.getElementById('img-upscale-btn');
  if (btn) { btn.disabled = true; btn.textContent = 'UPSCALING...'; }
  imgState.generating = true;

  var cmd = '/img ' + imgState.prompt +
    ' --flow ' + imgState.flow +
    ' --format ' + imgState.format +
    ' --seed ' + imgState.seed +
    ' --upscale --count 1';

  try {
    var resp = await fetch(API_BASE + '/chat/' + sessionId, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: cmd }),
    });
    var data = await resp.json();

    if (data.type === 'image_variants' && data.images && data.images.length > 0) {
      imgState.images[imgState.selected] = data.images[0];
      imgRenderVariants();
      imgRenderPreview(imgState.selected);
      imgShowStatus('\u2713 Upscaled', false);
      if (btn) { btn.textContent = 'UPSCALED'; btn.disabled = true; btn.style.opacity = '0.3'; }
    } else {
      imgShowStatus('Upscale failed — possibly VRAM issue', true);
      if (btn) { btn.disabled = false; btn.textContent = 'UPSCALE'; }
    }
  } catch (e) {
    imgShowStatus('Upscale failed: ' + e.message, true);
    if (btn) { btn.disabled = false; btn.textContent = 'UPSCALE'; }
  }

  imgState.generating = false;
}

/* ═══════════════════════════════════════════════════════════════
   REVISE
   ═══════════════════════════════════════════════════════════════ */

function imgShowRevisePanel() {
  imgShow('img-revision-section');
  var ta = document.getElementById('img-revision-text');
  if (ta) ta.focus();
}

async function imgRevise() {
  if (imgState.generating || !sessionId) return;

  var ta = document.getElementById('img-revision-text');
  var notes = ta ? ta.value.trim() : '';
  if (!notes) return;

  var btn = document.querySelector('[data-action="img-revise-generate"]');
  if (btn) { btn.disabled = true; btn.textContent = 'GENERATING REVISION...'; }
  imgState.generating = true;

  var revisedPrompt = imgState.prompt + ', ' + notes;

  /* Preserve format from settings */
  var cmd = '/img ' + revisedPrompt +
    ' --flow ' + imgState.flow +
    ' --format ' + imgState.format +
    ' --seed ' + imgState.seed;

  try {
    var resp = await fetch(API_BASE + '/chat/' + sessionId, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: cmd }),
    });
    var data = await resp.json();

    if (data.type === 'image_variants' && data.images && data.images.length > 0) {
      imgState.images = data.images;
      imgState.seed = data.seed;
      imgState.prompt = revisedPrompt;
      imgState.selected = 0;

      /* Update prompt field */
      var promptEl = document.getElementById('img-prompt');
      if (promptEl) promptEl.value = revisedPrompt;
      var seedEl = document.getElementById('img-seed');
      if (seedEl) seedEl.value = data.seed;

      imgRenderVariants();
      imgRenderPreview(0);
      imgHide('img-revision-section');
    } else {
      imgShowStatus('Revision failed — no images generated', true);
    }
  } catch (e) {
    imgShowStatus('Revision failed: ' + e.message, true);
  }

  imgState.generating = false;
  if (btn) {
    btn.disabled = false;
    btn.innerHTML = '<svg fill="currentColor" width="16" height="16"><use href="icons/sprite.svg#i-image"/></svg> GENERATE REVISION';
  }
}

/* ═══════════════════════════════════════════════════════════════
   DOWNLOAD
   ═══════════════════════════════════════════════════════════════ */

function imgDownload(btn) {
  var url = null;
  /* Check if button has stored URL (old generation) */
  if (btn && btn.dataset.url) {
    url = btn.dataset.url;
  } else {
    var img = imgState.images[imgState.selected];
    if (img) url = IMG_BASE + img.url;
  }
  if (!url) return;
  var a = document.createElement('a');
  a.href = url;
  a.download = img.filename || 'image.png';
  a.target = '_blank';
  document.body.appendChild(a);
  a.click();
  a.remove();
  imgShowStatus('\u2713 Downloaded: ' + (img.filename || ''), false);
}

/* ═══════════════════════════════════════════════════════════════
   CREATE NEW (fresh generation below current results)
   ═══════════════════════════════════════════════════════════════ */

function imgNew() {
  var wrap = document.querySelector('.tool-wrap');
  if (!wrap) return;

  /* Store current image URLs on old download buttons before reset */
  var oldDownloads = document.querySelectorAll('[data-action="img-download"]');
  oldDownloads.forEach(function(btn) {
    var idx = imgState.selected || 0;
    var img = imgState.images[idx];
    if (img) btn.dataset.url = IMG_BASE + img.url;
  });
  /* Store URLs on old thumbnails and change action to old-select */
  document.querySelectorAll('[data-action="img-select"]').forEach(function(thumb) {
    var idx = parseInt(thumb.dataset.idx);
    var img = imgState.images[idx];
    if (img) {
      thumb.dataset.action = 'img-old-select';
      thumb.dataset.url = IMG_BASE + img.url;
    }
    thumb.style.opacity = '0.6';
  });
  /* Store URLs on old preview image for lightbox */
  var oldPreviewImg = document.querySelector('#img-preview-img img');
  if (oldPreviewImg) {
    oldPreviewImg.dataset.action = 'img-open-lightbox';
    oldPreviewImg.style.cursor = 'pointer';
  }
  /* Strip ALL img-* IDs from current DOM (prevents conflicts) */
  document.querySelectorAll('[id^="img-"]').forEach(function(el) {
    el.removeAttribute('id');
  });
  /* Disable old action buttons except DOWNLOAD */
  document.querySelectorAll('[data-action="img-revise"], [data-action="img-new"], [data-action="img-revise-generate"], [data-action="img-generate"]').forEach(function(btn) {
    btn.disabled = true;
    btn.style.opacity = '0.3';
    btn.style.pointerEvents = 'none';
  });
  /* Hide old revision sections */
  document.querySelectorAll('[data-action="img-revise-generate"]').forEach(function(btn) {
    var sec = btn.closest('div');
    if (sec) sec.style.display = 'none';
  });

  /* Reset state */
  imgState = { images: [], selected: null, prompt: '', negative: '', flow: 'photo', format: '1024x1024', seed: null, generating: false };

  /* Build fresh section */
  var section = document.createElement('div');
  section.className = 'img-run';
  section.innerHTML =
    '<div class="tool-separator"></div>' +
    '<div id="img-prompt-section">' +
      '<div class="fl-row">' +
        '<div class="fl-field fl-field-grow"><select class="fl-select" id="img-flow">' +
          '<option value="photo" selected>Juggernaut XL (Photo)</option>' +
          '<option value="concept">DreamShaper XL (Concept)</option>' +
          '<option value="epic">Epic Realism XL</option>' +
          '<option value="flux">FLUX Schnell</option>' +
          '<option value="sd15">SD 1.5 (Legacy)</option></select>' +
          '<label class="fl-label">WORKFLOW</label></div>' +
        '<div class="fl-field" style="width:200px"><select class="fl-select" id="img-format">' +
          '<option value="1024x1024" selected>Square (1024)</option>' +
          '<option value="1152x768">Landscape (1152\u00d7768)</option>' +
          '<option value="768x1152">Portrait (768\u00d71152)</option></select>' +
          '<label class="fl-label">FORMAT</label></div>' +
      '</div>' +
      '<div class="fl-field"><textarea class="fl-input" id="img-prompt" rows="1" placeholder=" "></textarea><label class="fl-label">POSITIVE PROMPT</label></div>' +
      '<div class="fl-field"><textarea class="fl-input" id="img-negative" rows="1" placeholder=" "></textarea><label class="fl-label">NEGATIVE PROMPT</label></div>' +
      '<div class="fl-row">' +
        '<div class="fl-field" style="width:120px"><input class="fl-input" id="img-seed" type="text" value="-1" placeholder=" "><label class="fl-label">SEED</label></div>' +
        '<div class="fl-field" style="width:100px"><input class="fl-input" id="img-steps" type="text" value="25" placeholder=" "><label class="fl-label">STEPS</label></div>' +
        '<div class="fl-field" style="width:100px"><input class="fl-input" id="img-cfg" type="text" value="7.5" placeholder=" "><label class="fl-label">CFG</label></div>' +
      '</div>' +
      '<div class="tool-actions"><button class="btn-ico" data-action="img-generate" id="img-generate-btn">' +
        '<svg fill="currentColor" width="16" height="16"><use href="icons/sprite.svg#i-image"/></svg> GENERATE</button></div>' +
    '</div>' +
    '<div id="img-variants-section" style="display:none"><div class="img-field-lbl">4 VARIANTS \u2014 CLICK TO SELECT</div><div class="img-grid" id="img-grid"></div></div>' +
    '<div id="img-preview-section" style="display:none">' +
      '<div class="tool-result-head" id="img-preview-badge"></div><div id="img-preview-img"></div>' +
      '<div class="tool-result-btns" id="img-btns">' +
                '<button class="tool-action-btn" data-action="img-revise">REVISE</button>' +
        '<button class="tool-action-btn" data-action="img-download">DOWNLOAD</button>' +
        '<button class="tool-action-btn" data-action="img-new">CREATE NEW</button></div>' +
      '<div class="tool-result-status" id="img-status"></div></div>' +
    '<div id="img-revision-section" style="display:none">' +
      '<div class="fl-field"><textarea class="fl-input" id="img-revision-text" rows="1" placeholder=" "></textarea><label class="fl-label">REVISION NOTES</label></div>' +

      '<div class="tool-actions"><button class="btn-ico" data-action="img-revise-generate">' +
        '<svg fill="currentColor" width="16" height="16"><use href="icons/sprite.svg#i-image"/></svg> GENERATE REVISION</button></div></div>';

  wrap.appendChild(section);
  imgAutoResize('img-prompt');
  imgAutoResize('img-negative');
  section.scrollIntoView({ behavior: 'smooth' });
}

function imgAutoResize(id) {
  var el = document.getElementById(id);
  if (!el) return;
  function resize() { el.style.height = "auto"; el.style.height = el.scrollHeight + "px"; }
  el.addEventListener("input", resize);
  resize();
}

/* ═══════════════════════════════════════════════════════════════
   HELPERS
   ═══════════════════════════════════════════════════════════════ */

function imgShow(id) {
  var el = document.getElementById(id);
  if (el) el.style.display = '';
}

function imgHide(id) {
  var el = document.getElementById(id);
  if (el) el.style.display = 'none';
}

function imgShowStatus(msg, isError) {
  var el = document.getElementById('img-status');
  if (el) el.innerHTML = '<span style="color:var(--c-' + (isError ? 'red' : 'green') + ')">' + imgEsc(msg) + '</span>';
}

function imgClearStatus() {
  var el = document.getElementById('img-status');
  if (el) el.innerHTML = '';
}

function imgEsc(str) {
  var div = document.createElement('div');
  div.textContent = str;
  return div.innerHTML;
}

/* ═══════════════════════════════════════════════════════════════
   EVENT DELEGATION
   ═══════════════════════════════════════════════════════════════ */

document.addEventListener('click', function(e) {
  var target = e.target.closest('[data-action]');
  if (!target) return;

  switch (target.dataset.action) {
    case 'img-generate':        imgGenerate(); break;
    case 'img-select':          imgSelect(parseInt(target.dataset.idx)); break;
    case 'img-upscale':         imgUpscale(); break;
    case 'img-revise':          imgShowRevisePanel(); break;
    case 'img-revise-generate': imgRevise(); break;
    case 'img-download':        imgDownload(target); break;
    case 'img-old-select':
      /* Switch preview image in old generation */
      var oldPreview = target.closest('.img-run, .tool-wrap');
      if (oldPreview) {
        var previewDiv = oldPreview.querySelector('[style*="width:100%"]') ||
                         oldPreview.querySelectorAll('img[style]');
        /* Find the large preview img in this section */
        oldPreview.querySelectorAll('img').forEach(function(img) {
          if (img.style.width === '100%' || img.style.cssText.includes('width:100%')) {
            img.src = target.dataset.url + '?t=' + Date.now();
          }
        });
        /* Update active thumbnail */
        var grid = target.closest('.img-grid');
        if (grid) {
          grid.querySelectorAll('.img-thumb').forEach(function(th) { th.classList.remove('img-thumb-active'); });
          target.closest('.img-thumb').classList.add('img-thumb-active');
        }
        /* Update download button URL */
        var dlBtn = oldPreview.querySelector('[data-action="img-download"]');
        if (dlBtn) dlBtn.dataset.url = target.dataset.url;
      }
      break;
    case 'img-new':             imgNew(); break;
    case 'img-open-lightbox':
      var imgUrl = target.dataset.url || target.src;
      if (imgUrl && typeof openLightbox === 'function') openLightbox(imgUrl);
      break;
  }
});
