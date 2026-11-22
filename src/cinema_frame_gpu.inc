// The European CinemaFrame layout draws PicTopFrame and PicBottomFrame as
// two 400x20 quads in one draw. The scene behind them is already rendered
// into the widened viewport. Skip the matte, not the camera or the fades.
bool is_cinema_frame(const DrawRec &draw) {
    constexpr uint32_t quad_vertices = 6;
    if (draw.count != 2 * quad_vertices || cur_ky == 1.0f ||
        draw.color->width != frontend::SCREEN_HEIGHT ||
        draw.color->height != frontend::TOP_WIDTH ||
        !wide_cinematics.load(std::memory_order_relaxed) ||
        draw.fu.flags[1] != 1 || regs[TEX0_DIM] != 0x00080008 || regs[DEPTH_COLOR_MASK] != 0x1f00 ||
        (regs[STENCIL_TEST] & 1) ||
        !(regs[COLOR_OP] & (1u << 8)) || regs[BLEND_FUNC] != 0x76760000)
        return false;

    // The screen is rotated: clip x runs along its height. Both quads must
    // contain all four corners at the original layout's exact positions.
    constexpr float inner = 1.0f - 2.0f * 20.0f / frontend::SCREEN_HEIGHT;
    auto near = [](float a, float b) { return std::fabs(a - b) < 0.0005f; };
    unsigned corners[2]{};
    bool sides[2]{};
    const float w = vertices[draw.first].pos[3];
    if (!(w > 0.0f)) return false;
    for (uint32_t quad = 0; quad < 2; ++quad) {
        const uint32_t first = draw.first + quad * quad_vertices;
        const bool positive = vertices[first].pos[0] > 0;
        sides[quad] = positive;
        for (uint32_t i = first; i < first + quad_vertices; ++i) {
            const auto &p = vertices[i].pos;
            if (!near(p[3], w) || !near(p[2] / w, -0.5f) || ((p[0] > 0) != positive)) return false;
            const float x = std::fabs(p[0] / w), y = p[1] / w;
            const bool outer_edge = near(x, 1.0f);
            if ((!outer_edge && !near(x, inner)) || !near(std::fabs(y), 1.0f)) return false;
            corners[quad] |= 1u << ((outer_edge ? 2 : 0) + (y > 0 ? 1 : 0));
        }
    }
    if (sides[0] == sides[1] || corners[0] != 15 || corners[1] != 15) return false;

    // MyBase.bclim, the matte's flat 8x8 luminance texture. Match the guest
    // pixels so this works with or without a replacement texture pack.
    const Texture t = load_texture(0);
    return t.data && t.format == 10 && t.bytes == 32 &&
           std::all_of(t.data, t.data + t.bytes, [](uint8_t b) { return b == 0xff; });
}
