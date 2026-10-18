-- SPDX-License-Identifier: MIT
-- Actual LuaJIT uint64 arithmetic; mocked Win32 launch avoids UI/processes.
local available, real_ffi = pcall(require, "ffi")
if not available then error("LUAJIT_FFI_UNAVAILABLE") end
local passed = 0
local function equal(actual, expected) assert(actual == expected, tostring(actual) .. " ~= " .. tostring(expected)) end
local function fixture(settings)
    local state = {launches = {}, logs = {}, result = 33, times_ok = true}
    local function decode(value)
        local result, index = "", 0
        while value[index] ~= 0 do result = result .. string.char(value[index]); index = index + 1 end
        return result
    end
    local kernel = {}
    function kernel.MultiByteToWideChar(_, _, value, _, destination, _)
        if destination ~= nil then for i = 1, #value do destination[i - 1] = value:byte(i) end; destination[#value] = 0 end
        return #value + 1
    end
    function kernel.GetCurrentProcessId() return 123 end
    function kernel.GetCurrentProcess() return 1 end
    function kernel.GetProcessTimes(_, created, _, _, _)
        created[0].high, created[0].low = 33554432, 123
        return state.times_ok and 1 or 0
    end
    local shell = {}
    function shell.ShellExecuteW(_, verb, program, args, directory, show)
        table.insert(state.launches, {verb = decode(verb), program = decode(program), args = decode(args), directory = decode(directory), show = show})
        return real_ffi.cast("void *", state.result)
    end
    local ffi = setmetatable({os = "Windows", load = function(name) return name == "kernel32" and kernel or shell end}, {__index = real_ffi})
    local obs = {LOG_INFO = 200, LOG_ERROR = 400, OBS_PATH_FILE = 0, OBS_PATH_FILE_SAVE = 1, OBS_TEXT_DEFAULT = 0}
    function obs.script_log(_, message) table.insert(state.logs, message) end
    function obs.obs_data_get_string(data, key) return data[key] or "" end
    function obs.obs_data_get_bool(data, key) return data[key] == true end
    function obs.obs_data_get_int(data, key) return data[key] or 0 end
    local function default(data, key, value) if data[key] == nil then data[key] = value end end
    obs.obs_data_set_default_string, obs.obs_data_set_default_int, obs.obs_data_set_default_bool = default, default, default
    function obs.obs_properties_create() return {} end
    function obs.obs_properties_add_button(props, key, _, callback) props[key] = callback end
    function obs.obs_properties_add_bool(...) end
    obs.obs_properties_add_int, obs.obs_properties_add_path, obs.obs_properties_add_text = obs.obs_properties_add_bool, obs.obs_properties_add_bool, obs.obs_properties_add_bool
    local environment = setmetatable({obslua = obs, require = function(name) equal(name, "ffi"); return ffi end,
        script_path = function() return 'C:/test path/native/' end}, {__index = _G})
    local chunk = assert(loadfile(ADAPTER_PATH)); setfenv(chunk, environment); chunk()
    state.settings, state.env = settings or {}, environment
    environment.script_defaults(state.settings); environment.script_load(state.settings)
    state.props = environment.script_properties()
    return state
end
local function config()
    return {python_path = 'C:\\Python path\\python.exe', node_path = 'C:\\Node path\\node.exe', native_channel = 'live_test-1', status_file = 'C:\\test path\\status.json'}
end
local function case(test) test(); passed = passed + 1 end
case(function() local s = fixture(config()); equal(#s.launches, 0); equal(s.settings.autostart, false) end)
case(function()
    local s = fixture(config()); s.props.start(); local v = s.launches[1]
    equal(v.verb, 'open'); equal(v.show, 0); equal(v.program, s.settings.python_path)
    assert(v.args:find('--obs%-pid 123 %-%-obs%-start%-ticks 144115188075855995'))
    assert(v.args:find('"C:/test path/native/live_observer.py"', 1, true))
    assert(v.args:find('--port 8765', 1, true)); assert(v.args:find('--status-file "C:\\test path\\status.json"', 1, true))
end)
case(function() local c = config(); c.autostart = true; local s = fixture(c); equal(#s.launches, 1) end)
case(function() local c = config(); c.native_channel = 'bad/channel'; local s = fixture(c); s.props.start(); equal(#s.launches, 0) end)
case(function() local c = config(); c.python_path = ''; local s = fixture(c); s.props.start(); equal(#s.launches, 0) end)
case(function() local s = fixture(config()); s.times_ok = false; s.props.start(); equal(#s.launches, 0) end)
case(function()
    local c = config(); c.node_path = 'C:\\quoted" directory\\node.exe'; c.status_file = 'C:\\trailing\\'
    local s = fixture(c); s.props.start(); local args = s.launches[1].args
    assert(args:find('"C:\\quoted\\" directory\\node.exe"', 1, true))
    assert(args:find('"C:\\trailing\\\\"', 1, true))
end)
NATIVE_OBSERVER_TESTS_PASSED = passed
