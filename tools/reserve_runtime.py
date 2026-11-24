"""Deliver the controller shortcut on the guest touchscreen sampling clock."""
from display_options import once
from prepare_runtime import between


def reserve_frontend(source):
    source = once(source, '    sm3dl::ReserveTap reserve_tap;\n', '')
    source = once(source, 'std::mutex input_lock;\nInput current_input;',
                  'std::mutex input_lock;\nInput current_input;\nsm3dl::ReserveTap reserve_tap;')
    source = once(source, '                reserve_tap.press(SDL_GamepadButton(e.gbutton.button), pica::course_reserve_ready(), SDL_GetTicks());',
        '''                if (e.gbutton.button == SDL_GAMEPAD_BUTTON_DPAD_UP) {
                    std::lock_guard lk(input_lock);
                    reserve_tap.press(SDL_GAMEPAD_BUTTON_DPAD_UP, pica::course_reserve_ready(), SDL_GetTicks());
                }''')
    source = once(source, '            reserve_tap.apply(in, pica::course_reserve_ready(), SDL_GetTicks());\n', '')
    source = once(source, '    control.apply(in);\n    title_capture.press(top_frames, in);',
        '    control.apply(in);\n    reserve_tap.sample(in, pica::course_reserve_ready(), SDL_GetTicks());\n'
        '    title_capture.press(top_frames, in);')

    old = between(source, '        Input touch;\n        reserve.apply', '        SDL_CloseGamepad(gamepad);')
    return once(source, old, '''        sm3dl::CourseTouchReadiness hud;
        hud.publish(true, false);
        hud.publish(false, false);
        if (!hud.active()) fatal("A partial HUD frame blocked the reserve shortcut");
        Input touch;
        for (unsigned i = 0; i < sm3dl::ReserveTap::samples; ++i) {
            touch = {};
            reserve.sample(touch, hud.active(), 1220 + i * 20);
            if (!touch.touching || touch.touch_x != sm3dl::reserve_x || touch.touch_y != sm3dl::reserve_y)
                fatal("A single D-pad press did not reach the guest touchscreen");
        }
        touch = {};
        reserve.sample(touch, true, 1370);
        if (touch.touching) fatal("Reserve tap was repeated or remained pressed");
        hud.publish(true, true);
        if (hud.active()) fatal("Pause must block the shortcut immediately");
        reserve.press(SDL_GAMEPAD_BUTTON_DPAD_UP, hud.active(), 1400);
        reserve.sample(touch, true, 1450);
        if (touch.touching) fatal("Menu input leaked into a course");
        hud.publish(true, false);
        for (int i = 0; i < 5; ++i) hud.publish(false, false);
        if (hud.active()) fatal("The reserve shortcut remained armed after leaving a course");
        reserve.press(SDL_GAMEPAD_BUTTON_DPAD_UP, true, 1500);
        touch = {};
        touch.touching = true;
        touch.touch_x = 30;
        reserve.sample(touch, true, 1520);
        if (touch.touch_x != 30) fatal("The shortcut hijacked mouse input");
        touch = {};
        reserve.sample(touch, true, 1550);
        if (!touch.touching || touch.touch_x != sm3dl::reserve_x)
            fatal("The queued reserve tap was lost after mouse release");
''')


def reserve_pica(source):
    return once(source, 'return course_touch_scan.ready.load(std::memory_order_relaxed);',
                'return course_touch_scan.readiness.active();')
