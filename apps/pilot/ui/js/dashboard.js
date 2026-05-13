/* ═══════════════════════════════════════════════════════════════
   MORA02 PILOT — Dashboard Module (2026-03-20)
   ═══════════════════════════════════════════════════════════════
   Live service health checks via HTTP ping.
   ═══════════════════════════════════════════════════════════════ */

var dashServices = {
  llm: [
    { name: 'Qwen3-14B', url: 'http://mora02.local:8080/health', port: 8080, detail: '~15.5 GB VRAM' },
  ],
  services: [
    { name: 'Pilot Bot',     url: 'http://mora02.local:8098/health', port: 8098 },
    { name: 'Dify Web',      url: 'http://mora02.local:8190/',        port: 8190 },
    { name: 'Baserow',       url: 'http://mora02.local:8085/api/',   port: 8085 },
    { name: 'Script Runner',  url: 'http://mora02.local:8096/health', port: 8096 },
    { name: 'Knowledge API',  url: 'http://mora02.local:8095/health', port: 8095 },
    { name: 'Activepieces',   url: 'http://mora02.local:8089/',       port: 8089 },
    { name: 'SearXNG',        url: 'http://mora02.local:8094/',       port: 8094 },
  ],
  creative: [
    { name: 'ComfyUI',    url: 'http://mora02.local:8188/',  port: 8188 },
    { name: 'Penpot',     url: 'http://mora02.local:8101/',  port: 8101 },
    { name: 'Excalidraw', url: 'http://mora02.local:8102/',  port: 8102 },
  ],
  infra: [
    { name: 'nginx',      url: 'http://mora02.local:8092/health', port: 8092 },
    { name: 'Ollama',     url: 'http://mora02.local:11434/',       port: 11434 },
    { name: 'Open-WebUI', url: 'http://mora02.local:3000/',          port: 3000 },
  ],
};

/* ─── Init ──────────────────────────────────────────────────── */

function initDashboard() {
  dashRenderAll();
  dashCheckAll();
  dashRenderLLMProfiles();
  dashRenderTTSToggle();
}

/* ─── LLM Profile Switcher ─────────────────────────────────── */

var dashLLMSwitching = false;

async function dashRenderLLMProfiles() {
  var togglesEl = document.getElementById('dash-llm-toggles');
  var currentEl = document.getElementById('dash-llm-current');
  if (!togglesEl || !currentEl) return;

  // Ensure state is loaded
  if (!window.llmState || !window.llmState.loaded) {
    if (typeof llmLoadProfiles === 'function') {
      await llmLoadProfiles();
    }
  }

  var state = window.llmState || { profiles: [], current: null };
  var profiles = state.profiles || [];
  var current = state.current;

  if (!profiles.length) {
    togglesEl.innerHTML = '<div class="dash-llm-err">Could not load profiles from script-runner (port 8096). Is it running?</div>';
    currentEl.textContent = '';
    return;
  }

  // Current profile banner
  if (current) {
    var since = current.since ? ' · since ' + current.since : '';
    currentEl.innerHTML = 'Active: <strong>' + escapeHTML(current.label || current.name) +
      '</strong> <span class="dash-llm-meta">(' + escapeHTML(current.model || '') +
      ' · ' + escapeHTML(current.vram || '') + since + ')</span>';
  } else {
    currentEl.innerHTML = '<em>Active profile unknown — click a button to set one.</em>';
  }

  // Toggle buttons
  var html = '';
  profiles.forEach(function(p) {
    var isActive = current && current.name === p.name;
    html += '<button class="dash-llm-btn' + (isActive ? ' act' : '') + '"' +
      ' data-action="dash-llm-switch" data-profile="' + escapeHTML(p.name) + '"' +
      ' title="' + escapeHTML(p.description || '') + ' · ' + escapeHTML(p.vram || '') + '">' +
      '<span class="dash-llm-btn-lbl">' + escapeHTML(p.label) + '</span>' +
      '<span class="dash-llm-btn-cat">' + escapeHTML(p.category || '') + '</span>' +
      '</button>';
  });
  togglesEl.innerHTML = html;
}

async function dashLLMSwitch(profileName) {
  if (dashLLMSwitching) return;
  var statusEl = document.getElementById('dash-llm-status');
  var togglesEl = document.getElementById('dash-llm-toggles');
  if (!statusEl || !togglesEl) return;

  dashLLMSwitching = true;
  togglesEl.querySelectorAll('.dash-llm-btn').forEach(function(b) {
    b.setAttribute('disabled', 'disabled');
    if (b.dataset.profile === profileName) b.classList.add('switching');
  });
  statusEl.innerHTML = '<div style="display:flex;width:100%;justify-content:center;padding:40px 0"><div class="m2-loader-m" id="dash-m2-loader"></div></div>' +
    '<div style="text-align:center;color:var(--tx-muted);font-size:var(--fs-xs)">Switching to <strong>' + escapeHTML(profileName) + '</strong>… (up to ~4 min for cold loads)</div>';
  startM2(document.getElementById('dash-m2-loader'), 9, 35);

  try {
    var result = await llmSwitchProfile(profileName);
    stopM2();
    var dashLoader = document.getElementById('dash-m2-loader');
    if (dashLoader) dashLoader.innerHTML = '';
    if (result && result.ok) {
      statusEl.innerHTML = '<span class="dash-llm-ok">✓</span> Switched: ' + escapeHTML(result.message || 'ready');
    } else {
      var msg = (result && result.message) || 'unknown error';
      var html = '<span class="dash-llm-err">✗</span> ' + escapeHTML(msg);
      // If it's a VRAM problem, offer the Free GPU button inline
      if (/insufficient vram/i.test(msg)) {
        html += ' <button class="dash-llm-inline-btn" data-action="dash-vram-free-retry" data-profile="' + escapeHTML(profileName) + '">FREE GPU &amp; RETRY</button>';
      }
      statusEl.innerHTML = html;
    }
  } catch (e) {
    stopM2();
    var dashLoader2 = document.getElementById('dash-m2-loader');
    if (dashLoader2) dashLoader2.innerHTML = '';
    statusEl.innerHTML = '<span class="dash-llm-err">✗</span> ' + escapeHTML(e.message || String(e));
  } finally {
    dashLLMSwitching = false;
    await dashRenderLLMProfiles();
  }
}

/* ─── VRAM Free button ─────────────────────────────────────── */

async function dashFreeVRAM(retryProfile) {
  var statusEl = document.getElementById('dash-llm-status');
  if (!statusEl) return;

  statusEl.innerHTML = '<div style="display:flex;width:100%;justify-content:center;padding:40px 0"><div class="m2-loader-m" id="dash-vram-m2-loader"></div></div>' +
    '<div style="text-align:center;color:var(--tx-muted);font-size:var(--fs-xs)">Releasing GPU memory…</div>';
  startM2(document.getElementById('dash-vram-m2-loader'), 9, 35);

  try {
    var resp = await fetch(LLM_API_BASE + '/vram/free', { method: 'POST' });
    var data = await resp.json();

    stopM2();
    var vramLoader = document.getElementById('dash-vram-m2-loader');
    if (vramLoader) vramLoader.innerHTML = '';

    var parts = [];
    if (data.results) {
      Object.keys(data.results).forEach(function(svc) {
        var r = data.results[svc];
        var mark = r.ok ? '✓' : '✗';
        parts.push(svc + ' ' + mark + (r.message ? ' (' + r.message + ')' : ''));
      });
    }
    var summary = parts.length ? parts.join(', ') : 'no services responded';

    if (data.success) {
      statusEl.innerHTML = '<span class="dash-llm-ok">✓</span> GPU released: ' + escapeHTML(summary);
    } else {
      statusEl.innerHTML = '<span class="dash-llm-err">✗</span> ' + escapeHTML(summary);
    }
  } catch (e) {
    stopM2();
    var vramLoader2 = document.getElementById('dash-vram-m2-loader');
    if (vramLoader2) vramLoader2.innerHTML = '';
    statusEl.innerHTML = '<span class="dash-llm-err">✗</span> ' + escapeHTML(e.message || String(e));
    return;
  }

  // Optional: chain into a retry of a failed profile switch
  if (retryProfile) {
    // small pause so the user sees the release status before the retry blurb
    await new Promise(function(r) { setTimeout(r, 800); });
    await dashLLMSwitch(retryProfile);
  }
}

function escapeHTML(s) {
  return String(s == null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

/* ─── Render cards (grey = checking) ────────────────────────── */

function dashRenderAll() {
  dashRenderGroup('dash-llm', dashServices.llm);
  dashRenderGroup('dash-services', dashServices.services);
  dashRenderGroup('dash-creative', dashServices.creative);
  dashRenderGroup('dash-infra', dashServices.infra);
}

function dashRenderGroup(containerId, services) {
  var el = document.getElementById(containerId);
  if (!el) return;

  var html = '';
  services.forEach(function(svc) {
    html +=
      '<div class="dash-card" id="dash-' + svc.port + '">' +
        '<div class="dash-dot dash-checking"></div>' +
        '<div class="dash-info">' +
          '<span class="dash-name">' + svc.name + '</span>' +
          '<span class="dash-detail">Port ' + svc.port + (svc.detail ? ' · ' + svc.detail : '') + '</span>' +
        '</div>' +
      '</div>';
  });
  el.innerHTML = html;
}

/* ─── Health checks ─────────────────────────────────────────── */

function dashCheckAll() {
  var all = [].concat(dashServices.llm, dashServices.services, dashServices.creative, dashServices.infra);
  all.forEach(function(svc) {
    dashCheck(svc);
  });
}

function dashCheck(svc) {
  var card = document.getElementById('dash-' + svc.port);
  if (!card) return;
  var dot = card.querySelector('.dash-dot');

  var controller = new AbortController();
  var timeout = setTimeout(function() { controller.abort(); }, 4000);

  fetch(svc.url, { mode: 'no-cors', signal: controller.signal })
    .then(function() {
      clearTimeout(timeout);
      if (dot) { dot.className = 'dash-dot dash-online'; }
    })
    .catch(function() {
      clearTimeout(timeout);
      if (dot) { dot.className = 'dash-dot dash-offline'; }
    });
}

/* ─── TTS Engine Toggle (Chatterbox) ───────────────────────── */

var KNOWLEDGE_API_DASH = 'http://mora02.local:8095';
var dashTTSBusy = false;

async function dashRenderTTSToggle() {
  var togglesEl = document.getElementById('dash-tts-toggles');
  var currentEl = document.getElementById('dash-tts-current');
  if (!togglesEl || !currentEl) return;

  try {
    var r = await fetch(KNOWLEDGE_API_DASH + '/tts/chatterbox/status');
    var data = await r.json();
    var running = data.running && data.healthy;
    var starting = data.running && !data.healthy;

    if (running) {
      currentEl.innerHTML = 'Chatterbox: <strong style="color:var(--c-green)">ACTIVE</strong> <span class="dash-llm-meta">(GPU · multilingual · voice cloning)</span>';
    } else if (starting) {
      currentEl.innerHTML = 'Chatterbox: <strong style="color:var(--c-orange)">STARTING...</strong> <span class="dash-llm-meta">(model warmup)</span>';
    } else {
      currentEl.innerHTML = 'Chatterbox: <strong style="color:var(--tx-muted)">OFF</strong> <span class="dash-llm-meta">(click to start · ~4 GB VRAM)</span>';
    }

    togglesEl.innerHTML =
      '<button class="dash-llm-btn' + (running ? ' act' : '') + '"' +
      ' data-action="dash-tts-toggle" style="' + (running ? 'border-color:var(--c-green)' : '') + '">' +
      '<span class="dash-llm-btn-lbl">' + (running ? 'STOP' : 'START') + ' CHATTERBOX</span>' +
      '<span class="dash-llm-btn-cat">Quality TTS · ~4 GB VRAM</span>' +
      '</button>';
  } catch (e) {
    currentEl.textContent = 'Chatterbox: status unknown';
    togglesEl.innerHTML = '';
  }
}

async function dashTTSToggle() {
  if (dashTTSBusy) return;
  dashTTSBusy = true;

  var statusEl = document.getElementById('dash-tts-status');
  var togglesEl = document.getElementById('dash-tts-toggles');
  if (togglesEl) togglesEl.querySelectorAll('.dash-llm-btn').forEach(function(b) { b.setAttribute('disabled', 'disabled'); });

  try {
    // Check current state
    var sr = await fetch(KNOWLEDGE_API_DASH + '/tts/chatterbox/status');
    var state = await sr.json();
    var isRunning = state.running;

    var action = isRunning ? 'stop' : 'start';
    if (statusEl) statusEl.innerHTML = isRunning
      ? 'Stopping Chatterbox...'
      : 'Starting Chatterbox (model warmup ~1-2 min)...';

    var r = await fetch(KNOWLEDGE_API_DASH + '/tts/chatterbox/' + action, { method: 'POST' });
    var data = await r.json();

    if (data.status === 'ok') {
      if (statusEl) statusEl.innerHTML = '<span class="dash-llm-ok">\u2713</span> ' + data.message;

      // If starting, poll until healthy
      if (action === 'start') {
        var attempts = 0;
        var maxAttempts = 60; // 2 min
        var pollInterval = setInterval(async function() {
          attempts++;
          try {
            var pr = await fetch(KNOWLEDGE_API_DASH + '/tts/chatterbox/status');
            var ps = await pr.json();
            if (ps.healthy) {
              clearInterval(pollInterval);
              if (statusEl) statusEl.innerHTML = '<span class="dash-llm-ok">\u2713</span> Chatterbox ready!';
              dashTTSBusy = false;
              dashRenderTTSToggle();
            } else if (attempts >= maxAttempts) {
              clearInterval(pollInterval);
              if (statusEl) statusEl.innerHTML = '<span class="dash-llm-err">\u2717</span> Chatterbox timeout — check logs';
              dashTTSBusy = false;
              dashRenderTTSToggle();
            }
          } catch (e) {
            // keep polling
          }
        }, 2000);
        return; // don't reset dashTTSBusy yet
      }
    } else {
      if (statusEl) statusEl.innerHTML = '<span class="dash-llm-err">\u2717</span> ' + (data.message || 'Error');
    }
  } catch (e) {
    if (statusEl) statusEl.innerHTML = '<span class="dash-llm-err">\u2717</span> ' + e.message;
  }

  dashTTSBusy = false;
  dashRenderTTSToggle();
}

/* ─── Events ────────────────────────────────────────────────── */

document.addEventListener('click', function(e) {
  var t = e.target.closest('[data-action]');
  if (!t) return;
  if (t.dataset.action === 'dash-refresh') {
    dashRenderAll();
    dashCheckAll();
    dashRenderLLMProfiles();
    dashRenderTTSToggle();
  }
  if (t.dataset.action === 'dash-llm-switch') {
    var profile = t.dataset.profile;
    if (profile) dashLLMSwitch(profile);
  }
  if (t.dataset.action === 'dash-tts-toggle') {
    dashTTSToggle();
  }
  if (t.dataset.action === 'dash-vram-free') {
    dashFreeVRAM();
  }
  if (t.dataset.action === 'dash-vram-free-retry') {
    dashFreeVRAM(t.dataset.profile);
  }
});
