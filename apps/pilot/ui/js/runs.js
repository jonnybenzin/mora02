/* RUNS view — a persistent, live window on pipeline runs (independent of the chat).
 * Reads the run logs via script-runner (GET /pipeline/runs, /pipeline/run/{id}) and
 * renders each run as a step block-stack with per-step status + media previews.
 * Polls while a run is still active so progress updates live. */

var RUNS_API = (typeof LLM_API_BASE !== 'undefined') ? LLM_API_BASE : 'http://mora02.local:8096';
var _runsPoll = null;
var _runsLastCount = -1, _runsStable = 0;

function _runEsc(s){ return String(s == null ? '' : s).replace(/[&<>"]/g, function(c){ return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]; }); }

function _runsStopPoll(){ if (_runsPoll){ clearInterval(_runsPoll); _runsPoll = null; } }

async function initRuns(){
  _runsStopPoll();
  await _runsList();
}

async function _runsList(){
  _runsStopPoll();
  var el = document.getElementById('runs-list');
  if (!el) return;
  if (!el.innerHTML) el.innerHTML = '<div class="run-note">Lade Läufe…</div>';
  var runs;
  try { runs = ((await (await fetch(RUNS_API + '/pipeline/runs')).json()).runs) || []; }
  catch(e){ el.innerHTML = '<div class="run-err">Runs nicht erreichbar: ' + _runEsc(e.message) + '</div>'; return; }
  if (!runs.length){ el.innerHTML = '<div class="run-note">Noch keine Läufe. Starte einen mit <code>/flow &lt;name&gt;</code>.</div>'; return; }
  el.innerHTML = runs.map(function(r){
    var badge = r.failed ? '<span class="run-badge fail">Fehler</span>'
              : (r.active ? '<span class="run-badge live">läuft</span>' : '<span class="run-badge done">fertig</span>');
    var subj = (r.args && r.args.subject) ? ' · „' + _runEsc(r.args.subject) + '"' : '';
    return '<div class="run-card" data-run="' + _runEsc(r.run_id) + '"><div class="run-card-h">' +
           '<span class="run-name">' + _runEsc(r.pipeline) + '</span>' + badge + '</div>' +
           '<div class="run-card-meta">' + r.steps_done + ' Schritte · zuletzt ' + _runEsc(r.last_op || '—') + subj + '</div></div>';
  }).join('');
}

async function _runsShow(runId, isPoll){
  var el = document.getElementById('runs-list');
  if (!el){ _runsStopPoll(); return; }
  var d;
  try { d = await (await fetch(RUNS_API + '/pipeline/run/' + encodeURIComponent(runId))).json(); }
  catch(e){ el.innerHTML = '<div class="run-err">' + _runEsc(e.message) + '</div>'; return; }
  var steps = d.steps || [];

  // liveness: stop polling once the step count has been stable for a few ticks
  if (isPoll){
    if (steps.length === _runsLastCount){ _runsStable++; } else { _runsStable = 0; }
    _runsLastCount = steps.length;
    var lastOk = steps.length && steps[steps.length - 1].status === 'ok';
    var lastFail = steps.length && steps[steps.length - 1].status === 'failed';
    if (_runsStable >= 3 && (lastFail || lastOk)) _runsStopPoll();
    // don't re-render if nothing changed (keeps media playback intact)
    if (steps.length === el.dataset.renderedCount * 1 && !lastFail) return;
  }

  var subj = (d.args && d.args.subject) ? ' · „' + _runEsc(d.args.subject) + '"' : '';
  var h = '<div class="run-back" data-run-back>← alle Läufe</div>';
  h += '<div class="run-detail-title">' + _runEsc(d.pipeline || runId) + subj + '</div>';
  steps.forEach(function(s, i){
    var icon = s.status === 'ok' ? '✅' : (s.status === 'failed' ? '❌' : '<span class="run-spin">⏳</span>');
    if (i > 0) h += '<div class="run-conn"></div>';
    h += '<div class="run-block' + (s.status === 'failed' ? ' fail' : '') + '">';
    h += '<div class="run-block-h">' + icon + ' <span class="run-op">' + _runEsc(s.op) + '</span>' +
         '<span class="run-id">#' + _runEsc(s.step_id) + '</span>' +
         (s.out_type ? '<span class="run-badge type">' + _runEsc(s.out_type) + '</span>' : '') + '</div>';
    var body = '';
    if (s.status === 'failed' && s.error) body = '<div class="run-err-line">' + _runEsc(s.error) + '</div>';
    else if (s.url && s.out_type === 'image') body = '<img class="run-media" src="' + _runEsc(s.url) + '">';
    else if (s.url && s.out_type === 'video') body = '<video class="run-media" src="' + _runEsc(s.url) + '" controls preload="metadata"></video>';
    else if (s.url && s.out_type === 'audio') body = '<audio src="' + _runEsc(s.url) + '" controls style="width:100%;margin-top:8px"></audio>';
    else if (typeof s.out === 'string' && s.out && s.out.indexOf('asset://') !== 0) body = '<div class="run-out-text">' + _runEsc(s.out.slice(0, 2000)) + '</div>';
    if (body) h += '<div class="run-body">' + body + '</div>';
    h += '</div>';
  });
  el.innerHTML = h;
  el.dataset.renderedCount = steps.length;
  el.dataset.viewingRun = runId;

  // start polling for live progress (first open only)
  if (!isPoll){
    _runsStopPoll(); _runsLastCount = -1; _runsStable = 0;
    _runsPoll = setInterval(function(){
      if (el.dataset.viewingRun === runId && document.getElementById('runs-list') === el) _runsShow(runId, true);
      else _runsStopPoll();
    }, 3000);
  }
}

// delegated clicks for the runs page
document.addEventListener('click', function(e){
  var back = e.target.closest('[data-run-back]');
  if (back){ _runsStopPoll(); var el = document.getElementById('runs-list'); if (el){ el.dataset.viewingRun = ''; el.innerHTML = ''; } _runsList(); return; }
  var card = e.target.closest('[data-run]');
  if (card && document.getElementById('runs-list')){ _runsShow(card.getAttribute('data-run'), false); return; }
});
