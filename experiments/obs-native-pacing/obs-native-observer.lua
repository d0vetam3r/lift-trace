-- SPDX-License-Identifier: MIT
-- Preserve saved script paths/settings and the host script environment.
local implementation = assert(loadfile(script_path() .. "../../native/obs/obs-native-observer.lua"))
setfenv(implementation, getfenv(1))
implementation()
