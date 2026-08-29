/* ═══════════════════════════════════════════════════════════════
   MORA02 PILOT — Wiki Module v3 (Kompendium)
   ═══════════════════════════════════════════════════════════════
   Four fixed tabs over the Kompendium under /opt/mora02/kompendium/:
     ATLAS  — one file per article (atlas/<slug>.md)
     ADR    — one file per ADR     (adrs/NNN-<slug>.md)
     GLOSSAR — sections in glossar.md, split at "## term"
     BASH   — sections in bash.md,   split at "## command"
   Plus an X-RAY tab that embeds the latest scan dashboard.
   Live filter works against the entry-name list of the active tab.
   ═══════════════════════════════════════════════════════════════ */

var WIKI_BASE = 'http://mora02.local:8092/wiki/';
var XRAY_BASE = 'http://mora02.local:8092/x-ray/';

var wikiTabs = [
  { id: 'atlas',   label: 'ATLAS',   kind: 'files',    path: 'atlas/',  excludeRe: /^(README|coverage)\.md$/i },
  { id: 'glossar', label: 'GLOSSAR', kind: 'sections', path: 'glossar.md' },
  { id: 'bash',    label: 'BASH',    kind: 'sections', path: 'bash.md' },
  { id: 'adr',     label: 'ADR',     kind: 'files',    path: 'adrs/' },
  { id: 'vocab',   label: 'VOKABULAR', kind: 'table' },
  { id: 'xray',    label: 'X-RAY',   kind: 'iframe' }
];

var wikiActive = 'atlas';
var wikiCache = {};       // per-tab cached entry list
var wikiSourceFile = {};  // per-tab source-file URL (for sections)
var wikiHistory = [];     // back-stack of doc snapshots {tabId, docName, docHtml}
var xrayLatest = '';
var xrayView = 'dashboard';

/* ─── Init ──────────────────────────────────────────────────── */

async function initWiki() {
  wikiActive = 'atlas';
  wikiCache = {};
  wikiSourceFile = {};
  wikiHistory = [];
  wikiUpdateBackButton();
  wikiHideDoc();

  wikiRenderTabs();
  await wikiLoadTab(wikiActive);

  /* Search listener */
  var search = document.getElementById('wiki-search');
  if (search) {
    search.value = '';
    search.removeEventListener('input', wikiOnSearchInput);
    search.addEventListener('input', wikiOnSearchInput);
  }
}

function wikiOnSearchInput() {
  var value = (document.getElementById('wiki-search') || {}).value || '';
  if (wikiActive === 'vocab') { vocabOnSearch(value); return; }
  wikiUpdateCount();
  wikiRenderList();
}

/* ─── Tabs ──────────────────────────────────────────────────── */

function wikiRenderTabs() {
  var container = document.getElementById('wiki-tabs');
  if (!container) return;
  var html = '';
  wikiTabs.forEach(function(t) {
    var cls = 'wiki-tab' + (t.id === wikiActive ? ' wiki-tab-active' : '');
    html += '<button class="' + cls + '" data-action="wiki-tab" data-tab="' + t.id + '">' + t.label + '</button>';
  });
  container.innerHTML = html;
}

async function wikiSetTab(tab) {
  wikiActive = tab;
  wikiClearHistory();
  wikiRenderTabs();
  var search = document.getElementById('wiki-search');
  if (search) search.value = '';
  await wikiLoadTab(tab);
}

/* ─── Load active tab ───────────────────────────────────────── */

async function wikiLoadTab(tabId) {
  var tab = wikiTabs.find(function(t) { return t.id === tabId; });
  if (!tab) return;

  var nav = document.getElementById('wiki-nav');
  var doc = document.getElementById('wiki-doc');

  /* X-Ray uses its own viewer */
  if (tab.kind === 'iframe') {
    wikiShowXray();
    return;
  }

  /* VOKABULAR renders its own table into the list area: it is not a pile of
     documents but one live view, fed from /pipeline/ops rather than from a file. */
  if (tab.kind === 'table') {
    wikiHideDoc();
    wikiHideXray();
    var vs = document.getElementById('wiki-search');
    if (vs) { vs.style.display = ''; vs.placeholder = 'Vokabel, Zweck oder Dienst suchen…'; }
    var vc = document.getElementById('wiki-count');
    if (vc) vc.textContent = '';
    await vocabShow();
    return;
  }

  /* Reset to nav view */
  wikiHideDoc();
  wikiHideXray();

  /* Hide search field for X-Ray-only tabs, show otherwise */
  var search = document.getElementById('wiki-search');
  if (search) { search.style.display = ''; search.placeholder = 'Filter by filename...'; }

  /* Load entries (cached) */
  if (!wikiCache[tabId]) {
    if (tab.kind === 'files') {
      wikiCache[tabId] = await wikiLoadFiles(tab);
    } else if (tab.kind === 'sections') {
      var res = await wikiLoadSections(tab);
      wikiCache[tabId] = res.entries;
      wikiSourceFile[tabId] = res.sourceUrl;
    }
  }

  wikiUpdateCount();
  wikiRenderList();
}

/* ─── Loader: files (atlas/, adrs/) ─────────────────────────── */

async function wikiLoadFiles(tab) {
  try {
    var resp = await fetch(WIKI_BASE + tab.path);
    var entries = await resp.json();
    return entries
      .filter(function(f) { return f.type === 'file' && /\.md$/i.test(f.name); })
      .filter(function(f) { return !tab.excludeRe || !tab.excludeRe.test(f.name); })
      .map(function(f) {
        return {
          name: f.name.replace(/\.md$/i, ''),
          file: f.name,
          url: WIKI_BASE + tab.path + f.name,
          mtime: f.mtime || '',
          size: f.size || 0
        };
      })
      .sort(function(a, b) { return a.name.localeCompare(b.name); });
  } catch (e) {
    return [];
  }
}

/* ─── Loader: sections (glossar.md, bash.md) ────────────────── */

async function wikiLoadSections(tab) {
  var sourceUrl = WIKI_BASE + tab.path;
  try {
    var resp = await fetch(sourceUrl);
    var text = await resp.text();
    var entries = wikiParseSections(text);
    return { entries: entries, sourceUrl: sourceUrl };
  } catch (e) {
    return { entries: [], sourceUrl: sourceUrl };
  }
}

/* Parse Markdown into entries.
   Layout: frontmatter (--- ... ---), then a file-level "# Title" + intro,
   then entries separated by "---" lines. Inside each entry block the first
   "## name" line is the entry title; the rest of the block (which may
   contain further "## subsections") becomes the body.
   Returns: [{name, body}], sorted by name. */
function wikiParseSections(text) {
  /* Strip leading frontmatter */
  text = text.replace(/^---[\s\S]*?\n---\s*\n?/, '');

  /* Split at "---" lines (entry separator) */
  var blocks = text.split(/^---\s*$/m);

  var sections = [];
  blocks.forEach(function(block) {
    var lines = block.split('\n');
    var name = null;
    var bodyLines = [];
    for (var i = 0; i < lines.length; i++) {
      var line = lines[i];
      if (name === null) {
        var m = line.match(/^##\s+(.+?)\s*$/);
        if (m) {
          name = m[1].trim();
        }
        /* Skip everything before the first "## name" header in a block —
           that filters the file-level "# Title" + intro paragraph. */
        continue;
      }
      bodyLines.push(line);
    }
    if (name) {
      sections.push({ name: name, body: bodyLines.join('\n').trim() });
    }
  });

  return sections.sort(function(a, b) { return a.name.localeCompare(b.name); });
}

/* ─── Filter + render list ──────────────────────────────────── */

function wikiGetFiltered() {
  var entries = wikiCache[wikiActive] || [];
  var search = (document.getElementById('wiki-search') || {}).value || '';
  var q = search.toLowerCase().trim();
  if (!q) return entries;
  return entries.filter(function(e) { return e.name.toLowerCase().indexOf(q) !== -1; });
}

function wikiUpdateCount() {
  var el = document.getElementById('wiki-count');
  if (!el) return;
  var entries = wikiCache[wikiActive] || [];
  var filtered = wikiGetFiltered();
  el.textContent = filtered.length + (filtered.length !== entries.length ? ' of ' + entries.length : '') + ' entries';
}

function wikiRenderList() {
  var list = document.getElementById('wiki-list');
  if (!list) return;

  var entries = wikiGetFiltered();
  if (entries.length === 0) {
    list.innerHTML = '<div style="color:var(--tx-disabled);padding:var(--sp-16)">No entries found</div>';
    return;
  }

  var tab = wikiTabs.find(function(t) { return t.id === wikiActive; });
  var isFiles = tab.kind === 'files';

  var html = '';
  entries.forEach(function(e) {
    var icon = isFiles ? '📄' : '◆';
    if (isFiles) {
      html +=
        '<div class="tool-item" style="cursor:pointer" data-action="wiki-open-file" data-url="' + wikiEsc(e.url) + '" data-name="' + wikiEsc(e.name) + '">' +
          '<span class="tool-item-num">' + icon + '</span>' +
          '<span class="tool-item-name">' + wikiEsc(e.name) + '</span>' +
        '</div>';
    } else {
      html +=
        '<div class="tool-item" style="cursor:pointer" data-action="wiki-open-section" data-name="' + wikiEsc(e.name) + '">' +
          '<span class="tool-item-num">' + icon + '</span>' +
          '<span class="tool-item-name">' + wikiEsc(e.name) + '</span>' +
        '</div>';
    }
  });
  list.innerHTML = html;
}

/* ─── Wiki-link transform ───────────────────────────────────── */

/* Convert [[target]] and [[target|display]] markers to clickable anchors
   that our click delegate handles (data-action="wiki-jump").
   Targets: atlas/<slug>, adr/<NNN-slug>, bash/<cmd>, glossar/<term>,
   or bare <term> (treated as glossar). */
function wikiTransformWikiLinks(md) {
  return md.replace(/\[\[([^\]|]+)(?:\|([^\]]+))?\]\]/g, function(_, target, display) {
    target = target.trim();
    var text = (display || target).trim();
    var slash = target.indexOf('/');
    var type, name;
    if (slash >= 0) {
      type = target.slice(0, slash).toLowerCase();
      name = target.slice(slash + 1);
    } else {
      type = 'glossar';
      name = target;
    }
    return '<a href="javascript:void(0)" class="wiki-link" data-action="wiki-jump"' +
           ' data-type="' + wikiAttrEsc(type) + '" data-name="' + wikiAttrEsc(name) + '">' +
           wikiEsc(text) + '</a>';
  });
}

/* ─── Open: file (atlas, adr) ───────────────────────────────── */

async function wikiOpenFile(url, name) {
  var nameEl = document.getElementById('wiki-doc-name');
  var bodyEl = document.getElementById('wiki-doc-body');
  if (nameEl) nameEl.textContent = name;
  if (bodyEl) bodyEl.innerHTML = '<div style="color:var(--tx-disabled)">Loading...</div>';
  wikiShowDoc();

  try {
    var resp = await fetch(url);
    var text = await resp.text();
    /* Strip frontmatter before rendering */
    text = text.replace(/^---[\s\S]*?\n---\s*\n?/, '');
    text = wikiTransformWikiLinks(text);
    if (bodyEl) {
      if (typeof marked !== 'undefined' && marked.parse) {
        bodyEl.innerHTML = marked.parse(text);
      } else {
        bodyEl.innerHTML = '<pre style="white-space:pre-wrap">' + wikiEsc(text) + '</pre>';
      }
    }
  } catch (e) {
    if (bodyEl) bodyEl.innerHTML = '<div style="color:var(--c-red)">Failed to load: ' + wikiEsc(e.message) + '</div>';
  }
}

/* ─── Open: section (glossar, bash) ─────────────────────────── */

function wikiOpenSection(name) {
  var entries = wikiCache[wikiActive] || [];
  var entry = entries.find(function(e) { return e.name === name; });
  if (!entry) return;

  var nameEl = document.getElementById('wiki-doc-name');
  var bodyEl = document.getElementById('wiki-doc-body');
  if (nameEl) nameEl.textContent = name;

  /* Render entry-name as H1, body keeps its own H2 subsections */
  var md = '# ' + entry.name + '\n\n' + wikiTransformWikiLinks(entry.body);
  if (bodyEl) {
    if (typeof marked !== 'undefined' && marked.parse) {
      bodyEl.innerHTML = marked.parse(md);
    } else {
      bodyEl.innerHTML = '<pre style="white-space:pre-wrap">' + wikiEsc(md) + '</pre>';
    }
  }
  wikiShowDoc();
}

/* ─── History stack: back-button across cross-links ────────── */

function wikiSnapshotState() {
  var nameEl = document.getElementById('wiki-doc-name');
  var bodyEl = document.getElementById('wiki-doc-body');
  if (!nameEl || !bodyEl) return null;
  if (!bodyEl.innerHTML.trim()) return null;
  return { tabId: wikiActive, docName: nameEl.textContent, docHtml: bodyEl.innerHTML };
}

function wikiPushHistory() {
  var snap = wikiSnapshotState();
  if (snap) {
    wikiHistory.push(snap);
    wikiUpdateBackButton();
  }
}

function wikiClearHistory() {
  wikiHistory = [];
  wikiUpdateBackButton();
}

function wikiUpdateBackButton() {
  var btn = document.getElementById('wiki-back');
  if (btn) btn.style.display = wikiHistory.length > 0 ? '' : 'none';
}

function wikiBack() {
  if (!wikiHistory.length) return;
  var prev = wikiHistory.pop();
  wikiUpdateBackButton();

  /* Switch tab if needed (without clearing history!) */
  if (prev.tabId !== wikiActive) {
    wikiActive = prev.tabId;
    wikiRenderTabs();
    /* Reset search field — the snapshot already has the doc content,
       and we don't want stale filter state from the previous tab. */
    var search = document.getElementById('wiki-search');
    if (search) search.value = '';
  }

  /* Restore doc directly from snapshot (no re-fetch needed) */
  var nameEl = document.getElementById('wiki-doc-name');
  var bodyEl = document.getElementById('wiki-doc-body');
  if (nameEl) nameEl.textContent = prev.docName;
  if (bodyEl) bodyEl.innerHTML = prev.docHtml;
  wikiShowDoc();
}

/* ─── Wiki-jump: cross-link click ──────────────────────────── */

async function wikiJump(type, name) {
  /* Push current state so BACK can come back here */
  wikiPushHistory();

  /* Map type to existing tab. Unknown types fall back to glossar. */
  var validTabs = { atlas: 1, adr: 1, bash: 1, glossar: 1 };
  var tabId = validTabs[type] ? type : 'glossar';

  /* Switch tab if needed (without clearing history!) */
  if (tabId !== wikiActive) {
    wikiActive = tabId;
    wikiRenderTabs();
    var search = document.getElementById('wiki-search');
    if (search) search.value = '';
  }

  /* Load tab if not cached */
  if (!wikiCache[tabId]) {
    await wikiLoadTab(tabId);
  }

  /* Resolve and open target entry */
  var entries = wikiCache[tabId] || [];
  var entry;
  if (tabId === 'atlas' || tabId === 'adr') {
    /* file-based: match by displayed name (filename without .md) */
    entry = entries.find(function(e) { return e.name === name; });
    if (entry) {
      wikiOpenFile(entry.url, entry.name);
    } else {
      wikiJumpMiss(tabId, name);
    }
  } else {
    /* section-based */
    entry = entries.find(function(e) { return e.name === name; });
    if (entry) {
      wikiOpenSection(name);
    } else {
      wikiJumpMiss(tabId, name);
    }
  }
}

function wikiJumpMiss(tabId, name) {
  var bodyEl = document.getElementById('wiki-doc-body');
  var nameEl = document.getElementById('wiki-doc-name');
  if (nameEl) nameEl.textContent = name + ' (not found)';
  if (bodyEl) bodyEl.innerHTML =
    '<div style="color:var(--c-yellow,#e8a735);padding:var(--sp-16)">' +
    'Wiki entry <strong>' + wikiEsc(name) + '</strong> in <strong>' + wikiEsc(tabId) + '</strong> not found.<br>' +
    'The cross-link points to an entry that doesn\'t exist (yet).' +
    '</div>';
  wikiShowDoc();
}

/* ─── Show/Hide ─────────────────────────────────────────────── */

function wikiShowDoc() {
  var nav = document.getElementById('wiki-nav');
  var doc = document.getElementById('wiki-doc');
  var xray = document.getElementById('wiki-xray');
  if (nav) nav.style.display = 'none';
  if (doc) doc.style.display = '';
  if (xray) xray.style.display = 'none';
}

function wikiHideDoc() {
  var nav = document.getElementById('wiki-nav');
  var doc = document.getElementById('wiki-doc');
  if (nav) nav.style.display = '';
  if (doc) doc.style.display = 'none';
}

/* ─── X-Ray viewer ──────────────────────────────────────────── */

function wikiShowXray() {
  var nav = document.getElementById('wiki-nav');
  var doc = document.getElementById('wiki-doc');
  if (nav) nav.style.display = 'none';
  if (doc) doc.style.display = 'none';

  var host = document.getElementById('wiki-xray');
  if (!host) {
    /* Create lazy on first open */
    host = document.createElement('div');
    host.id = 'wiki-xray';
    host.style.cssText = 'display:flex;flex-direction:column;height:100%;gap:var(--sp-8)';
    host.innerHTML =
      '<div style="display:flex;gap:var(--sp-8);align-items:center">' +
        '<button id="xray-btn-dashboard" class="tool-action-btn" data-action="xray-view" data-view="dashboard">DASHBOARD</button>' +
        '<button id="xray-btn-architektur" class="tool-action-btn" data-action="xray-view" data-view="architektur">ARCHITEKTUR</button>' +
        '<button class="tool-action-btn" data-action="xray-run">RUN SCAN</button>' +
        '<span id="xray-stamp" style="font-family:var(--ff-mono);font-size:var(--fs-xs);color:var(--tx-disabled);margin-left:auto"></span>' +
      '</div>' +
      '<iframe id="xray-frame" style="flex:1;border:1px solid var(--brd);background:white" src="about:blank"></iframe>';
    var wrap = document.querySelector('.tool-wrap');
    if (wrap) wrap.appendChild(host);
  }
  host.style.display = '';

  if (!xrayLatest) {
    initXray();
  } else {
    xrayLoadView(xrayView);
  }
}

function wikiHideXray() {
  var host = document.getElementById('wiki-xray');
  if (host) host.style.display = 'none';
}

function initXray() {
  fetch(XRAY_BASE)
    .then(function(r) { return r.json(); })
    .then(function(dirs) {
      var sorted = dirs.filter(function(d) { return d.type === 'directory'; })
        .sort(function(a, b) { return b.name.localeCompare(a.name); });
      if (sorted.length) {
        xrayLatest = sorted[0].name.replace(/\/$/, '');
        var stamp = document.getElementById('xray-stamp');
        if (stamp) stamp.textContent = 'latest: ' + xrayLatest;
        xrayLoadView(xrayView);
      }
    })
    .catch(function() {
      var stamp = document.getElementById('xray-stamp');
      if (stamp) stamp.textContent = 'no scans found';
    });
}

function xrayLoadView(view) {
  xrayView = view;
  var frame = document.getElementById('xray-frame');
  if (frame && xrayLatest) {
    frame.src = XRAY_BASE + xrayLatest + '/xray-' + view + '.html';
  }
  var btnD = document.getElementById('xray-btn-dashboard');
  var btnA = document.getElementById('xray-btn-architektur');
  if (btnD) btnD.style.opacity = view === 'dashboard' ? '1' : '0.4';
  if (btnA) btnA.style.opacity = view === 'architektur' ? '1' : '0.4';
}

/* ─── Helpers ───────────────────────────────────────────────── */

function wikiEsc(s) {
  var d = document.createElement('div');
  d.textContent = String(s == null ? '' : s);
  return d.innerHTML;
}

function wikiAttrEsc(s) {
  return String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;');
}

/* ─── Events ────────────────────────────────────────────────── */

document.addEventListener('click', function(e) {
  var t = e.target.closest('[data-action]');
  if (!t) return;
  switch (t.dataset.action) {
    case 'wiki-tab':           wikiSetTab(t.dataset.tab); break;
    case 'wiki-open-file':     wikiClearHistory(); wikiOpenFile(t.dataset.url, t.dataset.name); break;
    case 'wiki-open-section':  wikiClearHistory(); wikiOpenSection(t.dataset.name); break;
    case 'wiki-jump':          wikiJump(t.dataset.type, t.dataset.name); break;
    case 'wiki-back':          wikiBack(); break;
    case 'wiki-close':         wikiClearHistory(); wikiHideDoc(); break;
    case 'xray-view':          xrayLoadView(t.dataset.view); break;
    case 'xray-run':           prompt('Paste this in your terminal:', 'python3 /opt/mora02/scripts/xray/mora02-xray.py'); break;
  }
});
