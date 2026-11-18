"""Download and install the optional 1080p textures from the author's pack."""

import argparse
import hashlib
from pathlib import Path, PurePosixPath
import re
import shutil
import tempfile
from urllib.request import urlopen
from zipfile import ZipFile


PACK_URL = ("https://drive.usercontent.google.com/download?"
            "id=1J0aEd7K6DUkNHcYsU42SBmxpNcZpC2Wd&export=download&confirm=t")
PACK_SHA256 = "3e395856dcc9df28406002ecec2a5112294087ae003a7494fa82c6109c03e631"
PACK_SIZE = 107111023
PACK_NAME = "sm3dl-1080p-1.2.0b"
TEXTURE = re.compile(r"tex1_[0-9]+x[0-9]+_[0-9a-fA-F]{16}_[0-9]+_mip0\.png")


def extract_textures(archive, destination):
    with ZipFile(archive) as contents:
        for member in contents.infolist():
            path = PurePosixPath(member.filename)
            if ("0004000000054000" not in path.parts or not TEXTURE.fullmatch(path.name)):
                continue
            with contents.open(member) as source, (destination / path.name).open("xb") as output:
                shutil.copyfileobj(source, output)
    if len(list(destination.glob("*.png"))) != 297:
        raise ValueError("The HD texture archive has an unexpected file list.")


def install_pack(userdata, report):
    root = userdata / "hd-textures"
    installed = root / PACK_NAME
    marker = installed / ".archive-sha256"
    if marker.is_file() and marker.read_text(encoding="ascii").strip() == PACK_SHA256:
        return
    if installed.exists():
        raise ValueError("The HD texture folder already exists but its installation could not be verified.")
    root.mkdir(parents=True, exist_ok=True)
    report("Build stage: Installing HD textures")
    with tempfile.TemporaryDirectory(prefix=".hd-pack-", dir=root) as temporary:
        work = Path(temporary)
        archive = work / "1080p.zip"
        digest = hashlib.sha256()
        total = 0
        with urlopen(PACK_URL, timeout=30) as response, archive.open("wb") as output:
            while block := response.read(1 << 20):
                total += len(block)
                if total > PACK_SIZE:
                    raise ValueError("The HD texture download exceeded the expected size.")
                digest.update(block)
                output.write(block)
        if total != PACK_SIZE or digest.hexdigest() != PACK_SHA256:
            raise ValueError("The HD texture download did not match the expected 1080p archive.")
        staging = work / "textures"
        staging.mkdir()
        extract_textures(archive, staging)
        (staging / marker.name).write_text(PACK_SHA256 + "\n", encoding="ascii")
        try:
            staging.rename(installed)
        except OSError:
            if not marker.is_file() or marker.read_text(encoding="ascii").strip() != PACK_SHA256:
                raise


def configure_hd(game_folder, requested, report):
    userdata = game_folder / "userdata"
    warning = None
    try:
        if requested:
            install_pack(userdata, report)
    except (OSError, ValueError) as error:
        warning = "HD textures unavailable. The game was built with original textures."
        report(f"{warning} {error}")
    settings = userdata / "settings.ini"
    userdata.mkdir(parents=True, exist_ok=True)
    lines = settings.read_text(encoding="utf-8-sig").splitlines() if settings.is_file() else []
    lines = [line for line in lines if line.partition("=")[0].strip() != "hd_textures"]
    lines.append(f"hd_textures={int(requested and warning is None)}")
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=userdata, delete=False) as file:
        pending = Path(file.name)
        file.write("\n".join(lines) + "\n")
    try:
        pending.replace(settings)
    finally:
        pending.unlink(missing_ok=True)
    return warning


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("game_folder", type=Path)
    args = parser.parse_args()
    if configure_hd(args.game_folder, True, print):
        raise SystemExit(1)
