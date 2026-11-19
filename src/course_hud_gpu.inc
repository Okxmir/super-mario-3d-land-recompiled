// This is included by the PICA GPU renderer. Replay the lower LCD's existing
// course UI with its original texture bindings, colors and alpha test.
namespace {

constexpr int hud_target_w = COURSE_HUD_HEIGHT * COURSE_HUD_SCALE;
constexpr int hud_target_h = COURSE_HUD_WIDTH * COURSE_HUD_SCALE;
constexpr auto hud_lives = sm3dl::course_lives;
constexpr auto hud_reserve = sm3dl::course_reserve;
constexpr auto hud_level = sm3dl::course_level;
constexpr auto hud_reserve_caption = sm3dl::reserve_caption;
constexpr auto course_parts = sm3dl::course_hud_parts;
constexpr int reserve_center_x = sm3dl::reserve_x, reserve_center_y = sm3dl::reserve_y;
constexpr int hud_reserve_x = 111;
constexpr float hud_reserve_scale = 0.21f;

std::atomic<bool> hud_enabled{false};
std::atomic<bool> centered_pause_enabled{false};
std::atomic<SDL_GPUTexture *> hud_latest{nullptr};
SDL_GPUTexture *hud_targets[3] = {};
SDL_GPUTexture *pause_targets[3] = {};
CoursePauseFrame pause_latest;
unsigned hud_parts = 0;
unsigned pause_button_rows = 0;
bool pause_confirmation = false;
bool pause_drawn = false;
int hud_slot = 0;
int pause_slot = 0;

uint64_t pause_texture_hash() {
    const auto texture = load_texture(0);
    return texture.data ? sm3dl::texture_hash(reinterpret_cast<const char *>(texture.data), texture.bytes) : 0;
}

bool hide_course_pause_title(const DrawRec &d) {
    if (!centered_pause_enabled.load(std::memory_order_relaxed) || pause_latest.panel == CoursePause::None ||
        d.color->width != frontend::SCREEN_HEIGHT || d.color->height != frontend::TOP_WIDTH ||
        d.viewport.h == frontend::BOTTOM_WIDTH * d.color->scale ||
        regs[TEX0_DIM] != ((128u << 16) | 128u) || (d.count != 12 && d.count != 18) ||
        regs[BLEND_FUNC] != 0x76760000)
        return false;
    // The native upper LCD spells PAUSE with two font atlases. The centered
    // menu takes its place only while the lower screen is hidden.
    const auto hash = pause_texture_hash();
    if (hash != 0x6b21e851fd7e05abull && hash != 0x2134d8e34aeca271ull) return false;
    for (uint32_t i = d.first; i < d.first + d.count; ++i) {
        const auto &p = vertices[i].pos;
        if (p[3] <= 0 || std::fabs(p[0] / p[3]) > 0.40f || std::fabs(p[1] / p[3]) > 0.48f)
            return false;
    }
    return true;
}

CoursePause pending_pause_panel() {
    if (pause_confirmation) return CoursePause::Confirmation;
    if (pause_button_rows == 7) return CoursePause::Buttons;
    return CoursePause::None;
}

unsigned course_hud_part(DrawRec &d, uint32_t dims, uint32_t blend) {
    const bool hud = hud_enabled.load(std::memory_order_relaxed);
    const bool pause_button = dims == ((16u << 16) | 64u) && d.count == 12;
    const unsigned width = dims >> 16, height = dims & 0xffff;
    const bool dialog = dims == ((16u << 16) | 16u) && d.count == 24 &&
                        pause_latest.panel != CoursePause::None;
    // Localized text can use larger font textures. Identify the text by its
    // placement within the already identified pause panel.
    const bool pause_text = (pause_button_rows || pause_confirmation) && width >= 32 && height >= 32;
    const bool pause_focus = pause_button_rows && width == 16 && height == 16 && d.count == 6;
    if (((!hud || d.count > 48) && !pause_button && !dialog && !pause_text && !pause_focus) ||
        d.color->width != frontend::SCREEN_HEIGHT || d.color->height != frontend::TOP_WIDTH || d.count < 6 ||
        d.viewport.h != frontend::BOTTOM_WIDTH * d.color->scale || blend != 0x76760000)
        return 0;

    sm3dl::CourseHudBounds bounds;
    for (uint32_t i = d.first; i < d.first + d.count; ++i) {
        const auto &p = vertices[i].pos;
        if (p[3] <= 0) return 0;
        bounds.add(p[0], p[1], p[3]);
    }
    const auto [left, right, top, bottom] = bounds;

    const float center = (top + bottom) / 2;
    unsigned row = 0;
    if (center >= 68 && center <= 90) row = 1;
    if (center >= 125 && center <= 147) row = 2;
    if (center >= 182 && center <= 205) row = 4;
    if (pause_button && bounds.pause_row()) {
        // Each pause option uses the same idle and pressed textures.
        // Identify the complete panel regardless of the language or HD replacement.
        const auto hash = pause_texture_hash();
        if (hash == 0x5811254e7d4f5210ull || hash == 0x83c9bf0261b1211aull) {
            pause_button_rows |= row;
            d.pause_sprite = true;
        }
    }
    // Follow the pause menu into its native confirmation dialog. The same
    // dialog frame is also used outside courses, so require a preceding pause.
    if (dialog && left <= 4 && right >= 316) {
        const auto hash = pause_texture_hash();
        if (hash == 0x6d09173f3c0eb868ull || hash == 0xe2dc14ec290a5b50ull)
            pause_confirmation = d.pause_sprite = true;
    }
    if (pause_confirmation && (pause_button ||
        (pause_text && left >= 12 && right <= 308 && bottom - top <= 62)))
        d.pause_sprite = true;
    if (pause_text && (pause_button_rows & row) &&
        left >= 30 && right <= 290 && bottom - top >= 13 && bottom - top <= 25)
        d.pause_sprite = true;
    if (pause_focus &&
        top >= 40 && bottom <= 234 && pause_texture_hash() == 0x3beb52e71c46a364ull)
        d.pause_sprite = true;
    if (!hud || d.count > 48 || d.pause_sprite) return 0;

    return bounds.hud_part(width, height);
}

void append_hud_vertices(const DrawRec &d) {
    float old_x, old_y, x, scale;
    if (d.hud_part == hud_level) {
        old_x = 48; old_y = 21; x = COURSE_HUD_ROW_WIDTH + COURSE_HUD_LABEL_WIDTH / 2.0f; scale = 0.78f;
    } else if (d.hud_part == hud_lives) {
        old_x = 272; old_y = 20; x = 176; scale = 0.80f;
    } else if (d.hud_part & hud_reserve) {
        old_x = reserve_center_x; old_y = reserve_center_y; x = hud_reserve_x;
        scale = d.hud_part & hud_reserve_caption ? 0.27f : hud_reserve_scale;
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

SDL_GPURenderPass *begin_course_overlay(SDL_GPUCommandBuffer *cmd, SDL_GPUBuffer *vbuf,
                                      SDL_GPUTexture *target, bool drawn) {
    // RGB is premultiplied by alpha in the transparent target. Use source-over
    // alpha for both the game's layered sprites and the later window composite.
    PipelineKey overlay{};
    overlay.blend = 1;
    overlay.blend_cfg = 0x71760000;
    overlay.color_mask = 0xf;
    SDL_GPUColorTargetInfo color{};
    color.texture = target;
    color.load_op = drawn ? SDL_GPU_LOADOP_LOAD : SDL_GPU_LOADOP_CLEAR;
    color.store_op = SDL_GPU_STOREOP_STORE;
    auto *pass = SDL_BeginGPURenderPass(cmd, &color, 1, nullptr);
    SDL_BindGPUGraphicsPipeline(pass, pipeline(overlay));
    SDL_GPUBufferBinding vb{vbuf, 0};
    SDL_BindGPUVertexBuffers(pass, 0, &vb, 1);
    return pass;
}

void draw_course_sprite(SDL_GPURenderPass *pass, SDL_GPUCommandBuffer *cmd, const DrawRec &draw, uint32_t first) {
    SDL_GPUTextureSamplerBinding tex[4] = {
        {draw.tex[0], draw.samp[0]}, {draw.tex[1], draw.samp[1]}, {draw.tex[2], draw.samp[2]},
        {lut_tex, nearest_clamp}};
    SDL_BindGPUFragmentSamplers(pass, 0, tex, 4);
    SDL_PushGPUVertexUniformData(cmd, 0, draw.depth_map, sizeof draw.depth_map);
    SDL_PushGPUFragmentUniformData(cmd, 0, &draw.fu, sizeof draw.fu);
    SDL_DrawGPUPrimitives(pass, draw.count, 1, first, 0);
}

void draw_course_hud(SDL_GPUCommandBuffer *cmd, SDL_GPUBuffer *vbuf, uint32_t first) {
    SDL_GPUTexture *&target = hud_targets[hud_slot];
    if (!target) target = make_texture(hud_target_w, hud_target_h, SDL_GPU_TEXTUREFORMAT_R8G8B8A8_UNORM,
                                       SDL_GPU_TEXTUREUSAGE_COLOR_TARGET | SDL_GPU_TEXTUREUSAGE_SAMPLER);
    if (!target) return;
    auto *pass = begin_course_overlay(cmd, vbuf, target, hud_parts != 0);
    for (const auto &draw : batch) {
        if (!draw.hud_part) continue;
        draw_course_sprite(pass, cmd, draw, first);
        first += draw.count;
        hud_parts |= draw.hud_part;
    }
    SDL_EndGPURenderPass(pass);
}

void draw_course_pause(SDL_GPUCommandBuffer *cmd, SDL_GPUBuffer *vbuf) {
    if (std::none_of(batch.begin(), batch.end(), [](const DrawRec &draw) { return draw.pause_sprite; }))
        return;
    // Use the original sprites and their transparency. The lower screen
    // backdrop and its fade animation never enter this texture.
    SDL_GPUTexture *&target = pause_targets[pause_slot];
    if (!target) target = make_texture(frontend::SCREEN_HEIGHT * COURSE_HUD_SCALE,
                                       frontend::BOTTOM_WIDTH * COURSE_HUD_SCALE, SDL_GPU_TEXTUREFORMAT_R8G8B8A8_UNORM,
                                       SDL_GPU_TEXTUREUSAGE_COLOR_TARGET | SDL_GPU_TEXTUREUSAGE_SAMPLER);
    if (!target) return;
    auto *pass = begin_course_overlay(cmd, vbuf, target, pause_drawn);
    for (const auto &draw : batch)
        if (draw.pause_sprite) draw_course_sprite(pass, cmd, draw, draw.first);
    SDL_EndGPURenderPass(pass);
    pause_drawn = true;
}

void publish_course_hud() {
    const auto pause = pending_pause_panel();
    pause_latest = {pause, nullptr};
    if (pause != CoursePause::None && pause_drawn) {
        pause_latest.sprites = pause_targets[pause_slot];
        pause_slot = (pause_slot + 1) % 3;
    }
    pause_button_rows = 0;
    pause_confirmation = false;
    pause_drawn = false;

    // Require the status bar and the reserve slot. This
    // keeps similarly placed sprites in the menus and map out of the HUD.
    if (pause == CoursePause::None && (hud_parts & course_parts) == course_parts) {
        hud_latest.store(hud_targets[hud_slot], std::memory_order_release);
        hud_slot = (hud_slot + 1) % 3;
    } else {
        hud_latest.store(nullptr, std::memory_order_release);
    }
    hud_parts = 0;
}

void copy_course_reserve(SDL_GPUCommandBuffer *cmd, SDL_GPUTexture *bottom_lcd) {
    if (pending_pause_panel() != CoursePause::None || (hud_parts & course_parts) != course_parts) return;

    // The power-up is a 3D model on the lower LCD. Copy the inside of the
    // slot from the finished image so the model keeps its depth and animation.
    constexpr float scale = COURSE_HUD_SCALE * hud_reserve_scale;
    constexpr float radius = 65.0f;
    const int extent = int(std::ceil(radius * scale));
    constexpr int center_x = hud_target_w / 2, center_y = hud_reserve_x * COURSE_HUD_SCALE;
    const SDL_Rect scissor{center_x - extent, center_y - extent, 2 * extent, 2 * extent};
    SDL_GPUColorTargetInfo color{};
    color.texture = hud_targets[hud_slot];
    color.load_op = SDL_GPU_LOADOP_LOAD;
    color.store_op = SDL_GPU_STOREOP_STORE;
    auto *pass = SDL_BeginGPURenderPass(cmd, &color, 1, nullptr);
    SDL_BindGPUGraphicsPipeline(pass, blit_pipeline);
    SDL_SetGPUScissor(pass, &scissor);
    const SDL_GPUTextureSamplerBinding source{bottom_lcd, linear_clamp};
    SDL_BindGPUFragmentSamplers(pass, 0, &source, 1);
    const BlitUniforms u{{float(center_x), float(center_y), 1 / scale, radius},
                        {4, reserve_center_x, reserve_center_y, (hud_parts & hud_reserve_caption) != 0}};
    SDL_PushGPUFragmentUniformData(cmd, 0, &u, sizeof u);
    SDL_DrawGPUPrimitives(pass, 3, 1, 0, 0);
    SDL_EndGPURenderPass(pass);
}

} // namespace
