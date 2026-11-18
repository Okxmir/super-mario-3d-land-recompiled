#include "hd_texture_pack.h"
#include "log.h"
#include "platform.h"
#include "video/internal.h"

#include <SDL3/SDL.h>

#include <algorithm>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <map>
#include <memory>
#include <string_view>
#include <tuple>

namespace sm3dl {
namespace {

using TextureShape = std::tuple<uint32_t, uint32_t, uint32_t>;
using TextureFiles = std::map<TextureShape, std::map<uint64_t, std::filesystem::path>>;
using Surface = std::unique_ptr<SDL_Surface, decltype(&SDL_DestroySurface)>;

// The European game has different hashes for a few UI atlases whose sprites
// and cell positions match these editions in the 1080p pack. Keep exact
// replacements preferred and let unmatched layouts use the game's own pixels.
constexpr std::pair<uint64_t, uint64_t> ui_aliases[] = {
    {0x057677e58805aaf7, 0xb82fd3989f38128c},
    {0x0b05a639741c97fc, 0x9b9443ef678860f1},
    {0x25d14c9e2097a92f, 0xac881f297f7f642a},
    {0x2dab0f04fbd84c16, 0x63748a9d8c45099e},
    {0x3ad3b2990a7d6e27, 0x6e141d76640eb6e9},
    {0x41503f6038f04979, 0xd20e1b26a9cdd0ff},
    {0x4267e0c8e8e65349, 0xa260c225dc68f7d1},
    {0x4e8296f976ee2324, 0xeb1f90d731a9df27},
    {0x52586d01a1e81ec9, 0x1a6afcbf8f756704},
    {0x6bb4d72e77036e75, 0x63748a9d8c45099e},
    {0x718529eed1c0f82b, 0xcb61832908621ecf},
    {0x7289df8df2d7afe9, 0xdaddb9eb0edd35be},
    {0x737035f67b3651ee, 0x4120550645efc43f},
    {0x76c88981fa6fe818, 0xd20e1b26a9cdd0ff},
    {0x7d2cae81a9ab263c, 0xb0e5299b13441dfc},
    {0x96a54bbb67b0a290, 0xb0e5299b13441dfc},
    {0x973380ad23fe1738, 0xfefecca870c405ee},
    {0xaa61216af8cb5508, 0xe0e0cc0246d11686},
    {0xad59732c2a07024c, 0xac881f297f7f642a},
    {0xb069adc6e48f9855, 0x6e141d76640eb6e9},
    {0xc08b471fcdf59fb7, 0xe0e0cc0246d11686},
    {0xd306e452a7a4bff3, 0x76f30968b9d51da8},
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

Surface load_rgba_png(const std::filesystem::path &path) {
    const auto name = path.u8string();
    Surface png(SDL_LoadPNG(reinterpret_cast<const char *>(name.c_str())), SDL_DestroySurface);
    return Surface(png ? SDL_ConvertSurface(png.get(), SDL_PIXELFORMAT_RGBA32) : nullptr, SDL_DestroySurface);
}

PackTexture copy_pixels(const SDL_Surface &image) {
    PackTexture texture{uint32_t(image.w), uint32_t(image.h), {}};
    const auto row = std::size_t(image.w) * 4;
    texture.rgba.resize(row * image.h);
    // The pack's PNG rows follow the guest texture's row order.
    for (int y = 0; y < image.h; ++y)
        std::memcpy(texture.rgba.data() + row * y,
                    static_cast<const uint8_t *>(image.pixels) + std::size_t(y) * image.pitch, row);
    return texture;
}

struct FontGrid {
    uint64_t hash;
    int width, height, cell_width, cell_height;
    std::u32string_view glyphs;
};

// French UI sheets put the same glyphs in different cells. Match the exact
// guest sheet before putting HD glyphs back into its original layout.
constexpr FontGrid french_fonts[] = {
    {0x0f25f25157bf97d5, 256, 32, 19, 32, U" !'+,-./01234"},
    {0x160ffc43e3a6975a, 256, 32, 19, 32, U"56789:?ABCDEG"},
    {0x411cd9f79bab4e66, 256, 32, 19, 32, U"opqrstuvxyz\u00c0\u00e0"},
    {0xc9c0bfb200add759, 256, 32, 19, 32, U"\u00e2\u00e7\u00e8\u00e9\u00ea\u00ee\u0153"},
    {0xcfd3c136b24b3ab2, 256, 32, 19, 32, U"KLMNOPQRSTUV_"},
    {0xf4f15e0b1c22bb58, 256, 32, 19, 32, U"abcdefghijlmn"},
    {0x7d5345710d92845b, 256, 64, 17, 18,
     U"Z_abcdefghijklm" U"nopqrstuvwxyz\u00a9\u00c9" U"\u00e0\u00e2\u00e8\u00e9\u00ea\u00f4\u00fc"},
    {0xffccaa0158c553b8, 256, 64, 17, 18,
     U" !',-./01234567" U"89:?@ABCDEFGHIJ" U"KLMNOPQRSTUVWXY"},
};

constexpr FontGrid pack_fonts[] = {
    {0x284c0fe7f456e652, 64, 64, 19, 20, U" !'+,-./0"},
    {0xce0dbf4532175f8a, 64, 64, 19, 20, U"123456789"},
    {0x3a0d70a4e38fc2b7, 64, 64, 19, 20, U":?ABCDEFG"},
    {0x0912c6485528d675, 64, 64, 19, 20, U"FGHIKLMNO"},
    {0x9b9443ef678860f1, 64, 64, 19, 20, U"IJKMNOPQR"},
    {0x4fed2f17f1bc7338, 64, 64, 19, 20, U"RSTUWY_ab"},
    {0xdaddb9eb0edd35be, 64, 64, 19, 20, U"STUWY_abc"},
    {0x4120550645efc43f, 64, 64, 19, 20, U"defghijkl"},
    {0xd20e1b26a9cdd0ff, 64, 64, 19, 20, U"mnoprstuv"},
    {0x1901ee4eb7fe240b, 64, 64, 19, 20, U"nopqrstuv"},
    {0x57fc7a527bd0530d, 64, 64, 19, 20, U"vwxy"},
    {0x21abcf916bcae8a5, 64, 128, 17, 18, U"WXYZ_abcdefghijklmnop"},
    {0x0e2ce0da9f407ae6, 64, 128, 17, 18, U"BCDEFGHIJKLMNOPQRSTUV"},
    {0xc8ea95d872d389ef, 64, 128, 17, 18, U"rstuvwyz\u00a9\u00e0\u00e8\u00e9\u00fc"},
};

SDL_Rect glyph_bounds(const SDL_Surface &surface, const FontGrid &font, std::size_t slot) {
    const int scale = surface.w / font.width;
    const auto columns = std::size_t(font.width / font.cell_width);
    const int x = int(slot % columns) * font.cell_width * scale;
    const int y = int(slot / columns) * font.cell_height * scale;
    const int end_x = x + font.cell_width * scale, end_y = y + font.cell_height * scale;
    int left = end_x, top = end_y, right = x, bottom = y;
    for (int row = y; row < end_y; ++row) {
        const auto *pixels = static_cast<const uint8_t *>(surface.pixels) + std::size_t(row) * surface.pitch;
        for (int col = x; col < end_x; ++col) {
            if (!pixels[col * 4 + 3]) continue;
            left = std::min(left, col), right = std::max(right, col + 1);
            top = std::min(top, row), bottom = std::max(bottom, row + 1);
        }
    }
    return {left, top, right - left, bottom - top};
}

PackTexture repack_french_font(const pica::Texture &guest, uint64_t hash) {
    if (guest.width != 256 || guest.format != 11) return {};
    const auto *layout = std::find_if(std::begin(french_fonts), std::end(french_fonts),
        [&](const FontGrid &font) { return font.hash == hash && font.height == int(guest.height); });
    if (layout == std::end(french_fonts)) return {};

    constexpr int scale = 4;
    Surface original(SDL_CreateSurface(layout->width, layout->height, SDL_PIXELFORMAT_RGBA32),
                     SDL_DestroySurface);
    if (!original) return {};
    pica::decode_texture(guest, static_cast<uint8_t *>(original->pixels));
    SDL_SetSurfaceBlendMode(original.get(), SDL_BLENDMODE_NONE);
    Surface high(SDL_ScaleSurface(original.get(), layout->width * scale, layout->height * scale,
                                  SDL_SCALEMODE_LINEAR), SDL_DestroySurface);
    if (!high) return {};
    std::map<uint64_t, Surface> pages;
    unsigned replaced = 0;
    for (std::size_t i = 0; i < layout->glyphs.size(); ++i) {
        const auto letter = layout->glyphs[i];
        const SDL_Rect box = glyph_bounds(*original, *layout, i);
        if (box.w <= 0 || box.h <= 0) continue;
        const SDL_Rect dest{box.x * scale, box.y * scale, box.w * scale, box.h * scale};
        for (const auto &font : pack_fonts) {
            const auto slot = font.glyphs.find(letter);
            if (slot == std::u32string_view::npos) continue;
            const auto shape = pack_files().find({font.width, font.height, 11});
            if (shape == pack_files().end()) continue;
            const auto file = shape->second.find(font.hash);
            if (file == shape->second.end()) continue;
            auto page = pages.find(font.hash);
            if (page == pages.end()) page = pages.emplace(font.hash, load_rgba_png(file->second)).first;
            auto *source = page->second.get();
            if (!source || source->w % font.width || source->h != font.height * (source->w / font.width))
                continue;
            const SDL_Rect src = glyph_bounds(*source, font, slot);
            if (src.w <= 0 || src.h <= 0) continue;
            SDL_SetSurfaceBlendMode(source, SDL_BLENDMODE_NONE);
            if (SDL_BlitSurfaceScaled(source, &src, high.get(), &dest, SDL_SCALEMODE_LINEAR)) {
                ++replaced;
                break;
            }
        }
    }
    if (!replaced) return {};
    if (std::getenv("SM3DL_TRACE_HD_TEXTURES"))
        LOG("HD textures: %016llx French font repacked at %dx%d (%u HD glyphs)",
            (unsigned long long)hash, high->w, high->h, replaced);
    return copy_pixels(*high);
}

} // namespace

bool has_hd_texture_pack() { return !pack_files().empty(); }

PackTexture load_pack_texture(const uint8_t *data, std::size_t size, uint32_t width,
                              uint32_t height, uint32_t format) {
    const auto &index = pack_files();
    const auto shape = index.find({width, height, format});
    const bool localized_font = width == 256 && (height == 32 || height == 64) && format == 11;
    if (index.empty() || (shape == index.end() && !localized_font)) return {};
    const uint64_t hash = texture_hash(reinterpret_cast<const char *>(data), size);
    auto localized_replacement = [&] {
        if (!localized_font) return PackTexture{};
        pica::Texture guest;
        guest.data = data;
        guest.bytes = uint32_t(size);
        guest.width = width;
        guest.height = height;
        guest.format = format;
        return repack_french_font(guest, hash);
    };
    if (shape == index.end()) return localized_replacement();
    auto file = shape->second.find(hash);
    if (file == shape->second.end()) {
        for (const auto &[original, replacement] : ui_aliases)
            if (hash == original) {
                file = shape->second.find(replacement);
                break;
            }
    }
    if (file == shape->second.end()) return localized_replacement();
    const auto path = file->second.u8string();
    const auto *filename = reinterpret_cast<const char *>(path.c_str());
    Surface image = load_rgba_png(file->second);
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
    return copy_pixels(*image);
}

} // namespace sm3dl
