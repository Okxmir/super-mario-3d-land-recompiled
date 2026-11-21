#pragma once

#include <cstdint>

namespace logic60 {
// Only takes effect for this launch. Unsupported scenes retain their clock.
void request();
bool requested();
bool active();
void vblank(bool hardware_renderer);
void presented(bool address_changed, uint64_t scanout_sequence);
}
