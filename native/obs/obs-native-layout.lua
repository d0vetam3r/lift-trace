-- SPDX-License-Identifier: MIT
-- Optional native-source placement adapter. No input, recording, or visibility
-- policy lives here. OBS Lua timers run on the video thread: they must not open
-- handles, read files, wait for a writer, or fall back to a source name.
local obs = obslua
local ffi = require("ffi")
local config = {source_name = "Lift Native", native_channel = "", follow_position = true}
local binding, connection
local last_error, last_error_at = "", -math.huge
local SOURCE_ID, PACKET_BYTES, HEADER_BYTES = "lift_trace_native_pacing", 98472, 168

local labels = {
    en = {description = "<b>Lift Trace native layout experiment</b><br>Explicitly bind a native source, then follow the existing UI's 1080p placement. New items start hidden. Visibility remains owned by the separately selected automatic controller. No server or recording is started here.",
        source_name = "Native source name", native_channel = "Live channel (same as the experimental launcher)",
        follow_position = "Follow the UI's calculated position", add = "Add native source / bind and apply placement"},
    ko = {description = "<b>Lift Trace 네이티브 배치 실험</b><br>네이티브 소스를 명시적으로 연결한 뒤 기존 UI의 1080p 계산 위치를 따릅니다. 새 항목은 숨김 상태로 추가됩니다. 표시 제어는 별도로 선택한 자동 제어가 담당합니다. 이 스크립트는 서버나 녹화를 시작하지 않습니다.",
        source_name = "네이티브 소스 이름", native_channel = "라이브 채널 (실험용 런처와 동일)",
        follow_position = "UI에서 계산한 위치 따라가기", add = "네이티브 소스 추가 / 연결 및 배치 적용"},
    ja = {description = "<b>Lift Trace ネイティブ配置実験</b><br>ネイティブソースを明示的に接続し、既存UIの1080p計算位置に追従します。新しい項目は非表示で追加されます。表示制御は別途選択した自動制御が担当します。このスクリプトはサーバーや録画を開始しません。",
        source_name = "ネイティブソース名", native_channel = "ライブチャンネル（実験用ランチャーと同じ値）",
        follow_position = "UIで計算した位置に追従", add = "ネイティブソース追加 / 接続と配置適用"},
}

local function tr(key)
    local language = tostring(obs.obs_get_locale and obs.obs_get_locale() or "en-US"):lower():sub(1, 2)
    return (labels[language] or labels.en)[key]
end

local function report(message)
    local now = os.time()
    if message ~= last_error or now - last_error_at >= 10 then
        obs.script_log(obs.LOG_WARNING, "Lift native layout: " .. message)
        last_error, last_error_at = message, now
    end
end

local function valid_channel(channel)
    return type(channel) == "string" and #channel >= 1 and #channel <= 48
        and not channel:find("[^A-Za-z0-9_-]")
end

local function native_available()
    -- OBS preserves missing/failed sources as non-nil placeholders. A source
    -- object alone does not prove that the experimental plugin is loaded.
    local name = obs.obs_source_get_display_name(SOURCE_ID)
    return name ~= nil and name ~= ""
end

local kernel
if ffi.os == "Windows" then
    if not pcall(ffi.typeof, "lift_native_layout_header_v2") then
        ffi.cdef[[
            typedef struct {
                char magic[8]; uint32_t version, size;
                uint64_t session, sequence, qpc_ns; double epoch_ms;
                uint32_t alive, count; double settings[13]; uint32_t flags;
                int16_t obs_offset_x, obs_offset_y;
            } lift_native_layout_header_v2;
        ]]
    end
    ffi.cdef[[
        void *CreateFileMappingW(void *, void *, unsigned long, unsigned long, unsigned long, const uint16_t *);
        void *MapViewOfFile(void *, unsigned long, unsigned long, unsigned long, size_t);
        void *CreateMutexW(void *, int, const uint16_t *);
        unsigned long WaitForSingleObject(void *, unsigned long);
        int ReleaseMutex(void *); int CloseHandle(void *); int UnmapViewOfFile(const void *);
        int QueryPerformanceCounter(int64_t *); int QueryPerformanceFrequency(int64_t *);
    ]]
    kernel = ffi.load("kernel32")
end

local function close_connection(value)
    if not value then return end
    if value.view ~= nil then kernel.UnmapViewOfFile(value.view) end
    if value.mapping ~= nil then kernel.CloseHandle(value.mapping) end
    if value.mutex ~= nil then kernel.CloseHandle(value.mutex) end
end

local function wide_ascii(value)
    local result = ffi.new("uint16_t[?]", #value + 1)
    for index = 1, #value do result[index - 1] = value:byte(index) end
    return result
end

-- Called only by the explicit button or script_load, never by the timer.
-- Creating an empty mapping permits either side to start first. Its consumer
-- view is read-only; only the launcher publishes bytes under the same mutex.
local function open_connection(channel)
    if not kernel then return nil, "This adapter requires Windows." end
    if ffi.sizeof("lift_native_layout_header_v2") ~= HEADER_BYTES then
        return nil, "Unexpected shared-header ABI."
    end
    local value = {header = ffi.new("lift_native_layout_header_v2[1]"),
        counter = ffi.new("int64_t[1]"), frequency = ffi.new("int64_t[1]")}
    if kernel.QueryPerformanceFrequency(value.frequency) == 0 or tonumber(value.frequency[0]) <= 0 then
        return nil, "The monotonic clock is unavailable."
    end
    local name = "Local\\LiftTraceNative-" .. channel
    value.mutex = kernel.CreateMutexW(nil, 0, wide_ascii(name .. "-mutex"))
    if value.mutex == nil then return nil, "Could not create the snapshot mutex." end
    value.mapping = kernel.CreateFileMappingW(ffi.cast("void *", -1), nil, 4, 0,
        PACKET_BYTES, wide_ascii(name)) -- PAGE_READWRITE backing, FILE_MAP_READ view.
    if value.mapping ~= nil then value.view = kernel.MapViewOfFile(value.mapping, 4, 0, 0, PACKET_BYTES) end
    if value.view == nil then
        close_connection(value)
        return nil, "Could not map the read-only live snapshot."
    end
    return value
end

local function finite(value, low, high)
    return value == value and value >= low and value <= high
end

local function integer(value, low, high)
    return finite(value, low, high) and value == math.floor(value)
end

local function read_layout(value)
    if not value then return nil end
    local result = kernel.WaitForSingleObject(value.mutex, 0)
    if result == 258 then return nil end -- Busy: keep the existing position.
    if result == 128 then -- Abandoned: quarantine this possibly torn write.
        ffi.copy(value.header, value.view, HEADER_BYTES)
        value.blocked_session, value.blocked_sequence = value.header[0].session, value.header[0].sequence
        kernel.ReleaseMutex(value.mutex)
        return nil
    end
    if result ~= 0 then return nil end
    ffi.copy(value.header, value.view, HEADER_BYTES)
    if kernel.ReleaseMutex(value.mutex) == 0 then return nil end
    local h = value.header[0]
    if ffi.string(h.magic, 8) ~= "LIFTNV01" or h.version ~= 2 or h.size ~= PACKET_BYTES
        or h.session == 0 or h.sequence == 0 or h.qpc_ns == 0 or h.alive ~= 1 or h.count > 4096
        or h.flags > 63 or (h.session == value.blocked_session and h.sequence == value.blocked_sequence)
        or (h.session == value.session and h.sequence < value.sequence)
        or not finite(h.epoch_ms, 0, 100000000000000) then return nil end
    local s = h.settings
    if not finite(s[0], 50, 2000) or not integer(s[2], 0, 999) or not integer(s[1], 0, 999)
        or s[1] + s[2] > 999 or not integer(s[3], 160, 3840) or not integer(s[4], 1, 2160)
        or not finite(s[5], .5, 4) or not finite(s[6], .25, 2) or not finite(s[7], 2, 30)
        or not finite(s[8], .25, 4) or not finite(s[9], 0, 2000)
        or not integer(s[10], 1, 2000) or not integer(s[11], 1, 100) or not finite(s[12], 0, 1)
        or not integer(h.obs_offset_x, -3840, 3840) or not integer(h.obs_offset_y, -2160, 2160)
        then return nil end
    if kernel.QueryPerformanceCounter(value.counter) == 0 then return nil end
    local now = tonumber(value.counter[0]) / tonumber(value.frequency[0]) * 1000000000
    local age = now - tonumber(h.qpc_ns)
    if age < -250000000 or age > 1000000000 then return nil end
    value.session, value.sequence = h.session, h.sequence
    return (h.flags % 2 == 1 and 1413 or 75) + h.obs_offset_x,
        723 - math.floor(723 * s[2] / 1000 + .5) + h.obs_offset_y
end

local function source_matches(source, pinned)
    if not source or obs.obs_source_get_unversioned_id(source) ~= SOURCE_ID
        or obs.obs_source_get_uuid(source) ~= pinned.source_uuid
        or obs.obs_source_get_width(source) <= 0 then return false end
    local data = obs.obs_source_get_settings(source)
    local matches = obs.obs_data_get_string(data, "live_channel") == pinned.channel
    obs.obs_data_release(data)
    return matches
end

local function pinned_item(pinned)
    local scene_source = obs.obs_get_source_by_uuid(pinned.scene_uuid)
    if not scene_source then return nil end
    local scene = obs.obs_scene_from_source(scene_source)
    -- Enumeration retains each item until list_release. A scene source ref
    -- alone does not keep an item alive if another thread removes it.
    local items = scene and obs.obs_scene_enum_items(scene)
    local item
    for _, candidate in ipairs(items or {}) do
        if obs.obs_sceneitem_get_id(candidate) == pinned.item_id then item = candidate; break end
    end
    if not item or not source_matches(obs.obs_sceneitem_get_source(item), pinned) then
        if items then obs.sceneitem_list_release(items) end
        obs.obs_source_release(scene_source)
        return nil
    end
    return item, scene_source, items
end

local function set_position(item, x, y)
    local position = obs.vec2()
    position.x, position.y = x, y
    obs.obs_sceneitem_set_pos(item, position)
end

local function follow_position()
    if not config.follow_position or not binding or not connection
        or config.native_channel ~= binding.channel or config.source_name ~= binding.configured_name then return end
    local x, y = read_layout(connection)
    if not x then return end
    local item, scene_source, items = pinned_item(binding)
    if not item then report("The bound scene item was removed or replaced. Use Add / bind again."); return end
    -- Position only. No transform reset, visibility, lock, order or input reset.
    if x ~= binding.x or y ~= binding.y then set_position(item, x, y); binding.x, binding.y = x, y end
    obs.sceneitem_list_release(items)
    obs.obs_source_release(scene_source)
end

local function reset_transform(item)
    local scale, crop = obs.vec2(), obs.obs_sceneitem_crop()
    scale.x, scale.y = 1, 1
    crop.left, crop.top, crop.right, crop.bottom = 0, 0, 0, 0
    obs.obs_sceneitem_set_alignment(item, 5) -- OBS_ALIGN_TOP | OBS_ALIGN_LEFT
    obs.obs_sceneitem_set_bounds_type(item, obs.OBS_BOUNDS_NONE)
    obs.obs_sceneitem_set_crop(item, crop)
    obs.obs_sceneitem_set_scale(item, scale)
    obs.obs_sceneitem_set_rot(item, 0)
end

local function add_native()
    if not valid_channel(config.native_channel) then report("Enter a live channel: 1–48 ASCII letters, digits, '_' or '-'."); return false end
    if not native_available() then report("The experimental native plugin is unavailable."); return false end
    local new_connection, reason = open_connection(config.native_channel)
    if not new_connection then report(reason); return false end
    local scene_source = obs.obs_frontend_get_current_scene()
    local scene = scene_source and obs.obs_scene_from_source(scene_source)
    if not scene then
        if scene_source then obs.obs_source_release(scene_source) end
        close_connection(new_connection); report("Select a scene before binding."); return false
    end
    local source = obs.obs_get_source_by_name(config.source_name)
    local items, retained_new_item
    local function fail(message)
        if retained_new_item then obs.obs_sceneitem_release(retained_new_item) end
        if items then obs.sceneitem_list_release(items) end
        if source then obs.obs_source_release(source) end
        obs.obs_source_release(scene_source); close_connection(new_connection); report(message)
        return false
    end
    if source then
        if obs.obs_source_get_unversioned_id(source) ~= SOURCE_ID then return fail("This name belongs to a different source type. Choose another name.") end
        local data = obs.obs_source_get_settings(source)
        local channel = obs.obs_data_get_string(data, "live_channel")
        obs.obs_data_release(data)
        if channel ~= config.native_channel then return fail("This source belongs to another channel. Choose another source name or its existing channel.") end
    end
    local scene_uuid = obs.obs_source_get_uuid(scene_source)
    local item, count = nil, 0
    if source then
        local source_uuid = obs.obs_source_get_uuid(source)
        items = obs.obs_scene_enum_items(scene)
        for _, candidate in ipairs(items or {}) do
            if obs.obs_source_get_uuid(obs.obs_sceneitem_get_source(candidate)) == source_uuid then
                count = count + 1; item = candidate
            end
        end
        if count > 1 then
            item = nil
            if binding and binding.scene_uuid == scene_uuid and binding.source_uuid == source_uuid
                and binding.channel == config.native_channel then
                for _, candidate in ipairs(items or {}) do
                    if obs.obs_sceneitem_get_id(candidate) == binding.item_id then item = candidate; break end
                end
            end
            if not item or not source_matches(obs.obs_sceneitem_get_source(item), binding) then
                return fail("The selected scene contains multiple copies. Bind a single item before duplicating it.")
            end
        end
    end
    local data = obs.obs_data_create()
    obs.obs_data_set_string(data, "live_channel", config.native_channel)
    obs.obs_data_set_bool(data, "diagnostics", false)
    if source then obs.obs_source_update(source, data)
    else source = obs.obs_source_create(SOURCE_ID, config.source_name, data, nil) end
    obs.obs_data_release(data)
    if not source or obs.obs_source_get_width(source) <= 0 then return fail("The experimental native source could not be initialized.") end
    if not item then
        item = obs.obs_scene_add(scene, source)
        if not item then return fail("Could not add a native scene item.") end
        obs.obs_sceneitem_addref(item); retained_new_item = item
        obs.obs_sceneitem_set_visible(item, false)
    end
    local pinned = {scene_uuid = scene_uuid, source_uuid = obs.obs_source_get_uuid(source),
        item_id = obs.obs_sceneitem_get_id(item), channel = config.native_channel, configured_name = config.source_name}
    local x, y = read_layout(new_connection)
    reset_transform(item)
    if x then set_position(item, x, y); pinned.x, pinned.y = x, y end
    close_connection(connection)
    connection, binding = new_connection, pinned
    if retained_new_item then obs.obs_sceneitem_release(retained_new_item) end
    if items then obs.sceneitem_list_release(items) end
    obs.obs_source_release(source); obs.obs_source_release(scene_source)
    obs.script_log(obs.LOG_INFO, x and "Lift native layout bound; placement applied." or
        "Lift native layout bound; waiting for a fresh launcher snapshot. Existing position is preserved.")
    return false
end

function script_description() return tr("description") end

function script_defaults(data)
    obs.obs_data_set_default_string(data, "source_name", "Lift Native")
    obs.obs_data_set_default_string(data, "native_channel", "")
    obs.obs_data_set_default_bool(data, "follow_position", true)
end

function script_update(data)
    config.source_name = obs.obs_data_get_string(data, "source_name")
    if config.source_name == "" then config.source_name = "Lift Native" end
    config.native_channel = obs.obs_data_get_string(data, "native_channel")
    local following = obs.obs_data_get_bool(data, "follow_position")
    if following and not config.follow_position and binding then binding.x, binding.y = nil, nil end
    config.follow_position = following
    -- Edits never retarget the pin. A different name/channel requires Add / bind.
end

function script_properties()
    local props = obs.obs_properties_create()
    obs.obs_properties_add_text(props, "source_name", tr("source_name"), obs.OBS_TEXT_DEFAULT)
    obs.obs_properties_add_text(props, "native_channel", tr("native_channel"), obs.OBS_TEXT_DEFAULT)
    obs.obs_properties_add_bool(props, "follow_position", tr("follow_position"))
    obs.obs_properties_add_button(props, "add", tr("add"), add_native)
    return props
end

function script_save(data)
    obs.obs_data_set_string(data, "bound_scene_uuid", binding and binding.scene_uuid or "")
    obs.obs_data_set_string(data, "bound_source_uuid", binding and binding.source_uuid or "")
    obs.obs_data_set_int(data, "bound_item_id", binding and binding.item_id or 0)
    obs.obs_data_set_string(data, "bound_channel", binding and binding.channel or "")
    obs.obs_data_set_string(data, "bound_configured_name", binding and binding.configured_name or "")
end

function script_load(data)
    script_update(data)
    local pinned = {scene_uuid = obs.obs_data_get_string(data, "bound_scene_uuid"),
        source_uuid = obs.obs_data_get_string(data, "bound_source_uuid"), item_id = obs.obs_data_get_int(data, "bound_item_id"),
        channel = obs.obs_data_get_string(data, "bound_channel"), configured_name = obs.obs_data_get_string(data, "bound_configured_name")}
    if native_available() and pinned.scene_uuid ~= "" and pinned.source_uuid ~= "" and valid_channel(pinned.channel)
        and integer(pinned.item_id, 0, 9007199254740991) then
        local item, scene_source, items = pinned_item(pinned)
        if item then
            binding = pinned
            local reason
            connection, reason = open_connection(pinned.channel)
            if not connection then report(reason) end
            obs.sceneitem_list_release(items)
            obs.obs_source_release(scene_source)
        else report("Saved binding is no longer valid. Use Add / bind again.") end
    end
    obs.timer_add(follow_position, 250)
end

function script_unload()
    obs.timer_remove(follow_position)
    close_connection(connection); connection, binding = nil, nil
end
