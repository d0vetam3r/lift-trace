// SPDX-License-Identifier: MIT
// Golden live-event geometry from the unchanged InputClient, TrailEngine and
// Canvas renderer. Uses generated controller samples, never a physical device.
import { InputClient } from '../../web/client.js';
import { TrailEngine } from '../../web/engine.js';
import { drawOverlay } from '../../web/render.js';

const epoch = 1800000000000.25;
const base = {
  inputMode: 'native', greenNumber: 270, suddenNumber: 70, liftNumber: 401,
  width: 432, scratchWidth: 5 / 3, blackKeyRatio: 7 / 9, noteHeight: 12,
  inputBodyEnabled: false, shortInputEnabled: true,
  shortInputThresholdMs: 200, shortInputPercent: 30, speedScale: 1,
  delayMs: 0, side: '1P', background: 'transparent', showGuides: false,
  trailOpacity: .38, scratchThreshold: .008, scratchStopMs: 100,
};
const variants = [
  { name: 'heads-only', initial: {} },
  { name: 'full-body', initial: { inputBodyEnabled: true, shortInputEnabled: false } },
  { name: 'short-body', initial: { inputBodyEnabled: true } },
  { name: 'below-threshold', initial: { inputBodyEnabled: true, shortInputThresholdMs: 35 } },
  { name: 'above-threshold', initial: { inputBodyEnabled: true, shortInputThresholdMs: 36 } },
  { name: 'delayed-release', initial: { inputBodyEnabled: true, delayMs: 100 } },
  { name: 'second-player', initial: { side: '2P', inputBodyEnabled: true } },
  { name: 'scratch-inverted', initial: { scratchInvert: true } },
  { name: 'narrow-lanes', initial: { width: 160, scratchWidth: .5, blackKeyRatio: 2, noteHeight: 30 } },
  { name: 'ui-display-change', initial: {}, update: {
    width: '610', greenNumber: '350', noteHeight: '9', speedScale: '1.25',
    side: '2P', heightMode: 'manual', manualOverlayHeight: '210',
    inputBodyEnabled: true, shortInputPercent: '70',
  } },
  { name: 'manual-zero-lift', initial: { liftNumber: 0, heightMode: 'manual', manualOverlayHeight: 60 } },
  { name: 'normalized-bounds', initial: {
    greenNumber: 0, width: 99999, noteHeight: 999, speedScale: 99,
    shortInputPercent: 0, inputBodyEnabled: true,
  } },
];
// Each entry is [milliseconds after epoch, pressed button indices, axis].
const scenarios = [
  { name: 'fractional-tap', samples: [[0, [], 0], [10.125, [0], 0], [45.625, [], 0]] },
  { name: 'held-and-chord', samples: [[0, [], 0], [10.125, [1, 6], 0], [45.625, [6], 0], [400.75, [], 0]] },
  { name: 'clockwise-then-stop', samples: [[0, [], 0], [10.125, [0], .04], [35.625, [], .08], [80.25, [], .12]] },
  { name: 'counterclockwise-and-reverse', samples: [[0, [], .2], [10.125, [2], .14], [45.625, [], .08], [80.25, [], .14]] },
  { name: 'wrapping-turntable', samples: [[0, [], .98], [10.125, [], -.98], [45.625, [3], -.94], [80.25, [], .98]] },
];
const times = [5, 20, 45.625, 55, 80.25, 120, 145.625, 180.25, 250, 450, 700, 1500];
const vectors = [];
for (const variant of variants) {
  for (const scenario of scenarios) {
    for (const elapsed of times) {
      const client = new InputClient();
      client.configure({ ...base, ...variant.initial });
      for (const [at, pressed, axis] of scenario.samples) {
        if (at > elapsed) break;
        client.native({ type: 'input', device: 0, time: epoch + at,
          buttons: Array.from({ length: 32 }, (_, index) => pressed.includes(index)),
          axes: [axis, 0, 0, 0, 0, 0] });
      }
      client.tick(epoch + elapsed);
      const before = JSON.stringify(client.engine.events);
      if (variant.update) client.configure({ ...client.settings, ...variant.update });
      if (before !== JSON.stringify(client.engine.events)) throw new Error('Display settings changed input records');
      const settings = { ...client.settings, buttonMap: [...client.settings.buttonMap] };
      const events = client.engine.events.map(event => ({ ...event }));
      const reference = events.map((raw, index) => {
        const engine = new TrailEngine(settings);
        engine.events = [{ ...raw }];
        const rectangles = [];
        const context = {
          save() {}, restore() {}, translate() {}, beginPath() {}, rect() {}, clip() {},
          arc() {}, moveTo() {}, lineTo() {}, stroke() {},
          fillRect(x, y, width, height) { rectangles.push({ x, y, width, height }); },
        };
        drawOverlay(context, engine, settings, epoch + elapsed);
        const visible = engine.snapshot(epoch + elapsed)[0];
        if (!visible) {
          if (rectangles.length) throw new Error('Renderer emitted an absent input');
          return { index, present: false };
        }
        const body = settings.inputBodyEnabled !== false || raw.lane === 0;
        if (rectangles.length !== (body ? 3 : 1)) throw new Error('Unexpected live renderer shape');
        const head = rectangles[body ? 1 : 0];
        return { index, present: true, values: [
          head.x, head.width, head.y + head.height / 2,
          body ? rectangles[0].y : visible.tailY,
          head.height, Number(body), Number(visible.active),
          raw.start, raw.end === null ? -1 : raw.end, raw.direction,
        ] };
      });
      vectors.push({ variant: variant.name, scenario: scenario.name, elapsed,
        now: epoch + elapsed, settings, events, reference });
    }
  }
}
process.stdout.write(JSON.stringify({ source: 'web/client.js + web/engine.js + web/render.js',
  vectors, eventVectors: vectors.reduce((sum, item) => sum + item.reference.length, 0) }));
