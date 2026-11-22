"""Bit-preserving PICA draw preparation for the isolated 60 FPS renderer."""


def once(source, old, new):
    if source.count(old) != 1:
        raise ValueError(f'Expected one renderer optimization anchor: {old.splitlines()[0]}')
    return source.replace(old, new)


def coherent_pica_fast(source):
    source = once(source, '// A pool of threads for parallel vertex shading:', '''// The 60 Hz trial is latency sensitive. On a hybrid Windows CPU keep
// PICA dispatch and vertex shading on the allowed faster cores only.
struct CoherentPerformanceSets {
    unsigned core_count = 0;
#ifdef _WIN32
    std::vector<ULONG> ids;
#endif
};

const CoherentPerformanceSets &coherent_performance_sets() {
    static const auto sets = [] {
        CoherentPerformanceSets out;
#ifdef _WIN32
        if (std::getenv("SM3DL_COHERENT_ALL_CORES")) return out;
        const auto process = GetCurrentProcess();
        DWORD_PTR allowed = 0, system = 0;
        if (!GetProcessAffinityMask(process, &allowed, &system) || !allowed) return out;
        PROCESSOR_NUMBER current{};
        GetCurrentProcessorNumberEx(&current);
        ULONG bytes = 0;
        GetSystemCpuSetInformation(nullptr, 0, &bytes, process, 0);
        if (!bytes) return out;
        std::vector<uint8_t> records(bytes);
        if (!GetSystemCpuSetInformation(reinterpret_cast<PSYSTEM_CPU_SET_INFORMATION>(records.data()),
                                        bytes, &bytes, process, 0)) return out;
        struct Entry { ULONG id; unsigned core, efficiency; };
        std::vector<Entry> candidates;
        unsigned fast = 0, slow = 255;
        for (size_t offset = 0; offset + 8 <= bytes;) {
            const auto *entry = reinterpret_cast<const SYSTEM_CPU_SET_INFORMATION *>(records.data() + offset);
            if (entry->Size < 8 || entry->Size > bytes - offset) return CoherentPerformanceSets{};
            offset += entry->Size;
            if (entry->Type != CpuSetInformation || entry->Size < sizeof *entry) continue;
            const auto &cpu = entry->CpuSet;
            if (cpu.Group != current.Group || cpu.LogicalProcessorIndex >= sizeof(DWORD_PTR) * 8 ||
                !(allowed & (DWORD_PTR(1) << cpu.LogicalProcessorIndex)) ||
                (cpu.Allocated && !cpu.AllocatedToTargetProcess)) continue;
            candidates.push_back({cpu.Id, cpu.CoreIndex, cpu.EfficiencyClass});
            fast = std::max(fast, unsigned(cpu.EfficiencyClass));
            slow = std::min(slow, unsigned(cpu.EfficiencyClass));
        }
        if (fast <= slow) return out; // uniform CPU or caller already restricted the process
        bool cores[256]{};
        for (const auto &entry : candidates) if (entry.efficiency == fast) {
            out.ids.push_back(entry.id);
            if (!cores[entry.core]) cores[entry.core] = true, ++out.core_count;
        }
        if (out.core_count < 2) return CoherentPerformanceSets{};
#endif
        return out;
    }();
    return sets;
}

void coherent_select_performance_cores() {
#ifdef _WIN32
    const auto &sets = coherent_performance_sets();
    if (sets.ids.empty()) return;
    if (SetThreadSelectedCpuSets(GetCurrentThread(), sets.ids.data(), ULONG(sets.ids.size()))) {
        static const bool announced = [&] {
            LOG("pica: coherent rendering prefers %u performance cores", sets.core_count);
            return true;
        }();
        (void)announced;
    }
#endif
}

// A pool of threads for parallel vertex shading:''')
    source = once(source, '        lanes = int(std::clamp(hw ? hw : 1u, 1u, 8u));', '''        const auto &sets = coherent_performance_sets();
        if (sets.core_count) hw = sets.core_count;
        lanes = int(std::clamp(hw ? hw : 1u, 1u, 8u));''')
    source = once(source, '    void loop(int lane) {\n        uint64_t seen = 0;', '''    void loop(int lane) {
        coherent_select_performance_cores();
        uint64_t seen = 0;''')
    source = once(source, 'void draw(bool indexed) {\n    course_touch_scan.begin();', '''void draw(bool indexed) {
    static thread_local const bool selected = [] { coherent_select_performance_cores(); return true; }();
    (void)selected;
    course_touch_scan.begin();''')
    source = once(source, '        if (lanes == 1 || count < 256) return fn(0, count);\n'
        '        job = &fn;\n        job_count = count;\n        pending.store(lanes - 1, std::memory_order_relaxed);\n'
        '        generation.fetch_add(1, std::memory_order_release);\n        generation.notify_all();',
        '''        // Small draws rarely benefit from waking all available lanes.
        constexpr size_t group = 192;
        const size_t active = std::min(size_t(lanes), (count + group - 1) / group);
        if (active < 2) return fn(0, count);
        job = &fn;
        job_count = count;
        slice_size = (count + active - 1) / active;
        pending.store(int(active - 1), std::memory_order_relaxed);
        for (size_t i = 1; i < active; ++i) {
            generation[i].fetch_add(1, std::memory_order_release);
            generation[i].notify_one();
        }''')
    source = once(source, '    std::atomic<uint64_t> generation{0};',
                  '    std::atomic<uint64_t> generation[8]{};\n    size_t slice_size = 0;')
    source = once(source, '        size_t per = (count + size_t(lanes) - 1) / size_t(lanes);',
                  '        size_t per = slice_size;')
    source = once(source, '            generation.wait(seen, std::memory_order_acquire);',
                  '            generation[lane].wait(seen, std::memory_order_acquire);')
    source = once(source, '            seen = generation.load(std::memory_order_acquire);',
                  '            seen = generation[lane].load(std::memory_order_acquire);')
    source = once(source, '''Vertex shade(const Vec4 attrs[16], const OutputMap &map, CompiledVertex compiled = nullptr) {
    Vec4 in[16] = {}, out[16] = {};
    for (uint32_t i = 0; i < map.input_count; ++i) in[map.input_registers[i]] = attrs[i];''', '''struct CoherentVertexFetch {
    struct Item { AttrSource src; uint8_t reg; };
    Vec4 initial[16]{};
    Item items[12]{};
    unsigned n = 0;
    bool valid = false;

    CoherentVertexFetch(const VertexLoader &loader, const OutputMap &map) {
        if (map.input_count > 12 || map.input_count > loader.attr_count) return;
        uint32_t assigned = 0;
        for (uint32_t i = 0; i < map.input_count; ++i) {
            const uint8_t reg = map.input_registers[i];
            if (assigned & (1u << reg)) return;
            assigned |= 1u << reg;
            const auto &src = loader.attrs[i];
            if ((loader.fixed_mask >> i) & 1 || !src.data) initial[reg] = fixed_attr[i];
            else items[n++] = {src, reg};
        }
        valid = true;
    }

    void load(uint32_t index, Vec4 in[16]) const {
        std::memcpy(in, initial, sizeof initial);
        for (unsigned i = 0; i < n; ++i) {
            const auto &a = items[i].src;
            const auto *p = a.data + size_t(index) * a.stride;
            Vec4 v{{0, 0, 0, 1}};
            if (a.type == 3) {
                // Packed float3 is twelve bytes, not an overreading vector load.
                switch (a.count) {
                case 4: std::memcpy(v.v, p, 16); break;
                case 3: std::memcpy(v.v, p, 12); break;
                case 2: std::memcpy(v.v, p, 8); break;
                default: std::memcpy(v.v, p, 4); break;
                }
            } else if (a.type == 2) {
                for (uint32_t j = 0; j < a.count; ++j) v[j] = float(int16_t(load16(p + 2 * j)));
            } else if (a.type == 1) {
                for (uint32_t j = 0; j < a.count; ++j) v[j] = float(p[j]);
            } else {
                for (uint32_t j = 0; j < a.count; ++j) v[j] = float(int8_t(p[j]));
            }
            in[items[i].reg] = v;
        }
    }
};

Vertex shade_mapped(const Vec4 in[16], const OutputMap &map, CompiledVertex compiled) {
    Vec4 out[16] = {};''')
    source = once(source, '// Widescreen: whether a draw fills the screen', '''Vertex shade(const Vec4 attrs[16], const OutputMap &map, CompiledVertex compiled = nullptr) {
    Vec4 in[16]{};
    for (uint32_t i = 0; i < map.input_count; ++i) in[map.input_registers[i]] = attrs[i];
    return shade_mapped(in, map, compiled);
}

// Widescreen: whether a draw fills the screen''')
    source = once(source, '    if (n >= 512 && !indexed) {', '''    const CoherentVertexFetch plan(loader, map);
    static const bool verify_inputs = std::getenv("SM3DL_VERIFY_COHERENT_INPUTS") != nullptr;
    if (verify_inputs && plan.valid) {
        static const bool announced = [] { LOG("pica: verifying coherent vertex inputs bit for bit"); return true; }();
        (void)announced;
    }
    auto shade_index = [&](uint32_t index) {
        if (plan.valid) {
            Vec4 in[16];
            plan.load(index, in);
            if (verify_inputs) {
                Vec4 original[16]{}, expected[16]{};
                loader.read(index, original);
                for (uint32_t i = 0; i < map.input_count; ++i) expected[map.input_registers[i]] = original[i];
                if (std::memcmp(expected, in, sizeof in) != 0)
                    fatal("coherent PICA vertex input mismatch at index %u", index);
            }
            return shade_mapped(in, map, compiled);
        }
        Vec4 attrs[16]{};
        loader.read(index, attrs);
        return shade(attrs, map, compiled);
    };
    if (n >= 512 && !indexed) {''')
    source = once(source, '''            Vec4 attrs[16];
            for (size_t k = begin; k < end; ++k) {
                loader.read(first + uint32_t(k), attrs);
                shaded[k] = shade(attrs, map, compiled);
            }''', '''            for (size_t k = begin; k < end; ++k) shaded[k] = shade_index(first + uint32_t(k));''')
    source = once(source, '''            Vec4 attrs[16];
            for (size_t k = begin; k < end; k++) {
                loader.read(unique[k], attrs);
                shaded[k] = shade(attrs, map, compiled);
            }''', '''            for (size_t k = begin; k < end; ++k) shaded[k] = shade_index(unique[k]);''')
    source = once(source, '        Vec4 attrs[16];\n        for (uint32_t i = 0; i < n; i++) {',
                  '        for (uint32_t i = 0; i < n; i++) {')
    source = once(source, '                    loader.read(index, attrs);\n                    e.v = shade(attrs, map, compiled);',
                  '                    e.v = shade_index(index);')
    return once(source, '                loader.read(index, attrs);\n                Vertex v = shade(attrs, map, compiled);',
                '                Vertex v = shade_index(index);')
