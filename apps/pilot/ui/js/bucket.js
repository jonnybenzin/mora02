/* ═══════════════════════════════════════════════════════════════
   MORA02 PILOT — Bucket Module v1 (2026-04-15)
   ═══════════════════════════════════════════════════════════════
   Session-local asset clipboard for creative pipelines.
   Items are references (URLs) — no file copying.
   ───────────────────────────────────────────────────────────────
   Depends on: app.js (API_BASE, sessionId)
   ═══════════════════════════════════════════════════════════════ */

/* ─── STATE ────────────────────────────────────────────────── */

var bucketItems = [];
var bucketCounter = 0;
var bucketOverlayOpen = false;
var bucketDragItem = null; /* set during dragstart, read during dragover */
var bucketDragging = false; /* true while dragging an item out of bucket */

/* ═══════════════════════════════════════════════════════════════
   CORE API
   ═══════════════════════════════════════════════════════════════ */

function bucketAdd(item) {
  bucketCounter++;
  var entry = {
    id: 'b_' + bucketCounter,
    type: item.type || 'image',
    url: item.url || '',
    thumb: item.thumb || item.url || '',
    source: item.source || 'unknown',
    label: item.label || '',
    added_at: new Date().toISOString()
  };
  bucketItems.push(entry);
  bucketUpdateBadge();
  bucketRenderOverlayContent();
  return entry;
}

function bucketRemove(id) {
  bucketItems = bucketItems.filter(function(it) { return it.id !== id; });
  bucketUpdateBadge();
  bucketRenderOverlayContent();
}

function bucketClear() {
  bucketItems = [];
  bucketUpdateBadge();
  bucketRenderOverlayContent();
}

function bucketGetAll() {
  return bucketItems.slice();
}

function bucketGetByType(type) {
  return bucketItems.filter(function(it) { return it.type === type; });
}

function bucketGetByTypes(types) {
  return bucketItems.filter(function(it) { return types.indexOf(it.type) !== -1; });
}

function bucketToJSON() {
  return bucketItems.map(function(it) {
    return { type: it.type, url: it.url, source: it.source, label: it.label, added_at: it.added_at };
  });
}

/* ═══════════════════════════════════════════════════════════════
   BADGE
   ═══════════════════════════════════════════════════════════════ */

function bucketUpdateBadge() {
  var count = bucketItems.length;

  /* Update all badge elements */
  var badges = document.querySelectorAll('#bucket-badge, #bucket-badge-mob, #bucket-badge-float');
  badges.forEach(function(el) {
    if (!el) return;
    if (count > 0) {
      el.textContent = count;
      el.style.display = 'flex';
    } else {
      el.style.display = 'none';
    }
  });

  /* Sidebar bucket icon — always visible */
  var icons = document.querySelectorAll('.bucket-si');
  icons.forEach(function(el) {
    el.style.display = '';
  });

  /* Floating bucket button — always visible */
  var floatBtn = document.getElementById('bucket-float');
  if (floatBtn) {
    floatBtn.style.display = 'flex';
  }
}

/* ═══════════════════════════════════════════════════════════════
   OVERLAY — open / close / render
   ═══════════════════════════════════════════════════════════════ */

function bucketToggle() {
  bucketOverlayOpen ? bucketClose() : bucketOpen();
}

function bucketOpen() {
  var ov = document.getElementById('bucket-overlay');
  if (!ov) return;
  bucketRenderOverlayContent();
  ov.style.display = 'block';
  bucketOverlayOpen = true;
}

function bucketClose() {
  var ov = document.getElementById('bucket-overlay');
  if (!ov) return;
  ov.style.display = 'none';
  bucketOverlayOpen = false;
}

function bucketRenderOverlayContent() {
  var grid = document.getElementById('bucket-grid');
  if (!grid) return;

  if (bucketItems.length === 0) {
    grid.innerHTML = '<div class="bucket-empty">Bucket is empty</div>';
    return;
  }

  var html = '';
  for (var i = 0; i < bucketItems.length; i++) {
    var it = bucketItems[i];
    var isVideo = it.type === 'video' || it.type === 'animation';
    var isText = it.type === 'text';
    var thumbHtml = isVideo
      ? '<video class="bucket-thumb" src="' + it.url + '" muted preload="metadata"></video>'
      : isText
      ? '<div class="bucket-thumb" style="display:flex;align-items:center;justify-content:center;background:var(--c-grey2);color:var(--tx-muted);font-family:var(--ff-mono);font-size:10px;font-weight:bold">TXT</div>'
      : '<img class="bucket-thumb" src="' + it.thumb + '" alt="">';

    html += '<div class="bucket-item" draggable="true" data-bucket-id="' + it.id + '">'
      + thumbHtml
      + '<div class="bucket-item-info">'
      + '<span class="bucket-item-label">' + (it.label || it.source) + '</span>'
      + '<span class="bucket-item-type">' + it.type + '</span>'
      + '</div>'
      + '<button class="bucket-item-rm" data-bucket-rm="' + it.id + '">'
      + '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M4 4l8 8M12 4l-8 8"/></svg>'
      + '</button>'
      + '</div>';
  }
  grid.innerHTML = html;

  /* Bind drag start on each item */
  var items = grid.querySelectorAll('.bucket-item[draggable]');
  items.forEach(function(el) {
    el.addEventListener('dragstart', bucketOnDragStart);
  });

  /* Bind remove buttons */
  var rmBtns = grid.querySelectorAll('[data-bucket-rm]');
  rmBtns.forEach(function(btn) {
    btn.addEventListener('click', function(e) {
      e.stopPropagation();
      bucketRemove(btn.getAttribute('data-bucket-rm'));
    });
  });
}

/* ═══════════════════════════════════════════════════════════════
   DRAG & DROP — source side (from bucket)
   ═══════════════════════════════════════════════════════════════ */

function bucketOnDragStart(e) {
  var id = e.currentTarget.getAttribute('data-bucket-id');
  var item = bucketItems.find(function(it) { return it.id === id; });
  if (!item) return;
  bucketDragItem = item;
  bucketDragging = true;
  e.dataTransfer.setData('application/x-bucket-item', JSON.stringify(item));
  e.dataTransfer.effectAllowed = 'copy';
  e.currentTarget.classList.add('bucket-dragging');
  e.currentTarget.addEventListener('dragend', function() {
    e.currentTarget.classList.remove('bucket-dragging');
    bucketDragItem = null;
    bucketDragging = false;
  }, { once: true });
}

/* ═══════════════════════════════════════════════════════════════
   DRAG & DROP — target side (for tool widgets)
   ═══════════════════════════════════════════════════════════════
   Usage: bucketBindDropZone(elementOrId, acceptTypes, onDropCallback)
   - acceptTypes: array e.g. ['image'] or ['video','animation']
   - onDropCallback(bucketItem): called with the dropped item
*/

function bucketBindDropZone(elOrId, acceptTypes, onDrop) {
  var el = typeof elOrId === 'string' ? document.getElementById(elOrId) : elOrId;
  if (!el) return;

  el.addEventListener('dragover', function(e) {
    if (!e.dataTransfer.types || e.dataTransfer.types.indexOf('application/x-bucket-item') === -1) return;
    e.preventDefault();

    /* Check type match via module-level drag item */
    var accepted = bucketDragItem && acceptTypes.indexOf(bucketDragItem.type) !== -1;
    if (accepted) {
      e.dataTransfer.dropEffect = 'copy';
      el.classList.add('bucket-drop-active');
      el.classList.remove('bucket-drop-reject');
    } else {
      e.dataTransfer.dropEffect = 'none';
      el.classList.remove('bucket-drop-active');
      el.classList.add('bucket-drop-reject');
    }
  });

  el.addEventListener('dragleave', function() {
    el.classList.remove('bucket-drop-active');
    el.classList.remove('bucket-drop-reject');
  });

  el.addEventListener('drop', function(e) {
    el.classList.remove('bucket-drop-active');
    el.classList.remove('bucket-drop-reject');
    var raw = e.dataTransfer.getData('application/x-bucket-item');
    if (!raw) return;
    e.preventDefault();
    try {
      var item = JSON.parse(raw);
      if (acceptTypes.indexOf(item.type) !== -1) {
        onDrop(item);
      }
    } catch (err) {
      console.warn('[bucket] drop parse error', err);
    }
  });

  /* Store accepted types as data attribute for reject tooltip */
  el.setAttribute('data-bucket-accepts', acceptTypes.join(', '));
}

/* ═══════════════════════════════════════════════════════════════
   HELPER — "add to bucket" button HTML
   ═══════════════════════════════════════════════════════════════
   Returns an HTML string for a button. Caller must wire up the
   click handler or use event delegation with data-bucket-add.
*/

function bucketBtnHtml(type, url, source, label) {
  return '<button class="bucket-add-btn" '
    + 'data-bucket-add '
    + 'data-bucket-type="' + type + '" '
    + 'data-bucket-url="' + url + '" '
    + 'data-bucket-source="' + source + '" '
    + 'data-bucket-label="' + (label || '') + '" '
    + 'title="Add to Bucket">'
    + '<svg viewBox="0 0 16 16" fill="currentColor" width="14" height="14">'
    + '<path d="M8 1a5 5 0 0 0-5 5v3.5c0 .5-.2 1-.6 1.4L1 12.3V13h14v-.7l-1.4-1.4c-.4-.4-.6-.9-.6-1.4V6a5 5 0 0 0-5-5z"/>'
    + '<circle cx="8" cy="15" r="1.5"/>'
    + '</svg>'
    + ' BUCKET'
    + '</button>';
}

/* ═══════════════════════════════════════════════════════════════
   EVENT DELEGATION — global click handler for bucket-add buttons
   ═══════════════════════════════════════════════════════════════ */

function bucketInitDelegation() {
  document.addEventListener('click', function(e) {
    var btn = e.target.closest('[data-bucket-add]');
    if (!btn) return;
    e.preventDefault();
    e.stopPropagation();
    var added = bucketAdd({
      type: btn.getAttribute('data-bucket-type') || 'image',
      url: btn.getAttribute('data-bucket-url') || '',
      source: btn.getAttribute('data-bucket-source') || 'unknown',
      label: btn.getAttribute('data-bucket-label') || ''
    });
    /* Brief visual feedback */
    btn.classList.add('bucket-add-ok');
    btn.textContent = 'ADDED';
    setTimeout(function() { btn.classList.remove('bucket-add-ok'); }, 800);
  });

  /* Close on click outside flyout (but not while dragging) */
  document.addEventListener('click', function(e) {
    if (!bucketOverlayOpen || bucketDragging) return;
    var panel = document.getElementById('bucket-overlay');
    var floatBtn = document.getElementById('bucket-float');
    if (panel && !panel.contains(e.target) && floatBtn && !floatBtn.contains(e.target)) {
      bucketClose();
    }
  });

  /* Overlay close button */
  var closeBtn = document.getElementById('bucket-close');
  if (closeBtn) {
    closeBtn.addEventListener('click', bucketClose);
  }

  /* Clear button */
  var clearBtn = document.getElementById('bucket-clear');
  if (clearBtn) {
    clearBtn.addEventListener('click', bucketClear);
  }

  /* Sidebar icon click */
  var icons = document.querySelectorAll('.bucket-si');
  icons.forEach(function(el) {
    el.addEventListener('click', function(e) {
      e.stopPropagation();
      bucketToggle();
    });
  });

  /* Floating button click */
  var floatBtn = document.getElementById('bucket-float');
  if (floatBtn) {
    floatBtn.addEventListener('click', function(e) {
      e.stopPropagation();
      bucketToggle();
    });
  }

  /* Init badge state */
  bucketUpdateBadge();

  /* Save button — toggle save form */
  var saveBtn = document.getElementById('bucket-save-btn');
  if (saveBtn) {
    saveBtn.addEventListener('click', function(e) {
      e.stopPropagation();
      var form = document.getElementById('bucket-save-form');
      var list = document.getElementById('bucket-saved-list');
      if (list) list.style.display = 'none';
      if (form) {
        var isOpen = form.style.display !== 'none';
        form.style.display = isOpen ? 'none' : 'flex';
        if (!isOpen) {
          var inp = document.getElementById('bucket-save-name');
          if (inp) { inp.value = ''; inp.focus(); }
        }
      }
    });
  }

  /* Save confirm */
  var saveConfirm = document.getElementById('bucket-save-confirm');
  if (saveConfirm) {
    saveConfirm.addEventListener('click', function(e) {
      e.stopPropagation();
      bucketSaveToDB();
    });
  }

  /* Save on Enter in name input */
  var saveInput = document.getElementById('bucket-save-name');
  if (saveInput) {
    saveInput.addEventListener('keydown', function(e) {
      if (e.key === 'Enter') { e.preventDefault(); bucketSaveToDB(); }
    });
  }

  /* Load button — toggle saved list */
  var loadBtn = document.getElementById('bucket-load-btn');
  if (loadBtn) {
    loadBtn.addEventListener('click', function(e) {
      e.stopPropagation();
      var list = document.getElementById('bucket-saved-list');
      var form = document.getElementById('bucket-save-form');
      if (form) form.style.display = 'none';
      if (list) {
        var isOpen = list.style.display !== 'none';
        if (isOpen) {
          list.style.display = 'none';
        } else {
          bucketLoadList();
        }
      }
    });
  }
}


/* ═══════════════════════════════════════════════════════════════
   BUCKET PERSISTENCE — Save / Load / Delete
   ═══════════════════════════════════════════════════════════════ */

async function bucketSaveToDB() {
  var nameInput = document.getElementById('bucket-save-name');
  var name = nameInput ? nameInput.value.trim() : '';
  if (!name) { nameInput.focus(); return; }
  if (bucketItems.length === 0) return;

  var btn = document.getElementById('bucket-save-confirm');
  if (btn) { btn.textContent = 'SAVING...'; btn.disabled = true; }

  try {
    var resp = await fetch(API_BASE + '/bucket/save', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: name, items: bucketToJSON() }),
    });
    var data = await resp.json();
    if (data.success) {
      if (btn) btn.textContent = 'SAVED!';
      setTimeout(function() {
        var form = document.getElementById('bucket-save-form');
        if (form) form.style.display = 'none';
        if (btn) { btn.textContent = 'SAVE BUCKET'; btn.disabled = false; }
      }, 800);
    } else {
      if (btn) { btn.textContent = 'ERROR'; btn.disabled = false; }
    }
  } catch (e) {
    console.error('Bucket save failed:', e);
    if (btn) { btn.textContent = 'ERROR'; btn.disabled = false; }
  }
}

async function bucketLoadList() {
  var list = document.getElementById('bucket-saved-list');
  if (!list) return;
  list.style.display = 'block';
  list.innerHTML = '<div class="bucket-saved-empty">Loading...</div>';

  try {
    var resp = await fetch(API_BASE + '/bucket/list');
    var data = await resp.json();
    var buckets = data.buckets || [];

    if (buckets.length === 0) {
      list.innerHTML = '<div class="bucket-saved-empty">No saved buckets</div>';
      return;
    }

    var html = '';
    for (var i = 0; i < buckets.length; i++) {
      var b = buckets[i];
      var date = b.created_at ? b.created_at.substring(0, 16).replace('T', ' ') : '';
      html += '<div class="bucket-saved-item" data-bucket-load-id="' + b.id + '">'
        + '<div class="bucket-saved-info">'
        + '<span class="bucket-saved-name">' + (b.name || 'Untitled') + '</span>'
        + '<span class="bucket-saved-meta">' + b.item_count + ' items · ' + date + '</span>'
        + '</div>'
        + '<button class="bucket-saved-del" data-bucket-del-id="' + b.id + '">'
        + '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M4 4l8 8M12 4l-8 8"/></svg>'
        + '</button>'
        + '</div>';
    }
    list.innerHTML = html;

    /* Bind load clicks */
    list.querySelectorAll('[data-bucket-load-id]').forEach(function(el) {
      el.addEventListener('click', function(e) {
        if (e.target.closest('[data-bucket-del-id]')) return;
        bucketLoadFromDB(parseInt(el.getAttribute('data-bucket-load-id')));
      });
    });

    /* Bind delete clicks */
    list.querySelectorAll('[data-bucket-del-id]').forEach(function(el) {
      el.addEventListener('click', function(e) {
        e.stopPropagation();
        bucketDeleteFromDB(parseInt(el.getAttribute('data-bucket-del-id')), el.closest('.bucket-saved-item'));
      });
    });
  } catch (e) {
    console.error('Bucket list failed:', e);
    list.innerHTML = '<div class="bucket-saved-empty">Failed to load</div>';
  }
}

async function bucketLoadFromDB(id) {
  try {
    var resp = await fetch(API_BASE + '/bucket/' + id);
    var data = await resp.json();
    if (data.items && data.items.length > 0) {
      /* Replace current bucket with loaded items */
      bucketItems = [];
      bucketCounter = 0;
      data.items.forEach(function(it) {
        bucketAdd(it);
      });
      /* Hide load list */
      var list = document.getElementById('bucket-saved-list');
      if (list) list.style.display = 'none';
    }
  } catch (e) {
    console.error('Bucket load failed:', e);
  }
}

async function bucketDeleteFromDB(id, itemEl) {
  try {
    var resp = await fetch(API_BASE + '/bucket/' + id, { method: 'DELETE' });
    var data = await resp.json();
    if (data.success && itemEl) {
      itemEl.remove();
      /* Check if list is now empty */
      var list = document.getElementById('bucket-saved-list');
      if (list && !list.querySelector('.bucket-saved-item')) {
        list.innerHTML = '<div class="bucket-saved-empty">No saved buckets</div>';
      }
    }
  } catch (e) {
    console.error('Bucket delete failed:', e);
  }
}

/* ═══════════════════════════════════════════════════════════════
   TEXT DROP — drop bucket text items onto any input/textarea
   ═══════════════════════════════════════════════════════════════ */

document.addEventListener('dragover', function(e) {
  if (!e.dataTransfer.types || e.dataTransfer.types.indexOf('application/x-bucket-item') === -1) return;
  var field = e.target.closest('textarea, input[type="text"], .fl-input');
  if (!field) return;
  if (bucketDragItem && bucketDragItem.type === 'text') {
    e.preventDefault();
    e.dataTransfer.dropEffect = 'copy';
    field.classList.add('bucket-drop-active');
  }
});

document.addEventListener('dragleave', function(e) {
  var field = e.target.closest('textarea, input[type="text"], .fl-input');
  if (field) field.classList.remove('bucket-drop-active');
});

document.addEventListener('drop', function(e) {
  var field = e.target.closest('textarea, input[type="text"], .fl-input');
  if (!field) return;
  field.classList.remove('bucket-drop-active');
  var raw = e.dataTransfer.getData('application/x-bucket-item');
  if (!raw) return;
  try {
    var item = JSON.parse(raw);
    if (item.type === 'text' && item.label) {
      e.preventDefault();
      /* Insert at cursor or append */
      var start = field.selectionStart || field.value.length;
      var before = field.value.substring(0, start);
      var after = field.value.substring(field.selectionEnd || start);
      field.value = before + (before && !before.endsWith(' ') ? ' ' : '') + item.label + after;
      field.focus();
      field.dispatchEvent(new Event('input', { bubbles: true }));
    }
  } catch (err) { console.warn('[bucket] text drop error', err); }
});
