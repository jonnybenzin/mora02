/* ═══════════════════════════════════════════════════════════════
   MORA02 PILOT — Post Editor
   CRUD for social media posts via Baserow table 557.
   Init: initPost() called from tools.js initToolPage().
   Depends on: app.js (API_BASE)
   ═══════════════════════════════════════════════════════════════ */

var MEDIA_BASE = 'http://mora02.local:8092/socialmedia/';

var postState = {
  posts: [],
  editId: null,
  filter: 'all',
};

function postHeaders() {
  return { 'Content-Type': 'application/json' };
}

function postApiUrl(rowId) {
  return rowId ? API_BASE + '/posts/' + rowId : API_BASE + '/posts';
}

/* ─── INIT ──────────────────────────────────────────────────── */

async function initPost() {
  postState = { posts: [], editId: null, openId: null, filter: 'all' };
  postClearForm();

  var uploadInput = document.getElementById('post-upload-input');
  if (uploadInput) {
    uploadInput.addEventListener('change', postHandleUpload);
  }

  var caption = document.getElementById('post-caption');
  if (caption) {
    caption.addEventListener('input', function() { postAutoResize(caption); });
  }

  /* Bucket drop zone on upload row */
  if (typeof bucketBindDropZone === 'function') {
    bucketBindDropZone('post-upload-row', ['image', 'video', 'animation'], function(item) {
      var mediaField = document.getElementById('post-media');
      var nameEl = document.getElementById('post-upload-name');
      if (mediaField) mediaField.value = item.url;
      if (nameEl) nameEl.textContent = (item.label || 'Bucket item') + ' (from bucket)';
      /* Show inline preview */
      var row = document.getElementById('post-upload-row');
      var existing = document.getElementById('post-bucket-preview');
      if (existing) existing.remove();
      if (row && item.url) {
        var isVid = item.type === 'video' || item.type === 'animation';
        var preview = document.createElement('div');
        preview.id = 'post-bucket-preview';
        preview.style.cssText = 'margin-top:8px';
        preview.innerHTML = isVid
          ? '<video src="' + item.url + '" controls muted style="max-width:100%;max-height:200px;border-radius:4px"></video>'
          : '<img src="' + item.url + '" style="max-width:100%;max-height:200px;border-radius:4px">';
        row.after(preview);
      }
      if (typeof postMsg === 'function') postMsg('Media set from bucket', 'success');
    });
  }

  await postLoadList();
}

/* ─── LOAD LIST ─────────────────────────────────────────────── */

async function postLoadList() {
  var list = document.getElementById('post-list');
  if (list) list.innerHTML = '<div style="color:var(--tx-muted);padding:var(--sp-10)">Loading...</div>';

  try {
    var allPosts = [];
    var page = 1;
    while (true) {
      var url = postApiUrl() + '&size=50&page=' + page + '&order_by=-created_at';
      console.log('[POST] Loading:', url);
      var resp = await fetch(url, { headers: postHeaders() });
      var data = await resp.json();
      console.log('[POST] Got', (data.results || []).length, 'posts, next:', !!data.next);
      allPosts = allPosts.concat(data.results || []);
      if (!data.next) break;
      page++;
    }
    postState.posts = allPosts;
    postRenderList();
  } catch (e) {
    console.error('[POST] Load error:', e);
    if (list) list.innerHTML = '<div style="color:var(--tx-muted);padding:var(--sp-10)">Could not load posts: ' + e.message + '</div>';
  }
}

/* ─── RENDER LIST ───────────────────────────────────────────── */

function postRenderList() {
  var list = document.getElementById('post-list');
  if (!list) return;

  var filtered = postState.posts;
  if (postState.filter !== 'all') {
    filtered = filtered.filter(function(p) {
      var s = p.status ? p.status.value : '';
      return s === postState.filter;
    });
  }

  if (filtered.length === 0) {
    list.innerHTML = '<div style="color:var(--tx-muted);padding:var(--sp-10)">No posts</div>';
    return;
  }

  var html = '';
  for (var i = 0; i < filtered.length; i++) {
    var p = filtered[i];
    var status = p.status ? p.status.value : '—';
    var name = (p.Name || '').trim() || '(unnamed)';
    var captionShort = (p.caption_master || '').substring(0, 60);
    if ((p.caption_master || '').length > 60) captionShort += '…';
    var captionFull = p.caption_master || '';
    var mediaFile = (p.media_path || '').trim();
    var isOpen = postState.openId === p.id;
    var isEditing = postState.editId === p.id;
    var isPublished = status === 'published';
    var mediaUrl = mediaFile ? (mediaFile.indexOf('http') === 0 ? mediaFile : MEDIA_BASE + mediaFile) : '';
    var isVideo = mediaFile && (/\.(mp4|webm|mov)$/i.test(mediaFile) || mediaFile.indexOf('/wan/') !== -1);

    html += '<div class="post-item' + (isEditing ? ' post-item-active' : '') + '">'
          + '<div class="post-item-header" data-action="post-expand" data-id="' + p.id + '">'
          + '<div class="post-item-row">';
    if (mediaFile && !isVideo) {
      html += '<img class="post-item-thumb" src="' + mediaUrl + '" alt="">';
    } else if (isVideo) {
      html += '<video class="post-item-thumb" src="' + mediaUrl + '" muted preload="metadata"></video>';
    }
    html += '<div class="post-item-content">'
          + '<div class="post-item-top">'
          + '<span class="post-item-name">' + postEsc(name) + '</span>'
          + '<span class="post-item-badge post-badge-' + status + '">' + status + '</span>'
          + '</div>';
    if (!isOpen && captionShort) html += '<div class="post-item-caption">' + postEsc(captionShort) + '</div>';
    html += '</div></div></div>';

    if (isOpen) {
      html += '<div class="post-item-detail">';
      if (mediaUrl) {
        if (isVideo) {
          html += '<video class="post-item-media" src="' + mediaUrl + '" controls></video>';
        } else {
          html += '<img class="post-item-media" src="' + mediaUrl + '" alt="">';
        }
      }
      if (captionFull) html += '<div class="post-item-fullcaption">' + postEsc(captionFull) + '</div>';
      if (!isPublished) {
        html += '<button class="post-item-edit-btn" data-action="post-select" data-id="' + p.id + '">EDIT</button>';
      }
      html += '</div>';
    }

    html += '</div>';
  }
  list.innerHTML = html;
}

/* ─── SELECT POST ───────────────────────────────────────────── */

function postSelect(id) {
  var post = postState.posts.find(function(p) { return p.id === id; });
  if (!post) return;
  postState.editId = id;

  var name = document.getElementById('post-name');
  var caption = document.getElementById('post-caption');
  var status = document.getElementById('post-status');
  var scheduled = document.getElementById('post-scheduled');
  var media = document.getElementById('post-media');

  if (name) name.value = post.Name || '';
  if (caption) { caption.value = post.caption_master || ''; postAutoResize(caption); }
  if (status) status.value = post.status ? post.status.value : 'draft';
  if (scheduled) scheduled.value = post.scheduled_for ? post.scheduled_for.substring(0, 16) : '';
  if (media) media.value = post.media_path || '';
  var uploadName = document.getElementById('post-upload-name');
  if (uploadName) uploadName.textContent = '';

  postRenderList();
  var editor = document.getElementById('post-editor');
  if (editor) editor.scrollIntoView({ behavior: 'smooth' });
}

/* ─── SAVE POST ─────────────────────────────────────────────── */

async function postSave() {
  var name = (document.getElementById('post-name') || {}).value || '';
  var caption = (document.getElementById('post-caption') || {}).value || '';
  var status = (document.getElementById('post-status') || {}).value || 'draft';
  var scheduled = (document.getElementById('post-scheduled') || {}).value || null;
  var media = (document.getElementById('post-media') || {}).value || '';

  var body = {
    'Name': name,
    'caption_master': caption,
    'status': status,
    'scheduled_for': scheduled,
    'media_path': media,
  };

  try {
    var resp;
    if (postState.editId) {
      resp = await fetch(postApiUrl(postState.editId), {
        method: 'PATCH',
        headers: postHeaders(),
        body: JSON.stringify(body),
      });
    } else {
      resp = await fetch(postApiUrl(), {
        method: 'POST',
        headers: postHeaders(),
        body: JSON.stringify(body),
      });
    }

    if (resp.ok) {
      var saved = await resp.json();
      postMsg(postState.editId ? 'Updated #' + saved.id : 'Created #' + saved.id, 'success');
      postState.editId = saved.id;
      await postLoadList();
    } else {
      var err = await resp.text();
      postMsg('Save failed: ' + err, 'error');
    }
  } catch (e) {
    postMsg('Network error: ' + e.message, 'error');
  }
}

/* ─── NEW POST ──────────────────────────────────────────────── */

function postNew() {
  postState.editId = null;
  postClearForm();
  postRenderList();
  var name = document.getElementById('post-name');
  if (name) name.focus();
}

/* ─── FORM HELPERS ──────────────────────────────────────────── */

function postClearForm() {
  var fields = ['post-name', 'post-caption', 'post-media', 'post-scheduled'];
  fields.forEach(function(id) {
    var el = document.getElementById(id);
    if (el) el.value = '';
  });
  var status = document.getElementById('post-status');
  if (status) status.value = 'draft';
  postMsgHide();
}

function postMsg(text, kind) {
  var el = document.getElementById('post-status-msg');
  if (!el) return;
  el.textContent = text;
  el.className = 'post-status-msg' + (kind ? ' post-msg-' + kind : '');
  el.style.display = '';
  if (kind === 'success') setTimeout(postMsgHide, 3000);
}

function postMsgHide() {
  var el = document.getElementById('post-status-msg');
  if (el) el.style.display = 'none';
}

function postAutoResize(el) {
  el.style.height = 'auto';
  el.style.height = el.scrollHeight + 'px';
}

function postEsc(str) {
  var d = document.createElement('div');
  d.textContent = str;
  return d.innerHTML;
}

/* ─── FILTER ────────────────────────────────────────────────── */

function postSetFilter(filter) {
  postState.filter = filter;
  document.querySelectorAll('.post-filter').forEach(function(btn) {
    btn.classList.toggle('post-filter-active', btn.dataset.filter === filter);
  });
  postRenderList();
}

/* ─── EXPAND ITEM ───────────────────────────────────────────── */

function postExpand(id) {
  postState.openId = postState.openId === id ? null : id;
  postRenderList();
}

/* ─── TOGGLE LIST ───────────────────────────────────────────── */

function postToggleList() {
  var body = document.getElementById('post-list-body');
  var chev = document.getElementById('post-list-chev');
  if (!body) return;
  var open = body.style.display !== 'none';
  body.style.display = open ? 'none' : '';
  if (chev) chev.style.transform = open ? '' : 'rotate(180deg)';
}

/* ─── UPLOAD MEDIA ──────────────────────────────────────────── */

async function postHandleUpload() {
  var input = document.getElementById('post-upload-input');
  if (!input || !input.files || !input.files.length) return;

  var file = input.files[0];
  var nameEl = document.getElementById('post-upload-name');
  if (nameEl) nameEl.textContent = 'Uploading ' + file.name + '...';

  var formData = new FormData();
  formData.append('file', file);

  try {
    var resp = await fetch(API_BASE + '/upload/post-media', {
      method: 'POST',
      body: formData,
    });
    var data = await resp.json();
    if (data.success) {
      var mediaField = document.getElementById('post-media');
      if (mediaField) mediaField.value = data.filename;
      if (nameEl) nameEl.textContent = data.filename;
      postMsg('Media uploaded', 'success');
    } else {
      if (nameEl) nameEl.textContent = '';
      postMsg('Upload failed: ' + (data.error || 'unknown'), 'error');
    }
  } catch (e) {
    if (nameEl) nameEl.textContent = '';
    postMsg('Upload error: ' + e.message, 'error');
  }

  input.value = '';
}
