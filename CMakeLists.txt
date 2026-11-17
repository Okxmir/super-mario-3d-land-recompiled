cmake_minimum_required(VERSION 3.24)
if(POLICY CMP0141)
    cmake_policy(SET CMP0141 NEW)
endif()
set(CMAKE_MSVC_DEBUG_INFORMATION_FORMAT "$<$<CONFIG:Debug,RelWithDebInfo>:Embedded>")
set(CMAKE_TRY_COMPILE_CONFIGURATION Release)
project(SuperMario3DLandRecompiled LANGUAGES C CXX)

if(NOT WIN32 OR NOT CMAKE_SIZEOF_VOID_P EQUAL 8 OR
   (MSVC AND NOT MSVC_CXX_ARCHITECTURE_ID STREQUAL "x64") OR
   (NOT MSVC AND NOT (MINGW AND CMAKE_CXX_COMPILER_ID STREQUAL "Clang")))
    message(FATAL_ERROR "Use the Windows x64 MSVC or LLVM-MinGW toolchain")
endif()

set(CMAKE_C_STANDARD 17)
set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
# Keep standalone builds independent of the player's installed MSVC runtime.
set(CMAKE_MSVC_RUNTIME_LIBRARY "MultiThreaded$<$<CONFIG:Debug>:Debug>")

set(UPSTREAM "${CMAKE_CURRENT_SOURCE_DIR}/build/upstream")
set(RUNTIME "${CMAKE_CURRENT_BINARY_DIR}/runtime")
set(GENERATED "${CMAKE_CURRENT_SOURCE_DIR}/generated/sm3dl-eur")
set(SDL3_DIR "${UPSTREAM}/SDL3-3.4.0/cmake")
find_package(Python3 REQUIRED COMPONENTS Interpreter)
find_package(SDL3 REQUIRED CONFIG COMPONENTS SDL3)
set_property(DIRECTORY APPEND PROPERTY CMAKE_CONFIGURE_DEPENDS tools/prepare_runtime.py)
execute_process(
    COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/tools/prepare_runtime.py"
            "${UPSTREAM}/clockwork-master/runtime" "${RUNTIME}"
    COMMAND_ERROR_IS_FATAL ANY
)

file(GLOB TRANSLATED_CODE CONFIGURE_DEPENDS "${GENERATED}/*.c")
if(NOT TRANSLATED_CODE)
    message(FATAL_ERROR "Prepare the cartridge with scripts/prepare.ps1 before building")
endif()
add_library(game_code OBJECT ${TRANSLATED_CODE})
target_include_directories(game_code PRIVATE "${RUNTIME}/include" "${GENERATED}")
target_compile_definitions(game_code PRIVATE RECOMP_TRACE_CALLS)
option(SM3DL_FAST_BUILD "Disable optimization for shorter iteration builds" ON)
if(MSVC)
    target_compile_options(game_code PRIVATE /bigobj /fp:precise /w
        $<IF:$<BOOL:${SM3DL_FAST_BUILD}>,/Od,/O1>)
else()
    target_compile_options(game_code PRIVATE -ffp-contract=off -fwrapv -w
        $<IF:$<BOOL:${SM3DL_FAST_BUILD}>,-O0,-O1>)
endif()

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
    src/cecd.cpp src/microphone.cpp src/local_mii.cpp ${RUNTIME_FILES})
set_target_properties(SuperMario3DLand PROPERTIES OUTPUT_NAME SuperMario3DLandRecompiled)
target_include_directories(SuperMario3DLand PRIVATE "${RUNTIME}/include" "${RUNTIME}/src" src "${UPSTREAM}/xbyak-df112862583c2d327c1d9782fd28f53aa675f11d")
target_compile_definitions(SuperMario3DLand PRIVATE NOMINMAX _CRT_SECURE_NO_WARNINGS)
target_link_libraries(SuperMario3DLand PRIVATE game_code SDL3::SDL3 ws2_32 bcrypt)
if(MSVC)
    target_compile_options(SuperMario3DLand PRIVATE /W3 /utf-8)
else()
    foreach(target SuperMario3DLand)
        target_compile_definitions(${target} PRIVATE WINVER=0x0A00 _WIN32_WINNT=0x0A00 NTDDI_VERSION=0x0A000002)
        target_link_options(${target} PRIVATE -static -municode)
    endforeach()
    target_link_libraries(SuperMario3DLand PRIVATE comctl32 dwmapi)
endif()
add_custom_command(TARGET SuperMario3DLand POST_BUILD
    COMMAND "${CMAKE_COMMAND}" -E copy_if_different "$<TARGET_FILE:SDL3::SDL3>" "$<TARGET_FILE_DIR:SuperMario3DLand>"
)

enable_testing()
add_test(NAME cartridge_integrity
    COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/tools/verify_extraction.py"
            "${CMAKE_CURRENT_SOURCE_DIR}/extracted/SM3DL-EUR.cxi")



add_test(NAME native_startup_routine
    COMMAND SuperMario3DLand --verify-startup "${CMAKE_CURRENT_SOURCE_DIR}/extracted/SM3DL-EUR.cxi")

add_test(NAME etc1a4_texture_updates COMMAND SuperMario3DLand --verify-textures)
add_test(NAME native_display_colors COMMAND SuperMario3DLand --verify-display-colors)
add_test(NAME gamepad_mapping COMMAND SuperMario3DLand --verify-gamepad)

set(DXC "${UPSTREAM}/dxc-1.8.2505.1/bin/x64/dxc.exe")
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
