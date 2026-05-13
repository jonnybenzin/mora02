/* ═══════════════════════════════════════════════════════════════
   MORA02 PILOT — App Controller
   ═══════════════════════════════════════════════════════════════
   Handles: Sidebar, Routing, Event Delegation, Session Init.
   No inline onclick — all events via data-action attributes.
   ═══════════════════════════════════════════════════════════════ */

const API_BASE = 'http://mora02.local:8098';
const CONTENT = document.getElementById('content');

let sessionId = null;
let activePage = 'home';
let homeHTML = null; // cached homepage content

/* ─── SESSION ───────────────────────────────────────────────── */

async function initSession() {
  try {
    const resp = await fetch(`${API_BASE}/session/create`, { method: 'POST' });
    const data = await resp.json();
    sessionId = data.session_id;
    console.log('Session:', sessionId);
  } catch (e) {
    console.warn('Backend not available — UI-only mode');
  }
}

/* ─── ROUTING ───────────────────────────────────────────────── */

function animateContent() {
  CONTENT.style.opacity = '0';
  CONTENT.style.transform = 'scale(0.97)';
  requestAnimationFrame(function() {
    CONTENT.style.transition = 'opacity var(--anim-duration-med) var(--anim-ease-out), transform var(--anim-duration-med) var(--anim-ease-out)';
    CONTENT.style.opacity = '1';
    CONTENT.style.transform = 'scale(1)';
    setTimeout(function() { CONTENT.style.transition = ''; }, 300);
  });
}

var autoFocusMap = {
  'chat':             '#chat-input',
  'imagegen':         '#img-prompt',
  'expander':         '#exp-prompt',
  'video-generate':   '#vid-prompt',
  'musicgen':         '#mus-tags',
  'ttsgen':           '#tts-text',
  'typer':            '#typer-text',
  'pixeltext':        '#px-words',
  'post':             '#post-name',
  'wiki':             '#wiki-search',
  'persona-create':   '#pc-name',
};

function autoFocusPage(page) {
  var sel = autoFocusMap[page];
  if (!sel) return;
  setTimeout(function() {
    var el = document.querySelector(sel);
    if (el) el.focus();
  }, 80);
}

async function navigate(page) {
  if (page === activePage) return;

  // Cache homepage on first leave
  if (activePage === 'home' && !homeHTML) {
    homeHTML = CONTENT.innerHTML;
  }

  // Load page
  if (page === 'home') {
    CONTENT.innerHTML = homeHTML; animateContent();
    CONTENT.className = 'pg-home';
    initLogo(); // re-init interactive logo
    setTimeout(function() { var hi = document.querySelector('.home-inp'); if (hi) hi.focus(); }, 80);
  } else {
    try {
      const resp = await fetch(`pages/${page}.html`);
      if (resp.ok) {
        CONTENT.innerHTML = await resp.text(); animateContent();
        CONTENT.className = 'pg-content';
        if (page === 'chat') initChat();
        if (typeof initToolPage === 'function') initToolPage(page);
        if (page === 'imagegen' && typeof initImageGen === 'function') initImageGen();
        if (page === 'expander' && typeof initExpander === 'function') initExpander();
        if (page === 'video-generate' && typeof initVideoGen === 'function') initVideoGen();
        if (page === 'ttsgen' && typeof initTtsGen === 'function') initTtsGen();
        if (page === 'musicgen' && typeof initMusicGen === 'function') initMusicGen();
        if (typeof initSettingsPage === 'function') initSettingsPage(page);
        if (page === "files" && typeof initFiles === "function") initFiles();
        if (page === "wiki" && typeof initWiki === "function") initWiki();
        if (page === "dashboard" && typeof initDashboard === "function") initDashboard();
        if (page === "styleguide" && typeof initStyleGuide === "function") initStyleGuide();
        if (page === "xray") initXray();
        // Auto-focus primary input field
        autoFocusPage(page);
      } else {
        CONTENT.innerHTML = `<div class="pg-placeholder"><h2>${page.toUpperCase()}</h2><p>Coming soon</p></div>`; animateContent();
        CONTENT.className = 'pg-content';
      }
    } catch (e) {
      CONTENT.innerHTML = `<div class="pg-placeholder"><h2>${page.toUpperCase()}</h2><p>Page not found</p></div>`; animateContent();
      CONTENT.className = 'pg-content';
    }
  }

  activePage = page;

  // Update active state in sidebar
  document.querySelectorAll('.mi[data-action="navigate"]').forEach(mi => {
    mi.classList.toggle('act', mi.dataset.page === page);
  });
}

/* ─── SIDEBAR ───────────────────────────────────────────────── */

function toggleSidebar() {
  const sb = document.getElementById('sb');
  const tog = document.getElementById('tog');
  sb.classList.toggle('c');
  const collapsed = sb.classList.contains('c');
  tog.innerHTML = collapsed
    ? '<svg fill="currentColor"><use href="icons/sprite.svg#i-arrow-r"/></svg>'
    : '<svg fill="currentColor"><use href="icons/sprite.svg#i-arrow-l"/></svg>';
}
function toggleSection(header) {

  var sec = header.closest('.sec');
  var opening = !sec.classList.contains("open");
  sec.classList.toggle('open');
  if (opening) {
    sec.querySelectorAll('.sec-body > .mi, .sec-body > .p-sub .p-sub-i').forEach(function(mi, i) {
      mi.style.opacity = '0';
      mi.style.transform = 'translateY(-8px)';
      setTimeout(function() {
        mi.style.transition = 'opacity var(--anim-duration-med) var(--anim-ease-out), transform var(--anim-duration-med) var(--anim-ease-out)';
        mi.style.opacity = '1';
        mi.style.transform = 'translateY(0)';
        setTimeout(function() { mi.style.transition = ''; mi.style.transform = ''; }, 300);
      }, i * 30);
    });
  }
}

function selectLLM(item) {
  const color = item.dataset.color;
  const model = item.dataset.model;

  // Update active in all LLM lists (open + collapsed flyout)
  document.querySelectorAll('[data-action="select-llm"]').forEach(mi => {
    mi.classList.remove('act');
    const lbl = mi.querySelector('.mi-lbl');
    if (lbl) lbl.style.color = '';
  });

  // Activate clicked + matching model in other list
  document.querySelectorAll(`[data-action="select-llm"][data-model="${model}"]`).forEach(mi => {
    mi.classList.add('act');
    const lbl = mi.querySelector('.mi-lbl');
    if (lbl) lbl.style.color = `var(--${color})`;
  });

  // Update section header + collapsed icon
  const hd = document.getElementById('hd-llm');
  const si = document.getElementById('si-llm');
  // if (hd) hd.style.color = removed
  if (si) si.style.color = `var(--${color})`;

  // Update send button color
  document.querySelectorAll('.chat-btn-send').forEach(function(btn) {
    btn.style.background = 'var(--' + color + ')';
  });

  // Navigate to chat
  navigate('chat');

  // Tell backend
  if (sessionId) {
    fetch(`${API_BASE}/session/${sessionId}/model`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ model }),
    }).catch(() => {});
  }
}

function selectInSection(item) {
  const body = item.closest('.sec-body') || item.closest('.si-fly-in');
  if (body) {
    body.querySelectorAll('.mi').forEach(mi => mi.classList.remove('act'));
  }
  item.classList.add('act');
}

/* ─── EVENT DELEGATION ──────────────────────────────────────── */

document.addEventListener('click', function(e) {
  const target = e.target.closest('[data-action]');
  if (!target) return;

  const action = target.dataset.action;

  switch (action) {
    case 'toggle-sidebar':
      toggleSidebar();
      break;

    case 'toggle-section':
      toggleSection(target);
      break;

    case 'select-llm':
      selectLLM(target);
      break;

    case 'select-persona':
      selectPersona(target);
      selectInSection(target);
      break;

    case 'home-attach':
      window._pendingAttach = true;
      navigate('chat');
      break;

    case 'home-send':
      var homeInput = document.querySelector('.home-inp');
      if (homeInput && homeInput.value.trim()) {
        window._pendingChatMessage = homeInput.value.trim();
        navigate('chat');
      }
      break;

    case 'navigate':
      navigate(target.dataset.page);
      break;

    case 'external':
      window.open(target.dataset.url, '_blank');
      break;

    case 'open-mobile':
      if(document.querySelector('.app').classList.contains('mob-open')){closeMob();return}
      openMob();
      break;

    case 'close-mobile':
      closeMob();
      break;

    case 'open-feedback':
      fbOpen();
      break;

    case 'close-feedback':
      fbClose();
      break;

    case 'fb-capture':
      fbCapture();
      break;

    case 'fb-remove-screenshot':
      fbRemoveScreenshot();
      break;

    case 'fb-submit':
      fbSubmit();
      break;
  }
});

// Close mobile overlay on backdrop click
// Close menu: tap anywhere outside drawer OR tap close button
document.addEventListener('click', function(e) {
  var ov = document.getElementById('mob-ov');
  if (!ov || !ov.classList.contains('open')) return;
  // Tap on overlay background (not inside drawer)
  if (e.target === ov || e.target.closest('.mob-close')) {
    closeMob();
  }
});

// Home input: command palette + Enter to navigate to chat
(function() {
  function wireHomePalette() {
    var inp = document.querySelector('.home-inp');
    var pal = document.getElementById('home-cmd-palette');
    if (inp && pal && !inp._cmdWired) {
      inp._cmdWired = true;
      inp.addEventListener('input', function() {
        if (typeof cmdPaletteRender === 'function') cmdPaletteRender(inp, pal);
      });
    }
  }
  wireHomePalette();
  // Re-wire after navigation back to home
  var _origNav = window.navigate;
  if (_origNav) {
    window.navigate = function() {
      _origNav.apply(this, arguments);
      setTimeout(wireHomePalette, 100);
    };
  }
})();

document.addEventListener('keydown', function(e) {
  if (e.target.classList.contains('home-inp')) {
    if (typeof cmdPaletteIsOpen === 'function' && cmdPaletteIsOpen()) {
      if (e.key === 'ArrowUp')   { e.preventDefault(); cmdPaletteNav('up'); return; }
      if (e.key === 'ArrowDown') { e.preventDefault(); cmdPaletteNav('down'); return; }
      if (e.key === 'Tab' || (e.key === 'Enter' && !e.shiftKey)) {
        if (cmdActiveIdx >= 0) { e.preventDefault(); cmdPaletteSelect(cmdActiveIdx); return; }
      }
      if (e.key === 'Escape') { e.preventDefault(); cmdPaletteClose(); return; }
    }
    if (e.key === 'Enter') {
      e.preventDefault();
      var text = e.target.value.trim();
      if (text) {
        window._pendingChatMessage = text;
        navigate('chat');
      }
    }
  }
});

/* ─── INIT ──────────────────────────────────────────────────── */

initSession().then(function() {
  if (typeof loadMonthlyCost === "function") loadMonthlyCost();
  if (typeof llmLoadProfiles === "function") llmLoadProfiles();
  if (typeof bucketInitDelegation === "function") bucketInitDelegation();
});

/* ─── MOBILE MENU ──────────────────────────────────────────── */
function openMob() {
  var drawer = document.getElementById('mob-menu-content');
  var scroll = document.querySelector('.sb-scroll');
  var foot = document.querySelector('.sb-foot');
  if (drawer && scroll) {
    drawer.innerHTML = scroll.innerHTML;
    if (foot) drawer.innerHTML += foot.innerHTML;
  }
  // Pure overlay — do NOT push .app with transform
  document.getElementById('mob-ov').classList.add('open');
  document.body.style.overflow = 'hidden';
  // Re-wire data-action clicks inside cloned drawer
  drawer.querySelectorAll('[data-action]').forEach(function(el) {
    el.addEventListener('click', function(e) {
      closeMob();
    });
  });
}

function closeMob() {
  document.getElementById('mob-ov').classList.remove('open');
  document.body.style.overflow = '';
}

/* ─── CHAT: Scroll to bottom button ───────────────────────── */
setInterval(function() {
  var msgs = document.getElementById('chat-messages');
  var btn = document.getElementById('chat-scroll-btn');
  if (!msgs || !btn) return;
  btn.style.display = (msgs.scrollHeight - msgs.scrollTop - msgs.clientHeight < 100) ? 'none' : 'flex';
}, 300);

/* ─── PERSONAS (dynamic from backend) ───────────────────────── */

var activePersonaId = null;

async function loadPersonas() {
  try {
    var resp = await fetch(API_BASE + '/personas');
    if (!resp.ok) return;
    var personas = await resp.json();

    var listEl = document.getElementById('persona-list');
    var flyEl = document.getElementById('persona-fly');
    if (!listEl) return;

    var html = '';
    var flyHtml = '';

    // "Neutral" = no persona
    html += '<div class="mi' + (activePersonaId === null ? ' act' : '') + '" data-action="select-persona" data-persona-id="null">' +
      '<div class="mi-l"><div class="mi-ico"><svg fill="currentColor"><use href="icons/sprite.svg#i-persona"/></svg></div>' +
      '<span class="mi-lbl">NEUTRAL</span></div></div>';
    flyHtml += '<div class="mi' + (activePersonaId === null ? ' act' : '') + '" data-action="select-persona" data-persona-id="null">' +
      '<div class="mi-l"><span class="mi-lbl">NEUTRAL</span></div></div>';

    personas.forEach(function(p) {
      var isActive = activePersonaId === p.id;
      html += '<div class="mi' + (isActive ? ' act' : '') + '" data-action="select-persona" data-persona-id="' + p.id + '">' +
        '<div class="mi-l"><div class="mi-ico">' + p.icon + '</div>' +
        '<span class="mi-lbl">' + p.name.toUpperCase() + '</span></div></div>';
      flyHtml += '<div class="mi' + (isActive ? ' act' : '') + '" data-action="select-persona" data-persona-id="' + p.id + '">' +
        '<div class="mi-l"><span class="mi-lbl">' + p.name.toUpperCase() + '</span></div></div>';
    });

    // Sub-links
    html += '<div class="p-sub">' +
      '<div class="p-sub-i" data-action="navigate" data-page="persona-settings">▸ ADJUST SETTINGS</div>' +
      '<div class="p-sub-i" data-action="navigate" data-page="persona-create">+ CREATE NEW PERSONA</div></div>';

    listEl.innerHTML = html;
    if (flyEl) flyEl.innerHTML = flyHtml;

  } catch (e) {
    console.warn('Could not load personas:', e);
  }
}

async function selectPersona(item) {
  var idStr = item.dataset.personaId;
  var personaId = (idStr === 'null' || !idStr) ? null : parseInt(idStr);

  // Visual update: both open + collapsed
  document.querySelectorAll('[data-action="select-persona"]').forEach(function(mi) {
    mi.classList.toggle('act', mi.dataset.personaId === idStr);
  });

  activePersonaId = personaId;
  if (activePage === "persona-settings" && typeof initPersonaSettings === "function") initPersonaSettings();

  // Backend call
  if (sessionId) {
    if (personaId === null) {
      fetch(API_BASE + '/session/' + sessionId + '/persona', { method: 'DELETE' }).catch(function(){});
    } else {
      fetch(API_BASE + '/session/' + sessionId + '/persona', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ persona_id: personaId }),
      }).catch(function(){});
    }
  }
}

/* ─── FEEDBACK / BUG REPORTER ──────────────────────────────── */

var fbScreenshotData = null;

function fbOpen() {
  var ov = document.getElementById('fb-overlay');
  if (!ov) return;
  ov.classList.add('fb-open');

  // Reset form
  var desc = document.getElementById('fb-desc');
  if (desc) desc.value = '';
  var typeEl = document.getElementById('fb-type');
  if (typeEl) typeEl.value = 'bug';
  var sevEl = document.getElementById('fb-severity');
  if (sevEl) sevEl.value = 'medium';
  fbRemoveScreenshot();

  // Fill meta info
  fbUpdateMeta();
}

function fbClose() {
  var ov = document.getElementById('fb-overlay');
  if (ov) ov.classList.remove('fb-open');
}

function fbUpdateMeta() {
  var el = document.getElementById('fb-meta');
  if (!el) return;
  var parts = [];
  parts.push('Page: ' + (activePage || 'home'));
  parts.push('Session: ' + (sessionId || 'n/a'));
  // Get current model from active LLM item
  var activeModel = document.querySelector('[data-action="select-llm"].act');
  var modelName = activeModel ? (activeModel.dataset.model || '?') : '?';
  parts.push('Model: ' + modelName);
  // Persona
  var personaName = 'neutral';
  if (activePersonaId) {
    var personaEl = document.querySelector('[data-action="select-persona"].act .mi-lbl');
    if (personaEl) personaName = personaEl.textContent.toLowerCase();
  }
  parts.push('Persona: ' + personaName);
  el.textContent = parts.join(' · ');
}

async function fbCapture() {
  var statusEl = document.getElementById('fb-screenshot-status');
  if (statusEl) statusEl.textContent = 'Capturing...';

  // Hide the feedback overlay temporarily so it's not in the screenshot
  var ov = document.getElementById('fb-overlay');
  if (ov) ov.style.display = 'none';
  var floatBtn = document.getElementById('fb-float');
  if (floatBtn) floatBtn.style.display = 'none';

  try {
    // Small delay to let DOM repaint without the overlay
    await new Promise(function(r) { setTimeout(r, 100); });

    if (typeof html2canvas !== 'function') {
      if (statusEl) statusEl.textContent = 'html2canvas not loaded';
      return;
    }

    var canvas = await html2canvas(document.body, {
      scale: 1,
      useCORS: true,
      logging: false,
      backgroundColor: '#000',
    });

    fbScreenshotData = canvas.toDataURL('image/png');

    // Show preview
    var preview = document.getElementById('fb-screenshot-preview');
    var img = document.getElementById('fb-screenshot-img');
    if (preview && img) {
      img.src = fbScreenshotData;
      preview.style.display = 'block';
    }
    if (statusEl) statusEl.textContent = '';
  } catch (e) {
    console.error('Screenshot failed:', e);
    if (statusEl) statusEl.textContent = 'Failed — try manual upload';
  } finally {
    // Restore overlay
    if (ov) { ov.style.display = ''; }
    if (floatBtn) { floatBtn.style.display = ''; }
  }
}

function fbRemoveScreenshot() {
  fbScreenshotData = null;
  var preview = document.getElementById('fb-screenshot-preview');
  if (preview) preview.style.display = 'none';
  var statusEl = document.getElementById('fb-screenshot-status');
  if (statusEl) statusEl.textContent = '';
}

async function fbSubmit() {
  var desc = document.getElementById('fb-desc');
  var text = desc ? desc.value.trim() : '';
  if (!text) {
    var statusEl = document.getElementById('fb-screenshot-status');
    if (statusEl) statusEl.textContent = 'Please add a description';
    return;
  }

  var submitBtn = document.querySelector('[data-action="fb-submit"]');
  if (submitBtn) { submitBtn.disabled = true; submitBtn.textContent = 'SENDING...'; }

  // Gather current model
  var activeModel = document.querySelector('[data-action="select-llm"].act');
  var modelName = activeModel ? (activeModel.dataset.model || '') : '';

  // Gather current persona
  var personaName = '';
  if (activePersonaId) {
    var personaEl = document.querySelector('[data-action="select-persona"].act .mi-lbl');
    if (personaEl) personaName = personaEl.textContent;
  }

  var payload = {
    type: document.getElementById('fb-type').value,
    severity: document.getElementById('fb-severity').value,
    description: text,
    page: activePage || 'home',
    session_id: sessionId || '',
    model: modelName,
    persona: personaName,
  };

  if (fbScreenshotData) {
    payload.screenshot = fbScreenshotData;
  }

  try {
    var resp = await fetch(API_BASE + '/feedback', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    var data = await resp.json();
    if (data.success) {
      // Brief success state then close
      if (submitBtn) { submitBtn.textContent = 'SENT!'; }
      setTimeout(function() { fbClose(); }, 600);
    } else {
      if (submitBtn) { submitBtn.textContent = 'ERROR — TRY AGAIN'; }
    }
  } catch (e) {
    console.error('Feedback submit failed:', e);
    if (submitBtn) { submitBtn.textContent = 'ERROR — TRY AGAIN'; }
  } finally {
    setTimeout(function() {
      if (submitBtn) { submitBtn.disabled = false; submitBtn.textContent = 'SEND FEEDBACK'; }
    }, 2000);
  }
}

// Close on backdrop click
document.addEventListener('click', function(e) {
  var ov = document.getElementById('fb-overlay');
  if (ov && e.target === ov) fbClose();
});

// Close on Escape
document.addEventListener('keydown', function(e) {
  if (e.key === 'Escape') {
    var ov = document.getElementById('fb-overlay');
    if (ov && ov.classList.contains('fb-open')) fbClose();
  }
});

// Load on startup
loadPersonas();
