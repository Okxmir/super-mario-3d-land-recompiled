// Included in the Vulkan renderer, after the device and error helper.
// SDL command buffers must be submitted on the thread that acquired them.
struct ListCommands {
    SDL_GPUCommandBuffer *buffer = nullptr;
    unsigned batches = 0;
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

void submit_now(SDL_GPUCommandBuffer *cmd) {
    // Checkpoint the queue periodically even if the window is in a menu or
    // minimized. Retire finished work without sleeping the guest render thread.
    // A bounded backlog is still needed for resource lifetime and input latency.
    static std::mutex lock;
    static std::deque<SDL_GPUFence *> fences;
    static unsigned submissions = 0;
    constexpr unsigned checkpoint = 12, max_checkpoints = 4;
    static const bool trace = std::getenv("SM3DL_FPS") != nullptr;
    std::lock_guard guard(lock);
    const auto start = trace ? now_ns() : 0;
    int64_t queued = 0;
    if (++submissions == checkpoint) {
        submissions = 0;
        auto *fence = SDL_SubmitGPUCommandBufferAndAcquireFence(cmd);
        if (!fence) gpu_failure("command submission");
        if (trace) queued = now_ns();
        fences.push_back(fence);
        size_t ready = 0;
        while (ready < fences.size() && SDL_QueryGPUFence(dev, fences[ready])) ++ready;
        if (ready) {
            // The query doesn't reclaim SDL's command buffers. Calling Wait on
            // a signaled fence performs that cleanup without waiting for GPU work.
            auto *complete = fences[ready - 1];
            if (!SDL_WaitForGPUFences(dev, true, &complete, 1)) gpu_failure("command cleanup");
            for (; ready > 0; --ready) {
                SDL_ReleaseGPUFence(dev, fences.front());
                fences.pop_front();
            }
        }
        if (fences.size() >= max_checkpoints) {
            auto *oldest = fences.front();
            if (!SDL_WaitForGPUFences(dev, true, &oldest, 1)) gpu_failure("command retirement");
            SDL_ReleaseGPUFence(dev, oldest);
            fences.pop_front();
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
    if (list.buffer) submit_now(list.buffer);
    list.buffer = nullptr;
    list.batches = 0;
}

void submit_commands(SDL_GPUCommandBuffer *cmd) {
    auto &list = list_commands;
    if (!list.recording || cmd != list.buffer) {
        submit_now(cmd);
        return;
    }
    // Each batch keeps its original passes, resources and order. Limit the
    // amount of recorded work so an unusually long PICA list stays bounded.
    if (++list.batches >= 8) submit_recorded_commands();
}
