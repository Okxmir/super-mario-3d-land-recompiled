"""Upload only changed ranges without replacing the GPU LUT or merging passes."""
from coherent_pica_fast import once


def lut_header(source):
    return once(source, 'extern uint32_t lighting_lut[24][256];',
                'extern uint32_t lighting_lut[24][256];\nextern uint64_t lighting_row_version[24];')


def lut_pica(source):
    source = once(source, 'uint32_t lighting_lut[24][256];',
                  'uint32_t lighting_lut[24][256];\nuint64_t lighting_row_version[24]{};')
    return once(source, 'if (entry != value) entry = value, ++lighting_lut_version;',
                'if (entry != value) entry = value, ++lighting_lut_version, ++lighting_row_version[table];')


def lut_gpu(source):
    source = once(source, 'std::vector<float> lut_pixels(256 * 25 * 2);', '''std::vector<float> lut_pixels(256 * 25 * 2);
std::array<uint64_t, 24> decoded_lut_versions{};
bool lut_initialized = false;
unsigned lut_first = 25, lut_last = 0;
constexpr size_t lut_row_bytes = 512 * sizeof(float);
size_t lut_bytes() { return size_t(lut_last - lut_first) * lut_row_bytes; }
void mark_lut(unsigned row) {
    lut_first = std::min(lut_first, row);
    lut_last = std::max(lut_last, row + 1);
}''')
    source = once(source, '''    for (int t = 0; t < 24; t++)
        for (int i = 0; i < 256; i++) {''', '''    static const bool full = std::getenv("SM3DL_LAB_FULL_LUT") != nullptr;
    for (int t = 0; t < 24; t++) {
        if (!full && lut_initialized && decoded_lut_versions[t] == lighting_row_version[t]) continue;
        decoded_lut_versions[t] = lighting_row_version[t];
        mark_lut(unsigned(t));
        for (int i = 0; i < 256; i++) {''')
    source = once(source, '''        }
    for (int i = 0; i < 128; i++) {
        uint32_t e = fog_lut[i];
        lut_pixels[(24 * 256 + i) * 2] = float((e >> 13) & 0x7FF) / 2047.0f;
        lut_pixels[(24 * 256 + i) * 2 + 1] = float(int32_t(e << 19) >> 19) / 2047.0f;
    }
    lut_version_done = lighting_lut_version;
    std::memcpy(fog_done, fog_lut, sizeof fog_done);
    lut_upload = true;''', '''        }
    }
    if (full || !lut_initialized || std::memcmp(fog_done, fog_lut, sizeof fog_done)) {
        mark_lut(24);
        for (int i = 0; i < 128; i++) {
            uint32_t e = fog_lut[i];
            lut_pixels[(24 * 256 + i) * 2] = float((e >> 13) & 0x7FF) / 2047.0f;
            lut_pixels[(24 * 256 + i) * 2 + 1] = float(int32_t(e << 19) >> 19) / 2047.0f;
        }
    }
    lut_initialized = true;
    lut_version_done = lighting_lut_version;
    std::memcpy(fog_done, fog_lut, sizeof fog_done);
    lut_upload = lut_first < lut_last;''')
    source = once(source, '    if (lut_upload) total += lut_pixels.size() * sizeof(float);',
                  '    if (lut_upload) total = ((total + 7) & ~size_t(7)) + lut_bytes();')
    source = once(source, '''    if (lut_upload) {
        std::memcpy(map + at, lut_pixels.data(), lut_pixels.size() * sizeof(float));
        at += lut_pixels.size() * sizeof(float);
    }''', '''    if (lut_upload) {
        lut_at = at = (at + 7) & ~size_t(7);
        std::memcpy(map + at, lut_pixels.data() + lut_first * 512, lut_bytes());
        at += lut_bytes();
    }''')
    source = once(source, '''        SDL_GPUTextureTransferInfo src{tb, uint32_t(lut_at), 256, 25};
        SDL_GPUTextureRegion dst{};
        dst.texture = lut_tex, dst.w = 256, dst.h = 25, dst.d = 1;''', '''        const uint32_t height = lut_last - lut_first;
        SDL_GPUTextureTransferInfo src{tb, uint32_t(lut_at), 256, height};
        SDL_GPUTextureRegion dst{};
        dst.texture = lut_tex, dst.y = lut_first, dst.w = 256, dst.h = height, dst.d = 1;
        static const bool trace = std::getenv("SM3DL_LAB_LUT_TRACE") != nullptr;
        if (trace) {
            static uint64_t bytes = 0, uploads = 0;
            bytes += lut_bytes();
            if (++uploads % 4096 == 0)
                LOG("LUT transfer: %llu bytes for %llu uploads (full: %llu bytes)",
                    (unsigned long long)bytes, (unsigned long long)uploads,
                    (unsigned long long)(uploads * 25 * lut_row_bytes));
        }''')
    return once(source, '    lut_upload = false;\n', '    lut_upload = false;\n    lut_first = 25; lut_last = 0;\n')
