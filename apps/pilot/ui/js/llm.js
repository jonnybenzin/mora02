/* ═══════════════════════════════════════════════════════════════
   MORA02 PILOT — LLM Profile + Menu Module
   ═══════════════════════════════════════════════════════════════
   - Renders the LLM dropdown from Pilot's /models endpoint
     (single source of truth: lib/.../llm/models.py MODELS dict)
   - Talks to script-runner at :8096 for local LLM profile switching
   - Keeps the active local-profile label in sync across menu and
     chat rendering. Routing key stays "qwen" — purely cosmetic.
   ═══════════════════════════════════════════════════════════════ */

var LLM_API_BASE = 'http://mora02.local:8096';
var PILOT_API_BASE = (typeof API_BASE !== 'undefined') ? API_BASE : 'http://mora02.local:8098';
var LLM_FALLBACK_LABEL = 'LOCAL LLM';

// Global state
window.llmState = {
  profiles: [],         // array of profile objects from script-runner
  current: null,        // current profile object (or null if unknown)
  loaded: false,
  models: [],           // array of model entries from Pilot /models
};

/* ─── Render LLM dropdown from /models ───────────────────────── */

async function renderLLMMenu() {
  var listEl = document.getElementById('llm-list');
  var flyEl = document.getElementById('llm-fly-list');
  if (!listEl && !flyEl) return;

  try {
    var resp = await fetch(PILOT_API_BASE + '/models');
    if (!resp.ok) throw new Error('status ' + resp.status);
    window.llmState.models = await resp.json();
  } catch (e) {
    console.warn('LLM models load failed:', e);
    return;
  }

  function buildMi(m, isFirst, withIcon) {
    var div = document.createElement('div');
    div.className = 'mi' + (isFirst ? ' act' : '');
    div.setAttribute('data-action', 'select-llm');
    div.setAttribute('data-model', m.key);
    div.setAttribute('data-color', m.color);

    var left = document.createElement('div');
    left.className = 'mi-l';
    if (withIcon) {
      var ico = document.createElement('div');
      ico.className = 'mi-ico';
      ico.style.color = 'var(--' + m.color + ')';
      ico.innerHTML = '<svg fill="currentColor"><use href="icons/sprite.svg#i-bot"/></svg>';
      left.appendChild(ico);
    }
    var lbl = document.createElement('span');
    lbl.className = 'mi-lbl';
    if (isFirst && withIcon) lbl.style.color = 'var(--' + m.color + ')';
    lbl.textContent = m.label;
    left.appendChild(lbl);
    div.appendChild(left);

    if (m.tier) {
      var right = document.createElement('div');
      right.className = 'mi-r';
      right.textContent = m.tier;
      div.appendChild(right);
    }
    return div;
  }

  if (listEl) {
    listEl.innerHTML = '';
    window.llmState.models.forEach(function(m, i) {
      listEl.appendChild(buildMi(m, i === 0, true));
    });
  }
  if (flyEl) {
    flyEl.innerHTML = '';
    window.llmState.models.forEach(function(m, i) {
      flyEl.appendChild(buildMi(m, i === 0, false));
    });
  }
}

/* ─── Fetch profiles & current ──────────────────────────────── */

async function llmLoadProfiles() {
  try {
    var resp = await fetch(LLM_API_BASE + '/llm/profiles');
    if (!resp.ok) throw new Error('status ' + resp.status);
    var data = await resp.json();
    window.llmState.profiles = data.profiles || [];
    window.llmState.current = data.current || null;
    window.llmState.loaded = true;
    llmRenderMenuLabel();
  } catch (e) {
    console.warn('LLM profile load failed:', e);
    window.llmState.loaded = true;  // mark loaded so fallback label sticks
    llmRenderMenuLabel();
  }
}

/* ─── Get display label for the currently active local profile ─ */

function llmCurrentLabel() {
  var cur = window.llmState.current;
  if (cur && cur.label) return cur.label.toUpperCase();
  return LLM_FALLBACK_LABEL;
}

/* ─── Translate a chat message model key to its display label ─── */

function llmModelLabel(model) {
  if (!model) return 'SYSTEM';
  if (model === 'qwen') return llmCurrentLabel();
  return String(model).toUpperCase();
}

/* ─── Update the "QWEN" menu entry label everywhere ─────────── */

function llmRenderMenuLabel() {
  var label = llmCurrentLabel();
  document.querySelectorAll('[data-action="select-llm"][data-model="qwen"] .mi-lbl')
    .forEach(function(el) {
      el.textContent = label;
    });
}

/* ─── Switch profile: submit + poll ─────────────────────────── */

async function llmSwitchProfile(profileName) {
  var resp = await fetch(LLM_API_BASE + '/llm/switch', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ profile: profileName }),
  });
  if (!resp.ok) {
    var err = await resp.text();
    throw new Error('switch failed: ' + err);
  }
  var data = await resp.json();
  var requestId = data.request_id;

  // Poll until done or timeout. Must exceed host-side MAX_HEALTH_WAIT (240s)
  // with buffer for network/parse overhead.
  var maxWait = 300000;  // 5 minutes
  var started = Date.now();
  while (Date.now() - started < maxWait) {
    await new Promise(function(r) { setTimeout(r, 1500); });
    var sResp = await fetch(LLM_API_BASE + '/llm/switch/' + encodeURIComponent(requestId));
    if (!sResp.ok) continue;
    var sData = await sResp.json();
    if (sData.status === 'done') {
      // Refresh state from server (authoritative)
      await llmLoadProfiles();
      return sData.result;
    }
  }
  throw new Error('timeout waiting for switch');
}

/* ─── Init on startup ───────────────────────────────────────── */

(async function llmInit() {
  await renderLLMMenu();
  llmLoadProfiles();
})();
