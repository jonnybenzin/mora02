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
  } else {
    try {
      const resp = await fetch(`pages/${page}.html`);
      if (resp.ok) {
        CONTENT.innerHTML = await resp.text(); animateContent();
        CONTENT.className = 'pg-content';
        if (page === 'chat') initChat();
        if (typeof initToolPage === 'function') initToolPage(page);
        if (page === 'imagegen' && typeof initImageGen === 'function') initImageGen();
        if (typeof initSettingsPage === 'function') initSettingsPage(page);
        if (page === "files" && typeof initFiles === "function") initFiles();
        if (page === "wiki" && typeof initWiki === "function") initWiki();
        if (page === "dashboard" && typeof initDashboard === "function") initDashboard();
        if (page === "styleguide" && typeof initStyleGuide === "function") initStyleGuide();
        if (page === "xray") initXray();
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
      break;
  }
});

// Close mobile overlay on backdrop click
document.getElementById('mob-ov')?.addEventListener('click', function(e) {
  if (e.target === this) this.classList.remove('open');
});

// Home input: Enter to navigate to chat
document.addEventListener('keydown', function(e) {
  if (e.target.classList.contains('home-inp') && e.key === 'Enter') {
    e.preventDefault();
    const text = e.target.value.trim();
    if (text) {
      // Navigate to chat and send the message
      window._pendingChatMessage = text;
      navigate('chat');
    }
  }
});

/* ─── INIT ──────────────────────────────────────────────────── */

initSession().then(function() { if (typeof loadMonthlyCost === "function") loadMonthlyCost(); });

/* ─── MOBILE MENU ──────────────────────────────────────────── */
function openMob() {
  var drawer = document.getElementById('mob-menu-content');
  var scroll = document.querySelector('.sb-scroll');
  var foot = document.querySelector('.sb-foot');
  if (drawer && scroll) {
    drawer.innerHTML = scroll.innerHTML;
    if (foot) drawer.innerHTML += foot.innerHTML;
  }
  document.querySelector('.app').classList.add('mob-open');
  document.getElementById('mob-ov').classList.add('open');
}

function closeMob() {
  document.querySelector('.app').classList.remove('mob-open');
  document.getElementById('mob-ov').classList.remove('open');
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

// Load on startup
loadPersonas();
