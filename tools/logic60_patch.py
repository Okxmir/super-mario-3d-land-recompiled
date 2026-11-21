"""Apply revision-specific 60 Hz hooks to build-local copies of translated code."""
import argparse
from pathlib import Path


def change(source, original, replacement, count=1):
    actual = source.count(original)
    if actual != count:
        raise ValueError(f"Expected {count} match(es), got {actual}: {original.splitlines()[0]}")
    return source.replace(original, replacement)


def before(source, anchor, statement, count=1):
    return change(source, anchor, statement + "\n" + anchor, count)


def after(source, anchor, statement):
    return change(source, anchor, anchor + "\n" + statement)


def animation(source, instruction, dest, frame, rate):
    op = f"    /* {instruction} */\n"
    old = f"set_f32(ctx, {dest}, get_f32(ctx, {frame}) + get_f32(ctx, {rate}));"
    new = f"set_f32(ctx, {dest}, get_f32(ctx, {frame}) + get_f32(ctx, {rate}) * sm3dl60_animation_step());"
    return change(source, op + "    " + old, op + "    " + new)


def player_vertical(source):
    entry = "    RECOMP_ENTER(ctx, 0x0018e1c8u);"
    source = after(source, entry, '''    uint32_t hold = 0, original_limit = 0;
    float gravity_fraction = 0.5f;
    const uint32_t initial_bits = rd32(ctx->r[1]);
    if (sm3dl60_player_step(ctx->r[0], 1) == 0.5f) {
        hold = rd32(ctx->r[0] + 8u);
        if (hold) {
            original_limit = rd32(hold);
            if (original_limit < 120u)
                wr32(hold, 2u * original_limit + 1u);
            else
                hold = 0;
        }
    }''')
    source = before(source, "    /* 0018e364: pop {r4, r5, r6, r7, pc} */",
                    "    if (hold) wr32(hold, original_limit);")
    source = before(source, "    /* 0018e23c: bl 0x18fd44 */", '''    if (hold && ctx->r[0] == hold && !rd8(hold + 8u)) {
        sm3dl60_reset_release();
        const uint32_t elapsed = rd32(hold + 4u);
        if (!ctx->r[1] && elapsed && (elapsed & 1u) == 0 && elapsed < 2u * original_limit + 2u)
            ctx->r[1] = 1;
    }''')
    source = change(source, '''    /* 0018e288: ble 0x18e2a8 */
    if (ctx->z || ctx->n != ctx->v) {''', '''    /* 0018e288: ble 0x18e2a8 */
    const _Bool drag = !(ctx->z || ctx->n != ctx->v);
    if (!(hold ? sm3dl60_release_drag(hold, drag) : drag)) {''')
    source = change(source, '''    /* 0018e2a0: vmul.f32 s0, s0, s1 */
    set_f32(ctx, 0, get_f32(ctx, 0) * get_f32(ctx, 1));''', '''    /* 0018e2a0: vmul.f32 s0, s0, s1 */
    const float retention = get_f32(ctx, 0);
    const float substep_retention = hold && retention >= 0.f ? sqrtf(retention) : retention;
    if (hold && substep_retention >= 0.f) gravity_fraction = 1.f / (1.f + substep_retention);
    set_f32(ctx, 0, substep_retention * get_f32(ctx, 1));''')
    source = change(source, '''    /* 0018e2bc: vmls.f32 s1, s0, s16 */
    set_f32(ctx, 1, get_f32(ctx, 1) - get_f32(ctx, 0) * get_f32(ctx, 16));''', '''    /* 0018e2bc: vmls.f32 s1, s0, s16 */
    const float gravity_step = sm3dl60_player_step(ctx->r[4], 1);
    set_f32(ctx, 1, get_f32(ctx, 1) - get_f32(ctx, 0) * get_f32(ctx, 16) *
        (gravity_step == 0.5f ? gravity_fraction : 1.f));''')
    source = before(source, "    /* 0018e324: ldr r0, [r4, #4] */", '''    if (sm3dl60_player_step(ctx->r[4], 1) == 0.5f) {
        const uint32_t speed_bits = rd32(ctx->r[5]);
        float initial, speed;
        memcpy(&initial, &initial_bits, sizeof initial);
        memcpy(&speed, &speed_bits, sizeof speed);
        sm3dl60_record_acceleration(ctx->r[4], ctx->r[7], speed - initial);
    }''')
    source = before(source, '    /* 001862f4: bl 0x262988 */',
                    '    ctx->s[0] = sm3dl60_dry_bones_patrol_clock(ctx->r[0], ctx->s[0], 0);')
    source = before(source, '    /* 00186388: bl 0x2799ec */',
                    '    ctx->r[1] = sm3dl60_dry_bones_patrol_clock(rd32(ctx->r[4] + 12), ctx->r[1], 1);')
    return animation(source, "0018f2e4: vadd.f32 s0, s0, s2", 0, 0, 2)


def player_displacement(source):
    source = before(source, "    /* 0026d6d8: cmp r2, #0 */", '''    extern float sm3dl60_balance_tilt_step(uint32_t actor);
    extern _Bool sm3dl60_balance_count_tick(uint32_t actor);
    const float native_balance_tilt = sm3dl60_balance_tilt_step(ctx->r[0]);
    set_f32(ctx, 3, get_f32(ctx, 3) * native_balance_tilt);''')
    for instruction in ("0026d7bc: vsub.f32 s1, s1, s2", "0026d830: vadd.f32 s1, s1, s2"):
        source = before(source, f"    /* {instruction} */",
                        "    set_f32(ctx, 2, get_f32(ctx, 2) * native_balance_tilt);")
    for address, sign, instruction in ((0x26d724, "-", "add r0, r0, #1"),
                                       (0x26d778, "+", "sub r0, r0, #1")):
        source = before(source, f"    /* {address:08x}: {instruction} */",
                        f"    if (!sm3dl60_balance_count_tick(ctx->r[4])) ctx->r[0] {sign}= 1u;")
    for entry in (0x0026df08, 0x0026df44):
        source = after(source, f"    RECOMP_ENTER(ctx, 0x{entry:08x}u);", "    _Bool legacy_actor = 0;")
    source = before(source, "    /* 0026df74: ldr r0, [r4, #28] */",
                    '''    if (sm3dl60_legacy_actor(ctx->r[4])) {
        if (!sm3dl60_legacy_actor_tick()) goto L_0026e134;
        legacy_actor = 1;
        sm3dl60_legacy_actor_enter();
    }''', 2)
    for addr in (0x0026e128, 0x0026e134):
        source = before(source, f"    /* {addr:08x}: add sp, sp, #48 */",
                        "    if (legacy_actor) sm3dl60_legacy_actor_leave();", 2)
    source = before(source, "    /* 002631a4: vldr s0, [r4] */", '''    {
        const float scale = sm3dl60_player_step(ctx->r[5], 0);
        if (scale != 1.0f) {
            const uint32_t original = ctx->r[4];
            const uint32_t displacement = ctx->r[13] + 0x58u;
            for (uint32_t axis = 0; axis < 3; ++axis) {
                const uint32_t bits = rd32(original + 4u * axis);
                float delta;
                memcpy(&delta, &bits, sizeof delta);
                delta = delta * scale + sm3dl60_movement_bias(ctx->r[5], axis);
                uint32_t output;
                memcpy(&output, &delta, sizeof output);
                wr32(displacement + 4u * axis, output);
            }
            ctx->r[4] = displacement;
        }
    }''')
    return before(source, "    /* 0026e00c: ldr r0, [r4, #44] */", "    sm3dl60_actor_before(ctx->r[4]);", 2)


def course(source):
    source = before(source, "    /* 003647c4: bl 0x176aa0 */",
                    "    ctx->r[0] = sm3dl60_countdown(ctx->r[4], ctx->r[0]);")
    source = before(source, "    /* 00366934: ldr r3, [0x3669f8] */", '''    extern uint32_t sm3dl60_mystery_clock(uint32_t actor, uint32_t raw, uint32_t *prior, _Bool *replace_events);
    uint32_t mystery_prior = 0;
    _Bool mystery_override = 0;
    const uint32_t mystery_age = sm3dl60_mystery_clock(ctx->r[4], ctx->r[0], &mystery_prior, &mystery_override);
    if (mystery_override) ctx->r[0] = mystery_age;''')
    for pc in (0x366964, 0x36697c, 0x366990, 0x3669bc):
        old = f"    /* {pc:08x}: bl 0x279d14 */\n    {{\n        ctx->r[14] = 0x{pc+4:08x}u;\n        f_00279d14(ctx);"
        source = change(source, old, old.replace('        f_00279d14(ctx);', '''        if (mystery_override) ctx->r[0] = mystery_prior < ctx->r[1] && ctx->r[1] <= mystery_age;
        else f_00279d14(ctx);'''))
    for address in (0x369780, 0x369790, 0x3697a0):
        source = before(source, f"    /* {address:08x}: pop {{r4, lr}} */", "    ctx->s[0] = sm3dl60_rail_rate(ctx->s[0]);")
    source = before(source, '    /* 0036f5e0: bl 0x27cc64 */', '    ctx->s[0] = sm3dl60_rail_rate(ctx->s[0]);')
    for address in (0x36f448, 0x36f578, 0x36f51c):
        source = before(source, f'    /* {address:08x}: bl 0x2799ec */',
                        '    ctx->r[1] = sm3dl60_actor_transition_duration(ctx->r[1]);')
    return source


def lift(source, instructions):
    for pc, target, include_last in instructions:
        source = before(source, f"    /* {pc:08x}: bl {target:#x} */",
                        f"    ctx->r[1] = sm3dl60_lift_duration(ctx->r[4], ctx->r[1], {int(include_last)});")
    return source


def rail_camera(source):
    # The common camera mixer advances its private blend counter once per
    # camera update. In the opt-in mode keep its age in half-ticks: that
    # preserves 30 Hz output and avoids a phase jump if game cadence changes
    # while the camera is blending (for example on a death or course intro).
    source = before(source, '    /* 00158d88: cmp r0, r1 */',
                    '    if (sm3dl60_configured() && ctx->r[0] <= 0x3fffffffu) ctx->r[0] *= 2u;')
    source = before(source, '    /* 00158dd8: vdiv.f32 s0, s1, s2 */',
                    '    if (sm3dl60_configured()) set_f32(ctx, 1, 0.5f * get_f32(ctx, 1));')
    mixer = '    /* 00158f5c: add r0, r0, #1 */\n    {\n'
    whole = '        uint32_t res = ctx->r[0] + 0x00000001u + 0;'
    source = change(source, mixer + whole, mixer + '        uint32_t res = ctx->r[0] + sm3dl60_camera_wave_step();')
    # The Rail camera reads the configured Arg0 speed into the follower's
    # per-update delta. Retiming the background actor would not fix the camera.
    source = before(source, '    /* 00159660: vstr s0, [r0, #32] */',
                    '    ctx->s[0] = sm3dl60_rail_rate(ctx->s[0]);')
    source = before(source, '    /* 00159898: vadd.f32 s0, s0, s1 */',
                    '    ctx->s[1] = sm3dl60_rail_rate(ctx->s[1]);')
    for pc in (0x00159650, 0x00159900):
        anchor = f'    /* {pc:08x}: cmp r0, #60 */\n    {{\n'
        term = '        uint32_t c, v; uint32_t res = add_cv(ctx->r[0], ~0x0000003cu, 1, &c, &v);'
        source = change(source, anchor + term, anchor + term.replace('0x0000003cu', 'sm3dl60_camera_duration(60u)'))
    source = before(source, '    /* 00159a44: add r5, r4, #20 */',
                    '    set_f32(ctx, 16, sm3dl60_camera_blend(get_f32(ctx, 16)));')
    # CameraWaveArea's private phase counter is zeroed on entry/reset. Keep it
    # in half-frame units in both modes, so temporarily dropping to the
    # original cadence does not jump to a different point in the wave.
    source = before(source, '    /* 00159d04: vmul.f32 s0, s0, s1 */',
                    '    if (sm3dl60_configured()) set_f32(ctx, 0, get_f32(ctx, 0) * 0.5f);')
    anchor = '    /* 00159d44: add r0, r0, #1 */\n    {\n'
    step = '        uint32_t res = ctx->r[0] + 0x00000001u + 0;'
    source = change(source, anchor + step, anchor + '        uint32_t res = ctx->r[0] + sm3dl60_camera_wave_step();')
    return before(source, '    /* 0015e990: bl 0x27f340 */',
                  '    ctx->r[1] = sm3dl60_killer_frames(ctx->r[4], ctx->r[1]);', 2)


def advance_rail(source, anchor):
    return before(source, anchor, '    ctx->s[0] = sm3dl60_rail_rate(ctx->s[0]);')


def rail_objects(source):
    source = before(source, '    /* 00344cfc: bleq 0x279e8c */',
                    '    if (ctx->z) ctx->s[0] = sm3dl60_rail_rate(ctx->s[0]);')
    for anchor in ('0034d87c: bl 0x273e28', '0034d8c4: bl 0x240e08', '0034d7f0: bl 0x240e08'):
        source = advance_rail(source, f'    /* {anchor} */')
    for anchor in ('0034d308: bl 0x25ac6c', '0034d320: bl 0x240e08',
                   '00349960: bl 0x273e5c', '00349704: bl 0x273e5c'):
        source = advance_rail(source, f'    /* {anchor} */')
    # Seagull's continuous flight takes one rail step and one angular
    # steering step; its model animation already follows the common clock.
    for anchor in ('0034c560: bl 0x273e28', '0034c580: bl 0x27c000'):
        source = advance_rail(source, f'    /* {anchor} */')
    source = before(source, '    /* 00347668: vldr s0, [r4, #100] */',
                    '    ctx->s[1] = sm3dl60_thwomp_fall(ctx->r[4], ctx->s[1]);')
    source = before(source, '    /* 00345bc8: bl 0x26b754 */',
                    '    sm3dl60_dry_bones_drag(ctx->r[4], ctx->s[2]);\n'
                    '    ctx->s[3] = sm3dl60_rail_rate(ctx->s[3]);')
    for anchor in ('0034d7fc: bl 0x2799ec', '003476ec: bl 0x2799ec', '00345c04: bl 0x2799ec',
                   '00349324: bl 0x2799ec', '00349780: bl 0x2799ec'):
        source = before(source, f'    /* {anchor} */',
                        '    ctx->r[1] = sm3dl60_actor_transition_duration(ctx->r[1]);')
    return source


def goomba_contacts(source):
    source = before(source, '    /* 00308160: cmp r0, #0 */',
                    '    if (ctx->r[0]) sm3dl60_goomba_event(ctx->r[4], ctx->r[7], ctx->r[6]);')
    source = before(source, '    /* 00308194: cmp r0, #0 */',
                    '    if (ctx->r[0]) sm3dl60_goomba_event(ctx->r[4], ctx->r[7], ctx->r[6]);')
    source = before(source, '    /* 00308284: cmp r0, #0 */',
                    '    if (ctx->r[0]) sm3dl60_goomba_event(ctx->r[4], ctx->r[6], 45u);')
    source = advance_rail(source, '    /* 0030aebc: bl 0x273e5c */')
    source = before(source, '    /* 0030af38: vmla.f32 s0, s2, s1 */', '    sm3dl60_boo_impulse(ctx->r[4]);')
    source = before(source, '    /* 0030aa50: strgt r1, [r0, #172] */',
                    '    if (!ctx->z && ctx->n == ctx->v) ctx->r[1] = sm3dl60_boo_cooldown(ctx->r[0], ctx->r[1]);')
    for instruction in ('00307fb8: bl 0x279d14', '00308000: bl 0x279cf0', '00308074: bl 0x27f340'):
        source = before(source, f'    /* {instruction} */', '    ctx->r[1] = sm3dl60_killer_frames(ctx->r[4], ctx->r[1]);')
    source = before(source, '    /* 00308018: bl 0x279c8c */',
                    '    ctx->r[1] = sm3dl60_killer_frames(ctx->r[4], ctx->r[1]);\n'
                    '    ctx->r[2] = sm3dl60_killer_frames(ctx->r[4], ctx->r[2]);')
    source = before(source, '    /* 00307e68: add r0, r0, #1 */',
                    '    if (sm3dl60_killer_half_tick(ctx->r[4])) --ctx->r[0];')
    return before(source, '    /* 00307f5c: strgt r0, [r4, #172] */',
                  '    if (!ctx->z && ctx->n == ctx->v && sm3dl60_killer_half_tick(ctx->r[4])) ++ctx->r[0];')


def player_contacts(source):
    source = before(source, "    /* 001341d0: cmp r0, #0 */", '''    extern void sm3dl60_balance_rider_contact(uint32_t board, uint32_t receiver, uint32_t sender);
    if (ctx->r[0]) sm3dl60_balance_rider_contact(ctx->r[4], ctx->r[6], ctx->r[7]);''')
    source = before(source, "    /* 001343e4: vstr s0, [r4, #156] */", '''    extern float sm3dl60_balance_accelerate(uint32_t actor, float whole_velocity);
    set_f32(ctx, 0, sm3dl60_balance_accelerate(ctx->r[4], get_f32(ctx, 0)));''')
    source = before(source, "    /* 00134428: bl 0x1478a8 */", '''    extern float sm3dl60_balance_rail_step(uint32_t actor, float full);
    set_f32(ctx, 0, sm3dl60_balance_rail_step(ctx->r[4], get_f32(ctx, 0)));''')
    source = before(source, "    /* 00134464: vmla.f32 s1, s0, s2 */", '''    extern float sm3dl60_balance_slope_step(uint32_t actor);
    set_f32(ctx, 2, get_f32(ctx, 2) * sm3dl60_balance_slope_step(ctx->r[4]));''')
    for address in ("00134304", "001346ec"):
        source = before(source, f"    /* {address}: bl 0x280610 */", '''    extern void sm3dl60_balance_leave_rail(uint32_t actor);
    sm3dl60_balance_leave_rail(ctx->r[4]);''')
    source = before(source, "    /* 00134e4c: vldr s2, [r4, #156] */", '''    extern _Bool sm3dl60_balance_fall_begin(uint32_t actor);
    const _Bool native_balance_fall = sm3dl60_balance_fall_begin(ctx->r[4]);''')
    source = before(source, "    /* 00134e60: vmul.f32 s2, s2, s3 */", '''    if (native_balance_fall) {
        set_f32(ctx, 3, sqrtf(get_f32(ctx, 3)));
        set_f32(ctx, 0, sqrtf(get_f32(ctx, 0)));
    }''')
    source = before(source, "    /* 00134e88: bl 0x27cc64 */",
                    "    if (native_balance_fall) set_f32(ctx, 0, get_f32(ctx, 0) * (.997496867f / 1.997496867f));")
    source = before(source, "    /* 00134eb4: bl 0x27cc64 */",
                    "    if (native_balance_fall) set_f32(ctx, 0, sqrtf(get_f32(ctx, 0)));")
    source = before(source, "    /* 00134f14: bl 0x27cb48 */", '''    if (native_balance_fall) {
        extern void sm3dl60_balance_fall_delta(uint32_t velocity, uint32_t delta);
        const uint32_t out = ctx->r[13] + 36;
        sm3dl60_balance_fall_delta(ctx->r[2], out);
        ctx->r[2] = out;
    }''')
    source = before(source, "    /* 00134920: vadd.f32 s0, s0, s3 */", '''    extern float sm3dl60_balance_tilt_step(uint32_t actor);
    const float native_balance_rotation = sm3dl60_balance_tilt_step(ctx->r[4]);
    set_f32(ctx, 2, get_f32(ctx, 2) * native_balance_rotation);
    set_f32(ctx, 3, get_f32(ctx, 3) * native_balance_rotation);''')
    return before(source, "    /* 001303b4: mov r0, #1 */",
                  "    sm3dl60_player_contact(ctx->r[4], ctx->r[7], ctx->r[6]);")


def koopa_walk(source):
    source = advance_rail(source, '    /* 003164a8: bl 0x27139c */')
    return advance_rail(source, '    /* 003164b4: bl 0x25ac6c */')


def dry_bones_walk(source):
    for address in (0x00214540, 0x0021459c, 0x002145e4):
        source = before(source, f'    /* {address:08x}: bl 0x279e5c */',
                        '    sm3dl60_dry_bones_drag(ctx->r[4], ctx->s[0]);')
    return before(source, '    /* 002187a8: bl 0x279e5c */', '    sm3dl60_boo_drag(ctx->r[4], ctx->s[0]);')


def dry_bones_patrol_drag(source):
    for address in (0x002587b8, 0x002587d4):
        source = before(source, f'    /* {address:08x}: b 0x279e5c */',
                        '    sm3dl60_dry_bones_drag(ctx->r[0], ctx->s[0]);')
    return source


def lift_and_launcher(source):
    source = lift(source, [(0x35f558, 0x27f340, True)])
    for address, target, period in ((0x3528b0, 0x269464, 0), (0x3528d4, 0x27f340, 1),
                                    (0x352938, 0x2799ec, 2)):
        source = before(source, f'    /* {address:08x}: bl {target:#x} */',
                        '    extern uint32_t sm3dl60_pata_duration(uint32_t actor, uint32_t steps, unsigned period);\n'
                        f'    ctx->r[1] = sm3dl60_pata_duration(ctx->r[4], ctx->r[1], {period}u);')
    for address in (0x3528a4, 0x35292c):
        source = advance_rail(source, f'    /* {address:08x}: bl 0x273e5c */')
    source = before(source, '    /* 0035d980: b 0x2416e4 */',
                    '    set_f32(ctx, 0, sm3dl60_teresa_rotor_step(get_f32(ctx, 0)));')
    source = before(source, '    /* 003596bc: bl 0x17e68c */',
                    '    set_f32(ctx, 0, sm3dl60_poison_turn(ctx->r[4], get_f32(ctx, 0)));')
    for address in (0x003596dc, 0x003568dc):
        anchor = f'    /* {address:08x}: bl 0x24e9f8 */'
        block = f'{anchor}\n    {{\n        ctx->r[14] = 0x{address+4:08x}u;\n        f_0024e9f8(ctx);\n    }}'
        source = change(source, block, block.replace('    {\n', '    if (!sm3dl60_mushroom_half_tick(ctx->r[4])) {\n', 1))
    for address in (0x003516e8, 0x00351798):
        anchor = f'    /* {address:08x}: bl 0x24e9f8 */'
        block = f'{anchor}\n    {{\n        ctx->r[14] = 0x{address+4:08x}u;\n        f_0024e9f8(ctx);\n    }}'
        source = change(source, block, block.replace('    {\n', '    if (!sm3dl60_killer_half_tick(ctx->r[4])) {\n', 1))
    source = before(source, '    /* 003516f4: bl 0x27f340 */',
                    '    ctx->r[1] = sm3dl60_killer_frames(ctx->r[4], ctx->r[1]);')
    return before(source, '    /* 0035f7bc: bl 0x27f340 */',
                  '    ctx->r[1] = sm3dl60_killer_frames(ctx->r[4], ctx->r[1]);')


def super_mushroom_turn(source, count):
    return before(source, '    /* 0017e594: bl 0x27c000 */',
                  '    set_f32(ctx, 0, sm3dl60_super_mushroom_turn(ctx->r[0], get_f32(ctx, 0)));', count)


def generator_fish(source):
    # The two phases advance the same spline using the original speed.
    # Its end point is checked geometrically; the first phase changes
    # when the (already retimed) launch animation finishes.
    for address in ("0036d0a8", "0036d130"):
        source = advance_rail(source, f"    /* {address}: bl 0x27139c */")
    return source


def sambo_rail(source, braking):
    # Sambo's path stays geometric; only advancement and the original 15-tick
    # acceleration/deceleration ramps are scaled. Its hit states are untouched.
    ramp, frames, movement, fx, after_fx, owner = (
        ("0034f524", "0034f538", ("0034f52c",), "0034f574", "0034f578", 4) if braking else
        ("0032314c", "00323120", ("00323154", "0032316c"), "003231c0", "003231c4", 5))
    source = before(source, f"    /* {ramp}: vmul.f32 s0, s0, s1 */",
                    f'''    extern float sm3dl60_sambo_ramp(uint32_t actor, float factor, _Bool braking);
    set_f32(ctx, 0, sm3dl60_sambo_ramp(ctx->r[{owner}], get_f32(ctx, 0), {int(braking)}));''')
    source = before(source, f"    /* {frames}: bl 0x{'27f340' if braking else '27a5fc'} */",
                    f'''    extern uint32_t sm3dl60_sambo_ramp_frames(uint32_t actor, uint32_t frames);
    ctx->r[1] = sm3dl60_sambo_ramp_frames(ctx->r[{owner}], ctx->r[1]);''')
    for pc in movement:
        source = before(source, f"    /* {pc}: bl 0x27139c */",
                        f'''    extern float sm3dl60_sambo_step(uint32_t actor, float distance);
    set_f32(ctx, 0, sm3dl60_sambo_step(ctx->r[{owner}], get_f32(ctx, 0)));''')
    source = before(source, f"    /* {fx}: bl 0x24e9f8 */",
                    f'''    extern _Bool sm3dl60_sambo_effect(uint32_t actor);
    if (sm3dl60_sambo_effect(ctx->r[{owner}])) {{''')
    return before(source, f"    /* {after_fx}: add sp, sp, #8 */", "    }")


def projectile_contacts(source):
    return after(source, '    RECOMP_ENTER(ctx, 0x0011d4c8u);',
                 '    if (sm3dl60_killer_half_tick(ctx->r[0])) return;')


HOOKS = {
    # The variant's age, effect emission, and contact look-ahead are coupled.
    # Keep this part on its original ticks while moving at both half-steps.
    "recomp_0011.c": projectile_contacts,
    "recomp_0013.c": player_contacts,
    "recomp_0014.c": lambda s: before(s, "    /* 0014f7fc: bl 0x27cb48 */",
                                     """    extern void sm3dl60_preserve_balance_carry(uint32_t collider, uint32_t delta);
    sm3dl60_preserve_balance_carry(ctx->r[4], ctx->r[2]);"""),
    "recomp_0015.c": lambda s: rail_camera(lift(s, [(0x15e670, 0x27f3d0, False), (0x15e6ac, 0x27f340, True)])),
    "recomp_0017.c": lambda s: super_mushroom_turn(advance_rail(s, '    /* 00176058: bl 0x2694a4 */'), 2),
    "recomp_0018.c": player_vertical,
    "recomp_0019.c": lambda s: advance_rail(s, '    /* 0019b388: bl 0x260e68 */'),
    "recomp_001a.c": lambda s: after(s, '    RECOMP_ENTER(ctx, 0x001a8278u);', '''    extern _Bool sm3dl60_hold_damage_timer(uint32_t guard);
    if (sm3dl60_hold_damage_timer(ctx->r[0])) return;'''),
    "recomp_001e.c": lambda s: before(s, "    /* 001ebd10: ldr r0, [r4, #32] */",
                                     "    ctx->r[5] = sm3dl60_actor_delta(ctx->r[4], ctx->r[5], ctx->r[13]);"),
    "recomp_0021.c": dry_bones_walk,
    "recomp_0025.c": dry_bones_patrol_drag,
    "recomp_0026.c": player_displacement,
    "recomp_002a.c": lambda s: animation(s, "002a370c: vadd.f32 s2, s1, s0", 2, 1, 0),
    "recomp_0030.c": goomba_contacts,
    "recomp_0031.c": koopa_walk,
    "recomp_0032.c": lambda s: before(sambo_rail(s, False), '    /* 0032c998: bl 0x2799ec */',
                                       '    ctx->r[1] = sm3dl60_dry_bones_patrol_clock(rd32(ctx->r[4] + 12), ctx->r[1], 1);'),
    "recomp_0034.c": lambda s: sambo_rail(rail_objects(s), True),
    "recomp_0035.c": lift_and_launcher,
    # The recompiler also inlines this same turn into the walk-state handler.
    "recomp_0036.c": lambda s: generator_fish(super_mushroom_turn(course(s), 1)),
}

DECLS = '''#include <stdint.h>
#include <math.h>
#include <string.h>
extern _Bool sm3dl60_configured(void);
extern uint32_t sm3dl60_countdown(uint32_t owner, uint32_t amount);
extern float sm3dl60_player_step(uint32_t object, _Bool gravity);
extern void sm3dl60_record_acceleration(uint32_t object, uint32_t axis, float delta);
extern float sm3dl60_movement_bias(uint32_t collider, unsigned axis);
extern void sm3dl60_reset_release(void);
extern _Bool sm3dl60_release_drag(uint32_t state, _Bool drag);
extern float sm3dl60_animation_step(void);
extern _Bool sm3dl60_legacy_actor(uint32_t actor);
extern _Bool sm3dl60_legacy_actor_tick(void);
extern void sm3dl60_legacy_actor_enter(void);
extern void sm3dl60_legacy_actor_leave(void);
extern void sm3dl60_goomba_event(uint32_t actor, uint32_t sensor, uint32_t message);
extern void sm3dl60_player_contact(uint32_t mario, uint32_t sensor, uint32_t message);
extern void sm3dl60_actor_before(uint32_t actor);
extern uint32_t sm3dl60_actor_delta(uint32_t actor, uint32_t velocity, uint32_t scratch);
extern uint32_t sm3dl60_thwomp_fall(uint32_t actor, uint32_t velocity);
extern void sm3dl60_dry_bones_drag(uint32_t actor, uint32_t retention);
extern uint32_t sm3dl60_dry_bones_patrol_clock(uint32_t actor, uint32_t value, _Bool timer);
extern void sm3dl60_boo_impulse(uint32_t actor);
extern void sm3dl60_boo_drag(uint32_t actor, uint32_t retention);
extern uint32_t sm3dl60_boo_cooldown(uint32_t actor, uint32_t decremented);
extern uint32_t sm3dl60_killer_frames(uint32_t actor, uint32_t frames);
extern _Bool sm3dl60_killer_half_tick(uint32_t actor);
extern uint32_t sm3dl60_rail_rate(uint32_t bits);
extern float sm3dl60_teresa_rotor_step(float degrees);
extern float sm3dl60_poison_turn(uint32_t actor, float degrees);
extern float sm3dl60_super_mushroom_turn(uint32_t actor, float degrees);
extern _Bool sm3dl60_mushroom_half_tick(uint32_t actor);
extern uint32_t sm3dl60_camera_duration(uint32_t steps);
extern uint32_t sm3dl60_camera_wave_step(void);
extern float sm3dl60_camera_blend(float alpha);
extern uint32_t sm3dl60_lift_duration(uint32_t actor, uint32_t frames, _Bool inclusive);
extern uint32_t sm3dl60_actor_transition_duration(uint32_t original);
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    contents = DECLS + HOOKS[args.input.name](args.input.read_text(encoding="utf-8"))
    if not args.output.is_file() or args.output.read_text(encoding="utf-8") != contents:
        args.output.write_text(contents, encoding="utf-8")


if __name__ == "__main__":
    main()
