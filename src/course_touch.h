#pragma once

#include "frontend/frontend.h"

#include <SDL3/SDL_events.h>
#include <algorithm>
#include <cstdint>

namespace sm3dl {

inline constexpr int reserve_x = 160, reserve_y = 131;
inline constexpr unsigned course_lives = 1, course_reserve = 2, course_medals = 4, course_level = 8;
inline constexpr unsigned reserve_caption = 16;
inline constexpr unsigned course_hud_parts = course_lives | course_reserve | course_medals | course_level;

// The original lower LCD is rotated in PICA clip space.
struct CourseHudBounds {
    float left = 320, right = 0, top = 240, bottom = 0;

    void add(float x, float y, float w) {
        x = (1 - x / w) * 120;
        y = (1 - y / w) * 160;
        left = std::min(left, y), right = std::max(right, y);
        top = std::min(top, x), bottom = std::max(bottom, x);
    }

    unsigned hud_part(unsigned width, unsigned height) const {
        if (left >= right || top >= bottom) return 0;
        if (top >= 0 && bottom <= 43) {
            if (left >= 0 && right <= 105 && width == 128 && height == 128) return course_level;
            if (left >= 211 && right <= 320 && width == 32 && height == 256) return course_lives;
            if (left >= 105 && right <= 213 && bottom - top >= 19) return course_medals;
        }
        if (width == 128 && height == 128 && left >= 105 && right <= 215 && top >= 110 && bottom <= 144)
            return course_reserve | reserve_caption;
        if (left >= 78 && right <= 242 && top >= 49 && bottom <= 215) return course_reserve;
        return 0;
    }

    unsigned pause_row() const {
        if (left < 8 || left > 45 || right < 275 || right > 312 ||
            bottom - top < 50 || bottom - top > 68) return 0;
        const float center = (top + bottom) / 2;
        if (center >= 68 && center <= 90) return 1;
        if (center >= 125 && center <= 147) return 2;
        if (center >= 182 && center <= 205) return 4;
        return 0;
    }
};

struct ReserveTap {
    void press(SDL_GamepadButton button, bool in_course, uint64_t now) {
        if (button == SDL_GAMEPAD_BUTTON_DPAD_UP && in_course) held_until = now + 110;
    }

    void apply(frontend::Input &input, bool in_course, uint64_t now) {
        if (!in_course || input.touching) held_until = 0;
        if (now >= held_until) return;
        input.touching = true;
        input.touch_x = reserve_x;
        input.touch_y = reserve_y;
    }

private:
    uint64_t held_until = 0;
};

} // namespace sm3dl
