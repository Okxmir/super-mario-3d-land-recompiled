// Local StreetPass mailboxes. The daemon stays idle and exchanges no messages.
#include "hle/service.h"
#include "memory.h"
#include "platform.h"

#include <cstdio>
#include <filesystem>
#include <fstream>
#include <system_error>

namespace hle {
namespace {
namespace fs = std::filesystem;

constexpr uint32_t not_found = 0xc880bbfa;
constexpr uint32_t read_mode = 2;
constexpr uint32_t write_mode = 4;
constexpr uint32_t create_directory_mode = 8;

fs::path mailbox_path(uint32_t title, uint32_t type) {
    const auto root = platform::state_dir() / "cec";
    char name[9];
    std::snprintf(name, sizeof name, "%08x", title);
    const auto mailbox = root / name;
    switch (type) {
    case 1: return root / "MBoxList";
    case 2: return mailbox / "MBoxInfo";
    case 3: return mailbox / "InBox" / "BoxInfo";
    case 4: return mailbox / "OutBox" / "BoxInfo";
    case 5: return mailbox / "OutBox" / "OBIndex";
    case 10: return root;
    case 11: return mailbox;
    case 12: return mailbox / "InBox";
    case 13: return mailbox / "OutBox";
    default:
        if (type >= 101 && type <= 199) return mailbox / ("MBoxData." + std::to_string(type - 100));
        return {};
    }
}

bool open_file(std::fstream &file, const fs::path &path, uint32_t flags, uint32_t *size,
               bool truncate = false) {
    if (path.empty() || !(flags & (read_mode | write_mode))) return false;
    std::error_code error;
    if (flags & write_mode) {
        fs::create_directories(path.parent_path(), error);
        if (error) return false;
        if (!fs::exists(path, error)) {
            std::ofstream create(path, std::ios::binary);
            if (!create) return false;
        }
    }
    if (!fs::is_regular_file(path, error)) return false;
    const auto length = fs::file_size(path, error);
    if (error || length > UINT32_MAX) return false;
    auto mode = std::ios::binary | std::ios::in;
    if (flags & write_mode) mode |= std::ios::out;
    if (truncate) mode |= std::ios::trunc;
    file.open(path, mode);
    *size = static_cast<uint32_t>(length);
    return bool(file);
}

struct Cecd : Service {
    std::shared_ptr<kernel::Event> info = std::make_shared<kernel::Event>(kernel::ResetType::OneShot, "CECD info");
    std::shared_ptr<kernel::Event> change = std::make_shared<kernel::Event>(kernel::ResetType::OneShot, "CECD state");
    std::fstream active;
    uint32_t active_flags = 0;

    Cecd() : Service("cecd") {}

    void handle(Request &req) override {
        switch (req.id()) {
        case 0x0001: { // Open(title, path type, flags, pid) -> size
            const auto path = mailbox_path(req.arg(0), req.arg(1));
            const uint32_t flags = req.arg(2);
            if (active.is_open()) active.close();
            active.clear();
            active_flags = 0;
            uint32_t size = 0;
            bool opened = false;
            if (!path.empty() && req.arg(1) >= 10 && req.arg(1) <= 13) {
                std::error_code error;
                if (flags & create_directory_mode) fs::create_directories(path, error);
                opened = !error && fs::is_directory(path, error);
            } else {
                opened = open_file(active, path, flags, &size);
                if (opened) active_flags = flags;
            }
            auto reply = req.reply(2, 0, opened ? 0 : not_found);
            reply.push(size);
            break;
        }
        case 0x0002: { // Read(size, mapped buffer) -> bytes read
            const uint32_t length = req.arg(0), buffer = req.arg(2);
            if (!(active_flags & read_mode)) {
                req.reply(1, 0, not_found);
                break;
            }
            active.read(reinterpret_cast<char *>(mem::ptr(buffer)), length);
            auto reply = req.reply(2, 2);
            reply.push(uint32_t(active.gcount()));
            reply.push(req.arg(1));
            reply.push(buffer);
            break;
        }
        case 0x0005: { // Write(size, mapped buffer)
            const uint32_t length = req.arg(0), buffer = req.arg(2);
            if (!(active_flags & write_mode) ||
                !active.write(reinterpret_cast<const char *>(mem::ptr(buffer)), length).flush()) {
                req.reply(1, 0, not_found);
                break;
            }
            auto reply = req.reply(1, 2);
            reply.push(req.arg(1));
            reply.push(buffer);
            break;
        }
        case 0x0008: { // Delete(title, path type, box, message id)
            const auto path = mailbox_path(req.arg(0), req.arg(1));
            std::error_code error;
            if (!path.empty() && req.arg(1) != 10) fs::remove(path, error);
            auto reply = req.reply(1, 2, error ? not_found : 0);
            reply.push(req.arg(4));
            reply.push(req.arg(5));
            break;
        }
        case 0x0009: { // SetData(title, buffer size, option, mapped buffer)
            const uint32_t length = req.arg(1), option = req.arg(2), buffer = req.arg(4);
            if (option == 2 && length) {
                std::fstream file;
                uint32_t size = 0;
                if (!open_file(file, mailbox_path(req.arg(0), 5), write_mode, &size, true) ||
                    !file.write(reinterpret_cast<const char *>(mem::ptr(buffer)), length).flush()) {
                    req.reply(1, 0, not_found);
                    break;
                }
            }
            // The offline daemon has no received messages to update.
            auto reply = req.reply(1, 2);
            reply.push(req.arg(3));
            reply.push(buffer);
            break;
        }
        case 0x000b: // Start
        case 0x000c: // Stop
            req.reply(1, 0);
            break;
        case 0x000e: { // GetCecStateAbbreviated: idle
            auto reply = req.reply(2, 0);
            reply.push(1);
            break;
        }
        case 0x000f:
        case 0x0010: {
            auto reply = req.reply(1, 2);
            reply.push_handles({kernel::add_handle(req.id() == 0x000f ? info : change)});
            break;
        }
        case 0x0011:
        case 0x0012: {
            const bool write = req.id() == 0x0011;
            const uint32_t length = req.arg(0), buffer = req.arg(7);
            const auto path = mailbox_path(req.arg(1), req.arg(2));
            std::fstream file;
            uint32_t size = 0;
            if (!open_file(file, path, write ? write_mode : read_mode, &size, write)) {
                req.reply(1, 0, not_found);
                break;
            }
            if (write) {
                if (!file.write(reinterpret_cast<const char *>(mem::ptr(buffer)), length).flush()) {
                    req.reply(1, 0, not_found);
                    break;
                }
            } else {
                file.read(reinterpret_cast<char *>(mem::ptr(buffer)), length);
            }
            auto reply = req.reply(write ? 1 : 2, 2);
            if (!write) reply.push(uint32_t(file.gcount()));
            reply.push(req.arg(6));
            reply.push(buffer);
            break;
        }
        default:
            unimplemented(*this, req);
        }
    }
};
} // namespace

void register_cecd() { register_service({"cecd:u", "cecd:s"}, std::make_shared<Cecd>()); }
} // namespace hle
