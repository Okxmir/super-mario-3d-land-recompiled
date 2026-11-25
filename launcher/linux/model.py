"""Storage and game lifecycle for the graphical Linux launcher."""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

APP = Path(__file__).resolve().parents[2]
EXE = "SuperMario3DLandRecompiled"
FILES = (EXE, "SM3DL-EUR.cxi", "mii.romfs", "shared-font.bcfnt")
LANGUAGES = {"English": ("en", 1), "French": ("fr", 2), "German": ("de", 3), "Italian": ("it", 4),
             "Spanish": ("es", 5), "Dutch": ("nl", 8), "Portuguese": ("pt", 9), "Russian": ("ru", 10)}
VERSION = "1.1.7"
PACKS = ("None", "1080p", "4K")
VERSION_RE = re.compile(r"(?:0|[1-9][0-9]{0,4})(?:\.(?:0|[1-9][0-9]{0,4})){2}\Z")


def version_key(value):
    if not isinstance(value, str) or not VERSION_RE.fullmatch(value):
        raise ValueError("Invalid launcher version.")
    return tuple(map(int, value.split(".")))


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write_text(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as file:
        pending = Path(file.name)
        file.write(data)
    try:
        pending.replace(path)
    finally:
        pending.unlink(missing_ok=True)


def read_json(path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def read_ini(path):
    try:
        return {key: value for line in path.read_text(encoding="utf-8-sig").splitlines()
                for key, sep, value in [line.partition("=")] if sep and key}
    except (OSError, ValueError):
        return {}


def valid_game(folder):
    return (folder is not None and all((folder / name).is_file() for name in FILES)
            and os.access(folder / EXE, os.X_OK))


def rom_file(path):
    return path.is_file() and path.suffix.lower() in {".3ds", ".cci", ".cxi"}


class Session:
    def __init__(self, app=APP, install=None):
        self.app = Path(app)
        self.install = Path(install).resolve() if install else self.app
        self.source = self.app / "source" if (self.app / "source/build.sh").is_file() else self.app
        self.stamp = read_json(self.app / "launcher-release.json", {})
        if not isinstance(self.stamp, dict):
            self.stamp = {}
        self.version = self.stamp.get("version", VERSION)
        version_key(self.version)
        self.revision = self.stamp.get("game_revision", "checkout")
        self.packaged = bool(self.stamp) and self.source != self.app
        self.root = self.install / "LauncherData"
        self.game = self.root / "Game"
        self.log = self.root / "build.log"
        self.prefs_path = self.root / "launcher-linux.json"
        self.receipt = self.game / ".launcher-build.json"
        self.required = self.root / "required-linux-update.txt"
        prefs = read_json(self.prefs_path, {})
        self.prefs = prefs if isinstance(prefs, dict) else {}
        self._verified = None
        previous = self.prefs.get("version")
        if self.packaged and previous and version_key(previous) < version_key(self.version):
            self.require(self.version)

    def save(self):
        self.prefs["version"] = self.version
        write_text(self.prefs_path, json.dumps(self.prefs, indent=2) + "\n")

    @property
    def required_version(self):
        try:
            value = self.required.read_text(encoding="utf-8").strip()
            version_key(value)
            return value
        except (OSError, ValueError):
            return None

    def require(self, value):
        old = self.required_version
        if not old or version_key(value) > version_key(old):
            write_text(self.required, value + "\n")
            self._verified = None

    @property
    def update_required(self):
        required = self.required_version
        return bool(required and version_key(required) > version_key(self.version))

    def verified_game(self, recheck=False):
        if self._verified is None or recheck:
            record = read_json(self.receipt, {})
            try:
                self._verified = (valid_game(self.game) and isinstance(record, dict)
                                  and record.get("version") == self.version
                                  and record.get("revision") == self.revision
                                  and record.get("sha256") == digest(self.game / EXE))
            except OSError:
                self._verified = False
        return self._verified

    @property
    def rebuild_required(self):
        return bool(self.required_version and not self.update_required and not self.verified_game())

    @property
    def linked(self):
        path = self.prefs.get("linked")
        return Path(path) if isinstance(path, str) and path else None

    def installation(self):
        if self.required_version and self.verified_game():
            return self.game
        return self.linked if valid_game(self.linked) else self.game if valid_game(self.game) else None

    def link(self, path):
        if self.update_required or self.rebuild_required:
            raise ValueError("Rebuild the game before playing.")
        if path.name != EXE or not valid_game(path.parent):
            raise ValueError("Choose the Linux game executable from the complete game folder.")
        self.prefs["linked"] = str(path.parent.resolve())
        self.prefs.pop("save_from", None)
        self.save()

    def profile(self, folder):
        if folder.resolve() == self.game.resolve():
            return self.game / "userdata"
        key = hashlib.sha256(os.fsencode(folder.resolve())).hexdigest()[:24]
        return self.root / "profiles" / key

    def save_profile(self, folder):
        previous = self.prefs.get("save_from")
        if folder.resolve() == self.game.resolve() and previous:
            return self.profile(Path(previous))
        return self.profile(folder)

    def tools(self):
        path = str(self.source / "tools")
        if path not in sys.path:
            sys.path.insert(0, path)
        from hd_pack import configure_hd, pack_ready, PACKS as info
        return configure_hd, pack_ready, info

    def available_hd(self, folder):
        if folder is None:
            return ["None"]
        _, ready, info = self.tools()
        root = self.profile(folder) / "hd-textures"
        return ["None"] + [label for index, label in enumerate(PACKS[1:], 1) if ready(root / info[index].folder)]

    def play(self):
        if self.update_required:
            raise ValueError("Install the required launcher update first.")
        if self.required_version and not self.verified_game(recheck=True):
            raise ValueError("Rebuild the game to apply the latest fixes.")
        folder = self.installation()
        if folder is None:
            raise ValueError("Build or link the game first.")
        profile = self.profile(folder)
        settings = read_ini(profile / "settings.ini")
        settings.update({"fps_target": "60", "resolution": "2", "aspect_ratio": "1", "single_screen": "0",
                         "picture_in_picture": "0", "smart_layout": "0", "swap_screens": "0",
                         "fullscreen": "0", "gpu_renderer": "1", "vsync": "1"})
        settings.update(self.prefs.get("graphics", {}))
        settings.update(self.prefs.get("bindings", {}))
        settings["language"] = LANGUAGES.get(self.prefs.get("language"), LANGUAGES["English"])[1]
        selected = self.prefs.get("hd", "None")
        settings["hd_quality"] = PACKS.index(selected) if selected in self.available_hd(folder) else 0
        write_text(profile / "settings.ini", "".join(f"{key}={value}\n" for key, value in settings.items()))
        return subprocess.Popen([folder / EXE], cwd=folder, env={
            **os.environ, "SM3DL_DATA_DIR": str(profile), "SM3DL_SAVE_DIR": str(self.save_profile(folder))
        }, stdin=subprocess.DEVNULL)

    def build(self, rom, language, hd, four_k, report):
        if self.update_required or not rom_file(rom):
            raise ValueError("A valid ROM and an up-to-date launcher are required.")
        if rom.resolve() == (self.game / "SM3DL-EUR.cxi").resolve():
            raise ValueError("Choose the original ROM, not the compiled game's data file.")
        if self.linked:
            self.prefs["save_from"] = str(self.linked)
            self.save()
        self.root.mkdir(parents=True, exist_ok=True)
        env = {**os.environ, "NINJA_STATUS": "[%f/%t] ", "PYTHONUNBUFFERED": "1"}
        command = ["bash", self.source / "build.sh", "--cartridge", rom, "--language", LANGUAGES[language][0],
                   "--output-directory", self.game]
        with self.log.open("w", encoding="utf-8", buffering=1) as log:
            def emit(line):
                log.write(line + "\n")
                report(line)
            with subprocess.Popen(command, cwd=self.source, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                  stderr=subprocess.STDOUT, encoding="utf-8", errors="replace") as child:
                for line in child.stdout:
                    emit(line.rstrip())
                if child.wait() != 0 or not valid_game(self.game):
                    raise ValueError("Build failed. See the build log for details.")
            warning = None
            if hd or four_k:
                configure, _, _ = self.tools()
                warning = configure(self.game, hd, emit, four_k=four_k)
                packs = self.available_hd(self.game)
                self.prefs["hd"] = "4K" if four_k and "4K" in packs else "1080p" if hd and "1080p" in packs else "None"
            self.prefs.pop("linked", None)
            self.save()
            write_text(self.receipt, json.dumps({"version": self.version, "revision": self.revision,
                         "sha256": digest(self.game / EXE)}) + "\n")
            self._verified = True
            return warning
