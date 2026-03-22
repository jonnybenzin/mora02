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

/* ─── Events ────────────────────────────────────────────────── */

document.addEventListener('click', function(e) {
  var t = e.target.closest('[data-action]');
  if (!t) return;
  if (t.dataset.action === 'dash-refresh') {
    dashRenderAll();
    dashCheckAll();
  }
});
