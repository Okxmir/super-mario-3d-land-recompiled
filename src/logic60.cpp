#include "logic60.h"

#include "log.h"
#include "memory.h"

#include <array>
#include <atomic>
#include <bit>
#include <cmath>
#include <cstdint>
#include <cstdlib>

namespace {
// Identified in the supported European executable. These are not timing constants shared by other ROMs.
constexpr uint32_t frame_interval = 0x1591689c;
constexpr uint32_t course_app = 0x003e23c4;
constexpr uint32_t goomba_table = 0x003d2ce8;
constexpr uint32_t grounded_goomba = 0x003f21e0;
constexpr uint32_t koopa_table = 0x003d4018;
constexpr uint32_t grounded_koopa = 0x003f2274;
constexpr uint32_t turning_koopa = 0x003f2284;
constexpr uint32_t thwomp_table = 0x003d29ac;
constexpr uint32_t dry_bones_table = 0x003d2434;
constexpr uint32_t patrolling_dry_bones = 0x003f2160;
constexpr uint32_t turning_dry_bones = 0x003f2168;
constexpr uint32_t attack_hit_dry_bones = 0x003f2174;
constexpr uint32_t boo_table = 0x003d2f68;
constexpr uint32_t chasing_boo = 0x003f23d8;
constexpr uint32_t killer_table = 0x003d2c4c;
constexpr uint32_t killer_variant_table = 0x003c4944;
constexpr uint32_t killer_variant_flight = 0x003f3010;
constexpr uint32_t killer_variant_cruise = 0x003f3024;
constexpr uint32_t killer_launch = 0x003f2190;
constexpr uint32_t killer_flight = 0x003f2194;
constexpr uint32_t killer_launcher_table = 0x003ca808;
constexpr uint32_t boomerang_table = 0x003d019c;
constexpr uint32_t braking_boomerang = 0x003f2f90;
constexpr uint32_t teresa_rotor_table = 0x003c93fc;
constexpr uint32_t teresa_rotor_turn = 0x003f2b80;
constexpr uint32_t needle_block_table = 0x003c6610;
constexpr uint32_t attached_needle_block = 0x003f29e4;
constexpr uint32_t needle_plant_table = 0x003c6740;
constexpr uint32_t waiting_needle_plant = 0x003f2a08;
constexpr uint32_t super_mushroom_table = 0x003c6210;
constexpr uint32_t walking_super_mushroom = 0x003f1658;
constexpr uint32_t poison_mushroom_table = 0x003c7264;
constexpr uint32_t chasing_poison_mushroom = 0x003f1634;
constexpr uint32_t pata_kuribo_table = 0x003c4d50;
constexpr uint32_t pata_kuribo_travel = 0x003f22ec;
constexpr uint32_t pata_kuribo_wait = 0x003f22f0;
constexpr uint32_t balance_truck_table = 0x003c6bdc;
constexpr uint32_t balance_truck_falling = 0x003f2530;
constexpr uint32_t balance_truck_driving = 0x003f2534;
constexpr uint32_t falling_thwomp = 0x003f1f90;
constexpr uint32_t rising_thwomp = 0x003f1f98;
constexpr uint32_t lift_table = 0x003ca6cc;
constexpr uint32_t coin_table = 0x003d1fd4;
constexpr uint32_t coin_rail_table = 0x003cf6d4;
constexpr uint32_t fish_rail_table = 0x003cc998;
constexpr uint32_t fish_patrol_table = 0x003d4200;
constexpr uint32_t generator_fish_table = 0x003cfd1c;
constexpr uint32_t generator_fish_takeoff = 0x003f3078;
constexpr uint32_t generator_fish_flight = 0x003f307c;
constexpr uint32_t seagull_table = 0x003d3a30;
constexpr uint32_t seagull_flight = 0x003f2b88;
constexpr uint32_t sambo_head_table = 0x003d538c;
constexpr uint32_t sambo_head_patrol = 0x003f2394;
constexpr uint32_t sambo_head_brake = 0x003f2398;
constexpr uint32_t player_damage_guard_table = 0x003d0940;
constexpr uint32_t mystery_rule_table = 0x003cd6e0;
constexpr uint32_t mystery_counting = 0x003f1668;

std::atomic<bool> opted_in{}, enabled{};
std::atomic<uint32_t> tick{}, last_course_tick{}, player_property{};
std::atomic<unsigned> logic_updates{}, timer_steps{}, player_steps{}, guest_buffers{}, active_blanks{};
std::atomic<unsigned> guest_address_swaps{};
std::atomic<unsigned> activation_epoch{};
std::atomic<unsigned> course_sequence{};
std::atomic<uint32_t> goomba_bounce_until{};
std::atomic<uint32_t> damage_entry_until{};
// One atomic stamp keeps the rule identity and its last tick paired for
// the VBlank thread. Zero means this trial has not seen a real timed room.
std::atomic<uint64_t> mystery_heartbeat{};
uint32_t read(uint32_t address) {
    return address && mem::is_committed(address) ? mem::read32(address) : 0;
}
float scalar(uint32_t address) { return std::bit_cast<float>(read(address)); }
uint32_t player() {
    const uint32_t app = read(course_app);
    return app ? read(app + 0x5c) : 0;
}
bool matches_player(uint32_t object, bool gravity) {
    const uint32_t property = player_property.load(std::memory_order_relaxed);
    if (!property || !object) return false;
    uint32_t found = read(object + (gravity ? 4 : 12));
    if (gravity && found) found = read(found);
    return found == property;
}
bool is_player(uint32_t object, bool gravity) {
    return logic60::active() && matches_player(object, gravity);
}
uint32_t nerve(uint32_t actor) {
    const uint32_t state = read(actor + 0x2c);
    return state ? read(state + 4) : 0;
}
bool mystery_clock_enabled() {
    return opted_in.load(std::memory_order_relaxed);
}
bool mystery_timed_rule(uint32_t actor) {
    return read(actor) == mystery_rule_table && nerve(actor) == mystery_counting;
}
struct MysteryAge {
    uint32_t owner{}, raw{}, half{};
    struct Sample { uint32_t prior, whole, steps; bool fresh; };
    constexpr Sample update(uint32_t actor, uint32_t age, bool native) {
        const bool fresh = owner != actor || raw > age;
        if (fresh) *this = {actor, age, 2 * age};
        const auto prior = half / 2;
        const auto steps = age - raw;
        half += steps * (native ? 1u : 2u);
        raw = age;
        return {fresh && prior ? prior - 1 : prior, half / 2, steps, fresh};
    }
};
static_assert([] {
    MysteryAge time;
    if (time.update(1, 0, false).whole != 0 || time.update(1, 1, false).whole != 1) return false;
    if (time.update(1, 2, true).whole != 1 || time.update(1, 3, true).whole != 2) return false;
    const auto paused = time.update(1, 3, false);
    if (paused.prior != 2 || paused.whole != 2 || paused.steps) return false;
    if (time.update(1, 4, false).whole != 3) return false;
    return time.update(1, 0, false).fresh && time.half == 0;
}());
uint32_t velocity_address(uint32_t actor) {
    const uint32_t pose = read(actor + 0x14);
    const uint32_t table = pose ? read(pose) : 0;
    switch (table ? read(table + 8) : 0) {
    case 0x00335064: return pose + 0x2c;
    case 0x00334f78: case 0x003350e0: return pose + 0x28;
    default: return 0;
    }
}
struct MotionBias { uint32_t property{}; std::array<float, 3> acceleration{}; };
thread_local MotionBias bias;
struct Release { uint32_t state{}; bool second{}; bool drag{}; };
thread_local Release release;
struct EnemyStep {
    uint32_t actor{}, nerve{};
    std::array<float, 3> velocity{};
    float retention{};
    bool impulse{};
    std::array<float, 2> forward{};
};
thread_local EnemyStep enemy;
thread_local unsigned legacy_actor_depth{};
struct BalanceMotion {
    uint32_t actor{};
    float rail_delta{};
};
thread_local BalanceMotion balance_motion;
thread_local std::array<float, 3> balance_fall_velocity;
struct BalanceRider {
    uint32_t board{}, player{}, sequence{};
};
thread_local BalanceRider balance_rider;

bool native_boo_state(uint32_t state) {
    switch (state) {
    case 0x003f23cc: case 0x003f23d0: case chasing_boo:
    case 0x003f23f0: case 0x003f23f4: case 0x003f23f8: return true;
    default: return false;
    }
}

bool native_killer_state(uint32_t state) {
    return state == killer_launch || state == killer_flight;
}

bool native_boomerang_state(uint32_t state) {
    return state == 0x003f2f8c || state == braking_boomerang || state == 0x003f2f94 || state == 0x003f2f98;
}

}

void logic60::request() { opted_in.store(true, std::memory_order_relaxed); }

bool logic60::requested() { return opted_in.load(std::memory_order_relaxed); }

bool logic60::active() { return enabled.load(std::memory_order_relaxed); }

extern "C" bool sm3dl60_configured() { return logic60::requested(); }

void logic60::vblank(bool hardware_renderer) {
    if (!sm3dl60_configured()) return;
    static const bool log_clock = std::getenv("SM3DL_FPS") != nullptr;
    const uint32_t now = tick.fetch_add(1, std::memory_order_relaxed) + 1;
    const uint32_t last = last_course_tick.load(std::memory_order_relaxed);
    const bool course_running = last && now - last <= 5;
    const uint64_t mystery = mystery_heartbeat.load(std::memory_order_relaxed);
    const bool mystery_running = mystery_clock_enabled() && mystery && now - uint32_t(mystery) <= 5 &&
                                 mystery_timed_rule(uint32_t(mystery >> 32));
    const uint32_t actor = (course_running || mystery_running) ? player() : 0;
    const uint32_t controller = actor ? read(actor + 0x74) : 0;
    const uint32_t property = controller ? read(controller) : 0;
    player_property.store(property, std::memory_order_relaxed);
    // Never set a new interval in title screens/cinematics. Restore only the interval we changed.
    auto *interval = mem::is_committed(frame_interval) ? mem::ptr(frame_interval) : nullptr;
    const bool previous = active();
    const bool request = hardware_renderer && property != 0 && interval &&
                         now >= damage_entry_until.load(std::memory_order_relaxed) &&
                         (*interval == 2 || (previous && *interval == 1));
    if (request) *interval = 1;
    else if (previous && interval && *interval == 1) *interval = 2;
    if (request != previous) {
        activation_epoch.fetch_add(1, std::memory_order_relaxed);
        enabled.store(request, std::memory_order_relaxed);
        LOG("logic60: %s", request ? "60 Hz course logic enabled" : "original course cadence restored");
    }
    if (request) active_blanks.fetch_add(1, std::memory_order_relaxed);
    if (now % 300 == 0 && log_clock) {
        LOG("logic60: 300 VBlanks: %u native60, %u course updates, %u timer decrements, %u player collision steps, %u new frames, %u address swaps",
            active_blanks.exchange(0), logic_updates.exchange(0), timer_steps.exchange(0),
            player_steps.exchange(0), guest_buffers.exchange(0), guest_address_swaps.exchange(0));
    }
}

namespace {
struct ScanoutClock {
    uint64_t latest{};
    constexpr bool observe(uint64_t serial) {
        if (serial <= latest) return false;
        latest = serial;
        return true;
    }
};
static_assert([] {
    ScanoutClock count;
    return count.observe(1) && count.observe(2) && !count.observe(1) &&
           !count.observe(2) && count.observe(3) && !count.observe(0);
}());
}

void logic60::presented(bool address_changed, uint64_t scanout_sequence) {
    if (!sm3dl60_configured()) return;
    // Mark completed top-LCD blits, not address changes or synthetic images.
    // The same guest framebuffer can contain a new original frame.
    static ScanoutClock clock;
    const bool new_scanout = clock.observe(scanout_sequence);
    const bool fresh = active() ? new_scanout : address_changed;
    if (fresh) guest_buffers.fetch_add(1, std::memory_order_relaxed);
    if (address_changed) guest_address_swaps.fetch_add(1, std::memory_order_relaxed);
}

extern "C" uint32_t sm3dl60_countdown(uint32_t owner, uint32_t amount) {
    if (!sm3dl60_configured() || amount != 1) return amount;
    last_course_tick.store(tick.load(std::memory_order_relaxed), std::memory_order_relaxed);
    logic_updates.fetch_add(1, std::memory_order_relaxed);
    course_sequence.fetch_add(1, std::memory_order_relaxed);
    if (logic60::active()) {
        thread_local uint32_t last_owner{}, last_epoch{};
        thread_local bool skip{};
        const uint32_t epoch = activation_epoch.load(std::memory_order_relaxed);
        if (last_owner != owner || last_epoch != epoch) skip = false;
        last_owner = owner;
        last_epoch = epoch;
        const bool drop = skip;
        skip = !skip;
        if (drop) return 0;
    }
    timer_steps.fetch_add(1, std::memory_order_relaxed);
    return amount;
}

extern "C" uint32_t sm3dl60_mystery_clock(uint32_t actor, uint32_t raw, uint32_t *prior, bool *replace_events) {
    *replace_events = false;
    *prior = raw;
    if (!mystery_clock_enabled() || raw > 900 || !mystery_timed_rule(actor)) return raw;
    const auto now = tick.load(std::memory_order_relaxed);
    const bool native = logic60::active();
    mystery_heartbeat.store((uint64_t(actor) << 32) | now, std::memory_order_relaxed);
    static thread_local MysteryAge state;
    // Waiting at a pause dialog must not reinterpret an already-counted
    // native half-step as a whole original frame when the room resumes.
    const auto [previous, elapsed, steps, fresh] = state.update(actor, raw, native);
    *replace_events = true;
    *prior = previous;
    if (native && steps) {
        course_sequence.fetch_add(steps, std::memory_order_relaxed);
        logic_updates.fetch_add(steps, std::memory_order_relaxed);
        if (elapsed != previous) timer_steps.fetch_add(elapsed - previous, std::memory_order_relaxed);
    }
    return elapsed;
}

extern "C" float sm3dl60_player_step(uint32_t object, bool gravity) {
    if (!is_player(object, gravity)) return 1;
    if (!gravity) player_steps.fetch_add(1, std::memory_order_relaxed);
    return .5f;
}

extern "C" void sm3dl60_goomba_event(uint32_t, uint32_t sensor, uint32_t message) {
    const auto owner = read(sensor + 40);
    const auto mario = player();
    const uint32_t now = tick.load(std::memory_order_relaxed);
    if (logic60::active() && owner == mario && mario && message == 1u)
        goomba_bounce_until.store(now + 22, std::memory_order_relaxed);

}

extern "C" void sm3dl60_player_contact(uint32_t mario, uint32_t, uint32_t message) {
    if (message == 45 && mario && logic60::active() && mario == player()) {
        // The damage freeze suspends the course countdown. It already uses
        // the original cadence while the countdown is suspended; switch at
        // the accepted contact, not several ticks later when the gate notices.
        damage_entry_until.store(tick.load(std::memory_order_relaxed) + 16, std::memory_order_relaxed);
    }

}

extern "C" void sm3dl60_record_acceleration(uint32_t object, uint32_t axis, float delta) {
    if (!is_player(object, true) || !axis || !mem::is_committed(axis + 8) || !std::isfinite(delta)) {
        bias = {};
        return;
    }
    bias.property = player_property.load(std::memory_order_relaxed);
    for (unsigned i = 0; i < 3; ++i) bias.acceleration[i] = .25f * delta * scalar(axis + 4 * i);
}

extern "C" float sm3dl60_movement_bias(uint32_t collider, unsigned axis) {
    if (axis >= 3 || !collider || bias.property != read(collider + 12)) return 0;
    // The stomp launch consumes the incoming vertical velocity before gravity.
    // Two half-steps need the opposite integration correction for that impulse.
    const uint32_t now = tick.load(std::memory_order_relaxed);
    if (axis == 1 && now < goomba_bounce_until.load(std::memory_order_relaxed)) {
        const auto velocity = velocity_address(player());
        if (velocity && scalar(velocity + 4) > 0.f) return -bias.acceleration[axis];
    }
    return bias.acceleration[axis];
}

extern "C" void sm3dl60_reset_release() { release = {}; }

extern "C" bool sm3dl60_release_drag(uint32_t state, bool drag) {
    if (release.state == state && release.second) {
        release.second = false;
        return release.drag;
    }
    release = {state, true, drag};
    return drag;
}

static bool uses_actor_substeps(uint32_t actor, uint32_t table) {
    const auto state = nerve(actor);
    // Use the laboratory's default set of retimed states. Unfinished states
    // (including Bird, Bob-omb and lava columns) stay on their original clock.
    switch (table) {
    case mystery_rule_table: return mystery_clock_enabled() && state == mystery_counting;
    case pata_kuribo_table: return state == pata_kuribo_travel || state == pata_kuribo_wait;
    case balance_truck_table: return state == balance_truck_driving || state == balance_truck_falling;
    case generator_fish_table: return state == generator_fish_takeoff || state == generator_fish_flight;
    case seagull_table: return state == seagull_flight;
    case sambo_head_table: return state == sambo_head_patrol || state == sambo_head_brake;
    case poison_mushroom_table: return state == chasing_poison_mushroom;
    case super_mushroom_table: return state == walking_super_mushroom;
    case needle_plant_table: return state == waiting_needle_plant;
    case teresa_rotor_table: return state == teresa_rotor_turn;
    case needle_block_table: {
        if (state != attached_needle_block || !(read(actor + 132) & 0xffu)) return false;
        const auto attachment = read(actor + 136);
        return attachment && read(attachment + 48);
    }
    case goomba_table: return state == grounded_goomba;
    case koopa_table: return state == grounded_koopa || state == turning_koopa;
    case thwomp_table: return state >= 0x003f1f88 && state <= rising_thwomp && (state & 3u) == 0;
    case dry_bones_table: return state == patrolling_dry_bones || state == turning_dry_bones;
    case boo_table: return native_boo_state(state);
    case killer_table: return native_killer_state(state);
    case killer_variant_table: return state == killer_variant_flight || state == killer_variant_cruise;
    case boomerang_table: return native_boomerang_state(state);
    case killer_launcher_table: return state == 0x003f21ac || state == 0x003f21b0;
    case coin_rail_table: return state == 0x003f2690;
    case coin_table: return state == 0x003f265c && !read(actor + 104) && !read(actor + 108);
    case fish_rail_table: return state == 0x003f234c || state == 0x003f2350 || state == 0x003f2354 || state == 0x003f2358;
    case fish_patrol_table: return state == 0x003f2328 || state == 0x003f232c;
    default: return false;
    }
}

extern "C" bool sm3dl60_legacy_actor(uint32_t actor) {
    if (!logic60::active() || !actor || actor == player()) return false;
    // Actor scripts were written in whole 30 Hz ticks. Only upgrade fully
    // retimed classes. Physics, camera and rendering still run on the course clock.
    const auto table = read(actor);
    return table != lift_table && !uses_actor_substeps(actor, table);
}

extern "C" bool sm3dl60_legacy_actor_tick() {
    // Use the simulation clock, not host refresh count: a missed render does not
    // switch the phase of an object's animation, collision or effect timers.
    return (course_sequence.load(std::memory_order_relaxed) & 1u) == 0;
}

extern "C" bool sm3dl60_hold_damage_timer(uint32_t guard) {
    if (!logic60::active() || sm3dl60_legacy_actor_tick() || !guard ||
        read(guard) != player_damage_guard_table) return false;
    // The original grants 90 whole 30 Hz steps. Keep that duration while
    // running collision geometry and player movement on both half-steps.
    const auto actor = player();
    return actor && read(read(actor + 116) + 56) == guard;
}

extern "C" void sm3dl60_legacy_actor_enter() { ++legacy_actor_depth; }
extern "C" void sm3dl60_legacy_actor_leave() { --legacy_actor_depth; }

extern "C" float sm3dl60_animation_step() { return logic60::active() && !legacy_actor_depth ? .5f : 1.f; }

extern "C" void sm3dl60_actor_before(uint32_t actor) {
    if (!logic60::active() || legacy_actor_depth) return;
    enemy = {};
    const auto table = read(actor);
    if (table != goomba_table && table != koopa_table && table != thwomp_table && table != dry_bones_table &&
        table != boo_table && table != killer_table && table != killer_variant_table && table != boomerang_table &&
        table != super_mushroom_table && table != poison_mushroom_table) return;
    const auto velocity = velocity_address(actor);
    if (velocity) enemy = {actor, nerve(actor), {scalar(velocity), scalar(velocity + 4), scalar(velocity + 8)}};
    if (enemy.actor && table == poison_mushroom_table && enemy.nerve == chasing_poison_mushroom) {
        const auto pose = read(actor + 20);
        if (pose && read(read(pose) + 36) == 0x001db734)
            enemy.forward = {scalar(pose + 16), scalar(pose + 24)};
    }
}

namespace {
constexpr float thwomp_drag = .98f;
constexpr float thwomp_half_drag = .989949494f;
constexpr float thwomp_midpoint = .5f * thwomp_half_drag / (1.f + thwomp_half_drag);
float thwomp_half_distance(float before, float after) {
    return .5f * after + thwomp_midpoint * (after - before);
}
}

extern "C" uint32_t sm3dl60_thwomp_fall(uint32_t actor, uint32_t bits) {
    if (!logic60::active() || legacy_actor_depth || enemy.actor != actor || enemy.nerve != falling_thwomp) return bits;
    // The guest just performed one full drag/acceleration step. Replace the
    // stored velocity and this floor-prediction sample with the exact half-step.
    const auto velocity = velocity_address(actor);
    if (!velocity) return bits;
    const float before = enemy.velocity[1], full = std::bit_cast<float>(bits);
    const float half = thwomp_half_drag * before + (full - thwomp_drag * before) / (1.f + thwomp_half_drag);
    mem::write32(velocity + 4, std::bit_cast<uint32_t>(half));
    return std::bit_cast<uint32_t>(thwomp_half_distance(before, half));
}

extern "C" void sm3dl60_dry_bones_drag(uint32_t actor, uint32_t bits) {
    if (!logic60::active() || legacy_actor_depth || enemy.actor != actor || read(actor) != dry_bones_table ||
        (enemy.nerve != patrolling_dry_bones && enemy.nerve != turning_dry_bones && enemy.nerve != attack_hit_dry_bones)) return;
    enemy.retention = std::bit_cast<float>(bits); // the guest selects ground or air drag
}

extern "C" uint32_t sm3dl60_dry_bones_patrol_clock(uint32_t actor, uint32_t operand, bool timer) {
    if (!logic60::active() || legacy_actor_depth || enemy.actor != actor || read(actor) != dry_bones_table ||
        enemy.nerve != patrolling_dry_bones) return operand;
    // The patrol component is shared by several actors; change only Karon.
    if (timer) return operand <= 0x3fffffffu ? 2 * operand + 2 : operand;
    return std::bit_cast<uint32_t>(.5f * std::bit_cast<float>(operand));
}

extern "C" void sm3dl60_boo_impulse(uint32_t actor) {
    if (logic60::active() && !legacy_actor_depth && enemy.actor == actor && enemy.nerve == chasing_boo)
        enemy.impulse = true;
}

extern "C" void sm3dl60_boo_drag(uint32_t actor, uint32_t bits) {
    if (!logic60::active() || legacy_actor_depth || enemy.actor != actor || enemy.nerve != chasing_boo) return;
    // The pursuer eases speed towards its target, then applies friction.
    // If it did not pursue this tick only the friction term was applied.
    enemy.retention = std::bit_cast<float>(bits) * (enemy.impulse ? .92f : 1.f);
}

extern "C" uint32_t sm3dl60_boo_cooldown(uint32_t actor, uint32_t decremented) {
    return logic60::active() && !legacy_actor_depth && read(actor) == boo_table &&
           native_boo_state(nerve(actor)) && !sm3dl60_legacy_actor_tick() ? decremented + 1 : decremented;
}

static bool killer_native_step(uint32_t actor) {
    if (!logic60::active() || legacy_actor_depth) return false;
    const auto table = read(actor);
    return (table == killer_table || table == killer_variant_table) && uses_actor_substeps(actor, table);
}

extern "C" uint32_t sm3dl60_killer_frames(uint32_t actor, uint32_t frames) {
    const bool launcher = logic60::active() && !legacy_actor_depth && read(actor) == killer_launcher_table;
    return (launcher || killer_native_step(actor)) && frames <= 0x3fffffffu ? 2 * frames : frames;
}

extern "C" bool sm3dl60_killer_half_tick(uint32_t actor) {
    return killer_native_step(actor) && !sm3dl60_legacy_actor_tick();
}

extern "C" float sm3dl60_poison_turn(uint32_t actor, float degrees) {
    return logic60::active() && !legacy_actor_depth && enemy.actor == actor &&
           enemy.nerve == chasing_poison_mushroom ? .5f * degrees : degrees;
}

extern "C" float sm3dl60_super_mushroom_turn(uint32_t actor, float degrees) {
    return logic60::active() && !legacy_actor_depth && enemy.actor == actor &&
           enemy.nerve == walking_super_mushroom ? .5f * degrees : degrees;
}

extern "C" bool sm3dl60_mushroom_half_tick(uint32_t actor) {
    if (!logic60::active() || legacy_actor_depth || sm3dl60_legacy_actor_tick()) return false;
    const auto table = read(actor);
    return (table == super_mushroom_table || table == poison_mushroom_table) &&
           uses_actor_substeps(actor, table);
}

extern "C" uint32_t sm3dl60_actor_delta(uint32_t actor, uint32_t velocity, uint32_t scratch) {
    if (!logic60::active() || legacy_actor_depth || !velocity || !actor || enemy.actor != actor) return velocity;
    const auto step = enemy;
    enemy = {};
    const auto table = read(actor);
    if (table == boomerang_table && native_boomerang_state(step.nerve)) {
        const bool braking = step.nerve == braking_boomerang && nerve(actor) == braking_boomerang;
        for (unsigned axis = 0; axis < 3; ++axis) {
            const float v = scalar(velocity + 4 * axis);
            const float distance = .5f * v + (braking ? .25f * (v - step.velocity[axis]) : 0.f);
            mem::write32(scratch + 4 * axis, std::bit_cast<uint32_t>(distance));
        }
        return scratch;
    }
    if ((table == koopa_table && (step.nerve == grounded_koopa || step.nerve == turning_koopa)) ||
        (table == boo_table && step.nerve != chasing_boo && native_boo_state(step.nerve)) ||
        (table == killer_table && native_killer_state(step.nerve)) ||
        (table == killer_variant_table &&
         (step.nerve == killer_variant_flight || step.nerve == killer_variant_cruise)) ||
        (table == thwomp_table && (step.nerve == falling_thwomp || step.nerve == rising_thwomp))) {
        if (table == thwomp_table && nerve(actor) != step.nerve) return velocity;
        for (unsigned axis = 0; axis < 3; ++axis) {
            const float v = scalar(velocity + 4 * axis);
            const float distance = axis == 1 && table == thwomp_table && step.nerve == falling_thwomp
                ? thwomp_half_distance(step.velocity[1], v) : .5f * v;
            mem::write32(scratch + 4 * axis, std::bit_cast<uint32_t>(distance));
        }
        return scratch;
    }
    const bool goomba = table == goomba_table && step.nerve == grounded_goomba;
    const bool dry_bones = table == dry_bones_table &&
                         (step.nerve == patrolling_dry_bones || step.nerve == turning_dry_bones ||
                          step.nerve == attack_hit_dry_bones) &&
                         (step.retention == .80f || step.retention == .96f);
    const bool boo = table == boo_table && step.nerve == chasing_boo && step.retention > .5f && step.retention <= 1.f;
    const bool super_mushroom = table == super_mushroom_table && step.nerve == walking_super_mushroom &&
                                nerve(actor) == walking_super_mushroom;
    const bool poison = table == poison_mushroom_table && step.nerve == chasing_poison_mushroom &&
                        nerve(actor) == chasing_poison_mushroom;
    if (!goomba && !dry_bones && !boo && !super_mushroom && !poison) return velocity;
    // Split the original recurrence so two half-steps cover the same distance as one full step.
    // The walking Super Mushroom's original ground update retains 90% of its
    // prior velocity and adds a forward impulse (0.72 in this scenario).
    const bool mushroom = super_mushroom || poison;
    const float retention = goomba ? .87f : mushroom ? .90f : step.retention;
    const float half = goomba ? .932737905f : mushroom ? .948683298f :
                       (boo ? std::sqrt(retention) : (retention == .80f ? .894427191f : .979795897f));
    const float midpoint = .5f * half / (1.f + half);
    // The Super Mushroom's terrain response can replace the velocity with
    // a reflection in one tick. It is not an acceleration or drag step:
    // splitting that impulse would almost stop it at each wall.
    const float full_x = scalar(velocity), full_z = scalar(velocity + 8);
    const float old_speed_sq = step.velocity[0] * step.velocity[0] + step.velocity[2] * step.velocity[2];
    const float new_speed_sq = full_x * full_x + full_z * full_z;
    const bool reflected = super_mushroom && old_speed_sq > 1.0f && new_speed_sq > .50f * old_speed_sq &&
        new_speed_sq < 2.f * old_speed_sq && step.velocity[0] * full_x + step.velocity[2] * full_z < 0.f;
    auto rotated = step.velocity;
    if (poison) {
        // The existing AI rotates both direction and velocity together. Apply
        // drag and impulse in that rotated basis, so the guest's half turn
        // isn't accidentally halved again by the acceleration fix.
        const auto pose = read(actor + 20);
        const float x = scalar(pose + 16), z = scalar(pose + 24);
        const float size = std::hypot(x, z) * std::hypot(step.forward[0], step.forward[1]);
        if (size > .5f && std::isfinite(size)) {
            const float c = (step.forward[0] * x + step.forward[1] * z) / size;
            const float s = (step.forward[1] * x - step.forward[0] * z) / size;
            rotated[0] = c * step.velocity[0] + s * step.velocity[2];
            rotated[2] = c * step.velocity[2] - s * step.velocity[0];
        }
    }
    for (unsigned axis = 0; axis < 3; ++axis) {
        if (axis == 1 && goomba) {
            mem::write32(scratch + 4, std::bit_cast<uint32_t>(.5f * scalar(velocity + 4)));
            continue;
        }
        const float before = step.velocity[axis], full = scalar(velocity + 4 * axis);
        if (reflected && axis != 1) {
            mem::write32(scratch + 4 * axis, std::bit_cast<uint32_t>(.5f * full));
            continue;
        }
        const float next = half * rotated[axis] + (full - retention * rotated[axis]) / (1.f + half);
        mem::write32(velocity + 4 * axis, std::bit_cast<uint32_t>(next));
        mem::write32(scratch + 4 * axis, std::bit_cast<uint32_t>(.5f * next + midpoint * (next - before)));
    }
    return scratch;
}

extern "C" uint32_t sm3dl60_rail_rate(uint32_t bits) {
    return logic60::active() && !legacy_actor_depth ? std::bit_cast<uint32_t>(.5f * std::bit_cast<float>(bits)) : bits;
}

static bool native_sambo_patrol(uint32_t actor) {
    return logic60::active() && !legacy_actor_depth && read(actor) == sambo_head_table &&
           uses_actor_substeps(actor, sambo_head_table);
}

extern "C" uint32_t sm3dl60_sambo_ramp_frames(uint32_t actor, uint32_t frames) {
    // Both the acceleration predicate (age <= frames) and the braking
    // predicate (age >= frames, after movement) include the final tick.
    return native_sambo_patrol(actor) && frames <= 0x3fffffffu ? 2 * frames + 1 : frames;
}

extern "C" float sm3dl60_sambo_ramp(uint32_t actor, float factor, bool braking) {
    if (!native_sambo_patrol(actor)) return factor;
    // Two samples of each linear ramp have the same mean as the original
    // full step. The braking callback supplies 15 - age, not raw age.
    if (braking) return std::max(0.f, .5f * factor + 7.75f);
    if (factor < 2.f) return 0.f;
    return .5f * factor - .25f;
}

extern "C" float sm3dl60_sambo_step(uint32_t actor, float distance) {
    return native_sambo_patrol(actor) ? .5f * distance : distance;
}

extern "C" bool sm3dl60_sambo_effect(uint32_t actor) {
    return !native_sambo_patrol(actor) || sm3dl60_legacy_actor_tick();
}

extern "C" float sm3dl60_teresa_rotor_step(float degrees) {
    // Apply half a rotation step, not half of the accumulated orientation.
    // This call site belongs to the turning nerve of this particular floor.
    return logic60::active() && !legacy_actor_depth ? degrees * .5f : degrees;
}

extern "C" uint32_t sm3dl60_actor_transition_duration(uint32_t original) {
    // The guest checks age > N, then commits the new state on its next tick.
    // Match the whole observed N+2 ticks, including the transition boundary.
    return logic60::active() && !legacy_actor_depth && original <= 0x3fffffffu ? 2 * original + 2 : original;
}

extern "C" uint32_t sm3dl60_pata_duration(uint32_t actor, uint32_t original, unsigned period) {
    if (!logic60::active() || legacy_actor_depth || read(actor) != pata_kuribo_table ||
        !uses_actor_substeps(actor, pata_kuribo_table) || original > 0x3fffffffu) return original;
    // Mode 0 is the cubic interpolation denominator. Modes 1 and 2
    // account for the guest's respective >= and > transition tests and
    // the tick on which the new state is committed.
    return 2u * original + period;
}

static bool native_balance_step(uint32_t actor) {
    return logic60::active() && !legacy_actor_depth && read(actor) == balance_truck_table &&
           uses_actor_substeps(actor, balance_truck_table);
}

extern "C" float sm3dl60_balance_tilt_step(uint32_t actor) {
    return native_balance_step(actor) ? .5f : 1.f;
}

extern "C" bool sm3dl60_balance_count_tick(uint32_t actor) {
    return !native_balance_step(actor) || sm3dl60_legacy_actor_tick();
}

extern "C" float sm3dl60_balance_accelerate(uint32_t actor, float whole_velocity) {
    balance_motion = {};
    if (!native_balance_step(actor)) return whole_velocity;
    constexpr float drag = .94f, half = .969535971f;
    const float old = scalar(actor + 0x9c);
    const float next = half * old + (whole_velocity - drag * old) / (1.f + half);
    // The original rail integrates the end-of-step velocity. Include its
    // endpoint bias so a pair of half steps has the same traveled distance.
    balance_motion = {actor, .5f * next + (.5f * half / (1.f + half)) * (next - old)};
    return next;
}

extern "C" float sm3dl60_balance_rail_step(uint32_t actor, float full) {
    const auto motion = balance_motion;
    balance_motion = {};
    return motion.actor == actor ? motion.rail_delta : full;
}

extern "C" float sm3dl60_balance_slope_step(uint32_t actor) {
    return native_balance_step(actor) ? 1.f / (1.f + .969535971f) : 1.f;
}

extern "C" void sm3dl60_balance_leave_rail(uint32_t actor) {
    // A geyser sends this message from its own 30 Hz actor update. The
    // caller's legacy scope must not mask the board's 60 Hz driving state.
    if (!logic60::active() || read(actor) != balance_truck_table ||
        nerve(actor) != balance_truck_driving || !uses_actor_substeps(actor, balance_truck_table)) return;
    // The driving routine stores the actual position difference from the
    // last update. Falling stores velocity in original-tick units instead.
    for (unsigned axis = 0; axis < 3; ++axis) {
        const auto field = actor + 124 + 4 * axis;
        mem::write32(field, std::bit_cast<uint32_t>(2.f * scalar(field)));
    }
}

extern "C" bool sm3dl60_balance_fall_begin(uint32_t actor) {
    if (!native_balance_step(actor) || nerve(actor) != balance_truck_falling) return false;
    for (unsigned axis = 0; axis < 3; ++axis)
        balance_fall_velocity[axis] = scalar(actor + 124 + 4 * axis);
    return true;
}

extern "C" void sm3dl60_balance_fall_delta(uint32_t velocity, uint32_t delta) {
    // The two half-steps reproduce the original end-of-step integration.
    // The rail collision receives only a displacement, not a halved velocity.
    constexpr float drag_root = .997496867f, bias_scale = .5f * drag_root / (1.f + drag_root);
    for (unsigned axis = 0; axis < 3; ++axis) {
        const auto v = scalar(velocity + 4 * axis);
        const auto step = .5f * v + bias_scale * (v - balance_fall_velocity[axis]);
        mem::write32(delta + 4 * axis, std::bit_cast<uint32_t>(step));
    }
}

extern "C" void sm3dl60_balance_rider_contact(uint32_t board, uint32_t receiver, uint32_t sender) {
    if (!native_balance_step(board)) return;
    const auto rider = player();
    if (rider && (read(receiver + 40) == rider || read(sender + 40) == rider))
        balance_rider = {board, rider, course_sequence.load(std::memory_order_relaxed)};
}

extern "C" void sm3dl60_preserve_balance_carry(uint32_t collider, uint32_t surface_delta) {
    if (!balance_rider.board || !is_player(collider, false) || balance_rider.player != player() ||
        course_sequence.load(std::memory_order_relaxed) - balance_rider.sequence > 2 ||
        !native_balance_step(balance_rider.board)) return;
    // This vector was already produced for the current half-step by the
    // platform transform. Only commanded movement needs the generic 0.5
    // multiplier later in the player solver; keep its carry term unchanged.
    for (unsigned axis = 0; axis < 3; ++axis) {
        const auto field = surface_delta + 4u * axis;
        const float value = scalar(field);
        if (std::isfinite(value))
            mem::write32(field, std::bit_cast<uint32_t>(2.f * value));
    }
}

extern "C" uint32_t sm3dl60_camera_duration(uint32_t steps) {
    return logic60::active() ? steps * 2 : steps;
}

extern "C" uint32_t sm3dl60_camera_wave_step() {
    return logic60::active() || !sm3dl60_configured() ? 1u : 2u;
}

extern "C" float sm3dl60_camera_blend(float alpha) {
    // Two half-steps must retain the same amount of the old camera position
    // as a single original step. A snap (alpha = 1) stays a snap.
    return logic60::active() && alpha > 0.f && alpha < 1.f ? 1.f - std::sqrt(1.f - alpha) : alpha;
}

extern "C" uint32_t sm3dl60_lift_duration(uint32_t actor, uint32_t frames, bool inclusive) {
    return logic60::active() && read(actor) == lift_table && frames <= 0x3fffffffu
        ? 2 * frames + unsigned(inclusive) : frames;
}
