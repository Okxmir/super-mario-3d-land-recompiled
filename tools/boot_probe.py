"""Run a bounded native boot test with isolated save data."""

import argparse
import ctypes
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def restrict_affinity(process, count):
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetProcessAffinityMask.argtypes = (
        ctypes.c_void_p, ctypes.POINTER(ctypes.c_size_t), ctypes.POINTER(ctypes.c_size_t))
    kernel.SetProcessAffinityMask.argtypes = (ctypes.c_void_p, ctypes.c_size_t)
    allowed, system = ctypes.c_size_t(), ctypes.c_size_t()
    handle = int(process._handle)
    if not kernel.GetProcessAffinityMask(handle, ctypes.byref(allowed), ctypes.byref(system)):
        raise ctypes.WinError(ctypes.get_last_error())
    mask = 0
    bits = allowed.value
    for _ in range(count):
        bit = bits & -bits
        if not bit:
            raise ValueError("The requested CPU count exceeds the process affinity")
        mask |= bit
        bits ^= bit
    if not kernel.SetProcessAffinityMask(handle, mask):
        raise ctypes.WinError(ctypes.get_last_error())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=float, default=15)
    parser.add_argument("--graphics", action="store_true")
    parser.add_argument("--screenshot", help="Frame number or frame:interval:count")
    parser.add_argument("--press", help="Frame-based button sequence for the runtime")
    parser.add_argument("--state", default="probe-userdata")
    parser.add_argument("--trace", default="")
    parser.add_argument("--cpu", action="store_true")
    parser.add_argument("--resolution", choices=(1, 2, 4), type=int)
    parser.add_argument("--logical-cpus", choices=(1, 2, 4), type=int)
    parser.add_argument("--log", default="boot-probe")
    args = parser.parse_args()
    for name in (args.state, args.log):
        if Path(name).name != name:
            parser.error("State and log names must be filenames")

    logs = ROOT / "logs"
    logs.mkdir(exist_ok=True)
    state = ROOT / "build" / args.state
    env = os.environ.copy()
    env.update(SM3DL_DATA_DIR=str(state), SM3DL_NO_DIALOG="1", SM3DL_FPS="1",
               RECOMP_TRACE=args.trace)
    if args.graphics:
        env["SM3DL_TEST_HIDDEN"] = "1"
        env.pop("SM3DL_HEADLESS", None)
    else:
        env["SM3DL_HEADLESS"] = "1"
    settings = {}
    if args.cpu:
        settings["gpu_renderer"] = 0
    if args.resolution:
        settings["resolution"] = args.resolution
    state.mkdir(parents=True, exist_ok=True)
    path = state / "settings.ini"
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    lines = [line for line in lines if line.partition("=")[0] not in settings]
    lines.extend(f"{key}={value}" for key, value in settings.items())
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    if args.press:
        env["SM3DL_PRESS"] = args.press
    if args.screenshot:
        env["SM3DL_WINDOW_SCREENSHOT"] = str(logs / f"{args.log}-") + ":" + args.screenshot
    command = [ROOT / "dist/SuperMario3DLandRecompiled.exe"]
    with (logs / f"{args.log}.txt").open("wb") as output:
        with subprocess.Popen(command, env=env, stdout=output, stderr=subprocess.STDOUT,
                              creationflags=subprocess.CREATE_NO_WINDOW) as process:
            try:
                if args.logical_cpus:
                    restrict_affinity(process, args.logical_cpus)
                code = process.wait(timeout=args.seconds)
                output.write(f"\nGame exited with code {code}.\n".encode())
                return code
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
                output.write(f"\nProbe ended after {args.seconds} seconds.\n".encode())
                return 124
            except (OSError, ValueError):
                process.kill()
                process.wait()
                raise


if __name__ == "__main__":
    raise SystemExit(main())
