/* ═══════════════════════════════════════════════════════════════
   MORA02 PILOT — Settings Module (2026-03-19)
   ═══════════════════════════════════════════════════════════════
   Settings: Load/Save temperature, max_tokens, system prompt
   ───────────────────────────────────────────────────────────────
   Depends on: app.js (API_BASE, sessionId)
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
   PAGE INIT ROUTER
   ═══════════════════════════════════════════════════════════════ */

function initSettingsPage(page) {
  switch (page) {
    case 'settings':         initSettings(); break;
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
  }
});
