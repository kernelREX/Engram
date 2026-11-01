# The Engram RED4ext plugin.
#
#   cmake -B build -S . -A x64
#   cmake --build build --config Release
#
# The result is build/Release/Engram.dll, which goes in
# <game>/red4ext/plugins/Engram/Engram.dll alongside the redscript in mod/r6/scripts.
#
# `cmake --install build --config Release` copies both into a game directory, if
# ENGRAM_GAME_DIR is set to one.

cmake_minimum_required(VERSION 3.21)

project(
  Engram
  VERSION 1.0.0
  DESCRIPTION "Carry a Cyberpunk 2077 save to another PC with a code"
  LANGUAGES C CXX
)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

if(NOT WIN32)
  message(FATAL_ERROR "The plugin is a Windows DLL loaded by the game, so it only builds on Windows.")
endif()

# The game loads this DLL into its own process, so it links the runtime statically and
# carries no dependency on a Visual C++ redistributable the player may not have. This has
# to be set before the SDK subproject is added, or the SDK compiles against the dynamic
# runtime and the two will not link.
set(CMAKE_MSVC_RUNTIME_LIBRARY "MultiThreaded$<$<CONFIG:Debug>:Debug>" CACHE STRING "" FORCE)

add_subdirectory(vendor/RED4ext.SDK)

# miniz for the container's zip, nlohmann/json for the manifest and the header. Both are
# vendored so a build needs nothing fetched.
add_library(engram_vendor STATIC vendor/miniz/miniz.c)
target_include_directories(engram_vendor PUBLIC vendor/miniz)
if(MSVC)
  target_compile_options(engram_vendor PRIVATE /W0)
endif()

set(ENGRAM_CORE
  src/Code.cpp
  src/Container.cpp
  src/Crypto.cpp
  src/Http.cpp
  src/Mods.cpp
  src/SaveData.cpp
  src/SaveFolder.cpp
)

add_library(Engram SHARED
  src/Main.cpp
  src/Jobs.cpp
  ${ENGRAM_CORE}
)

target_include_directories(Engram PRIVATE src vendor/json vendor/miniz)
target_link_libraries(Engram PRIVATE engram_vendor)

target_link_libraries(Engram PRIVATE
  RED4ext::SDK
  Shell32      # SHGetKnownFolderPath
  Ole32        # CoTaskMemFree
  Winhttp      # the file hosts
  Bcrypt       # AES-256-GCM, SHA-256 and PBKDF2
  Version      # mod version resources
)

target_compile_definitions(Engram PRIVATE
  WIN32_LEAN_AND_MEAN
  NOMINMAX
  UNICODE
  _UNICODE
)

if(MSVC)
  target_compile_options(Engram PRIVATE /W4 /permissive- /EHsc /utf-8)
endif()

set_target_properties(Engram PROPERTIES
  OUTPUT_NAME "Engram"
  PREFIX ""
)

# A plain exe over the same sources, so the file reading can be checked on this machine
# without starting the game. The RTTI binding still needs Cyberpunk to prove.
add_executable(engram_harness tests/harness.cpp ${ENGRAM_CORE})
target_include_directories(engram_harness PRIVATE src vendor/json vendor/miniz)
target_link_libraries(engram_harness PRIVATE engram_vendor Shell32 Ole32 Bcrypt Winhttp Version)
target_compile_definitions(engram_harness PRIVATE WIN32_LEAN_AND_MEAN NOMINMAX UNICODE _UNICODE)
if(MSVC)
  target_compile_options(engram_harness PRIVATE /W4 /permissive- /EHsc /utf-8)
endif()

if(DEFINED ENGRAM_GAME_DIR)
  install(TARGETS Engram RUNTIME DESTINATION "${ENGRAM_GAME_DIR}/red4ext/plugins/Engram")
  install(DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}/../mod/r6/scripts/Engram/"
          DESTINATION "${ENGRAM_GAME_DIR}/r6/scripts/Engram")
endif()
