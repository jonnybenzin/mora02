/* ═══════════════════════════════════════════════════════════════
   MORA02 PILOT — Style Guide (2026-03-20)
   ═══════════════════════════════════════════════════════════════
   Reads live CSS custom properties and renders a reference page.
   ═══════════════════════════════════════════════════════════════ */

function initStyleGuide() {
  var el = document.getElementById('sg-content');
  if (!el) return;
  var s = getComputedStyle(document.documentElement);
  var html = '';

  /* Instructions */
  html += '<div class="sg-instructions">' +
    '<strong>How to customize:</strong> Open <code>css/design-tokens.css</code> in a text editor. ' +
    'All values are CSS custom properties in the <code>:root</code> block. Change a value, save the file, ' +
    'refresh the browser (<code>Ctrl+Shift+R</code>) — done. Example: to make H1 larger, find ' +
    '<code>--typo-h1-size: var(--fs-md);</code> and change to <code>--typo-h1-size: 18px;</code>' +
  '</div>';

  /* ═══ COLORS: Grey Scale ════════════════════════════════════ */
  html += sgSection('COLORS: GREY SCALE', 'design-tokens.css → :root');
  var greys = [
    ['--c-black','c-black'],['--c-grey1','c-grey1'],['--c-grey1-5','c-grey1-5'],['--c-grey2','c-grey2'],
    ['--c-grey3','c-grey3'],['--c-grey4','c-grey4'],['--c-grey5','c-grey5'],['--c-grey6','c-grey6'],
    ['--c-grey7','c-grey7'],['--c-grey8','c-grey8'],['--c-grey9','c-grey9'],['--c-grey10','c-grey10'],['--c-white','c-white']
  ];
  html += '<div class="sg-swatches">';
  greys.forEach(function(g) {
    var val = s.getPropertyValue(g[0]).trim();
    var light = ['--c-grey7','--c-grey8','--c-grey9','--c-grey10','--c-white'].indexOf(g[0]) !== -1;
    html += '<div class="sg-swatch" style="background:' + val + '">' +
      '<span style="color:' + (light ? '#000' : '#fff') + ';font-size:9px">' + g[1] + '<br>' + val + '</span></div>';
  });
  html += '</div>';

  /* ═══ COLORS: Accents ═══════════════════════════════════════ */
  html += sgSection('COLORS: ACCENTS (bright + dim pairs)', 'design-tokens.css → --c-*');
  var accentPairs = [['blue','--c-blue','--c-blue-dim'],['purple','--c-purple','--c-purple-dim'],['pink','--c-pink','--c-pink-dim'],['orange','--c-orange','--c-orange-dim'],['green','--c-green','--c-green-dim']];
  html += '<div class="sg-swatches">';
  accentPairs.forEach(function(a) {
    var bright = s.getPropertyValue(a[1]).trim();
    var dim = s.getPropertyValue(a[2]).trim();
    html += '<div class="sg-swatch" style="background:' + dim + ';border:1px solid ' + bright + '"><span style="color:' + bright + ';font-size:9px">' + a[0] + '-dim<br>' + dim + '</span></div>';
    html += '<div class="sg-swatch" style="background:' + bright + '"><span style="color:#000;font-size:9px">' + a[0] + '<br>' + bright + '</span></div>';
  });
  html += '</div>';

  /* ═══ COLORS: Model Colors ═════════════════════════════════ */
  html += sgSection('COLORS: LLM MODELS', 'design-tokens.css → --m-*');
  var models = [['--m-qwen','QWEN'],['--m-haiku','HAIKU'],['--m-sonnet','SONNET'],['--m-opus','OPUS'],['--m-perplexity','PERPLEXITY']];
  html += '<div class="sg-swatches">';
  models.forEach(function(m) {
    var val = s.getPropertyValue(m[0]).trim();
    html += '<div class="sg-swatch" style="background:' + val + '"><span style="color:#000;font-size:9px">' + m[1] + '<br>' + m[0] + '</span></div>';
  });
  html += '</div>';

  /* ═══ SEMANTIC SURFACES ════════════════════════════════════ */
  html += sgSection('SEMANTIC SURFACES', 'design-tokens.css → --sf-* (aliases for grey scale)');
  var surfaces = ['--sf-app','--sf-sidebar','--sf-sec-head','--sf-footer','--sf-input','--sf-card','--sf-flyout','--sf-hover','--sf-toggle','--sf-btn-attach','--sf-btn-send'];
  html += '<div style="display:grid;grid-template-columns:1fr 1fr;gap:var(--sp-4);margin-bottom:var(--sp-20)">';
  surfaces.forEach(function(sf) {
    var val = s.getPropertyValue(sf).trim();
    html += '<div style="display:flex;align-items:center;gap:var(--sp-8)">' +
      '<div style="width:24px;height:24px;background:' + val + ';border:1px solid #333;border-radius:2px;flex-shrink:0"></div>' +
      '<span class="sg-typo-meta">' + sf + ' → ' + val + '</span></div>';
  });
  html += '</div>';

  /* ═══ SEMANTIC TEXT ═════════════════════════════════════════ */
  html += sgSection('SEMANTIC TEXT COLORS', 'design-tokens.css → --tx-*');
  var texts = ['--tx-primary','--tx-secondary','--tx-muted','--tx-disabled','--tx-active','--tx-icon-act'];
  html += '<div style="display:flex;gap:var(--sp-20);flex-wrap:wrap;margin-bottom:var(--sp-20)">';
  texts.forEach(function(tx) {
    var val = s.getPropertyValue(tx).trim();
    html += '<div style="text-align:center"><span style="color:' + val + ';font-family:var(--font);font-size:14px;font-weight:700">' + tx.replace('--tx-','') + '</span><br>' +
      '<span style="font-family:var(--font);font-size:9px;color:var(--tx-disabled)">' + tx + ' → ' + val + '</span></div>';
  });
  html += '</div>';

  /* ═══ TYPOGRAPHY ═══════════════════════════════════════════ */
  html += sgSection('TYPOGRAPHY SCALE', 'design-tokens.css → --typo-*');

  var typos = [
    { name: 'H1 — Tool/Page Titles', token: 'typo-h1', sample: 'GIFER · CLIPPER · SETTINGS',
      css: 'font: var(--typo-h1-font), size: var(--typo-h1-size), weight: var(--typo-h1-weight)' },
    { name: 'H2 — Section Titles', token: 'typo-h2', sample: 'Chat Heading · Content Section',
      css: 'font: var(--typo-h2-font), size: var(--typo-h2-size)' },
    { name: 'Body — Chat, Descriptions', token: 'typo-body', sample: 'This is body text used for chat messages, descriptions, and flowing content throughout the interface.',
      css: 'font: var(--typo-body-font), size: var(--typo-body-size), line-height: var(--typo-body-line-h)' },
    { name: 'Label — Settings, Headers', token: 'typo-label', sample: 'QUALITY · DURATION · WORKFLOW',
      css: 'font: var(--typo-label-font), size: var(--typo-label-size), spacing: var(--typo-label-spacing)' },
    { name: 'Button — Actions', token: 'typo-btn', sample: 'GENERATE GIF · FINALIZE AND SAVE · DOWNLOAD',
      css: 'font: var(--typo-btn-font), size: var(--typo-btn-size), weight: var(--typo-btn-weight)' },
    { name: 'Menu Item — Sidebar', token: 'typo-mi', sample: 'IMAGE GEN · GIFER · CLIPPER · TYPER',
      css: 'font: var(--typo-mi-font), size: var(--typo-mi-size)' },
    { name: 'Meta — Timestamps, Model Names', token: 'typo-meta', sample: 'QWEN · 14:32 · 1.2K tokens',
      css: 'font: var(--typo-meta-font), size: var(--typo-meta-size)' },
    { name: 'Code — Code Blocks', token: 'typo-code', sample: 'docker compose up -d nginx-images',
      css: 'font: var(--typo-code-font), size: var(--typo-code-size)' },
    { name: 'Input — Text Fields', token: 'typo-input', sample: 'Type your message here...',
      css: 'font: var(--typo-input-font), size: var(--typo-input-size)' },
  ];

  typos.forEach(function(t) {
    var font = s.getPropertyValue('--' + t.token + '-font').trim() || 'inherit';
    var size = s.getPropertyValue('--' + t.token + '-size').trim() || '14px';
    var weight = s.getPropertyValue('--' + t.token + '-weight').trim() || '400';
    var color = s.getPropertyValue('--' + t.token + '-color').trim() || 'inherit';
    var spacing = s.getPropertyValue('--' + t.token + '-spacing').trim() || '0';
    var lineH = s.getPropertyValue('--' + t.token + '-line-h').trim() || '1.4';

    html +=
      '<div class="sg-typo-row">' +
        '<div class="sg-typo-label">' + t.name + '</div>' +
        '<div class="sg-typo-sample" style="font-family:' + font + ';font-size:' + size + ';font-weight:' + weight + ';color:' + color + ';letter-spacing:' + spacing + ';line-height:' + lineH + '">' + t.sample + '</div>' +
        '<div class="sg-typo-meta">' + t.css + '</div>' +
      '</div>';
  });

  /* ═══ FONT SIZES ═══════════════════════════════════════════ */
  html += sgSection('FONT SIZES', 'design-tokens.css → --fs-*');
  var sizes = [['--fs-xs','9px'],['--fs-sm','11px'],['--fs-base','13px'],['--fs-md','14px']];
  html += '<div style="display:flex;gap:var(--sp-30);flex-wrap:wrap;margin-bottom:var(--sp-20)">';
  sizes.forEach(function(sz) {
    html += '<div><span style="font-family:var(--font);font-size:' + sz[1] + ';color:var(--tx-primary)">' + sz[0] + ' (' + sz[1] + ')</span></div>';
  });
  html += '</div>';

  /* ═══ FONT WEIGHTS ═════════════════════════════════════════ */
  html += sgSection('FONT WEIGHTS', 'design-tokens.css → --fw-*');
  var weights = [['400','regular'],['500','medium'],['600','semi'],['700','bold'],['800','black']];
  html += '<div style="display:flex;gap:var(--sp-20);flex-wrap:wrap;margin-bottom:var(--sp-20)">';
  weights.forEach(function(w) {
    html += '<span style="font-family:var(--font);font-size:14px;font-weight:' + w[0] + ';color:var(--tx-primary)">' + w[1] + ' (' + w[0] + ')</span>';
  });
  html += '</div>';

  /* ═══ SPACING ══════════════════════════════════════════════ */
  html += sgSection('SPACING SCALE', 'design-tokens.css → --sp-*');
  var spacings = ['--sp-2','--sp-4','--sp-6','--sp-8','--sp-10','--sp-16','--sp-20','--sp-26','--sp-30','--sp-40'];
  html += '<div style="display:flex;align-items:flex-end;gap:var(--sp-8);margin-bottom:var(--sp-20)">';
  spacings.forEach(function(sp) {
    var val = s.getPropertyValue(sp).trim();
    var px = parseInt(val);
    html += '<div style="text-align:center"><div style="width:' + val + ';height:' + val + ';background:var(--c-green);opacity:0.4"></div>' +
      '<div style="font-family:var(--font);font-size:9px;color:var(--tx-disabled);margin-top:4px">' + sp.replace('--','') + '<br>' + val + '</div></div>';
  });
  html += '</div>';

  /* ═══ COMPONENTS ═══════════════════════════════════════════ */
  html += sgSection('COMPONENTS: ICON BUTTON (PRIMARY ACTION)', 'tools.css → .btn-ico · design-tokens.css → --btn-ico-*');
  html +=
    '<div style="display:flex;gap:var(--sp-10);flex-wrap:wrap;margin-bottom:var(--sp-16)">' +
      '<button class="btn-ico"><svg fill="currentColor"><use href="icons/sprite.svg#i-image"></use></svg> GENERATE</button>' +
      '<button class="btn-ico"><svg fill="currentColor"><use href="icons/sprite.svg#i-gif"></use></svg> GENERATE GIF</button>' +
      '<button class="btn-ico"><svg fill="currentColor"><use href="icons/sprite.svg#i-download"></use></svg> DOWNLOAD</button>' +
      '<button class="btn-ico" disabled><svg fill="currentColor"><use href="icons/sprite.svg#i-image"></use></svg> DISABLED</button>' +
    '</div>' +
    '<div class="sg-typo-meta">Usage: &lt;button class="btn-ico"&gt;&lt;svg&gt;&lt;use href="icons/sprite.svg#i-name"&gt;&lt;/svg&gt; LABEL&lt;/button&gt;<br>' +
      'Tokens: --btn-ico-height (44px), --btn-ico-bg, --btn-ico-color, --btn-ico-icon-size (16px)<br>' +
      'Hover: scale(1.03) + bg change. Primary action button for each tool page.</div>';

  html += sgSection('COMPONENTS: BUTTONS', 'tools.css → .tool-action-btn, .tool-btn-primary');
  html +=
    '<div style="display:flex;gap:var(--sp-10);flex-wrap:wrap;margin-bottom:var(--sp-20)">' +
      '<button class="tool-action-btn">ACTION BUTTON</button>' +
      '<button class="tool-action-btn" disabled style="opacity:0.3">DISABLED</button>' +
      '<button class="tool-btn tool-btn-primary">PRIMARY BUTTON</button>' +
      '<button class="tool-btn tool-btn-secondary">SECONDARY BUTTON</button>' +
    '</div>' +
    '<div class="sg-typo-meta">.tool-action-btn — black bg, design token fonts<br>' +
      '.tool-btn-primary — green bg (send color)<br>' +
      '.tool-btn-secondary — grey bg with border</div>';

  /* ═══ FORM ELEMENTS ════════════════════════════════════════ */
  html += sgSection('COMPONENTS: FORM ELEMENTS', 'tools.css → .tool-select, .tool-input-sm, .tool-text, .tool-input-wide');
  html +=
    '<div class="tool-settings" style="margin-bottom:var(--sp-16)">' +
      '<div class="tool-setting"><span class="tool-setting-lbl">SELECT:</span><select class="tool-select"><option>OPTION A</option><option>OPTION B</option></select></div>' +
      '<div class="tool-setting"><span class="tool-setting-lbl">SMALL INPUT:</span><input class="tool-input-sm" type="text" value="1024" style="width:60px"></div>' +
    '</div>' +
    '<div style="margin-bottom:var(--sp-10)"><input class="tool-input-wide" type="text" value="Full width input" style="width:100%"></div>' +
    '<textarea class="tool-text" rows="2" style="min-height:auto">Textarea with tool-text class</textarea>' +
    '<div class="sg-typo-meta">.tool-select — dropdown<br>.tool-input-sm — small number/text<br>.tool-input-wide — full-width input<br>.tool-text — multiline textarea</div>';

  /* ═══ CARD / LIST ITEM ════════════════════════════════════ */
  html += sgSection('COMPONENTS: LIST ITEMS', 'tools.css → .tool-item');
  html +=
    '<div class="tool-item">' +
      '<span class="tool-item-num">01</span>' +
      '<div class="tool-item-thumb" style="background:var(--c-grey3);width:60px;height:60px"></div>' +
      '<span class="tool-item-name">example-file.png</span>' +
      '<div class="tool-item-arrows">' +
        '<div class="tool-item-arrow"><svg fill="currentColor" style="width:8px;height:8px"><use href="icons/sprite.svg#i-chev-up"/></svg></div>' +
        '<input class="tool-item-val" type="text" value="1">' +
        '<div class="tool-item-arrow"><svg fill="currentColor" style="width:8px;height:8px"><use href="icons/sprite.svg#i-chev-down"/></svg></div>' +
      '</div>' +
      '<div class="tool-item-delete"><svg fill="currentColor" style="width:14px;height:14px"><use href="icons/sprite.svg#i-delete"/></svg></div>' +
    '</div>' +
    '<div class="sg-typo-meta" style="margin-top:var(--sp-8)">.tool-item — drag-reorderable list row (gifer, clipper)<br>.tool-item-thumb, .tool-item-name, .tool-item-val, .tool-item-delete</div>';

  /* ═══ DASHBOARD CARD ═══════════════════════════════════════ */
  html += sgSection('COMPONENTS: DASHBOARD CARD', 'tools.css → .dash-card, .dash-dot');
  html +=
    '<div style="display:flex;flex-direction:column;gap:var(--sp-8);margin-bottom:var(--sp-16);max-width:400px">' +
      '<div class="dash-card"><div class="dash-dot dash-online"></div><div class="dash-info"><span class="dash-name">Service Online</span><span class="dash-detail">Port 8080</span></div></div>' +
      '<div class="dash-card"><div class="dash-dot dash-offline"></div><div class="dash-info"><span class="dash-name">Service Offline</span><span class="dash-detail">Port 9999</span></div></div>' +
      '<div class="dash-card"><div class="dash-dot dash-checking"></div><div class="dash-info"><span class="dash-name">Checking...</span><span class="dash-detail">Port 8080</span></div></div>' +
    '</div>' +
    '<div class="sg-typo-meta">.dash-card — service health card<br>.dash-dot.dash-online — green<br>.dash-dot.dash-offline — red<br>.dash-dot.dash-checking — grey</div>';

  /* ═══ STATUS LINE ══════════════════════════════════════════ */
  html += sgSection('COMPONENTS: STATUS / FEEDBACK', 'tools.css → .tool-result-status');
  html +=
    '<div class="tool-result-status"><span style="color:var(--c-green)">✓ Saved to Baserow</span> <a href="#" style="color:var(--tx-secondary);text-decoration:underline">http://mora02.local:8092/...</a></div>' +
    '<div class="tool-result-status"><span style="color:var(--c-red,#f55)">Error: Generation failed</span></div>' +
    '<div class="sg-typo-meta" style="margin-top:var(--sp-8)">.tool-result-status — success/error feedback below actions</div>';

  /* ═══ WIKI TABS ════════════════════════════════════════════ */
  html += sgSection('COMPONENTS: TABS', 'tools.css → .wiki-tab');
  html +=
    '<div class="wiki-tabs" style="margin-bottom:var(--sp-16)">' +
      '<button class="wiki-tab wiki-tab-active">ACTIVE TAB</button>' +
      '<button class="wiki-tab">INACTIVE</button>' +
      '<button class="wiki-tab">ANOTHER</button>' +
    '</div>' +
    '<div class="sg-typo-meta">.wiki-tab — horizontal tab bar<br>.wiki-tab-active — underline + bright text</div>';

  /* ═══ LAYOUT TOKENS ════════════════════════════════════════ */
  html += sgSection('LAYOUT TOKENS', 'design-tokens.css → sidebar, homepage');
  var layouts = [
    ['--sb-w', 'Sidebar width'],['--sb-coll', 'Sidebar collapsed'],['--sb-head-h', 'Sidebar header height'],
    ['--mob-drawer', 'Mobile drawer width'],['--mob-bar-h', 'Mobile bar height'],
    ['--hero-max-w', 'Hero max width'],['--input-max-w', 'Input max width'],['--flyout-w', 'Flyout width']
  ];
  html += '<div style="display:grid;grid-template-columns:1fr 1fr;gap:var(--sp-4);margin-bottom:var(--sp-20)">';
  layouts.forEach(function(l) {
    var val = s.getPropertyValue(l[0]).trim();
    html += '<div style="font-family:var(--font);font-size:11px"><span style="color:var(--tx-muted)">' + l[0] + '</span> <span style="color:var(--tx-primary)">' + val + '</span> <span style="color:var(--tx-disabled)">— ' + l[1] + '</span></div>';
  });
  html += '</div>';

  /* ═══ ICONS (SVG Sprite) ════════════════════════════════════ */
  html += sgSection('ICONS (SVG SPRITE)', 'icons/sprite.svg — reference via use href');
  var icons = ['i-bot','i-persona','i-apps','i-library','i-core','i-settings','i-arrow-l','i-arrow-up','i-plus','i-delete','i-hamburger','i-image','i-reload','i-copy','i-download','i-arrow-r','i-chev','i-shuffle','i-chev-up','i-chev-down','i-gif','i-mpg','i-typer','i-baserow','i-activepieces','i-comfyui','i-excalidraw'];
  html += '<div class="sg-icons">';
  var spriteBase = 'icons/sprite' + '.svg#';
  icons.forEach(function(id) {
    html += '<div class="sg-icon">' +
      '<svg fill="currentColor" style="width:20px;height:20px"><use href="' + spriteBase + id + '"></use></svg>' +
      '<span>' + id + '</span></div>';
  });
  html += '</div>';

    /* ═══ CSS FILES REFERENCE ══════════════════════════════════ */
  html += sgSection('CSS FILES', 'All stylesheets');
  html +=
    '<div style="font-family:var(--font);font-size:11px;color:var(--tx-secondary);line-height:2">' +
      '<strong>design-tokens.css</strong> — All CSS custom properties (single source of truth)<br>' +
      '<strong>pilot.css</strong> — Sidebar, layout, homepage, mobile responsive<br>' +
      '<strong>chat.css</strong> — Chat messages, input bar, code blocks, lightbox<br>' +
      '<strong>tools.css</strong> — Tool pages (gifer, clipper, typer, imagegen, settings, files, wiki, dashboard)<br>' +
    '</div>';

  el.innerHTML = html;
}

/* ─── Section helper ────────────────────────────────────────── */

function sgSection(title, subtitle) {
  return '<div class="sg-section">' +
    '<div class="sg-section-title">' + title + '</div>' +
    '<div class="sg-section-sub">' + subtitle + '</div>' +
  '</div>';
}
