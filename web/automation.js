import { getLocale } from './i18n.js';

export const AUTO_TEXT = {
  en: {
    title:'Show sources during INFINITAS play · experimental',
    help:'Show selected OBS sources when the game shows its play screen, and hide them on other screens. This detects the game screen, not controller input.',
    connectionStep:'1. Connect to OBS', selectionStep:'2. Choose sources', referenceStep:'3. Register the play screen',
    connectionHelp:'In OBS, open Tools → WebSocket Server Settings and enable the server. Enter its port and password below.',
    port:'OBS WebSocket port', password:'Password (blank keeps the saved password)', connect:'Connect to OBS', refresh:'Refresh list',
    scene:'OBS scene', sceneHelp:'Choose the OBS scene containing the sources you want to control.', chooseScene:'Choose an OBS scene', chooseCapture:'Choose the original game capture',
    capture:'Source to read the game screen from', captureHelp:'Choose the original full game capture. This source stays visible and is excluded from automatic hiding.',
    targets:'Sources to show and hide automatically', targetsHelp:'Check to add a source; uncheck to remove it from automatic control. Then save. This does not delete sources from OBS.',
    duplicateHelp:'Repeated sources are distinguished by their position in the OBS source list.',
    duplicateTop:'upper placement', duplicateBottom:'lower placement', duplicatePosition:'placement {n} from the top',
    save:'Save selection', template:'Register play screen', referenceHelp:'Register once while the play screen with the SCORE label is visible.',
    extraTitle:'Supported setup and more help',
    supported:'This version supports the tested INFINITAS 1920 × 1080 layout. Other layouts and BMS are not supported yet. The pre-song play screen also counts as playing.',
    privacy:'Only a small reference crop is saved on this PC. Full game screenshots are not saved.',
    competing:'If you use another tool to show or hide these sources automatically, stop its rules for these sources before starting here.',
    start:'Start automatic visibility', stop:'Stop automatic visibility',
    stopHelp:'Stopping leaves the sources as they are. Automatic visibility starts only when you press Start, including after restarting Lift Trace.',
    reconnectHelp:'After an OBS disconnect or scene-collection change, reconnect and check your selected sources.',
    idle:'Stopped', playing:'Play screen detected', not_playing:'Outside the play screen', unknown:'Waiting for a recognizable game screen',
    shown:'Selected sources shown', hidden:'Selected sources hidden', uncertain:'Source visibility not confirmed',
    referenceReady:'Play screen registered', referenceMissing:'Register a play screen before starting',
    failure:'Could not complete this step. Check the OBS connection, selected sources and registered screen.',
    unavailable:'Automatic visibility dependencies are unavailable in this source environment.',
    dirty:'Source selection changed. Save it before registering a screen or starting.',
    chooseTarget:'Select at least one source to control. Use Stop to leave all sources under manual control.',
    connectFirst:'Connect to OBS to load its scenes and sources.', editWhileRunning:'Stop automatic visibility before changing the selected sources.',
    selectionInvalid:'Keep the original game capture visible, check the selected sources and save again.',
    connectFailed:'Enable the OBS WebSocket server and check its port and password.',
    catalogFailed:'Could not refresh the OBS source list. This refresh did not stop automatic visibility.',
  },
  ko: {
    title:'INFINITAS 플레이 중 소스 표시 · 실험 기능',
    help:'게임의 플레이 화면이 감지되면 선택한 OBS 소스를 표시하고, 그 외 화면에서는 숨깁니다. 컨트롤러 입력이 아닌 게임 화면을 감지합니다.',
    connectionStep:'1. OBS 연결', selectionStep:'2. 소스 선택', referenceStep:'3. 플레이 화면 등록',
    connectionHelp:'OBS의 도구 → WebSocket 서버 설정에서 서버를 켜고, 아래에 포트와 비밀번호를 입력하세요.',
    port:'OBS WebSocket 포트', password:'비밀번호 (비우면 저장된 값 유지)', connect:'OBS 연결', refresh:'목록 새로고침',
    scene:'OBS 장면', sceneHelp:'자동으로 제어할 소스가 들어 있는 OBS 장면을 선택하세요.', chooseScene:'OBS 장면 선택', chooseCapture:'원본 게임 캡처 선택',
    capture:'게임 화면을 읽을 소스', captureHelp:'전체 게임 화면이 보이는 원본 캡처를 선택하세요. 이 소스는 계속 표시하며 자동으로 숨기지 않습니다.',
    targets:'자동으로 표시·숨길 소스', targetsHelp:'체크하면 대상에 추가하고, 해제하면 제외합니다. 바꾼 뒤 저장하세요. OBS 소스 자체를 삭제하지는 않습니다.',
    duplicateHelp:'같은 소스를 여러 번 배치한 경우 OBS 소스 목록의 위·아래 위치로 구분합니다.',
    duplicateTop:'위쪽 배치', duplicateBottom:'아래쪽 배치', duplicatePosition:'위에서 {n}번째 배치',
    save:'선택 저장', template:'플레이 화면 등록', referenceHelp:'SCORE 글자가 보이는 플레이 화면에서 한 번 등록하세요.',
    extraTitle:'지원 범위와 추가 안내',
    supported:'현재는 확인된 INFINITAS 1920 × 1080 배치를 지원합니다. 다른 배치와 BMS는 아직 지원하지 않습니다. 곡이 시작되기 전 플레이 화면도 감지합니다.',
    privacy:'작은 기준 이미지만 이 PC에 저장합니다. 전체 게임 화면은 저장하지 않습니다.',
    competing:'다른 도구로도 같은 소스를 자동으로 표시·숨기고 있다면, 그 소스에 적용된 자동 제어를 중지한 뒤 시작하세요.',
    start:'자동 표시 시작', stop:'자동 표시 중지',
    stopHelp:'중지하면 소스의 현재 표시 상태를 유지합니다. Lift Trace를 다시 켰을 때도 시작 버튼을 눌러야 자동 표시가 켜집니다.',
    reconnectHelp:'OBS 연결이 끊기거나 장면 모음을 바꾸면 다시 연결하고 선택한 소스를 확인하세요.',
    idle:'중지됨', playing:'플레이 화면 감지', not_playing:'플레이 화면 아님', unknown:'게임 화면 확인 대기',
    shown:'선택한 소스 표시 중', hidden:'선택한 소스 숨김', uncertain:'소스 표시 상태 확인 안 됨',
    referenceReady:'플레이 화면 등록됨', referenceMissing:'시작하려면 플레이 화면을 등록하세요',
    failure:'이 단계를 완료하지 못했습니다. OBS 연결, 선택한 소스와 등록한 화면을 확인하세요.',
    unavailable:'이 소스 실행 환경에는 자동 표시에 필요한 라이브러리가 없습니다.',
    dirty:'소스 선택이 바뀌었습니다. 화면 등록이나 시작 전에 저장하세요.',
    chooseTarget:'제어할 소스를 한 개 이상 선택하세요. 모두 수동으로 제어하려면 자동 표시를 중지하세요.',
    connectFirst:'OBS에 연결하면 장면과 소스 목록이 나옵니다.', editWhileRunning:'소스 선택을 바꾸려면 먼저 자동 표시를 중지하세요.',
    selectionInvalid:'원본 게임 캡처를 켜고, 선택한 소스를 확인한 뒤 다시 저장하세요.',
    connectFailed:'OBS WebSocket 서버를 켜고 포트와 비밀번호를 확인하세요.',
    catalogFailed:'OBS 소스 목록을 불러오지 못했습니다. 이 새로고침으로 자동 표시를 중지하지는 않았습니다.',
  },
  ja: {
    title:'INFINITASのプレイ中にソースを表示 · 実験機能',
    help:'プレイ画面を検出すると選択したOBSソースを表示し、それ以外の画面では非表示にします。コントローラー入力ではなくゲーム画面を検出します。',
    connectionStep:'1. OBSに接続', selectionStep:'2. ソースを選択', referenceStep:'3. プレイ画面を登録',
    connectionHelp:'OBSのツール → WebSocketサーバー設定でサーバーを有効にし、ポートとパスワードを入力してください。',
    port:'OBS WebSocketポート', password:'パスワード（空欄なら保存済みの値を使用）', connect:'OBSに接続', refresh:'一覧を更新',
    scene:'OBSシーン', sceneHelp:'自動制御するソースがあるOBSシーンを選択してください。', chooseScene:'OBSシーンを選択', chooseCapture:'元のゲームキャプチャを選択',
    capture:'ゲーム画面を読み取るソース', captureHelp:'ゲーム画面全体が映る元のキャプチャを選択します。このソースは表示を維持し、自動では非表示にしません。',
    targets:'自動で表示・非表示にするソース', targetsHelp:'チェックで対象に追加し、外すと自動制御から除外します。変更後に保存してください。OBSのソース自体は削除しません。',
    duplicateHelp:'同じソースを複数配置した場合は、OBSのソース一覧の上下の位置で区別します。',
    duplicateTop:'上側の配置', duplicateBottom:'下側の配置', duplicatePosition:'上から{n}番目の配置',
    save:'選択を保存', template:'プレイ画面を登録', referenceHelp:'SCOREの文字が見えるプレイ画面で一度登録してください。',
    extraTitle:'対応範囲と補足',
    supported:'現在は確認済みのINFINITAS 1920 × 1080配置に対応しています。別の配置とBMSには未対応です。曲が始まる前のプレイ画面も検出します。',
    privacy:'小さな基準画像だけをこのPCに保存します。ゲーム画面全体は保存しません。',
    competing:'ほかのツールでも同じソースを自動で表示・非表示にしている場合は、そのソースの自動制御を停止してから開始してください。',
    start:'自動表示を開始', stop:'自動表示を停止',
    stopHelp:'停止時はソースの表示状態を維持します。Lift Traceの再起動後も、開始ボタンを押すまで自動表示は無効です。',
    reconnectHelp:'OBS切断やシーンコレクション変更後は、再接続して選択したソースを確認してください。',
    idle:'停止中', playing:'プレイ画面を検出', not_playing:'プレイ画面以外', unknown:'ゲーム画面の確認待ち',
    shown:'選択したソースを表示中', hidden:'選択したソースは非表示', uncertain:'ソースの表示状態を未確認',
    referenceReady:'プレイ画面を登録済み', referenceMissing:'開始前にプレイ画面を登録してください',
    failure:'この手順を完了できませんでした。OBS接続、選択したソース、登録した画面を確認してください。',
    unavailable:'このソース実行環境には自動表示に必要なライブラリがありません。',
    dirty:'ソースの選択が変わりました。画面の登録や開始前に保存してください。',
    chooseTarget:'制御するソースを1つ以上選択してください。すべて手動で制御する場合は自動表示を停止します。',
    connectFirst:'OBSに接続するとシーンとソースの一覧が表示されます。', editWhileRunning:'ソースの選択を変更する前に自動表示を停止してください。',
    selectionInvalid:'元のゲームキャプチャを表示し、選択したソースを確認して保存し直してください。',
    connectFailed:'OBS WebSocketサーバーを有効にして、ポートとパスワードを確認してください。',
    catalogFailed:'OBSソース一覧を更新できませんでした。この更新によって自動表示は停止していません。',
  },
};

export function selectableItems(items) {
  return items.filter(item => !item.isGroup && item.sourceType !== 'OBS_SOURCE_TYPE_SCENE');
}

// OBS indexes from bottom to top. Keep IDs internal; duplicate names need a
// placement hint so a cropped copy cannot be confused with its original.
export function sourceLabels(items, locale = 'en') {
  const words = AUTO_TEXT[locale] || AUTO_TEXT.en;
  const sorted = selectableItems(items).map((item,index)=>({item,index}))
    .sort((a,b)=>(b.item.sceneItemIndex ?? b.index)-(a.item.sceneItemIndex ?? a.index));
  return sorted.map(({item}) => {
    const copies=sorted.filter(other=>other.item.sourceName===item.sourceName);
    const index=copies.findIndex(other=>other.item.sceneItemId===item.sceneItemId);
    const suffix=copies.length===2 ? words[index===0 ? 'duplicateTop' : 'duplicateBottom']
      : words.duplicatePosition.replace('{n}',String(index+1));
    return {...item, label:copies.length>1 ? `${item.sourceName} · ${suffix}` : item.sourceName};
  });
}

export function selectedConfig(sceneUuid, captureId, targetIds, items) {
  if (!sceneUuid || captureId === '' || captureId === null || captureId === undefined) throw new Error('Select a scene and capture');
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
  const selected = () => selectedConfig($('scene').value, $('capture').value,
    [...$('targets').querySelectorAll('input:checked')].map(node => node.value), items);
  const markDirty = () => {
    const saved=status.config || {};
    const comparable=value=>JSON.stringify({...value,targets:[...value.targets].sort((a,b)=>a.sceneItemId-b.sceneItemId)});
    try { dirty=comparable(selected())!==comparable({sceneUuid:saved.sceneUuid,captureItemId:saved.captureItemId,
      captureSourceUuid:saved.captureSourceUuid,targets:saved.targets || []}); }
    catch { dirty=true; }
  };
  const render = () => {
    for (const node of $('panel').querySelectorAll('[data-auto-text]')) node.textContent = tr(node.dataset.autoText);
    const running = !!status.running;
    const message = {'obs-connect-failed':'connectFailed', 'obs-not-connected':'connectFirst',
      'obs-disconnected':'connectFirst', 'obs-request-failed':'connectFirst', 'obs-catalog-failed':'catalogFailed',
      'invalid-automation-config':'selectionInvalid', 'template-required':'referenceMissing'}[errorCode || status.error] || 'failure';
    let valid=false; try { selected(); valid=true; } catch { /* incomplete selection */ }
    $('status').textContent = [tr(!status.connected ? 'connectFirst' : running ? status.state || 'unknown' : 'idle'),
      tr(status.applied === true ? 'shown' : status.applied === false ? 'hidden' : 'uncertain'),
      tr(status.templateReady ? 'referenceReady' : 'referenceMissing'),
      status.available === false ? tr('unavailable') : '',
      dirty ? tr('dirty') : '', failed || status.error ? tr(message) : '',
    ].filter(Boolean).join(' · ');
    $('edit-help').textContent=running ? tr('editWhileRunning') : items.length && !valid ? tr('chooseTarget') : '';
    for (const id of ['connect','scene','capture','save','template','port','password']) $(id).disabled=busy || running;
    $('scene').disabled ||= !status.connected;
    $('capture').disabled ||= !status.connected;
    $('save').disabled ||= !valid || !dirty || !status.connected;
    $('template').disabled ||= dirty || !status.connected || !status.config?.captureSourceUuid;
    $('refresh').disabled=busy || dirty || !status.connected;
    $('start').disabled=busy || running || dirty || !status.connected || !status.templateReady || !status.config?.targets?.length;
    $('stop').disabled=!running;
    for (const input of $('targets').querySelectorAll('input')) input.disabled=busy || running || !status.connected;
    // Translate placement hints without rebuilding unsaved checks.
    const labels=new Map(sourceLabels(items,getLocale()).map(item=>[String(item.sceneItemId),item.label]));
    if ($('scene').options[0]?.value==='') $('scene').options[0].textContent=tr('chooseScene');
    if ($('capture').options[0]?.value==='') $('capture').options[0].textContent=tr('chooseCapture');
    for (const node of $('capture').options) node.textContent=labels.get(node.value) || node.textContent;
    for (const label of $('targets').querySelectorAll('label')) label.querySelector('span').textContent=labels.get(label.querySelector('input').value);
  };
  const send = async (action, value, read=false) => {
    const started = revision;
    const response = await request(`/api/automation${action ? '/' + action : ''}`, action && !read ? {
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
  const drawTargets = (keep=null) => {
    const checked = keep || new Set(status.config?.sceneUuid === $('scene').value
      ? status.config.targets?.map(item => `${item.sceneItemId}:${item.sourceUuid}`) : []);
    $('targets').replaceChildren();
    for (const item of sourceLabels(items,getLocale())) {
      if ($('capture').value !== '' && item.sceneItemId === Number($('capture').value)) continue;
      const label = root.createElement('label'); label.className = 'check';
      const input = root.createElement('input'); input.type = 'checkbox'; input.value = item.sceneItemId;
      input.checked = checked.has(`${item.sceneItemId}:${item.sourceUuid}`);
      input.addEventListener('change', () => { markDirty(); render(); });
      const name = root.createElement('span'); name.textContent = item.label;
      label.append(input, name); $('targets').append(label);
    }
    const candidates=selectableItems(items);
    $('duplicate-help').hidden=new Set(candidates.map(item=>item.sourceName)).size===candidates.length;
  };
  const catalog = async (sceneUuid=status.config?.sceneUuid) => {
    const result=await send('catalog'+(sceneUuid ? '?sceneUuid='+encodeURIComponent(sceneUuid) : ''),undefined,true);
    items=result.items;
    $('scene').replaceChildren(option('',tr('chooseScene')),...result.scenes.map(scene=>option(scene.sceneUuid,scene.sceneName)));
    $('scene').value=sceneUuid || '';
    $('capture').replaceChildren(option('',tr('chooseCapture')),...sourceLabels(items,getLocale()).map(item=>option(item.sceneItemId,item.label)));
    const saved=status.config || {};
    $('capture').value=saved.sceneUuid===$('scene').value ? String(saved.captureItemId) : '';
    if (!$('capture').value) $('capture').value=''; // Never guess the original among duplicates.
    drawTargets();
    if (items.length) markDirty(); else dirty=false;
  };
  $('connect').addEventListener('click', () => act(async () => {
    const password = $('password').value;
    await send('connect', {port:Number($('port').value), ...(password ? {password} : {})});
    $('password').value = '';
    await catalog();
  }));
  $('refresh').addEventListener('click', () => act(()=>catalog($('scene').value)));
  $('scene').addEventListener('change', () => act(()=>catalog($('scene').value)));
  $('capture').addEventListener('change', () => {
    const keep=new Set([...$('targets').querySelectorAll('input:checked')].map(node=>{
      const item=items.find(item=>item.sceneItemId===Number(node.value)); return `${item.sceneItemId}:${item.sourceUuid}`;
    }));
    drawTargets(keep); markDirty(); render();
  });
  $('save').addEventListener('click', () => act(async () => { await send('config',selected()); dirty=false; }));
  $('template').addEventListener('click', () => act(()=>send('template')));
  $('start').addEventListener('click', () => act(()=>send('start')));
  $('stop').addEventListener('click', () => act(()=>send('stop')));
  new MutationObserver(render).observe(root.documentElement, {attributes:true, attributeFilter:['lang']});
  const poll = async () => {
    if (!busy) { try { await send(''); } catch { failed=true; } render(); }
    setTimeout(poll,1000);
  };
  act(async()=>{ await send(''); $('port').value=status.config?.port || 4455; if (status.connected) await catalog(); });
  setTimeout(poll,1000);
}

if (typeof document !== 'undefined') mountAutomation();
