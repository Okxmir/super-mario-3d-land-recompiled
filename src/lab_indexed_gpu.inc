// Draw complete 3D lists with one packed vertex per distinct source index.
// Draw order, clipping/culling and vertex bits match the expanded path.
bool indexed_triangles(const Vertex *source, size_t count, const uint16_t *draw, uint32_t n) {
    static const bool disabled = std::getenv("SM3DL_LAB_EXPAND_TRIANGLES") != nullptr;
    static const bool verify = std::getenv("SM3DL_LAB_VERIFY_TRIANGLES") != nullptr;
    if (disabled || cur_skip || interp_on || draw_fills_screen || (cur_ky != 1.0f && draw_geom.valid) ||
        count * 2 > n || count > 65536 || vertices.size() != cur.first || hud_scale() < 1.0f)
        return false;
    // Mixed/2D geometry needs the existing per-triangle anchoring rules.
    for (size_t i = 0; i < count; ++i) {
        const float w = source[i].a[POS + 3];
        if (!(std::fabs(w - 1.0f) > 1e-4f)) return false;
    }

    static std::vector<GpuVertex> reference;
    if (verify) {
        const uint32_t previous_tris = cur_tris;
        for (uint32_t i = 0; i < n; i += 3)
            triangle(source[draw[i]], source[draw[i + 1]], source[draw[i + 2]]);
        reference.assign(vertices.begin() + cur.first, vertices.end());
        vertices.resize(cur.first);
        cur_tris = previous_tris;
    }
    static std::vector<int32_t> slots;
    static std::vector<std::array<float, 2>> normalized;
    slots.assign(count, -1);
    const bool cull = cur_cull == 1 || cur_cull == 2;
    if (cull) {
        normalized.resize(count);
        for (size_t i = 0; i < count; ++i) {
            const float *a = source[i].a + POS;
            if (a[3] > 0.0f) normalized[i] = {a[0] / a[3], a[1] / a[3]};
        }
    }
    const float kx = cur_ky != 1.0f ? camera_zoom() : 1.0f;
    const float ky = cur_ky * kx;
    cur.index_first = uint32_t(lab_indices.size());
    for (uint32_t i = 0; i < n; i += 3) {
        const uint16_t i0 = draw[i], i1 = draw[i + 1], i2 = draw[i + 2];
        ++cur_tris;
        if (cull) {
            const float *a = source[i0].a + POS, *b = source[i1].a + POS, *c = source[i2].a + POS;
            if (a[3] > 0 && b[3] > 0 && c[3] > 0) {
                const auto &p = normalized[i0], &q = normalized[i1], &r = normalized[i2];
                const float area = (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0]);
                if ((cur_cull == 1 && area >= 0) || (cur_cull == 2 && area <= 0)) continue;
            } else {
                const double x0 = a[0], x1 = b[0], x2 = c[0];
                const double y0 = a[1], y1 = b[1], y2 = c[1];
                const float w0 = a[3], w1 = b[3], w2 = c[3];
                const double area = x0 * (y1 * w2 - y2 * w1) - y0 * (x1 * w2 - x2 * w1) + w0 * (x1 * y2 - x2 * y1);
                if ((cur_cull == 1 && area >= 0) || (cur_cull == 2 && area <= 0)) continue;
            }
        }
        for (uint16_t index : {i0, i1, i2}) {
            int32_t &slot = slots[index];
            if (slot < 0) {
                slot = int32_t(vertices.size() - cur.first);
                vertices.push_back(lab_pack_vertex(source[index], kx, ky, 0.0f));
            }
            lab_indices.push_back(uint16_t(slot));
        }
    }
    cur.index_count = uint32_t(lab_indices.size()) - cur.index_first;
    if (verify) {
        if (reference.size() != cur.index_count) fatal("Indexed triangle count differs");
        for (uint32_t i = 0; i < cur.index_count; ++i) {
            const auto &fast = vertices[cur.first + lab_indices[cur.index_first + i]];
            if (std::memcmp(&fast, &reference[i], sizeof fast)) fatal("Indexed GPU vertex differs");
        }
    }
    static const bool trace = std::getenv("SM3DL_LAB_INDEX_TRACE") != nullptr;
    if (trace) {
        static uint64_t emitted = 0, uploaded = 0, draws = 0;
        emitted += cur.index_count;
        uploaded += vertices.size() - cur.first;
        if (++draws % 2048 == 0)
            LOG("indexed GPU: %llu draws, %llu packed vs %llu expanded vertices",
                (unsigned long long)draws, (unsigned long long)uploaded, (unsigned long long)emitted);
    }
    return true;
}
