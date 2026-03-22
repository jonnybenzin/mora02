/* ═══════════════════════════════════════════════════════════════
   MORA02 PILOT — Chat Module v3 (Clean Rewrite 2026-03-18)
   ═══════════════════════════════════════════════════════════════
   SSE Streaming · Markdown (marked.js) · Code Blocks · Lightbox
   Image Attachment · Slash-Command Responses · Persona · Stats
   ───────────────────────────────────────────────────────────────
   Depends on: app.js (API_BASE, sessionId, initSession)
               marked.min.js (optional, has basic fallback)
   ═══════════════════════════════════════════════════════════════ */

/* ─── STATE ─────────────────────────────────────────────────── */

var isStreaming      = false;
var currentStreamEl  = null;
var streamFullText   = '';
var abortController  = null;
var attachedImage    = null;
var attachedFileName = null;

/* ═══════════════════════════════════════════════════════════════
   INIT
   ═══════════════════════════════════════════════════════════════ */

function initChat() {
  var msgs = document.getElementById('chat-messages');
  if (!msgs) return;

  msgs.innerHTML = '';

  if (typeof marked !== 'undefined') {
    marked.setOptions({ breaks: true, gfm: true, headerIds: false, mangle: false });
  }

  var input = document.getElementById('chat-input');
  if (input) {
    input.addEventListener('input', function() { autoResizeInput(input); });
    input.addEventListener('keydown', handleChatKeydown);
    input.focus();
  }

  setupScrollObserver();
  syncSendButtonColor();

  if (window._pendingChatMessage) {
    var pending = window._pendingChatMessage;
    delete window._pendingChatMessage;
    var inp = document.getElementById('chat-input');
    if (inp) {
      inp.value = pending;
      setTimeout(function() { sendChatMessage(); }, 100);
    }
  }

  // Open file picker if triggered from homepage
  if (window._pendingAttach) {
    delete window._pendingAttach;
    setTimeout(function() { handleFileAttach(); }, 200);
  }
  console.log('Chat initialized, session:', sessionId);
}

/* ═══════════════════════════════════════════════════════════════
   SEND MESSAGE
   ═══════════════════════════════════════════════════════════════ */

async function sendChatMessage() {
  var input = document.getElementById('chat-input');
  if (!input) return;

  var text = input.value.trim();
  if (!text || isStreaming) return;

  if (!sessionId) {
    addSystemMessage('No session — reconnecting...');
    await initSession();
    if (!sessionId) { addSystemMessage('Backend not available.'); return; }
  }

  input.value = '';
  autoResizeInput(input);
  addUserMessage(text);
  showTyping(true);
  isStreaming = true;
  updateSendButton(false);

  var imageData = getAttachedImage();
  clearAttachment();

  try {
    abortController = new AbortController();
    var payload = { message: text };
    if (imageData) payload.image = imageData;

    var resp = await fetch(API_BASE + '/chat/' + sessionId, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
      signal: abortController.signal,
    });

    var ct = resp.headers.get('content-type') || '';

    if (ct.includes('text/event-stream')) {
      await handleSSEStream(resp);
    } else {
      showTyping(false);
      handleJSONResponse(await resp.json());
    }
  } catch (err) {
    showTyping(false);
    if (err.name !== 'AbortError') addSystemMessage('Error: ' + err.message);
  }

  isStreaming = false;
  abortController = null;
  updateSendButton(true);
  updateStats();
}

/* ═══════════════════════════════════════════════════════════════
   SSE STREAM
   ═══════════════════════════════════════════════════════════════ */

async function handleSSEStream(resp) {
  var reader = resp.body.getReader();
  var decoder = new TextDecoder();
  var shell = createBotMessageShell();

  currentStreamEl = shell.bodyEl;
  streamFullText = '';
  showTyping(false);

  var buffer = '';
  var model = null;

  while (true) {
    var chunk = await reader.read();
    if (chunk.done) break;

    buffer += decoder.decode(chunk.value, { stream: true });
    var lines = buffer.split('\n');
    buffer = lines.pop();

    for (var i = 0; i < lines.length; i++) {
      if (lines[i].startsWith('data: ')) {
        try {
          var data = JSON.parse(lines[i].slice(6));
          if (data.content) {
            streamFullText += data.content;
            renderMarkdown(currentStreamEl, streamFullText);
            scrollToBottom();
          }
          if (data.model) model = data.model;
        } catch (e) {}
      }
    }
  }

  /* Finalize: model badge */
  if (model) {
    var head = shell.el.querySelector('.msg-model');
    if (head) {
      head.textContent = model.toUpperCase();
      head.style.color = 'var(--m-' + model + ', var(--tx-muted))';
    }
    shell.el.setAttribute('data-model', model);
  }

  /* Finalize: persona */
  var persona = getActivePersona();
  if (persona) {
    var headDiv = shell.el.querySelector('.msg-head');
    if (headDiv) {
      var span = document.createElement('span');
      span.className = 'msg-persona';
      span.textContent = persona;
      var timeEl = headDiv.querySelector('.msg-time');
      if (timeEl) headDiv.insertBefore(span, timeEl);
    }
  }

  /* Finalize: action buttons + code blocks */
  shell.el.insertAdjacentHTML('beforeend', msgActionsHTML());
  wrapCodeBlocks(currentStreamEl);
  currentStreamEl = null;
}

/* ═══════════════════════════════════════════════════════════════
   JSON RESPONSE HANDLER (slash commands, tools)
   ═══════════════════════════════════════════════════════════════ */

function handleJSONResponse(data) {
  var model = data.model || 'system';

  switch (data.type) {
    case 'command_result':   addBotMessage(data.result, model, true); break;
    case 'stock_results':    renderStockResults(data); break;
    case 'script_result':    renderScriptResult(data); break;
    case 'image_variants':
    case 'comfyui_result':   renderComfyResult(data); break;
    case 'search_results':   renderSearchResults(data); break;
    case 'session_done':     addSystemMessage(data.result || 'Session ended.'); break;
    case 'error':            addSystemMessage('Error: ' + (data.error || data.message || 'Unknown')); break;
    default:
      if (data.result)       addBotMessage(data.result, model, true);
      else if (data.answer)  addBotMessage(data.answer, model, false);
      else                   addBotMessage(JSON.stringify(data, null, 2), model, true);
  }
}

/* ── Stock Images ──────────────────────────────────────────── */

function renderStockResults(data) {
  var persona = getActivePersona();
  var m = (data.model || 'script-runner').toUpperCase();
  var html = msgHeadHTML(m, 'var(--tx-muted)', persona) +
    '<div class="msg-body"><p>Found ' + (data.results || []).length +
    ' results for "' + escapeHTML(data.query || '') + '":</p><div class="stock-grid">';
  (data.results || []).forEach(function(img) {
    html += '<div class="stock-item" data-fullurl="' + img.url + '">' +
      '<img src="' + img.thumbnail + '" alt="' + escapeHTML(img.photographer || '') + '" loading="lazy">' +
      '<div class="stock-meta">' + escapeHTML(img.photographer || '') + '</div></div>';
  });
  html += '</div></div>';
  appendBotEl(data.model || 'script-runner', html);
}

/* ── Script Results (gifer, typer, clipper) ─────────────────── */

function renderScriptResult(data) {
  var m = (data.model || 'script-runner').toUpperCase();
  var html = msgHeadHTML(m, 'var(--tx-muted)') + '<div class="msg-body">';
  if (data.result) html += '<p>' + escapeHTML(data.result) + '</p>';
  if (data.preview_url) {
    if (/\.(gif|png|jpg|jpeg)$/i.test(data.preview_url))
      html += '<div class="script-preview"><img src="' + data.preview_url + '" loading="lazy"></div>';
    else if (/\.mp4$/i.test(data.preview_url))
      html += '<div class="script-preview"><video src="' + data.preview_url + '" controls autoplay muted loop></video></div>';
  }
  html += '</div>';
  appendBotEl(data.model || 'script-runner', html);
}

/* ── ComfyUI Results ───────────────────────────────────────── */

function renderComfyResult(data) {
  var html = msgHeadHTML('COMFYUI', 'var(--c-purple)') + '<div class="msg-body">';
  if (data.result) html += '<p>' + escapeHTML(data.result) + '</p>';
  if (data.prompt) html += '<p>' + escapeHTML(data.prompt) + '</p>';
  if (data.images && data.images.length) {
    html += '<div class="stock-grid">';
    data.images.forEach(function(url) {
      html += '<div class="stock-item" data-fullurl="' + url + '">' +
        '<img src="' + url + '" loading="lazy"></div>';
    });
    html += '</div>';
  }
  html += '</div>';
  appendBotEl('comfyui', html);
}

/* ── Search Results ────────────────────────────────────────── */

function renderSearchResults(data) {
  var html = msgHeadHTML('SEARCH', 'var(--tx-muted)') +
    '<div class="msg-body"><p>Results for "' + escapeHTML(data.query || '') + '":</p><ul>';
  (data.results || []).forEach(function(r) {
    html += '<li><a href="' + r.url + '" target="_blank">' + escapeHTML(r.title) + '</a><br>' +
      '<small>' + escapeHTML(r.content || '') + '</small></li>';
  });
  html += '</ul></div>';
  appendBotEl('searxng', html);
}

/* ═══════════════════════════════════════════════════════════════
   MESSAGE RENDERING
   ═══════════════════════════════════════════════════════════════ */

function addUserMessage(text) {
  var msgs = document.getElementById('chat-messages');
  if (!msgs) return;
  var wrap = document.createElement('div');
  wrap.className = 'msg-user-wrap';
  wrap.innerHTML =
    '<div class="msg-user-head"><span class="msg-time">' + timeStamp() + '</span> <span>YOU</span></div>' +
    '<div class="msg-user">' + escapeHTML(text) + '</div>';
  msgs.appendChild(wrap);
  scrollToBottom();
}

function addBotMessage(content, model, isCommand) {
  var msgs = document.getElementById('chat-messages');
  if (!msgs) return;
  var m = (model || 'system').toUpperCase();
  var persona = getActivePersona();
  var color = model ? 'var(--m-' + model + ', var(--tx-muted))' : 'var(--tx-muted)';
  var bodyHTML = isCommand
    ? '<pre class="cmd-result">' + escapeHTML(content) + '</pre>'
    : renderMarkdownString(content);
  var html = msgHeadHTML(m, color, persona) +
    '<div class="msg-body">' + bodyHTML + '</div>' + msgActionsHTML();
  var el = appendBotEl(model || 'system', html);
  wrapCodeBlocks(el.querySelector('.msg-body'));
}

function addSystemMessage(text) {
  var msgs = document.getElementById('chat-messages');
  if (!msgs) return;
  var el = document.createElement('div');
  el.className = 'msg-system';
  el.innerHTML = '<span>' + escapeHTML(text) + '</span>';
  msgs.appendChild(el);
  scrollToBottom();
}

function createBotMessageShell() {
  var msgs = document.getElementById('chat-messages');
  var el = document.createElement('div');
  el.className = 'msg-bot';
  el.setAttribute('data-model', 'streaming');
  el.innerHTML =
    '<div class="msg-head">' +
      '<span class="msg-model" style="color:var(--tx-muted)">...</span>' +
      '<span class="msg-time">' + timeStamp() + '</span>' +
    '</div><div class="msg-body"></div>';
  msgs.appendChild(el);
  return { el: el, bodyEl: el.querySelector('.msg-body') };
}

/* ── HTML Helpers (DRY) ────────────────────────────────────── */

function appendBotEl(model, innerHTML) {
  var msgs = document.getElementById('chat-messages');
  var el = document.createElement('div');
  el.className = 'msg-bot';
  el.setAttribute('data-model', model);
  el.innerHTML = innerHTML;
  msgs.appendChild(el);
  scrollToBottom();
  return el;
}

function msgHeadHTML(label, color, persona) {
  return '<div class="msg-head">' +
    '<span class="msg-model" style="color:' + color + '">' + label + '</span>' +
    (persona ? '<span class="msg-persona">' + persona + '</span>' : '') +
    '<span class="msg-time">' + timeStamp() + '</span></div>';
}

function msgActionsHTML() {
  return '<div class="msg-actions">' +
    '<div class="msg-action" title="Regenerate"><svg fill="currentColor"><use href="icons/sprite.svg#i-reload"/></svg></div>' +
    '<div class="msg-action" title="Good"><svg viewBox="0 0 16 16" fill="currentColor"><path d="M2 8h2v6H2V8zm4-3c0-1 .5-3 2-4 .5 1 1 2 1 3v2h4c1 0 1.5 1 1.5 2l-1.5 6H6V5z"/></svg></div>' +
    '<div class="msg-action" title="Bad"><svg viewBox="0 0 16 16" fill="currentColor"><path d="M12 8h2V2h-2v6zM8 11c0 1-.5 3-2 4-.5-1-1-2-1-3V10H1c-1 0-1.5-1-1.5-2L1 2h6v6z"/></svg></div></div>';
}

/* ═══════════════════════════════════════════════════════════════
   MARKDOWN
   ═══════════════════════════════════════════════════════════════ */

function renderMarkdown(el, text) {
  el.innerHTML = (typeof marked !== 'undefined') ? marked.parse(text) : basicMarkdown(text);
}

function renderMarkdownString(text) {
  return (typeof marked !== 'undefined') ? marked.parse(text) : basicMarkdown(text);
}

function basicMarkdown(text) {
  return text
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\n/g, '<br>');
}

/* ═══════════════════════════════════════════════════════════════
   CODE BLOCKS
   ═══════════════════════════════════════════════════════════════ */

function wrapCodeBlocks(container) {
  if (!container) return;
  container.querySelectorAll('pre > code').forEach(function(code) {
    var pre = code.parentElement;
    if (pre.closest('.code-block')) return;
    var langClass = Array.from(code.classList).find(function(c) { return c.startsWith('language-'); });
    var lang = langClass ? langClass.replace('language-', '') : '';
    var wrapper = document.createElement('div');
    wrapper.className = 'code-block';
    wrapper.innerHTML =
      '<div class="code-head"><span class="code-lang">' + (lang || 'code') + '</span>' +
        '<div class="code-actions"><div class="code-action" title="Copy" data-action="copy-code">' +
          '<svg fill="currentColor"><use href="icons/sprite.svg#i-copy"/></svg></div></div></div>' +
      '<div class="code-body"></div>';
    wrapper.querySelector('.code-body').appendChild(pre.cloneNode(true));
    pre.replaceWith(wrapper);
  });
}

function copyCodeFromAction(el) {
  var block = el.closest('.code-block');
  if (!block) return;
  var code = block.querySelector('code');
  if (!code) return;
  navigator.clipboard.writeText(code.textContent).then(function() {
    el.title = 'Copied!';
    setTimeout(function() { el.title = 'Copy'; }, 1500);
  });
}

/* ═══════════════════════════════════════════════════════════════
   TYPING INDICATOR
   ═══════════════════════════════════════════════════════════════ */

function showTyping(show) {
  var indicator = document.getElementById('chat-typing');
  var msgs = document.getElementById('chat-messages');
  if (!msgs) return;
  if (show && !indicator) {
    indicator = document.createElement('div');
    indicator.id = 'chat-typing';
    indicator.className = 'msg-bot msg-typing';
    indicator.innerHTML =
      '<div class="msg-head"><span class="msg-model" style="color:var(--tx-muted)">THINKING</span></div>' +
      '<div class="msg-body"><div class="typing-dots"><span></span><span></span><span></span></div></div>';
    msgs.appendChild(indicator);
    scrollToBottom();
  } else if (!show && indicator) {
    indicator.remove();
  }
}

/* ═══════════════════════════════════════════════════════════════
   SCROLL
   ═══════════════════════════════════════════════════════════════ */

function scrollToBottom() {
  var msgs = document.getElementById('chat-messages');
  if (msgs) msgs.scrollTop = msgs.scrollHeight;
}

function setupScrollObserver() {
  var msgs = document.getElementById('chat-messages');
  var btn = document.getElementById('chat-scroll-btn');
  if (!msgs || !btn) return;
  msgs.addEventListener('scroll', function() {
    btn.classList.toggle('visible', (msgs.scrollHeight - msgs.scrollTop - msgs.clientHeight) > 200);
  });
}

/* ═══════════════════════════════════════════════════════════════
   INPUT
   ═══════════════════════════════════════════════════════════════ */

function handleChatKeydown(e) {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendChatMessage(); }
}

function autoResizeInput(el) {
  el.style.height = 'auto';
  el.style.height = Math.min(el.scrollHeight, 200) + 'px';
}

function updateSendButton(enabled) {
  var btn = document.getElementById('chat-send');
  if (btn) { btn.disabled = !enabled; btn.style.opacity = enabled ? '' : '0.3'; }
}

function syncSendButtonColor() {
  var active = document.querySelector('[data-action="select-llm"].act');
  if (active) {
    var btn = document.querySelector('.chat-btn-send');
    if (btn) btn.style.background = 'var(--' + active.dataset.color + ')';
  }
}

/* ═══════════════════════════════════════════════════════════════
   IMAGE ATTACHMENT
   ═══════════════════════════════════════════════════════════════ */

function handleFileAttach() {
  var input = document.createElement('input');
  input.type = 'file';
  input.accept = 'image/*';
  input.onchange = function(e) {
    var file = e.target.files[0];
    if (!file) return;
    attachedFileName = file.name;
    var reader = new FileReader();
    reader.onload = function() { attachedImage = reader.result; renderAttachPreview(); };
    reader.readAsDataURL(file);
  };
  input.click();
}

function renderAttachPreview() {
  var area = document.getElementById('chat-attach-area');
  if (!area) {
    area = document.createElement('div');
    area.id = 'chat-attach-area';
    area.className = 'attach-area';
    var inner = document.querySelector('.chat-input-inner');
    if (inner) inner.insertBefore(area, inner.firstChild);
  }
  if (!attachedImage) { area.remove(); return; }
  area.innerHTML =
    '<div class="attach-thumb"><img src="' + attachedImage + '">' +
      '<button class="attach-x" data-action="remove-attachment">\u2715</button></div>' +
    '<span class="attach-fname">' + escapeHTML(attachedFileName || 'image') + '</span>';
}

function getAttachedImage() {
  if (!attachedImage) return null;
  var match = attachedImage.match(/^data:(image\/[a-z+]+);base64,(.+)$/i);
  if (match) return { media_type: match[1], data: match[2] };
  var idx = attachedImage.indexOf(',');
  return { media_type: 'image/png', data: idx > -1 ? attachedImage.slice(idx + 1) : attachedImage };
}

function clearAttachment() {
  attachedImage = null;
  attachedFileName = null;
  var area = document.getElementById('chat-attach-area');
  if (area) area.remove();
}

/* ═══════════════════════════════════════════════════════════════
   IMAGE LIGHTBOX
   ═══════════════════════════════════════════════════════════════ */

function openLightbox(imgUrl) {
  var lb = document.getElementById('lightbox');
  if (!lb) {
    lb = document.createElement('div');
    lb.id = 'lightbox';
    lb.className = 'lightbox';
    lb.innerHTML =
      '<button class="lightbox-close" data-action="close-lightbox">\u2715</button>' +
      '<img id="lightbox-img" src="">' +
      '<div class="lightbox-actions">' +
        '<button class="lightbox-btn" data-action="lightbox-download">DOWNLOAD</button>' +
        '<button class="lightbox-btn" data-action="lightbox-copy">COPY TO CLIPBOARD</button></div>';
    document.body.appendChild(lb);
    lb.addEventListener('click', function(e) { if (e.target === lb) closeLightbox(); });
  }
  lb.querySelector('#lightbox-img').src = imgUrl;
  lb.dataset.url = imgUrl;
  lb.classList.add('open');
}

function closeLightbox() {
  var lb = document.getElementById('lightbox');
  if (lb) lb.classList.remove('open');
}

async function lightboxCopy() {
  var lb = document.getElementById('lightbox');
  if (!lb) return;
  try {
    var resp = await fetch(lb.dataset.url);
    var blob = await resp.blob();
    await navigator.clipboard.write([new ClipboardItem({ [blob.type]: blob })]);
    var btn = lb.querySelector('[data-action="lightbox-copy"]');
    if (btn) { btn.textContent = 'COPIED'; setTimeout(function() { btn.textContent = 'COPY TO CLIPBOARD'; }, 1500); }
  } catch (e) { navigator.clipboard.writeText(lb.dataset.url); }
}

function lightboxDownload() {
  var lb = document.getElementById('lightbox');
  if (!lb) return;
  var a = document.createElement('a');
  a.href = lb.dataset.url;
  a.download = lb.dataset.url.split('/').pop() || 'image';
  a.target = '_blank';
  document.body.appendChild(a);
  a.click();
  a.remove();
}

/* ═══════════════════════════════════════════════════════════════
   END SESSION
   ═══════════════════════════════════════════════════════════════ */

async function endSession() {
  if (!sessionId) return;
  addSystemMessage('Ending session...');
  try {
    var resp = await fetch(API_BASE + '/session/' + sessionId + '/end', { method: 'POST' });
    var data = await resp.json();
    addSystemMessage(data.result || data.message || 'Session ended.');
  } catch (err) { addSystemMessage('Error: ' + err.message); }
}

/* ═══════════════════════════════════════════════════════════════
   STATS & COSTS
   ═══════════════════════════════════════════════════════════════ */

async function updateStats() {
  loadMonthlyCost();
  if (!sessionId) return;
  try {
    var resp = await fetch(API_BASE + '/session/' + sessionId + '/stats');
    if (!resp.ok) return;
    var d = await resp.json();
    var el = document.getElementById('chat-stats');
    if (el) el.textContent = (d.messages||0) + ' msgs \u00b7 ' +
      (d.tokens_in||0) + '\u2193 ' + (d.tokens_out||0) + '\u2191 \u00b7 $' + (d.cost_usd||0).toFixed(3);
  } catch (e) {}
}

async function loadMonthlyCost() {
  try {
    var resp = await fetch(API_BASE + '/costs/monthly');
    if (!resp.ok) return;
    var d = await resp.json();
    var el = document.getElementById('monthly-cost');
    if (el) el.textContent = (d.total || 0).toFixed(2) + '\u20ac';
  } catch (e) {}
}

/* ═══════════════════════════════════════════════════════════════
   HELPERS
   ═══════════════════════════════════════════════════════════════ */

function getActivePersona() {
  var active = document.querySelector('[data-action="select-persona"].act .mi-lbl');
  if (!active) return '';
  var name = active.textContent.trim().toUpperCase();
  return (name === 'NEUTRAL') ? '' : name;
}

function timeStamp() {
  return new Date().toLocaleTimeString('de-DE', { hour: '2-digit', minute: '2-digit' });
}

function escapeHTML(str) {
  var div = document.createElement('div');
  div.textContent = str;
  return div.innerHTML;
}

/* ═══════════════════════════════════════════════════════════════
   EVENT DELEGATION — single listener for all chat actions
   ═══════════════════════════════════════════════════════════════ */

document.addEventListener('click', function(e) {
  /* Image click → lightbox (check before data-action) */
  var img = e.target.closest('.stock-item img, .script-preview img');
  if (img) {
    e.preventDefault();
    var item = img.closest('.stock-item');
    openLightbox((item && item.dataset.fullurl) ? item.dataset.fullurl : img.src);
    return;
  }

  var target = e.target.closest('[data-action]');
  if (!target) return;

  switch (target.dataset.action) {
    case 'send-chat':         sendChatMessage(); break;
    case 'scroll-bottom':     scrollToBottom(); break;
    case 'end-session':       endSession(); break;
    case 'attach-file':       handleFileAttach(); break;
    case 'remove-attachment': clearAttachment(); break;
    case 'copy-code':         copyCodeFromAction(target); break;
    case 'close-lightbox':    closeLightbox(); break;
    case 'lightbox-copy':     lightboxCopy(); break;
    case 'lightbox-download': lightboxDownload(); break;
  }
});

document.addEventListener('keydown', function(e) {
  if (e.key === 'Escape') closeLightbox();
});
