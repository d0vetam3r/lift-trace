import test, { before, after } from 'node:test';
import assert from 'node:assert/strict';
import { normalizeSettings, TrailEngine } from '../web/engine.js';
import { resizeCanvas, drawPreview, drawOverlay, laneGeometry, SCRATCH_COLORS, NOTE_COLORS } from '../web/render.js';

const originalWindow = globalThis.window;
before(() => { globalThis.window = { devicePixelRatio: 1.25 }; });
after(() => {
  if (originalWindow === undefined) delete globalThis.window;
  else globalThis.window = originalWindow;
});

function fakeCanvas() {
  let transform = [1, 1, 0, 0];
  const stack = [];
  const ctx = {
    rectangles: [], strokes: 0, arcs: [],
    setTransform(x, _b, _c, y, tx, ty) { transform = [x, y, tx, ty]; },
    translate(x, y) { transform[2] += x * transform[0]; transform[3] += y * transform[1]; },
    save() { stack.push({ transform: [...transform], fillStyle: this.fillStyle }); },
    restore() { const state = stack.pop(); transform = state.transform; this.fillStyle = state.fillStyle; },
    fillRect(x, y, width, height) {
      this.rectangles.push({ x: x * transform[0] + transform[2], y: y * transform[1] + transform[3],
        width: width * transform[0], height: height * transform[1], logicalHeight: height, color: this.fillStyle });
    },
    clearRect() { this.rectangles = []; this.arcs = []; },
    arc(x, y, radius, start, end, anticlockwise) { this.arcs.push({ x, y, radius, start, end, anticlockwise }); },
    beginPath() {}, rect() {}, clip() {}, moveTo() {}, lineTo() {}, stroke() { this.strokes++; },
  };
  return { width: 0, height: 0, style: {}, getContext: () => ctx };
}

test('fractional DPR preserves one CSS pixel per logical pixel at every output height', () => {
  for (const height of [80, 81, 240, 801]) {
    const canvas = fakeCanvas();
    const ctx = resizeCanvas(canvas, 400, height);
    ctx.fillRect(0, 10, 1, 1);
    ctx.fillRect(0, 30, 1, 1);
    const pixelDisplacement = ctx.rectangles[1].y - ctx.rectangles[0].y;
    const cssDisplacement = pixelDisplacement * height / canvas.height;
    assert.ok(Math.abs(cssDisplacement - 20) < 1e-10, `height ${height}: ${cssDisplacement}`);
  }
});

test('preview motion keeps the same display scale at equal widths as output height changes', () => {
  for (const width of [400, 800]) {
    for (const overlayHeight of [80, 81, 240, 801]) {
      const settings = normalizeSettings({ width, heightMode: 'manual', manualOverlayHeight: overlayHeight, greenNumber: 433.8, suddenNumber: 600 });
      const engine = new TrailEngine(settings);
      engine.press(1, 0);
      const canvas = fakeCanvas(), ctx = canvas.getContext('2d');
      const headPositions = [100, 200].map(now => {
        drawPreview(canvas, { settings, engine }, now);
        const head = ctx.rectangles.find(rectangle => rectangle.color === '#e8edf5' && rectangle.logicalHeight === settings.noteHeight);
        const [aspectWidth, aspectHeight] = canvas.style.aspectRatio.split('/').map(Number);
        const cssHeight = parseFloat(canvas.style.width) * aspectHeight / aspectWidth;
        return head.y * cssHeight / canvas.height;
      });
      // 400 logical px/s travels 40px in 100ms. The 800px preview has a fixed 50% width scale.
      const expectedDisplacement = width === 400 ? 40 : 20;
      assert.ok(Math.abs(headPositions[1] - headPositions[0] - expectedDisplacement) < 1e-10,
        `width ${width}, height ${overlayHeight}`);
    }
  }
});

test('auto LIFT zero draws no input, guides, or background on the 1px placeholder', () => {
  for (const background of ['black', 'transparent']) {
    const settings = normalizeSettings({ heightMode: 'auto', liftNumber: 0, showGuides: true, background });
    const engine = new TrailEngine(settings);
    engine.press(1, 0);
    engine.press(0, 0, 1);
    const canvas = fakeCanvas(), ctx = resizeCanvas(canvas, settings.width, settings.overlayHeight);
    drawOverlay(ctx, engine, settings, 20);
    assert.equal(settings.overlayHeight, 1);
    assert.deepEqual(ctx.rectangles, []);
    assert.equal(ctx.strokes, 0);
  }
});

test('manual mode can render with zero game LIFT while auto positive LIFT renders in the derived height', () => {
  for (const raw of [
    { heightMode: 'manual', liftNumber: 0, manualOverlayHeight: 400 },
    { heightMode: 'auto', liftNumber: 401 },
  ]) {
    const settings = normalizeSettings(raw);
    const engine = new TrailEngine(settings);
    engine.press(1, 0);
    const canvas = fakeCanvas(), ctx = resizeCanvas(canvas, settings.width, settings.overlayHeight);
    drawOverlay(ctx, engine, settings, 20);
    assert.equal(ctx.rectangles.find(rectangle => rectangle.color === '#000000').logicalHeight, settings.overlayHeight);
    assert.ok(ctx.rectangles.some(rectangle => rectangle.color === '#e8edf5'));
    assert.ok(ctx.strokes > 0);
  }
});

test('both scratch directions use distinct note colors and matching circular arrows in 1P and 2P', () => {
  for (const side of ['1P', '2P']) {
    for (const direction of [1, -1]) {
      for (const heldMs of [1, 100, 1000]) {
        const settings = normalizeSettings({ side, heightMode: 'manual', manualOverlayHeight: 400 });
        const engine = new TrailEngine(settings);
        engine.press(0, 0, direction); engine.release(0, heldMs);
        engine.press(1, heldMs);
        const ctx = fakeCanvas().getContext('2d');
        drawOverlay(ctx, engine, settings, heldMs + 20);
        const expected = SCRATCH_COLORS[direction === 1 ? 'clockwise' : 'counterclockwise'];
        assert.ok(ctx.rectangles.some(rect => rect.color === expected && rect.logicalHeight === settings.noteHeight));
        assert.ok(ctx.rectangles.some(rect => rect.color === NOTE_COLORS[1]));
        assert.equal(ctx.arcs.length, 1, 'even a short scratch has a circular marker');
        assert.equal(ctx.arcs[0].anticlockwise, direction === -1, 'player side must not reverse physical rotation');
        assert.ok(ctx.arcs[0].radius >= 2);
      }
    }
  }
});

test('scratch reversals retain both colors in successive segments without changing note timing', () => {
  const settings = normalizeSettings({ heightMode: 'manual', manualOverlayHeight: 600 });
  const engine = new TrailEngine(settings);
  engine.press(0, 0, 1); engine.press(0, 80, -1); engine.release(0, 160);
  const before = engine.snapshot(180);
  const ctx = fakeCanvas().getContext('2d');
  drawOverlay(ctx, engine, settings, 180);
  const heads = ctx.rectangles.filter(rect => rect.logicalHeight === settings.noteHeight);
  assert.deepEqual(heads.map(rect => rect.color), [SCRATCH_COLORS.clockwise, SCRATCH_COLORS.counterclockwise]);
  assert.deepEqual(ctx.arcs.map(arc => arc.anticlockwise), [false, true]);
  assert.deepEqual(engine.snapshot(180), before);
});

test('complete circular markers fit inside the narrowest supported scratch lane', () => {
  for (const side of ['1P', '2P']) {
    for (const direction of [1, -1]) {
      const settings = normalizeSettings({ side, width: 160, scratchWidth: .5, blackKeyRatio: 2,
        heightMode: 'manual', manualOverlayHeight: 240 });
      const engine = new TrailEngine(settings); engine.press(0, 0, direction);
      const ctx = fakeCanvas().getContext('2d');
      drawOverlay(ctx, engine, settings, 60);
      const lane = laneGeometry(settings)[0], arc = ctx.arcs[0];
      const outerExtent = arc.radius * 1.55 + Math.min(4, arc.radius * .7) / 2;
      assert.ok(arc.x - outerExtent >= lane.x + 1 - 1e-10);
      assert.ok(arc.x + outerExtent <= lane.x + lane.width - 1 + 1e-10);
    }
  }
});

function trailFixture(raw = {}) {
  const settings = normalizeSettings({ greenNumber: 433.8, heightMode: 'manual', manualOverlayHeight: 1000,
    background: 'transparent', showGuides: false, shortInputEnabled: true, ...raw });
  const engine = new TrailEngine(settings);
  const ctx = fakeCanvas().getContext('2d');
  return { settings, engine, ctx };
}

test('head-only mode draws exactly one head for every keyboard lane, held and released at any duration', () => {
  for (let lane = 1; lane <= 7; lane++) {
    for (const duration of [0, 80, 200, 500]) {
      for (const released of [false, true]) {
        const { settings, engine, ctx } = trailFixture({ inputBodyEnabled: false });
        engine.press(lane, 100);
        if (released) engine.release(lane, 100 + duration);
        const before = engine.snapshot(120 + duration);
        const rawEvent = engine.events[0];
        drawOverlay(ctx, engine, settings, 120 + duration);
        assert.equal(ctx.rectangles.length, 1, `lane ${lane}, duration ${duration}, released ${released}`);
        const [head] = ctx.rectangles;
        assert.equal(head.logicalHeight, settings.noteHeight);
        assert.equal(head.y, duration + 20 - settings.noteHeight / 2);
        assert.equal(head.color, NOTE_COLORS[lane]);
        assert.deepEqual(engine.snapshot(120 + duration), before);
        assert.equal(engine.events[0], rawEvent);
        assert.equal(engine.active.has(lane), !released);
      }
    }
  }
});

test('head-only rendering respects press delay and keeps the head moving smoothly through release', () => {
  const { settings, engine, ctx } = trailFixture({ inputBodyEnabled: false, delayMs: 100 });
  engine.press(1, 100); engine.release(1, 160);
  for (const [now, expectedY] of [[199, null], [200, -3], [250, 47], [260, 57], [280, 77]]) {
    ctx.clearRect();
    drawOverlay(ctx, engine, settings, now);
    if (expectedY === null) assert.deepEqual(ctx.rectangles, []);
    else {
      assert.equal(ctx.rectangles.length, 1);
      assert.equal(ctx.rectangles[0].y, expectedY);
      assert.equal(ctx.rectangles[0].logicalHeight, settings.noteHeight);
    }
  }
});

test('re-enabling bodies restores the selected short-input ratio without changing recorded input', () => {
  const { settings, engine, ctx } = trailFixture({ shortInputThresholdMs: 300, shortInputPercent: 50 });
  engine.press(1, 100); engine.release(1, 200);
  const render = inputBodyEnabled => {
    ctx.clearRect();
    drawOverlay(ctx, engine, { ...settings, inputBodyEnabled }, 220);
    return structuredClone(ctx.rectangles);
  };
  const original = render(true);
  assert.equal(original[0].logicalHeight, 50);
  assert.deepEqual(render(false), [original[1]]);
  assert.deepEqual(render(true), original);
});

test('head-only setting leaves scratch ribbons, tail caps, and arrows unchanged on either side', () => {
  for (const side of ['1P', '2P']) {
    for (const direction of [-1, 1]) {
      for (const released of [false, true]) {
        const render = inputBodyEnabled => {
          const { settings, engine, ctx } = trailFixture({ side, inputBodyEnabled });
          engine.press(0, 100, direction);
          if (released) engine.release(0, 180);
          drawOverlay(ctx, engine, settings, 200);
          return { rectangles: ctx.rectangles, arcs: ctx.arcs, strokes: ctx.strokes };
        };
        const original = render(true);
        assert.equal(original.rectangles.length, 3);
        assert.equal(original.arcs.length, 1);
        assert.deepEqual(render(false), original);
      }
    }
  }
});

test('preview game chart retains its long-note body while head-only mode affects input marks', () => {
  const { settings, engine } = trailFixture({ inputBodyEnabled: false });
  engine.press(1, 100); engine.release(1, 200);
  const canvas = fakeCanvas();
  drawPreview(canvas, { settings, engine }, 220, [{ lane: 1, start: 200, end: 300, long: true }]);
  const notes = canvas.getContext('2d').rectangles.filter(rect => rect.color === NOTE_COLORS[1]);
  assert.deepEqual(notes.map(rect => rect.logicalHeight), [100, settings.noteHeight, 2, settings.noteHeight]);
});

test('finished short keyboard trails shrink only the body, preserving press position and raw history', () => {
  for (let lane = 1; lane <= 7; lane++) {
    for (const percent of [1, 30, 75]) {
      const { settings, engine, ctx } = trailFixture({ shortInputPercent: percent });
      engine.press(lane, 100); engine.release(lane, 200);
      const rawEvent = engine.events[0];
      const before = engine.snapshot(220);
      drawOverlay(ctx, engine, settings, 220);
      const [body, head, tail] = ctx.rectangles;
      assert.equal(body.logicalHeight, percent);
      assert.equal(body.y, 120 - percent);
      assert.equal(head.y, 120 - settings.noteHeight / 2);
      assert.equal(head.logicalHeight, settings.noteHeight);
      assert.equal(tail.y, body.y);
      assert.equal(engine.events[0], rawEvent);
      assert.deepEqual(rawEvent, { lane, start: 100, end: 200, direction: 0 });
      assert.deepEqual(engine.snapshot(220), before);
      assert.equal(engine.active.size, 0);
    }
  }
});

test('compression uses a strict configurable threshold and keeps equal or longer inputs unchanged', () => {
  for (const threshold of [50, 200, 1000]) {
    for (const duration of [threshold - 1, threshold, threshold + 1]) {
      const { settings, engine, ctx } = trailFixture({ shortInputThresholdMs: threshold });
      engine.press(1, 100); engine.release(1, 100 + duration);
      drawOverlay(ctx, engine, settings, 120 + duration);
      const expected = duration < threshold ? duration * .3 : duration;
      assert.ok(Math.abs(ctx.rectangles[0].logicalHeight - expected) < 1e-9,
        `threshold ${threshold}, duration ${duration}`);
    }
  }
});

test('held keyboard inputs stay on the judgment line before and after the threshold', () => {
  for (const elapsed of [50, 200, 500]) {
    const { settings, engine, ctx } = trailFixture();
    engine.press(1, 100);
    drawOverlay(ctx, engine, settings, 100 + elapsed);
    const [body, head] = ctx.rectangles;
    assert.equal(body.y, 0);
    assert.equal(body.logicalHeight, elapsed);
    assert.equal(head.y, elapsed - settings.noteHeight / 2);
    assert.equal(engine.active.get(1).end, null);
  }
});

test('a known future release is compressed only when the display delay reaches that release', () => {
  const { settings, engine, ctx } = trailFixture({ delayMs: 100 });
  engine.press(1, 100); engine.release(1, 160);
  drawOverlay(ctx, engine, settings, 199);
  assert.deepEqual(ctx.rectangles, [], 'the delayed press is not visible early');
  drawOverlay(ctx, engine, settings, 250);
  assert.equal(ctx.rectangles[0].logicalHeight, 50);
  assert.equal(ctx.rectangles[0].y, 0);
  assert.equal(engine.snapshot(250)[0].active, true);
  ctx.clearRect();
  drawOverlay(ctx, engine, settings, 260);
  assert.equal(ctx.rectangles[0].logicalHeight, 18);
  assert.equal(ctx.rectangles[0].y, 42);
  assert.equal(ctx.rectangles[1].y, 60 - settings.noteHeight / 2);
  assert.equal(engine.snapshot(260)[0].active, false);
});

test('disabled compression and a 100 percent setting preserve the complete original rendering', () => {
  const render = raw => {
    const { settings, engine, ctx } = trailFixture(raw);
    engine.press(1, 100); engine.release(1, 180);
    drawOverlay(ctx, engine, settings, 200);
    return ctx.rectangles;
  };
  const original = render({ shortInputEnabled: false });
  assert.equal(original[0].logicalHeight, 80);
  assert.deepEqual(render({ shortInputEnabled: false, shortInputPercent: 1 }), original);
  assert.deepEqual(render({ shortInputPercent: 100 }), original);
});

test('short scratch trails retain their complete rendering and direction markers with compression enabled', () => {
  for (const side of ['1P', '2P']) {
    for (const direction of [-1, 1]) {
      const render = shortInputEnabled => {
        const { settings, engine, ctx } = trailFixture({ shortInputEnabled, side });
        engine.press(0, 100, direction); engine.release(0, 180);
        drawOverlay(ctx, engine, settings, 200);
        return { rectangles: ctx.rectangles, arcs: ctx.arcs, strokes: ctx.strokes };
      };
      const original = render(false);
      assert.equal(original.rectangles[0].logicalHeight, 80);
      assert.equal(original.arcs.length, 1);
      assert.deepEqual(render(true), original);
    }
  }
});

test('zero-duration keyboard taps keep their visible head without inventing trail duration', () => {
  const { settings, engine, ctx } = trailFixture();
  engine.press(1, 100); engine.release(1, 100);
  drawOverlay(ctx, engine, settings, 120);
  assert.equal(ctx.rectangles[0].logicalHeight, 0);
  assert.equal(ctx.rectangles[0].y, 20);
  assert.equal(ctx.rectangles[1].logicalHeight, settings.noteHeight);
  assert.equal(ctx.rectangles[1].y, 20 - settings.noteHeight / 2);
});

test('preview game notes stay unchanged while the input overlay uses compressed trails', () => {
  const { settings, engine } = trailFixture();
  engine.press(1, 100); engine.release(1, 200);
  const canvas = fakeCanvas();
  drawPreview(canvas, { settings, engine }, 220, [{ lane: 1, start: 200, end: 300, long: true }]);
  const notes = canvas.getContext('2d').rectangles.filter(rect => rect.color === NOTE_COLORS[1]);
  assert.deepEqual(notes.map(rect => rect.logicalHeight), [100, settings.noteHeight, 2, 30, settings.noteHeight, 2]);
});
