import test from 'node:test';
import assert from 'node:assert/strict';
import { ControllerSetup } from '../web/setup.js';

const sample = (down = [], axes = [0, 0], device = 4) => ({device, buttons:Array.from({length:16}, (_, index) => down.includes(index)), axes});
const press = (setup, button, axes) => { setup.feed(sample([button], axes)); setup.feed(sample([], axes)); };
function mapped() {
  const setup = new ControllerSetup(4);
  setup.feed(sample());
  for (const button of [3, 2, 1, 0, 7, 6, 5]) press(setup, button);
  assert.equal(setup.phase, 'scratchClockwise');
  return setup;
}

test('each key is recorded only after its own press and release, in physical order', () => {
  const setup = new ControllerSetup(4);
  setup.feed(sample([3]));
  assert.equal(setup.phase, 'release', 'pre-held buttons cannot become the first assignment');
  setup.feed(sample());
  setup.feed(sample([3]));
  setup.feed(sample([3]));
  assert.deepEqual(setup.buttonMap, []);
  setup.feed(sample());
  assert.deepEqual(setup.buttonMap, [3]);
  press(setup, 2);
  assert.deepEqual(setup.buttonMap, [3, 2]);
  assert.equal(setup.phase, 'press');
  assert.equal(setup.apply(), null, 'partial maps cannot be applied');
});

test('chords, overlap, and repeated buttons are rejected until all buttons are released', () => {
  const setup = new ControllerSetup(4);
  setup.feed(sample());
  setup.feed(sample([0, 1]));
  setup.feed(sample([0]));
  assert.equal(setup.phase, 'retryRelease');
  assert.deepEqual(setup.buttonMap, []);
  setup.feed(sample()); press(setup, 0);
  press(setup, 0);
  assert.equal(setup.error, 'setupDuplicate');
  assert.deepEqual(setup.buttonMap, [0]);
  setup.feed(sample([1])); setup.feed(sample([1, 2])); setup.feed(sample([2])); setup.feed(sample());
  assert.deepEqual(setup.buttonMap, [0]);
  setup.feed(sample([1])); setup.feed(sample([2])); setup.feed(sample());
  assert.deepEqual(setup.buttonMap, [0], 'button rollover without an empty sample is rejected');
  press(setup, 1);
  assert.deepEqual(setup.buttonMap, [0, 1]);
});

test('clockwise then counterclockwise calibrates normal and reversed device polarity across wraps', () => {
  for (const rawSign of [1, -1]) {
    const setup = mapped();
    setup.retryScratch([rawSign * 0.95, 0]);
    setup.feed(sample([], [-rawSign * 0.85, 0])); // 0.20 across wrap
    setup.checkScratch();
    assert.equal(setup.phase, 'scratchCounterclockwise');
    assert.equal(setup.apply(), null, 'one direction alone cannot be applied');
    setup.feed(sample([], [rawSign * 0.95, 0]));
    setup.checkScratch();
    assert.equal(setup.phase, 'review');
    assert.deepEqual(setup.apply(), {buttonMap:[3, 2, 1, 0, 7, 6, 5], axisIndex:0, scratchInvert:rawSign < 0});
    assert.equal(setup.phase, 'applied');
  }
});

test('tiny noise, insufficient movement and back-and-forth movement cannot calibrate clockwise', () => {
  const setup = mapped();
  for (let i = 0; i < 1000; i++) setup.feed(sample([], [i % 2 ? 0.001 : 0, 0]));
  setup.checkScratch();
  assert.equal(setup.phase, 'scratchClockwise');
  assert.equal(setup.error, 'setupNoAxis');
  setup.feed(sample([], [0.06, 0])); setup.checkScratch();
  assert.equal(setup.phase, 'scratchClockwise');
  setup.feed(sample([], [0.26, 0])); setup.feed(sample([], [0.06, 0])); setup.checkScratch();
  assert.equal(setup.phase, 'scratchClockwise');
  assert.equal(setup.apply(), null);
  setup.feed(sample([], [0.26, 0])); setup.checkScratch();
  assert.equal(setup.phase, 'scratchCounterclockwise', 'failed checks clear old movement for a fresh attempt');
});

test('counterclockwise must be consistent opposite movement on the same axis', () => {
  const setup = mapped();
  setup.feed(sample([], [0.2, 0])); setup.checkScratch();
  setup.feed(sample([], [0.4, 0])); setup.checkScratch();
  assert.equal(setup.phase, 'scratchCounterclockwise');
  assert.equal(setup.error, 'setupOpposite');
  setup.feed(sample([], [0.4, -0.2])); setup.checkScratch();
  assert.equal(setup.phase, 'scratchCounterclockwise', 'a different moving axis does not match');
  setup.feed(sample([], [0.2, -0.2])); setup.feed(sample([], [0.4, -0.2])); setup.checkScratch();
  assert.equal(setup.phase, 'scratchCounterclockwise', 'back-and-forth movement does not match');
  setup.feed(sample([], [0.2, -0.2])); setup.checkScratch();
  assert.equal(setup.phase, 'review');
  assert.equal(setup.apply().scratchInvert, false);
});

test('ambiguous axes require explicit choice and retain each axis polarity', () => {
  const setup = mapped();
  setup.feed(sample([], [0.2, -0.2])); setup.checkScratch();
  setup.feed(sample([], [0, 0])); setup.checkScratch();
  assert.equal(setup.phase, 'axisChoice');
  assert.deepEqual(setup.candidates, [0, 1]);
  assert.equal(setup.apply(), null);
  assert.equal(setup.chooseAxis(5), false);
  assert.equal(setup.chooseAxis(1), true);
  assert.equal(setup.phase, 'review');
  assert.deepEqual(setup.apply(), {buttonMap:[3, 2, 1, 0, 7, 6, 5], axisIndex:1, scratchInvert:true});
});

test('only axes matching both steps are offered, even if other axes moved in the first step', () => {
  const setup = mapped();
  setup.feed(sample([], [0.2, -0.2])); setup.checkScratch();
  setup.feed(sample([], [0.2, 0])); setup.checkScratch();
  assert.equal(setup.phase, 'review');
  assert.equal(setup.axisIndex, 1);
  assert.equal(setup.scratchInvert, true);
});

test('retry clears both directions and keeps seven keys, from either scratch step or review', () => {
  for (const phase of ['scratchClockwise', 'scratchCounterclockwise', 'review']) {
    const setup = mapped();
    if (phase !== 'scratchClockwise') { setup.feed(sample([], [0.2, 0])); setup.checkScratch(); }
    if (phase === 'review') { setup.feed(sample([], [0, 0])); setup.checkScratch(); }
    setup.retryScratch([0, 0]);
    assert.equal(setup.phase, 'scratchClockwise');
    assert.deepEqual(setup.clockwiseDirections, []);
    assert.equal(setup.axisIndex, null);
    setup.checkScratch(); assert.equal(setup.phase, 'scratchClockwise');
    setup.feed(sample([], [0, -0.2])); setup.checkScratch();
    setup.feed(sample([], [0, 0])); setup.checkScratch();
    assert.equal(setup.phase, 'review');
    assert.equal(setup.axisIndex, 1);
    assert.equal(setup.scratchInvert, true);
    assert.equal(setup.buttonMap.length, 7);
  }
});

test('slow continuous rotation accumulates despite per-sample movement below noise threshold', () => {
  const setup = mapped();
  for (let i = 0; i <= 200; i++) setup.feed(sample([], [0, i / 1000]));
  setup.checkScratch();
  assert.equal(setup.phase, 'scratchCounterclockwise');
  for (let i = 200; i >= 0; i--) setup.feed(sample([], [0, i / 1000]));
  setup.checkScratch();
  assert.equal(setup.phase, 'review');
  assert.equal(setup.axisIndex, 1);
});

test('cancellation, disconnect, and a changed device discard drafts without yielding settings', () => {
  for (const action of [setup => setup.cancel(), setup => setup.detach(), setup => setup.feed(sample([], [0, 0], 7))]) {
    const setup = mapped();
    action(setup);
    assert.deepEqual(setup.buttonMap, []);
    assert.equal(setup.apply(), null);
    setup.feed(sample([4])); setup.feed(sample());
    assert.deepEqual(setup.buttonMap, []);
  }
});

test('review and returned settings use copies and do not continue collecting inputs', () => {
  const setup = mapped();
  setup.feed(sample([], [0, 0.2])); setup.checkScratch(); setup.feed(sample([], [0, 0])); setup.checkScratch();
  setup.feed(sample([9], [0.6, 0])); setup.feed(sample());
  assert.equal(setup.axisIndex, 1);
  const settings = setup.apply(); settings.buttonMap[0] = 15;
  assert.equal(setup.buttonMap[0], 3);
  assert.equal(setup.apply(), null, 'cannot apply a draft twice');
});
