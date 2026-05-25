/* ═══════════════════════════════════════════════════════════════
   MORA02 PILOT — Expander Module
   ═══════════════════════════════════════════════════════════════
   Outpaint / expand images to 1920x1920 via FLUX.
   Drop image from bucket → expand → download/bucket.
   ═══════════════════════════════════════════════════════════════ */

var IMG_BASE_EXP = 'http://mora02.local:8092';

var expState = {
  imageUrl: '',
  imageName: '',
  resultUrl: '',
  generating: false,
};

/* ═══════════════════════════════════════════════════════════════
   INIT
   ═══════════════════════════════════════════════════════════════ */

function initExpander() {
  expState = { imageUrl: '', imageName: '', resultUrl: '', generating: false };
  expHide('exp-result-section');
  expShow('exp-input-section');
  expHide('exp-preview');
  expHide('exp-settings-body');
  var toggle = document.getElementById('exp-settings-toggle');
  if (toggle) toggle.classList.remove('open');
  var btn = document.getElementById('exp-generate-btn');
  if (btn) { btn.disabled = true; btn.innerHTML = '<svg fill="currentColor" width="16" height="16"><use href="icons/sprite.svg#i-image"/></svg> EXPAND'; }
  expAutoResize('exp-prompt');
  expBindUpload();
}

function expBindUpload() {
  var zone = document.getElementById('exp-drop-zone');
  if (!zone) return;

  /* Bucket drag & drop */
  zone.setAttribute('data-bucket-accepts', 'image');
  zone.addEventListener('dragover', function(e) {
    e.preventDefault();
    if (e.dataTransfer.types && e.dataTransfer.types.indexOf('application/x-bucket-item') !== -1) {
      var accepted = typeof bucketDragItem !== 'undefined' && bucketDragItem && bucketDragItem.type === 'image';
      zone.classList.toggle('bucket-drop-active', accepted);
      zone.classList.toggle('bucket-drop-reject', !accepted);
      e.dataTransfer.dropEffect = accepted ? 'copy' : 'none';
      return;
    }
    zone.classList.add('dragover');
  });
  zone.addEventListener('dragleave', function() {
    zone.classList.remove('dragover', 'bucket-drop-active', 'bucket-drop-reject');
  });
  zone.addEventListener('drop', function(e) {
    e.preventDefault();
    zone.classList.remove('dragover', 'bucket-drop-active', 'bucket-drop-reject');
    /* Bucket item: use URL directly */
    var bucketRaw = e.dataTransfer.getData('application/x-bucket-item');
    if (bucketRaw) {
      try {
        var item = JSON.parse(bucketRaw);
        if (item.type === 'image' && item.url) {
          expLoadFromUrl(item.url, item.label || 'bucket image');
        }
      } catch (err) { console.warn('[expander] bucket drop error', err); }
      return;
    }
    /* Regular file drop */
    if (e.dataTransfer.files.length) expHandleFiles(e.dataTransfer.files);
  });

  /* Click to browse */
  zone.addEventListener('click', function() { expPickFile(); });
}

function expPickFile() {
  var input = document.getElementById('exp-file-input');
  if (!input) return;
  input.click();
  input.onchange = function() {
    if (input.files.length) expHandleFiles(input.files);
  };
}

/* Load image from a server URL (bucket items) */
function expLoadFromUrl(url, name) {
  expState.imageUrl = url;
  expState.imageName = name || url.split('/').pop();

  var displayUrl = url.startsWith('/') ? IMG_BASE_EXP + url : url;
  var preview = document.getElementById('exp-preview-img');
  if (preview) {
    preview.innerHTML = '<img src="' + displayUrl + '" style="width:100%;border-radius:var(--sp-4);display:block">';
  }
  expShow('exp-preview');
  expHide('exp-drop-zone');
  var btn = document.getElementById('exp-generate-btn');
  if (btn) btn.disabled = false;
}

/* Load image from local file (file picker / regular drop) */
function expHandleFiles(files) {
  if (!files || !files.length) return;
  var file = files[0];
  var blobUrl = URL.createObjectURL(file);
  expState.imageName = file.name;
  expState.imageUrl = blobUrl;
  expState._file = file;

  var preview = document.getElementById('exp-preview-img');
  if (preview) {
    preview.innerHTML = '<img src="' + blobUrl + '" style="width:100%;border-radius:var(--sp-4);display:block">';
  }
  expShow('exp-preview');
  expHide('exp-drop-zone');
  var btn = document.getElementById('exp-generate-btn');
  if (btn) btn.disabled = false;
}

/* ═══════════════════════════════════════════════════════════════
   GENERATE (EXPAND)
   ═══════════════════════════════════════════════════════════════ */

async function expGenerate() {
  console.log('[expander] expGenerate called, state:', JSON.stringify({generating: expState.generating, imageUrl: expState.imageUrl, sessionId: typeof sessionId !== 'undefined' ? sessionId : 'undef'}));
  if (expState.generating) { console.log('[expander] blocked: already generating'); return; }
  if (!sessionId) {
    await initSession();
    if (!sessionId) { expShowStatus('No session — please reload', true); return; }
  }
  if (!expState.imageUrl) { expShowStatus('No image loaded', true); return; }

  var promptEl = document.getElementById('exp-prompt');
  var prompt = promptEl ? promptEl.value.trim() : '';
  var seedEl = document.getElementById('exp-seed');
  var seedVal = seedEl ? seedEl.value.trim() : '-1';
  var stepsEl = document.getElementById('exp-steps');
  var steps = stepsEl ? stepsEl.value.trim() : '28';
  var featherEl = document.getElementById('exp-feathering');
  var feathering = featherEl ? featherEl.value.trim() : '40';

  /* Prevent double-click */
  expState.generating = true;

  /* Resolve image URL: strip host prefix, blobs need upload */
  var imageUrl = expState.imageUrl;
  /* Strip full URL to relative path (http://mora02.local:8092/comfyui/... → /comfyui/...) */
  if (imageUrl.indexOf('/comfyui/') !== -1) {
    imageUrl = imageUrl.substring(imageUrl.indexOf('/comfyui/'));
  } else if (imageUrl.indexOf('/output/') !== -1) {
    imageUrl = imageUrl.substring(imageUrl.indexOf('/output/'));
  }
  if (imageUrl.startsWith('blob:')) {
    /* Upload the file first */
    if (expState._file) {
      var formData = new FormData();
      formData.append('file', expState._file);
      try {
        var uploadResp = await fetch(API_BASE + '/upload/comfyui', { method: 'POST', body: formData });
        var uploadData = await uploadResp.json();
        if (uploadData.url) imageUrl = uploadData.url;
        else if (uploadData.filename) imageUrl = '/comfyui/wip/' + uploadData.filename;
      } catch (e) {
        expShowStatus('Upload failed: ' + e.message, true);
        return;
      }
    }
  }

  /* Build command */
  var cmd = '/expand ' + imageUrl;
  if (prompt) cmd += ' --prompt ' + prompt;
  if (seedVal && seedVal !== '-1') cmd += ' --seed ' + seedVal;
  if (steps && steps !== '28') cmd += ' --steps ' + steps;
  if (feathering && feathering !== '40') cmd += ' --feathering ' + feathering;

  var btn = document.getElementById('exp-generate-btn');
  if (btn) { btn.disabled = true; btn.textContent = 'EXPANDING...'; }
  expLoaderShow();

  try {
    var resp = await fetch(API_BASE + '/chat/' + sessionId, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: cmd }),
    });
    var data = await resp.json();
    expLoaderHide();

    if (data.images && data.images.length > 0) {
      var img = data.images[0];
      var resultUrl = IMG_BASE_EXP + img.url;
      expState.resultUrl = resultUrl;

      /* Replace source preview with expanded result (same area) */
      var preview = document.getElementById('exp-preview-img');
      if (preview) {
        preview.innerHTML =
          '<div class="tool-result-head">EXPANDED \u2014 ' + (data.target || '1920x1920') + ' \u2014 seed: ' + (data.seed || '?') + '</div>' +
          '<img src="' + resultUrl + '?t=' + Date.now() + '" style="width:100%;border-radius:var(--sp-4);display:block">';
      }

      /* Show result buttons below preview */
      var badge = document.getElementById('exp-result-badge');
      if (badge) badge.textContent = '';
      expShow('exp-result-section');
      /* Hide the separate result image (we show it in preview area instead) */
      var resultImg = document.getElementById('exp-result-img');
      if (resultImg) resultImg.innerHTML = '';

      if (typeof loadMonthlyCost === 'function') loadMonthlyCost();
    } else {
      expShowStatus(data.data || data.result || 'Expansion failed', true);
    }
  } catch (e) {
    expLoaderHide();
    expShowStatus('Request failed: ' + e.message, true);
  }

  expState.generating = false;
  if (btn) {
    btn.disabled = false;
    btn.innerHTML = '<svg fill="currentColor" width="16" height="16"><use href="icons/sprite.svg#i-image"/></svg> EXPAND';
  }
}

/* ═══════════════════════════════════════════════════════════════
   DOWNLOAD + BUCKET
   ═══════════════════════════════════════════════════════════════ */

function expDownload() {
  if (!expState.resultUrl) return;
  var a = document.createElement('a');
  a.href = expState.resultUrl;
  a.download = 'expanded_' + (expState.imageName || 'image.png');
  a.target = '_blank';
  document.body.appendChild(a);
  a.click();
  a.remove();
  expShowStatus('\u2713 Downloaded', false);
}

function expAddToBucket() {
  if (!expState.resultUrl) return;
  bucketAdd({
    type: 'image',
    url: expState.resultUrl,
    thumb: expState.resultUrl,
    source: 'expander',
    label: 'Expanded ' + (expState.imageName || 'image').substring(0, 40),
  });
  expShowStatus('\u2713 Added to bucket', false);
}

/* ═══════════════════════════════════════════════════════════════
   NEW EXPAND (collapse current, open fresh)
   ═══════════════════════════════════════════════════════════════ */

function expNew() {
  var wrap = document.getElementById('exp-generate-btn');
  if (wrap) wrap = wrap.closest('.tool-wrap');
  if (!wrap) return;

  var isChat = !!wrap.closest('.post-widget');

  if (isChat) {
    /* Chat context: collapse to bar, open fresh widget */
    var oldMsgBot = wrap.closest('.msg-bot');
    if (oldMsgBot) oldMsgBot.style.display = 'none';

    /* Build collapsed bar */
    var thumbUrl = expState.resultUrl || '';
    var label = expState.imageName || 'expanded image';
    var barHtml = msgHeadHTML('EXPANDER', 'var(--tx-muted)') +
      '<div class="msg-body"><div class="post-widget" style="border:1px solid #444;border-radius:8px;padding:var(--sp-10)">' +
        '<div class="tool-collapsed">' +
          '<div class="tool-collapsed-bar" data-action="img-expand-collapsed">' +
            (thumbUrl ? '<img class="tool-collapsed-thumb" src="' + thumbUrl + '">' : '') +
            '<div class="tool-collapsed-info">' +
              '<div class="tool-collapsed-meta">' + label.substring(0, 80) + '</div>' +
            '</div>' +
            '<button class="tool-action-btn" data-action="exp-download" data-url="' + thumbUrl + '" style="flex-shrink:0">DOWNLOAD</button>' +
            '<button class="tool-action-btn bucket-add-btn" data-action="exp-bucket" data-url="' + thumbUrl + '" style="flex-shrink:0">ADD TO BUCKET</button>' +
            '<span class="tool-collapse-arrow" style="flex-shrink:0">&#9654;</span>' +
          '</div>' +
          '<div class="tool-collapsed-content" style="display:none">' +
            (thumbUrl ? '<img src="' + thumbUrl + '" style="width:100%;border-radius:var(--sp-4);display:block">' : '') +
          '</div>' +
        '</div>' +
      '</div></div>';
    appendBotEl('system', barHtml);

    /* Reset state + fresh widget */
    expState = { imageUrl: '', imageName: '', resultUrl: '', generating: false };
    renderToolWidget('expander', 'initExpander');
  } else {
    /* Standalone: just reset the tool */
    expState = { imageUrl: '', imageName: '', resultUrl: '', generating: false };
    initExpander();
    expShow('exp-drop-zone');
  }
}

/* ═══════════════════════════════════════════════════════════════
   LOADER OVERLAY
   ═══════════════════════════════════════════════════════════════ */

function expLoaderShow() {
  var existing = document.getElementById('exp-loader-wrap');
  if (existing) return;
  var genBtn = document.getElementById('exp-generate-btn');
  var wrap = genBtn ? genBtn.closest('.tool-wrap') : document.querySelector('.tool-wrap');
  if (!wrap) return;
  wrap.style.position = 'relative';
  var overlay = document.createElement('div');
  overlay.id = 'exp-loader-wrap';
  overlay.className = 'tool-gen-overlay';
  overlay.innerHTML = '<div class="tool-gen-overlay-label">EXPANDING</div><div class="m2-loader-m" id="exp-m2-loader"></div>';
  wrap.appendChild(overlay);
  startM2(document.getElementById('exp-m2-loader'), 9, 35);
}

function expLoaderHide() {
  stopM2();
  var el = document.getElementById('exp-loader-wrap');
  if (el) { var m = el.querySelector('.m2-loader-m'); if (m) m.innerHTML = ''; el.remove(); }
}

/* ═══════════════════════════════════════════════════════════════
   HELPERS
   ═══════════════════════════════════════════════════════════════ */

function expShow(id) { var el = document.getElementById(id); if (el) el.style.display = ''; }
function expHide(id) { var el = document.getElementById(id); if (el) el.style.display = 'none'; }

function expShowStatus(msg, isError) {
  var el = document.getElementById('exp-status');
  if (el) el.innerHTML = '<span style="color:var(--c-' + (isError ? 'red' : 'green') + ')">' + msg + '</span>';
}

function expAutoResize(id) {
  var el = document.getElementById(id);
  if (!el) return;
  function resize() { el.style.height = 'auto'; el.style.height = el.scrollHeight + 'px'; }
  el.addEventListener('input', resize);
  resize();
}

function expToggleSettings() {
  var body = document.getElementById('exp-settings-body');
  var head = document.getElementById('exp-settings-toggle');
  if (!body || !head) return;
  var isOpen = body.style.display !== 'none';
  body.style.display = isOpen ? 'none' : '';
  head.classList.toggle('open', !isOpen);
}

/* ═══════════════════════════════════════════════════════════════
   EVENT DELEGATION
   ═══════════════════════════════════════════════════════════════ */

document.addEventListener('click', function(e) {
  var target = e.target.closest('[data-action]');
  if (!target) return;
  switch (target.dataset.action) {
    case 'exp-generate':        expGenerate(); break;
    case 'exp-download':
      /* Support data-url for collapsed bars */
      if (target.dataset.url) {
        var a = document.createElement('a'); a.href = target.dataset.url; a.download = 'expanded.png'; a.target = '_blank';
        document.body.appendChild(a); a.click(); a.remove();
      } else { expDownload(); }
      break;
    case 'exp-bucket':
      if (target.dataset.url) {
        bucketAdd({ type: 'image', url: target.dataset.url, thumb: target.dataset.url, source: 'expander', label: 'Expanded image' });
        target.classList.add('bucket-add-ok'); target.textContent = 'ADDED';
        setTimeout(function() { target.classList.remove('bucket-add-ok'); target.textContent = 'ADD TO BUCKET'; }, 800);
      } else { expAddToBucket(); }
      break;
    case 'exp-new':             expNew(); break;
    case 'exp-toggle-settings': expToggleSettings(); break;
  }
});
