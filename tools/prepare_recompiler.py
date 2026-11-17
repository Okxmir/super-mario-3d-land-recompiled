"""Configure Clockwork discovery for the supported European 3D Land executable."""

import argparse
import shutil
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("upstream", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    shutil.copytree(args.upstream, args.output, dirs_exist_ok=True)
    discover = args.output / "discover.rs"
    source = discover.read_text(encoding="utf-8")
    anchor = "        d.add_entry(image.text.addr, false);"
    if source.count(anchor) != 1:
        raise ValueError("Unexpected Clockwork discovery source")
    source = source.replace(anchor, """        d.add_entry(image.text.addr, false);
        // 3D Land EUR's initializer at 0x003a0da4 walks signed, self-relative
        // pointers. The compiler emits no direct calls to these callbacks.
        let start = 0x003a0db4u32.wrapping_add(image.u32(0x003a0ddc).unwrap());
        let end = 0x003a0dbcu32.wrapping_add(image.u32(0x003a0de0).unwrap());
        assert_eq!((start, end), (0x003a0de4, image.text.addr + image.text.size));
        for slot in (start..end).step_by(4) {
            let address = slot.wrapping_add(image.u32(slot).unwrap());
            assert!(address >= image.text.addr && address < start && address & 3 == 0);
            d.add_entry(address, false);
        }
        // The virtual call at 0x0021ea98 uses a method immediately before
        // a null slot in this table.
        let method = image.u32(0x003d9444).unwrap();
        assert_eq!(method, 0x0024dcf4);
        d.add_entry(method, false);""")
    source = source.replace("        Op::Udf | Op::Bkpt(_) => Flow::Stop,",
                            "        Op::Udf | Op::Bkpt(_) if !conditional => Flow::Stop,")
    discover.write_text(source, encoding="utf-8")


if __name__ == "__main__":
    main()
