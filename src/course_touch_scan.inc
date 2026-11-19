// Observe native lower-screen draws before either renderer transforms them.
struct CourseTouchScan {
    sm3dl::CourseHudBounds bounds;
    unsigned parts = 0, pause_rows = 0, vertex_count = 0;
    bool tracking = false, pause_dialog = false, was_paused = false;
    std::atomic<bool> ready{false};

    void begin() {
        const unsigned count = regs[VERTEX_COUNT];
        tracking = count >= 3 && count <= 48 && regs[BLEND_FUNC] == 0x76760000 &&
                   f24(regs[VIEWPORT_WIDTH]) == 120 && f24(regs[VIEWPORT_HEIGHT]) == 160;
        vertex_count = 0;
        if (tracking) bounds = {};
    }

    void add(const Vertex &vertex) {
        const float *p = vertex.a + POS;
        if (!(p[3] > 0)) {
            tracking = false;
            return;
        }
        bounds.add(p[0], p[1], p[3]);
        ++vertex_count;
    }

    void end() {
        if (!tracking || vertex_count < 6 || vertex_count > 48) return;
        tracking = false;
        const unsigned width = regs[TEX0_DIM] >> 16, height = regs[TEX0_DIM] & 0xffff;
        if (width == 16 && height == 64 && vertex_count == 12)
            pause_rows |= bounds.pause_row();
        if (was_paused && width == 16 && height == 16 && vertex_count == 24 &&
            bounds.left <= 4 && bounds.right >= 316)
            pause_dialog = true;
        parts |= bounds.hud_part(width, height);
    }

    void publish() {
        was_paused = pause_rows == 7 || pause_dialog;
        ready.store(!was_paused && (parts & sm3dl::course_hud_parts) == sm3dl::course_hud_parts,
                    std::memory_order_relaxed);
        parts = pause_rows = 0;
        pause_dialog = false;
    }
} course_touch_scan;
