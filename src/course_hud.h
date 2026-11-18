#pragma once

struct SDL_GPUTexture;

namespace pica::gpu {

// The top row and level label share a texture in the PICA's rotated orientation.
inline constexpr int COURSE_HUD_ROW_WIDTH = 218;
inline constexpr int COURSE_HUD_LABEL_WIDTH = 76;
inline constexpr int COURSE_HUD_WIDTH = COURSE_HUD_ROW_WIDTH + COURSE_HUD_LABEL_WIDTH;
inline constexpr int COURSE_HUD_HEIGHT = 40;
inline constexpr int COURSE_HUD_SCALE = 4;

enum class CoursePause { None, Buttons, Confirmation };

struct CoursePauseFrame {
    CoursePause panel = CoursePause::None;
    SDL_GPUTexture *sprites = nullptr;
};

void enable_course_hud(bool enabled, bool centered_pause);
SDL_GPUTexture *course_hud_frame();
CoursePauseFrame course_pause_frame();

} // namespace pica::gpu
