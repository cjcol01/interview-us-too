import io
import os
import platform
import shutil
import subprocess

import mss
from PIL import Image

SCREENSHOT_PATH = os.path.join(os.path.dirname(__file__), "last_screenshot.png")

_GNOME_SCREENSHOTS = os.path.expanduser("~/Pictures/Screenshots")


def _capture_mss(monitor_index: int = 1) -> bytes:
    with mss.mss() as sct:
        monitors = sct.monitors
        if monitor_index >= len(monitors):
            raise ValueError(f"monitor {monitor_index} not found, only {len(monitors) - 1} monitor(s) available")
        raw = sct.grab(monitors[monitor_index])
        img = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")
        img.save(SCREENSHOT_PATH)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()


def _capture_wayland() -> bytes:
    before = set(os.listdir(_GNOME_SCREENSHOTS)) if os.path.exists(_GNOME_SCREENSHOTS) else set()
    try:
        subprocess.run(["gnome-screenshot"], capture_output=True, timeout=10)
    except subprocess.TimeoutExpired:
        pass
    after = set(os.listdir(_GNOME_SCREENSHOTS)) if os.path.exists(_GNOME_SCREENSHOTS) else set()
    new_files = after - before
    if not new_files:
        raise RuntimeError("no new screenshot found in ~/Pictures/Screenshots")
    newest = os.path.join(_GNOME_SCREENSHOTS, sorted(new_files)[-1])
    shutil.copy(newest, SCREENSHOT_PATH)
    with open(SCREENSHOT_PATH, "rb") as f:
        return f.read()


def screenshot(monitor_index: int = 1) -> bytes:
    if platform.system() == "Windows":
        return _capture_mss(monitor_index)
    if os.environ.get("WAYLAND_DISPLAY"):
        return _capture_wayland()
    return _capture_mss(monitor_index)
