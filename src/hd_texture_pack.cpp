#include "hd_texture_pack.h"
#include "log.h"
#include "platform.h"

#include <SDL3/SDL.h>

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
    const auto file = shape->second.find(hash);
    if (file == shape->second.end()) return {};
    const auto path = file->second.u8string();
    const auto *filename = reinterpret_cast<const char *>(path.c_str());
    using Surface = std::unique_ptr<SDL_Surface, decltype(&SDL_DestroySurface)>;
    Surface png(SDL_LoadPNG(filename), SDL_DestroySurface);
    Surface image(png ? SDL_ConvertSurface(png.get(), SDL_PIXELFORMAT_RGBA32) : nullptr, SDL_DestroySurface);
    if (!image || image->w < 1 || image->h < 1 || image->w > 4096 || image->h > 4096) {
        LOG("HD textures: could not load %s", filename);
        return {};
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
