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
  style: '',
  styleWeight: 0.7,
};

/* ═══════════════════════════════════════════════════════════════
   INIT
   ═══════════════════════════════════════════════════════════════ */

/* Flows where seed/steps/cfg/negative are irrelevant (API-based) */
var IMG_API_FLOWS = ['nanban'];

function initImageGen() {
  /* Deactivate any previous image gen instances (strip their IDs to prevent conflicts) */
  document.querySelectorAll('[id="img-generate-btn"]').forEach(function(btn, idx, all) {
    if (idx < all.length - 1) {
      var w = btn.closest('.tool-wrap');
      if (w) {
        w.querySelectorAll('[id^="img-"], [id^="sp-"]').forEach(function(el) { el.removeAttribute('id'); });
        w.querySelectorAll('[data-action^="img-"], [data-action^="sp-"]').forEach(function(b) {
          b.disabled = true; b.style.opacity = '0.3'; b.style.pointerEvents = 'none';
        });
      }
    }
  });

  imgState = { images: [], selected: null, prompt: '', negative: '', flow: 'photo', format: '1024x1024', seed: null, generating: false, style: '', styleWeight: 0.7 };
  imgHide('img-variants-section');
  imgHide('img-preview-section');
  imgHide('img-revision-section');
  imgShow('img-prompt-section');
  /* Hide settings toggle + collapse additional settings on fresh init */
  var settingsToggle = document.getElementById('img-settings-toggle');
  if (settingsToggle) { settingsToggle.style.display = 'none'; settingsToggle.classList.remove('open'); }
  var additionalBody = document.getElementById('img-additional-body');
  if (additionalBody) additionalBody.style.display = 'none';
  var additionalToggle = document.getElementById('img-additional-toggle');
  if (additionalToggle) additionalToggle.classList.remove('open');
  imgAutoResize('img-prompt');
  imgAutoResize('img-negative');
  imgBindFlowToggle();
  spLoadPacks();
  spBindWeightSlider();
  spLoadQuickFolders();
}

function imgBindFlowToggle() {
  var sel = document.getElementById('img-flow');
  if (!sel) return;
  sel.addEventListener('change', function() { imgToggleApiFields(sel.value); });
  imgToggleApiFields(sel.value);
}

function imgToggleApiFields(flow) {
  var isApi = IMG_API_FLOWS.indexOf(flow) !== -1;
  ['img-seed', 'img-steps', 'img-cfg', 'img-negative'].forEach(function(id) {
    var el = document.getElementById(id);
    if (!el) return;
    var field = el.closest('.fl-field');
    if (!field) return;
    if (isApi) { field.classList.add('fl-disabled'); }
    else { field.classList.remove('fl-disabled'); }
  });
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

  /* Read style */
  var styleEl = document.getElementById('img-style');
  imgState.style = styleEl ? styleEl.value : '';
  var weightSlider = document.getElementById('sp-weight-slider');
  imgState.styleWeight = weightSlider ? parseFloat(weightSlider.value) / 100 : 0.7;

  /* Build /img command */
  var cmd = '/img ' + prompt + ' --flow ' + imgState.flow + ' --format ' + imgState.format;
  if (steps && steps !== '25') cmd += ' --steps ' + steps;
  if (cfg && cfg !== '7.5') cmd += ' --cfg ' + cfg;
  if (seedVal && seedVal !== '-1') cmd += ' --seed ' + seedVal;
  if (imgState.style) {
    var weightTypeEl = document.getElementById('sp-weight-type');
    var weightType = weightTypeEl ? weightTypeEl.value : 'style transfer';
    cmd += ' --style ' + imgState.style + ' --style-weight ' + imgState.styleWeight + ' --style-type ' + weightType.replace(/ /g, '_');
  }

  var btn = document.getElementById('img-generate-btn');
  if (btn) { btn.disabled = true; btn.textContent = 'GENERATING...'; }
  imgState.generating = true;

  /* Overlay covers entire bubble — settings stay visible but dimmed */
  imgLoaderShow();

  try {
    var resp = await fetch(API_BASE + '/chat/' + sessionId, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: cmd }),
    });
    var data = await resp.json();
    imgLoaderHide();

    if (data.type === 'image_variants' && data.images && data.images.length > 0) {
      imgState.images = data.images;
      imgState.seed = data.seed;
      imgState.selected = 0;

      /* Update seed field with actual seed used */
      var seedEl = document.getElementById('img-seed');
      if (seedEl) seedEl.value = data.seed;

      /* Collapse settings, show toggle */
      imgHide('img-prompt-section');
      var toggle = document.getElementById('img-settings-toggle');
      if (toggle) { toggle.style.display = ''; toggle.classList.remove('open'); }

      imgRenderVariants();
      imgRenderPreview(0);
      imgShow('img-variants-section');
      imgShow('img-preview-section');
      imgHide('img-revision-section');
      if (typeof loadMonthlyCost === 'function') loadMonthlyCost();
    } else if (data.type === 'image_variants' && (!data.images || data.images.length === 0)) {
      imgShowStatus('No images generated — VRAM out of memory. Try restarting ComfyUI or use SD 1.5.', true);
    } else {
      imgShowStatus(data.result || data.data || 'Generation failed', true);
    }
  } catch (e) {
    imgLoaderHide();
    imgShowStatus('Request failed: ' + e.message, true);
  }

  imgState.generating = false;
  if (btn) {
    btn.disabled = false;
    /* After first generation, button becomes REGENERATE */
    var label = imgState.images.length > 0 ? 'REGENERATE' : 'GENERATE';
    btn.innerHTML = '<svg fill="currentColor" width="16" height="16"><use href="icons/sprite.svg#i-image"/></svg> ' + label;
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
  imgLoaderShow();

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

    imgLoaderHide();
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
    imgLoaderHide();
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
  imgLoaderShow();

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

    imgLoaderHide();
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
    imgLoaderHide();
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
  /* Find the ACTIVE tool-wrap (the one with current generate button) */
  var genBtn = document.getElementById('img-generate-btn');
  var wrap = genBtn ? genBtn.closest('.tool-wrap') : document.querySelector('.tool-wrap');
  if (!wrap) return;

  /* Capture info for collapsed bar before stripping IDs */
  var thumbUrl = '';
  var selectedImg = imgState.images[imgState.selected];
  if (selectedImg) thumbUrl = IMG_BASE + selectedImg.url;
  var promptText = imgState.prompt || 'Image generation';
  var flowText = (imgState.flow || 'photo').toUpperCase();

  /* Store URLs on old download buttons */
  document.querySelectorAll('[data-action="img-download"]').forEach(function(btn) {
    var img = imgState.images[imgState.selected || 0];
    if (img) btn.dataset.url = IMG_BASE + img.url;
  });
  /* Store URLs on old thumbnails, change action */
  document.querySelectorAll('[data-action="img-select"]').forEach(function(thumb) {
    var idx = parseInt(thumb.dataset.idx);
    var img = imgState.images[idx];
    if (img) {
      thumb.dataset.action = 'img-old-select';
      thumb.dataset.url = IMG_BASE + img.url;
    }
  });

  /* Detect chat context vs standalone */
  var isChat = !!wrap.closest('.post-widget');
  if (isChat) {
    imgNewChat(wrap, thumbUrl, promptText, flowText);
  } else {
    imgNewStandalone(wrap, thumbUrl, promptText, flowText);
  }
}

/* ── CREATE NEW: Chat context (collapsed = own chat bubble) ───── */

function imgNewChat(wrap, thumbUrl, promptText, flowText) {
  /* Hide the ENTIRE old chat bubble */
  var oldMsgBot = wrap.closest('.msg-bot');
  if (oldMsgBot) oldMsgBot.style.display = 'none';

  /* Build static read-only snapshot: just the selected image + actions */
  var snapshotHtml = '';
  if (imgState.images.length > 0) {
    var selImg = imgState.images[imgState.selected || 0];
    if (selImg) {
      var selUrl = IMG_BASE + selImg.url;
      snapshotHtml += '<div class="tool-result-head">' +
        'v' + ((imgState.selected || 0) + 1) + ' \u2014 ' + flowText + ' \u2014 seed: ' + (imgState.seed || '?') + '</div>';
      snapshotHtml += '<img src="' + selUrl + '" style="width:100%;border-radius:var(--sp-4);display:block;margin-bottom:var(--sp-10)">';
      snapshotHtml += '<div class="tool-result-btns">' +
        '<button class="tool-action-btn" data-action="img-download" data-url="' + selUrl + '">DOWNLOAD</button>' +
        '<button class="tool-action-btn bucket-add-btn" data-action="img-bucket" data-url="' + selUrl + '">ADD TO BUCKET</button>' +
        '</div>';
    }
  }

  /* Create collapsed bar as a new chat bubble with proper frame */
  var barHtml = msgHeadHTML('IMAGE GEN', 'var(--tx-muted)') +
    '<div class="msg-body"><div class="post-widget" style="border:1px solid #444;border-radius:8px;padding:var(--sp-10)">' +
      '<div class="tool-collapsed">' +
        '<div class="tool-collapsed-bar" data-action="img-expand-collapsed">' +
          (thumbUrl ? '<img class="tool-collapsed-thumb" src="' + thumbUrl + '">' : '') +
          '<div class="tool-collapsed-info">' +
            '<div class="tool-collapsed-meta">' + imgEsc(promptText.length > 80 ? promptText.substring(0, 80) + '\u2026' : promptText) + '</div>' +
          '</div>' +
          '<button class="tool-action-btn bucket-add-btn" data-action="img-bucket" data-url="' + (thumbUrl || '') + '" style="flex-shrink:0">ADD TO BUCKET</button>' +
          '<span class="tool-collapse-arrow" style="flex-shrink:0">&#9654;</span>' +
        '</div>' +
        '<div class="tool-collapsed-content" style="display:none">' + snapshotHtml + '</div>' +
      '</div>' +
    '</div></div>';

  appendBotEl('system', barHtml);

  /* Reset state + render fresh tool widget as new chat bubble */
  imgState = { images: [], selected: null, prompt: '', negative: '', flow: 'photo', format: '1024x1024', seed: null, generating: false, style: '', styleWeight: 0.7 };
  renderToolWidget('imagegen', 'initImageGen');
}

/* ── CREATE NEW: Standalone page (collapsed inside tool-wrap) ─── */

function imgNewStandalone(wrap, thumbUrl, promptText, flowText) {
  /* Build static read-only snapshot: just the selected image + actions */
  var snapshotHtml = '';
  if (imgState.images.length > 0) {
    var selImg = imgState.images[imgState.selected || 0];
    if (selImg) {
      var selUrl = IMG_BASE + selImg.url;
      snapshotHtml += '<div class="tool-result-head">v' + ((imgState.selected || 0) + 1) + ' \u2014 ' + flowText + ' \u2014 seed: ' + (imgState.seed || '?') + '</div>';
      snapshotHtml += '<img src="' + selUrl + '" style="width:100%;border-radius:var(--sp-4);display:block;margin-bottom:var(--sp-10)">';
      snapshotHtml += '<div class="tool-result-btns">' +
        '<button class="tool-action-btn" data-action="img-download" data-url="' + selUrl + '">DOWNLOAD</button>' +
        '<button class="tool-action-btn bucket-add-btn" data-action="img-bucket" data-url="' + selUrl + '">BUCKET</button></div>';
    }
  }

  /* Remove old interactive content from tool-wrap */
  var toRemove = ['img-settings-toggle', 'img-prompt-section', 'img-result-area'];
  toRemove.forEach(function(id) { var el = document.getElementById(id); if (el) el.remove(); });

  /* Build collapsed bar with static snapshot */
  var collapsed = document.createElement('div');
  collapsed.className = 'tool-collapsed';
  collapsed.innerHTML =
    '<div class="tool-collapsed-bar" data-action="img-expand-collapsed">' +
      (thumbUrl ? '<img class="tool-collapsed-thumb" src="' + thumbUrl + '">' : '') +
      '<div class="tool-collapsed-info">' +
        '<div class="tool-collapsed-title">IMAGE GEN \u2014 ' + imgEsc(flowText) + '</div>' +
        '<div class="tool-collapsed-meta">' + imgEsc(promptText.length > 80 ? promptText.substring(0, 80) + '\u2026' : promptText) + '</div>' +
      '</div>' +
      '<span class="tool-collapse-arrow">&#9654;</span>' +
    '</div>' +
    '<div class="tool-collapsed-content" style="display:none">' + snapshotHtml + '</div>';

  var lastCollapsed = wrap.querySelector('.tool-collapsed:last-of-type');
  var insertAfter = lastCollapsed || wrap.querySelector('.tool-desc');
  if (insertAfter) insertAfter.after(collapsed);

  /* ── Reset state ────────────────────────────────────────── */
  imgState = { images: [], selected: null, prompt: '', negative: '', flow: 'photo', format: '1024x1024', seed: null, generating: false, style: '', styleWeight: 0.7 };

  /* ── Build fresh section ────────────────────────────────── */
  var section = document.createElement('div');
  section.className = 'img-run';
  section.innerHTML =
    '<div class="tool-separator"></div>' +
    '<div class="tool-collapse-head" id="img-settings-toggle" data-action="img-toggle-settings" style="display:none">' +
      '<span class="tool-collapse-arrow">&#9654;</span> SETTINGS &amp; REGENERATION</div>' +
    '<div id="img-prompt-section">' +
      '<div class="fl-grid fl-grid-2">' +
        '<div class="fl-field"><select class="fl-select" id="img-flow">' +
          '<option value="photo" selected>Juggernaut XL (Photo)</option>' +
          '<option value="concept">DreamShaper XL (Concept)</option>' +
          '<option value="epic">Epic Realism XL</option>' +
          '<option value="nanban">Nano Banana 2 (Gemini)</option>' +
          '<option value="flux">FLUX Schnell</option>' +
          '<option value="sd15">SD 1.5 (Legacy)</option></select>' +
          '<label class="fl-label">WORKFLOW</label></div>' +
        '<div class="fl-field"><select class="fl-select" id="img-format">' +
          '<option value="1024x1024" selected>Square (1024)</option>' +
          '<option value="1152x768">Landscape (1152\u00d7768)</option>' +
          '<option value="768x1152">Portrait (768\u00d71152)</option></select>' +
          '<label class="fl-label">FORMAT</label></div>' +
      '</div>' +
      '<div class="sp-row">' +
        '<div class="fl-field fl-field-grow" style="margin-bottom:0"><select class="fl-select" id="img-style"><option value="" selected>No Style Reference</option></select>' +
          '<label class="fl-label">STYLE REFERENCE</label></div>' +
        '<button class="sp-manage-btn" id="sp-manage-btn" data-action="sp-open-modal" title="Manage Styles">+</button>' +
      '</div>' +
      '<div class="sp-active-info" id="sp-active-info" style="display:none">' +
        '<span id="sp-active-name"></span><span id="sp-active-count"></span>' +
        '<input type="range" id="sp-weight-slider" min="0" max="100" value="80" class="sp-slider">' +
        '<span id="sp-weight-label" class="sp-weight-lbl">0.8</span>' +
        '<select class="sp-type-select" id="sp-weight-type">' +
          '<option value="style transfer">Style Transfer</option>' +
          '<option value="style transfer precise">Precise Style</option>' +
          '<option value="style and composition">Style + Composition</option>' +
          '<option value="linear">Linear</option></select>' +
      '</div>' +
      '<div class="fl-field"><textarea class="fl-input" id="img-prompt" rows="1" placeholder=" "></textarea><label class="fl-label">POSITIVE PROMPT</label></div>' +
      '<div class="tool-collapse-head" id="img-additional-toggle" data-action="img-toggle-additional">' +
        '<span class="tool-collapse-arrow">&#9654;</span> ADDITIONAL SETTINGS</div>' +
      '<div id="img-additional-body" class="tool-collapse-body" style="display:none">' +
        '<div class="fl-field"><textarea class="fl-input" id="img-negative" rows="1" placeholder=" "></textarea><label class="fl-label">NEGATIVE PROMPT</label></div>' +
        '<div class="fl-grid fl-grid-3">' +
          '<div class="fl-field"><input class="fl-input" id="img-seed" type="text" value="-1" placeholder=" "><label class="fl-label">SEED</label></div>' +
          '<div class="fl-field"><input class="fl-input" id="img-steps" type="text" value="25" placeholder=" "><label class="fl-label">STEPS</label></div>' +
          '<div class="fl-field"><input class="fl-input" id="img-cfg" type="text" value="7.5" placeholder=" "><label class="fl-label">CFG</label></div>' +
        '</div>' +
      '</div>' +
      '<div class="tool-actions"><button class="btn-ico" data-action="img-generate" id="img-generate-btn">' +
        '<svg fill="currentColor" width="16" height="16"><use href="icons/sprite.svg#i-image"/></svg> GENERATE</button></div>' +
    '</div>' +
    '<div id="img-result-area">' +
      '<div id="img-variants-section" style="display:none"><div class="img-field-lbl">4 VARIANTS \u2014 CLICK TO SELECT</div><div class="img-grid" id="img-grid"></div></div>' +
      '<div id="img-preview-section" style="display:none">' +
        '<div class="tool-result-head" id="img-preview-badge"></div><div id="img-preview-img"></div>' +
        '<div class="tool-result-btns" id="img-btns">' +
          '<button class="tool-action-btn" data-action="img-revise">REVISE</button>' +
          '<button class="tool-action-btn" data-action="img-download">DOWNLOAD</button>' +
          '<button class="tool-action-btn" data-action="img-new">CREATE NEW</button>' +
          '<button class="tool-action-btn bucket-add-btn" data-action="img-bucket">BUCKET</button></div>' +
        '<div class="tool-result-status" id="img-status"></div></div>' +
      '<div id="img-revision-section" style="display:none">' +
        '<div class="fl-field"><textarea class="fl-input" id="img-revision-text" rows="1" placeholder=" "></textarea><label class="fl-label">REVISION NOTES</label></div>' +
        '<div class="tool-actions"><button class="btn-ico" data-action="img-revise-generate">' +
          '<svg fill="currentColor" width="16" height="16"><use href="icons/sprite.svg#i-image"/></svg> GENERATE REVISION</button></div></div>' +
    '</div>';

  wrap.appendChild(section);
  imgAutoResize('img-prompt');
  imgAutoResize('img-negative');
  imgBindFlowToggle();
  spLoadPacks();
  spBindWeightSlider();
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
   M2 LOADER
   ═══════════════════════════════════════════════════════════════ */

function imgLoaderShow() {
  var existing = document.getElementById('img-m2-loader-wrap');
  if (existing) return;
  /* Overlay covers entire tool-wrap (the whole chat bubble content) */
  var genBtn = document.getElementById('img-generate-btn');
  var wrap = genBtn ? genBtn.closest('.tool-wrap') : null;
  if (!wrap) { wrap = document.getElementById('img-result-area'); if (wrap) wrap = wrap.closest('.tool-wrap'); }
  if (!wrap) wrap = document.querySelector('.tool-wrap');
  if (!wrap) return;
  wrap.style.position = 'relative';
  var overlay = document.createElement('div');
  overlay.id = 'img-m2-loader-wrap';
  overlay.className = 'tool-gen-overlay';
  overlay.innerHTML = '<div class="tool-gen-overlay-label">GENERATING</div><div class="m2-loader-m" id="img-m2-loader"></div>';
  wrap.appendChild(overlay);
  startM2(document.getElementById('img-m2-loader'), 9, 35);
}

function imgLoaderHide() {
  stopM2();
  var el = document.getElementById('img-m2-loader-wrap');
  if (el) { el.querySelector('.m2-loader-m').innerHTML = ''; el.remove(); }
}

/* ═══════════════════════════════════════════════════════════════
   COLLAPSIBLE TOGGLES
   ═══════════════════════════════════════════════════════════════ */

function imgToggleAdditional() {
  var body = document.getElementById('img-additional-body');
  var head = document.getElementById('img-additional-toggle');
  if (!body || !head) return;
  var isOpen = body.style.display !== 'none';
  body.style.display = isOpen ? 'none' : '';
  head.classList.toggle('open', !isOpen);
}

function imgToggleSettings() {
  var head = document.getElementById('img-settings-toggle');
  var section = document.getElementById('img-prompt-section');
  if (!head || !section) return;
  var isOpen = section.style.display !== 'none';
  section.style.display = isOpen ? 'none' : '';
  head.classList.toggle('open', !isOpen);
}

function imgExpandCollapsed(bar) {
  var collapsed = bar.closest('.tool-collapsed');
  if (!collapsed) return;
  var content = collapsed.querySelector('.tool-collapsed-content');
  var arrow = bar.querySelector('.tool-collapse-arrow');
  if (!content) return;
  var isOpen = content.style.display !== 'none';
  content.style.display = isOpen ? 'none' : '';
  if (arrow) arrow.style.transform = isOpen ? '' : 'rotate(90deg)';
  /* Toggle class to hide bar thumbnail + bar bucket button when expanded */
  collapsed.classList.toggle('tool-collapsed-open', !isOpen);
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
   ADD TO BUCKET
   ═══════════════════════════════════════════════════════════════ */

function imgAddToBucket(btn) {
  /* Find the URL: either from data-url on old gens, or current selected */
  var url = btn && btn.dataset.url;
  if (!url) {
    var img = imgState.images[imgState.selected];
    if (img) url = IMG_BASE + img.url;
  }
  if (!url) return;
  bucketAdd({
    type: 'image',
    url: url,
    thumb: url,
    source: 'imagegen',
    label: (imgState.prompt || 'image').substring(0, 60)
  });
  btn.classList.add('bucket-add-ok');
  btn.textContent = 'ADDED';
  setTimeout(function() { btn.classList.remove('bucket-add-ok'); btn.textContent = 'BUCKET'; }, 800);
}

/* ═══════════════════════════════════════════════════════════════
   STYLE PACKS
   ═══════════════════════════════════════════════════════════════ */

var spUploadFiles = [];

async function spLoadPacks() {
  try {
    var resp = await fetch(API_BASE + '/api/styles');
    var data = await resp.json();
    var sel = document.getElementById('img-style');
    if (!sel) return;
    /* Keep first option */
    sel.innerHTML = '<option value="">No Style Reference</option>';
    (data.results || []).forEach(function(p) {
      var opt = document.createElement('option');
      opt.value = p.name;
      opt.textContent = p.name + ' (' + (p.image_count || '?') + ' imgs)';
      opt.dataset.id = p.id;
      opt.dataset.weight = p.style_weight || '0.7';
      sel.appendChild(opt);
    });
    /* Bind change */
    sel.onchange = function() { spOnStyleChange(sel); };
  } catch(e) { console.warn('[sp] load error:', e); }
}

function spOnStyleChange(sel) {
  var info = document.getElementById('sp-active-info');
  if (!sel.value) {
    if (info) info.style.display = 'none';
    imgState.style = '';
    return;
  }
  imgState.style = sel.value;
  var opt = sel.options[sel.selectedIndex];
  var nameEl = document.getElementById('sp-active-name');
  var countEl = document.getElementById('sp-active-count');
  if (nameEl) nameEl.textContent = sel.value;
  if (countEl) countEl.textContent = opt.textContent.match(/\(.*\)/)?.[0] || '';
  /* Restore weight from pack */
  var w = parseFloat(opt.dataset.weight || '0.7');
  var slider = document.getElementById('sp-weight-slider');
  var label = document.getElementById('sp-weight-label');
  if (slider) slider.value = Math.round(w * 100);
  if (label) label.textContent = w.toFixed(1);
  imgState.styleWeight = w;
  if (info) info.style.display = '';
}

function spBindWeightSlider() {
  var slider = document.getElementById('sp-weight-slider');
  if (!slider) return;
  slider.addEventListener('input', function() {
    var v = parseFloat(slider.value) / 100;
    imgState.styleWeight = v;
    var label = document.getElementById('sp-weight-label');
    if (label) label.textContent = v.toFixed(1);
  });
}

/* ─── Modal ──────────────────────────────────────────────────── */

function spOpenModal() {
  var overlay = document.getElementById('sp-overlay');
  if (overlay) overlay.classList.add('sp-open');
  spRenderList();
  spResetForm();
}

function spCloseModal() {
  var overlay = document.getElementById('sp-overlay');
  if (overlay) overlay.classList.remove('sp-open');
}

async function spRenderList() {
  var list = document.getElementById('sp-list');
  if (!list) return;
  try {
    var resp = await fetch(API_BASE + '/api/styles');
    var data = await resp.json();
    var packs = data.results || [];
    if (packs.length === 0) {
      list.innerHTML = '<div class="sp-list-empty">No style packs yet</div>';
      return;
    }
    list.innerHTML = packs.map(function(p) {
      return '<div class="sp-list-item">' +
        '<span class="sp-list-name">' + imgEsc(p.name) + '</span>' +
        '<span class="sp-list-count">' + (p.image_count || '?') + ' imgs</span>' +
        '<button class="sp-list-del" data-action="sp-delete" data-id="' + p.id + '" title="Delete"><svg fill="currentColor"><use href="icons/sprite.svg#i-close"/></svg></button>' +
      '</div>';
    }).join('');
  } catch(e) {
    list.innerHTML = '<div class="sp-list-empty">Error loading packs</div>';
  }
}

function spResetForm() {
  var name = document.getElementById('sp-name');
  var path = document.getElementById('sp-folder-path');
  var result = document.getElementById('sp-scan-result');
  var grid = document.getElementById('sp-preview-grid');
  var saveBtn = document.getElementById('sp-save-btn');
  var uploadCount = document.getElementById('sp-upload-count');
  if (name) name.value = '';
  if (path) path.value = '';
  if (result) { result.textContent = ''; result.className = 'sp-scan-result'; }
  if (grid) grid.innerHTML = '';
  if (saveBtn) saveBtn.disabled = true;
  if (uploadCount) uploadCount.textContent = '';
  spUploadFiles = [];
}

/* ─── Source toggle ──────────────────────────────────────────── */

function spToggleFolder() {
  document.getElementById('sp-toggle-folder').classList.add('sp-toggle-active');
  document.getElementById('sp-toggle-upload').classList.remove('sp-toggle-active');
  document.getElementById('sp-folder-input').style.display = '';
  document.getElementById('sp-upload-input').style.display = 'none';
}

function spToggleUpload() {
  document.getElementById('sp-toggle-upload').classList.add('sp-toggle-active');
  document.getElementById('sp-toggle-folder').classList.remove('sp-toggle-active');
  document.getElementById('sp-folder-input').style.display = 'none';
  document.getElementById('sp-upload-input').style.display = '';
}

/* ─── Scan folder ────────────────────────────────────────────── */

async function spScanFolder() {
  var pathEl = document.getElementById('sp-folder-path');
  var resultEl = document.getElementById('sp-scan-result');
  var gridEl = document.getElementById('sp-preview-grid');
  var saveBtn = document.getElementById('sp-save-btn');
  var path = pathEl ? pathEl.value.trim() : '';
  if (!path) return;

  resultEl.textContent = 'Scanning...';
  resultEl.className = 'sp-scan-result';

  try {
    var resp = await fetch(API_BASE + '/api/styles/scan-folder?path=' + encodeURIComponent(path));
    var data = await resp.json();
    if (!data.exists) {
      resultEl.textContent = 'Folder not found';
      resultEl.className = 'sp-scan-result sp-scan-err';
      if (saveBtn) saveBtn.disabled = true;
      if (gridEl) gridEl.innerHTML = '';
      return;
    }
    resultEl.textContent = data.count + ' images found';
    resultEl.className = 'sp-scan-result sp-scan-ok';
    if (saveBtn) saveBtn.disabled = !data.count || !document.getElementById('sp-name').value.trim();

    /* Show preview thumbnails (first 8) */
    if (gridEl && data.images && data.images.length) {
      /* Build a URL-safe base path for nginx serving */
      var basePath = path.startsWith('/data/styles/') ? path.replace('/data/styles/', '') : path;
      gridEl.innerHTML = data.images.slice(0, 8).map(function(fname) {
        return '<div class="sp-preview-thumb" style="background-image:url(\'/api/styles/scan-folder?path=' + encodeURIComponent(path) + '\')"></div>';
      }).join('');
      /* Note: previews won't load until we have a proper image serving endpoint — placeholder for now */
      gridEl.innerHTML = data.images.slice(0, 8).map(function() {
        return '<div class="sp-preview-thumb" style="background:var(--c-grey2)"></div>';
      }).join('');
    }
  } catch(e) {
    resultEl.textContent = 'Scan failed: ' + e.message;
    resultEl.className = 'sp-scan-result sp-scan-err';
  }
}

/* ─── Quick folders ──────────────────────────────────────────── */

async function spLoadQuickFolders() {
  try {
    var resp = await fetch(API_BASE + '/api/styles/list-folders');
    var data = await resp.json();
    var el = document.getElementById('sp-quick-folders');
    if (!el || !data.folders || !data.folders.length) return;
    el.innerHTML = data.folders.map(function(f) {
      return '<button class="sp-quick-folder" data-action="sp-pick-folder" data-path="' + imgEsc(f.path) + '">' +
        imgEsc(f.name) + ' (' + f.image_count + ')' +
      '</button>';
    }).join('');
  } catch(e) { /* ignore */ }
}

function spPickFolder(path) {
  var pathEl = document.getElementById('sp-folder-path');
  if (pathEl) pathEl.value = path;
  spScanFolder();
}

/* ─── Upload handling ────────────────────────────────────────── */

function spInitUpload() {
  var fileInput = document.getElementById('sp-file-input');
  if (fileInput) {
    fileInput.click();
    fileInput.onchange = function() {
      spUploadFiles = Array.from(fileInput.files);
      var countEl = document.getElementById('sp-upload-count');
      if (countEl) countEl.textContent = spUploadFiles.length + ' files selected';
      var saveBtn = document.getElementById('sp-save-btn');
      if (saveBtn) saveBtn.disabled = !spUploadFiles.length || !document.getElementById('sp-name').value.trim();
    };
  }
}

/* ─── Save ───────────────────────────────────────────────────── */

async function spSave() {
  var nameEl = document.getElementById('sp-name');
  var name = nameEl ? nameEl.value.trim() : '';
  if (!name) return;

  var saveBtn = document.getElementById('sp-save-btn');
  if (saveBtn) { saveBtn.disabled = true; saveBtn.textContent = 'SAVING...'; }

  var isFolderMode = document.getElementById('sp-toggle-folder').classList.contains('sp-toggle-active');

  try {
    var resp, data;
    if (isFolderMode) {
      var pathEl = document.getElementById('sp-folder-path');
      var path = pathEl ? pathEl.value.trim() : '';
      resp = await fetch(API_BASE + '/api/styles', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: name, source_type: 'folder', source_path: path }),
      });
      data = await resp.json();
    } else {
      /* Upload mode: send files as multipart/form-data */
      var formData = new FormData();
      spUploadFiles.forEach(function(f) { formData.append('files', f); });
      resp = await fetch(API_BASE + '/api/styles/upload?name=' + encodeURIComponent(name), {
        method: 'POST',
        body: formData,
      });
      data = await resp.json();
    }

    if (data.error) {
      alert('Error: ' + data.error);
      if (saveBtn) { saveBtn.disabled = false; saveBtn.textContent = 'SAVE STYLE PACK'; }
      return;
    }

    /* Refresh dropdown + modal list */
    await spLoadPacks();
    spRenderList();
    spResetForm();
    if (saveBtn) saveBtn.textContent = 'SAVE STYLE PACK';
  } catch(e) {
    alert('Save failed: ' + e.message);
    if (saveBtn) { saveBtn.disabled = false; saveBtn.textContent = 'SAVE STYLE PACK'; }
  }
}

/* ─── Delete ─────────────────────────────────────────────────── */

async function spDelete(id) {
  if (!confirm('Delete this style pack?')) return;
  try {
    await fetch(API_BASE + '/api/styles/' + id, { method: 'DELETE' });
    await spLoadPacks();
    spRenderList();
  } catch(e) { console.warn('[sp] delete error:', e); }
}

/* ─── Enable save when name is filled ────────────────────────── */

document.addEventListener('input', function(e) {
  if (e.target.id === 'sp-name') {
    var saveBtn = document.getElementById('sp-save-btn');
    if (!saveBtn) return;
    var hasName = e.target.value.trim().length > 0;
    var isFolderMode = document.getElementById('sp-toggle-folder').classList.contains('sp-toggle-active');
    var resultEl = document.getElementById('sp-scan-result');
    var hasScan = resultEl && resultEl.classList.contains('sp-scan-ok');
    var hasUpload = spUploadFiles.length > 0;
    saveBtn.disabled = !hasName || (isFolderMode ? !hasScan : !hasUpload);
  }
});

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
    case 'img-bucket':          imgAddToBucket(target); break;
    case 'img-toggle-additional': imgToggleAdditional(); break;
    case 'img-toggle-settings':   imgToggleSettings(); break;
    case 'img-expand-collapsed':  imgExpandCollapsed(target); break;
    case 'img-open-lightbox':
      var imgUrl = target.dataset.url || target.src;
      if (imgUrl && typeof openLightbox === 'function') openLightbox(imgUrl);
      break;
    /* Style Pack actions */
    case 'sp-open-modal':       spOpenModal(); break;
    case 'sp-close-modal':      spCloseModal(); break;
    case 'sp-toggle-folder':    spToggleFolder(); break;
    case 'sp-toggle-upload':    spToggleUpload(); break;
    case 'sp-scan-folder':      spScanFolder(); break;
    case 'sp-pick-folder':      spPickFolder(target.dataset.path); break;
    case 'sp-drop-click':       spInitUpload(); break;
    case 'sp-save':             spSave(); break;
    case 'sp-delete':           spDelete(target.dataset.id); break;
  }
});
