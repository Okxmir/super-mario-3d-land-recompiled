"""Bit-preserving PICA draw preparation for the isolated 60 FPS renderer."""


def once(source, old, new):
    if source.count(old) != 1:
        raise ValueError(f'Expected one renderer optimization anchor: {old.splitlines()[0]}')
    return source.replace(old, new)


def coherent_pica_fast(source):
    source = once(source, '#include <algorithm>', '''#include <algorithm>
#include <bit>
#ifdef __linux__
#include <sched.h>
#endif''')
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
        const auto process = GetCurrentProcess();
        DWORD_PTR allowed = 0, system = 0;
        if (!GetProcessAffinityMask(process, &allowed, &system) || !allowed) return out;
        out.core_count = std::popcount(allowed);
        if (std::getenv("SM3DL_COHERENT_ALL_CORES")) return out;
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
            if (entry->Size < 8 || entry->Size > bytes - offset) return out;
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
        // Hyper-thread siblings share the execution units of their physical
        // core. Waking both for every small mesh can stall the render thread.
        if (fast <= slow) {
            bool cores[256]{};
            unsigned physical = 0;
            for (const auto &entry : candidates)
                if (!cores[entry.core]) cores[entry.core] = true, ++physical;
            if (physical) out.core_count = physical;
            return out;
        }
        CoherentPerformanceSets preferred;
        bool cores[256]{};
        for (const auto &entry : candidates) if (entry.efficiency == fast) {
            preferred.ids.push_back(entry.id);
            if (!cores[entry.core]) cores[entry.core] = true, ++preferred.core_count;
        }
        if (preferred.core_count >= 2) return preferred;
#elif defined(__linux__)
        cpu_set_t cpus;
        if (sched_getaffinity(0, sizeof cpus, &cpus) == 0) out.core_count = unsigned(CPU_COUNT(&cpus));
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
        if (const char *override = std::getenv("SM3DL_VERTEX_LANES")) {
            const int requested = std::atoi(override);
            if (requested >= 1 && requested <= 8) hw = unsigned(requested);
        }
        lanes = int(std::clamp(hw ? hw : 1u, 1u, 8u));
        LOG("pica: %d vertex shading lane(s)", lanes);''')
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
        // A worker wake-up can cost more than a small slice on a busy 2–4 core PC.
        const size_t group = lanes <= 4 ? 384 : 192;
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
    uint8_t init_registers[16]{};
    unsigned init_count = 0;
    unsigned n = 0;
    bool valid = false;

    CoherentVertexFetch(const VertexLoader &loader, const OutputMap &map, uint16_t used = 0xffff) {
        if (map.input_count > 12 || map.input_count > loader.attr_count) return;
        uint32_t assigned = 0, dynamic = 0;
        for (uint32_t i = 0; i < map.input_count; ++i) {
            const uint8_t reg = map.input_registers[i];
            if (assigned & (1u << reg)) return;
            assigned |= 1u << reg;
            if (!(used & (1u << reg))) continue;
            const auto &src = loader.attrs[i];
            if ((loader.fixed_mask >> i) & 1 || !src.data) initial[reg] = fixed_attr[i];
            else {
                items[n++] = {src, reg};
                dynamic |= 1u << reg;
            }
        }
        for (unsigned reg = 0; reg < 16; ++reg)
            if ((used & ~dynamic) & (1u << reg)) init_registers[init_count++] = uint8_t(reg);
        valid = true;
    }

    void load(uint32_t index, Vec4 in[16]) const {
        if (init_count > 8) std::memcpy(in, initial, sizeof initial);
        else for (unsigned i = 0; i < init_count; ++i) {
            const uint8_t reg = init_registers[i];
            in[reg] = initial[reg];
        }
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
    # The PICA output registers usually map four consecutive float components
    # to one vertex semantic (position, quaternion, color, UV). Build a copy
    # plan once per draw instead of scattering every component per vertex.
    # Retain original order even for unusual/overlapping maps.
    source = once(source, '    uint32_t component_count = 0;\n    uint8_t input_registers[16]{};', '''    uint32_t component_count = 0;
    struct Run { uint8_t reg, channel, semantic, count; };
    Run runs[28]{};
    uint32_t run_count = 0;
    uint16_t mapped_outputs = 0;
    uint8_t zero_regs[16]{};
    unsigned zero_count = 16; // interpreter and immediate-mode safe default
    void configure_output_initialization(const CompiledVertexUsage &usage) {
        const uint16_t required = usage.read_before_write | (mapped_outputs & ~usage.written_outputs);
        zero_count = 0;
        for (unsigned reg = 0; reg < 16; ++reg)
            if (required & (1u << reg)) zero_regs[zero_count++] = uint8_t(reg);
    }
    uint8_t input_registers[16]{};''')
    source = once(source, '''            reg++;
        }
    }
};

struct CoherentVertexFetch''', '''            reg++;
        }
        for (uint32_t i = 0; i < component_count; ++i) {
            const auto c = components[i];
            mapped_outputs |= uint16_t(1u << c.reg);
            if (run_count) {
                auto &last = runs[run_count - 1];
                if (last.reg == c.reg && last.channel + last.count == c.channel &&
                    last.semantic + last.count == c.semantic && last.count < 4) {
                    ++last.count;
                    continue;
                }
            }
            runs[run_count++] = {c.reg, c.channel, c.semantic, 1};
        }
    }
};

struct CoherentVertexFetch''')
    source = once(source, '''    for (uint32_t i = 0; i < map.component_count; ++i) {
        const auto &component = map.components[i];
        v.a[component.semantic] = out[component.reg][component.channel];
    }''', '''    for (uint32_t i = 0; i < map.run_count; ++i) {
        const auto &run = map.runs[i];
        const float *in = out[run.reg].v + run.channel;
        float *dst = v.a + run.semantic;
        switch (run.count) {
        case 4: std::memcpy(dst, in, 16); break;
        case 3: std::memcpy(dst, in, 12); break;
        case 2: std::memcpy(dst, in, 8); break;
        default: std::memcpy(dst, in, 4); break;
        }
    }
    static const bool verify_map = std::getenv("SM3DL_VERIFY_COHERENT_OUTPUTS") != nullptr;
    if (verify_map) {
        Vertex reference{};
        for (uint32_t i = 0; i < map.component_count; ++i) {
            const auto &component = map.components[i];
            reference.a[component.semantic] = out[component.reg][component.channel];
        }
        if (std::memcmp(&reference, &v, sizeof v) != 0) fatal("PICA output copy plan mismatch");
    }''')
    source = once(source, '    const auto compiled = interpret ? nullptr : find_compiled_shader(vs, regs[VS_ENTRY] & 0xFFFF, shader_revision);', '''    uint16_t used_inputs = 0xffff;
    CompiledVertexUsage usage{};
    const auto compiled = interpret ? nullptr : find_compiled_shader(vs, regs[VS_ENTRY] & 0xFFFF, shader_revision, &usage);
    static const bool all_inputs = std::getenv("SM3DL_ALL_VERTEX_INPUTS") || std::getenv("SM3DL_VERIFY_VERTEX");
    static const bool all_outputs = std::getenv("SM3DL_ALL_VERTEX_OUTPUTS") || std::getenv("SM3DL_VERIFY_VERTEX");
    if (!all_inputs) used_inputs = usage.inputs;
    if (!all_outputs && compiled) map.configure_output_initialization(usage);''')
    source = once(source, 'Vertex shade_mapped(const Vec4 in[16], const OutputMap &map, CompiledVertex compiled) {\n    Vec4 out[16] = {};',
        '''Vertex shade_mapped(const Vec4 in[16], const OutputMap &map, CompiledVertex compiled) {
    Vec4 out[16];
    if (map.zero_count > 8) std::memset(out, 0, sizeof out);
    else for (unsigned i = 0; i < map.zero_count; ++i) out[map.zero_regs[i]] = Vec4{};''')
    source = once(source, '    if (n >= 512 && !indexed) {', '''    const CoherentVertexFetch plan(loader, map, used_inputs);
    static const bool verify_inputs = std::getenv("SM3DL_VERIFY_COHERENT_INPUTS") != nullptr;
    static const bool verify_mask = std::getenv("SM3DL_VERIFY_INPUT_MASK") != nullptr;
    OutputMap reference_map = map;
    reference_map.zero_count = 16;
    if (verify_inputs && plan.valid) {
        static const bool announced = [] { LOG("pica: verifying coherent vertex inputs bit for bit"); return true; }();
        (void)announced;
    }
    auto shade_index = [&](uint32_t index) {
        if (plan.valid) {
            Vec4 in[16];
            plan.load(index, in);
            if (verify_inputs || verify_mask) {
                Vec4 original[16]{}, expected[16]{};
                loader.read(index, original);
                for (uint32_t i = 0; i < map.input_count; ++i) expected[map.input_registers[i]] = original[i];
                for (unsigned reg = 0; reg < 16; ++reg)
                    if ((used_inputs & (1u << reg)) && std::memcmp(&expected[reg], &in[reg], sizeof(Vec4)) != 0)
                        fatal("coherent PICA vertex input mismatch at index %u, register %u", index, reg);
                if (verify_mask && compiled) {
                    const Vertex actual = shade_mapped(in, map, compiled);
                    const Vertex reference = shade_mapped(expected, reference_map, compiled);
                    if (std::memcmp(&reference, &actual, sizeof actual) != 0)
                        fatal("PICA input-mask optimization changed shaded vertex at index %u", index);
                    return actual;
                }
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
