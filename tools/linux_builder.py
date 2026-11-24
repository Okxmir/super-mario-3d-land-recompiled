#!/usr/bin/env python3
"""Build or launch Super Mario 3D Land on Linux x86-64."""

import argparse
import os
import platform
import queue
import re
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

from hd_pack import configure_hd, DOWNLOAD_PROGRESS, HD_ACTIVE, HD_WARNING


HERE = Path(__file__).resolve().parents[1]
EXE = "SuperMario3DLandRecompiled"
OUTPUT_NAME = "Super-Mario-3D-Land-Recompiled-Linux-x64"
LOCATION_FILE = HERE / "build/linux-game-location.txt"
LOG_FILE = HERE / "build/linux-builder.log"
LANGUAGES = {"English": "en", "French": "fr", "German": "de", "Italian": "it",
             "Spanish": "es", "Dutch": "nl", "Portuguese": "pt", "Russian": "ru"}
STAGES = {
    "Preparing dependencies": 2,
    "Extracting the ROM": 10,
    "Recompiling ARM code": 15,
    "Preparing game resources": 22,
    "Compiling the game": 28,
    "Running tests": 95,
    "Writing game files": 98,
    "Installing HD textures": 99,
}
NINJA_STEP = re.compile(r"^\[(\d+)/(\d+)\] (?:Building|Linking|Generating)\b")


def validate_rom(rom):
    from cartridge import validate_decrypted_rom

    return validate_decrypted_rom(rom)


def replace_text_file(path, content):
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as temp:
        pending = Path(temp.name)
        temp.write(content)
    try:
        pending.replace(path)
    finally:
        pending.unlink(missing_ok=True)


def find_game():
    try:
        folder = Path(LOCATION_FILE.read_text(encoding="utf-8").rstrip("\n"))
        files = (EXE, "SM3DL-EUR.cxi", "mii.romfs", "shared-font.bcfnt")
        if (folder.is_absolute() and all((folder / file).is_file() for file in files)
                and os.access(folder / EXE, os.X_OK)):
            return folder
    except (OSError, ValueError):
        pass
    return None


def build(rom, language, report, hd_textures=False, hd_4k=False):
    rom = validate_rom(rom)
    output = rom.parent / OUTPUT_NAME
    command = ["bash", HERE / "build.sh", "--cartridge", rom, "--language", language,
               "--output-directory", output]
    env = dict(os.environ, NINJA_STATUS="[%f/%t] ", PYTHONUNBUFFERED="1")
    LOG_FILE.parent.mkdir(exist_ok=True)
    with LOG_FILE.open("a", encoding="utf-8", buffering=1) as log:
        log.write("\nStarting a Linux build.\n")
        output_tail = []
        with subprocess.Popen(command, cwd=HERE, env=env, stdin=subprocess.DEVNULL,
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              encoding="utf-8", errors="replace") as child:
            for raw in child.stdout:
                line = raw.rstrip()
                log.write(line + "\n")
                output_tail = [*output_tail[-11:], line]
                report(line)
            if child.wait() != 0:
                detail = next((line for line in reversed(output_tail) if line.startswith("error: ")), "")
                raise ValueError(f"{detail or 'Build failed.'} See build/linux-builder.log.")
        def report_hd(line):
            log.write(line + "\n")
            report(line)

        configure_hd(output, hd_textures, report_hd, four_k=hd_4k)
        replace_text_file(LOCATION_FILE, str(output) + "\n")
    return output


class Progress:
    def __init__(self):
        self.started = time.monotonic()
        self.percent = 0
        self.stage = "Preparing dependencies"
        self.compile_start = None
        self.predicted = None
        self.hd_warning = False
        self.hd_selected = None
        self.hd_status = None

    def update(self, line, now):
        if line.startswith(HD_WARNING):
            self.hd_warning = True
        if line.startswith(HD_ACTIVE):
            self.hd_selected = line.removeprefix(HD_ACTIVE)
        if line.startswith(DOWNLOAD_PROGRESS):
            self.hd_status = line.removeprefix(DOWNLOAD_PROGRESS)
        marker = "Build stage: "
        if line.startswith(marker) and (stage := line[len(marker):]) in STAGES:
            self.stage = stage
            self.percent = max(self.percent, STAGES[stage])
            if stage == "Compiling the game":
                self.compile_start = None
            self.predicted = None
        if self.stage != "Compiling the game" or not (step := NINJA_STEP.match(line)):
            return
        done, total = map(int, step.groups())
        if not 0 < done <= total:
            return
        if self.compile_start is None:
            self.compile_start = (done, now)
        self.percent = max(self.percent, 28 + 66 * done // total)
        first, start = self.compile_start
        if done > first and done - first >= min(5, total - 1) and now - start >= 5:
            self.predicted = now + (now - start) * (total - done) / (done - first)

    def caption(self, now):
        elapsed = f"{int(now - self.started) // 60}:{int(now - self.started) % 60:02}"
        eta = "Estimating time remaining..."
        if self.predicted is not None:
            minutes = max(1, round((self.predicted - now) / 60))
            eta = f"About {minutes} min remaining"
        if self.stage in ("Running tests", "Writing game files", "Installing HD textures"):
            eta = "Finishing..."
        if self.stage == "Installing HD textures" and self.hd_status:
            return f"Installing HD textures: {self.hd_status}\n{elapsed} elapsed"
        return f"{self.stage}\n{elapsed} elapsed  |  {eta}"


def gui(startup_error=None):
    import tkinter as tk
    from tkinter import filedialog, ttk

    try:
        window = tk.Tk()
    except tk.TclError as error:
        raise ValueError("The builder needs a desktop session. Run bash build.sh in a terminal to build without a window.") from error
    window.title("Super Mario 3D Land Builder")
    window.resizable(False, False)
    window.configure(background="#16231e")
    panel = tk.Frame(window, background="#16231e", padx=24, pady=22)
    panel.grid(sticky="nsew")

    def label(text, row, size=10):
        tk.Label(panel, text=text, font=("TkDefaultFont", size), justify="left",
                 bg="#16231e", fg="#eef8ee").grid(row=row, column=0, columnspan=2, sticky="w", pady=(0, 8))

    label("Select a decrypted European ROM", 0, 18)
    label("CTR-P-AREP  |  .3ds, .cci, .cxi", 1)
    label("ROM file", 2)
    rom = tk.StringVar()
    ttk.Entry(panel, textvariable=rom, width=51, state="readonly").grid(row=3, column=0, sticky="ew")
    language = tk.StringVar(value="English")
    label("Game language", 4)
    languages = ttk.Combobox(panel, textvariable=language, values=list(LANGUAGES), state="readonly", width=20)
    languages.grid(row=5, column=0, sticky="w")
    hd_textures = tk.BooleanVar(value=True)
    hd_option = ttk.Checkbutton(panel, text="Install HD textures (1080p, 107 MB)", variable=hd_textures)
    hd_option.grid(row=6, column=0, sticky="w", pady=(10, 0))
    hd_4k = tk.BooleanVar(value=False)
    hd_4k_option = ttk.Checkbutton(panel, text="Install 4K textures (184 MB)", variable=hd_4k)
    hd_4k_option.grid(row=7, column=0, sticky="w")
    progress = ttk.Progressbar(panel, maximum=100)
    progress.grid(row=8, column=0, columnspan=2, sticky="ew", pady=(18, 8))
    message = tk.StringVar(value=startup_error or "The game folder will be created beside the ROM.")
    tk.Label(panel, textvariable=message, bg="#16231e", fg="#eef8ee", justify="left", anchor="w",
             wraplength=355, width=49, height=4).grid(row=9, column=0, sticky="w")

    updates = queue.Queue()
    active = None

    def choose():
        filename = filedialog.askopenfilename(parent=window, title="Select a decrypted European ROM",
                                               filetypes=[("European ROMs", ("*.3ds", "*.cci", "*.cxi",
                                                                             "*.3DS", "*.CCI", "*.CXI"))])
        if filename:
            rom.set(filename)
            button.configure(text="Build", state="disabled")
            progress["value"] = 0
            try:
                validate_rom(Path(filename))
            except (OSError, ValueError) as error:
                message.set(str(error))
            else:
                message.set("European Super Mario 3D Land ROM detected.\nThe game folder will be created beside it.")
                button.configure(state="normal")

    def start():
        nonlocal active
        active = Progress()
        filename, selected = Path(rom.get()), LANGUAGES[language.get()]
        install_hd = hd_textures.get()
        install_4k = hd_4k.get()
        browse.configure(state="disabled")
        languages.configure(state="disabled")
        hd_option.configure(state="disabled")
        hd_4k_option.configure(state="disabled")
        button.configure(text="Build 0%", state="disabled")

        def run():
            try:
                output = build(filename, selected, lambda line: updates.put(("line", line, time.monotonic())),
                               hd_textures=install_hd, hd_4k=install_4k)
            except (OSError, ValueError) as error:
                updates.put(("error", str(error), time.monotonic()))
            else:
                updates.put(("done", output, time.monotonic()))

        threading.Thread(target=run, daemon=True).start()
        poll()

    def poll():
        nonlocal active
        while not updates.empty():
            event, value, timestamp = updates.get()
            if event == "line":
                active.update(value, timestamp)
                continue
            browse.configure(state="normal")
            languages.configure(state="readonly")
            hd_option.configure(state="normal")
            hd_4k_option.configure(state="normal")
            button.configure(text="Build 100%" if event == "done" else "Build", state="normal")
            progress["value"] = 100 if event == "done" else 0
            elapsed = round(timestamp - active.started)
            hd_warning = active.hd_warning
            hd_selected = active.hd_selected
            active = None
            if event == "done":
                result = f"Build complete in {elapsed // 60} min {elapsed % 60} sec."
                if hd_selected:
                    result += f"\nHD textures active: {hd_selected}."
                if hd_warning:
                    result += "\nAn HD pack failed. See the build log or BUILD.md."
                message.set(result + "\nReopen the builder to play.")
            else:
                message.set(value)
        if active is not None:
            progress["value"] = active.percent
            button.configure(text=f"Build {active.percent}%")
            message.set(active.caption(time.monotonic()))
            window.after(200, poll)

    browse = ttk.Button(panel, text="Browse...", command=choose)
    browse.grid(row=3, column=1, padx=(8, 0))
    button = ttk.Button(panel, text="Build", command=start, state="disabled")
    button.grid(row=9, column=1, sticky="e", padx=(8, 0))
    window.protocol("WM_DELETE_WINDOW", lambda: window.iconify() if active is not None else window.destroy())
    browse.focus_set()
    window.mainloop()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--build", type=Path, metavar="ROM")
    action.add_argument("--build-menu", action="store_true", help="Open the menu to select a ROM or change the language.")
    parser.add_argument("--language", choices=LANGUAGES, default="English")
    parser.add_argument("--hd-textures", action="store_true", help="Download and install the optional 1080p textures.")
    parser.add_argument("--hd-4k", action="store_true", help="Download and install the optional 4K textures.")
    args = parser.parse_args()
    if platform.system() != "Linux" or platform.machine() != "x86_64":
        parser.error("This builder requires Linux x86-64.")
    if args.build:
        report = print if sys.stdout is not None else lambda line: None
        try:
            report(build(args.build, LANGUAGES[args.language], report, hd_textures=args.hd_textures,
                         hd_4k=args.hd_4k) / EXE)
        except (OSError, ValueError) as error:
            if sys.stderr is not None:
                print(error, file=sys.stderr)
            return 1
    else:
        startup_error = None
        if not args.build_menu and (folder := find_game()) is not None:
            try:
                os.chdir(folder)
                os.execv(folder / EXE, [str(folder / EXE)])
            except OSError:
                startup_error = "Could not start the compiled game. You can build again."
        try:
            gui(startup_error)
        except ImportError:
            print("Install Tk for Python (python3-tk on Ubuntu) to open the builder.", file=sys.stderr)
            return 1
        except ValueError as error:
            print(error, file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
