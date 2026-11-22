"""Relocate the exact 0.2-preview IPS to the supported European ARM image.

Use the upstream IPS and the player's verified decrypted European code.
The input ROM stays unchanged. All generated code remains local.
"""

import argparse
import hashlib
from pathlib import Path
import struct


BASE = 0x100000
CAVE = 0x3a177c
CAVE_INSTRUCTIONS = 0x3a1f84 - CAVE
STATE = 0x432000
GLOVE = 0x224ae0
GLOVE_SIZE = 168
GLOVE_EUR = 0x473000
BSS_SIZE = 0x7e684
CODE_HASH = 'e1d7e188ff88467df776c17cec45c44857fadf5b699944baa8cddcae7d939e64'
IPS_HASH = '6cdc315748eb2eb1461ed5447bb9fdb65b195d49f4237bd760bbf5166bd2004f'
HOOKS = {
    0x11abf8: (0x11abfc, 0xe5900008),
    0x129064: (0x12906c, 0xea0524eb),
    0x129350: (0x129358, 0xea052430),
    0x13e21c: (0x13e224, 0xe3a01000),
    0x162e80: (0x162e88, 0xe3550000),
    0x1dcba0: (0x1dcba8, 0xe92d41f0),
    0x224ae0: (0x224ae8, 0xed2d8b02),
    0x265b88: (0x265b90, 0xe52de004),
    0x29d9c8: (0x29d9d0, 0xe284bf6f),
    0x2a0404: (0x2a040c, 0xe2840f6f),
    0x2a073c: (0x2a0744, 0xe92d4ff0),
    0x2afd24: (0x2afd2c, 0xe2840f6f),
    0x3187b4: (0x3187bc, 0xe92d4070),
    0x3358c0: (0x3358c8, 0xe2861f6f),
}


def parse(data):
    if hashlib.sha256(data).hexdigest() != IPS_HASH or data[:5] != b'PATCH':
        raise ValueError('Not the original Alon Boroda 0.2-preview IPS')
    i = 5
    while data[i:i + 3] != b'EOF':
        address = BASE + int.from_bytes(data[i:i + 3], 'big')
        length = int.from_bytes(data[i + 3:i + 5], 'big')
        i += 5
        if not length or i + length > len(data):
            raise ValueError('Unexpected IPS record encoding')
        yield address, data[i:i + length]
        i += length
    if i + 3 != len(data):
        raise ValueError('Unexpected IPS trailer')


def eur_pc(address):
    # The native port uses the European routine under this USA code cave.
    # Don't replace any of it. Keep the helper byte-for-byte except branches.
    if GLOVE <= address < GLOVE + GLOVE_SIZE:
        return GLOVE_EUR + address - GLOVE
    if address in (0x11abf8, 0x11abfc):
        return address + 4
    if BASE <= address < 0x3a2000:
        return address + 8
    raise ValueError(f'Unexpected executable branch: 0x{address:08x}')


def relocate(address, data):
    if address == STATE:
        return address, data
    result = bytearray(data)
    end = CAVE_INSTRUCTIONS if address == CAVE else len(data)
    for off in range(0, end, 4):
        (word,) = struct.unpack_from('<I', data, off)
        if (word & 0x0e000000) != 0x0a000000:
            continue
        if word >> 28 == 15:
            raise ValueError('Unexpected ARM BLX immediate in the original IPS')
        disp = word & 0xffffff
        if disp >= 0x800000:
            disp -= 0x1000000
        src = address + off
        target = src + 8 + disp * 4
        delta = eur_pc(target) - eur_pc(address) - off - 8
        if delta & 3 or not -(1 << 25) <= delta < (1 << 25):
            raise ValueError('ARM branch cannot be encoded after relocation')
        struct.pack_into('<I', result, off, (word & 0xff000000) | ((delta // 4) & 0xffffff))
    # Clockwork targets the 3DS-era VFP decoder and does not support these
    # VFP immediate encodings. Use a literal load of exactly the same IEEE
    # floats, with the same destination and no change to flags.
    replacements = {
        CAVE: ((0x3a1ed4 - CAVE, 0xeeb63a00, 6, 0x3f000000),
               (0x3a1f30 - CAVE, 0xeeb61a00, 2, 0x3f000000)),
        GLOVE: ((0x60, 0xeeb00a07, 0, 0x40380000),),
    }.get(address, ())
    literals = {}
    for off, expected, reg, bits in replacements:
        if struct.unpack_from('<I', result, off)[0] != expected:
            raise ValueError('Unexpected VFP immediate')
        if bits not in literals:
            literals[bits] = len(result)
            result.extend(struct.pack('<I', bits))
        delta = literals[bits] - off - 8
        if not 0 <= delta <= 1020 or delta & 3:
            raise ValueError('VFP constant outside literal range')
        vldr = 0xed9f0a00 | ((reg >> 1) << 12) | ((reg & 1) << 22) | (delta // 4)
        struct.pack_into('<I', result, off, vldr)
    return eur_pc(address), result


def build(ips, original, output, cpp):
    code = bytearray((original / 'code.bin').read_bytes())
    if hashlib.sha256(code).hexdigest() != CODE_HASH:
        raise ValueError('Unsupported European executable')
    for address, word in HOOKS.values():
        if struct.unpack_from('<I', code, address - BASE)[0] != word:
            raise ValueError(f'Unexpected original instruction at {address:#x}')
    patch = dict(parse(ips.read_bytes()))
    if patch.keys() != HOOKS.keys() | {CAVE, STATE} or len(patch[CAVE]) != 2136 or len(patch[STATE]) != 192:
        raise ValueError('Unexpected patch layout')
    records = [relocate(a, d) for a, d in patch.items()]
    if len(patch[GLOVE]) != GLOVE_SIZE:
        raise ValueError('Unexpected glove handle helper size')
    relocated = dict(records)
    code.extend(bytes(GLOVE_EUR + len(relocated[GLOVE_EUR]) - BASE - len(code)))
    for adr, payload in records:
        if adr != STATE:
            off = adr - BASE
            if adr == eur_pc(CAVE) and any(code[off:off + len(payload)]):
                raise ValueError('The code cave is occupied')
            code[off:off + len(payload)] = payload
    header = bytearray((original / 'exheader.bin').read_bytes())
    text_end = eur_pc(CAVE) + len(relocated[eur_pc(CAVE)])
    struct.pack_into('<I', header, 0x18, text_end - BASE)
    struct.pack_into('<I', header, 0x3c, BSS_SIZE)
    output.mkdir(parents=True, exist_ok=True)
    (output / 'code.bin').write_bytes(code)
    (output / 'exheader.bin').write_bytes(header)
    lines = ['// Generated from the unmodified upstream IPS.\n',
             'static void install_alon_eur_patch() {\n']
    for adr, payload in records:
        lines.append(f'    static constexpr uint8_t p_{adr:x}[] = {{\n')
        for i in range(0, len(payload), 16):
            lines.append('        ' + ', '.join(f'0x{b:02x}' for b in payload[i:i+16]) + ',\n')
        lines.append(f'    }};\n    std::memcpy(mem::ptr(0x{adr:08x}), p_{adr:x}, sizeof p_{adr:x});\n')
    lines.append('}\n')
    cpp.write_text(''.join(lines), encoding='ascii')
    print(f'Relocated {len(records)} IPS blocks for EUR; native ARM text ends at {text_end:#x}')


if __name__ == '__main__':
    arg = argparse.ArgumentParser(description=__doc__)
    for name in ('ips', 'original', 'output', 'cpp'):
        arg.add_argument(name, type=Path)
    args = arg.parse_args()
    build(args.ips, args.original, args.output, args.cpp)
