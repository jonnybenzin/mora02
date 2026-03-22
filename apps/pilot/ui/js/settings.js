/* ═══════════════════════════════════════════════════════════════
   MORA02 PILOT — Settings & Persona Module (2026-03-19)
   ═══════════════════════════════════════════════════════════════
   Settings: Load/Save temperature, max_tokens, system prompt
   Persona: View active, Create new
   ───────────────────────────────────────────────────────────────
   Depends on: app.js (API_BASE, sessionId, activePersonaId)
   ═══════════════════════════════════════════════════════════════ */

/* ═══════════════════════════════════════════════════════════════
   SETTINGS
   ═══════════════════════════════════════════════════════════════ */

async function initSettings() {
  if (!sessionId) return;

  try {
    var resp = await fetch(API_BASE + '/session/' + sessionId + '/system-prompt');
    if (!resp.ok) return;
    var data = await resp.json();

    var temp = document.getElementById('set-temp');
    var slider = document.getElementById('set-temp-slider');
    var tokens = document.getElementById('set-maxtokens');
    var prompt = document.getElementById('set-sysprompt');

    if (temp) temp.value = data.temperature || 0.7;
    if (slider) slider.value = Math.round((data.temperature || 0.7) * 100);
    if (tokens) tokens.value = data.max_tokens || 4096;
    if (prompt) prompt.value = data.system_prompt || '';

    /* Sync slider ↔ input */
    if (slider && temp) {
      slider.addEventListener('input', function() {
        temp.value = (parseInt(slider.value) / 100).toFixed(2);
      });
      temp.addEventListener('change', function() {
        slider.value = Math.round(parseFloat(temp.value) * 100);
      });
    }

    /* Auto-resize prompt */
    if (prompt) {
      prompt.addEventListener('input', function() {
        prompt.style.height = 'auto';
        prompt.style.height = prompt.scrollHeight + 'px';
      });
      prompt.style.height = 'auto';
      prompt.style.height = prompt.scrollHeight + 'px';
    }
  } catch (e) {
    console.warn('Failed to load settings:', e);
  }
}

async function settingsSave() {
  if (!sessionId) return;

  var temp = document.getElementById('set-temp');
  var tokens = document.getElementById('set-maxtokens');
  var prompt = document.getElementById('set-sysprompt');

  var body = {};
  if (temp) body.temperature = parseFloat(temp.value);
  if (tokens) body.max_tokens = parseInt(tokens.value);
  if (prompt && prompt.value.trim()) body.system_prompt = prompt.value.trim();

  try {
    var resp = await fetch(API_BASE + '/session/' + sessionId + '/system-prompt', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    var data = await resp.json();
    setStatus('set-status', '\u2713 Saved', false);
  } catch (e) {
    setStatus('set-status', 'Save failed: ' + e.message, true);
  }
}

async function settingsReset() {
  if (!sessionId) return;

  try {
    var resp = await fetch(API_BASE + '/session/' + sessionId + '/system-prompt', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({}),
    });
    var data = await resp.json();

    var temp = document.getElementById('set-temp');
    var slider = document.getElementById('set-temp-slider');
    var tokens = document.getElementById('set-maxtokens');
    var prompt = document.getElementById('set-sysprompt');

    if (temp) temp.value = data.temperature || 0.7;
    if (slider) slider.value = Math.round((data.temperature || 0.7) * 100);
    if (tokens) tokens.value = data.max_tokens || 4096;
    if (prompt) {
      prompt.value = data.system_prompt || '';
      prompt.style.height = 'auto';
      prompt.style.height = prompt.scrollHeight + 'px';
    }

    setStatus('set-status', '\u2713 Reset to defaults', false);
  } catch (e) {
    setStatus('set-status', 'Reset failed: ' + e.message, true);
  }
}

/* ═══════════════════════════════════════════════════════════════
   PERSONA SETTINGS (read-only view of active persona)
   ═══════════════════════════════════════════════════════════════ */

async function initPersonaSettings() {
  var content = document.getElementById('persona-edit-content');
  var empty = document.getElementById('persona-edit-empty');

  /* Find active persona ID from sidebar */
  var activeMi = document.querySelector('[data-action="select-persona"].act');
  var pid = activeMi ? activeMi.dataset.personaId : null;

  if (!pid || pid === 'null') {
    if (content) content.style.display = 'none';
    if (empty) empty.style.display = '';
    return;
  }

  if (content) content.style.display = '';
  if (empty) empty.style.display = 'none';

  /* Fetch persona details */
  try {
    var resp = await fetch(API_BASE + '/personas');
    if (!resp.ok) return;
    var personas = await resp.json();
    var persona = personas.find(function(p) { return String(p.id) === String(pid); });
    if (!persona) return;

    var name = document.getElementById('pe-name');
    var icon = document.getElementById('pe-icon');
    var desc = document.getElementById('pe-description');
    var prompt = document.getElementById('pe-prompt');
    var briefing = document.getElementById('pe-briefing');
    var usage = document.getElementById('pe-usage');

    if (name) name.value = persona.name || '';
    if (icon) icon.value = persona.icon || '';
    if (desc) desc.value = persona.description || '';
    if (prompt) prompt.value = persona.prompt || '';
    if (briefing) briefing.value = persona.briefing_target || '';
    if (usage) usage.textContent = (persona.usage_count || 0) + ' conversations';

    /* Auto-resize textareas */
    [desc, prompt].forEach(function(el) {
      if (el) { el.style.height = 'auto'; el.style.height = el.scrollHeight + 'px'; }
    });
  } catch (e) {
    console.warn('Failed to load persona:', e);
  }
}

/* ═══════════════════════════════════════════════════════════════
   PERSONA CREATE
   ═══════════════════════════════════════════════════════════════ */

async function initPersonaCreate() {
  /* Nothing to load — empty form */
  setStatus('pc-status', '');
}

async function personaCreateSave() {
  var name = (document.getElementById('pc-name') || {}).value || '';
  var icon = (document.getElementById('pc-icon') || {}).value || '';
  var desc = (document.getElementById('pc-description') || {}).value || '';
  var prompt = (document.getElementById('pc-prompt') || {}).value || '';
  var briefing = (document.getElementById('pc-briefing') || {}).value || '';

  if (!name.trim()) {
    setStatus('pc-status', 'Name is required', true);
    return;
  }

  try {
    var resp = await fetch(API_BASE + '/personas', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        name: name.trim(),
        icon: icon.trim() || '\ud83c\udfad',
        description: desc.trim(),
        prompt: prompt.trim(),
        briefing_target: briefing.trim(),
      }),
    });
    var data = await resp.json();

    if (data.id || data.name) {
      setStatus('pc-status', '\u2713 Persona "' + (data.name || name) + '" created', false);

      /* Clear form */
      ['pc-name', 'pc-icon', 'pc-description', 'pc-prompt', 'pc-briefing'].forEach(function(id) {
        var el = document.getElementById(id);
        if (el) el.value = '';
      });

      /* Refresh persona list in sidebar */
      if (typeof loadPersonas === 'function') loadPersonas();
    } else {
      setStatus('pc-status', data.error || 'Create failed', true);
    }
  } catch (e) {
    setStatus('pc-status', 'Create failed: ' + e.message, true);
  }
}

/* ═══════════════════════════════════════════════════════════════
   PERSONA ARCHIVE (set active=false in Baserow)
   ═══════════════════════════════════════════════════════════════ */

async function personaArchive() {
  var activeMi = document.querySelector('[data-action="select-persona"].act');
  var pid = activeMi ? activeMi.dataset.personaId : null;
  if (!pid || pid === 'null') return;

  if (!confirm('Archive this persona? It will be hidden from the menu.')) return;

  try {
    var resp = await fetch('http://mora02.local:8085/api/database/rows/table/575/' + pid + '/?user_field_names=true', {
      method: 'PATCH',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': 'Token ***BASEROW_TOKEN_OLD_REVOKED***',
        'Host': 'mora02.local:8085',
      },
      body: JSON.stringify({ active: false }),
    });
    if (resp.ok) {
      setStatus('pe-status', '\u2713 Persona archived');
      /* Refresh sidebar */
      if (typeof loadPersonas === 'function') loadPersonas();
      /* Navigate home */
      if (typeof navigate === 'function') navigate('home');
    } else {
      setStatus('pe-status', 'Archive failed', true);
    }
  } catch (e) {
    setStatus('pe-status', 'Archive failed: ' + e.message, true);
  }
}

/* ═══════════════════════════════════════════════════════════════
   PAGE INIT ROUTER
   ═══════════════════════════════════════════════════════════════ */

function initSettingsPage(page) {
  switch (page) {
    case 'settings':         initSettings(); break;
    case 'persona-settings': initPersonaSettings(); break;
    case 'persona-create':   initPersonaCreate(); break;
  }
}

/* ═══════════════════════════════════════════════════════════════
   HELPERS
   ═══════════════════════════════════════════════════════════════ */

function setStatus(id, msg, isError) {
  var el = document.getElementById(id);
  if (!el) return;
  if (!msg) { el.innerHTML = ''; return; }
  el.innerHTML = '<span style="color:var(--c-' + (isError ? 'red' : 'green') + ')">' + msg + '</span>';
}

/* ═══════════════════════════════════════════════════════════════
   EVENT DELEGATION
   ═══════════════════════════════════════════════════════════════ */

document.addEventListener('click', function(e) {
  var target = e.target.closest('[data-action]');
  if (!target) return;

  switch (target.dataset.action) {
    case 'settings-save':        settingsSave(); break;
    case 'settings-reset':       settingsReset(); break;
    case 'persona-create-save':  personaCreateSave(); break;
    case 'persona-archive':      personaArchive(); break;
  }
});
