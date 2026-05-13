/* ═══════════════════════════════════════════════════════════════
   MORA02 PILOT — Tools Module v2 (Clean Rewrite 2026-03-19)
   ═══════════════════════════════════════════════════════════════
   Gifer · (Clipper, Typer, ImageGen planned)
   ───────────────────────────────────────────────────────────────
   Depends on: app.js (API_BASE), Script-Runner at :8096
   ═══════════════════════════════════════════════════════════════ */

var SCRIPT_API = 'http://mora02.local:8096';

/* ═══════════════════════════════════════════════════════════════
   GIFER
   ═══════════════════════════════════════════════════════════════ */

var giferState = {
  sessionId: null,
  files: [],
  resultUrl: null,
  finalUrl: null,
  finalized: false,
};

/* ─── Init ──────────────────────────────────────────────────── */

async function initGifer() {
  giferState = { sessionId: null, files: [], resultUrl: null, finalUrl: null, finalized: false };

  var list = document.getElementById('gifer-list');
  if (list) list.innerHTML = '';

  try {
    var resp = await fetch(SCRIPT_API + '/session/create', { method: 'POST' });
    var data = await resp.json();
    giferState.sessionId = data.session_id;
  } catch (e) {
    console.warn('Script-Runner not available');
  }

  bindUploadArea(document.getElementById('gifer-upload'), giferUploadFiles, giferPickFiles);
  giferShowArrange();
  giferHideArrangeDetails();
  updateGiferGenBtn();
}

/* ─── Upload Area Binding ───────────────────────────────────── */

function bindUploadArea(upload, uploadFn, pickFn, bucketAcceptTypes) {
  if (!upload) return;
  var doUpload = uploadFn || giferUploadFiles;
  var doPick = pickFn || giferPickFiles;
  var acceptTypes = bucketAcceptTypes || ['image'];

  upload.setAttribute('data-bucket-accepts', acceptTypes.join(', '));

  upload.addEventListener('dragover', function(e) {
    e.preventDefault();
    /* Bucket drag: show accept/reject feedback */
    if (e.dataTransfer.types && e.dataTransfer.types.indexOf('application/x-bucket-item') !== -1) {
      var accepted = typeof bucketDragItem !== 'undefined' && bucketDragItem && acceptTypes.indexOf(bucketDragItem.type) !== -1;
      if (accepted) {
        e.dataTransfer.dropEffect = 'copy';
        upload.classList.add('bucket-drop-active');
        upload.classList.remove('bucket-drop-reject');
      } else {
        e.dataTransfer.dropEffect = 'none';
        upload.classList.add('bucket-drop-reject');
        upload.classList.remove('bucket-drop-active');
      }
      return;
    }
    upload.classList.add('dragover');
  });
  upload.addEventListener('dragleave', function() { upload.classList.remove('dragover'); upload.classList.remove('bucket-drop-active'); upload.classList.remove('bucket-drop-reject'); });
  upload.addEventListener('drop', function(e) {
    e.preventDefault();
    upload.classList.remove('dragover');
    upload.classList.remove('bucket-drop-active');
    upload.classList.remove('bucket-drop-reject');
    /* Check for bucket item first */
    var bucketRaw = e.dataTransfer.getData('application/x-bucket-item');
    if (bucketRaw) {
      try {
        var item = JSON.parse(bucketRaw);
        if (acceptTypes.indexOf(item.type) !== -1) {
          bucketUrlToFiles(item.url, function(files) { doUpload(files); });
        }
      } catch (err) { console.warn('[tools] bucket drop parse error', err); }
      return;
    }
    if (e.dataTransfer.files.length) doUpload(e.dataTransfer.files);
  });
  upload.addEventListener('click', function() { doPick(); });
}

/* ─── Helper: fetch URL → FileList-like array ──────────────── */

async function bucketUrlToFiles(url, callback) {
  try {
    var resp = await fetch(url);
    var blob = await resp.blob();
    var ext = url.split('.').pop().split('?')[0] || 'png';
    var name = url.split('/').pop().split('?')[0] || ('bucket.' + ext);
    var file = new File([blob], name, { type: blob.type || 'application/octet-stream' });
    /* Wrap in array-like to match FileList interface */
    var files = [file];
    files.item = function(i) { return files[i]; };
    callback(files);
  } catch (err) {
    console.warn('[tools] bucket URL fetch failed:', err);
  }
}

/* ─── File Pick & Upload ────────────────────────────────────── */

function giferPickFiles() {
  var input = document.createElement('input');
  input.type = 'file';
  input.accept = 'image/*';
  input.multiple = true;
  input.onchange = function(e) {
    if (e.target.files.length) giferUploadFiles(e.target.files);
  };
  input.click();
}

async function giferUploadFiles(fileList) {
  if (!giferState.sessionId) return;

  var localThumbs = [];
  for (var i = 0; i < fileList.length; i++) {
    localThumbs.push(URL.createObjectURL(fileList[i]));
  }

  var formData = new FormData();
  for (var i = 0; i < fileList.length; i++) {
    formData.append('files', fileList[i]);
  }

  try {
    var resp = await fetch(SCRIPT_API + '/upload/' + giferState.sessionId, {
      method: 'POST',
      body: formData,
    });
    var data = await resp.json();

    (data.uploaded || []).forEach(function(name, idx) {
      giferState.files.push({
        name: name,
        thumbUrl: localThumbs[idx] || '',
        duration: '1',
      });
    });

    renderGiferList();
    giferShowArrangeDetails();
    updateGiferGenBtn();
  } catch (e) {
    console.error('Upload failed:', e);
  }
}

/* ─── Show/Hide Arrange vs Result ───────────────────────────── */

function giferShowArrange() {
  var arrange = document.getElementById('gifer-arrange');
  var result = document.getElementById('gifer-result');
  if (arrange) arrange.style.display = '';
  if (result) result.style.display = 'none';
}

function giferShowResultPanel() {
  var arrange = document.getElementById('gifer-arrange');
  var result = document.getElementById('gifer-result');
  var upload = document.getElementById('gifer-upload');
  if (arrange) arrange.style.display = 'none';
  if (upload) upload.style.display = 'none';
  if (result) result.style.display = '';
}

/* ─── Render File List ──────────────────────────────────────── */

function renderGiferList() {
  var list = document.getElementById('gifer-list');
  if (!list) return;

  if (giferState.files.length === 0) { list.innerHTML = ''; return; }

  var html = '';
  giferState.files.forEach(function(file, idx) {
    html +=
      '<div class="tool-item" data-idx="' + idx + '">' +
        '<div class="tool-item-drag"><svg fill="currentColor"><use href="icons/sprite.svg#i-shuffle"/></svg></div>' +
        '<span class="tool-item-num">' + String(idx + 1).padStart(2, '0') + '</span>' +
        '<div class="tool-item-thumb" style="background:url(\'' + file.thumbUrl + '\') center/cover"></div>' +
        '<span class="tool-item-name">' + esc(file.name.replace(/^\d+-/, '')) + '</span>' +
        '<div class="tool-item-arrows">' +
          '<div class="tool-item-arrow" data-action="gifer-dur-up" data-idx="' + idx + '"><svg fill="currentColor"><use href="icons/sprite.svg#i-chev-up"/></svg></div>' +
          '<input class="tool-item-val" type="text" value="' + file.duration + '" data-action-input="gifer-dur" data-idx="' + idx + '">' +
          '<div class="tool-item-arrow" data-action="gifer-dur-down" data-idx="' + idx + '"><svg fill="currentColor"><use href="icons/sprite.svg#i-chev-down"/></svg></div>' +
        '</div>' +
        '<div class="tool-item-delete" data-action="gifer-remove" data-idx="' + idx + '"><svg fill="currentColor"><use href="icons/sprite.svg#i-delete"/></svg></div>' +
      '</div>';
  });

  list.innerHTML = html;

  /* Duration input listeners */
  list.querySelectorAll('[data-action-input="gifer-dur"]').forEach(function(input) {
    input.addEventListener('change', function() {
      var idx = parseInt(input.dataset.idx);
      if (giferState.files[idx]) giferState.files[idx].duration = input.value;
    });
  });

  /* Drag & drop reorder */
  list.querySelectorAll('.tool-item').forEach(function(item) {
    item.setAttribute('draggable', 'true');
    item.addEventListener('dragstart', function(e) {
      e.dataTransfer.setData('text/plain', item.dataset.idx);
      item.classList.add('dragging');
    });
    item.addEventListener('dragend', function() { item.classList.remove('dragging'); });
    item.addEventListener('dragover', function(e) { e.preventDefault(); item.classList.add('drag-over'); });
    item.addEventListener('dragleave', function() { item.classList.remove('drag-over'); });
    item.addEventListener('drop', function(e) {
      e.preventDefault();
      item.classList.remove('drag-over');
      var fromIdx = parseInt(e.dataTransfer.getData('text/plain'));
      var toIdx = parseInt(item.dataset.idx);
      if (fromIdx !== toIdx) {
        var moved = giferState.files.splice(fromIdx, 1)[0];
        giferState.files.splice(toIdx, 0, moved);
        renderGiferList();
      }
    });
  });
}

function updateGiferGenBtn() {
  var btn = document.querySelector('[data-action="gifer-generate"]');
  if (btn) {
    btn.disabled = giferState.files.length < 2;
    btn.style.opacity = giferState.files.length < 2 ? '0.3' : '';
  }
}

/* ─── Generate ──────────────────────────────────────────────── */

async function giferGenerate() {
  if (!giferState.sessionId || giferState.files.length < 2) return;

  var btn = document.querySelector('[data-action="gifer-generate"]');
  if (btn) { btn.disabled = true; btn.textContent = 'GENERATING...'; }

  var qualityEl = document.getElementById('gifer-quality');
  var sizeWEl = document.getElementById('gifer-size-w');
  var sizeHEl = document.getElementById('gifer-size-h');

  var quality = qualityEl ? qualityEl.value.toLowerCase() : 'medium';
  var durations = giferState.files.map(function(f) { return f.duration; }).join(',');
  var size = null;
  if (sizeWEl && sizeHEl && sizeWEl.value && sizeHEl.value) {
    size = sizeWEl.value + 'x' + sizeHEl.value;
  }

  var payload = { session_id: giferState.sessionId, durations: durations, quality: quality };
  if (size) payload.size = size;

  try {
    var resp = await fetch(SCRIPT_API + '/run/gifer', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    var data = await resp.json();

    if (data.success) {
      giferState.resultUrl = SCRIPT_API + (data.preview_url || '/preview/' + giferState.sessionId + '/' + data.filename) + '?t=' + Date.now();
      giferState.finalized = false;
      giferRenderResult();
      giferShowResultPanel();
    } else {
      giferRenderError(data.error || 'Generation failed');
      giferShowResultPanel();
    }
  } catch (e) {
    giferRenderError('Request failed: ' + e.message);
    giferShowResultPanel();
  }

  if (btn) {
    btn.disabled = false;
    btn.innerHTML = '<svg fill="currentColor" style="width:20px;height:20px"><use href="icons/sprite.svg#i-gif"/></svg> GENERATE GIF';
  }
}

/* ─── Render Result ─────────────────────────────────────────── */

function giferRenderResult() {
  var result = document.getElementById('gifer-result');
  if (!result) return;

  result.dataset.sessionId = giferState.sessionId;
  result.innerHTML =
    '<div class="tool-result-head">RESULT</div>' +
    '<div class="tool-result-preview"><img src="' + giferState.resultUrl + '" loading="lazy"></div>' +
    '<div class="tool-result-btns" id="gifer-btns">' +
      '<button class="tool-action-btn" data-action="gifer-finalize" id="gifer-finalize-btn">FINALIZE AND SAVE</button>' +
      '<button class="tool-action-btn" data-action="gifer-download">DOWNLOAD</button>' +
      '<button class="tool-action-btn" data-action="gifer-new">CREATE NEW GIF</button>' +
      '<button class="tool-action-btn bucket-add-btn" data-action="gifer-bucket">BUCKET</button>' +
    '</div>' +
    '<div class="tool-result-status" id="gifer-status"></div>';
}

function giferRenderError(msg) {
  var result = document.getElementById('gifer-result');
  if (!result) return;
  result.innerHTML =
    '<div class="tool-result-error">' + esc(msg) + '</div>' +
    '<div class="tool-result-btns">' +
      '<button class="tool-action-btn" data-action="gifer-redo">BACK TO ARRANGE</button>' +
    '</div>';
}

/* ─── Redo (back to arrange, same images) ───────────────────── */

function giferRedo() {
  giferState.resultUrl = null;
  giferState.finalized = false;
  var upload = document.getElementById('gifer-upload');
  if (upload) upload.style.display = '';
  giferShowArrange();
}

/* ─── Finalize ──────────────────────────────────────────────── */

async function giferFinalize() {
  /* Use sessionId from the clicked button or current result */
  var finBtn = document.getElementById('gifer-finalize-btn');
  /* Check if this is a history finalize (button has data-sid) */
  var clickedBtn = document.activeElement;
  var sid = null;
  if (clickedBtn && clickedBtn.dataset.sid) {
    sid = clickedBtn.dataset.sid;
    finBtn = clickedBtn;
  } else {
    var result = document.getElementById('gifer-result');
    sid = result ? result.dataset.sessionId : giferState.sessionId;
  }
  if (!sid) return;
  if (finBtn && finBtn.disabled) return;
  if (finBtn) { finBtn.disabled = true; finBtn.style.opacity = '0.3'; finBtn.textContent = 'SAVING...'; }

  try {
    var resp = await fetch(SCRIPT_API + '/finalize-session', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: sid, script_type: 'gifer' }),
    });
    var data = await resp.json();

    if (data.success || data.baserow_entry) {
      giferState.finalized = true;
      giferState.finalUrl = (data.preview_url || '').replace('script-bot-assets', 'tool-assets');

      /* Status line — find in current result or create after buttons */
      var parentResult = finBtn ? finBtn.closest('.tool-result, .tool-result-history') : null;
      var status = parentResult ? parentResult.querySelector('.tool-result-status') : document.getElementById('gifer-status');
      if (!status && parentResult) {
        status = document.createElement('div');
        status.className = 'tool-result-status';
        parentResult.appendChild(status);
      }
      if (status) {
        status.innerHTML =
          '<span style="color:var(--c-green)">\u2713 Saved to Baserow</span>' +
          (giferState.finalUrl ? ' <a href="' + giferState.finalUrl + '" target="_blank">' + giferState.finalUrl + '</a>' : '');
      }

      /* Disable REDO + FINALIZE */
      if (finBtn) { finBtn.textContent = 'FINALIZED'; finBtn.disabled = true; finBtn.style.opacity = '0.3'; }
      var redoBtn = document.querySelector('#gifer-btns [data-action="gifer-redo"]');
      if (redoBtn) { redoBtn.disabled = true; redoBtn.style.opacity = '0.3'; redoBtn.style.pointerEvents = 'none'; }
    } else {
      if (finBtn) { finBtn.disabled = false; finBtn.style.opacity = ''; finBtn.textContent = 'FINALIZE AND SAVE'; }
      giferRenderError(data.error || 'Finalize failed');
    }
  } catch (e) {
    if (finBtn) { finBtn.disabled = false; finBtn.style.opacity = ''; finBtn.textContent = 'FINALIZE AND SAVE'; }
    giferRenderError('Finalize failed: ' + e.message);
  }
}

/* ─── Download ──────────────────────────────────────────────── */

function giferDownload() {
  var url = giferState.finalUrl || giferState.resultUrl;
  if (!url) return;
  var a = document.createElement('a');
  a.href = url;
  a.download = url.split('/').pop() || 'output.gif';
  a.target = '_blank';
  document.body.appendChild(a);
  a.click();
  a.remove();
}

/* ─── Create New (fresh form below finalized result) ─────────── */

function giferNew() {
  var wrap = document.querySelector('.tool-wrap');
  if (!wrap) return;

  /* Detach current result + arrange (keep result visible, remove IDs) */
  var oldResult = document.getElementById('gifer-result');
  if (oldResult) {
    oldResult.removeAttribute('id');
    oldResult.classList.add('tool-result-history');
    /* Disable REDO + CREATE NEW, keep DOWNLOAD + FINALIZE */
    var oldSid = oldResult.dataset.sessionId || '';
    oldResult.querySelectorAll('.tool-action-btn').forEach(function(btn) {
      var action = btn.dataset.action;
      if (action === 'gifer-finalize' && oldSid) {
        btn.dataset.sid = oldSid;
        btn.removeAttribute('id');
      } else if (action !== 'gifer-download' && action !== 'gifer-finalize') {
        btn.disabled = true;
        btn.style.opacity = '0.3';
        btn.style.pointerEvents = 'none';
      }
    });
  }
  /* Remove old upload area + arrange */
  var oldUpload = document.getElementById('gifer-upload');
  if (oldUpload) oldUpload.remove();
  var oldArrange = document.getElementById('gifer-arrange');
  if (oldArrange) oldArrange.remove();

  /* Reset state */
  giferState = { sessionId: null, files: [], resultUrl: null, finalUrl: null, finalized: false };

  /* Build fresh section */
  var section = document.createElement('div');
  section.className = 'gifer-run';
  section.innerHTML =
    '<div class="tool-separator"></div>' +
    '<div class="tool-upload" id="gifer-upload">' +
      '<svg fill="currentColor"><use href="icons/sprite.svg#i-plus"/></svg>' +
      '<span class="tool-upload-lbl">CLICK OR DRAG & DROP TO ADD IMAGES</span>' +
    '</div>' +
    '<div id="gifer-arrange">' +
      '<div class="tool-settings" style="display:none">' +
        '<div class="tool-setting"><span class="tool-setting-lbl">QUALITY:</span>' +
          '<select class="tool-select" id="gifer-quality"><option>LOW</option><option selected>MEDIUM</option><option>HIGH</option><option>ULTRA</option></select></div>' +
        '<div class="tool-setting"><span class="tool-setting-lbl">SIZE:</span>' +
          '<input class="tool-input-sm" id="gifer-size-w" type="text" value="" placeholder="auto">' +
          '<span class="tool-size-x">\u00d7</span>' +
          '<input class="tool-input-sm" id="gifer-size-h" type="text" value="" placeholder="auto"></div>' +
      '</div>' +
      '<div class="tool-list-head" style="display:none"><span class="tool-list-head-lbl">duration (seconds)</span></div>' +
      '<div class="tool-list" id="gifer-list" style="display:none"></div>' +
      '<div class="tool-add" style="display:none"><button class="tool-action-btn" data-action="gifer-add-more">+ ADD MORE IMAGES</button></div>' +
      '<div class="tool-actions"><button class="btn-ico" data-action="gifer-generate" disabled style="opacity:0.3">' +
        '<svg fill="currentColor" style="width:20px;height:20px"><use href="icons/sprite.svg#i-gif"/></svg> GENERATE GIF</button></div>' +
    '</div>' +
    '<div class="tool-result" id="gifer-result" style="display:none"></div>';

  wrap.appendChild(section);
  bindUploadArea(document.getElementById('gifer-upload'), giferUploadFiles, giferPickFiles);

  /* New session */
  fetch(SCRIPT_API + '/session/create', { method: 'POST' })
    .then(function(r) { return r.json(); })
    .then(function(d) {
      giferState.sessionId = d.session_id;
    });

  section.scrollIntoView({ behavior: 'smooth' });
}

/* ─── Duration Arrows ───────────────────────────────────────── */

function giferDurChange(idx, delta) {
  if (!giferState.files[idx]) return;
  var val = parseFloat(giferState.files[idx].duration) || 1;
  val = Math.max(0.01, val + delta);
  giferState.files[idx].duration = String(Math.round(val * 100) / 100);
  var input = document.querySelector('[data-action-input="gifer-dur"][data-idx="' + idx + '"]');
  if (input) input.value = giferState.files[idx].duration;
}

function giferRemoveFile(idx) {
  giferState.files.splice(idx, 1);
  renderGiferList();
  updateGiferGenBtn();
}

/* ─── Show/hide arrange details (settings, list, add more) ──── */

function giferHideArrangeDetails() {
  var els = document.querySelectorAll('#gifer-arrange .tool-settings, #gifer-arrange .tool-list-head, #gifer-arrange .tool-list, #gifer-arrange .tool-add');
  els.forEach(function(el) { el.style.display = 'none'; });
}

function giferShowArrangeDetails() {
  var els = document.querySelectorAll('#gifer-arrange .tool-settings, #gifer-arrange .tool-list-head, #gifer-arrange .tool-list, #gifer-arrange .tool-add');
  els.forEach(function(el) { el.style.display = ''; });
}

/* ─── Video Thumbnail Generator ──────────────────────────────── */

function videoThumb(file) {
  return new Promise(function(resolve) {
    var url = URL.createObjectURL(file);
    var video = document.createElement('video');
    video.preload = 'metadata';
    video.muted = true;
    video.src = url;
    video.onloadeddata = function() {
      video.currentTime = 0.5;
    };
    video.onseeked = function() {
      var canvas = document.createElement('canvas');
      canvas.width = 160;
      canvas.height = 90;
      canvas.getContext('2d').drawImage(video, 0, 0, 160, 90);
      URL.revokeObjectURL(url);
      resolve(canvas.toDataURL('image/jpeg', 0.7));
    };
    video.onerror = function() {
      URL.revokeObjectURL(url);
      resolve('');
    };
  });
}

/* ═══════════════════════════════════════════════════════════════
   HELPERS
   ═══════════════════════════════════════════════════════════════ */

function esc(str) {
  var div = document.createElement('div');
  div.textContent = str;
  return div.innerHTML;
}

function formatBytes(bytes) {
  if (bytes < 1024) return bytes + ' B';
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
  return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
}


/* ═══════════════════════════════════════════════════════════════
   CLIPPER
   ═══════════════════════════════════════════════════════════════ */

var clipperState = {
  sessionId: null,
  files: [],
  resultUrl: null,
  finalUrl: null,
  finalized: false,
};

/* ─── Init ──────────────────────────────────────────────────── */

async function initClipper() {
  clipperState = { sessionId: null, files: [], resultUrl: null, finalUrl: null, finalized: false };

  var list = document.getElementById('clipper-list');
  if (list) list.innerHTML = '';

  try {
    var resp = await fetch(SCRIPT_API + '/session/create', { method: 'POST' });
    var data = await resp.json();
    clipperState.sessionId = data.session_id;
  } catch (e) {
    console.warn('Script-Runner not available');
  }

  bindUploadArea(document.getElementById('clipper-upload'), clipperUploadFiles, clipperPickFiles, ['image', 'video', 'animation']);
  clipperShowArrange();
  clipperHideArrangeDetails();
  updateClipperGenBtn();
}

/* ─── File Pick & Upload ────────────────────────────────────── */

function clipperPickFiles() {
  var input = document.createElement('input');
  input.type = 'file';
  input.accept = 'image/*,video/*';
  input.multiple = true;
  input.onchange = function(e) {
    if (e.target.files.length) clipperUploadFiles(e.target.files);
  };
  input.click();
}

async function clipperUploadFiles(fileList) {
  if (!clipperState.sessionId) return;

  /* Generate thumbnails — canvas grab for videos, blob URL for images */
  var localThumbs = [];
  for (var i = 0; i < fileList.length; i++) {
    var file = fileList[i];
    if (file.type.startsWith('video/')) {
      localThumbs.push(await videoThumb(file));
    } else {
      localThumbs.push(URL.createObjectURL(file));
    }
  }

  var formData = new FormData();
  for (var i = 0; i < fileList.length; i++) {
    formData.append('files', fileList[i]);
  }

  try {
    var resp = await fetch(SCRIPT_API + '/upload/' + clipperState.sessionId, {
      method: 'POST',
      body: formData,
    });
    var data = await resp.json();

    (data.uploaded || []).forEach(function(name, idx) {
      clipperState.files.push({
        name: name,
        thumbUrl: localThumbs[idx] || '',
        duration: '4',
      });
    });

    renderClipperList();
    clipperShowArrangeDetails();
    updateClipperGenBtn();
  } catch (e) {
    console.error('Clipper upload failed:', e);
  }
}

/* ─── Show/Hide ─────────────────────────────────────────────── */

function clipperShowArrange() {
  var arrange = document.getElementById('clipper-arrange');
  var result = document.getElementById('clipper-result');
  var upload = document.getElementById('clipper-upload');
  if (arrange) arrange.style.display = '';
  if (upload) upload.style.display = '';
  if (result) result.style.display = 'none';
}

function clipperShowResultPanel() {
  var arrange = document.getElementById('clipper-arrange');
  var result = document.getElementById('clipper-result');
  var upload = document.getElementById('clipper-upload');
  if (arrange) arrange.style.display = 'none';
  if (upload) upload.style.display = 'none';
  if (result) result.style.display = '';
}

function clipperHideArrangeDetails() {
  var els = document.querySelectorAll('#clipper-arrange .tool-settings, #clipper-arrange .tool-list-head, #clipper-arrange .tool-list, #clipper-arrange .tool-add');
  els.forEach(function(el) { el.style.display = 'none'; });
}

function clipperShowArrangeDetails() {
  var els = document.querySelectorAll('#clipper-arrange .tool-settings, #clipper-arrange .tool-list-head, #clipper-arrange .tool-list, #clipper-arrange .tool-add');
  els.forEach(function(el) { el.style.display = ''; });
}

/* ─── Render File List ──────────────────────────────────────── */

function renderClipperList() {
  var list = document.getElementById('clipper-list');
  if (!list) return;

  if (clipperState.files.length === 0) { list.innerHTML = ''; return; }

  var html = '';
  clipperState.files.forEach(function(file, idx) {
    html +=
      '<div class="tool-item" data-idx="' + idx + '">' +
        '<div class="tool-item-drag"><svg fill="currentColor"><use href="icons/sprite.svg#i-shuffle"/></svg></div>' +
        '<span class="tool-item-num">' + String(idx + 1).padStart(2, '0') + '</span>' +
        '<div class="tool-item-thumb" style="background:url(\'' + file.thumbUrl + '\') center/cover"></div>' +
        '<span class="tool-item-name">' + esc(file.name.replace(/^\d+-/, '')) + '</span>' +
        '<div class="tool-item-arrows">' +
          '<div class="tool-item-arrow" data-action="clipper-dur-up" data-idx="' + idx + '"><svg fill="currentColor"><use href="icons/sprite.svg#i-chev-up"/></svg></div>' +
          '<input class="tool-item-val" type="text" value="' + file.duration + '" data-action-input="clipper-dur" data-idx="' + idx + '">' +
          '<div class="tool-item-arrow" data-action="clipper-dur-down" data-idx="' + idx + '"><svg fill="currentColor"><use href="icons/sprite.svg#i-chev-down"/></svg></div>' +
        '</div>' +
        '<div class="tool-item-delete" data-action="clipper-remove" data-idx="' + idx + '"><svg fill="currentColor"><use href="icons/sprite.svg#i-delete"/></svg></div>' +
      '</div>';
  });

  list.innerHTML = html;

  list.querySelectorAll('[data-action-input="clipper-dur"]').forEach(function(input) {
    input.addEventListener('change', function() {
      var idx = parseInt(input.dataset.idx);
      if (clipperState.files[idx]) clipperState.files[idx].duration = input.value;
    });
  });

  list.querySelectorAll('.tool-item').forEach(function(item) {
    item.setAttribute('draggable', 'true');
    item.addEventListener('dragstart', function(e) {
      e.dataTransfer.setData('text/plain', item.dataset.idx);
      item.classList.add('dragging');
    });
    item.addEventListener('dragend', function() { item.classList.remove('dragging'); });
    item.addEventListener('dragover', function(e) { e.preventDefault(); item.classList.add('drag-over'); });
    item.addEventListener('dragleave', function() { item.classList.remove('drag-over'); });
    item.addEventListener('drop', function(e) {
      e.preventDefault();
      item.classList.remove('drag-over');
      var fromIdx = parseInt(e.dataTransfer.getData('text/plain'));
      var toIdx = parseInt(item.dataset.idx);
      if (fromIdx !== toIdx) {
        var moved = clipperState.files.splice(fromIdx, 1)[0];
        clipperState.files.splice(toIdx, 0, moved);
        renderClipperList();
      }
    });
  });
}

function updateClipperGenBtn() {
  var btn = document.querySelector('[data-action="clipper-generate"]');
  if (btn) {
    btn.disabled = clipperState.files.length < 1;
    btn.style.opacity = clipperState.files.length < 1 ? '0.3' : '';
  }
}

/* ─── Generate ──────────────────────────────────────────────── */

async function clipperGenerate() {
  if (!clipperState.sessionId || clipperState.files.length < 1) return;

  var btn = document.querySelector('[data-action="clipper-generate"]');
  if (btn) { btn.disabled = true; btn.textContent = 'GENERATING...'; }

  var durations = clipperState.files.map(function(f) { return f.duration; }).join(',');

  var payload = {
    session_id: clipperState.sessionId,
    durations: durations,
    animation: (document.getElementById('clipper-animation') || {}).value || 'zoom_in',
    direction: (document.getElementById('clipper-direction') || {}).value || '90',
    intensity: (document.getElementById('clipper-intensity') || {}).value || '20',
    resolution: (document.getElementById('clipper-resolution') || {}).value || '1080p',
    transition: (document.getElementById('clipper-transition') || {}).value || '1',
  };

  try {
    var resp = await fetch(SCRIPT_API + '/run/clipper', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    var data = await resp.json();

    if (data.success) {
      clipperState.resultUrl = SCRIPT_API + (data.preview_url || '/preview/' + clipperState.sessionId + '/' + data.filename) + '?t=' + Date.now();
      clipperState.finalized = false;
      clipperRenderResult();
      clipperShowResultPanel();
    } else {
      clipperRenderError(data.error || 'Generation failed');
      clipperShowResultPanel();
    }
  } catch (e) {
    clipperRenderError('Request failed: ' + e.message);
    clipperShowResultPanel();
  }

  if (btn) {
    btn.disabled = false;
    btn.innerHTML = '<svg fill="currentColor" style="width:28px;height:14px"><use href="icons/sprite.svg#i-mpg"/></svg> GENERATE CLIP';
  }
}

/* ─── Result ────────────────────────────────────────────────── */

function clipperRenderResult() {
  var result = document.getElementById('clipper-result');
  if (!result) return;
  result.dataset.sessionId = clipperState.sessionId;

  result.innerHTML =
    '<div class="tool-result-head">RESULT</div>' +
    '<div class="tool-result-preview"><video src="' + clipperState.resultUrl + '" controls autoplay muted loop></video></div>' +
    '<div class="tool-result-btns" id="clipper-btns">' +
      '<button class="tool-action-btn" data-action="clipper-finalize" id="clipper-finalize-btn">FINALIZE AND SAVE</button>' +
      '<button class="tool-action-btn" data-action="clipper-download">DOWNLOAD</button>' +
      '<button class="tool-action-btn" data-action="clipper-new">CREATE NEW CLIP</button>' +
      '<button class="tool-action-btn bucket-add-btn" data-action="clipper-bucket">BUCKET</button>' +
    '</div>' +
    '<div class="tool-result-status" id="clipper-status"></div>';
}

function clipperRenderError(msg) {
  var result = document.getElementById('clipper-result');
  if (!result) return;
  result.innerHTML =
    '<div class="tool-result-error">' + esc(msg) + '</div>' +
    '<div class="tool-result-btns">' +
      '<button class="tool-action-btn" data-action="clipper-new">CREATE NEW CLIP</button>' +
    '</div>';
}

/* ─── Finalize ──────────────────────────────────────────────── */

async function clipperFinalize() {
  var result = document.getElementById('clipper-result');
  var sid = result ? result.dataset.sessionId : clipperState.sessionId;
  var finBtn = document.getElementById('clipper-finalize-btn');
  if (!sid) return;
  if (finBtn && finBtn.disabled) return;
  if (finBtn) { finBtn.disabled = true; finBtn.style.opacity = '0.3'; finBtn.textContent = 'SAVING...'; }

  try {
    var resp = await fetch(SCRIPT_API + '/finalize-session', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: sid, script_type: 'clipper' }),
    });
    var data = await resp.json();

    if (data.success || data.baserow_entry) {
      clipperState.finalized = true;
      clipperState.finalUrl = (data.preview_url || '').replace('script-bot-assets', 'tool-assets');
      var status = document.getElementById('clipper-status');
      if (status) {
        status.innerHTML =
          '<span style="color:var(--c-green)">\u2713 Saved to Baserow</span>' +
          (clipperState.finalUrl ? ' <a href="' + clipperState.finalUrl + '" target="_blank">' + clipperState.finalUrl + '</a>' : '');
      }
      if (finBtn) finBtn.textContent = 'FINALIZED';
    } else {
      if (finBtn) { finBtn.disabled = false; finBtn.style.opacity = ''; finBtn.textContent = 'FINALIZE AND SAVE'; }
    }
  } catch (e) {
    if (finBtn) { finBtn.disabled = false; finBtn.style.opacity = ''; finBtn.textContent = 'FINALIZE AND SAVE'; }
  }
}

/* ─── Download ──────────────────────────────────────────────── */

function clipperDownload() {
  var url = clipperState.finalUrl || clipperState.resultUrl;
  if (!url) return;
  var clean = url.split('?')[0];
  var a = document.createElement('a');
  a.href = clean;
  a.download = clean.split('/').pop() || 'output.mp4';
  a.target = '_blank';
  document.body.appendChild(a);
  a.click();
  a.remove();
}

/* ─── Create New ────────────────────────────────────────────── */

function clipperNew() {
  var wrap = document.querySelector('.tool-wrap');
  if (!wrap) return;

  var oldResult = document.getElementById('clipper-result');
  if (oldResult) {
    oldResult.removeAttribute('id');
    oldResult.classList.add('tool-result-history');
    oldResult.querySelectorAll('.tool-action-btn').forEach(function(btn) {
      var action = btn.dataset.action;
      if (action !== 'clipper-download' && action !== 'clipper-finalize') {
        btn.disabled = true; btn.style.opacity = '0.3'; btn.style.pointerEvents = 'none';
      }
    });
  }
  var oldUpload = document.getElementById('clipper-upload');
  if (oldUpload) oldUpload.remove();
  var oldArrange = document.getElementById('clipper-arrange');
  if (oldArrange) oldArrange.remove();

  clipperState = { sessionId: null, files: [], resultUrl: null, finalUrl: null, finalized: false };

  var section = document.createElement('div');
  section.className = 'clipper-run';
  section.innerHTML =
    '<div class="tool-separator"></div>' +
    '<div class="tool-upload" id="clipper-upload">' +
      '<svg fill="currentColor"><use href="icons/sprite.svg#i-plus"/></svg>' +
      '<span class="tool-upload-lbl">CLICK OR DRAG & DROP TO ADD IMAGES</span>' +
    '</div>' +
    '<div id="clipper-arrange">' +
      '<div class="tool-settings" style="display:none">' +
        '<div class="tool-setting"><span class="tool-setting-lbl">ANIMATION:</span>' +
          '<select class="tool-select" id="clipper-animation"><option value="pan">PAN</option><option value="zoom_in" selected>ZOOM IN</option><option value="zoom_out">ZOOM OUT</option><option value="none">NONE</option></select></div>' +
        '<div class="tool-setting"><span class="tool-setting-lbl">DIRECTION:</span>' +
          '<input class="tool-input-sm" id="clipper-direction" type="text" value="90" style="width:40px"><span class="tool-size-x">&deg;</span></div>' +
        '<div class="tool-setting"><span class="tool-setting-lbl">INTENSITY:</span>' +
          '<select class="tool-select" id="clipper-intensity"><option value="10">10</option><option value="20" selected>20</option><option value="30">30</option></select></div>' +
      '</div>' +
      '<div class="tool-settings" style="display:none">' +
        '<div class="tool-setting"><span class="tool-setting-lbl">RESOLUTION:</span>' +
          '<select class="tool-select" id="clipper-resolution"><option value="1080x1080" selected>Square 1:1 (1080)</option><option value="1080x1350">Portrait 4:5 (1080x1350)</option><option value="1080x1920">Story 9:16 (1080x1920)</option><option value="1920x1080">Landscape 16:9 (1920x1080)</option></select></div>' +
        '<div class="tool-setting"><span class="tool-setting-lbl">TRANSITION:</span>' +
          '<input class="tool-input-sm" id="clipper-transition" type="text" value="1" style="width:40px"><span class="tool-size-x">s</span></div>' +
      '</div>' +
      '<div class="tool-list-head" style="display:none"><span class="tool-list-head-lbl">duration (seconds)</span></div>' +
      '<div class="tool-list" id="clipper-list" style="display:none"></div>' +
      '<div class="tool-add" style="display:none"><button class="tool-action-btn" data-action="clipper-add-more">+ ADD MORE IMAGES</button></div>' +
      '<div class="tool-actions"><button class="btn-ico" data-action="clipper-generate" disabled style="opacity:0.3">' +
        '<svg fill="currentColor" style="width:28px;height:14px"><use href="icons/sprite.svg#i-mpg"/></svg> GENERATE CLIP</button></div>' +
    '</div>' +
    '<div class="tool-result" id="clipper-result" style="display:none"></div>';

  wrap.appendChild(section);
  bindUploadArea(document.getElementById('clipper-upload'), clipperUploadFiles, clipperPickFiles, ['image', 'video', 'animation']);

  fetch(SCRIPT_API + '/session/create', { method: 'POST' })
    .then(function(r) { return r.json(); })
    .then(function(d) { clipperState.sessionId = d.session_id; });

  section.scrollIntoView({ behavior: 'smooth' });
}

/* ─── Duration Arrows ───────────────────────────────────────── */

function clipperDurChange(idx, delta) {
  if (!clipperState.files[idx]) return;
  var val = parseFloat(clipperState.files[idx].duration) || 4;
  val = Math.max(0.5, val + delta);
  clipperState.files[idx].duration = String(Math.round(val * 10) / 10);
  var input = document.querySelector('[data-action-input="clipper-dur"][data-idx="' + idx + '"]');
  if (input) input.value = clipperState.files[idx].duration;
}

function clipperRemoveFile(idx) {
  clipperState.files.splice(idx, 1);
  renderClipperList();
  updateClipperGenBtn();
}


/* ═══════════════════════════════════════════════════════════════
   TYPER
   ═══════════════════════════════════════════════════════════════ */

var typerState = {
  sessionId: null,
  resultUrls: [],
  finalUrl: null,
  finalized: false,
};

/* ─── Init ──────────────────────────────────────────────────── */

async function initTyper() {
  typerState = { sessionId: null, resultUrls: [], finalUrl: null, finalized: false };

  try {
    var resp = await fetch(SCRIPT_API + '/session/create', { method: 'POST' });
    var data = await resp.json();
    typerState.sessionId = data.session_id;
  } catch (e) {
    console.warn('Script-Runner not available');
  }

  typerShowArrange();
}

/* ─── Show/Hide ─────────────────────────────────────────────── */

function typerShowArrange() {
  var arrange = document.getElementById('typer-arrange');
  var result = document.getElementById('typer-result');
  if (arrange) arrange.style.display = '';
  if (result) result.style.display = 'none';
}

function typerShowResultPanel() {
  var arrange = document.getElementById('typer-arrange');
  var result = document.getElementById('typer-result');
  if (arrange) arrange.style.display = 'none';
  if (result) result.style.display = '';
}

/* ─── Generate ──────────────────────────────────────────────── */

async function typerGenerate() {
  /* Fresh session each generate (no leftover output files) */
  try {
    var sResp = await fetch(SCRIPT_API + '/session/create', { method: 'POST' });
    var sData = await sResp.json();
    typerState.sessionId = sData.session_id;
  } catch (e) {}
  if (!typerState.sessionId) return;

  var textEl = document.getElementById('typer-text');
  var text = textEl ? textEl.value.trim() : '';
  if (!text) return;

  var btn = document.querySelector('[data-action="typer-generate"]');
  if (btn) { btn.disabled = true; btn.textContent = 'GENERATING...'; }

  var sizeW = (document.getElementById('typer-size-w') || {}).value || '1080';
  var sizeH = (document.getElementById('typer-size-h') || {}).value || '1080';

  var payload = {
    session_id: typerState.sessionId,
    text: text.replace(/\/b/g, '\\n'),
    size: sizeW + 'x' + sizeH,
    template: (document.getElementById('typer-template') || {}).value || 'dark',
    font: (document.getElementById('typer-font') || {}).value || 'bold',
    fontsize: (document.getElementById('typer-fontsize') || {}).value || 'medium',
    layout: (document.getElementById('typer-layout') || {}).value || 'left',
  };

  try {
    var resp = await fetch(SCRIPT_API + '/run/typer', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    var data = await resp.json();

    if (data.success) {
      /* Typer can produce multiple slides — check session output */
      var filesResp = await fetch(SCRIPT_API + '/session/' + typerState.sessionId + '/files');
      var filesData = await filesResp.json();
      typerState.resultUrls = (filesData.output || []).map(function(name) {
        return SCRIPT_API + '/preview/' + typerState.sessionId + '/' + name + '?t=' + Date.now();
      });
      typerState.finalized = false;
      typerRenderResult();
      typerShowResultPanel();
    } else {
      typerRenderError(data.error || 'Generation failed');
      typerShowResultPanel();
    }
  } catch (e) {
    typerRenderError('Request failed: ' + e.message);
    typerShowResultPanel();
  }

  if (btn) {
    btn.disabled = false;
    btn.innerHTML = '<svg fill="currentColor" style="width:28px;height:14px"><use href="icons/sprite.svg#i-typer"/></svg> GENERATE PNG';
  }
}

/* ─── Result ────────────────────────────────────────────────── */

function typerRenderResult() {
  var result = document.getElementById('typer-result');
  if (!result) return;
  result.dataset.sessionId = typerState.sessionId;

  var html = '<div class="tool-result-head">RESULT</div>';

  if (typerState.resultUrls.length > 1) {
    html += '<div class="typer-slides">';
    typerState.resultUrls.forEach(function(url, idx) {
      html += '<div class="tool-result-preview"><img src="' + url + '" loading="lazy"></div>';
    });
    html += '</div>';
  } else if (typerState.resultUrls.length === 1) {
    html += '<div class="tool-result-preview"><img src="' + typerState.resultUrls[0] + '" loading="lazy"></div>';
  }

  html +=
    '<div class="tool-result-btns" id="typer-btns">' +
      '<button class="tool-action-btn" data-action="typer-edit">EDIT TEXT</button>' +
      '<button class="tool-action-btn" data-action="typer-finalize" id="typer-finalize-btn">FINALIZE AND SAVE</button>' +
      '<button class="tool-action-btn" data-action="typer-download">DOWNLOAD</button>' +
      '<button class="tool-action-btn" data-action="typer-new">CREATE NEW</button>' +
    '</div>' +
    '<div class="tool-result-status" id="typer-status"></div>';

  result.innerHTML = html;
}

function typerRenderError(msg) {
  var result = document.getElementById('typer-result');
  if (!result) return;
  result.innerHTML =
    '<div class="tool-result-error">' + esc(msg) + '</div>' +
    '<div class="tool-result-btns">' +
      '<button class="tool-action-btn" data-action="typer-edit">BACK TO EDIT</button>' +
    '</div>';
}

/* ─── Edit (back to text input) ─────────────────────────────── */

function typerEdit() {
  typerState.resultUrls = [];
  typerState.finalized = false;
  typerShowArrange();
}

/* ─── Finalize ──────────────────────────────────────────────── */

async function typerFinalize() {
  var result = document.getElementById('typer-result');
  var sid = result ? result.dataset.sessionId : typerState.sessionId;
  var finBtn = document.getElementById('typer-finalize-btn');
  if (!sid) return;
  if (finBtn && finBtn.disabled) return;
  if (finBtn) { finBtn.disabled = true; finBtn.style.opacity = '0.3'; finBtn.textContent = 'SAVING...'; }

  try {
    var resp = await fetch(SCRIPT_API + '/finalize-session', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: sid, script_type: 'typer' }),
    });
    var data = await resp.json();

    if (data.success || data.baserow_entry) {
      typerState.finalized = true;
      typerState.finalUrl = (data.preview_url || '').replace('script-bot-assets', 'tool-assets');
      var status = document.getElementById('typer-status');
      if (status) {
        status.innerHTML =
          '<span style="color:var(--c-green)">\u2713 Saved to Baserow</span>' +
          (typerState.finalUrl ? ' <a href="' + typerState.finalUrl + '" target="_blank">' + typerState.finalUrl + '</a>' : '');
      }
      if (finBtn) finBtn.textContent = 'FINALIZED';
      var editBtn = document.querySelector('#typer-btns [data-action="typer-edit"]');
      if (editBtn) { editBtn.disabled = true; editBtn.style.opacity = '0.3'; editBtn.style.pointerEvents = 'none'; }
    } else {
      if (finBtn) { finBtn.disabled = false; finBtn.style.opacity = ''; finBtn.textContent = 'FINALIZE AND SAVE'; }
    }
  } catch (e) {
    if (finBtn) { finBtn.disabled = false; finBtn.style.opacity = ''; finBtn.textContent = 'FINALIZE AND SAVE'; }
  }
}

/* ─── Download ──────────────────────────────────────────────── */

function typerDownload() {
  var url = typerState.finalUrl || (typerState.resultUrls.length ? typerState.resultUrls[0] : null);
  if (!url) return;
  var clean = url.split('?')[0];
  var a = document.createElement('a');
  a.href = clean;
  a.download = clean.split('/').pop() || 'output.png';
  a.target = '_blank';
  document.body.appendChild(a);
  a.click();
  a.remove();
}

/* ─── Create New ────────────────────────────────────────────── */

function typerNew() {
  var wrap = document.querySelector('.tool-wrap');
  if (!wrap) return;

  var oldResult = document.getElementById('typer-result');
  if (oldResult) {
    oldResult.removeAttribute('id');
    oldResult.classList.add('tool-result-history');
    oldResult.querySelectorAll('.tool-action-btn').forEach(function(btn) {
      var action = btn.dataset.action;
      if (action !== 'typer-download' && action !== 'typer-finalize') {
        btn.disabled = true; btn.style.opacity = '0.3'; btn.style.pointerEvents = 'none';
      }
    });
  }
  var oldArrange = document.getElementById('typer-arrange');
  if (oldArrange) oldArrange.remove();

  typerState = { sessionId: null, resultUrls: [], finalUrl: null, finalized: false };

  var section = document.createElement('div');
  section.className = 'typer-run';
  section.innerHTML =
    '<div class="tool-separator"></div>' +
    '<div id="typer-arrange">' +
      '<textarea class="tool-text" id="typer-text" rows="5" placeholder="Enter your text here..."></textarea>' +
      '<div class="tool-settings">' +
        '<div class="tool-setting"><span class="tool-setting-lbl">TEMPLATE:</span>' +
          '<select class="tool-select" id="typer-template"><option value="dark" selected>DARK</option><option value="darker">DARKER</option><option value="light">LIGHT</option><option value="black">BLACK</option></select></div>' +
        '<div class="tool-setting"><span class="tool-setting-lbl">FONT:</span>' +
          '<select class="tool-select" id="typer-font"><option value="bold" selected>BOLD</option><option value="bold-italic">BOLD ITALIC</option><option value="thin">THIN</option><option value="thin-italic">THIN ITALIC</option></select></div>' +
      '</div>' +
      '<div class="tool-settings">' +
        '<div class="tool-setting"><span class="tool-setting-lbl">FONTSIZE:</span>' +
          '<select class="tool-select" id="typer-fontsize"><option value="small">SMALL</option><option value="medium" selected>MEDIUM</option><option value="large">LARGE</option></select></div>' +
        '<div class="tool-setting"><span class="tool-setting-lbl">LAYOUT:</span>' +
          '<select class="tool-select" id="typer-layout"><option value="left" selected>LEFT</option><option value="centered">CENTERED</option></select></div>' +
        '<div class="tool-setting"><span class="tool-setting-lbl">SIZE:</span>' +
          '<input class="tool-input-sm" id="typer-size-w" type="text" value="1080">' +
          '<span class="tool-size-x">\u00d7</span>' +
          '<input class="tool-input-sm" id="typer-size-h" type="text" value="1080"></div>' +
      '</div>' +
      '<div class="tool-actions"><button class="btn-ico" data-action="typer-generate">' +
        '<svg fill="currentColor" style="width:28px;height:14px"><use href="icons/sprite.svg#i-typer"/></svg> GENERATE PNG</button></div>' +
    '</div>' +
    '<div class="tool-result" id="typer-result" style="display:none"></div>';

  wrap.appendChild(section);

  fetch(SCRIPT_API + '/session/create', { method: 'POST' })
    .then(function(r) { return r.json(); })
    .then(function(d) { typerState.sessionId = d.session_id; });

  section.scrollIntoView({ behavior: 'smooth' });
}

/* ═══════════════════════════════════════════════════════════════
   PAGE INIT ROUTER (called from app.js navigate())
   ═══════════════════════════════════════════════════════════════ */

function initToolPage(page) {
  switch (page) {
    case 'gifer':     initGifer(); break;
    case 'clipper':   initClipper(); break;
    case 'typer':     initTyper(); break;
    case 'pixeltext': if (typeof initPixelText === 'function') initPixelText(); break;
    case 'post':      if (typeof initPost === 'function') initPost(); break;
    case 'imagegen':  /* initImageGen(); */ break;
    case 'ttsgen':    if (typeof initTtsGen === 'function') initTtsGen(); break;
    case 'musicgen':  if (typeof initMusicGen === 'function') initMusicGen(); break;
  }
}

/* ═══════════════════════════════════════════════════════════════
   ADD TO BUCKET — Gifer / Clipper
   ═══════════════════════════════════════════════════════════════ */

function giferAddToBucket(btn) {
  var url = giferState.finalUrl || giferState.resultUrl;
  if (!url) return;
  bucketAdd({
    type: 'animation',
    url: url,
    thumb: url,
    source: 'gifer',
    label: 'GIF'
  });
  btn.classList.add('bucket-add-ok');
  btn.textContent = 'ADDED';
  setTimeout(function() { btn.classList.remove('bucket-add-ok'); btn.textContent = 'BUCKET'; }, 800);
}

function clipperAddToBucket(btn) {
  var url = clipperState.finalUrl || clipperState.resultUrl;
  if (!url) return;
  bucketAdd({
    type: 'video',
    url: url,
    thumb: '',
    source: 'clipper',
    label: 'Clip'
  });
  btn.classList.add('bucket-add-ok');
  btn.textContent = 'ADDED';
  setTimeout(function() { btn.classList.remove('bucket-add-ok'); btn.textContent = 'BUCKET'; }, 800);
}

/* ═══════════════════════════════════════════════════════════════
   EVENT DELEGATION
   ═══════════════════════════════════════════════════════════════ */

document.addEventListener('click', function(e) {
  var target = e.target.closest('[data-action]');
  if (!target) return;
  var idx = parseInt(target.dataset.idx);

  switch (target.dataset.action) {
    case 'gifer-generate':  giferGenerate(); break;
    case 'gifer-redo':      giferRedo(); break;
    case 'gifer-finalize':  giferFinalize(); break;
    case 'gifer-download':  giferDownload(); break;
    case 'gifer-new':       giferNew(); break;
    case 'gifer-bucket':    giferAddToBucket(target); break;
    case 'gifer-add-more':  giferPickFiles(); break;
    case 'gifer-dur-up':    giferDurChange(idx, 0.5); break;
    case 'gifer-dur-down':  giferDurChange(idx, -0.5); break;
    case 'gifer-remove':    giferRemoveFile(idx); break;
    case 'clipper-generate':  clipperGenerate(); break;
    case 'clipper-finalize':  clipperFinalize(); break;
    case 'clipper-download':  clipperDownload(); break;
    case 'clipper-new':       clipperNew(); break;
    case 'clipper-bucket':    clipperAddToBucket(target); break;
    case 'clipper-add-more':  clipperPickFiles(); break;
    case 'clipper-dur-up':    clipperDurChange(idx, 0.5); break;
    case 'clipper-dur-down':  clipperDurChange(idx, -0.5); break;
    case 'clipper-remove':    clipperRemoveFile(idx); break;
    case 'typer-generate':  typerGenerate(); break;
    case 'typer-edit':      typerEdit(); break;
    case 'typer-finalize':  typerFinalize(); break;
    case 'typer-download':  typerDownload(); break;
    case 'typer-new':       typerNew(); break;
    case 'px-mode':         pxSetMode(target.dataset.mode); break;
    case 'px-trans':        pxSelectTransition(target.dataset.style); break;
    case 'px-prev-word':    pxPrevWord(); break;
    case 'px-next-word':    pxNextWord(); break;
    case 'px-preview':      pxStartPreview(); break;
    case 'px-render':       pxStartRender(); break;
    case 'px-cycle-preview':pxCyclePreview(parseInt(target.dataset.delta) || 1); break;
    case 'post-save':       postSave(); break;
    case 'post-new':        postNew(); break;
    case 'post-expand':     postExpand(parseInt(target.closest('[data-id]').dataset.id)); break;
    case 'post-select':     postSelect(parseInt(target.closest('[data-id]').dataset.id)); break;
    case 'post-filter':     postSetFilter(target.dataset.filter); break;
    case 'post-toggle-list':postToggleList(); break;
  }
});
