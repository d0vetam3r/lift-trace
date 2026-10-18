# 선택적 OBS 네이티브 렌더러

[한국어](README.ko.md) · [日本語](README.ja.md) · [English](README.md)

이 폴더는 실입력 렌더러, 읽기 전용 입력 전달 프로세스와 OBS 어댑터를 담당합니다. 명시적으로 설치하는 선택 구성 요소이며 정식 Windows 앱 배포에는 포함하지 않습니다. 일반 앱·브라우저 미리보기·설정 UI·입력 기록은 그대로이며 Node, 이 플러그인, Live Core, 리모컨 없이 독립 실행됩니다.

| 경로 | 역할 |
| --- | --- |
| `live_observer.py` | 기존 로컬 상태/SSE 읽기, 재연결 및 자신이 실행한 Node 관리 |
| `live_bridge.py`, `live-input.mjs` | 크기가 제한된 공유 메모리 전달과 기존 입력·스크래치 엔진 재사용 |
| `lift-native-pacing.c`, `live-protocol.h`, `pacing-geometry.h` | OBS 프레임 기준 그리기, v2 검증과 실입력 위치 계산 |
| `obs-native-observer.lua` | 원래 OBS 프로세스 수명에 연결한 선택적 숨김 실행 |
| `obs-native-layout.lua` | 명시적으로 고정한 장면·항목·소스·채널의 위치 추적 |
| `tests/` | 생성 입력, 전달·수명 검사 및 OBS 모의 검사 |

## 기존 앱에 연결

Python 3.10+, Node 22+, 별도로 빌드한 플러그인이 필요합니다. 기존 Lift Trace를 실행한 뒤 연결합니다.

```text
python native/obs/live_observer.py --node PATH_TO_NODE_EXE --channel lift-test --port 8765
```

OBS 네이티브 소스에 같은 채널을 지정합니다. 입력 폴러·서버·설정 UI·녹화 제어기를 중복 실행하지 않습니다. 오래된 입력은 1초 안에 비우고 새 엔진으로 재연결합니다. 기존 UI가 설정을 관리하며 실제 입력 시각은 바꾸지 않습니다. 영상 스레드의 공유 메모리 읽기는 대기하지 않습니다.

두 Lua는 OBS와 함께 실행하거나 설정의 위치를 따르는 선택 기능입니다. 자동 표시는 기존 UI에서 네이티브 항목을 선택합니다. 배치의 연결 버튼은 변환을 초기화하므로 코드 갱신만을 위해 다시 연결하지 마세요. 배포 시 기존 소스 이름·UUID·항목 ID·자르기·표시·녹화 대상은 보존합니다. Core는 선택 요소이며 최초 최대 240초 저장과 다음 판 미저장 폐기 규칙을 담당합니다.

## 빌드 경계

OBS 버전에 맞는 공식 SDK와 C11 컴파일러로 `native/obs/CMakeLists.txt`를 빌드합니다. 이 빌드는 **채널이 비어 있어도 시험 노트를 생성하지 않습니다.** 진단 바코드는 명시적 선택 기능이며 기본 꺼짐입니다. 기존 장면과의 호환성을 위해 모듈 파일명 `lift-native-pacing`, 소스 ID `lift_trace_native_pacing`, 프로토콜 v2와 Lua 저장 키를 유지합니다.

CMake는 설치 단계를 포함하지 않는 참고 경로입니다. 소스 검사가 통과했다는 것만으로 특정 SDK 빌드까지 검증했다고 볼 수 없습니다. SDK·DLL·개인 설정·녹화는 배포하지 않습니다.

[프레임 비교 실험](../../experiments/obs-native-pacing/README.ko.md)은 합성 입력 빌드·일회용 녹화 도구·분석을 담당합니다. 이 실험 빌드는 빈 채널에서 기존 120ms 주기·40ms 누름을 생성합니다. 방송용으로 설치하지 마세요. 실입력 그리기는 같은 구현을 공유하며 소스 ID도 같으므로 두 빌드를 동시에 로드하지 않습니다.

## 기존 경로와 배포

기존 실험 폴더의 `live_observer.py`, `live_bridge.py`, `live-input.mjs`, 두 Lua 경로는 이 구현으로 연결됩니다. 배포 시 저장소의 상대 구조를 유지하고 이 폴더의 실행 파일, 이미 등록된 기존 경로의 연결 파일, `web/client.js`, `web/engine.js`, `web/games/infinitas.js`를 함께 복사합니다. 기존 경로를 유지하면 스크립트 재등록·설정 이전이 필요하지 않습니다. OBS를 닫은 상태에서 실사용 빌드 DLL로 교체합니다.

## 검증

```text
node --test native/obs/tests/live-input.test.mjs
python -m unittest discover -s native/obs/tests -p "test_*.py"
```

생성 입력과 모의 어댑터 검사이며 실물 컨트롤러·게임 부하 검증은 아닙니다. 선택 검사에는 기존 LuaJIT의 `LUA51_LIBRARY`와 별도 실입력 계산 검사 라이브러리의 `LIFT_NATIVE_TEST_GEOMETRY_DLL`를 지정합니다. 압축 해제한 소스에서도 새 경로와 기존 경로의 실행을 검사합니다.

`tests/renderer-mode-test.c`는 그래픽 호출을 모의 처리합니다. 일반 빌드와 `LIFT_NATIVE_SYNTHETIC=1` 빌드를 각각 만들고 필요한 검사 코드만 링크한 뒤, `LIFT_NATIVE_TEST_RUNTIME_MODE_DLL`과 `LIFT_NATIVE_TEST_BENCHMARK_MODE_DLL`을 지정하면 두 빌드의 빈 채널·오래된 입력·실입력 검사를 실행합니다.

새 코드는 저장소 MIT 라이선스를 따릅니다. OBS 구성 요소는 별도의 GPL-2.0-or-later 라이선스를 따르므로 연결된 플러그인의 빌드·배포 시 해당 라이선스를 확인합니다.
