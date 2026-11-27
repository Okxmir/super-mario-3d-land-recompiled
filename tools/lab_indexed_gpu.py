"""Use the same shaded geometry as indexed Vulkan primitives in the lab."""
from coherent_pica_fast import once


def indexed_header(source):
    return once(source, 'void triangle(const Vertex &v0, const Vertex &v1, const Vertex &v2);',
                '''void triangle(const Vertex &v0, const Vertex &v1, const Vertex &v2);
bool indexed_triangles(const Vertex *source, size_t count, const uint16_t *draw, uint32_t n);''')


def indexed_pica(source):
    source = once(source, '    void push_range(uint32_t count, VertexAt vertex_at) {', '''    void push_range(uint32_t count, VertexAt vertex_at, const Vertex *packed = nullptr,
                    size_t packed_count = 0, const uint16_t *indices = nullptr) {''')
    source = once(source, '''            // Complete lists can be emitted directly from the shaded vertices.
            for (; count - i >= 3; i += 3)''', '''            if (indices && complete == count && !deferring && draw_log_state != 2 &&
                !course_touch_scan.tracking && gpu::active() && gpu::indexed_triangles(packed, packed_count, indices, count))
                return;
            // Complete lists can be emitted directly from the shaded vertices.
            for (; count - i >= 3; i += 3)''')
    return once(source, 'assembler.push_range(n, [&](uint32_t i) -> const Vertex & { return shaded[draw_indices[i]]; });',
        '''assembler.push_range(n, [&](uint32_t i) -> const Vertex & { return shaded[draw_indices[i]]; },
                                 shaded.data(), shaded.size(), draw_indices.data());''')


def indexed_gpu(source):
    source = once(source, '    bool interpolated = false;\n};\n\nstruct TextureUpload',
        '    bool interpolated = false;\n    uint32_t index_first = 0, index_count = 0;\n};\n\nstruct TextureUpload')
    source = once(source, 'std::vector<GpuVertex> vertices;', 'std::vector<GpuVertex> vertices;\nstd::vector<uint16_t> lab_indices;')
    # Both versions use the same vertex packing and arithmetic, not a new shader.
    pack_start = source.index('        const float *a = v[i]->a;\n        GpuVertex g;', source.index('void triangle('))
    pack_end = source.index('        vertices.push_back(g);', pack_start) + len('        vertices.push_back(g);')
    pack = source[pack_start:pack_end].replace('v[i]->a', 'vertex.a').replace('ky[i]', 'ky').replace('vertices.push_back(g);', 'return g;')
    pack = '\n'.join(line[4:] for line in pack.splitlines())
    source = source[:pack_start] + '        vertices.push_back(lab_pack_vertex(*v[i], kx, ky[i], shift));' + source[pack_end:]
    source = once(source, 'void triangle(const Vertex &v0, const Vertex &v1, const Vertex &v2) {',
        'GpuVertex lab_pack_vertex(const Vertex &vertex, float kx, float ky, float shift) {\n' + pack + '\n}\n\n'
        'void triangle(const Vertex &v0, const Vertex &v1, const Vertex &v2) {')
    source = once(source, '// HUD size: shrinks the top screen', '#include "lab_indexed_gpu.inc"\n\n// HUD size: shrinks the top screen')
    source = once(source, '    size_t vbytes = vertices.size() * sizeof(GpuVertex);\n    total += vbytes;',
        '''    const size_t vbytes = vertices.size() * sizeof(GpuVertex);
    const size_t ibytes = lab_indices.size() * sizeof(uint16_t);
    const size_t geometry_bytes = vbytes + ((ibytes + 3) & ~size_t(3));
    total += geometry_bytes;''')
    source = once(source, '    if (vbytes) std::memcpy(map + at, vertices.data(), vbytes);',
        '''    if (vbytes) std::memcpy(map + at, vertices.data(), vbytes);
    if (ibytes) {
        std::memcpy(map + at + vbytes, lab_indices.data(), ibytes);
        std::memset(map + at + vbytes + ibytes, 0, geometry_bytes - vbytes - ibytes);
    }''')
    # SDL requires vertex and index buffer usages on separate buffers.
    # Keep the staging allocation shared, but upload to two explicit buffers.
    source = once(source, 'uint64_t upload_pending(SDL_GPUCommandBuffer *cmd, SDL_GPUBuffer **vbuf) {',
                  'uint64_t upload_pending(SDL_GPUCommandBuffer *cmd, SDL_GPUBuffer **vbuf, SDL_GPUBuffer **ibuf) {')
    source = once(source, '    SDL_EndGPUCopyPass(copy);\n    // SDL retains', '''    if (ibytes) {
        const uint32_t size = uint32_t(geometry_bytes - vbytes);
        SDL_GPUBufferCreateInfo info{SDL_GPU_BUFFERUSAGE_INDEX, size, 0};
        *ibuf = SDL_CreateGPUBuffer(dev, &info);
        if (!*ibuf) gpu_failure("index buffer allocation");
        const SDL_GPUTransferBufferLocation src{tb, uint32_t(vert_at + vbytes)};
        const SDL_GPUBufferRegion dst{*ibuf, 0, size};
        SDL_UploadToGPUBuffer(copy, &src, &dst, false);
    }
    SDL_EndGPUCopyPass(copy);
    // SDL retains''')
    source = once(source, '    if (is_cinema_frame(cur)) {', '    if (!cur.index_count && is_cinema_frame(cur)) {')
    source = once(source, '''        cur.hud_part = course_hud_part(cur, regs[TEX0_DIM], regs[BLEND_FUNC]);
        cur.hide_pause_title = hide_course_pause_title(cur);''', '''        cur.hud_part = cur.index_count ? 0 : course_hud_part(cur, regs[TEX0_DIM], regs[BLEND_FUNC]);
        cur.hide_pause_title = !cur.index_count && hide_course_pause_title(cur);''')
    source = once(source, '    const auto temporary_uploads = upload_pending(cmd, &vbuf);',
                  '    SDL_GPUBuffer *ibuf = nullptr;\n    const auto temporary_uploads = upload_pending(cmd, &vbuf, &ibuf);')
    source = once(source, '        SDL_DrawGPUPrimitives(pass, d.count, 1, d.first, 0);', '''        if (d.index_count) {
            SDL_GPUBufferBinding ib{ibuf, 0};
            SDL_BindGPUIndexBuffer(pass, &ib, SDL_GPU_INDEXELEMENTSIZE_16BIT);
            SDL_DrawGPUIndexedPrimitives(pass, d.index_count, 1, d.index_first, int32_t(d.first), 0);
        } else SDL_DrawGPUPrimitives(pass, d.count, 1, d.first, 0);''')
    return once(source, '    if (vbuf) SDL_ReleaseGPUBuffer(dev, vbuf);\n    batch.clear();\n    vertices.clear();',
        '    if (vbuf) SDL_ReleaseGPUBuffer(dev, vbuf);\n    if (ibuf) SDL_ReleaseGPUBuffer(dev, ibuf);\n    batch.clear();\n    vertices.clear();\n    lab_indices.clear();')
