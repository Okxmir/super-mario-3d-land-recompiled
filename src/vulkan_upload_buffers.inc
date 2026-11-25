// Small, frequent uploads can cycle without inheriting the size of a rare HD
// upload. Large batches use exact-sized staging released after encoding.
struct UploadStaging {
    SDL_GPUTransferBuffer *buffer = nullptr;
    bool transient = false;
};

UploadStaging acquire_upload_staging(size_t bytes) {
    if (bytes > UINT32_MAX) return {};
    constexpr uint32_t bucket_sizes[] = {64u << 10, 256u << 10, 1u << 20};
    static SDL_GPUTransferBuffer *pools[std::size(bucket_sizes)]{};
    for (size_t i = 0; i < std::size(bucket_sizes); ++i) {
        if (bytes > bucket_sizes[i]) continue;
        auto *&pool = pools[i];
        if (!pool) {
            SDL_GPUTransferBufferCreateInfo info{SDL_GPU_TRANSFERBUFFERUSAGE_UPLOAD, bucket_sizes[i], 0};
            pool = SDL_CreateGPUTransferBuffer(dev, &info);
        }
        if (pool) return {pool, false};
        break; // try an exact-size allocation if even this pool failed
    }
    SDL_GPUTransferBufferCreateInfo info{SDL_GPU_TRANSFERBUFFERUSAGE_UPLOAD, uint32_t(bytes), 0};
    return {SDL_CreateGPUTransferBuffer(dev, &info), true};
}
