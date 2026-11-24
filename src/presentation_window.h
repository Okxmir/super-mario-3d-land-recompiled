#pragma once

#include <algorithm>
#include <cstdint>

namespace sm3dl {

inline constexpr float widescreen_aspect = 16.0f / 9.0f;

constexpr bool is_16_by_9(int width, int height) {
    return width > 0 && height > 0 && std::int64_t(width) * 9 == std::int64_t(height) * 16;
}

// Some 16:9 displays round their width, for example 1366x768. A difference
// of less than one pixel needs no letterbox: the wider PICA buffer already
// has room for the exact drawable while keeping a uniform scale.
constexpr bool pixel_rounded_16_by_9(int width, int height) {
    const auto remainder = std::int64_t(width) * 9 - std::int64_t(height) * 16;
    return width > 0 && height > 0 && remainder > -9 && remainder < 9;
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

// Only window chrome calls for a wider crop. On F11 the output belongs
// to the monitor, even if SDL still reports the saved maximized state.
constexpr bool extend_maximized_16_by_9(bool fullscreen, bool maximized, int width, int height) {
    return !fullscreen && maximized && can_extend_16_by_9(width, height);
}

constexpr int top_margin_for_client(int width, int height, int native_width, int native_height) {
    if (!can_extend_16_by_9(width, height)) return 0;
    const auto numerator = std::int64_t(width) * native_height - std::int64_t(height) * native_width;
    const auto denominator = std::int64_t(height) * 2;
    return int((numerator + denominator - 1) / denominator);
}

} // namespace sm3dl
