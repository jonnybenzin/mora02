/* FLOWS page — the from-scratch flow builder.
 *
 * Left column: the live vocabulary (GET /pipeline/ops), grouped by bucket. An op
 * whose io contract does not fit the current end of the stack is greyed out WITH
 * the reason — the contract teaches instead of just refusing.
 * Right column: the flow library (GET /pipeline/flows), or one flow as a linear
 * step stack that can be edited and saved (POST /pipeline/flow/<name>).
 *
 * A step folds open into its parameters, driven by the vocabulary: plain params
 * first, the ones flagged "advanced" behind a sub-collapse. Any param can be a
 * literal, a reference to an EARLIER step (the run bucket holds every step's
 * output for the whole run, so it may reach back arbitrarily far), or a run input.
 *
 * Every string a person sees here is English — house rule for the whole Pilot UI.
 */

var FLOWS_API = (typeof LLM_API_BASE !== 'undefined') ? LLM_API_BASE : 'http://mora02.local:8098/sr';

var _flOpsCache = null;
var _flState = { name: null, spec: null, dirty: false };
// Which steps are folded open. Kept out of the spec on purpose - it is UI
// state and must never end up in the saved file.
var _flOpenSteps = {};
// Where the next block lands. null = at the end; otherwise the index it takes.
// Gates are the reason this exists: a human checkpoint usually belongs BETWEEN
// two steps, not after the last one.
var _flInsertAt = null;

var FL_BUCKETS = [
  ['source', 'Sources'], ['image', 'Image'], ['video', 'Video'],
  ['blender', '3D text'], ['media', 'Media finish'], ['audio', 'Audio'],
  ['llm', 'LLM local'], ['cloud', 'LLM cloud'], ['db', 'Database'],
  ['data', 'Values'],
  ['web', 'Web & stock'], ['publish', 'Publish'], ['delivery', 'Delivery']
];
var FL_TYPES = { image: 'image', video: 'video', audio: 'audio', text: 'text', any: 'any' };
var FL_CHEV = '<svg class="flw-chev" viewBox="0 0 16 16" width="9" height="9"><path fill="currentColor" d="M6 4l4 4-4 4z"/></svg>';
var FL_NAME_RE = /^[a-z0-9][a-z0-9-]{1,63}$/;

function _flEsc(s){ return String(s == null ? '' : s).replace(/[&<>"]/g, function(c){ return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]; }); }
function _flIsRef(v){ return v && typeof v === 'object' && 'from' in v; }
function _flIsArg(v){ return v && typeof v === 'object' && 'arg' in v; }
function _flTy(t){ return FL_TYPES[t] || t; }

// Fold umlauts, drop everything a file name and a URL cannot carry.
function _flSlug(s){
  return String(s || '').toLowerCase()
    .replace(/ä/g, 'ae').replace(/ö/g, 'oe').replace(/ü/g, 'ue').replace(/ß/g, 'ss')
    .replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 64);
}
function _flIo(op){
  var inp = (op.consumes === 'none') ? '—'
          : _flTy(op.input_type) + (op.consumes === 'many' ? ' (several)' : '');
  return inp + ' → ' + _flTy(op.output_type);
}

async function _flOps(){
  if (_flOpsCache) return _flOpsCache;
  var d = await (await fetch(FLOWS_API + '/pipeline/ops')).json();
  _flOpsCache = { byName: {}, all: (d.ops || []) };
  _flOpsCache.all.forEach(function(o){ _flOpsCache.byName[o.name] = o; });
  return _flOpsCache;
}

// ---- spec shape ----------------------------------------------------------
// A step is a single-key object: the key is the op name, or "gate"/"review".
function _flStepShape(raw){
  var key = Object.keys(raw)[0];
  var val = raw[key];
  if (key === 'gate' || key === 'review'){
    return { kind: key, prompt: (typeof val === 'string') ? val : (val && val.prompt) || '' };
  }
  return { kind: 'op', op: key, params: (val && typeof val === 'object') ? val : {} };
}
function _flSteps(){ return (_flState.spec && _flState.spec.steps) || []; }

// The value travelling on the wire INTO position `index` — the output type of the
// last op step before it. Gates pass the wire through untouched.
function _flWireBefore(index){
  var ops = (_flOpsCache || {}).byName || {}, wire = null, steps = _flSteps();
  for (var i = 0; i < index && i < steps.length; i++){
    var s = _flStepShape(steps[i]);
    if (s.kind === 'op' && ops[s.op]) wire = ops[s.op].output_type;
  }
  return wire;
}

// Can this op be appended at the end of the stack, given what lies on the wire?
function _flCanAppend(op, wire){
  if (op.consumes === 'none' || op.consumes_optional) return { ok: true };
  if (!wire) return { ok: false, why: 'needs an input — there is no step before it' };
  if (op.input_type === 'any' || wire === 'any' || wire === op.input_type) return { ok: true };
  return { ok: false, why: 'needs ' + _flTy(op.input_type) + ', but the wire carries ' + _flTy(wire) };
}

// ---- entry point ---------------------------------------------------------
async function initFlows(){
  var pal = document.getElementById('fl-palette');
  var main = document.getElementById('fl-main');
  if (!pal || !main) return;
  _flState = { name: null, spec: null, dirty: false };

  document.querySelectorAll('[data-fl-act]').forEach(function(b){
    b.addEventListener('click', function(){
      if (b.dataset.flAct === 'library'){
        if (_flState.dirty && !confirm('Discard unsaved changes?')) return;
        _flLibrary();
      }
      if (b.dataset.flAct === 'new') _flNew();
    });
  });

  main.innerHTML = '<div class="flw-note">Loading vocabulary…</div>';
  try { await _flRenderPalette(pal); }
  catch (e){ pal.innerHTML = '<div class="flw-err" style="padding:12px">Vocabulary unreachable:<br>' + _flEsc(e.message) + '</div>'; }
  _flLibrary();
}

// ---- palette -------------------------------------------------------------
async function _flRenderPalette(el){
  var ops = await _flOps();
  var byBucket = {};
  ops.all.forEach(function(o){ (byBucket[o.bucket] = byBucket[o.bucket] || []).push(o); });

  var order = FL_BUCKETS.filter(function(b){ return byBucket[b[0]]; });
  Object.keys(byBucket).forEach(function(b){
    if (!FL_BUCKETS.some(function(k){ return k[0] === b; })) order.push([b, b]);
  });

  // Gates are NOT ops — the spec parser handles "gate"/"review" itself, so they
  // never appear in /pipeline/ops. They still belong in the palette: a human
  // checkpoint is a block you place like any other.
  var h = '<div class="flw-grp open"><div class="flw-grp-h">' + FL_CHEV +
            '<span>Human</span><span class="flw-grp-n">2</span></div><div class="flw-grp-body">' +
          '<div class="flw-op" data-fl-gate="gate">' +
            '<div class="flw-op-n"><span class="flw-dot wired"></span>Approval</div>' +
            '<div class="flw-op-d">Stops and asks a human before going on.</div>' +
            '<div class="flw-op-io">passes through whatever is on the wire</div></div>' +
          '<div class="flw-op" data-fl-gate="review">' +
            '<div class="flw-op-n"><span class="flw-dot wired"></span>Review</div>' +
            '<div class="flw-op-d">Sends the previous step\'s result to a human (Signal), then asks.</div>' +
            '<div class="flw-op-io">passes through whatever is on the wire</div></div>' +
          '</div></div>';

  order.forEach(function(pair){
    var list = byBucket[pair[0]];
    h += '<div class="flw-grp"><div class="flw-grp-h">' + FL_CHEV + '<span>' + _flEsc(pair[1]) + '</span>' +
           '<span class="flw-grp-n">' + list.length + '</span></div><div class="flw-grp-body">';
    list.forEach(function(o){
      var planned = o.status !== 'wired';
      h += '<div class="flw-op' + (planned ? ' planned' : '') + '" data-fl-op="' + _flEsc(o.name) + '">' +
             '<div class="flw-op-n"><span class="flw-dot ' + (planned ? 'planned' : 'wired') + '"></span>' + _flEsc(o.name) + '</div>' +
             (o.plain ? '<div class="flw-op-d">' + _flEsc(o.plain) + '</div>' : '') +
             '<div class="flw-op-io">' + _flEsc(_flIo(o)) + '</div>' +
             '<div class="flw-op-why" hidden></div>' +
           '</div>';
    });
    h += '</div></div>';
  });
  el.innerHTML = h;

  el.querySelectorAll('.flw-grp-h').forEach(function(hd){
    hd.addEventListener('click', function(){ hd.parentElement.classList.toggle('open'); });
  });
  el.querySelectorAll('.flw-op').forEach(function(row){
    row.addEventListener('click', function(){
      if (row.classList.contains('disabled')) return;
      if (row.dataset.flGate) _flAddGate(row.dataset.flGate);
      else _flAddOp(row.dataset.flOp);
    });
  });
  _flUpdatePalette();
}

// Grey out what cannot dock onto the current end of the stack, with the reason.
function _flUpdatePalette(){
  if (!_flOpsCache) return;
  var editing = !!_flState.spec;
  var wire = _flWireBefore(_flInsertIndex());
  document.querySelectorAll('#fl-palette .flw-op').forEach(function(row){
    // A gate imposes no type condition — it passes the wire through untouched.
    if (row.dataset.flGate) return;
    var op = _flOpsCache.byName[row.dataset.flOp];
    var why = row.querySelector('.flw-op-why');
    if (!op || !editing){ row.classList.remove('disabled'); if (why) why.hidden = true; return; }
    var v = _flCanAppend(op, wire);
    row.classList.toggle('disabled', !v.ok);
    if (why){ why.hidden = v.ok; why.textContent = v.ok ? '' : v.why; }
    row.title = v.ok ? (op.summary || '') : v.why;
  });
}

// ---- library -------------------------------------------------------------
async function _flLibrary(){
  var main = document.getElementById('fl-main');
  _flState = { name: null, spec: null, dirty: false };
  _flUpdatePalette();
  main.innerHTML = '<div class="flw-note">Loading library…</div>';
  var flows;
  try { flows = ((await (await fetch(FLOWS_API + '/pipeline/flows')).json()).flows) || []; }
  catch (e){ main.innerHTML = '<div class="flw-err">Library unreachable: ' + _flEsc(e.message) + '</div>'; return; }

  if (!flows.length){
    main.innerHTML = '<div class="flw-note">No flows saved yet. "+ New flow" creates the first one.</div>';
    return;
  }
  var h = '<div class="flw-lib">';
  flows.forEach(function(f){
    h += '<div class="flw-card" data-fl-open="' + _flEsc(f.name) + '">' +
           '<div class="flw-card-n">' + _flEsc(f.name) + '</div>' +
           (f.description ? '<div class="flw-card-d">' + _flEsc(f.description) + '</div>' : '') +
           '<div class="flw-card-f">' +
             (f.tags || []).map(function(t){ return '<span class="flw-tag">' + _flEsc(t) + '</span>'; }).join('') +
             '<span class="flw-card-m">' + f.steps + ' steps</span></div></div>';
  });
  main.innerHTML = h + '</div>';
  main.querySelectorAll('[data-fl-open]').forEach(function(c){
    c.addEventListener('click', function(){ _flOpen(c.dataset.flOpen); });
  });
}

function _flNew(){
  _flState = { name: null, spec: { name: '', description: '', tags: [], steps: [] }, dirty: false };
  _flRenderFlow();
}

async function _flOpen(name){
  var main = document.getElementById('fl-main');
  main.innerHTML = '<div class="flw-note">Loading "' + _flEsc(name) + '"…</div>';
  try {
    var resp = await fetch(FLOWS_API + '/pipeline/flow/' + encodeURIComponent(name));
    var spec = await resp.json();
    if (!resp.ok) throw new Error(spec.detail || ('HTTP ' + resp.status));
    await _flOps();
    _flState = { name: name, spec: spec, dirty: false };
    _flRenderFlow();
  } catch (e){
    main.innerHTML = '<div class="flw-err">Loading failed: ' + _flEsc(e.message) + '</div>';
  }
}

// ---- editing -------------------------------------------------------------
function _flIdsInUse(skip){
  var used = [];
  _flSteps().forEach(function(raw, i){
    if (i === skip) return;
    var s = _flStepShape(raw);
    if (s.kind === 'op') used.push(s.params.id || (_flOpsCache.byName[s.op] || {}).default_id || s.op.split('.')[0]);
  });
  return used;
}
// Every inserted step gets an explicit id: a later step can only reference what
// has a name, and duplicate defaults would be refused by the spec parser.
function _flMakeId(base, used){
  var id = base, n = 2;
  while (used.indexOf(id) >= 0) id = base + (n++);
  return id;
}
function _flTouch(){ _flState.dirty = true; _flRenderFlow(); }

// Mark unsaved WITHOUT a re-render: text fields must keep focus while typing,
// so the badge is placed into the existing header instead of redrawing it.
function _flMarkDirty(){
  _flState.dirty = true;
  var head = document.querySelector('.flw-head-n');
  if (head && !head.querySelector('.flw-dirty')){
    var s = document.createElement('span');
    s.className = 'flw-dirty';
    s.textContent = ' • unsaved';
    head.appendChild(s);
  }
}

function _flInsertIndex(){
  var n = _flSteps().length;
  return (_flInsertAt == null || _flInsertAt > n || _flInsertAt < 0) ? n : _flInsertAt;
}
function _flInsertStep(step){
  var at = _flInsertIndex();
  _flSteps().splice(at, 0, step);
  // Shift the fold-open flags of everything below the new step, open it, and
  // move the insertion point past it so several blocks can be added in a row.
  for (var k = _flSteps().length - 1; k > at; k--) _flOpenSteps[k] = _flOpenSteps[k - 1];
  _flOpenSteps[at] = true;
  _flInsertAt = at + 1;
  _flTouch();
}
function _flAddOp(opName){
  if (!_flState.spec) _flNew();
  var op = _flOpsCache.byName[opName] || {};
  var id = _flMakeId(op.default_id || opName.split('.')[0], _flIdsInUse(-1));
  var step = {}; step[opName] = { id: id };
  _flInsertStep(step);
}
function _flAddGate(kind){
  if (!_flState.spec) _flNew();
  var step = {};
  step[kind] = { prompt: (kind === 'gate')
    ? 'Approve?'
    : 'Check the result (look at your phone)?' };
  _flInsertStep(step);
}
function _flMove(i, dir){
  var st = _flSteps(), j = i + dir;
  if (j < 0 || j >= st.length) return;
  var tmp = st[i]; st[i] = st[j]; st[j] = tmp;
  var open = _flOpenSteps[i]; _flOpenSteps[i] = _flOpenSteps[j]; _flOpenSteps[j] = open;
  _flTouch();
}
function _flDelete(i){
  var s = _flStepShape(_flSteps()[i]);
  var label = s.kind === 'op' ? s.op : s.kind;
  if (!confirm('Delete step ' + (i + 1) + ' ("' + label + '")?')) return;
  _flSteps().splice(i, 1);
  for (var k = i; k < _flSteps().length; k++) _flOpenSteps[k] = _flOpenSteps[k + 1];
  delete _flOpenSteps[_flSteps().length];
  _flTouch();
}
function _flSetId(i, value){
  var raw = _flSteps()[i], key = Object.keys(raw)[0];
  var v = _flSlug(value);
  if (!v) return;
  if (_flIdsInUse(i).indexOf(v) >= 0){
    alert('The id "' + v + '" is already taken.');
    _flRenderFlow();
    return;
  }
  raw[key].id = v;
  _flState.dirty = true;
  _flRenderFlow();
}

// ---- save ----------------------------------------------------------------
async function _flSave(){
  var spec = _flState.spec;
  var name = _flSlug(spec.name || '');
  // Re-query every time: a successful save re-renders the stack, which replaces
  // the hint element — a reference captured up front would write into a detached node.
  function say(msg, bad){
    var el = document.getElementById('fl-savehint');
    if (el){ el.textContent = msg; el.className = 'flw-hint' + (bad ? ' bad' : ''); }
  }

  if (!FL_NAME_RE.test(name)){ say('Name: 2–64 characters, lowercase letters, digits, hyphens.', true); return; }
  if (!spec.steps.length){ say('A flow needs at least one step.', true); return; }
  spec.name = name;

  async function post(overwrite){
    return await fetch(FLOWS_API + '/pipeline/flow/' + encodeURIComponent(name) + (overwrite ? '?overwrite=true' : ''), {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(spec)
    });
  }
  say('Saving…');
  try {
    var r = await post(_flState.name === name);
    if (r.status === 409){
      if (!confirm('A flow "' + name + '" already exists. Overwrite?')){ say(''); return; }
      r = await post(true);
    }
    var j = await r.json();
    if (!r.ok){ say('Refused: ' + (j.detail || ('HTTP ' + r.status)), true); return; }
    _flState.name = name;
    _flState.dirty = false;
    _flRenderFlow();
    say('Saved: ' + j.file + ' (' + j.steps + ' steps)' + (j.replaced ? ', replaced' : ''));
  } catch (e){ say('Error: ' + e.message, true); }
}

// ---- render one flow -----------------------------------------------------
function _flRenderFlow(){
  var main = document.getElementById('fl-main');
  var spec = _flState.spec || { steps: [] };
  var ops = (_flOpsCache || {}).byName || {};
  var steps = spec.steps || [];

  var h = '<div class="flw-head">' +
            '<div class="flw-head-n">' + _flEsc(spec.name || 'New flow') +
              (_flState.dirty ? ' <span class="flw-dirty">• unsaved</span>' : '') + '</div>' +
            // Shared Pilot form components (css/tools.css): the label follows the
            // input because .fl-label floats via the "~" sibling selector, and the
            // blank placeholder is what :not(:placeholder-shown) keys off.
            '<div class="fl-grid">' +
              '<div class="fl-field">' +
                '<input class="fl-input" id="fl-f-name" value="' + _flEsc(spec.name || '') + '" placeholder=" ">' +
                '<label class="fl-label">Name</label></div>' +
              '<div class="fl-field">' +
                '<input class="fl-input" id="fl-f-desc" value="' + _flEsc(spec.description || '') + '" placeholder=" ">' +
                '<label class="fl-label">Description</label></div>' +
              '<div class="fl-field">' +
                '<input class="fl-input" id="fl-f-tags" value="' + _flEsc((spec.tags || []).join(', ')) + '" placeholder=" ">' +
                '<label class="fl-label">Tags (comma-separated)</label></div>' +
            '</div></div>';

  h += '<div class="flw-bar">' +
         '<button class="tool-btn tool-btn-secondary" data-fl-add="gate">+ Approval</button>' +
         '<button class="tool-btn tool-btn-secondary" data-fl-add="review">+ Review</button>' +
         '<span class="flw-sp"></span>' +
         '<span class="flw-hint" id="fl-savehint"></span>' +
         (_flState.name ? '<button class="tool-btn tool-btn-secondary tool-btn-danger" data-fl-delflow="1">Delete</button>' : '') +
         '<button class="tool-btn tool-btn-secondary" data-fl-run="1">Run</button>' +
         '<button class="tool-btn tool-btn-primary" data-fl-save="1">Save</button>' +
       '</div><div id="fl-runpanel"></div>';

  if (!steps.length){
    h += '<div class="flw-note">No steps yet. Click a vocabulary entry on the left to insert the first one — ' +
         'greyed-out entries do not fit what is currently on the wire.</div>';
  }

  steps.forEach(function(raw, i){
    var s = _flStepShape(raw);
    var tools = '<span class="flw-tools">' +
      '<button class="flw-t" data-fl-up="' + i + '"' + (i === 0 ? ' disabled' : '') + ' title="move up">↑</button>' +
      '<button class="flw-t" data-fl-down="' + i + '"' + (i === steps.length - 1 ? ' disabled' : '') + ' title="move down">↓</button>' +
      '<button class="flw-t del" data-fl-del="' + i + '" title="delete">×</button></span>';

    h += _flInsHtml(i);
    if (s.kind !== 'op'){
      h += '<div class="flw-step gate' + (_flOpenSteps[i] ? ' open' : '') + '">' +
             '<div class="flw-step-h" data-fl-step="' + i + '">' +
             '<span class="flw-num">' + (i + 1) + '</span>' + FL_CHEV +
             '<span class="flw-badge gate">' + (s.kind === 'gate' ? 'Approval' : 'Review') + '</span>' +
             '<span class="flw-step-s" data-fl-gsum="' + i + '">' + _flEsc(s.prompt) + '</span>' + tools +
           '</div>' +
           '<div class="flw-step-body">' + _flGateBody(i, s) + '</div></div>';
      return;
    }
    var op = ops[s.op] || {};
    var planned = op.status && op.status !== 'wired';
    var id = s.params.id || op.default_id || s.op.split('.')[0];
    var lits = [], refs = [];
    Object.keys(s.params).forEach(function(k){
      if (k === 'id') return;
      var v = s.params[k];
      if (_flIsRef(v)) refs.push({ txt: k + ' ← ' + v.from, live: true });
      else if (_flIsArg(v)) refs.push({ txt: k + ' ← input "' + v.arg + '"', live: true });
      else if (k === 'in') refs.push(v === 'none'
        ? { txt: 'no input', live: false }
        : { txt: 'input ← ' + (Array.isArray(v) ? v.join(', ') : v), live: true });
      else lits.push(k + '=' + v);
    });
    h += '<div class="flw-step' + (planned ? ' planned' : '') + (_flOpenSteps[i] ? ' open' : '') +
           '"><div class="flw-step-h" data-fl-step="' + i + '">' +
           '<span class="flw-num">' + (i + 1) + '</span>' + FL_CHEV +
           '<span class="flw-step-op">' + _flEsc(s.op) + '</span>' +
           '<input class="flw-idin" data-fl-id="' + i + '" value="' + _flEsc(id) + '" title="Step id — later steps refer to it">' +
           (planned ? '<span class="flw-badge plan">planned</span>' : '') +
           '<span class="flw-step-s">' + _flEsc(lits.join('  ')) + '</span>' + tools +
         '</div>' +
         '<div class="flw-step-body">' + _flParamsHtml(i, op, s.params) + '</div>' +
         (refs.length ? '<div class="flw-ref">' + refs.map(function(r){
            return r.live ? '<b>' + _flEsc(r.txt) + '</b>'
                          : '<span class="flw-none">' + _flEsc(r.txt) + '</span>';
          }).join(' · ') + '</div>' : '') +
         '</div>';
  });

  if (steps.length) h += _flInsHtml(steps.length);
  main.innerHTML = h;
  _flWire(main);
  _flUpdatePalette();
}

function _flWire(main){
  var spec = _flState.spec;
  main.querySelectorAll('[data-fl-add]').forEach(function(b){
    b.addEventListener('click', function(){ _flAddGate(b.dataset.flAdd); });
  });
  main.querySelectorAll('[data-fl-up]').forEach(function(b){
    b.addEventListener('click', function(){ _flMove(+b.dataset.flUp, -1); });
  });
  main.querySelectorAll('[data-fl-down]').forEach(function(b){
    b.addEventListener('click', function(){ _flMove(+b.dataset.flDown, 1); });
  });
  main.querySelectorAll('[data-fl-del]').forEach(function(b){
    b.addEventListener('click', function(){ _flDelete(+b.dataset.flDel); });
  });
  main.querySelectorAll('[data-fl-id]').forEach(function(inp){
    inp.addEventListener('change', function(){ _flSetId(+inp.dataset.flId, inp.value); });
  });
  var sv = main.querySelector('[data-fl-save]');
  if (sv) sv.addEventListener('click', _flSave);

  // Metadata fields write straight into the spec; no re-render while typing.
  var n = main.querySelector('#fl-f-name');
  if (n) n.addEventListener('input', function(){ spec.name = n.value; _flMarkDirty(); });
  var d = main.querySelector('#fl-f-desc');
  if (d) d.addEventListener('input', function(){ spec.description = d.value; _flMarkDirty(); });
  var g = main.querySelector('#fl-f-tags');
  if (g) g.addEventListener('input', function(){
    spec.tags = g.value.split(',').map(function(x){ return x.trim(); }).filter(Boolean);
    _flMarkDirty();
  });

  // --- step bodies (increment 3b) ---
  main.querySelectorAll('[data-fl-step]').forEach(function(hd){
    hd.addEventListener('click', function(ev){
      // The header also carries the id field and the tool buttons — those keep
      // their own behaviour instead of folding the step open.
      var tag = (ev.target.tagName || '').toLowerCase();
      if (tag === 'input' || tag === 'button' || ev.target.closest('button')) return;
      var i = +hd.dataset.flStep;
      _flOpenSteps[i] = !_flOpenSteps[i];
      hd.parentElement.classList.toggle('open', !!_flOpenSteps[i]);
    });
  });
  main.querySelectorAll('.flw-detail-h').forEach(function(hd){
    hd.addEventListener('click', function(){ hd.parentElement.classList.toggle('open'); });
  });
  main.querySelectorAll('[data-fl-pmode]').forEach(function(sel){
    sel.addEventListener('change', function(){
      var parts = sel.dataset.flPmode.split('|');
      _flSetParamMode(+parts[0], parts[1], sel.value);
    });
  });
  main.querySelectorAll('[data-fl-pval]').forEach(function(el){
    var parts = el.dataset.flPval.split('|');
    // Selects re-render (the summary line changes); text fields must not, or
    // they would lose focus on every keystroke.
    var evt = (el.tagName.toLowerCase() === 'select') ? 'change' : 'input';
    el.addEventListener(evt, function(){
      _flSetParamValue(+parts[0], parts[1], el.value, evt === 'change');
    });
  });
  main.querySelectorAll('[data-fl-in]').forEach(function(sel){
    sel.addEventListener('change', function(){ _flSetIn(+sel.dataset.flIn, sel); });
  });
  var dl = main.querySelector('[data-fl-delflow]');
  if (dl) dl.addEventListener('click', _flDeleteFlow);
  var rn = main.querySelector('[data-fl-run]');
  if (rn) rn.addEventListener('click', _flRunClicked);

  main.querySelectorAll('[data-fl-ins]').forEach(function(d){
    d.addEventListener('click', function(){
      var at = +d.dataset.flIns;
      _flInsertAt = (_flInsertIndex() === at) ? null : at;   // clicking again cancels
      _flRenderFlow();
    });
  });
  main.querySelectorAll('[data-fl-gkind]').forEach(function(sel){
    sel.addEventListener('change', function(){ _flSetGateKind(+sel.dataset.flGkind, sel.value); });
  });
  main.querySelectorAll('[data-fl-gk]').forEach(function(inp){
    var parts = inp.dataset.flGk.split('|');
    inp.addEventListener('input', function(){
      _flSetGate(+parts[0], parts[1], inp.value);
      if (parts[1] === 'prompt'){
        // Keep the collapsed summary honest while typing, without a re-render
        // that would take the focus out of the field.
        var sum = main.querySelector('[data-fl-gsum="' + parts[0] + '"]');
        if (sum) sum.textContent = inp.value;
      }
    });
  });
}

// ---- gates ---------------------------------------------------------------

// A gate/review step is either the shorthand string or a mapping. Editing always
// normalises to the mapping, which is what carries id, delivery target and a
// custom response schema.
function _flSetGate(i, key, value){
  var raw = _flSteps()[i], kind = Object.keys(raw)[0];
  var cur = raw[kind];
  if (typeof cur === 'string') cur = { prompt: cur };
  if (value === '') delete cur[key]; else cur[key] = value;
  if (cur.prompt == null) cur.prompt = '';
  raw[kind] = cur;
  _flMarkDirty();
}

// Approval and review differ only in delivery, so switching between them is a
// key swap that keeps the question. Going back to a plain gate drops the
// delivery params — a gate has nowhere to send to.
function _flSetGateKind(i, kind){
  var raw = _flSteps()[i], cur = Object.keys(raw)[0];
  if (cur === kind) return;
  var cfg = (typeof raw[cur] === 'string') ? { prompt: raw[cur] } : (raw[cur] || {});
  if (kind === 'gate'){ delete cfg.target; delete cfg.channel; delete cfg.message; }
  delete raw[cur];
  raw[kind] = cfg;
  _flState.dirty = true;
  _flOpenSteps[i] = true;
  _flRenderFlow();
}

function _flGateBody(i, s){
  var raw = _flSteps()[i], kind = Object.keys(raw)[0];
  var cfg = (typeof raw[kind] === 'string') ? { prompt: raw[kind] } : (raw[kind] || {});
  var h = '<div class="flw-p"><div class="flw-p-h"><span class="flw-p-n">Kind</span></div>' +
            '<select class="flw-pin" data-fl-gkind="' + i + '">' +
              _flOptions([{ v: 'gate', l: 'Approval — only stops and asks' },
                          { v: 'review', l: 'Review — delivers first (Signal), then asks' }], kind) +
            '</select>' +
            '<div class="flw-p-d">Both stop the run and are decided in the INBOX. ' +
              'Review additionally sends out the result of the step before.</div></div>' +
          '<div class="flw-p"><div class="flw-p-h"><span class="flw-p-n">Question to the human</span></div>' +
            '<input class="flw-pin" data-fl-gk="' + i + '|prompt" value="' + _flEsc(cfg.prompt || '') + '">' +
            '<div class="flw-p-d">' + (kind === 'gate'
              ? 'The run stops here until someone decides in the INBOX. The value on the wire continues unchanged.'
              : 'The result of the step before is delivered, then the question is asked. Without a target it goes to the default from the configuration.') +
            '</div></div>';
  if (kind === 'review'){
    h += '<div class="flw-p"><div class="flw-p-h"><span class="flw-p-n">Target</span></div>' +
           '<input class="flw-pin" data-fl-gk="' + i + '|target" value="' + _flEsc(cfg.target || '') + '" placeholder="(default from the configuration)">' +
           '<div class="flw-p-d">Recipient of the delivery.</div></div>' +
         '<div class="flw-p"><div class="flw-p-h"><span class="flw-p-n">Channel</span></div>' +
           '<input class="flw-pin" data-fl-gk="' + i + '|channel" value="' + _flEsc(cfg.channel || '') + '" placeholder="(default)">' +
           '<div class="flw-p-d">Delivery route, e.g. signal.</div></div>' +
         '<div class="flw-p"><div class="flw-p-h"><span class="flw-p-n">Caption</span></div>' +
           '<input class="flw-pin" data-fl-gk="' + i + '|message" value="' + _flEsc(cfg.message || '') + '" placeholder="(the question above)">' +
           '<div class="flw-p-d">Text next to the medium; empty means: the same question.</div></div>';
  }
  return h;
}

// The insertion point — clicking a divider decides where the next block lands.
function _flInsHtml(at){
  var active = (_flInsertIndex() === at);
  return '<div class="flw-ins' + (active ? ' active' : '') + '" data-fl-ins="' + at + '">' +
           '<span>' + (active ? 'insert here' : '+') + '</span></div>';
}

// ---- running -------------------------------------------------------------

// Every {"arg": "..."} in the spec is a value the run has to be given. The
// optional "default" beside it is authoring metadata (the compiler ignores it),
// which is exactly what belongs in the field as a prefill.
function _flCollectArgs(){
  var seen = {}, out = [];
  _flSteps().forEach(function(raw){
    var s = _flStepShape(raw);
    if (s.kind !== 'op') return;
    Object.keys(s.params).forEach(function(k){
      var v = s.params[k];
      if (_flIsArg(v) && v.arg && !seen[v.arg]){
        seen[v.arg] = true;
        out.push({ name: v.arg, def: v.default == null ? '' : String(v.default) });
      }
    });
  });
  return out;
}

function _flRunClicked(){
  if (!_flState.spec || !_flSteps().length){
    _flRunSay('A flow needs at least one step.', true);
    return;
  }
  if (_flState.dirty &&
      !confirm('There are unsaved changes. The run takes the state from the editor — continue?')) return;

  var args = _flCollectArgs();
  if (!args.length){ _flRun({}); return; }

  var panel = document.getElementById('fl-runpanel');
  panel.innerHTML =
    '<div class="flw-head" style="padding:13px 15px">' +
      '<div class="flw-p-n" style="margin-bottom:6px">Run inputs</div>' +
      args.map(function(a){
        return '<div class="flw-p"><div class="flw-p-h"><span class="flw-p-n">' + _flEsc(a.name) + '</span></div>' +
               '<input class="flw-pin" data-fl-arg="' + _flEsc(a.name) + '" value="' + _flEsc(a.def) + '"></div>';
      }).join('') +
      '<div class="flw-bar"><span class="flw-hint" id="fl-runhint"></span>' +
        '<button class="tool-btn tool-btn-secondary" data-fl-runcancel="1">Cancel</button>' +
        '<button class="tool-btn tool-btn-primary" data-fl-rungo="1">Go</button></div>' +
    '</div>';
  panel.querySelector('[data-fl-runcancel]').addEventListener('click', function(){ panel.innerHTML = ''; });
  panel.querySelector('[data-fl-rungo]').addEventListener('click', function(){
    var vals = {};
    panel.querySelectorAll('[data-fl-arg]').forEach(function(inp){ vals[inp.dataset.flArg] = inp.value; });
    _flRun(vals);
  });
}

function _flRunSay(msg, bad){
  var el = document.getElementById('fl-runhint') || document.getElementById('fl-savehint');
  if (el){ el.textContent = msg; el.className = 'flw-hint' + (bad ? ' bad' : ''); }
}

async function _flRun(args){
  _flRunSay('Running… (media steps take minutes)');
  var body = { spec: _flState.spec, title: _flState.spec.name || 'Flow' };
  if (args && Object.keys(args).length) body.args = args;
  // Through Pilot, NOT straight to script-runner: only this route files a pause
  // at a gate into the HITL inbox. Calling run-spec directly would strand the
  // run with a resume token nobody holds.
  var pilot = (typeof API_BASE !== 'undefined') ? API_BASE : 'http://mora02.local:8098';
  try {
    var r = await fetch(pilot + '/pipeline/run', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body)
    });
    var d = await r.json();
    if (!r.ok){ _flRunSay('Refused: ' + (d.error || d.detail || ('HTTP ' + r.status)), true); return; }
    var j = d.result || {};
    if (j.is_paused){
      _flRunSay(d.inbox_item
        ? 'Paused at an approval — the item is in the INBOX.'
        : 'Paused at an approval, but could not be filed into the INBOX.', !d.inbox_item);
    } else if (j.ok === false || j.status === 'error'){
      _flRunSay('Failed: ' + ((j.error && (j.error.message || JSON.stringify(j.error))) || j.status || 'see RUNS'), true);
    } else {
      _flRunSay('Completed (' + (j.status || 'done') + '). Details in RUNS.');
    }
  } catch (e){
    _flRunSay('Start failed: ' + e.message, true);
  }
}

// ---- parameters (increment 3b) -------------------------------------------

// Every step id BEFORE index i, with what it produces. The run bucket keeps each
// step's output for the whole run (mora02_core.pipeline.runbucket), so a param
// may reach back arbitrarily far — not just to the previous step.
function _flEarlier(i){
  var out = [], ops = (_flOpsCache || {}).byName || {}, steps = _flSteps();
  for (var k = 0; k < i && k < steps.length; k++){
    var s = _flStepShape(steps[k]);
    if (s.kind !== 'op') continue;
    var op = ops[s.op] || {};
    out.push({ id: s.params.id || op.default_id || s.op.split('.')[0],
               type: op.output_type || 'any', op: s.op });
  }
  return out;
}

function _flParamMode(v){
  if (_flIsRef(v)) return 'from';
  if (_flIsArg(v)) return 'arg';
  return 'value';
}
var FL_MODES = { value: 'value', from: '← step', arg: '← input' };

function _flOptions(list, selected){
  return list.map(function(o){
    var val = (typeof o === 'string') ? o : o.v;
    var lbl = (typeof o === 'string') ? o : o.l;
    return '<option value="' + _flEsc(val) + '"' + (String(selected) === String(val) ? ' selected' : '') +
           '>' + _flEsc(lbl) + '</option>';
  }).join('');
}

function _flParamRow(i, p, value){
  var key = i + '|' + p.name;
  var mode = _flParamMode(value);
  var modes = ['value', 'from', 'arg'].map(function(m){ return { v: m, l: FL_MODES[m] }; });
  var field;

  if (mode === 'from'){
    var earlier = _flEarlier(i);
    // Types are shown, not filtered: the vocabulary declares an asset type per
    // STEP, not per param — so the human judges the fit, the UI just informs.
    field = earlier.length
      ? '<select class="flw-pin ref" data-fl-pval="' + key + '">' +
          _flOptions(earlier.map(function(e){
            return { v: e.id, l: e.id + ' — ' + e.op + ' (' + _flTy(e.type) + ')' };
          }), value.from) + '</select>'
      : '<div class="flw-p-d">No earlier step available.</div>';
  } else if (mode === 'arg'){
    field = '<input class="flw-pin ref" data-fl-pval="' + key + '" value="' + _flEsc(value.arg || '') +
            '" placeholder="name of the run input">';
  } else if (p.choices && p.choices.length){
    field = '<select class="flw-pin" data-fl-pval="' + key + '">' +
              _flOptions([{ v: '', l: '(default: ' + (p.default == null ? '—' : p.default) + ')' }]
                .concat(p.choices), value == null ? '' : value) + '</select>';
  } else if (p.type === 'bool'){
    field = '<select class="flw-pin" data-fl-pval="' + key + '">' +
              _flOptions([{ v: '', l: '(default)' }, { v: 'true', l: 'yes' }, { v: 'false', l: 'no' }],
                value == null ? '' : String(value)) + '</select>';
  } else {
    field = '<input class="flw-pin" data-fl-pval="' + key + '"' +
            (p.type === 'int' ? ' type="number"' : '') +
            ' value="' + _flEsc(value == null ? '' : value) + '"' +
            ' placeholder="' + _flEsc(p.default == null ? '' : 'default: ' + p.default) + '">';
  }

  return '<div class="flw-p"><div class="flw-p-h">' +
           '<span class="flw-p-n">' + _flEsc(p.name) + (p.required ? '<span class="flw-p-req"> *</span>' : '') + '</span>' +
           '<select class="flw-p-mode" data-fl-pmode="' + key + '">' + _flOptions(modes, mode) + '</select>' +
         '</div>' + field +
         (p.desc ? '<div class="flw-p-d">' + _flEsc(p.desc) + '</div>' : '') +
       '</div>';
}

function _flParamsHtml(i, op, params){
  if (!op || !op.params) return '<div class="flw-p-d">This entry is unknown to the vocabulary.</div>';
  var h = '';

  // What feeds this step's stdin. Here the type IS known (op.input_type), so the
  // list really is filtered — unlike the per-param references above.
  if (op.consumes && op.consumes !== 'none'){
    var fit = _flEarlier(i).filter(function(e){
      return op.input_type === 'any' || e.type === 'any' || e.type === op.input_type;
    });
    var cur = params['in'];
    var curStr = Array.isArray(cur) ? cur.join(',') : (cur == null ? '' : String(cur));
    h += '<div class="flw-p flw-instep"><div class="flw-p-h"><span class="flw-p-n">Input</span></div>' +
           '<select class="flw-pin" data-fl-in="' + i + '"' + (op.consumes === 'many' ? ' multiple size="4"' : '') + '>' +
             _flOptions([{ v: '', l: '(previous step)' }, { v: 'none', l: 'no input' }]
               .concat(fit.map(function(e){ return { v: e.id, l: e.id + ' — ' + e.op + ' (' + _flTy(e.type) + ')' }; })),
               curStr) + '</select>' +
           '<div class="flw-p-d">Expects ' + _flEsc(_flTy(op.input_type)) +
             (op.consumes === 'many' ? ' (several selectable)' : '') + '.</div></div>';
  }

  var basics = op.params.filter(function(p){ return !p.advanced; });
  var adv = op.params.filter(function(p){ return p.advanced; });
  basics.forEach(function(p){ h += _flParamRow(i, p, params[p.name]); });
  if (adv.length){
    h += '<div class="flw-detail"><div class="flw-detail-h">' + FL_CHEV +
           '<span>Detailed settings (' + adv.length + ')</span></div><div class="flw-detail-body">';
    adv.forEach(function(p){ h += _flParamRow(i, p, params[p.name]); });
    h += '</div></div>';
  }
  if (!basics.length && !adv.length) h += '<div class="flw-p-d">This entry has no parameters.</div>';
  return h;
}

function _flStepParams(i){
  var raw = _flSteps()[i];
  return raw[Object.keys(raw)[0]];
}

function _flSetParamMode(i, name, mode){
  var params = _flStepParams(i);
  if (mode === 'from'){
    var first = _flEarlier(i)[0];
    params[name] = { from: first ? first.id : '' };
  } else if (mode === 'arg'){
    params[name] = { arg: '' };
  } else {
    delete params[name];
  }
  _flState.dirty = true;
  _flOpenSteps[i] = true;
  _flRenderFlow();
}

function _flSetParamValue(i, name, raw, rerender){
  var params = _flStepParams(i);
  var cur = params[name];
  if (_flIsRef(cur)){ params[name] = { from: raw }; }
  else if (_flIsArg(cur)){ params[name] = { arg: raw }; }
  else if (raw === ''){ delete params[name]; }          // empty falls back to the op default
  else {
    var op = (_flOpsCache.byName[Object.keys(_flSteps()[i])[0]] || {});
    var def = (op.params || []).filter(function(p){ return p.name === name; })[0] || {};
    if (def.type === 'int' && raw !== '' && !isNaN(+raw)) params[name] = +raw;
    else if (def.type === 'bool') params[name] = (raw === 'true');
    else params[name] = raw;
  }
  if (rerender){ _flState.dirty = true; _flOpenSteps[i] = true; _flRenderFlow(); }
  else _flMarkDirty();
}

function _flSetIn(i, sel){
  var params = _flStepParams(i);
  var vals = sel.multiple
    ? Array.prototype.slice.call(sel.selectedOptions).map(function(o){ return o.value; }).filter(Boolean)
    : (sel.value ? [sel.value] : []);
  if (!vals.length) delete params['in'];
  else if (vals.length === 1) params['in'] = vals[0];
  else params['in'] = vals;
  _flState.dirty = true;
  _flOpenSteps[i] = true;
  _flRenderFlow();
}

async function _flDeleteFlow(){
  var name = _flState.name;
  if (!name) return;
  if (!confirm('Delete flow "' + name + '" for good? The file will be removed.')) return;
  try {
    var r = await fetch(FLOWS_API + '/pipeline/flow/' + encodeURIComponent(name), { method: 'DELETE' });
    var j = await r.json();
    if (!r.ok) throw new Error(j.detail || ('HTTP ' + r.status));
    _flLibrary();
  } catch (e){
    var el = document.getElementById('fl-savehint');
    if (el){ el.textContent = 'Delete failed: ' + e.message; el.className = 'flw-hint bad'; }
  }
}
