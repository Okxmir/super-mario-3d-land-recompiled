#pragma once

#include <cstdint>

namespace pica {

struct Vec4;
struct ShaderSetup;
using CompiledVertex = void (*)(const Vec4 *, const Vec4 *, Vec4 *, Vec4 *);
using CompiledVertexPair = bool (*)(const Vec4 *, const Vec4 *, Vec4 *, Vec4 *);
struct LabPairProgramProfile {
    uint32_t ops[64]{};
    uint32_t branches = 0, equal_comparisons = 0, relative_loads = 0;
    uint32_t uniform_dots = 0, same_dot_vector = 0;
    uint32_t matrix_groups = 0;
    uint32_t machine_bytes = 0;
};
struct LabPairMatrixPlan {
    static constexpr unsigned capacity = 24;
    uint8_t rows[capacity][4]{};
    unsigned count = 0;
};
struct CompiledVertexUsage {
    uint16_t inputs = 0xffff;
    uint16_t written_outputs = 0;
    uint16_t read_before_write = 0xffff;
    uint64_t uniform_slots[2]{};
    uint64_t lab_generation = 0;
    const LabPairProgramProfile *lab_profile = nullptr;
    const LabPairMatrixPlan *lab_matrices = nullptr;
};

// Request on the draw thread before dispatching the vertices to workers.
CompiledVertex find_compiled_shader(const ShaderSetup &shader, uint32_t entry, uint64_t revision,
                                    CompiledVertexUsage *usage = nullptr,
                                    CompiledVertexPair *lab_pair = nullptr,
                                    CompiledVertexPair *lab_guarded_pair = nullptr);
int lab_verify_fused_matrix();

} // namespace pica
