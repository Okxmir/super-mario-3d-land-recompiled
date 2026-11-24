#pragma once

#include <cstdint>

namespace sm3dl {

int boot_fps();
void set_boot_fps(int fps);

struct CursorIdle {
    static constexpr uint64_t delay_ms = 7000;
    uint64_t last_activity;

    void moved(uint64_t now) { last_activity = now; }
    bool expired(uint64_t now) const { return now - last_activity >= delay_ms; }
};

} // namespace sm3dl
