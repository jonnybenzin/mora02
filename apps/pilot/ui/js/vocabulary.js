/* VOCABULARY — the pipeline vocabulary as a filterable table.
 *
 * Two sources, both live:
 *   /pipeline/ops         the vocabulary itself (mora02_core.pipeline.vocab)
 *   /pipeline/vocab-stats what the run logs know: how long an op really takes,
 *                         when it last worked, what it has actually cost
 *
 * Deliberately NOT the generated markdown. That file is only correct when
 * somebody remembers to regenerate it, and on 2026-08-29 it claimed image.facefix
 * was unbuilt while the op had been running for weeks. The builder palette reads
 * the same endpoint, so both views of the vocabulary can only ever agree.
 *
 * The stats endpoint may be absent (older container) and every measured field may
 * be missing: the table then shows an em dash and stays usable. A view that dies
 * because one of its two sources is quiet would be worse than one that says "not
 * measured yet".
 */

var VOCAB_API = (typeof FLOWS_API !== 'undefined' && FLOWS_API)
  ? FLOWS_API : 'http://mora02.local:8096';

var vocabOps = [];
var vocabStats = null;
var vocabFilters = [];      // active filter ids; empty === ALL
var vocabSearch = '';
var vocabOpen = {};         // op name -> row expanded?

/* Filters are questions a human asks before using an op, not database columns. */
var VOCAB_FILTERS = [
  { id: 'free',    label: 'free',            test: function(o){ return o.cost === 'free'; } },
  { id: 'paid',    label: 'costs money',       test: function(o){ return o.cost === 'paid' || o.cost === 'mixed'; } },
  { id: 'gpu',     label: 'GPU time',          test: function(o){ return o.runs_on === 'local-gpu'; } },
  { id: 'local',   label: 'local',             test: function(o){ return (o.runs_on || '').indexOf('local') === 0; } },
  { id: 'cloud',   label: 'cloud',             test: function(o){ return o.runs_on === 'cloud'; } },
  { id: 'outward', label: 'leaves the house', test: function(o){ return o.effect === 'outward'; } },
  { id: 'writes',  label: 'writes',          test: function(o){ return o.effect === 'writes'; } }
];

function _vEsc(s) {
  return String(s == null ? '' : s).replace(/[&<>"']/g, function(c) {
    return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
  });
}

/* ─── data ──────────────────────────────────────────────────── */

async function vocabLoad() {
  var d = await (await fetch(VOCAB_API + '/pipeline/ops')).json();
  vocabOps = (d.ops || []).slice().sort(function(a, b) {
    return a.bucket === b.bucket ? a.name.localeCompare(b.name)
                                 : a.bucket.localeCompare(b.bucket);
  });
  try {
    var r = await fetch(VOCAB_API + '/pipeline/vocab-stats');
    vocabStats = r.ok ? await r.json() : null;
  } catch (e) {
    vocabStats = null;   // older container, or the logs are unreadable
  }
}

function vocabStatFor(name) {
  return (vocabStats && vocabStats.ops && vocabStats.ops[name]) || null;
}

/* ─── formatting ────────────────────────────────────────────── */

function vocabDuration(ms) {
  if (ms == null) return '—';
  if (ms < 1000) return ms + ' ms';
  var s = ms / 1000;
  if (s < 90) return (s < 10 ? s.toFixed(1) : Math.round(s)) + ' s';
  return Math.round(s / 60) + ' min';
}

function vocabWhen(iso) {
  if (!iso) return '—';
  var d = new Date(iso);
  if (isNaN(d)) return '—';
  var months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
  return d.getDate() + ' ' + months[d.getMonth()];
}

function vocabMoney(o) {
  /* An absent field is NOT "free": an older container has no cost field at all,
     and printing "free" there would assert something the page cannot know. */
  if (o.cost == null) return '<span style="opacity:.3" title="not known">—</span>';
  if (o.cost === 'paid') return '<span style="color:var(--c-warn,#eb4)">paid</span>';
  if (o.cost === 'mixed') return '<span style="color:var(--c-warn,#eb4)">partly</span>';
  return '<span style="opacity:.55">free</span>';
}

function vocabEffect(o) {
  if (o.effect == null) return '<span style="opacity:.3" title="not known">—</span>';
  if (o.effect === 'outward') return '<span style="color:#e66" title="leaves the house">⚠ outward</span>';
  if (o.effect === 'writes') return '<span style="opacity:.7" title="writes to a store">writes</span>';
  return '<span style="opacity:.3">—</span>';
}

/* ─── filtering ─────────────────────────────────────────────── */

function vocabVisible() {
  var q = vocabSearch.trim().toLowerCase();
  return vocabOps.filter(function(o) {
    if (vocabFilters.length) {
      var passes = vocabFilters.every(function(id) {
        var f = VOCAB_FILTERS.find(function(x) { return x.id === id; });
        return f ? f.test(o) : true;
      });
      if (!passes) return false;
    }
    if (!q) return true;
    return (o.name + ' ' + (o.plain || '') + ' ' + (o.summary || '') + ' ' +
            (o.service || '') + ' ' + o.bucket).toLowerCase().indexOf(q) !== -1;
  });
}

/* ─── render ────────────────────────────────────────────────── */

function vocabRender() {
  var el = document.getElementById('wiki-list');
  if (!el) return;
  var rows = vocabVisible();

  var chips = VOCAB_FILTERS.map(function(f) {
    var on = vocabFilters.indexOf(f.id) !== -1;
    return '<button class="tool-btn ' + (on ? 'tool-btn-primary' : 'tool-btn-secondary') +
           '" data-vf="' + f.id + '">' + _vEsc(f.label) + '</button>';
  }).join('');

  /* ALL is not a filter but the absence of them: it is highlighted exactly when
     nothing is filtered, and clicking it clears filters AND the search box. */
  var allOn = !vocabFilters.length && !vocabSearch;
  var h =
    '<div style="display:flex;gap:6px;flex-wrap:wrap;align-items:center;margin-bottom:10px">' +
      '<button class="tool-btn ' + (allOn ? 'tool-btn-primary' : 'tool-btn-secondary') +
        '" data-vf="__all">ALL</button>' +
      '<span style="opacity:.3">|</span>' + chips +
      '<span style="margin-left:auto;font-size:12px;opacity:.7" id="vocab-count">' +
        rows.length + ' of ' + vocabOps.length + '</span>' +
    '</div>';

  if (vocabStats && vocabStats.rate) {
    h += '<div style="font-size:11px;opacity:.5;margin-bottom:8px">Amounts in euros · ' +
         _vEsc(vocabStats.rate.note) + ' · measured over ' +
         vocabStats.scanned_runs + ' runs, window ' + vocabStats.window_days + ' days</div>';
  } else {
    h += '<div style="font-size:11px;color:var(--c-warn,#eb4);margin-bottom:8px">' +
         'Measured values (duration, last run, spend) are missing — the stats endpoint ' +
         'is not answering. A column showing “—” means not known, not “nothing”.</div>';
  }

  h += '<table class="vocab-table" style="width:100%;border-collapse:collapse;font-size:13px">' +
       '<thead><tr style="text-align:left;opacity:.6;font-size:11px">' +
         '<th style="padding:4px 6px">OP</th>' +
         '<th style="padding:4px 6px">WHAT IT DOES</th>' +
         '<th style="padding:4px 6px">IN → OUT</th>' +
         '<th style="padding:4px 6px">RUNS ON</th>' +
         '<th style="padding:4px 6px">MONEY</th>' +
         '<th style="padding:4px 6px">TYPICAL TIME</th>' +
         '<th style="padding:4px 6px">EFFECT</th>' +
         '<th style="padding:4px 6px">LAST OK</th>' +
       '</tr></thead><tbody>';

  rows.forEach(function(o) {
    var st = vocabStatFor(o.name);
    var open = !!vocabOpen[o.name];
    h += '<tr data-vrow="' + _vEsc(o.name) + '" style="cursor:pointer;border-top:1px solid var(--brd,#333)">' +
      '<td style="padding:6px"><code>' + _vEsc(o.name) + '</code></td>' +
      '<td style="padding:6px">' + _vEsc(o.plain || o.summary) + '</td>' +
      '<td style="padding:6px;white-space:nowrap;opacity:.75">' +
        _vEsc(o.input_type) + ' → ' + _vEsc(o.output_type) + '</td>' +
      '<td style="padding:6px;white-space:nowrap">' + _vEsc(o.runs_on || '—') + '</td>' +
      '<td style="padding:6px;white-space:nowrap">' + vocabMoney(o) + '</td>' +
      '<td style="padding:6px;white-space:nowrap;opacity:.75">' +
        vocabDuration(st && st.median_ms) + '</td>' +
      '<td style="padding:6px;white-space:nowrap">' + vocabEffect(o) + '</td>' +
      '<td style="padding:6px;white-space:nowrap;opacity:.6">' +
        vocabWhen(st && st.last_ok) + '</td>' +
    '</tr>';
    if (open) h += vocabDetailRow(o, st);
  });

  h += '</tbody></table>';
  if (!rows.length) {
    h += '<div style="padding:16px;opacity:.6">No op matches these filters. ' +
         'ALL brings the whole list back.</div>';
  }
  el.innerHTML = h;

  el.querySelectorAll('[data-vf]').forEach(function(b) {
    b.addEventListener('click', function() { vocabToggleFilter(b.dataset.vf); });
  });
  el.querySelectorAll('[data-vrow]').forEach(function(tr) {
    tr.addEventListener('click', function() {
      var n = tr.dataset.vrow;
      vocabOpen[n] = !vocabOpen[n];
      vocabRender();
    });
  });
}

function vocabDetailRow(o, st) {
  var parts = [];
  parts.push('<div style="opacity:.85;margin-bottom:8px">' + _vEsc(o.summary) + '</div>');

  var facts = [];
  if (o.service) facts.push('<b>Service:</b> ' + _vEsc(o.service));
  if (o.cost_note) facts.push('<b>Price:</b> ' + _vEsc(o.cost_note));
  if (st && st.spend_eur) facts.push('<b>Actually spent (30 days):</b> ' +
      String(st.spend_eur.toFixed(2)).replace('.', ',') + ' €');
  if (st && st.runs) facts.push('<b>Runs:</b> ' + st.runs +
      (st.failed ? ' (' + st.failed + ' failed)' : ''));
  if (st && st.stores && st.stores.length)
    facts.push('<b>Lands in:</b> ' + st.stores.map(function(s){ return 'asset://' + _vEsc(s); }).join(', '));
  if (st && st.used_by && st.used_by.length)
    facts.push('<b>Used by:</b> ' + st.used_by.map(_vEsc).join(', '));
  if (o.requires && o.requires.length)
    facts.push('<b>Needs:</b> ' + o.requires.map(_vEsc).join(' · '));
  if (facts.length) parts.push('<div style="margin-bottom:8px">' + facts.join('<br>') + '</div>');

  if (o.caveats && o.caveats.length) {
    parts.push('<div style="margin-bottom:8px"><b>Worth knowing</b><ul style="margin:4px 0 0 16px">' +
      o.caveats.map(function(c) { return '<li>' + _vEsc(c) + '</li>'; }).join('') + '</ul></div>');
  }

  if (o.params && o.params.length) {
    parts.push('<table style="width:100%;border-collapse:collapse;font-size:12px;margin-bottom:8px">' +
      '<tr style="opacity:.6;text-align:left"><th style="padding:2px 6px">Parameter</th>' +
      '<th style="padding:2px 6px">Type</th><th style="padding:2px 6px">Required</th>' +
      '<th style="padding:2px 6px">Default</th><th style="padding:2px 6px">Description</th></tr>' +
      o.params.map(function(p) {
        return '<tr><td style="padding:2px 6px"><code>' + _vEsc(p.name) + '</code></td>' +
               '<td style="padding:2px 6px">' + _vEsc(p.type) + '</td>' +
               '<td style="padding:2px 6px">' + (p.required ? 'yes' : '') + '</td>' +
               '<td style="padding:2px 6px">' + (p.default == null ? '' : '<code>' + _vEsc(p.default) + '</code>') + '</td>' +
               '<td style="padding:2px 6px;opacity:.8">' + _vEsc(p.desc || '') + '</td></tr>';
      }).join('') + '</table>');
  }

  parts.push('<div style="font-size:12px;opacity:.7"><b>Minimal example</b><pre style="margin:4px 0;padding:8px;' +
    'background:var(--bg-2,#1a1a1a);overflow-x:auto">' + _vEsc(vocabExample(o)) + '</pre></div>');

  return '<tr><td colspan="8" style="padding:12px 16px;background:var(--bg-2,#161616)">' +
         parts.join('') + '</td></tr>';
}

/* A spec snippet that can be pasted straight into a flow. */
function vocabExample(o) {
  var cfg = { id: o.default_id };
  if (o.consumes === 'none') cfg['in'] = 'none';
  (o.params || []).forEach(function(p) {
    if (p.required) cfg[p.name] = p.default != null ? p.default : '…';
  });
  var step = {}; step[o.name] = cfg;
  return JSON.stringify(step, null, 2);
}

function vocabToggleFilter(id) {
  if (id === '__all') {            // ALL = no filter at all, and clears the search
    vocabFilters = [];
    vocabSearch = '';
    var s = document.getElementById('wiki-search');
    if (s) s.value = '';
  } else {
    var i = vocabFilters.indexOf(id);
    if (i === -1) vocabFilters.push(id); else vocabFilters.splice(i, 1);
  }
  vocabRender();
}

/* Called by wiki.js when the VOCABULARY tab is opened or its search box changes. */
async function vocabShow() {
  var el = document.getElementById('wiki-list');
  if (el && !vocabOps.length) el.innerHTML = '<div class="flw-note">Loading vocabulary…</div>';
  if (!vocabOps.length) {
    try {
      await vocabLoad();
    } catch (e) {
      if (el) el.innerHTML = '<div class="flw-err" style="padding:12px">Vocabulary not reachable:<br>' +
        _vEsc(e.message) + '</div>';
      return;
    }
  }
  vocabRender();
}

function vocabOnSearch(value) {
  vocabSearch = value || '';
  vocabRender();
}
