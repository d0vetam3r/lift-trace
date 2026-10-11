import { InputClient } from './client.js';
import { resizeCanvas, drawOverlay } from './render.js';

const canvas = document.getElementById('overlay');
const client = new InputClient();
// No controls, game-side demo notes, or external assets are rendered on this page.
function frame() {
  const now = Date.now(), s = client.settings;
  client.tick(now);
  // A viewport resize must crop/extend the output, never rescale the note motion.
  canvas.style.width = s.width + 'px';
  canvas.style.height = s.overlayHeight + 'px';
  const ctx = resizeCanvas(canvas, s.width, s.overlayHeight);
  // Also erase prior pixels when switching to auto LIFT 0 (a blank 1px placeholder).
  ctx.clearRect(0, 0, s.width, s.overlayHeight);
  drawOverlay(ctx, client.engine, s, now);
  requestAnimationFrame(frame);
}
client.start().catch(() => { /* Transparent while server is unavailable; EventSource handles later drops. */ });
requestAnimationFrame(frame);
