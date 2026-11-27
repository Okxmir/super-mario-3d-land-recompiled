"""Select completed native frames using the generation of their GPU surface."""
from coherent_pica_fast import once


def native_surface_scanout(source):
    source = once(source, '    uint64_t guest_hash;\n    uint64_t last_used;',
                  '    uint64_t guest_hash;\n    uint64_t native_content_epoch = 0;\n    uint64_t last_used;')
    # Surface writes are serialized by the GX path; the LCD queue is protected
    # by lcd_lock. A render can finish without advancing the guest's dispatch ID.
    source = once(source, 'uint64_t use_clock = 0;', 'uint64_t native_render_epoch = 0;\nuint64_t use_clock = 0;')
    source = once(source, '    surface_loads.push_back({s, read_guest(*s)});',
                  '    surface_loads.push_back({s, read_guest(*s)});\n    s->native_content_epoch = ++native_render_epoch;')
    source = once(source, '    if (!vbuf) batch.clear(); // out of GPU memory: this batch is lost',
                  '    if (!vbuf) batch.clear(); // out of GPU memory: this batch is lost\n'
                  '    const uint64_t drawn_epoch = batch.empty() ? 0 : ++native_render_epoch;')
    source = once(source, '        d.color->drawn = true;',
                  '        d.color->drawn = true;\n        d.color->native_content_epoch = drawn_epoch;')
    source = once(source, '            s->drawn = false, s->guest_hash = guest_hash(*s); // the fill already wrote guest memory',
                  '            s->drawn = false, s->guest_hash = guest_hash(*s); // the fill already wrote guest memory\n'
                  '            s->native_content_epoch = ++native_render_epoch;')
    source = once(source, 'uint32_t native_render_id = 0;',
                  'uint32_t native_render_id = 0;\nuint64_t native_queued_epoch = 0;\nuintptr_t native_queued_source = 0;')
    source = once(source, '''    const bool native = out && stamp && stamp != native_render_id &&
        std::find(native_lcd_addresses.begin(), native_lcd_addresses.end(), out) != native_lcd_addresses.end();''', '''    const bool left_address = out &&
        std::find(native_lcd_addresses.begin(), native_lcd_addresses.end(), out) != native_lcd_addresses.end();
    const auto source_identity = reinterpret_cast<uintptr_t>(src);
    const bool known_surface = src->native_content_epoch && !src->reload;
    const bool new_surface = src->native_content_epoch != native_queued_epoch || source_identity != native_queued_source;
    const bool native = stamp && left_address && (known_surface ? new_surface : stamp != native_render_id);''')
    return once(source, '        native_render_id = stamp;', '''        native_render_id = stamp;
        native_queued_epoch = src->native_content_epoch;
        native_queued_source = source_identity;''')
