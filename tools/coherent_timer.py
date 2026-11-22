"""Make the existing guest timer deadlines precise on Windows, without retiming the guest."""


def coherent_timer(source):
    source = source.replace('#include <random>', '#include <random>\n#ifdef _WIN32\n#include <windows.h>\n#endif', 1)
    start = source.index('void timer_loop() {')
    source = source[:start] + '''#ifdef _WIN32
// Win32 condition-variable timeouts can round to the system tick. Use a
// high-resolution waitable timer, interrupted by the same queue notification.
// The Timer object's handles live as long as the detached kernel timer thread.
struct CoherentTimerWait {
    HANDLE changed = nullptr, timer = nullptr;
    CoherentTimerWait() {
        if (std::getenv("SM3DL_COHERENT_COARSE_TIMER")) return;
        constexpr DWORD high_resolution = 0x00000002; // CREATE_WAITABLE_TIMER_HIGH_RESOLUTION
        timer = CreateWaitableTimerExW(nullptr, nullptr, high_resolution, TIMER_MODIFY_STATE | SYNCHRONIZE);
        if (!timer) return; // older Windows: keep the original wait
        changed = CreateEventW(nullptr, FALSE, FALSE, nullptr);
        if (!changed) CloseHandle(timer), timer = nullptr;
    }
};

const CoherentTimerWait &coherent_timer_waiter() {
    static const CoherentTimerWait waiter;
    return waiter;
}

bool coherent_wait(std::unique_lock<std::mutex> &lk, uint64_t ns, bool timed) {
    const auto &waiter = coherent_timer_waiter();
    if (!waiter.timer || !waiter.changed) return false;
    if (timed) {
        LARGE_INTEGER due{};
        due.QuadPart = -LONGLONG(std::max<uint64_t>(1, (ns + 99) / 100));
        if (!SetWaitableTimer(waiter.timer, &due, 0, nullptr, nullptr, FALSE)) return false;
    }
    const HANDLE objects[] = {waiter.changed, waiter.timer};
    lk.unlock();
    const DWORD result = WaitForMultipleObjects(timed ? 2 : 1, objects, FALSE, INFINITE);
    lk.lock();
    return result == WAIT_OBJECT_0 || (timed && result == WAIT_OBJECT_0 + 1);
}
#endif

void notify_timer_queue() {
    k().timer_cv.notify_one();
#ifdef _WIN32
    if (const auto &waiter = coherent_timer_waiter(); waiter.changed) SetEvent(waiter.changed);
#endif
}

''' + source[start:]
    source = source.replace('void timer_loop() {\n    std::unique_lock lk(k().lock);', '''void timer_loop() {
#ifdef _WIN32
    if (coherent_timer_waiter().timer) LOG("timing: high-resolution Windows timer active");
#endif
    std::unique_lock lk(k().lock);''', 1)
    source = source.replace('            k().timer_cv.wait(lk);', '''#ifdef _WIN32
            if (coherent_wait(lk, 0, false)) continue;
#endif
            k().timer_cv.wait(lk);''', 1)
    source = source.replace('            k().timer_cv.wait_for(lk, wait);', '''#ifdef _WIN32
            if (coherent_wait(lk, uint64_t(wait.count()), true)) continue;
#endif
            k().timer_cv.wait_for(lk, wait);''', 1)
    # Notify both kinds of wait, but only when the next deadline gets earlier.
    source = source.replace('    k().timers.emplace(due, std::move(fn));\n    k().timer_cv.notify_one();',
        '''    const bool earlier = k().timers.empty() || due < k().timers.begin()->first;
    k().timers.emplace(due, std::move(fn));
    if (earlier) notify_timer_queue();''', 1)
    source = source.replace('    k().timers.emplace(p->due, *tick);\n    k().timer_cv.notify_one();',
        '''    const bool earlier = k().timers.empty() || p->due < k().timers.begin()->first;
    k().timers.emplace(p->due, *tick);
    if (earlier) notify_timer_queue();''', 1)
    return source
