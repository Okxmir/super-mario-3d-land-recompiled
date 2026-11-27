// Two independent PICA vertices in the two 128-bit halves of a YMM register.
// Address registers stay independent for each vertex (bone lookup).
// When the halves disagree about a branch, the caller re-runs them separately.
constexpr bool lab_pair_condition(unsigned nibble, unsigned reference, unsigned mode) {
    const unsigned differences = (nibble ^ reference) & 3;
    if (mode == 0) return differences != 3;
    if (mode == 1) return differences == 0;
    return !(differences & (mode - 1));
}

struct LabPairConditionLut { uint64_t different = 0, taken = 0; };

constexpr LabPairConditionLut lab_pair_condition_lut(unsigned reference, unsigned mode) {
    LabPairConditionLut table;
    for (unsigned hi = 0; hi < 4; ++hi) for (unsigned lo = 0; lo < 4; ++lo) {
        const unsigned bit = lo | (hi << 4);
        const bool left = lab_pair_condition(lo, reference, mode);
        const bool right = lab_pair_condition(hi, reference, mode);
        if (left != right) table.different |= uint64_t(1) << bit;
        if (left) table.taken |= uint64_t(1) << bit;
    }
    return table;
}

static_assert([] {
    for (unsigned mode = 0; mode < 4; ++mode) for (unsigned r = 0; r < 4; ++r) {
        const auto lut = lab_pair_condition_lut(r, mode);
        for (unsigned mask = 0; mask < 256; ++mask) {
            const unsigned canon = mask & 0x33;
            const unsigned low = (mask & 3) ^ r, high = ((mask >> 4) & 3) ^ r;
            const auto expected = [&](unsigned bits) {
                if (mode == 0) return (bits & 3) != 3;
                const unsigned arg = mode == 1 ? 3 : mode - 1;
                return (bits & arg) == 0;
            };
            if (bool((lut.different >> canon) & 1) != (expected(low) != expected(high)) ||
                bool((lut.taken >> canon) & 1) != expected(low)) return false;
        }
    }
    return true;
}());

class VertexPairEmitter final : public Xbyak::CodeGenerator {
public:
    VertexPairEmitter() : CodeGenerator(4096, Xbyak::AutoGrow) {}
    CompiledVertexUsage usage{0, 0, 0};
    unsigned rejected_opcode = 64;
    std::array<unsigned, 16> temp_hits{};
    std::array<unsigned, 16> temp_regs{};
    uint16_t graph_temp_zero = 0xffff, required_temp_zero = 0xffff;
    uint16_t planned_temp_zero = 0xffff;
    std::vector<uint16_t> incoming_temp_plan, computed_temp_plan;
    bool defer_invalid_multiply = false;
    bool interleaved_vertices = false;
    bool fast_conditions = false;
    bool profile_program = false;
    bool look_for_matrices = false;
    bool fuse_matrices = false;
    LabPairProgramProfile lab_profile;
    LabPairMatrixPlan matrices;

    bool cache_frequent_temps(const std::array<unsigned, 16> &hits) {
        std::array<unsigned, 16> order{};
        for (unsigned i = 0; i < 16; ++i) order[i] = i;
        std::sort(order.begin(), order.end(), [&](unsigned a, unsigned b) { return hits[a] > hits[b]; });
        unsigned count = 0;
        while (count < 10 && hits[order[count]] >= 4) {
            temp_regs[order[count]] = 6 + count;
            ++count;
        }
        return count != 0;
    }

    bool compile(const ShaderSetup &shader, uint32_t entry, bool graph = false) {
#ifdef _WIN32
        // Keep the volatile 256-bit semantics while saving the ABI's nonvolatile
        // low half of each extra register in the caller-owned scratch buffer.
        for (const unsigned reg : temp_regs)
            if (reg) vmovups(ptr[temps + saved_reg_offset(reg)], Xbyak::Xmm(reg));
        if (graph && fuse_matrices) {
            vmovups(ptr[temps + saved_reg_offset(6)], xmm6);
            vmovups(ptr[temps + saved_reg_offset(7)], xmm7);
        }
#endif
        unsigned budget = 4096;
        auto emit = [&](uint32_t word, int32_t loop) {
            if (!budget--) return false;
            const auto ins = decode_arithmetic(word);
            if (arithmetic(ins, shader.swizzle[ins.descriptor], loop)) return true;
            rejected_opcode = word >> 26;
            return false;
        };
        auto branch = [&](uint32_t word, uint32_t, uint32_t, uint32_t, int32_t) {
            rejected_opcode = word >> 26;
            return false;
        };
        if (graph) {
            if (!emit_graph(shader, entry)) return false;
            L(diverged);
            vxorps(ymm0, ymm0, ymm0);
            end(false);
        } else {
            if (!specialize_vertex_program(shader, entry, emit, branch)) return false;
            end(true);
        }
        limit_output_zeroing(usage);
        lab_profile.machine_bytes = uint32_t(getSize());
        readyRE();
#ifdef _WIN32
        return FlushInstructionCache(GetCurrentProcess(), getCode(), getSize()) != 0;
#else
        return true;
#endif
    }

private:
#ifdef _WIN32
    const Xbyak::Reg64 &uniforms = rcx, &inputs = rdx, &outputs = r8, &temps = r9;
#else
    const Xbyak::Reg64 &uniforms = rdi, &inputs = rsi, &outputs = rdx, &temps = rcx;
#endif
    uint16_t initialized = 0;
    uint16_t block_writes = 0, block_reads_before_write = 0;
    uint8_t address_written = 0;
    bool compare_enabled = false;
    uint32_t previous_dot_operand = ~0u;
    Xbyak::Label diverged;
    static constexpr unsigned stride = 16 * sizeof(Vec4);
    static constexpr unsigned address_scratch = 2 * stride;
    static unsigned saved_reg_offset(unsigned reg) { return address_scratch + 16 + (reg - 6) * 16; }

    void end(bool ok) {
#ifdef _WIN32
        for (const unsigned reg : temp_regs)
            if (reg) vmovups(Xbyak::Xmm(reg), ptr[temps + saved_reg_offset(reg)]);
        if (fuse_matrices) {
            vmovups(xmm6, ptr[temps + saved_reg_offset(6)]);
            vmovups(xmm7, ptr[temps + saved_reg_offset(7)]);
        }
#endif
        mov(eax, unsigned(ok));
        vzeroupper();
        ret();
    }

    void load_temp(const Xbyak::Ymm &dst, unsigned slot) {
        ++temp_hits[slot];
        const uint16_t bit = uint16_t(1u << slot);
        if (!(initialized & (1u << slot))) vxorps(dst, dst, dst);
        else {
            if (!(block_writes & bit)) block_reads_before_write |= bit;
            if (temp_regs[slot]) vmovaps(dst, Xbyak::Ymm(temp_regs[slot]));
            else vmovups(dst, ptr[temps + slot * 32]);
        }
    }

    void save_temp(unsigned slot, const Xbyak::Ymm &src) {
        ++temp_hits[slot];
        block_writes |= uint16_t(1u << slot);
        if (temp_regs[slot]) vmovaps(Xbyak::Ymm(temp_regs[slot]), src);
        else vmovups(ptr[temps + slot * 32], src);
    }

    void jump_on_condition(uint32_t word, Xbyak::Label &label, bool taken) {
        if (profile_program) { ++lab_profile.branches; previous_dot_operand = ~0u; }
        vmovmskps(eax, ymm4);
        const unsigned reference = ((word >> 25) & 1) | (((word >> 24) & 1) << 1);
        const unsigned mode = (word >> 22) & 3;
        if (fast_conditions) {
            const auto table = lab_pair_condition_lut(reference, mode);
            and_(eax, 0x33);
            mov(r11, table.different);
            bt(r11, rax);
            jc(diverged, T_NEAR);
            mov(r11, table.taken);
            bt(r11, rax);
            if (taken) jc(label, T_NEAR);
            else jnc(label, T_NEAR);
            return;
        }
        if (reference) xor_(eax, reference | (reference << 4));
        mov(r11d, eax);
        shr(r11d, 4);
        if (mode == 0) {
            and_(eax, 3);
            and_(r11d, 3);
            cmp(eax, 3); setne(al);
            cmp(r11d, 3); setne(r11b);
        } else {
            const unsigned mask = mode == 1 ? 3 : mode - 1;
            test(eax, mask); setz(al);
            test(r11d, mask); setz(r11b);
        }
        cmp(al, r11b);
        jne(diverged, T_NEAR);
        test(al, al);
        if (taken) jnz(label, T_NEAR);
        else jz(label, T_NEAR);
    }

    void compare(const Xbyak::Ymm &dst, unsigned mode) {
        if (mode >= 6) vpcmpeqd(dst, dst, dst);
        else if (mode >= 4) vcmpps(dst, ymm1, ymm0, mode - 3);
        else {
            static constexpr unsigned predicates[]{0, 4, 1, 2};
            vcmpps(dst, ymm0, ymm1, predicates[mode]);
        }
    }

    void one(const Xbyak::Ymm &dst) {
        mov(eax, 0x3f800000);
        vmovd(Xbyak::Xmm(dst.getIdx()), eax);
        vbroadcastss(dst, Xbyak::Xmm(dst.getIdx()));
    }

    void load_pair(const Xbyak::Ymm &dst, const Xbyak::Reg64 &base, unsigned reg) {
        if (interleaved_vertices) {
            vmovups(dst, ptr[base + reg * 2 * sizeof(Vec4)]);
            return;
        }
        vmovups(Xbyak::Xmm(dst.getIdx()), ptr[base + reg * sizeof(Vec4)]);
        vinsertf128(dst, dst, ptr[base + reg * sizeof(Vec4) + stride], 1);
    }

    void relative_pair(const Xbyak::Ymm &dst, unsigned index, unsigned relative) {
        Xbyak::Label lo_done, hi_done;
        one(dst); // out-of-range addresses return one, independently in each lane
        const unsigned slot = address_scratch + (relative - 1) * 8;
        mov(r10d, dword[temps + slot]);
        add(r10d, index);
        cmp(r10d, 96);
        jae(lo_done);
        shl(r10d, 4);
        vinsertf128(dst, dst, ptr[uniforms + r10], 0);
        L(lo_done);
        mov(r10d, dword[temps + slot + 4]);
        add(r10d, index);
        cmp(r10d, 96);
        jae(hi_done);
        shl(r10d, 4);
        vinsertf128(dst, dst, ptr[uniforms + r10], 1);
        L(hi_done);
    }

    bool operand(const Xbyak::Ymm &dst, unsigned reg, unsigned relative, uint32_t selector, int32_t loop) {
        if (reg < 16) {
            usage.inputs |= uint16_t(1u << reg);
            load_pair(dst, inputs, reg);
        } else if (reg < 32) {
            load_temp(dst, reg - 16);
        } else {
            const unsigned index = (reg - 32) + (relative == 3 ? loop : 0);
            if ((relative == 1 || relative == 2) && (address_written & (1u << (relative - 1)))) {
                if (profile_program) ++lab_profile.relative_loads;
                relative_pair(dst, index, relative);
            } else if (index < 96) vbroadcastf128(dst, ptr[uniforms + index * sizeof(Vec4)]);
            else one(dst);
        }
        const unsigned order = (selector >> 1) & 255;
        if (order != 0x1b) {
            const unsigned lanes = ((order & 3) << 6) | ((order & 12) << 2) |
                                   ((order & 48) >> 2) | ((order & 192) >> 6);
            vshufps(dst, dst, dst, lanes);
        }
        if (selector & 1) {
            vpcmpeqd(ymm5, ymm5, ymm5);
            vpslld(ymm5, ymm5, 31);
            vxorps(dst, dst, ymm5);
        }
        return true;
    }

    void mul() {
        if (defer_invalid_multiply) {
            vmulps(ymm0, ymm0, ymm1);
            return;
        }
        vcmpps(ymm2, ymm0, ymm1, 7); // ordered operands
        vmulps(ymm0, ymm0, ymm1);
        vcmpps(ymm3, ymm0, ymm0, 3); // unordered result
        vandps(ymm2, ymm2, ymm3);
        vandnps(ymm0, ymm2, ymm0);
    }

    void dot(unsigned op) {
        mul();
        vshufps(ymm2, ymm0, ymm0, 0x55);
        vaddps(ymm2, ymm2, ymm0); // x+y in lane zero of each half
        vshufps(ymm3, ymm0, ymm0, 0xaa);
        vaddps(ymm2, ymm2, ymm3);
        if (op != 0x01) {
            const auto &w = op == 0x02 ? ymm0 : ymm1;
            vshufps(ymm3, w, w, 0xff);
            vaddps(ymm2, ymm2, ymm3);
        }
        vshufps(ymm0, ymm2, ymm2, 0);
    }

    struct DotMatrix {
        uint8_t rows[4]{};
        uint8_t input = 0, destination = 0;
        uint16_t input_selector = 0;
    };

    // Find four DP4 instructions that fill different channels of one output.
    // The row-vector operand must be a direct uniform. The common input may
    // be swizzled/negated; it is still the same in all four instructions.
    static bool matrix_group(const ShaderSetup &shader, uint32_t first, DotMatrix &matrix) {
        unsigned channels = 0;
        for (unsigned n = 0; n < 4; ++n) {
            const auto ins = decode_arithmetic(shader.code[(first + n) & 4095]);
            if ((ins.word >> 26) != 2 || ins.source[0] < 32 || ins.address[0] || ins.destination >= 16)
                return false;
            const uint32_t desc = shader.swizzle[ins.descriptor];
            if (((desc >> 4) & 511) != 0x36) return false; // unnegated xyzw row
            const unsigned mask = desc & 15;
            if (!std::has_single_bit(mask) || (channels & mask)) return false;
            channels |= mask;
            const auto sel = uint16_t((desc >> 13) & 511);
            if (!n) {
                matrix.destination = ins.destination;
                matrix.input = ins.source[1];
                matrix.input_selector = sel;
            } else if (matrix.destination != ins.destination || matrix.input != ins.source[1] || sel != matrix.input_selector) {
                return false;
            }
            matrix.rows[3 - std::countr_zero(mask)] = ins.source[0] - 32;
        }
        return true;
    }

    bool try_emit_matrix(const DotMatrix &matrix) {
        unsigned slot = 0;
        for (; slot < matrices.count; ++slot)
            if (std::memcmp(matrices.rows[slot], matrix.rows, sizeof matrix.rows) == 0) break;
        if (slot >= LabPairMatrixPlan::capacity) return false;
        if (slot == matrices.count) {
            std::memcpy(matrices.rows[slot], matrix.rows, sizeof matrix.rows);
            ++matrices.count;
        }
        operand(ymm6, matrix.input, 0, matrix.input_selector, 0);
        for (unsigned column = 0; column < 4; ++column) {
            vbroadcastf128(ymm0, ptr[uniforms + (96 + 4*slot + column) * sizeof(Vec4)]);
            vshufps(ymm1, ymm6, ymm6, 0x55 * column);
            mul();
            // Keep the same y+x, then +z, then +w order as the original
            // code, including its NaN/signed-zero behavior; no FMA is used.
            if (column == 0) vmovaps(ymm7, ymm0);
            else if (column == 1) vaddps(ymm7, ymm0, ymm7);
            else vaddps(ymm7, ymm7, ymm0);
        }
        const unsigned dest = matrix.destination;
        usage.written_outputs |= uint16_t(1u << dest);
        if (interleaved_vertices) vmovups(ptr[outputs + dest * 2 * sizeof(Vec4)], ymm7);
        else {
            vmovups(ptr[outputs + dest * sizeof(Vec4)], xmm7);
            vextractf128(ptr[outputs + dest * sizeof(Vec4) + stride], ymm7, 1);
        }
        if (profile_program) lab_profile.ops[2] += 4;
        return true;
    }

    bool arithmetic(const ArithmeticInstruction &ins, uint32_t desc, int32_t loop) {
        const unsigned op = ins.word >> 26, mask = desc & 15;
        if (profile_program) {
            if (mask || ((op == 0x2e || op == 0x2f) && compare_enabled)) ++lab_profile.ops[op];
            const bool uniform_dot = mask && (op == 1 || op == 2 || op == 3) &&
                ins.source[1] < 32 && ins.source[0] >= 32 && !ins.address[0];
            const uint32_t dot_operand = uniform_dot ? (uint32_t(ins.source[1]) << 9) | ((desc >> 13) & 511) : ~0u;
            lab_profile.uniform_dots += uniform_dot;
            // Diagnostic only: even a matching operand does not prove that
            // the instruction between the dots didn't change that register.
            lab_profile.same_dot_vector += uniform_dot && dot_operand == previous_dot_operand;
            previous_dot_operand = dot_operand;
        }
        if (op == 0x2e || op == 0x2f) {
            if (!compare_enabled) return true;
            operand(ymm0, ins.source[0], ins.address[0], desc >> 4, loop);
            operand(ymm1, ins.source[1], ins.address[1], desc >> 13, loop);
            const unsigned xmode = (ins.word >> 24) & 7, ymode = (ins.word >> 21) & 7;
            if (xmode == ymode) {
                if (profile_program) ++lab_profile.equal_comparisons;
                if (fast_conditions) {
                    compare(ymm4, xmode);
                    return true;
                }
            }
            compare(ymm2, xmode);
            vshufps(ymm0, ymm0, ymm0, 0x55);
            vshufps(ymm1, ymm1, ymm1, 0x55);
            compare(ymm3, ymode);
            vblendps(ymm4, ymm2, ymm3, 0x22);
            return true;
        }
        if (op == 0x07) return false;
        if (!mask) return true;
        if (!operand(ymm0, ins.source[0], ins.address[0], desc >> 4, loop)) return false;
        switch (op) {
        case 0x0b: vroundps(ymm0, ymm0, 1 | 8); break;
        case 0x0e:
        case 0x0f:
            vshufps(ymm0, ymm0, ymm0, 0);
            if (op == 0x0f) vsqrtps(ymm0, ymm0);
            one(ymm1);
            vdivps(ymm0, ymm1, ymm0);
            break;
        case 0x12: // MOVA: keep both half-register values for relative lookups.
            if (mask & 12) {
                vcvttps2dq(ymm3, ymm0);
                vextractf128(xmm2, ymm3, 1);
                for (unsigned axis = 0; axis < 2; ++axis) if (mask & (8u >> axis)) {
                    vpextrd(dword[temps + address_scratch + 8 * axis], xmm3, axis);
                    vpextrd(dword[temps + address_scratch + 8 * axis + 4], xmm2, axis);
                    address_written |= uint8_t(1u << axis);
                }
            }
            return true;
        case 0x13: break;
        default:
            if (!operand(ymm1, ins.source[1], ins.address[1], desc >> 13, loop)) return false;
            switch (op) {
            case 0x00: vaddps(ymm0, ymm0, ymm1); break;
            case 0x01: case 0x02: case 0x03: case 0x18: dot(op); break;
            case 0x04: case 0x19: // DST
                vmovaps(ymm5, ymm0);
                mul();
                vblendps(ymm0, ymm0, ymm5, 0x44);
                vblendps(ymm0, ymm0, ymm1, 0x88);
                one(ymm5);
                vblendps(ymm0, ymm0, ymm5, 0x11);
                break;
            case 0x08: mul(); break;
            case 0x09: case 0x1a:
                vcmpps(ymm1, ymm1, ymm0, 2);
                one(ymm0);
                vandps(ymm0, ymm0, ymm1);
                break;
            case 0x0a: case 0x1b:
                vcmpps(ymm0, ymm0, ymm1, 1);
                one(ymm1);
                vandps(ymm0, ymm0, ymm1);
                break;
            case 0x0c: vmaxps(ymm0, ymm0, ymm1); break;
            case 0x0d: vminps(ymm0, ymm0, ymm1); break;
            default:
                if (op < 0x30) return false;
                mul();
                if (!operand(ymm1, ins.source[2], ins.address[2], desc >> 22, loop)) return false;
                vaddps(ymm0, ymm0, ymm1);
                break;
            }
        }
        const bool output = ins.destination < 16;
        const unsigned index = ins.destination & 15;
        const uint16_t bit = uint16_t(1u << index);
        if (output) {
            if (!(usage.written_outputs & bit) && mask != 15) usage.read_before_write |= bit;
            usage.written_outputs |= bit;
        }
        if (mask != 15) {
            if (output) load_pair(ymm1, outputs, index);
            else load_temp(ymm1, index);
            const unsigned lanes = ((mask & 1) << 3) | ((mask & 2) << 1) |
                                   ((mask & 4) >> 1) | ((mask & 8) >> 3);
            vblendps(ymm0, ymm1, ymm0, lanes | (lanes << 4));
        }
        if (output) {
            if (interleaved_vertices) vmovups(ptr[outputs + index * 2 * sizeof(Vec4)], ymm0);
            else {
                vmovups(ptr[outputs + index * sizeof(Vec4)], xmm0);
                vextractf128(ptr[outputs + index * sizeof(Vec4) + stride], ymm0, 1);
            }
        } else {
            save_temp(index, ymm0);
            initialized |= bit;
        }
        return true;
    }

    // Match the single-vertex graph's PICA call and return rules. Both lanes
    // follow the same path here; no speculative writes cross a divergent jump.
    bool emit_graph(const ShaderSetup &shader, uint32_t entry) {
        compare_enabled = true;
        usage.read_before_write = 0xffff;
        initialized = 0xffff;
        address_written = 3;
        vxorps(ymm4, ymm4, ymm4);
        for (unsigned i = 0; i < 16; ++i) if (graph_temp_zero & (1u << i)) {
            if (temp_regs[i]) vxorps(Xbyak::Ymm(temp_regs[i]), Xbyak::Ymm(temp_regs[i]), Xbyak::Ymm(temp_regs[i]));
            else vmovups(ptr[temps + i * 32], ymm4);
        }
        vmovups(ptr[temps + address_scratch], xmm4);
        struct Frame {
            uint32_t end, resume;
            auto operator<=>(const Frame &) const = default;
        };
        struct State {
            uint32_t pc;
            size_t depth = 0;
            std::array<Frame, 16> frames{};
            auto operator<=>(const State &) const = default;
            void resolve() {
                while (depth && pc == frames[depth - 1].end) {
                    pc = frames[depth - 1].resume;
                    frames[--depth] = {};
                }
            }
            bool enter(uint32_t first, uint32_t end, uint32_t resume) {
                if (depth == frames.size()) return false;
                frames[depth++] = {end, resume};
                pc = first;
                return true;
            }
        };
        struct Edge { size_t destination; uint16_t writes_before_branch; };
        struct Block { State state; Xbyak::Label label; std::vector<Edge> edges; uint16_t initial_reads = 0; };
        std::map<State, size_t> indices;
        std::deque<Block> blocks;
        auto enqueue = [&](State state) {
            state.resolve();
            const auto [it, inserted] = indices.try_emplace(state, blocks.size());
            if (inserted) blocks.push_back({state, {}, {}});
            return it->second;
        };
        enqueue(State{entry});
        unsigned budget = 4096;
        for (size_t i = 0; i < blocks.size(); ++i) {
            auto &block = blocks[i];
            auto state = block.state;
            if (!incoming_temp_plan.empty() && i >= incoming_temp_plan.size()) return false;
            initialized = incoming_temp_plan.empty() ? 0xffff : incoming_temp_plan[i];
            previous_dot_operand = ~0u;
            block_writes = block_reads_before_write = 0;
            auto branch_label = [&](State target) -> Xbyak::Label & {
                const size_t next = enqueue(target);
                block.edges.push_back({next, block_writes});
                return blocks[next].label;
            };
            L(block.label);
            for (;;) {
                if (!budget--) return false;
                const uint32_t word = shader.code[state.pc++ & 4095], op = word >> 26;
                const uint32_t count = word & 255, target = (word >> 10) & 4095;
                const bool uniform = (shader.b >> ((word >> 22) & 15)) & 1;
                rejected_opcode = op;
                if (op == 0x22) {
                    end(true);
                    break;
                }
                if (op < 0x20 || op >= 0x2e) {
                    if (op == 2 && (look_for_matrices || profile_program || fuse_matrices)) {
                        DotMatrix matrix;
                        const uint32_t first = state.pc - 1;
                        auto scan = state;
                        bool consecutive = true;
                        for (unsigned j = 1; j < 4; ++j) {
                            scan.resolve();
                            if (scan.pc != first + j || indices.find(scan) != indices.end()) consecutive = false;
                            ++scan.pc;
                        }
                        if (consecutive && matrix_group(shader, first, matrix)) {
                            ++lab_profile.matrix_groups;
                            if (fuse_matrices && try_emit_matrix(matrix)) {
                                if (budget < 3) return false;
                                budget -= 3;
                                state = scan;
                                state.resolve();
                                if (auto next = indices.find(state); next != indices.end()) {
                                    block.edges.push_back({next->second, block_writes});
                                    jmp(blocks[next->second].label, T_NEAR);
                                    break;
                                }
                                continue;
                            }
                        }
                    }
                    const auto ins = decode_arithmetic(word);
                    if (!arithmetic(ins, shader.swizzle[ins.descriptor], 0)) return false;
                } else if (op >= 0x24 && op <= 0x26) {
                    if (op == 0x25) {
                        auto taken = state;
                        if (!taken.enter(target, target + count, state.pc)) return false;
                        jump_on_condition(word, branch_label(taken), true);
                    } else if ((op == 0x24 || uniform) && !state.enter(target, target + count, state.pc)) {
                        return false;
                    }
                } else if (op == 0x27 || op == 0x28) {
                    if (target < state.pc) return false;
                    const uint32_t resume = target + count;
                    if (op == 0x28) {
                        auto other = state;
                        if (!other.enter(target, resume, resume)) return false;
                        jump_on_condition(word, branch_label(other), false);
                    }
                    const bool taken = op == 0x28 || uniform;
                    if (!state.enter(taken ? state.pc : target, taken ? target : resume, resume)) return false;
                } else if (op == 0x2c || op == 0x2d) {
                    if (target < state.pc) return false;
                    if (op == 0x2c) {
                        auto taken = state;
                        taken.pc = target;
                        jump_on_condition(word, branch_label(taken), true);
                    } else if (uniform != bool(count & 1)) state.pc = target;
                } else if (op != 0x21) return false;
                state.resolve();
                if (auto next = indices.find(state); next != indices.end()) {
                    block.edges.push_back({next->second, block_writes});
                    jmp(blocks[next->second].label, T_NEAR);
                    break;
                }
            }
            block.initial_reads = block_reads_before_write;
        }
        if (!incoming_temp_plan.empty() && incoming_temp_plan.size() != blocks.size()) return false;
        std::vector<size_t> incoming(blocks.size()), ready;
        for (const auto &block : blocks) for (const auto &edge : block.edges) ++incoming[edge.destination];
        for (size_t i = 0; i < incoming.size(); ++i) if (!incoming[i]) ready.push_back(i);
        // Intersect writes at every join: a temporary may skip its zero only
        // when every incoming path has already written it before its first read.
        std::vector<uint16_t> definitely_written(blocks.size(), 0xffff);
        computed_temp_plan.assign(blocks.size(), 0);
        for (const auto i : ready) definitely_written[i] = 0;
        required_temp_zero = 0;
        planned_temp_zero = 0;
        for (size_t i = 0; i < ready.size(); ++i) {
            const size_t from = ready[i];
            required_temp_zero |= uint16_t(blocks[from].initial_reads & ~definitely_written[from]);
            // If no edge can have written the register, synthesize zero in
            // its first read instead of reading scratch. Only paths that
            // disagree about having written need an initial zero in scratch.
            planned_temp_zero |= uint16_t(blocks[from].initial_reads & computed_temp_plan[from] & ~definitely_written[from]);
            for (const auto &edge : blocks[from].edges) {
                const size_t v = edge.destination;
                definitely_written[v] &= uint16_t(definitely_written[from] | edge.writes_before_branch);
                computed_temp_plan[v] |= uint16_t(computed_temp_plan[from] | edge.writes_before_branch);
                if (!--incoming[v]) ready.push_back(v);
            }
        }
        return ready.size() == blocks.size() && !(required_temp_zero & ~graph_temp_zero) &&
            (incoming_temp_plan.empty() || incoming_temp_plan == computed_temp_plan);
    }
};
