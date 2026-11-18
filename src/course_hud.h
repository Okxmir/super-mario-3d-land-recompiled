#pragma once

struct SDL_GPUTexture;

namespace pica::gpu {

// The top row and level label share a texture in the PICA's rotated orientation.
inline constexpr int COURSE_HUD_ROW_WIDTH = 218;
inline constexpr int COURSE_HUD_LABEL_WIDTH = 76;
inline constexpr int COURSE_HUD_WIDTH = COURSE_HUD_ROW_WIDTH + COURSE_HUD_LABEL_WIDTH;
inline constexpr int COURSE_HUD_HEIGHT = 40;
inline constexpr int COURSE_HUD_SCALE = 2;

void enable_course_hud(bool enabled);
SDL_GPUTexture *course_hud_frame();

} // namespace pica::gpu
