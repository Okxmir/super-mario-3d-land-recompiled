#pragma once

#include <cstdint>

namespace pica {

struct Vec4;
struct ShaderSetup;
using CompiledVertex = void (*)(const Vec4 *, const Vec4 *, Vec4 *, Vec4 *);
struct CompiledVertexUsage {
    uint16_t inputs = 0xffff;
    uint16_t written_outputs = 0;
    uint16_t read_before_write = 0xffff;
};

// Request on the draw thread before dispatching the vertices to workers.
CompiledVertex find_compiled_shader(const ShaderSetup &shader, uint32_t entry, uint64_t revision,
                                    CompiledVertexUsage *usage = nullptr);

} // namespace pica
