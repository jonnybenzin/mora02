/* ═══════════════════════════════════════════════════════════════
   MORA02 PILOT — Wiki Module v2 (2026-03-20)
   ═══════════════════════════════════════════════════════════════
   Browse + search knowledge docs with folder tabs.
   ═══════════════════════════════════════════════════════════════ */

var WIKI_BASE = 'http://mora02.local:8092/wiki/';
var wikiAll = [];
var wikiActiveTab = 'all';

/* ─── Recursive folder scanner ─────────────────────────────── */

async function wikiScanFolder(path, tabName, depth) {
  depth = depth || 0;
  if (depth > 3) return [];
  try {
    var resp = await fetch(WIKI_BASE + path + '/');
    var entries = await resp.json();
    var files = entries
      .filter(function(f) { return f.type === 'file' && /\.(md|txt|html)$/i.test(f.name); })
      .map(function(f) {
        return {
          name: f.name,
          folder: tabName,
          url: WIKI_BASE + path + '/' + f.name,
          mtime: f.mtime || '',
          size: f.size || 0,
        };
      });
    var subdirs = entries.filter(function(f) {
      return f.type === 'directory' && !f.name.startsWith('.');
    });
    var subResults = await Promise.all(subdirs.map(function(d) {
      var subPath = path + '/' + d.name.replace(/\/$/, '');
      return wikiScanFolder(subPath, tabName, depth + 1);
    }));
    subResults.forEach(function(r) { files = files.concat(r); });
    return files;
  } catch (e) { return []; }
}

/* ─── Init ──────────────────────────────────────────────────── */

async function initWiki() {
  wikiAll = [];
  wikiActiveTab = 'all';
  wikiHideDoc();

  /* Fetch folder list */
  var folders = [];
  try {
    var resp = await fetch(WIKI_BASE);
    var data = await resp.json();
    folders = data.filter(function(f) { return f.type === 'directory'; }).map(function(f) {
      return f.name.replace(/\/$/, '');
    });
  } catch (e) { folders = []; }

  /* Render tabs */
  wikiRenderTabs(folders);

  /* Fetch all folders in parallel (with recursive subfolder scan) */
  var fetches = folders.map(function(folder) {
    return wikiScanFolder(folder, folder);
  });

  var results = await Promise.all(fetches);
  results.forEach(function(files) { wikiAll = wikiAll.concat(files); });

  /* Sort newest first */
  wikiAll.sort(function(a, b) { return new Date(b.mtime || 0) - new Date(a.mtime || 0); });

  wikiUpdateCount();
  wikiRenderList();

  /* Search listener */
  var search = document.getElementById('wiki-search');
  if (search) {
    search.value = '';
    search.addEventListener('input', function() { wikiRenderList(); });
  }
}

/* ─── Tabs ──────────────────────────────────────────────────── */

function wikiRenderTabs(folders) {
  var container = document.getElementById('wiki-tabs');
  if (!container) return;

  var html = '<button class="wiki-tab wiki-tab-active" data-action="wiki-tab" data-tab="all">ALL</button>';
  folders.forEach(function(f) {
    html += '<button class="wiki-tab" data-action="wiki-tab" data-tab="' + f + '">' + f.toUpperCase() + '</button>';
  });
  container.innerHTML = html;
}

function wikiSetTab(tab) {
  wikiActiveTab = tab;

  /* Update active class */
  document.querySelectorAll('.wiki-tab').forEach(function(btn) {
    btn.classList.toggle('wiki-tab-active', btn.dataset.tab === tab);
  });

  wikiUpdateCount();
  wikiRenderList();
}

/* ─── Get filtered files ────────────────────────────────────── */

function wikiGetFiltered() {
  var search = (document.getElementById('wiki-search') || {}).value || '';
  var q = search.toLowerCase().trim();

  var filtered = wikiAll;

  /* Tab filter */
  if (wikiActiveTab !== 'all') {
    filtered = filtered.filter(function(f) { return f.folder === wikiActiveTab; });
  }

  /* Search filter */
  if (q) {
    filtered = filtered.filter(function(f) { return f.name.toLowerCase().indexOf(q) !== -1; });
  }

  return filtered;
}

function wikiUpdateCount() {
  var filtered = wikiGetFiltered();
  var el = document.getElementById('wiki-count');
  if (el) {
    var total = wikiActiveTab === 'all' ? wikiAll.length : wikiAll.filter(function(f) { return f.folder === wikiActiveTab; }).length;
    el.textContent = filtered.length + (filtered.length !== total ? ' of ' + total : '') + ' docs';
  }
}

/* ─── Render File List ──────────────────────────────────────── */

function wikiRenderList() {
  var list = document.getElementById('wiki-list');
  if (!list) return;

  var files = wikiGetFiltered();

  if (files.length === 0) {
    list.innerHTML = '<div style="color:var(--tx-disabled);padding:var(--sp-16)">No documents found</div>';
    return;
  }

  var html = '';
  files.forEach(function(f) {
    var date = f.mtime ? new Date(f.mtime) : null;
    var dateStr = date ? date.toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: '2-digit' }) : '';
    var sizeStr = f.size ? wikiSize(f.size) : '';
    var icon = f.name.endsWith('.md') ? '📄' : '📝';
    var stale = date && (Date.now() - date.getTime()) > 90 * 24 * 60 * 60 * 1000;
    var staleTag = stale ? '<span style="font-size:var(--fs-xs);color:var(--c-yellow,#e8a735);margin-left:var(--sp-6)" title="Last modified over 90 days ago">⚠ OUTDATED?</span>' : '';

    html +=
      '<div class="tool-item" style="cursor:pointer" data-action="wiki-open" data-url="' + wikiEsc(f.url) + '" data-name="' + wikiEsc(f.name) + '">' +
        '<span class="tool-item-num">' + icon + '</span>' +
        '<span class="tool-item-name">' + wikiEsc(f.name) + staleTag + '</span>' +
        (wikiActiveTab === 'all' ? '<span style="font-family:var(--ff-mono);font-size:var(--fs-xs);color:var(--tx-disabled);white-space:nowrap;margin-left:var(--sp-8)">' + f.folder + '</span>' : '') +
        '<span style="font-family:var(--ff-mono);font-size:var(--fs-xs);color:var(--tx-disabled);white-space:nowrap;margin-left:auto">' + sizeStr + '</span>' +
        '<span style="font-family:var(--ff-mono);font-size:var(--fs-xs);color:var(--tx-muted);white-space:nowrap;min-width:80px;text-align:right">' + dateStr + '</span>' +
      '</div>';
  });

  list.innerHTML = html;
}

/* ─── Open Document ─────────────────────────────────────────── */

async function wikiOpen(url, name) {
  var nameEl = document.getElementById('wiki-doc-name');
  var bodyEl = document.getElementById('wiki-doc-body');
  if (nameEl) nameEl.textContent = name;
  if (bodyEl) bodyEl.innerHTML = '<div style="color:var(--tx-disabled)">Loading...</div>';

  wikiShowDoc();

  try {
    var resp = await fetch(url);
    var text = await resp.text();

    if (bodyEl) {
      if (/\.md$/i.test(name) && typeof marked !== 'undefined' && marked.parse) {
        bodyEl.innerHTML = marked.parse(text);
      } else if (/\.html$/i.test(name)) {
        bodyEl.innerHTML = text;
      } else {
        bodyEl.innerHTML = '<pre style="white-space:pre-wrap;font-family:var(--ff-mono);font-size:var(--fs-sm);color:var(--tx-secondary)">' + wikiEsc(text) + '</pre>';
      }
    }
  } catch (e) {
    if (bodyEl) bodyEl.innerHTML = '<div style="color:var(--c-red)">Failed to load: ' + wikiEsc(e.message) + '</div>';
  }
}

/* ─── Show/Hide ─────────────────────────────────────────────── */

function wikiShowDoc() {
  var nav = document.getElementById('wiki-nav');
  var doc = document.getElementById('wiki-doc');
  if (nav) nav.style.display = 'none';
  if (doc) doc.style.display = '';
}

function wikiHideDoc() {
  var nav = document.getElementById('wiki-nav');
  var doc = document.getElementById('wiki-doc');
  if (nav) nav.style.display = '';
  if (doc) doc.style.display = 'none';
}

/* ─── Helpers ───────────────────────────────────────────────── */

function wikiSize(bytes) {
  if (bytes < 1024) return bytes + 'B';
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(0) + 'KB';
  return (bytes / (1024 * 1024)).toFixed(1) + 'MB';
}

function wikiEsc(s) {
  var d = document.createElement('div');
  d.textContent = s;
  return d.innerHTML;
}

/* ─── Events ────────────────────────────────────────────────── */

document.addEventListener('click', function(e) {
  var t = e.target.closest('[data-action]');
  if (!t) return;
  switch (t.dataset.action) {
    case 'wiki-tab':   wikiSetTab(t.dataset.tab); break;
    case 'wiki-open':  wikiOpen(t.dataset.url, t.dataset.name); break;
    case 'wiki-close': wikiHideDoc(); break;
    case 'xray-view':  xrayLoadView(t.dataset.view); break;
    case 'xray-run':   prompt('Paste this in your terminal:', 'python3 /opt/mora02/scripts/xray/mora02-xray.py'); break;
  }
});

/* ─── X-Ray Dashboard Loader ───────────────────────────────── */
var xrayLatest = '';
var xrayView = 'dashboard';

function initXray() {
  fetch('http://mora02.local:8092/wiki/x-ray/')
    .then(function(r) { return r.json(); })
    .then(function(dirs) {
      var sorted = dirs.filter(function(d) { return d.type === 'directory'; })
        .sort(function(a, b) { return b.name.localeCompare(a.name); });
      if (sorted.length) {
        xrayLatest = sorted[0].name.replace(/\/\$/, '');
        xrayLoadView('dashboard');
      }
    });
}

function xrayLoadView(view) {
  xrayView = view;
  var frame = document.getElementById('xray-frame');
  if (frame && xrayLatest) {
    frame.src = 'http://mora02.local:8092/wiki/x-ray/' + xrayLatest + '/xray-' + view + '.html';
  }
  var btnD = document.getElementById('xray-btn-dashboard');
  var btnA = document.getElementById('xray-btn-architektur');
  if (btnD) btnD.style.opacity = view === 'dashboard' ? '1' : '0.4';
  if (btnA) btnA.style.opacity = view === 'architektur' ? '1' : '0.4';
}
