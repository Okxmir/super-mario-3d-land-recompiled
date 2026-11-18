"""Inspect an NCSD cartridge and extract its executable NCCH without modifying it."""

import argparse
import hashlib
import json
import os
import re
import struct
import sys
import tempfile
from pathlib import Path


ROM_TYPES = {".3ds", ".cci", ".cxi"}
REQUIRED_REGIONS = ("ExHeader", "ExeFS", "RomFS")
# Fingerprint of the full ExHeader in the supported European revision.
EUROPE_EXHEADER_SHA256 = bytes.fromhex("94e61359c80498495dd77bb2df16f0def6fca94fca736dc8c3c929279b44d2c8")
EUROPE_PACKED_CODE_SHA256 = bytes.fromhex("e56bb54f32d681dfe16f00355b9bcc374fff056767129944212d3566df3e2554")
EUROPE_CODE_SHA256 = bytes.fromhex("e1d7e188ff88467df776c17cec45c44857fadf5b699944baa8cddcae7d939e64")
EUROPE_CODE_SIZE = 0x2F4000


def u32(data, offset):
    return struct.unpack_from("<I", data, offset)[0]


def read_at(stream, offset, size):
    stream.seek(offset)
    data = stream.read(size)
    if len(data) != size:
        raise ValueError(f"Truncated input at {offset:#x} ({size:#x} bytes expected)")
    return data


def media_unit(exponent):
    if exponent > 8:
        raise ValueError(f"Unsupported media unit exponent {exponent}")
    return 512 << exponent


def check_ranges(ranges, limit, start=512):
    end = start
    for offset, size, name in sorted(ranges):
        if offset < end or size <= 0 or offset + size > limit:
            raise ValueError(f"Overlapping or out-of-range {name}: {offset:#x}+{size:#x}")
        end = offset + size


def read_partition(stream, offset, size, index):
    header = read_at(stream, offset, 512)
    if header[0x100:0x104] != b"NCCH":
        raise ValueError(f"Partition {index} has no NCCH header")
    unit = media_unit(header[0x18E])
    content_size = u32(header, 0x104) * unit
    if not 512 <= content_size <= size:
        raise ValueError(f"Invalid NCCH size in partition {index}")

    region_specs = (
        ("plain", 0x190, None, None),
        ("logo", 0x198, None, None),
        ("ExeFS", 0x1A0, 0x1C0, 2),
        ("RomFS", 0x1B0, 0x1E0, 3),
    )
    regions = {}
    exheader_size = u32(header, 0x180)
    if exheader_size:
        regions["ExHeader"] = (512, 2 * exheader_size, exheader_size, 0x160, 1)
    for name, field, digest_at, kind in region_specs:
        region_start, length = struct.unpack_from("<II", header, field)
        if length:
            hash_size = u32(header, field + 8) * unit if digest_at is not None else 0
            if hash_size > length * unit:
                raise ValueError(f"Invalid hash span for {name}")
            regions[name] = (region_start * unit, length * unit, hash_size, digest_at, kind)
    check_ranges([(off, size, name) for name, (off, size, *_) in regions.items()], content_size)
    return header, content_size, regions


def read_cartridge(stream, size):
    header = read_at(stream, 0, 512)
    if header[0x100:0x104] == b"NCCH":
        return "NCCH", [(0, size, 0)]
    if header[0x100:0x104] != b"NCSD":
        raise ValueError("Expected an NCSD cartridge (.3ds/.cci) or raw NCCH (.cxi)")
    unit = media_unit(header[0x18E])
    media_size = u32(header, 0x104) * unit
    partitions = []
    for index in range(8):
        offset, length = struct.unpack_from("<II", header, 0x120 + 8 * index)
        if offset or length:
            partitions.append((offset * unit, length * unit, index))
    check_ranges(partitions, min(size, media_size))
    if not partitions or partitions[0][2] != 0:
        raise ValueError("The cartridge has no primary partition")
    return "NCSD", partitions


def printable_ascii(data):
    return data.split(b"\0", 1)[0].decode("ascii", errors="replace")


def is_european_mario(header):
    return (printable_ascii(header[0x150:0x160]) == "CTR-P-AREP" and
            int.from_bytes(header[0x118:0x120], "little") == 0x0004000000053F00)


def can_repair_digest(stream, base, header, name, region):
    # Only replace the digest of the exact, known plaintext ExHeader.
    return (name == "ExHeader" and region == (512, 0x800, 0x400, 0x160, 1) and
            is_european_mario(header) and
            hashlib.sha256(read_at(stream, base + 512, 0x800)).digest() == EUROPE_EXHEADER_SHA256)


def region_digest(stream, base, region):
    offset, _, length, _, _ = region
    digest = hashlib.sha256()
    while length:
        block = read_at(stream, base + offset, min(length, 1024 * 1024))
        digest.update(block)
        offset += len(block)
        length -= len(block)
    return digest.digest()


def has_plain_exheader(stream, base, header, region):
    _, _, length, digest_at, _ = region
    return bool(length) and (region_digest(stream, base, region) == header[digest_at:digest_at + 32] or
                             can_repair_digest(stream, base, header, "ExHeader", region))


def unpack_code(image):
    # BLZ stores tokens backwards, with the size of the decoded code in its footer.
    if len(image) < 8:
        raise ValueError("Invalid compressed game code.")
    layout, extra = struct.unpack_from("<II", image, len(image) - 8)
    footer, region = layout >> 24, layout & 0xFFFFFF
    if not 8 <= footer <= region <= len(image):
        raise ValueError("Invalid compressed game code footer.")
    if len(image) + extra != EUROPE_CODE_SIZE:
        return b""
    decoded = bytearray(EUROPE_CODE_SIZE)
    decoded[:len(image)] = image
    src, stop, dst = len(image) - footer, len(image) - region, len(decoded)
    while src > stop:
        src -= 1
        controls = image[src]
        for bit in range(7, -1, -1):
            if src <= stop:
                break
            if controls & (1 << bit):
                if src - stop < 2:
                    raise ValueError("Truncated compressed game code.")
                src -= 2
                pair = image[src] | (image[src + 1] << 8)
                count, distance = (pair >> 12) + 3, (pair & 0xFFF) + 2
                if dst - count < stop or dst + distance >= len(decoded):
                    raise ValueError("Invalid reference in compressed game code.")
                for _ in range(count):
                    decoded[dst - 1] = decoded[dst + distance]
                    dst -= 1
            else:
                src -= 1
                dst -= 1
                if dst < stop:
                    raise ValueError("Invalid length in compressed game code.")
                decoded[dst] = image[src]
    if dst != stop:
        raise ValueError("Incomplete compressed game code.")
    return decoded


def verify_supported_code(stream, base, regions):
    exefs, size, *_ = regions["ExeFS"]
    if size < 512:
        raise ValueError("The ROM has an invalid ExeFS header.")
    directory = read_at(stream, base + exefs, 512)
    for index in range(10):
        name, offset, length = struct.unpack_from("<8sII", directory, index * 16)
        if name.rstrip(b"\0") != b".code":
            continue
        if not 0 < length <= size - 512 - offset:
            raise ValueError("The ROM has an invalid ExeFS game code entry.")
        if length > EUROPE_CODE_SIZE:
            break
        code = read_at(stream, base + exefs + 512 + offset, length)
        digest = hashlib.sha256(code).digest()
        hash_at = 512 - (index + 1) * 32
        if digest != directory[hash_at:hash_at + 32]:
            raise ValueError("The ROM's ExeFS game code failed its SHA-256 check.")
        compressed = read_at(stream, base + regions["ExHeader"][0] + 0xD, 1)[0] & 1
        if compressed and digest == EUROPE_PACKED_CODE_SHA256:
            return
        if compressed:
            digest = hashlib.sha256(unpack_code(code)).digest()
        if digest == EUROPE_CODE_SHA256:
            return
        break
    else:
        raise ValueError("The ROM has no ExeFS game code.")
    raise ValueError("This European ROM has different game code. Use the supported original revision of CTR-P-AREP.")


def integrity_error(region, encrypted):
    if encrypted:
        return f"{region} SHA-256 mismatch after decryption. Check the key and your ROM dump."
    return (f"{region} SHA-256 mismatch. The ROM may be incompletely decrypted or damaged. "
            "Select a fresh decrypted European Super Mario 3D Land ROM (CTR-P-AREP).")


def validate_decrypted_rom(path):
    """Check the plaintext NCCH headers and supported game code before building."""
    path = path.resolve(strict=True)
    if not path.is_file() or path.suffix.lower() not in ROM_TYPES:
        raise ValueError("Choose a .3ds, .cci, or .cxi file.")
    with path.open("rb") as stream:
        try:
            _, partitions = read_cartridge(stream, os.fstat(stream.fileno()).st_size)
            base, size, index = partitions[0]
            header, _, regions = read_partition(stream, base, size, index)
        except ValueError as error:
            raise ValueError("The file is not a readable Nintendo 3DS ROM.") from error

        if not is_european_mario(header):
            raise ValueError("Choose the European Super Mario 3D Land ROM (CTR-P-AREP).")
        if any(name not in regions for name in REQUIRED_REGIONS):
            raise ValueError("The ROM is missing required game data.")
        if not header[0x18F] & 4 and not has_plain_exheader(stream, base, header, regions["ExHeader"]):
            raise ValueError("The ROM could not be verified as decrypted. Choose a decrypted European copy.")

        for name in REQUIRED_REGIONS:
            region = regions[name]
            _, _, length, digest_at, _ = region
            if not length:
                raise ValueError(f"The ROM is missing the {name} integrity data.")
            if (region_digest(stream, base, region) != header[digest_at:digest_at + 32] and
                    not can_repair_digest(stream, base, header, name, region)):
                raise ValueError(integrity_error(name, encrypted=False))
        verify_supported_code(stream, base, regions)
    return path


def inspect_rom(stream, size, hash_rom):
    fmt, partitions = read_cartridge(stream, size)
    report = {"container": fmt, "size": size, "partitions": []}
    if hash_rom:
        stream.seek(0)
        report["sha256"] = hashlib.file_digest(stream, "sha256").hexdigest()
    for offset, length, index in partitions:
        header, content_size, regions = read_partition(stream, offset, length, index)
        record = {
            "index": index,
            "offset": offset,
            "size": content_size,
            "program_id": f"{int.from_bytes(header[0x118:0x120], 'little'):016X}",
            "partition_id": f"{int.from_bytes(header[0x108:0x110], 'little'):016X}",
            "product": printable_ascii(header[0x150:0x160]),
            "ncch_version": int.from_bytes(header[0x112:0x114], "little"),
            "flags": header[0x188:0x190].hex(),
            "encrypted": not bool(header[0x18F] & 4),
            "regions": {
                name: {"offset": start, "size": length, "hash_size": hash_size}
                for name, (start, length, hash_size, *_) in regions.items()
            },
        }
        if "plain" in regions:
            start, length, *_ = regions["plain"]
            record["plain_strings"] = [
                part.decode("ascii") for part in re.findall(rb"\[[ -~]{4,200}\]", read_at(stream, offset + start, min(length, 65536)))
            ]
        report["partitions"].append(record)
    return report


def make_decryptor(header, key_x, kind):
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

    mask = (1 << 128) - 1

    def rotate_left(value, bits):
        return ((value << bits) | (value >> (128 - bits))) & mask

    x = int.from_bytes(key_x, "big")
    y = int.from_bytes(header[:16], "big")
    scrambler = 0x1FF9E9AAC5FE0408024591DC5D52768A
    normal_key = rotate_left(((rotate_left(x, 2) ^ y) + scrambler) & mask, 87)
    counter = header[0x108:0x110][::-1] + bytes([kind]) + bytes(7)
    return Cipher(algorithms.AES(normal_key.to_bytes(16, "big")), modes.CTR(counter)).decryptor()


def extract_primary(stream, size, output, key_file):
    _, partitions = read_cartridge(stream, size)
    offset, length, _ = partitions[0]
    header, length, regions = read_partition(stream, offset, length, 0)
    if any(name not in regions for name in REQUIRED_REGIONS):
        raise ValueError("The primary partition is missing executable data")
    marked_encrypted = not bool(header[0x18F] & 4)
    encrypted = marked_encrypted and not (
        is_european_mario(header) and has_plain_exheader(stream, offset, header, regions["ExHeader"]))
    key_x = None
    if encrypted:
        if header[0x112:0x114] != b"\x02\x00" or header[0x18B] != 0 or header[0x18F] & 0x21:
            raise ValueError("Only encrypted NCCH v2 with original retail slot 0x2C is supported")
        source = key_file.read_text(encoding="ascii") if key_file else os.getenv("SM3DL_KEYX_2C", "")
        if not re.fullmatch(r"[0-9a-fA-F]{32}", source.strip()):
            raise ValueError("Provide the retail slot 0x2C KeyX through --key-file or SM3DL_KEYX_2C")
        key_x = bytes.fromhex(source.strip())

    output = output.resolve()
    if output.exists():
        raise FileExistsError(f"Output already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    # Publish only after the original NCCH digests match the extracted bytes.
    with tempfile.TemporaryDirectory(dir=output.parent, prefix=".ncch-") as temp:
        staged = Path(temp) / "partition.cxi"
        with staged.open("x+b") as out:
            local_header = bytearray(header)
            if marked_encrypted:
                local_header[0x18F] |= 4
                if not encrypted:
                    print("Verified plaintext ExHeader despite the encryption flag.")
            out.write(local_header)
            repaired = False
            cursor = 512
            for name, region in sorted(
                regions.items(), key=lambda pair: pair[1][0]
            ):
                start, count, hash_size, hash_offset, kind = region
                copy_region(stream, out, offset + cursor, start - cursor)
                decryptor = make_decryptor(header, key_x, kind) if encrypted and kind else None
                digest = copy_region(stream, out, offset + start, count, decryptor, hash_size)
                if hash_size and digest != header[hash_offset:hash_offset + 32]:
                    position = out.tell()
                    if encrypted or not can_repair_digest(out, 0, header, name, region):
                        raise ValueError(integrity_error(name, encrypted))
                    out.seek(position)
                    local_header[hash_offset:hash_offset + 32] = digest
                    repaired = True
                    print("Restored the ExHeader digest in the build copy.")
                print(f"{name}: {count} bytes" + (", SHA-256 verified" if hash_size else ""))
                cursor = start + count
            copy_region(stream, out, offset + cursor, length - cursor)
            if repaired:
                out.seek(0)
                out.write(local_header)
        staged.rename(output)
    print(output)


def copy_region(stream, out, start, size, decryptor=None, hash_size=0):
    digest = hashlib.sha256()
    while size:
        data = read_at(stream, start, min(size, 4 * 1024 * 1024))
        if decryptor is not None:
            data = decryptor.update(data)
        if hash_size:
            count = min(len(data), hash_size)
            digest.update(data[:count])
            hash_size -= count
        out.write(data)
        size -= len(data)
        start += len(data)
    if decryptor is not None:
        out.write(decryptor.finalize())
    return digest.digest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, nargs="?")
    parser.add_argument("--extract", metavar="OUTPUT.cxi", type=Path)
    parser.add_argument("--key-file", type=Path, help="Text file with one 32-digit slot 0x2C KeyX")
    parser.add_argument("--no-hash", action="store_true", help="Skip hashing the full input during inspection")
    args = parser.parse_args()
    try:
        root = Path(__file__).resolve().parents[1]
        candidates = sorted(p for p in root.iterdir() if p.is_file() and p.suffix.lower() in {".3ds", ".cci", ".cxi"})
        source = args.input or (candidates[0] if len(candidates) == 1 else None)
        if source is None:
            raise ValueError("Specify the input when there is no unique cartridge image in the workspace")
        with source.open("rb") as stream:
            size = os.fstat(stream.fileno()).st_size
            if args.extract:
                extract_primary(stream, size, args.extract, args.key_file)
            else:
                print(json.dumps(inspect_rom(stream, size, not args.no_hash), indent=2))
    except (OSError, ValueError, ImportError) as error:
        parser.exit(1, f"error: {error}\n")


if __name__ == "__main__":
    main()
