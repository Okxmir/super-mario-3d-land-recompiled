"""Overlap draw setup with CPU work on disjoint vertex/index memory."""
from coherent_pica_fast import once


def overlap_gpu_header(source):
    return once(source, 'void begin_draw();', '''struct LabVertexRange { uint32_t addr, bytes; };
bool lab_vertex_ranges_disjoint(const LabVertexRange *ranges, size_t count);
void begin_draw();''')


def overlap_gpu(source):
    return once(source, 'void begin_draw() {', '''bool lab_vertex_ranges_disjoint(const LabVertexRange *ranges, size_t count) {
    if (!ok) return false;
    for (size_t i = 0; i < count; ++i) {
        const uint64_t a = ranges[i].addr, end = a + ranges[i].bytes;
        const bool linear = a >= mem::LINEAR_BASE && end <= uint64_t(mem::LINEAR_BASE) + 0x08000000;
        const bool vram = a >= mem::VRAM_BASE && end <= uint64_t(mem::VRAM_BASE) + mem::VRAM_SIZE;
        if (!(linear || vram)) return false;
        const uint64_t first = to_physical(ranges[i].addr), last = first + ranges[i].bytes;
        // Observe all existing targets, even if their draws are still queued.
        // begin_draw can download one while resolving a texture, or download
        // all color targets when switching HD packs. A newly allocated target
        // has no prior draws that can be downloaded.
        for (const auto &s : surfaces)
            if (!s->depth && first < uint64_t(s->addr) + s->bytes() && uint64_t(s->addr) < last)
                return false;
    }
    return true;
}

void begin_draw() {''')


def overlap_pica(source):
    source = once(source, '''        job_count = count;
        slice_size = (count + active - 1) / active;''', '''        job_count = count;
        background_first = 0;
        slice_size = (count + active - 1) / active;''')
    source = once(source, '''        // Leave short jobs in userspace; longer jobs still sleep normally.
        for (unsigned i = 0; i < spins && pending.load(std::memory_order_acquire); ++i) _mm_pause();
        for (int left = pending.load(std::memory_order_acquire); left;
             left = pending.load(std::memory_order_acquire))
            pending.wait(left, std::memory_order_acquire);
    }

private:
    int lanes = 1;''', '''        finish();
    }

    template<class F, class Prepare>
    bool during(size_t count, const F &fn, const Prepare &prepare) {
        if (lanes < 3 || count < 192) {
            prepare(); run(count, fn); return false;
        }
        static const size_t block = [] {
            const auto *setting = static_cast<const char *>(nullptr);
            return setting ? size_t(std::clamp(std::atoi(setting), 32, 512) & ~1) : size_t(0);
        }();
        if (!block) return during_fixed(count, fn, prepare);
        // Keep the setup thread useful after it has finished its GPU work.
        // Blocks are even so both vertices of a pair stay with one worker.
        alignas(64) std::atomic<size_t> next{0};
        auto claim = [&](size_t, size_t) {
            for (size_t first = next.fetch_add(block, std::memory_order_relaxed); first < count;
                 first = next.fetch_add(block, std::memory_order_relaxed))
                fn(first, std::min(count, first + block));
        };
        return during_fixed(count, claim, [&] { prepare(); claim(0, count); });
    }

    template<class F, class Prepare>
    bool during_fixed(size_t count, const F &fn, const Prepare &prepare) {
        const size_t group = lanes <= 4 ? 384 : 192;
        const size_t active = std::min(size_t(lanes - 1), (count + group - 1) / group);
        job = &fn;
        invoke = [](const void *object, size_t a, size_t b) { (*static_cast<const F *>(object))(a, b); };
        job_count = count;
        background_first = 1;
        slice_size = (count + active - 1) / active;
        pending.store(int(active), std::memory_order_relaxed);
        for (size_t i = 1; i <= active; ++i) {
            generation[i].value.fetch_add(1, std::memory_order_release);
            generation[i].value.notify_one();
        }
        try { prepare(); }
        catch (...) { finish(); throw; }
        finish();
        return true;
    }

private:
    void finish() {
        for (unsigned i = 0; i < spins && pending.load(std::memory_order_acquire); ++i) _mm_pause();
        for (int left = pending.load(std::memory_order_acquire); left;
             left = pending.load(std::memory_order_acquire))
            pending.wait(left, std::memory_order_acquire);
    }

    int lanes = 1, background_first = 0;''')
    source = once(source, 'std::min(count, slice_size * size_t(lane));',
                  'std::min(count, slice_size * size_t(lane - background_first));')
    source = once(source, 'void draw(bool indexed) {', '''bool lab_can_overlap_setup(bool indexed) {
    static const bool enabled = true;
    if (!enabled || !indexed || !gpu::active() || log_cfg::gpu) return false;
    const uint32_t count = regs[VERTEX_COUNT];
    if (count < lab_large_draw_min() || count > 65536) return false;
    const bool wide = regs[INDEX_BUFFER] >> 31;
    const uint32_t index_bytes = count * (wide ? 2 : 1);
    const uint32_t base = (regs[ATTR_BASE] & 0x1FFFFFFE) << 3;
    const uint32_t address = base + (regs[INDEX_BUFFER] & 0x0FFFFFFF);
    const uint8_t *indices = phys(address, index_bytes);
    if (!indices) return false;
    gpu::LabVertexRange ranges[13]{{to_virtual(address), index_bytes}};
    uint16_t strides[13]{};
    uint16_t widths[13]{};
    size_t n = 1;
    const VertexLoader loader;
    for (unsigned i = 0; i < 12 && i < loader.attr_count; ++i) {
        if ((loader.fixed_mask >> i) & 1) continue;
        const auto &v = loader.attrs[i];
        if (!v.data) continue;
        uint32_t start;
        if (!mem::guest_address(v.data, &start)) return false;
        // Bound all possible raw indices, not just those seen in a sampled
        // triangle. This only inspects address ranges, never extra memory.
        strides[n] = uint16_t(v.stride);
        widths[n] = uint16_t(v.count * attr_type_size(v.type));
        ranges[n] = {start, (wide ? 65535u : 255u) * strides[n] + widths[n]};
        ++n;
    }
    if (gpu::lab_vertex_ranges_disjoint(ranges, n)) return true;
    static const bool tight = true;
    if (!tight || !gpu::lab_vertex_ranges_disjoint(ranges, 1)) return false;
    // The conservative 16-bit bound covers up to 16 MiB of unused attributes.
    // Refine it only when the full bound overlaps and the index buffer is
    // guaranteed not to be rewritten by setup. Read exactly the draw's indices.
    uint32_t first = 65535, last = 0;
    for (uint32_t i = 0; i < count; ++i) {
        const uint32_t index = wide ? load16(indices + 2 * i) : indices[i];
        first = std::min(first, index);
        last = std::max(last, index);
    }
    for (size_t i = 1; i < n; ++i) {
        const uint64_t start = uint64_t(ranges[i].addr) + uint64_t(first) * strides[i];
        if (start > UINT32_MAX) return false;
        ranges[i] = {uint32_t(start), (last - first) * strides[i] + widths[i]};
    }
    return gpu::lab_vertex_ranges_disjoint(ranges, n);
}

void draw(bool indexed) {''')
    source = once(source, '''    auto t_setup = std::chrono::steady_clock::now();
    begin_draw();''', '''    auto prepare_gpu = [&] {
    auto t_setup = std::chrono::steady_clock::now();
    begin_draw();''')
    source = once(source, '''    LOG_GPU("draw%s n=%u topo=''', '''    };
    const bool deferred_setup = lab_can_overlap_setup(indexed);
    if (!deferred_setup) prepare_gpu();
    auto t_shade = std::chrono::steady_clock::now();
    LOG_GPU("draw%s n=%u topo=''')
    source = once(source, '''        if (!indices) {
            LOG("pica: index buffer outside GPU memory; draw skipped");''', '''        if (!indices) {
            if (deferred_setup) prepare_gpu();
            LOG("pica: index buffer outside GPU memory; draw skipped");''')
    return once(source, '''        workers().run(total, shade_slice);
        if (trace_pairs) {''', '''
        bool overlapped = false;
        if (deferred_setup) overlapped = workers().during(total, shade_slice, prepare_gpu);
        else workers().run(total, shade_slice);
        static const bool verify_overlap = std::getenv("SM3DL_LAB_VERIFY_OVERLAP") != nullptr;
        if (overlapped && verify_overlap) {
            // Reconstruct the old ordering, when setup is fully complete.
            for (size_t i = 0; i < total; ++i) {
                const Vertex serial = shade_index(at(i));
                if (std::memcmp(&serial, &out[i], sizeof serial))
                    fatal("Concurrent GPU setup changed vertex %u", at(i));
            }
        }
        static const bool trace_overlap = std::getenv("SM3DL_LAB_TRACE_OVERLAP") != nullptr;
        if (trace_overlap) {
            static uint64_t tries = 0, successes = 0;
            successes += unsigned(overlapped);
            if (++tries % 4096 == 0)
                LOG("overlapping draw setup: %llu of %llu large draws",
                    (unsigned long long)successes, (unsigned long long)tries);
        }
        if (trace_pairs) {''')
