"""Experimental geometry scheduling; no guest state or shader math changes."""
from coherent_pica_fast import once


def geometry_jobs(source):
    source = once(source, '''        const size_t group = lanes <= 4 ? 384 : 192;''', '''        static const unsigned override_group = [] {
            const char *value = std::getenv("SM3DL_LAB_VERTICES_PER_LANE");
            return value ? unsigned(std::clamp(std::atoi(value), 32, 2048)) : 0u;
        }();
        const size_t group = override_group ? override_group : (lanes <= 4 ? 384 : 192);''')
    source = once(source, '''    void run(size_t count, const std::function<void(size_t, size_t)> &fn) {
        // Small draws rarely benefit from waking all available lanes.''', '''    template<class F>
    void run(size_t count, const F &fn) {
        // Small draws rarely benefit from waking all available lanes.''')
    source = once(source, '''        job = &fn;
        job_count = count;''', '''        job = &fn;
        invoke = [](const void *object, size_t begin, size_t end) {
            (*static_cast<const F *>(object))(begin, end);
        };
        job_count = count;''')
    source = once(source, '''            generation[i].fetch_add(1, std::memory_order_release);
            generation[i].notify_one();''', '''            generation[i].value.fetch_add(1, std::memory_order_release);
            generation[i].value.notify_one();''')
    source = once(source, '''        slice(0, fn, count);
        for (int left = pending.load(std::memory_order_acquire); left;
             left = pending.load(std::memory_order_acquire))
            pending.wait(left, std::memory_order_acquire);''', '''        fn(0, std::min(count, slice_size));
        // Leave short jobs in userspace; longer jobs still sleep normally.
        for (unsigned i = 0; i < spins && pending.load(std::memory_order_acquire); ++i) _mm_pause();
        for (int left = pending.load(std::memory_order_acquire); left;
             left = pending.load(std::memory_order_acquire))
            pending.wait(left, std::memory_order_acquire);''')
    source = once(source, '''    int lanes = 1;
    std::atomic<int> pending{0};
    std::atomic<uint64_t> generation[8]{};
    size_t slice_size = 0;
    size_t job_count = 0;
    const std::function<void(size_t, size_t)> *job = nullptr;

    void slice(int lane, const std::function<void(size_t, size_t)> &fn, size_t count) {
        size_t per = slice_size;
        size_t begin = std::min(count, per * size_t(lane)), end = std::min(count, begin + per);
        if (begin < end) fn(begin, end);
    }''', '''    int lanes = 1;
    unsigned spins = [] {
        const auto *s = std::getenv("SM3DL_LAB_SPINS");
        return unsigned(s ? std::clamp(std::atoi(s), 0, 512) : 64);
    }();
    alignas(64) std::atomic<int> pending{0};
    struct alignas(64) Generation { std::atomic<uint64_t> value{0}; };
    Generation generation[8]{};
    size_t slice_size = 0;
    size_t job_count = 0;
    const void *job = nullptr;
    void (*invoke)(const void *, size_t, size_t) = nullptr;''')
    source = once(source, '''            generation[lane].wait(seen, std::memory_order_acquire);
            seen = generation[lane].load(std::memory_order_acquire);
            slice(lane, *job, job_count);''', '''            auto &next = generation[lane].value;
            for (unsigned i = 0; i < spins && next.load(std::memory_order_acquire) == seen; ++i) _mm_pause();
            next.wait(seen, std::memory_order_acquire);
            seen = next.load(std::memory_order_acquire);
            const size_t count = job_count;
            const size_t begin = std::min(count, slice_size * size_t(lane));
            const size_t end = std::min(count, begin + slice_size);
            if (begin < end) invoke(job, begin, end);''')
    return source


def dense_indices(source):
    source = once(source, '''        unique.clear();
        for (uint32_t i = 0; i < n; i++) {''', '''        static std::vector<uint16_t> draw_indices;
        static const bool legacy = std::getenv("SM3DL_LAB_LEGACY_INDICES") != nullptr;
        if (!legacy) draw_indices.resize(n);
        unique.clear();
        for (uint32_t i = 0; i < n; i++) {''')
    source = once(source, '''                unique.push_back(index);
            }
        }
        shaded.resize(unique.size());''', '''                unique.push_back(index);
            }
            if (!legacy) draw_indices[i] = uint16_t(slot[index]);
        }
        shaded.resize(unique.size());''')
    return once(source, '''        assembler.push_range(n, [&](uint32_t i) -> const Vertex & {
            return shaded[size_t(slot[index_at(i)])];
        });''', '''        if (!legacy) {
            assembler.push_range(n, [&](uint32_t i) -> const Vertex & { return shaded[draw_indices[i]]; });
        } else {
            assembler.push_range(n, [&](uint32_t i) -> const Vertex & { return shaded[size_t(slot[index_at(i)])]; });
        }''')
