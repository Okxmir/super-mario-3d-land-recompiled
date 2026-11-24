"""Use the upstream ARM render phases in the native port."""

import argparse
from pathlib import Path

from coherent_pica_fast import coherent_pica_fast
from coherent_timer import coherent_timer
from display_options import frontend_options, settings_options, settings_fields, texture_options
from prepare_runtime import edit, prepare
from reserve_runtime import reserve_frontend, reserve_pica


def replace_once(source, old, new):
    if source.count(old) != 1:
        raise ValueError(f'Expected one rendering anchor: {old.splitlines()[0]}')
    return source.replace(old, new, 1)


def faster_scanout_draws(source):
    # In widescreen, perspective triangles never need a HUD bounding box.
    # Leave the orthographic classification and the stencil/culling path alone.
    source = replace_once(source, '''        bool perspective = false;
        float lo = 1e9f, hi = -1e9f, xlo = 1e9f, xhi = -1e9f;
        for (auto *x : v) {
            float w = x->a[POS + 3];
            perspective |= std::fabs(w - 1.0f) > 1e-4f;
            lo = std::min(lo, x->a[POS + 1] / w), hi = std::max(hi, x->a[POS + 1] / w);
            xlo = std::min(xlo, x->a[POS] / w), xhi = std::max(xhi, x->a[POS] / w);
        }
        // only full-screen layers (backgrounds, fades, tints) and bars across the whole width (a
        // banner, a menu's title bar: see side_of) stretch; other HUD keeps its size
        bool full_screen = draw_fills_screen || (!perspective && draw_geom.valid && draw_geom.full_width) ||
                           (!perspective && lo <= -0.99f && hi >= 0.99f && xlo <= -0.99f && xhi >= 0.99f);''', '''        const bool perspective = std::fabs(v0.a[POS + 3] - 1.0f) > 1e-4f ||
                                 std::fabs(v1.a[POS + 3] - 1.0f) > 1e-4f ||
                                 std::fabs(v2.a[POS + 3] - 1.0f) > 1e-4f;
        bool full_screen = draw_fills_screen;
        if (!full_screen && !perspective) {
            full_screen = draw_geom.valid && draw_geom.full_width;
            if (!full_screen) {
                float lo = 1e9f, hi = -1e9f, xlo = 1e9f, xhi = -1e9f;
                for (const auto *x : v) {
                    const float yy = x->a[POS + 1] / x->a[POS + 3], xx = x->a[POS] / x->a[POS + 3];
                    lo = std::min(lo, yy), hi = std::max(hi, yy);
                    xlo = std::min(xlo, xx), xhi = std::max(xhi, xx);
                }
                full_screen = lo <= -0.99f && hi >= 0.99f && xlo <= -0.99f && xhi >= 0.99f;
            }
        }''')
    return source


def faster_texture_checks(source):
    # These fingerprints are internal. Preserve old on-disk mod/dump names.
    source = replace_once(source, 'return g ? hash_bytes(g, s.bytes()) : 0;',
        'return g ? sm3dl::texture_hash(reinterpret_cast<const char *>(g), s.bytes()) : 0;')
    source = replace_once(source, '    uint32_t changes = 0; // times its contents changed: text the game draws into it, not art',
        '''    uint32_t changes = 0; // times its contents changed: text the game draws into it, not art
    uint64_t mod_hash = 0; // legacy key for local texture mods and dumps''')
    source = replace_once(source, '''    if (fresh) known->second = hash_bytes(t.data, t.bytes);
    uint64_t h = known->second;''', '''    if (fresh) known->second = sm3dl::texture_hash(reinterpret_cast<const char *>(t.data), t.bytes);
    const uint64_t fingerprint = known->second;''')
    source = replace_once(source, 'it->second.hash == h) {', 'it->second.hash == fingerprint) {')
    source = replace_once(source, '    int64_t t0 = now_ns();\n    sm3dl::PackTexture pack;',
        '''    int64_t t0 = now_ns();
    const uint64_t h = hash_bytes(t.data, t.bytes);
    sm3dl::PackTexture pack;''')
    source = replace_once(source, 'levels), h, use_clock, w, th})', 'levels), fingerprint, use_clock, w, th})')
    source = replace_once(source, '    it->second.hash = h;', '    it->second.hash = fingerprint;\n    it->second.mod_hash = h;')
    return replace_once(source, 'if (c.hash == h) c.hash = 0;', 'if (c.mod_hash == h) c.hash = 0;')


def alon_loader(source):
    changes = {
        '#include "loader.h"': '#include "loader.h"\n#include "display_options.h"',
        '} // namespace\n\nGameImage load_game()':
            '#include "alon_eur_payload.inc"\n} // namespace\n\nGameImage load_game()',
        '    g.bss_size = u32(exheader, 0x3C);': '    g.bss_size = sm3dl::boot_fps() == 60 ? 0x7e684 : u32(exheader, 0x3C);',
        '    LOG("loaded %s:':
            '    if (sm3dl::boot_fps() == 60) {\n'
            '        mem::commit(0x00473000, mem::PAGE); // relocated glove helper\n'
            '        install_alon_eur_patch();\n'
            '        LOG("timing: Alon ARM 0.2-preview relocated for EUR; renderer uses native guest frames");\n'
            '    } else {\n'
            '        LOG("timing: original ARM render path (30 FPS)");\n'
            '    }\n'
            '    LOG("loaded %s:',
    }
    for old, new in changes.items():
        if source.count(old) != 1:
            raise ValueError(f'Unexpected loader anchor: {old}')
        source = source.replace(old, new)
    return source


def alon_gsp(source):
    source = '#include "display_options.h"\n' + source
    source = source.replace('            remember(left_eye, info[1]);',
        '            remember(left_eye, info[1]);\n            pica::gpu::remember_alon_top_buffer(info[1]);', 1)
    source = source.replace('            frames_rendered = top_updates = interpolated_slots = 0;',
        '''            if (sm3dl::boot_fps() == 60 && std::getenv("SM3DL_ALON_TRACE")) {
                static uint32_t last_dispatch = 0, last_updates = 0;
                const auto dispatch = mem::read32(0x00432008), updates = mem::read32(0x00432040);
                LOG("alon: %.1f dispatch/s, %.1f simulation updates/s", (dispatch - last_dispatch) / seconds,
                    (updates - last_updates) / seconds);
                last_dispatch = dispatch;
                last_updates = updates;
            }
            frames_rendered = top_updates = interpolated_slots = 0;''', 1)
    return alon_frame_samples(source)


def alon_native_scanout(source):
    # Keep both ARM-rendered phases when they arrive in the same VBlank
    # interval, without synthesizing an image or delaying the guest IRQs.
    source = '#include "display_options.h"\n' + source
    source = source.replace('} top_queue; // under lcd_lock', '''} top_queue; // under lcd_lock
std::array<uint32_t, 3> native_lcd_addresses{}; // previous top-left selections, under lcd_lock
uint32_t native_render_id = 0;''', 1)
    source = replace_once(source, 'void advance_top_queue() {', 'void advance_top_queue(bool native_frame = false) {')
    source = replace_once(source, '        q.priming = true;\n        return;', '''        // A late native image only costs this tick. Requiring two more images
        // after a single miss inserts another hitch, even when rendering has recovered.
        if (!native_frame) q.priming = true;
        return;''')
    source = source.replace('    bool queue = top && interp_on;', '''    static const bool baseline = std::getenv("SM3DL_ALON_BASE_RENDER") != nullptr;
    const uint32_t stamp = sm3dl::boot_fps() == 60 && !baseline && top && land_top && mem::is_committed(0x00432008u) ?
        mem::read32(0x00432008u) : 0;
    const bool native = out && stamp && stamp != native_render_id &&
        std::find(native_lcd_addresses.begin(), native_lcd_addresses.end(), out) != native_lcd_addresses.end();
    bool queue = native || (top && interp_on);''', 1)
    source = source.replace('    bool mid = queue && interp_this', '    bool mid = !native && queue && interp_this', 1)
    source = source.replace('        qslot = q.next, q.next = (q.next + 1) % 8;', '''        qslot = q.next, q.next = (q.next + 1) % 8;
        if (native && !q.tex[qslot]) q.reset(), queue = false;''', 1)
    source = source.replace('    if (queue) {\n        if (mid) interp_stats.mids++;', '''    if (queue && native) {
        // One frame of headroom handles a render that finishes just either
        // side of the VBlank. Never accumulate a long or stale queue.
        q.depth = 2;
        if (q.last_push + 3 < vblanks.load()) q.reset();
        while (q.ready.size() >= 3) q.ready.pop_front();
        q.ready.push_back(qslot);
        native_render_id = stamp;
        q.last_push = vblanks.load();
        q.addr = out;
    } else if (queue) {
        if (mid) interp_stats.mids++;''', 1)
    source = source.replace('    advance_top_queue();\n    SDL_UnlockMutex(lcd_lock);', '''    static const bool baseline = std::getenv("SM3DL_ALON_BASE_RENDER") != nullptr;
    if (baseline) advance_top_queue();
    SDL_UnlockMutex(lcd_lock);''', 1)
    start = source.index('SDL_GPUTexture *top_frame(')
    end = source.index('void enable_course_hud(', start)
    return source[:start] + '''void remember_alon_top_buffer(uint32_t address) {
    if (sm3dl::boot_fps() != 60 || !ok || !address) return;
    SDL_LockMutex(lcd_lock);
    auto &addresses = native_lcd_addresses;
    auto match = std::find(addresses.begin(), addresses.end(), address);
    if (match == addresses.end()) match = addresses.end() - 1;
    std::rotate(addresses.begin(), match, match + 1);
    addresses.front() = address;
    SDL_UnlockMutex(lcd_lock);
}

SDL_GPUTexture *top_frame(uint32_t address, int *width, int *height, bool *interpolated) {
    *interpolated = false;
    static const bool baseline = std::getenv("SM3DL_ALON_BASE_RENDER") != nullptr;
    if (sm3dl::boot_fps() == 60 && !baseline && ok) {
        SDL_LockMutex(lcd_lock);
        auto &q = top_queue;
        const auto it = lcd.find(address);
        SDL_GPUTexture *result = nullptr;
        if (it != lcd.end() && it->second.latest >= 0 && it->second.w == q.w && it->second.h == q.h &&
            vblanks.load() - q.last_push < 3) {
            advance_top_queue(true);
            const int slot = q.latest >= 0 ? q.latest : q.ready.empty() ? -1 : q.ready.front();
            if (slot >= 0) result = q.tex[slot];
            if (result) *width = q.w, *height = q.h;
        } else {
            q.reset();
        }
        SDL_UnlockMutex(lcd_lock);
        if (result) return result;
    }
    return lcd_frame(address, width, height);
}

''' + source[end:]


def alon_frame_samples(source):
    source = source.replace('#include <cstdlib>', '#include <cstdlib>\n#include <bit>\n#include <cstdio>')
    return source.replace('            if (screen == 0 && frame != previous_top_frame) {', '''            if (screen == 0) {
                static std::FILE *csv = [] {
                    const auto *path = std::getenv("SM3DL_ALON_CSV");
                    auto *out = path ? std::fopen(path, "wb") : nullptr;
                    if (out) std::fputs("ns,new_frame,dispatch,simulation,timer,x,y,z\\n", out);
                    return out;
                }();
                if (csv) {
                    const auto now = std::chrono::steady_clock::now();
                    const auto read = [](uint32_t p) {
                        return p && !(p & 3u) && mem::is_committed(p) ? mem::read32(p) : 0u;
                    };
                    const auto app = read(0x003e23c4);
                    const auto actor = app ? read(app + 0x5c) : 0;
                    const auto pose = actor ? read(actor + 0x14) : 0;
                    uint32_t timer = app;
                    for (const uint32_t offset : {0x14, 0x1c, 0x90, 0x1b0, 0x24})
                        timer = timer ? read(timer + offset) : 0;
                    const auto xyz = [&](uint32_t offset) {
                        return pose ? std::bit_cast<float>(read(pose + offset)) : 0.f;
                    };
                    const auto ns = std::chrono::duration_cast<std::chrono::nanoseconds>(now.time_since_epoch()).count();
                    static unsigned rows = 0;
                    std::fprintf(csv, "%lld,%d,%u,%u,%u,%.3f,%.3f,%.3f\\n", static_cast<long long>(ns),
                        frame && frame != previous_top_frame, read(0x00432008), read(0x00432040),
                        timer ? read(timer + 0x18) : 0, xyz(4), xyz(8), xyz(12));
                    if (++rows % 60 == 0) std::fflush(csv);
                }
            }
            if (screen == 0 && frame != previous_top_frame) {''', 1)


def vulkan_scheduling(source):
    source = replace_once(source, '#include <bit>', '#include <bit>\n#include <mutex>')
    start = source.index('SDL_GPUCommandBuffer *acquire_commands() {')
    end = source.index("// Copies a surface's image back into guest memory", start)
    source = source[:start] + '#include "vulkan_submission.inc"\n\n' + source[end:]
    source = replace_once(source, '    flush();\n    uint32_t w = s->width, h = s->height;',
        '    flush();\n    submit_recorded_commands(); // readback must see all earlier GPU writes\n'
        '    uint32_t w = s->width, h = s->height;')
    # The readback itself always uses a standalone buffer, regardless of list recording.
    source = replace_once(source, '    uint32_t w = s->width, h = s->height;\n    SDL_GPUTexture *image = s->tex;\n'
        '    SDL_GPUCommandBuffer *cmd = acquire_commands();',
        '    uint32_t w = s->width, h = s->height;\n    SDL_GPUTexture *image = s->tex;\n'
        '    SDL_GPUCommandBuffer *cmd = SDL_AcquireGPUCommandBuffer(dev);\n'
        '    if (!cmd) gpu_failure("readback command acquisition");')
    source = replace_once(source, 'void begin_list() {', '''void end_list() {
    submit_recorded_commands();
    list_commands.recording = false;
}

void begin_list() {
    list_commands.recording = true;''')
    source = replace_once(source, 'SDL_GPUGraphicsPipeline *pipeline(const PipelineKey &k) {',
        'SDL_GPUGraphicsPipeline *pipeline(const PipelineKey &k, bool warmup = false) {')
    source = replace_once(source, '    if (!p) fatal("GPU pipeline: %s", SDL_GetError());', '''    if (!p) {
        if (warmup) return nullptr; // optional variants cannot prevent startup
        fatal("GPU pipeline: %s", SDL_GetError());
    }''')
    source = replace_once(source, '    costs.pipelines++, costs.pipeline_ns += now_ns() - t0;', '''    if (!warmup) costs.pipelines++, costs.pipeline_ns += now_ns() - t0;
    static const bool trace_keys = std::getenv("SM3DL_TRACE_VULKAN_PIPELINES") != nullptr;
    if (trace_keys && !warmup) {
        static constexpr char hex[] = "0123456789abcdef";
        char text[sizeof(PipelineKey) * 2 + 1]{};
        for (size_t i = 0; i < sizeof(PipelineKey); ++i) {
            const auto byte = static_cast<unsigned char>(key[i]);
            text[i * 2] = hex[byte >> 4], text[i * 2 + 1] = hex[byte & 15];
        }
        LOG("vulkan pipeline key: %s", text);
    }''')
    source = replace_once(source, '// ---- the batch ----',
        '#include "vulkan_warmup.inc"\n\n// ---- the batch ----')
    source = replace_once(source, '    lcd_lock = SDL_CreateMutex();\n',
        '    warm_vulkan_pipelines(); // same pipelines, before game timing begins\n'
        '    lcd_lock = SDL_CreateMutex();\n')
    return source


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('upstream', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    # Keep the main port's fixes without the old synthetic Vulkan midpoints.
    prepare(args.upstream, args.output, experimental_geometry=False)
    src = args.output / 'src'
    edit(src / 'loader.cpp', alon_loader)
    edit(src / 'video/gpu/gpu.cpp', lambda source: faster_texture_checks(faster_scanout_draws(alon_native_scanout(source))))
    edit(src / 'video/gpu/gpu.cpp', texture_options)
    edit(src / 'video/gpu/gpu.cpp', vulkan_scheduling)
    edit(src / 'frontend/settings.h', settings_fields)
    edit(src / 'frontend/settings.cpp', settings_options)
    edit(src / 'frontend/sdl.cpp', lambda source: reserve_frontend(frontend_options(source)))
    edit(src / 'video/pica.cpp', reserve_pica)
    edit(src / 'video/gpu/gpu.h', lambda source: source.replace('SDL_GPUTexture *top_frame(',
        'void remember_alon_top_buffer(uint32_t address);\nSDL_GPUTexture *top_frame(', 1))
    edit(src / 'hle/gsp.cpp', alon_gsp)
    edit(src / 'video/pica.cpp', coherent_pica_fast)
    edit(src / 'video/pica.cpp', lambda source: replace_once(source,
        '    flush_draws(); // the GPU is done with this list once everything in it is drawn',
        '    flush_draws(); // send the recorded passes before completing the guest list\n'
        '    if (gpu::active()) gpu::end_list();'))
    edit(src / 'video/gpu/gpu.h', lambda source: replace_once(source, 'void begin_list();',
        'void end_list(); // submit outstanding passes on the recording thread\nvoid begin_list();'))
    edit(src / 'kernel/kernel.cpp', coherent_timer)


if __name__ == '__main__':
    main()
