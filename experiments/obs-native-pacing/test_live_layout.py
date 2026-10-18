"""Run the Lua adapter's OBS/WinAPI boundary tests without starting OBS.

Set LUA51_LIBRARY to a Lua 5.1/LuaJIT shared library (OBS ships lua51.dll on
Windows). Absence is an explicit skip; no system package is installed by tests.
The FFI boundary is mocked; the separate isolated OBS test covers real FFI/ABI.
"""
from __future__ import annotations

import ctypes
import ctypes.util
import json
import os
from pathlib import Path
import unittest

HERE = Path(__file__).resolve().parent


class LiveLayoutLuaTests(unittest.TestCase):
    def test_public_callbacks_and_timer(self):
        self.run_lua_mock("obs-native-layout.lua", "native-layout-mock.lua", "assert(NATIVE_LAYOUT_TESTS_PASSED == 16)")

    def test_observer_launcher_callbacks_and_exact_owner_identity(self):
        self.run_lua_mock("obs-native-observer.lua", "native-observer-mock.lua", "assert(NATIVE_OBSERVER_TESTS_PASSED == 7)")

    def run_lua_mock(self, adapter_name, mock_name, assertion):
        library = os.environ.get("LUA51_LIBRARY")
        if not library:
            library = ctypes.util.find_library("lua5.1") or ctypes.util.find_library("luajit-5.1")
        if not library:
            self.skipTest("Set LUA51_LIBRARY to run the Lua 5.1 adapter boundary tests.")
        lua = ctypes.CDLL(library)
        lua.luaL_newstate.restype = ctypes.c_void_p
        lua.luaL_openlibs.argtypes = [ctypes.c_void_p]
        lua.luaL_loadbuffer.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_size_t, ctypes.c_char_p]
        lua.luaL_loadbuffer.restype = ctypes.c_int
        lua.lua_pcall.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_int]
        lua.lua_pcall.restype = ctypes.c_int
        lua.lua_tolstring.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.POINTER(ctypes.c_size_t)]
        lua.lua_tolstring.restype = ctypes.c_char_p
        lua.lua_close.argtypes = [ctypes.c_void_p]
        state = lua.luaL_newstate()
        self.assertTrue(state, "Could not create a Lua state.")
        try:
            lua.luaL_openlibs(state)
            # json.dumps is used as Lua string syntax here, never shell code.
            program = ("ADAPTER_PATH = " + json.dumps((HERE / adapter_name).as_posix(), ensure_ascii=False) + "\n"
                       + (HERE / mock_name).read_text(encoding="utf-8") + "\n" + assertion + "\n").encode("utf-8")
            result = lua.luaL_loadbuffer(state, program, len(program), b"native-layout-mock")
            if result == 0:
                result = lua.lua_pcall(state, 0, 0, 0)
            if result:
                message = lua.lua_tolstring(state, -1, None)
                if message and b"LUAJIT_FFI_UNAVAILABLE" in message:
                    self.skipTest("Observer launch arithmetic mock requires LuaJIT FFI (included with OBS).")
                self.fail(message.decode("utf-8", errors="replace") if message else "Unknown Lua error")
        finally:
            lua.lua_close(state)


if __name__ == "__main__":
    unittest.main()
