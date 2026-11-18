// This is included by the PICA GPU renderer. Replay the lower LCD's existing
// course UI with its original texture bindings, colors and alpha test.
namespace {

constexpr int hud_target_w = COURSE_HUD_HEIGHT * COURSE_HUD_SCALE;
constexpr int hud_target_h = COURSE_HUD_WIDTH * COURSE_HUD_SCALE;
constexpr auto hud_lives = 1u;
constexpr auto hud_reserve = 2u;
constexpr auto hud_medals = 4u;
constexpr auto hud_level = 8u;

std::atomic<bool> hud_enabled{false};
std::atomic<SDL_GPUTexture *> hud_latest{nullptr};
SDL_GPUTexture *hud_targets[3] = {};
unsigned hud_parts = 0;
int hud_slot = 0;

unsigned course_hud_part(const DrawRec &d, uint32_t dims, uint32_t blend) {
    if (!hud_enabled.load(std::memory_order_relaxed) || d.color->width != frontend::SCREEN_HEIGHT ||
        d.color->height != frontend::TOP_WIDTH || d.count < 6 || d.count > 48 ||
        d.viewport.h != frontend::BOTTOM_WIDTH * d.color->scale || blend != 0x76760000)
        return 0;

    float left = 320, right = 0, top = 240, bottom = 0;
    for (uint32_t i = d.first; i < d.first + d.count; ++i) {
        const auto &p = vertices[i].pos;
        if (p[3] <= 0) return 0;
        // The two axes of the guest framebuffer are rotated relative to the LCD.
        const float x = (1 - p[1] / p[3]) * 160;
        const float y = (1 - p[0] / p[3]) * 120;
        left = std::min(left, x), right = std::max(right, x);
        top = std::min(top, y), bottom = std::max(bottom, y);
    }

    const unsigned width = dims >> 16, height = dims & 0xffff;
    if (top >= 0 && bottom <= 43) {
        // The two text atlases have different sizes. The level label is on
        // the left of the touchscreen, and the lives are on the right.
        if (left >= 0 && right <= 105 && width == 128 && height == 128) return hud_level;
        if (left >= 211 && right <= 320 && width == 32 && height == 256) return hud_lives;
        if (left >= 105 && right <= 213 && bottom - top >= 19) return hud_medals;
    }
    if (left >= 78 && right <= 242 && top >= 49 && bottom <= 215)
        return hud_reserve;
    return 0;
}

void append_hud_vertices(const DrawRec &d) {
    float old_x, old_y, x, scale;
    if (d.hud_part == hud_level) {
        old_x = 48; old_y = 21; x = COURSE_HUD_ROW_WIDTH + COURSE_HUD_LABEL_WIDTH / 2.0f; scale = 0.78f;
    } else if (d.hud_part == hud_lives) {
        old_x = 272; old_y = 20; x = 176; scale = 0.80f;
    } else if (d.hud_part == hud_reserve) {
        old_x = 160; old_y = 131; x = 111; scale = 0.21f;
    } else {
        old_x = 159; old_y = 21; x = 40; scale = 0.82f;
    }
    for (uint32_t i = d.first; i < d.first + d.count; ++i) {
        GpuVertex v = vertices[i];
        const float w = v.pos[3];
        v.pos[0] *= 240 * scale / COURSE_HUD_HEIGHT;
        v.pos[0] += (120 - old_y) * (-2 * scale / COURSE_HUD_HEIGHT) * w;
        v.pos[1] *= 320 * scale / COURSE_HUD_WIDTH;
        v.pos[1] += (1 - 2 * (x + (160 - old_x) * scale) / COURSE_HUD_WIDTH) * w;
        vertices.push_back(v);
    }
}

void draw_course_hud(SDL_GPUCommandBuffer *cmd, SDL_GPUBuffer *vbuf, uint32_t first) {
    // RGB is premultiplied by alpha in the transparent target. Use source-over
    // alpha for both the game's layered sprites and the later window composite.
    PipelineKey overlay{};
    overlay.blend = 1;
    overlay.blend_cfg = 0x71760000;
    overlay.color_mask = 0xf;
    SDL_GPUTexture *&target = hud_targets[hud_slot];
    if (!target) target = make_texture(hud_target_w, hud_target_h, SDL_GPU_TEXTUREFORMAT_R8G8B8A8_UNORM,
                                       SDL_GPU_TEXTUREUSAGE_COLOR_TARGET | SDL_GPU_TEXTUREUSAGE_SAMPLER);
    if (!target) return;

    SDL_GPUColorTargetInfo color{};
    color.texture = target;
    color.load_op = hud_parts ? SDL_GPU_LOADOP_LOAD : SDL_GPU_LOADOP_CLEAR;
    color.store_op = SDL_GPU_STOREOP_STORE;
    auto *pass = SDL_BeginGPURenderPass(cmd, &color, 1, nullptr);
    SDL_BindGPUGraphicsPipeline(pass, pipeline(overlay));
    SDL_GPUBufferBinding vb{vbuf, 0};
    SDL_BindGPUVertexBuffers(pass, 0, &vb, 1);
    for (const auto &draw : batch) {
        if (!draw.hud_part) continue;
        SDL_GPUTextureSamplerBinding tex[4] = {
            {draw.tex[0], draw.samp[0]}, {draw.tex[1], draw.samp[1]}, {draw.tex[2], draw.samp[2]},
            {lut_tex, nearest_clamp}};
        SDL_BindGPUFragmentSamplers(pass, 0, tex, 4);
        SDL_PushGPUVertexUniformData(cmd, 0, draw.depth_map, sizeof draw.depth_map);
        SDL_PushGPUFragmentUniformData(cmd, 0, &draw.fu, sizeof draw.fu);
        SDL_DrawGPUPrimitives(pass, draw.count, 1, first, 0);
        first += draw.count;
        hud_parts |= draw.hud_part;
    }
    SDL_EndGPURenderPass(pass);
}

void publish_course_hud() {
    // Require the status bar and the reserve slot. This
    // keeps similarly placed sprites in the menus and map out of the HUD.
    if (hud_parts == (hud_lives | hud_reserve | hud_medals | hud_level)) {
        hud_latest.store(hud_targets[hud_slot], std::memory_order_release);
        hud_slot = (hud_slot + 1) % 3;
    } else {
        hud_latest.store(nullptr, std::memory_order_release);
    }
    hud_parts = 0;
}

} // namespace
