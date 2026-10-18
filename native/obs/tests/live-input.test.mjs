// SPDX-License-Identifier: MIT
// In-memory input fixtures only. No controller, socket, UI or OBS access.
import test from 'node:test';
import assert from 'node:assert/strict';
import { InputClient } from '../../../web/client.js';
import { LiveInputObserver } from '../live-input.mjs';

const BASE = Object.freeze({
  inputMode: 'native', greenNumber: 270, suddenNumber: 70, liftNumber: 401,
  width: 432, scratchWidth: 5 / 3, blackKeyRatio: 7 / 9, noteHeight: 12,
  inputBodyEnabled: false, shortInputEnabled: true, shortInputThresholdMs: 300,
  shortInputPercent: 50, scratchThreshold: .008, scratchStopMs: 100,
  axisIndex: 0, buttonMap: [0, 1, 2, 3, 4, 5, 6],
});

function pair(settings = BASE) {
  const observer = new LiveInputObserver();
  const reference = new InputClient();
  feed(observer, reference, { type: 'settings', settings });
  return { observer, reference };
}

function feed(observer, reference, event) {
  observer.accept(event);
  if (event.type === 'settings') reference.configure(event.settings);
  if (event.type === 'input') reference.native(event);
  if (event.type === 'key' && reference.settings.inputMode === 'demo') reference.applyKey(event);
  if (event.type === 'reset') reference.reset();
}

function capture(observer, reference, now) {
  reference.tick(now);
  reference.engine.prune(now);
  const snapshot = observer.snapshot(now);
  assert.equal(snapshot.type, 'snapshot');
  assert.equal(snapshot.epochMs, now);
  assert.deepEqual(snapshot.settings, reference.settings);
  assert.deepEqual(snapshot.events, reference.engine.events);
  return snapshot;
}

function raw(time, pressed = [], axis = 0) {
  return { type: 'input', time, device: 0,
    buttons: Array.from({ length: 7 }, (_, index) => pressed.includes(index)), axes: [axis] };
}

test('waits for settings and preserves simultaneous key press/release timestamps exactly', () => {
  const observer = new LiveInputObserver();
  assert.equal(observer.snapshot(100000), null);
  observer.accept(raw(100000, [0]));
  assert.equal(observer.snapshot(100000), null);
  const reference = new InputClient();
  feed(observer, reference, { type: 'settings', settings: BASE });
  feed(observer, reference, raw(100010.25, [0, 6]));
  feed(observer, reference, raw(100020.75, [0, 6]));
  feed(observer, reference, raw(100050.5, [6]));
  feed(observer, reference, raw(100070.125, []));
  const result = capture(observer, reference, 100080);
  assert.deepEqual(result.events, [
    { lane: 1, start: 100010.25, end: 100050.5, direction: 0 },
    { lane: 7, start: 100010.25, end: 100070.125, direction: 0 },
  ]);
});

test('scratch wrap, direction reversal and grace stop match the existing InputClient', () => {
  const { observer, reference } = pair();
  for (const event of [raw(100000, [], .90), raw(100010, [], .99),
    raw(100020, [], -.99), raw(100030, [], -.8), raw(100040, [], -.9)]) {
    feed(observer, reference, event);
    capture(observer, reference, event.time);
  }
  const before = capture(observer, reference, 100139);
  assert.deepEqual(before.events, [
    { lane: 0, start: 100010, end: 100040, direction: 1 },
    { lane: 0, start: 100040, end: null, direction: -1 },
  ]);
  // Existing scratch semantics use the actual observing tick time. They do
  // not retroactively stamp lastMotion + stopMs when a callback arrives late.
  const after = capture(observer, reference, 100143.5);
  assert.equal(after.events[1].end, 100143.5);
});

test('scratch accumulated movement and ambiguous jump rebase match canonical behavior', () => {
  const { observer, reference } = pair();
  for (const event of [raw(200000, [], 0), raw(200004, [], .003),
    raw(200008, [], .006), raw(200012, [], .009), raw(200016, [], .7)]) {
    feed(observer, reference, event);
  }
  const result = capture(observer, reference, 200020);
  assert.equal(result.events.length, 1);
  assert.deepEqual(result.events[0], { lane: 0, start: 200012, end: null, direction: 1 });
  assert.equal(capture(observer, reference, 200116).events[0].end, 200116);
});

test('display-only settings preserve raw key and scratch intervals', () => {
  const { observer, reference } = pair();
  feed(observer, reference, raw(300000, [0], 0));
  feed(observer, reference, raw(300010, [0], .1));
  feed(observer, reference, raw(300020, [], .2));
  const before = capture(observer, reference, 300030);
  feed(observer, reference, { type: 'settings', settings: { ...BASE,
    greenNumber: 320, noteHeight: 20, inputBodyEnabled: true,
    shortInputPercent: 1, side: '2P', background: 'transparent' } });
  const after = capture(observer, reference, 300040);
  assert.deepEqual(after.events, before.events);
  assert.equal(after.settings.noteHeight, 20);
  assert.equal(after.settings.shortInputPercent, 1);
});

test('OBS placement settings use existing normalization without resetting input', () => {
  const { observer, reference } = pair();
  feed(observer, reference, raw(350000.125, [0], 0));
  feed(observer, reference, raw(350010.25, [0], .1));
  const before = capture(observer, reference, 350020);
  feed(observer, reference, { type: 'settings', settings: { ...BASE,
    side: '2P', liftNumber: 500, obsOffsetX: '-17.4', obsOffsetY: 9999 } });
  const after = capture(observer, reference, 350030);
  assert.deepEqual(after.events, before.events);
  assert.equal(after.settings.side, '2P');
  assert.equal(after.settings.liftNumber, 500);
  assert.equal(after.settings.obsOffsetX, -17);
  assert.equal(after.settings.obsOffsetY, 2160);
});

test('mapping, mode, axis and scratch inversion changes retain canonical reset behavior', () => {
  for (const change of [
    { buttonMap: [6, 5, 4, 3, 2, 1, 0] }, { axisIndex: 1 },
    { scratchInvert: true }, { inputMode: 'demo' },
  ]) {
    const { observer, reference } = pair();
    feed(observer, reference, raw(400000, [0], 0));
    feed(observer, reference, raw(400010, [0], .1));
    assert.equal(capture(observer, reference, 400020).events.length, 2);
    feed(observer, reference, { type: 'settings', settings: { ...BASE, ...change } });
    assert.deepEqual(capture(observer, reference, 400030).events, []);
  }
});

test('demo keys and native keys obey the same mode gates; reset removes held marks', () => {
  const { observer, reference } = pair({ ...BASE, inputMode: 'demo' });
  feed(observer, reference, raw(500000, [0], .1));
  assert.deepEqual(capture(observer, reference, 500001).events, []);
  feed(observer, reference, { type: 'key', lane: 3, down: true, time: 500010 });
  feed(observer, reference, { type: 'key', lane: 3, down: false, time: 500050 });
  assert.deepEqual(capture(observer, reference, 500060).events,
    [{ lane: 3, start: 500010, end: 500050, direction: 0 }]);
  feed(observer, reference, { type: 'reset' });
  assert.deepEqual(capture(observer, reference, 500070).events, []);
  feed(observer, reference, { type: 'settings', settings: BASE });
  feed(observer, reference, { type: 'key', lane: 3, down: true, time: 500080 });
  assert.deepEqual(capture(observer, reference, 500090).events, []);
});

test('display delay and settings normalization do not rewrite recorded event times', () => {
  const { observer, reference } = pair({ ...BASE, inputMode: 'demo',
    delayMs: 500, noteHeight: 1000, shortInputPercent: -5 });
  feed(observer, reference, { type: 'key', lane: 2, down: true, time: 600000.125 });
  feed(observer, reference, { type: 'key', lane: 2, down: false, time: 600040.875 });
  const result = capture(observer, reference, 600500);
  assert.equal(result.settings.noteHeight, 30);
  assert.equal(result.settings.shortInputPercent, 1);
  assert.deepEqual(result.events,
    [{ lane: 2, start: 600000.125, end: 600040.875, direction: 0 }]);
});

test('returned snapshots cannot mutate canonical input records or button mapping', () => {
  const { observer, reference } = pair();
  feed(observer, reference, raw(700000, [0], 0));
  const result = capture(observer, reference, 700010);
  result.events[0].start = 1;
  result.settings.noteHeight = 29;
  result.settings.buttonMap[0] = 31;
  const next = capture(observer, reference, 700020);
  assert.equal(next.events[0].start, 700000);
  assert.equal(next.settings.noteHeight, 12);
  assert.equal(next.settings.buttonMap[0], 0);
});

test('canonical 4096-event bound is preserved without introducing synthetic input', () => {
  const { observer, reference } = pair({ ...BASE, inputMode: 'demo' });
  for (let index = 0; index < 4200; index++) {
    const time = 800000 + index / 100;
    feed(observer, reference, { type: 'key', lane: 1, down: true, time });
    feed(observer, reference, { type: 'key', lane: 1, down: false, time: time + .005 });
  }
  const result = capture(observer, reference, 800050);
  assert.equal(result.events.length, 4096);
  assert.equal(result.events[0].start, 800001.04);
  assert.equal(result.events.at(-1).end, 800041.995);
});

test('malformed envelopes and clocks fail instead of inventing input', () => {
  const { observer } = pair();
  for (const event of [null, [], { type: 'unknown' },
    { type: 'settings', settings: [] }, { ...raw(1), buttons: Array(33).fill(false) },
    { ...raw(1), axes: Array(7).fill(0) }, { ...raw(1), time: NaN },
    { ...raw(1), buttons: ['true'] }, { ...raw(1), axes: [1.1] },
    { ...raw(1), axes: [Infinity] }, { ...raw(1), axes: ['0'] },
    { type: 'key', lane: 8, down: true, time: 1 },
    { type: 'key', lane: 1, down: 'yes', time: 1 }]) {
    assert.throws(() => observer.accept(event));
  }
  for (const clock of [-1, NaN, Infinity]) assert.throws(() => observer.snapshot(clock));
  assert.deepEqual(observer.snapshot(900000).events, []);
});
