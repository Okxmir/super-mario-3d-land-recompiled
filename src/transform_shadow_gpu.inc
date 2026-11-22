// Find one projected motion for a complete closed shadow volume. Applying the
// same clip-space translation to its faces preserves their winding and depth.
struct ShadowVolume {
    uint32_t first, count;
    uint64_t pose_hash;
    int32_t previous;
    float cx, cy;
    bool paired = false;
};

struct ShadowFrame {
    std::unordered_map<uint64_t, std::vector<ShadowVolume>> volumes;
    std::vector<GpuVertex> verts;
    void clear() { volumes.clear(); verts.clear(); }
};

ShadowFrame last_shadow, now_shadow;

uint64_t shadow_key(const DrawRec &d) {
    uint64_t h = mix(mix(d.color->addr, d.depth->addr), d.volume_count);
    h = mix(h, regs[ATTR_BASE]);
    h = mix(h, regs[INDEX_BUFFER]);
    h = mix(h, regs[ATTR_LOADER]);
    h = mix(h, regs[VERTEX_OFFSET]);
    return mix(h, regs[VS_ENTRY]);
}

bool continuous_shadow(const GpuVertex *then, const GpuVertex *now, uint32_t count) {
    unsigned visible = 0;
    float total = 0;
    for (uint32_t i = 0; i < count; ++i) {
        const float *a = then[i].pos, *b = now[i].pos;
        for (int c = 0; c < 4; ++c)
            if (!std::isfinite(a[c]) || !std::isfinite(b[c])) return false;
        if (a[3] <= 1e-4f || b[3] <= 1e-4f) continue;
        const float ax = a[0] / a[3], ay = a[1] / a[3];
        const float bx = b[0] / b[3], by = b[1] / b[3];
        if (std::max({std::fabs(ax), std::fabs(ay), std::fabs(bx), std::fabs(by)}) > 1.5f) continue;
        const float moved = std::fabs(ax - bx) + std::fabs(ay - by);
        if (moved > .40f) return false;
        ++visible;
        total += moved;
    }
    return visible && total < .16f * float(visible);
}

int32_t match_shadow(const DrawRec &d, const GpuVertex *now) {
    // Front and back passes have different pipelines, but identical submitted
    // vertices. They must share one match and one all-or-nothing decision.
    uint64_t hash = 0;
    for (uint32_t i = 0; i < d.volume_count; ++i)
        for (float c : now[i].pos) hash = mix(hash, std::bit_cast<uint32_t>(c));
    auto &volumes = now_shadow.volumes[d.volume_key];
    for (const auto &volume : volumes) {
        if (volume.pose_hash != hash || volume.count != d.volume_count) continue;
        const GpuVertex *recorded = &now_shadow.verts[volume.first];
        uint32_t i = 0;
        while (i < d.volume_count && !std::memcmp(recorded[i].pos, now[i].pos, sizeof(now[i].pos))) ++i;
        if (i == d.volume_count) return volume.previous;
    }
    float cx, cy;
    centroid(now, d.volume_count, cx, cy);
    auto old = last_shadow.volumes.find(d.volume_key);
    ShadowVolume *best = nullptr;
    float best_distance = 0;
    if (old != last_shadow.volumes.end()) {
        for (auto &candidate : old->second) {
            if (candidate.paired || candidate.count != d.volume_count) continue;
            const float distance = (cx - candidate.cx) * (cx - candidate.cx) + (cy - candidate.cy) * (cy - candidate.cy);
            if (!best || distance < best_distance) best = &candidate, best_distance = distance;
        }
    }
    int32_t previous = -1;
    if (best && best_distance < .04f && continuous_shadow(&last_shadow.verts[best->first], now, d.volume_count)) {
        best->paired = true;
        previous = int32_t(best->first);
    }
    volumes.push_back({uint32_t(now_shadow.verts.size()), d.volume_count, hash, previous, cx, cy});
    now_shadow.verts.insert(now_shadow.verts.end(), now, now + d.volume_count);
    return previous;
}

void interpolate_shadow(DrawRec &d, std::vector<GpuVertex> &mid) {
    d.ifirst = uint32_t(vertices.size() + mid.size());
    const auto *now = &shadow_vertices[d.volume_first];
    static const bool freeze = std::getenv("SM3DL_SHADOW_FREEZE") != nullptr;
    const int32_t offset = freeze ? -1 : match_shadow(d, now);
    static const bool trace = std::getenv("SM3DL_SHADOW_TRACE") != nullptr;
    static unsigned traced = 0;
    if (trace && offset >= 0 && traced++ < 8)
        LOG("shadow: interpolated complete volume (%u triangles, cull %u)", d.volume_count / 3, unsigned(d.volume_cull));
    const size_t first = mid.size();
    mid.insert(mid.end(), vertices.begin() + d.first, vertices.begin() + d.first + d.count);
    if (offset >= 0) {
        const GpuVertex *then = &last_shadow.verts[size_t(offset)];
        // Extruded rays can cross the eye plane or land far away. Track the
        // nearby caster vertices instead and move the entire mask uniformly.
        float nearest_w = INFINITY;
        for (uint32_t i = 0; i < d.volume_count; ++i) {
            const float *a = then[i].pos, *b = now[i].pos;
            if (a[3] > 1e-4f && b[3] > 1e-4f && std::fabs(b[0]) <= b[3] && std::fabs(b[1]) <= b[3])
                nearest_w = std::min(nearest_w, b[3]);
        }
        float dx = 0, dy = 0;
        unsigned votes = 0;
        for (uint32_t i = 0; i < d.volume_count; ++i) {
            const float *a = then[i].pos, *b = now[i].pos;
            if (a[3] <= 1e-4f || b[3] <= 1e-4f || b[3] > nearest_w * 1.20f) continue;
            if (std::fabs(a[0]) > a[3] || std::fabs(b[0]) > b[3] || std::fabs(a[1]) > a[3] || std::fabs(b[1]) > b[3]) continue;
            dx += a[0] / a[3] - b[0] / b[3];
            dy += a[1] / a[3] - b[1] / b[3];
            ++votes;
        }
        if (votes) {
            dx *= INTERP_T / float(votes);
            dy *= INTERP_T / float(votes);
            if (std::fabs(dx) + std::fabs(dy) < .08f) {
                for (size_t i = first; i < mid.size(); ++i) {
                    float *p = mid[i].pos;
                    p[0] += dx * p[3];
                    p[1] += dy * p[3];
                }
            }
        }
    }
    d.icount = uint32_t(vertices.size() + mid.size()) - d.ifirst;
    d.interpolated = d.icount != 0;
    ++interp_stats.draws;
    if (offset >= 0) ++interp_stats.matched;
}
