// Included by the Vulkan renderer with its LCD buffers and submission helpers in scope.
struct LcdSmoother {
    SDL_GPUGraphicsPipeline *estimate = nullptr, *interpolate = nullptr;
    SDL_GPUTexture *scores = nullptr;
    SDL_GPUTexture *outputs[3]{};
    SDL_GPUTexture *previous = nullptr;
    uint32_t previous_address = 0;
    uint64_t previous_tick = 0;
    int width = 0, height = 0, next = 0;
    bool initialized = false, ready = false, original_pending = false;

    SDL_GPUGraphicsPipeline *create_pipeline(SDL_GPUShader *vertex_shader, const unsigned char *code, size_t length) {
        SDL_GPUShader *shader = make_shader(code, length, SDL_GPU_SHADERSTAGE_FRAGMENT, 2, 0);
        if (!shader) return nullptr;
        SDL_GPUColorTargetDescription color{};
        color.format = SDL_GPU_TEXTUREFORMAT_R8G8B8A8_UNORM;
        SDL_GPUGraphicsPipelineCreateInfo info{};
        info.vertex_shader = vertex_shader;
        info.fragment_shader = shader;
        info.primitive_type = SDL_GPU_PRIMITIVETYPE_TRIANGLELIST;
        info.target_info.color_target_descriptions = &color;
        info.target_info.num_color_targets = 1;
        auto *pipeline = SDL_CreateGPUGraphicsPipeline(dev, &info);
        SDL_ReleaseGPUShader(dev, shader);
        return pipeline;
    }

    bool initialize() {
        if (initialized) return ready;
        initialized = true;
        estimate = create_pipeline(vs_full, sm3dl_estimate, sizeof sm3dl_estimate);
        auto *screen_vertex = make_shader(sm3dl_screen_motion, sizeof sm3dl_screen_motion, SDL_GPU_SHADERSTAGE_VERTEX, 1, 0);
        if (screen_vertex) {
            interpolate = create_pipeline(screen_vertex, sm3dl_interpolate, sizeof sm3dl_interpolate);
            SDL_ReleaseGPUShader(dev, screen_vertex);
        }
        if (!estimate || !interpolate) {
            LOG("graphics: motion smoothing unavailable (%s)", SDL_GetError());
            for (auto *pipeline : {estimate, interpolate})
                if (pipeline) SDL_ReleaseGPUGraphicsPipeline(dev, pipeline);
            return false;
        }
        // The score texture has one slot for each half-frame shift from -4 to +4.
        scores = create_target(9, 9);
        return ready = scores != nullptr;
    }

    SDL_GPUTexture *create_target(int w, int h) {
        SDL_GPUTextureCreateInfo info{};
        info.type = SDL_GPU_TEXTURETYPE_2D;
        info.format = SDL_GPU_TEXTUREFORMAT_R8G8B8A8_UNORM;
        info.usage = SDL_GPU_TEXTUREUSAGE_COLOR_TARGET | SDL_GPU_TEXTUREUSAGE_SAMPLER;
        info.width = w;
        info.height = h;
        info.layer_count_or_depth = 1;
        info.num_levels = 1;
        auto *texture = SDL_CreateGPUTexture(dev, &info);
        if (!texture) LOG("graphics: could not allocate motion smoothing texture (%s)", SDL_GetError());
        return texture;
    }

    bool resize(int w, int h) {
        if (width == w && height == h) return true;
        for (auto *texture : outputs)
            if (texture) retired_scanouts.push_back(texture);
        for (auto *&texture : outputs) texture = nullptr;
        for (auto *&texture : outputs) {
            texture = create_target(w, h);
            if (!texture) {
                for (auto *&allocated : outputs) {
                    if (allocated) SDL_ReleaseGPUTexture(dev, allocated);
                    allocated = nullptr;
                }
                return ready = false;
            }
        }
        width = w;
        height = h;
        next = 0;
        return true;
    }

    SDL_GPUTexture *render(SDL_GPUTexture *before, SDL_GPUTexture *after, int w, int h) {
        if (!initialize() || !resize(w, h)) return nullptr;
        auto *cmd = acquire_commands();
        auto *output = outputs[next];
        next = (next + 1) % 3;
        SDL_GPUTextureSamplerBinding frames[]{{before, linear_clamp}, {after, linear_clamp}};
        SDL_GPUTextureSamplerBinding candidates{scores, nearest_clamp};
        auto render_pass = [&](SDL_GPUTexture *target, SDL_GPUGraphicsPipeline *pipeline) {
            SDL_GPUColorTargetInfo color{};
            color.texture = target;
            color.load_op = SDL_GPU_LOADOP_DONT_CARE;
            color.store_op = SDL_GPU_STOREOP_STORE;
            auto *pass = SDL_BeginGPURenderPass(cmd, &color, 1, nullptr);
            SDL_BindGPUGraphicsPipeline(pass, pipeline);
            if (pipeline == interpolate) SDL_BindGPUVertexSamplers(pass, 0, &candidates, 1);
            SDL_BindGPUFragmentSamplers(pass, 0, frames, 2);
            SDL_DrawGPUPrimitives(pass, 3, 1, 0, 0);
            SDL_EndGPURenderPass(pass);
        };
        render_pass(scores, estimate);
        render_pass(output, interpolate);
        submit_commands(cmd);
        return output;
    }
};
