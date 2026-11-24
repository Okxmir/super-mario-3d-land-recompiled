"""Route the host shortcut to the original in-game reserve command."""
from display_options import once
from prepare_runtime import between


def reserve_frontend(source):
    source = once(source, '    sm3dl::ReserveTap reserve_tap;\n', '')
    source = once(source, 'std::mutex input_lock;\nInput current_input;',
                  'std::mutex input_lock;\nInput current_input;\nsm3dl::ReserveCommand reserve_command;\nbool reserve_up_queued = false;')
    source = once(source, '    for (;;) {\n        SDL_Event e;\n        while (SDL_PollEvent(&e)) {\n            if ((e.type == SDL_EVENT_MOUSE_MOTION',
        '    for (;;) {\n        bool reserve_edge = false;\n        SDL_Event e;\n        while (SDL_PollEvent(&e)) {\n            if ((e.type == SDL_EVENT_MOUSE_MOTION')
    source = once(source, '            case SDL_EVENT_KEY_DOWN:\n                if (e.key.repeat) break;',
        '            case SDL_EVENT_KEY_DOWN:\n                if (e.key.repeat) break;\n'
        '                if (e.key.scancode == s.keys[C_UP]) reserve_edge = true;')
    source = once(source, '                reserve_tap.press(SDL_GamepadButton(e.gbutton.button), pica::course_reserve_ready(), SDL_GetTicks());',
        '                if (e.gbutton.button == SDL_GAMEPAD_BUTTON_DPAD_UP) reserve_edge = true;')
    source = once(source, '            reserve_tap.apply(in, pica::course_reserve_ready(), SDL_GetTicks());',
        '            reserve_up_queued |= reserve_edge;')
    source = once(source, '\nInput input() {', '''
static bool trace_reserve_command() {
    static const bool enabled = std::getenv("SM3DL_TRACE_RESERVE") != nullptr;
    return enabled;
}

extern "C" int sm3dl_take_reserve_command() {
    const auto now = SDL_GetTicks();
    if (!reserve_command.take(now)) return 0;
    if (trace_reserve_command()) LOG("reserve command: %llums native activation frame=%d",
                                    (unsigned long long)now, top_frames.load());
    return 1;
}

Input input() {''')
    source = once(source, '    control.apply(in);\n    title_capture.press(top_frames, in);',
        '''    control.apply(in);
    const auto now = SDL_GetTicks();
    if (reserve_command.sample(in, pica::course_reserve_ready(), now, reserve_up_queued) &&
            trace_reserve_command())
        LOG("reserve command: %llums single press queued frame=%d", (unsigned long long)now, top_frames.load());
    reserve_up_queued = false;
    title_capture.press(top_frames, in);''')

    old = between(source, '        if (!device.button(SDL_GAMEPAD_BUTTON_DPAD_UP, true))', '        SDL_CloseGamepad(gamepad);')
    return once(source, old, '''        if (!device.button(SDL_GAMEPAD_BUTTON_DPAD_UP, true)) fatal("Cannot press D-pad Up");
        SDL_PumpEvents();
        SDL_Event event;
        bool edge = false;
        while (SDL_PollEvent(&event)) {
            if (event.type == SDL_EVENT_GAMEPAD_BUTTON_DOWN && event.gbutton.which == device.instance() &&
                    event.gbutton.button == SDL_GAMEPAD_BUTTON_DPAD_UP) edge = true;
        }
        if (!edge) fatal("A single virtual D-pad press did not generate an event");
        static_assert(sm3dl::is_course_hud(sm3dl::course_hud_parts & ~sm3dl::course_reserve));
        static_assert(!sm3dl::is_course_hud(sm3dl::course_reserve | sm3dl::course_lives));
        sm3dl::ReserveCommand reserve;
        sm3dl::CourseTouchReadiness hud;
        hud.publish(true, false);
        hud.publish(false, false);
        if (!hud.active()) fatal("A partial HUD frame blocked the reserve shortcut");
        Input input;
        input.buttons = BTN_UP | BTN_B;
        if (!reserve.sample(input, hud.active(), 1000, edge) || input.touching || input.buttons != BTN_B)
            fatal("One D-pad press must queue a reserve command without a fake touch");
        if (!reserve.take(1000) || reserve.take(1000)) fatal("Reserve command was not immediate and one-shot");
        input.buttons = BTN_UP;
        if (reserve.sample(input, true, 1017) || reserve.take(1017)) fatal("Holding Up repeated the command");
        hud.publish(true, true);
        if (hud.active()) fatal("Pause must block the shortcut immediately");
        input.buttons = BTN_UP;
        if (reserve.sample(input, hud.active(), 1050, true) || input.buttons != BTN_UP || reserve.take(1050))
            fatal("Menu input was intercepted or leaked into the course");
        hud.publish(true, false);
        for (int i = 0; i < 5; ++i) hud.publish(false, false);
        if (hud.active()) fatal("The reserve shortcut remained armed after leaving a course");
        input = {};
        input.touching = true;
        input.touch_x = 30;
        if (!reserve.sample(input, true, 1100, true) || !input.touching || input.touch_x != 30)
            fatal("The shortcut hijacked mouse input");
        if (reserve.take(1300)) fatal("An old reserve command leaked into a later state");
''')


def reserve_pica(source):
    return once(source, 'return course_touch_scan.ready.load(std::memory_order_relaxed);',
                'return course_touch_scan.readiness.active();')
