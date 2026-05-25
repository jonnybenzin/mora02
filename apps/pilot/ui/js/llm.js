/* ═══════════════════════════════════════════════════════════════
   MORA02 PILOT — LLM Profile Module
   ═══════════════════════════════════════════════════════════════
   Talks to script-runner at :8096 for local LLM profile switching.
   Keeps the active profile label in sync across menu and chat
   rendering. Routing key stays "qwen" — this is purely cosmetic.
   ═══════════════════════════════════════════════════════════════ */

var LLM_API_BASE = 'http://mora02.local:8096';
var LLM_FALLBACK_LABEL = 'LOCAL LLM';

// Global state
window.llmState = {
  profiles: [],         // array of profile objects from script-runner
  current: null,        // current profile object (or null if unknown)
  loaded: false,
};

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

llmLoadProfiles();
