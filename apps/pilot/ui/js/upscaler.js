/* ═══════════════════════════════════════════════════════════════
   MORA02 PILOT — Upscaler Module
   ═══════════════════════════════════════════════════════════════
   Hybrid high-end upscale: 4x-UltraSharp ESRGAN pre-pass + SDXL
   tile-diffusion refiner (Juggernaut XL, denoise 0.2).
   Drop image from bucket → factor 2/3/4 → upscale → download/bucket.
   ═══════════════════════════════════════════════════════════════ */

var IMG_BASE_UP = 'http://mora02.local:8092';

var upState = {
  imageUrl: '',
  imageName: '',
  resultUrl: '',
  generating: false,
};

/* ═══════════════════════════════════════════════════════════════
   INIT
   ═══════════════════════════════════════════════════════════════ */

function initUpscaler() {
  upState = { imageUrl: '', imageName: '', resultUrl: '', generating: false };
  upHide('up-result-section');
  upShow('up-input-section');
  upHide('up-preview');
  upHide('up-settings-body');
  var toggle = document.getElementById('up-settings-toggle');
  if (toggle) toggle.classList.remove('open');
  var btn = document.getElementById('up-generate-btn');
  if (btn) { btn.disabled = true; btn.innerHTML = '<svg fill="currentColor" width="16" height="16"><use href="icons/sprite.svg#i-image"/></svg> UPSCALE'; }
  upAutoResize('up-prompt');
  upBindUpload();
}

function upBindUpload() {
  var zone = document.getElementById('up-drop-zone');
  if (!zone) return;

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
    var bucketRaw = e.dataTransfer.getData('application/x-bucket-item');
    if (bucketRaw) {
      try {
        var item = JSON.parse(bucketRaw);
        if (item.type === 'image' && item.url) {
          upLoadFromUrl(item.url, item.label || 'bucket image');
        }
      } catch (err) { console.warn('[upscaler] bucket drop error', err); }
      return;
    }
    if (e.dataTransfer.files.length) upHandleFiles(e.dataTransfer.files);
  });

  zone.addEventListener('click', function() { upPickFile(); });
}

function upPickFile() {
  var input = document.getElementById('up-file-input');
  if (!input) return;
  input.click();
  input.onchange = function() {
    if (input.files.length) upHandleFiles(input.files);
  };
}

function upLoadFromUrl(url, name) {
  upState.imageUrl = url;
  upState.imageName = name || url.split('/').pop();

  var displayUrl = url.startsWith('/') ? IMG_BASE_UP + url : url;
  var preview = document.getElementById('up-preview-img');
  if (preview) {
    preview.innerHTML = '<img src="' + displayUrl + '" style="width:100%;border-radius:var(--sp-4);display:block">';
  }
  upShow('up-preview');
  upHide('up-drop-zone');
  var btn = document.getElementById('up-generate-btn');
  if (btn) btn.disabled = false;
}

function upHandleFiles(files) {
  if (!files || !files.length) return;
  var file = files[0];
  var blobUrl = URL.createObjectURL(file);
  upState.imageName = file.name;
  upState.imageUrl = blobUrl;
  upState._file = file;

  var preview = document.getElementById('up-preview-img');
  if (preview) {
    preview.innerHTML = '<img src="' + blobUrl + '" style="width:100%;border-radius:var(--sp-4);display:block">';
  }
  upShow('up-preview');
  upHide('up-drop-zone');
  var btn = document.getElementById('up-generate-btn');
  if (btn) btn.disabled = false;
}

/* ═══════════════════════════════════════════════════════════════
   GENERATE (UPSCALE)
   ═══════════════════════════════════════════════════════════════ */

async function upGenerate() {
  if (upState.generating) return;
  if (!sessionId) {
    await initSession();
    if (!sessionId) { upShowStatus('No session — please reload', true); return; }
  }
  if (!upState.imageUrl) { upShowStatus('No image loaded', true); return; }

  var promptEl = document.getElementById('up-prompt');
  var prompt = promptEl ? promptEl.value.trim() : '';
  var factorEl = document.getElementById('up-factor');
  var factor = factorEl ? factorEl.value : '2';
  var denoiseEl = document.getElementById('up-denoise');
  var denoise = denoiseEl ? denoiseEl.value.trim() : '0.2';
  var seedEl = document.getElementById('up-seed');
  var seedVal = seedEl ? seedEl.value.trim() : '-1';
  var stepsEl = document.getElementById('up-steps');
  var steps = stepsEl ? stepsEl.value.trim() : '20';
  var cfgEl = document.getElementById('up-cfg');
  var cfg = cfgEl ? cfgEl.value.trim() : '6.0';

  upState.generating = true;

  /* Resolve image URL */
  var imageUrl = upState.imageUrl;
  if (imageUrl.indexOf('/comfyui/') !== -1) {
    imageUrl = imageUrl.substring(imageUrl.indexOf('/comfyui/'));
  } else if (imageUrl.indexOf('/output/') !== -1) {
    imageUrl = imageUrl.substring(imageUrl.indexOf('/output/'));
  }
  if (imageUrl.startsWith('blob:')) {
    if (upState._file) {
      var formData = new FormData();
      formData.append('file', upState._file);
      try {
        var uploadResp = await fetch(API_BASE + '/upload/comfyui', { method: 'POST', body: formData });
        var uploadData = await uploadResp.json();
        if (uploadData.url) imageUrl = uploadData.url;
        else if (uploadData.filename) imageUrl = '/comfyui/wip/' + uploadData.filename;
      } catch (e) {
        upState.generating = false;
        upShowStatus('Upload failed: ' + e.message, true);
        return;
      }
    }
  }

  /* Build command */
  var cmd = '/upscale ' + imageUrl + ' --factor ' + factor;
  if (denoise && denoise !== '0.2') cmd += ' --denoise ' + denoise;
  if (prompt) cmd += ' --prompt ' + prompt;
  if (seedVal && seedVal !== '-1') cmd += ' --seed ' + seedVal;
  if (steps && steps !== '20') cmd += ' --steps ' + steps;
  if (cfg && cfg !== '6.0') cmd += ' --cfg ' + cfg;

  var btn = document.getElementById('up-generate-btn');
  if (btn) { btn.disabled = true; btn.textContent = 'UPSCALING...'; }
  upLoaderShow();

  try {
    var resp = await fetch(API_BASE + '/chat/' + sessionId, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: cmd }),
    });
    var data = await resp.json();
    upLoaderHide();

    if (data.images && data.images.length > 0) {
      var img = data.images[0];
      var resultUrl = IMG_BASE_UP + img.url;
      upState.resultUrl = resultUrl;

      var preview = document.getElementById('up-preview-img');
      if (preview) {
        preview.innerHTML =
          '<div class="tool-result-head">UPSCALED — ' + (data.factor || factor) + 'x — seed: ' + (data.seed || '?') + '</div>' +
          '<img src="' + resultUrl + '?t=' + Date.now() + '" style="width:100%;border-radius:var(--sp-4);display:block">';
      }

      var badge = document.getElementById('up-result-badge');
      if (badge) badge.textContent = '';
      upShow('up-result-section');
      var resultImg = document.getElementById('up-result-img');
      if (resultImg) resultImg.innerHTML = '';

      if (typeof loadMonthlyCost === 'function') loadMonthlyCost();
    } else {
      upShowStatus(data.data || data.result || 'Upscale failed', true);
    }
  } catch (e) {
    upLoaderHide();
    upShowStatus('Request failed: ' + e.message, true);
  }

  upState.generating = false;
  if (btn) {
    btn.disabled = false;
    btn.innerHTML = '<svg fill="currentColor" width="16" height="16"><use href="icons/sprite.svg#i-image"/></svg> UPSCALE';
  }
}

/* ═══════════════════════════════════════════════════════════════
   DOWNLOAD + BUCKET
   ═══════════════════════════════════════════════════════════════ */

function upDownload() {
  if (!upState.resultUrl) return;
  var a = document.createElement('a');
  a.href = upState.resultUrl;
  a.download = 'upscaled_' + (upState.imageName || 'image.png');
  a.target = '_blank';
  document.body.appendChild(a);
  a.click();
  a.remove();
  upShowStatus('✓ Downloaded', false);
}

function upAddToBucket() {
  if (!upState.resultUrl) return;
  bucketAdd({
    type: 'image',
    url: upState.resultUrl,
    thumb: upState.resultUrl,
    source: 'upscaler',
    label: 'Upscaled ' + (upState.imageName || 'image').substring(0, 40),
  });
  upShowStatus('✓ Added to bucket', false);
}

/* ═══════════════════════════════════════════════════════════════
   NEW UPSCALE
   ═══════════════════════════════════════════════════════════════ */

function upNew() {
  var wrap = document.getElementById('up-generate-btn');
  if (wrap) wrap = wrap.closest('.tool-wrap');
  if (!wrap) return;

  var isChat = !!wrap.closest('.post-widget');

  if (isChat) {
    var oldMsgBot = wrap.closest('.msg-bot');
    if (oldMsgBot) oldMsgBot.style.display = 'none';

    var thumbUrl = upState.resultUrl || '';
    var label = upState.imageName || 'upscaled image';
    var barHtml = msgHeadHTML('UPSCALER', 'var(--tx-muted)') +
      '<div class="msg-body"><div class="post-widget" style="border:1px solid #444;border-radius:8px;padding:var(--sp-10)">' +
        '<div class="tool-collapsed">' +
          '<div class="tool-collapsed-bar" data-action="img-expand-collapsed">' +
            (thumbUrl ? '<img class="tool-collapsed-thumb" src="' + thumbUrl + '">' : '') +
            '<div class="tool-collapsed-info">' +
              '<div class="tool-collapsed-meta">' + label.substring(0, 80) + '</div>' +
            '</div>' +
            '<button class="tool-action-btn" data-action="up-download" data-url="' + thumbUrl + '" style="flex-shrink:0">DOWNLOAD</button>' +
            '<button class="tool-action-btn bucket-add-btn" data-action="up-bucket" data-url="' + thumbUrl + '" style="flex-shrink:0">ADD TO BUCKET</button>' +
            '<span class="tool-collapse-arrow" style="flex-shrink:0">&#9654;</span>' +
          '</div>' +
          '<div class="tool-collapsed-content" style="display:none">' +
            (thumbUrl ? '<img src="' + thumbUrl + '" style="width:100%;border-radius:var(--sp-4);display:block">' : '') +
          '</div>' +
        '</div>' +
      '</div></div>';
    appendBotEl('system', barHtml);

    upState = { imageUrl: '', imageName: '', resultUrl: '', generating: false };
    renderToolWidget('upscaler', 'initUpscaler');
  } else {
    upState = { imageUrl: '', imageName: '', resultUrl: '', generating: false };
    initUpscaler();
    upShow('up-drop-zone');
  }
}

/* ═══════════════════════════════════════════════════════════════
   LOADER OVERLAY
   ═══════════════════════════════════════════════════════════════ */

function upLoaderShow() {
  var existing = document.getElementById('up-loader-wrap');
  if (existing) return;
  var genBtn = document.getElementById('up-generate-btn');
  var wrap = genBtn ? genBtn.closest('.tool-wrap') : document.querySelector('.tool-wrap');
  if (!wrap) return;
  wrap.style.position = 'relative';
  var overlay = document.createElement('div');
  overlay.id = 'up-loader-wrap';
  overlay.className = 'tool-gen-overlay';
  overlay.innerHTML = '<div class="tool-gen-overlay-label">UPSCALING</div><div class="m2-loader-m" id="up-m2-loader"></div>';
  wrap.appendChild(overlay);
  startM2(document.getElementById('up-m2-loader'), 9, 35);
}

function upLoaderHide() {
  stopM2();
  var el = document.getElementById('up-loader-wrap');
  if (el) { var m = el.querySelector('.m2-loader-m'); if (m) m.innerHTML = ''; el.remove(); }
}

/* ═══════════════════════════════════════════════════════════════
   HELPERS
   ═══════════════════════════════════════════════════════════════ */

function upShow(id) { var el = document.getElementById(id); if (el) el.style.display = ''; }
function upHide(id) { var el = document.getElementById(id); if (el) el.style.display = 'none'; }

function upShowStatus(msg, isError) {
  var el = document.getElementById('up-status');
  if (el) el.innerHTML = '<span style="color:var(--c-' + (isError ? 'red' : 'green') + ')">' + msg + '</span>';
}

function upAutoResize(id) {
  var el = document.getElementById(id);
  if (!el) return;
  function resize() { el.style.height = 'auto'; el.style.height = el.scrollHeight + 'px'; }
  el.addEventListener('input', resize);
  resize();
}

function upToggleSettings() {
  var body = document.getElementById('up-settings-body');
  var head = document.getElementById('up-settings-toggle');
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
    case 'up-generate':        upGenerate(); break;
    case 'up-download':
      if (target.dataset.url) {
        var a = document.createElement('a'); a.href = target.dataset.url; a.download = 'upscaled.png'; a.target = '_blank';
        document.body.appendChild(a); a.click(); a.remove();
      } else { upDownload(); }
      break;
    case 'up-bucket':
      if (target.dataset.url) {
        bucketAdd({ type: 'image', url: target.dataset.url, thumb: target.dataset.url, source: 'upscaler', label: 'Upscaled image' });
        target.classList.add('bucket-add-ok'); target.textContent = 'ADDED';
        setTimeout(function() { target.classList.remove('bucket-add-ok'); target.textContent = 'ADD TO BUCKET'; }, 800);
      } else { upAddToBucket(); }
      break;
    case 'up-new':             upNew(); break;
    case 'up-toggle-settings': upToggleSettings(); break;
  }
});
