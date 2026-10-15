import { normalizeSettings } from './engine.js';
import { drawOverlay, laneGeometry, resizeCanvas } from './render.js';

const WIDTH = 300, HEIGHT = 190;
const SAMPLES = Object.freeze([80, 150, 300]);
const HEAD_Y = 148, PIXELS_PER_MS = .3;

/** A static comparison of released sample inputs, independent of live input history. */
export function drawShortInputComparison(canvas, settings, labels = {}) {
  const view = {
    ...normalizeSettings(settings), width: 160, scratchWidth: 1, blackKeyRatio: 1,
    heightMode: 'manual', overlayHeight: 166, background: 'transparent', showGuides: false,
  };
  const ctx = resizeCanvas(canvas, WIDTH, HEIGHT);
  canvas.style.width = '100%';
  canvas.style.height = 'auto';
  canvas.style.aspectRatio = `${WIDTH} / ${HEIGHT}`;
  ctx.clearRect(0, 0, WIDTH, HEIGHT);
  ctx.fillStyle = '#0b0e12'; ctx.fillRect(0, 0, WIDTH, HEIGHT);
  ctx.font = '11px system-ui, sans-serif'; ctx.textAlign = 'center'; ctx.textBaseline = 'middle';

  for (const [group, enabled] of [false, view.shortInputEnabled].entries()) {
    const left = group * 150;
    ctx.fillStyle = '#151b24'; ctx.fillRect(left + 5, 30, 140, 134);
    ctx.fillStyle = group ? '#a8d1ff' : '#c3ccd9';
    ctx.fillText(group ? (labels.current || 'Current') : (labels.original || 'Original'), left + 75, 16, 136);
    const groupSettings = { ...view, inputBodyEnabled: group === 0 || view.inputBodyEnabled, shortInputEnabled: enabled };
    for (const [index, duration] of SAMPLES.entries()) {
      const x = left + 20 + index * 45, lane = index + 1;
      const tailY = HEAD_Y - duration * PIXELS_PER_MS;
      // The thin guide marks the full duration; the real renderer paints the note.
      ctx.fillStyle = '#3c4655'; ctx.fillRect(x - 2, tailY, 1, HEAD_Y - tailY);
      const sample = { lane, start: 0, end: duration, direction: 0, active: false, headY: HEAD_Y, tailY };
      const engine = { snapshot: () => [{ ...sample }] };
      ctx.save(); ctx.translate(x - laneGeometry(groupSettings)[lane].x, 0);
      drawOverlay(ctx, engine, groupSettings, 0);
      ctx.restore();
      ctx.fillStyle = '#9ba8b9'; ctx.fillText(`${duration} ms`, x + 10, 178);
    }
  }
}
