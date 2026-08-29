#!/usr/bin/env python3
"""
Build the Chrome extension for dev or prod.

Usage:
    python build_extension.py dev
    python build_extension.py prod

Outputs to:
    dist/extension-dev/   (loads as unpacked extension in Chrome)
    dist/extension-prod/  (zip this and submit to the Chrome Web Store)

The only difference between the two builds is the manifest — all JS/HTML/CSS/
icons are copied unchanged from extension/. Keep extension/ as the source of
truth and never edit the dist/ directories by hand.

Dev build:
  - Uses extension/manifest.dev.json (localhost in host_permissions + matches,
    "_dev": true so background.js seeds the local server URL automatically)
  - Name shows [DEV] so you can tell the two extensions apart in the toolbar

Prod build:
  - Uses extension/manifest.json as-is

After building:
  - Dev:  Chrome → chrome://extensions → Load unpacked → dist/extension-dev/
  - Prod: zip dist/extension-prod/ and upload to the Chrome Web Store
"""

import sys
import shutil
import zipfile
from pathlib import Path

SRC       = Path(__file__).parent / 'extension'
DIST      = Path(__file__).parent / 'dist'
DEV_OUT   = DIST / 'extension-dev'
PROD_OUT  = DIST / 'extension-prod'

# Files/dirs to copy verbatim from extension/ into the build output.
# manifest.json is intentionally excluded — it's replaced by the right variant.
COPY_ITEMS = [
    'background.js',
    'content.js',
    'popup.js',
    'popup.css',
    'popup.html',
    'offscreen.js',
    'offscreen.html',
    'grant-mic.js',
    'grant-mic.html',
    'icons',
]


def build(target: str):
    if target == 'dev':
        out = DEV_OUT
        manifest_src = SRC / 'manifest.dev.json'
    elif target == 'prod':
        out = PROD_OUT
        manifest_src = SRC / 'manifest.json'
    else:
        print(f'Unknown target: {target!r}  (use "dev" or "prod")')
        sys.exit(1)

    if not manifest_src.exists():
        print(f'Missing manifest: {manifest_src}')
        sys.exit(1)

    # Clean and recreate output dir
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    # Copy source files
    missing = []
    for item in COPY_ITEMS:
        src_path = SRC / item
        if not src_path.exists():
            missing.append(item)
            continue
        dst_path = out / item
        if src_path.is_dir():
            shutil.copytree(src_path, dst_path)
        else:
            shutil.copy2(src_path, dst_path)

    if missing:
        print(f'Warning: missing source items (skipped): {", ".join(missing)}')

    # Drop in the correct manifest as manifest.json
    shutil.copy2(manifest_src, out / 'manifest.json')

    # Dev build: overwrite the runtime toolbar icon slots (used by updateIcon in
    # background.js) with the dev variants. background.js hardcodes the filenames
    # icons/16-{on,off}.png and icons/32-{on,off}.png — we slot the dev icons in
    # so the toolbar shows the right icon without any JS changes. The 16px source
    # is used for the 32 slot too; Chrome scales it down cleanly from 48 anyway
    # but we only have 16 and 48 from the designer.
    if target == 'dev':
        icon_dir = out / 'icons'
        for state in ('on', 'off'):
            src16 = icon_dir / f'16-{state}-dev.png'
            src48 = icon_dir / f'48-{state}-dev.png'
            if src16.exists():
                shutil.copy2(src16, icon_dir / f'16-{state}.png')
                shutil.copy2(src16, icon_dir / f'32-{state}.png')
            if src48.exists():
                shutil.copy2(src48, icon_dir / f'48-{state}.png')

    print(f'Built {target} extension → {out}')

    if target == 'prod':
        zip_path = DIST / 'extension-prod.zip'
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            for f in sorted(out.rglob('*')):
                if f.is_file():
                    zf.write(f, f.relative_to(out))
        print(f'Zipped               → {zip_path}')
        print()
        print('Upload dist/extension-prod.zip to the Chrome Web Store.')
    else:
        print()
        print('Load as unpacked extension:')
        print('  Chrome → chrome://extensions → enable Developer mode → Load unpacked')
        print(f'  → select {out}')
        print()
        print('The [DEV] extension seeds http://127.0.0.1:8080 automatically on a')
        print('fresh install. If you already had it installed with a different URL,')
        print('clear its storage once:')
        print("  chrome.storage.local.set({ server_url: 'http://127.0.0.1:8080' })")
        print('  (run in DevTools → background service worker console)')


if __name__ == '__main__':
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(1)
    build(sys.argv[1])
