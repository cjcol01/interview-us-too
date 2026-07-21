"""Packages extension/ into static/extension/interviewace-extension.zip for the
manual-install fallback page (/install-manual, gated by SIDELOAD_ENABLED).

Run this after any change to extension/ and commit the resulting zip — it's
served both same-origin and via jsDelivr's CDN fronting this repo. After
committing, purge jsDelivr's cache (see config.py SIDELOAD_ZIP_URL comment).

Usage: python scripts/build_extension_zip.py
"""
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = ROOT / "extension"
OUT_PATH = ROOT / "static" / "extension" / "interviewace-extension.zip"


def build():
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    files = sorted(p for p in SRC_DIR.rglob("*") if p.is_file())
    with zipfile.ZipFile(OUT_PATH, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in files:
            zf.write(path, arcname=str(Path("interviewace-extension") / path.relative_to(SRC_DIR)))
    print(f"Wrote {OUT_PATH} ({len(files)} files, {OUT_PATH.stat().st_size / 1024:.1f} KB)")


if __name__ == "__main__":
    build()
