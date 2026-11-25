import io
import json
import os
import tarfile
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from launcher import Launcher
from model import APP, EXE, FILES, Session, digest, read_ini, version_key
from controls import keyboard_name
import updater


class LauncherTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.model = Session(APP, self.root / "launcher with spaces")
        self.linked = self.root / "earlier game"
        self.make_game(self.linked)

    @staticmethod
    def make_game(folder):
        folder.mkdir(parents=True)
        for name in FILES:
            path = folder / name
            path.write_bytes(b"test")
            if name == EXE:
                path.chmod(0o755)

    def test_update_gates_play_and_keeps_linked_saves(self):
        session = self.model
        session.link(self.linked / EXE)
        previous = session.save_profile(self.linked)
        session.require(session.version)
        self.assertTrue(session.rebuild_required)
        with self.assertRaisesRegex(ValueError, "Rebuild"):
            session.play()
        self.make_game(session.game)
        session.prefs.update(save_from=str(self.linked), language="French",
                             bindings={"key_b": "G", "pad_b": "righttrigger"})
        session.receipt.write_text(json.dumps({"version": session.version, "revision": session.revision,
                                              "sha256": digest(session.game / EXE)}))
        self.assertTrue(session.verified_game(recheck=True))
        self.assertEqual(session.installation(), session.game)
        with patch("model.subprocess.Popen") as play:
            session.play()
        self.assertEqual(play.call_args.kwargs["env"]["SM3DL_SAVE_DIR"], str(previous))
        self.assertEqual(read_ini(session.profile(session.game) / "settings.ini")["pad_b"], "righttrigger")
        self.assertEqual(read_ini(session.profile(session.game) / "settings.ini")["language"], "2")
        self.assertFalse((self.linked / "userdata").exists())
        (session.game / EXE).write_bytes(b"modified game")
        with self.assertRaisesRegex(ValueError, "Rebuild"):
            session.play()

    def test_build_bridge_forwards_rom_language_and_isolates_output(self):
        rom = self.root / "European game.3ds"
        rom.write_bytes(b"ROM fixture")
        session = self.model
        session.link(self.linked / EXE)
        self.make_game(session.game)
        with patch("model.subprocess.Popen") as build:
            child = build.return_value.__enter__.return_value
            child.stdout = ["Build stage: Extracting the ROM\n", "Build stage: Writing game files\n"]
            child.wait.return_value = 0
            lines = []
            session.build(rom, "German", False, False, lines.append)
        command = build.call_args.args[0]
        self.assertEqual(command[command.index("--cartridge") + 1], rom)
        self.assertEqual(command[command.index("--language") + 1], "de")
        self.assertEqual(command[command.index("--output-directory") + 1], session.game)
        self.assertTrue(session.verified_game())
        self.assertIn("Build stage: Writing game files", lines)
        self.assertEqual(session.save_profile(session.game), session.profile(self.linked))

    def test_update_select_and_secure_archive(self):
        major, minor, patch = version_key(self.model.version)
        version = f"{major}.{minor}.{patch + 1}"
        asset = f"Super-Mario-3D-Land-Linux-x64-v{version}.tar.gz"
        endpoint = f"https://github.com/{updater.REPO}/releases/download/v1/{asset}"
        with self.subTest("fixture package"):
            archive = self.root / asset
            with tarfile.open(archive, "w:gz") as tar:
                files = {"launcher-release.json": json.dumps({"version": version, "game_revision": "a" * 40}).encode(),
                         "launcher/linux/launcher.py": b"# launcher",
                         "source/build.sh": b"#!/bin/sh", "source/tools/build_linux.py": b"# build",
                         "SuperMario3DLandBuilder": b"#!/bin/sh"}
                for name, data in files.items():
                    item = tarfile.TarInfo("SM3DL-Launcher/" + name)
                    item.size = len(data)
                    tar.addfile(item, io.BytesIO(data))
            metadata = {"name": asset, "state": "uploaded", "size": archive.stat().st_size,
                        "digest": "sha256:" + digest(archive), "browser_download_url": endpoint}
            release = updater.select([{"tag_name": "v1", "assets": [metadata]}])
            self.assertEqual(release.version, version)
            legacy_asset = f"SM3DL-Launcher-Linux-x64-v{version}.tar.gz"
            legacy = {**metadata, "name": legacy_asset, "browser_download_url":
                      f"https://github.com/{updater.REPO}/releases/download/v1/{legacy_asset}"}
            self.assertEqual(updater.select([{"tag_name": "v1", "assets": [legacy]}]).version, version)
            self.assertIsNone(updater.select([{"tag_name": "v1", "prerelease": True, "assets": [metadata]}]))
            self.assertIsNone(updater.select([{"tag_name": "v1", "assets": [
                {**metadata, "browser_download_url": "https://example.invalid/" + asset}]}]))
            self.model.require(release.version)
            updater.stage_archive(self.model, release, archive)
            pointer = (self.model.root / "active-linux-launcher.txt").read_text().strip()
            app = self.model.root / "launcher-updates" / pointer
            self.assertTrue((app / "source/build.sh").is_file())
            self.assertTrue(self.model.update_required)
            self.assertTrue(Session(app, self.model.install).rebuild_required)
        with self.subTest("archive traversal"):
            broken = self.root / "bad.tar.gz"
            with tarfile.open(broken, "w:gz") as tar:
                name = tarfile.TarInfo("SM3DL-Launcher/../outside")
                tar.addfile(name, io.BytesIO())
            with self.assertRaisesRegex(ValueError, "Unexpected file"):
                updater.stage_archive(self.model, updater.Release(version, endpoint, broken.stat().st_size,
                                                                     digest(broken)), broken)
            self.assertFalse((self.model.root / "outside").exists())

    def test_keyboard_cases(self):
        self.assertEqual(keyboard_name(SimpleNamespace(keysym="g", keycode=42)), "G")
        self.assertIsNone(keyboard_name(SimpleNamespace(keysym="Tab", keycode=23)))

    @unittest.skipUnless(os.getenv("SM3DL_TEST_ASSET"), "An actual release archive was not supplied")
    def test_generated_release_can_be_installed(self):
        archive = Path(os.environ["SM3DL_TEST_ASSET"])
        version = self.model.version
        self.model.version = "0.0.0"
        self.model.require(version)
        updater.stage_archive(self.model, updater.Release(version, "https://github.com/", archive.stat().st_size,
                                                           digest(archive)), archive)
        pointer = (self.model.root / "active-linux-launcher.txt").read_text().strip()
        app = self.model.root / "launcher-updates" / pointer
        installed = Session(app, self.model.install)
        self.assertEqual(installed.version, version)
        self.assertTrue(installed.rebuild_required)
        self.assertEqual(installed.root, self.model.root)
        for path in ("SuperMario3DLandBuilder", "source/build.sh"):
            self.assertFalse(b"\r\n" in (app / path).read_bytes())
        self.assertFalse(any(p.suffix.lower() in {".3ds", ".cci", ".cxi", ".exe"} for p in app.rglob("*") if p.is_file()))

    @unittest.skipUnless(os.getenv("SM3DL_TEST_TK") == "1", "Run only when a desktop is available")
    def test_graphical_pages_and_keyboard_profile(self):
        import tkinter as tk
        window = tk.Tk()
        window.withdraw()
        self.addCleanup(window.destroy)
        app = Launcher(window, self.model)
        for page in ("home", "rom", "options", "build", "graphics", "log", "controls"):
            app.show(page)
            window.update_idletasks()
        app.begin_capture("b")
        self.assertEqual(app.control_key(SimpleNamespace(keysym="g", keycode=42)), "break")
        self.assertEqual(self.model.prefs["bindings"]["key_b"], "G")


if __name__ == "__main__":
    unittest.main()
