#pragma once

#include "frontend/frontend.h"

#include <algorithm>
#include <atomic>
#include <bit>
#include <cstdint>

namespace sm3dl {

inline constexpr int reserve_x = 160, reserve_y = 131;
inline constexpr unsigned course_lives = 1, course_reserve = 2, course_medals = 4, course_level = 8;
inline constexpr unsigned reserve_caption = 16;
inline constexpr unsigned course_hud_parts = course_lives | course_reserve | course_medals | course_level;

constexpr bool is_course_hud(unsigned parts) {
    // The occupied reserve can be drawn differently from the empty slot. No
    // single HUD element is required, but the surrounding HUD identifies a course.
    return std::popcount(parts & course_hud_parts) >= 3;
}

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

// A lower-screen transfer may omit transient HUD draws. Do not lose the
// shortcut during a short partial update, but block immediately on pause.
struct CourseTouchReadiness {
    void publish(bool full_hud, bool paused) {
        if (paused) grace = 0;
        else if (full_hud) grace = 5;
        else if (grace) --grace;
        ready.store(grace != 0, std::memory_order_relaxed);
    }

    bool active() const { return ready.load(std::memory_order_relaxed); }

private:
    unsigned grace = 0;
    std::atomic<bool> ready{false};
};

struct ReserveCommand {
    // HID samples the PC buttons. Only the native reserve UI consumes the
    // command, on the next eligible game update; no touch is synthesized.
    bool sample(frontend::Input &input, bool in_course, uint64_t now, bool queued_edge = false) {
        const bool down = (input.buttons & frontend::BTN_UP) != 0;
        const bool pressed = queued_edge || (down && !was_down);
        was_down = down;
        if (!in_course) {
            pending_until.store(0, std::memory_order_relaxed);
            return false;
        }
        input.buttons &= ~frontend::BTN_UP;
        if (pressed) pending_until.store(now + 200, std::memory_order_relaxed);
        return pressed;
    }

    bool take(uint64_t now) {
        return pending_until.exchange(0, std::memory_order_relaxed) > now;
    }

private:
    std::atomic<uint64_t> pending_until{0};
    bool was_down = false;
};

} // namespace sm3dl
