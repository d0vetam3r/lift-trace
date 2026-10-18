-- SPDX-License-Identifier: MIT
-- Optional lab recorder. Never load in a production scene collection.
local obs = obslua
local lab, channel, scene_source, source, item
local phase, since = 'boot', 0
local function now() return obs.os_gettime_ns() / 1e9 end
local function report(value, recording)
    phase=value; since=now()
    local data=obs.obs_data_create()
    obs.obs_data_set_string(data,'phase',value)
    obs.obs_data_set_double(data,'qpcSeconds',since)
    if recording then obs.obs_data_set_string(data,'recording',recording) end
    obs.obs_data_save_json(data,lab..'/live-progress.json')
    local file=io.open(lab..'/live-events.jsonl','a')
    if file then file:write(obs.obs_data_get_json(data):gsub('\n','')..'\n'); file:close() end
    obs.obs_data_release(data)
end
local function finish(reason)
    obs.timer_remove(tick)
    report(reason)
end
function tick()
    local elapsed=now()-since
    if phase=='boot' and elapsed>=3 then
        if obs.obs_frontend_streaming_active() or obs.obs_frontend_recording_active()
            or obs.obs_frontend_replay_buffer_active() then finish('unexpected_output'); return end
        scene_source=obs.obs_frontend_get_current_scene()
        if not scene_source or obs.obs_source_get_name(scene_source)~='NativeLive' then finish('wrong_scene'); return end
        local data=obs.obs_data_create()
        obs.obs_data_set_string(data,'live_channel',channel)
        obs.obs_data_set_bool(data,'diagnostics',true)
        source=obs.obs_source_create('lift_trace_native_pacing','Native live test',data,nil)
        obs.obs_data_release(data)
        if not source then finish('source_failed'); return end
        item=obs.obs_scene_add(obs.obs_scene_from_source(scene_source),source)
        report('warmup')
    elseif phase=='warmup' and elapsed>=3 then
        if obs.obs_source_get_width(source)~=432 or obs.obs_source_get_height(source)~=390 then finish('wrong_size'); return end
        obs.obs_frontend_recording_start(); report('start_pending')
    elseif phase=='start_pending' then
        if obs.obs_frontend_recording_active() then report('recording')
        elseif elapsed>8 then finish('recording_failed') end
    elseif phase=='recording' and elapsed>=24 then
        obs.obs_frontend_recording_stop(); report('stop_pending')
    elseif phase=='stop_pending' then
        if not obs.obs_frontend_recording_active() then finish('done'); report('done',obs.obs_frontend_get_last_recording())
        elseif elapsed>8 then finish('stop_failed') end
    end
end
function script_description() return 'Disposable native live-input test recorder; isolated scene and marker required.' end
function script_load(settings)
    lab=obs.obs_data_get_string(settings,'lab_root')
    channel=obs.obs_data_get_string(settings,'live_channel')
    if lab=='' or channel=='' then return end
    local marker=io.open(lab..'/ISOLATED_LIVE_LAB','r')
    if not marker then return end
    marker:close(); report('boot'); obs.timer_add(tick,100)
end
function script_unload()
    obs.timer_remove(tick)
    if item then obs.obs_sceneitem_remove(item) end
    if source then obs.obs_source_release(source) end
    if scene_source then obs.obs_source_release(scene_source) end
end
