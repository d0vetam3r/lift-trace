import { getLocale } from './i18n.js';

export const AUTO_TEXT = {
  en: {
    title:'INFINITAS automatic visibility · experimental',
    help:'Enable the WebSocket server in OBS → Tools. Connect below, choose the original 1920 × 1080 game capture and the items to show during gameplay. This first profile detects the SCORE area, including the pre-song play UI; it does not read chart notes.',
    port:'OBS WebSocket port', password:'Password (blank keeps the saved password)', connect:'Connect to OBS',
    scene:'Scene', capture:'Original game capture · keep this visible', targets:'Items to show together',
    save:'Save selected items', template:'Save reference from the play screen',
    referenceHelp:'Save the reference while the play UI and SCORE label are visible in the original capture. The small reference image stays on this PC. Only this 1080p layout is supported; a different layout needs separate validation.',
    exclusive:'I have stopped Advanced Scene Switcher or other rules controlling these same items.',
    start:'Start automatic visibility', stop:'Stop · return to manual control',
    stopHelp:'Stopping leaves the current visibility unchanged. After an OBS disconnect or scene-collection change, reconnect and select the items again. Restarting Lift Trace leaves automation off.',
    idle:'Stopped', playing:'Play UI confirmed', not_playing:'Outside play UI', unknown:'Not confirmed',
    shown:'Last request: shown', hidden:'Last request: hidden', uncertain:'Application not confirmed',
    referenceReady:'Reference saved', referenceMissing:'Reference needed',
    failure:'Could not complete this step. Check the OBS connection, saved selection and reference.',
    unavailable:'Automatic visibility dependencies are unavailable in this source environment.',
    dirty:'Selection changed. Save it before capturing a reference or starting.',
    connectFirst:'Connect to OBS again before continuing.',
    selectionInvalid:'Check that the original capture is visible and the selected items still exist, then save them again.',
    connectFailed:'Enable the OBS WebSocket server and check its port and password.',
  },
  ko: {
    title:'INFINITAS 자동 표시 · 실험 기능',
    help:'OBS → 도구에서 WebSocket 서버를 켜세요. 연결한 뒤 원본 1920 × 1080 게임 캡처와 플레이 중 함께 표시할 항목을 선택합니다. 첫 프로필은 SCORE 영역을 감지하므로 곡 시작 전 플레이 UI도 포함하며, 채보를 읽지는 않습니다.',
    port:'OBS WebSocket 포트', password:'비밀번호 (비우면 저장된 값 유지)', connect:'OBS 연결',
    scene:'장면', capture:'원본 게임 캡처 · 항상 표시 유지', targets:'함께 표시할 항목',
    save:'선택 항목 저장', template:'플레이 화면에서 기준 저장',
    referenceHelp:'원본 캡처에 플레이 UI와 SCORE 글자가 보일 때 기준을 저장하세요. 작은 기준 이미지는 이 PC에만 저장합니다. 현재는 이 1080p 배치만 지원하며 다른 배치는 별도 검증이 필요합니다.',
    exclusive:'같은 항목을 제어하는 Advanced Scene Switcher 등의 규칙을 껐습니다.',
    start:'자동 표시 시작', stop:'중지 · 수동 제어로 전환',
    stopHelp:'중지하면 현재 표시 상태를 유지합니다. OBS 연결이 끊기거나 장면 모음을 바꾸면 다시 연결하고 항목을 선택하세요. Lift Trace를 다시 켜면 자동화는 꺼진 상태입니다.',
    idle:'중지됨', playing:'플레이 UI 확인', not_playing:'플레이 UI 아님', unknown:'판별 미확인',
    shown:'마지막 요청: 표시', hidden:'마지막 요청: 숨김', uncertain:'적용 미확인',
    referenceReady:'기준 저장됨', referenceMissing:'기준 저장 필요',
    failure:'이 단계를 완료하지 못했습니다. OBS 연결, 저장한 항목과 기준 화면을 확인하세요.',
    unavailable:'이 소스 실행 환경에는 자동 표시에 필요한 라이브러리가 없습니다.',
    dirty:'선택이 바뀌었습니다. 기준 저장이나 시작 전에 선택 항목을 저장하세요.',
    connectFirst:'계속하려면 OBS에 다시 연결하세요.',
    selectionInvalid:'원본 캡처가 켜져 있고 선택한 항목이 남아 있는지 확인한 뒤 다시 저장하세요.',
    connectFailed:'OBS WebSocket 서버를 켜고 포트와 비밀번호를 확인하세요.',
  },
  ja: {
    title:'INFINITAS 自動表示 · 実験機能',
    help:'OBS → ツールでWebSocketサーバーを有効にします。接続後、元の1920 × 1080ゲームキャプチャとプレイ中に表示する項目を選択してください。この最初のプロファイルはSCORE領域を検出するため、曲開始前のプレイUIも含みます。譜面は読みません。',
    port:'OBS WebSocketポート', password:'パスワード（空欄なら保存済みの値を使用）', connect:'OBSに接続',
    scene:'シーン', capture:'元のゲームキャプチャ · 表示を維持', targets:'一緒に表示する項目',
    save:'選択した項目を保存', template:'プレイ画面から基準を保存',
    referenceHelp:'元のキャプチャにプレイUIとSCOREの文字が見えるときに保存します。小さな基準画像はこのPCだけに保存されます。現在はこの1080p配置のみが対象で、別の配置には個別の検証が必要です。',
    exclusive:'同じ項目を制御するAdvanced Scene Switcherなどのルールを停止しました。',
    start:'自動表示を開始', stop:'停止 · 手動制御に戻す',
    stopHelp:'停止時は現在の表示状態を維持します。OBS切断やシーンコレクション変更後は、再接続して項目を選び直してください。Lift Traceの再起動後は自動化が無効になります。',
    idle:'停止中', playing:'プレイUI確認', not_playing:'プレイUI以外', unknown:'判別未確認',
    shown:'最後の要求: 表示', hidden:'最後の要求: 非表示', uncertain:'適用未確認',
    referenceReady:'基準保存済み', referenceMissing:'基準の保存が必要',
    failure:'この手順を完了できませんでした。OBS接続、保存した項目、基準画面を確認してください。',
    unavailable:'このソース実行環境には自動表示に必要なライブラリがありません。',
    dirty:'選択が変わりました。基準の保存や開始前に項目を保存してください。',
    connectFirst:'続けるにはOBSに再接続してください。',
    selectionInvalid:'元のキャプチャが表示中で、選択した項目が存在することを確認して保存し直してください。',
    connectFailed:'OBS WebSocketサーバーを有効にして、ポートとパスワードを確認してください。',
  },
};

export function selectableItems(items) {
  return items.filter(item => !item.isGroup && item.sourceType !== 'OBS_SOURCE_TYPE_SCENE');
}

export function selectedConfig(sceneUuid, captureId, targetIds, items) {
  const candidates = selectableItems(items);
  const capture = candidates.find(item => item.sceneItemId === Number(captureId));
  if (!capture) throw new Error('Select a capture item');
  const ids = new Set(targetIds.map(Number));
  if (!ids.size || ids.has(capture.sceneItemId)) throw new Error('Select targets other than the capture');
  const targets = candidates.filter(item => ids.has(item.sceneItemId));
  if (targets.length !== ids.size) throw new Error('A selected item is no longer available');
  return { sceneUuid, captureItemId:capture.sceneItemId, captureSourceUuid:capture.sourceUuid,
    targets:targets.map(item => ({sceneUuid, sceneItemId:item.sceneItemId, sourceUuid:item.sourceUuid})) };
}

export function mountAutomation(root = document, request = fetch) {
  const $ = id => root.getElementById(`auto-${id}`);
  if (!$('panel')) return;
  let status = {}, items = [], busy = false, dirty = false, failed = false, revision = 0, errorCode = null;
  const tr = key => AUTO_TEXT[getLocale()]?.[key] || AUTO_TEXT.en[key] || key;
  const render = () => {
    for (const node of $('panel').querySelectorAll('[data-auto-text]')) node.textContent = tr(node.dataset.autoText);
    const running = !!status.running;
    const message = {'obs-connect-failed':'connectFailed', 'obs-not-connected':'connectFirst',
      'obs-disconnected':'connectFirst', 'obs-request-failed':'connectFirst',
      'invalid-automation-config':'selectionInvalid', 'template-required':'referenceMissing',
      'exclusive-control-required':'exclusive'}[errorCode || status.error] || 'failure';
    $('status').textContent = [tr(running ? status.state || 'unknown' : 'idle'),
      tr(status.applied === true ? 'shown' : status.applied === false ? 'hidden' : 'uncertain'),
      tr(status.templateReady ? 'referenceReady' : 'referenceMissing'),
      Number.isFinite(status.score) ? `SCORE ${status.score.toFixed(4)}` : '',
      status.available === false ? tr('unavailable') : '',
      dirty ? tr('dirty') : '', failed || status.error ? tr(message) : '',
    ].filter(Boolean).join(' · ');
    for (const id of ['connect', 'scene', 'capture', 'save', 'template', 'port', 'password']) {
      $(id).disabled = busy || running;
    }
    $('save').disabled ||= !items.length || !status.connected;
    $('template').disabled ||= dirty || !status.connected || !status.config?.captureSourceUuid;
    $('start').disabled = busy || running || dirty || !status.connected || !status.templateReady || !$('exclusive').checked;
    $('stop').disabled = !running;
    for (const input of $('targets').querySelectorAll('input')) input.disabled = busy || running;
  };
  const send = async (action, value) => {
    const started = revision;
    const response = await request(`/api/automation${action ? '/' + action : ''}`, action ? {
      method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(value || {}),
    } : {});
    const result = await response.json();
    if (action || started === revision) status = result.status || (!action ? result : status);
    if (!response.ok) { errorCode = result.code; throw new Error(result.error || 'Request failed'); }
    return result;
  };
  const act = async operation => {
    if (busy) return;
    revision++; busy = true; failed = false; errorCode = null; render();
    try { await operation(); } catch { failed = true; }
    finally { busy = false; render(); }
  };
  const option = (value, text) => {
    const node = root.createElement('option'); node.value = value; node.textContent = text; return node;
  };
  const drawTargets = () => {
    const previously = new Set(status.config?.sceneUuid === $('scene').value
      ? status.config.targets?.map(item => `${item.sceneItemId}:${item.sourceUuid}`) : []);
    $('targets').replaceChildren();
    for (const item of selectableItems(items)) {
      if (item.sceneItemId === Number($('capture').value)) continue;
      const label = root.createElement('label'); label.className = 'check';
      const input = root.createElement('input'); input.type = 'checkbox'; input.value = item.sceneItemId;
      input.checked = previously.has(`${item.sceneItemId}:${item.sourceUuid}`);
      input.addEventListener('change', () => { dirty = true; render(); });
      const name = root.createElement('span'); name.textContent = `${item.sourceName} (#${item.sceneItemId})`;
      label.append(input, name); $('targets').append(label);
    }
  };
  const discover = async () => {
    const result = await send('discover', {sceneUuid:$('scene').value}); items = result.items;
    $('capture').replaceChildren(...selectableItems(items).map(item => option(item.sceneItemId, `${item.sourceName} (#${item.sceneItemId})`)));
    const saved = status.config || {};
    if (saved.sceneUuid === $('scene').value) $('capture').value = String(saved.captureItemId);
    if (!$('capture').value && $('capture').options.length) $('capture').selectedIndex = 0;
    drawTargets();
    try {
      const current = selectedConfig($('scene').value, $('capture').value,
        [...$('targets').querySelectorAll('input:checked')].map(node => node.value), items);
      const comparable = value => JSON.stringify({...value,
        targets:[...value.targets].sort((a,b)=>a.sceneItemId-b.sceneItemId)});
      dirty = comparable(current) !== comparable({sceneUuid:saved.sceneUuid, captureItemId:saved.captureItemId,
        captureSourceUuid:saved.captureSourceUuid, targets:saved.targets || []});
    } catch { dirty = true; }
  };
  $('connect').addEventListener('click', () => act(async () => {
    const password = $('password').value;
    const data = await send('connect', {port:Number($('port').value), ...(password ? {password} : {})});
    $('password').value = '';
    $('scene').replaceChildren(...data.scenes.map(scene => option(scene.sceneUuid, scene.sceneName)));
    if (status.config?.sceneUuid) $('scene').value = status.config.sceneUuid;
    if (!$('scene').value && $('scene').options.length) $('scene').selectedIndex = 0;
    if ($('scene').value) await discover();
  }));
  $('scene').addEventListener('change', () => act(async () => { await discover(); dirty = true; }));
  $('capture').addEventListener('change', () => { drawTargets(); dirty = true; render(); });
  $('exclusive').addEventListener('change', render);
  $('save').addEventListener('click', () => act(async () => {
    await send('config', selectedConfig($('scene').value, $('capture').value,
      [...$('targets').querySelectorAll('input:checked')].map(node => node.value), items));
    dirty = false;
  }));
  $('template').addEventListener('click', () => act(() => send('template')));
  $('start').addEventListener('click', () => act(() => send('start', {exclusiveControl:$('exclusive').checked})));
  $('stop').addEventListener('click', () => act(() => send('stop')));
  new MutationObserver(render).observe(root.documentElement, {attributes:true, attributeFilter:['lang']});
  const poll = async () => {
    if (!busy) {
      try { await send(''); } catch { failed = true; }
      render();
    }
    setTimeout(poll, 1000);
  };
  send('').then(() => { $('port').value = status.config?.port || 4455; render(); }).catch(() => { failed = true; render(); });
  setTimeout(poll, 1000);
  render();
}

if (typeof document !== 'undefined') mountAutomation();
