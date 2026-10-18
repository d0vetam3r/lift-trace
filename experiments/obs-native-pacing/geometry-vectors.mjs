// SPDX-License-Identifier: MIT
// Output golden vectors from the existing production JavaScript implementation.
// No browser, server, controller, settings file or OBS is needed.
import { TrailEngine, normalizeSettings } from '../../web/engine.js';
import { drawOverlay } from '../../web/render.js';

const base = {
  greenNumber: 270, suddenNumber: 70, liftNumber: 401, width: 432,
  scratchWidth: 5 / 3, blackKeyRatio: 7 / 9, noteHeight: 12,
  inputBodyEnabled: false, shortInputEnabled: true,
  shortInputThresholdMs: 300, shortInputPercent: 50,
  speedScale: 1, delayMs: 0, side: '1P', background: 'transparent',
  showGuides: false, trailOpacity: .38,
};
const variants = [
  {},
  { inputBodyEnabled: true, shortInputEnabled: false },
  { inputBodyEnabled: true, shortInputThresholdMs: 200, shortInputPercent: 30 },
  { inputBodyEnabled: true, shortInputThresholdMs: 40, shortInputPercent: 30 },
  { inputBodyEnabled: true, delayMs: 100 },
  { side: '2P' },
];
const vectors = [];
for (const [variant, overrides] of variants.entries()) {
  for (const elapsed of [-10, 0, 1, 20, 39.99, 40, 41, 99, 100, 120, 140, 250, 499, 1000]) {
    for (const index of [-3, -1, 0, 1, 2]) {
      const settings = normalizeSettings({ ...base, ...overrides });
      const engine = new TrailEngine(settings);
      const lane = ((index % 7) + 7) % 7 + 1;
      engine.press(lane, 1000 + index * 120);
      engine.release(lane, 1040 + index * 120);
      const rectangles = [];
      const context = {
        save() {}, restore() {}, translate() {}, beginPath() {}, rect() {}, clip() {},
        fillRect(x, y, width, height) { rectangles.push({ x, y, width, height }); },
      };
      drawOverlay(context, engine, settings, 1000 + elapsed);
      const events = engine.snapshot(1000 + elapsed);
      const event = events[0];
      if (!event) {
        if (rectangles.length) throw new Error('Unexpected note without an event');
        vectors.push({ variant, elapsed, index, present: false });
        continue;
      }
      const body = settings.inputBodyEnabled;
      const head = rectangles[body ? 1 : 0];
      if (rectangles.length !== (body ? 3 : 1)) throw new Error('Unexpected drawing shape');
      vectors.push({ variant, elapsed, index, present: true, values: [
        head.x, head.width, head.y + head.height / 2,
        body ? rectangles[0].y : event.tailY,
        head.height, Number(body), Number(event.active), event.start - 1000, event.end - 1000,
      ] });
    }
  }
}
process.stdout.write(JSON.stringify({ source: 'web/engine.js + web/render.js', vectors }));
