/* AGENTS page — the agent builder.
 *
 * An agent is a folder: agents/instances/<id>/{agent.json, SOUL.md}. This page
 * edits exactly that and nothing else. Saving writes the folder (PUT /agents/<id>);
 * the gateway only follows when someone presses "Deploy" (POST /agents/deploy),
 * and "Check drift" (GET /agents/drift) shows the difference in between. Two
 * steps on purpose: a form that deploys on every save cannot be used to prepare.
 *
 * What the form is careful about, because each was measured to matter:
 *  - tool rights are the biggest block and never folded away (ADR-029: an agent
 *    without an allow list gets EVERY tool, and that looks like nothing)
 *  - a cloud model is marked "leaves the house" next to its name, not in a tooltip
 *  - limits can be borrowed from another agent (`same_as`), because two agents
 *    meant to be compared must share their numbers by construction, and six
 *    differing values once invalidated a whole day's comparison
 *  - a SOUL may be shared (symlink) — same principle, for the prose
 *  - `_why…` comment blocks in the manifest are carried through untouched;
 *    the form shows how many it is keeping and never renders them as fields
 *
 * Every string a person sees here is English — house rule for the whole Pilot UI.
 */

var AGB_API = (typeof LLM_API_BASE !== 'undefined') ? LLM_API_BASE : 'http://mora02.local:8098/sr';

var _agb = {
  roster: [], models: [], skills: [], tools: [],
  id: null,           // the agent open on the right; null = nothing, '' = new
  isNew: false,
  manifest: null,     // the manifest as edited (comments included)
  soul: '', soulShared: null,
  roots: null,      // GET /agents/roots -- where agents live, and whether one can be made
  files: {},        // TOOLS.md / USER.md / IDENTITY.md as read
  filesEdit: {},    // the ones touched in this session; '' = remove
  dirty: false
};
var AGB_EXTRA_FILES = [
  ['TOOLS.md', 'Tool notes: how THIS agent should use its tools, on top of the tool descriptions.'],
  ['USER.md', 'What THIS agent knows about the person. Without this file, data/agents/USER.md applies — the one shared by all agents.'],
  ['IDENTITY.md', 'Name, role, form of address — in case the SOUL does not say so already.']
];

function _agbEsc(s){ return String(s == null ? '' : s).replace(/[&<>"]/g, function(c){ return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]; }); }
var AGB_ID_RE = /^[a-z0-9][a-z0-9-]{1,63}$/;
var AGB_LIMIT_KEYS = ['page_chars','max_urls','max_queries','snippet_chars','results_per_query','max_pages_total','max_searches_total'];
var AGB_LIMIT_HELP = {
  page_chars: 'characters per page read', max_urls: 'pages per web_read call',
  max_queries: 'queries per web_search call', snippet_chars: 'characters per result snippet',
  results_per_query: 'results per query', max_pages_total: 'pages per turn in total',
  max_searches_total: 'searches per turn in total'
};

async function _agbGet(path){
  var r = await fetch(AGB_API + path);
  var j = await r.json().catch(function(){ return {}; });
  if (!r.ok) throw new Error(j.detail || ('HTTP ' + r.status));
  return j;
}

// ---- entry ---------------------------------------------------------------
async function initAgents(){
  var list = document.getElementById('agb-list');
  var main = document.getElementById('agb-main');
  if (!list || !main) return;
  _agb.id = null; _agb.dirty = false;

  document.querySelectorAll('[data-agb-act]').forEach(function(b){
    b.addEventListener('click', function(){
      if (b.dataset.agbAct === 'new') _agbNew();
      if (b.dataset.agbAct === 'drift') _agbDrift(null);
    });
  });

  main.innerHTML = '<div class="agb-note">Loading building blocks (models from the gateway, skills, tools)…</div>';
  try {
    var res = await Promise.all([
      _agbGet('/agents/roster?include_inactive=true'),
      _agbGet('/agents/skills'),
      _agbGet('/agents/tools'),
      _agbGet('/agents/models').catch(function(e){ return { models: [], error: e.message }; }),
      _agbGet('/agents/roots').catch(function(){ return { can_create: true }; })
    ]);
    _agb.roots = res[4];
    _agb.roster = res[0].agents || [];
    _agb.skills = res[1].skills || [];
    _agb.tools = res[2].tools || [];
    _agb.models = res[3].models || [];
    _agb.modelsError = res[3].error || null;
  } catch (e){
    main.innerHTML = '<div class="agb-err">Agent layer unreachable: ' + _agbEsc(e.message) + '</div>';
    list.innerHTML = '';
    return;
  }
  _agbRenderList();
  main.innerHTML = '<div class="agb-note">Pick an agent on the left, or create a new one at the top right.<br><br>'
    + 'An agent is a folder under <code>data/agents/instances/</code> — part of this installation, not of the repo. '
    + 'The repo ships the methods (skills), the tool list and the gateway\'s reception desk; it ships no agents.<br><br>'
    + 'Save writes the folder; only "Deploy" takes it to the gateway. "Check drift" shows in between what would change.'
    + (_agb.roots && !_agb.roots.can_create ? '<br><br><span style="color:#e88">data/agents is not mounted (MORA02_AGENTS_LOCAL_DIR) — there is no place for agents.</span>' : '') + '</div>';
}

// ---- roster --------------------------------------------------------------
function _agbRenderList(){
  var el = document.getElementById('agb-list');
  if (!el) return;
  var h = '<div class="agb-list-h">Instances<span class="agb-list-n">' + _agb.roster.length + '</span></div>';
  _agb.roster.forEach(function(a){
    var cloud = a.model && a.model.indexOf('llama-local/') !== 0;
    h += '<div class="agb-row' + (a.id === _agb.id ? ' sel' : '') + (a.active ? '' : ' off') + '" data-agb-open="' + _agbEsc(a.id) + '">'
      + '<span class="agb-ico">' + _agbEsc(a.icon || '·') + '</span>'
      + '<div class="agb-row-t"><div class="agb-row-n">' + _agbEsc(a.label || a.id) + '</div>'
      + '<div class="agb-row-m">' + _agbEsc(a.id) + (a.active ? '' : ' · inactive') + '</div></div>'
      + (a.model ? '<span class="agb-pill ' + (cloud ? 'cloud' : 'local') + '">' + (cloud ? 'cloud' : 'local') + '</span>' : '')
      + '</div>';
  });
  el.innerHTML = h;
  el.querySelectorAll('[data-agb-open]').forEach(function(r){
    r.addEventListener('click', function(){ _agbOpen(r.dataset.agbOpen); });
  });
}

async function _agbReloadRoster(){
  try { _agb.roster = (await _agbGet('/agents/roster?include_inactive=true')).agents || []; } catch (e) {}
  _agbRenderList();
  if (typeof loadAgents === 'function') loadAgents(); // the chat's slash list, same source
}

// ---- open / new ----------------------------------------------------------
async function _agbOpen(id){
  if (_agb.dirty && !confirm('Discard unsaved changes?')) return;
  var main = document.getElementById('agb-main');
  main.innerHTML = '<div class="agb-note">Loading ' + _agbEsc(id) + '…</div>';
  try {
    var d = await _agbGet('/agents/' + encodeURIComponent(id) + '/detail');
    _agb.id = id; _agb.isNew = false;
    _agb.manifest = d.manifest || {};
    _agb.soul = d.soul || '';
    _agb.soulShared = d.soul_shared_with || null;
    _agb.files = d.files || {};
    _agb.filesEdit = {};
    _agb.dirty = false;
    _agbRenderList();
    _agbRenderForm();
  } catch (e){
    main.innerHTML = '<div class="agb-err">' + _agbEsc(e.message) + '</div>';
  }
}

function _agbNew(){
  if (_agb.dirty && !confirm('Discard unsaved changes?')) return;
  var local = _agb.models.filter(function(m){ return m.local; })[0];
  _agb.id = ''; _agb.isNew = true;
  _agb.manifest = {
    label: '', icon: '', colour: '#8ab4f8', description: '', opening: '',
    active: true, sort_order: 50,
    // Local by default. The choice to send a question out of the house is made
    // at the moment of asking, never inherited from a form's default.
    model: local ? local.key : '',
    timeout: 600,
    skills: [],
    // The narrowest working list, not an empty one: the gateway refuses a run
    // with no callable tool, so an agent starts with `read` and grows from there.
    tools: { allow: ['read'] }
  };
  _agb.soul = '# Who you are\n\n';
  _agb.soulShared = null;
  _agb.files = {}; _agb.filesEdit = {};
  _agb.dirty = false;
  _agbRenderList();
  _agbRenderForm();
}

// ---- the form ------------------------------------------------------------
function _agbRenderForm(){
  var main = document.getElementById('agb-main');
  var m = _agb.manifest;
  var comments = Object.keys(m).filter(function(k){ return k.charAt(0) === '_'; });
  var h = '';

  // header + identity
  h += '<div class="agb-card"><div class="agb-card-h">Identity'
     + '<span class="agb-hint">' + (comments.length ? comments.length + ' comment block(s) (<code>_why…</code>) are kept' : '') + '</span></div>';
  h += '<div class="agb-head-n" id="agb-headn">' + _agbEsc(m.label || (_agb.isNew ? 'New agent' : _agb.id)) + '<span class="agb-dirty" id="agb-dirty"></span></div>';
  h += '<div class="agb-grid" style="margin-top:10px">';
  h += _agbField('id', 'id', _agb.isNew ? '' : _agb.id, 'Folder name = id. Lowercase letters, digits, hyphens.', { disabled: !_agb.isNew, placeholder: 'e.g. strategy' });
  h += _agbField('label', 'Label', m.label || '', 'Name in the chat and in the list.');
  h += _agbField('icon', 'Icon', m.icon || '', 'One emoji.');
  h += _agbField('colour', 'Colour', m.colour || '', 'Hex, e.g. #a3e635.');
  h += _agbField('sort_order', 'Sort order', m.sort_order != null ? m.sort_order : 100, 'Smaller = further up.', { type: 'number' });
  h += '</div>';
  h += _agbField('description', 'Description', m.description || '', 'Shown in the slash list. For a cloud model, name the price and that the request leaves the house.', { textarea: true });
  h += _agbField('opening', 'Opening', m.opening || '', 'What a bare /<id> without text sends. Leave empty if the agent needs a question.');
  h += '<label class="agb-ck" style="display:inline-flex;margin-top:6px"><input type="checkbox" data-agb-f="active" ' + (m.active !== false ? 'checked' : '') + '><div class="agb-ck-t"><div class="agb-ck-n">active</div><div class="agb-ck-d">Callable in the chat. Inactive = exists, but is not offered.</div></div></label>';
  h += '<label class="agb-ck" style="display:inline-flex;margin-top:6px"><input type="checkbox" data-agb-f="sensitive" ' + (m.sensitive === true ? 'checked' : '') + '><div class="agb-ck-t"><div class="agb-ck-n">sensitive</div><div class="agb-ck-d">Receives data that must not leave the house. Forces a local model — a cloud model is refused on save (ADR-029).</div></div></label>';
  h += '</div>';

  // model + timeout
  h += '<div class="agb-card"><div class="agb-card-h">Model &amp; time</div><div class="agb-grid">';
  h += '<div class="agb-f"><div class="agb-l"><b>Model</b></div><select class="agb-sel" data-agb-f="model">';
  {
    var seen = false;
    var groups = [['local — stays in the house', function(x){ return x.local; }], ['Cloud — the request leaves the house', function(x){ return !x.local; }]];
    groups.forEach(function(g){
      var ms = _agb.models.filter(g[1]);
      if (!ms.length) return;
      h += '<optgroup label="' + _agbEsc(g[0]) + '">';
      ms.forEach(function(x){
        var sel = x.key === m.model; if (sel) seen = true;
        // A local entry is named by what is loaded, not by its gateway id: the id
        // is a port, and showing it here once put "qwen3-14b" under a 27B model.
        var label = x.local ? ('local — ' + (x.loaded || 'llama-server')) : x.key;
        h += '<option value="' + _agbEsc(x.key) + '"' + (sel ? ' selected' : '') + (x.available ? '' : ' disabled') + '>'
           + _agbEsc(label) + (x.context_window ? '  · ' + Math.round(x.context_window / 1024) + 'k' : '') + '</option>';
      });
      h += '</optgroup>';
    });
    if (m.model && !seen) h += '<option value="' + _agbEsc(m.model) + '" selected>' + _agbEsc(m.model) + ' (unknown to the gateway)</option>';
    if (!m.model) h += '<option value="" selected disabled>— choose —</option>';
  }
  h += '</select><div class="agb-hint" id="agb-modelhint"></div>'
     + (_agb.modelsError ? '<div class="agb-hint bad">Model list could not be loaded from the gateway: ' + _agbEsc(_agb.modelsError) + '</div>' : '')
     + '</div>';
  h += _agbField('timeout', 'Timeout (s)', m.timeout != null ? m.timeout : '', 'Per turn. A research turn takes minutes; too small a number looks like a broken agent.', { type: 'number' });
  h += '</div></div>';

  // limits
  var lim = m.limits;
  var mode = !lim ? 'none' : (lim.same_as ? 'same_as' : 'own');
  h += '<div class="agb-card"><div class="agb-card-h">Payload limits<span class="agb-hint">for web_search / web_read</span></div>';
  h += '<div class="agb-grid" style="grid-template-columns:200px 1fr">';
  h += '<div class="agb-f"><div class="agb-l"><b>Source</b></div><select class="agb-sel" data-agb-lmode>'
     + '<option value="none"' + (mode === 'none' ? ' selected' : '') + '>none (server defaults)</option>'
     + '<option value="same_as"' + (mode === 'same_as' ? ' selected' : '') + '>same as another agent</option>'
     + '<option value="own"' + (mode === 'own' ? ' selected' : '') + '>own values</option></select></div>';
  h += '<div class="agb-f" id="agb-limbox"></div></div>';
  h += '<div class="agb-hint" style="margin-top:6px">Two agents you want to compare MUST share the same limits — otherwise the comparison measures the configuration. "Same as another agent" couples them by construction; a copy drifts.</div>';
  h += '</div>';

  // skills
  h += '<div class="agb-card"><div class="agb-card-h">Skills<span class="agb-hint">agents/skills/ — only the description reaches the prompt</span></div><div class="agb-checks">';
  if (!_agb.skills.length) h += '<div class="agb-hint">No skills under agents/skills/.</div>';
  _agb.skills.forEach(function(s){
    var on = (m.skills || []).indexOf(s.name) >= 0;
    h += '<label class="agb-ck' + (on ? ' on' : '') + '"><input type="checkbox" data-agb-skill="' + _agbEsc(s.name) + '"' + (on ? ' checked' : '') + '>'
       + '<div class="agb-ck-t"><div class="agb-ck-n">' + _agbEsc(s.name)
       + '<a class="agb-pill agb-files-tg" data-agb-skfiles="' + _agbEsc(s.name) + '" title="Read the files of this skill">' + s.files + ' file(s) ▸</a></div>'
       + '<div class="agb-ck-d">' + (s.description ? _agbEsc(s.description) : '<span style="color:#e88">no description — gets listed and never used</span>') + '</div></div></label>';
  });
  h += '</div><div id="agb-skfiles"></div></div>';

  // tools — never folded, always the whole list
  var unrestricted = m.tools === 'unrestricted';
  var allow = (m.tools && m.tools.allow) || [];
  h += '<div class="agb-card"><div class="agb-card-h">Tool rights<span class="agb-hint">Allow list. Without a list an agent would get ALL tools — which is why it sits here and not in a submenu.</span></div>';
  if (unrestricted) {
    h += '<div class="agb-hint bad" style="margin-bottom:8px">This agent is set to <code>"tools": "unrestricted"</code> — deliberately and in writing. The form does not change that; whoever wants a list sets it in the file.</div>';
  }
  var mcp = _agb.tools.filter(function(t){ return t.source === 'mcp'; });
  var gw = _agb.tools.filter(function(t){ return t.source !== 'mcp'; });
  var known = {}; _agb.tools.forEach(function(t){ known[t.id] = true; });
  h += '<div class="agb-sub">House tools (MCP, script-runner)</div><div class="agb-checks">' + mcp.map(function(t){ return _agbToolCk(t, allow, unrestricted); }).join('') + '</div>';
  h += '<div class="agb-sub">Gateway tools</div><div class="agb-checks">' + gw.map(function(t){ return _agbToolCk(t, allow, unrestricted); }).join('') + '</div>';
  var unknownAllowed = allow.filter(function(a){ return !known[a]; });
  if (unknownAllowed.length) {
    h += '<div class="agb-sub">In the list, unknown here</div><div class="agb-checks">' + unknownAllowed.map(function(a){
      return _agbToolCk({ id: a, risk: 'act', what: 'Is on the allow list, but neither our MCP server nor agents/tools.json knows it.', source: '?' }, allow, unrestricted);
    }).join('') + '</div>';
  }
  h += '<div class="agb-hint" id="agb-toolhint" style="margin-top:8px"></div></div>';

  // SOUL
  var originals = _agb.roster.filter(function(a){ return a.id !== _agb.id; });
  h += '<div class="agb-card"><div class="agb-card-h">SOUL.md — who the agent is<span class="agb-hint">Prose. Skills say HOW, the SOUL says WHO. Shared = a reference in the manifest to another agent.</span></div>';
  h += '<div class="agb-grid" style="grid-template-columns:200px 1fr;margin-bottom:8px">';
  h += '<div class="agb-f"><div class="agb-l"><b>Source</b></div><select class="agb-sel" data-agb-smode>'
     + '<option value="own"' + (!_agb.soulShared ? ' selected' : '') + '>own file</option>'
     + '<option value="shared"' + (_agb.soulShared ? ' selected' : '') + '>shared with another agent (reference)</option></select></div>';
  h += '<div class="agb-f" id="agb-soulsrc">' + (_agb.soulShared ? _agbSoulShareSelect(originals) : '') + '</div></div>';
  h += '<textarea class="agb-ta" data-agb-soul' + (_agb.soulShared ? ' disabled' : '') + ' spellcheck="false">' + _agbEsc(_agb.soul) + '</textarea>';
  if (_agb.soulShared) h += '<div class="agb-hint">Showing the file of <b>' + _agbEsc(_agb.soulShared) + '</b>. Changing it means changing it there — both agents get it.</div>';
  h += '</div>';

  // the other workspace files -- optional, folded, but present: the rollout
  // renders exactly these, and a file the builder cannot see is a file that
  // gets edited in a terminal and forgotten there.
  h += '<div class="agb-card"><div class="agb-card-h">Other workspace files<span class="agb-hint">optional · leave empty = remove the file</span></div>';
  AGB_EXTRA_FILES.forEach(function(f){
    var name = f[0];
    var cur = (_agb.filesEdit[name] !== undefined) ? _agb.filesEdit[name] : (_agb.files[name] || '');
    var has = cur !== '';
    h += '<details class="agb-det"' + (has ? ' open' : '') + '><summary>' + _agbEsc(name) + (has ? ' <span class="agb-pill local">present</span>' : ' <span class="agb-pill">absent</span>') + '</summary>'
       + '<div class="agb-hint" style="margin:4px 0 6px">' + _agbEsc(f[1]) + '</div>'
       + '<textarea class="agb-ta short" data-agb-xfile="' + _agbEsc(name) + '" spellcheck="false" placeholder="(empty = no file)">' + _agbEsc(cur) + '</textarea></details>';
  });
  h += '</div>';

  // actions
  h += '<div class="agb-bar">'
     + '<button class="tool-btn tool-btn-primary" data-agb-do="save">Save</button>'
     + '<button class="tool-btn tool-btn-secondary" data-agb-do="drift"' + (_agb.isNew ? ' disabled' : '') + '>Check drift</button>'
     + '<button class="tool-btn tool-btn-secondary" data-agb-do="deploy"' + (_agb.isNew ? ' disabled' : '') + '>Deploy</button>'
     + '<button class="tool-btn tool-btn-secondary" data-agb-do="test"' + (_agb.isNew || m.active === false ? ' disabled' : '') + '>Test</button>'
     + '<span class="agb-sp"></span>'
     + (_agb.isNew ? '' : '<button class="tool-btn tool-btn-secondary tool-btn-danger" data-agb-do="delete">Delete</button>')
     + '</div>';
  h += '<div class="agb-hint" id="agb-savehint"></div>';
  h += '<div id="agb-outbox" style="margin-top:10px"></div>';

  main.innerHTML = h;
  _agbRenderLimits(mode);
  _agbModelHint();
  _agbToolHint();
  _agbWire();
}

function _agbField(key, label, value, help, opt){
  opt = opt || {};
  var h = '<div class="agb-f"><div class="agb-l"><b>' + _agbEsc(label) + '</b></div>';
  if (opt.textarea) h += '<textarea class="agb-ta short" data-agb-f="' + key + '" spellcheck="false">' + _agbEsc(value) + '</textarea>';
  else h += '<input class="agb-in" type="' + (opt.type || 'text') + '" data-agb-f="' + key + '" value="' + _agbEsc(value) + '"' + (opt.disabled ? ' disabled' : '') + (opt.placeholder ? ' placeholder="' + _agbEsc(opt.placeholder) + '"' : '') + '>';
  if (help) h += '<div class="agb-hint">' + help + '</div>';
  return h + '</div>';
}

function _agbToolCk(t, allow, unrestricted){
  var on = unrestricted || allow.indexOf(t.id) >= 0;
  var risk = t.risk || 'read';
  var label = { read: 'reads', write: 'writes', act: 'acts' }[risk] || risk;
  return '<label class="agb-ck ' + risk + (on ? ' on' : '') + '"><input type="checkbox" data-agb-tool="' + _agbEsc(t.id) + '"' + (on ? ' checked' : '') + (unrestricted ? ' disabled' : '') + '>'
    + '<div class="agb-ck-t"><div class="agb-ck-n">' + _agbEsc(t.id) + '<span class="agb-risk">' + label + '</span></div>'
    + '<div class="agb-ck-d">' + _agbEsc(t.what || '') + '</div></div></label>';
}

function _agbSoulShareSelect(originals){
  var h = '<div class="agb-l"><b>File of</b></div><select class="agb-sel" data-agb-sshare>';
  if (!originals.length) h += '<option value="">— no other agent —</option>';
  originals.forEach(function(a){
    h += '<option value="' + _agbEsc(a.id) + '"' + (a.id === _agb.soulShared ? ' selected' : '') + '>' + _agbEsc(a.id) + '</option>';
  });
  return h + '</select>';
}

function _agbRenderLimits(mode){
  var box = document.getElementById('agb-limbox');
  if (!box) return;
  var m = _agb.manifest;
  if (mode === 'none'){ box.innerHTML = '<div class="agb-hint" style="margin-top:18px">The server applies its defaults.</div>'; return; }
  if (mode === 'same_as'){
    var others = _agb.roster.filter(function(a){ return a.id !== _agb.id; });
    var cur = (m.limits && m.limits.same_as) || '';
    var h = '<div class="agb-l"><b>Limits of</b></div><select class="agb-sel" data-agb-lsame>';
    others.forEach(function(a){ h += '<option value="' + _agbEsc(a.id) + '"' + (a.id === cur ? ' selected' : '') + '>' + _agbEsc(a.id) + '</option>'; });
    box.innerHTML = h + '</select><div class="agb-hint">The other agent must have values of its own (no chain).</div>';
    box.querySelector('[data-agb-lsame]').addEventListener('change', function(e){ _agb.manifest.limits = { same_as: e.target.value }; _agbMark(); });
    if (!cur && others.length){ _agb.manifest.limits = { same_as: others[0].id }; }
    return;
  }
  var own = (m.limits && !m.limits.same_as) ? m.limits : {};
  var g = '<div class="agb-grid" style="grid-template-columns:repeat(auto-fit,minmax(130px,1fr))">';
  AGB_LIMIT_KEYS.forEach(function(k){
    g += '<div class="agb-f"><div class="agb-l">' + k + '</div><input class="agb-in" type="number" min="1" data-agb-lim="' + k + '" value="' + (own[k] != null ? own[k] : '') + '"><div class="agb-hint">' + AGB_LIMIT_HELP[k] + '</div></div>';
  });
  box.innerHTML = g + '</div>';
  box.querySelectorAll('[data-agb-lim]').forEach(function(inp){
    inp.addEventListener('input', function(){
      var lim = {};
      box.querySelectorAll('[data-agb-lim]').forEach(function(i2){ if (i2.value !== '') lim[i2.dataset.agbLim] = parseInt(i2.value, 10); });
      _agb.manifest.limits = lim; _agbMark();
    });
  });
}

function _agbModelHint(){
  var el = document.getElementById('agb-modelhint');
  if (!el) return;
  var k = _agb.manifest.model || '';
  if (!k){ el.textContent = ''; return; }
  if (k.indexOf('llama-local/') === 0){
    el.className = 'agb-hint ok';
    var lm = _agb.models.filter(function(x){ return x.key === k; })[0];
    el.textContent = 'Local on llama-server' + (lm && lm.loaded ? ', loaded: ' + lm.loaded : '') + '. The request stays in the house.';
  } else {
    el.className = 'agb-hint warn';
    el.textContent = 'Cloud: every request leaves the house and costs money (a research turn on Sonnet ~33 ct). Only for agents that steer nothing.';
  }
}

function _agbToolHint(){
  var el = document.getElementById('agb-toolhint');
  if (!el) return;
  var m = _agb.manifest;
  if (m.tools === 'unrestricted'){ el.className = 'agb-hint bad'; el.textContent = 'Unrestricted.'; return; }
  var allow = (m.tools && m.tools.allow) || [];
  var risky = allow.filter(function(a){ var t = _agb.tools.filter(function(x){ return x.id === a; })[0]; return t && t.risk === 'act'; });
  var cloud = m.model && m.model.indexOf('llama-local/') !== 0;
  if (!allow.length){ el.className = 'agb-hint bad'; el.textContent = 'Empty list: the gateway aborts a run without a callable tool. At least one.'; return; }
  if (allow.indexOf('lobster') >= 0){ el.className = 'agb-hint bad'; el.textContent = 'lobster resolves approvals itself and knows no input gate. For flows, use mora02__flow_run.'; return; }
  if (risky.length && cloud){ el.className = 'agb-hint bad'; el.textContent = 'A cloud model with acting tools (' + risky.join(', ') + ') steers the house from outside. Steering stays local — refused on save.'; return; }
  if (m.sensitive === true && cloud){ el.className = 'agb-hint bad'; el.textContent = 'Marked sensitive, but a cloud model: the data would leave the house. Refused on save.'; return; }
  if (risky.length){ el.className = 'agb-hint warn'; el.textContent = allow.length + ' tool(s), acting: ' + risky.join(', ') + '.'; return; }
  el.className = 'agb-hint ok'; el.textContent = allow.length + ' tool(s), none acts beyond the workspace.';
}

function _agbMark(){
  _agb.dirty = true;
  var d = document.getElementById('agb-dirty'); if (d) d.textContent = '● unsaved';
}

function _agbWire(){
  var main = document.getElementById('agb-main');
  main.querySelectorAll('[data-agb-f]').forEach(function(inp){
    inp.addEventListener('input', function(){
      var k = inp.dataset.agbF;
      if (k === 'id'){ _agb.id = inp.value.trim(); return; }
      if (inp.type === 'checkbox') _agb.manifest[k] = inp.checked;
      else if (inp.type === 'number') _agb.manifest[k] = inp.value === '' ? undefined : parseInt(inp.value, 10);
      else _agb.manifest[k] = inp.value;
      if (_agb.manifest[k] === undefined) delete _agb.manifest[k];
      if (k === 'label'){ var hn = document.getElementById('agb-headn'); if (hn) hn.firstChild.textContent = inp.value || _agb.id || 'New agent'; }
      if (k === 'model'){ _agbModelHint(); _agbToolHint(); }
      _agbMark();
    });
    if (inp.tagName === 'SELECT') inp.addEventListener('change', function(){ _agb.manifest[inp.dataset.agbF] = inp.value; _agbModelHint(); _agbToolHint(); _agbMark(); });
  });
  main.querySelectorAll('[data-agb-skill]').forEach(function(ck){
    ck.addEventListener('change', function(){
      var s = _agb.manifest.skills || [];
      s = s.filter(function(x){ return x !== ck.dataset.agbSkill; });
      if (ck.checked) s.push(ck.dataset.agbSkill);
      _agb.manifest.skills = s; ck.closest('.agb-ck').classList.toggle('on', ck.checked); _agbMark();
    });
  });
  main.querySelectorAll('[data-agb-skfiles]').forEach(function(a){
    a.addEventListener('click', function(e){ e.preventDefault(); e.stopPropagation(); _agbShowSkill(a.dataset.agbSkfiles); });
  });
  main.querySelectorAll('[data-agb-xfile]').forEach(function(ta){
    ta.addEventListener('input', function(){ _agb.filesEdit[ta.dataset.agbXfile] = ta.value; _agbMark(); });
  });
  main.querySelectorAll('[data-agb-tool]').forEach(function(ck){
    ck.addEventListener('change', function(){
      if (_agb.manifest.tools === 'unrestricted') return;
      var a = ((_agb.manifest.tools || {}).allow || []).filter(function(x){ return x !== ck.dataset.agbTool; });
      if (ck.checked) a.push(ck.dataset.agbTool);
      _agb.manifest.tools = { allow: a }; ck.closest('.agb-ck').classList.toggle('on', ck.checked); _agbToolHint(); _agbMark();
    });
  });
  var lmode = main.querySelector('[data-agb-lmode]');
  if (lmode) lmode.addEventListener('change', function(){
    if (lmode.value === 'none') delete _agb.manifest.limits;
    else if (lmode.value === 'same_as') _agb.manifest.limits = { same_as: (_agb.manifest.limits && _agb.manifest.limits.same_as) || '' };
    else if (_agb.manifest.limits && _agb.manifest.limits.same_as) _agb.manifest.limits = {};
    _agbRenderLimits(lmode.value); _agbMark();
  });
  var smode = main.querySelector('[data-agb-smode]');
  var ta = main.querySelector('[data-agb-soul]');
  if (smode) smode.addEventListener('change', function(){
    var src = document.getElementById('agb-soulsrc');
    var originals = _agb.roster.filter(function(a){ return a.id !== _agb.id; });
    if (smode.value === 'shared'){
      _agb.soulShared = _agb.soulShared || (originals[0] && originals[0].id) || null;
      src.innerHTML = _agbSoulShareSelect(originals);
      var sel = src.querySelector('[data-agb-sshare]');
      if (sel) sel.addEventListener('change', function(){ _agb.soulShared = sel.value || null; _agbMark(); });
      ta.disabled = true;
    } else {
      _agb.soulShared = null; src.innerHTML = ''; ta.disabled = false;
    }
    _agbMark();
  });
  var sshare = main.querySelector('[data-agb-sshare]');
  if (sshare) sshare.addEventListener('change', function(){ _agb.soulShared = sshare.value || null; _agbMark(); });
  if (ta) ta.addEventListener('input', function(){ _agb.soul = ta.value; _agbMark(); });

  main.querySelectorAll('[data-agb-do]').forEach(function(b){
    b.addEventListener('click', function(){
      var act = b.dataset.agbDo;
      if (act === 'save') _agbSave();
      if (act === 'drift') _agbDrift(_agb.id);
      if (act === 'deploy') _agbDeploy();
      if (act === 'test') _agbTest();
      if (act === 'delete') _agbDelete();
    });
  });
}

function _agbSay(msg, cls){
  var el = document.getElementById('agb-savehint');
  if (el){ el.textContent = msg; el.className = 'agb-hint' + (cls ? ' ' + cls : ''); }
}

// ---- save ----------------------------------------------------------------
async function _agbSave(){
  var id = (_agb.id || '').trim();
  if (!AGB_ID_RE.test(id)){ _agbSay('id: 2–64 characters, lowercase letters, digits, hyphens.', 'bad'); return; }
  if (_agb.isNew && _agb.roster.some(function(a){ return a.id === id; })){ _agbSay('There already is an agent "' + id + '".', 'bad'); return; }
  var body = { manifest: _agb.manifest };
  if (_agb.soulShared) body.soul_shared_with = _agb.soulShared;
  else body.soul = _agb.soul;
  // Only the files touched in this session travel; '' removes, absent leaves alone.
  if (Object.keys(_agb.filesEdit).length){
    body.files = {};
    Object.keys(_agb.filesEdit).forEach(function(k){ body.files[k] = _agb.filesEdit[k].trim() === '' ? '' : _agb.filesEdit[k]; });
  }
  _agbSay('Saving…');
  try {
    var r = await fetch(AGB_API + '/agents/' + encodeURIComponent(id), {
      method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body)
    });
    var j = await r.json().catch(function(){ return {}; });
    if (!r.ok){ _agbSay('Refused: ' + (j.detail || ('HTTP ' + r.status)), 'bad'); return; }
    _agb.dirty = false; _agb.isNew = false; _agb.id = id;
    _agbSay((j.created ? 'Created: ' : 'Saved: ') + 'data/agents/instances/' + id + '/ — not deployed yet.', 'ok');
    await _agbReloadRoster();
    await _agbOpen(id);
    _agbSay((j.created ? 'Created: ' : 'Saved: ') + 'data/agents/instances/' + id + '/ — checking drift…', 'ok');
    await _agbDrift(id);
  } catch (e){ _agbSay('Error: ' + e.message, 'bad'); }
}

// ---- drift / deploy ------------------------------------------------------
function _agbOut(html){
  var box = document.getElementById('agb-outbox') || document.getElementById('agb-main');
  if (box) box.innerHTML = html;
}

function _agbDriftHtml(res, title){
  var lines = res.drift || [];
  var h = '<div class="agb-card"><div class="agb-card-h">' + _agbEsc(title) + '</div>';
  // Seen and left alone (a hand-made gateway agent): shown dim, and never
  // the reason the two disagree -- "in sync" may stand beside a note.
  var notes = (res.notes || []).map(function(l){ return '<span class="dim">' + _agbEsc(l) + '</span>'; }).join('\n');
  if (res.in_sync && !res.applied){
    return h + '<div class="agb-hint ok">Gateway and folder agree — nothing to do.</div>'
      + (notes ? '<div class="agb-out">' + notes + '</div>' : '') + '</div>';
  }
  h += '<div class="agb-out">';
  if (res.log && res.log.length) h += res.log.map(function(l){ return '<span class="dim">' + _agbEsc(l) + '</span>'; }).join('\n') + '\n\n';
  h += lines.map(function(l){
    var cls = /does not exist|missing|deleted in the roster|stale|no record/.test(l) ? 'ok' : '';
    return '<span class="' + cls + '">' + _agbEsc(l) + '</span>';
  }).join('\n');
  if (notes) h += '\n' + notes;
  if (res.applied){
    h += '\n\n' + (res.ok ? '<span class="ok">Deployed and read back — in sync.</span>' : '<span class="bad">Deployed, but still different afterwards:\n' + _agbEsc((res.left || []).join('\n')) + '</span>');
  }
  return h + '</div></div>';
}

async function _agbDrift(id){
  _agbOut('<div class="agb-note">Comparing folder with the gateway…</div>');
  try {
    var res = await _agbGet('/agents/drift');
    _agbOut(_agbDriftHtml(res, 'Drift — what "Deploy" would change'));
    _agbSay('');
  } catch (e){ _agbOut('<div class="agb-err">Drift check: ' + _agbEsc(e.message) + '</div>'); }
}

async function _agbDeploy(){
  if (_agb.dirty){ _agbSay('Save first, then deploy.', 'bad'); return; }
  _agbOut('<div class="agb-note">Deploying (config patch, workspace files, MCP reload)…</div>');
  try {
    var r = await fetch(AGB_API + '/agents/deploy', { method: 'POST' });
    var j = await r.json().catch(function(){ return {}; });
    if (!r.ok){ _agbOut('<div class="agb-err">Deploy refused: ' + _agbEsc(j.detail || ('HTTP ' + r.status)) + '</div>'); return; }
    _agbOut(_agbDriftHtml(j, j.applied ? 'Deploy' : 'Deploy — nothing to do'));
    if (typeof loadAgents === 'function') loadAgents();
  } catch (e){ _agbOut('<div class="agb-err">Deploy: ' + _agbEsc(e.message) + '</div>'); }
}

// ---- test ----------------------------------------------------------------
async function _agbTest(){
  if (_agb.dirty){ _agbSay('Save (and deploy) first, then test.', 'bad'); return; }
  var q = prompt('Test message to ' + _agb.id + ':', _agb.manifest.opening || 'Who are you, and what can you do for me? Two sentences.');
  if (q == null || !q.trim()) return;
  var cloud = _agb.manifest.model && _agb.manifest.model.indexOf('llama-local/') !== 0;
  if (cloud && !confirm('This agent runs on a cloud model: the test leaves the house and costs money. Continue anyway?')) return;
  var t0 = Date.now();
  _agbOut('<div class="agb-card"><div class="agb-card-h">Test</div><div class="agb-note">The agent is working… (timeout ' + (_agb.manifest.timeout || 180) + ' s)</div></div>');
  try {
    var r = await fetch(AGB_API + '/agent/' + encodeURIComponent(_agb.id) + '/message', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: q, conversation: 'builder-' + Date.now() })
    });
    var j = await r.json().catch(function(){ return {}; });
    if (!r.ok){ _agbOut('<div class="agb-err">The agent did not answer: ' + _agbEsc(j.detail || ('HTTP ' + r.status)) + '\n\nNot deployed yet? Then the gateway does not know it.</div>'); return; }
    var secs = Math.round((Date.now() - t0) / 1000);
    var meta = [];
    if (j.model_real) meta.push('Model: ' + j.model_real + (j.model_declared && j.model_declared !== j.model_real ? ' (declared ' + j.model_declared + ')' : ''));
    meta.push(secs + ' s');
    if (j.tool_calls != null) meta.push(j.tool_calls + ' tool call(s)' + (j.tools_used && j.tools_used.length ? ': ' + j.tools_used.join(', ') : ''));
    if (j.cost_eur_last_call) meta.push('≥ ' + j.cost_eur_last_call.toFixed(3) + ' € (last call)');
    _agbOut('<div class="agb-card"><div class="agb-card-h">Test<span class="agb-hint">' + _agbEsc(q.slice(0, 80)) + '</span></div>'
      + '<div class="agb-answer">' + _agbEsc(j.text || j.answer || JSON.stringify(j).slice(0, 800)) + '</div>'
      + '<div class="agb-meta">' + _agbEsc(meta.join(' · ')) + '</div></div>');
  } catch (e){ _agbOut('<div class="agb-err">Test: ' + _agbEsc(e.message) + '</div>'); }
}

// ---- delete --------------------------------------------------------------
async function _agbDelete(){
  var id = _agb.id;
  if (!confirm('Delete agent "' + id + '"?\n\nThe folder moves to data/agents/instances/.trash/ (recoverable). It disappears from the gateway at the next deploy.')) return;
  try {
    var r = await fetch(AGB_API + '/agents/' + encodeURIComponent(id), { method: 'DELETE' });
    var j = await r.json().catch(function(){ return {}; });
    if (!r.ok){ _agbSay('Refused: ' + (j.detail || ('HTTP ' + r.status)), 'bad'); return; }
    _agb.id = null; _agb.dirty = false;
    await _agbReloadRoster();
    document.getElementById('agb-main').innerHTML = '<div class="agb-note">"' + _agbEsc(id) + '" moved to <code>' + _agbEsc(j.moved_to || '.trash/') + '</code>.<br><br>It still exists in the gateway — "Check drift" shows that, "Deploy" removes it there.</div>'
      + '<div class="agb-bar"><button class="tool-btn tool-btn-secondary" data-agb-do2="drift">Check drift</button><button class="tool-btn tool-btn-primary" data-agb-do2="deploy">Deploy</button></div><div id="agb-outbox"></div>';
    document.querySelectorAll('[data-agb-do2]').forEach(function(b){
      b.addEventListener('click', function(){ if (b.dataset.agbDo2 === 'drift') _agbDrift(null); else _agbDeploy(); });
    });
  } catch (e){ _agbSay('Error: ' + e.message, 'bad'); }
}

// ---- skill files, read-only ----------------------------------------------
// A skill is shared between agents and lives in agents/skills/<name>/. What it
// contains is the part of an agent most worth reading -- the question
// catalogue, the template -- and until this existed it was the only part the
// browser could not show. Reading only: writing skill files is the skill
// editor, a separate decision (three tiers, three homes, one mounted).
var _agbSkillOpen = null;
async function _agbShowSkill(name){
  var box = document.getElementById('agb-skfiles');
  if (!box) return;
  if (_agbSkillOpen === name){ box.innerHTML = ''; _agbSkillOpen = null; return; }
  _agbSkillOpen = name;
  box.innerHTML = '<div class="agb-note">Loading ' + _agbEsc(name) + '…</div>';
  try {
    var d = await _agbGet('/agents/skills/' + encodeURIComponent(name));
    var h = '<div class="agb-skbox"><div class="agb-sub" style="margin-top:4px">' + (d.root === 'local' ? 'data/agents' : 'agents') + '/skills/' + _agbEsc(name) + '/ · used by: ' + (d.used_by && d.used_by.length ? _agbEsc(d.used_by.join(', ')) : '—') + '</div>';
    h += '<div class="agb-skfiles-l">';
    (d.files || []).forEach(function(f, i){
      h += '<a class="agb-skfile' + (i === 0 ? ' sel' : '') + '" data-agb-skf="' + i + '">' + _agbEsc(f.path) + ' <span class="dim">' + Math.round(f.size / 100) / 10 + ' kB</span></a>';
    });
    h += '</div><pre class="agb-out agb-skpre" id="agb-skpre"></pre>'
       + '<div class="agb-hint">Read only. Editing today means: change the file in the repo and deploy — the skill editor is a separate step.</div></div>';
    box.innerHTML = h;
    function show(i){
      var f = d.files[i];
      var pre = document.getElementById('agb-skpre');
      pre.textContent = f.content != null ? f.content : '(' + f.path + ': no text preview, ' + f.size + ' bytes)';
      box.querySelectorAll('.agb-skfile').forEach(function(a, j){ a.classList.toggle('sel', j === i); });
    }
    box.querySelectorAll('[data-agb-skf]').forEach(function(a){ a.addEventListener('click', function(e){ e.preventDefault(); show(parseInt(a.dataset.agbSkf, 10)); }); });
    if (d.files && d.files.length) show(0);
  } catch (e){ box.innerHTML = '<div class="agb-err">' + _agbEsc(e.message) + '</div>'; }
}
