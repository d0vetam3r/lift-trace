# Native renderer measurements — 2026-10-18

## Live transport, scratch and settings integration

The final Windows candidate connected generated controller samples through the
**unchanged** `Bridge` polling/subscription path, `InputClient`, `ScratchTracker`
and `TrailEngine`, then through local shared memory to the OBS C renderer.
It used the existing settings and device HTTP handlers with in-memory requests.
No browser UI was operated. The physical WinMM adapter was available, but no
connected controller was detected; the user deferred physical interaction.
These are automated end-to-end input-path tests, **not actual-controller gameplay**.

The isolated OBS 32.1.2 recording used 432 × 390 at 60 fps (432 × 290 input notes
plus diagnostics), H.264 NVENC, and the same encoder settings as the earlier
baseline below. In its steady 2–10-second window:

| Measurement | Final live candidate |
| --- | ---: |
| Decoded frames / measured transitions | 480 / 479 |
| Stationary input-note frames / large steps | 0 / 0 |
| Qualified actual pixel-motion coverage | 100% |
| Invalid barcodes / output PTS gaps | 0 / 0 |
| Movement error RMS versus nominal 60Hz step | 0.294 px |
| Render callback CPU submission cost, p99 | 0.286 ms |

Every source tick advanced by one. CPU cost excludes GPU completion and encoding.
This small recording does not establish gameplay input latency or behavior under
game/OBS overload. A preceding integration run also had 0/0 stationary/large
steps over 479 transitions; final results above include the connection worker.

The final recording also confirmed:

- Both scratch directions have distinct colors and visible circular arrows.
- Existing UI settings requests changed 1P to 2P, 12px to 6px note heads,
  head-only to body display, and then 400 × 240 output dimensions. Appearance
  settings did not reset held input intervals; scratch stayed exempt from
  keyboard shortening.
- OBS created the source before the producer started; the connection worker
  attached without an OBS settings update.
- Terminating only the owned Node observer at about 19 seconds cleared colored
  input marks by the 20.5-second sample. Controller polling and existing status
  requests continued. Restarting the producer on the same channel at about
  21 seconds restored actual note and arrow pixels by the 22.5-second sample.

The separate C geometry library matched the real JavaScript renderer across
720 settings/time snapshots and 1,368 input-event vectors. All ten compared
values matched with maximum absolute error 0 (tolerance 1e-7). Coverage includes
keyboard and clockwise/counterclockwise scratch, wrapping/reversal, delayed
release, strict shortening thresholds, 2P and normalized UI changes. Another
10 Node observer tests and 14 transport/protocol tests passed locally, including
producer ownership, held consumer handles during restart, nonblocking contention,
abandoned mutexes, EOF/crash cleanup and malformed/stale data. The previous
420 synthetic geometry vectors and 126 existing JavaScript tests also passed.

Tested C source SHA-256:
`5e38b7c31057a8f07020600e9173bef993adb0a6d21347728dade5c7bdfb466b`

Tested experimental DLL SHA-256:
`3b97e571b222400884a7783962e7466e203942ad7b5e5019c27bc98ca2196459`

No production OBS configuration, executable, settings, media, Core or Remote was
changed. Owned test OBS/Node processes exited. The original settings file hash
was unchanged. Scene placement (`obsOffsetX/Y` and the existing automatic
placement button), automatic visibility and recording remain on the original
browser source; this experiment does not migrate them. Lift Trace remains
independent, and recording code and the four-minute rule are untouched.

한국어: 기존 입력·스크래치 코드와 표시 설정을 C 렌더러에 연결해 자동 검증했습니다.
최종 녹화의 479개 프레임 전환에서 멈춤·큰 이동은 각각 0회였습니다. 양방향 스크래치,
설정 변경, 연결 종료 후 노트 제거와 재시작 복구를 확인했습니다. 컨트롤러가 연결되어
있지 않아 실물 테스트는 사용자의 요청에 따라 보류했습니다. OBS 자동 배치·자동 표시·
녹화 대상 전환은 포함하지 않고, 기존 환경·독립 실행·4분 저장 규칙을 유지합니다.

日本語: 既存の入力・スクラッチ処理と表示設定を C レンダラーへ接続し、自動検証しました。
最終録画の479フレーム遷移で停止・大きな移動は各0回でした。両方向スクラッチ、設定変更、
切断時の消去と再起動後の復帰を確認しました。機器未接続のため、実機確認は利用者の希望で
保留しています。OBS 自動配置・自動表示・録画対象の移行は含まず、既存環境・単独実行・
最大4分の保存規則を維持しています。

## Earlier synthetic pacing comparison

The remaining sections preserve results for the earlier synthetic-only revision.
They predate the live integration described above.

The OBS-native C prototype eliminated the observed stationary/catch-up pattern
in both measured synthetic runs. This is evidence for the rendering approach,
not a production release or a guarantee under gameplay/GPU overload.

| Run | Measured transitions | Stationary note frames | Large note steps | Motion error RMS (px) |
| --- | ---: | ---: | ---: | ---: |
| Browser A | 1,199 | 116 | 116 | 6.308 |
| Native C A | 1,199 | 0 | 0 | 0.373 |
| Browser B | 1,199 | 61 | 59 | 4.637 |
| Native C B | 1,199 | 0 | 0 | 0.373 |

Four sequential 24-second recordings were measured over the same central
2–22-second window (1,200 frames each). Sources were removed between trials;
no previous browser source remained underneath the next source. Both native
runs advanced one source tick for every output transition. Browser B included
two three-tick jumps, so stationary and large-step counts need not match.

The independent pixel tracker measured note-head movement in seven keyboard
lanes; it did not infer visual success from the counter alone. All four runs
had 100% qualified motion coverage, zero invalid barcodes, and no output PTS
gaps. Normal movement is 14.165444 px per frame. Native pixel movement was
approximately 14 or 15 px, consistent with rasterization; RMS is measured
against the nominal 60 fps step, excluding MKV millisecond PTS quantization.
No rendering/encoding lag was reported by the test OBS log.

## Conditions and limits

- Windows x64, OBS 32.1.2, obs-browser 2.26.8 / CEF 127, RTX 5070 Ti.
- A disposable hidden portable OBS, isolated scene/configuration, no game,
  camera, microphone, controller, Core, or Remote sources or connections.
- 432 × 390 output at 60 fps, including a 432 × 290 note area and barcodes.
  Native and browser receive the same normalized fixture settings and synthetic
  120 ms press / 40 ms release schedule. Note heads are 12 px; bodies are off.
- Browser geometry/rendering is imported from the existing production JS.
  Native geometry uses the same equations at the OBS video-frame time.
- NVENC H.264 CQP 16 / P1. The actual encoder log reports two B-frames and AQ
  enabled in all runs. Analysis uses decoded display frames, not packet order.
- CPU callback cost p99: browser 0.200/0.200 ms, native 0.168/0.135 ms.
  These values exclude GPU completion and cannot measure input latency.
- Sequence is A/B/A/B, one PC/session. Background system load was not controlled.
  This was not a simultaneous game-capture or high-load streaming test.
- Only synthetic keyboard inputs are connected. Existing UI and input history
  remain unchanged; live settings/input transport and scratch rendering are
  not implemented in this prototype. Standalone Lift Trace and the separate
  recording service's first-at-most-240-second rule are unchanged.

## Build and checks

- Existing portable Clang 22 / LLD, C11, `-O2 -Wall -Wextra -Werror` passed.
- The local test used declarations checked against official OBS 32.1.2 headers
  and an import library generated from that installation's `obs.dll` exports.
  This local ABI adapter is not a distributed SDK. The conventional CMake path
  with an official SDK has not been exercised in this environment.
- Pure C clock/geometry/bounds regression passed. All 420 vectors generated by
  the actual existing JS renderer matched the C geometry, including body/short
  display, delay, side and preserved event timestamps.
- Pixel analyzer self-tests distinguish frozen notes even when a counter keeps
  advancing. Previous browser recordings also reproduced matching pixel and
  counter anomalies.
- Tested C source SHA-256:
  `c7caab0d11bb94d85a17dfae6a97f5647248c496effc11ea4fdd4d32b8ef17d2`.
- Tested native DLL SHA-256:
  `7402419be84e4c970bda15948041355d202031cd6bc8c71b0ea2888516433311`.
- Test OBS and its descendants exited after completion. No administrator
  request, UI interaction, production installation, or settings modification
  was used. No DLL, private configuration, logs, or recording is published here.

## 한국어

각 20초 구간의 실제 노트 이동을 비교한 결과, 브라우저의 정지는 116회·61회,
C 렌더러는 두 번 모두 0회였습니다. 노트 픽셀 추적률은 모두 100%이며 바코드
오류와 출력 프레임 시간의 누락은 없었습니다. 기존 JS 렌더러와의 계산 비교
420개도 통과했습니다. 이 결과는 OBS 내부 렌더링 방식의 효과를 뒷받침합니다.

이전 합성 건반 시험 당시에는 실제 게임 부하·컨트롤러·스크래치와
설정 UI의 실시간 전달을 검증하지 않았습니다. 후속 검증은 문서 위쪽에 기록했습니다. 기존 설정 UI와 입력 기록,
Lift Trace 독립 실행, 최초 최대 4분 저장 규칙은 변경하지 않았습니다.
실행 중인 제품 환경에 적용하지 않았고 관리자 권한·화면 조작도 사용하지
않았습니다. 일반 SDK/CMake 빌드는 이 환경에서 검증하지 않았습니다.

## 日本語

各20秒区間の実際のノーツ移動を比較した結果、ブラウザーでは116回・61回の
停止があり、Cレンダラーでは両方とも0回でした。ピクセル追跡率はすべて
100%で、バーコードエラーや出力フレーム時刻の欠落はありませんでした。
既存JSレンダラーとの計算比較420件も成功しました。この結果はOBS内部で
描画する方式の有効性を裏付けます。

以前の合成鍵盤試験の時点では、実ゲーム負荷、コントローラー、スクラッチ、
設定UIからのリアルタイム転送は未検証でした。その後の検証は文書上部に記載しています。既存の設定UIと入力記録、
Lift Traceの単独実行、開始から最大4分の保存ルールは変更していません。
通常の実行環境には適用せず、管理者権限や画面操作も使用していません。
通常のSDK/CMakeビルドはこの環境では検証していません。
