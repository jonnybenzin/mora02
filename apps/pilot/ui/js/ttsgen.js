/* ═══════════════════════════════════════════════════════════════
   TTS GEN — Text-to-Speech Generation
   DE → Piper (CPU), EN → Kokoro (CPU)
   API: knowledge-api /tts/generate
   ═══════════════════════════════════════════════════════════════ */

var KNOWLEDGE_API = 'http://mora02.local:8095';
var TTS_MEDIA    = 'http://mora02.local:8092';

var ttsState = {
  generating: false,
  audioUrl:   null,
  filename:   null,
  voices:     null,
};

/* ─── INIT ─────────────────────────────────────────────────── */

function initTtsGen() {
  ttsState = { generating: false, audioUrl: null, filename: null, voices: null };
  ttsShow('tts-prompt-section');
  ttsHide('tts-result-section');
  ttsLoadVoices();

  var langSel = document.getElementById('tts-language');
  if (langSel) {
    langSel.addEventListener('change', function() {
      ttsPopulateVoiceDropdown(langSel.value);
      ttsUpdateControlVisibility();
    });
  }

  var engineSel = document.getElementById('tts-engine');
  if (engineSel) {
    engineSel.addEventListener('change', function() {
      ttsUpdateControlVisibility();
      ttsCheckChatterboxStatus();
    });
  }

  // Slider value displays
  ttsBindSlider('tts-speed', 'tts-speed-val', function(v) { return parseFloat(v).toFixed(1) + 'x'; });
  ttsBindSlider('tts-expression', 'tts-expression-val', function(v) { return parseFloat(v).toFixed(2); });
  ttsBindSlider('tts-timbre', 'tts-timbre-val', function(v) { return parseFloat(v).toFixed(2); });
  ttsBindSlider('tts-exaggeration', 'tts-exaggeration-val', function(v) { return parseFloat(v).toFixed(2); });
  ttsBindSlider('tts-cfg', 'tts-cfg-val', function(v) { return parseFloat(v).toFixed(2); });
  ttsBindSlider('tts-temperature', 'tts-temperature-val', function(v) { return parseFloat(v).toFixed(2); });

  // Show/hide controls based on engine + language
  ttsUpdateControlVisibility();
  ttsCheckChatterboxStatus();
}

/* ─── VOICES ───────────────────────────────────────────────── */

function ttsLoadVoices() {
  fetch(KNOWLEDGE_API + '/tts/voices')
    .then(function(r) { return r.json(); })
    .then(function(data) {
      ttsState.voices = data;
      var lang = document.getElementById('tts-language');
      if (lang) ttsPopulateVoiceDropdown(lang.value);
    })
    .catch(function(e) {
      console.warn('TTS voices load failed:', e);
      // fallback defaults
      ttsState.voices = {
        de: [{ id: 'thorsten', name: 'Thorsten (Male)' }, { id: 'kerstin', name: 'Kerstin (Female)' }],
        en: [{ id: 'af_bella', name: 'Bella (Female)' }, { id: 'am_adam', name: 'Adam (Male)' }],
      };
      var lang = document.getElementById('tts-language');
      if (lang) ttsPopulateVoiceDropdown(lang.value);
    });
}

function ttsPopulateVoiceDropdown(language) {
  var sel = document.getElementById('tts-voice');
  if (!sel || !ttsState.voices) return;
  var voices = ttsState.voices[language] || [];
  sel.innerHTML = '';
  for (var i = 0; i < voices.length; i++) {
    var opt = document.createElement('option');
    opt.value = voices[i].id;
    opt.textContent = voices[i].name;
    sel.appendChild(opt);
  }
}

/* ─── GENERATE ─────────────────────────────────────────────── */

function ttsGenerate() {
  if (ttsState.generating) return;

  var text = document.getElementById('tts-text').value.trim();
  if (!text) return;

  var language = document.getElementById('tts-language').value;
  var voice    = document.getElementById('tts-voice').value;
  var format   = document.getElementById('tts-format').value;
  var speed    = parseFloat(document.getElementById('tts-speed').value) || 1.0;
  var expression = parseFloat(document.getElementById('tts-expression').value) || 0.667;
  var timbre   = parseFloat(document.getElementById('tts-timbre').value) || 0.8;

  ttsState.generating = true;
  var btn = document.getElementById('tts-generate-btn');
  if (btn) btn.classList.add('loading');
  ttsSetStatus('Generating...');

  var engineChoice = document.getElementById('tts-engine').value;
  var exaggeration = parseFloat(document.getElementById('tts-exaggeration').value) || 0.5;

  var cfg = parseFloat((document.getElementById('tts-cfg') || {}).value) || 0.5;
  var temperature = parseFloat((document.getElementById('tts-temperature') || {}).value) || 0.8;

  var cbVoice = (document.getElementById('tts-cb-voice') || {}).value || '';

  var payload = { text: text, language: language, voice: voice, format: format, speed: speed, engine: engineChoice };
  if (engineChoice === 'chatterbox') {
    payload.exaggeration = exaggeration;
    payload.cfg_weight = cfg;
    payload.temperature = temperature;
    payload.cb_voice = cbVoice;
  } else if (language === 'de') {
    payload.noise_scale = expression;
    payload.noise_w = timbre;
  }

  fetch(KNOWLEDGE_API + '/tts/generate', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
    .then(function(r) { return r.json(); })
    .then(function(data) {
      ttsState.generating = false;
      if (btn) btn.classList.remove('loading');

      if (data.success) {
        ttsState.audioUrl  = TTS_MEDIA + data.url;
        ttsState.filename  = data.filename;
        ttsRenderResult(data);
        ttsHide('tts-prompt-section');
        ttsShow('tts-result-section');
        ttsSetStatus('');
      } else {
        ttsSetStatus('Error: ' + (data.message || 'Unknown error'));
      }
    })
    .catch(function(e) {
      ttsState.generating = false;
      if (btn) btn.classList.remove('loading');
      ttsSetStatus('Error: ' + e.message);
    });
}

/* ─── RESULT ───────────────────────────────────────────────── */

function ttsRenderResult(data) {
  var player = document.getElementById('tts-player');
  if (!player) return;

  player.innerHTML =
    '<audio controls style="width:100%;margin:var(--sp-10) 0">' +
    '<source src="' + ttsState.audioUrl + '" type="audio/' + (data.filename.endsWith('.mp3') ? 'mpeg' : 'wav') + '">' +
    '</audio>' +
    '<div style="color:var(--tx-muted);font-size:var(--fs-xs);margin-top:var(--sp-4)">' +
    data.engine.toUpperCase() + ' &middot; ' + data.voice + ' &middot; ' + data.text_length + ' chars</div>';

  var badge = document.getElementById('tts-result-badge');
  if (badge) badge.textContent = 'AUDIO READY — ' + data.engine.toUpperCase();
}

function ttsDownload() {
  if (!ttsState.audioUrl) return;
  var a = document.createElement('a');
  a.href = ttsState.audioUrl;
  a.download = ttsState.filename || 'tts-output.wav';
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
}

function ttsNew() {
  ttsHide('tts-result-section');
  ttsShow('tts-prompt-section');
  ttsSetStatus('');
}

/* ─── HELPERS ──────────────────────────────────────────────── */

function ttsShow(id) { var el = document.getElementById(id); if (el) el.style.display = ''; }
function ttsHide(id) { var el = document.getElementById(id); if (el) el.style.display = 'none'; }
function ttsSetStatus(msg) { var el = document.getElementById('tts-status'); if (el) el.textContent = msg; }

function ttsBindSlider(sliderId, displayId, formatter) {
  var slider = document.getElementById(sliderId);
  var display = document.getElementById(displayId);
  if (slider && display) {
    display.textContent = formatter(slider.value);
    slider.addEventListener('input', function() {
      display.textContent = formatter(slider.value);
    });
  }
}

function ttsUpdateControlVisibility() {
  var engine = (document.getElementById('tts-engine') || {}).value || 'auto';
  var language = (document.getElementById('tts-language') || {}).value || 'de';
  var isChatterbox = engine === 'chatterbox';
  var isDE = language === 'de';

  // Voice dropdown: hide for chatterbox (it uses reference audio, not voice IDs)
  var voiceField = document.getElementById('tts-voice');
  if (voiceField) voiceField.closest('.fl-field').style.display = isChatterbox ? 'none' : '';

  // Piper-specific sliders: only for auto/piper + DE
  var deOnly = document.querySelectorAll('.tts-de-only');
  for (var i = 0; i < deOnly.length; i++) {
    deOnly[i].style.display = (!isChatterbox && isDE) ? '' : 'none';
  }

  // Chatterbox-specific sliders
  var cbOnly = document.querySelectorAll('.tts-chatterbox-only');
  for (var i = 0; i < cbOnly.length; i++) {
    cbOnly[i].style.display = isChatterbox ? '' : 'none';
  }

  // Piper sliders container: hide entirely for chatterbox
  var slidersEl = document.getElementById('tts-sliders');
  if (slidersEl) slidersEl.style.display = isChatterbox ? 'none' : '';
}

function ttsCheckChatterboxStatus() {
  var engine = (document.getElementById('tts-engine') || {}).value || 'auto';
  var notice = document.getElementById('tts-chatterbox-notice');
  if (engine !== 'chatterbox' || !notice) {
    if (notice) notice.style.display = 'none';
    return;
  }
  fetch(KNOWLEDGE_API + '/tts/chatterbox/status')
    .then(function(r) { return r.json(); })
    .then(function(data) {
      if (notice) notice.style.display = (data.healthy) ? 'none' : '';
      if (data.healthy) ttsLoadVoiceLibrary();
    })
    .catch(function() {
      if (notice) notice.style.display = '';
    });
}

/* ─── VOICE LIBRARY (CHATTERBOX) ───────────────────────────── */

function ttsLoadVoiceLibrary() {
  fetch(KNOWLEDGE_API + '/tts/voices/library')
    .then(function(r) { return r.json(); })
    .then(function(data) {
      var sel = document.getElementById('tts-cb-voice');
      if (!sel) return;
      sel.innerHTML = '<option value="">Default Voice</option>';
      var voices = data.voices || [];
      for (var i = 0; i < voices.length; i++) {
        var v = voices[i];
        var opt = document.createElement('option');
        opt.value = v.name;
        opt.textContent = v.name + (v.language ? ' (' + v.language + ')' : '');
        sel.appendChild(opt);
      }
    })
    .catch(function(e) { console.warn('Voice library load failed:', e); });
}

function ttsVoiceUpload() {
  var fileInput = document.getElementById('tts-voice-file');
  var nameInput = document.getElementById('tts-voice-name');
  var statusEl = document.getElementById('tts-upload-status');

  if (!fileInput || !fileInput.files || !fileInput.files.length) {
    if (statusEl) statusEl.textContent = 'No file selected';
    return;
  }
  var voiceName = (nameInput ? nameInput.value.trim() : '');
  if (!voiceName) {
    if (statusEl) statusEl.textContent = 'Enter a voice name first';
    return;
  }

  var language = (document.getElementById('tts-language') || {}).value || 'de';
  var formData = new FormData();
  formData.append('file', fileInput.files[0]);
  formData.append('voice_name', voiceName);
  formData.append('language', language);

  if (statusEl) statusEl.textContent = 'Uploading & converting...';

  fetch(KNOWLEDGE_API + '/tts/voices/upload', {
    method: 'POST',
    body: formData,
  })
    .then(function(r) { return r.json(); })
    .then(function(data) {
      if (data.success) {
        if (statusEl) statusEl.textContent = 'Voice "' + voiceName + '" uploaded!';
        if (nameInput) nameInput.value = '';
        fileInput.value = '';
        ttsLoadVoiceLibrary();
      } else {
        if (statusEl) statusEl.textContent = 'Error: ' + (data.message || 'Upload failed');
      }
    })
    .catch(function(e) {
      if (statusEl) statusEl.textContent = 'Error: ' + e.message;
    });
}

/* ─── EVENT DELEGATION ─────────────────────────────────────── */

document.addEventListener('click', function(e) {
  var target = e.target.closest('[data-action]');
  if (!target) return;
  switch (target.dataset.action) {
    case 'tts-generate':  ttsGenerate(); break;
    case 'tts-download':  ttsDownload(); break;
    case 'tts-new':       ttsNew(); break;
    case 'tts-voice-pick':
      var vn = document.getElementById('tts-voice-name');
      var us = document.getElementById('tts-upload-status');
      if (!vn || !vn.value.trim()) {
        if (us) us.textContent = 'Enter a voice name first, then click UPLOAD VOICE';
        if (vn) vn.focus();
        break;
      }
      var fi = document.getElementById('tts-voice-file');
      if (fi) {
        fi.onchange = function() {
          if (fi.files && fi.files.length) ttsVoiceUpload();
        };
        fi.click();
      }
      break;
  }
});
