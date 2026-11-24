#include "dump.h"
#include "display_options.h"
#include "frontend/frontend.h"
#include "game_code.h"
#include "kernel/kernel.h"
#include "loader.h"
#include "log.h"
#include "memory.h"
#include "platform.h"
#include "save_storage.h"
#include "video/internal.h"

#include <SDL3/SDL.h>
#ifdef _WIN32
#include <windows.h>
#include <bcrypt.h>
#else
#include <openssl/sha.h>
#endif

#include <algorithm>
#include <array>
#include <atomic>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <filesystem>
#include <string>

extern "C" const RecompEntry original_recomp_functions[];
extern "C" const size_t original_recomp_function_count;

namespace sm3dl {
namespace { int startup_fps = 60; }
int boot_fps() { return startup_fps; }
void set_boot_fps(int fps) { startup_fps = fps == 30 ? 30 : 60; }
}

namespace game_code {
const RecompEntry *functions() { return sm3dl::boot_fps() == 30 ? original_recomp_functions : recomp_functions; }
size_t function_count() { return sm3dl::boot_fps() == 30 ? original_recomp_function_count : recomp_function_count; }
}

namespace hle {
int verify_apt_wrap();
}

namespace {
constexpr uint64_t europe_title = 0x0004000000053F00;
constexpr const char *cartridge_required =
    "Select a decrypted European Super Mario 3D Land ROM (CTR-P-AREP, original revision).\n"
    "Supported extensions: .3ds, .cci, .cxi.";

std::string utf8_path(const std::filesystem::path &path) {
    const auto utf8 = path.u8string();
    return std::string(utf8.begin(), utf8.end());
}

std::filesystem::path pick_cartridge() {
    if (!SDL_InitSubSystem(SDL_INIT_VIDEO)) fatal("%s\n\n%s", cartridge_required, SDL_GetError());

    static SDL_DialogFileFilter filters[] = {
        {"European ROM (*.3ds, *.cci, *.cxi)", "3ds;cci;cxi"}
    };
    const SDL_PropertiesID props = SDL_CreateProperties();
    if (!props ||
        !SDL_SetPointerProperty(props, SDL_PROP_FILE_DIALOG_FILTERS_POINTER, filters) ||
        !SDL_SetNumberProperty(props, SDL_PROP_FILE_DIALOG_NFILTERS_NUMBER, 1) ||
        !SDL_SetStringProperty(props, SDL_PROP_FILE_DIALOG_TITLE_STRING,
                               "Select a decrypted European ROM (.3ds, .cci, .cxi)")) {
        fatal("Could not configure the ROM selector: %s", SDL_GetError());
    }

    std::filesystem::path image;
    for (;;) {
        struct Selection {
            std::atomic<bool> done{false};
            std::string path, error;
            bool failed = false;
        } selection;
        SDL_ShowFileDialogWithProperties(SDL_FILEDIALOG_OPENFILE, [](void *userdata, const char *const *files, int) {
            auto &result = *static_cast<Selection *>(userdata);
            if (!files) {
                result.failed = true;
                result.error = SDL_GetError();
            } else if (*files) {
                result.path = *files;
            }
            result.done.store(true, std::memory_order_release);
        }, &selection, props);
        while (!selection.done.load(std::memory_order_acquire)) {
            SDL_PumpEvents();
            SDL_Delay(16);
        }
        if (selection.failed) fatal("%s\n\nFile picker: %s", cartridge_required, selection.error.c_str());
        if (selection.path.empty()) break;

        image = std::filesystem::u8path(selection.path);
        const auto extension = utf8_path(image.extension());
        if ((SDL_strcasecmp(extension.c_str(), ".3ds") == 0 ||
             SDL_strcasecmp(extension.c_str(), ".cci") == 0 ||
             SDL_strcasecmp(extension.c_str(), ".cxi") == 0) &&
            peek_program_id(image) == europe_title)
            break;
        image.clear();
        SDL_ShowSimpleMessageBox(SDL_MESSAGEBOX_ERROR, "Unsupported ROM", cartridge_required, nullptr);
    }
    SDL_DestroyProperties(props);
    SDL_QuitSubSystem(SDL_INIT_VIDEO);
    return image;
}

#ifdef _WIN32
LONG WINAPI report_access_violation(EXCEPTION_POINTERS *info) {
    const auto &record = *info->ExceptionRecord;
    if (record.ExceptionCode != EXCEPTION_ACCESS_VIOLATION || record.NumberParameters < 2)
        return EXCEPTION_CONTINUE_SEARCH;

    HMODULE module = nullptr;
    char path[MAX_PATH + 1]{};
    const auto instruction = reinterpret_cast<uintptr_t>(record.ExceptionAddress);
    const auto operation = record.ExceptionInformation[0];
    const char *kind = operation == 0 ? "read" : operation == 1 ? "write" : operation == 8 ? "execute" : "access";
    if (GetModuleHandleExA(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
                           reinterpret_cast<LPCSTR>(instruction), &module) && GetModuleFileNameA(module, path, MAX_PATH)) {
        const char *name = std::strrchr(path, '\\');
        LOG("Windows access violation (0xc0000005): %s in %s+0x%llx", kind, name ? name + 1 : path,
            static_cast<unsigned long long>(instruction - reinterpret_cast<uintptr_t>(module)));
    } else {
        LOG("Windows access violation (0xc0000005): %s outside a loaded module", kind);
    }
    uint32_t guest = 0;
    if (recomp_mem && mem::guest_address(reinterpret_cast<void *>(record.ExceptionInformation[1]), &guest))
        LOG("guest address: %08x", guest);
    std::fflush(stderr);
    return EXCEPTION_CONTINUE_SEARCH;
}
#endif

constexpr std::array<uint8_t, 32> expected_code = {
    0xe1, 0xd7, 0xe1, 0x88, 0xff, 0x88, 0x46, 0x7d, 0xf7, 0x76, 0xc1, 0x7c, 0xec, 0x45, 0xc4, 0x48,
    0x57, 0xfa, 0xdf, 0x5b, 0x69, 0x99, 0x44, 0xba, 0xa8, 0xcd, 0xdc, 0xae, 0x7d, 0x93, 0x9e, 0x64,
};

GameImage load(const char *path) {
    const auto image = std::filesystem::u8path(path);
    if (peek_program_id(image) != europe_title)
        fatal("%s\n\nSelected file: %s", cartridge_required, path);
    open_dump(image);
    const auto &code = dump().code();
    if (code.size() != 0x2f4000) fatal("%s", cartridge_required);
    std::array<uint8_t, 32> hash{};
#ifdef _WIN32
    const auto status = BCryptHash(BCRYPT_SHA256_ALG_HANDLE, nullptr, 0, const_cast<PUCHAR>(code.data()),
                                   static_cast<ULONG>(code.size()), hash.data(), static_cast<ULONG>(hash.size()));
    const bool hashed = status >= 0;
#else
    const bool hashed = SHA256(code.data(), code.size(), hash.data()) != nullptr;
#endif
    if (!hashed || hash != expected_code) fatal("%s", cartridge_required);
    mem::init();
    return load_game();
}

int verify_native_startup(const char *path, bool original) {
    sm3dl::set_boot_fps(original ? 30 : 60);
    const auto image = load(path);
    constexpr uint32_t entry = 0x00100000;
    const auto *first = game_code::functions();
    const auto *end = first + game_code::function_count();
    const auto *start = std::lower_bound(first, end, entry,
        [](const RecompEntry &item, uint32_t target) { return item.addr < target; });
    if (start == end || start->addr != entry || !start->fn)
        fatal("The native startup entry point is missing");
    const auto helper = std::lower_bound(first, end, 0x00473000u,
        [](const RecompEntry &item, uint32_t target) { return item.addr < target; });
    const bool patched_table = helper != end && helper->addr == 0x00473000u && helper->fn;
    const bool original_hook = mem::read32(0x0011abfc) == 0xe5900008u;
    if (patched_table == original || original_hook != original ||
        image.bss_size != (original ? 0x3d684u : 0x7e684u))
        fatal("The selected ARM data and native function table do not match the FPS mode");
    std::printf("Verified the %d FPS ARM mode and native entry point at 0x%08x\n", sm3dl::boot_fps(), entry);
    return 0;
}

int verify_mouse_idle() {
    sm3dl::CursorIdle cursor{50};
    if (cursor.expired(7049) || !cursor.expired(7050)) return 1;
    cursor.moved(8000);
    if (cursor.expired(8000) || cursor.expired(14999) || !cursor.expired(15000)) return 1;
    std::puts("Cursor timeout is seven seconds and resets on mouse activity");
    return 0;
}

int verify_texture_updates() {
    constexpr uint32_t width = 32, height = 24;
    std::array<uint8_t, width * height> compressed{};
    uint32_t seed = 0x9b31a59u;
    for (auto &byte : compressed) {
        seed = seed * 1664525u + 1013904223u;
        byte = uint8_t(seed >> 24);
    }
    pica::Texture texture{};
    texture.data = compressed.data();
    texture.bytes = static_cast<uint32_t>(compressed.size());
    texture.width = width;
    texture.height = height;
    texture.format = 13; // ETC1 with 4-bit alpha
    texture.mag_linear = false;
    texture.wrap_s = texture.wrap_t = 0;
    std::array<uint8_t, width * height * 4> reference{}, incremental{};
    pica::decode_texture(texture, incremental.data());
    for (uint32_t y = 0; y < height; ++y) {
        for (uint32_t x = 0; x < width; ++x) {
            const auto sample = pica::sample_texture(texture, (x + 0.5f) / width, (height - y - 0.5f) / height);
            const auto *pixel = incremental.data() + (y * width + x) * 4;
            if (pixel[0] != sample.r || pixel[1] != sample.g || pixel[2] != sample.b || pixel[3] != sample.a)
                fatal("ETC1A4 full decode differs from texture sampling at %u,%u", x, y);
        }
    }

    auto previous = compressed;
    for (const size_t offset : {size_t{0}, size_t{8}, size_t{21}, compressed.size() - 1}) {
        compressed[offset] ^= 0x7b;
        pica::update_etc1a4(texture, previous.data(), incremental.data());
        pica::decode_texture(texture, reference.data());
        if (incremental != reference || previous != compressed)
            fatal("ETC1A4 block cache differs from full decode after changing byte %zu", offset);
    }
    std::puts("ETC1A4 full decode and incremental updates match texture sampling and reference decoding");
    return 0;
}

int verify_display_colors() {
    std::array<uint8_t, 8 * 8 * 2> render_target{}, scanout{};
    constexpr uint32_t gx_rgb565 = 2u << 8 | 2u << 12;
    struct Sample {
        pica::Rgba color;
        uint16_t packed;
    };
    constexpr std::array<Sample, 6> samples = {{
        {{0, 0, 0, 255}, 0x0000},
        {{132, 130, 132, 255}, 0x8410},
        {{255, 255, 255, 255}, 0xffff},
        {{255, 0, 0, 255}, 0xf800},
        {{0, 255, 0, 255}, 0x07e0},
        {{0, 0, 255, 255}, 0x001f},
    }};
    const auto format = pica::render_target_format(3u << 16);
    if (pica::render_target_format(2u << 16) != pica::FB_RGB5A1)
        fatal("PICA RGB5A1 render-target format was decoded incorrectly");
    for (uint32_t x = 0; x < samples.size(); ++x)
        pica::fb_encode(format, samples[x].color, render_target.data() + pica::morton8(x, 0) * 2);
    pica::convert_transfer(render_target.data(), 8, 8, scanout.data(), 8, 8, gx_rgb565);
    for (uint32_t x = 0; x < samples.size(); ++x) {
        if (pica::load16(scanout.data() + x * 2) != samples[x].packed)
            fatal("PICA RGB565 display transfer changed the packed color at pixel %u", x);
    }
    std::puts("PICA render targets preserve RGB565 colors through the display transfer");
    return 0;
}

void play(const char *path) {
    const auto image = load(path);
    LOG("startup: opening save storage");
    sm3dl::lock_save_directory(platform::state_dir());
    LOG("startup: initializing the game kernel");
    kernel::init(image);
    kernel::run(image);
}
}

template<typename Char>
int run_game(int argc, Char **argv) {
#ifdef _WIN32
    SetUnhandledExceptionFilter(report_access_violation);
#endif
    const auto option = argc > 1 ? utf8_path(argv[1]) : std::string{};
    if (argc == 2 && option == "--verify-gamepad") return frontend::verify_gamepad();
    if (argc == 2 && option == "--verify-aspect-ratio") return frontend::verify_aspect_ratio();
    if (argc == 2 && option == "--verify-textures") return verify_texture_updates();
    if (argc == 2 && option == "--verify-display-colors") return verify_display_colors();
    if (argc == 2 && option == "--verify-apt-wrap") return hle::verify_apt_wrap();
    if (argc == 2 && option == "--verify-mouse-idle") return verify_mouse_idle();
    const bool verify = argc == 3 && (option == "--verify-startup" || option == "--verify-original-startup");
    if (!verify && (argc > 2 || option.starts_with("--"))) {
        std::puts("SuperMario3DLandRecompiled [path to a decrypted European ROM (.3ds, .cci, .cxi)]");
        return argc == 2 && option == "--help" ? 0 : 2;
    }
    log_cfg::init();
    if (verify) return verify_native_startup(utf8_path(argv[2]).c_str(), option == "--verify-original-startup");
    LOG("timing: original 30 Hz game logic");
    if (!std::getenv("SM3DL_NO_DIALOG")) {
        fatal_hook = [](const char *message) {
            SDL_ShowSimpleMessageBox(SDL_MESSAGEBOX_ERROR, "Super Mario 3D Land", message, nullptr);
        };
    }
    const char *base = SDL_GetBasePath();
    const auto directory = std::filesystem::u8path(base ? base : ".");
    std::filesystem::path image;
    if (argc == 2) {
        image = argv[1];
    } else {
        image = directory / "SM3DL-EUR.cxi";
        if (!std::filesystem::is_regular_file(image)) image = directory / ".." / "extracted" / "SM3DL-EUR.cxi";
        if (!std::filesystem::is_regular_file(image)) {
            if (std::getenv("SM3DL_NO_DIALOG")) fatal("%s", cartridge_required);
            image = pick_cartridge();
            if (image.empty()) return 0;
        }
    }
    const auto path = utf8_path(image);
    if (!std::filesystem::is_regular_file(image)) fatal("ROM file not found: %s", path.c_str());
    frontend::run(play, path.c_str());
    return 0;
}

#ifdef _WIN32
int wmain(int argc, wchar_t **argv) { return run_game(argc, argv); }
#else
int main(int argc, char **argv) { return run_game(argc, argv); }
#endif
