cmake_minimum_required(VERSION 3.20)
project(lift_native_pacing LANGUAGES C)

# Developer-only experiment. Supply an OBS SDK matching the test installation.
# Never installs into the user's OBS folder or enters the normal app package.
find_path(OBS_INCLUDE_DIR obs-module.h PATH_SUFFIXES obs REQUIRED)
find_library(OBS_LIBRARY NAMES obs libobs REQUIRED)
add_library(lift-native-pacing MODULE lift-native-pacing.c)
target_compile_features(lift-native-pacing PRIVATE c_std_11)
target_include_directories(lift-native-pacing PRIVATE "${OBS_INCLUDE_DIR}")
target_link_libraries(lift-native-pacing PRIVATE "${OBS_LIBRARY}")
if(WIN32)
  target_link_libraries(lift-native-pacing PRIVATE kernel32)
endif()
set_target_properties(lift-native-pacing PROPERTIES PREFIX "")
add_library(pacing-geometry-test SHARED geometry-test.c)
target_compile_features(pacing-geometry-test PRIVATE c_std_11)
add_library(live-geometry-test SHARED live-geometry-test.c)
target_compile_features(live-geometry-test PRIVATE c_std_11)
