#include <algorithm>
#include <cstdint>
#include <string_view>
#include <vector>

namespace hle {

// A local default profile for the library applet. Layout follows the 3DS
// Mii Selector result format and libctru's CFLStoreData definition.
std::vector<uint8_t> local_mii_selection() {
    std::vector<uint8_t> reply(0x84);
    std::fill_n(reply.begin() + 8, 4, uint8_t{0xff}); // No guest Mii index.
    auto *mii = reply.data() + 0x0c;
    const auto put = [mii](size_t offset, uint32_t value, unsigned bytes) {
        for (unsigned i = 0; i < bytes; ++i)
            mii[offset + i] = uint8_t(value >> (8 * i));
    };
    mii[0] = 3;    // Format version.
    mii[3] = 0x30; // Nintendo 3DS origin.
    put(4, 0x4c443300, 4);
    put(12, 0x10000001, 4);
    mii[16] = 2;   // Locally administered origin identifier.
    mii[0x2e] = 64;
    mii[0x2f] = 64;
    mii[0x30] = 1; // Keep the profile local.
    mii[0x32] = 9;
    mii[0x33] = 1;
    constexpr std::string_view name = "Player";
    for (size_t i = 0; i < name.size(); ++i)
        mii[0x1a + i * 2] = uint8_t(name[i]);
    put(0x34, 2u | (4u << 9) | (4u << 21) | (10u << 25), 4); // Eyes.
    put(0x38, 3u | (4u << 8) | (4u << 20) | (7u << 24), 4);  // Eyebrows.
    put(0x3c, 1u | (4u << 5) | (9u << 9), 2);                 // Nose.
    put(0x3e, 2u | (4u << 9), 2);                             // Mouth.
    mii[0x40] = 14;                                          // Mouth position.

    uint16_t crc = 0;
    for (size_t i = 0; i < 0x5e; ++i) {
        crc = uint16_t(crc ^ (uint16_t(mii[i]) << 8));
        for (int bit = 0; bit < 8; ++bit)
            crc = uint16_t((crc << 1) ^ (crc & 0x8000 ? 0x1021 : 0));
    }
    mii[0x5e] = uint8_t(crc >> 8);
    mii[0x5f] = uint8_t(crc);
    return reply;
}

} // namespace hle
