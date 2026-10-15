import test from 'node:test';
import assert from 'node:assert/strict';
import { ShortInputDraft } from '../web/short-input-controls.js';

const current = {inputBodyEnabled:true, shortInputEnabled:true, shortInputThresholdMs:200, shortInputPercent:30};

test('slider draft remains local and survives old settings messages while adjusting', () => {
  const state = new ShortInputDraft(current);
  for (const percent of [50, 85, 70]) state.edit({shortInputPercent:percent});
  state.receive(current);
  assert.equal(state.draft.shortInputPercent, 70);
  assert.deepEqual(state.saved, current);
  assert.equal(state.dirty, true);
  assert.equal(state.saving, false);
});

test('cancel restores the applied settings, including a newer external setting', () => {
  const state = new ShortInputDraft(current);
  state.edit({shortInputPercent:85});
  state.receive({...current, shortInputThresholdMs:150});
  state.discard();
  assert.deepEqual(state.draft, {...current, shortInputThresholdMs:150});
  assert.equal(state.dirty, false);
});

test('turning off retains the chosen length and threshold and normalizes numeric edits', () => {
  const state = new ShortInputDraft(current);
  state.edit({shortInputPercent:'85', shortInputThresholdMs:'175', shortInputEnabled:false});
  assert.deepEqual(state.draft, {inputBodyEnabled:true, shortInputEnabled:false, shortInputThresholdMs:175, shortInputPercent:85});
  state.edit({shortInputEnabled:true});
  assert.equal(state.draft.shortInputPercent, 85);
  state.edit({shortInputPercent:101, shortInputThresholdMs:0});
  assert.equal(state.draft.shortInputPercent, 100);
  assert.equal(state.draft.shortInputThresholdMs, 1);
});

test('success uses reconciled settings supplied by the writer without a second echo guard', () => {
  const state = new ShortInputDraft(current);
  state.edit({shortInputPercent:85});
  const submitted = state.begin();
  state.finish(true, submitted);
  assert.equal(state.draft.shortInputPercent, 85);
  assert.equal(state.saved.shortInputPercent, 85);
  assert.equal(state.dirty, false);
  state.receive({...submitted, shortInputPercent:70});
  assert.equal(state.draft.shortInputPercent, 70);
});

test('SSE confirmation before the response and duplicate clicks are safe', () => {
  const state = new ShortInputDraft(current);
  assert.equal(state.begin(), null);
  state.edit({shortInputPercent:85});
  const submitted = state.begin();
  assert.equal(state.begin(), null);
  state.edit({shortInputPercent:30});
  state.discard();
  state.receive(submitted);
  state.finish(true);
  assert.equal(state.draft.shortInputPercent, 85);
  assert.equal(state.dirty, false);
});

test('failed save preserves the draft for retry and never marks it saved', () => {
  const state = new ShortInputDraft(current);
  state.edit({shortInputPercent:70});
  state.begin(); state.finish(false);
  state.receive(current);
  assert.equal(state.error, true);
  assert.equal(state.saved.shortInputPercent, 30);
  assert.equal(state.draft.shortInputPercent, 70);
  assert.equal(state.dirty, true);
  const retry = state.begin();
  assert.equal(retry.shortInputPercent, 70);
  state.receive(retry); state.finish(true);
  assert.equal(state.error, false);
  assert.equal(state.dirty, false);
});

test('editing never mutates the source settings or accepts unrelated draft keys', () => {
  const source = Object.freeze({...current, inputMode:'native', delayMs:120});
  const state = new ShortInputDraft(source);
  state.edit({shortInputPercent:85, inputMode:'demo', delayMs:0});
  assert.deepEqual(Object.keys(state.draft), ['inputBodyEnabled', 'shortInputEnabled', 'shortInputThresholdMs', 'shortInputPercent']);
  assert.equal(source.shortInputPercent, 30);
  assert.equal(source.delayMs, 120);
});

test('heads-only mode stays local until saved and preserves shortening choices across toggles', () => {
  const state = new ShortInputDraft(current);
  state.edit({inputBodyEnabled:false});
  state.receive(current);
  assert.equal(state.saved.inputBodyEnabled, true);
  assert.deepEqual(state.draft, {...current, inputBodyEnabled:false});
  state.discard();
  assert.deepEqual(state.draft, current);
  state.edit({inputBodyEnabled:false});
  const submitted = state.begin();
  state.finish(true, submitted);
  assert.equal(state.draft.inputBodyEnabled, false);
  state.receive(submitted);
  const reloaded = new ShortInputDraft(submitted);
  assert.deepEqual(reloaded.draft, {...current, inputBodyEnabled:false});
  reloaded.edit({inputBodyEnabled:true});
  assert.deepEqual(reloaded.draft, current);
});

test('success never replaces a newer received setting with the original submission', () => {
  const state = new ShortInputDraft(current);
  state.edit({shortInputPercent:50});
  const submitted = state.begin();
  state.receive(submitted);
  const external = {...submitted, shortInputPercent:70};
  state.receive(external);
  state.finish(true);
  assert.deepEqual(state.saved, external);
  assert.deepEqual(state.draft, external);
  assert.equal(state.dirty, false);
});
