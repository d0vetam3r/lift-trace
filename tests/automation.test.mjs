import test from 'node:test';
import assert from 'node:assert/strict';
import {AUTO_TEXT, selectableItems, selectedConfig, sourceLabels} from '../web/automation.js';

const items = [
  {sceneItemId:1,sourceUuid:'game',sourceName:'Game'},
  {sceneItemId:2,sourceUuid:'game',sourceName:'Game'},
  {sceneItemId:3,sourceUuid:'camera',sourceName:'Camera'},
  {sceneItemId:4,sourceUuid:'group',isGroup:true},
  {sceneItemId:5,sourceUuid:'scene',sourceType:'OBS_SOURCE_TYPE_SCENE'},
];
test('selection keeps a duplicate capture placement distinct and excludes the original', () => {
  const result = selectedConfig('s','1',['2','3'],items);
  assert.equal(result.captureSourceUuid,'game');
  assert.deepEqual(result.targets,[{sceneUuid:'s',sceneItemId:2,sourceUuid:'game'},
    {sceneUuid:'s',sceneItemId:3,sourceUuid:'camera'}]);
  assert.deepEqual(selectableItems(items).map(item=>item.sceneItemId),[1,2,3]);
});
test('missing, nested or original-capture targets cannot form a configuration', () => {
  for (const ids of [[],[1],[4],[5],[99]]) assert.throws(()=>selectedConfig('s',1,ids,items));
  assert.throws(()=>selectedConfig('s',99,[2],items));
  assert.throws(()=>selectedConfig('s','',[2],[{...items[0],sceneItemId:0},items[1]]));
});
test('automation instructions and failure text are available in all three languages', () => {
  const keys=Object.keys(AUTO_TEXT.en).sort();
  for (const locale of ['ko','ja']) assert.deepEqual(Object.keys(AUTO_TEXT[locale]).sort(),keys);
  for (const dictionary of Object.values(AUTO_TEXT)) {
    for (const value of Object.values(dictionary)) assert.ok(value.trim());
  }
});

test('source names hide internal IDs and distinguish repeated placements in OBS order', () => {
  const named=sourceLabels([
    {...items[0],sceneItemIndex:0}, {...items[1],sceneItemIndex:3}, {...items[2],sceneItemIndex:5},
  ],'ko');
  assert.deepEqual(named.map(item=>item.label),['Camera','Game · 위쪽 배치','Game · 아래쪽 배치']);
  assert.deepEqual(named.map(item=>item.sceneItemId),[3,2,1]);
  assert.ok(named.every(item=>!item.label.includes('#')));
});

test('native renderer inputs use the unchanged exact scene-item selection contract', () => {
  const native = {sceneItemId:6, sourceUuid:'native', sourceName:'Lift Native',
    inputKind:'lift_trace_native_pacing', sourceType:'OBS_SOURCE_TYPE_INPUT', isGroup:false};
  const candidates = [...items, native, {...native, sceneItemId:7}];
  const result = selectedConfig('s', 1, [6], candidates);
  assert.deepEqual(result.targets, [{sceneUuid:'s', sceneItemId:6, sourceUuid:'native'}]);
  assert.equal(selectableItems(candidates).filter(item => item.sourceUuid === 'native').length, 2);
  const renamed = candidates.map(item => item.sceneItemId === 6
    ? {...item, sourceName:'Renamed native overlay'} : item);
  assert.deepEqual(selectedConfig('s', 1, [6], renamed), result);
  assert.throws(() => selectedConfig('s', 1, [6], candidates.filter(item => item.sceneItemId !== 6)));
});
