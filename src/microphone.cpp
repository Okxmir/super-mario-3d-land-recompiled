#include "hle/service.h"

namespace hle {
namespace {

// The game's microphone session can operate without a host capture device.
// Keep the shared block alive and leave its write position unchanged.
class Microphone final : public Service {
public:
    Microphone() : Service("mic:u") {}

    void handle(Request &request) override {
        switch (request.id()) {
        case 0x0001: { // MapSharedMem
            auto block = kernel::get<kernel::SharedMemory>(request.in[3]);
            if (!block) {
                request.reply(1, 0, kernel::RESULT_INVALID_HANDLE);
                return;
            }
            const uint32_t size = request.arg(0);
            if (size < sizeof(uint32_t) || size > block->size) {
                request.reply(1, 0, kernel::RESULT_INVALID_COMBINATION);
                return;
            }
            shared_memory = std::move(block);
            shared_size = size;
            break;
        }
        case 0x0002: // UnmapSharedMem
            sampling = false;
            shared_memory.reset();
            shared_size = 0;
            break;
        case 0x0003: { // StartSampling
            const uint32_t offset = request.arg(2);
            const uint32_t size = request.arg(3);
            if (!shared_memory || uint64_t(offset) + size > shared_size - sizeof(uint32_t)) {
                request.reply(1, 0, kernel::RESULT_INVALID_COMBINATION);
                return;
            }
            sampling = true;
            break;
        }
        case 0x0004: // AdjustSampling
            break;
        case 0x0005: // StopSampling
            sampling = false;
            break;
        case 0x0006: // IsSampling
            request.reply(2, 0).push(sampling);
            return;
        case 0x0007: // GetBufferFullEvent
            request.reply(1, 2).push_handles({kernel::add_handle(buffer_full)});
            return;
        case 0x0008: // SetGain
            gain = uint8_t(request.arg(0));
            break;
        case 0x0009: // GetGain
            request.reply(2, 0).push(gain);
            return;
        case 0x000a: // SetPower
            power = request.arg(0) != 0;
            break;
        case 0x000b: // GetPower
            request.reply(2, 0).push(power);
            return;
        case 0x000d: // SetClamp
            clamp = request.arg(0) != 0;
            break;
        case 0x000e: // GetClamp
            request.reply(2, 0).push(clamp);
            return;
        case 0x000f: // SetAllowShellClosed
        case 0x0010: // SetClientVersion
            break;
        default:
            unimplemented(*this, request);
        }
        request.reply(1, 0);
    }

private:
    std::shared_ptr<kernel::SharedMemory> shared_memory;
    uint32_t shared_size = 0;
    std::shared_ptr<kernel::Event> buffer_full =
        std::make_shared<kernel::Event>(kernel::ResetType::OneShot, "Mic buffer full");
    uint8_t gain = 0;
    bool sampling = false;
    bool power = false;
    bool clamp = false;
};

} // namespace

void register_microphone() {
    register_service({"mic:u"}, std::make_shared<Microphone>());
}

} // namespace hle
