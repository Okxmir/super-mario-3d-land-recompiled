#include "hle/service.h"
#include "log.h"
#include "memory.h"
#include "platform.h"

#ifdef _WIN32
#include <windows.h>
#include <bcrypt.h>
#else
#include <openssl/evp.h>
#endif

#include <algorithm>
#include <array>
#include <cstdio>
#include <span>
#include <vector>

namespace hle {
namespace {

using Key = std::array<uint8_t, 16>;
using Nonce = std::array<uint8_t, 12>;
using Tag = std::array<uint8_t, 16>;

bool crypt_ccm(bool encrypt, Key key, Nonce nonce, Tag &tag, std::span<uint8_t> input,
               std::span<uint8_t> output) {
#ifdef _WIN32
    BCRYPT_ALG_HANDLE algorithm = nullptr;
    if (BCryptOpenAlgorithmProvider(&algorithm, BCRYPT_AES_ALGORITHM, nullptr, 0) < 0) return false;
    BCRYPT_KEY_HANDLE handle = nullptr;
    wchar_t mode[] = BCRYPT_CHAIN_MODE_CCM;
    bool ok = BCryptSetProperty(algorithm, BCRYPT_CHAINING_MODE, reinterpret_cast<PUCHAR>(mode),
                                 sizeof mode, 0) >= 0 &&
              BCryptGenerateSymmetricKey(algorithm, &handle, nullptr, 0, key.data(), key.size(), 0) >= 0;
    if (ok) {
        BCRYPT_AUTHENTICATED_CIPHER_MODE_INFO info;
        BCRYPT_INIT_AUTH_MODE_INFO(info);
        info.pbNonce = nonce.data();
        info.cbNonce = nonce.size();
        info.pbTag = tag.data();
        info.cbTag = tag.size();
        ULONG written = 0;
        auto crypt = encrypt ? BCryptEncrypt : BCryptDecrypt;
        ok = crypt(handle, input.data(), ULONG(input.size()), &info, nullptr, 0,
                   output.data(), ULONG(output.size()), &written, 0) >= 0 && written == input.size();
    }
    if (handle) BCryptDestroyKey(handle);
    BCryptCloseAlgorithmProvider(algorithm, 0);
    return ok;
#else
    const std::unique_ptr<EVP_CIPHER_CTX, decltype(&EVP_CIPHER_CTX_free)> ctx(
        EVP_CIPHER_CTX_new(), EVP_CIPHER_CTX_free);
    int written = 0;
    const int size = int(input.size());
    if (!ctx || EVP_CipherInit_ex(ctx.get(), EVP_aes_128_ccm(), nullptr, nullptr, nullptr, encrypt) != 1 ||
        EVP_CIPHER_CTX_ctrl(ctx.get(), EVP_CTRL_AEAD_SET_IVLEN, nonce.size(), nullptr) != 1 ||
        EVP_CIPHER_CTX_ctrl(ctx.get(), EVP_CTRL_AEAD_SET_TAG, tag.size(), encrypt ? nullptr : tag.data()) != 1 ||
        EVP_CipherInit_ex(ctx.get(), nullptr, nullptr, key.data(), nonce.data(), encrypt) != 1 ||
        EVP_CipherUpdate(ctx.get(), nullptr, &written, nullptr, size) != 1 ||
        EVP_CipherUpdate(ctx.get(), output.data(), &written, input.data(), size) != 1 || written != size)
        return false;
    if (!encrypt) return true;
    return EVP_CipherFinal_ex(ctx.get(), output.data() + written, &written) == 1 && written == 0 &&
           EVP_CIPHER_CTX_ctrl(ctx.get(), EVP_CTRL_AEAD_GET_TAG, tag.size(), tag.data()) == 1;
#endif
}

bool transform(bool wrap, const Key &key, size_t offset, size_t nonce_size,
               std::span<const uint8_t> input, std::span<uint8_t> output) {
    Nonce nonce{};
    Tag tag{};
    // The 3DS rounds the nonce length down to a multiple of four and pads it to 12 bytes.
    nonce_size = std::min(nonce_size & ~size_t{3}, nonce.size());
    const size_t plain_size = wrap ? input.size() : output.size();
    const size_t wrapped_size = wrap ? output.size() : input.size();
    if (wrapped_size < tag.size() || wrapped_size - tag.size() != plain_size ||
        offset > plain_size || nonce_size > plain_size - offset ||
        plain_size - nonce_size >= (1u << 24))
        return false;

    const size_t payload_size = plain_size - nonce_size;
    // Keep valid pointers for the crypto providers even for an empty payload.
    std::vector<uint8_t> data(std::max<size_t>(payload_size, 1)), result(data.size());
    if (wrap) {
        std::copy_n(input.begin() + offset, nonce_size, nonce.begin());
        std::copy_n(input.begin(), offset, data.begin());
        std::copy(input.begin() + offset + nonce_size, input.end(), data.begin() + offset);
    } else {
        std::copy_n(input.begin(), nonce_size, nonce.begin());
        std::copy_n(input.begin() + nonce_size, payload_size, data.begin());
        std::copy_n(input.end() - tag.size(), tag.size(), tag.begin());
    }
    if (!crypt_ccm(wrap, key, nonce, tag, std::span(data).first(payload_size),
                   std::span(result).first(payload_size)))
        return false;

    if (wrap) {
        std::copy_n(nonce.begin(), nonce_size, output.begin());
        std::copy_n(result.begin(), payload_size, output.begin() + nonce_size);
        std::copy(tag.begin(), tag.end(), output.end() - tag.size());
    } else {
        std::copy_n(result.begin(), offset, output.begin());
        std::copy_n(nonce.begin(), nonce_size, output.begin() + offset);
        std::copy_n(result.begin() + offset, payload_size - offset, output.begin() + offset + nonce_size);
    }
    return true;
}

bool mapped_range(uint32_t address, uint32_t size) {
    const uint64_t end = uint64_t(address) + size;
    if (end > (uint64_t{1} << 32)) return false;
    for (uint64_t page = mem::page_down(address); page < end; page += mem::PAGE) {
        if (!mem::is_committed(uint32_t(page))) return false;
    }
    return true;
}

Key mailbox_key() {
    // The PC mailbox is local to this runtime. Derive a stable key from the
    // saved virtual console identity so its own messages survive restarts.
    Key key{'S', 'M', '3', 'D', 'L', 'A', 'P', 'T'};
    const auto id = platform::console_id();
    for (unsigned i = 0; i < 8; ++i) key[8 + i] = uint8_t(id >> (8 * i));
    return key;
}

} // namespace

void reply_apt_wrap(Request &req) {
    constexpr uint32_t invalid = kernel::RESULT_INVALID_COMBINATION;
    const bool wrap = req.id() == 0x0046;
    if (req.header() != (wrap ? 0x00460104u : 0x00470104u)) {
        req.reply(1, 0, invalid);
        return;
    }
    const auto output_size = req.arg(0), input_size = req.arg(1);
    const auto input_descriptor = req.arg(4), output_descriptor = req.arg(6);
    const auto input_address = req.arg(5), output_address = req.arg(7);
    bool ok = (input_descriptor & 15) == 0xA && (output_descriptor & 15) == 0xC &&
              (input_descriptor >> 4) == input_size && (output_descriptor >> 4) == output_size &&
              mapped_range(input_address, input_size) && mapped_range(output_address, output_size) &&
              transform(wrap, mailbox_key(), req.arg(2), req.arg(3),
                        {mem::ptr(input_address), input_size}, {mem::ptr(output_address), output_size});
    auto response = req.reply(1, 4, ok ? kernel::RESULT_OK : invalid);
    response.push(input_descriptor);
    response.push(input_address);
    response.push(output_descriptor);
    response.push(output_address);
    LOG_IPC("APT %s %u bytes -> %u bytes (%s)", wrap ? "Wrap" : "Unwrap", input_size, output_size,
            ok ? "OK" : "invalid data");
}

int verify_apt_wrap() {
    // The Mystery Box uses a 0x60-byte payload and requests a 10-byte nonce at 0x0C.
    const Key key{};
    std::array<uint8_t, 0x60> input{}, decoded{};
    std::array<uint8_t, 0x70> wrapped{};
    for (size_t i = 0; i < input.size(); ++i) input[i] = uint8_t(i);
    if (!transform(true, key, 12, 10, input, wrapped) ||
        !std::equal(wrapped.begin(), wrapped.begin() + 8, input.begin() + 12) ||
        !transform(false, key, 12, 10, wrapped, decoded) || decoded != input)
        return 1;
    wrapped.back() ^= 1;
    decoded.fill(0);
    if (transform(false, key, 12, 10, wrapped, decoded) ||
        std::any_of(decoded.begin(), decoded.end(), [](uint8_t b) { return b != 0; }) ||
        transform(true, key, input.size(), 10, input, wrapped))
        return 1;
    std::puts("APT Wrap and Unwrap verified for the Mystery Box payload, including invalid data.");
    return 0;
}

} // namespace hle
