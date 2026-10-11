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
