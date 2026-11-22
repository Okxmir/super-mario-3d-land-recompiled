// One midpoint sample for each complete view of the scene: move unclipped
// geometry before culling, then let the game's original depth/stencil passes
// shade the result. Never interpolate a subset of a shadow volume's faces.
struct CoherentDraw {
    uint32_t first, count;
    float x, y;
    uint64_t pose_hash;
    int32_t previous;
    bool taken = false;
};

struct CoherentFrame {
    std::unordered_map<uint64_t, std::vector<CoherentDraw>> draws;
    struct Point { alignas(16) float pos[4]; };
    std::vector<Point> verts;
    void clear() { draws.clear(); verts.clear(); }
};

CoherentFrame last_shadow, now_shadow;

uint64_t shadow_key(const DrawRec &d) {
    uint64_t h = mix(mix(d.color->addr, d.depth ? d.depth->addr : 0), d.volume_count);
    h = mix(h, regs[ATTR_BASE]);
    h = mix(h, regs[INDEX_BUFFER]);
    h = mix(h, regs[ATTR_LOADER]);
    h = mix(h, regs[VERTEX_OFFSET]);
    h = mix(h, regs[VS_ENTRY]);
    if (!d.shadow_volume) {
        h = mix(h, uint64_t(uintptr_t(d.pipeline)));
        h = mix(h, regs[TEX0_ADDR]);
        h = mix(h, d.stencil_ref);
        h = mix(h, d.volume_cull);
        for (auto v : {d.viewport.x, d.viewport.y, d.viewport.w, d.viewport.h}) h = mix(h, std::bit_cast<uint32_t>(v));
        for (auto v : {d.scissor.x, d.scissor.y, d.scissor.w, d.scissor.h}) h = mix(h, uint32_t(v));
        // Surface topology and its static UV mapping identify the same rigid
        // geometry; changing texture coordinates opt it out of this match.
        const uint32_t step = std::max(1u, d.volume_count / 32);
        for (uint32_t i = 0; i < d.volume_count; i += step) {
            const auto &v = shadow_vertices[d.volume_first + i];
            for (float uv : v.tc01) h = mix(h, std::bit_cast<uint32_t>(uv));
        }
    }
    return h;
}

bool coherent_winding(const GpuVertex *v, uint8_t cull) {
    if (cull != 1 && cull != 2) return true;
    const float *a = v[0].pos, *b = v[1].pos, *c = v[2].pos;
    const double x0 = a[0], x1 = b[0], x2 = c[0];
    const double y0 = a[1], y1 = b[1], y2 = c[1];
    const double w0 = a[3], w1 = b[3], w2 = c[3];
    const double area = x0 * (y1 * w2 - y2 * w1) - y0 * (x1 * w2 - x2 * w1) + w0 * (x1 * y2 - x2 * y1);
    return cull == 1 ? area < 0.0 : area > 0.0;
}

bool coherent_pair(const CoherentFrame::Point *a, const GpuVertex *b, uint32_t count) {
    const uint32_t stride = std::max(1u, count / 96);
    unsigned samples = 0, jumps = 0;
    float movement = 0;
    for (uint32_t i = 0; i < count; i += stride) {
        for (unsigned j = 0; j < 4; ++j)
            if (!std::isfinite(a[i].pos[j]) || !std::isfinite(b[i].pos[j])) return false;
        const float aw = a[i].pos[3], bw = b[i].pos[3];
        if (aw <= 1e-4f || bw <= 1e-4f) continue;
        const float ax = a[i].pos[0] / aw, ay = a[i].pos[1] / aw;
        const float bx = b[i].pos[0] / bw, by = b[i].pos[1] / bw;
        if (std::max({std::fabs(ax), std::fabs(ay), std::fabs(bx), std::fabs(by)}) > 1.6f) continue;
        const float d = std::fabs(ax - bx) + std::fabs(ay - by);
        movement += d;
        jumps += d > .25f;
        ++samples;
    }
    return samples && jumps * 6 <= samples && movement < .145f * float(samples);
}

int32_t match_coherent(const DrawRec &d, const GpuVertex *now) {
    auto &draws = now_shadow.draws[d.volume_key];
    uint64_t hash = 0;
    if (d.shadow_volume) {
        // A stencil's front/back draws may have different shader state, but
        // identical input vertices. Share one temporal match for both passes.
        for (uint32_t i = 0; i < d.volume_count; ++i)
            for (float value : now[i].pos) hash = mix(hash, std::bit_cast<uint32_t>(value));
        for (const auto &peer : draws) {
            if (peer.pose_hash != hash || peer.count != d.volume_count) continue;
            const auto *stored = &now_shadow.verts[peer.first];
            uint32_t i = 0;
            while (i < d.volume_count && !std::memcmp(stored[i].pos, now[i].pos, sizeof(now[i].pos))) ++i;
            if (i == d.volume_count) return peer.previous;
        }
    }
    float x, y;
    centroid(now, d.volume_count, x, y);
    CoherentDraw *best = nullptr;
    float distance = .04f;
    if (const auto it = last_shadow.draws.find(d.volume_key); it != last_shadow.draws.end()) {
        for (auto &peer : it->second) {
            if (peer.taken || peer.count != d.volume_count) continue;
            const float dx = x - peer.x, dy = y - peer.y;
            const float cost = dx * dx + dy * dy;
            if (cost < distance) best = &peer, distance = cost;
        }
    }
    int32_t previous = -1;
    if (best && coherent_pair(&last_shadow.verts[best->first], now, d.volume_count)) {
        best->taken = true;
        previous = int32_t(best->first);
    }
    const size_t start = now_shadow.verts.size();
    draws.push_back({uint32_t(start), d.volume_count, x, y, hash, previous});
    now_shadow.verts.resize(start + d.volume_count);
    for (uint32_t i = 0; i < d.volume_count; ++i)
        _mm_store_ps(now_shadow.verts[start + i].pos, _mm_loadu_ps(now[i].pos));
    return previous;
}

bool coherent_atomic_stencil() {
#if defined(SM3DL_COHERENT_ATOMIC_STENCIL_DEFAULT)
    return true;
#else
    static const bool enabled = std::getenv("SM3DL_COHERENT_ATOMIC_STENCIL") != nullptr;
    return enabled;
#endif
}

bool coherent_local_mesh(const GpuVertex *verts, uint32_t count) {
    // Large receiver meshes can share borders with unmatched overlays. When
    // keeping the original stencil, keep their entire coverage in the same
    // phase too. Reconstruct local models (player, enemies, moving objects).
    float x_min = 10.0f, x_max = -10.0f, y_min = 10.0f, y_max = -10.0f;
    for (uint32_t i = 0; i < count; ++i) {
        const float *p = verts[i].pos;
        if (p[3] <= 1e-4f) return false;
        const float x = p[0] / p[3], y = p[1] / p[3];
        x_min = std::min(x_min, x); x_max = std::max(x_max, x);
        y_min = std::min(y_min, y); y_max = std::max(y_max, y);
        if (x_max - x_min >= .78f || y_max - y_min >= .78f) return false;
    }
    return true;
}

void interpolate_shadow(DrawRec &d, std::vector<GpuVertex> &mid) {
    d.ifirst = uint32_t(vertices.size() + mid.size());
    const GpuVertex *now = &shadow_vertices[d.volume_first];
    const int32_t previous = coherent_atomic_stencil() && !coherent_local_mesh(now, d.volume_count)
        ? -1 : match_coherent(d, now);
    bool identical = previous >= 0;
    if (identical) {
        const auto *then = &last_shadow.verts[size_t(previous)];
        for (uint32_t i = 0; i < d.volume_count; ++i) {
            if (std::memcmp(then[i].pos, now[i].pos, sizeof now[i].pos) != 0) {
                identical = false;
                break;
            }
        }
    }
    if (previous < 0 || identical) {
        d.ifirst = d.first;
        d.icount = d.count;
        d.interpolated = d.count != 0;
        ++interp_stats.draws;
        if (identical) ++interp_stats.matched;
        return;
    } else {
        const auto *then = &last_shadow.verts[size_t(previous)];
        const __m128 half = _mm_set1_ps(INTERP_T);
        for (uint32_t i = 0; i < d.volume_count; i += 3) {
            GpuVertex triple[3] = {now[i], now[i + 1], now[i + 2]};
            for (uint32_t k = 0; k < 3; ++k) {
                const __m128 a = _mm_load_ps(then[i + k].pos), b = _mm_loadu_ps(now[i + k].pos);
                _mm_storeu_ps(triple[k].pos, _mm_mul_ps(_mm_add_ps(a, b), half));
            }
            if (coherent_winding(triple, d.volume_cull)) mid.insert(mid.end(), triple, triple + 3);
        }
    }
    d.icount = uint32_t(vertices.size() + mid.size()) - d.ifirst;
    d.interpolated = d.icount != 0;
    ++interp_stats.draws;
    if (previous >= 0) {
        ++interp_stats.matched;
        static const bool trace = std::getenv("SM3DL_SHADOW_TRACE") != nullptr;
        if (trace && d.shadow_volume) {
            static unsigned count = 0;
            if (count++ < 10) LOG("geometry: midpoint shadow volume (%u triangles, cull %u)",
                                  d.volume_count / 3, unsigned(d.volume_cull));
        }
    }
}
