"""Build and package Super Mario 3D Land for Linux x86-64."""

import argparse
import hashlib
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile

if sys.platform == "linux":
    import fcntl


ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "build"
UPSTREAM = BUILD / "upstream"
EXTRACTED = ROOT / "extracted"
GENERATED = ROOT / "generated" / "sm3dl-eur"
CLOCKWORK = "3047d9e990be4ac2c84174cb570dfec569c882e9"
XBYAK = "df112862583c2d327c1d9782fd28f53aa675f11d"
ALON = "eab11f6cc03c9df6ba06cd56af1ac28e7cf64a09"
FONT = "f470e0c9d341db73b8a24880295d2eab4cd81660"
LANGUAGES = {"en": 1, "fr": 2, "de": 3, "it": 4, "es": 5, "nl": 8, "pt": 9, "ru": 10}


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def download(name, url, sha256):
    path = UPSTREAM / name
    if path.is_file():
        if digest(path) != sha256:
            raise ValueError(f"SHA-256 mismatch for {path}")
        return path
    print(f"Downloading {name}", flush=True)
    with tempfile.TemporaryDirectory(dir=UPSTREAM) as work:
        candidate = Path(work) / name
        with urllib.request.urlopen(url, timeout=90) as response, candidate.open("wb") as output:
            shutil.copyfileobj(response, output)
        if digest(candidate) != sha256:
            raise ValueError(f"SHA-256 mismatch for {name}")
        candidate.replace(path)
    return path


def github_zip(name, repo, commit, directory, sha256):
    archive = download(name, f"https://codeload.github.com/{repo}/zip/{commit}", sha256)
    target = UPSTREAM / directory
    if not target.is_dir():
        with tempfile.TemporaryDirectory(dir=UPSTREAM) as work:
            with zipfile.ZipFile(archive) as source:
                source.extractall(work)
            (Path(work) / f"{repo.split('/')[-1]}-{commit}").replace(target)
    return target


def release_tar(name, repo, tag, directory, sha256, strip=0):
    archive = download(name, f"https://github.com/{repo}/releases/download/{tag}/{name}", sha256)
    target = UPSTREAM / directory
    if not target.is_dir():
        with tempfile.TemporaryDirectory(dir=UPSTREAM) as work:
            staged = Path(work) / directory
            staged.mkdir()
            subprocess.run(["tar", "-xf", archive, "-C", staged, f"--strip-components={strip}"], check=True)
            staged.replace(target)


def prepare_dependencies():
    UPSTREAM.mkdir(parents=True, exist_ok=True)
    clockwork = github_zip("clockwork-pinned.zip", "watchmakerers/clockwork", CLOCKWORK, "clockwork-master",
                          "7923e82994e3a06f7aa17dfdb2a6e25a608e3495227baf1a0fdbcc32dfbe1ded")
    github_zip("xbyak-pinned.zip", "herumi/xbyak", XBYAK, f"xbyak-{XBYAK}",
               "b0e8d74a5813d4c4d2baa550b889b7f7c2696e471dfb8de1554ce47f7e52d7f8")
    release_tar("SDL3-3.4.0.tar.gz", "libsdl-org/SDL", "release-3.4.0", "SDL3-3.4.0-linux",
                "082cbf5f429e0d80820f68dc2b507a94d4cc1b4e70817b119bbb8ec6a69584b8", strip=1)
    release_tar("linux_dxc_2025_07_14.x86_64.tar.gz", "microsoft/DirectXShaderCompiler", "v1.8.2505.1",
                "dxc-linux-1.8.2505.1", "f2213da1fc99dc8778c8823078e16ba97c7f80f86a1d4520ab1adf4b462bc48c")
    return clockwork


def python(script, *args, cwd=ROOT):
    subprocess.run([sys.executable, script, *args], cwd=cwd, check=True)


def prepare_system_resources():
    source = github_zip("system-archives-pinned.zip", "B3n30/citra_system_archives", FONT,
                        f"citra_system_archives-{FONT}",
                        "2f2072de4026462e786bc0e6040238a6fde356325041cabc4d66f9432f75e3db")
    mii = EXTRACTED / "mii.romfs"
    if not mii.is_file():
        python("mii.py", "-c", "custom", mii, cwd=source / "mii")
    target = EXTRACTED / "shared-font.bcfnt"
    if not target.is_file():
        font = source / "shared_font"
        python("create_png.py", cwd=font)
        for glyph in (font / "reserved_unicode_chars").glob("*.png"):
            shutil.copyfile(glyph, font / glyph.name)
        python("bcfnt.py", "-c", "-y", "-f", "code.bcfnt", cwd=font)
        shutil.copyfile(font / "code.bcfnt", target)


def prepare_game(args, clockwork, alon_patch):
    workspace = BUILD / "linux-tools"
    workspace.mkdir(exist_ok=True)
    for name in ("Cargo.toml", "Cargo.lock"):
        shutil.copy2(clockwork / name, workspace / name)
    for name in ("ctrx", "recomp"):
        shutil.copytree(clockwork / "tools" / name, workspace / "tools" / name, dirs_exist_ok=True)
    python("tools/prepare_recompiler.py", clockwork / "tools/recomp/src", workspace / "tools/recomp/src")
    subprocess.run(["cargo", "build", "--locked", "--release", "--target-dir", workspace / "target"],
                   cwd=workspace, check=True)
    tools = workspace / "target" / "release"

    print("Build stage: Extracting the ROM", flush=True)
    EXTRACTED.mkdir(exist_ok=True)
    cxi = EXTRACTED / "SM3DL-EUR.cxi"
    with tempfile.TemporaryDirectory(dir=EXTRACTED) as work:
        candidate = cxi
        if args.cartridge.resolve() != cxi:
            candidate = Path(work) / cxi.name
            options = ["--key-file", args.key_file.resolve()] if args.key_file else []
            python("tools/cartridge.py", args.cartridge.resolve(), "--extract", candidate, *options)
        python("tools/verify_extraction.py", candidate)
        code = Path(work) / "code"
        subprocess.run([tools / "ctrx", "--code-only", candidate, code], check=True)
        if digest(code / "code.bin") != "e1d7e188ff88467df776c17cec45c44857fadf5b699944baa8cddcae7d939e64":
            raise ValueError("The cartridge does not match the supported European game revision")
        if candidate != cxi:
            candidate.replace(cxi)
        print("Build stage: Recompiling ARM code", flush=True)
        GENERATED.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=GENERATED.parent) as output:
            patched = Path(work) / "alon-eur-code"
            python("tools/relocate_alon.py", alon_patch, code, patched, Path(output) / "alon_eur_payload.inc")
            subprocess.run([tools / "recomp", "emit", patched, output], check=True)
            generated = {file.name: file for file in Path(output).iterdir()}
            for name, file in generated.items():
                existing = GENERATED / name
                if not existing.is_file() or digest(file) != digest(existing):
                    file.replace(existing)
            for file in GENERATED.glob("*.c"):
                if file.name not in generated:
                    file.unlink()


def package(build, language, dist):
    userdata = dist / "userdata"
    userdata.mkdir(parents=True, exist_ok=True)
    with (userdata / "sm3dl-save.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ValueError("Close the game before updating its files.") from error
        licenses = dist / "licenses"
        licenses.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=dist) as work:
            staging = Path(work)
            game_files = (build / "SuperMario3DLandRecompiled", EXTRACTED / "SM3DL-EUR.cxi",
                          EXTRACTED / "shared-font.bcfnt", EXTRACTED / "mii.romfs")
            for source in game_files:
                shutil.copy2(source, staging)
            shutil.copyfile(ROOT / "LICENSE", licenses / "Clockwork.txt")
            shutil.copyfile(ROOT / "licenses/CityHash.txt", licenses / "CityHash.txt")
            shutil.copyfile(UPSTREAM / "SDL3-3.4.0-linux/LICENSE.txt", licenses / "SDL.txt")
            shutil.copyfile(UPSTREAM / f"xbyak-{XBYAK}/COPYRIGHT", licenses / "Xbyak.txt")
            shutil.copyfile(UPSTREAM / f"citra_system_archives-{FONT}/license.txt", licenses / "SystemArchives.txt")
            for source in game_files:
                (staging / source.name).replace(dist / source.name)
            if language is not None:
                settings = userdata / "settings.ini"
                lines = settings.read_text(encoding="utf-8-sig").splitlines() if settings.is_file() else []
                lines = [line for line in lines if line.partition("=")[0].strip() != "language"]
                lines.append(f"language={LANGUAGES[language]}")
                pending = staging / settings.name
                pending.write_text("\n".join(lines) + "\n", encoding="utf-8")
                pending.replace(settings)
                print(f"Game language: {language}")
    print(f"Run {dist / 'SuperMario3DLandRecompiled'}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cartridge", type=Path, required=True)
    parser.add_argument("--language", choices=LANGUAGES)
    parser.add_argument("--key-file", type=Path)
    parser.add_argument("--output-directory", type=Path, default=ROOT / "dist/linux-x64")
    args = parser.parse_args()
    if platform.system() != "Linux" or platform.machine() != "x86_64":
        parser.error("This build requires Linux x86-64.")
    args.cartridge = args.cartridge.expanduser().resolve()
    args.output_directory = args.output_directory.expanduser().resolve()
    if args.output_directory == EXTRACTED:
        parser.error("Choose an output directory outside the extracted files folder.")
    if args.output_directory / "SM3DL-EUR.cxi" == args.cartridge:
        parser.error("Choose an output directory that does not overwrite the input ROM.")
    if not args.cartridge.is_file():
        parser.error(f"cartridge file not found: {args.cartridge}")
    try:
        requirements = ("cargo", "cmake", "ninja", "ctest", "cc", "c++", "pkg-config", "tar")
        missing = [tool for tool in requirements if shutil.which(tool) is None]
        if missing:
            raise ValueError(f"Missing build tools: {', '.join(missing)}. See BUILD.md.")
        try:
            import PIL
            import png
        except ImportError as error:
            raise ValueError("Install Pillow and PyPNG as described in BUILD.md.") from error
        BUILD.mkdir(exist_ok=True)
        with (BUILD / "linux.lock").open("a") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise ValueError("A Linux build is already running in this directory.") from error
            run_build(args)
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"error: {error}\n")


def run_build(args):
    print("Build stage: Preparing dependencies", flush=True)
    clockwork = prepare_dependencies()
    alon_patch = download("alon-60fps-0.2-preview.ips",
                          f"https://raw.githubusercontent.com/AlonBorodAHub/mario-3d-land-60fps/{ALON}/patch/code.ips",
                          "6cdc315748eb2eb1461ed5447bb9fdb65b195d49f4237bd760bbf5166bd2004f")
    prepare_game(args, clockwork, alon_patch)
    print("Build stage: Preparing game resources", flush=True)
    prepare_system_resources()
    print("Build stage: Compiling the game", flush=True)
    build = BUILD / "linux-Release"
    subprocess.run(["cmake", "-S", ROOT, "-B", build, "-G", "Ninja", "-DCMAKE_BUILD_TYPE=Release",
                    "-DSM3DL_FAST_BUILD=OFF"], check=True)
    jobs = os.environ.get("CMAKE_BUILD_PARALLEL_LEVEL") or str(min(4, len(os.sched_getaffinity(0))))
    subprocess.run(["cmake", "--build", build, "--parallel", jobs], check=True)
    print("Build stage: Running tests", flush=True)
    subprocess.run(["ctest", "--test-dir", build, "--output-on-failure", "--no-tests=error"], check=True)
    print("Build stage: Writing game files", flush=True)
    package(build, args.language, args.output_directory)


if __name__ == "__main__":
    main()
