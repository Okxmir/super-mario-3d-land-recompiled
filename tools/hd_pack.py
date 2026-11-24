"""Download and install the optional 1080p and 4K texture packs."""

import argparse
import hashlib
from pathlib import Path, PurePosixPath
from typing import NamedTuple
import re
import shutil
import tempfile
from urllib.request import urlopen
from zipfile import ZipFile


class Pack(NamedTuple):
    label: str
    folder: str
    file_id: str
    sha256: str
    size: int


PACKS = {
    1: Pack("1080p", "sm3dl-1080p-1.2.0b", "1J0aEd7K6DUkNHcYsU42SBmxpNcZpC2Wd",
            "3e395856dcc9df28406002ecec2a5112294087ae003a7494fa82c6109c03e631", 107111023),
    2: Pack("4K", "sm3dl-4k-1.2.0b", "1EG2kf2-_i1k5VCN9foHnS6DkQtdwz80Y",
            "4f989bd08ec6379a06487d8a6a7432730e9dab305cddcfbdf5ea3496b715f759", 183771391),
}
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


def install_pack(userdata, pack, report):
    root = userdata / "hd-textures"
    installed = root / pack.folder
    marker = installed / ".archive-sha256"
    if marker.is_file() and marker.read_text(encoding="ascii").strip() == pack.sha256:
        return
    if installed.exists():
        raise ValueError("The HD texture folder already exists but its installation could not be verified.")
    root.mkdir(parents=True, exist_ok=True)
    report("Build stage: Installing HD textures")
    with tempfile.TemporaryDirectory(prefix=".hd-pack-", dir=root) as temporary:
        work = Path(temporary)
        archive = work / "textures.zip"
        digest = hashlib.sha256()
        total = 0
        url = f"https://drive.usercontent.google.com/download?id={pack.file_id}&export=download&confirm=t"
        report(f"Downloading the {pack.label} texture pack")
        with urlopen(url, timeout=30) as response, archive.open("wb") as output:
            while block := response.read(1 << 20):
                total += len(block)
                if total > pack.size:
                    raise ValueError("The HD texture download exceeded the expected size.")
                digest.update(block)
                output.write(block)
        if total != pack.size or digest.hexdigest() != pack.sha256:
            raise ValueError(f"The download did not match the expected {pack.label} archive.")
        staging = work / "textures"
        staging.mkdir()
        extract_textures(archive, staging)
        (staging / marker.name).write_text(pack.sha256 + "\n", encoding="ascii")
        try:
            staging.rename(installed)
        except OSError:
            if not marker.is_file() or marker.read_text(encoding="ascii").strip() != pack.sha256:
                raise


def configure_hd(game_folder, requested, report, four_k=False):
    userdata = game_folder / "userdata"
    warnings = []
    selected = 0
    for quality, checked in ((1, requested), (2, four_k)):
        if not checked:
            continue
        pack = PACKS[quality]
        try:
            install_pack(userdata, pack, report)
            selected = quality
        except (OSError, ValueError) as error:
            warnings.append(f"{pack.label} textures unavailable: {error}")
            report(warnings[-1])
    settings = userdata / "settings.ini"
    userdata.mkdir(parents=True, exist_ok=True)
    lines = settings.read_text(encoding="utf-8-sig").splitlines() if settings.is_file() else []
    lines = [line for line in lines if line.partition("=")[0].strip() not in ("hd_textures", "hd_quality")]
    lines.append(f"hd_quality={selected}")
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=userdata, delete=False) as file:
        pending = Path(file.name)
        file.write("\n".join(lines) + "\n")
    try:
        pending.replace(settings)
    finally:
        pending.unlink(missing_ok=True)
    return "\n".join(warnings) or None


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("game_folder", type=Path)
    parser.add_argument("--4k", dest="four_k", action="store_true", help="Install the 4K archive instead of 1080p.")
    args = parser.parse_args()
    if configure_hd(args.game_folder, not args.four_k, print, four_k=args.four_k):
        raise SystemExit(1)
