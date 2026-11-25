// Included in the Vulkan renderer, after the device and error helper.
// SDL command buffers must be submitted on the thread that acquired them.
struct ListCommands {
    SDL_GPUCommandBuffer *buffer = nullptr;
    unsigned batches = 0;
    uint64_t transient_uploads = 0;
    bool recording = false;
};
thread_local ListCommands list_commands;

SDL_GPUCommandBuffer *acquire_commands() {
    auto &list = list_commands;
    if (list.recording && list.buffer) return list.buffer;
    auto *cmd = SDL_AcquireGPUCommandBuffer(dev);
    if (!cmd) gpu_failure("command acquisition");
    if (list.recording) list.buffer = cmd;
    return cmd;
}

void submit_now(SDL_GPUCommandBuffer *cmd, uint64_t transient_uploads = 0) {
    // Checkpoint the queue periodically even if the window is in a menu or
    // minimized. Retire finished work without sleeping the guest render thread.
    // A bounded backlog is still needed for resource lifetime and input latency.
    static std::mutex lock;
    struct Checkpoint {
        SDL_GPUFence *fence;
        uint64_t upload_bytes;
    };
    static std::deque<Checkpoint> fences;
    static unsigned submissions = 0;
    static uint64_t pending_uploads = 0, untracked_uploads = 0;
    constexpr unsigned checkpoint = 12, max_checkpoints = 4;
    constexpr uint64_t upload_checkpoint = 16ull << 20, upload_limit = 128ull << 20;
    static const bool trace = std::getenv("SM3DL_FPS") != nullptr;
    std::lock_guard guard(lock);
    const auto start = trace ? now_ns() : 0;
    int64_t queued = 0;
    pending_uploads += transient_uploads;
    untracked_uploads += transient_uploads;
    if (++submissions == checkpoint || untracked_uploads >= upload_checkpoint ||
        pending_uploads > upload_limit) {
        submissions = 0;
        auto *fence = SDL_SubmitGPUCommandBufferAndAcquireFence(cmd);
        if (!fence) gpu_failure("command submission");
        if (trace) queued = now_ns();
        fences.push_back({fence, untracked_uploads});
        untracked_uploads = 0;
        const auto retire_front = [&] {
            pending_uploads -= fences.front().upload_bytes;
            SDL_ReleaseGPUFence(dev, fences.front().fence);
            fences.pop_front();
        };
        size_t ready = 0;
        while (ready < fences.size() && SDL_QueryGPUFence(dev, fences[ready].fence)) ++ready;
        if (ready) {
            // The query doesn't reclaim SDL's command buffers. Calling Wait on
            // a signaled fence performs that cleanup without waiting for GPU work.
            auto *complete = fences[ready - 1].fence;
            if (!SDL_WaitForGPUFences(dev, true, &complete, 1)) gpu_failure("command cleanup");
            for (; ready > 0; --ready) retire_front();
        }
        while (fences.size() >= max_checkpoints || pending_uploads > upload_limit) {
            auto *oldest = fences.front().fence;
            if (!SDL_WaitForGPUFences(dev, true, &oldest, 1)) gpu_failure("command retirement");
            retire_front();
        }
    } else if (!SDL_SubmitGPUCommandBuffer(cmd)) {
        gpu_failure("command submission");
    }
    if (trace) {
        const auto end = now_ns();
        if (!queued) queued = end;
        if (end - start >= 8'000'000)
            LOG("vulkan submit: enqueue %.1f ms, retirement %.1f ms", (queued - start) / 1e6, (end - queued) / 1e6);
    }
}

void submit_recorded_commands() {
    auto &list = list_commands;
    if (list.buffer) submit_now(list.buffer, list.transient_uploads);
    list.buffer = nullptr;
    list.batches = 0;
    list.transient_uploads = 0;
}

void submit_commands(SDL_GPUCommandBuffer *cmd, uint64_t transient_uploads = 0) {
    auto &list = list_commands;
    if (!list.recording || cmd != list.buffer) {
        submit_now(cmd, transient_uploads);
        return;
    }
    // Each batch keeps its original passes, resources and order. Limit the
    // amount of recorded work so an unusually long PICA list stays bounded.
    list.transient_uploads += transient_uploads;
    if (++list.batches >= 8 || list.transient_uploads >= (32ull << 20)) submit_recorded_commands();
}
