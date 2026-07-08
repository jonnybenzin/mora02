/* /flow tool — the flow-authoring surface.
 *
 * `/flow`         → picker of the library (GET /pipeline/flows)
 * `/flow <name>`  → loads that flow (GET /pipeline/flow/<name>) and renders it as a
 *                   vertical, collapsible block-stack, with param forms driven by the
 *                   live vocabulary (GET /pipeline/ops). Run → POST /pipeline/run-spec.
 *
 * The block-stack is the graphical twin of a pipeline spec: linear steps top→bottom,
 * each op a collapsible block (basics + a "detailed settings" sub-collapse for the
 * advanced params), fan-in shown as "← step" dropdowns. Reuses Pilot design tokens. */

var FLOW_API = (typeof LLM_API_BASE !== 'undefined') ? LLM_API_BASE : 'http://mora02.local:8096';
var _fbOpsCache = null;

function _fbEsc(s){ return String(s == null ? '' : s).replace(/[&<>"]/g, function(c){ return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]; }); }
// fold German umlauts + strip non-alnum, for lenient `/flow tanzbär`→"tanzbaer-clip" matching
function _fbNorm(s){ return String(s).toLowerCase().replace(/ä/g,'ae').replace(/ö/g,'oe').replace(/ü/g,'ue').replace(/ß/g,'ss').replace(/[^a-z0-9]/g,''); }
function _fbIsRef(v){ return v && typeof v === 'object' && 'from' in v; }
function _fbIsArg(v){ return v && typeof v === 'object' && 'arg' in v; }
var _FB_CHEV = '<svg class="fb-chev" viewBox="0 0 16 16" width="11" height="11"><path fill="currentColor" d="M6 4l4 4-4 4z"/></svg>';

async function _fbOps(){
  if (_fbOpsCache) return _fbOpsCache;
  var d = await (await fetch(FLOW_API + '/pipeline/ops')).json();
  _fbOpsCache = {};
  (d.ops || []).forEach(function(o){ _fbOpsCache[o.name] = o; });
  return _fbOpsCache;
}

// entry point — called by renderToolWidget with the text after "/flow"
async function initFlowBuilder(args){
  var wraps = document.querySelectorAll('[data-fb-wrap]');
  var el = wraps[wraps.length - 1];
  if (!el) return;
  args = (args || '').trim();
  el.innerHTML = '<div class="fb-note" style="padding:10px">Lade Flow-Library…</div>';
  try {
    var flows = ((await (await fetch(FLOW_API + '/pipeline/flows')).json()).flows) || [];
    if (!args){ _fbPicker(el, flows); return; }
    var q = _fbNorm(args);
    var m = flows.filter(function(f){ return _fbNorm(f.name).indexOf(q) >= 0 || _fbNorm(f.file).indexOf(q) >= 0; });
    if (m.length === 1) await _fbStack(el, m[0].name);
    else if (m.length === 0) _fbPicker(el, flows, 'Kein Flow für „' + _fbEsc(args) + '". Verfügbar:');
    else _fbPicker(el, m, 'Mehrere Treffer für „' + _fbEsc(args) + '":');
  } catch(e){
    el.innerHTML = '<div style="color:#e77;padding:10px">Flow-Library nicht erreichbar: ' + _fbEsc(e.message) + '</div>';
  }
}

function _fbPicker(el, flows, note){
  var h = '<p class="fb-title">Flow-Library</p>';
  if (note) h += '<p class="fb-note" style="margin:0 0 10px">' + note + '</p>';
  if (!flows.length){
    h += '<p class="fb-note">Noch keine Flows in <code>pipelines/specs/</code>. Leg einen an, dann erscheint er hier.</p>';
  } else {
    h += '<div class="fb-pick">';
    flows.forEach(function(f){
      h += '<div class="fb-card" data-fb-flow="' + _fbEsc(f.name) + '">' +
             '<div class="fb-card-name">' + _fbEsc(f.name) + '</div>' +
             (f.description ? '<div class="fb-card-desc">' + _fbEsc(f.description) + '</div>' : '') +
             '<div class="fb-card-meta">' + f.steps + ' Schritte</div></div>';
    });
    h += '</div>';
  }
  el.innerHTML = h;
}

async function _fbStack(el, name){
  el.innerHTML = '<div class="fb-note" style="padding:10px">Lade Flow „' + _fbEsc(name) + '"…</div>';
  var spec, ops;
  try {
    var resp = await fetch(FLOW_API + '/pipeline/flow/' + encodeURIComponent(name));
    spec = await resp.json();
    if (!resp.ok) throw new Error(spec.detail || ('HTTP ' + resp.status));
    ops = await _fbOps();
  } catch(e){
    el.innerHTML = '<div style="color:#e77;padding:10px">Laden fehlgeschlagen: ' + _fbEsc(e.message) + '</div>';
    return;
  }
  el.dataset.fbName = spec.name || name;

  var steps = (spec.steps || []).map(function(step){
    var op = Object.keys(step)[0];
    var v = step[op];
    var isGate = (op === 'gate' || op === 'review');
    var cfg = (v && typeof v === 'object' && !Array.isArray(v)) ? v : {};
    var prompt = isGate ? (typeof v === 'string' ? v : (cfg.prompt || '')) : '';
    return { op: op, id: (cfg.id || (op.indexOf('.') >= 0 ? op.split('.')[0] : op)), cfg: cfg, isGate: isGate, prompt: prompt };
  });
  var stepIds = steps.map(function(s){ return s.id; });

  // collect args (variable inputs)
  var args = {};
  steps.forEach(function(s){ Object.keys(s.cfg).forEach(function(k){ var v = s.cfg[k]; if (_fbIsArg(v)) args[v.arg] = (v.default || ''); }); });

  var h = '<p class="fb-title">Flow · ' + _fbEsc(el.dataset.fbName) + '</p>';

  if (Object.keys(args).length){
    h += '<div class="fb-inputs"><div class="fb-inputs-h">Inputs</div>';
    Object.keys(args).forEach(function(k){
      h += '<div class="fb-field"><label>' + _fbEsc(k) + '</label><input class="fb-in" data-fb-arg="' + _fbEsc(k) + '" value="' + _fbEsc(args[k]) + '"></div>';
    });
    h += '</div>';
  }

  steps.forEach(function(s, i){
    if (s.isGate){
      if (i > 0) h += '<div class="fb-connector"></div>';
      h += '<div class="fb-block fb-gate" data-fb-block>' +
           '<div class="fb-head" data-fb-head>' + _FB_CHEV +
           '<span class="fb-op">⏸ ' + _fbEsc(s.op) + '</span>' +
           '<span class="fb-summary">' + _fbEsc(s.prompt) + '</span>' +
           '<span class="fb-badge gate">HITL</span></div>' +
           '<div class="fb-body"><div class="fb-io">' + _fbEsc(s.prompt) + '</div>' +
           '<div class="fb-note" style="margin-top:6px">Mensch-Freigabe — die Pipeline pausiert hier, bis jemand in der Inbox entscheidet.</div></div></div>';
      return;
    }
    var def = ops[s.op] || { params: [], output_type: null, status: 'wired' };
    var params = def.params || [];
    var planned = (def.status === 'planned') || Object.keys(s.cfg).some(function(k){ var d = _fbParamDef(params, k); return d && d.status === 'planned'; });

    // collapsed summary: first ref/arg, else first literal
    var summ = '';
    var refKey = Object.keys(s.cfg).find(function(k){ return _fbIsRef(s.cfg[k]) || _fbIsArg(s.cfg[k]); });
    if (refKey) summ = refKey + ' ← ' + (_fbIsArg(s.cfg[refKey]) ? 'input:' + s.cfg[refKey].arg : s.cfg[refKey].from);
    else { var litK = Object.keys(s.cfg).find(function(k){ return k !== 'id' && k !== 'in' && typeof s.cfg[k] !== 'object'; }); if (litK) summ = litK + ': ' + String(s.cfg[litK]).slice(0, 26); }

    if (i > 0) h += '<div class="fb-connector"></div>';
    h += '<div class="fb-block' + (planned ? ' planned' : '') + '" data-fb-block>';
    h += '<div class="fb-head" data-fb-head>' + _FB_CHEV +
         '<span class="fb-op">' + _fbEsc(s.op) + '</span><span class="fb-id">#' + _fbEsc(s.id) + '</span>' +
         '<span class="fb-summary">' + _fbEsc(summ) + '</span>';
    if (def.output_type) h += '<span class="fb-badge out">→ ' + _fbEsc(def.output_type) + '</span>';
    if (planned) h += '<span class="fb-badge plan">planned</span>';
    h += '</div><div class="fb-body">';

    // input line
    var inSrc = s.cfg.in, inTxt;
    if (inSrc === 'none') inTxt = '—';
    else if (Array.isArray(inSrc)) inTxt = inSrc.map(function(x){ return '#' + x; }).join(' + ');
    else if (inSrc) inTxt = '#' + inSrc;
    else inTxt = i > 0 ? '#' + steps[i-1].id + ' (Vorgänger)' : '—';
    h += '<div class="fb-io">Input: <b>' + _fbEsc(inTxt) + '</b></div>';

    var basics = params.filter(function(p){ return !p.advanced; });
    var adv = params.filter(function(p){ return p.advanced; });
    h += basics.map(function(p){ return _fbFieldHTML(p, s.cfg[p.name], stepIds.slice(0, i)); }).join('');

    if (adv.length){
      h += '<div class="fb-detail" data-fb-detail><div class="fb-detail-h" data-fb-detail-head>' + _FB_CHEV +
           'Detaillierte Einstellungen (' + adv.length + ')</div><div class="fb-detail-body">' +
           adv.map(function(p){ return _fbFieldHTML(p, s.cfg[p.name], stepIds.slice(0, i)); }).join('') +
           '</div></div>';
    }
    if (def.output_type) h += '<div class="fb-io" style="margin-top:10px">Output: <b>' + _fbEsc(def.output_type) + '</b> → <span class="fb-id">#' + _fbEsc(s.id) + '</span></div>';
    h += '</div></div>';
  });

  var hasPlanned = steps.some(function(s){ var d = ops[s.op]; return d && d.status === 'planned'; });
  h += '<div class="fb-run"><button class="fb-runbtn" data-fb-run>▶ Pipeline starten</button>' +
       '<span class="fb-status" data-fb-status>' + (hasPlanned ? 'enthält planned-Ops → läuft erst nach dem Wiring' : 'startet mit den Inputs oben') + '</span></div>';
  el.innerHTML = h;
}

function _fbParamDef(params, name){ return params.find(function(p){ return p.name === name; }); }

function _fbFieldHTML(p, val, priorIds){
  if (_fbIsRef(val) || _fbIsArg(val)){
    var cur = _fbIsArg(val) ? 'input:' + val.arg : val.from;
    var opts = _fbIsArg(val) ? [cur] : priorIds;
    return '<div class="fb-field"><label>' + _fbEsc(p.name) + ' ←</label><select class="fb-sel" data-fb-ref="' + _fbEsc(p.name) + '">' +
      opts.map(function(o){ return '<option' + (o === cur || o === (val.from) ? ' selected' : '') + '>' + _fbEsc(o) + '</option>'; }).join('') + '</select></div>';
  }
  if (p.type === 'enum' && p.choices){
    return '<div class="fb-field"><label>' + _fbEsc(p.name) + '</label><select class="fb-sel" data-fb-param="' + _fbEsc(p.name) + '">' +
      p.choices.map(function(c){ return '<option' + ((val != null ? val : p.default) === c ? ' selected' : '') + '>' + _fbEsc(c) + '</option>'; }).join('') + '</select></div>';
  }
  var v = (val != null) ? val : (p.default != null ? p.default : '');
  return '<div class="fb-field"><label>' + _fbEsc(p.name) + '</label><input class="fb-in" data-fb-param="' + _fbEsc(p.name) + '" value="' + _fbEsc(v) + '"></div>';
}

async function _fbRun(btn){
  var el = btn.closest('[data-fb-wrap]');
  var status = el.querySelector('[data-fb-status]');
  var args = {};
  el.querySelectorAll('[data-fb-arg]').forEach(function(inp){ args[inp.getAttribute('data-fb-arg')] = inp.value; });
  status.style.color = ''; status.textContent = 'starte…';
  // Route through Pilot's /pipeline/run (not script-runner directly) so a pause at a
  // gate gets filed into the HITL inbox for approval.
  var PILOT = (typeof PILOT_API_BASE !== 'undefined') ? PILOT_API_BASE
            : (typeof API_BASE !== 'undefined' ? API_BASE : 'http://mora02.local:8098');
  try {
    var resp = await fetch(PILOT + '/pipeline/run', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: el.dataset.fbName, args: args, title: el.dataset.fbName })
    });
    var data = await resp.json();
    if (!resp.ok) { status.style.color = '#e77'; status.textContent = 'Fehler: ' + (data.error || data.detail || ('HTTP ' + resp.status)); return; }
    var res = data.result || {};
    if (res.is_paused) {
      status.style.color = '#eb4';
      status.textContent = '⏸ pausiert am Gate — Freigabe in der INBOX (links im Menü).';
    } else if (res.ok === false || res.status === 'error') {
      status.style.color = '#e77';
      status.textContent = 'Fehler: ' + ((res.error && (res.error.message || res.error)) || res.status || 'siehe Run-Log');
    } else {
      status.style.color = '#8ec';
      status.textContent = '✓ fertig (' + (res.status || 'ok') + ')';
    }
  } catch(e){ status.style.color = '#e77'; status.textContent = 'Fehler: ' + e.message; }
}

// one delegated listener for all /flow widgets (script loads once)
document.addEventListener('click', function(e){
  var card = e.target.closest('[data-fb-flow]');
  if (card){ var w = card.closest('[data-fb-wrap]'); if (w) _fbStack(w, card.getAttribute('data-fb-flow')); return; }
  var run = e.target.closest('[data-fb-run]');
  if (run){ _fbRun(run); return; }
  var dh = e.target.closest('[data-fb-detail-head]');
  if (dh){ dh.closest('[data-fb-detail]').classList.toggle('open'); return; }
  var head = e.target.closest('[data-fb-head]');
  if (head){ head.closest('[data-fb-block]').classList.toggle('open'); return; }
});
