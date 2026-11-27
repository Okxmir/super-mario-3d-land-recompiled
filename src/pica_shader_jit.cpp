#include "pica_shader_jit.h"

#include "hd_texture_pack.h"
#include "pica_shader_decode.h"
#include "pica_shader_flow.h"

#include <algorithm>
#include <array>
#include <compare>
#include <cstdlib>
#include <cstring>
#include <deque>
#include <list>
#include <map>
#include <memory>
#include <unordered_map>
#include <utility>
#include <vector>

#ifdef _WIN32
#include <windows.h>
#endif
#ifdef _MSC_VER
#include <intrin.h>
#endif

#define XBYAK_NO_OP_NAMES
#include <xbyak/xbyak.h>

namespace pica {
namespace {

// Uniform decisions are resolved once per draw state. The compiler emits supported
// vertex-dependent branches and falls back to the interpreter for other shaders.
// Generated functions use only caller-saved registers on both x86-64 ABIs.
class VertexEmitter final : public Xbyak::CodeGenerator {
public:
    VertexEmitter() : CodeGenerator(4096, Xbyak::AutoGrow) {}
    CompiledVertexUsage usage{0, 0, 0};

    bool compile(const ShaderSetup &shader, uint32_t entry, bool graph = false) {
        if (graph) {
            if (!emit_graph(shader, entry)) return false;
            usage.read_before_write = 0xffff;
        } else if (!emit_specialized(shader, entry)) {
            return false;
        }
        readyRE();
#ifdef _WIN32
        return FlushInstructionCache(GetCurrentProcess(), getCode(), getSize()) != 0;
#else
        return true;
#endif
    }

private:
#ifdef _WIN32
    const Xbyak::Reg64 &uniforms = rcx, &inputs = rdx, &outputs = r8, &temporaries = r9;
#else
    const Xbyak::Reg64 &uniforms = rdi, &inputs = rsi, &outputs = rdx, &temporaries = rcx;
#endif

    bool emit_specialized(const ShaderSetup &shader, uint32_t entry) {
        auto emit = [&](uint32_t word, int32_t loop) {
            if (!instructions_left) return false;
            --instructions_left;
            loop_address = loop;
            const auto decoded = decode_arithmetic(word);
            return arithmetic(decoded, shader.swizzle[decoded.descriptor]);
        };
        auto branch = [&](uint32_t word, uint32_t start, uint32_t alternate, uint32_t end, int32_t loop) {
            // Branches can skip a write, so do not elide output initialization.
            usage.read_before_write = 0xffff;
            loop_address = loop;
            return conditional(shader, word, start, alternate, end);
        };
        if (!specialize_vertex_program(shader, entry, emit, branch)) return false;
        ret();
        return true;
    }

    static_assert(sizeof(Vec4) == 16);
    std::array<bool, 16> initialized{};
    std::array<bool, 2> moved_address{};
    int32_t loop_address = 0;
    bool compared = false;
    unsigned instructions_left = 4096;

    void splat_constant(const Xbyak::Xmm &dst, uint32_t bits) {
        mov(eax, bits);
        movd(dst, eax);
        shufps(dst, dst, 0);
    }

    void operand(const Xbyak::Xmm &dst, unsigned reg, unsigned relative, uint32_t selector) {
        if (reg < 16) {
            usage.inputs |= uint16_t(1u << reg);
            movups(dst, ptr[inputs + reg * sizeof(Vec4)]);
        } else if (reg < 32) {
            if (initialized[reg - 16]) movups(dst, ptr[temporaries + (reg - 16) * sizeof(Vec4)]);
            else xorps(dst, dst);
        } else {
            const unsigned offset = reg - 32;
            if (relative == 1 || relative == 2) {
                if (moved_address[relative - 1]) {
                    Xbyak::Label out_of_range, loaded;
                    lea(eax, ptr[(relative == 1 ? r10 : r11) + offset]);
                    cmp(eax, 96);
                    jae(out_of_range);
                    shl(eax, 4);
                    movups(dst, ptr[uniforms + rax]);
                    jmp(loaded);
                    L(out_of_range);
                    splat_constant(dst, 0x3f800000);
                    L(loaded);
                } else {
                    movups(dst, ptr[uniforms + offset * sizeof(Vec4)]);
                }
            } else {
                const unsigned index = offset + (relative == 3 ? loop_address : 0);
                if (index < 96) movups(dst, ptr[uniforms + index * sizeof(Vec4)]);
                else splat_constant(dst, 0x3f800000);
            }
        }
        const uint32_t order = (selector >> 1) & 255;
        if (order != 0x1b) {
            const uint32_t lanes = ((order & 3) << 6) | ((order & 12) << 2) |
                                   ((order & 48) >> 2) | ((order & 192) >> 6);
            shufps(dst, dst, lanes);
        }
        if (selector & 1) {
            pcmpeqd(xmm5, xmm5);
            pslld(xmm5, 31);
            xorps(dst, xmm5);
        }
    }

    void multiply() {
        // Match the interpreter's 0 * infinity rule without discarding NaN inputs.
        movaps(xmm2, xmm0);
        cmpordps(xmm2, xmm1);
        mulps(xmm0, xmm1);
        movaps(xmm3, xmm0);
        cmpunordps(xmm3, xmm0);
        andps(xmm2, xmm3);
        andnps(xmm2, xmm0);
        movaps(xmm0, xmm2);
    }

    void dot(unsigned op) {
        multiply();
        movaps(xmm2, xmm0);
        shufps(xmm2, xmm2, 0x55);
        addss(xmm2, xmm0);
        movaps(xmm3, xmm0);
        shufps(xmm3, xmm3, 0xaa);
        addss(xmm2, xmm3);
        if (op != 0x01) {
            const auto &w = op == 0x02 ? xmm0 : xmm1;
            shufps(w, w, 0xff);
            addss(xmm2, w);
        }
        shufps(xmm2, xmm2, 0);
        movaps(xmm0, xmm2);
    }

    void compare_lane(const Xbyak::Xmm &result, const Xbyak::Xmm &left, const Xbyak::Xmm &right, unsigned mode) {
        if (mode >= 6) {
            pcmpeqd(result, result);
        } else if (mode >= 4) {
            movaps(result, right);
            cmpss(result, left, mode - 3);
        } else {
            static constexpr unsigned predicates[] = {0, 4, 1, 2};
            movaps(result, left);
            cmpss(result, right, predicates[mode]);
        }
    }

    bool conditional(const ShaderSetup &shader, uint32_t word, uint32_t start, uint32_t alternate, uint32_t end) {
        prepare_branch_state();
        Xbyak::Label otherwise, done;
        jump_on_condition(word, otherwise, false);
        auto emit_range = [&](uint32_t begin, uint32_t limit) {
            for (uint32_t pc = begin; pc < limit; ++pc) {
                const auto ins = decode_arithmetic(shader.code[pc & 4095]);
                const uint32_t op = ins.word >> 26;
                if (!instructions_left) return false;
                --instructions_left;
                if (op == 0x21) continue;
                if (op >= 0x20 && op < 0x2e) return false;
                if (!arithmetic(ins, shader.swizzle[ins.descriptor])) return false;
            }
            return true;
        };
        if (!emit_range(start, alternate)) return false;
        if (alternate != end) jmp(done, T_NEAR);
        L(otherwise);
        if (!emit_range(alternate, end)) return false;
        L(done);
        return true;
    }

    void prepare_branch_state() {
        // Both paths may write temporaries and address registers. Give untouched registers
        // their interpreter defaults before the split so either path can reach the join.
        xorps(xmm5, xmm5);
        for (unsigned i = 0; i < initialized.size(); ++i) {
            if (!initialized[i]) movups(ptr[temporaries + i * sizeof(Vec4)], xmm5);
        }
        initialized.fill(true);
        if (!moved_address[0]) xor_(r10d, r10d);
        if (!moved_address[1]) xor_(r11d, r11d);
        moved_address.fill(true);
        if (!compared) xorps(xmm4, xmm4);
        compared = true;
    }

    void jump_on_condition(uint32_t word, Xbyak::Label &target, bool when_true) {
        movmskps(eax, xmm4);
        const uint32_t reference = ((word >> 25) & 1) | (((word >> 24) & 1) << 1);
        if (reference) xor_(eax, reference);
        const unsigned mode = (word >> 22) & 3;
        if (mode == 0) {
            and_(eax, 3);
            cmp(eax, 3);
            if (when_true) jne(target, T_NEAR);
            else je(target, T_NEAR);
        } else {
            test(eax, mode == 1 ? 3 : mode - 1);
            if (when_true) jz(target, T_NEAR);
            else jnz(target, T_NEAR);
        }
    }

    struct FlowFrame {
        uint32_t end, resume;
        auto operator<=>(const FlowFrame &) const = default;
    };

    struct FlowState {
        uint32_t pc;
        size_t depth = 0;
        std::array<FlowFrame, 16> frames{};
        auto operator<=>(const FlowState &) const = default;

        void resolve_returns() {
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

    // Compile control flow using the PICA return stack as part of the block key.
    // A branch may jump over an enclosing block's end, as the interpreter allows.
    bool emit_graph(const ShaderSetup &shader, uint32_t entry) {
        prepare_branch_state();
        struct Block {
            FlowState state;
            Xbyak::Label label;
            std::vector<size_t> successors;
        };
        std::map<FlowState, size_t> indices;
        std::deque<Block> blocks;
        auto enqueue = [&](FlowState state) {
            state.resolve_returns();
            auto [it, added] = indices.try_emplace(state, blocks.size());
            if (added) blocks.push_back({state, {}, {}});
            return it->second;
        };
        enqueue(FlowState{entry});
        for (size_t block_index = 0; block_index < blocks.size(); ++block_index) {
            auto &block = blocks[block_index];
            auto state = block.state;
            const auto branch_target = [&](FlowState target) -> Xbyak::Label & {
                const size_t next = enqueue(target);
                block.successors.push_back(next);
                return blocks[next].label;
            };
            L(block.label);
            for (;;) {
                if (!instructions_left) return false;
                --instructions_left;
                const uint32_t pc = state.pc++;
                const uint32_t word = shader.code[pc & 4095], op = word >> 26;
                const uint32_t count = word & 255, target = (word >> 10) & 4095;
                const bool uniform = (shader.b >> ((word >> 22) & 15)) & 1;
                if (op == 0x22) {
                    ret();
                    break;
                }
                if (op < 0x20 || op >= 0x2e) {
                    const auto ins = decode_arithmetic(word);
                    if (!arithmetic(ins, shader.swizzle[ins.descriptor])) return false;
                } else if (op >= 0x24 && op <= 0x26) {
                    if (op == 0x25) {
                        auto taken = state;
                        if (!taken.enter(target, target + count, state.pc)) return false;
                        jump_on_condition(word, branch_target(taken), true);
                    } else if (op == 0x24 || uniform) {
                        if (!state.enter(target, target + count, state.pc)) return false;
                    }
                } else if (op == 0x27 || op == 0x28) {
                    const uint32_t resume = target + count;
                    if (target < state.pc) return false;
                    if (op == 0x28) {
                        auto otherwise = state;
                        if (!otherwise.enter(target, resume, resume)) return false;
                        jump_on_condition(word, branch_target(otherwise), false);
                    }
                    const bool taken = op == 0x28 || uniform;
                    if (!state.enter(taken ? state.pc : target, taken ? target : resume, resume)) return false;
                } else if (op == 0x2c || op == 0x2d) {
                    if (target < state.pc) return false;
                    if (op == 0x2c) {
                        auto taken = state;
                        taken.pc = target;
                        jump_on_condition(word, branch_target(taken), true);
                    } else if (uniform != bool(count & 1)) {
                        state.pc = target;
                    }
                } else if (op != 0x21) {
                    return false;
                }
                state.resolve_returns();
                if (auto found = indices.find(state); found != indices.end()) {
                    block.successors.push_back(found->second);
                    jmp(blocks[found->second].label, T_NEAR);
                    break;
                }
            }
        }
        // Reject cycles so generated code cannot run indefinitely on a shader
        // where the interpreter would eventually stop at its instruction limit.
        std::vector<size_t> incoming(blocks.size());
        for (const auto &block : blocks)
            for (size_t next : block.successors) ++incoming[next];
        std::vector<size_t> ready;
        for (size_t i = 0; i < incoming.size(); ++i)
            if (!incoming[i]) ready.push_back(i);
        for (size_t i = 0; i < ready.size(); ++i)
            for (size_t next : blocks[ready[i]].successors)
                if (!--incoming[next]) ready.push_back(next);
        return ready.size() == blocks.size();
    }

    bool arithmetic(const ArithmeticInstruction &ins, uint32_t desc) {
        const uint32_t op = ins.word >> 26;
        const uint32_t mask = desc & 15;
        if (op == 0x2e || op == 0x2f) {
            operand(xmm0, ins.source[0], ins.address[0], desc >> 4);
            operand(xmm1, ins.source[1], ins.address[1], desc >> 13);
            compare_lane(xmm2, xmm0, xmm1, (ins.word >> 24) & 7);
            shufps(xmm0, xmm0, 0x55);
            shufps(xmm1, xmm1, 0x55);
            compare_lane(xmm3, xmm0, xmm1, (ins.word >> 21) & 7);
            unpcklps(xmm2, xmm3);
            movaps(xmm4, xmm2);
            compared = true;
            return true;
        }
        if (op == 0x07) return false; // LITP also updates the condition flags.
        if (!mask) return true;
        operand(xmm0, ins.source[0], ins.address[0], desc >> 4);
        switch (op) {
        case 0x0b: // FLR
            roundps(xmm0, xmm0, 1 | 8);
            break;
        case 0x0e: // RCP
        case 0x0f: // RSQ
            if (op == 0x0f) sqrtss(xmm0, xmm0);
            splat_constant(xmm1, 0x3f800000);
            divss(xmm1, xmm0);
            shufps(xmm1, xmm1, 0);
            movaps(xmm0, xmm1);
            break;
        case 0x12: // MOVA
            if (mask & 8) {
                cvttss2si(r10d, xmm0);
                moved_address[0] = true;
            }
            if (mask & 4) {
                shufps(xmm0, xmm0, 0x55);
                cvttss2si(r11d, xmm0);
                moved_address[1] = true;
            }
            return true;
        case 0x13: // MOV
            break;
        default:
            operand(xmm1, ins.source[1], ins.address[1], desc >> 13);
            switch (op) {
            case 0x00: addps(xmm0, xmm1); break;
            case 0x01:
            case 0x02:
            case 0x03:
            case 0x18: dot(op); break;
            case 0x04:
            case 0x19: // DST
                movaps(xmm5, xmm0);
                multiply();
                blendps(xmm0, xmm5, 4); // z comes from the first operand
                blendps(xmm0, xmm1, 8); // w comes from the second operand
                splat_constant(xmm5, 0x3f800000);
                blendps(xmm0, xmm5, 1); // x is one
                break;
            case 0x08: multiply(); break;
            case 0x09:
            case 0x1a: // SGE
                cmpleps(xmm1, xmm0);
                splat_constant(xmm0, 0x3f800000);
                andps(xmm0, xmm1);
                break;
            case 0x0a:
            case 0x1b: // SLT
                cmpltps(xmm0, xmm1);
                splat_constant(xmm1, 0x3f800000);
                andps(xmm0, xmm1);
                break;
            case 0x0c: maxps(xmm0, xmm1); break;
            case 0x0d: minps(xmm0, xmm1); break;
            default:
                if (op < 0x30) return false;
                multiply();
                operand(xmm1, ins.source[2], ins.address[2], desc >> 22);
                addps(xmm0, xmm1);
                break;
            }
            break;
        }

        const bool output = ins.destination < 16;
        const unsigned index = ins.destination & 15;
        if (output) {
            const uint16_t bit = uint16_t(1u << index);
            if (!(usage.written_outputs & bit) && mask != 15) usage.read_before_write |= bit;
            usage.written_outputs |= bit;
        }
        const auto destination = ptr[(output ? outputs : temporaries) + index * sizeof(Vec4)];
        if (mask != 15) {
            if (output || initialized[index]) movups(xmm1, destination);
            else xorps(xmm1, xmm1);
            const uint32_t lanes = ((mask & 1) << 3) | ((mask & 2) << 1) |
                                   ((mask & 4) >> 1) | ((mask & 8) >> 3);
            blendps(xmm1, xmm0, lanes);
            movups(destination, xmm1);
        } else {
            movups(destination, xmm0);
        }
        if (!output) initialized[index] = true;
        return true;
    }
};

struct ShaderKey {
    uint32_t entry, booleans;
    std::array<uint32_t, 4> integers;
    bool operator==(const ShaderKey &) const = default;
};

struct ShaderKeyHash {
    size_t operator()(const ShaderKey &key) const {
        size_t hash = (size_t(key.entry) << 16) | key.booleans;
        for (auto integer : key.integers) hash = (hash ^ integer) * 0x9e3779b185ebca87ull;
        return hash;
    }
};

using VertexVariants = std::unordered_map<ShaderKey, std::unique_ptr<VertexEmitter>, ShaderKeyHash>;

struct VertexProgram {
    uint64_t code_hash = 0, swizzle_hash = 0;
    std::array<uint32_t, 4096> code;
    std::array<uint32_t, 128> swizzle;
    VertexVariants variants;
};

} // namespace

CompiledVertex find_compiled_shader(const ShaderSetup &shader, uint32_t entry, uint64_t revision,
                                    CompiledVertexUsage *usage) {
    if (usage) *usage = {};
    static const bool available = [] {
#ifdef _MSC_VER
        int cpu[4];
        __cpuid(cpu, 1);
        return (cpu[2] & (1 << 19)) != 0; // SSE4.1
#else
        return __builtin_cpu_supports("sse4.1") != 0;
#endif
    }();
    if (!available) return nullptr;

    // Uploading another PICA program is not a reason to discard the compiled
    // code for the previous one. The same small set can alternate within one
    // course frame. Match every code and swizzle word before reusing any code.
    static_assert(sizeof(VertexProgram::code) == sizeof(shader.code));
    static_assert(sizeof(VertexProgram::swizzle) == sizeof(shader.swizzle));
    static thread_local std::list<VertexProgram> programs;
    static thread_local uint64_t last_revision = 0;
    static const bool legacy_cache = std::getenv("SM3DL_LEGACY_VERTEX_CACHE") != nullptr;
    if (programs.empty() || revision != last_revision) {
        if (legacy_cache) programs.clear(); // local A/B diagnostics
        const uint64_t code_hash = sm3dl::texture_hash(reinterpret_cast<const char *>(shader.code), sizeof(shader.code));
        const uint64_t swizzle_hash = sm3dl::texture_hash(reinterpret_cast<const char *>(shader.swizzle), sizeof(shader.swizzle));
        auto found = std::find_if(programs.begin(), programs.end(), [&](const VertexProgram &p) {
            return p.code_hash == code_hash && p.swizzle_hash == swizzle_hash &&
                   std::memcmp(p.code.data(), shader.code, sizeof(shader.code)) == 0 &&
                   std::memcmp(p.swizzle.data(), shader.swizzle, sizeof(shader.swizzle)) == 0;
        });
        if (found != programs.end()) {
            programs.splice(programs.begin(), programs, found);
        } else {
            if (programs.size() == 16) programs.pop_back();
            auto &p = programs.emplace_front();
            p.code_hash = code_hash;
            p.swizzle_hash = swizzle_hash;
            std::memcpy(p.code.data(), shader.code, sizeof(shader.code));
            std::memcpy(p.swizzle.data(), shader.swizzle, sizeof(shader.swizzle));
        }
        last_revision = revision;
    }
    auto &cache = programs.front().variants;
    ShaderKey key{entry, shader.b, {}};
    std::memcpy(key.integers.data(), shader.i, sizeof(shader.i));
    if (auto it = cache.find(key); it != cache.end()) {
        if (usage && it->second) *usage = it->second->usage;
        return it->second ? it->second->getCode<CompiledVertex>() : nullptr;
    }
    if (cache.size() >= 128) cache.clear();
    auto &compiled = cache[key];
    try {
        auto code = std::make_unique<VertexEmitter>();
        if (code->compile(shader, entry)) {
            compiled = std::move(code);
        } else {
            code = std::make_unique<VertexEmitter>();
            if (code->compile(shader, entry, true)) compiled = std::move(code);
        }
    } catch (const Xbyak::Error &) {
        // The interpreter also works when executable allocations are unavailable.
    }
    if (usage && compiled) *usage = compiled->usage;
    return compiled ? compiled->getCode<CompiledVertex>() : nullptr;
}

} // namespace pica
