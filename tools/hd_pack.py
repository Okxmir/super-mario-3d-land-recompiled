"""Download and install the optional 1080p and 4K texture packs."""

import argparse
import hashlib
import http.client
from pathlib import Path, PurePosixPath
from typing import NamedTuple
import re
import shutil
import tempfile
import time
from urllib.request import Request, urlopen
from uuid import uuid4
from zipfile import BadZipFile, ZipFile


class Pack(NamedTuple):
    label: str
    folder: str
    filename: str
    sha256: str
    size: int


# Pin the assets to their release so a new game release does not move the URLs.
PACK_RELEASE = "https://github.com/Okxmir/super-mario-3d-land-recompiled/releases/download/v1.1.4"
PACKS = {
    1: Pack("1080p", "sm3dl-1080p-1.2.0b", "SM3DL.4K.1.2.0b.1080p.zip",
            "3e395856dcc9df28406002ecec2a5112294087ae003a7494fa82c6109c03e631", 107111023),
    2: Pack("4K", "sm3dl-4k-1.2.0b", "SM3DL.4K.1.2.0b.4K.zip",
            "4f989bd08ec6379a06487d8a6a7432730e9dab305cddcfbdf5ea3496b715f759", 183771391),
}
TEXTURE = re.compile(r"tex1_[0-9]+x[0-9]+_[0-9a-fA-F]{16}_[0-9]+_mip0\.png")
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
PACK_TEXTURES = 297
DOWNLOAD_PROGRESS = "HD download: "
HD_WARNING = "HD download unavailable: "
HD_ACTIVE = "HD selected: "


def pack_ready(folder):
    if folder.is_symlink() or not folder.is_dir():
        return False
    try:
        textures = [p for p in folder.iterdir() if TEXTURE.fullmatch(p.name) and p.is_file()]
        if len(textures) != PACK_TEXTURES:
            return False
        for path in textures:
            with path.open("rb") as image:
                header = image.read(24)
            if len(header) != 24 or not header.startswith(PNG_SIGNATURE) or header[12:16] != b"IHDR":
                return False
    except OSError:
        return False
    return True


def extract_textures(archive, destination):
    with ZipFile(archive) as contents:
        for member in contents.infolist():
            path = PurePosixPath(member.filename)
            if ("0004000000054000" not in path.parts or not TEXTURE.fullmatch(path.name)):
                continue
            with contents.open(member) as source, (destination / path.name).open("xb") as output:
                shutil.copyfileobj(source, output)
    if not pack_ready(destination):
        raise ValueError("The HD texture archive does not contain all 297 expected PNGs.")


def download_pack(archive, pack, report):
    url = f"{PACK_RELEASE}/{pack.filename}"
    last_error = None
    for attempt in range(1, 4):
        if attempt > 1:
            time.sleep(1)
        report(f"{DOWNLOAD_PROGRESS}{pack.label} - connecting to GitHub ({attempt}/3)")
        request = Request(url, headers={"User-Agent": "SM3DL-Builder/1.0", "Accept": "application/zip, application/octet-stream, */*"})
        try:
            digest = hashlib.sha256()
            with urlopen(request, timeout=60) as response, archive.open("wb") as output:
                header = response.read(4)
                if header != b"PK\x03\x04":
                    raise ValueError("GitHub did not return the expected ZIP. Check the release asset or download it manually.")
                digest.update(header)
                output.write(header)
                total, last_progress = len(header), -5
                while block := response.read(1 << 20):
                    total += len(block)
                    if total > pack.size:
                        raise ValueError("The download exceeded the expected ZIP size.")
                    digest.update(block)
                    output.write(block)
                    progress = total * 100 // pack.size
                    if progress >= last_progress + 5 or progress == 100:
                        last_progress = progress
                        report(f"{DOWNLOAD_PROGRESS}{pack.label} - {progress}%")
            if total != pack.size or digest.hexdigest() != pack.sha256:
                raise ValueError(f"The received ZIP did not match the expected {pack.label} archive.")
            return
        except (OSError, http.client.HTTPException, ValueError) as error:
            last_error = error
            report(f"{pack.label} download attempt {attempt} failed: {error}")
    raise ValueError(f"{last_error} See the Manual texture installation section in BUILD.md.")


def archive_digest(path):
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def install_pack(userdata, pack, report, local_zip=None):
    root = userdata / "hd-textures"
    installed = root / pack.folder
    if installed.is_symlink() or (installed.exists() and not installed.is_dir()):
        raise ValueError(f"Move {installed} aside first; it is not an ordinary folder.")
    if pack_ready(installed):
        report(f"{pack.label} textures already installed.")
        return
    root.mkdir(parents=True, exist_ok=True)
    report("Build stage: Installing HD textures")
    with tempfile.TemporaryDirectory(prefix=".hd-pack-", dir=root) as temporary:
        work = Path(temporary)
        archive = local_zip or work / "textures.zip"
        if local_zip is None:
            download_pack(archive, pack, report)
        elif archive.stat().st_size != pack.size or archive_digest(archive) != pack.sha256:
            raise ValueError(f"This ZIP is not the supported {pack.label} v1.2.0b pack.")
        staging = work / "textures"
        staging.mkdir()
        report(f"{DOWNLOAD_PROGRESS}{pack.label} - verifying and unpacking")
        extract_textures(archive, staging)
        (staging / ".archive-sha256").write_text(pack.sha256 + "\n", encoding="ascii")
        backup = None
        if installed.exists():
            if pack_ready(installed):  # Another installer finished first.
                return
            backup = root / f"{pack.folder}.previous-{uuid4().hex[:8]}"
            installed.rename(backup)
        try:
            staging.rename(installed)
        except OSError:
            if backup is not None and not installed.exists():
                backup.rename(installed)
            raise
        if backup is not None:
            report(f"Kept the incomplete previous pack at {backup}.")
        report(f"Installed {pack.label} textures in {installed}.")


def configure_hd(game_folder, requested, report, four_k=False, local_zip=None):
    userdata = game_folder / "userdata"
    warnings = []
    selected = 0
    for quality, checked in ((1, requested), (2, four_k)):
        if not checked:
            continue
        pack = PACKS[quality]
        try:
            install_pack(userdata, pack, report, local_zip)
            selected = quality
        except (OSError, ValueError, BadZipFile) as error:
            warnings.append(f"{HD_WARNING}{pack.label}: {error}")
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
    report(f"{HD_ACTIVE}{PACKS[selected].label if selected else 'None'}")
    return "\n".join(warnings) or None


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("game_folder", type=Path)
    parser.add_argument("--4k", dest="four_k", action="store_true", help="Install the 4K archive instead of 1080p.")
    parser.add_argument("--archive", type=Path, help="Install a ZIP downloaded manually, without a network request.")
    args = parser.parse_args()
    if configure_hd(args.game_folder, not args.four_k, print, four_k=args.four_k, local_zip=args.archive):
        raise SystemExit(1)
