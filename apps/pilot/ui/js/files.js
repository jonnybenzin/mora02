/* ═══════════════════════════════════════════════════════════════
   MORA02 PILOT — Files Module v3 (2026-03-19)
   ═══════════════════════════════════════════════════════════════ */

var FILES_BASE = 'http://mora02.local:8092';
var filesAll = [];
var filesShown = 0;
var FILES_PAGE = 24;

/* ─── Init ──────────────────────────────────────────────────── */

async function initFiles() {
  filesAll = [];
  filesShown = 0;
  var grid = document.getElementById('files-grid');
  if (grid) grid.innerHTML = '';
  filesSetCount('loading...');

  var results = await Promise.allSettled([
    filesLoadImages(),
    filesLoadTool('gifer', 'gif'),
    filesLoadTool('clipper', 'mp4'),
    filesLoadTool('typer', 'png'),
  ]);

  results.forEach(function(r) {
    if (r.status === 'fulfilled' && r.value) filesAll = filesAll.concat(r.value);
  });

  filesDoSort();
  filesSetCount(filesAll.length + ' files');
  filesRenderMore();

  var typeSel = document.getElementById('files-type');
  if (typeSel) typeSel.onchange = function() {
    filesShown = 0;
    if (grid) grid.innerHTML = '';
    var filtered = filesGetFiltered();
    filesSetCount(filtered.length + (typeSel.value === 'all' ? '' : ' of ' + filesAll.length) + ' files');
    filesRenderMore();
  };

  var sortSel = document.getElementById('files-sort');
  if (sortSel) sortSel.onchange = function() {
    filesDoSort();
    filesShown = 0;
    if (grid) grid.innerHTML = '';
    filesRenderMore();
  };
}

/* ─── Load ComfyUI images ───────────────────────────────────── */

async function filesLoadImages() {
  try {
    var resp = await fetch(FILES_BASE + '/comfyui/wip/');
    var data = await resp.json();
    var items = [];
    data.forEach(function(f) {
      if (f.type === 'file' && /\.(png|jpg|jpeg|webp)$/i.test(f.name)) {
        items.push({
          name: f.name,
          type: 'images',
          url: FILES_BASE + '/comfyui/wip/' + f.name,
          thumb: FILES_BASE + '/comfyui/wip/' + f.name,
          mtime: f.mtime || '',
        });
      }
    });
    return items;
  } catch (e) { return []; }
}

/* ─── Load tool assets (gifer/clipper/typer) ────────────────── */

async function filesLoadTool(tool, ext) {
  try {
    var resp = await fetch(FILES_BASE + '/tool-assets/' + tool + '/');
    var data = await resp.json();
    var folders = data.filter(function(f) {
      return f.type === 'directory' && !f.name.startsWith('x_');
    });

    var fetches = folders.map(function(f) {
      var folder = f.name.replace(/\/$/, '');
      var folderUrl = FILES_BASE + '/tool-assets/' + tool + '/' + folder + '/';
      return fetch(folderUrl).then(function(r) { return r.json(); }).then(function(files) {
        var media = files.find(function(ff) {
          return ff.type === 'file' && new RegExp('\\.' + ext + '$', 'i').test(ff.name);
        });
        if (!media) return null;
        return {
          name: media.name,
          type: tool,
          url: folderUrl + media.name,
          thumb: folderUrl + media.name,
          isVideo: ext === 'mp4',
          mtime: media.mtime || f.mtime || '',
        };
      }).catch(function() { return null; });
    });

    var results = await Promise.all(fetches);
    return results.filter(function(r) { return r !== null; });
  } catch (e) { return []; }
}

/* ─── Sort ──────────────────────────────────────────────────── */

function filesDoSort() {
  var order = (document.getElementById('files-sort') || {}).value || 'newest';
  if (order === 'newest') {
    filesAll.sort(function(a, b) { return new Date(b.mtime || 0) - new Date(a.mtime || 0); });
  } else if (order === 'oldest') {
    filesAll.sort(function(a, b) { return new Date(a.mtime || 0) - new Date(b.mtime || 0); });
  } else {
    filesAll.sort(function(a, b) { return a.name.toLowerCase().localeCompare(b.name.toLowerCase()); });
  }
}

/* ─── Filter ────────────────────────────────────────────────── */

function filesGetFiltered() {
  var type = (document.getElementById('files-type') || {}).value || 'all';
  return type === 'all' ? filesAll : filesAll.filter(function(f) { return f.type === type; });
}

/* ─── Render ────────────────────────────────────────────────── */

function filesRenderMore() {
  var grid = document.getElementById('files-grid');
  if (!grid) return;

  var filtered = filesGetFiltered();
  var batch = filtered.slice(filesShown, filesShown + FILES_PAGE);
  filesShown += batch.length;

  var oldBtn = grid.querySelector('.files-load-more');
  if (oldBtn) oldBtn.remove();

  batch.forEach(function(item) {
    var typeLabel = item.type === 'images' ? 'IMAGE' : item.type.toUpperCase();
    var card = document.createElement('div');
    card.className = 'files-card';
    card.innerHTML =
      '<div class="files-thumb" data-action="files-preview" data-url="' + item.url + '"' +
        (item.thumb ? ' data-thumb="' + item.thumb + '"' : '') +
        ' style="background:var(--c-grey2)">' +
        '<span style="color:var(--tx-disabled);font-size:10px">' + typeLabel + '</span>' +
        '<div class="files-actions">' +
          '<button class="files-action" data-action="files-download" data-url="' + item.url + '" data-name="' + filesEsc(item.name) + '" title="Download"><svg fill="currentColor"><use href="icons/sprite.svg#i-download"/></svg></button>' +
          '<button class="files-action" data-action="files-copy" data-url="' + item.url + '" title="Copy URL"><svg fill="currentColor"><use href="icons/sprite.svg#i-copy"/></svg></button>' +
        '</div>' +
      '</div>' +
      '<div class="files-info">' +
        '<span class="files-name">' + filesEsc(item.name) + '</span>' +
        '<span class="files-meta">' + typeLabel + '</span>' +
      '</div>';
    grid.appendChild(card);
  });

  if (filesShown < filtered.length) {
    var more = document.createElement('div');
    more.className = 'files-load-more';
    more.style.cssText = 'grid-column:1/-1;text-align:center;padding:var(--sp-16)';
    more.innerHTML = '<button class="tool-action-btn" data-action="files-load-more">LOAD MORE (' + (filtered.length - filesShown) + ' remaining)</button>';
    grid.appendChild(more);
  }

  filesLazy(grid);
}

/* ─── Lazy thumbnails ───────────────────────────────────────── */

var filesObs = null;

function filesLazy(grid) {
  if (!filesObs) {
    filesObs = new IntersectionObserver(function(entries) {
      entries.forEach(function(entry) {
        if (entry.isIntersecting) {
          var el = entry.target;
          var thumb = el.dataset.thumb;
          if (thumb && /\.(mp4|mov|webm)$/i.test(thumb)) {
            var vid = document.createElement('video');
            vid.src = thumb;
            vid.muted = true;
            vid.preload = 'metadata';
            vid.style.cssText = 'position:absolute;inset:0;width:100%;height:100%;object-fit:cover';
            vid.onloadeddata = function() { vid.currentTime = 0.5; };
            el.style.position = 'relative';
            el.appendChild(vid);
            var label = el.querySelector('span');
            if (label) label.style.display = 'none';
          } else if (thumb) {
            el.style.background = "url('" + thumb + "') center/cover";
            var label = el.querySelector('span');
            if (label) label.style.display = 'none';
          }
          filesObs.unobserve(el);
        }
      });
    }, { rootMargin: '300px' });
  }
  grid.querySelectorAll('.files-thumb[data-thumb]:not([data-lazy])').forEach(function(el) {
    el.dataset.lazy = '1';
    filesObs.observe(el);
  });
}

/* ─── Helpers ───────────────────────────────────────────────── */

function filesSetCount(t) {
  var el = document.getElementById('files-count');
  if (el) el.textContent = t;
}

function filesEsc(s) {
  var d = document.createElement('div');
  d.textContent = s;
  return d.innerHTML;
}

/* ─── Video Lightbox ─────────────────────────────────────────── */

function filesVideoLightbox(url) {
  var overlay = document.createElement('div');
  overlay.className = 'lightbox open';
  overlay.innerHTML =
    '<button class="lightbox-close" onclick="this.parentElement.remove()">&times;</button>' +
    '<video src="' + url + '" controls autoplay style="max-width:90vw;max-height:75vh;border-radius:var(--sp-4)"></video>' +
    '<div class="lightbox-actions">' +
      '<button class="lightbox-btn" onclick="var a=document.createElement(\'a\');a.href=\'' + url + '\';a.download=\'' + url.split('/').pop() + '\';document.body.appendChild(a);a.click();a.remove()">DOWNLOAD</button>' +
    '</div>';
  overlay.addEventListener('click', function(e) {
    if (e.target === overlay) overlay.remove();
  });
  document.body.appendChild(overlay);
}

/* ─── Events ────────────────────────────────────────────────── */

document.addEventListener('click', function(e) {
  var t = e.target.closest('[data-action]');
  if (!t) return;
  switch (t.dataset.action) {
    case 'files-preview':
      if (/\.(mp4|mov|webm)$/i.test(t.dataset.url)) filesVideoLightbox(t.dataset.url);
      else if (typeof openLightbox === 'function') openLightbox(t.dataset.url);
      else window.open(t.dataset.url, '_blank');
      break;
    case 'files-download':
      var a = document.createElement('a');
      a.href = t.dataset.url; a.download = t.dataset.name || 'file'; a.target = '_blank';
      document.body.appendChild(a); a.click(); a.remove();
      break;
    case 'files-copy':
      navigator.clipboard.writeText(t.dataset.url).catch(function(){});
      break;
    case 'files-load-more':
      filesRenderMore();
      break;
  }
});
