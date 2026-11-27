#pragma once

#include <cstddef>
#include <cstdint>
#include <optional>
#include <vector>

namespace sm3dl {

struct PackTexture {
    uint32_t width = 0, height = 0;
    std::vector<uint8_t> rgba;
};

uint64_t texture_hash(const char *data, std::size_t size);
bool has_hd_texture_pack(int quality);
const char *hd_quality_name(int quality);
PackTexture load_pack_texture(const uint8_t *data, std::size_t size, uint32_t width,
                              uint32_t height, uint32_t format, int quality,
                              std::optional<uint64_t> fingerprint = std::nullopt);

} // namespace sm3dl

namespace pica::gpu {
void set_hd_textures(int quality);
}
