"""Build the title-specific frontend from the pinned Clockwork runtime."""

import argparse
import shutil
from pathlib import Path


def between(source, start, end):
    left = source.index(start)
    return source[left:source.index(end, left)]


def edit(path, transform):
    path.write_text(transform(path.read_text(encoding="utf-8")), encoding="utf-8")


def frontend(source):
    source = source.replace('#include <cstdio>', '#include <cstdio>\n#include <cmath>')
    source = source.replace('#include "settings.h"\n',
                            '#include "settings.h"\n#include "course_hud.h"\n#include "course_pause_menu.h"\n'
                            '#include "course_touch.h"\n'
                            '#include "hd_texture_pack.h"\n')
    source = source.replace('int big = s.swap_screens ? 1 : 0, small = 1 - big;',
                            'int big = s.swap_screens && !s.widescreen_layout() ? 1 : 0, small = 1 - big;')
    source = source.replace('s.swap_screens = !s.swap_screens, relayout();',
                            's.toggle_secondary_screen(), relayout();')
    source = source.replace('        layout.update();\n        s.save();',
                            '        layout.update();\n'
                            '        pica::gpu::enable_course_hud(s.widescreen_layout(),\n'
                            '                                     s.widescreen_layout() && !s.picture_in_picture);\n'
                            '        s.save();')
    source = source.replace('    SDL_Texture *shown_gpu[2] = {nullptr, nullptr};',
                            '    SDL_Texture *shown_gpu[2] = {nullptr, nullptr};\n    CoursePauseMenu pause_menu;\n'
                            '    sm3dl::ReserveTap reserve_tap;')
    source = source.replace(
        '            case SDL_EVENT_GAMEPAD_BUTTON_DOWN:\n',
        '            case SDL_EVENT_GAMEPAD_BUTTON_DOWN:\n'
        '                reserve_tap.press(SDL_GamepadButton(e.gbutton.button), pica::course_reserve_ready(), SDL_GetTicks());\n')
    source = source.replace(
        '            current_input = in;',
        '            reserve_tap.apply(in, pica::course_reserve_ready(), SDL_GetTicks());\n'
        '            current_input = in;')
    source = source.replace(
        '            } else if (w == "log") {',
        '''            } else if (w == "pad-up") {
                LOG("control: reserve %s", pica::course_reserve_ready() ? "ready" : "blocked");
                SDL_Event event{};
                event.type = SDL_EVENT_GAMEPAD_BUTTON_DOWN;
                event.gbutton.button = SDL_GAMEPAD_BUTTON_DPAD_UP;
                SDL_PushEvent(&event);
            } else if (w == "log") {''')
    source = source.replace('            if (layout.touch_at(lx, ly, tx, ty)) {',
                            '''            if (pause_menu.panel != pica::gpu::CoursePause::None &&
                    s.widescreen_layout() && !s.picture_in_picture
                    ? pause_menu.touch_at(layout.rect[0], lx, ly, tx, ty)
                    : layout.touch_at(lx, ly, tx, ty)) {''')
    source = source.replace('        SDL_RenderClear(renderer);\n        for (int i : {layout.first, 1 - layout.first}) {',
                            '''        SDL_RenderClear(renderer);
        const auto pause = shown_gpu[0] && s.widescreen_layout() && !s.picture_in_picture
                         ? pica::gpu::course_pause_frame() : pica::gpu::CoursePauseFrame{};
        auto *pause_sprites = pause.sprites ? gpu_texture(pause.sprites, SCREEN_HEIGHT * pica::gpu::COURSE_HUD_SCALE,
                                                         BOTTOM_WIDTH * pica::gpu::COURSE_HUD_SCALE) : nullptr;
        pause_menu.panel = pause_sprites ? pause.panel : pica::gpu::CoursePause::None;
        for (int i : {layout.first, 1 - layout.first}) {''')
    source = source.replace('            SDL_RenderTexture(renderer, t, &src, &layout.rect[i]);', '''            SDL_RenderTexture(renderer, t, &src, &layout.rect[i]);
            if (i == 0 && shown_gpu[0] && s.widescreen_layout() && !s.picture_in_picture) {
                using namespace pica::gpu;
                if (pause_menu.panel != CoursePause::None) {
                    pause_menu.draw(renderer, pause_sprites, layout.rect[0]);
                } else if (auto *frame = course_hud_frame()) {
                    auto *hud = gpu_texture(frame, COURSE_HUD_HEIGHT * COURSE_HUD_SCALE,
                                             COURSE_HUD_WIDTH * COURSE_HUD_SCALE);
                    if (hud) {
                        SDL_SetTextureBlendMode(hud, SDL_BLENDMODE_BLEND_PREMULTIPLIED);
                        // The top row and level label are adjacent in the rotated texture.
                        const auto &screen = layout.rect[0];
                        auto draw_hud = [&](float offset, float width, float left, float center_y) {
                            const SDL_FRect source{0, offset * COURSE_HUD_SCALE, float(hud->w),
                                                   width * COURSE_HUD_SCALE};
                            const SDL_FRect dest{screen.x + left + (width - COURSE_HUD_HEIGHT) / 2.0f,
                                                 screen.y + center_y - width / 2.0f,
                                                 float(COURSE_HUD_HEIGHT), width};
                            SDL_RenderTextureRotated(renderer, hud, &source, &dest, -90.0, nullptr, SDL_FLIP_NONE);
                        };
                        draw_hud(0, COURSE_HUD_ROW_WIDTH, 100, 19);
                        draw_hud(COURSE_HUD_ROW_WIDTH, COURSE_HUD_LABEL_WIDTH,
                                 screen.w - COURSE_HUD_LABEL_WIDTH - 8, screen.h - 21);
                    }
                }
            }''')
    source = source.replace('    float top_width = TOP_WIDTH;',
                            '    float window_top_width = 0; // optional native width of a wider client area\n'
                            '    float top_width = TOP_WIDTH;')
    source = source.replace(
        '        const float W[2] = {top_width, float(BOTTOM_WIDTH)}, H = float(SCREEN_HEIGHT);',
        '''        constexpr float top_widths[] = {float(TOP_WIDTH), SCREEN_HEIGHT * 16.0f / 9.0f,
                                        SCREEN_HEIGHT * 21.0f / 9.0f};
        const float target_width = window_top_width > 0 ? window_top_width
            : top_widths[std::clamp(s.aspect_ratio, 0, 2)];
        const float display_width = std::min(top_width, target_width);
        const float W[2] = {display_width, float(BOTTOM_WIDTH)}, H = float(SCREEN_HEIGHT);''')
    source = source.replace(
        '        src[0] = {0, 0, W[0], H}, src[1] = {0, 0, W[1], H};',
        '        src[0] = {(top_width - W[0]) / 2, 0, W[0], H}, src[1] = {0, 0, W[1], H};')
    source = source.replace(
        'SDL_SetRenderLogicalPresentation(renderer, int(layout.w), int(layout.h), SDL_LOGICAL_PRESENTATION_LETTERBOX);',
        '''SDL_SetRenderLogicalPresentation(renderer, int(std::lround(layout.w * 3)),
                                         int(std::lround(layout.h * 3)), SDL_LOGICAL_PRESENTATION_LETTERBOX);
        // Three canvas units per native pixel represent the 16:9 width exactly.
        SDL_SetRenderScale(renderer, 3.0f, 3.0f);''')
    source = source.replace(
        '                if (e.key.scancode == SDL_SCANCODE_F9) s.single_screen = !s.single_screen, relayout();\n', '')
    source = source.replace('#include "handoff.h"\n', '').replace('#include "launcher.h"\n', '')
    source = source.replace('#include "settings.h"\n',
                            '#include "settings.h"\n#include "presentation_window.h"\n'
                            '#ifdef _WIN32\n#include "resolution_menu.h"\n#endif\n'
                            '#include "virtual_gamepad.h"\n')
    source = source.replace("Input input() {", """int verify_aspect_ratio() {
    static_assert(sm3dl::is_16_by_9(1920, 1080) && sm3dl::is_16_by_9(2560, 1440));
    static_assert(!sm3dl::is_16_by_9(1919, 988) && !sm3dl::is_16_by_9(3440, 1440));
    constexpr auto fitted = sm3dl::fit_16_by_9(1919, 988);
    static_assert(sm3dl::is_16_by_9(fitted.width, fitted.height) &&
                  fitted.width <= 1919 && fitted.height <= 988);
    static_assert(sm3dl::can_extend_16_by_9(1919, 988) &&
                  !sm3dl::can_extend_16_by_9(1920, 1080) && !sm3dl::can_extend_16_by_9(3440, 1440));
    static_assert(sm3dl::top_margin_for_client(1919, 988, 400, 240) == 34);
    auto &s = settings();
    const Settings previous = s;
    s.smart_layout = false;
    s.swap_screens = false;
    s.picture_in_picture = true;
    constexpr int rendered_widths[] = {400, 428, 560};
    constexpr int numerators[] = {5, 16, 7}, denominators[] = {3, 9, 3};
    for (int mode = 0; mode < 3; ++mode) {
        s.aspect_ratio = mode;
        for (bool single : {false, true}) {
            s.single_screen = single;
            Layout layout;
            layout.top_width = float(rendered_widths[mode]);
            layout.update();
            const auto &top = layout.rect[0];
            const auto &crop = layout.src[0];
            if (std::fabs(top.w * denominators[mode] - top.h * numerators[mode]) > 0.001f ||
                std::fabs(crop.w - top.w) > 0.001f || crop.x < 0 ||
                std::fabs(2 * crop.x + crop.w - layout.top_width) > 0.001f)
                fatal("Incorrect aspect ratio or nonuniform scaling for mode %d", mode);
            const auto &bottom = layout.rect[1];
            float tx, ty;
            if (!layout.touch_at(bottom.x + bottom.w * 0.25f, bottom.y + bottom.h * 0.75f, tx, ty) ||
                std::fabs(tx - 80.0f) > 0.001f || std::fabs(ty - 180.0f) > 0.001f)
                fatal("Touchscreen coordinates changed for aspect ratio %d", mode);
            if (single && mode == 1 &&
                std::lround(layout.w * 3) * 9 != std::lround(layout.h * 3) * 16)
                fatal("The 16:9 presentation canvas is not exact");
            if (single) {
                const CoursePauseMenu menu{pica::gpu::CoursePause::Buttons};
                const auto pause = menu.destination(top);
                if (std::fabs(pause.x + pause.w / 2 - (top.x + top.w / 2)) > 0.001f ||
                    std::fabs(pause.y + pause.h / 2 - (top.y + top.h / 2)) > 0.001f ||
                    menu.touch_at(top, pause.x - 1, pause.y + pause.h / 2, tx, ty))
                    fatal("The pause panel is misaligned for aspect ratio %d", mode);
                for (float row : {75.0f, 136.0f, 197.0f}) {
                    const float y = pause.y + (row - menu.source().y) * menu.scale();
                    if (!menu.touch_at(top, pause.x + pause.w / 2, y, tx, ty) ||
                        std::fabs(tx - 160.0f) > 0.001f || std::fabs(ty - row) > 0.001f)
                        fatal("Pause button touch coordinates are incorrect for aspect ratio %d", mode);
                }
            }
        }
    }
    s.single_screen = false;
    s.swap_screens = true;
    s.smart_layout = true;
    s.picture_in_picture = false;
    s.aspect_ratio = 1;
    s.toggle_screen_layout();
    Layout selected;
    selected.top_width = 428.0f;
    selected.update();
    if (!s.widescreen_layout() || s.swap_screens || s.picture_in_picture ||
        selected.first != 0 || !selected.shown[0] || selected.shown[1])
        fatal("F9 did not select the upper screen on its own");
    s.toggle_secondary_screen();
    selected.update();
    const auto &inset = selected.rect[1];
    float tx, ty;
    if (selected.first != 0 || !selected.shown[0] || !selected.shown[1] ||
        std::fabs(inset.x + inset.w - (selected.w - 4)) > 0.001f ||
        std::fabs(inset.y + inset.h - (selected.h - 4)) > 0.001f ||
        !selected.touch_at(inset.x + inset.w / 2, inset.y + inset.h / 2, tx, ty) ||
        std::fabs(tx - 160.0f) > 0.001f || std::fabs(ty - 120.0f) > 0.001f)
        fatal("Tab/R3 did not show an interactive lower-right touchscreen inset");
    s.toggle_secondary_screen();
    selected.update();
    if (selected.first != 0 || selected.shown[1])
        fatal("Tab/R3 did not restore the upper screen on its own");
    s.toggle_screen_layout();
    selected.update();
    if (s.single_screen || selected.h != 2 * SCREEN_HEIGHT)
        fatal("F9 did not restore the two stacked screens");
    s = previous;
    std::puts("Exact display ratios, centered overscan crop and touchscreen mapping verified.");
    return 0;
}

int verify_gamepad() {
    SDL_SetHint(SDL_HINT_JOYSTICK_ALLOW_BACKGROUND_EVENTS, "1");
    if (!SDL_Init(SDL_INIT_GAMEPAD)) fatal("Gamepad initialization failed: %s", SDL_GetError());
    {
        VirtualGamepad device;
        if (!device) fatal("Cannot create the virtual gamepad: %s", SDL_GetError());
        SDL_Gamepad *gamepad = SDL_OpenGamepad(device.instance());
        if (!gamepad) fatal("Cannot open the virtual gamepad: %s", SDL_GetError());
        if (!device.button(SDL_GAMEPAD_BUTTON_EAST, true) ||
            !device.button(SDL_GAMEPAD_BUTTON_SOUTH, true) ||
            !device.button(SDL_GAMEPAD_BUTTON_START, true) ||
            !device.axis(SDL_GAMEPAD_AXIS_LEFTX, 32767) ||
            !device.axis(SDL_GAMEPAD_AXIS_LEFTY, -32767)) {
            fatal("Cannot set virtual gamepad input: %s", SDL_GetError());
        }
        SDL_UpdateJoysticks();
        int16_t x = 0, y = 0;
        const uint32_t buttons = gamepad_buttons(gamepad, x, y);
        if (buttons != (BTN_A | BTN_B | BTN_START) || x != CIRCLE_MAX || y != CIRCLE_MAX)
            fatal("3DS gamepad mapping mismatch: buttons %08x, stick %d/%d", buttons, x, y);
        if (!device.button(SDL_GAMEPAD_BUTTON_DPAD_UP, true)) fatal("Cannot press D-pad Up");
        SDL_PumpEvents();
        SDL_Event event;
        sm3dl::ReserveTap reserve;
        while (SDL_PollEvent(&event)) {
            if (event.type == SDL_EVENT_GAMEPAD_BUTTON_DOWN && event.gbutton.which == device.instance())
                reserve.press(SDL_GamepadButton(event.gbutton.button), true, 1000);
        }
        Input touch;
        reserve.apply(touch, true, 1050);
        if (!touch.touching || touch.touch_x != sm3dl::reserve_x || touch.touch_y != sm3dl::reserve_y)
            fatal("D-pad Up did not tap the reserve slot");
        touch = {};
        reserve.apply(touch, true, 1110);
        if (touch.touching) fatal("Reserve tap remained pressed");
        reserve.press(SDL_GAMEPAD_BUTTON_DPAD_UP, false, 1200);
        reserve.apply(touch, true, 1250);
        if (touch.touching) fatal("Menu input triggered an item tap");
        SDL_CloseGamepad(gamepad);
    }
    SDL_Quit();
    std::puts("SDL gamepad buttons and left stick reached the 3DS input mapping.");
    return 0;
}

Input input() {""")
    source = source.replace(between(source, "bool hand_off_or_explain", "void run(void (*start)"), "")
    source = source.replace("const char *cli_dump, bool force_launcher, bool play", "const char *cli_dump")
    source = source.replace(
        "SDL_WINDOW_RESIZABLE | SDL_WINDOW_HIGH_PIXEL_DENSITY);",
        "SDL_WINDOW_RESIZABLE | SDL_WINDOW_HIGH_PIXEL_DENSITY |\n"
        "                                          (std::getenv(\"SM3DL_TEST_HIDDEN\") ? SDL_WINDOW_HIDDEN : 0));")
    source = source.replace("    SDL_RaiseWindow(window);",
                            "    if (!std::getenv(\"SM3DL_TEST_HIDDEN\")) SDL_RaiseWindow(window);")
    source = source.replace(
        '        if (std::string problem; !hand_off_or_explain(cli_dump, &problem)) fatal("%s", problem.c_str());\n',
        "",
    )
    source = source.replace(between(source, "    // the launcher, unless", "    if (device && !pica::gpu::init"),
                            '    game_path = s.game_path;\n    const std::string game_id = "sm3dl";\n')
    source = source.replace(
        """        auto absolute = std::filesystem::absolute(cli_dump, ec);
        s.game_path = ec ? cli_dump : absolute.string();""",
        """        const auto absolute = std::filesystem::absolute(std::filesystem::u8path(cli_dump), ec);
        const auto utf8 = absolute.u8string();
        s.game_path = ec ? cli_dump : std::string(utf8.begin(), utf8.end());""")
    source = source.replace('SDL_SetAppMetadata("Clockwork", nullptr, "io.github.yw2recomp")',
                            'SDL_SetAppMetadata("Super Mario 3D Land recompiled", nullptr, "local.sm3dl.native")')
    source = source.replace('"Clockwork - Yo-kai Watch 2"', '"Super Mario 3D Land recompiled"')
    source = source.replace('"Clockwork: Yo-kai Watch 2 stopped"', '"Super Mario 3D Land recompiled"')
    source = source.replace('    if (!window) fatal("cannot create window: %s", SDL_GetError());',
                            '    if (!window) fatal("cannot create window: %s", SDL_GetError());\n'
                            '    SDL_RaiseWindow(window);')
    source = source.replace(
        "    SDL_SetWindowFullscreen(window, s.fullscreen); // the game's own choice, whatever the launcher was",
        "    if (s.fullscreen) SDL_SetWindowFullscreen(window, true);\n"
        "#ifdef _WIN32\n"
        "    ResolutionMenu resolution_menu(window, s);\n"
        "    resolution_menu.set_visible(!(SDL_GetWindowFlags(window) & SDL_WINDOW_FULLSCREEN));\n"
        "#endif\n"
        "    SDL_RaiseWindow(window);")
    source = source.replace(
        """                    s.fullscreen = !(SDL_GetWindowFlags(window) & SDL_WINDOW_FULLSCREEN);
                    SDL_SetWindowFullscreen(window, s.fullscreen);
                    s.save();""",
        """                    set_fullscreen(!(SDL_GetWindowFlags(window) & SDL_WINDOW_FULLSCREEN));
                    if (!s.fullscreen) first_layout = true, relayout();""")
    source = source.replace("    pica::set_resolution_scale(s.resolution);",
                            "    pica::set_resolution_scale(s.resolution);\n"
                            "    if (pica::gpu::active()) pica::gpu::set_hd_textures(s.hd_textures);\n"
                            '    LOG("graphics: resolution %dx", std::clamp(s.resolution, 1, 4));')
    source = source.replace("    pica::set_widescreen(s.widescreen);",
                            "    pica::set_aspect_ratio(pica::gpu::active() ? s.aspect_ratio : 0);")
    source = source.replace("e.key.scancode == SDL_SCANCODE_F7)",
                            "e.key.scancode == SDL_SCANCODE_F7 && pica::gpu::active())")
    source = source.replace("    pica::set_camera_zoom(float(s.camera_zoom) / 100.0f);",
                            "    pica::set_camera_zoom(1.0f);")
    source = source.replace("                    s.widescreen = !s.widescreen;",
                            "                    s.aspect_ratio = (s.aspect_ratio + 1) % 3;\n"
                            "                    s.widescreen = s.aspect_ratio != 0;")
    source = source.replace(
        '                    pica::set_aspect_ratio(pica::gpu::active() ? s.aspect_ratio : 0);\n                    s.save();',
        '                    relayout();')
    # This title draws both LCDs into 400-row targets. The generic HUD
    # heuristic treats parts of the lower LCD as top-screen overlays.
    source = source.replace("    pica::set_hud_scale(float(s.hud_size) / 100.0f);\n", "")
    source = source.replace(
        '    if (const char *e = std::getenv("YW2_HUD")) pica::set_hud_scale(float(std::atoi(e)) / 100.0f);\n', "")
    source = source.replace("    pica::set_frame_interpolation(s.frame_interpolation);\n", "")
    source = source.replace(
        '    if (const char *e = std::getenv("YW2_INTERP")) pica::set_frame_interpolation(std::atoi(e) != 0);\n', "")
    source = source.replace(
        "void present_gpu(int screen, SDL_GPUTexture *texture, int width, int height) {\n    if (screen == 0) {",
        """void present_gpu(int screen, SDL_GPUTexture *texture, int width, int height) {
    static int logged_width[2]{}, logged_height[2]{};
    static const bool log_resolution = std::getenv("SM3DL_FPS") != nullptr;
    if (log_resolution && (width != logged_width[screen] || height != logged_height[screen])) {
        LOG("graphics: Vulkan %s LCD %dx%d", screen == 0 ? "top" : "bottom", width, height);
        logged_width[screen] = width, logged_height[screen] = height;
    }
    if (screen == 0) {""")
    source = source.replace("    fatal_hook = show_fatal;",
                            '    if (!std::getenv("SM3DL_NO_DIALOG")) fatal_hook = show_fatal;')
    source = source.replace(
        "            SDL_SetBooleanProperty(props, SDL_PROP_GPU_DEVICE_CREATE_SHADERS_SPIRV_BOOLEAN, true);",
        "            SDL_SetBooleanProperty(props, SDL_PROP_GPU_DEVICE_CREATE_SHADERS_SPIRV_BOOLEAN, true);\n"
        "            SDL_SetBooleanProperty(props, SDL_PROP_GPU_DEVICE_CREATE_DEBUGMODE_BOOLEAN, false);\n"
        "#ifdef __linux__\n"
        "            SDL_SetBooleanProperty(props, SDL_PROP_GPU_DEVICE_CREATE_VULKAN_REQUIRE_HARDWARE_ACCELERATION_BOOLEAN, true);\n"
        "#endif")
    source = source.replace(
        "    if (!SDL_Init(SDL_INIT_VIDEO | SDL_INIT_GAMEPAD | SDL_INIT_AUDIO)) {",
        """#ifdef _WIN32
    // SDL's HIDAPI scan can block on the standard USB DualSense.
    // Leave that device to Windows and keep HIDAPI available for other controllers.
    SDL_SetHintWithPriority(SDL_HINT_HIDAPI_IGNORE_DEVICES, "0x054c/0x0ce6", SDL_HINT_DEFAULT);
#endif
    if (!SDL_Init(SDL_INIT_VIDEO | SDL_INIT_AUDIO)) {""",
    )
    source = source.replace(
        "    if (SDL_JoystickID *ids = SDL_GetGamepads(&count)) {",
        """    if (!SDL_InitSubSystem(SDL_INIT_GAMEPAD))
        LOG("gamepad initialization failed: %s", SDL_GetError());
    if (SDL_JoystickID *ids = SDL_GetGamepads(&count)) {""",
    )
    source = source.replace(
        "    std::vector<SDL_Gamepad *> pads;",
        """    std::vector<SDL_Gamepad *> pads;
    auto open_gamepad = [&](SDL_JoystickID id) {
        if (SDL_Gamepad *pad = SDL_OpenGamepad(id)) {
            pads.push_back(pad);
            const char *name = SDL_GetGamepadName(pad);
            LOG("gamepad connected: %s", name ? name : "Unknown controller");
        }
    };""",
    )
    source = source.replace(
        "            if (SDL_Gamepad *g = SDL_OpenGamepad(ids[j])) pads.push_back(g);",
        "            open_gamepad(ids[j]);",
    ).replace(
        "                    if (SDL_Gamepad *g = SDL_OpenGamepad(e.gdevice.which)) pads.push_back(g);",
        "                    open_gamepad(e.gdevice.which);",
    )
    source = source.replace(
        "constexpr int CIRCLE_MAX = 156;",
        """constexpr int CIRCLE_MAX = 156;

// SDL 3.4.0 can log a lost Vulkan swapchain and still return true from SDL_RenderPresent.
std::atomic<bool> vulkan_device_lost{false};
SDL_LogOutputFunction previous_sdl_log = nullptr;
void *previous_sdl_log_data = nullptr;

void SDLCALL capture_sdl_log(void *, int category, SDL_LogPriority priority, const char *message) {
    if (category == SDL_LOG_CATEGORY_RENDER && priority >= SDL_LOG_PRIORITY_ERROR &&
        std::strstr(message, "VK_ERROR_DEVICE_LOST"))
        vulkan_device_lost.store(true, std::memory_order_relaxed);
    if (previous_sdl_log) previous_sdl_log(previous_sdl_log_data, category, priority, message);
}""",
    )
    source = source.replace(
        '    SDL_SetAppMetadata(',
        """    SDL_GetLogOutputFunction(&previous_sdl_log, &previous_sdl_log_data);
    SDL_SetLogOutputFunction(capture_sdl_log, nullptr);
    SDL_SetAppMetadata(""",
        1,
    )
    source = source.replace(
        """        if (!renderer && !(renderer = SDL_CreateRenderer(window, nullptr)))
            fatal("cannot create a renderer: %s", SDL_GetError());""",
        """        // Check Vulkan presentation while only the window exists so a
        // startup failure can switch renderers before any game state is created.
        if (device && (!SDL_RenderClear(renderer) || !SDL_RenderPresent(renderer) ||
                       vulkan_device_lost.load(std::memory_order_relaxed))) {
            LOG("Vulkan startup presentation failed: %s; trying the fallback renderer",
                vulkan_device_lost.load(std::memory_order_relaxed) ? "VK_ERROR_DEVICE_LOST" : SDL_GetError());
            SDL_DestroyRenderer(renderer);
            SDL_DestroyGPUDevice(device);
            renderer = nullptr;
            device = nullptr;
        }
#ifdef _WIN32
        if (!renderer) renderer = SDL_CreateRenderer(window, "direct3d11");
#endif
        if (!renderer && !(renderer = SDL_CreateRenderer(window, "software")))
            fatal("cannot create a fallback renderer: %s", SDL_GetError());""",
    )
    source = source.replace(
        '    LOG("window: %s renderer, %.2fx scale", SDL_GetRendererName(renderer), double(scale));',
        '''    const SDL_DisplayMode *display = SDL_GetCurrentDisplayMode(SDL_GetDisplayForWindow(window));
    LOG("window: %s renderer, %.2fx scale, %.2f Hz", SDL_GetRendererName(renderer), double(scale),
        display ? double(display->refresh_rate) : 0.0);
    const bool log_presentation = std::getenv("SM3DL_FPS") != nullptr;
    uint64_t presentation_since = SDL_GetTicksNS();
    uint64_t longest_present = 0;
    unsigned presentations = 0;''',
    )
    source = source.replace("#include <atomic>\n", "#include <atomic>\n#include <chrono>\n#include <condition_variable>\n")
    source = source.replace("std::mutex frame_lock;",
                            """std::mutex frame_lock;
std::condition_variable frame_ready;
bool lcd_present_pending = false;
std::vector<SDL_GPUTexture *> retired_gpu_frames;""")
    source = source.replace(
        "// a dump this executable can't play: hand it to the one that can, or say why not (false)",
        """void finish_scanout(const std::vector<SDL_GPUTexture *> &retired) {
    {
        std::lock_guard lk(frame_lock);
        retired_gpu_frames.insert(retired_gpu_frames.end(), retired.begin(), retired.end());
        lcd_present_pending = frame_dirty[0] || frame_dirty[1] || !retired_gpu_frames.empty();
    }
    frame_ready.notify_one();
}""")
    source = source.replace(
        "    auto show_message = [&](std::string text) { message = std::move(text), message_until = SDL_GetTicks() + 2500; };",
        """    bool redraw_requested = true;
    bool first_layout = true;
    bool overlay_was_visible = false;
    auto show_message = [&](std::string text) {
        message = std::move(text);
        message_until = SDL_GetTicks() + 2500;
        redraw_requested = true;
    };""")
    source = source.replace("    auto relayout = [&] {\n", """    // Keep the window chrome. Widen the 3D camera to the wider client area
    // instead of forcing fullscreen or scaling the 16:9 frame nonuniformly.
    auto top_screen_16_by_9 = [&] {
        return pica::gpu::active() && s.widescreen_layout() && s.aspect_ratio == 1;
    };
    bool restore_after_fullscreen = false;
    auto set_fullscreen = [&](bool enabled) {
        if (enabled) restore_after_fullscreen = (SDL_GetWindowFlags(window) & SDL_WINDOW_MAXIMIZED) != 0;
#ifdef _WIN32
        if (enabled) resolution_menu.set_visible(false);
#endif
        if (!SDL_SetWindowFullscreen(window, enabled)) LOG("window: fullscreen change failed: %s", SDL_GetError());
        s.fullscreen = (SDL_GetWindowFlags(window) & SDL_WINDOW_FULLSCREEN) != 0;
        if (!s.fullscreen && restore_after_fullscreen) {
            restore_after_fullscreen = false;
            SDL_RestoreWindow(window);
        }
#ifdef _WIN32
        resolution_menu.set_visible(!s.fullscreen);
#endif
        redraw_requested = true;
        s.save();
    };
    bool locked_16_by_9 = false;
    auto relayout = [&] {
        redraw_requested = true;
        const bool lock_ratio = top_screen_16_by_9();
        const bool changed_lock = lock_ratio != locked_16_by_9;
        if (changed_lock) {
            const float ratio = lock_ratio ? sm3dl::widescreen_aspect : 0.0f;
            SDL_SetWindowAspectRatio(window, ratio, ratio);
            locked_16_by_9 = lock_ratio;
        }
        const auto flags = SDL_GetWindowFlags(window);
        int client_w = 0, client_h = 0;
        const bool fill_window = lock_ratio && (flags & SDL_WINDOW_MAXIMIZED) && !(flags & SDL_WINDOW_FULLSCREEN) &&
            SDL_GetRenderOutputSize(renderer, &client_w, &client_h) && sm3dl::can_extend_16_by_9(client_w, client_h);
        layout.window_top_width = fill_window ? float(double(client_w) * SCREEN_HEIGHT / client_h) : 0;
        if (fill_window)
            pica::set_window_top_margin(sm3dl::top_margin_for_client(client_w, client_h, TOP_WIDTH, SCREEN_HEIGHT));
        else
            pica::set_aspect_ratio(pica::gpu::active() ? s.aspect_ratio : 0);
""")
    source = source.replace("        float old_h = layout.h;", "        float old_w = layout.w, old_h = layout.h;")
    source = source.replace(
        "if (old_h != layout.h && !(SDL_GetWindowFlags(window) & SDL_WINDOW_FULLSCREEN))",
        "if ((first_layout || changed_lock || old_w != layout.w || old_h != layout.h) &&\n"
        "            !(SDL_GetWindowFlags(window) & (SDL_WINDOW_FULLSCREEN | SDL_WINDOW_MAXIMIZED)))")
    source = source.replace(
        "SDL_SetWindowSize(window, ww, int(float(ww) * layout.h / layout.w));",
        """if (lock_ratio) {
                SDL_Rect usable{};
                int top = 0, left = 0, bottom = 0, right = 0;
                SDL_GetWindowBordersSize(window, &top, &left, &bottom, &right);
                const bool have_bounds = SDL_GetDisplayUsableBounds(SDL_GetDisplayForWindow(window), &usable);
                const auto size = sm3dl::fit_16_by_9(have_bounds ? std::min(ww, usable.w - left - right) : ww,
                                                    have_bounds ? usable.h - top - bottom : ww);
                SDL_SetWindowSize(window, size.width, size.height);
            } else {
                SDL_SetWindowSize(window, ww, int(std::lround(float(ww) * layout.h / layout.w)));
            }""")
    source = source.replace("    };\n    relayout();", "        first_layout = false;\n    };\n    relayout();")
    source = source.replace(
        '''        SDL_SetRenderLogicalPresentation(renderer, int(std::lround(layout.w * 3)),
                                         int(std::lround(layout.h * 3)), SDL_LOGICAL_PRESENTATION_LETTERBOX);
        // Three canvas units per native pixel represent the 16:9 width exactly.
        SDL_SetRenderScale(renderer, 3.0f, 3.0f);''',
        '''        if (fill_window && layout.w == layout.window_top_width && layout.h == SCREEN_HEIGHT) {
            // Match the drawable exactly, using one scale in both dimensions.
            SDL_SetRenderLogicalPresentation(renderer, client_w, client_h, SDL_LOGICAL_PRESENTATION_LETTERBOX);
            const float pixel_scale = float(client_h) / SCREEN_HEIGHT;
            SDL_SetRenderScale(renderer, pixel_scale, pixel_scale);
        } else {
            SDL_SetRenderLogicalPresentation(renderer, int(std::lround(layout.w * 3)),
                                             int(std::lround(layout.h * 3)), SDL_LOGICAL_PRESENTATION_LETTERBOX);
            SDL_SetRenderScale(renderer, 3.0f, 3.0f);
        }''')
    source = source.replace(
        "        while (SDL_PollEvent(&e)) {\n",
        """        while (SDL_PollEvent(&e)) {
#ifdef _WIN32
            if (e.type == ResolutionMenu::layout_toggle_event()) {
                s.toggle_screen_layout();
                relayout();
                continue;
            }
            if (e.type == ResolutionMenu::aspect_changed_event()) {
                relayout();
                continue;
            }
#else
            if (e.type == SDL_EVENT_KEY_DOWN && !e.key.repeat && e.key.scancode == SDL_SCANCODE_F10 &&
                e.key.mod & SDL_KMOD_CTRL && pica::gpu::active() && sm3dl::has_hd_texture_pack()) {
                s.hd_textures = !s.hd_textures;
                pica::gpu::set_hd_textures(s.hd_textures);
                s.save();
                show_message(s.hd_textures ? "HD on" : "HD off");
                continue;
            }
            if (e.type == SDL_EVENT_KEY_DOWN && !e.key.repeat && e.key.scancode == SDL_SCANCODE_F4 &&
                pica::gpu::active()) {
                s.resolution = s.resolution == 1 ? 2 : s.resolution == 2 ? 4 : 1;
                pica::set_resolution_scale(s.resolution);
                s.save();
                show_message(std::to_string(s.resolution) + "x");
                continue;
            }
#endif
            if (top_screen_16_by_9() &&
                (e.type == SDL_EVENT_WINDOW_MAXIMIZED || e.type == SDL_EVENT_WINDOW_RESIZED ||
                 e.type == SDL_EVENT_WINDOW_PIXEL_SIZE_CHANGED) &&
                (SDL_GetWindowFlags(window) & SDL_WINDOW_MAXIMIZED))
                relayout();
            if ((e.type == SDL_EVENT_WINDOW_LEAVE_FULLSCREEN || e.type == SDL_EVENT_WINDOW_RESTORED) &&
                top_screen_16_by_9() && !(SDL_GetWindowFlags(window) & (SDL_WINDOW_FULLSCREEN | SDL_WINDOW_MAXIMIZED))) {
                first_layout = true;
                relayout();
            }
            if (e.type == SDL_EVENT_KEY_DOWN && !e.key.repeat && e.key.scancode == SDL_SCANCODE_F9) {
                s.toggle_screen_layout();
                relayout();
                continue;
            }
            if ((e.type >= SDL_EVENT_WINDOW_FIRST && e.type <= SDL_EVENT_WINDOW_LAST) ||
                e.type == SDL_EVENT_RENDER_TARGETS_RESET)
                redraw_requested = true;
""")
    source = source.replace(
        """        {
            std::lock_guard lk(frame_lock);
            for (int i = 0; i < 2; i++) {""",
        """        const bool show_overlay = !message.empty() && SDL_GetTicks() < message_until;
        {
            std::unique_lock lk(frame_lock);
            if (!lcd_present_pending && !redraw_requested && show_overlay == overlay_was_visible) {
                // Wake on the guest's next scanout. Revisit input and window events even when it is idle.
                frame_ready.wait_for(lk, std::chrono::milliseconds(4), [] { return lcd_present_pending; });
                continue;
            }
            lcd_present_pending = false;
            redraw_requested = false;
            overlay_was_visible = show_overlay;
            // The display thread owns the SDL wrappers. Remove them before releasing
            // the GPU textures they wrap, after the previous window frame was submitted.
            for (auto *texture : retired_gpu_frames) {
                auto it = wrapped.find(texture);
                for (int i = 0; i < 2; ++i) {
                    if (gpu_frame[i] == texture) {
                        gpu_frame[i] = nullptr;
                        frame_dirty[i] = false;
                    }
                    if (it != wrapped.end() && shown_gpu[i] == it->second.tex)
                        shown_gpu[i] = nullptr;
                }
                if (it != wrapped.end()) {
                    if (it->second.tex) SDL_DestroyTexture(it->second.tex);
                    wrapped.erase(it);
                }
                SDL_ReleaseGPUTexture(device, texture);
            }
            retired_gpu_frames.clear();
            for (int i = 0; i < 2; i++) {""")
    source = source.replace("        if (!message.empty() && SDL_GetTicks() < message_until) {",
                            "        if (show_overlay) {")
    source = source.replace(
        "        SDL_RenderPresent(renderer); // paced by vsync",
        """        const uint64_t present_start = log_presentation ? SDL_GetTicksNS() : 0;
        const bool presented = SDL_RenderPresent(renderer);
        if (log_presentation) {
            const uint64_t now = SDL_GetTicksNS();
            longest_present = std::max(longest_present, now - present_start);
            presentations += presented;
            const uint64_t elapsed = now - presentation_since;
            if (elapsed >= 5 * SDL_NS_PER_SECOND) {
                LOG("presentation: %.1f/s, longest call %.2f ms",
                    double(presentations) * SDL_NS_PER_SECOND / double(elapsed),
                    double(longest_present) / SDL_NS_PER_MS);
                presentation_since = now;
                longest_present = 0;
                presentations = 0;
            }
        }
        if (device && (vulkan_device_lost.load(std::memory_order_relaxed) ||
                       (!presented && std::strstr(SDL_GetError(), "VK_ERROR_DEVICE_LOST"))))
            fatal("Vulkan device lost during presentation (VK_ERROR_DEVICE_LOST). "
                  "Set gpu_renderer=0 in userdata/settings.ini to use the fallback renderer.");""",
    )
    return source


def platform(source):
    source = source.replace('#include "log.h"', '#include "log.h"\n#include <SDL3/SDL.h>')
    return source.replace(
        between(source, "        std::filesystem::path base;", "        std::filesystem::create_directories(d);"),
        '''        const char *override_path = std::getenv("SM3DL_DATA_DIR");
        const char *base = SDL_GetBasePath();
        if ((!override_path || !*override_path) && !base) fatal("could not find the executable directory");
        auto d = override_path && *override_path ? std::filesystem::path(override_path)
                                                 : std::filesystem::u8path(base) / "userdata";
''',
    ).replace('"YW2_STATE_DIR"', '"SM3DL_SAVE_DIR"')


def filesystem(source):
    source = source.replace("    bool romfs = false, update = false;",
                            "    bool romfs = false, update = false, read_only = false;")
    source = source.replace("            if (romfs) {\n                req.reply(1, 0, ERR_UNSUPPORTED);",
                            "            if (romfs || read_only) {\n                req.reply(1, 0, ERR_UNSUPPORTED);")
    source = source.replace("            if (!romfs) {\n                host.flush();",
                            """            if (romfs || read_only) {
                req.reply(1, 0, ERR_UNSUPPORTED);
                break;
            }
            {
                host.flush();""")
    source = source.replace("        case SELF_NCCH:\n        case NCCH:",
                            """        case NCCH: {
            uint64_t title = 0;
            if (path.data.size() >= sizeof title) std::memcpy(&title, path.data.data(), sizeof title);
            if (title == 0x0004009b00010202ull) {
                const char *base = SDL_GetBasePath();
                auto image = std::filesystem::u8path(base ? base : ".") / "mii.romfs";
                if (!fs::is_regular_file(image)) {
                    const auto utf8 = image.u8string();
                    LOG("fs: missing Mii resource archive %s; rerun the build command",
                        reinterpret_cast<const char *>(utf8.c_str()));
                    return ERR_ARCHIVE_NOT_FOUND;
                }
                *out = {id, image};
                return kernel::RESULT_OK;
            }
            if (title != dump().program_id()) return ERR_ARCHIVE_NOT_FOUND;
            *out = {id, {}};
            return kernel::RESULT_OK;
        }
        case SELF_NCCH:""")
    source = source.replace("        auto f = std::make_shared<File>();\n        if (a.root.empty()) {",
                            """        auto f = std::make_shared<File>();
        if (a.id == NCCH && !a.root.empty()) {
            if (flags != 1 || path.type != PATH_BINARY || path.data.size() != 20 ||
                std::any_of(path.data.begin(), path.data.end(), [](uint8_t b) { return b != 0; }))
                return ERR_FILE_NOT_FOUND;
            f->host_path = a.root;
            f->host.open(a.root, std::ios::binary | std::ios::in);
            if (!f->host) return ERR_FILE_NOT_FOUND;
            f->read_only = true;
            *out = f;
            return kernel::RESULT_OK;
        }
        if (a.root.empty()) {""")
    source = source.replace("    std::fstream host;",
                            "    std::fstream host;\n    const std::vector<uint8_t> *exefs = nullptr;")
    source = source.replace("        return fs::file_size(host_path);",
                            "        return exefs ? exefs->size() : fs::file_size(host_path);")
    source = source.replace("            } else {\n                host.clear();\n                host.seekg",
                            """            } else if (exefs) {
                got = offset >= exefs->size() ? 0 : std::min<uint64_t>(len, exefs->size() - offset);
                if (got) std::memcpy(mem::ptr(dest), exefs->data() + offset, size_t(got));
            } else {
                host.clear();
                host.seekg""")
    source = source.replace("            if (type == 5 && !dump().has_update())",
                            """            if (type == 2 && a.id == SELF_NCCH && flags == 1 &&
                path.type == PATH_BINARY && path.data.size() == 12) {
                const char *name = reinterpret_cast<const char *>(path.data.data() + 4);
                auto entry = dump().exefs_files().find(std::string(name, strnlen(name, 8)));
                if (entry == dump().exefs_files().end()) return ERR_FILE_NOT_FOUND;
                f->exefs = &entry->second;
                f->read_only = true;
                *out = f;
                return kernel::RESULT_OK;
            }
            if (type == 5 && !dump().has_update())""")
    source = source.replace('#include "platform.h"', '#include "platform.h"\n#include "save_storage.h"')
    source = source.replace("            if (req.arg(0) == SAVE_DATA && !fs::exists(save_root())) {",
                            """            if (req.arg(0) == SAVE_DATA) {
                const auto format = sm3dl::read_save_format(save_root());
                if (format) {
                    auto reply = req.reply(5, 0);
                    for (uint32_t field : *format) reply.push(field);
                    break;
                }
            }
            if (req.arg(0) == SAVE_DATA && !fs::exists(save_root())) {""")
    source = source.replace(
        between(source, "            if (req.arg(0) == SAVE_DATA) {\n                std::error_code ec;",
                "            req.reply(1, 0);\n            break;\n        default:"),
        """            if (req.arg(0) == SAVE_DATA) {
                sm3dl::format_save(save_root(), {req.arg(3) * 512, req.arg(4), req.arg(5), req.arg(8) & 1});
            }
""")
    source = source.replace("                d->entries.push_back({e.path().filename().string(), e.is_directory(ec), e.is_directory(ec) ? 0 : e.file_size(ec)});",
                            """                if (!sm3dl::is_save_format_file(e.path()))
                    d->entries.push_back({e.path().filename().string(), e.is_directory(ec), e.is_directory(ec) ? 0 : e.file_size(ec)});""")
    return source.replace('#include "service.h"', '#include "service.h"\n#include <SDL3/SDL.h>')

def gpu(source):
    source = source.replace(
        between(source, "    // cull (mode 1 keeps clockwise", "    for (int i = 0; i < 3; i++) {\n        const float *a = v[i]->a;"),
        """    // Cull according to the winding of the visible part of the triangle.
    if (cur_cull == 1 || cur_cull == 2) {
        float w0 = v0.a[POS + 3], w1 = v1.a[POS + 3], w2 = v2.a[POS + 3];
        if (w0 > 0 && w1 > 0 && w2 > 0) {
            float x0 = v0.a[POS] / w0, y0 = v0.a[POS + 1] / w0, x1 = v1.a[POS] / w1, y1 = v1.a[POS + 1] / w1;
            float x2 = v2.a[POS] / w2, y2 = v2.a[POS + 1] / w2;
            float area = (x1 - x0) * (y2 - y0) - (y1 - y0) * (x2 - x0);
            if ((cur_cull == 1 && area >= 0) || (cur_cull == 2 && area <= 0)) return;
        } else {
            // Clipping to positive w preserves the sign of this homogeneous determinant.
            // Dividing by w here would misclassify triangles crossing the camera plane.
            // Submitting them to both cull passes breaks stencil shadows (e.g. W6-3).
            const double x0 = v0.a[POS], x1 = v1.a[POS], x2 = v2.a[POS];
            const double y0 = v0.a[POS + 1], y1 = v1.a[POS + 1], y2 = v2.a[POS + 1];
            const double area = x0 * (y1 * w2 - y2 * w1) - y0 * (x1 * w2 - x2 * w1) + w0 * (x1 * y2 - x2 * y1);
            if ((cur_cull == 1 && area >= 0) || (cur_cull == 2 && area <= 0)) return;
        }
    }
""")
    source = source.replace(
        "    k.color_mask = regs[COLOR_WRITE_ALLOW] ? uint8_t((dm >> 8) & 0xF) : 0;",
        """    // PICA logic op 6 keeps the destination while depth and stencil still run.
    const bool preserve_color = !k.blend && (regs[LOGIC_OP] & 0xF) == 6;
    k.color_mask = !preserve_color && regs[COLOR_WRITE_ALLOW] ? uint8_t((dm >> 8) & 0xF) : 0;""")
    source = source.replace(
        "std::vector<std::unique_ptr<Surface>> surfaces;",
        "std::vector<std::unique_ptr<Surface>> surfaces;\nint render_scale = 1, render_margin = 0;")
    source = source.replace(
        "    int margin, scale;\n    requested_enhancement(&margin, &scale);",
        "    int margin = render_margin;\n    const int scale = render_scale;")
    source = source.replace(
        "void begin_list() {\n    list_hashes.clear();",
        """void begin_list() {
    list_hashes.clear();
    int margin, scale;
    requested_enhancement(&margin, &scale);
    if (scale != render_scale || margin != render_margin) {
        // Preserve guest-visible color buffers before rebuilding targets at the new size.
        for (const auto &s : surfaces) {
            if (!s->depth && s->drawn && !s->reload && !overwritten(s.get()))
                download_surface(s.get());
        }
        release_twins();
        for (const auto &s : surfaces) SDL_ReleaseGPUTexture(dev, s->tex);
        surfaces.clear();
        last_frame.clear();
        this_frame.clear();
        interp_this = false;
        render_scale = scale;
        render_margin = margin;
    }""")
    source = source.replace("SDL_Mutex *lcd_lock;",
                            "SDL_Mutex *lcd_lock;\nstd::vector<SDL_GPUTexture *> retired_scanouts;")
    for frame in ("f", "q"):
        indent = "        " if frame == "f" else "            "
        source = source.replace(
            f"{indent}for (auto *t : {frame}.tex)\n{indent}    if (t) SDL_ReleaseGPUTexture(dev, t);",
            f"{indent}for (auto *t : {frame}.tex)\n{indent}    if (t) retired_scanouts.push_back(t);")
    source = source.replace(
        "SDL_GPUTexture *lcd_frame(uint32_t addr, int *width, int *height) {",
        """std::vector<SDL_GPUTexture *> take_retired_scanouts() {
    std::vector<SDL_GPUTexture *> result;
    if (!ok) return result;
    SDL_LockMutex(lcd_lock);
    result.swap(retired_scanouts);
    SDL_UnlockMutex(lcd_lock);
    return result;
}

SDL_GPUTexture *lcd_frame(uint32_t addr, int *width, int *height) {""")
    source = source.replace("cmd = SDL_AcquireGPUCommandBuffer(dev);", "cmd = acquire_commands();")
    source = source.replace("SDL_SubmitGPUCommandBuffer(cmd);", "submit_commands(cmd);")
    download_comment = between(source, "// Copies a surface's image back into guest memory", "void download_surface")
    source = source.replace(
        download_comment,
        """[[noreturn]] void gpu_failure(const char *operation) {
    fatal("Vulkan %s failed: %s. Set gpu_renderer=0 in userdata/settings.ini to use the fallback renderer.",
          operation, SDL_GetError());
}

SDL_GPUCommandBuffer *acquire_commands() {
    auto *cmd = SDL_AcquireGPUCommandBuffer(dev);
    if (!cmd) gpu_failure("command acquisition");
    return cmd;
}

void submit_commands(SDL_GPUCommandBuffer *cmd) {
    // SDL Vulkan normally reclaims submissions when the window presents. Windows
    // can block that thread in a menu or resize loop while the game keeps rendering.
    // Retire completed batches independently and cap how far the producer can run ahead.
    static constexpr unsigned submissions_per_fence = 64;
    static unsigned submissions = 0;
    static SDL_GPUFence *previous_fence = nullptr;
    if (++submissions < submissions_per_fence) {
        if (!SDL_SubmitGPUCommandBuffer(cmd)) gpu_failure("command submission");
        return;
    }
    submissions = 0;
    SDL_GPUFence *fence = SDL_SubmitGPUCommandBufferAndAcquireFence(cmd);
    if (!fence) gpu_failure("command submission");
    if (previous_fence) {
        if (!SDL_WaitForGPUFences(dev, true, &previous_fence, 1)) gpu_failure("command retirement");
        SDL_ReleaseGPUFence(dev, previous_fence);
    }
    previous_fence = fence;
}

""" + download_comment,
    )
    source = source.replace(
        "    SDL_GPUCopyPass *copy = SDL_BeginGPUCopyPass(cmd);\n    SDL_GPUTextureRegion src{};",
        """    if (!tb) gpu_failure("readback allocation");
    SDL_GPUCopyPass *copy = SDL_BeginGPUCopyPass(cmd);
    SDL_GPUTextureRegion src{};""",
        1,
    )
    source = source.replace(
        "    SDL_WaitForGPUFences(dev, true, &fence, 1);",
        """    if (!fence) gpu_failure("readback submission");
    if (!SDL_WaitForGPUFences(dev, true, &fence, 1)) gpu_failure("readback wait");""",
        1,
    )
    source = source.replace(
        "    const auto *rgba = static_cast<const uint8_t *>(SDL_MapGPUTransferBuffer(dev, tb, false));",
        """    const auto *rgba = static_cast<const uint8_t *>(SDL_MapGPUTransferBuffer(dev, tb, false));
    if (!rgba) gpu_failure("readback mapping");""",
        1,
    )
    source = source.replace(
        "uint32_t cfmt = (regs[COLOR_FORMAT] >> 16) & 7, dfmt = regs[DEPTH_FORMAT] & 3;",
        "const uint32_t cfmt = render_target_format(regs[COLOR_FORMAT]);\n"
        "    const uint32_t dfmt = regs[DEPTH_FORMAT] & 3;")
    source = source.replace(
        """        SDL_GPUTexture *staging = make_texture(l.surface->width, l.surface->height, SDL_GPU_TEXTUREFORMAT_R8G8B8A8_UNORM,
                                               SDL_GPU_TEXTUREUSAGE_SAMPLER);
        loaded.push_back(staging);
        items.push_back({at, staging, l.surface->width, l.surface->height});""",
        """        auto &surface = *l.surface;
        const bool direct = surface.tw == surface.width && surface.th == surface.height;
        SDL_GPUTexture *staging = direct ? nullptr :
            make_texture(surface.width, surface.height, SDL_GPU_TEXTUREFORMAT_R8G8B8A8_UNORM,
                         SDL_GPU_TEXTUREUSAGE_SAMPLER);
        loaded.push_back(staging);
        if (direct || staging)
            items.push_back({at, direct ? surface.tex : staging, surface.width, surface.height});
        else
            surface.reload = true;""")
    source = source.replace(
        "        Surface *s = surface_loads[i].surface;",
        "        if (!loaded[i]) continue;\n        Surface *s = surface_loads[i].surface;")
    # A native-resolution target can be downloaded without an intermediate GPU blit.
    source = source.replace(
        between(source, "    SDL_GPUTexture *tmp = make_texture(w, h", "    SDL_GPUTransferBufferCreateInfo tbi"),
        """    SDL_GPUTexture *image = s->tex;
    SDL_GPUCommandBuffer *cmd = acquire_commands();
    if (s->tw != w || s->th != h) {
        image = make_texture(w, h, SDL_GPU_TEXTUREFORMAT_R8G8B8A8_UNORM,
                             SDL_GPU_TEXTUREUSAGE_SAMPLER | SDL_GPU_TEXTUREUSAGE_COLOR_TARGET);
        SDL_GPUBlitInfo blit{};
        blit.source.texture = s->tex;
        blit.source.y = uint32_t(s->margin * s->scale);
        blit.source.w = s->tw;
        blit.source.h = h * uint32_t(s->scale);
        blit.destination.texture = image;
        blit.destination.w = w;
        blit.destination.h = h;
        blit.load_op = SDL_GPU_LOADOP_DONT_CARE;
        blit.filter = SDL_GPU_FILTER_LINEAR;
        SDL_BlitGPUTexture(cmd, &blit);
    }
""")
    source = source.replace("    src.texture = tmp, src.w = w, src.h = h, src.d = 1;",
                            "    src.texture = image, src.w = w, src.h = h, src.d = 1;")
    source = source.replace("    SDL_ReleaseGPUTexture(dev, tmp);\n    s->drawn = false;",
                            "    if (image != s->tex) SDL_ReleaseGPUTexture(dev, image);\n    s->drawn = false;")
    source = source.replace("    TextureUpload u{it->second.tex, {}, w, th};",
                            """    if (std::getenv("SM3DL_TRACE_TEXTURE_UPLOADS") && changes >= 4 && changes % 120 == 0)
        LOG("dynamic texture %08x %ux%u format %u change %u", t.addr, t.width, t.height, t.format, changes);
    TextureUpload u{it->second.tex, {}, w, th};""")
    # Reuse decoded pixels for unchanged blocks of the animated ETC1A4 atlas.
    source = source.replace("    uint32_t changes = 0; // times",
                            "    std::vector<uint8_t> compressed, decoded;\n    uint32_t changes = 0; // times")
    source = source.replace("        u.rgba.resize(size_t(t.width) * t.height * 4);\n        decode_texture(t, u.rgba.data());",
                            """        if (t.format == 13 && t.bytes >= (256u << 10) && changes >= 2) {
            auto &cached = it->second;
            if (cached.decoded.empty()) {
                cached.decoded.resize(size_t(t.width) * t.height * 4);
                decode_texture(t, cached.decoded.data());
                cached.compressed.assign(t.data, t.data + t.bytes);
            } else {
                update_etc1a4(t, cached.compressed.data(), cached.decoded.data());
            }
            u.rgba = cached.decoded;
        } else {
            u.rgba.resize(size_t(t.width) * t.height * 4);
            decode_texture(t, u.rgba.data());
        }""")
    source = source.replace(
        "    tri_ids.push_back(tri);",
        "    if (interp_on) tri_ids.push_back(tri);",
    )
    source = source.replace("#include <cmath>", "#include <cmath>\n#include <immintrin.h>")
    source = source.replace(
        """            float x0 = v0.a[POS] / w0, y0 = v0.a[POS + 1] / w0, x1 = v1.a[POS] / w1, y1 = v1.a[POS + 1] / w1;
            float x2 = v2.a[POS] / w2, y2 = v2.a[POS + 1] / w2;""",
        """            alignas(16) float xy[4], last[4];
            _mm_store_ps(xy, _mm_div_ps(_mm_setr_ps(v0.a[POS], v0.a[POS + 1], v1.a[POS], v1.a[POS + 1]),
                                      _mm_setr_ps(w0, w0, w1, w1)));
            _mm_store_ps(last, _mm_div_ps(_mm_setr_ps(v2.a[POS], v2.a[POS + 1], 0.0f, 0.0f), _mm_set1_ps(w2)));
            const float x0 = xy[0], y0 = xy[1], x1 = xy[2], y1 = xy[3], x2 = last[0], y2 = last[1];""",
    )
    source = source.replace(
        """        for (int c = 0; c < 4; c++) g.color[c] = a[COLOR + c], g.quat[c] = a[QUAT + c];
        g.tc01[0] = a[TEX0], g.tc01[1] = a[TEX0 + 1], g.tc01[2] = a[TEX1], g.tc01[3] = a[TEX1 + 1];""",
        """        _mm_storeu_ps(g.color, _mm_loadu_ps(a + COLOR));
        _mm_storeu_ps(g.quat, _mm_loadu_ps(a + QUAT));
        _mm_storeu_ps(g.tc01, _mm_loadu_ps(a + TEX0));""",
    )
    source = source.replace(
        "    for (auto &l : surface_loads) reloaded.push_back(l.surface);",
        "    if (interp_this) for (auto &l : surface_loads) reloaded.push_back(l.surface);",
    )
    source = reuse_upload_buffer(source)
    return hd_texture_gpu(course_hud_gpu(lcd_smoothing(land_lcd(source))))


def hd_texture_gpu(source):
    source = source.replace('#include "gpu.h"', '#include "gpu.h"\n#include "hd_texture_pack.h"')
    source = source.replace('#include <algorithm>', '#include <algorithm>\n#include <bit>')
    source = source.replace('SDL_GPUTextureUsageFlags usage) {',
                            'SDL_GPUTextureUsageFlags usage, uint32_t levels = 1) {', 1)
    source = source.replace('info.layer_count_or_depth = 1, info.num_levels = 1;',
                            'info.layer_count_or_depth = 1, info.num_levels = levels;', 1)
    source = source.replace('    uint32_t changes = 0; // times',
                            '    uint32_t levels = 1;\n    uint32_t changes = 0; // times', 1)
    source = source.replace('    uint32_t w, h;\n};\nstruct SurfaceLoad',
                            '    uint32_t w, h;\n    bool mipmaps = false;\n};\nstruct SurfaceLoad', 1)
    source = source.replace('SDL_GPUSampler *sampler(bool linear, uint32_t wrap_s, uint32_t wrap_t) {\n'
                            '    int key = int(linear) | int(wrap_s & 7) << 1 | int(wrap_t & 7) << 4;',
                            'SDL_GPUSampler *sampler(bool linear, uint32_t wrap_s, uint32_t wrap_t, bool mipmaps) {\n'
                            '    int key = int(linear) | int(wrap_s & 7) << 1 | int(wrap_t & 7) << 4 | int(mipmaps) << 7;')
    source = source.replace('    info.min_filter = info.mag_filter = linear ? SDL_GPU_FILTER_LINEAR : SDL_GPU_FILTER_NEAREST;\n'
                            '    info.mipmap_mode = SDL_GPU_SAMPLERMIPMAPMODE_NEAREST;',
                            '    info.mag_filter = linear ? SDL_GPU_FILTER_LINEAR : SDL_GPU_FILTER_NEAREST;\n'
                            '    info.min_filter = mipmaps ? SDL_GPU_FILTER_LINEAR : info.mag_filter;\n'
                            '    info.mipmap_mode = mipmaps ? SDL_GPU_SAMPLERMIPMAPMODE_LINEAR : SDL_GPU_SAMPLERMIPMAPMODE_NEAREST;\n'
                            '    info.max_lod = mipmaps ? 16.0f : 0.0f;')
    source = source.replace('SDL_GPUTexture *texture_for(const Texture &t) {',
                            'SDL_GPUTexture *texture_for(const Texture &t, bool &mipmaps) {\n    mipmaps = false;')
    source = source.replace('if (it != textures.end() && it->second.hash == h) {\n',
                            'if (it != textures.end() && it->second.hash == h) {\n'
                            '        mipmaps = it->second.levels > 1;\n', 1)
    source = source.replace('bool hd_indexed = false;', '''bool hd_indexed = false;
std::atomic<bool> hd_pack_requested{false};
bool hd_pack_enabled = false;''')
    source = source.replace('    const HdImage *hd = hd_texture(h);\n    uint32_t w = hd ? hd->w : t.width, th = hd ? hd->h : t.height;', '''    sm3dl::PackTexture pack;
    if (hd_pack_enabled) pack = sm3dl::load_pack_texture(t.data, t.bytes, t.width, t.height, t.format);
    const HdImage *hd = pack.rgba.empty() ? hd_texture(h) : nullptr;
    uint32_t w = pack.width ? pack.width : hd ? hd->w : t.width;
    uint32_t th = pack.height ? pack.height : hd ? hd->h : t.height;
    // Never filter an HD atlas below the dimensions of the original PICA texture.
    const uint32_t levels = pack.rgba.empty() ? 1 : std::max<uint32_t>(1, std::bit_width(std::min(w / t.width, th / t.height)));
    mipmaps = levels > 1;''')
    source = source.replace('(it->second.w != w || it->second.h != th)',
                            '(it->second.w != w || it->second.h != th || it->second.levels != levels)', 1)
    source = source.replace('SDL_GPU_TEXTUREUSAGE_SAMPLER),\n                                                 h, use_clock, w, th})',
                            'SDL_GPU_TEXTUREUSAGE_SAMPLER | (mipmaps ? SDL_GPU_TEXTUREUSAGE_COLOR_TARGET : 0),\n'
                            '                                                              levels), h, use_clock, w, th})', 1)
    source = source.replace('    TextureUpload u{it->second.tex, {}, w, th};',
                            '    it->second.levels = levels;\n    TextureUpload u{it->second.tex, {}, w, th, mipmaps};', 1)
    source = source.replace('    if (hd) {\n        u.rgba = hd->rgba;',
                            '    if (!pack.rgba.empty()) {\n        u.rgba = std::move(pack.rgba);\n'
                            '    } else if (hd) {\n        u.rgba = hd->rgba;')
    source = source.replace('        d.tex[unit] = texture_for(t);\n        d.samp[unit] = sampler(t.mag_linear, t.wrap_s, t.wrap_t);',
                            '        bool mipmaps;\n        d.tex[unit] = texture_for(t, mipmaps);\n'
                            '        d.samp[unit] = sampler(t.mag_linear, t.wrap_s, t.wrap_t, mipmaps);')
    source = source.replace('    SDL_EndGPUCopyPass(copy);\n\n    // surface loads',
                            '    SDL_EndGPUCopyPass(copy);\n'
                            '    for (const auto &upload : texture_uploads)\n'
                            '        if (upload.mipmaps) SDL_GenerateMipmapsForGPUTexture(cmd, upload.tex);\n\n'
                            '    // surface loads')
    source = source.replace('void begin_list() {\n    list_hashes.clear();', '''void set_hd_textures(bool enabled) {
    hd_pack_requested.store(enabled && sm3dl::has_hd_texture_pack(), std::memory_order_relaxed);
}

void begin_list() {
    list_hashes.clear();
    const bool hd = hd_pack_requested.load(std::memory_order_relaxed);
    if (hd != hd_pack_enabled) {
        // SDL defers releasing in-flight GPU resources. Rebuild textures at a guest list boundary.
        for (const auto &[key, entry] : textures) SDL_ReleaseGPUTexture(dev, entry.tex);
        textures.clear();
        hd_pack_enabled = hd;
        LOG("HD textures: %s", hd ? "on" : "off");
    }''')
    return source


def lcd_smoothing(source):
    source = source.replace('#include "sm3dl_lcd.inc"',
                            '#include "sm3dl_lcd.inc"\n#include "sm3dl_estimate.inc"\n'
                            '#include "sm3dl_screen_motion.inc"\n#include "sm3dl_interpolate.inc"')
    source = source.replace("std::vector<SDL_GPUTexture *> retired_scanouts;",
                            'std::vector<SDL_GPUTexture *> retired_scanouts;\n#include "lcd_smoothing.h"\nLcdSmoother smoother;')
    source = source.replace(between(source, "SDL_GPUTexture *top_frame(", "std::vector<SDL_GPUTexture *> take_retired_scanouts()"),
                            """SDL_GPUTexture *top_frame(uint32_t address, int *width, int *height, bool *interpolated) {
    if (!ok) return nullptr;
    SDL_LockMutex(lcd_lock);
    auto it = lcd.find(address);
    SDL_GPUTexture *frame = nullptr;
    if (it != lcd.end() && it->second.latest >= 0) {
        frame = it->second.tex[it->second.latest];
        *width = it->second.w;
        *height = it->second.h;
    }
    const uint64_t tick = vblanks.load();
    if (!frame) {
        smoother.previous = nullptr;
        smoother.original_pending = false;
    } else if (smoother.previous != frame || smoother.previous_address != address) {
        auto last = lcd.find(smoother.previous_address);
        const uint64_t gap = tick - smoother.previous_tick;
        const bool same_size = last != lcd.end() && last->second.w == *width && last->second.h == *height;
        const bool previous_valid = same_size && last->second.latest >= 0 &&
                                    last->second.tex[last->second.latest] == smoother.previous;
        auto *previous = smoother.previous;
        const bool pending = smoother.original_pending;
        smoother.previous = frame;
        smoother.previous_address = address;
        smoother.previous_tick = tick;
        smoother.original_pending = false;
        if (previous_valid && pending && gap == 1) {
            frame = previous;
            smoother.original_pending = true;
        // Only fill a missing refresh when the game provides a new 30 Hz frame.
        // A cut or stall must never accumulate extra latency.
        } else if (previous_valid && previous && gap >= 2 && gap <= 3) {
            if (auto *mid = smoother.render(previous, frame, *width, *height)) {
                frame = mid;
                *interpolated = true;
                smoother.original_pending = true;
            }
        }
    } else {
        smoother.original_pending = false;
    }
    SDL_UnlockMutex(lcd_lock);
    return frame;
}

""")
    return source


def land_lcd(source):
    source = source.replace(
        '    int sx0 = 0, sy0 = 0, sx1 = int(w) - 1, sy1 = int(h) - 1 + 2 * m;',
        '''    // Both LCDs reuse the same render target, but the lower LCD has a
    // 320-row viewport. Place it unchanged inside the widened target's center.
    if (w == frontend::SCREEN_HEIGHT && h == frontend::TOP_WIDTH &&
        2 * hh == frontend::BOTTOM_WIDTH) {
        cur_ky = 1.0f;
        d.viewport.y += float(m * s);
        d.viewport.h = 2 * hh * float(s);
    }
    int sx0 = 0, sy0 = 0, sx1 = int(w) - 1, sy1 = int(h) - 1 + 2 * m;''')
    source = source.replace('#include "gpu.h"', '#include "gpu.h"\n#include "frontend/frontend.h"')
    source = source.replace('#include "shaders.inc"', '#include "shaders.inc"\n#include "sm3dl_lcd.inc"')
    source = source.replace("SPIRV_blit_lcd_frag, sizeof SPIRV_blit_lcd_frag", "sm3dl_lcd, sizeof sm3dl_lcd")
    source = source.replace(
        "uint32_t flags) {\n    if (!ok) return false;\n    list_hashes.clear();\n    if (in_h == 400)",
        """uint32_t flags, bool right_eye) {
    if (!ok) return false;
    list_hashes.clear();
    // The European game's LCD transfers are rotated in memory. Their
    // destination sizes, rather than the shared render target size, define the LCDs.
    const bool lcd_source = in_w == frontend::SCREEN_HEIGHT && in_h == frontend::TOP_WIDTH &&
                            out_w == frontend::SCREEN_HEIGHT;
    const bool land_top = lcd_source && out_h == frontend::TOP_WIDTH && flags == 0x2000;
    const bool land_bottom = lcd_source && out_h == frontend::BOTTOM_WIDTH && flags == 0x2004;
    const bool top = in_h == frontend::TOP_WIDTH && out_h == frontend::TOP_WIDTH && !right_eye;
    if (top)""").replace("    bool top = in_h == 400;\n", "")
    source = source.replace(
        "    bool to_lcd = !(flags & 2) && !(flags & 0x20) && (((flags >> 12) & 7) <= 1);",
        """    const bool rgb565 = land_top || land_bottom;
    const bool to_lcd = rgb565 || (!(flags & 2) && !(flags & 0x20) && (((flags >> 12) & 7) <= 1));
    uint32_t row = 0;
    bool alias = false;
    if (!src && land_bottom) {
        // The lower LCD is a tile-row-aligned view of the 400-row RGBA8 target.
        for (auto &surface : surfaces) {
            if (surface->depth || surface->reload || surface->format != FB_RGBA8 || surface->width != in_w ||
                surface->addr >= p || p >= uint64_t(surface->addr) + surface->bytes()) continue;
            const uint32_t pitch = surface->width * surface->bpp();
            const uint32_t offset = p - surface->addr;
            if (offset % (8 * pitch) || offset / pitch + out_h > surface->height) continue;
            if (!src || surface->last_used >= src->last_used) {
                src = surface.get();
                row = offset / pitch;
                alias = true;
            }
        }
    }""")
    source = source.replace("    flush();\n    uint32_t hs =",
                            "    flush();\n    if (alias && overwritten(src)) return false;\n    uint32_t hs =")
    source = source.replace(
        "    int w = int(src->th >> vs), h = int(src->tw >> hs); // upright: rows of the output become columns\n"
        "    (void)out_w, (void)out_h;",
        """    const int w = rgb565 ? int((out_h + (land_top ? 2 * src->margin : 0)) * src->scale) : int(src->th >> vs);
    const int h = rgb565 ? int(out_w * src->scale) : int(src->tw >> hs);""")
    source = source.replace(
        "{int32_t(flags & 1), int32_t(hs), int32_t(vs), 0}};",
        "{int32_t((flags & 1) | (rgb565 ? 2 : 0)), int32_t(hs), int32_t(vs), "
        "int32_t((row + (land_top ? 0 : src->margin)) * src->scale)}};")
    source = source.replace("struct LcdFrames {", "struct LcdFrames {\n    uint32_t scanout_bytes = 0;")
    source = source.replace("    LcdFrames &f = lcd[out];",
        "    LcdFrames &f = lcd[out];\n    f.scanout_bytes = out_w * out_h * fb_bpp((flags >> 12) & 7);")
    return source.replace(
        "    lcd.erase(addr); // an LCD buffer written by the CPU shows that, not an older GPU frame\n"
        "    if (addr == top_queue.addr) top_queue.reset();",
        """    for (auto &[address, frame] : lcd) {
        const uint32_t start = to_physical(address);
        if (p < uint64_t(start) + frame.scanout_bytes && start < uint64_t(p) + size) {
            frame.latest = -1;
            if (address == top_queue.addr) top_queue.reset();
        }
    }""")


def reuse_upload_buffer(source):
    source = source.replace(
        "// copies pending texture, LUT, surface and vertex data to the GPU (one copy pass)",
        """// Keep the transfer buffer across batches. SDL cycles its backing storage\n// when commands from an earlier batch still reference it.
SDL_GPUTransferBuffer *batch_upload = nullptr;
uint32_t upload_capacity = 0;

uint32_t batch_capacity(size_t size) {
    return uint32_t(std::min<uint64_t>(UINT32_MAX, std::max<uint64_t>(65536, uint64_t(size) * 2)));
}

// copies pending texture, LUT, surface and vertex data to the GPU (one copy pass)""")
    source = source.replace(
        """    SDL_GPUTransferBufferCreateInfo tbi{SDL_GPU_TRANSFERBUFFERUSAGE_UPLOAD, uint32_t(total), 0};
    SDL_GPUTransferBuffer *tb = SDL_CreateGPUTransferBuffer(dev, &tbi);
    if (!tb) out_of_gpu_memory(), tb = SDL_CreateGPUTransferBuffer(dev, &tbi);
    if (!tb) {""",
        """    if (total > upload_capacity && total <= UINT32_MAX) {
        SDL_GPUTransferBufferCreateInfo info{SDL_GPU_TRANSFERBUFFERUSAGE_UPLOAD, batch_capacity(total), 0};
        if (auto *larger = SDL_CreateGPUTransferBuffer(dev, &info)) {
            if (batch_upload) SDL_ReleaseGPUTransferBuffer(dev, batch_upload);
            batch_upload = larger;
            upload_capacity = info.size;
        }
    }
    SDL_GPUTransferBuffer *tb = total <= upload_capacity ? batch_upload : nullptr;
    auto *map = tb ? static_cast<uint8_t *>(SDL_MapGPUTransferBuffer(dev, tb, true)) : nullptr;
    if (!map) {""")
    source = source.replace(
        "    auto *map = static_cast<uint8_t *>(SDL_MapGPUTransferBuffer(dev, tb, false));\n    size_t at = 0;",
        "    size_t at = 0;")
    source = source.replace("    SDL_EndGPUCopyPass(copy);\n    SDL_ReleaseGPUTransferBuffer(dev, tb);\n\n    // surface loads",
                            "    SDL_EndGPUCopyPass(copy);\n\n    // surface loads")
    return source


def course_hud_gpu(source):
    source = source.replace('#include "gpu.h"', '#include "gpu.h"\n#include "course_hud.h"\n#include "course_touch.h"')
    source = source.replace('    uint32_t first, count;\n',
                            '    uint32_t first, count;\n    unsigned hud_part = 0;\n'
                            '    bool pause_sprite = false, hide_pause_title = false;\n', 1)
    source = source.replace('void end_draw() {', '#include "course_hud_gpu.inc"\n\nvoid end_draw() {')
    source = source.replace(
        '        batch.push_back(cur);',
        '        cur.pause_sprite = false;\n'
        '        cur.hud_part = course_hud_part(cur, regs[TEX0_DIM], regs[BLEND_FUNC]);\n'
        '        cur.hide_pause_title = hide_course_pause_title(cur);\n'
        '        batch.push_back(cur);')
    source = source.replace('    for (const DrawRec &d : batch) {\n        begin_render_pass',
                            '    for (const DrawRec &d : batch) {\n        if (d.hide_pause_title) continue;\n'
                            '        begin_render_pass')
    source = source.replace('            if (!d.interpolated) continue;\n            SDL_GPUTexture *color',
                            '            if (!d.interpolated || d.hide_pause_title) continue;\n'
                            '            SDL_GPUTexture *color')
    source = source.replace(
        '    clear_fresh(cmd);\n    upload_pending(cmd, &vbuf);',
        '''    clear_fresh(cmd);
    const uint32_t hud_first = uint32_t(vertices.size());
    if (hud_enabled.load(std::memory_order_relaxed)) {
        for (const auto &draw : batch)
            if (draw.hud_part) append_hud_vertices(draw);
    }
    const bool has_hud_draws = vertices.size() != hud_first;
    upload_pending(cmd, &vbuf);''')
    source = source.replace(
        '    submit_commands(cmd);\n    if (vbuf) SDL_ReleaseGPUBuffer(dev, vbuf);',
        '    if (vbuf && has_hud_draws) draw_course_hud(cmd, vbuf, hud_first);\n'
        '    if (vbuf) draw_course_pause(cmd, vbuf);\n'
        '    submit_commands(cmd);\n    if (vbuf) SDL_ReleaseGPUBuffer(dev, vbuf);')
    source = source.replace(
        '    blit(src->tex, f.tex[slot]);',
        '    blit(src->tex, f.tex[slot]);\n    if (land_bottom) copy_course_reserve(cmd, f.tex[slot]);')
    source = source.replace(
        '    submit_commands(cmd);\n\n    SDL_LockMutex(lcd_lock);\n    f.latest = slot;',
        '    submit_commands(cmd);\n\n    SDL_LockMutex(lcd_lock);\n'
        '    if (land_bottom) publish_course_hud();\n    f.latest = slot;')
    source = source.replace('std::vector<SDL_GPUTexture *> take_retired_scanouts() {', '''void enable_course_hud(bool enabled, bool centered_pause) {
    hud_enabled.store(enabled, std::memory_order_relaxed);
    centered_pause_enabled.store(centered_pause, std::memory_order_relaxed);
}

SDL_GPUTexture *course_hud_frame() {
    return hud_latest.load(std::memory_order_acquire);
}

CoursePauseFrame course_pause_frame() {
    SDL_LockMutex(lcd_lock);
    const auto frame = pause_latest;
    SDL_UnlockMutex(lcd_lock);
    return frame;
}

std::vector<SDL_GPUTexture *> take_retired_scanouts() {''')
    return source


def pica(source):
    source = source.replace('#include "gpu/gpu.h"', '#include "gpu/gpu.h"\n#include "course_touch.h"')
    source = source.replace(
        'void emit_triangle(const Vertex &v0, const Vertex &v1, const Vertex &v2) {',
        '''#include "course_touch_scan.inc"

void emit_triangle(const Vertex &v0, const Vertex &v1, const Vertex &v2) {
    if (course_touch_scan.tracking) {
        course_touch_scan.add(v0);
        course_touch_scan.add(v1);
        course_touch_scan.add(v2);
    }''')
    source = source.replace(
        'void draw(bool indexed) {',
        'void draw(bool indexed) {\n    course_touch_scan.begin();')
    source = source.replace(
        '    count_draw(n && std::fabs(w - 1.0f) > 1e-4f);',
        '    course_touch_scan.end();\n    count_draw(n && std::fabs(w - 1.0f) > 1e-4f);')
    source = source.replace(
        '        scene_published.bottom_draws = scene_building.bottom_draws;',
        '        course_touch_scan.publish();\n        scene_published.bottom_draws = scene_building.bottom_draws;')
    source = source.replace(
        'SceneInfo scene_info() {',
        'bool course_reserve_ready() { return course_touch_scan.ready.load(std::memory_order_relaxed); }\n\n'
        'SceneInfo scene_info() {')
    source = source.replace(
        "    if (log_cfg::gpu) {\n        static const uint32_t stages[6]",
        """    if (log_cfg::gpu) {
        LOG("    framebuffer color op %x, logic op %x, masks %x/%x, stencil %08x/%x, depth format %x",
            regs[COLOR_OP], regs[LOGIC_OP], regs[COLOR_WRITE_ALLOW], regs[DEPTH_COLOR_MASK],
            regs[STENCIL_TEST], regs[STENCIL_OP], regs[DEPTH_FORMAT]);
        static const uint32_t stages[6]""")
    source = source.replace('#include "gpu/gpu.h"', '#include "gpu/gpu.h"\n#include "pica_shader_jit.h"')
    source = source.replace("ShaderSetup vs;", "ShaderSetup vs;\nstatic uint64_t shader_revision = 0;")
    source = source.replace("            vs.code[at & 4095] = value;",
                            """            auto &word = vs.code[at & 4095];
            if (word != value) ++shader_revision;
            word = value;""")
    source = source.replace("            vs.swizzle[at & 127] = value;",
                            """            auto &word = vs.swizzle[at & 127];
            if (word != value) ++shader_revision;
            word = value;""")
    source = source.replace("Vertex shade(const Vec4 attrs[16], const OutputMap &map) {",
                            "Vertex shade(const Vec4 attrs[16], const OutputMap &map, CompiledVertex compiled = nullptr) {")
    source = source.replace("    run_shader(vs, regs[VS_ENTRY] & 0xFFFF, in, out);",
                            """    if (compiled) {
        // Generated code supplies zero for unwritten temporaries.
        Vec4 scratch[16];
        compiled(vs.f, in, out, scratch);
        static const bool verify = std::getenv("SM3DL_VERIFY_VERTEX") != nullptr;
        if (verify) {
            Vec4 expected[16]{};
            run_shader(vs, regs[VS_ENTRY] & 0xFFFF, in, expected);
            if (std::memcmp(expected, out, sizeof out) != 0)
                fatal("Vertex shader output differs at %#x", regs[VS_ENTRY] & 0xFFFF);
        }
    } else {
        run_shader(vs, regs[VS_ENTRY] & 0xFFFF, in, out);
    }""")
    source = source.replace("    OutputMap map;\n", """    OutputMap map;
    static const bool interpret = std::getenv("SM3DL_INTERPRET_VERTEX") != nullptr;
    const auto compiled = interpret ? nullptr : find_compiled_shader(vs, regs[VS_ENTRY] & 0xFFFF, shader_revision);
""")
    source = source.replace("    int8_t semantic[16][4];\n    uint32_t mask;",
                            """    struct Component { uint8_t reg, channel, semantic; };
    Component components[28]{};
    uint32_t component_count = 0;
    uint8_t input_registers[16]{};
    uint32_t input_count = 0;""")
    source = source.replace("        std::memset(semantic, -1, sizeof semantic);\n        mask = regs[VS_OUTPUT_MASK] & 0xFFFF;",
                            """        const uint32_t mask = regs[VS_OUTPUT_MASK] & 0xFFFF;
        input_count = (regs[VS_INPUT_CONFIG] & 0xF) + 1;
        const uint64_t input_map = regs[VS_INPUT_MAP_LO] | (uint64_t(regs[VS_INPUT_MAP_HI]) << 32);
        for (uint32_t i = 0; i < input_count; ++i)
            input_registers[i] = uint8_t((input_map >> (4 * i)) & 0xF);""")
    source = source.replace("                semantic[reg][c] = sem < SEMANTIC_COUNT ? int8_t(sem) : -1;",
                            "                if (sem < SEMANTIC_COUNT)\n"
                            "                    components[component_count++] = {uint8_t(reg), uint8_t(c), uint8_t(sem)};")
    source = source.replace(
        between(source, "    uint32_t inputs = (regs[VS_INPUT_CONFIG]", "    if (compiled)"),
        "    for (uint32_t i = 0; i < map.input_count; ++i) in[map.input_registers[i]] = attrs[i];\n")
    source = source.replace(
        between(source, "    for (int r = 0; r < 16; r++)", "    // colors are clamped"),
        """    for (uint32_t i = 0; i < map.component_count; ++i) {
        const auto &component = map.components[i];
        v.a[component.semantic] = out[component.reg][component.channel];
    }
""")
    source = source.replace(
        "            for (uint32_t c = 0; c < a.count; c++) {",
        """            if (a.type == 3) {
                // Float vertex arrays dominate Mario's meshes. Load exactly
                // the declared components, including tightly packed XYZ.
                switch (a.count) {
                    case 4: std::memcpy(v.v, p, 16); break;
                    case 3: std::memcpy(v.v, p, 12); break;
                    case 2: std::memcpy(v.v, p, 8); break;
                    default: std::memcpy(v.v, p, 4); break;
                }
                out[i] = v;
                continue;
            }
            for (uint32_t c = 0; c < a.count; c++) {""",
    ).replace("                default: std::memcpy(&v[c], p + 4 * c, 4);", "")
    source = source.replace(
        "        for (auto &e : cache) e.index = ~0u;",
        "        if (indexed) for (auto &e : cache) e.index = ~0u;",
    )
    source = source.replace("#include <cmath>", "#include <cmath>\n#include <immintrin.h>")
    source = source.replace(
        "    for (int c = 0; c < 4; c++) v.a[COLOR + c] = std::fmin(std::fabs(v.a[COLOR + c]), 1.0f);",
        """    const __m128 color = _mm_loadu_ps(v.a + COLOR);
    const __m128 magnitude = _mm_andnot_ps(_mm_set1_ps(-0.0f), color);
    // MINPS selects the second operand for NaN, matching fmin here.
    _mm_storeu_ps(v.a + COLOR, _mm_min_ps(magnitude, _mm_set1_ps(1.0f)));""",
    )
    source = source.replace(
        "    if (n >= 512) {",
        """    if (n >= 512 && !indexed) {
        // Sequential draws have no repeated indices to look up or restore.
        static std::vector<Vertex> shaded;
        shaded.resize(n);
        const uint32_t first = regs[VERTEX_OFFSET];
        workers().run(n, [&](size_t begin, size_t end) {
            Vec4 attrs[16];
            for (size_t k = begin; k < end; ++k) {
                loader.read(first + uint32_t(k), attrs);
                shaded[k] = shade(attrs, map);
            }
        });
        for (const Vertex &v : shaded) assembler.push(v);
        w = shaded.back().a[POS + 3];
    } else if (n >= 512) {""",
    )
    source = source.replace(
        "    void push(const Vertex &v) {",
        """    template <class VertexAt>
    void push_range(uint32_t count, VertexAt vertex_at) {
        const uint32_t topology = (regs[PRIMITIVE_CONFIG] >> 8) & 3;
        uint32_t i = 0;
        if (topology != 1 && topology != 2 && list_count == 0) {
            // Complete lists can be emitted directly from the shaded vertices.
            for (; count - i >= 3; i += 3)
                emit_triangle(vertex_at(i), vertex_at(i + 1), vertex_at(i + 2));
        }
        for (; i < count; ++i) push(vertex_at(i));
    }

    void push(const Vertex &v) {""",
    ).replace(
        "        for (const Vertex &v : shaded) assembler.push(v);",
        "        assembler.push_range(n, [&](uint32_t i) -> const Vertex & { return shaded[i]; });",
    ).replace(
        "        for (uint32_t i = 0; i < n; i++) assembler.push(shaded[size_t(slot[index_at(i)])]);",
        """        assembler.push_range(n, [&](uint32_t i) -> const Vertex & {
            return shaded[size_t(slot[index_at(i)])];
        });""",
    )
    return source.replace("shade(attrs, map)", "shade(attrs, map, compiled)")


def shader(source):
    source = source.replace('#include "log.h"', '#include "log.h"\n#include "pica_shader_arithmetic.h"')
    source = source.replace(between(source, "// 0 * anything", "struct Frame"), "")
    source = source.replace(between(source, "    static const Vec4 ones", "    auto evaluate"), "")
    source = source.replace("    int32_t addr[3] = {0, 0, 0}; // a0.x, a0.y, aL",
                            "    int32_t addr[4] = {}; // constant zero, a0.x, a0.y, aL")
    source = source.replace("addr[2] += f.increment;", "addr[3] += f.increment;")
    source = source.replace("addr[2] = iu[1];", "addr[3] = iu[1];")
    return source.replace(between(source, "        // arithmetic:", "        // flow control"),
                          """        if (op < 0x20 || op >= 0x2E) {
            run_arithmetic(s, pc, ins, in, out, tmp, addr, cond);
            ++pc;
            continue;
        }

""")


def vertex_workers(source):
    source = source.replace("#include <thread>", """#include <thread>
#ifdef _WIN32
#include <bit>
#include <windows.h>
#else
#include <sched.h>
#endif""")
    source = source.replace(
        "        unsigned hw = std::thread::hardware_concurrency();",
        """        unsigned hw = std::thread::hardware_concurrency();
#ifdef _WIN32
        DWORD_PTR allowed = 0, system = 0;
        if (GetProcessAffinityMask(GetCurrentProcess(), &allowed, &system) && allowed)
            hw = std::popcount(allowed);
#else
        cpu_set_t allowed;
        if (sched_getaffinity(0, sizeof allowed, &allowed) == 0)
            hw = CPU_COUNT(&allowed);
#endif""",
    )
    source = source.replace("#include <condition_variable>", "#include <atomic>")
    source = source.replace(between(source, "        if (lanes == 1 || count < 64)", "    void slice("),
                            """        if (lanes == 1 || count < 256) return fn(0, count);
        job = &fn;
        job_count = count;
        pending.store(lanes - 1, std::memory_order_relaxed);
        generation.fetch_add(1, std::memory_order_release);
        generation.notify_all();
        slice(0, fn, count);
        for (int left = pending.load(std::memory_order_acquire); left;
             left = pending.load(std::memory_order_acquire))
            pending.wait(left, std::memory_order_acquire);
    }

private:
    int lanes = 1;
    std::atomic<int> pending{0};
    std::atomic<uint64_t> generation{0};
    size_t job_count = 0;
    const std::function<void(size_t, size_t)> *job = nullptr;

""")
    return source.replace(between(source, "        uint64_t seen = 0;", "\n};\n\nWorkers &workers"),
                          """        uint64_t seen = 0;
        for (;;) {
            generation.wait(seen, std::memory_order_acquire);
            seen = generation.load(std::memory_order_acquire);
            slice(lane, *job, job_count);
            if (pending.fetch_sub(1, std::memory_order_acq_rel) == 1) pending.notify_one();
        }
    }""")


def transfer(source):
    source = source.replace(
        "void display_transfer(uint32_t in, uint32_t out, uint32_t in_dims, uint32_t out_dims, uint32_t flags) {",
        "void display_transfer(uint32_t in, uint32_t out, uint32_t in_dims, uint32_t out_dims, uint32_t flags, bool right_eye) {")
    source = source.replace("    scene_frame_done(in_h);", "    if (!right_eye) scene_frame_done(out_h);")
    source = source.replace("gpu::display_transfer(in, out, in_w, in_h, out_w, out_h, flags)",
                            "gpu::display_transfer(in, out, in_w, in_h, out_w, out_h, flags, right_eye)")
    return source.replace("    auto src_offset = [&](uint32_t x, uint32_t y) {",
                          """    // These RGB565 transfers only untile/crop. Copy the packed pixels
    // directly, preserving all bits and visiting memory in tile order.
    if (in_fmt == FB_RGB565 && out_fmt == FB_RGB565 && !input_linear && !tiled_both &&
        !scale && w <= in_w && h <= in_h && (in_w % 8) == 0 && (w % 8) == 0 && (h % 8) == 0 &&
        (uintptr_t(src) + uint64_t(in_w) * in_h * 2 <= uintptr_t(dst) ||
         uintptr_t(dst) + uint64_t(w) * h * 2 <= uintptr_t(src))) {
        for (uint32_t y = 0; y < h; y += 8)
            for (uint32_t x = 0; x < w; x += 8) {
                const uint8_t *tile = src + 2 * (y * in_w + x * 8);
                for (uint32_t row = 0; row < 8; ++row) {
                    const uint32_t target_y = flip ? h - 1 - (y + row) : y + row;
                    uint8_t *target = dst + 2 * (target_y * w + x);
                    for (uint32_t col = 0; col < 8; col += 2)
                        std::memcpy(target + col * 2, tile + morton8(col, row) * 2, 4);
                }
            }
        return;
    }
    auto src_offset = [&](uint32_t x, uint32_t y) {""")


def texture(source):
    source = source.replace("void decode_texture(const Texture &t, uint8_t *rgba) {",
                          """void decode_texture(const Texture &t, uint8_t *rgba) {
    if (t.format == T_RGBA8) {
        for (uint32_t y = 0; y < t.height; y += 8)
            for (uint32_t x = 0; x < t.width; x += 8) {
                const uint8_t *tile = t.data + 4 * (y * t.width + x * 8);
                for (uint32_t row = 0; row < 8; ++row) {
                    auto *out = rgba + 4 * ((y + row) * t.width + x);
                    for (uint32_t col = 0; col < 8; ++col) {
                        uint32_t pixel;
                        std::memcpy(&pixel, tile + morton8(col, row) * 4, 4);
                        pixel = SDL_Swap32(pixel);
                        std::memcpy(out + col * 4, &pixel, 4);
                    }
                }
            }
        return;
    }
    if (t.format == T_RGB565 || t.format == T_RGB5A1 || t.format == T_RGBA4) {
        const uint32_t format = t.format == T_RGB565 ? FB_RGB565 : t.format == T_RGB5A1 ? FB_RGB5A1 : FB_RGBA4;
        for (uint32_t y = 0; y < t.height; y += 8)
            for (uint32_t x = 0; x < t.width; x += 8) {
                const uint8_t *tile = t.data + 2 * (y * t.width + x * 8);
                for (uint32_t row = 0; row < 8; ++row) {
                    auto *out = rgba + 4 * ((y + row) * t.width + x);
                    for (uint32_t col = 0; col < 8; ++col) {
                        const Rgba pixel = fb_decode(format, tile + morton8(col, row) * 2);
                        std::memcpy(out + col * 4, &pixel, 4);
                    }
                }
            }
        return;
    }
    if (t.format == T_ETC1 || t.format == T_ETC1A4) {
        const bool alpha = t.format == T_ETC1A4;
        const uint32_t block_bytes = alpha ? 16 : 8;
        const auto *block = t.data;
        for (uint32_t y = 0; y < t.height; y += 8)
            for (uint32_t x = 0; x < t.width; x += 8)
                for (uint32_t dy = 0; dy < 8; dy += 4)
                    for (uint32_t dx = 0; dx < 8; dx += 4, block += block_bytes) {
                        uint64_t colors, alphas = UINT64_MAX;
                        if (alpha) std::memcpy(&alphas, block, 8);
                        std::memcpy(&colors, block + (alpha ? 8 : 0), 8);
                        for (uint32_t row = 0; row < 4; ++row) {
                            auto *out = rgba + 4 * ((y + dy + row) * t.width + x + dx);
                            for (uint32_t col = 0; col < 4; ++col) {
                                Rgba pixel = etc1(colors, col, row);
                                pixel.a = expand4(uint32_t(alphas >> (4 * (4 * col + row))) & 15);
                                std::memcpy(out + 4 * col, &pixel, 4);
                            }
                        }
                    }
        return;
    }""").replace("#include <algorithm>", "#include <algorithm>\n#include <cstring>\n#include <SDL3/SDL_endian.h>")
    return source.replace("Rgba sample_texture(const Texture &t, float u, float v) {",
                          """void update_etc1a4(const Texture &t, uint8_t *previous, uint8_t *rgba) {
    const uint8_t *block = t.data;
    for (uint32_t y = 0; y < t.height; y += 8)
        for (uint32_t x = 0; x < t.width; x += 8)
            for (uint32_t dy = 0; dy < 8; dy += 4)
                for (uint32_t dx = 0; dx < 8; dx += 4, block += 16, previous += 16) {
                    if (!std::memcmp(previous, block, 16)) continue;
                    std::memcpy(previous, block, 16);
                    uint64_t colors, alphas;
                    std::memcpy(&alphas, block, 8);
                    std::memcpy(&colors, block + 8, 8);
                    for (uint32_t row = 0; row < 4; ++row) {
                        auto *out = rgba + 4 * ((y + dy + row) * t.width + x + dx);
                        for (uint32_t col = 0; col < 4; ++col) {
                            Rgba pixel = etc1(colors, col, row);
                            pixel.a = expand4(uint32_t(alphas >> (4 * (4 * col + row))) & 15);
                            std::memcpy(out + 4 * col, &pixel, 4);
                        }
                    }
                }
}

Rgba sample_texture(const Texture &t, float u, float v) {""")


def applets(source):
    return source.replace(
        '#include "log.h"', '#include "log.h"\n#include "memory.h"\n#include <cstring>\n#include <vector>').replace(
        "constexpr uint32_t SIGNAL_WAKEUP = 1;",
        "constexpr uint32_t SIGNAL_WAKEUP = 1;\n"
        "constexpr uint32_t APPID_MII_SELECTOR = 0x402;\n"
        "constexpr uint32_t APPID_ERROR = 0x406;\n"
        "constexpr uint32_t SIGNAL_RESPONSE = 3;\n"
        "constexpr uint32_t SIGNAL_WAKEUP_BY_EXIT = 10;\n"
        "constexpr uint32_t ERROR_PARAM_SIZE = 0xf80;\n"
        "constexpr uint32_t ERROR_RESULT_OFFSET = 0xf70;").replace(
        "namespace hle {\nnamespace {",
        "namespace hle {\nvoid reply_sm3dl_shared_font(Request &req);\n"
        "void reply_apt_wrap(Request &req);\n"
        "std::vector<uint8_t> local_mii_selection();\nnamespace {").replace(
        "    Parameter parameter;",
        "    Parameter parameter;\n    uint32_t prepared_applet = 0;\n    std::vector<uint8_t> applet_reply;").replace(
        "            r.push(0); // parameter data size",
        "            const auto size = parameter.signal == SIGNAL_WAKEUP_BY_EXIT\n"
        "                ? std::min<uint32_t>(req.arg(1), uint32_t(applet_reply.size())) : 0;\n"
        "            r.push(size);").replace(
        "            r.push_handles({parameter.handle}, true);",
        """            auto handle = parameter.handle;
            if (handle && req.id() == 0x000E)
                handle = kernel::add_handle(kernel::get_handle(handle));
            r.push_handles({handle}, true);""").replace(
        "            req.push_static_buffer(r, 0, nullptr, 0);",
        "            req.push_static_buffer(r, 0, applet_reply.data(), size);").replace(

        "app == APPID_APPLICATION || app == 0;",
        "app == APPID_APPLICATION || app == 0 || app == prepared_applet;").replace(
        "        case 0x004B:",
        """        case 0x0006: { // GetAppletInfo
            if (req.arg(0) != APPID_MII_SELECTOR || prepared_applet != APPID_MII_SELECTOR) {
                req.reply(1, 0, 0xc880cffa);
                break;
            }
            auto r = req.reply(7, 0);
            r.push(0x0000d402); // European Mii Selector title ID, low word.
            r.push(0x00040030);
            r.push(0); // NAND
            r.push(1); // Registered
            r.push(1); // Loaded
            r.push(1); // Library applet position
            break;
        }
        case 0x000C: { // SendParameter: the applet requests shared capture memory.
            if (!prepared_applet || req.arg(1) != prepared_applet ||
                req.arg(2) != 2 || req.arg(3) != 0x20) unimplemented(*this, req);
            const auto size = mem::read32(req.arg(7));
            if (!size || size > 0x00400000) {
                req.reply(1, 0, kernel::RESULT_INVALID_COMBINATION);
                break;
            }
            auto capture = std::make_shared<kernel::SharedMemory>();
            capture->name = "APT library applet capture";
            capture->size = size;
            req.reply(1, 0);
            send_parameter({prepared_applet, SIGNAL_RESPONSE, kernel::add_handle(capture)});
            break;
        }
        case 0x0016: // PreloadLibraryApplet
        case 0x0017: // FinishPreloadingLibraryApplet
        case 0x0018: // PrepareToStartLibraryApplet
            if (req.arg(0) != APPID_ERROR && req.arg(0) != APPID_MII_SELECTOR) unimplemented(*this, req);
            prepared_applet = req.arg(0);
            req.reply(1, 0);
            break;
        case 0x001E: { // StartLibraryApplet
            const auto applet = req.arg(0);
            if (!prepared_applet || applet != prepared_applet) unimplemented(*this, req);
            if (applet == APPID_MII_SELECTOR) {
                applet_reply = local_mii_selection();
                LOG("APT: selected the local Player Mii");
            } else {
                if (req.arg(1) != ERROR_PARAM_SIZE) unimplemented(*this, req);
                const auto *input = mem::ptr(req.arg(5));
                applet_reply.assign(input, input + req.arg(1));
                // Report dismissal and no agreement so the game may continue offline.
                std::fill_n(applet_reply.begin() + ERROR_RESULT_OFFSET, 6, uint8_t{0});
                uint32_t code;
                std::memcpy(&code, input + 4, sizeof code);
                LOG("APT: dismissed error display (type %u, code %u)", input[0], code);
            }
            prepared_applet = 0;
            req.reply(1, 0);
            send_parameter({applet, SIGNAL_WAKEUP_BY_EXIT, 0});
            break;
        }
        case 0x0040: // SendCaptureBufferInfo
            if (!prepared_applet || req.arg(0) != 0x20) unimplemented(*this, req);
            req.reply(1, 0);
            break;
        case 0x0044: // GetSharedFont
            reply_sm3dl_shared_font(req);
            break;
        case 0x0046: // Wrap
        case 0x0047: // Unwrap
            reply_apt_wrap(req);
            break;
        case 0x004B:""")


def native_timing_replace(source, anchor, replacement):
    if source.count(anchor) != 1:
        raise ValueError(f"Missing or ambiguous native timing anchor: {anchor.strip()}")
    return source.replace(anchor, replacement)


def native_course_gsp(source):
    return '#include "logic60.h"\n' + native_timing_replace(
        source, '            pica::gpu::vblank();\n            apply_swaps();',
        '''            logic60::vblank(pica::gpu::active());
            pica::gpu::vblank();
            const auto old_top = lcd[0].addr;
            apply_swaps();
            if (logic60::requested())
                logic60::presented(old_top != lcd[0].addr, pica::gpu::lcd_frame_sequence(lcd[0].addr));''')


def native_course_gpu(source):
    source = '#include "logic60.h"\n' + source
    source = native_timing_replace(source, '    uint32_t scanout_bytes = 0;',
                                   '    uint32_t scanout_bytes = 0;\n    uint64_t native_sequence = 0;')
    source = native_timing_replace(source, 'SDL_Mutex *lcd_lock;',
                                   'SDL_Mutex *lcd_lock;\nuint64_t native_scanout_serial = 0; // under lcd_lock')
    source = native_timing_replace(source, '    f.latest = slot;', '''    f.latest = slot;
    if (top && logic60::requested()) f.native_sequence = ++native_scanout_serial;''')
    source = native_timing_replace(source, 'SDL_GPUTexture *lcd_frame(uint32_t addr, int *width, int *height) {',
                                   '''uint64_t lcd_frame_sequence(uint32_t addr) {
    if (!ok || !addr) return 0;
    SDL_LockMutex(lcd_lock);
    const auto it = lcd.find(addr);
    const uint64_t sequence = it == lcd.end() ? 0 : it->second.native_sequence;
    SDL_UnlockMutex(lcd_lock);
    return sequence;
}

SDL_GPUTexture *lcd_frame(uint32_t addr, int *width, int *height) {''')
    source = native_timing_replace(source, '    bool want = interp_wanted.load();',
                                   '    bool want = interp_wanted.load() && !logic60::active();')
    return native_timing_replace(source, '    const uint64_t tick = vblanks.load();\n    if (!frame) {', '''    // Native simulation already supplies the frames: no synthetic frame or queue delay.
    if (logic60::active()) {
        smoother.previous = nullptr;
        smoother.original_pending = false;
        *interpolated = false;
        SDL_UnlockMutex(lcd_lock);
        return frame;
    }
    const uint64_t tick = vblanks.load();
    if (!frame) {''')


def prepare(upstream, output):
    for directory in ("src", "include"):
        shutil.copytree(upstream / directory, output / directory, dirs_exist_ok=True)
    src = output / "src"
    edit(src / "frontend/sdl.cpp", frontend)
    edit(src / "frontend/frontend.h", lambda source: source.replace(
        "const char *cli_dump, bool force_launcher, bool play", "const char *cli_dump").replace(
        "Input input();", "Input input();\nint verify_gamepad();\nint verify_aspect_ratio();").replace(
        "#include <cstdint>", "#include <cstdint>\n#include <vector>").replace(
        "// queues `frames` stereo", "// Signals that the LCD updates for one VBlank are ready.\n"
        "void finish_scanout(const std::vector<SDL_GPUTexture *> &retired);\n\n// queues `frames` stereo"))
    edit(src / "video/gpu/gpu.h", lambda source: source.replace(
        "#include <cstdint>", "#include <cstdint>\n#include <vector>").replace(
        "uint32_t out_w, uint32_t out_h,\n                      uint32_t flags);",
        "uint32_t out_w, uint32_t out_h,\n                      uint32_t flags, bool right_eye);").replace(
        "top_frame(int *width, int *height)", "top_frame(uint32_t address, int *width, int *height, bool *interpolated)").replace(
        "SDL_GPUTexture *lcd_frame(", "std::vector<SDL_GPUTexture *> take_retired_scanouts();\n"
        "uint64_t lcd_frame_sequence(uint32_t addr);\nSDL_GPUTexture *lcd_frame("))
    edit(src / "video/pica.h", lambda source: source.replace(
        "uint32_t in_dims, uint32_t out_dims, uint32_t flags);",
        "uint32_t in_dims, uint32_t out_dims, uint32_t flags, bool right_eye = false);").replace(
        "SceneInfo scene_info();", "SceneInfo scene_info();\nbool course_reserve_ready();"))
    edit(src / "frontend/games.h", lambda source: source.replace(
        'inline constexpr KnownDump KNOWN_DUMPS[] = {',
        'inline constexpr KnownDump KNOWN_DUMPS[] = {\n'
        '    {0x0004000000053F00, "sm3dl", "", "SuperMario3DLand", Region::EUR},'))
    edit(src / "platform.cpp", platform)
    edit(src / "frontend/settings.h", lambda source: source.replace(
        "    int volume = 100;", "    int volume = 25;\n    bool hd_textures = false;").replace("int hud_size = 80;", "int hud_size = 100;").replace(
        "    int resolution = 1;", "    int aspect_ratio = 0; // 0 original, 1 16:9, 2 21:9\n    int resolution = 1;").replace(
        "    void reset_controls();", '''    void reset_controls();
    void toggle_screen_layout() {
        single_screen = !single_screen;
        if (single_screen) {
            swap_screens = false;
            smart_layout = false;
            picture_in_picture = false;
        }
    }
    bool widescreen_layout() const { return single_screen && !smart_layout; }
    void toggle_secondary_screen() {
        if (widescreen_layout())
            picture_in_picture = !picture_in_picture;
        else
            swap_screens = !swap_screens;
    }'''))
    edit(src / "frontend/settings.cpp", lambda source: source.replace(
        'else if (k == "volume") volume = std::atoi(v.c_str());',
        'else if (k == "volume") volume = std::clamp(std::atoi(v.c_str()), 0, 100);').replace(
        'else if (k == "language") language = std::clamp(std::atoi(v.c_str()), 1, 5);',
        'else if (k == "language") language = std::atoi(v.c_str());').replace(
        '        else if (k == "frame_interpolation") frame_interpolation = b;\n', '').replace(
        '      << "frame_interpolation=" << frame_interpolation << "\\n"\n', '').replace(
        '    std::ifstream f(file());', '    bool has_aspect_ratio = false;\n    std::ifstream f(file());').replace(
        '        else if (k == "widescreen") widescreen = b;',
        '        else if (k == "hd_textures") hd_textures = b;\n'
        '        else if (k == "widescreen") widescreen = b;\n'
        '        else if (k == "aspect_ratio") {\n'
        '            aspect_ratio = std::clamp(std::atoi(v.c_str()), 0, 2);\n'
        '            has_aspect_ratio = true;\n'
        '        }').replace(
        '\n}\n\nvoid Settings::save() const',
        '\n    if (!has_aspect_ratio) aspect_ratio = widescreen ? 1 : 0;\n'
        '    widescreen = aspect_ratio != 0;\n}\n\nvoid Settings::save() const').replace(
        '      << "widescreen=" << widescreen << "\\n"',
        '      << "hd_textures=" << hd_textures << "\\n"\n'
        '      << "aspect_ratio=" << aspect_ratio << "\\n"\n'
        '      << "widescreen=" << widescreen << "\\n"'))
    edit(src / "video/pica.h", lambda source: source.replace(
        'void set_widescreen(bool on);',
        'void set_aspect_ratio(int mode);\nvoid set_window_top_margin(int margin);\nvoid set_widescreen(bool on);'))
    edit(src / "video/widescreen.cpp", lambda source: source.replace(
        'void set_widescreen(bool on) { requested_margin = on ? 14 : 0; }',
        'void set_aspect_ratio(int mode) {\n'
        '    constexpr int margins[] = {0, 14, 80};\n'
        '    requested_margin = margins[std::clamp(mode, 0, 2)];\n'
        '}\nvoid set_window_top_margin(int margin) { requested_margin = std::clamp(margin, 14, 80); }\n'
        'void set_widescreen(bool on) { set_aspect_ratio(on ? 1 : 0); }'))
    edit(src / "hle/cfg.cpp", lambda source: source.replace(
        '    default: return 110; // United Kingdom',
        '    case 8: return 94;  // Netherlands\n'
        '    case 9: return 98;  // Portugal\n'
        '    case 10: return 100; // Russia\n'
        '    default: return 110; // United Kingdom').replace(
        '            uint8_t language = l >= 1 && l <= 5 ? uint8_t(l) : LANGUAGE_ENGLISH;',
        '            const bool supported = (l >= 1 && l <= 5) || (l >= 8 && l <= 10);\n'
        '            uint8_t language = supported ? uint8_t(l) : LANGUAGE_ENGLISH;'))
    edit(src / "dump.h", lambda source: source.replace(
        "    uint64_t program_id() const",
        "    const auto &exefs_files() const { return exefs_files_; }\n    uint64_t program_id() const").replace(
        "    std::vector<uint8_t> exheader_, code_;",
        "    std::vector<uint8_t> exheader_, code_;\n    std::map<std::string, std::vector<uint8_t>> exefs_files_;"))
    edit(src / "dump.cpp", lambda source: source.replace(
        "    std::vector<uint8_t> exheader, code;",
        "    std::vector<uint8_t> exheader, code;\n    std::map<std::string, std::vector<uint8_t>> exefs_files;").replace(
        '        if (std::strncmp(reinterpret_cast<const char *>(e), ".code", 8) != 0) continue;',
        '''        const char *raw = reinterpret_cast<const char *>(e);
        std::string name(raw, strnlen(raw, 8));
        if (name == "icon" || name == "logo" || name == "banner") {
            uint64_t offset = uint64_t(u32(e + 8)) + 0x200;
            uint64_t size = u32(e + 12);
            if (offset + size > uint64_t(u32(h + 0x1A4)) * MEDIA_UNIT)
                fatal("Invalid ExeFS section: %s", name.c_str());
            auto &data = n.exefs_files[name];
            data.resize(size_t(size));
            read_at(exefs + offset, data.data(), data.size());
        }
        if (name != ".code") continue;''').replace(
        "    romfs_offset_ = game.romfs_offset",
        "    exefs_files_ = std::move(game.exefs_files);\n    romfs_offset_ = game.romfs_offset"))
    edit(src / "hle/gsp.cpp", lambda source: source.replace(
        "    } lcd[2];", "    } lcd[2];\n    std::array<uint32_t, 3> left_eye{};\n    std::array<uint32_t, 3> right_eye{};").replace(
        '            if (static const bool hold = std::getenv("YW2_GPU_HOLD_CPU") != nullptr; hold) {',
        """            static const bool hold = std::getenv("YW2_GPU_HOLD_CPU") != nullptr;
#ifdef __linux__
            // Keep software rendering and guest command completion on the same thread.
            if (hold || !pica::gpu::active()) {
#else
            if (hold) {
#endif""").replace(
        "            SDL_GPUTexture *frame = screen == 0 ? pica::gpu::top_frame(&gw, &gh) : nullptr;",
        """            bool interpolated = false;
            SDL_GPUTexture *frame = screen == 0 ? pica::gpu::top_frame(lcd[0].addr, &gw, &gh, &interpolated) : nullptr;
            if (screen == 0 && frame != previous_top_frame) {
                previous_top_frame = frame;
                if (frame) {
                    ++top_updates;
                    if (interpolated) ++frames_interpolated;
                }
            }""").replace(
        "        lcd[screen] = {info[1], info[3], info[4]};",
        """        if (screen == 0) {
            auto remember = [](auto &history, uint32_t address) {
                if (address && std::find(history.begin(), history.end(), address) == history.end()) {
                    std::rotate(history.rbegin(), history.rbegin() + 1, history.rend());
                    history.front() = address;
                }
            };
            remember(left_eye, info[1]);
            if (info[2] != info[1]) remember(right_eye, info[2]);
        }
        lcd[screen] = {info[1], info[3], info[4]};""").replace(
        """        case 0x03: // DisplayTransfer(in, out, in dims, out dims, flags)
            pica::display_transfer(c[1], c[2], c[3], c[4], c[5]);
            raise(PPF);
            break;""",
        """        case 0x03: { // DisplayTransfer
            const bool visible = std::find(left_eye.begin(), left_eye.end(), c[2]) != left_eye.end();
            const bool stereo_buffer = std::find(right_eye.begin(), right_eye.end(), c[2]) != right_eye.end();
            const bool top_copy = c[4] == (400u << 16 | 240u) && c[5] == 0x2000;
            const bool hidden_eye = c[2] && top_copy && !visible && (stereo_buffer || left_eye.back());
            pica::display_transfer(c[1], c[2], c[3], c[4], c[5], hidden_eye);
            raise(PPF);
            break;
        }""").replace(
        "            present();\n            raise(PDC0);",
        """            // Collect old scanouts before reading the current LCD textures. A
            // texture retired later remains alive until we publish again.
            auto retired = pica::gpu::take_retired_scanouts();
            present();
            frontend::finish_scanout(retired);
            raise(PDC0);""").replace(
        "    void set_buffer(uint32_t screen, const uint32_t *info) {",
        "    void set_buffer(uint32_t screen, const uint32_t *info) {").replace(
        "        lcd[screen] = {info[1], info[3], info[4]};",
        "        if (screen == 0 && lcd[0].addr != info[1]) ++frames_rendered;\n"
        "        lcd[screen] = {info[1], info[3], info[4]};").replace(
        "            if ((c[3] >> 16) == 400) frames_rendered++;\n", "").replace(
        "    uint32_t frames_rendered = 0; // display transfers to the top screen, for YW2_FPS",
        "    uint32_t frames_rendered = 0; // new top-screen buffers for SM3DL_FPS\n"
        "    SDL_GPUTexture *previous_top_frame = nullptr;\n"
        "    uint32_t top_updates = 0;\n"
        "    uint32_t frames_interpolated = 0;\n"
        "    std::chrono::steady_clock::time_point fps_since = std::chrono::steady_clock::now();").replace(
        "            pica::SceneInfo si = pica::scene_info();",
        "            const auto now = std::chrono::steady_clock::now();\n"
        "            const double seconds = std::chrono::duration<double>(now - fps_since).count();\n"
        "            fps_since = now;\n"
        "            pica::SceneInfo si = pica::scene_info();").replace(
        "frames_rendered / 5.0", "frames_rendered / seconds").replace(
        "            frames_rendered = 0;",
        """            if (frames_interpolated)
                LOG("graphics: %.1f top LCD updates/s (%.1f original + %.1f extra refreshes)",
                    top_updates / seconds, (top_updates - frames_interpolated) / seconds,
                    frames_interpolated / seconds);
            frames_rendered = frames_interpolated = top_updates = 0;"""))
    edit(src / "video/color.h", lambda source: source.replace(
        "inline uint32_t fb_bpp(uint32_t format)",
        """// The PICA render-target register swaps the two 16-bit format IDs used by GX and LCD.
inline uint32_t render_target_format(uint32_t reg) {
    uint32_t format = (reg >> 16) & 7;
    if (format == 2) return FB_RGB5A1;
    if (format == 3) return FB_RGB565;
    return format;
}

inline uint32_t fb_bpp(uint32_t format)"""))
    edit(src / "hle/gsp.cpp", native_course_gsp)
    edit(src / "video/gpu/gpu.cpp", lambda source: native_course_gpu(gpu(source)))
    edit(src / "video/pica.cpp", lambda source: vertex_workers(pica(source)))
    edit(src / "video/raster.cpp", lambda source: source.replace(
        "cur.color_format = (regs[COLOR_FORMAT] >> 16) & 7;",
        "cur.color_format = render_target_format(regs[COLOR_FORMAT]);"))
    edit(src / "video/shader.cpp", shader)
    edit(src / "video/transfer.cpp", transfer)
    edit(src / "video/internal.h", lambda source: source.replace(
        "void decode_texture(const Texture &t, uint8_t *rgba);",
        "void decode_texture(const Texture &t, uint8_t *rgba);\n"
        "void update_etc1a4(const Texture &t, uint8_t *previous, uint8_t *rgba);"))
    edit(src / "video/texture.cpp", texture)
    edit(src / "hle/fs.cpp", filesystem)
    edit(src / "hle/service.cpp", lambda source: source.replace(
        "void register_dsp();", "void register_dsp();\nvoid register_microphone();").replace(
        "    register_dsp();", "    register_dsp();\n    register_microphone();"))
    edit(src / "hle/apt.cpp", applets)
    # The SDK puts the result immediately after the error type/revision word.
    edit(src / "hle/err.cpp", lambda source: source.replace(
        "name, w[2], w[3], w[6], w[5]", "name, w[1], w[2], w[6], w[5]"))
    for path in src.rglob("*"):
        if path.suffix in (".h", ".cpp"):
            content = path.read_text(encoding="utf-8")
            if "YW2_" in content:
                path.write_text(content.replace("YW2_", "SM3DL_"), encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("upstream", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    prepare(args.upstream, args.output)
