import test, { before, after } from 'node:test';
import assert from 'node:assert/strict';
import { InputClient, parseSettingsFile } from '../web/client.js';
import { getSpeed, normalizeSettings } from '../web/engine.js';
import { laneGeometry } from '../web/render.js';

class FakeEventSource {
  constructor(url) { this.url = url; }
  open() { this.onopen?.({}); }
  fail() { this.onerror?.({}); }
  send(event) { this.onmessage?.({ data: JSON.stringify(event) }); }
  sendText(data) { this.onmessage?.({ data }); }
}

const original = {
  EventSource: globalThis.EventSource,
  CustomEvent: globalThis.CustomEvent,
  fetch: globalThis.fetch,
};

before(() => {
  globalThis.EventSource = FakeEventSource;
  if (!globalThis.CustomEvent) {
    globalThis.CustomEvent = class extends Event {
      constructor(type, options = {}) { super(type); this.detail = options.detail; }
    };
  }
  // A test must never make an HTTP request; initial configuration arrives over SSE.
  globalThis.fetch = async () => { throw new Error('Unexpected network request in client test'); };
});

after(() => {
  for (const [name, value] of Object.entries(original)) {
    if (value === undefined) delete globalThis[name];
    else globalThis[name] = value;
  }
});

async function connected(settings = {}) {
  const client = new InputClient();
  await client.start();
  client.stream.send({ type: 'settings', settings: { ...client.settings, ...settings } });
  client.stream.open();
  return client;
}

function sample(time, buttons = [], axes = [0]) {
  return { type: 'input', device: 3, buttons, axes, time };
}

test('settings import accepts the current export and direct legacy configuration', () => {
  const current = {liftNumber: 401, obsOffsetX: 2, scratchInvert: true};
  assert.deepEqual(parseSettingsFile(JSON.stringify({version: 2, settings: current})), current);
  assert.deepEqual(parseSettingsFile('{"liftHeight":240,"visibleHeight":500}'), {liftHeight:240, visibleHeight:500});
});

test('unrelated or malformed JSON cannot be imported as default settings', () => {
  for (const text of ['null', '[]', '0', 'true', '"text"', '{', '{}', '{"name":"other app"}',
    '{"settings":null}', '{"settings":false}', '{"settings":[]}', '{"settings":{}}']) {
    assert.throws(() => parseSettingsFile(text), {message: 'importInvalid'}, text);
  }
});

test('SSE opens without HTTP bootstrap and supplies normalized initial settings and status', async () => {
  const client = new InputClient();
  const connections = [], settings = [], statuses = [];
  client.addEventListener('connection', event => connections.push(event.detail));
  client.addEventListener('settings', event => settings.push(event.detail));
  client.addEventListener('status', event => statuses.push(event.detail));
  await client.start();
  assert.equal(client.stream.url, '/api/events');
  client.stream.open();
  const status = { type: 'status', selectedDevice: 3, devices: [{ id: 3, name: 'Test Controller' }] };
  client.stream.send(status);
  client.stream.send({ type: 'settings', settings: { inputMode: 'native', greenNumber: 400, delayMs: -10, width: 640 } });
  assert.deepEqual(connections, [true]);
  assert.deepEqual(statuses, [status]);
  assert.equal(settings.length, 1);
  assert.equal(client.settings.inputMode, 'native');
  assert.equal(client.settings.delayMs, 0);
  assert.equal(client.settings.width, 640);
  assert.deepEqual(client.engine.settings, normalizeSettings(client.settings));
});

test('neutral demo key events preserve server timing and raw native input does not duplicate them', async () => {
  const client = await connected();
  const raw = [];
  client.addEventListener('raw', event => raw.push(event.detail));
  client.stream.send({ type: 'key', lane: 4, down: true, direction: 0, time: 1000 });
  client.stream.send({ type: 'key', lane: 4, down: true, direction: 0, time: 1005 });
  client.stream.send(sample(1010, [true]));
  client.stream.sendText('not json');
  client.stream.send({ type: 'unrecognized' });
  client.stream.send({ type: 'key', lane: 4, down: false, direction: 0, time: 1020 });
  assert.equal(raw.length, 1);
  assert.equal(client.engine.events.length, 1);
  assert.deepEqual(client.engine.events[0], { lane: 4, start: 1000, end: 1020, direction: 0 });
  assert.ok(Math.abs(client.engine.snapshot(1020)[0].headY - 20 * getSpeed(client.settings) / 1000) < 1e-10);
});

test('native button mapping supports arbitrary WinMM button indices and ignores duplicate states', async () => {
  const client = await connected({ inputMode: 'native', buttonMap: [31, 5, 4, 3, 2, 1, 0] });
  const buttons = Array(32).fill(false);
  buttons[31] = true;
  buttons[5] = true;
  client.stream.send(sample(1000, buttons));
  client.stream.send(sample(1004, buttons));
  client.stream.send({ type: 'key', lane: 7, down: true, direction: 0, time: 1005 });
  assert.deepEqual([...client.engine.active.keys()], [1, 2]);
  assert.equal(client.engine.events.length, 2);
  buttons[5] = false;
  client.stream.send(sample(1020, buttons));
  assert.equal(client.engine.events.find(event => event.lane === 2).end, 1020);
  assert.equal(client.engine.active.has(1), true);
});

test('mode and mapping changes clear stale held keys and a fresh native snapshot reseeds them', async () => {
  const client = await connected();
  client.stream.send({ type: 'key', lane: 1, down: true, time: 100 });
  client.stream.send({ type: 'settings', settings: { ...client.settings, inputMode: 'native' } });
  assert.equal(client.engine.events.length, 0);
  client.stream.send(sample(120, [true]));
  assert.equal(client.engine.active.has(1), true);
  client.stream.send({ type: 'settings', settings: { ...client.settings, buttonMap: [1, 0, 2, 3, 4, 5, 6] } });
  assert.equal(client.engine.events.length, 0);
  assert.deepEqual(client.buttons, []);
  client.stream.send(sample(140, [true, false]));
  assert.deepEqual([...client.engine.active.keys()], [2]);
  client.stream.send({ type: 'settings', settings: { ...client.settings, inputMode: 'demo' } });
  assert.equal(client.engine.events.length, 0);
  client.stream.send(sample(160, [true, true]));
  assert.equal(client.engine.events.length, 0);
  client.stream.send({ type: 'key', lane: 7, down: true, time: 180 });
  assert.deepEqual([...client.engine.active.keys()], [7]);
});

test('native scratch wraps, reverses, and closes smoothly on timeout without releasing held keys', async () => {
  const client = await connected({ inputMode: 'native', scratchStopMs: 80 });
  client.stream.send(sample(1000, [true], [.98]));
  client.stream.send(sample(1010, [true], [-.99]));
  client.stream.send(sample(1020, [true], [-.97]));
  client.stream.send(sample(1030, [true], [.99]));
  client.tick(1109);
  assert.equal(client.engine.active.get(0).direction, -1);
  client.tick(1110);
  assert.equal(client.engine.active.has(0), false);
  assert.equal(client.engine.active.has(1), true);
  const scratches = client.engine.events.filter(event => event.lane === 0);
  assert.deepEqual(scratches, [
    { lane: 0, start: 1010, end: 1030, direction: 1 },
    { lane: 0, start: 1030, end: 1110, direction: -1 },
  ]);
  assert.equal(client.engine.snapshot(1110).filter(event => event.lane === 0).at(-1).tailY, 0);
});

test('changing scratch calibration clears old directions and reseeds held keys and the axis', async () => {
  const client = await connected({ inputMode: 'native', scratchThreshold: .01 });
  const resets = [];
  client.addEventListener('reset', event => resets.push(event.detail));
  client.stream.send(sample(1000, [true], [.98]));
  client.stream.send(sample(1010, [true], [-.99]));
  assert.equal(client.engine.active.get(0).direction, 1);
  client.stream.send({ type: 'settings', settings: { ...client.settings, scratchInvert: true } });
  assert.equal(resets.length, 1);
  assert.equal(client.engine.events.length, 0);
  assert.equal(client.engine.active.size, 0);
  assert.deepEqual(client.buttons, []);
  assert.equal(client.scratch.previous, null);
  assert.equal(client.scratch.pendingDelta, 0);
  assert.equal(client.scratch.direction, 0);
  // This unchanged held button is reseeded, but the first axis value cannot invent motion.
  client.stream.send(sample(1020, [true], [-.99]));
  assert.equal(client.engine.active.has(1), true);
  assert.equal(client.engine.active.has(0), false);
  client.stream.send(sample(1030, [true], [.98]));
  assert.equal(client.engine.active.get(0).direction, 1);
  client.stream.send(sample(1040, [true], [-.99]));
  assert.equal(client.engine.active.get(0).direction, -1);
  assert.deepEqual(client.engine.events.filter(event => event.lane === 0), [
    { lane: 0, start: 1030, end: 1040, direction: 1 },
    { lane: 0, start: 1040, end: null, direction: -1 },
  ]);
  // Reapplying the same calibration must keep current input and history intact.
  client.stream.send({ type: 'settings', settings: { ...client.settings } });
  assert.equal(resets.length, 1);
  assert.equal(client.engine.active.get(0).direction, -1);
});

test('scratch inversion affects raw native motion, never canonical demo or manual key events', async () => {
  const client = await connected({ scratchInvert: true });
  client.stream.send({ type: 'key', lane: 0, down: true, direction: 1, time: 1000 });
  client.stream.send({ type: 'key', lane: 0, down: true, direction: -1, time: 1010 });
  assert.deepEqual(client.engine.events, [
    { lane: 0, start: 1000, end: 1010, direction: 1 },
    { lane: 0, start: 1010, end: null, direction: -1 },
  ]);
  client.configure({ ...client.settings, inputMode: 'native' });
  client.applyKey({ lane: 0, down: true, direction: 1, time: 1020 });
  assert.equal(client.engine.active.get(0).direction, 1);
});

test('reset and connection loss clear keys and scratch; reconnect accepts an unchanged held state', async () => {
  const client = await connected({ inputMode: 'native' });
  const connections = [], resets = [];
  client.addEventListener('connection', event => connections.push(event.detail));
  client.addEventListener('reset', event => resets.push(event.detail));
  client.stream.send(sample(1000, [true], [0]));
  client.stream.send(sample(1010, [true], [.1]));
  client.stream.send({ type: 'reset' });
  assert.equal(client.engine.events.length, 0);
  assert.equal(client.scratch.direction, 0);
  assert.deepEqual(client.buttons, []);
  client.stream.send(sample(1020, [true], [.1]));
  assert.equal(client.engine.active.has(1), true);
  client.stream.fail();
  assert.equal(client.engine.events.length, 0);
  assert.equal(client.scratch.previous, null);
  client.stream.open();
  client.stream.send(sample(1030, [true], [.1]));
  assert.equal(client.engine.active.has(1), true);
  assert.equal(client.engine.active.has(0), false);
  assert.deepEqual(connections, [false, true]);
  assert.equal(resets.length, 2);
});

test('appearance and timing settings sync to both engines without erasing input history', async () => {
  const client = await connected({ inputMode: 'native' });
  const updates = [];
  client.addEventListener('settings', event => updates.push(event.detail));
  client.stream.send(sample(1000, [true]));
  const next = { ...client.settings, greenNumber: 400, suddenNumber: 150, liftNumber: 200,
    heightMode: 'manual', manualOverlayHeight: 500, overlayHeight: 500, width: 640, blackKeyRatio: .75,
    delayMs: 30, side: '2P', scratchThreshold: .02, scratchStopMs: 200 };
  client.stream.send({ type: 'settings', settings: next });
  assert.equal(client.engine.events.length, 1);
  assert.equal(client.engine.active.has(1), true);
  assert.deepEqual(client.settings, next);
  assert.deepEqual(client.engine.settings, normalizeSettings(next));
  assert.equal(client.scratch.threshold, .02);
  assert.equal(client.scratch.stopMs, 200);
  assert.deepEqual(updates, [next]);
  assert.equal(client.engine.snapshot(1029).length, 0);
  assert.equal(client.engine.snapshot(1030)[0].headY, 0);
});

test('SSE output-height changes preserve current note position and fullscreen speed', async () => {
  const client = await connected({ inputMode: 'native', greenNumber: 433.8, suddenNumber: 100, liftNumber: 200,
    heightMode: 'manual', manualOverlayHeight: 80 });
  client.stream.send(sample(1000, [true]));
  client.stream.send(sample(1020, [false]));
  const before = client.engine.snapshot(1040);
  const speed = getSpeed(client.settings);
  client.stream.send({ type: 'settings', settings: { ...client.settings, manualOverlayHeight: 800 } });
  assert.equal(client.settings.overlayHeight, 800);
  assert.equal(getSpeed(client.settings), speed);
  assert.deepEqual(client.engine.snapshot(1040), before);
  assert.equal(client.engine.events.length, 1);
});

test('legacy SSE settings retain the old crop for manual mode and default to auto height', async () => {
  const client = await connected();
  client.stream.send({ type: 'settings', settings: { greenNumber: 300, visibleHeight: 500, liftHeight: 350, inputMode: 'native' } });
  assert.equal(client.settings.heightMode, 'auto');
  assert.equal(client.settings.overlayHeight, 1);
  assert.equal(client.settings.manualOverlayHeight, 350);
  assert.equal(Object.hasOwn(client.settings, 'visibleHeight'), false);
  assert.equal(Object.hasOwn(client.settings, 'liftHeight'), false);
  assert.equal(client.settings.suddenNumber, 0);
  assert.equal(client.settings.liftNumber, 0);
  assert.equal(getSpeed(client.settings), 1446);
  assert.deepEqual(client.engine.settings, normalizeSettings(client.settings));
});

test('persisted auto height remains canonical across SSE clients and manual fallback survives switching back', async () => {
  const client = await connected({ inputMode: 'native' });
  // A previous version's settings select auto by default while retaining its custom crop.
  client.stream.send({ type: 'settings', settings: { inputMode: 'native', liftNumber: 401, overlayHeight: 640 } });
  assert.equal(client.settings.heightMode, 'auto');
  assert.equal(client.settings.overlayHeight, 290);
  assert.equal(client.settings.manualOverlayHeight, 640);
  client.stream.send(sample(1000, [true]));
  const speed = getSpeed(client.settings);
  const snapshot = client.engine.snapshot(1020);
  const saved = JSON.parse(JSON.stringify(client.settings));
  client.stream.send({ type: 'settings', settings: saved });
  assert.deepEqual(client.settings, saved);
  assert.deepEqual(client.engine.snapshot(1020), snapshot);
  assert.equal(getSpeed(client.settings), speed);
  const overlayClient = await connected();
  overlayClient.stream.send({ type: 'settings', settings: saved });
  assert.deepEqual(overlayClient.settings, saved);
  assert.deepEqual(overlayClient.engine.settings, client.engine.settings);
  client.stream.send({ type: 'settings', settings: { ...saved, liftNumber: 200 } });
  assert.equal(client.settings.overlayHeight, 145);
  assert.equal(client.settings.manualOverlayHeight, 640);
  client.stream.send({ type: 'settings', settings: { ...client.settings, heightMode: 'manual' } });
  assert.equal(client.settings.overlayHeight, 640);
  assert.equal(client.engine.active.has(1), true);
});

test('server demo events are forwarded to the app and do not invent input notes', async () => {
  const client = await connected();
  const states = [];
  client.addEventListener('demo', event => states.push(event.detail));
  const started = { type: 'demo', running: true, startTime: 1000, period: 7200,
    notes: [{ lane: 1, start: 700, duration: 65, direction: 0 }] };
  const stopped = { ...started, running: false };
  client.stream.send(started);
  client.stream.send(stopped);
  assert.deepEqual(states, [started, stopped]);
  assert.equal(client.engine.events.length, 0);
});

test('1P and 2P geometry preserve physical key order, scratch width, and complete lane coverage', () => {
  for (const side of ['1P', '2P']) {
    const settings = normalizeSettings({ side, width: 860, scratchWidth: 1.6 });
    const geometry = laneGeometry(settings);
    assert.equal(geometry.length, 8);
    assert.equal(geometry[0].width, 160);
    const expected = side === '1P' ? [0, 1, 2, 3, 4, 5, 6, 7] : [1, 2, 3, 4, 5, 6, 7, 0];
    const ordered = geometry.map((value, lane) => ({ ...value, lane })).sort((a, b) => a.x - b.x);
    assert.deepEqual(ordered.map(value => value.lane), expected);
    let edge = 0;
    for (const lane of ordered) { assert.equal(lane.x, edge); edge += lane.width; }
    assert.equal(edge, settings.width);
    for (let lane = 1; lane <= 7; lane++) assert.equal(geometry[lane].width, 100);
  }
});

test('unequal keyboard lanes match calibrated widths in 1P and 2P without changing key order', () => {
  for (const side of ['1P', '2P']) {
    const settings = normalizeSettings({ side, width: 432, scratchWidth: 90 / 54, blackKeyRatio: 42 / 54 });
    const geometry = laneGeometry(settings);
    const expectedWidths = [90, 54, 42, 54, 42, 54, 42, 54];
    for (const [lane, expectedWidth] of expectedWidths.entries()) {
      assert.ok(Math.abs(geometry[lane].width - expectedWidth) < 1e-10);
    }
    const order = side === '1P' ? [0, 1, 2, 3, 4, 5, 6, 7] : [1, 2, 3, 4, 5, 6, 7, 0];
    let expectedX = 0;
    for (const lane of order) {
      assert.ok(Math.abs(geometry[lane].x - expectedX) < 1e-10);
      expectedX += expectedWidths[lane];
    }
    assert.equal(expectedX, 432);
    assert.ok(Math.abs(geometry[0].x - (side === '1P' ? 0 : 342)) < 1e-10);
  }
});
