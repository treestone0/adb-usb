#!/usr/bin/env python3
"""Capture an Android screenshot and crop a close-button template with the mouse.

Usage: python make_template.py [--name x_circle] [--serial SERIAL]
Drag a box around the close button, press ENTER/SPACE to save, or C to cancel.
"""
import argparse
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np

TEMPLATE_DIR = Path(__file__).parent / "close_templates"


def capture_screen(serial):
    cmd = ["adb", "-s", serial] if serial else ["adb"]
    out = subprocess.run(cmd + ["exec-out", "screencap", "-p"], capture_output=True, check=True).stdout
    img = cv2.imdecode(np.frombuffer(out, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise RuntimeError("Failed to decode screenshot from adb.")
    return img


def main():
    parser = argparse.ArgumentParser(description="Capture screen and crop a close-button template.")
    parser.add_argument("--serial", help="adb device serial")
    parser.add_argument("--name", help="Template file name without extension (default: close_N)")
    parser.add_argument("--image", help="Use an existing screenshot instead of capturing")
    args = parser.parse_args()

    screen = cv2.imread(args.image) if args.image else capture_screen(args.serial)
    if screen is None:
        print("[ERROR] cannot load screenshot", file=sys.stderr)
        return 1

    TEMPLATE_DIR.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(TEMPLATE_DIR.parent / "last_screenshot.png"), screen)

    # Fit the window to the display; ROI coordinates are returned in original pixels.
    cv2.namedWindow("select close button", cv2.WINDOW_NORMAL)
    cv2.resizeWindow("select close button", int(screen.shape[1] * 0.4), int(screen.shape[0] * 0.4))
    x, y, w, h = cv2.selectROI("select close button", screen, showCrosshair=True)
    cv2.destroyAllWindows()
    if w == 0 or h == 0:
        print("[INFO] cancelled")
        return 2

    name = args.name or f"close_{len(list(TEMPLATE_DIR.glob('close_*.png'))) + 1}"
    path = TEMPLATE_DIR / f"{name}.png"
    cv2.imwrite(str(path), screen[y : y + h, x : x + w])
    print(f"[DONE] saved {path} ({w}x{h})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
