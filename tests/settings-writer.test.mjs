import test from 'node:test';
import assert from 'node:assert/strict';
import { SettingsWriter } from '../web/settings-writer.js';

const initial = { shortInputEnabled: true, shortInputPercent: 30, shortInputThresholdMs: 200, greenNumber: 300, buttonMap: [0, 1, 2, 3, 4, 5, 6] };
const deferred = () => {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
};
const nextTurn = () => new Promise(resolve => setImmediate(resolve));
function fakeClock() {
  let now = 0, next = 0;
  const timers = new Map();
  return {
    setTimeout(callback, delay) { const id = ++next; timers.set(id, {at:now + delay, callback}); return id; },
    clearTimeout(id) { timers.delete(id); },
    advance(ms) {
      const end = now + ms;
      for (;;) {
        const due = [...timers].filter(([, timer]) => timer.at <= end).sort((a, b) => a[1].at - b[1].at)[0];
        if (!due) break;
        const [id, timer] = due; now = timer.at; timers.delete(id); timer.callback();
      }
      now = end;
    },
    get pending() { return timers.size; },
  };
}
function fixture() {
  const calls = [], reads = [], refreshed = [], clock = fakeClock();
  const writer = new SettingsWriter(settings => {
    const response = deferred(); calls.push({ settings, ...response }); return response.promise;
  }, {
    read(signal) { const response = deferred(); reads.push({signal, ...response}); return response.promise; },
    onRefresh(settings) { refreshed.push(settings); }, clock, echoTimeoutMs:2000, refreshTimeoutMs:2000,
  });
  writer.receive(initial);
  return { writer, calls, reads, refreshed, clock };
}

test('overlapping Apply and ordinary settings changes serialize and retain the newest local baseline', async () => {
  const { writer, calls, clock } = fixture();
  const applied = { ...writer.current(), shortInputPercent: 85 };
  const first = writer.save(applied);
  const changed = { ...writer.current(), greenNumber: 350 };
  const second = writer.save(changed);
  assert.equal(changed.shortInputPercent, 85);
  assert.deepEqual(writer.receive(initial), changed);
  await nextTurn();
  assert.equal(calls.length, 1);
  assert.deepEqual(calls[0].settings, applied);
  calls[0].resolve(); await first; await nextTurn();
  assert.equal(calls.length, 2);
  assert.deepEqual(calls[1].settings, changed);
  assert.deepEqual(writer.receive(applied), changed);
  calls[1].resolve(); await second;
  assert.equal(writer.pending, true);
  assert.deepEqual(writer.receive(initial), changed, 'an earlier echo cannot undo an unconfirmed write');
  assert.deepEqual(writer.receive(changed), changed);
  assert.equal(writer.pending, false);
  assert.equal(clock.pending, 0);
});

test('a newer server snapshot after confirmation survives HTTP completion', async () => {
  const { writer, calls, clock } = fixture();
  const changed = { ...initial, shortInputPercent: 70 };
  const external = { ...changed, shortInputPercent: 85 };
  const saved = writer.save(changed); await nextTurn();
  writer.receive(changed);
  assert.deepEqual(writer.receive(external), changed, 'protect the local draft until the response settles');
  calls[0].resolve(); await saved;
  assert.equal(writer.pending, false);
  assert.deepEqual(writer.current(), external);
  assert.equal(clock.pending, 0);
});

test('an unsent queued value cannot be confirmed by a coincidentally matching old echo', async () => {
  const { writer, calls } = fixture();
  const first = writer.save({ ...initial, shortInputPercent: 85 });
  const second = writer.save(initial);
  writer.receive(initial);
  await nextTurn(); calls[0].resolve(); await first; await nextTurn();
  calls[1].resolve(); await second;
  assert.equal(writer.pending, true);
  writer.receive(initial);
  assert.equal(writer.pending, false);
});

test('a failed latest write rejects, falls back to remote settings, and permits retry', async () => {
  const { writer, calls, clock } = fixture();
  const changed = { ...initial, shortInputPercent: 85 };
  const failed = writer.save(changed);
  const rejection = assert.rejects(failed, /disk unavailable/);
  await nextTurn(); calls[0].reject(new Error('disk unavailable')); await rejection;
  assert.equal(writer.pending, false);
  assert.deepEqual(writer.current(), initial);
  assert.equal(clock.pending, 0);
  const retry = writer.save(changed); await nextTurn();
  writer.receive(changed); calls[1].resolve(); await retry;
  assert.equal(writer.pending, false);
  assert.deepEqual(writer.current(), changed);
});

test('a failed earlier write does not cancel or roll back a later queued change', async () => {
  const { writer, calls } = fixture();
  const first = writer.save({ ...initial, shortInputPercent: 50 });
  const rejection = assert.rejects(first, /first failed/);
  const latest = { ...initial, shortInputPercent: 85 };
  const second = writer.save(latest);
  await nextTurn(); calls[0].reject(new Error('first failed')); await rejection; await nextTurn();
  assert.deepEqual(writer.current(), latest);
  assert.equal(calls.length, 2);
  writer.receive(latest); calls[1].resolve(); await second;
  assert.equal(writer.pending, false);
});

test('failed follow-up preserves a prior successful value until confirmation', async () => {
  const { writer, calls, clock } = fixture();
  const applied = { ...initial, shortInputPercent: 85 };
  const first = writer.save(applied); await nextTurn(); calls[0].resolve(); await first;
  const second = writer.save({ ...applied, greenNumber: 350 });
  const rejection = assert.rejects(second, /second failed/);
  await nextTurn(); calls[1].reject(new Error('second failed')); await rejection;
  assert.deepEqual(writer.current(), applied);
  assert.equal(writer.pending, true);
  assert.deepEqual(writer.receive(initial), applied);
  writer.receive(applied);
  assert.equal(writer.pending, false);
  assert.equal(clock.pending, 0);
});

test('external updates are accepted after the local write has been confirmed', async () => {
  const { writer, calls } = fixture();
  const changed = { ...initial, shortInputPercent: 85 };
  const saved = writer.save(changed); await nextTurn();
  writer.receive(changed); calls[0].resolve(); await saved;
  const external = { ...initial, shortInputPercent: 70 };
  assert.deepEqual(writer.receive(external), external);
  assert.deepEqual(writer.current(), external);
});

test('snapshots are isolated from callers, write callbacks, and returned values', async () => {
  const { writer, calls } = fixture();
  const source = structuredClone(initial);
  const saved = writer.save(source); source.buttonMap[0] = 10;
  const returned = writer.current(); returned.buttonMap[1] = 11;
  await nextTurn(); calls[0].settings.buttonMap[2] = 12;
  assert.deepEqual(writer.current(), initial);
  writer.receive({ buttonMap: [...initial.buttonMap], greenNumber: 300, shortInputThresholdMs: 200, shortInputPercent: 30, shortInputEnabled: true });
  calls[0].resolve(); await saved;
  assert.equal(writer.pending, false, 'key ordering does not change settings equality');
  assert.deepEqual(initial.buttonMap, [0, 1, 2, 3, 4, 5, 6]);
});

test('a lost own echo triggers one bounded authoritative refresh and releases later server updates', async () => {
  const { writer, calls, reads, refreshed, clock } = fixture();
  const changed = {...initial, shortInputPercent:50}, external = {...initial, shortInputPercent:70};
  const saved = writer.save(changed); await nextTurn(); calls[0].resolve(); await saved;
  writer.receive(external);
  clock.advance(1999); await nextTurn(); assert.equal(reads.length, 0);
  clock.advance(1); await nextTurn(); assert.equal(reads.length, 1);
  reads[0].resolve(external); await nextTurn();
  assert.equal(writer.pending, false);
  assert.deepEqual(writer.current(), external);
  assert.deepEqual(refreshed, [external]);
  assert.equal(clock.pending, 0);
  const newer = {...external, shortInputPercent:85};
  assert.deepEqual(writer.receive(newer), newer);
});

test('failed refresh preserves a committed value but never pins subsequent SSE', async () => {
  const { writer, calls, reads, clock } = fixture();
  const changed = {...initial, shortInputPercent:50};
  const saved = writer.save(changed); await nextTurn(); calls[0].resolve(); await saved;
  clock.advance(2000); await nextTurn(); reads[0].reject(new Error('offline')); await nextTurn();
  assert.equal(writer.pending, false);
  assert.deepEqual(writer.current(), changed);
  assert.equal(clock.pending, 0);
  assert.deepEqual(writer.receive(initial), initial);
});

test('a hung refresh is aborted at its deadline and ignores a late response', async () => {
  const { writer, calls, reads, refreshed, clock } = fixture();
  const changed = {...initial, shortInputPercent:50};
  const saved = writer.save(changed); await nextTurn(); calls[0].resolve(); await saved;
  clock.advance(2000); await nextTurn();
  clock.advance(2000); await nextTurn();
  assert.equal(reads[0].signal.aborted, true);
  assert.equal(writer.pending, false);
  assert.equal(clock.pending, 0);
  assert.deepEqual(writer.current(), changed);
  const external = {...initial, shortInputPercent:70};
  writer.receive(external);
  reads[0].resolve(initial); await nextTurn();
  assert.deepEqual(writer.current(), external);
  assert.deepEqual(refreshed, [changed]);
});

test('reconnect refresh does not need an exact copy of the lost own echo', async () => {
  const { writer, calls, reads, clock } = fixture();
  const saved = writer.save({...initial, shortInputPercent:50});
  await nextTurn(); calls[0].resolve(); await saved;
  const refreshing = writer.refresh(); await nextTurn();
  assert.equal(reads.length, 1);
  const external = {...initial, shortInputPercent:70};
  reads[0].resolve(external); await refreshing;
  assert.equal(writer.pending, false);
  assert.deepEqual(writer.current(), external);
  assert.equal(clock.pending, 0);
});

test('an earlier refresh response cannot overwrite a later SSE snapshot', async () => {
  const { writer, calls, reads, refreshed, clock } = fixture();
  const changed = {...initial, shortInputPercent:50}, external = {...initial, shortInputPercent:70};
  const saved = writer.save(changed); await nextTurn(); calls[0].resolve(); await saved;
  const refreshing = writer.refresh(); await nextTurn();
  writer.receive(external);
  reads[0].resolve(changed); await refreshing;
  assert.equal(writer.pending, false);
  assert.deepEqual(writer.current(), external);
  assert.deepEqual(refreshed, [external]);
  assert.equal(clock.pending, 0);
});

test('a refresh cannot overwrite a newer local write, and a superseding lost echo still recovers', async () => {
  const { writer, calls, reads, refreshed, clock } = fixture();
  const refreshing = writer.refresh(); await nextTurn();
  const changed = {...initial, shortInputPercent:50};
  const saved = writer.save(changed); await nextTurn(); calls[0].resolve(); await saved;
  reads[0].resolve(initial); await refreshing;
  assert.deepEqual(writer.current(), changed);
  assert.equal(writer.pending, true);
  assert.deepEqual(refreshed, []);
  clock.advance(2000); await nextTurn();
  assert.equal(reads.length, 2);
  reads[1].resolve(changed); await nextTurn();
  assert.equal(writer.pending, false);
  assert.deepEqual(writer.current(), changed);
  assert.equal(clock.pending, 0);
});
