# Optional native OBS renderer

[한국어](README.ko.md) · [日本語](README.ja.md) · [English](README.md)

This directory owns the optional live renderer, read-only input observer and OBS adapters. It is still an explicitly installed optional component, not part of the released Windows app. The ordinary app, browser preview, settings UI and input history remain unchanged and run without Node, this plugin, Live Core or Remote.

| Path | Responsibility |
| --- | --- |
| `live_observer.py` | Read the existing loopback status/SSE stream; reconnect and own only its Node child. |
| `live_bridge.py`, `live-input.mjs` | Bounded shared-memory transport and the existing `InputClient`/`TrailEngine`/`ScratchTracker`. |
| `lift-native-pacing.c`, `live-protocol.h`, `pacing-geometry.h` | OBS-frame drawing, protocol v2 validation and live-event geometry. |
| `obs-native-observer.lua` | Optional hidden observer launch, tied to the exact original OBS process. |
| `obs-native-layout.lua` | Optional position following for an explicitly pinned scene/item/source/channel. |
| `tests/` | Offline input, transport and mocked OBS/lifecycle checks. |

## Existing application

With Python 3.10+, Node 22+ and the separately built plugin, attach to an already running Lift Trace app:

```text
python native/obs/live_observer.py --node PATH_TO_NODE_EXE --channel lift-test --port 8765
```

Enter the same channel in the native OBS source. The observer creates no second input poller, server, settings UI or recording controller. It clears stale input within one second and reconnects with a fresh engine. The existing UI remains the settings owner; source input timestamps are not rewritten. Shared-memory acquisition never waits on the video thread.

The two optional Lua scripts can start the observer with OBS and follow position settings. The existing automatic-control UI selects the native item just as it selects a browser item. Binding is explicit; the layout bind button normalizes transforms, so do not rebind an existing deployed item merely to update code. Source names, UUIDs, item IDs, crop, visibility and recording target identities must be retained during deployment. Core remains optional and owns the first-at-most-240-second save/next-round unsaved-discard rule.

## Build boundary

Build `native/obs/CMakeLists.txt` with a matching official OBS SDK and C11 compiler. This build generates **no synthetic notes**, including when the channel is empty. Diagnostic barcodes remain an explicit opt-in and default off. Keep the existing module filename `lift-native-pacing` and source ID `lift_trace_native_pacing` for saved-scene compatibility; their historical names do not select benchmark behavior. Protocol v2 and Lua saved setting keys are unchanged.

The CMake route is a reference build with no install step. Local validation may use a recorded separate toolchain; do not infer an SDK/build route was tested from source tests alone. No SDK, DLL, local settings or recordings are distributed here.

[The pacing experiment](../../experiments/obs-native-pacing/README.md) contains the explicit synthetic build, disposable recording scripts and analysis. Its build still generates the original 120 ms/40 ms schedule with an empty channel. Do not install that benchmark DLL for live use. Both builds share the same live drawing implementation and must not be loaded together because their source IDs intentionally match.

## Compatibility and migration

Existing `experiments/obs-native-pacing/live_observer.py`, `live_bridge.py`, `live-input.mjs` and the two Lua paths forward to this implementation. Keep the repository-relative layout when deploying: copy this directory's runtime files, the legacy entry shims if already registered, and the existing `web/client.js`, `web/engine.js`, `web/games/infinitas.js` dependencies. No OBS script re-registration or settings migration is needed when retaining those paths. Install with OBS stopped; replace the plugin only with the live runtime build.

## Validation

```text
node --test native/obs/tests/live-input.test.mjs
python -m unittest discover -s native/obs/tests -p "test_*.py"
```

Tests use generated input and mocked adapters; they do not prove physical-controller behavior or pacing under game load. Set `LUA51_LIBRARY` to an existing LuaJIT library and `LIFT_NATIVE_TEST_GEOMETRY_DLL` to the separately built live geometry test library for the optional checks. Source archive tests also exercise extracted canonical and legacy entry points.

`tests/renderer-mode-test.c` uses mocked graphics. Build it once normally and once with `LIFT_NATIVE_SYNTHETIC=1`, linking only retained test code; set `LIFT_NATIVE_TEST_RUNTIME_MODE_DLL` and `LIFT_NATIVE_TEST_BENCHMARK_MODE_DLL` to run the empty/stale/live-input checks for both builds.

New source uses the repository MIT license. OBS components retain their GPL-2.0-or-later license; consult the component licenses when building or distributing a linked plugin.
