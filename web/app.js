import { InputClient, api, cleanConfig, parseSettingsFile } from './client.js';
import { getSpeed, getGameGeometry, getObsPlacement, FULLSCREEN_LAYOUT } from './engine.js';
import { drawPreview, laneGeometry } from './render.js';
import { t, getLocale, setLocale, applyTranslations } from './i18n.js';
import { ControllerSetup } from './setup.js';

const $ = id => document.getElementById(id);
const client = new InputClient();
const fields = ['greenNumber', 'liftNumber', 'suddenNumber', 'heightMode', 'overlayHeight', 'width', 'obsOffsetX', 'obsOffsetY', 'speedScale', 'delayMs', 'side', 'background', 'noteHeight', 'trailOpacity', 'showGuides', 'scratchInvert', 'scratchThreshold', 'scratchStopMs', 'axisIndex', 'scratchWidth', 'blackKeyRatio', 'buttonMap'];
const keyMap = { KeyZ:1, KeyS:2, KeyX:3, KeyD:4, KeyC:5, KeyF:6, KeyV:7, ShiftLeft:0, ShiftRight:0, ControlLeft:0, ControlRight:0 };
let toastTimer, saveTimer, inputQueue = Promise.resolve(), status = {}, activeKeys = new Map();
let running = false, demoState = {startTime:0,period:7200,notes:[]}, gameNotes = [];
let configIdentity = '';
let connectionState = 'connecting', settingsSaved = false, rawInput = null, toastMessage = null;
let controllerSetup = null, setupRenderKey = '', setupSaving = false;

function toast(key, values) {
  toastMessage = {key, values}; $('toast').textContent = t(key, values); $('toast').hidden = false;
  if ($('obs-dialog').open) { $('dialog-copy-feedback').textContent = t(key, values); $('dialog-copy-feedback').hidden = false; }
  clearTimeout(toastTimer); toastTimer = setTimeout(() => { $('toast').hidden = true; $('dialog-copy-feedback').hidden = true; }, 2800);
}
function report(error) {
  const message = error.message || String(error);
  // The shared client keeps its API unchanged; localize its existing HTTP error here.
  const requestError = /^요청 실패 \((\d+)\)$/.exec(message);
  if (requestError) toast('requestFailed', {status:requestError[1]});
  else if (error instanceof SyntaxError) toast('importInvalid');
  else if (error instanceof TypeError && /fetch|network|load failed/i.test(message)) toast('networkFailed');
  else toast(message);
}
function updateDemoLabels() {
  $('demo-toggle').textContent = t(running ? 'demoStop' : 'demoStart');
  $('demo-status').textContent = t(running ? 'demoRunning' : 'demoIdle');
}
function updateRawInput() {
  const buttons = (rawInput?.buttons || []).map((down,index) => down ? index : null).filter(value => value !== null);
  const axis = rawInput?.axes[client.settings.axisIndex];
  $('raw-input').textContent = t('rawInput', {buttons:buttons.length ? buttons.join(', ') : '—', axis:Number.isFinite(axis) ? axis.toFixed(4) : '—'});
}
function refreshLanguage() {
  applyTranslations(); $('language').value = getLocale();
  syncSettings(client.settings); updateDemoLabels(); updateRawInput();
  $('connection').textContent = t(connectionState);
  $('save-status').textContent = t(settingsSaved ? 'saved' : 'savedLocal');
  if ('devices' in status || 'nativeSupported' in status) updateDevices(status);
  else $('device-status').textContent = t('scanning');
  for (const button of $('keybed').querySelectorAll('button[data-lane]')) {
    if (button.dataset.lane !== '0') button.setAttribute('aria-label', t('keyPress', {key:button.dataset.lane}));
  }
  if (toastMessage) {
    $('toast').textContent = t(toastMessage.key, toastMessage.values);
    $('dialog-copy-feedback').textContent = t(toastMessage.key, toastMessage.values);
  }
  renderControllerSetup(true);
}
$('language').addEventListener('change', event => { setLocale(event.target.value); refreshLanguage(); });
function sendKey(lane, down, direction = 0, time = Date.now()) {
  inputQueue = inputQueue.then(() => api('/api/input', { type:'key', lane, down, ...(direction ? {direction} : {}), time })).catch(report);
  return inputQueue;
}
function syncSettings(s) {
  const nextIdentity = JSON.stringify([s.inputMode, s.axisIndex, s.buttonMap, s.scratchInvert]);
  if (configIdentity && configIdentity !== nextIdentity) activeKeys.clear();
  configIdentity = nextIdentity;
  for (const name of fields) {
    if (name === 'showGuides' || name === 'scratchInvert') $(name).checked = s[name];
    else $(name).value = name === 'buttonMap' ? s[name].join(',') : s[name];
  }
  $('input-mode').value = s.inputMode;
  $('native-controls').hidden = s.inputMode !== 'native';
  $('preview-mode').textContent = t(s.inputMode === 'native' ? 'previewNative' : 'previewDemo');
  $('demo-toggle').disabled = s.inputMode === 'native';
  $('speed-value').textContent = Math.round(getSpeed(s)) + ' px/s';
  const geometry = getGameGeometry(s);
  $('speed-detail').textContent = t('speedDetail', {height:geometry.visibleHeight.toFixed(1), seconds:(s.greenNumber / 600).toFixed(3)});
  const autoHeight = s.heightMode === 'auto';
  $('overlayHeight').readOnly = autoHeight;
  $('overlayHeight').min = autoHeight ? '1' : '40';
  $('height-explanation').textContent = t(autoHeight ? 'heightAutoHelp' : 'heightManualHelp', {lift:s.liftNumber, height:s.overlayHeight});
  $('zero-lift-help').hidden = !autoHeight || s.liftNumber > 0;
  $('dialog-zero-lift').hidden = !autoHeight || s.liftNumber > 0;
  $('preview-zero-lift').hidden = !autoHeight || s.liftNumber > 0;
  const placement = getObsPlacement(s);
  const obsValues = {width:s.width, height:s.overlayHeight, ...placement};
  for (const name of ['width', 'height', 'x', 'y']) {
    const value = obsValues[name];
    $('output-' + name).textContent = String(value);
    $('dialog-' + name).textContent = String(value);
  }
  $('overlay-link').href = new URL('/overlay.html', location.href).href;
  const keybed = $('keybed');
  keybed.style.gridTemplateColumns = laneGeometry(s).sort((a, b) => a.x - b.x).map(lane => `${lane.width}fr`).join(' ');
  const scratch = $('scratch-tests');
  if (s.side === '1P') keybed.prepend(scratch); else keybed.append(scratch);
}
async function persist(s) {
  const clean = cleanConfig(s); client.configure(clean);
  await api('/api/settings', clean);
  settingsSaved = true; $('save-status').textContent = t('saved');
}
function updateSettings() {
  const s = { ...client.settings, inputMode: $('input-mode').value };
  for (const name of fields) {
    if (name === 'showGuides' || name === 'scratchInvert') s[name] = $(name).checked;
    else if (name === 'side' || name === 'background' || name === 'heightMode') s[name] = $(name).value;
    else if (name === 'overlayHeight') {
      // Switching from automatic to manual restores the saved manual height,
      // rather than accidentally replacing it with the calculated height.
      if (client.settings.heightMode === 'manual') s.manualOverlayHeight = Number($(name).value);
    }
    else if (name === 'buttonMap') {
      const values = $(name).value.split(',').map(value => Number(value.trim()));
      if (values.length !== 7 || values.some(value => !Number.isInteger(value) || value < 0 || value > 31)) { $(name).classList.add('invalid'); toast('invalidButtons'); return; }
      $(name).classList.remove('invalid'); s[name] = values;
    } else s[name] = Number($(name).value);
  }
  if (s.liftNumber + s.suddenNumber >= 1000) {
    toast('invalidLane');
    return;
  }
  clearTimeout(saveTimer); persist(s).catch(report);
}
for (const name of [...fields, 'input-mode']) $(name).addEventListener('change', updateSettings);
$('fullscreen-preset').addEventListener('click', async () => {
  try {
    await persist({...client.settings, width:FULLSCREEN_LAYOUT.laneWidth,
      scratchWidth:FULLSCREEN_LAYOUT.scratchWidth, blackKeyRatio:FULLSCREEN_LAYOUT.blackKeyRatio,
      obsOffsetX:0, obsOffsetY:0});
    toast('fullscreenPresetApplied');
  } catch (error) { report(error); }
});

function stopDemo() {
  inputQueue = inputQueue.then(() => api('/api/demo', {running:false})).catch(report);
}
function startDemo() {
  if (client.settings.inputMode !== 'demo') return;
  activeKeys.clear(); inputQueue = inputQueue.then(() => api('/api/demo', {running:true})).catch(report);
}
$('demo-toggle').addEventListener('click', () => running ? stopDemo() : startDemo());
$('clear').addEventListener('click', () => { activeKeys.clear(); client.reset(); inputQueue = inputQueue.then(() => api('/api/reset', {})).catch(report); });

function press(id, lane, direction) {
  if (client.settings.inputMode !== 'demo' || activeKeys.has(id)) return;
  if (running) stopDemo();
  activeKeys.set(id, {lane, direction}); sendKey(lane, true, direction);
}
function release(id) {
  const item = activeKeys.get(id); if (!item) return;
  activeKeys.delete(id);
  const remaining = [...activeKeys.values()].filter(value => value.lane === item.lane);
  if (remaining.length) { if (item.lane === 0) sendKey(0, true, remaining.at(-1).direction); }
  else sendKey(item.lane, false, item.direction);
}
window.addEventListener('keydown', event => {
  if (!(event.code in keyMap) || event.repeat || /INPUT|SELECT|TEXTAREA/.test(event.target.tagName) || $('obs-dialog').open || $('setup-dialog').open) return;
  event.preventDefault(); press(event.code, keyMap[event.code], event.code.startsWith('Control') ? -1 : event.code.startsWith('Shift') ? 1 : 0);
});
window.addEventListener('keyup', event => { if (activeKeys.has(event.code)) { event.preventDefault(); release(event.code); } });
window.addEventListener('blur', () => { for (const key of [...activeKeys.keys()]) release(key); });
for (const button of $('keybed').querySelectorAll('button')) {
  button.addEventListener('pointerdown', event => { event.preventDefault(); button.setPointerCapture(event.pointerId); press('pointer'+event.pointerId, Number(button.dataset.lane), Number(button.dataset.direction || 0)); });
  for (const name of ['pointerup', 'pointercancel', 'lostpointercapture']) button.addEventListener(name, event => release('pointer'+event.pointerId));
}

function updateDevices(next) {
  status = next; const list = $('device');
  list.replaceChildren(new Option(t('selectDevice'), ''));
  for (const device of next.devices || []) list.add(new Option(`${device.name} (ID ${device.id})`, String(device.id)));
  list.value = next.selectedDevice == null ? '' : String(next.selectedDevice);
  const selected = (next.devices || []).find(device => device.id === next.selectedDevice);
  $('controller-setup').disabled = !selected || next.nativeSupported === false;
  if (controllerSetup && $('setup-dialog').open && (!selected || selected.id !== controllerSetup.deviceId)) {
    controllerSetup.detach(); renderControllerSetup();
  }
  const axisNames = selected?.axisNames || ['X','Y','Z','R','U','V'];
  const axisSelect = $('axisIndex'); axisSelect.replaceChildren(...axisNames.map((name,index) => new Option(`${name} (${index})`, String(index))));
  axisSelect.value = String(client.settings.axisIndex);
  $('device-status').textContent = t(next.nativeSupported === false ? 'nativeUnsupported'
    : !(next.devices || []).length ? 'noDevices'
    : next.selectedDevice == null ? 'devicePrompt' : 'deviceReady');
}
$('rescan').addEventListener('click', () => api('/api/rescan', {}).then(result => { if (result.devices) updateDevices(result); }).catch(report));
$('device').addEventListener('change', () => api('/api/device', {id:$('device').value === '' ? null : Number($('device').value)}).catch(report));
client.addEventListener('status', event => updateDevices(event.detail));
client.addEventListener('raw', event => {
  rawInput = event.detail; updateRawInput();
  if (controllerSetup && $('setup-dialog').open) { controllerSetup.feed(event.detail); renderControllerSetup(); }
});
client.addEventListener('settings', event => syncSettings(event.detail));
client.addEventListener('demo', event => {
  demoState = event.detail; running = Boolean(demoState.running); gameNotes = [];
  updateDemoLabels();
});
client.addEventListener('connection', event => {
  connectionState = event.detail ? 'connected' : 'disconnected';
  $('connection').textContent = t(connectionState);
  $('connection').className = 'connection ' + (event.detail ? 'ok' : 'error');
  if (!event.detail) {
    running = false; gameNotes = []; updateDemoLabels();
    if (controllerSetup && $('setup-dialog').open) { controllerSetup.detach(); renderControllerSetup(); }
  }
});

function selectedController() { return (status.devices || []).find(device => device.id === status.selectedDevice); }
function axisLabel(index) { return selectedController()?.axisNames?.[index] || String(index + 1); }
function beginControllerSetup() {
  const selected = selectedController();
  if (!selected) { toast('setupSelectDevice'); return; }
  controllerSetup = new ControllerSetup(selected.id);
  if (rawInput?.device === selected.id) controllerSetup.feed(rawInput);
  renderControllerSetup(true);
  if (!$('setup-dialog').open) $('setup-dialog').showModal();
}
function renderControllerSetup(force = false) {
  if (!controllerSetup) return;
  const draft = controllerSetup;
  const renderKey = JSON.stringify([draft.phase, draft.buttonMap, draft.axisIndex, draft.candidates, draft.error, getLocale(), setupSaving]);
  if (!force && setupRenderKey === renderKey) return;
  setupRenderKey = renderKey;
  const stage = draft.buttonMap.length < 7 ? 'setupKeys'
    : draft.phase === 'scratchClockwise' ? 'setupClockwise' : draft.phase === 'scratchCounterclockwise' ? 'setupCounterclockwise' : 'setupTurntable';
  $('setup-progress').textContent = t(draft.phase === 'review' ? 'setupReview' : stage, {key:draft.buttonMap.length + 1});
  const messageKey = {release:'setupReleaseAll', press:'setupPressKey', held:'setupReleaseKey', retryRelease:'setupReleaseAll', scratchClockwise:'setupRotateClockwise', scratchCounterclockwise:'setupRotateCounterclockwise', axisChoice:'setupAmbiguous', review:'setupReviewHelp', detached:'setupDetached', applied:'setupSaving'}[draft.phase] || 'setupReleaseAll';
  $('setup-instruction').textContent = t(messageKey, {key:draft.buttonMap.length + 1});
  $('setup-instruction').classList.toggle('scratch-clockwise', draft.phase === 'scratchClockwise');
  $('setup-instruction').classList.toggle('scratch-counterclockwise', draft.phase === 'scratchCounterclockwise');
  $('setup-error').textContent = draft.error ? t(draft.error) : '';
  $('setup-error').hidden = !draft.error;
  $('setup-check').hidden = !['scratchClockwise', 'scratchCounterclockwise'].includes(draft.phase);
  $('setup-check').textContent = t(draft.phase === 'scratchClockwise' ? 'setupCheckClockwise' : 'setupCheckCounterclockwise');
  $('setup-retry-scratch').hidden = !['scratchClockwise', 'scratchCounterclockwise', 'axisChoice', 'review'].includes(draft.phase);
  $('setup-apply').hidden = draft.phase !== 'review' && !setupSaving;
  $('setup-apply').disabled = draft.phase !== 'review' || setupSaving;
  $('setup-restart').disabled = setupSaving || draft.phase === 'detached';
  $('setup-cancel').disabled = setupSaving;
  const choices = $('setup-axis-choices'); choices.replaceChildren();
  if (draft.phase === 'axisChoice') {
    for (const index of draft.candidates) {
      const button = document.createElement('button'); button.type = 'button'; button.className = 'secondary';
      button.textContent = t('setupUseAxis', {axis:axisLabel(index)});
      button.addEventListener('click', () => { draft.chooseAxis(index); renderControllerSetup(); });
      choices.append(button);
    }
  }
  $('setup-review').hidden = draft.phase !== 'review';
  $('setup-review').textContent = draft.phase === 'review'
    ? t('setupMappingReview', {buttons:draft.buttonMap.join(' · '), axis:axisLabel(draft.axisIndex)}) : '';
}
$('controller-setup').addEventListener('click', beginControllerSetup);
$('setup-restart').addEventListener('click', beginControllerSetup);
$('setup-check').addEventListener('click', () => { controllerSetup.checkScratch(); renderControllerSetup(); });
$('setup-retry-scratch').addEventListener('click', () => { controllerSetup.retryScratch(rawInput?.axes || []); renderControllerSetup(); });
$('setup-cancel').addEventListener('click', () => $('setup-dialog').close());
$('setup-dialog').addEventListener('cancel', event => { if (setupSaving) event.preventDefault(); });
$('setup-dialog').addEventListener('close', () => { if (controllerSetup?.phase !== 'applied') controllerSetup?.cancel(); controllerSetup = null; });
$('setup-apply').addEventListener('click', async () => {
  const draft = controllerSetup, mapping = draft?.apply(); if (!mapping) return;
  setupSaving = true; renderControllerSetup();
  try { await persist({...client.settings, ...mapping, inputMode:'native'}); $('setup-dialog').close(); toast('setupApplied'); }
  catch (error) { if (draft.phase === 'applied') draft.phase = 'review'; report(error); }
  finally { setupSaving = false; renderControllerSetup(); }
});
async function copyValue(value, successKey, promptKey = 'copyPrompt') {
  try { await navigator.clipboard.writeText(String(value)); toast(successKey); }
  catch { window.prompt(t(promptKey), String(value)); }
}
function copyUrl() { return copyValue(new URL('/overlay.html', location.href).href, 'urlCopied'); }
$('copy-url').addEventListener('click', copyUrl); $('dialog-copy').addEventListener('click', copyUrl);
for (const prefix of ['copy', 'dialog-copy']) {
  $(prefix + '-width').addEventListener('click', () => copyValue(client.settings.width, 'widthCopied', 'copyNumberPrompt'));
  $(prefix + '-height').addEventListener('click', () => copyValue(client.settings.overlayHeight, 'heightCopied', 'copyNumberPrompt'));
  $(prefix + '-x').addEventListener('click', () => copyValue(getObsPlacement(client.settings).x, 'xCopied', 'copyNumberPrompt'));
  $(prefix + '-y').addEventListener('click', () => copyValue(getObsPlacement(client.settings).y, 'yCopied', 'copyNumberPrompt'));
}
$('obs-help').addEventListener('click', () => $('obs-dialog').showModal());
$('first-obs-help').addEventListener('click', () => $('obs-dialog').showModal());
$('export').addEventListener('click', () => {
  const blob = new Blob([JSON.stringify({version:2,settings:client.settings},null,2)+'\n'], {type:'application/json'});
  const url = URL.createObjectURL(blob), link = document.createElement('a'); link.href=url;link.download='lift-trace-settings.json';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
});
$('import').addEventListener('change', async event => {
  const file = event.target.files[0]; if (!file) return;
  try {
    if (file.size > 32768) throw new Error('importTooLarge');
    const settings = parseSettingsFile(await file.text());
    await persist(settings); toast('imported');
  } catch (error) { report(error); }
  event.target.value='';
});
function frame() {
  const now = Date.now();
  if (running) {
    const cycle = Math.max(0, Math.floor((now-demoState.startTime)/demoState.period));
    gameNotes = [cycle,cycle+1].flatMap(index => demoState.notes.map(note => {
      const start = demoState.startTime + index * demoState.period + note.start;
      return {lane:note.lane,start,end:start+note.duration,long:note.duration>300,direction:note.direction || 0};
    }));
  }
  client.tick(now); drawPreview($('preview'),client,now,gameNotes);
  const active = client.engine.snapshot(now).filter(event => event.active);
  for (const button of $('keybed').querySelectorAll('button')) {
    const lane = Number(button.dataset.lane), direction = Number(button.dataset.direction || 0);
    button.classList.toggle('active', active.some(event => event.lane === lane && (lane !== 0 || event.direction === direction)));
  }
  requestAnimationFrame(frame);
}
refreshLanguage(); requestAnimationFrame(frame);
client.start().then(() => api('/api/status')).then(updateDevices).catch(error => { connectionState='connectionFailed';$('connection').textContent=t(connectionState);$('connection').className='connection error';report(error); });
