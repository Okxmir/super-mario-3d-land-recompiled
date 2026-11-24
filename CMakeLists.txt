cmake_minimum_required(VERSION 3.24)
if(POLICY CMP0141)
    cmake_policy(SET CMP0141 NEW)
endif()
set(CMAKE_MSVC_DEBUG_INFORMATION_FORMAT "$<$<CONFIG:Debug,RelWithDebInfo>:Embedded>")
set(CMAKE_TRY_COMPILE_CONFIGURATION Release)
project(SuperMario3DLandRecompiled LANGUAGES C CXX)

if(WIN32)
    if(NOT CMAKE_SIZEOF_VOID_P EQUAL 8 OR
       (MSVC AND NOT MSVC_CXX_ARCHITECTURE_ID STREQUAL "x64") OR
       (NOT MSVC AND NOT (MINGW AND CMAKE_CXX_COMPILER_ID STREQUAL "Clang")))
        message(FATAL_ERROR "Use the Windows x64 MSVC or LLVM-MinGW toolchain")
    endif()
elseif(NOT CMAKE_SYSTEM_NAME STREQUAL "Linux" OR
       NOT CMAKE_SYSTEM_PROCESSOR STREQUAL "x86_64" OR NOT CMAKE_SIZEOF_VOID_P EQUAL 8)
    message(FATAL_ERROR "Supported hosts are Windows x64 and Linux x86-64")
endif()

set(CMAKE_C_STANDARD 17)
set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
# Keep standalone builds independent of the player's installed MSVC runtime.
set(CMAKE_MSVC_RUNTIME_LIBRARY "MultiThreaded$<$<CONFIG:Debug>:Debug>")

set(UPSTREAM "${CMAKE_CURRENT_SOURCE_DIR}/build/upstream")
set(RUNTIME "${CMAKE_CURRENT_BINARY_DIR}/runtime")
set(GENERATED "${CMAKE_CURRENT_SOURCE_DIR}/generated/sm3dl-eur")
find_package(Python3 REQUIRED COMPONENTS Interpreter)
if(WIN32)
    set(SDL3_DIR "${UPSTREAM}/SDL3-3.4.0/cmake")
    find_package(SDL3 REQUIRED CONFIG COMPONENTS SDL3)
    set(DXC "${UPSTREAM}/dxc-1.8.2505.1/bin/x64/dxc.exe")
else()
    find_package(Threads REQUIRED)
    find_package(OpenSSL REQUIRED COMPONENTS Crypto)
    set(SDL_SHARED OFF)
    set(SDL_STATIC ON)
    set(SDL_TEST_LIBRARY OFF)
    add_subdirectory("${UPSTREAM}/SDL3-3.4.0-linux" "${CMAKE_CURRENT_BINARY_DIR}/sdl" EXCLUDE_FROM_ALL)
    set(DXC "${UPSTREAM}/dxc-linux-1.8.2505.1/bin/dxc")
endif()
set_property(DIRECTORY APPEND PROPERTY CMAKE_CONFIGURE_DEPENDS
    tools/prepare_runtime.py tools/alon_runtime.py tools/display_options.py tools/reserve_runtime.py
    tools/coherent_pica_fast.py tools/coherent_timer.py)
execute_process(
    COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/tools/alon_runtime.py"
            "${UPSTREAM}/clockwork-master/runtime" "${RUNTIME}"
    COMMAND_ERROR_IS_FATAL ANY
)

file(GLOB TRANSLATED_CODE CONFIGURE_DEPENDS "${GENERATED}/*.c")
set(ORIGINAL "${GENERATED}-original")
file(GLOB ORIGINAL_CODE CONFIGURE_DEPENDS "${ORIGINAL}/*.c")
if(NOT TRANSLATED_CODE OR NOT ORIGINAL_CODE OR NOT EXISTS "${GENERATED}/alon_eur_payload.inc")
    message(FATAL_ERROR "Prepare the game with build.cmd on Windows or build.sh on Linux")
endif()
add_library(game_code OBJECT ${TRANSLATED_CODE})
add_library(game_original OBJECT ${ORIGINAL_CODE})
option(SM3DL_FAST_BUILD "Disable optimization for shorter iteration builds" ON)
foreach(mode game_code game_original)
    target_include_directories(${mode} PRIVATE "${RUNTIME}/include")
    target_compile_definitions(${mode} PRIVATE RECOMP_TRACE_CALLS)
    if(MSVC)
        target_compile_options(${mode} PRIVATE /bigobj /fp:precise /w
            $<IF:$<BOOL:${SM3DL_FAST_BUILD}>,/Od,/O1>)
    else()
        target_compile_options(${mode} PRIVATE -ffp-contract=off -fwrapv -w
            $<IF:$<BOOL:${SM3DL_FAST_BUILD}>,-O0,-O1>)
    endif()
endforeach()

set(RUNTIME_FILES
    arm_ops.c
    audio/bcstm.cpp audio/dsp_hle.cpp
    dump.cpp frontend/sdl.cpp frontend/settings.cpp
    hle/apt.cpp hle/cfg.cpp hle/dsp.cpp hle/err.cpp hle/frd.cpp hle/fs.cpp
    hle/gsp.cpp hle/hid.cpp hle/offline.cpp hle/ptm.cpp hle/service.cpp hle/srv.cpp
    hle/stubs.cpp hle/uds.cpp hle/y2r.cpp
    kernel/kernel.cpp kernel/svc.cpp
    level5.cpp loader.cpp log.cpp memory.cpp mods.cpp net/air.cpp net/relay.cpp platform.cpp
    video/gpu/gpu.cpp video/lighting.cpp video/pica.cpp video/raster.cpp video/shader.cpp
    video/texture.cpp video/transfer.cpp video/upscale.cpp video/widescreen.cpp
)
list(TRANSFORM RUNTIME_FILES PREPEND "${RUNTIME}/src/")

add_executable(SuperMario3DLand src/main.cpp src/shared_font.cpp src/save_storage.cpp src/pica_shader_jit.cpp
    src/cecd.cpp src/microphone.cpp src/local_mii.cpp src/apt_wrap.cpp src/hd_texture_pack.cpp src/cityhash64.cpp ${RUNTIME_FILES})
set_target_properties(SuperMario3DLand PROPERTIES OUTPUT_NAME SuperMario3DLandRecompiled)
target_include_directories(SuperMario3DLand PRIVATE "${RUNTIME}/include" "${RUNTIME}/src" "${GENERATED}" src
    "${UPSTREAM}/xbyak-df112862583c2d327c1d9782fd28f53aa675f11d")
target_link_libraries(SuperMario3DLand PRIVATE game_code game_original SDL3::SDL3)
if(WIN32)
    target_compile_definitions(SuperMario3DLand PRIVATE NOMINMAX _CRT_SECURE_NO_WARNINGS)
    target_link_libraries(SuperMario3DLand PRIVATE ws2_32 bcrypt)
    if(MSVC)
        target_compile_options(SuperMario3DLand PRIVATE /W3 /utf-8)
    else()
        target_compile_definitions(SuperMario3DLand PRIVATE WINVER=0x0A00 _WIN32_WINNT=0x0A00 NTDDI_VERSION=0x0A000002)
        target_link_options(SuperMario3DLand PRIVATE -static -municode)
        target_link_libraries(SuperMario3DLand PRIVATE comctl32 dwmapi)
    endif()
    add_custom_command(TARGET SuperMario3DLand POST_BUILD
        COMMAND "${CMAKE_COMMAND}" -E copy_if_different "$<TARGET_FILE:SDL3::SDL3>" "$<TARGET_FILE_DIR:SuperMario3DLand>"
    )
else()
    target_link_libraries(SuperMario3DLand PRIVATE OpenSSL::Crypto Threads::Threads)
endif()

enable_testing()
add_test(NAME cartridge_integrity
    COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/tools/verify_extraction.py"
            "${CMAKE_CURRENT_SOURCE_DIR}/extracted/SM3DL-EUR.cxi")



add_test(NAME native_startup_routine
    COMMAND SuperMario3DLand --verify-startup "${CMAKE_CURRENT_SOURCE_DIR}/extracted/SM3DL-EUR.cxi")
add_test(NAME original_30_fps_startup
    COMMAND SuperMario3DLand --verify-original-startup "${CMAKE_CURRENT_SOURCE_DIR}/extracted/SM3DL-EUR.cxi")
add_test(NAME mouse_idle_timeout COMMAND SuperMario3DLand --verify-mouse-idle)

add_test(NAME etc1a4_texture_updates COMMAND SuperMario3DLand --verify-textures)
add_test(NAME native_display_colors COMMAND SuperMario3DLand --verify-display-colors)
add_test(NAME gamepad_mapping COMMAND SuperMario3DLand --verify-gamepad)
add_test(NAME display_aspect_ratios COMMAND SuperMario3DLand --verify-aspect-ratio)
add_test(NAME mystery_box_applet_wrap COMMAND SuperMario3DLand --verify-apt-wrap)

set(LCD_HEADER "${CMAKE_CURRENT_BINARY_DIR}/sm3dl_lcd.inc")
add_custom_command(OUTPUT "${LCD_HEADER}"
    COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/tools/compile_lcd.py"
            "${DXC}" "${CMAKE_CURRENT_SOURCE_DIR}/src/lcd_blit.hlsl" "${LCD_HEADER}"
    DEPENDS tools/compile_lcd.py src/lcd_blit.hlsl "${DXC}"
    VERBATIM)
target_sources(SuperMario3DLand PRIVATE "${LCD_HEADER}")
foreach(entry estimate screen_motion interpolate)
    set(profile ps_6_0)
    if(entry STREQUAL "screen_motion")
        set(profile vs_6_0)
    endif()
    set(header "${CMAKE_CURRENT_BINARY_DIR}/sm3dl_${entry}.inc")
    add_custom_command(OUTPUT "${header}"
        COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/tools/compile_lcd.py"
                "${DXC}" "${CMAKE_CURRENT_SOURCE_DIR}/src/lcd_interpolation.hlsl" "${header}"
                --entry "${entry}" --symbol "sm3dl_${entry}" --profile "${profile}"
        DEPENDS tools/compile_lcd.py src/lcd_interpolation.hlsl "${DXC}"
        VERBATIM)
    target_sources(SuperMario3DLand PRIVATE "${header}")
endforeach()
target_include_directories(SuperMario3DLand PRIVATE "${CMAKE_CURRENT_BINARY_DIR}")
