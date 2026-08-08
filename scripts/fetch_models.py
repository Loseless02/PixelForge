#!/usr/bin/env python3
"""Download the Real-ESRGAN ncnn-vulkan runtime into ``vendor/``.

The binary and its weights are ~45 MB, so they are not committed to the
repository. Run this once after cloning:

    python scripts/fetch_models.py

Everything afterwards works offline. Model weights are verified against known
SHA-256 digests; the platform executable is verified on Windows, where the
digest is pinned.
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import stat
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

RELEASE = "v0.2.5.0"
BUILD = "20220424"
BASE = f"https://github.com/xinntao/Real-ESRGAN/releases/download/{RELEASE}"

ASSETS = {
    "win32": f"realesrgan-ncnn-vulkan-{BUILD}-windows.zip",
    "darwin": f"realesrgan-ncnn-vulkan-{BUILD}-macos.zip",
    "linux": f"realesrgan-ncnn-vulkan-{BUILD}-ubuntu.zip",
}

# Weights are identical on every platform.
MODEL_DIGESTS = {
    "models/realesr-animevideov3-x2.bin":
        "548a36f9c3f4ab8da56cd3b13badf23968bee207b396dad14d04b830e5f2ab2d",
    "models/realesr-animevideov3-x2.param":
        "b88ff4f00ebf019a7fdac17fdd45a7fd3665d37509efc5baf2e4da2e24420a04",
    "models/realesr-animevideov3-x3.bin":
        "548a36f9c3f4ab8da56cd3b13badf23968bee207b396dad14d04b830e5f2ab2d",
    "models/realesr-animevideov3-x3.param":
        "d1a5755008791d09b57e3425fc9dd0bd26b00fdf79c606210bc0e693f8230881",
    "models/realesr-animevideov3-x4.bin":
        "548a36f9c3f4ab8da56cd3b13badf23968bee207b396dad14d04b830e5f2ab2d",
    "models/realesr-animevideov3-x4.param":
        "850a248e7c14c27e5bd8cf7265113a9441036a7db63963bb8aa5169d788a435e",
    "models/realesrgan-x4plus-anime.bin":
        "fe01c269cfd10cdef8e018ab66ebe750cf79c7af4d1f9c16c737e1295229bacc",
    "models/realesrgan-x4plus-anime.param":
        "2b8fb6e0ae4d2d85704ca08c119a2f5ea40add4f2ecd512eb7f4cd44b6127ed4",
    "models/realesrgan-x4plus.bin":
        "713ee713b0353afaa27976f0563a64a5043bd70b9bd8936c2e26e25ebcdbcddf",
    "models/realesrgan-x4plus.param":
        "35330ececcea33b6c397a72548e788d5d53becee4734c50b7fada36e89f10a86",
}

BINARY_DIGESTS = {
    "win32": {
        "realesrgan-ncnn-vulkan.exe":
            "07e49f7cbb4ede01ae4dd4c399d3a7e5846e3d2085c3128eff881e55cb7b1a0c",
        "vcomp140.dll":
            "8f72ef2e483465444b2059fc6744d6cb22cd8d8a27f6fa56befd2a42dcd0f78b",
    }
}

# Files shipped in the release that PixelForge does not need.
JUNK = ("input.jpg", "input2.jpg", "onepiece_demo.mp4", "vcomp140d.dll")

ROOT = Path(__file__).resolve().parent.parent
TARGET = ROOT / "vendor" / "realesrgan"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def already_installed() -> bool:
    executable = TARGET / ("realesrgan-ncnn-vulkan.exe" if sys.platform == "win32"
                           else "realesrgan-ncnn-vulkan")
    if not executable.is_file():
        return False
    return all((TARGET / name).is_file() for name in MODEL_DIGESTS)


def download(url: str, destination: Path) -> None:
    print(f"Downloading {url}")
    with urllib.request.urlopen(url) as response:
        total = int(response.headers.get("Content-Length", 0))
        done = 0
        with destination.open("wb") as handle:
            while chunk := response.read(1 << 18):
                handle.write(chunk)
                done += len(chunk)
                if total:
                    percent = done * 100 / total
                    print(f"\r  {percent:5.1f}%  {done >> 20} / {total >> 20} MiB",
                          end="", flush=True)
    print()


def extract(archive: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as zf:
        names = zf.namelist()
        # Some platform archives nest everything under a single top folder.
        roots = {n.split("/", 1)[0] for n in names if "/" in n}
        strip = len(roots) == 1 and not any("/" not in n for n in names)
        for info in zf.infolist():
            if info.is_dir():
                continue
            name = info.filename.split("/", 1)[1] if strip else info.filename
            if not name or Path(name).name in JUNK:
                continue
            out = destination / name
            out.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, out.open("wb") as dst:
                shutil.copyfileobj(src, dst)


def verify() -> list[str]:
    problems: list[str] = []
    expected = dict(MODEL_DIGESTS)
    expected.update(BINARY_DIGESTS.get(sys.platform, {}))
    for name, digest in expected.items():
        path = TARGET / name
        if not path.is_file():
            problems.append(f"missing: {name}")
        elif sha256(path) != digest:
            problems.append(f"checksum mismatch: {name}")
    return problems


def make_executable() -> None:
    if sys.platform == "win32":
        return
    binary = TARGET / "realesrgan-ncnn-vulkan"
    if binary.is_file():
        binary.chmod(binary.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true",
                        help="Re-download even if the files are already present.")
    args = parser.parse_args()

    asset = ASSETS.get(sys.platform)
    if asset is None:
        print(f"No prebuilt Real-ESRGAN binary for platform '{sys.platform}'.",
              file=sys.stderr)
        print("Build ncnn-vulkan yourself and drop it in vendor/realesrgan/.",
              file=sys.stderr)
        return 1

    if already_installed() and not args.force:
        problems = verify()
        if not problems:
            print(f"Already installed in {TARGET}")
            return 0
        print("Existing install failed verification, re-downloading:")
        for problem in problems:
            print(f"  {problem}")

    with tempfile.TemporaryDirectory(prefix="pixelforge-fetch-") as tmp:
        archive = Path(tmp) / asset
        try:
            download(f"{BASE}/{asset}", archive)
        except OSError as exc:
            print(f"Download failed: {exc}", file=sys.stderr)
            return 1
        extract(archive, TARGET)

    make_executable()
    problems = verify()
    if problems:
        print("Verification failed:", file=sys.stderr)
        for problem in problems:
            print(f"  {problem}", file=sys.stderr)
        return 1

    print(f"Installed Real-ESRGAN {RELEASE} into {TARGET}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
