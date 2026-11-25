"""Create the versioned GitHub release asset; no ROM or compiled game is included."""
import argparse
import io
import json
import subprocess
import tarfile
import tempfile
from pathlib import Path

from model import APP, VERSION, digest, version_key
from updater import ROOT_NAME


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--revision", required=True, help="Tested game Git commit to publish.")
    parser.add_argument("--output", type=Path, default=APP / "dist" / "launcher-linux")
    args = parser.parse_args()
    args.output = args.output.resolve()
    version_key(VERSION)
    revision = subprocess.check_output(["git", "rev-parse", "--verify", args.revision + "^{commit}"], cwd=APP, text=True).strip()
    args.output.mkdir(parents=True, exist_ok=True)
    asset = args.output / f"Super-Mario-3D-Land-Linux-x64-v{VERSION}.tar.gz"
    with tempfile.TemporaryDirectory(dir=args.output) as folder:
        folder = Path(folder)
        sources = folder / "sources.tar"
        subprocess.run(["git", "archive", "--format=tar", f"--prefix={ROOT_NAME}/source/", f"--output={sources}",
                        revision, "--", "CMakeLists.txt", "BUILD.md", "LICENSE", "build.sh", "licenses", "scripts",
                        "src", "tools"], cwd=APP, check=True)
        temporary = folder / "release.tar.gz"
        with tarfile.open(temporary, "w:gz") as result, tarfile.open(sources) as original:
            def add_file(source, name, executable=False):
                info = result.gettarinfo(str(source), f"{ROOT_NAME}/{name}")
                info.mode = 0o755 if executable else 0o644
                with source.open("rb") as stream:
                    result.addfile(info, stream)
            for member in original:
                result.addfile(member, original.extractfile(member) if member.isfile() else None)
            add_file(APP / "SuperMario3DLandBuilder", "SuperMario3DLandBuilder", True)
            add_file(APP / "BUILD.md", "BUILD.md")
            add_file(APP / "launcher/icon.png", "launcher/icon.png")
            add_file(APP / "launcher/README.md", "launcher/README.md")
            for path in sorted((APP / "launcher/linux").glob("*.py")):
                if path.name not in {"package.py", "test_launcher.py"}:
                    add_file(path, "launcher/linux/" + path.name)
            metadata = json.dumps({"version": VERSION, "game_revision": revision}).encode()
            info = tarfile.TarInfo(f"{ROOT_NAME}/launcher-release.json")
            info.size = len(metadata)
            result.addfile(info, io.BytesIO(metadata))
        temporary.replace(asset)
    print(asset)
    print(f"SHA-256: {digest(asset)}")


if __name__ == "__main__":
    main()
