"""Opt-in AVX2 for independent vertex pairs; compare to the existing JIT."""
from coherent_pica_fast import once


def paired_vertices(source):
    source = once(source, '''    void load(uint32_t index, Vec4 in[16]) const {
        if (init_count > 8) std::memcpy(in, initial, sizeof initial);''', '''    template<unsigned Stride = 1>
    void load(uint32_t index, Vec4 in[16]) const {
        if (Stride == 1 && init_count > 8) std::memcpy(in, initial, sizeof initial);''')
    source = once(source, '            in[reg] = initial[reg];', '            in[reg * Stride] = initial[reg];')
    source = once(source, '            in[items[i].reg] = v;', '            in[items[i].reg * Stride] = v;')
    source = once(source, '''            in[items[i].reg * Stride] = v;
        }
    }
};''', '''            in[items[i].reg * Stride] = v;
        }
    }

    // Select a load format once per register, not once per vertex. Copies
    // access exactly the declared width (in particular, float3 reads 12 bytes).
    void load_pair(uint32_t first, uint32_t second, Vec4 out[32]) const {
        for (unsigned i = 0; i < init_count; ++i) {
            const auto reg = init_registers[i];
            out[2 * reg] = out[2 * reg + 1] = initial[reg];
        }
        for (unsigned i = 0; i < n; ++i) {
            const auto &item = items[i];
            const auto &a = item.src;
            const uint8_t *p0 = a.data + size_t(first) * a.stride;
            const uint8_t *p1 = a.data + size_t(second) * a.stride;
            Vec4 lo{{0, 0, 0, 1}}, hi{{0, 0, 0, 1}};
            if (a.type == 3) {
                switch (a.count) {
                case 4: std::memcpy(lo.v, p0, 16); std::memcpy(hi.v, p1, 16); break;
                case 3: std::memcpy(lo.v, p0, 12); std::memcpy(hi.v, p1, 12); break;
                case 2: std::memcpy(lo.v, p0, 8); std::memcpy(hi.v, p1, 8); break;
                default: std::memcpy(lo.v, p0, 4); std::memcpy(hi.v, p1, 4); break;
                }
            } else if (a.type == 2) {
                for (unsigned k = 0; k < a.count; ++k) {
                    lo[k] = float(int16_t(load16(p0 + 2 * k)));
                    hi[k] = float(int16_t(load16(p1 + 2 * k)));
                }
            } else if (a.type == 1) {
                for (unsigned k = 0; k < a.count; ++k) lo[k] = float(p0[k]), hi[k] = float(p1[k]);
            } else {
                for (unsigned k = 0; k < a.count; ++k) lo[k] = float(int8_t(p0[k])), hi[k] = float(int8_t(p1[k]));
            }
            out[2 * item.reg] = lo;
            out[2 * item.reg + 1] = hi;
        }
    }
};''')
    source = once(source, '''    time_setup += std::chrono::duration_cast<std::chrono::nanoseconds>(t_shade - t_setup).count();''', '''    const auto setup_elapsed = std::chrono::duration_cast<std::chrono::nanoseconds>(t_shade - t_setup).count();
    time_setup += setup_elapsed;
    static const bool profile_setup = std::getenv("SM3DL_LAB_PROFILE_GEOMETRY") != nullptr;
    if (profile_setup) {
        static int64_t setup_bins[2]{};
        static auto setup_log = t_shade;
        setup_bins[regs[VERTEX_COUNT] >= lab_large_draw_min()] += setup_elapsed;
        if (t_shade - setup_log >= std::chrono::seconds(1)) {
            const double ms = 1e-6 / std::chrono::duration<double>(t_shade - setup_log).count();
            LOG("draw setup ms/s: small %.1f large %.1f", setup_bins[0] * ms, setup_bins[1] * ms);
            setup_log = t_shade;
            setup_bins[0] = setup_bins[1] = 0;
        }
    }''')
    source = once(source, 'Vertex shade_mapped(const Vec4 in[16], const OutputMap &map, CompiledVertex compiled) {',
        '''uint32_t lab_large_draw_min() {
    static const auto cutoff = [] {
        const char *value = std::getenv("SM3DL_LAB_LARGE_DRAW_MIN");
        return value ? uint32_t(std::clamp(std::atoi(value), 96, 4096)) : 256u;
    }();
    return cutoff;
}

Vertex shade_mapped(const Vec4 in[16], const OutputMap &map, CompiledVertex compiled) {''')
    source = once(source, 'Vertex shade_mapped(const Vec4 in[16], const OutputMap &map, CompiledVertex compiled) {', '''
template<unsigned Stride = 1>
Vertex map_shaded_vertex(const Vec4 out[16], const OutputMap &map);

Vertex shade_mapped(const Vec4 in[16], const OutputMap &map, CompiledVertex compiled) {''')
    source = once(source, '''        run_shader(vs, regs[VS_ENTRY] & 0xFFFF, in, out);
    }

    Vertex v{};''', '''        run_shader(vs, regs[VS_ENTRY] & 0xFFFF, in, out);
    }
    return map_shaded_vertex(out, map);
}

template<unsigned Stride>
Vertex map_shaded_vertex(const Vec4 out[16], const OutputMap &map) {
    Vertex v{};''')
    source = once(source, 'const float *in = out[run.reg].v + run.channel;',
                  'const float *in = out[run.reg * Stride].v + run.channel;')
    source = once(source, 'reference.a[component.semantic] = out[component.reg][component.channel];',
                  'reference.a[component.semantic] = out[component.reg * Stride][component.channel];')
    source = once(source, '''    const auto compiled = interpret ? nullptr : find_compiled_shader(vs, regs[VS_ENTRY] & 0xFFFF, shader_revision, &usage);''', '''    const uint32_t n = regs[VERTEX_COUNT];
    const bool large = n >= lab_large_draw_min();
    CompiledVertexPair pair = nullptr;
    CompiledVertexPair guarded_pair = nullptr;
    const auto compiled = interpret ? nullptr : find_compiled_shader(vs, regs[VS_ENTRY] & 0xFFFF, shader_revision, &usage,
        large ? &pair : nullptr, large ? &guarded_pair : nullptr);''')
    source = once(source, '''    uint32_t n = regs[VERTEX_COUNT];
    const uint8_t *indices = nullptr;''', '''    const uint8_t *indices = nullptr;''')
    source = once(source, '''    if (n >= 512 && !indexed) {''', '''    static const bool verify_pairs = std::getenv("SM3DL_LAB_VERIFY_PAIRS") != nullptr;
    static const bool trace_pairs = verify_pairs || std::getenv("SM3DL_LAB_PAIR_TRACE") != nullptr;
    static const bool force_retry = verify_pairs && std::getenv("SM3DL_LAB_FORCE_MULTIPLY_RETRY") != nullptr;
    static const bool interleaved_pair = true;
    static const bool load_together = true;
    static const auto multiply_tile = [] {
        const char *value = std::getenv("SM3DL_LAB_MULTIPLY_TILE");
        return value ? size_t(std::clamp(std::atoi(value), 8, 512) & ~1) : size_t(32);
    }();
    static const bool profile_geometry = std::getenv("SM3DL_LAB_PROFILE_GEOMETRY") != nullptr;
    static uint64_t split_ns[5]{};
    static auto last_split_log = t_shade;
    auto split_start = t_shade;
    auto phase = [&](unsigned stage) {
        if (profile_geometry) {
            const auto now = std::chrono::steady_clock::now();
            split_ns[stage] += std::chrono::duration_cast<std::chrono::nanoseconds>(now - split_start).count();
            split_start = now;
        }
    };
    auto shade_range = [&](std::vector<Vertex> &out, const auto &at) {
        const auto total = out.size();
        const bool together = pair && plan.valid && !verify_inputs && !verify_mask;
        std::atomic<uint32_t> completed{0};
        std::atomic<uint32_t> guarded_ok{0}, guarded_retry{0};
        auto shade_lane = [&]<bool Interleaved>(size_t begin, size_t end) {
            size_t k = begin;
            unsigned paired_vertices = 0, ok_vertices = 0, retry_vertices = 0;
            if (together) {
                auto emit_pair = [&](size_t index, CompiledVertexPair shader, bool verify, bool compare_fast) {
                    Vec4 in[32], results[32], scratch[43];
                    constexpr unsigned stride = Interleaved ? 2 : 1;
                    constexpr unsigned second = Interleaved ? 1 : 16;
                    if constexpr (Interleaved) {
                        if (load_together) plan.load_pair(at(index), at(index + 1), in);
                        else {
                            plan.load<2>(at(index), in);
                            plan.load<2>(at(index + 1), in + 1);
                        }
                    } else {
                        plan.load(at(index), in);
                        plan.load(at(index + 1), in + 16);
                    }
                    if (verify || map.zero_count > 8) std::memset(results, 0, sizeof results);
                    else for (unsigned i = 0; i < map.zero_count; ++i) {
                        const auto reg = map.zero_regs[i];
                        results[reg * stride] = results[reg * stride + second] = Vec4{};
                    }
                    if (verify) std::memset(scratch, 0x5a, sizeof scratch);
                    const bool paired = shader(vs.f, in, results, scratch);
                    Vec4 scalar_in[32];
                    const Vec4 *scalar = in;
                    if (Interleaved && (verify || !paired)) {
                        plan.load(at(index), scalar_in);
                        plan.load(at(index + 1), scalar_in + 16);
                        scalar = scalar_in;
                        if (verify && load_together) {
                            for (unsigned reg = 0; reg < 16; ++reg) if (used_inputs & (1u << reg)) {
                                if (std::memcmp(in + 2 * reg, scalar + reg, sizeof(Vec4)) ||
                                    std::memcmp(in + 2 * reg + 1, scalar + reg + 16, sizeof(Vec4)))
                                    fatal("Interleaved vertex input differs at register %u", reg);
                            }
                        }
                    }
                    if (paired && verify) {
                        Vec4 expected[32]{}, single_scratch[16];
                        compiled(vs.f, scalar, expected, single_scratch);
                        compiled(vs.f, scalar + 16, expected + 16, single_scratch);
                        for (unsigned i = 0; i < 32; ++i)
                            if (std::memcmp(expected + i, results + (i % 16) * stride + (i / 16) * second, sizeof(Vec4)))
                                fatal("AVX2 vertex result differs from scalar output at entry %#x, index %u, register %u",
                                    regs[VS_ENTRY] & 0xFFFF, at(index + i / 16), i % 16);
                    }
                    const Vertex a = !paired ? shade_mapped(scalar, map, compiled) : Interleaved ?
                        map_shaded_vertex<2>(results, map) : map_shaded_vertex(results, map);
                    const Vertex b = !paired ? shade_mapped(scalar + 16, map, compiled) : Interleaved ?
                        map_shaded_vertex<2>(results + 1, map) : map_shaded_vertex(results + 16, map);
                    if (compare_fast && (std::memcmp(&a, &out[index], sizeof a) ||
                                         std::memcmp(&b, &out[index + 1], sizeof b))) {
                        fatal("Guarded multiply changed vertex output at entry %#x, index %u",
                            regs[VS_ENTRY] & 0xFFFF, at(index));
                    }
                    out[index] = a;
                    out[index + 1] = b;
                    return paired;
                };
                // With all FP exceptions masked, VMULPS sets the sticky invalid bit
                // on a zero-times-infinity product. Such a tile is recomputed before
                // any of its scratch results reach triangle assembly. No rounding mode
                // or exception mask is changed. Keep the old numerical flags on retry.
                if (guarded_pair && (_mm_getcsr() & 0x1f80u) == 0x1f80u) {
                    const size_t last = begin + ((end - begin) & ~size_t(1));
                    for (; k < last;) {
                        const size_t first = k;
                        const size_t limit = std::min(last, first + multiply_tile);
                        const unsigned saved = _mm_getcsr();
                        _mm_setcsr(saved & ~1u);
                        std::atomic_signal_fence(std::memory_order_seq_cst);
                        unsigned attempted = 0;
                        for (; k < limit; k += 2)
                            if (emit_pair(k, guarded_pair, false, false) && trace_pairs) attempted += 2;
                        std::atomic_signal_fence(std::memory_order_seq_cst);
                        const unsigned flags = _mm_getcsr();
                        const bool invalid = (flags & 1u) != 0;
                        static thread_local unsigned trial_tiles = 0;
                        const bool forced = force_retry && (++trial_tiles % 1024u) == 1;
                        const bool retry = invalid || forced;
                        _mm_setcsr(retry ? saved : saved | (flags & 0x3fu));
                        if (retry) retry_vertices += unsigned(limit - first);
                        else ok_vertices += unsigned(limit - first);
                        if (retry || verify_pairs) {
                            attempted = 0;
                            for (size_t j = first; j < limit; j += 2)
                                if (emit_pair(j, pair, verify_pairs, verify_pairs && !invalid) && trace_pairs) attempted += 2;
                        }
                        paired_vertices += attempted;
                    }
                } else {
                    for (; k + 1 < end; k += 2)
                        if (emit_pair(k, pair, verify_pairs, false) && trace_pairs) paired_vertices += 2;
                }
            }
            for (; k < end; ++k) out[k] = shade_index(at(k));
            if (trace_pairs && paired_vertices) completed.fetch_add(paired_vertices, std::memory_order_relaxed);
            if (trace_pairs && ok_vertices) guarded_ok.fetch_add(ok_vertices, std::memory_order_relaxed);
            if (trace_pairs && retry_vertices) guarded_retry.fetch_add(retry_vertices, std::memory_order_relaxed);
        };
        auto shade_slice = [&](size_t begin, size_t end) {
            if (interleaved_pair) shade_lane.template operator()<true>(begin, end);
            else shade_lane.template operator()<false>(begin, end);
        };
        workers().run(total, shade_slice);
        if (trace_pairs) {
            static uint64_t eligible = 0, vertices = 0, paired = 0, next_log = 1000000;
            static uint64_t guarded_accepted = 0, repeats = 0;
            vertices += total;
            if (together) eligible += total;
            paired += completed.load(std::memory_order_relaxed);
            guarded_accepted += guarded_ok.load(std::memory_order_relaxed);
            repeats += guarded_retry.load(std::memory_order_relaxed);
            if (vertices >= next_log) {
                LOG("vertex pairs: %llu of %llu large-draw vertices (%llu eligible)%s", (unsigned long long)paired,
                    (unsigned long long)vertices, (unsigned long long)eligible, verify_pairs ? " (bit verification)" : "");
                if (guarded_accepted || repeats)
                    LOG("guarded multiply: %llu accepted vertices, %llu recomputed",
                        (unsigned long long)guarded_accepted, (unsigned long long)repeats);
                next_log = vertices + 1000000;
            }
        }
    };
    if (large && !indexed) {''')
    source = once(source, '''        workers().run(n, [&](size_t begin, size_t end) {
            for (size_t k = begin; k < end; ++k) shaded[k] = shade_index(first + uint32_t(k));
        });''', '''        phase(0);
        shade_range(shaded, [&](size_t k) { return first + uint32_t(k); });
        phase(1);''')
    source = once(source, '''        workers().run(unique.size(), [&](size_t begin, size_t end) {
            for (size_t k = begin; k < end; ++k) shaded[k] = shade_index(unique[k]);
        });''', '''        phase(0);
        shade_range(shaded, [&](size_t k) { return unique[k]; });
        phase(1);''')
    source = once(source, '''        w = shaded.back().a[POS + 3];
    } else if''', '''        w = shaded.back().a[POS + 3];
        phase(2);
    } else if''')
    source = once(source, '''    } else if (n >= 512) {''', '''    } else if (large) {''')
    source = once(source, '''        for (uint32_t index : unique) slot[index] = -1;
    } else {''', '''        for (uint32_t index : unique) slot[index] = -1;
        phase(2);
    } else {''')
    source = once(source, '''    }
    time_vertices += std::chrono::duration_cast''', '''        phase(3);
    }
    time_vertices += std::chrono::duration_cast''')
    return once(source, '''    finish_deferring();
    end_draw();
    log_draw_end(n, indexed, w);''', '''    finish_deferring();
    end_draw();
    phase(4);
    if (profile_geometry && split_start - last_split_log >= std::chrono::seconds(1)) {
        const double ms = 1e-6 / std::chrono::duration<double>(split_start - last_split_log).count();
        LOG("geometry ms/s: index %.1f shade %.1f assemble %.1f small %.1f finish %.1f",
            split_ns[0] * ms, split_ns[1] * ms, split_ns[2] * ms, split_ns[3] * ms, split_ns[4] * ms);
        for (auto &item : split_ns) item = 0;
        last_split_log = split_start;
    }
    log_draw_end(n, indexed, w);''')
