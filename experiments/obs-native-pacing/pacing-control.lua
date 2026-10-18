-- Synthetic comparison controller. Load only in a disposable portable OBS.
local obs = obslua
local lab, scene_source, source, item
local phase, since, index = 'boot', 0, 0
local runs = {{name='browser-a', native=false}, {name='native-a', native=true},
              {name='browser-b', native=false}, {name='native-b', native=true}}
local function now() return obs.os_gettime_ns() / 1e9 end
local function report(state, recording)
    local data = obs.obs_data_create()
    obs.obs_data_set_string(data, 'phase', state)
    obs.obs_data_set_int(data, 'run', index)
    obs.obs_data_set_string(data, 'name', runs[index] and runs[index].name or '')
    if recording then obs.obs_data_set_string(data, 'recording', recording) end
    obs.obs_data_save_json(data, lab .. '/progress.json')
    local file = io.open(lab .. '/events.jsonl', 'a')
    if file then file:write(obs.obs_data_get_json(data):gsub('\n', '') .. '\n'); file:close() end
    obs.obs_data_release(data)
end
local function setphase(value) phase=value; since=now(); report(value) end
local function remove_source()
    if item then obs.obs_sceneitem_remove(item); item=nil end
    if source then obs.obs_source_release(source); source=nil end
end
local function finish(reason)
    obs.timer_remove(tick)
    remove_source()
    report(reason)
end
local function next_run()
    remove_source()
    index=index+1
    if index>#runs then finish('done'); return end
    local run=runs[index]
    local data=obs.obs_data_create()
    local id
    if run.native then
        id='lift_trace_native_pacing'
        local settings=obs.obs_data_create_from_json_file(lab .. '/lift-settings.json')
        if not settings then obs.obs_data_release(data); finish('settings_failed'); return end
        obs.obs_data_set_obj(data,'lift_settings',settings)
        obs.obs_data_release(settings)
    else
        id='browser_source'
        obs.obs_data_set_bool(data,'is_local_file',true)
        obs.obs_data_set_string(data,'local_file',lab .. '/browser.html')
        obs.obs_data_set_int(data,'width',432)
        obs.obs_data_set_int(data,'height',390)
        obs.obs_data_set_bool(data,'fps_custom',true)
        obs.obs_data_set_int(data,'fps',60)
        obs.obs_data_set_bool(data,'shutdown',true)
        obs.obs_data_set_bool(data,'restart_when_active',true)
    end
    source=obs.obs_source_create(id,'Pacing '..run.name,data,nil)
    obs.obs_data_release(data)
    if not source then finish('source_failed'); return end
    item=obs.obs_scene_add(obs.obs_scene_from_source(scene_source),source)
    setphase('warmup')
end
function tick()
    local elapsed=now()-since
    if phase=='boot' and elapsed>=3 then
        if obs.obs_frontend_streaming_active() or obs.obs_frontend_recording_active()
            or obs.obs_frontend_replay_buffer_active() then finish('unexpected_output'); return end
        scene_source=obs.obs_frontend_get_current_scene()
        if not scene_source or obs.obs_source_get_name(scene_source)~='NativePacing' then finish('wrong_scene'); return end
        next_run()
    elseif phase=='warmup' and elapsed>=4 then
        if obs.obs_source_get_width(source)~=432 or obs.obs_source_get_height(source)~=390 then finish('wrong_size'); return end
        obs.obs_frontend_recording_start(); setphase('start_pending')
    elseif phase=='start_pending' then
        if obs.obs_frontend_recording_active() then setphase('recording')
        elseif elapsed>8 then finish('recording_failed') end
    elseif phase=='recording' and elapsed>=24 then
        obs.obs_frontend_recording_stop(); setphase('stop_pending')
    elseif phase=='stop_pending' then
        if not obs.obs_frontend_recording_active() then
            report('result',obs.obs_frontend_get_last_recording()); setphase('between')
        elseif elapsed>8 then finish('stop_failed') end
    elseif phase=='between' and elapsed>=2 then next_run() end
end
function script_description() return 'Disposable native/browser pacing comparison; synthetic input only.' end
function script_load(settings)
    lab=obs.obs_data_get_string(settings,'lab_root')
    if lab=='' then return end
    local marker=io.open(lab .. '/ISOLATED_PACING_LAB','r')
    if not marker then return end
    marker:close(); since=now(); report('boot'); obs.timer_add(tick,100)
end
function script_unload()
    obs.timer_remove(tick); remove_source()
    if scene_source then obs.obs_source_release(scene_source); scene_source=nil end
end
