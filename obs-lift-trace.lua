-- OBS Lua integration. Keep this file beside server.py and start-obs-bridge.ps1.
obs = obslua
local ffi = require("ffi")
local settings = {}
local status_path = nil
local status_attempts = 0

local translations = {
    en = {
        description = "<b>Lift Trace</b><br>Starts the input overlay server with OBS.<br>A server started by this script stops when OBS exits. An already-running server is kept.<br>Settings page: Korean / Japanese / English.",
        autostart = "Start automatically with OBS", python_path = "Python for source users (leave empty for Windows app)",
        port = "Local port", device_id = "Controller ID (-1: do not select automatically)",
        start = "Start / connect input server", settings = "Open input settings", source_name = "Overlay source name",
        source_use_settings = "Use the size set in Lift Trace (recommended)",
        source_width = "Manual width (when the option above is off)", source_height = "Manual height (when the option above is off)",
        source_use_position = "Use the position calculated in Lift Trace (recommended)",
        source_x = "Manual X position (when the option above is off)", source_y = "Manual Y position (when the option above is off)", add = "Add overlay / apply placement",
    },
    ko = {
        description = "<b>Lift Trace</b><br>OBS 실행 시 입력 오버레이 서버를 함께 시작합니다.<br>직접 시작한 서버는 OBS 종료 시 함께 종료됩니다. 이미 별도로 실행 중이던 서버는 유지됩니다.<br>설정 화면: 한국어 / 일본어 / 영어.",
        autostart = "OBS 시작 시 자동 실행", python_path = "소스 실행용 Python (Windows 앱 사용자는 빈칸)",
        port = "로컬 포트", device_id = "컨트롤러 번호 (-1: 자동 선택 안 함)",
        start = "입력 서버 시작 / 연결", settings = "입력 설정 열기", source_name = "오버레이 소스 이름",
        source_use_settings = "앱에서 정한 크기 사용 (추천)",
        source_width = "직접 정할 너비 (위 항목을 끈 경우)", source_height = "직접 정할 높이 (위 항목을 끈 경우)",
        source_use_position = "앱에서 계산한 위치 사용 (추천)",
        source_x = "직접 정할 X 위치 (위 항목을 끈 경우)", source_y = "직접 정할 Y 위치 (위 항목을 끈 경우)", add = "오버레이 소스 추가 / 배치 적용",
    },
    ja = {
        description = "<b>Lift Trace</b><br>OBSと同時に入力オーバーレイのサーバーを起動します。<br>このスクリプトが起動したサーバーはOBS終了時に終了します。別途起動済みのサーバーは維持されます。<br>設定画面: 日本語 / 韓国語 / 英語。",
        autostart = "OBS起動時に自動起動", python_path = "ソース実行用 Python（Windows アプリでは空欄）",
        port = "ローカルポート", device_id = "コントローラーID（-1: 自動選択しない）",
        start = "入力サーバーを起動 / 接続", settings = "入力設定を開く", source_name = "オーバーレイのソース名",
        source_use_settings = "Lift Traceで設定したサイズを使う（おすすめ）",
        source_width = "手動の幅（上の項目をオフにした場合）", source_height = "手動の高さ（上の項目をオフにした場合）",
        source_use_position = "Lift Traceで計算した位置を使う（おすすめ）",
        source_x = "手動のX位置（上の項目をオフにした場合）", source_y = "手動のY位置（上の項目をオフにした場合）", add = "オーバーレイを追加 / 配置を適用",
    },
}

local function tr(key)
    local locale = obs.obs_get_locale and obs.obs_get_locale() or "en-US"
    local language = tostring(locale):lower():sub(1, 2)
    return (translations[language] or translations.en)[key] or translations.en[key] or key
end

if ffi.os == "Windows" then
    ffi.cdef[[
        int MultiByteToWideChar(unsigned int, unsigned long, const char *, int, uint16_t *, int);
        void *ShellExecuteW(void *, const uint16_t *, const uint16_t *, const uint16_t *, const uint16_t *, int);
        unsigned long GetCurrentProcessId(void);
    ]]
end

local function wide(value)
    local count = ffi.C.MultiByteToWideChar(65001, 0, value, -1, nil, 0)
    if count == 0 then error("Could not encode a Windows path") end
    local result = ffi.new("uint16_t[?]", count)
    ffi.C.MultiByteToWideChar(65001, 0, value, -1, result, count)
    return result
end

-- Windows argv quoting, with no shell interpolation of user-entered paths.
local function quote(value)
    value = value:gsub('(\\*)"', '%1%1\\"'):gsub('(\\+)$', '%1%1')
    return '"' .. value .. '"'
end

local function launch_hidden(program, arguments)
    if ffi.os ~= "Windows" then
        obs.script_log(obs.LOG_ERROR, "OBS auto-start currently supports Windows. Start server.py manually on other systems.")
        return false
    end
    local shell = ffi.load("shell32")
    local result = shell.ShellExecuteW(nil, wide("open"), wide(program), wide(arguments or ""), wide(script_path()), 0)
    if tonumber(ffi.cast("intptr_t", result)) <= 32 then
        obs.script_log(obs.LOG_ERROR, "Could not start the hidden bridge helper.")
        return false
    end
    return true
end

local function refresh_overlay()
    local source = obs.obs_get_source_by_name(settings.source_name)
    if not source then return end
    if obs.obs_source_get_unversioned_id(source) == "browser_source" then
        local props = obs.obs_source_properties(source)
        local button = obs.obs_properties_get(props, "refreshnocache")
        if button then obs.obs_property_button_clicked(button, source) end
        obs.obs_properties_destroy(props)
    end
    obs.obs_source_release(source)
end

local function check_startup()
    status_attempts = status_attempts + 1
    local file = status_path and io.open(status_path, "r")
    if file then
        local message = file:read("*a")
        file:close()
        if message:match("^ready") then
            obs.timer_remove(check_startup)
            refresh_overlay()
            obs.script_log(obs.LOG_INFO, "Lift Input is ready at http://127.0.0.1:" .. settings.port)
            return
        elseif message:match("^error") then
            obs.timer_remove(check_startup)
            obs.script_log(obs.LOG_ERROR, message)
            return
        end
    end
    if status_attempts >= 60 then
        obs.timer_remove(check_startup)
        obs.script_log(obs.LOG_WARNING, "Bridge startup was not confirmed. Check data/obs-bridge-*.status and the Python executable setting.")
    end
end

local function start_bridge()
    if ffi.os ~= "Windows" then
        obs.script_log(obs.LOG_WARNING, "Automatic bridge startup is available on Windows only.")
        return false
    end
    local pid = tonumber(ffi.C.GetCurrentProcessId())
    status_path = script_path() .. "data/obs-bridge-" .. pid .. "-" .. settings.port .. ".status"
    os.remove(status_path)
    local args = "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File " .. quote(script_path() .. "start-obs-bridge.ps1")
        .. " -Port " .. settings.port .. " -DeviceId " .. settings.device_id .. " -ObsProcessId " .. pid
    if settings.python_path ~= "" then args = args .. " -PythonPath " .. quote(settings.python_path) end
    if launch_hidden("powershell.exe", args) then
        obs.timer_remove(check_startup)
        status_attempts = 0
        obs.timer_add(check_startup, 500)
    end
    return false
end

local function configured_layout()
    local width, height = settings.source_width, settings.source_height
    local x, y = settings.source_x, settings.source_y
    if not settings.source_use_settings and not settings.source_use_position then return width, height, x, y end
    local file = io.open(script_path() .. "data/settings.json", "rb")
    local contents = "{}"
    if file then
        contents = file:read(32769) or ""
        file:close()
    end
    if #contents > 32768 then
        obs.script_log(obs.LOG_ERROR, "Open Lift Trace, save its settings, and try again: settings file is too large.")
        return nil
    end
    local data = obs.obs_data_create_from_json(contents)
    if not data then
        obs.script_log(obs.LOG_ERROR, "Open Lift Trace, save its settings, and try again: settings file could not be read.")
        return nil
    end
    local function number(key, fallback, minimum, maximum)
        if not obs.obs_data_has_user_value(data, key) then return fallback end
        local value = obs.obs_data_get_double(data, key)
        return math.floor(math.min(maximum, math.max(minimum, value)) + 0.5)
    end
    local lift = number("liftNumber", 0, 0, 999)
    if settings.source_use_settings then
        width = number("width", 400, 160, 3840)
        if obs.obs_data_get_string(data, "heightMode") == "manual" then
            local legacy = number("overlayHeight", number("liftHeight", 240, 40, 2160), 40, 2160)
            height = number("manualOverlayHeight", legacy, 40, 2160)
        else
            -- Same fullscreen 1080p approximation as web/engine.js.
            -- LIFT zero uses a transparent 1 px surface, not a visible input area.
            height = math.max(1, math.floor(723 * lift / 1000 + 0.5))
        end
    end
    if settings.source_use_position then
        -- Match getObsPlacement in web/engine.js. 2P is a mirrored estimate of
        -- the 1P reference: 1920 - 75 - 432. Custom size never moves the origin.
        x = (obs.obs_data_get_string(data, "side") == "2P" and 1413 or 75)
            + number("obsOffsetX", 0, -3840, 3840)
        y = 723 - math.floor(723 * lift / 1000 + 0.5)
            + number("obsOffsetY", 0, -2160, 2160)
    end
    obs.obs_data_release(data)
    return width, height, x, y
end

local function add_overlay()
    local width, height, x, y = configured_layout()
    if not width then return false end
    local scene_source = obs.obs_frontend_get_current_scene()
    if not scene_source then
        obs.script_log(obs.LOG_WARNING, "Select a scene before adding the overlay.")
        return false
    end
    local scene = obs.obs_scene_from_source(scene_source)
    local source = obs.obs_get_source_by_name(settings.source_name)
    if source and obs.obs_source_get_unversioned_id(source) ~= "browser_source" then
        obs.script_log(obs.LOG_ERROR, "A non-browser source already uses this name. Choose another source name.")
        obs.obs_source_release(source)
        obs.obs_source_release(scene_source)
        return false
    end
    local data = obs.obs_data_create()
    obs.obs_data_set_string(data, "url", "http://127.0.0.1:" .. settings.port .. "/overlay.html")
    obs.obs_data_set_int(data, "width", width)
    obs.obs_data_set_int(data, "height", height)
    obs.obs_data_set_bool(data, "is_local_file", false)
    obs.obs_data_set_bool(data, "shutdown", false)
    obs.obs_data_set_bool(data, "restart_when_active", false)
    obs.obs_data_set_bool(data, "fps_custom", true)
    obs.obs_data_set_int(data, "fps", 60)
    if source then obs.obs_source_update(source, data)
    else source = obs.obs_source_create("browser_source", settings.source_name, data, nil) end
    obs.obs_data_release(data)
    if source then
        local item = obs.obs_scene_find_source(scene, settings.source_name)
        if not item then item = obs.obs_scene_add(scene, source) end
        if item then
            local position = obs.vec2()
            position.x, position.y = x, y
            local scale = obs.vec2()
            scale.x, scale.y = 1, 1
            -- OBS alignment flags are C macros and are not exposed by every
            -- Lua binding. Top (4) + left (1) is the required source origin.
            obs.obs_sceneitem_set_alignment(item, (obs.OBS_ALIGN_TOP or 4) + (obs.OBS_ALIGN_LEFT or 1))
            obs.obs_sceneitem_set_bounds_type(item, obs.OBS_BOUNDS_NONE)
            local crop = obs.obs_sceneitem_crop()
            crop.left, crop.top, crop.right, crop.bottom = 0, 0, 0, 0
            obs.obs_sceneitem_set_crop(item, crop)
            obs.obs_sceneitem_set_scale(item, scale)
            obs.obs_sceneitem_set_pos(item, position)
            obs.obs_sceneitem_set_rot(item, 0)
            obs.obs_sceneitem_set_order(item, obs.OBS_ORDER_MOVE_TOP)
            obs.obs_sceneitem_set_visible(item, true)
            obs.obs_sceneitem_set_locked(item, true)
        end
        obs.obs_source_release(source)
    else
        obs.script_log(obs.LOG_ERROR, "OBS Browser Source is unavailable.")
    end
    obs.obs_source_release(scene_source)
    return false
end

local function open_settings()
    launch_hidden("http://127.0.0.1:" .. settings.port .. "/", "")
    return false
end

function script_description()
    return tr("description")
end

function script_defaults(data)
    obs.obs_data_set_default_bool(data, "autostart", true)
    obs.obs_data_set_default_string(data, "python_path", "")
    obs.obs_data_set_default_int(data, "port", 8765)
    obs.obs_data_set_default_int(data, "device_id", 0)
    obs.obs_data_set_default_string(data, "source_name", "Lift Input")
    obs.obs_data_set_default_bool(data, "source_use_settings", true)
    obs.obs_data_set_default_bool(data, "source_use_position", true)
    obs.obs_data_set_default_int(data, "source_width", 400)
    obs.obs_data_set_default_int(data, "source_height", 240)
    obs.obs_data_set_default_int(data, "source_x", 0)
    obs.obs_data_set_default_int(data, "source_y", 0)
end

function script_update(data)
    settings.autostart = obs.obs_data_get_bool(data, "autostart")
    settings.python_path = obs.obs_data_get_string(data, "python_path")
    settings.port = obs.obs_data_get_int(data, "port")
    settings.device_id = obs.obs_data_get_int(data, "device_id")
    settings.source_name = obs.obs_data_get_string(data, "source_name")
    settings.source_use_settings = obs.obs_data_get_bool(data, "source_use_settings")
    -- Existing installations may already have deliberately placed their source.
    -- Preserve explicit legacy coordinates until the user enables the new option.
    if not obs.obs_data_has_user_value(data, "source_use_position")
        and (obs.obs_data_has_user_value(data, "source_x") or obs.obs_data_has_user_value(data, "source_y")) then
        obs.obs_data_set_bool(data, "source_use_position", false)
    end
    settings.source_use_position = obs.obs_data_get_bool(data, "source_use_position")
    if settings.source_name == "" then settings.source_name = "Lift Input" end
    for _, key in ipairs({"source_width", "source_height", "source_x", "source_y"}) do
        settings[key] = obs.obs_data_get_int(data, key)
    end
end

function script_properties()
    local props = obs.obs_properties_create()
    obs.obs_properties_add_bool(props, "autostart", tr("autostart"))
    obs.obs_properties_add_path(props, "python_path", tr("python_path"), obs.OBS_PATH_FILE, "Executable (*.exe)", nil)
    obs.obs_properties_add_int(props, "port", tr("port"), 1024, 65535, 1)
    obs.obs_properties_add_int(props, "device_id", tr("device_id"), -1, 15, 1)
    obs.obs_properties_add_button(props, "start", tr("start"), start_bridge)
    obs.obs_properties_add_button(props, "settings", tr("settings"), open_settings)
    obs.obs_properties_add_text(props, "source_name", tr("source_name"), obs.OBS_TEXT_DEFAULT)
    obs.obs_properties_add_bool(props, "source_use_settings", tr("source_use_settings"))
    obs.obs_properties_add_int(props, "source_width", tr("source_width"), 80, 3840, 1)
    obs.obs_properties_add_int(props, "source_height", tr("source_height"), 40, 2160, 1)
    obs.obs_properties_add_bool(props, "source_use_position", tr("source_use_position"))
    obs.obs_properties_add_int(props, "source_x", tr("source_x"), -3840, 7680, 1)
    obs.obs_properties_add_int(props, "source_y", tr("source_y"), -2160, 4320, 1)
    obs.obs_properties_add_button(props, "add", tr("add"), add_overlay)
    return props
end

function script_load(data)
    script_update(data)
    if settings.autostart then start_bridge() end
end

function script_unload()
    obs.timer_remove(check_startup)
    -- The helper owns only the server it created and stops it when OBS exits.
end
