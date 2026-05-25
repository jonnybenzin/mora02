/**
 * M2 Pixel Loader
 * Mora02 Pilot Cockpit — waiting animation
 *
 * Usage:
 *   startM2(element)                  → default (12px cells, speed 35)
 *   startM2(element, 20, 35)          → large / ComfyUI
 *   startM2(element, 7,  35)          → small / inline chat
 *   stopM2()                          → stop & clear
 *
 * HTML:
 *   <div class="m2-loader" id="my-loader"></div>
 *
 * Pixel grids (5×5):
 *   M:  XXXXX / XoXoX / XoXoX / XoXoX / XoXoX
 *   2:  XXXXX / ooooX / XXXXX / Xoooo / XXXXX
 */

const M2_SEQ  = [0,1,2,3,4, 5,10,15,20, 7,12,17,22, 9,14,19,24];
const TWO_SEQ = [0,1,2,3,4, 9, 14,13,12,11,10, 15, 20,21,22,23,24];

const M2_HOLD = 250;  // ms pause after full letter
const M2_GAP  = 120;  // ms pause between letters

let _m2timers = [];

function startM2(el, cellSize = 12, speed = 35) {
  stopM2();

  // Build grid
  el.classList.add('m2-grid');
  el.innerHTML = '';
  const cells = [];

  for (let i = 0; i < 25; i++) {
    const c = document.createElement('div');
    c.className = 'm2-cell';
    c.style.width  = cellSize + 'px';
    c.style.height = cellSize + 'px';
    el.appendChild(c);
    cells.push(c);
  }

  // Override grid column size
  el.style.gridTemplateColumns = `repeat(5, ${cellSize}px)`;

  function clearCells() {
    cells.forEach(c => c.classList.remove('on'));
  }

  function draw(seq, onDone) {
    clearCells();
    seq.forEach((idx, i) => {
      const t = setTimeout(() => {
        cells[idx].classList.add('on');
        if (i === seq.length - 1) {
          _m2timers.push(setTimeout(onDone, M2_HOLD));
        }
      }, i * speed);
      _m2timers.push(t);
    });
  }

  function loop() {
    draw(M2_SEQ, () => {
      _m2timers.push(setTimeout(() => {
        draw(TWO_SEQ, () => {
          _m2timers.push(setTimeout(loop, M2_GAP));
        });
      }, M2_GAP));
    });
  }

  loop();
}

function stopM2() {
  _m2timers.forEach(clearTimeout);
  _m2timers = [];
}

// ── Example usage patterns ────────────────────────────────────

// Chat — LLM thinking (inline, small):
// startM2(document.getElementById('chat-loader'), 7, 35);

// Chat — LLM thinking (overlay, medium):
// startM2(document.getElementById('chat-loader'), 12, 35);

// ImageGen — ComfyUI running (large):
// startM2(document.getElementById('imagegen-loader'), 20, 35);

// Stop when response arrives:
// stopM2();
// document.getElementById('chat-loader').innerHTML = '';
