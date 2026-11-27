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
uint32_t native_render_id = 0;
uint64_t native_pushes = 0, native_drops = 0, native_pops = 0, native_empty = 0;''', 1)
    source = replace_once(source, 'void advance_top_queue() {', 'void advance_top_queue(bool native_frame = false) {')
    source = replace_once(source, '        q.priming = true;\n        return;', '''        if (native_frame) ++native_empty;
        // A late native image only costs this tick. Requiring two more images
        // after a single miss inserts another hitch, even when rendering has recovered.
        if (!native_frame) q.priming = true;
        return;''')
    source = replace_once(source, '    while (q.ready.size() > q.depth) q.ready.pop_front(), interp_stats.dropped++; // fell behind',
        '''    // Native ARM phases sometimes complete two at once. Keep the small
    // extra headroom instead of discarding a valid phase that the next
    // VBlank may need. The older synthetic path keeps its original cap.
    const size_t limit = q.depth + (native_frame ? 1u : 0u);
    while (q.ready.size() > limit) {
        q.ready.pop_front(); ++interp_stats.dropped;
        if (native_frame) ++native_drops;
    }
    if (native_frame) ++native_pops;''')
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
        // Two frames of headroom absorb alternating late/early native
        // phases without changing guest timing. At most four pending images.
        q.depth = 3;
        if (q.last_push + 4 < vblanks.load()) q.reset();
        while (q.ready.size() >= 4) q.ready.pop_front(), ++native_drops;
        q.ready.push_back(qslot);
        ++native_pushes;
        native_render_id = stamp;
        q.last_push = vblanks.load();
        q.addr = out;
    } else if (queue) {
        if (mid) interp_stats.mids++;''', 1)
    source = source.replace('    advance_top_queue();\n    SDL_UnlockMutex(lcd_lock);', '''    static const bool baseline = std::getenv("SM3DL_ALON_BASE_RENDER") != nullptr;
    if (baseline) advance_top_queue();
    SDL_UnlockMutex(lcd_lock);''', 1)
    source = replace_once(source, '    if (queue) blit(src->tex, q.tex[qslot]);', '''    if (queue) {
        // The native LCD and queued native frame contain exactly the same
        // RGBA pixels. Copy the completed scanout instead of running its
        // full-screen conversion shader a second time.
        static const bool duplicate = std::getenv("SM3DL_DUPLICATE_NATIVE_BLIT") != nullptr;
        if (native && !duplicate && !land_bottom) {
            SDL_GPUTextureLocation from{}, to{};
            from.texture = f.tex[slot]; to.texture = q.tex[qslot];
            SDL_GPUCopyPass *copy = SDL_BeginGPUCopyPass(cmd);
            SDL_CopyGPUTextureToTexture(copy, &from, &to, uint32_t(w), uint32_t(h), 1, false);
            SDL_EndGPUCopyPass(copy);
        } else blit(src->tex, q.tex[qslot]);
    }''')
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
            vblanks.load() - q.last_push < 5) {
            advance_top_queue(true);
            const int slot = q.latest >= 0 ? q.latest : q.ready.empty() ? -1 : q.ready.front();
            if (slot >= 0) result = q.tex[slot];
            if (result) *width = q.w, *height = q.h;
        } else {
            q.reset();
        }
        static const bool trace = std::getenv("SM3DL_ALON_TRACE") != nullptr;
        static unsigned ticks = 0;
        if (trace && ++ticks == 300) {
            LOG("native queue: %llu pushed, %llu shown, %llu dropped, %llu empty ticks, %zu pending",
                (unsigned long long)native_pushes, (unsigned long long)native_pops,
                (unsigned long long)native_drops, (unsigned long long)native_empty, q.ready.size());
            native_pushes = native_pops = native_drops = native_empty = 0;
            ticks = 0;
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


def protect_sampled_textures(source):
    # Keep native and replacement resources separate. A warm HD toggle should
    # not reload every image in the scene or retire an entire cache at once.
    source = replace_once(source, '    uint64_t mod_hash = 0;',
        '    unsigned missing_hd = 0; // packs that have no replacement for this fingerprint\n'
        '    uint64_t mod_hash = 0;')
    source = replace_once(source,
        'std::map<std::tuple<uint32_t, uint32_t, uint32_t, uint32_t>, CachedTexture> textures;',
        '''using TextureKey = std::tuple<uint32_t, uint32_t, uint32_t, uint32_t, int>;
std::map<TextureKey, CachedTexture> textures;''')
    source = replace_once(source, '#include "vulkan_submission.inc"', '''#include "vulkan_submission.inc"

std::vector<SDL_GPUTexture *> retiring_textures;

void retire_sampled_texture(SDL_GPUTexture *texture) {
    // Unlike SDL's already-encoded GPU work, DrawRec and TextureUpload
    // only hold raw pointers until flush records them into a command buffer.
    if (list_commands.recording) retiring_textures.push_back(texture);
    else SDL_ReleaseGPUTexture(dev, texture);
}

bool texture_queued(SDL_GPUTexture *texture) {
    const auto uses = [texture](const DrawRec &draw) {
        return std::find(std::begin(draw.tex), std::end(draw.tex), texture) != std::end(draw.tex);
    };
    return uses(cur) || std::any_of(batch.begin(), batch.end(), uses) ||
        std::any_of(texture_uploads.begin(), texture_uploads.end(),
                    [texture](const TextureUpload &upload) { return upload.tex == texture; });
}''')
    source = replace_once(source, '''    auto key = std::make_tuple(t.addr, t.width, t.height, t.format);
    auto it = textures.find(key);
    if (it != textures.end() && it->second.hash == fingerprint) {
        mipmaps = it->second.levels > 1;
        it->second.last_used = use_clock;
        return it->second.tex;
    }''', '''    const TextureKey key{t.addr, t.width, t.height, t.format, hd_pack_quality};
    const TextureKey native_key{t.addr, t.width, t.height, t.format, 0};
    auto it = textures.find(key);
    const auto matches = [&](auto entry) {
        return entry != textures.end() && entry->second.hash == fingerprint;
    };
    const auto use = [&](CachedTexture &entry) {
        mipmaps = entry.levels > 1;
        entry.last_used = use_clock;
        return entry.tex;
    };
    if (matches(it)) return use(it->second);
    const auto native = hd_pack_quality ? textures.find(native_key) : it;
    const unsigned quality_bit = 1u << hd_pack_quality;
    if (hd_pack_quality && matches(native) && (native->second.missing_hd & quality_bit))
        return use(native->second);''')
    source = replace_once(source,
        '    const HdImage *hd = hd_pack_quality && pack.rgba.empty() ? hd_texture(h) : nullptr;',
        '''    const HdImage *hd = hd_pack_quality && pack.rgba.empty() ? hd_texture(h) : nullptr;
    const bool replaced = !pack.rgba.empty() || hd;
    if (!replaced) {
        it = native;
        if (matches(it)) {
            it->second.missing_hd |= quality_bit;
            return use(it->second);
        }
    }''')
    source = replace_once(source, '''    if (it != textures.end() && (it->second.w != w || it->second.h != th || it->second.levels != levels)) { // an HD texture came or went
        SDL_ReleaseGPUTexture(dev, it->second.tex);
        textures.erase(it);
        it = textures.end();
    }
    if (it == textures.end())
        it = textures.emplace(key, CachedTexture{make_texture(w, th, SDL_GPU_TEXTUREFORMAT_R8G8B8A8_UNORM,
                                                              SDL_GPU_TEXTUREUSAGE_SAMPLER | (mipmaps ? SDL_GPU_TEXTUREUSAGE_COLOR_TARGET : 0),
                                                              levels), fingerprint, use_clock, w, th})
                 .first;''', '''    const bool resize = it != textures.end() &&
        (it->second.w != w || it->second.h != th || it->second.levels != levels);
    // All uploads in a batch are encoded before its draws. Never overwrite
    // a texture a previous draw in this batch still expects to sample.
    if (it != textures.end() && (resize || texture_queued(it->second.tex))) {
        auto *old = it->second.tex;
        retire_sampled_texture(old);
        if (resize) {
            textures.erase(it);
            it = textures.end();
        } else {
            it->second.tex = make_texture(w, th, SDL_GPU_TEXTUREFORMAT_R8G8B8A8_UNORM,
                SDL_GPU_TEXTUREUSAGE_SAMPLER | (mipmaps ? SDL_GPU_TEXTUREUSAGE_COLOR_TARGET : 0), levels);
        }
        if (std::getenv("SM3DL_TRACE_TEXTURE_UPLOADS"))
            LOG("gpu: preserved a pending texture version at %08x", t.addr);
    }
    if (it == textures.end())
        it = textures.emplace(replaced ? key : native_key,
                 CachedTexture{make_texture(w, th, SDL_GPU_TEXTUREFORMAT_R8G8B8A8_UNORM,
                                            SDL_GPU_TEXTUREUSAGE_SAMPLER | (mipmaps ? SDL_GPU_TEXTUREUSAGE_COLOR_TARGET : 0),
                                            levels), fingerprint, use_clock, w, th}).first;
    it->second.missing_hd = replaced ? 0 : quality_bit;''')
    source = replace_once(source, '            SDL_ReleaseGPUTexture(dev, it->second.tex);\n            it = textures.erase(it);',
        '            retire_sampled_texture(it->second.tex);\n            it = textures.erase(it);')
    source = replace_once(source, '''void end_list() {
    submit_recorded_commands();
    list_commands.recording = false;
}''', '''void end_list() {
    submit_recorded_commands();
    list_commands.recording = false;
    for (auto *texture : retiring_textures) SDL_ReleaseGPUTexture(dev, texture);
    retiring_textures.clear();
}''')
    source = replace_once(source, '''        flush(); // finish draws that still reference the old pack
        // SDL defers releasing in-flight GPU resources. Rebuild textures at a guest list boundary.
        for (const auto &[key, entry] : textures) SDL_ReleaseGPUTexture(dev, entry.tex);
        textures.clear();
        hd_pack_quality = hd;''', '''        // Apply the menu request on the guest render thread. Each draw retains
        // the variant it was created with. Evict only inactive replacements.
        hd_pack_quality = hd;
        trim_inactive_hd_textures(hd);''')
    return replace_once(source, '''void begin_list() {
    list_commands.recording = true;''', '''uint64_t sampled_texture_bytes(const CachedTexture &entry) {
    uint64_t total = 0;
    for (uint32_t level = 0; level < entry.levels; ++level)
        total += uint64_t(std::max(1u, entry.w >> level)) * std::max(1u, entry.h >> level) * 4;
    return total;
}

void trim_inactive_hd_textures(int quality) {
    // Keep a small hot cache for switching back quickly, not two full packs.
    // The normal textures and the active pack keep their existing eviction.
    constexpr uint64_t budget = 64ull << 20;
    std::vector<decltype(textures)::iterator> inactive;
    uint64_t bytes = 0;
    for (auto it = textures.begin(); it != textures.end(); ++it) {
        const int pack = std::get<4>(it->first);
        if (!pack || pack == quality) continue;
        inactive.push_back(it);
        bytes += sampled_texture_bytes(it->second);
    }
    if (bytes <= budget) return;
    std::sort(inactive.begin(), inactive.end(), [](auto a, auto b) {
        return a->second.last_used < b->second.last_used;
    });
    const uint64_t before = bytes;
    for (auto it : inactive) {
        if (bytes <= budget) break;
        bytes -= sampled_texture_bytes(it->second);
        retire_sampled_texture(it->second.tex);
        textures.erase(it);
    }
    if (std::getenv("SM3DL_TRACE_UPLOAD_MEMORY"))
        LOG("gpu: inactive texture pack cache trimmed from %llu to %llu MiB",
            (unsigned long long)(before >> 20), (unsigned long long)(bytes >> 20));
}

void begin_list() {
    list_commands.recording = true;''')


def bound_upload_staging(source):
    start = source.index('// Keep the transfer buffer across batches.')
    end = source.index('// copies pending texture, LUT, surface and vertex data', start)
    source = source[:start] + '#include "vulkan_upload_buffers.inc"\n\n' + source[end:]
    source = replace_once(source, 'void upload_pending(SDL_GPUCommandBuffer *cmd, SDL_GPUBuffer **vbuf) {',
        'uint64_t upload_pending(SDL_GPUCommandBuffer *cmd, SDL_GPUBuffer **vbuf) {')
    start = source.index('    if (!total) return;', source.index('uint64_t upload_pending('))
    end = source.index('    if (!map) {', start)
    source = source[:start] + '''    if (!total) return 0;
    const auto staging = acquire_upload_staging(total);
    auto *tb = staging.buffer;
    auto *map = tb ? static_cast<uint8_t *>(SDL_MapGPUTransferBuffer(dev, tb, !staging.transient)) : nullptr;
''' + source[end:]
    source = replace_once(source, '        texture_uploads.clear(), surface_loads.clear();\n        return;',
        '        if (tb && staging.transient) SDL_ReleaseGPUTransferBuffer(dev, tb);\n'
        '        texture_uploads.clear(), surface_loads.clear();\n        return 0;')
    source = replace_once(source, '''    SDL_EndGPUCopyPass(copy);
    for (const auto &upload : texture_uploads)''', '''    SDL_EndGPUCopyPass(copy);
    // SDL retains the encoded reference until the command completes.
    if (staging.transient) SDL_ReleaseGPUTransferBuffer(dev, tb);
    for (const auto &upload : texture_uploads)''')
    source = replace_once(source, '    lut_upload = false;\n}\n\nvoid clear_fresh',
        '''    lut_upload = false;
    if (staging.transient && total >= (16u << 20) && std::getenv("SM3DL_TRACE_UPLOAD_MEMORY"))
        LOG("gpu: %llu MiB temporary upload", (unsigned long long)(total >> 20));
    return staging.transient ? total : 0;
}

void clear_fresh''')
    source = replace_once(source, '    upload_pending(cmd, &vbuf);',
        '    const auto temporary_uploads = upload_pending(cmd, &vbuf);')
    return replace_once(source, '    submit_commands(cmd);\n    if (vbuf) SDL_ReleaseGPUBuffer(dev, vbuf);',
        '    submit_commands(cmd, temporary_uploads);\n    if (vbuf) SDL_ReleaseGPUBuffer(dev, vbuf);')


def idempotent_lighting_writes(source):
    return replace_once(source,
        '            if (table < 24) lighting_lut[table][at & 0xFF] = value, lighting_lut_version++;',
        '''            if (table < 24) {
                auto &entry = lighting_lut[table][at & 0xFF];
                if (entry != value) entry = value, ++lighting_lut_version;
            }''')


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
    edit(src / 'video/gpu/gpu.cpp', lambda source: replace_once(texture_options(source),
        'sm3dl::load_pack_texture(t.data, t.bytes, t.width, t.height, t.format, hd_pack_quality)',
        'sm3dl::load_pack_texture(t.data, t.bytes, t.width, t.height, t.format, hd_pack_quality,\n'
        '        fresh ? std::optional<uint64_t>{fingerprint} : std::nullopt)'))
    edit(src / 'video/gpu/gpu.cpp', lambda source: bound_upload_staging(protect_sampled_textures(vulkan_scheduling(source))))
    edit(src / 'frontend/settings.h', settings_fields)
    edit(src / 'frontend/settings.cpp', settings_options)
    edit(src / 'frontend/sdl.cpp', lambda source: reserve_frontend(frontend_options(source)))
    edit(src / 'video/pica.cpp', reserve_pica)
    edit(src / 'video/gpu/gpu.h', lambda source: source.replace('SDL_GPUTexture *top_frame(',
        'void remember_alon_top_buffer(uint32_t address);\nSDL_GPUTexture *top_frame(', 1))
    edit(src / 'hle/gsp.cpp', alon_gsp)
    edit(src / 'video/pica.cpp', coherent_pica_fast)
    edit(src / 'video/pica.cpp', idempotent_lighting_writes)
    edit(src / 'video/pica.cpp', lambda source: replace_once(source,
        '    flush_draws(); // the GPU is done with this list once everything in it is drawn',
        '    flush_draws(); // send the recorded passes before completing the guest list\n'
        '    if (gpu::active()) gpu::end_list();'))
    edit(src / 'video/gpu/gpu.h', lambda source: replace_once(source, 'void begin_list();',
        'void end_list(); // submit outstanding passes on the recording thread\nvoid begin_list();'))
    edit(src / 'kernel/kernel.cpp', coherent_timer)


if __name__ == '__main__':
    main()
