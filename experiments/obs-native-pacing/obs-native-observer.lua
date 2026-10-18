-- SPDX-License-Identifier: MIT
-- Optional launcher only. The observer reads the existing Lift Trace SSE stream;
-- it starts no second input server and owns only its Node child. OBS ownership
-- is verified by an exact process handle and creation time inside the observer.
local obs = obslua
local ffi = require("ffi")
local settings = {}
local shell, kernel
if ffi.os == "Windows" then
    if not pcall(ffi.typeof, "lift_native_observer_filetime") then
        ffi.cdef[[typedef struct { unsigned long low, high; } lift_native_observer_filetime;]]
    end
    ffi.cdef[[
        int MultiByteToWideChar(unsigned int, unsigned long, const char *, int, uint16_t *, int);
        void *ShellExecuteW(void *, const uint16_t *, const uint16_t *, const uint16_t *, const uint16_t *, int);
        unsigned long GetCurrentProcessId(void); void *GetCurrentProcess(void);
        int GetProcessTimes(void *, lift_native_observer_filetime *, lift_native_observer_filetime *,
                            lift_native_observer_filetime *, lift_native_observer_filetime *);
    ]]
    kernel, shell = ffi.load("kernel32"), ffi.load("shell32")
end

local function wide(value)
    local count = kernel.MultiByteToWideChar(65001, 0, value, -1, nil, 0)
    if count == 0 then error("Could not encode an observer path.") end
    local result = ffi.new("uint16_t[?]", count)
    if kernel.MultiByteToWideChar(65001, 0, value, -1, result, count) == 0 then error("Could not encode an observer path.") end
    return result
end

-- Windows argv quoting only; ShellExecute invokes the executable directly.
local function quote(value)
    value = value:gsub('(\\*)"', '%1%1\\"'):gsub('(\\+)$', '%1%1')
    return '"' .. value .. '"'
end

local function start_observer()
    local ok, message = pcall(function()
        if not kernel then error("The optional native observer requires Windows.") end
        if settings.python_path == "" or settings.node_path == "" then error("Set Python and Node executable paths.") end
        if #settings.native_channel < 1 or #settings.native_channel > 48
            or settings.native_channel:find("[^A-Za-z0-9_-]") then error("Enter a valid live channel (1–48 ASCII letters, digits, '_' or '-').") end
        if settings.port < 1024 or settings.port > 65535 then error("Enter a valid local Lift Trace port.") end
        local created, exited = ffi.new("lift_native_observer_filetime[1]"), ffi.new("lift_native_observer_filetime[1]")
        local kernel_time, user = ffi.new("lift_native_observer_filetime[1]"), ffi.new("lift_native_observer_filetime[1]")
        if kernel.GetProcessTimes(kernel.GetCurrentProcess(), created, exited, kernel_time, user) == 0 then
            error("Could not identify the original OBS process.")
        end
        -- FILETIME is larger than an exactly representable Lua number. Keep the
        -- calculation in uint64 and strip LuaJIT's literal suffix, without tonumber.
        local ticks = ffi.new("uint64_t", created[0].high) * ffi.new("uint64_t", 4294967296)
            + ffi.new("uint64_t", created[0].low)
        local exact_ticks = tostring(ticks):gsub("ULL$", ""):gsub("LL$", "")
        local args = quote(script_path() .. "live_observer.py") .. " --node " .. quote(settings.node_path)
            .. " --channel " .. quote(settings.native_channel) .. " --port " .. settings.port
            .. " --obs-pid " .. tonumber(kernel.GetCurrentProcessId()) .. " --obs-start-ticks " .. exact_ticks
        if settings.status_file ~= "" then args = args .. " --status-file " .. quote(settings.status_file) end
        local result = shell.ShellExecuteW(nil, wide("open"), wide(settings.python_path), wide(args), wide(script_path()), 0)
        if tonumber(ffi.cast("intptr_t", result)) <= 32 then error("Could not start the hidden native observer.") end
        obs.script_log(obs.LOG_INFO, "Native observer launch requested. Existing input server and settings are unchanged.")
    end)
    if not ok then obs.script_log(obs.LOG_ERROR, "Lift native observer: " .. tostring(message)) end
    return false
end

function script_description()
    return "<b>Lift Trace optional native observer</b><br>Reads the existing local input server. "
        .. "No second UI or controller poller is started. The observer and its Node child exit with this OBS process. "
        .. "The normal Lift Trace server, automation and recording remain independently managed."
end

function script_defaults(data)
    obs.obs_data_set_default_bool(data, "autostart", false)
    obs.obs_data_set_default_string(data, "python_path", "")
    obs.obs_data_set_default_string(data, "node_path", "")
    obs.obs_data_set_default_string(data, "native_channel", "")
    obs.obs_data_set_default_string(data, "status_file", "")
    obs.obs_data_set_default_int(data, "port", 8765)
end

function script_update(data)
    for _, name in ipairs({"python_path", "node_path", "native_channel", "status_file"}) do settings[name] = obs.obs_data_get_string(data, name) end
    settings.autostart = obs.obs_data_get_bool(data, "autostart")
    settings.port = obs.obs_data_get_int(data, "port")
end

function script_properties()
    local props = obs.obs_properties_create()
    obs.obs_properties_add_bool(props, "autostart", "Start optional observer with OBS")
    obs.obs_properties_add_path(props, "python_path", "Python executable", obs.OBS_PATH_FILE, "Executable (*.exe)", nil)
    obs.obs_properties_add_path(props, "node_path", "Node executable", obs.OBS_PATH_FILE, "Executable (*.exe)", nil)
    obs.obs_properties_add_text(props, "native_channel", "Native live channel", obs.OBS_TEXT_DEFAULT)
    obs.obs_properties_add_int(props, "port", "Existing Lift Trace local port", 1024, 65535, 1)
    obs.obs_properties_add_path(props, "status_file", "Optional observer status JSON", obs.OBS_PATH_FILE_SAVE, "JSON (*.json)", nil)
    obs.obs_properties_add_button(props, "start", "Start native observer", start_observer)
    return props
end

function script_load(data)
    script_update(data)
    if settings.autostart then start_observer() end
end

-- No unload kill: removing/reloading this script must not guess process IDs.
-- The observer holds the original OBS process handle and exits on its closure.
