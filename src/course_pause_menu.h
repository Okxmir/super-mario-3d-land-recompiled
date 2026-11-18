#pragma once

#include "course_hud.h"
#include "frontend/frontend.h"

#include <SDL3/SDL.h>

namespace frontend {

struct CoursePauseMenu {
    pica::gpu::CoursePause panel = pica::gpu::CoursePause::None;

    float scale() const {
        return panel == pica::gpu::CoursePause::Confirmation ? 0.70f : 0.64f;
    }

    SDL_FRect source() const {
        // The choices begin below the status bar. Confirmation dialogs replace
        // that bar and occupy nearly the whole lower LCD.
        if (panel == pica::gpu::CoursePause::Confirmation) return {5, 5, 310, 230};
        return {10, 40, 300, 194};
    }

    SDL_FRect destination(const SDL_FRect &screen) const {
        const auto src = source();
        const float width = src.w * scale();
        const float height = src.h * scale();
        return {screen.x + (screen.w - width) / 2, screen.y + (screen.h - height) / 2, width, height};
    }

    bool touch_at(const SDL_FRect &screen, float x, float y, float &tx, float &ty) const {
        const auto dest = destination(screen);
        x -= dest.x;
        y -= dest.y;
        if (x < 0 || x >= dest.w || y < 0 || y >= dest.h) return false;
        const auto src = source();
        tx = src.x + x / scale();
        ty = src.y + y / scale();
        return true;
    }

    void draw(SDL_Renderer *renderer, SDL_Texture *sprites, const SDL_FRect &screen) const {
        SDL_BlendMode previous_blend = SDL_BLENDMODE_NONE;
        SDL_GetRenderDrawBlendMode(renderer, &previous_blend);
        SDL_SetRenderDrawBlendMode(renderer, SDL_BLENDMODE_BLEND);
        SDL_SetRenderDrawColor(renderer, 0, 0, 0, 105);
        SDL_RenderFillRect(renderer, &screen);
        SDL_SetRenderDrawBlendMode(renderer, previous_blend);

        const auto src = source();
        const float k = float(sprites->w) / SCREEN_HEIGHT;
        // The overlay retains the original rotated LCD orientation.
        const SDL_FRect crop{(SCREEN_HEIGHT - src.y - src.h) * k, src.x * k, src.h * k, src.w * k};
        const auto dest = destination(screen);
        const SDL_FRect rotated{dest.x + (dest.w - dest.h) / 2, dest.y + (dest.h - dest.w) / 2,
                                dest.h, dest.w};
        SDL_SetTextureBlendMode(sprites, SDL_BLENDMODE_BLEND_PREMULTIPLIED);
        SDL_SetTextureScaleMode(sprites, SDL_SCALEMODE_LINEAR);
        SDL_RenderTextureRotated(renderer, sprites, &crop, &rotated, -90, nullptr, SDL_FLIP_NONE);
    }
};

} // namespace frontend
