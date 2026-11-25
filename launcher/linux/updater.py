"""Verify and stage public Linux launcher releases without touching saves."""
from __future__ import annotations

import json
import re
import shutil
import tarfile
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from urllib.request import Request, build_opener, HTTPRedirectHandler
from urllib.parse import urlsplit

from model import version_key, digest, write_text, read_json

REPO = "Okxmir/super-mario-3d-land-recompiled"
API = f"https://api.github.com/repos/{REPO}/releases?per_page=20"
ROOT_NAME = "SM3DL-Launcher"
NAME = re.compile(r"(?:Super-Mario-3D-Land|SM3DL-Launcher)-Linux-x64-v([0-9.]+)\.tar\.gz\Z")
TAG = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}\Z")
SHA = re.compile(r"[0-9a-fA-F]{64}\Z")
MAX_SIZE = 32 * 1024 * 1024
HOSTS = {"github.com", "release-assets.githubusercontent.com", "objects.githubusercontent.com"}


@dataclass(frozen=True)
class Release:
    version: str
    url: str
    size: int
    sha256: str


def select(releases):
    best = None
    for item in releases:
        tag = item.get("tag_name") or ""
        if item.get("draft") or item.get("prerelease") or not TAG.fullmatch(tag):
            continue
        for asset in item.get("assets", ()):
            name = asset.get("name") or ""
            match = NAME.fullmatch(name)
            published_digest = asset.get("digest") or ""
            sha = published_digest.removeprefix("sha256:") if published_digest.startswith("sha256:") else ""
            size = asset.get("size")
            expected = f"https://github.com/{REPO}/releases/download/{tag}/{name}"
            if (not match or asset.get("state") != "uploaded" or not SHA.fullmatch(sha)
                    or type(size) is not int or not 0 < size <= MAX_SIZE or asset.get("browser_download_url") != expected):
                continue
            try:
                version = version_key(match.group(1))
            except ValueError:
                continue
            if best is None or version > version_key(best.version):
                best = Release(match.group(1), expected, size, sha.lower())
    return best


def check():
    class NoRedirect(HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None
    with build_opener(NoRedirect()).open(Request(API, headers={"User-Agent": "SM3DL-Launcher-Linux",
                                    "Accept": "application/vnd.github+json"}), timeout=6) as response:
        data = response.read(2 * 1024 * 1024 + 1)
    if len(data) > 2 * 1024 * 1024:
        raise ValueError("GitHub's response is too large.")
    return select(json.loads(data))


def trusted(url):
    parts = urlsplit(url)
    return parts.scheme == "https" and parts.hostname in HOSTS and parts.port in (None, 443) and parts.username is None


def download(release, path):
    class CheckedRedirect(HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            if not trusted(newurl):
                raise ValueError("The update redirected outside GitHub.")
            return super().redirect_request(req, fp, code, msg, headers, newurl)
    if not trusted(release.url):
        raise ValueError("Unrecognized update server.")
    request = Request(release.url, headers={"User-Agent": "SM3DL-Launcher-Linux", "Accept": "application/octet-stream"})
    with build_opener(CheckedRedirect()).open(request, timeout=15) as response, path.open("xb") as output:
        total = 0
        while chunk := response.read(128 * 1024):
            total += len(chunk)
            if total > release.size:
                raise ValueError("Unexpected update file size.")
            output.write(chunk)
    if total != release.size:
        raise ValueError("The update download was incomplete.")


def stage_archive(session, release, archive):
    if archive.stat().st_size != release.size or digest(archive) != release.sha256:
        raise ValueError("The update did not match GitHub's SHA-256.")
    if version_key(release.version) <= version_key(session.version):
        raise ValueError("Cannot downgrade the launcher.")
    builds = session.root / "launcher-updates"
    builds.mkdir(parents=True, exist_ok=True)
    target = f"version-{release.version}-{release.sha256[:12]}"
    with tempfile.TemporaryDirectory(dir=builds) as temp:
        root = Path(temp)
        total = 0
        seen = set()
        with tarfile.open(archive, mode="r:gz") as tar:
            for member in tar:
                p = PurePosixPath(member.name)
                if (not p.parts or p.parts[0] != ROOT_NAME or ".." in p.parts or "\\" in member.name or
                        ":" in member.name or p in seen or not (member.isfile() or member.isdir())):
                    raise ValueError("Unexpected file in the launcher archive.")
                seen.add(p)
                if len(seen) > 4096:
                    raise ValueError("The update contains too many files.")
                destination = root.joinpath(*p.parts)
                if member.isdir():
                    destination.mkdir(parents=True, exist_ok=True)
                    continue
                total += member.size
                if total > 64 * 1024 * 1024:
                    raise ValueError("The extracted update is too large.")
                destination.parent.mkdir(parents=True, exist_ok=True)
                with tar.extractfile(member) as source, destination.open("xb") as output:
                    shutil.copyfileobj(source, output)
                destination.chmod(0o755 if member.mode & 0o111 else 0o644)
        payload = root / ROOT_NAME
        metadata = read_json(payload / "launcher-release.json", {})
        if (not isinstance(metadata, dict) or metadata.get("version") != release.version or
                not re.fullmatch(r"[0-9a-f]{40}", metadata.get("game_revision", "")) or
                not all((payload / file).is_file() for file in ("launcher/linux/launcher.py", "source/build.sh",
                                                               "source/tools/build_linux.py", "SuperMario3DLandBuilder"))):
            raise ValueError("The update is not the advertised Linux launcher release.")
        final = builds / target
        if final.exists():
            # Keep prior builds intact; reattempts install into their own verified destination.
            target += "-" + root.name.removeprefix("tmp")
            final = builds / target
        payload.replace(final)
        write_text(session.root / "active-linux-launcher.txt", target + "\n")


def install(session, release):
    session.root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=session.root) as folder:
        archive = Path(folder) / "launcher.tar.gz"
        download(release, archive)
        stage_archive(session, release, archive)
