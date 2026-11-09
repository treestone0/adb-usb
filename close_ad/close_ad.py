#!/usr/bin/env python3
"""Capture an Android screenshot via adb, find the ad close button by template matching, and tap it.

Put cropped close-button images (png/jpg) into the templates directory.
"""
import argparse
import random
import subprocess
import sys
import time
from pathlib import Path

import cv2
import numpy as np


def adb_cmd(serial):
    return ["adb", "-s", serial] if serial else ["adb"]


def capture_screen(serial):
    result = subprocess.run(
        adb_cmd(serial) + ["exec-out", "screencap", "-p"],
        capture_output=True,
        check=True,
    )
    img = cv2.imdecode(np.frombuffer(result.stdout, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise RuntimeError("Failed to decode screenshot from adb.")
    return img


def load_templates(template_dir: Path):
    paths = sorted(
        p for p in template_dir.glob("*") if p.suffix.lower() in (".png", ".jpg", ".jpeg")
    )
    templates = []
    for p in paths:
        img = cv2.imread(str(p), cv2.IMREAD_GRAYSCALE)
        if img is not None:
            templates.append((p.name, img))
    if not templates:
        raise FileNotFoundError(f"No template images found in {template_dir}")
    return templates


def find_close_button(screen, templates, threshold, scales):
    gray = cv2.cvtColor(screen, cv2.COLOR_BGR2GRAY)
    best = None  # (score, cx, cy, w, h, name)
    for name, tpl in templates:
        for scale in scales:
            t = cv2.resize(tpl, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
            h, w = t.shape
            if h > gray.shape[0] or w > gray.shape[1] or h < 8 or w < 8:
                continue
            res = cv2.matchTemplate(gray, t, cv2.TM_CCOEFF_NORMED)
            _, score, _, loc = cv2.minMaxLoc(res)
            if best is None or score > best[0]:
                best = (score, loc[0] + w // 2, loc[1] + h // 2, w, h, name)
    if best and best[0] >= threshold:
        return best
    return None


def save_debug(screen, match, path: Path):
    img = screen.copy()
    if match:
        _, cx, cy, w, h, _ = match
        cv2.rectangle(img, (cx - w // 2, cy - h // 2), (cx + w // 2, cy + h // 2), (0, 0, 255), 4)
    cv2.imwrite(str(path), img)


def get_wm_size(serial):
    out = subprocess.run(
        adb_cmd(serial) + ["shell", "wm", "size"], capture_output=True, text=True, check=True
    ).stdout
    size = None
    for line in out.splitlines():
        if "size:" in line:
            w, h = line.split("size:")[1].strip().split("x")
            size = (int(w), int(h))  # an Override line comes last and wins
    return size


def to_input_coords(serial, screen, x, y):
    # input tap uses wm size space, which can differ from the screencap size.
    size = get_wm_size(serial)
    if not size:
        return x, y
    sh, sw = screen.shape[:2]
    if (sw > sh) != (size[0] > size[1]):  # landscape: wm size stays portrait
        size = (size[1], size[0])
    return round(x * size[0] / sw), round(y * size[1] / sh)


def human_point(x, y, w, h):
    # Gaussian around the center, clipped inside the central 70% of the button.
    dx = max(-0.35 * w, min(0.35 * w, random.gauss(0, w * 0.15)))
    dy = max(-0.35 * h, min(0.35 * h, random.gauss(0, h * 0.15)))
    return round(x + dx), round(y + dy)


def tap(serial, x, y, press_ms):
    if press_ms > 0:
        # A 0-2 px drift between down and up, like a real finger.
        ex, ey = x + random.randint(-2, 2), y + random.randint(-2, 2)
        cmd = ["shell", "input", "swipe", str(x), str(y), str(ex), str(ey), str(press_ms)]
    else:
        cmd = ["shell", "input", "tap", str(x), str(y)]
    subprocess.run(adb_cmd(serial) + cmd, check=True)


def parse_args():
    parser = argparse.ArgumentParser(description="Find and tap the ad close button.")
    parser.add_argument("--serial", help="adb device serial")
    parser.add_argument(
        "--templates",
        default=str(Path(__file__).parent / "close_templates"),
        help="Directory of close-button template images",
    )
    parser.add_argument("--threshold", type=float, default=0.8, help="Match score 0-1")
    parser.add_argument("--dry-run", action="store_true", help="Detect only, do not tap")
    parser.add_argument("--press-ms", type=int, nargs=2, default=[50, 130], metavar=("MIN", "MAX"),
                        help="Random press duration range in ms; 0 0 uses plain tap")
    parser.add_argument("--delay-ms", type=int, nargs=2, default=[300, 1200], metavar=("MIN", "MAX"),
                        help="Random reaction delay before tapping")
    parser.add_argument("--offset", type=int, nargs=2, default=[0, 0], metavar=("DX", "DY"),
                        help="Pixel offset added to the matched center (screenshot space)")
    parser.add_argument("--retries", type=int, default=3, help="Jittered retries if the button is still there")
    parser.add_argument("--loop", action="store_true", help="Keep scanning until Ctrl+C")
    parser.add_argument("--interval", type=float, default=2.0, help="Seconds between scans in loop mode")
    parser.add_argument(
        "--debug-image",
        default="close_ad_debug.png",
        help="Where to save annotated screenshot (empty to disable)",
    )
    return parser.parse_args()


def run_once(args, templates):
    screen = capture_screen(args.serial)
    scales = [0.6, 0.8, 1.0, 1.25, 1.5, 2.0]
    match = find_close_button(screen, templates, args.threshold, scales)
    if args.debug_image:
        save_debug(screen, match, Path(args.debug_image))
    if not match:
        print("[INFO] close button not found")
        return False
    score, x, y, w, h, name = match
    print(f"[INFO] found {name} score={score:.3f} at ({x}, {y}) size={w}x{h}")
    if args.dry_run:
        return True

    for i in range(args.retries + 1):
        wait = random.randint(*args.delay_ms)
        print(f"[WAIT] reaction delay {wait}ms")
        time.sleep(wait / 1000.0)
        hx, hy = human_point(x + args.offset[0], y + args.offset[1], w, h)
        px, py = to_input_coords(args.serial, screen, hx, hy)
        tap(args.serial, px, py, random.randint(*args.press_ms))
        print(f"[RUN] tap ({px}, {py}) attempt={i + 1}")
        time.sleep(1.0)
        screen = capture_screen(args.serial)
        again = find_close_button(screen, templates, args.threshold, scales)
        if not again or abs(again[1] - x) > w or abs(again[2] - y) > h:
            print("[DONE] button gone")
            return True
    print("[ERROR] button still present after retries")
    return False


def main():
    args = parse_args()
    template_dir = Path(args.templates)
    template_dir.mkdir(parents=True, exist_ok=True)
    try:
        templates = load_templates(template_dir)
    except FileNotFoundError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1

    try:
        if args.loop:
            while True:
                run_once(args, templates)
                time.sleep(args.interval * random.uniform(0.7, 1.4))
        else:
            return 0 if run_once(args, templates) else 2
    except KeyboardInterrupt:
        pass
    except subprocess.CalledProcessError as exc:
        print(f"[ERROR] adb failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
