/* AGENTS page — the agent builder.
 *
 * An agent is a folder: agents/instances/<id>/{agent.json, SOUL.md}. This page
 * edits exactly that and nothing else. Saving writes the folder (PUT /agents/<id>);
 * the gateway only follows when someone presses "Ausrollen" (POST /agents/deploy),
 * and "Drift prüfen" (GET /agents/drift) shows the difference in between. Two
 * steps on purpose: a form that deploys on every save cannot be used to prepare.
 *
 * What the form is careful about, because each was measured to matter:
 *  - tool rights are the biggest block and never folded away (ADR-029: an agent
 *    without an allow list gets EVERY tool, and that looks like nothing)
 *  - a cloud model is marked "verlässt das Haus" next to its name, not in a tooltip
 *  - limits can be borrowed from another agent (`same_as`), because two agents
 *    meant to be compared must share their numbers by construction, and six
 *    differing values once invalidated a whole day's comparison
 *  - a SOUL may be shared (symlink) — same principle, for the prose
 *  - `_why…` comment blocks in the manifest are carried through untouched;
 *    the form shows how many it is keeping and never renders them as fields
 */

var AGB_API = (typeof LLM_API_BASE !== 'undefined') ? LLM_API_BASE : 'http://mora02.local:8098/sr';

var _agb = {
  roster: [], models: [], skills: [], tools: [],
  id: null,           // the agent open on the right; null = nothing, '' = new
  isNew: false,
  manifest: null,     // the manifest as edited (comments included)
  soul: '', soulShared: null,
  dirty: false
};

function _agbEsc(s){ return String(s == null ? '' : s).replace(/[&<>"]/g, function(c){ return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]; }); }
var AGB_ID_RE = /^[a-z0-9][a-z0-9-]{1,63}$/;
var AGB_LIMIT_KEYS = ['page_chars','max_urls','max_queries','snippet_chars','results_per_query','max_pages_total','max_searches_total'];
var AGB_LIMIT_HELP = {
  page_chars: 'Zeichen je gelesener Seite', max_urls: 'Seiten je web_read-Aufruf',
  max_queries: 'Suchanfragen je web_search-Aufruf', snippet_chars: 'Zeichen je Treffer-Schnipsel',
  results_per_query: 'Treffer je Suchanfrage', max_pages_total: 'Seiten je Zug insgesamt',
  max_searches_total: 'Suchen je Zug insgesamt'
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

  main.innerHTML = '<div class="agb-note">Lade Bausteine (Modelle vom Gateway, Fertigkeiten, Werkzeuge)…</div>';
  try {
    var res = await Promise.all([
      _agbGet('/agents/roster?include_inactive=true'),
      _agbGet('/agents/skills'),
      _agbGet('/agents/tools'),
      _agbGet('/agents/models').catch(function(e){ return { models: [], error: e.message }; })
    ]);
    _agb.roster = res[0].agents || [];
    _agb.skills = res[1].skills || [];
    _agb.tools = res[2].tools || [];
    _agb.models = res[3].models || [];
    _agb.modelsError = res[3].error || null;
  } catch (e){
    main.innerHTML = '<div class="agb-err">Agenten-Schicht nicht erreichbar: ' + _agbEsc(e.message) + '</div>';
    list.innerHTML = '';
    return;
  }
  _agbRenderList();
  main.innerHTML = '<div class="agb-note">Links einen Agenten wählen, oder oben rechts einen neuen anlegen.<br><br>'
    + 'Ein Agent ist ein Ordner unter <code>agents/instances/</code>. Speichern schreibt den Ordner; '
    + 'erst „Ausrollen" bringt ihn in den Gateway. „Drift prüfen" zeigt dazwischen, was sich ändern würde.</div>';
}

// ---- roster --------------------------------------------------------------
function _agbRenderList(){
  var el = document.getElementById('agb-list');
  if (!el) return;
  var h = '<div class="agb-list-h">Instanzen<span class="agb-list-n">' + _agb.roster.length + '</span></div>';
  _agb.roster.forEach(function(a){
    var cloud = a.model && a.model.indexOf('llama-local/') !== 0;
    h += '<div class="agb-row' + (a.id === _agb.id ? ' sel' : '') + (a.active ? '' : ' off') + '" data-agb-open="' + _agbEsc(a.id) + '">'
      + '<span class="agb-ico">' + _agbEsc(a.icon || '·') + '</span>'
      + '<div class="agb-row-t"><div class="agb-row-n">' + _agbEsc(a.label || a.id) + '</div>'
      + '<div class="agb-row-m">' + _agbEsc(a.id) + (a.active ? '' : ' · inaktiv') + '</div></div>'
      + (a.model ? '<span class="agb-pill ' + (cloud ? 'cloud' : 'local') + '">' + (cloud ? 'cloud' : 'lokal') + '</span>' : '')
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
  if (_agb.dirty && !confirm('Ungespeicherte Änderungen verwerfen?')) return;
  var main = document.getElementById('agb-main');
  main.innerHTML = '<div class="agb-note">Lade ' + _agbEsc(id) + '…</div>';
  try {
    var d = await _agbGet('/agents/' + encodeURIComponent(id) + '/detail');
    _agb.id = id; _agb.isNew = false;
    _agb.manifest = d.manifest || {};
    _agb.soul = d.soul || '';
    _agb.soulShared = d.soul_shared_with || null;
    _agb.dirty = false;
    _agbRenderList();
    _agbRenderForm();
  } catch (e){
    main.innerHTML = '<div class="agb-err">' + _agbEsc(e.message) + '</div>';
  }
}

function _agbNew(){
  if (_agb.dirty && !confirm('Ungespeicherte Änderungen verwerfen?')) return;
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
  _agb.dirty = false;
  _agbRenderList();
  _agbRenderForm();
}

// ---- the form ------------------------------------------------------------
function _agbRenderForm(){
  var main = document.getElementById('agb-main');
  var m = _agb.manifest;
  var comments = Object.keys(m).filter(function(k){ return k.charAt(0) === '_'; });
  var isMain = _agb.id === 'main';
  var h = '';

  // header + identity
  h += '<div class="agb-card"><div class="agb-card-h">Identität'
     + '<span class="agb-hint">' + (comments.length ? comments.length + ' Kommentar-Block/Blöcke (<code>_why…</code>) bleiben erhalten' : '') + '</span></div>';
  h += '<div class="agb-head-n" id="agb-headn">' + _agbEsc(m.label || (_agb.isNew ? 'Neuer Agent' : _agb.id)) + '<span class="agb-dirty" id="agb-dirty"></span></div>';
  h += '<div class="agb-grid" style="margin-top:10px">';
  h += _agbField('id', 'id', _agb.isNew ? '' : _agb.id, 'Ordnername = Kennung. Kleinbuchstaben, Ziffern, Bindestriche.', { disabled: !_agb.isNew, placeholder: 'z. b. strategie' });
  h += _agbField('label', 'Label', m.label || '', 'Name im Chat und in der Liste.');
  h += _agbField('icon', 'Icon', m.icon || '', 'Ein Emoji.');
  h += _agbField('colour', 'Farbe', m.colour || '', 'Hex, z. B. #a3e635.');
  h += _agbField('sort_order', 'Reihenfolge', m.sort_order != null ? m.sort_order : 100, 'Kleiner = weiter oben.', { type: 'number' });
  h += '</div>';
  h += _agbField('description', 'Beschreibung', m.description || '', 'Steht in der Slash-Liste. Nennt bei einem Cloud-Modell den Preis und dass die Anfrage das Haus verlässt.', { textarea: true });
  h += _agbField('opening', 'Eröffnung', m.opening || '', 'Was ein nacktes /<id> ohne Text sendet. Leer, wenn der Agent eine Frage braucht.');
  h += '<label class="agb-ck" style="display:inline-flex;margin-top:6px"><input type="checkbox" data-agb-f="active" ' + (m.active !== false ? 'checked' : '') + (isMain ? ' disabled' : '') + '><div class="agb-ck-t"><div class="agb-ck-n">aktiv</div><div class="agb-ck-d">Im Chat aufrufbar. ' + (isMain ? 'main ist der Briefkasten am Nachrichtenkanal, kein Gesprächspartner.' : 'Inaktiv = angelegt, aber nicht angeboten.') + '</div></div></label>';
  h += '</div>';

  // model + timeout
  h += '<div class="agb-card"><div class="agb-card-h">Modell &amp; Zeit</div><div class="agb-grid">';
  h += '<div class="agb-f"><div class="agb-l"><b>Modell</b></div><select class="agb-sel" data-agb-f="model">';
  if (!isMain) {
    var seen = false;
    var groups = [['lokal — bleibt im Haus', function(x){ return x.local; }], ['Cloud — die Anfrage verlässt das Haus', function(x){ return !x.local; }]];
    groups.forEach(function(g){
      var ms = _agb.models.filter(g[1]);
      if (!ms.length) return;
      h += '<optgroup label="' + _agbEsc(g[0]) + '">';
      ms.forEach(function(x){
        var sel = x.key === m.model; if (sel) seen = true;
        h += '<option value="' + _agbEsc(x.key) + '"' + (sel ? ' selected' : '') + (x.available ? '' : ' disabled') + '>'
           + _agbEsc(x.key) + (x.context_window ? '  · ' + Math.round(x.context_window / 1024) + 'k' : '') + '</option>';
      });
      h += '</optgroup>';
    });
    if (m.model && !seen) h += '<option value="' + _agbEsc(m.model) + '" selected>' + _agbEsc(m.model) + ' (dem Gateway unbekannt)</option>';
    if (!m.model) h += '<option value="" selected disabled>— wählen —</option>';
  } else {
    h += '<option value="" selected>(Gateway-Vorgabe)</option>';
  }
  h += '</select><div class="agb-hint" id="agb-modelhint"></div>'
     + (_agb.modelsError ? '<div class="agb-hint bad">Modell-Liste vom Gateway nicht ladbar: ' + _agbEsc(_agb.modelsError) + '</div>' : '')
     + '</div>';
  h += _agbField('timeout', 'Zeitgrenze (s)', m.timeout != null ? m.timeout : '', 'Je Zug. Ein Recherche-Zug braucht Minuten; eine zu kleine Zahl sieht aus wie ein kaputter Agent.', { type: 'number' });
  h += '</div></div>';

  // limits
  var lim = m.limits;
  var mode = !lim ? 'none' : (lim.same_as ? 'same_as' : 'own');
  h += '<div class="agb-card"><div class="agb-card-h">Nutzlast-Limits<span class="agb-hint">für web_search / web_read</span></div>';
  h += '<div class="agb-grid" style="grid-template-columns:200px 1fr">';
  h += '<div class="agb-f"><div class="agb-l"><b>Quelle</b></div><select class="agb-sel" data-agb-lmode>'
     + '<option value="none"' + (mode === 'none' ? ' selected' : '') + '>keine (Vorgaben des Servers)</option>'
     + '<option value="same_as"' + (mode === 'same_as' ? ' selected' : '') + '>wie ein anderer Agent</option>'
     + '<option value="own"' + (mode === 'own' ? ' selected' : '') + '>eigene Werte</option></select></div>';
  h += '<div class="agb-f" id="agb-limbox"></div></div>';
  h += '<div class="agb-hint" style="margin-top:6px">Zwei Agenten, die man vergleichen will, MÜSSEN dieselben Limits haben — sonst misst der Vergleich die Konfiguration. „Wie ein anderer Agent" koppelt sie durch Bauart; eine Kopie driftet.</div>';
  h += '</div>';

  // skills
  h += '<div class="agb-card"><div class="agb-card-h">Fertigkeiten<span class="agb-hint">agents/skills/ — nur die Beschreibung erreicht den Prompt</span></div><div class="agb-checks">';
  if (!_agb.skills.length) h += '<div class="agb-hint">Keine Fertigkeiten unter agents/skills/.</div>';
  _agb.skills.forEach(function(s){
    var on = (m.skills || []).indexOf(s.name) >= 0;
    h += '<label class="agb-ck' + (on ? ' on' : '') + '"><input type="checkbox" data-agb-skill="' + _agbEsc(s.name) + '"' + (on ? ' checked' : '') + '>'
       + '<div class="agb-ck-t"><div class="agb-ck-n">' + _agbEsc(s.name) + '<span class="agb-pill">' + s.files + ' Datei(en)</span></div>'
       + '<div class="agb-ck-d">' + (s.description ? _agbEsc(s.description) : '<span style="color:#e88">ohne Beschreibung — wird gelistet und nie benutzt</span>') + '</div></div></label>';
  });
  h += '</div></div>';

  // tools — never folded, always the whole list
  var unrestricted = m.tools === 'unrestricted';
  var allow = (m.tools && m.tools.allow) || [];
  h += '<div class="agb-card"><div class="agb-card-h">Werkzeug-Rechte<span class="agb-hint">Freigabeliste. Ohne Liste bekäme ein Agent ALLE Werkzeuge — deshalb steht sie hier und nicht in einem Untermenü.</span></div>';
  if (unrestricted) {
    h += '<div class="agb-hint bad" style="margin-bottom:8px">Dieser Agent steht auf <code>"tools": "unrestricted"</code> — bewusst und schriftlich. Das Formular ändert das nicht; wer eine Liste will, setzt sie in der Datei.</div>';
  }
  var mcp = _agb.tools.filter(function(t){ return t.source === 'mcp'; });
  var gw = _agb.tools.filter(function(t){ return t.source !== 'mcp'; });
  var known = {}; _agb.tools.forEach(function(t){ known[t.id] = true; });
  h += '<div class="agb-sub">Haus-Werkzeuge (MCP, script-runner)</div><div class="agb-checks">' + mcp.map(function(t){ return _agbToolCk(t, allow, unrestricted); }).join('') + '</div>';
  h += '<div class="agb-sub">Gateway-Werkzeuge</div><div class="agb-checks">' + gw.map(function(t){ return _agbToolCk(t, allow, unrestricted); }).join('') + '</div>';
  var unknownAllowed = allow.filter(function(a){ return !known[a]; });
  if (unknownAllowed.length) {
    h += '<div class="agb-sub">In der Liste, hier unbekannt</div><div class="agb-checks">' + unknownAllowed.map(function(a){
      return _agbToolCk({ id: a, risk: 'act', what: 'Steht in der Freigabeliste, aber weder unser MCP-Server noch agents/tools.json kennen es.', source: '?' }, allow, unrestricted);
    }).join('') + '</div>';
  }
  h += '<div class="agb-hint" id="agb-toolhint" style="margin-top:8px"></div></div>';

  // SOUL
  var originals = _agb.roster.filter(function(a){ return a.id !== _agb.id && a.id !== 'main'; });
  h += '<div class="agb-card"><div class="agb-card-h">SOUL.md — wer der Agent ist<span class="agb-hint">Prosa. Fertigkeiten sagen WIE, die SOUL sagt WER.</span></div>';
  h += '<div class="agb-grid" style="grid-template-columns:200px 1fr;margin-bottom:8px">';
  h += '<div class="agb-f"><div class="agb-l"><b>Quelle</b></div><select class="agb-sel" data-agb-smode>'
     + '<option value="own"' + (!_agb.soulShared ? ' selected' : '') + '>eigene Datei</option>'
     + '<option value="shared"' + (_agb.soulShared ? ' selected' : '') + '>geteilt mit einem anderen Agenten (Symlink)</option></select></div>';
  h += '<div class="agb-f" id="agb-soulsrc">' + (_agb.soulShared ? _agbSoulShareSelect(originals) : '') + '</div></div>';
  h += '<textarea class="agb-ta" data-agb-soul' + (_agb.soulShared ? ' disabled' : '') + ' spellcheck="false">' + _agbEsc(_agb.soul) + '</textarea>';
  if (_agb.soulShared) h += '<div class="agb-hint">Angezeigt wird die Datei von <b>' + _agbEsc(_agb.soulShared) + '</b>. Ändern heißt dort ändern — beide Agenten bekommen es.</div>';
  h += '</div>';

  // actions
  h += '<div class="agb-bar">'
     + '<button class="tool-btn tool-btn-primary" data-agb-do="save">Speichern</button>'
     + '<button class="tool-btn tool-btn-secondary" data-agb-do="drift"' + (_agb.isNew ? ' disabled' : '') + '>Drift prüfen</button>'
     + '<button class="tool-btn tool-btn-secondary" data-agb-do="deploy"' + (_agb.isNew ? ' disabled' : '') + '>Ausrollen</button>'
     + '<button class="tool-btn tool-btn-secondary" data-agb-do="test"' + (_agb.isNew || isMain || m.active === false ? ' disabled' : '') + '>Testen</button>'
     + '<span class="agb-sp"></span>'
     + (_agb.isNew || isMain ? '' : '<button class="tool-btn tool-btn-secondary tool-btn-danger" data-agb-do="delete">Löschen</button>')
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
  var label = { read: 'liest', write: 'schreibt', act: 'handelt' }[risk] || risk;
  return '<label class="agb-ck ' + risk + (on ? ' on' : '') + '"><input type="checkbox" data-agb-tool="' + _agbEsc(t.id) + '"' + (on ? ' checked' : '') + (unrestricted ? ' disabled' : '') + '>'
    + '<div class="agb-ck-t"><div class="agb-ck-n">' + _agbEsc(t.id) + '<span class="agb-risk">' + label + '</span></div>'
    + '<div class="agb-ck-d">' + _agbEsc(t.what || '') + '</div></div></label>';
}

function _agbSoulShareSelect(originals){
  var h = '<div class="agb-l"><b>Datei von</b></div><select class="agb-sel" data-agb-sshare>';
  if (!originals.length) h += '<option value="">— kein anderer Agent —</option>';
  originals.forEach(function(a){
    h += '<option value="' + _agbEsc(a.id) + '"' + (a.id === _agb.soulShared ? ' selected' : '') + '>' + _agbEsc(a.id) + '</option>';
  });
  return h + '</select>';
}

function _agbRenderLimits(mode){
  var box = document.getElementById('agb-limbox');
  if (!box) return;
  var m = _agb.manifest;
  if (mode === 'none'){ box.innerHTML = '<div class="agb-hint" style="margin-top:18px">Der Server setzt seine Vorgaben ein.</div>'; return; }
  if (mode === 'same_as'){
    var others = _agb.roster.filter(function(a){ return a.id !== _agb.id && a.id !== 'main'; });
    var cur = (m.limits && m.limits.same_as) || '';
    var h = '<div class="agb-l"><b>Limits von</b></div><select class="agb-sel" data-agb-lsame>';
    others.forEach(function(a){ h += '<option value="' + _agbEsc(a.id) + '"' + (a.id === cur ? ' selected' : '') + '>' + _agbEsc(a.id) + '</option>'; });
    box.innerHTML = h + '</select><div class="agb-hint">Der andere Agent muss eigene Werte haben (keine Kette).</div>';
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
    el.textContent = 'Lokal. Der Name ist ein Port, nicht ein Gewicht — welches Modell wirklich antwortet, steht im llm-switch und im Umschlag jeder Antwort.';
  } else {
    el.className = 'agb-hint warn';
    el.textContent = 'Cloud: jede Anfrage verlässt das Haus und kostet Geld (Recherche-Zug auf Sonnet ~33 ct). Nur für Agenten, die nichts steuern.';
  }
}

function _agbToolHint(){
  var el = document.getElementById('agb-toolhint');
  if (!el) return;
  var m = _agb.manifest;
  if (m.tools === 'unrestricted'){ el.className = 'agb-hint bad'; el.textContent = 'Unbeschränkt.'; return; }
  var allow = (m.tools && m.tools.allow) || [];
  var risky = allow.filter(function(a){ var t = _agb.tools.filter(function(x){ return x.id === a; })[0]; return t && t.risk === 'act'; });
  var cloud = m.model && m.model.indexOf('llama-local/') !== 0;
  if (!allow.length){ el.className = 'agb-hint bad'; el.textContent = 'Leere Liste: der Gateway bricht einen Lauf ohne aufrufbares Werkzeug ab. Mindestens eines.'; return; }
  if (allow.indexOf('lobster') >= 0){ el.className = 'agb-hint bad'; el.textContent = 'lobster löst Freigaben selbst auf und kennt keinen input-Gate. Für Flows mora02__flow_run nehmen.'; return; }
  if (risky.length && cloud){ el.className = 'agb-hint bad'; el.textContent = 'Ein Cloud-Modell mit handelnden Werkzeugen (' + risky.join(', ') + ') steuert das Haus von außen. Die Leitplanke sagt: Steuerung bleibt lokal.'; return; }
  if (risky.length){ el.className = 'agb-hint warn'; el.textContent = allow.length + ' Werkzeug(e), davon handelnd: ' + risky.join(', ') + '.'; return; }
  el.className = 'agb-hint ok'; el.textContent = allow.length + ' Werkzeug(e), keines handelt über den Arbeitsbereich hinaus.';
}

function _agbMark(){
  _agb.dirty = true;
  var d = document.getElementById('agb-dirty'); if (d) d.textContent = '● ungespeichert';
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
      if (k === 'label'){ var hn = document.getElementById('agb-headn'); if (hn) hn.firstChild.textContent = inp.value || _agb.id || 'Neuer Agent'; }
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
    var originals = _agb.roster.filter(function(a){ return a.id !== _agb.id && a.id !== 'main'; });
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
  if (!AGB_ID_RE.test(id)){ _agbSay('Kennung: 2–64 Zeichen, Kleinbuchstaben, Ziffern, Bindestriche.', 'bad'); return; }
  if (_agb.isNew && _agb.roster.some(function(a){ return a.id === id; })){ _agbSay('Es gibt schon einen Agenten „' + id + '".', 'bad'); return; }
  var body = { manifest: _agb.manifest };
  if (_agb.soulShared) body.soul_shared_with = _agb.soulShared;
  else body.soul = _agb.soul;
  _agbSay('Speichere…');
  try {
    var r = await fetch(AGB_API + '/agents/' + encodeURIComponent(id), {
      method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body)
    });
    var j = await r.json().catch(function(){ return {}; });
    if (!r.ok){ _agbSay('Abgelehnt: ' + (j.detail || ('HTTP ' + r.status)), 'bad'); return; }
    _agb.dirty = false; _agb.isNew = false; _agb.id = id;
    _agbSay((j.created ? 'Angelegt: ' : 'Gespeichert: ') + 'agents/instances/' + id + '/ — noch nicht ausgerollt.', 'ok');
    await _agbReloadRoster();
    await _agbOpen(id);
    _agbSay((j.created ? 'Angelegt: ' : 'Gespeichert: ') + 'agents/instances/' + id + '/ — Drift wird geprüft…', 'ok');
    await _agbDrift(id);
  } catch (e){ _agbSay('Fehler: ' + e.message, 'bad'); }
}

// ---- drift / deploy ------------------------------------------------------
function _agbOut(html){
  var box = document.getElementById('agb-outbox') || document.getElementById('agb-main');
  if (box) box.innerHTML = html;
}

function _agbDriftHtml(res, title){
  var lines = res.drift || [];
  var h = '<div class="agb-card"><div class="agb-card-h">' + _agbEsc(title) + '</div>';
  if (res.in_sync && !res.applied){ return h + '<div class="agb-hint ok">Gateway und Ordner stimmen überein — nichts zu tun.</div></div>'; }
  h += '<div class="agb-out">';
  if (res.log && res.log.length) h += res.log.map(function(l){ return '<span class="dim">' + _agbEsc(l) + '</span>'; }).join('\n') + '\n\n';
  h += lines.map(function(l){
    var cls = /left alone/.test(l) ? 'dim' : (/does not exist|missing|deleted in the roster/.test(l) ? 'ok' : '');
    return '<span class="' + cls + '">' + _agbEsc(l) + '</span>';
  }).join('\n');
  if (res.applied){
    h += '\n\n' + (res.ok ? '<span class="ok">Ausgerollt und gegengelesen — in sync.</span>' : '<span class="bad">Ausgerollt, aber danach noch verschieden:\n' + _agbEsc((res.left || []).join('\n')) + '</span>');
  }
  return h + '</div></div>';
}

async function _agbDrift(id){
  _agbOut('<div class="agb-note">Vergleiche Ordner mit dem Gateway…</div>');
  try {
    var res = await _agbGet('/agents/drift');
    _agbOut(_agbDriftHtml(res, 'Drift — was „Ausrollen" ändern würde'));
    _agbSay('');
  } catch (e){ _agbOut('<div class="agb-err">Drift-Prüfung: ' + _agbEsc(e.message) + '</div>'); }
}

async function _agbDeploy(){
  if (_agb.dirty){ _agbSay('Erst speichern, dann ausrollen.', 'bad'); return; }
  _agbOut('<div class="agb-note">Rolle aus (config patch, Workspace-Dateien, MCP-Reload)…</div>');
  try {
    var r = await fetch(AGB_API + '/agents/deploy', { method: 'POST' });
    var j = await r.json().catch(function(){ return {}; });
    if (!r.ok){ _agbOut('<div class="agb-err">Rollout abgelehnt: ' + _agbEsc(j.detail || ('HTTP ' + r.status)) + '</div>'); return; }
    _agbOut(_agbDriftHtml(j, j.applied ? 'Rollout' : 'Rollout — nichts zu tun'));
    if (typeof loadAgents === 'function') loadAgents();
  } catch (e){ _agbOut('<div class="agb-err">Rollout: ' + _agbEsc(e.message) + '</div>'); }
}

// ---- test ----------------------------------------------------------------
async function _agbTest(){
  if (_agb.dirty){ _agbSay('Erst speichern (und ausrollen), dann testen.', 'bad'); return; }
  var q = prompt('Probe-Nachricht an ' + _agb.id + ':', _agb.manifest.opening || 'Wer bist du, und was kannst du für mich tun? Zwei Sätze.');
  if (q == null || !q.trim()) return;
  var cloud = _agb.manifest.model && _agb.manifest.model.indexOf('llama-local/') !== 0;
  if (cloud && !confirm('Dieser Agent läuft auf einem Cloud-Modell: die Probe verlässt das Haus und kostet Geld. Trotzdem?')) return;
  var t0 = Date.now();
  _agbOut('<div class="agb-card"><div class="agb-card-h">Probe</div><div class="agb-note">Der Agent arbeitet… (Zeitgrenze ' + (_agb.manifest.timeout || 180) + ' s)</div></div>');
  try {
    var r = await fetch(AGB_API + '/agent/' + encodeURIComponent(_agb.id) + '/message', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: q, conversation: 'builder-' + Date.now() })
    });
    var j = await r.json().catch(function(){ return {}; });
    if (!r.ok){ _agbOut('<div class="agb-err">Der Agent hat nicht geantwortet: ' + _agbEsc(j.detail || ('HTTP ' + r.status)) + '\n\nNoch nicht ausgerollt? Dann kennt der Gateway ihn nicht.</div>'); return; }
    var secs = Math.round((Date.now() - t0) / 1000);
    var meta = [];
    if (j.model_real) meta.push('Modell: ' + j.model_real + (j.model_declared && j.model_declared !== j.model_real ? ' (deklariert ' + j.model_declared + ')' : ''));
    meta.push(secs + ' s');
    if (j.tool_calls != null) meta.push(j.tool_calls + ' Werkzeugaufruf(e)' + (j.tools_used && j.tools_used.length ? ': ' + j.tools_used.join(', ') : ''));
    if (j.cost_eur_last_call) meta.push('≥ ' + j.cost_eur_last_call.toFixed(3) + ' € (letzter Aufruf)');
    _agbOut('<div class="agb-card"><div class="agb-card-h">Probe<span class="agb-hint">' + _agbEsc(q.slice(0, 80)) + '</span></div>'
      + '<div class="agb-answer">' + _agbEsc(j.text || j.answer || JSON.stringify(j).slice(0, 800)) + '</div>'
      + '<div class="agb-meta">' + _agbEsc(meta.join(' · ')) + '</div></div>');
  } catch (e){ _agbOut('<div class="agb-err">Probe: ' + _agbEsc(e.message) + '</div>'); }
}

// ---- delete --------------------------------------------------------------
async function _agbDelete(){
  var id = _agb.id;
  if (!confirm('Agent „' + id + '" löschen?\n\nDer Ordner wandert nach agents/instances/.trash/ (wiederherstellbar). Aus dem Gateway verschwindet er beim nächsten Ausrollen.')) return;
  try {
    var r = await fetch(AGB_API + '/agents/' + encodeURIComponent(id), { method: 'DELETE' });
    var j = await r.json().catch(function(){ return {}; });
    if (!r.ok){ _agbSay('Abgelehnt: ' + (j.detail || ('HTTP ' + r.status)), 'bad'); return; }
    _agb.id = null; _agb.dirty = false;
    await _agbReloadRoster();
    document.getElementById('agb-main').innerHTML = '<div class="agb-note">„' + _agbEsc(id) + '" verschoben nach <code>' + _agbEsc(j.moved_to || '.trash/') + '</code>.<br><br>Im Gateway existiert er noch — „Drift prüfen" zeigt das, „Ausrollen" entfernt ihn dort.</div>'
      + '<div class="agb-bar"><button class="tool-btn tool-btn-secondary" data-agb-do2="drift">Drift prüfen</button><button class="tool-btn tool-btn-primary" data-agb-do2="deploy">Ausrollen</button></div><div id="agb-outbox"></div>';
    document.querySelectorAll('[data-agb-do2]').forEach(function(b){
      b.addEventListener('click', function(){ if (b.dataset.agbDo2 === 'drift') _agbDrift(null); else _agbDeploy(); });
    });
  } catch (e){ _agbSay('Fehler: ' + e.message, 'bad'); }
}
