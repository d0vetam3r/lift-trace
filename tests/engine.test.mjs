import test from 'node:test';
import assert from 'node:assert/strict';
import { DEFAULTS, FULLSCREEN_LANE_HEIGHT, FULLSCREEN_LAYOUT, normalizeSettings, getGameGeometry, getSpeed, getObsPlacement, TrailEngine, ScratchTracker } from '../web/engine.js';

const SPEED_1000 = { greenNumber: 433.8, heightMode: 'manual', manualOverlayHeight: 240 };

test('OBS coordinates follow player side and LIFT at the fullscreen reference', () => {
  assert.deepEqual(getObsPlacement({ side: '1P', liftNumber: 401 }), { x: 75, y: 433 });
  assert.deepEqual(getObsPlacement({ side: '2P', liftNumber: 401 }), { x: 1413, y: 433 });
  assert.deepEqual(getObsPlacement({ liftNumber: 0 }), { x: 75, y: 723 });
  assert.deepEqual(getObsPlacement({ liftNumber: 999 }), { x: 75, y: 1 });
  assert.equal(getObsPlacement({ side: '2P' }).x + FULLSCREEN_LAYOUT.laneWidth,
    FULLSCREEN_LAYOUT.canvasWidth - FULLSCREEN_LAYOUT.laneX);
  for (let liftNumber = 1; liftNumber <= 999; liftNumber++) {
    const settings = normalizeSettings({ liftNumber });
    assert.equal(getObsPlacement(settings).y + settings.overlayHeight, FULLSCREEN_LAYOUT.judgmentY);
  }
});

test('OBS position is independent of manual output size, upper cover, note speed and scratch direction', () => {
  for (const side of ['1P', '2P']) {
    const expected = getObsPlacement({ side, liftNumber: 401 });
    for (const height of [40, 360, 2160]) {
      assert.deepEqual(getObsPlacement({ side, liftNumber: 401, heightMode: 'manual', manualOverlayHeight: height,
        width: height + 160, suddenNumber: 300, greenNumber: 600, speedScale: 2, delayMs: 100, scratchInvert: true }), expected);
    }
  }
});

test('placement corrections persist, remain bounded, and never affect note timing', () => {
  const settings = normalizeSettings({ side: '2P', liftNumber: 401, obsOffsetX: '12.3', obsOffsetY: -3.8 });
  assert.deepEqual(getObsPlacement(settings), { x: 1425, y: 429 });
  assert.deepEqual(normalizeSettings(JSON.parse(JSON.stringify(settings))), settings);
  assert.equal(getSpeed(settings), getSpeed({ liftNumber: 401 }));
  const invalid = normalizeSettings({ obsOffsetX: 'bad', obsOffsetY: Infinity });
  assert.equal(invalid.obsOffsetX, 0); assert.equal(invalid.obsOffsetY, 0);
  assert.deepEqual(getObsPlacement({ obsOffsetX: 1e9, obsOffsetY: -1e9 }), { x: 3915, y: -1437 });
});

test('fullscreen game geometry, green number, and calibration set pixels per second', () => {
  assert.equal(FULLSCREEN_LANE_HEIGHT, 723);
  assert.deepEqual(getGameGeometry({ suddenNumber: 200, liftNumber: 100 }), {
    baseHeight: 723, visibleHeight: 506.1, suddenHeight: 144.6, liftHeight: 72.3,
  });
  assert.equal(getSpeed(SPEED_1000), 1000);
  assert.equal(getSpeed({ ...SPEED_1000, speedScale: 1.2 }), 1200);
  assert.equal(getSpeed({ greenNumber: 867.6 }), 500);
  assert.equal(getSpeed({ ...SPEED_1000, suddenNumber: 200 }), 800);
  assert.equal(getSpeed({ ...SPEED_1000, liftNumber: 300 }), 700);
  assert.equal(getSpeed({ ...SPEED_1000, suddenNumber: 200, liftNumber: 300 }), 500);
});

test('overlay dimensions preserve speed and head/tail position, changing only retirement time', () => {
  const engines = [80, 240, 800].map(manualOverlayHeight => new TrailEngine({ ...SPEED_1000, manualOverlayHeight }));
  for (const engine of engines) {
    engine.press(1, 100);
    engine.release(1, 140);
    assert.equal(getSpeed(engine.settings), 1000);
    assert.deepEqual(engine.snapshot(170), [{ lane: 1, start: 100, end: 140, direction: 0,
      headY: 70, tailY: 30, active: false }]);
  }
  // A released tail leaves a small output first; the larger outputs retain identical geometry.
  assert.equal(engines[0].snapshot(227).length, 0);
  assert.equal(engines[1].snapshot(227)[0].tailY, 87);
  assert.equal(engines[2].snapshot(227)[0].tailY, 87);
  assert.equal(engines[1].snapshot(387).length, 0);
  assert.equal(engines[2].snapshot(387)[0].tailY, 247);
  assert.equal(engines[2].snapshot(947).length, 0);
  assert.equal(getSpeed({ ...SPEED_1000, width: 160 }), getSpeed({ ...SPEED_1000, width: 3840 }));
});

test('legacy dimensions retain a manual fallback but adopt automatic height without influencing speed', () => {
  const migrated = normalizeSettings({ visibleHeight: 80, liftHeight: 640 });
  assert.equal(migrated.heightMode, 'auto');
  assert.equal(migrated.overlayHeight, 1);
  assert.equal(migrated.manualOverlayHeight, 640);
  assert.equal(Object.hasOwn(migrated, 'visibleHeight'), false);
  assert.equal(Object.hasOwn(migrated, 'liftHeight'), false);
  assert.equal(getSpeed(migrated), getSpeed(DEFAULTS));
  assert.equal(normalizeSettings({ overlayHeight: 350, liftHeight: 640 }).manualOverlayHeight, 350);
  assert.equal(normalizeSettings({ overlayHeight: NaN, liftHeight: 640 }).manualOverlayHeight, DEFAULTS.manualOverlayHeight);
  assert.equal(getSpeed({ visibleHeight: 2000, liftHeight: 40 }), getSpeed(DEFAULTS));
});

test('automatic height follows fullscreen LIFT numbers, including a blank 1px zero-LIFT placeholder', () => {
  assert.equal(normalizeSettings({ liftNumber: 401 }).overlayHeight, 290);
  assert.equal(normalizeSettings({ liftNumber: 200 }).overlayHeight, 145);
  assert.equal(normalizeSettings({ liftNumber: 0 }).overlayHeight, 1);
  assert.equal(normalizeSettings({ liftNumber: 1 }).overlayHeight, 1);
  assert.deepEqual(normalizeSettings(DEFAULTS), DEFAULTS);
});

test('manual height survives automatic changes, persisted normalization, and switching back', () => {
  const engine = new TrailEngine({ heightMode: 'manual', manualOverlayHeight: 555, liftNumber: 401 });
  assert.equal(engine.settings.overlayHeight, 555);
  engine.configure({ liftNumber: 200 });
  assert.equal(engine.settings.overlayHeight, 555);
  engine.configure({ heightMode: 'auto' });
  assert.equal(engine.settings.overlayHeight, 145);
  assert.equal(engine.settings.manualOverlayHeight, 555);
  engine.configure({ liftNumber: 401 });
  assert.equal(engine.settings.overlayHeight, 290);
  const restored = normalizeSettings(JSON.parse(JSON.stringify(engine.settings)));
  assert.deepEqual(normalizeSettings(restored), restored);
  assert.equal(restored.manualOverlayHeight, 555);
  engine.configure({ ...restored, heightMode: 'manual' });
  assert.equal(engine.settings.overlayHeight, 555);
  // Effective dimensions from stale clients are not user edits to the saved crop.
  engine.configure({ overlayHeight: 999 });
  assert.equal(engine.settings.overlayHeight, 555);
  engine.configure({ manualOverlayHeight: 600 });
  assert.equal(engine.settings.overlayHeight, 600);
});

test('height migration and coercion honor explicit manual mode and preserve normalization idempotence', () => {
  const cases = [
    [{ liftNumber: '401', overlayHeight: '650' }, 'auto', 290, 650],
    [{ heightMode: 'manual', liftHeight: '350' }, 'manual', 350, 350],
    [{ heightMode: 'MANUAL', liftNumber: '200', manualOverlayHeight: -4 }, 'auto', 145, 40],
    [{ heightMode: 'manual', manualOverlayHeight: 9999, overlayHeight: 140 }, 'manual', 2160, 2160],
    [{ heightMode: 'manual', manualOverlayHeight: NaN, overlayHeight: 650 }, 'manual', 240, 240],
    [{ heightMode: 'manual', manualOverlayHeight: '500.6' }, 'manual', 501, 501],
  ];
  for (const [raw, mode, effective, manual] of cases) {
    const settings = normalizeSettings(raw);
    assert.equal(settings.heightMode, mode);
    assert.equal(settings.overlayHeight, effective);
    assert.equal(settings.manualOverlayHeight, manual);
    assert.deepEqual(normalizeSettings(settings), settings);
  }
});

test('automatic and manual height modes have identical speed and currently visible note positions', () => {
  const base = { greenNumber: 300, suddenNumber: 150, liftNumber: 401, manualOverlayHeight: 800 };
  const auto = new TrailEngine({ ...base, heightMode: 'auto' });
  const manual = new TrailEngine({ ...base, heightMode: 'manual' });
  for (const engine of [auto, manual]) { engine.press(1, 100); engine.release(1, 140); }
  assert.equal(getSpeed(auto.settings), getSpeed(manual.settings));
  assert.deepEqual(auto.snapshot(170), manual.snapshot(170));
  assert.equal(auto.settings.overlayHeight, 290);
  assert.equal(manual.settings.overlayHeight, 800);
});

test('black-key width defaults preserve old layouts and imports stay bounded without changing speed', () => {
  assert.equal(normalizeSettings({}).blackKeyRatio, 1);
  assert.equal(normalizeSettings({ blackKeyRatio: NaN }).blackKeyRatio, 1);
  assert.equal(normalizeSettings({ blackKeyRatio: -1 }).blackKeyRatio, .25);
  assert.equal(normalizeSettings({ blackKeyRatio: 99 }).blackKeyRatio, 2);
  assert.equal(normalizeSettings({ blackKeyRatio: '0.75' }).blackKeyRatio, .75);
  assert.equal(getSpeed({ blackKeyRatio: .25 }), getSpeed({ blackKeyRatio: 2 }));
});

test('head falls immediately, held tail remains on the judgment line', () => {
  const engine = new TrailEngine({ ...SPEED_1000, manualOverlayHeight: 500 });
  engine.press(3, 100);
  assert.deepEqual(engine.snapshot(200), [{ lane: 3, start: 100, end: null, direction: 0, headY: 100, tailY: 0, active: true }]);
  engine.release(3, 250);
  assert.deepEqual(engine.snapshot(300), [{ lane: 3, start: 100, end: 250, direction: 0, headY: 200, tailY: 50, active: false }]);
});

test('short taps and zero-duration taps remain visible', () => {
  const engine = new TrailEngine(SPEED_1000);
  engine.press(1, 0);
  engine.release(1, 1);
  engine.press(2, 2);
  engine.release(2, 2);
  const notes = engine.snapshot(10);
  assert.equal(notes[0].headY - notes[0].tailY, 1);
  assert.equal(notes[1].headY, notes[1].tailY);
  assert.equal(notes.length, 2);
});

test('positive delay hides future inputs and delays the release too', () => {
  const engine = new TrailEngine({ delayMs: 100, ...SPEED_1000 });
  engine.press(1, 20);
  engine.release(1, 60);
  assert.equal(engine.snapshot(119).length, 0);
  assert.equal(engine.snapshot(120)[0].headY, 0);
  assert.equal(engine.snapshot(140)[0].active, true);
  assert.equal(engine.snapshot(140)[0].tailY, 0);
  assert.equal(engine.snapshot(170)[0].tailY, 10);
  assert.equal(engine.snapshot(170)[0].active, false);
});

test('negative delay is clamped so new input starts on the judgment line', () => {
  const engine = new TrailEngine({ delayMs: -20, ...SPEED_1000 });
  engine.press(1, 100);
  assert.equal(engine.settings.delayMs, 0);
  assert.equal(engine.snapshot(100)[0].headY, 0);
});

test('duplicate presses do not spawn notes; a scratch reversal splits ribbons', () => {
  const engine = new TrailEngine({ heightMode: 'manual' });
  engine.press(2, 10);
  engine.press(2, 20);
  engine.press(0, 10, 1);
  engine.press(0, 15, 1);
  engine.press(0, 25, -1);
  const notes = engine.snapshot(30);
  assert.equal(notes.length, 3);
  assert.equal(notes[1].end, 25);
  assert.equal(notes[2].direction, -1);
});

test('stalled rendering prunes every expired released note, preserves holds', () => {
  const engine = new TrailEngine();
  for (let n = 0; n < 100; n++) { engine.press(1, n * 5); engine.release(1, n * 5 + 1); }
  engine.press(2, 600);
  assert.equal(engine.snapshot(100000).length, 1);
  assert.equal(engine.events.length, 1);
  engine.reset();
  assert.deepEqual(engine.snapshot(100001), []);
});

test('input-only producer is bounded without rendering', () => {
  const engine = new TrailEngine();
  engine.press(7, 0);
  for (let n = 0; n < 5000; n++) { engine.press(1, n); engine.release(1, n); }
  assert.ok(engine.events.length <= 4096);
  assert.equal(engine.active.get(7).start, 0);
});

test('invalid settings and input cannot produce non-finite geometry', () => {
  const s = normalizeSettings({ greenNumber: NaN, width: Infinity, overlayHeight: -1, suddenNumber: NaN,
    liftNumber: Infinity, side: 'x', noteHeight: 999, buttonMap: [-99, NaN, '5'], showGuides: 'false', speedScale: 0 });
  assert.equal(s.greenNumber, DEFAULTS.greenNumber);
  assert.equal(s.width, DEFAULTS.width);
  assert.equal(s.overlayHeight, 1);
  assert.equal(s.manualOverlayHeight, 40);
  assert.equal(s.suddenNumber, 0);
  assert.equal(s.liftNumber, 0);
  assert.ok(Number.isFinite(getSpeed(s)) && getSpeed(s) > 0);
  assert.equal(s.noteHeight, 30);
  assert.equal(s.side, '1P');
  assert.equal(s.showGuides, true);
  assert.deepEqual(s.buttonMap, [0, 1, 5, 3, 4, 5, 6]);
  assert.equal(s.speedScale, 0.25);
  assert.equal(normalizeSettings(null).greenNumber, DEFAULTS.greenNumber);
  const engine = new TrailEngine(s);
  engine.press(8, 0); engine.press(1, NaN); engine.press(1.5, 0); engine.press(1, -1);
  assert.deepEqual(engine.snapshot(100), []);
  engine.press(1, 20); engine.release(1, 10);
  assert.equal(engine.snapshot(20)[0].end, 20);
  engine.configure({ width: 640 });
  assert.equal(engine.settings.width, 640);
  assert.equal(engine.settings.overlayHeight, 1);
  assert.equal(engine.settings.manualOverlayHeight, 40);
});

test('imported settings use the same bounds as the form and WinMM input', () => {
  const high = normalizeSettings({ suddenNumber: 9999, liftNumber: 9999, overlayHeight: 9999, width: 9999, noteHeight: 999,
    speedScale: 999, delayMs: 9999, axisIndex: 999, scratchThreshold: 2, buttonMap: [99,99,99,99,99,99,99] });
  assert.equal(high.suddenNumber, 0);
  assert.equal(high.liftNumber, 999);
  assert.equal(getGameGeometry(high).visibleHeight, .723);
  assert.ok(Number.isFinite(getSpeed(high)) && getSpeed(high) > 0);
  assert.equal(high.overlayHeight, 722);
  assert.equal(high.manualOverlayHeight, 2160);
  assert.equal(high.width, 3840);
  assert.equal(high.noteHeight, 30);
  assert.equal(high.speedScale, 4);
  assert.equal(high.delayMs, 2000);
  assert.equal(high.axisIndex, 5);
  assert.equal(high.scratchThreshold, .5);
  assert.deepEqual(high.buttonMap, [31,31,31,31,31,31,31]);
  const low = normalizeSettings({ suddenNumber: -1, liftNumber: -1, overlayHeight: -1, width: -1, noteHeight: -1, scratchThreshold: 0 });
  assert.equal(low.suddenNumber, 0);
  assert.equal(low.liftNumber, 0);
  assert.equal(low.overlayHeight, 1);
  assert.equal(low.manualOverlayHeight, 40);
  assert.equal(low.width, 160);
  assert.equal(low.noteHeight, 2);
  assert.equal(low.scratchThreshold, .001);
  const combined = normalizeSettings({ suddenNumber: 500.4, liftNumber: 600.7 });
  assert.equal(combined.liftNumber, 601);
  assert.equal(combined.suddenNumber, 398);
  assert.equal(combined.suddenNumber + combined.liftNumber, 999);
});

test('scratch wraps both boundaries without flipping the direction', () => {
  const positive = new ScratchTracker();
  assert.deepEqual(positive.update(0.99, 0), []);
  assert.deepEqual(positive.update(-0.99, 8), [{ down: true, direction: 1, time: 8 }]);
  assert.deepEqual(positive.update(-0.97, 16), []);
  const negative = new ScratchTracker();
  negative.update(-0.99, 0);
  assert.deepEqual(negative.update(0.99, 8), [{ down: true, direction: -1, time: 8 }]);
});

test('scratch polarity defaults preserve legacy settings and only accept a boolean', () => {
  assert.equal(DEFAULTS.scratchInvert, false);
  assert.equal(normalizeSettings({ axisIndex: 2, scratchThreshold: .02 }).scratchInvert, false);
  assert.equal(normalizeSettings({ scratchInvert: true }).scratchInvert, true);
  assert.equal(normalizeSettings({ scratchInvert: false }).scratchInvert, false);
  for (const invalid of ['true', 'false', 1, 0, null, {}, [], undefined]) {
    assert.equal(normalizeSettings({ scratchInvert: invalid }).scratchInvert, false);
  }
});

test('inverted scratch calibration preserves physical directions across both wraps and reversals', () => {
  const tracker = new ScratchTracker({ scratchInvert: true, scratchStopMs: 80 });
  tracker.update(-.98, 0);
  // Decreasing raw values cross the boundary; calibration identifies this as clockwise.
  assert.deepEqual(tracker.update(.99, 10), [{ down: true, direction: 1, time: 10 }]);
  assert.deepEqual(tracker.update(.97, 20), []);
  // Reversing and crossing back ends CW and starts CCW at the same instant.
  assert.deepEqual(tracker.update(-.99, 30), [
    { down: false, direction: 1, time: 30 },
    { down: true, direction: -1, time: 30 },
  ]);
  assert.deepEqual(tracker.tick(109), []);
  assert.deepEqual(tracker.tick(110), [{ down: false, direction: -1, time: 110 }]);
});

test('sub-threshold motion accumulates but alternating jitter cancels', () => {
  const tracker = new ScratchTracker({ scratchThreshold: 0.01 });
  tracker.update(0, 0);
  for (let t = 1; t <= 20; t++) assert.deepEqual(tracker.update(t % 2 ? 0.004 : 0, t), []);
  assert.deepEqual(tracker.update(0.003, 21), []);
  assert.deepEqual(tracker.update(0.006, 22), []);
  assert.deepEqual(tracker.update(0.009, 23), []);
  assert.deepEqual(tracker.update(0.012, 24), [{ down: true, direction: 1, time: 24 }]);
});

test('scratch direction reversal emits an up and a down at the same time', () => {
  const tracker = new ScratchTracker();
  tracker.update(0, 0);
  tracker.update(0.02, 10);
  assert.deepEqual(tracker.update(0, 20), [{ down: false, direction: 1, time: 20 }, { down: true, direction: -1, time: 20 }]);
});

test('scratch cessation closes at detection time for a smooth tail, including grace', () => {
  const tracker = new ScratchTracker({ scratchStopMs: 100 });
  tracker.update(0, 0);
  tracker.update(0.02, 10);
  tracker.update(0.04, 20);
  assert.deepEqual(tracker.tick(119), []);
  assert.deepEqual(tracker.tick(120), [{ down: false, direction: 1, time: 120 }]);
  assert.deepEqual(tracker.tick(500), []);
});

test('scratch tail stays at the judgment line until stop detection, then moves smoothly', () => {
  const tracker = new ScratchTracker({ scratchStopMs: 100 });
  const engine = new TrailEngine(SPEED_1000);
  tracker.update(0, 0);
  for (const event of tracker.update(.02, 10)) engine.press(0, event.time, event.direction);
  assert.equal(engine.snapshot(109)[0].tailY, 0);
  for (const event of tracker.tick(110)) engine.release(0, event.time);
  assert.equal(engine.snapshot(110)[0].tailY, 0);
  assert.equal(engine.snapshot(120)[0].tailY, 10);
});

test('bad axis samples, stale timestamps and large discontinuities are ignored', () => {
  const tracker = new ScratchTracker();
  assert.deepEqual(tracker.update(NaN, 0), []);
  assert.deepEqual(tracker.update(2, 0), []);
  tracker.update(0, 10);
  assert.deepEqual(tracker.update(0.1, 5), []);
  assert.deepEqual(tracker.update(0.75, 20), []);
  assert.deepEqual(tracker.update(0.77, 30), [{ down: true, direction: 1, time: 30 }]);
  tracker.reset();
  assert.deepEqual(tracker.tick(1000), []);
  assert.deepEqual(tracker.update(-0.9, 1001), []);
});
