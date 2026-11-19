#pragma once

#include <algorithm>
#include <cstdint>

namespace sm3dl {

inline constexpr float widescreen_aspect = 16.0f / 9.0f;

constexpr bool is_16_by_9(int width, int height) {
    return width > 0 && height > 0 && std::int64_t(width) * 9 == std::int64_t(height) * 16;
}

struct ContentSize { int width, height; };

// Snap the content, not the outer window including its menu and caption.
constexpr ContentSize fit_16_by_9(int max_width, int max_height) {
    const int unit = std::max(1, std::min(max_width / 16, max_height / 9));
    return {16 * unit, 9 * unit};
}

// The maximized client of a 16:9 monitor is wider than the monitor's ratio
// because its title bar, menu and taskbar consume height. Use the existing 3D
// widescreen path up to the project's supported 21:9 field of view.
constexpr bool can_extend_16_by_9(int width, int height) {
    return width > 0 && height > 0 &&
           std::int64_t(width) * 9 > std::int64_t(height) * 16 &&
           std::int64_t(width) * 3 <= std::int64_t(height) * 7;
}

constexpr int top_margin_for_client(int width, int height, int native_width, int native_height) {
    if (!can_extend_16_by_9(width, height)) return 0;
    const auto numerator = std::int64_t(width) * native_height - std::int64_t(height) * native_width;
    const auto denominator = std::int64_t(height) * 2;
    return int((numerator + denominator - 1) / denominator);
}

} // namespace sm3dl
