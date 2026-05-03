import os
import io
import shutil
import subprocess
import mss
from PIL import Image


def _wayland() -> bool:
    return bool(os.environ.get("WAYLAND_DISPLAY"))


SCREENSHOT_PATH = os.path.join(os.path.dirname(__file__), "last_screenshot.png")


_GNOME_SCREENSHOTS = os.path.expanduser("~/Pictures/Screenshots")


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


def _capture_x11() -> bytes:
    with mss.mss() as sct:
        monitor = sct.monitors[1]
        raw = sct.grab(monitor)
        img = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")
        img.save(SCREENSHOT_PATH)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()


def screenshot() -> bytes:
    if _wayland():
        return _capture_wayland()
    return _capture_x11()
