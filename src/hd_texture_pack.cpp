#include "hd_texture_pack.h"
#include "log.h"
#include "platform.h"

#include <SDL3/SDL.h>

#include <algorithm>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <map>
#include <memory>
#include <tuple>

namespace sm3dl {
namespace {

using TextureShape = std::tuple<uint32_t, uint32_t, uint32_t>;
using TextureFiles = std::map<TextureShape, std::map<uint64_t, std::filesystem::path>>;

// The European game has different hashes for a few UI atlases whose sprites
// and cell positions match these editions in the 1080p pack. Keep exact
// replacements preferred and let unmatched layouts use the game's own pixels.
constexpr std::pair<uint64_t, uint64_t> ui_aliases[] = {
    {0x057677e58805aaf7, 0xb82fd3989f38128c},
    {0x25d14c9e2097a92f, 0xac881f297f7f642a},
    {0x2dab0f04fbd84c16, 0x63748a9d8c45099e},
    {0x3ad3b2990a7d6e27, 0x6e141d76640eb6e9},
    {0x41503f6038f04979, 0xd20e1b26a9cdd0ff},
    {0x4267e0c8e8e65349, 0xa260c225dc68f7d1},
    {0x52586d01a1e81ec9, 0x1a6afcbf8f756704},
    {0x6bb4d72e77036e75, 0x63748a9d8c45099e},
    {0x718529eed1c0f82b, 0xcb61832908621ecf},
    {0x7289df8df2d7afe9, 0xdaddb9eb0edd35be},
    {0x76c88981fa6fe818, 0xd20e1b26a9cdd0ff},
    {0x7d2cae81a9ab263c, 0xb0e5299b13441dfc},
    {0x96a54bbb67b0a290, 0xb0e5299b13441dfc},
    {0x973380ad23fe1738, 0xfefecca870c405ee},
    {0xaa61216af8cb5508, 0xe0e0cc0246d11686},
    {0xad59732c2a07024c, 0xac881f297f7f642a},
    {0xb069adc6e48f9855, 0x6e141d76640eb6e9},
    {0xc08b471fcdf59fb7, 0xe0e0cc0246d11686},
    {0xdcc7047f06224c25, 0x1a6afcbf8f756704},
    {0xfbd7a467bd47a0d7, 0xdaddb9eb0edd35be},
};

const TextureFiles &pack_files() {
    static const TextureFiles files = [] {
        TextureFiles index;
        const auto folder = platform::data_dir() / "hd-textures" / "sm3dl-1080p-1.2.0b";
        std::error_code error;
        for (auto file = std::filesystem::directory_iterator(folder, error);
             !error && file != std::filesystem::directory_iterator(); file.increment(error)) {
            if (!file->is_regular_file(error)) continue;
            const auto name = file->path().filename().u8string();
            unsigned width, height, format;
            unsigned long long hash;
            int end = 0;
            if (std::sscanf(reinterpret_cast<const char *>(name.c_str()), "tex1_%ux%u_%16llx_%u_mip0.png%n",
                            &width, &height, &hash, &format, &end) == 4 && std::size_t(end) == name.size())
                index[{width, height, format}].emplace(hash, file->path());
        }
        return index;
    }();
    return files;
}

} // namespace

bool has_hd_texture_pack() { return !pack_files().empty(); }

PackTexture load_pack_texture(const uint8_t *data, std::size_t size, uint32_t width,
                              uint32_t height, uint32_t format) {
    const auto &index = pack_files();
    const auto shape = index.find({width, height, format});
    if (shape == index.end()) return {};
    const uint64_t hash = texture_hash(reinterpret_cast<const char *>(data), size);
    auto file = shape->second.find(hash);
    if (file == shape->second.end()) {
        for (const auto &[original, replacement] : ui_aliases)
            if (hash == original) {
                file = shape->second.find(replacement);
                break;
            }
    }
    if (file == shape->second.end()) return {};
    const auto path = file->second.u8string();
    const auto *filename = reinterpret_cast<const char *>(path.c_str());
    using Surface = std::unique_ptr<SDL_Surface, decltype(&SDL_DestroySurface)>;
    Surface png(SDL_LoadPNG(filename), SDL_DestroySurface);
    Surface image(png ? SDL_ConvertSurface(png.get(), SDL_PIXELFORMAT_RGBA32) : nullptr, SDL_DestroySurface);
    if (!image || image->w < 1 || image->h < 1 || image->w > 8192 || image->h > 8192) {
        LOG("HD textures: could not load %s", filename);
        return {};
    }
    // Keep both axes in proportion when an atlas exceeds the renderer's size limit.
    if (image->w > 4096 || image->h > 4096) {
        image.reset(SDL_ScaleSurface(image.get(), image->w / 2, image->h / 2, SDL_SCALEMODE_LINEAR));
        if (!image) {
            LOG("HD textures: could not resize %s: %s", filename, SDL_GetError());
            return {};
        }
    }
    if (std::getenv("SM3DL_TRACE_HD_TEXTURES"))
        LOG("HD textures: %016llx %ux%u replaced with %dx%d", (unsigned long long)hash,
            width, height, image->w, image->h);
    PackTexture texture{uint32_t(image->w), uint32_t(image->h), {}};
    const auto row = std::size_t(image->w) * 4;
    texture.rgba.resize(row * image->h);
    // This pack's PNG rows already follow the guest texture's row order.
    for (int y = 0; y < image->h; ++y)
        std::memcpy(texture.rgba.data() + row * y,
                    static_cast<const uint8_t *>(image->pixels) + std::size_t(y) * image->pitch,
                    row);
    return texture;
}

} // namespace sm3dl
