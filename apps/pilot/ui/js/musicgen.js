/* ═══════════════════════════════════════════════════════════════
   MUSIC GEN — Text-to-Music via ComfyUI ACE-Step 1.5
   API: Pilot Backend /music/generate + /music/status
   ═══════════════════════════════════════════════════════════════ */

var MUS_API   = 'http://mora02.local:8098';
var MUS_MEDIA = 'http://mora02.local:8092';

var musState = {
  generating: false,
  audioUrl:   null,
  filename:   null,
  pollTimer:  null,
  refAudioFilename: null,
};

/* ─── INIT ─────────────────────────────────────────────────── */

function initMusicGen() {
  musState = { generating: false, audioUrl: null, filename: null, pollTimer: null, refAudioFilename: null };
  musShow('mus-prompt-section');
  musHide('mus-progress-section');
  musHide('mus-result-section');
  musSetupDropZone();
}

/* ─── REFERENCE AUDIO DROP ZONE ────────────────────────────── */

function musSetupDropZone() {
  var zone = document.getElementById('mus-drop-zone');
  var input = document.getElementById('mus-audio-file');
  if (!zone || !input) return;

  zone.addEventListener('click', function() { input.click(); });
  zone.addEventListener('dragover', function(e) { e.preventDefault(); zone.style.borderColor = 'var(--c-teal)'; });
  zone.addEventListener('dragleave', function() { zone.style.borderColor = 'var(--bd)'; });
  zone.addEventListener('drop', function(e) {
    e.preventDefault();
    zone.style.borderColor = 'var(--bd)';
    if (e.dataTransfer.files.length) musUploadRefAudio(e.dataTransfer.files[0]);
  });
  input.addEventListener('change', function() {
    if (input.files.length) musUploadRefAudio(input.files[0]);
  });
}

function musUploadRefAudio(file) {
  var label = document.getElementById('mus-drop-label');
  if (label) { label.style.opacity = '1'; label.textContent = 'Uploading: ' + file.name + '...'; }

  var fd = new FormData();
  fd.append('file', file);

  fetch(MUS_API + '/upload/comfyui-audio', { method: 'POST', body: fd })
    .then(function(r) { return r.json(); })
    .then(function(data) {
      if (data.name) {
        musState.refAudioFilename = data.name;
        if (label) label.textContent = 'Reference: ' + data.name + '  [click to change]';
      } else {
        if (label) label.textContent = 'Upload failed: ' + (data.error || 'unknown');
      }
    })
    .catch(function(e) {
      if (label) label.textContent = 'Upload error: ' + e.message;
    });
}

/* ─── GENERATE ─────────────────────────────────────────────── */

function musGenerate() {
  if (musState.generating) return;

  var tags     = (document.getElementById('mus-tags') || {}).value || '';
  var lyrics   = (document.getElementById('mus-lyrics') || {}).value || '';
  var duration = parseInt((document.getElementById('mus-duration') || {}).value) || 30;
  var bpm      = parseInt((document.getElementById('mus-bpm') || {}).value) || 120;
  var seed     = parseInt((document.getElementById('mus-seed') || {}).value);
  if (isNaN(seed)) seed = -1;
  var key      = (document.getElementById('mus-key') || {}).value || 'C major';
  var timeSig  = (document.getElementById('mus-timesig') || {}).value || '4';
  var language = (document.getElementById('mus-language') || {}).value || 'en';

  if (!tags.trim() && !lyrics.trim()) {
    musSetStatus('Enter style tags or lyrics');
    return;
  }

  musState.generating = true;
  musHide('mus-prompt-section');
  musHide('mus-result-section');
  musShow('mus-progress-section');
  musSetProgress('Sending to ComfyUI...');

  fetch(MUS_API + '/music/generate', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      tags: tags, lyrics: lyrics, duration: duration,
      bpm: bpm, seed: seed, key: key,
      time_signature: timeSig, language: language,
      ref_audio_filename: musState.refAudioFilename || undefined,
    }),
  })
    .then(function(r) { return r.json(); })
    .then(function(data) {
      if (data.error) {
        musState.generating = false;
        musSetProgress('Error: ' + data.error);
        return;
      }
      musSetProgress('Queued (seed: ' + data.seed + '). Generating ~' + duration + 's of music...');
      musStartPolling(data.prompt_id);
    })
    .catch(function(e) {
      musState.generating = false;
      musSetProgress('Error: ' + e.message);
    });
}

/* ─── POLLING ──────────────────────────────────────────────── */

function musStartPolling(promptId) {
  var elapsed = 0;
  musState.pollTimer = setInterval(function() {
    elapsed += 3;
    fetch(MUS_API + '/music/status/' + promptId)
      .then(function(r) { return r.json(); })
      .then(function(data) {
        if (data.status === 'done') {
          clearInterval(musState.pollTimer);
          musState.generating = false;
          musState.audioUrl = MUS_MEDIA + data.audio_url;
          musState.filename = data.filename;
          musRenderResult();
        } else if (data.status === 'error') {
          clearInterval(musState.pollTimer);
          musState.generating = false;
          musSetProgress('Error: ' + (data.message || 'Generation failed'));
        } else {
          musSetProgress('Generating... (' + elapsed + 's elapsed)');
        }
      })
      .catch(function() {
        // keep polling
      });
  }, 3000);
}

/* ─── RESULT ───────────────────────────────────────────────── */

function musRenderResult() {
  musHide('mus-progress-section');
  musShow('mus-result-section');

  var player = document.getElementById('mus-player');
  if (player) {
    player.innerHTML =
      '<audio controls style="width:100%;margin:var(--sp-10) 0">' +
      '<source src="' + musState.audioUrl + '" type="audio/mpeg">' +
      '</audio>';
  }

  var badge = document.getElementById('mus-result-badge');
  if (badge) badge.textContent = 'MUSIC READY';
}

function musDownload() {
  if (!musState.audioUrl) return;
  var a = document.createElement('a');
  a.href = musState.audioUrl;
  a.download = musState.filename || 'music-output.mp3';
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
}

function musNew() {
  if (musState.pollTimer) clearInterval(musState.pollTimer);
  musHide('mus-progress-section');
  musHide('mus-result-section');
  musShow('mus-prompt-section');
  musSetStatus('');
}

/* ─── HELPERS ──────────────────────────────────────────────── */

function musShow(id) { var el = document.getElementById(id); if (el) el.style.display = ''; }
function musHide(id) { var el = document.getElementById(id); if (el) el.style.display = 'none'; }
function musSetStatus(msg) { var el = document.getElementById('mus-status'); if (el) el.textContent = msg; }
function musSetProgress(msg) { var el = document.getElementById('mus-progress-info'); if (el) el.textContent = msg; }

/* ─── EVENT DELEGATION ─────────────────────────────────────── */

document.addEventListener('click', function(e) {
  var target = e.target.closest('[data-action]');
  if (!target) return;
  switch (target.dataset.action) {
    case 'mus-generate': musGenerate(); break;
    case 'mus-download': musDownload(); break;
    case 'mus-new':      musNew(); break;
  }
});
