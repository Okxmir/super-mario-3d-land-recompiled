#!/usr/bin/env python3
"""Super Mario 3D Land graphical launcher for Linux x86-64."""
from __future__ import annotations

import argparse
import os
import platform
import queue
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path

from model import APP, EXE, LANGUAGES, Session, read_ini, rom_file, version_key
from controls import BINDINGS, PAD_NAMES, SdlGamepads, draw_handheld, keyboard_name
import updater

BG, PANEL, SOFT, FG, MUTED, BLUE, GREEN = "#181A1F", "#232730", "#313744", "#F1F3F8", "#ACB6C8", "#425FD1", "#74BF9D"
STAGES = {"Preparing dependencies": 3, "Extracting the ROM": 10, "Recompiling ARM code": 16,
          "Preparing game resources": 22, "Compiling the game": 28, "Running tests": 95,
          "Writing game files": 98, "Installing HD textures": 99}
NINJA = re.compile(r"^\[(\d+)/(\d+)\]")


class Launcher:
    def __init__(self, window, model):
        import tkinter as tk
        from tkinter import filedialog, messagebox, ttk
        self.tk, self.ttk, self.dialog, self.messagebox = tk, ttk, filedialog, messagebox
        self.win, self.model = window, model
        self.events = queue.Queue()
        self.page = "home"
        self.busy = None
        self.checked = not model.packaged
        self.process = None
        self.message = ""
        self.capture = self.pad = self.pad_job = None
        self.pad_mode = False
        self.game_controls = {}
        self.log = []
        self.rom = tk.StringVar(value=model.prefs.get("rom", ""))
        self.language = tk.StringVar(value=model.prefs.get("language", "English"))
        self.hd1080 = tk.BooleanVar(value=model.prefs.get("hd1080", True))
        self.hd4k = tk.BooleanVar(value=model.prefs.get("hd4k", False))
        self.percent = tk.DoubleVar()
        self.caption = tk.StringVar()
        self.status = tk.StringVar()
        window.title("Super Mario 3D Land Recompiled")
        window.geometry("980x652")
        window.minsize(810, 580)
        window.configure(bg=BG)
        window.protocol("WM_DELETE_WINDOW", self.close)
        window.bind("<KeyPress>", self.control_key, add="+")
        self.icon = self.icon_small = None
        try:
            image = tk.PhotoImage(file=str(model.app / "launcher/icon.png"))
            self.icon = image.subsample(11)
            self.icon_small = image.subsample(44)
            window.iconphoto(True, self.icon)
        except tk.TclError:
            pass
        style = ttk.Style(window)
        style.theme_use("clam")
        style.configure("TCombobox", fieldbackground=PANEL, background=SOFT, foreground=FG, arrowcolor=FG)
        style.map("TCombobox", fieldbackground=[("readonly", PANEL)], foreground=[("readonly", FG)],
                  selectbackground=[("readonly", PANEL)], selectforeground=[("readonly", FG)])
        style.configure("Horizontal.TProgressbar", background=GREEN, troughcolor=SOFT, bordercolor=PANEL)
        self.bar = self.frame(window, BG)
        self.bar.pack(fill="x", padx=30, pady=(15, 0))
        self.body = self.frame(window, BG)
        self.body.pack(fill="both", expand=True, padx=42, pady=(12, 24))
        self.show("home")
        window.after(90, self.poll)
        if self.model.packaged:
            window.after(180, self.check_updates)
            window.after(900000, self.periodic_update_check)

    def frame(self, root, color=PANEL):
        return self.tk.Frame(root, bg=color)

    def label(self, root, text="", size=11, color=FG, bg=None, bold=False, **kw):
        return self.tk.Label(root, text=text, font=("TkDefaultFont", size, "bold" if bold else "normal"),
                             bg=bg or root.cget("bg"), fg=color, **kw)

    def button(self, root, text, fn, color=PANEL, fg=FG, **kw):
        return self.tk.Button(root, text=text, command=fn, bg=color, fg=fg, disabledforeground=MUTED,
                              activebackground=SOFT, activeforeground=FG, relief="flat", bd=0,
                              padx=12, pady=7, cursor="hand2", font=("TkDefaultFont", 10, "bold"), **kw)

    def allow(self, button, enabled):
        button.configure(state="normal" if enabled else "disabled")
        return button

    def close(self):
        if self.busy == "build":
            self.messagebox.showinfo("Build in progress", "Keep the launcher open until the build completes.")
            return
        self.cancel_capture()
        self.win.destroy()

    def hero(self, title, detail, action, fn, enabled=True):
        group = self.frame(self.body, BG)
        group.place(relx=.5, rely=.47, anchor="center")
        if self.icon:
            self.label(group, image=self.icon).pack(pady=(0, 17))
        self.label(group, title, 24, bold=True).pack()
        self.label(group, detail, color=MUTED, wraplength=460, justify="center").pack(pady=(8, 19))
        self.allow(self.button(group, action, fn, BLUE, width=21), enabled).pack()
        return group

    def show(self, page):
        if self.page == "controls" and page != "controls":
            self.cancel_capture()
        self.page = page
        for box in (self.bar, self.body):
            for child in box.winfo_children():
                child.destroy()
        if self.icon_small:
            self.label(self.bar, image=self.icon_small).pack(side="left", padx=(0, 6))
        self.label(self.bar, "3D Land Recompiled", bold=True).pack(side="left")
        self.label(self.bar, self.model.version, 9, MUTED).pack(side="left", padx=8)
        self.allow(self.button(self.bar, "⚙ Settings", lambda: self.show("graphics")),
                   not self.model.update_required and self.busy is None).pack(side="right")
        if self.model.update_required:
            self.hero("Launcher update required", self.message or "Checking GitHub for the required update…",
                      "Retry update", self.check_updates, self.busy is None)
        elif page == "home":
            self.home()
        elif page in {"rom", "options", "build"}:
            self.wizard(page)
        else:
            self.settings(page)

    def home(self):
        if self.model.rebuild_required:
            self.hero("Rebuild required", "Rebuild the game from your ROM to apply the latest fixes. Your saves will be kept.",
                      "Rebuild game", lambda: self.show("rom"))
            return
        current = self.model.installation()
        if current is None:
            box = self.hero("Build your game", "Turn your own European copy of Super Mario 3D Land into a native Linux game.",
                            "Set up the game", lambda: self.show("rom"))
            self.allow(self.button(box, "I already built the game", self.link, BG, "#B6C7FC"), self.checked).pack(pady=8)
            self.label(box, "Your ROM and saves stay on this PC.", 9, MUTED).pack()
            return
        box = self.frame(self.body, BG)
        box.place(relx=.5, rely=.44, relwidth=1, anchor="center")
        box.columnconfigure(0, weight=4)
        box.columnconfigure(1, weight=5)
        self.label(box, "Super Mario\n3D Land", 27, bold=True, justify="left").grid(row=0, column=0, sticky="w")
        detail = self.message or ("Game is running." if self.process else "Ready to play · Native Linux x86-64")
        self.label(box, detail, color=MUTED, wraplength=330, anchor="w").grid(row=1, column=0, sticky="w", pady=(10, 7))
        header = self.frame(box, BG)
        header.grid(row=1, column=1, sticky="sew", padx=(20, 0))
        self.label(header, "INSTALLATION", 9, MUTED).pack(side="left")
        self.allow(self.button(header, "+  New build", lambda: self.show("rom"), BG), not self.process).pack(side="right")
        self.button(box, "Save files  ›", lambda: self.open_folder(self.model.save_profile(current) / "games"),
                    anchor="w").grid(row=2, column=0, sticky="nsew", ipady=9)
        card = self.frame(box)
        card.grid(row=2, column=1, sticky="nsew", padx=(20, 0))
        self.label(card, "✓", 18, GREEN).pack(side="left", padx=(12, 8))
        self.label(card, "Super Mario 3D Land\n" + ("Local installation" if current == self.model.game else "Linked game · separate saves"),
                   justify="left").pack(side="left", pady=8)
        buttons = self.frame(box, BG)
        buttons.grid(row=3, column=0, sticky="w", pady=(14, 0))
        self.allow(self.button(buttons, "▶  Play", self.play, GREEN, "#10231A", width=10),
                   self.checked and not self.process and not self.busy).pack(side="left", padx=(0, 8))
        self.button(buttons, "⚙ Settings", lambda: self.show("graphics")).pack(side="left")
        self.button(box, "Open game folder  ↗", lambda: self.open_folder(current), BG, "#B6C7FC").grid(row=3, column=1, sticky="e")

    def open_folder(self, path):
        try:
            path.mkdir(parents=True, exist_ok=True)
            subprocess.Popen(["xdg-open", path], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError as error:
            self.messagebox.showerror("Open folder", str(error))

    def link(self):
        name = self.dialog.askopenfilename(title="Select the Linux game executable", parent=self.win)
        if name:
            try:
                self.model.link(Path(name))
                self.show("home")
            except (ValueError, OSError) as error:
                self.messagebox.showerror("Link game", str(error))

    def play(self):
        if not self.checked or self.process or self.busy:
            return
        try:
            self.process = self.model.play()
        except (OSError, ValueError) as error:
            self.messagebox.showerror("Play", str(error))
        self.show("home")

    def wizard(self, page):
        steps = ("rom", "options", "build")
        index = steps.index(page)
        self.label(self.bar, "   ".join(("1  Game file", "2  Options", "3  Build")), color=MUTED).pack()
        self.label(self.body, ("Your game file", "Installation options", "Build the game")[index], 22, bold=True).pack(anchor="w")
        info = ("Select your decrypted European ROM. The file stays on this PC.",
                "Choose the game language and which textures to download.",
                "The first build prepares tools and dependencies, then runs the game's self-tests.")
        self.label(self.body, info[index], color=MUTED, wraplength=660, justify="left").pack(anchor="w", pady=(4, 12))
        card = self.frame(self.body)
        card.pack(fill="x", ipadx=12, ipady=10)
        if index == 0:
            self.label(card, Path(self.rom.get()).name or "No ROM selected", wraplength=560).pack(side="left", padx=12)
            self.button(card, "Browse…", self.choose_rom).pack(side="right", padx=10)
            self.label(self.body, ".3ds, .cci, .cxi  ·  EUR", 9, MUTED).pack(anchor="w", pady=6)
        if index == 1:
            self.label(card, "Game language", bold=True).pack(anchor="w", padx=12, pady=(8, 3))
            self.ttk.Combobox(card, textvariable=self.language, values=list(LANGUAGES), state="readonly", width=23).pack(anchor="w", padx=12)
            for option, variable in (("Install the 1080p HD pack", self.hd1080), ("Install the 4K HD pack", self.hd4k)):
                self.tk.Checkbutton(card, text=option, variable=variable, bg=PANEL, fg=FG, activebackground=PANEL,
                                    activeforeground=FG, selectcolor=SOFT).pack(anchor="w", padx=12, pady=(8, 0))
            self.label(card, "Textures: Henriko Magnifico · downloads from GitHub", 9, MUTED).pack(anchor="w", padx=12, pady=7)
        if index == 2:
            self.label(card, f"{Path(self.rom.get()).name}  ·  {self.language.get()}", wraplength=650).pack(anchor="w", padx=12, pady=10)
            self.ttk.Progressbar(card, variable=self.percent, maximum=100).pack(fill="x", padx=12)
            self.label(card, textvariable=self.caption, color=MUTED, wraplength=650, justify="left").pack(anchor="w", padx=12, pady=9)
            self.button(self.body, "View build log", lambda: self.show("log"), BG, "#B6C7FC").pack(anchor="e", pady=5)
        bottom = self.frame(self.body, BG)
        bottom.pack(side="bottom", fill="x")
        back = "home" if index == 0 else steps[index - 1]
        self.allow(self.button(bottom, "Back", lambda: self.show(back)), self.busy is None).pack(side="left")
        title = "Build" if index == 2 else "Next"
        action = self.start_build if index == 2 else lambda: self.show(steps[index+1])
        self.allow(self.button(bottom, title, action, BLUE, width=12), rom_file(Path(self.rom.get()))
                   and self.busy is None and (index != 2 or self.checked)).pack(side="right")

    def choose_rom(self):
        name = self.dialog.askopenfilename(title="Select a decrypted European ROM", parent=self.win,
                                         filetypes=[("European ROMs", "*.3ds *.cci *.cxi *.3DS *.CCI *.CXI")])
        if name and rom_file(Path(name)):
            self.rom.set(name)
            self.model.prefs["rom"] = name
            self.model.save()
            self.show("rom")

    def start_build(self):
        if self.busy or not self.checked:
            return
        args = Path(self.rom.get()), self.language.get(), self.hd1080.get(), self.hd4k.get()
        self.model.prefs.update(rom=str(args[0]), language=args[1], hd1080=args[2], hd4k=args[3])
        self.model.save()
        self.busy = "build"
        self.percent.set(0)
        self.started = time.monotonic()
        self.compile_sample = None
        self.caption.set("Preparing dependencies…")
        self.show("build")
        def work():
            try:
                warning = self.model.build(*args, report=lambda line: self.events.put(("line", line)))
                self.events.put(("built", warning))
            except (OSError, ValueError, KeyError) as error:
                self.events.put(("failed", str(error)))
        threading.Thread(target=work, daemon=True).start()

    def check_updates(self):
        if not self.model.packaged or self.busy or self.process:
            return
        self.checked = False
        self.busy = "check"
        self.show(self.page)
        def work():
            try:
                candidate = updater.check()
                required = self.model.required_version
                if candidate and version_key(candidate.version) > version_key(self.model.version) and (
                        not required or version_key(candidate.version) >= version_key(required)):
                    self.model.require(candidate.version)
                    self.events.put(("updating", candidate.version))
                    updater.install(self.model, candidate)
                    self.events.put(("restart", None))
                else:
                    self.events.put(("checked", None))
            except Exception as error:
                self.events.put(("checked", str(error)))
        threading.Thread(target=work, daemon=True).start()

    def periodic_update_check(self):
        self.check_updates()
        self.win.after(900000, self.periodic_update_check)

    def poll(self):
        while not self.events.empty():
            event, data = self.events.get_nowait()
            if event == "line":
                self.log = (self.log + [data])[-300:]
                stage = data.removeprefix("Build stage: ")
                if stage in STAGES:
                    self.percent.set(max(self.percent.get(), STAGES[stage]))
                    self.caption.set(stage)
                if (match := NINJA.match(data)) and 28 <= self.percent.get() < 95:
                    done, total = map(int, match.groups())
                    if 0 < done <= total:
                        now = time.monotonic()
                        if not self.compile_sample:
                            self.compile_sample = (now, done)
                        instant, initial = self.compile_sample
                        self.percent.set(max(self.percent.get(), 28 + 66 * done / total))
                        eta = (now-instant)*(total-done)/(done-initial) if done > initial else None
                        remaining = f" · ~{max(1, round(eta / 60))} min left" if eta is not None and now-instant >= 5 else ""
                        self.caption.set(f"Compiling · {int(self.percent.get())}%{remaining}")
                if data.startswith("HD download: "):
                    self.caption.set(data)
            elif event in {"built", "failed"}:
                self.busy = None
                if event == "built":
                    self.message = "Game ready. An optional HD pack failed; see Log." if data else "Game ready."
                    self.show("home")
                else:
                    self.caption.set(data)
                    self.show("build")
            elif event == "updating":
                self.message = f"Downloading and verifying launcher {data}…"
                self.show("home")
            elif event == "checked":
                self.busy, self.checked = None, True
                if self.model.update_required:
                    self.message = "Could not install the required update. Check your connection and choose Retry update."
                self.show(self.page)
            elif event == "restart":
                self.model.save()
                bootstrap = self.model.install / "SuperMario3DLandBuilder"
                os.execvp("bash", ["bash", str(bootstrap)])
        if self.process and self.process.poll() is not None:
            self.process = None
            if self.page == "home":
                self.show("home")
        self.win.after(110, self.poll)

    def settings(self, page):
        nav = self.frame(self.body, BG)
        nav.pack(fill="x", pady=(0, 10))
        for key, label in (("graphics", "Graphics"), ("controls", "Controls"), ("log", "Log")):
            self.allow(self.button(nav, label, lambda k=key: self.show(k), SOFT if page == key else BG),
                       self.busy != "build" or key == "log").pack(side="left")
        self.button(nav, "Done", lambda: self.show("build" if self.busy == "build" else "home")).pack(side="right")
        if page == "graphics":
            self.graphics()
        elif page == "controls":
            self.control_page()
        else:
            contents = self.tk.Text(self.body, bg="#121419", fg=FG, bd=0, wrap="word")
            contents.pack(fill="both", expand=True)
            try:
                contents.insert("end", self.model.log.read_text(encoding="utf-8")[-40000:])
            except OSError:
                contents.insert("end", "Build output will appear here.")
            contents.configure(state="disabled")

    def graphics(self):
        self.label(self.body, "Graphics settings", 21, bold=True).pack(anchor="w", pady=(0, 12))
        card = self.frame(self.body)
        card.pack(fill="x", ipady=7)
        previous = self.model.prefs.get("graphics", {})
        variables = {}
        choices = (("Frame rate", "fps_target", {"30 FPS": "30", "60 FPS": "60"}, "60"),
                   ("Upscaling", "resolution", {"1×": "1", "2×": "2", "4×": "4"}, "2"),
                   ("Aspect ratio", "aspect_ratio", {"Original (5:3)": "0", "16:9": "1", "21:9": "2"}, "1"),
                   ("Screen layout", "single_screen", {"Stacked screens": "0", "Widescreen": "1"}, "0"),
                   ("Fullscreen", "fullscreen", {"Off": "0", "On": "1"}, "0"),
                   ("VSync", "vsync", {"Off": "0", "On": "1"}, "1"))
        for label, key, names, value in choices:
            row = self.frame(card)
            row.pack(fill="x", padx=12, pady=3)
            self.label(row, label).pack(side="left")
            chosen = previous.get(key, value)
            var = self.tk.StringVar(value=next(name for name, code in names.items() if code == chosen or code == value and chosen not in names.values()))
            variables[key] = var, names
            self.ttk.Combobox(row, textvariable=var, values=list(names), state="readonly", width=24).pack(side="right")
        row = self.frame(card)
        row.pack(fill="x", padx=12, pady=3)
        self.label(row, "HD textures").pack(side="left")
        available = self.model.available_hd(self.model.installation())
        hd = self.tk.StringVar(value=self.model.prefs.get("hd") if self.model.prefs.get("hd") in available else "None")
        self.ttk.Combobox(row, textvariable=hd, values=available, state="readonly", width=24).pack(side="right")
        def save():
            self.model.prefs["graphics"] = {key: names[var.get()] for key, (var, names) in variables.items()}
            self.model.prefs["hd"] = hd.get()
            self.model.save()
            self.show("home")
        self.button(self.body, "Save settings", save, BLUE).pack(anchor="e", pady=12)
        self.label(self.body, "Settings apply on the next launch. Only installed HD packs are shown.", color=MUTED).pack(anchor="w")

    def control_page(self):
        toolbar = self.frame(self.body, BG)
        toolbar.pack(fill="x", pady=(0, 9))
        self.label(toolbar, "Controls", 21, bold=True).pack(side="left", padx=(0, 18))
        self.button(toolbar, "Keyboard & Mouse", lambda: self.mode(False), BLUE if not self.pad_mode else SOFT).pack(side="left", padx=(0, 5))
        self.button(toolbar, "Controller", lambda: self.mode(True), BLUE if self.pad_mode else SOFT).pack(side="left")
        self.button(toolbar, "Reset defaults", self.reset_controls).pack(side="right")
        panel = self.frame(self.body)
        panel.pack(fill="x")
        panel.columnconfigure((0, 2), weight=1)
        left, center, right = (self.frame(panel) for _ in range(3))
        for i, column in enumerate((left, center, right)):
            column.grid(row=0, column=i, sticky="nsew", padx=7, pady=6)
        self.label(left, "LEFT & D-PAD", 9, MUTED, bold=True).pack(anchor="w")
        self.label(right, "RIGHT & ACTION", 9, MUTED, bold=True).pack(anchor="w")
        self.tiles = {}
        current = self.model.installation()
        self.game_controls = read_ini(self.model.profile(current) / "settings.ini") if current is not None else {}
        for i, name in enumerate(BINDINGS):
            if i < 14:
                self.tiles[name] = self.button(left if i < 7 else right, "", lambda k=name: self.begin_capture(k), SOFT, anchor="w")
                self.tiles[name].pack(fill="x", pady=1)
        picture = self.tk.Canvas(center, width=334, height=263, bg=PANEL, highlightthickness=0)
        picture.pack()
        draw_handheld(picture, self.begin_capture)
        move = self.frame(center)
        move.pack(fill="x")
        self.label(move, "CIRCLE PAD", 9, MUTED).pack(pady=(0, 2))
        move_keys = self.frame(move)
        move_keys.pack(fill="x")
        for symbol, name in zip("↑↓←→", list(BINDINGS)[14:]):
            self.tiles[name] = self.button(move_keys, symbol, lambda k=name: self.begin_capture(k), SOFT, width=5)
            self.tiles[name].pack(side="left", expand=True, fill="x", padx=2)
        mode_hint = ("Left stick and R3 are fixed. Physical D-pad Up also uses the reserve item." if self.pad_mode else
                     "Keys use physical QWERTY labels. The mouse controls the touchscreen.")
        self.label(self.body, mode_hint, 9, MUTED).pack(anchor="w", pady=(5, 0))
        self.status.set("Click a mapping or a button on the 3DS. Changes apply next launch.")
        self.label(self.body, textvariable=self.status, color=MUTED, wraplength=690, justify="left").pack(anchor="w", pady=6)
        self.capture_bar = self.frame(self.body, BG)
        self.capture_bar.pack(fill="x")
        self.update_tiles()

    def binding_key(self, name):
        return ("pad_" if self.pad_mode else "key_") + name

    def update_tiles(self):
        for name, tile in self.tiles.items():
            label, key, pad = BINDINGS[name]
            id = self.binding_key(name)
            value = self.model.prefs.get("bindings", {}).get(id, self.game_controls.get(id, pad if self.pad_mode else key))
            value = (PAD_NAMES.get(value, value) if self.pad_mode else "Enter" if value == "Return" else value) or "—"
            prefix = dict(zip(list(BINDINGS)[14:], "↑↓←→")).get(name, label)
            tile.configure(text=f"{prefix}   {value if name != self.capture else '…'}")

    def mode(self, pad):
        self.cancel_capture()
        self.pad_mode = pad
        self.show("controls")

    def begin_capture(self, name):
        self.cancel_capture()
        self.capture = name
        self.update_tiles()
        self.win.focus_set()
        self.button(self.capture_bar, "Cancel", self.cancel_capture).pack(side="right", padx=4)
        self.button(self.capture_bar, "Unbind", lambda: self.assign("")).pack(side="right", padx=4)
        if not self.pad_mode:
            self.status.set(f"Press a key for {BINDINGS[name][0]}. Esc cancels.")
            return
        lookup = {label: id for id, label in PAD_NAMES.items()}
        menu = self.ttk.Combobox(self.capture_bar, values=list(lookup), state="readonly", width=24)
        menu.set("Choose a controller button…")
        menu.pack(side="right")
        menu.bind("<<ComboboxSelected>>", lambda _event: self.assign(lookup[menu.get()]))
        try:
            self.pad = SdlGamepads()
            self.pad_previous = self.pad.sample()
            self.status.set("Press a controller button or choose one. Left stick and R3 are fixed.")
            self.pad_job = self.win.after(33, self.poll_pad)
        except (OSError, AttributeError, RuntimeError):
            self.status.set("Choose a controller button below. Live capture requires a shared SDL3 library.")

    def poll_pad(self):
        self.pad_job = None
        if self.capture is not None and self.pad:
            count, pressed = self.pad.sample()
            old_count, previous = self.pad_previous
            self.pad_previous = count, pressed
            if self.win.focus_get() is not None and count == old_count:
                pressed = (pressed - previous) & PAD_NAMES.keys()
                if pressed:
                    self.assign(sorted(pressed)[0])
                    return
            self.pad_job = self.win.after(33, self.poll_pad)

    def cancel_capture(self):
        if self.pad_job is not None:
            self.win.after_cancel(self.pad_job)
            self.pad_job = None
        if self.pad:
            self.pad.close()
            self.pad = None
        self.capture = None
        if self.page == "controls" and hasattr(self, "capture_bar"):
            for child in self.capture_bar.winfo_children():
                child.destroy()
            self.status.set("Click a mapping or a button on the 3DS. Changes apply next launch.")
            self.update_tiles()

    def assign(self, value):
        if self.capture is None:
            return
        self.model.prefs.setdefault("bindings", {})[self.binding_key(self.capture)] = value
        label = BINDINGS[self.capture][0]
        self.model.save()
        self.cancel_capture()
        self.status.set(f"{label} → {PAD_NAMES.get(value, value) or 'Unbound'} · saved for the next launch.")

    def control_key(self, event):
        if self.capture is None:
            return None
        if event.keysym == "Escape":
            self.cancel_capture()
            return "break"
        if not self.pad_mode:
            if (value := keyboard_name(event)) is not None:
                self.assign(value)
            else:
                self.status.set("That key is reserved or unsupported. Try another key.")
            return "break"

    def reset_controls(self):
        if self.messagebox.askyesno("Reset controls", "Restore the defaults for this input device?"):
            values = self.model.prefs.setdefault("bindings", {})
            for name, (_, key, pad) in BINDINGS.items():
                values[self.binding_key(name)] = pad if self.pad_mode else key
            self.model.save()
            self.cancel_capture()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--build", type=Path, metavar="ROM")
    action.add_argument("--build-menu", action="store_true", help="Open directly to the ROM picker.")
    parser.add_argument("--language", choices=LANGUAGES, default="English")
    parser.add_argument("--hd-textures", action="store_true")
    parser.add_argument("--hd-4k", action="store_true")
    args = parser.parse_args()
    if platform.system() != "Linux" or platform.machine() != "x86_64":
        parser.error("This launcher requires Linux x86-64.")
    model = Session(install=os.environ.get("SM3DL_LAUNCHER_HOME"))
    if args.build:
        try:
            model.prefs.update(rom=str(args.build.resolve()), language=args.language, hd1080=args.hd_textures, hd4k=args.hd_4k)
            model.build(args.build.resolve(), args.language, args.hd_textures, args.hd_4k, print)
            print(model.game / EXE)
            return 0
        except (OSError, ValueError) as error:
            parser.exit(1, f"error: {error}\n")
    try:
        import tkinter as tk
    except ImportError:
        parser.exit(1, "Install Tk for Python (python3-tk on Ubuntu) to use the launcher. See BUILD.md.\n")
    try:
        root = tk.Tk()
    except tk.TclError:
        parser.exit(1, "A graphical desktop is required. Use --build ROM or bash build.sh in a terminal.\n")
    app = Launcher(root, model)
    if args.build_menu:
        app.show("rom")
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
