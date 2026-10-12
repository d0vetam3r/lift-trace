import test from 'node:test';
import assert from 'node:assert/strict';
import {AUTO_TEXT, selectableItems, selectedConfig} from '../web/automation.js';

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
});
test('automation instructions and failure text are available in all three languages', () => {
  const keys=Object.keys(AUTO_TEXT.en).sort();
  for (const locale of ['ko','ja']) assert.deepEqual(Object.keys(AUTO_TEXT[locale]).sort(),keys);
  for (const dictionary of Object.values(AUTO_TEXT)) {
    for (const value of Object.values(dictionary)) assert.ok(value.trim());
  }
});
