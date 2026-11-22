// Standalone renderer experiment. No writes to ARM gameplay state.
uint32_t trial_read(uint32_t address) {
    return address && mem::is_committed(address) ? mem::read32(address) : 0;
}

struct TrialPose {
    uint32_t timer;
    float x, y, z;
};

TrialPose trial_pose() {
    const auto app = trial_read(0x003e23c4);
    const auto actor = app ? trial_read(app + 0x5c) : 0;
    const auto pose = actor ? trial_read(actor + 0x14) : 0;
    uint32_t timer = app;
    for (auto offset : {0x14u, 0x1cu, 0x90u, 0x1b0u, 0x24u})
        timer = timer ? trial_read(timer + offset) : 0;
    if (!pose || !timer) return {};
    return {trial_read(timer + 0x18), std::bit_cast<float>(trial_read(pose + 4)),
            std::bit_cast<float>(trial_read(pose + 8)), std::bit_cast<float>(trial_read(pose + 12))};
}

bool trial_motion() {
    static const bool allowed = !std::getenv("SM3DL_TRANSFORM_REFERENCE");
    return allowed && trial_pose().timer != 0;
}

// Audit the selected scanout using nonblocking readbacks on a separate test
// run. Only count scene pixels, not a moving clock or an input cursor.
struct TrialAudit {
    struct Pending {
        SDL_GPUFence *fence{};
        SDL_GPUTransferBuffer *buffer{};
        uint32_t w{}, h{}, allocation{};
        uint64_t tick{}, ticks_ns{};
        TrialPose pose{};
        bool middle{};
    };
    static constexpr unsigned slots = 8;
    Pending pending[slots];
    unsigned head{}, count{};
    FILE *report{};
    const char *capture = std::getenv("SM3DL_SHADOW_CAPTURE");
    const bool native_jump_crop = std::getenv("SM3DL_SHADOW_NATIVE_JUMPS") != nullptr;
    const bool hash_crop = std::getenv("SM3DL_TRANSFORM_HASH_CROP") != nullptr;
    unsigned captured{};
    std::vector<uint32_t> capture_pixels;
    TrialAudit() {
        if (const char *path = std::getenv("SM3DL_TRANSFORM_REPORT"))
            report = std::fopen(path, "wb");
        if (report) std::fputs("tick,ns,mid,timer,x,y,z,hash\n",report);
    }
    void drain() {
        while (count) {
            auto &a = pending[head];
            if (!SDL_QueryGPUFence(dev,a.fence)) break;
            auto *pixels = static_cast<const uint8_t *>(SDL_MapGPUTransferBuffer(dev,a.buffer,false));
            uint64_t hash = 0xcbf29ce484222325ull;
            if (pixels) {
                const uint32_t step = std::max(a.h / 240, 1u);
                // Leave out peripheral HUD; use RGB values only.
                for (uint32_t y = a.h / 5; y < a.h * 9 / 10; y += step)
                    for (uint32_t x = a.w / 20; x < a.w * 19 / 20; x += step) {
                        const auto *p = pixels + (size_t(y) * a.w + x) * 4;
                        hash = (hash ^ (unsigned(p[0]) | unsigned(p[1]) << 8 | unsigned(p[2]) << 16)) * 0x100000001b3ull;
                    }
                // Opt-in visual regression capture using the same scanout sampled above.
                if (capture && captured < 1200) {
                    const uint32_t w = a.w / step, h = a.h / step;
                    const std::string path = std::string(capture) + "/" + std::to_string(a.tick) + "_" +
                        std::to_string(a.middle) + "_" + std::to_string(w) + "_" + std::to_string(h) + ".rgba";
                    if (FILE *f = std::fopen(path.c_str(), "wb")) {
                        if (step == 1) {
                            std::fwrite(pixels, 4, size_t(w) * h, f);
                        } else {
                            capture_pixels.resize(size_t(w) * h);
                            for (uint32_t y = 0; y < h; ++y)
                                for (uint32_t x = 0; x < w; ++x)
                                    std::memcpy(&capture_pixels[size_t(y) * w + x], pixels + (size_t(y * step) * a.w + x * step) * 4, 4);
                            std::fwrite(capture_pixels.data(), 4, capture_pixels.size(), f);
                        }
                        std::fclose(f);
                        ++captured;
                    }
                    // Full-resolution pixels at 4x for the standing jump, not
                    // a downsample hiding subpixel shadow changes. The rest of
                    // the replay stays compact so the audit does not stream GBs.
                    const bool standing = a.pose.x >= -2301.0f && a.pose.x <= -2299.0f;
                    const bool moving = a.pose.x > -2200.0f && a.pose.x < -910.0f;
                    if (native_jump_crop && a.pose.timer < 11000 && (standing || moving) &&
                        a.pose.y > -992.0f && a.pose.z >= -6201.0f && a.pose.z <= -6199.0f) {
                        const uint32_t x0 = a.w * 29 / 100, x1 = a.w * 49 / 100;
                        const uint32_t y0 = a.h * 23 / 100, y1 = a.h * 74 / 100;
                        const std::string crop = std::string(capture) + "/" + std::to_string(a.tick) + "_" +
                            std::to_string(a.middle) + "_" + std::to_string(x1 - x0) + "_" + std::to_string(y1 - y0) +
                            (standing ? ".crop" : ".move");
                        if (FILE *f = std::fopen(crop.c_str(), "wb")) {
                            const uint32_t crop_w = x1 - x0;
                            capture_pixels.resize(size_t(crop_w) * (y1 - y0));
                            for (uint32_t y = y0; y < y1; ++y)
                                std::memcpy(&capture_pixels[size_t(y - y0) * crop_w],
                                    pixels + (size_t(y) * a.w + x0) * 4, size_t(crop_w) * 4);
                            std::fwrite(capture_pixels.data(), 4, capture_pixels.size(), f);
                            std::fclose(f);
                        }
                    }
                }
                SDL_UnmapGPUTransferBuffer(dev,a.buffer);
            } else hash = 0;
            std::fprintf(report,"%llu,%llu,%d,%u,%.5f,%.5f,%.5f,%016llx\n",
                static_cast<unsigned long long>(a.tick),static_cast<unsigned long long>(a.ticks_ns),int(a.middle),
                a.pose.timer,a.pose.x,a.pose.y,a.pose.z,static_cast<unsigned long long>(hash));
            std::fflush(report);
            SDL_ReleaseGPUFence(dev,a.fence);
            head = (head + 1) % slots;
            --count;
        }
    }
    void sample(SDL_GPUTexture *texture,int w,int h,bool middle,uint64_t tick) {
        if (!report) return;
        drain();
        const auto pose = trial_pose();
        if (!texture || !pose.timer || count == slots || w <= 0 || h <= 0) return;
        uint32_t x = 0, y = 0;
        if (hash_crop && !capture) {
            // Timing audit of the native center area: avoid a full 4x GPU
            // readback and any image writes. The game still draws at 4x.
            x = uint32_t(w) * 27 / 100; y = uint32_t(h) * 15 / 100;
            w = w * 29 / 100; h = h * 66 / 100;
        }
        auto &a = pending[(head + count) % slots];
        const uint32_t size = uint32_t(w) * uint32_t(h) * 4;
        if (!a.buffer || a.allocation < size) {
            if (a.buffer) SDL_ReleaseGPUTransferBuffer(dev,a.buffer);
            const SDL_GPUTransferBufferCreateInfo info{SDL_GPU_TRANSFERBUFFERUSAGE_DOWNLOAD,size,0};
            a.buffer = SDL_CreateGPUTransferBuffer(dev,&info);
            if (!a.buffer) return;
            a.allocation = size;
        }
        auto *cmd = acquire_commands();
        auto *copy = SDL_BeginGPUCopyPass(cmd);
        SDL_GPUTextureRegion src{};
        src.texture = texture; src.x = x; src.y = y; src.w = uint32_t(w); src.h = uint32_t(h); src.d = 1;
        const SDL_GPUTextureTransferInfo dst{a.buffer,0,uint32_t(w),uint32_t(h)};
        SDL_DownloadFromGPUTexture(copy,&src,&dst);
        SDL_EndGPUCopyPass(copy);
        a.fence = SDL_SubmitGPUCommandBufferAndAcquireFence(cmd);
        if (!a.fence) return;
        a.tick = tick; a.ticks_ns = SDL_GetTicksNS(); a.pose = pose; a.middle = middle;
        a.w = uint32_t(w); a.h = uint32_t(h);
        ++count;
    }
} trial_audit;
