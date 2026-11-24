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
        assert_eq!((start, end), (0x003a0de4, 0x003a1784));
        for slot in (start..end).step_by(4) {
            let address = slot.wrapping_add(image.u32(slot).unwrap());
            assert!(address >= image.text.addr && address < start && address & 3 == 0);
            d.add_entry(address, false);
        }
        // The virtual call at 0x0021ea98 uses a method immediately before
        // a null slot in this table.
        let method = image.u32(0x003d9444).unwrap();
        assert_eq!(method, 0x0024dcf4);
        d.add_entry(method, false);
        // These helpers exist only in the patched European executable.
        if image.text.addr + image.text.size == 0x003a1fe0 {
            for address in [0x003a1eb0, 0x003a1ebc, 0x003a1ef4, 0x00473000] {
                d.add_entry(address, false);
            }
        }""")
    source = source.replace("        Op::Udf | Op::Bkpt(_) => Flow::Stop,",
                            "        Op::Udf | Op::Bkpt(_) if !conditional => Flow::Stop,")
    discover.write_text(source, encoding="utf-8")
    image = args.output / "image.rs"
    source = image.read_text(encoding="utf-8")
    anchor = '        addr >= self.text.addr && addr < self.text.addr + self.text.size'
    if source.count(anchor) != 1:
        raise ValueError('Unexpected Clockwork text range')
    image.write_text(source.replace(anchor, anchor + '\n            || (self.text.addr + self.text.size == 0x003a1fe0'
                                    '\n                && (0x00473000..0x004730a8).contains(&addr))'), encoding="utf-8")
    emitter = args.output / "emit.rs"
    source = emitter.read_text(encoding="utf-8")
    changes = {
        'pub fn fn_name(addr: u32) -> String {\n    format!("f_{addr:08x}")\n}': '''fn original_symbols() -> bool {
    static ORIGINAL: std::sync::OnceLock<bool> = std::sync::OnceLock::new();
    *ORIGINAL.get_or_init(|| std::env::var_os("SM3DL_RECOMP_ORIGINAL").is_some())
}

pub fn fn_name(addr: u32) -> String {
    if original_symbols() { format!("orig_f_{addr:08x}") } else { format!("f_{addr:08x}") }
}''',
        '    write_if_changed(&out_dir.join("lookup.c"), lookup.as_bytes())?;':
            '''    if original_symbols() {
        lookup = lookup.replace("recomp_functions", "original_recomp_functions")
                       .replace("recomp_function_count", "original_recomp_function_count");
    }
    write_if_changed(&out_dir.join("lookup.c"), lookup.as_bytes())?;''',
    }
    for old, new in changes.items():
        if source.count(old) != 1:
            raise ValueError('Unexpected Clockwork emitter source')
        source = source.replace(old, new)
    instruction = '            let mut body = self.insn(f, insn, live[i], tables.get(&insn.addr).copied());'
    if source.count(instruction) != 1:
        raise ValueError('Unexpected Clockwork instruction emitter')
    source = source.replace(instruction, '''            // EUR reserve UI: at this branch the original code has already
            // checked the widget state. Accept the PC shortcut as an alternative
            // to the confirmed touch, then execute the original drop and UI update.
            if f.entry == 0x0035e738 && insn.addr == 0x0035e7e4 {
                assert_eq!(insn.raw, 0x0a000017);
                writeln!(out, "    {{ extern int sm3dl_take_reserve_command(void); if (sm3dl_take_reserve_command()) ctx->z = 0; }}").unwrap();
            }
''' + instruction)
    emitter.write_text(source, encoding="utf-8")


if __name__ == "__main__":
    main()
