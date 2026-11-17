"""Compile the LCD shader and embed the SPIR-V bytecode."""

import argparse
from pathlib import Path
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("compiler", type=Path)
    parser.add_argument("source", type=Path)
    parser.add_argument("header", type=Path)
    parser.add_argument("--entry", default="main")
    parser.add_argument("--symbol", default="sm3dl_lcd")
    parser.add_argument("--profile", default="ps_6_0")
    args = parser.parse_args()
    spirv = args.header.with_suffix(".spv")
    subprocess.run(
        [str(args.compiler), "-spirv", "-fspv-entrypoint-name=main", "-T", args.profile, "-E", args.entry,
         "-Fo", str(spirv), str(args.source)],
        check=True,
    )
    data = spirv.read_bytes()
    rows = ["    " + ", ".join(f"0x{x:02x}" for x in data[i:i+16]) + "," for i in range(0, len(data), 16)]
    args.header.write_text(f"alignas(4) static constexpr unsigned char {args.symbol}[] = {{\n"
                           + "\n".join(rows) + "\n};\n", encoding="ascii")


if __name__ == "__main__":
    main()
