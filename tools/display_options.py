"""Add the saved FPS and texture choices to the native frontend."""


def once(source, old, new):
    if source.count(old) != 1:
        raise ValueError(f'Unexpected display options anchor: {old.splitlines()[0]}')
    return source.replace(old, new)


def settings_fields(source):
    return once(source, '    bool hd_textures = false;',
        '    int hd_quality = 0; // 0 None, 1 1080p, 2 4K\n    int fps_target = 60;')


def settings_options(source):
    source = once(source, '    bool has_aspect_ratio = false;',
        '    bool has_aspect_ratio = false, has_hd_quality = false;\n    int legacy_hd = 0;')
    source = once(source, '        else if (k == "hd_textures") hd_textures = b;', '''        else if (k == "hd_textures") legacy_hd = b ? 1 : 0;
        else if (k == "hd_quality") {
            hd_quality = v == "1" ? 1 : v == "2" ? 2 : 0;
            has_hd_quality = true;
        }
        else if (k == "fps_target") fps_target = v == "30" ? 30 : 60;''')
    source = once(source, '    if (!has_aspect_ratio) aspect_ratio = widescreen ? 1 : 0;',
        '    if (!has_hd_quality) hd_quality = legacy_hd;\n    if (!has_aspect_ratio) aspect_ratio = widescreen ? 1 : 0;')
    return once(source, '      << "hd_textures=" << hd_textures << "\\n"',
        '      << "hd_quality=" << hd_quality << "\\n"\n      << "fps_target=" << fps_target << "\\n"')


def texture_options(source):
    source = once(source, 'std::atomic<bool> hd_pack_requested{false};\nbool hd_pack_enabled = false;',
        'std::atomic<int> hd_pack_requested{0};\nint hd_pack_quality = 0;')
    source = once(source, '    if (hd_pack_enabled) pack = sm3dl::load_pack_texture(t.data, t.bytes, t.width, t.height, t.format);\n'
        '    const HdImage *hd = pack.rgba.empty() ? hd_texture(h) : nullptr;',
        '    if (hd_pack_quality) pack = sm3dl::load_pack_texture(t.data, t.bytes, t.width, t.height, t.format, hd_pack_quality);\n'
        '    const HdImage *hd = hd_pack_quality && pack.rgba.empty() ? hd_texture(h) : nullptr;')
    source = once(source, 'void set_hd_textures(bool enabled) {\n'
        '    hd_pack_requested.store(enabled && sm3dl::has_hd_texture_pack(), std::memory_order_relaxed);',
        'void set_hd_textures(int quality) {\n'
        '    hd_pack_requested.store(sm3dl::has_hd_texture_pack(quality) ? quality : 0, std::memory_order_relaxed);')
    source = once(source, '    const bool hd = hd_pack_requested.load(std::memory_order_relaxed);\n'
        '    if (hd != hd_pack_enabled) {', '    const int hd = hd_pack_requested.load(std::memory_order_relaxed);\n'
        '    if (hd != hd_pack_quality) {\n        flush(); // finish draws that still reference the old pack')
    return once(source, '        hd_pack_enabled = hd;\n        LOG("HD textures: %s", hd ? "on" : "off");',
        '        hd_pack_quality = hd;\n        LOG("HD textures: %s", sm3dl::hd_quality_name(hd));')


def frontend_options(source):
    source = '#include "display_options.h"\n' + source
    source = once(source, '    s.load();\n    if (cli_dump)', '    if (cli_dump)')
    source = once(source, '    Settings &s = settings();\n    if (std::getenv("SM3DL_HEADLESS"))',
        '    Settings &s = settings();\n    s.load();\n    sm3dl::set_boot_fps(s.fps_target);\n    if (std::getenv("SM3DL_HEADLESS"))')
    source = once(source, '    if (pica::gpu::active()) pica::gpu::set_hd_textures(s.hd_textures);',
        '    if (pica::gpu::active()) pica::gpu::set_hd_textures(s.hd_quality);')
    source = once(source, '    for (;;) {\n        SDL_Event e;\n        while (SDL_PollEvent(&e)) {\n#ifdef _WIN32', '''    sm3dl::CursorIdle cursor{SDL_GetTicks()};
    const auto game_window = SDL_GetWindowID(window);
    auto mouse_active = [&] {
        cursor.moved(SDL_GetTicks());
        if (!SDL_CursorVisible()) SDL_ShowCursor();
    };
    auto fps_message = [&] {
        const auto fps = std::to_string(s.fps_target) + " FPS";
        if (s.fps_target == sm3dl::boot_fps()) show_message(fps);
        else show_message(s.language == 2 ? "Redemarre le jeu pour appliquer " + fps : "Restart the game to apply " + fps);
    };
    for (;;) {
        SDL_Event e;
        while (SDL_PollEvent(&e)) {
            if ((e.type == SDL_EVENT_MOUSE_MOTION && e.motion.windowID == game_window &&
                 (e.motion.xrel != 0.f || e.motion.yrel != 0.f)) ||
                (e.type == SDL_EVENT_MOUSE_BUTTON_DOWN && e.button.windowID == game_window) ||
                (e.type == SDL_EVENT_MOUSE_BUTTON_UP && e.button.windowID == game_window) ||
                ((e.type == SDL_EVENT_WINDOW_MOUSE_ENTER || e.type == SDL_EVENT_WINDOW_MOUSE_LEAVE ||
                  e.type == SDL_EVENT_WINDOW_FOCUS_LOST || e.type == SDL_EVENT_WINDOW_FOCUS_GAINED) &&
                 e.window.windowID == game_window)) mouse_active();
#ifdef _WIN32
            if (e.type == ResolutionMenu::fps_changed_event()) { fps_message(); continue; }
            if (e.type == ResolutionMenu::cursor_activity_event()) { mouse_active(); continue; }''')
    source = once(source, '''                e.key.mod & SDL_KMOD_CTRL && pica::gpu::active() && sm3dl::has_hd_texture_pack()) {
                s.hd_textures = !s.hd_textures;
                pica::gpu::set_hd_textures(s.hd_textures);
                s.save();
                show_message(s.hd_textures ? "HD on" : "HD off");''', '''                e.key.mod & SDL_KMOD_CTRL && pica::gpu::active()) {
                do { s.hd_quality = (s.hd_quality + 1) % 3; }
                while (s.hd_quality && !sm3dl::has_hd_texture_pack(s.hd_quality));
                pica::gpu::set_hd_textures(s.hd_quality);
                s.save();
                show_message(std::string("HD: ") + sm3dl::hd_quality_name(s.hd_quality));''')
    source = once(source, '            if (top_screen_16_by_9()) {\n                const auto flags', '''            if (e.type == SDL_EVENT_KEY_DOWN && !e.key.repeat && e.key.scancode == SDL_SCANCODE_F6 &&
                e.key.mod & SDL_KMOD_CTRL) {
                s.fps_target = s.fps_target == 30 ? 60 : 30;
                s.save();
                fps_message();
                continue;
            }
            if (top_screen_16_by_9()) {
                const auto flags''')
    return once(source, '        // smart layout: follow what the game shows', '''        if (SDL_GetMouseFocus() == window && !SDL_GetMouseState(nullptr, nullptr) &&
            cursor.expired(SDL_GetTicks()) && SDL_CursorVisible()) SDL_HideCursor();

        // smart layout: follow what the game shows''')
