-- SPDX-License-Identifier: MIT
-- OBS/WinAPI boundary mock. Executes public script callbacks and the actual
-- registered timer; no OBS process, input device, file polling or native DLL.
local adapter_path = assert(ADAPTER_PATH)
local passed = 0
local function copy(value)
    if type(value) ~= "table" then return value end
    local result = {}; for key, child in pairs(value) do result[key] = copy(child) end
    return result
end
local function equal(actual, expected, label)
    assert(actual == expected, (label or "value") .. ": expected " .. tostring(expected) .. ", got " .. tostring(actual))
end

local function fixture()
    local s = {now = 10000000000, wait = 0, handles = 0, views = 0, data_refs = 0, lists = 0,
        sources = {}, names = {}, all_items = {}, serial = 0, next_item = 1, maps = {}, logs = {}, plugin = true,
        opens = 0, pos_writes = 0, visibility_writes = 0, reset_writes = 0}
    function s:source(name, kind)
        self.serial = self.serial + 1
        local source = {uuid = "source-" .. self.serial, name = name, kind = kind, refs = 0,
            data = {live_channel = "test"}, width = 432}
        if kind == "scene" then source.scene = {items = {}} end
        self.sources[source.uuid], self.names[name] = source, source
        return source
    end
    function s:item(scene_source, source)
        local item = {source = source, id = self.next_item, refs = 0, visible = true, locked = true,
            x = 11, y = 22, scale = {x = 2, y = 3}, rotation = 15, alignment = 0, bounds = 3,
            crop = {left = 1, top = 2, right = 3, bottom = 4}, order = 7}
        self.next_item = self.next_item + 1
        table.insert(scene_source.scene.items, item)
        table.insert(self.all_items, item)
        return item
    end
    function s:packet(channel)
        local packet = {magic = "LIFTNV01", version = 2, size = 98472, session = 3, sequence = 1,
            qpc_ns = self.now, epoch_ms = 1700000000000, alive = 1, count = 0, flags = 32,
            obs_offset_x = 0, obs_offset_y = 0,
            settings = {[0] = 300, 0, 400, 432, 289, 1.6, 1, 6, 1, 0, 200, 30, .38}}
        local name = "Local\\LiftTraceNative-" .. (channel or "test")
        self.maps[name] = self.maps[name] or {}
        self.maps[name].packet = packet
        return packet
    end
    local function wide(value)
        local text, index = "", 0
        while value[index] and value[index] ~= 0 do text = text .. string.char(value[index]); index = index + 1 end
        return text
    end
    local function new_handle(kind, name)
        assert(not s.in_tick, "handle open on video timer")
        s.opens, s.handles = s.opens + 1, s.handles + 1
        return {kind = kind, name = name}
    end
    local kernel = {}
    function kernel.CreateMutexW(_, _, name) return new_handle("mutex", wide(name)) end
    function kernel.CreateFileMappingW(_, _, protection, _, size, name)
        equal(protection, 4); equal(size, 98472)
        local text = wide(name)
        s.maps[text] = s.maps[text] or {packet = {magic = "", version = 0}}
        return new_handle("mapping", text)
    end
    function kernel.MapViewOfFile(handle, access, _, _, size)
        assert(not s.in_tick, "map open on video timer")
        equal(access, 4, "FILE_MAP_READ"); equal(size, 98472)
        s.views = s.views + 1; return s.maps[handle.name]
    end
    function kernel.UnmapViewOfFile(_) assert(not s.in_tick); s.views = s.views - 1; return 1 end
    function kernel.CloseHandle(handle)
        assert(not s.in_tick); assert(not handle.closed); handle.closed = true; s.handles = s.handles - 1; return 1
    end
    function kernel.WaitForSingleObject(_, timeout) equal(timeout, 0, "nonblocking mutex"); return s.wait end
    function kernel.ReleaseMutex(_) return s.release_failure and 0 or 1 end
    function kernel.QueryPerformanceCounter(value) value[0] = s.now; return 1 end
    function kernel.QueryPerformanceFrequency(value) value[0] = 1000000000; return 1 end
    local ffi = {os = "Windows"}
    function ffi.typeof(_) return true end
    function ffi.cdef(_) end
    function ffi.sizeof(_) return 168 end
    function ffi.new(kind, _)
        if kind == "lift_native_layout_header_v2[1]" then return {[0] = {}} end
        return {[0] = 0}
    end
    function ffi.load(_) return kernel end
    function ffi.cast(_, value) return value end
    function ffi.copy(destination, source, size) equal(size, 168); destination[0] = copy(source.packet) end
    function ffi.string(value, count) return value:sub(1, count) end

    local obs = {LOG_WARNING = 300, LOG_INFO = 200, OBS_BOUNDS_NONE = 0, OBS_TEXT_DEFAULT = 0}
    local function retain(source) if source then source.refs = source.refs + 1 end; return source end
    local function data(value) s.data_refs = s.data_refs + 1; return copy(value or {}) end
    function obs.obs_get_locale() return "en-US" end
    function obs.script_log(_, message) table.insert(s.logs, message) end
    function obs.obs_source_get_display_name(_) return s.plugin and "Lift Trace native pacing experiment" or nil end
    function obs.obs_frontend_get_current_scene() return retain(s.current) end
    function obs.obs_scene_from_source(source) return source.scene end
    function obs.obs_get_source_by_uuid(uuid) return retain(s.sources[uuid]) end
    function obs.obs_get_source_by_name(name) return retain(s.names[name]) end
    function obs.obs_source_get_uuid(source) return source.uuid end
    function obs.obs_source_get_unversioned_id(source) return source.kind end
    function obs.obs_source_get_width(source) return source.width end
    function obs.obs_source_release(source) source.refs = source.refs - 1; assert(source.refs >= 0) end
    function obs.obs_source_get_settings(source) return data(source.data) end
    function obs.obs_data_create() return data() end
    function obs.obs_data_release(_) s.data_refs = s.data_refs - 1; assert(s.data_refs >= 0) end
    function obs.obs_data_get_string(value, key) return value[key] or "" end
    function obs.obs_data_get_bool(value, key) return value[key] == true end
    function obs.obs_data_get_int(value, key) return value[key] or 0 end
    function obs.obs_data_set_string(value, key, setting) value[key] = setting end
    obs.obs_data_set_int, obs.obs_data_set_bool = obs.obs_data_set_string, obs.obs_data_set_string
    function obs.obs_data_set_default_string(value, key, setting) if value[key] == nil then value[key] = setting end end
    obs.obs_data_set_default_bool = obs.obs_data_set_default_string
    function obs.obs_source_create(kind, name, value, _)
        local source = s:source(name, kind); source.data = copy(value)
        if s.create_failure then source.width = 0 end
        return retain(source)
    end
    function obs.obs_source_update(source, value) for key, setting in pairs(value) do source.data[key] = setting end end
    function obs.obs_scene_enum_items(scene) s.lists = s.lists + 1; local items = {}; for _, item in ipairs(scene.items) do item.refs = item.refs + 1; table.insert(items, item) end; return items end
    function obs.sceneitem_list_release(items) s.lists = s.lists - 1; for _, item in ipairs(items) do item.refs = item.refs - 1; assert(item.refs >= 0) end end
    function obs.obs_sceneitem_addref(item) item.refs = item.refs + 1 end
    function obs.obs_sceneitem_release(item) item.refs = item.refs - 1; assert(item.refs >= 0) end
    function obs.obs_sceneitem_get_source(item) return item.source end
    function obs.obs_sceneitem_get_id(item) return item.id end
    function obs.obs_scene_find_sceneitem_by_id(scene, id) for _, item in ipairs(scene.items) do if item.id == id then return item end end end
    function obs.obs_scene_add(scene, source)
        for _, candidate in pairs(s.sources) do if candidate.scene == scene then return s:item(candidate, source) end end
        error("unknown scene")
    end
    function obs.vec2() return {x = 0, y = 0} end
    function obs.obs_sceneitem_crop() return {} end
    function obs.obs_sceneitem_set_pos(item, position) assert(item.refs > 0, "must retain item during mutation"); s.pos_writes = s.pos_writes + 1; item.x, item.y = position.x, position.y end
    function obs.obs_sceneitem_set_visible(item, visible) assert(not s.in_tick); s.visibility_writes = s.visibility_writes + 1; item.visible = visible end
    local function transform(field)
        return function(item, value) assert(not s.in_tick, "transform reset on timer"); s.reset_writes = s.reset_writes + 1; item[field] = copy(value) end
    end
    obs.obs_sceneitem_set_alignment, obs.obs_sceneitem_set_bounds_type = transform("alignment"), transform("bounds")
    obs.obs_sceneitem_set_crop, obs.obs_sceneitem_set_scale, obs.obs_sceneitem_set_rot = transform("crop"), transform("scale"), transform("rotation")
    function obs.obs_properties_create() return {} end
    function obs.obs_properties_add_text(props, key, label, _) props[key] = label end
    function obs.obs_properties_add_bool(props, key, label) props[key] = label end
    function obs.obs_properties_add_button(props, key, label, callback) props[key] = callback end
    function obs.timer_add(callback, delay) equal(delay, 250); s.timer = callback end
    function obs.timer_remove(callback) if s.timer == callback then s.timer = nil end end
    s.obs = obs
    s.current = s:source("Main", "scene")
    s.settings = {source_name = "Lift Native", native_channel = "test", follow_position = true}
    function s:load()
        local env = setmetatable({obslua = obs, require = function(name) equal(name, "ffi"); return ffi end,
            io = {open = function() error("adapter must not access files") end}}, {__index = _G})
        local chunk = assert(loadfile(adapter_path)); setfenv(chunk, env); chunk()
        env.script_defaults(self.settings); env.script_load(self.settings)
        self.env, self.props = env, env.script_properties()
    end
    function s:add() self.props.add(); return self.current.scene.items[#self.current.scene.items] end
    function s:tick() self.in_tick = true; self.timer(); self.in_tick = false end
    function s:update() self.env.script_update(self.settings) end
    function s:close()
        self.env.script_unload()
        equal(self.handles, 0, "handle leak"); equal(self.views, 0, "view leak")
        equal(self.data_refs, 0, "OBS data leak"); equal(self.lists, 0, "OBS item list leak")
        for _, source in pairs(self.sources) do equal(source.refs, 0, "source reference leak") end
        for _, item in ipairs(self.all_items) do equal(item.refs, 0, "scene item reference leak") end
    end
    s:load()
    return s
end

local function case(name, test)
    local s = fixture()
    local ok, message = pcall(test, s)
    if not ok then error(name .. ": " .. tostring(message)) end
    s:close(); passed = passed + 1
end

case("new source starts hidden with current placement", function(s)
    s:packet(); local item = s:add()
    equal(item.x, 75); equal(item.y, 434); equal(item.visible, false)
    equal(item.source.data.diagnostics, false); equal(item.source.data.live_channel, "test")
    equal(item.alignment, 5); equal(item.scale.x, 1); equal(item.crop.bottom, 0); equal(item.rotation, 0)
end)
case("canonical rounding, sides, offsets and width independence", function(s)
    local p = s:packet(); local item = s:add()
    local cases = {{0, 0, 0, 0, 75, 723}, {500, 1, 0, 0, 1413, 361},
        {999, 0, 3840, -2160, 3915, -2159}, {500, 1, -3840, 2160, -2427, 2521}}
    for _, v in ipairs(cases) do
        p.settings[2], p.flags, p.obs_offset_x, p.obs_offset_y = v[1], v[2], v[3], v[4]
        p.settings[3] = 3840; p.sequence = p.sequence + 1; s:tick()
        equal(item.x, v[5]); equal(item.y, v[6])
    end
end)
case("follow changes position only and never searches current scene", function(s)
    local p = s:packet(); local item = s:add(); item.visible, item.locked = true, false
    item.scale = {x = 2, y = 3}; item.rotation, item.order = 30, 4; item.crop.left = 8
    s.current = s:source("Other", "scene")
    local resets, opens, visibility = s.reset_writes, s.opens, s.visibility_writes
    p.flags, p.sequence = 1, 2; s:tick()
    equal(item.x, 1413); equal(item.scale.x, 2); equal(item.rotation, 30); equal(item.order, 4)
    equal(item.crop.left, 8); equal(item.visible, true); equal(item.locked, false)
    equal(s.reset_writes, resets); equal(s.opens, opens); equal(s.visibility_writes, visibility)
end)
case("disabled follow permits explicit apply only", function(s)
    local p = s:packet(); s.settings.follow_position = false; s:update(); local item = s:add()
    equal(item.x, 75); p.flags = 1; s:tick(); equal(item.x, 75)
    s:add(); equal(item.x, 1413)
end)
case("reenabling follow restores position without resetting transforms", function(s)
    s:packet(); local item = s:add()
    s.settings.follow_position = false; s:update(); item.x, item.y = 250, 400; item.scale.x = 2
    s:tick(); equal(item.x, 250)
    s.settings.follow_position = true; s:update(); s:tick(); equal(item.x, 75); equal(item.y, 434); equal(item.scale.x, 2)
end)
case("cold explicit bind normalizes transform while preserving position and visibility", function(s)
    local source = s:source("Lift Native", "lift_trace_native_pacing")
    local item = s:item(s.current, source); s:add()
    equal(item.x, 11); equal(item.y, 22); equal(item.visible, true)
    equal(item.scale.x, 1); equal(item.alignment, 5); equal(item.crop.top, 0); equal(item.rotation, 0)
    s:packet(); s:tick(); equal(item.x, 75); equal(item.y, 434)
end)
case("producer can start after source and restart a session", function(s)
    local item = s:add(); equal(item.visible, false); equal(item.x, 11)
    local map = s.maps["Local\\LiftTraceNative-test"]
    local p = s:packet(); map.packet = p; s:tick(); equal(item.x, 75)
    p.session, p.sequence, p.flags = 4, 1, 1; s:tick(); equal(item.x, 1413)
end)
case("busy stale future closed invalid snapshots preserve placement", function(s)
    local p = s:packet(); local item = s:add(); p.flags = 1
    local mutations = {
        function() s.wait = 258 end, function() p.qpc_ns = s.now - 1000000001 end,
        function() p.qpc_ns = s.now + 250000001 end, function() p.alive = 0 end,
        function() p.version = 1 end, function() p.size = 8 end, function() p.session = 0 end,
        function() p.sequence = 0 end, function() p.obs_offset_x = 3841 end,
        function() p.obs_offset_y = -2161 end, function() p.settings[2] = 0/0 end,
        function() p.flags = 64 end, function() s.release_failure = true end,
    }
    local good = copy(p)
    for _, mutate in ipairs(mutations) do
        for key in pairs(p) do p[key] = nil end; for key, value in pairs(good) do p[key] = copy(value) end
        s.wait, s.release_failure = 0, false; mutate(); s:tick(); equal(item.x, 75)
    end
end)
case("abandoned mutex quarantine and sequence regression", function(s)
    local p = s:packet(); local item = s:add(); p.flags, p.sequence = 1, 10
    s.wait = 128; s:tick(); s.wait = 0; s:tick(); equal(item.x, 75)
    p.sequence = 11; s:tick(); equal(item.x, 1413)
    p.sequence, p.flags = 9, 0; s:tick(); equal(item.x, 1413)
    p.session, p.sequence = 9, 1; s:tick(); equal(item.x, 75)
end)
case("rename keeps UUID, replacement and reused item ID are rejected", function(s)
    local p = s:packet(); local item = s:add(); item.source.name = "Renamed"
    p.flags = 1; s:tick(); equal(item.x, 1413)
    local replacement = s:source("Lift Native", "lift_trace_native_pacing")
    item.source = replacement; p.flags, p.sequence = 0, 2; s:tick(); equal(item.x, 1413)
end)
case("deleted scene never falls back to same name", function(s)
    local p = s:packet(); local item = s:add(); s.sources[s.current.uuid] = nil
    s.current = s:source("Main", "scene"); p.flags = 1; s:tick(); equal(item.x, 75)
    equal(#s.current.scene.items, 0)
end)
case("channel or source-name property edits cannot retarget", function(s)
    local p = s:packet(); local item = s:add(); p.flags = 1
    s.settings.native_channel = "other"; s:update(); s:tick(); equal(item.x, 75)
    s.settings.native_channel, s.settings.source_name = "test", "Other"; s:update(); s:tick(); equal(item.x, 75)
    s.settings.source_name = "Lift Native"; s:update(); s:tick(); equal(item.x, 1413)
    item.source.data.live_channel = "another"; p.flags = 0; s:tick(); equal(item.x, 1413)
end)
case("wrong kind, channel, plugin or failed create does not change scene", function(s)
    s:packet(); local source = s:source("Lift Native", "browser_source")
    s:add(); equal(#s.current.scene.items, 0)
    source.kind, source.data.live_channel = "lift_trace_native_pacing", "other"
    s:add(); equal(#s.current.scene.items, 0)
    s.names["Lift Native"] = nil; s.plugin = false; s:add(); equal(#s.current.scene.items, 0)
    s.plugin, s.create_failure = true, true; s:add(); equal(#s.current.scene.items, 0)
end)
case("duplicates require an already exact pinned item", function(s)
    s:packet(); local source = s:source("Lift Native", "lift_trace_native_pacing")
    local first = s:item(s.current, source); s:item(s.current, source)
    s:add(); equal(first.x, 11); equal(s.pos_writes, 0)
    table.remove(s.current.scene.items); s:add(); equal(first.x, 75); equal(first.visible, true)
    local duplicate = s:item(s.current, source); s:add(); equal(duplicate.x, 11); equal(first.x, 75)
end)
case("save reload validates and retains exact pin", function(s)
    local p = s:packet(); local item = s:add(); s.env.script_save(s.settings); s:close()
    s:load(); p.flags = 1; s:tick(); equal(item.x, 1413)
    s:close(); item.source = s:source("Replacement", "lift_trace_native_pacing")
    s:load(); p.flags = 0; s:tick(); equal(item.x, 1413)
end)
case("bad channels never create handles or sources", function(s)
    for _, channel in ipairs({"", "space channel", "bad\\path", string.rep("x", 49)}) do
        s.settings.native_channel = channel; s:update(); s:add()
    end
    equal(s.opens, 0); equal(#s.current.scene.items, 0)
end)
NATIVE_LAYOUT_TESTS_PASSED = passed
