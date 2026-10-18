cmake_minimum_required(VERSION 3.20)
project(lift_native_obs LANGUAGES C)

# Optional sidecar plugin: explicit build only, no install() or normal app hook.
find_path(OBS_INCLUDE_DIR obs-module.h PATH_SUFFIXES obs REQUIRED)
find_library(OBS_LIBRARY NAMES obs libobs REQUIRED)
# Keep the deployed module filename and OBS source ID stable.
add_library(lift-native-pacing MODULE lift-native-pacing.c)
target_compile_features(lift-native-pacing PRIVATE c_std_11)
target_include_directories(lift-native-pacing PRIVATE "${OBS_INCLUDE_DIR}")
target_link_libraries(lift-native-pacing PRIVATE "${OBS_LIBRARY}")
if(WIN32)
  target_link_libraries(lift-native-pacing PRIVATE kernel32)
endif()
set_target_properties(lift-native-pacing PROPERTIES PREFIX "")
