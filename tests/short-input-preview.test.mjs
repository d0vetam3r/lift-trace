import test, { before, after } from 'node:test';
import assert from 'node:assert/strict';
import { normalizeSettings } from '../web/engine.js';
import { NOTE_COLORS } from '../web/render.js';
import { drawShortInputComparison } from '../web/short-input-preview.js';

const originalWindow = globalThis.window;
before(() => { globalThis.window = { devicePixelRatio: 1 }; });
after(() => {
  if (originalWindow === undefined) delete globalThis.window;
  else globalThis.window = originalWindow;
});

function fakeCanvas() {
  let transform = [1, 1, 0, 0];
  const stack = [];
  const ctx = {
    rectangles: [], texts: [],
    setTransform(x, _b, _c, y, tx, ty) { transform = [x, y, tx, ty]; },
    translate(x, y) { transform[2] += x * transform[0]; transform[3] += y * transform[1]; },
    save() { stack.push({ transform: [...transform], fillStyle: this.fillStyle, globalAlpha: this.globalAlpha }); },
    restore() { const state = stack.pop(); transform = state.transform; this.fillStyle = state.fillStyle; this.globalAlpha = state.globalAlpha; },
    fillRect(x, y, width, height) {
      this.rectangles.push({ x: x * transform[0] + transform[2], y: y * transform[1] + transform[3],
        width: width * transform[0], height: height * transform[1], logicalHeight: height, color: this.fillStyle });
    },
    fillText(text) { this.texts.push(text); },
    clearRect() { this.rectangles = []; this.texts = []; },
    beginPath() {}, rect() {}, clip() {},
  };
  return { width: 0, height: 0, style: {}, getContext: () => ctx };
}

function compare(raw = {}) {
  const settings = normalizeSettings({ shortInputEnabled: true, shortInputPercent: 30, shortInputThresholdMs: 200, ...raw });
  const canvas = fakeCanvas();
  drawShortInputComparison(canvas, settings, { original: '원래 길이', current: '조정한 길이' });
  const notes = canvas.getContext('2d').rectangles.filter(rect => NOTE_COLORS.includes(rect.color));
  assert.equal(notes.length, 18, 'six samples each retain the real renderer’s body, head, and tail');
  const bodies = notes.filter((_, index) => index % 3 === 0);
  return { canvas, notes, original: bodies.slice(0, 3), current: bodies.slice(3) };
}

test('comparison shows real renderer body lengths at 30 and 85 percent, with long samples unchanged', () => {
  for (const percent of [30, 85]) {
    const result = compare({ shortInputPercent: percent });
    assert.deepEqual(result.original.map(rect => rect.logicalHeight), [24, 45, 90]);
    const expected = [24 * percent / 100, 45 * percent / 100, 90];
    result.current.forEach((rect, index) => assert.ok(Math.abs(rect.logicalHeight - expected[index]) < 1e-9));
    result.current.forEach((rect, index) => assert.equal(rect.y + rect.height, result.original[index].y + result.original[index].height));
    assert.deepEqual(result.canvas.getContext('2d').texts, ['원래 길이', '80 ms', '150 ms', '300 ms', '조정한 길이', '80 ms', '150 ms', '300 ms']);
  }
});

test('a sample at the threshold keeps its full length, while shorter samples shrink', () => {
  const result = compare({ shortInputThresholdMs: 150 });
  assert.ok(Math.abs(result.current[0].logicalHeight - 7.2) < 1e-9);
  assert.equal(result.current[1].logicalHeight, 45);
  assert.equal(result.current[2].logicalHeight, 90);
});

test('disabled compression and 100 percent both show identical original and current notes', () => {
  for (const settings of [{ shortInputEnabled: false }, { shortInputPercent: 100 }]) {
    const result = compare(settings);
    const relative = (rect, xOffset) => ({ ...rect, x: rect.x - xOffset });
    assert.deepEqual(result.notes.slice(9).map(rect => relative(rect, 150)), result.notes.slice(0, 9));
  }
});

test('comparison supports fractional and high DPR with a responsive fixed aspect ratio', () => {
  for (const dpr of [1, 1.25, 3]) {
    globalThis.window.devicePixelRatio = dpr;
    const result = compare();
    const scale = Math.min(dpr, 2);
    assert.equal(result.canvas.width, Math.round(300 * scale));
    assert.equal(result.canvas.height, Math.round(190 * scale));
    assert.equal(result.canvas.style.width, '100%');
    assert.equal(result.canvas.style.height, 'auto');
    assert.equal(result.canvas.style.aspectRatio, '300 / 190');
    assert.ok(Math.abs(result.original[0].height / result.canvas.height * 190 - 24) < 1e-9);
  }
  globalThis.window.devicePixelRatio = 1;
});

test('rendering is deterministic and leaves settings, mapping, and labels untouched', () => {
  const settings = normalizeSettings({ shortInputEnabled: true, shortInputPercent: 85, side: '2P', liftNumber: 0 });
  Object.freeze(settings.buttonMap); Object.freeze(settings);
  const before = structuredClone(settings), labels = Object.freeze({ original: 'Before', current: 'After', scratch: 'Scratch' });
  const canvas = fakeCanvas();
  drawShortInputComparison(canvas, settings, labels);
  const first = structuredClone(canvas.getContext('2d').rectangles);
  drawShortInputComparison(canvas, settings, labels);
  assert.deepEqual(canvas.getContext('2d').rectangles, first);
  assert.deepEqual(settings, before);
  assert.deepEqual(labels, { original: 'Before', current: 'After', scratch: 'Scratch' });
});

test('heads-only comparison keeps original bodies and draws exactly three adjusted heads', () => {
  const settings = normalizeSettings({ inputBodyEnabled:false, shortInputEnabled:true, shortInputPercent:50, shortInputThresholdMs:300 });
  const canvas = fakeCanvas();
  drawShortInputComparison(canvas, settings);
  const notes = canvas.getContext('2d').rectangles.filter(rect => NOTE_COLORS.includes(rect.color));
  assert.equal(notes.length, 12, 'originals have body/head/tail; adjusted samples have only heads');
  assert.deepEqual(notes.slice(0, 9).filter((_, i) => i % 3 === 0).map(rect => rect.logicalHeight), [24, 45, 90]);
  const originalHeads = notes.slice(0, 9).filter((_, i) => i % 3 === 1);
  assert.deepEqual(notes.slice(9).map(rect => ({...rect, x:rect.x - 150})), originalHeads);
});
