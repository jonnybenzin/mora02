/* ═══════════════════════════════════════════════════════════════
   MORA02 PILOT — VideoGen Module v2 (2026-04-03)
   ═══════════════════════════════════════════════════════════════
   ComfyUI + WAN 2.2: Prompt → Video → Download/New
   Flows: wan-t2v, wan-i2v, wan-i2i2v
   Uses Pilot /chat/{sid} with /vid commands.
   Videos: mora02.local:8092/wan/
   ───────────────────────────────────────────────────────────────
   Depends on: app.js (API_BASE, sessionId, initSession)
   ═══════════════════════════════════════════════════════════════ */

var VID_BASE = 'http://mora02.local:8092';

var vidState = {
  videoUrl: null,
  filename: null,
  prompt: '',
  flow: 'wan-t2v',
  format: '512x512',
  seed: null,
  generating: false,
  startFrameFile: null,
  endFrameFile: null,
};

/* ═══════════════════════════════════════════════════════════════
   INIT
   ═══════════════════════════════════════════════════════════════ */

function initVideoGen() {
  /* Deactivate previous video gen instances (prevent ID conflicts) */
  document.querySelectorAll('[id="vid-generate-btn"]').forEach(function(btn, idx, all) {
    if (idx < all.length - 1) {
      var w = btn.closest('.tool-wrap');
      if (w) {
        w.querySelectorAll('[id^="vid-"]').forEach(function(el) { el.removeAttribute('id'); });
        w.querySelectorAll('[data-action^="vid-"]').forEach(function(b) {
          b.disabled = true; b.style.opacity = '0.3'; b.style.pointerEvents = 'none';
        });
      }
    }
  });

  vidState = { videoUrl: null, filename: null, prompt: '', flow: 'wan-t2v', format: '1080x1080', seed: null, generating: false, startFrameFile: null, endFrameFile: null, _evtSource: null };
  vidHide('vid-result-section');
  vidHide('vid-progress-section');
  vidShow('vid-prompt-section');
  vidAutoResize('vid-prompt');
  vidUpdateUpload();
  vidBindDropZone('vid-startframe-drop', 'start');
  vidBindDropZone('vid-endframe-drop', 'end');
}

/* ═══════════════════════════════════════════════════════════════
   WORKFLOW TOGGLE — show/hide upload sections
   ═══════════════════════════════════════════════════════════════ */

function vidUpdateUpload() {
  var flow = document.getElementById('vid-flow');
  if (!flow) return;
  var v = flow.value;
  if (v === 'wan-i2v') {
    vidShow('vid-upload-section');
    vidHide('vid-upload-end-section');
  } else if (v === 'wan-i2i2v') {
    vidShow('vid-upload-section');
    vidShow('vid-upload-end-section');
  } else {
    vidHide('vid-upload-section');
    vidHide('vid-upload-end-section');
  }
}

/* ═══════════════════════════════════════════════════════════════
   DRAG & DROP UPLOAD (same UX as Gifer)
   ═══════════════════════════════════════════════════════════════ */

function vidBindDropZone(id, which) {
  var zone = document.getElementById(id);
  if (!zone) return;

  zone.addEventListener('dragover', function(e) {
    e.preventDefault();
    /* Bucket drag: show accept/reject feedback */
    if (e.dataTransfer.types && e.dataTransfer.types.indexOf('application/x-bucket-item') !== -1) {
      var accepted = typeof bucketDragItem !== 'undefined' && bucketDragItem && bucketDragItem.type === 'image';
      if (accepted) {
        e.dataTransfer.dropEffect = 'copy';
        zone.classList.add('bucket-drop-active');
        zone.classList.remove('bucket-drop-reject');
      } else {
        e.dataTransfer.dropEffect = 'none';
        zone.classList.add('bucket-drop-reject');
        zone.classList.remove('bucket-drop-active');
      }
      return;
    }
    zone.classList.add('dragover');
  });
  zone.addEventListener('dragleave', function() { zone.classList.remove('dragover'); zone.classList.remove('bucket-drop-active'); zone.classList.remove('bucket-drop-reject'); });
  zone.addEventListener('drop', function(e) {
    e.preventDefault();
    zone.classList.remove('dragover');
    /* Check for bucket item first */
    var bucketRaw = e.dataTransfer.getData('application/x-bucket-item');
    if (bucketRaw) {
      try {
        var item = JSON.parse(bucketRaw);
        if (item.type === 'image') vidHandleBucketDrop(item, which, zone);
      } catch (err) { console.warn('[vid] bucket drop parse error', err); }
      return;
    }
    if (e.dataTransfer.files.length) vidHandleFile(e.dataTransfer.files[0], which, zone);
  });
  zone.addEventListener('click', function() { vidPickFile(which, zone); });

  /* Also register as bucket drop zone for visual feedback */
  if (typeof bucketBindDropZone === 'function') {
    /* Don't re-bind drop (already handled above), just add visual feedback */
    zone.setAttribute('data-bucket-accepts', 'image');
  }
}

function vidPickFile(which, zone) {
  var input = document.createElement('input');
  input.type = 'file';
  input.accept = 'image/png,image/jpeg,image/webp';
  input.onchange = function() {
    if (input.files && input.files.length) vidHandleFile(input.files[0], which, zone);
  };
  input.click();
}

function vidHandleFile(file, which, zone) {
  if (which === 'start') {
    vidState.startFrameFile = file;
  } else {
    vidState.endFrameFile = file;
  }
  /* Show preview in the drop zone */
  var reader = new FileReader();
  reader.onload = function(e) {
    zone.innerHTML =
      '<div style="position:relative;width:100%">' +
        '<img src="' + e.target.result + '" style="width:100%;max-height:200px;object-fit:contain;border-radius:var(--sp-4);display:block">' +
        '<div style="position:absolute;top:var(--sp-8);right:var(--sp-8);background:var(--c-black);padding:var(--sp-4) var(--sp-8);border-radius:var(--sp-4);font-size:var(--fs-xs);color:var(--tx-muted);letter-spacing:var(--ls-wide)">' +
          (which === 'start' ? 'START FRAME' : 'END FRAME') + ' — ' + vidEsc(file.name) +
        '</div>' +
      '</div>';
  };
  reader.readAsDataURL(file);
}

/* ═══════════════════════════════════════════════════════════════
   BUCKET DROP → convert URL to File and show preview
   ═══════════════════════════════════════════════════════════════ */

async function vidHandleBucketDrop(item, which, zone) {
  try {
    var resp = await fetch(item.url);
    var blob = await resp.blob();
    var ext = item.url.split('.').pop().split('?')[0] || 'png';
    var file = new File([blob], 'bucket_' + which + '.' + ext, { type: blob.type || 'image/png' });
    vidHandleFile(file, which, zone);
  } catch (err) {
    console.warn('[vid] bucket image fetch failed', err);
  }
}

/* ═══════════════════════════════════════════════════════════════
   UPLOAD IMAGE TO COMFYUI
   ═══════════════════════════════════════════════════════════════ */

async function vidUploadImage(file) {
  var formData = new FormData();
  /* Sanitize filename: remove spaces, umlauts, special chars */
  var safeName = file.name.replace(/[^a-zA-Z0-9._-]/g, '_');
  formData.append('image', file, safeName);
  var resp = await fetch(API_BASE + '/upload/comfyui', {
    method: 'POST',
    body: formData,
  });
  if (!resp.ok) throw new Error('Image upload failed: ' + resp.status);
  var data = await resp.json();
  return data.name;
}

/* ═══════════════════════════════════════════════════════════════
   GENERATE (with SSE progress)
   ═══════════════════════════════════════════════════════════════ */

async function vidGenerate() {
  if (vidState.generating) return;

  var promptEl = document.getElementById('vid-prompt');
  var prompt = promptEl ? promptEl.value.trim() : '';
  if (!prompt) return;

  /* Read settings */
  vidState.prompt = prompt;
  vidState.flow = (document.getElementById('vid-flow') || {}).value || 'wan-t2v';
  vidState.format = (document.getElementById('vid-format') || {}).value || '1080x1080';
  var steps = (document.getElementById('vid-steps') || {}).value || '4';
  var seedVal = (document.getElementById('vid-seed') || {}).value || '-1';
  var frames = (document.getElementById('vid-frames') || {}).value || '49';
  var fps = (document.getElementById('vid-fps') || {}).value || '16';

  var btn = document.getElementById('vid-generate-btn');
  if (btn) { btn.disabled = true; btn.textContent = 'PREPARING...'; }
  vidState.generating = true;
  vidHide('vid-result-section');

  try {
    /* Upload images to ComfyUI if needed */
    var startFrameName = null;
    var endFrameName = null;

    if ((vidState.flow === 'wan-i2v' || vidState.flow === 'wan-i2i2v') && vidState.startFrameFile) {
      if (btn) btn.textContent = 'UPLOADING START FRAME...';
      startFrameName = await vidUploadImage(vidState.startFrameFile);
    }
    if (vidState.flow === 'wan-i2i2v' && vidState.endFrameFile) {
      if (btn) btn.textContent = 'UPLOADING END FRAME...';
      endFrameName = await vidUploadImage(vidState.endFrameFile);
    }

    /* Build /vid command string */
    var cmd = '/vid ' + prompt + ' --flow ' + vidState.flow + ' --format ' + vidState.format;
    cmd += ' --frames ' + frames;
    cmd += ' --fps ' + fps;
    if (steps && steps !== '4') cmd += ' --steps ' + steps;
    if (seedVal && seedVal !== '-1') cmd += ' --seed ' + seedVal;
    if (startFrameName) cmd += ' --startframe ' + startFrameName;
    if (endFrameName) cmd += ' --endframe ' + endFrameName;

    /* Step 1: Queue the job */
    if (btn) btn.textContent = 'QUEUING...';
    var resp = await fetch(API_BASE + '/vid/generate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ command: cmd }),
    });
    var data = await resp.json();

    if (data.error) {
      vidShowStatus(data.error, true);
      vidResetBtn();
      return;
    }

    vidState.seed = data.seed;
    var seedEl = document.getElementById('vid-seed');
    if (seedEl && data.seed) seedEl.value = data.seed;

    /* Step 2: Show progress bar and listen to SSE */
    vidShowProgress(0, 'Loading models...');
    vidLoaderShow();
    if (btn) btn.textContent = 'GENERATING...';

    vidListenProgress(data.prompt_id);

  } catch (e) {
    vidLoaderHide();
    vidShowStatus('Request failed: ' + e.message, true);
    vidResetBtn();
  }
}

function vidListenProgress(promptId) {
  var startTime = Date.now();
  var pollTimer = setInterval(function() {
    var elapsed = Math.round((Date.now() - startTime) / 1000);
    var min = Math.floor(elapsed / 60);
    var sec = elapsed % 60;
    var time = min > 0 ? min + 'm ' + sec + 's' : sec + 's';
    var pct = Math.min(95, Math.round(elapsed / 600 * 100) + 5);
    vidShowProgress(pct, 'Generating... (' + time + ')', true);

    fetch(API_BASE + '/vid/status/' + promptId)
      .then(function(r) { return r.json(); })
      .then(function(d) {
        if (d.status === 'done') {
          clearInterval(pollTimer);
          vidLoaderHide();
          vidState.videoUrl = d.video_url;
          vidState.filename = d.filename || null;
          vidState.generating = false;
          vidShowProgress(100, 'Complete!', false);
          setTimeout(function() {
            vidHide('vid-progress-section');
            vidRenderPreview();
            vidShow('vid-result-section');
            vidResetBtn();
          }, 600);
        } else if (d.status === 'error') {
          clearInterval(pollTimer);
          vidLoaderHide();
          vidShowStatus(d.message || 'Generation failed', true);
          vidHide('vid-progress-section');
          vidResetBtn();
        }
      })
      .catch(function() { /* ignore, retry next interval */ });
  }, 2000);

  vidState._pollTimer = pollTimer;
}

function vidShowProgress(pct, text, pulse) {
  vidShow('vid-progress-section');
  var bar = document.getElementById('vid-progress-bar');
  if (bar) {
    bar.style.width = Math.max(pct, 3) + '%';
    if (pulse) {
      bar.classList.add('pulse');
    } else {
      bar.classList.remove('pulse');
    }
  }
  var info = document.getElementById('vid-progress-info');
  if (info) info.textContent = text || '';
}

function vidResetBtn() {
  vidState.generating = false;
  var btn = document.getElementById('vid-generate-btn');
  if (btn) {
    btn.disabled = false;
    btn.innerHTML = '<svg fill="currentColor" width="16" height="16"><use href="icons/sprite.svg#i-mpg"/></svg> GENERATE';
  }
}

/* ═══════════════════════════════════════════════════════════════
   RENDER PREVIEW
   ═══════════════════════════════════════════════════════════════ */

function vidRenderPreview() {
  var url = VID_BASE + vidState.videoUrl;

  var preview = document.getElementById('vid-preview-video');
  if (preview) {
    preview.innerHTML =
      '<video src="' + url + '?t=' + Date.now() + '" controls autoplay loop crossorigin="anonymous" ' +
      'style="width:100%;border-radius:var(--sp-4);display:block;margin-bottom:var(--sp-16)">' +
      '</video>';
  }

  var badge = document.getElementById('vid-preview-badge');
  if (badge) {
    var flowEl = document.getElementById('vid-flow');
    var label = flowEl ? flowEl.options[flowEl.selectedIndex].text : vidState.flow;
    badge.textContent = label + ' — ' + vidState.format + (vidState.seed ? ' — seed: ' + vidState.seed : '');
  }

  vidClearStatus();
}

/* ═══════════════════════════════════════════════════════════════
   DOWNLOAD
   ═══════════════════════════════════════════════════════════════ */

function vidDownload(btn) {
  var url = null;
  if (btn && btn.dataset.url) {
    url = btn.dataset.url;
  } else if (vidState.videoUrl) {
    url = VID_BASE + vidState.videoUrl;
  }
  if (!url) return;
  var a = document.createElement('a');
  a.href = url;
  a.download = vidState.filename || 'video.mp4';
  a.target = '_blank';
  document.body.appendChild(a);
  a.click();
  a.remove();
  vidShowStatus('\u2713 Downloaded: ' + (vidState.filename || ''), false);
}

/* ═══════════════════════════════════════════════════════════════
   CREATE NEW
   ═══════════════════════════════════════════════════════════════ */

function vidNew() {
  var wrap = document.querySelector('.tool-wrap');
  if (!wrap) return;

  /* Store URL on old download button */
  var oldDownloads = document.querySelectorAll('[data-action="vid-download"]');
  oldDownloads.forEach(function(btn) {
    if (vidState.videoUrl) btn.dataset.url = VID_BASE + vidState.videoUrl;
  });

  /* Strip vid-* IDs from current DOM */
  document.querySelectorAll('[id^="vid-"]').forEach(function(el) {
    el.removeAttribute('id');
  });

  /* Disable old action buttons except DOWNLOAD */
  document.querySelectorAll('[data-action="vid-new"], [data-action="vid-generate"]').forEach(function(btn) {
    btn.disabled = true;
    btn.style.opacity = '0.3';
    btn.style.pointerEvents = 'none';
  });

  /* Dim old video */
  document.querySelectorAll('video').forEach(function(v) {
    v.style.opacity = '0.6';
    v.removeAttribute('autoplay');
  });

  /* Reset state */
  vidState = { videoUrl: null, filename: null, prompt: '', flow: 'wan-t2v', format: '512x512', seed: null, generating: false, startFrameFile: null, endFrameFile: null };

  /* Build fresh section */
  var section = document.createElement('div');
  section.className = 'vid-run';
  section.innerHTML =
    '<div class="tool-separator"></div>' +
    '<div id="vid-prompt-section">' +
      '<div class="fl-grid fl-grid-2">' +
        '<div class="fl-field"><select class="fl-select" id="vid-flow">' +
          '<option value="wan-t2v" selected>WAN 2.2 Text-to-Video</option>' +
          '<option value="wan-i2v">WAN 2.2 Image-to-Video</option>' +
          '<option value="wan-i2i2v">WAN 2.2 Start+End Frame</option></select>' +
          '<label class="fl-label">WORKFLOW</label></div>' +
        '<div class="fl-field"><select class="fl-select" id="vid-format">' +
          '<option value="1080x1080" selected>1:1 1080\u00d71080</option>' +
          '<option value="1280x720">16:9 1280\u00d7720</option>' +
          '<option value="720x1280">9:16 720\u00d71280</option>' +
          '<option value="512x512">1:1 512\u00d7512</option></select>' +
          '<label class="fl-label">FORMAT</label></div>' +
      '</div>' +
      '<div id="vid-upload-section" style="display:none">' +
        '<div class="tool-upload" id="vid-startframe-drop">' +
          '<svg fill="currentColor"><use href="icons/sprite.svg#i-plus"/></svg>' +
          '<span class="tool-upload-lbl">CLICK OR DRAG & DROP START FRAME</span></div></div>' +
      '<div id="vid-upload-end-section" style="display:none">' +
        '<div class="tool-upload" id="vid-endframe-drop">' +
          '<svg fill="currentColor"><use href="icons/sprite.svg#i-plus"/></svg>' +
          '<span class="tool-upload-lbl">CLICK OR DRAG & DROP END FRAME</span></div></div>' +
      '<div class="fl-field"><textarea class="fl-input" id="vid-prompt" rows="1" placeholder=" "></textarea><label class="fl-label">PROMPT</label></div>' +
      '<div class="fl-grid fl-grid-2">' +
        '<div class="fl-field"><input class="fl-input" id="vid-frames" type="text" value="125" placeholder=" "><label class="fl-label">FRAMES</label></div>' +
        '<div class="fl-field"><input class="fl-input" id="vid-fps" type="text" value="25" placeholder=" "><label class="fl-label">FPS</label></div>' +
      '</div>' +
      '<div class="fl-grid fl-grid-2">' +
        '<div class="fl-field"><input class="fl-input" id="vid-seed" type="text" value="-1" placeholder=" "><label class="fl-label">SEED</label></div>' +
        '<div class="fl-field"><input class="fl-input" id="vid-steps" type="text" value="4" placeholder=" "><label class="fl-label">STEPS</label></div>' +
      '</div>' +
      '<div class="tool-actions"><button class="btn-ico" data-action="vid-generate" id="vid-generate-btn">' +
        '<svg fill="currentColor" width="16" height="16"><use href="icons/sprite.svg#i-mpg"/></svg> GENERATE</button></div>' +
    '</div>' +
    '<div id="vid-progress-section" style="display:none">' +
      '<div class="vid-progress-wrap"><div class="vid-progress-bar" id="vid-progress-bar"></div></div>' +
      '<div class="vid-progress-info" id="vid-progress-info"></div></div>' +
    '<div id="vid-result-section" style="display:none">' +
      '<div class="tool-result-head" id="vid-preview-badge"></div><div id="vid-preview-video"></div>' +
      '<div class="tool-result-btns" id="vid-btns">' +
        '<button class="tool-action-btn" data-action="vid-download">DOWNLOAD</button>' +
        '<button class="tool-action-btn" data-action="vid-new">CREATE NEW</button>' +
        '<button class="tool-action-btn bucket-add-btn" data-action="vid-bucket">BUCKET</button>' +
        '<button class="tool-action-btn" data-action="vid-last-frame">LAST FRAME → BUCKET</button></div>' +
      '<div class="tool-result-status" id="vid-status"></div></div>';

  wrap.appendChild(section);
  vidAutoResize('vid-prompt');
  vidUpdateUpload();
  vidBindDropZone('vid-startframe-drop', 'start');
  vidBindDropZone('vid-endframe-drop', 'end');
  section.scrollIntoView({ behavior: 'smooth' });
}

/* ═══════════════════════════════════════════════════════════════
   M2 LOADER
   ═══════════════════════════════════════════════════════════════ */

function vidLoaderShow() {
  var existing = document.getElementById('vid-m2-loader-wrap');
  if (existing) return;
  var progress = document.getElementById('vid-progress-section');
  if (!progress) return;
  var overlay = document.createElement('div');
  overlay.id = 'vid-m2-loader-wrap';
  overlay.style.cssText = 'display:flex;width:100%;justify-content:center;padding:40px 0';
  overlay.innerHTML = '<div class="m2-loader-m" id="vid-m2-loader"></div>';
  progress.after(overlay);
  startM2(document.getElementById('vid-m2-loader'), 9, 35);
}

function vidLoaderHide() {
  stopM2();
  var el = document.getElementById('vid-m2-loader-wrap');
  if (el) { el.querySelector('.m2-loader-m').innerHTML = ''; el.remove(); }
}

/* ═══════════════════════════════════════════════════════════════
   HELPERS
   ═══════════════════════════════════════════════════════════════ */

function vidAutoResize(id) {
  var el = document.getElementById(id);
  if (!el) return;
  function resize() { el.style.height = 'auto'; el.style.height = el.scrollHeight + 'px'; }
  el.addEventListener('input', resize);
  resize();
}

function vidShow(id) {
  var el = document.getElementById(id);
  if (el) el.style.display = '';
}

function vidHide(id) {
  var el = document.getElementById(id);
  if (el) el.style.display = 'none';
}

function vidShowStatus(msg, isError) {
  var el = document.getElementById('vid-status');
  if (el) el.innerHTML = '<span style="color:var(--c-' + (isError ? 'red' : 'green') + ')">' + vidEsc(msg) + '</span>';
}

function vidClearStatus() {
  var el = document.getElementById('vid-status');
  if (el) el.innerHTML = '';
}

function vidEsc(str) {
  var div = document.createElement('div');
  div.textContent = str;
  return div.innerHTML;
}

/* ═══════════════════════════════════════════════════════════════
   ADD TO BUCKET
   ═══════════════════════════════════════════════════════════════ */

function vidAddToBucket(btn) {
  var url = btn && btn.dataset.url;
  if (!url && vidState.videoUrl) url = VID_BASE + vidState.videoUrl;
  if (!url) return;
  bucketAdd({
    type: 'video',
    url: url,
    thumb: '',
    source: 'videogen',
    label: (vidState.prompt || 'video').substring(0, 60)
  });
  btn.classList.add('bucket-add-ok');
  btn.textContent = 'ADDED';
  setTimeout(function() { btn.classList.remove('bucket-add-ok'); btn.textContent = 'BUCKET'; }, 800);
}

/* ═══════════════════════════════════════════════════════════════
   LAST FRAME → BUCKET
   ═══════════════════════════════════════════════════════════════ */

function vidLastFrameToBucket(btn) {
  var video = document.querySelector('#vid-preview-video video');
  if (!video) { vidShowStatus('No video found', true); return; }

  function captureFrame() {
    try {
      var canvas = document.createElement('canvas');
      canvas.width = video.videoWidth || 512;
      canvas.height = video.videoHeight || 512;
      var ctx = canvas.getContext('2d');
      ctx.drawImage(video, 0, 0, canvas.width, canvas.height);

      canvas.toBlob(async function(blob) {
        if (!blob) { vidShowStatus('Frame capture failed', true); return; }
        /* Upload to server so the URL is persistent (not a blob:) */
        var formData = new FormData();
        var fname = 'lastframe_' + Date.now() + '.png';
        formData.append('image', blob, fname);
        try {
          var uploadResp = await fetch(API_BASE + '/upload/comfyui', { method: 'POST', body: formData });
          var uploadData = await uploadResp.json();
          var serverUrl = 'http://mora02.local:8092/comfyui/wip/' + (uploadData.name || fname);
          bucketAdd({
            type: 'image',
            url: serverUrl,
            thumb: serverUrl,
            source: 'videogen-lastframe',
            label: 'Last frame: ' + (vidState.prompt || 'video').substring(0, 40)
          });
          if (btn) {
            btn.classList.add('bucket-add-ok');
            btn.textContent = 'ADDED';
            setTimeout(function() { btn.classList.remove('bucket-add-ok'); btn.textContent = 'LAST FRAME \u2192 BUCKET'; }, 800);
          }
          vidShowStatus('\u2713 Last frame uploaded & added to bucket', false);
        } catch (e) {
          vidShowStatus('Upload failed: ' + e.message, true);
        }
      }, 'image/png');
    } catch (e) {
      vidShowStatus('Frame capture error: ' + e.message, true);
    }
  }

  /* Pause video, seek to end, then capture */
  video.pause();
  if (video.duration && isFinite(video.duration)) {
    video.currentTime = video.duration - 0.05;
    video.onseeked = function() { video.onseeked = null; captureFrame(); };
  } else {
    /* Duration unknown — capture current frame */
    captureFrame();
  }
}

/* ═══════════════════════════════════════════════════════════════
   EVENT DELEGATION
   ═══════════════════════════════════════════════════════════════ */

document.addEventListener('click', function(e) {
  var target = e.target.closest('[data-action]');
  if (!target) return;

  switch (target.dataset.action) {
    case 'vid-generate':    vidGenerate(); break;
    case 'vid-download':    vidDownload(target); break;
    case 'vid-new':         vidNew(); break;
    case 'vid-bucket':      vidAddToBucket(target); break;
    case 'vid-last-frame':  vidLastFrameToBucket(target); break;
  }
});

document.addEventListener('change', function(e) {
  if (e.target.id === 'vid-flow') vidUpdateUpload();
});
