#!/usr/bin/env python3
import argparse
import json
import random
import subprocess
import sys
import termios
import time
import tty
from pathlib import Path


def parse_args():
    parser = argparse.ArgumentParser(
        description="Read area ranges from JSON and run random adb tap(s)."
    )
    parser.add_argument(
        "--area",
        help="Optional one-time area id to tap, for example: 1 / 2 / 3",
    )
    parser.add_argument(
        "--config",
        default="areas.json",
        help="Path to JSON config file (default: areas.json)",
    )
    return parser.parse_args()


def load_config(config_path: Path):
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    try:
        with config_path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON format in {config_path}: {exc}") from exc

    if not isinstance(data, dict):
        raise ValueError("Config JSON root must be an object.")

    return data


def get_random_point(area_data: dict):
    required = ("x_min", "x_max", "y_min", "y_max")
    missing = [key for key in required if key not in area_data]
    if missing:
        raise ValueError(f"Area is missing fields: {', '.join(missing)}")

    try:
        x_min = int(area_data["x_min"])
        x_max = int(area_data["x_max"])
        y_min = int(area_data["y_min"])
        y_max = int(area_data["y_max"])
    except (TypeError, ValueError) as exc:
        raise ValueError("Area coordinates must be integers.") from exc

    if x_min > x_max or y_min > y_max:
        raise ValueError("Invalid area range: min value cannot be greater than max value.")

    x = random.randint(x_min, x_max)
    y = random.randint(y_min, y_max)
    return x, y


def run_adb_tap(x: int, y: int):
    result = subprocess.run(
        ["adb", "shell", "input", "tap", str(x), str(y)],
        check=False,
        capture_output=True,
        text=True,
    )
    return result


def run_adb_swipe(start_x: int, start_y: int, end_x: int, end_y: int, duration_ms: int):
    result = subprocess.run(
        [
            "adb",
            "shell",
            "input",
            "swipe",
            str(start_x),
            str(start_y),
            str(end_x),
            str(end_y),
            str(duration_ms),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    return result


def read_single_key():
    """Read one key immediately without requiring Enter."""
    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        key = sys.stdin.read(1)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
    return key


def tap_area_once(config: dict, area_id: str):
    if area_id not in config:
        raise KeyError(f"Area '{area_id}' not found in config.")

    x, y = get_random_point(config[area_id])
    print(f"Selected area: {area_id}")
    print(f"Random tap point: ({x}, {y})")

    result = run_adb_tap(x, y)
    if result.returncode != 0:
        stderr = result.stderr.strip() if result.stderr else "Unknown adb error."
        raise RuntimeError(f"adb tap failed: {stderr}")

    print("adb tap executed successfully.")
    # A tiny delay helps avoid back-to-back taps being merged by some apps/UI flows.
    time.sleep(0.08)


def swipe_area_once(config: dict, area_id: str):
    area_data = config[area_id]
    start_area = area_data.get("start")
    end_area = area_data.get("end")
    if not isinstance(start_area, dict) or not isinstance(end_area, dict):
        raise ValueError("Swipe area must include object fields: 'start' and 'end'.")

    duration_ms = int(area_data.get("duration_ms", 300))
    if duration_ms <= 0:
        raise ValueError("duration_ms must be a positive integer.")

    start_x, start_y = get_random_point(start_area)
    end_x, end_y = get_random_point(end_area)
    print(f"Selected swipe area: {area_id}")
    print(f"Swipe start point: ({start_x}, {start_y})")
    print(f"Swipe end point: ({end_x}, {end_y})")
    print(f"Swipe duration: {duration_ms} ms")

    result = run_adb_swipe(start_x, start_y, end_x, end_y, duration_ms)
    if result.returncode != 0:
        stderr = result.stderr.strip() if result.stderr else "Unknown adb error."
        raise RuntimeError(f"adb swipe failed: {stderr}")

    print("adb swipe executed successfully.")
    time.sleep(0.08)


def run_area_once(config: dict, area_id: str):
    if area_id not in config:
        raise KeyError(f"Area '{area_id}' not found in config.")

    area_data = config[area_id]
    if not isinstance(area_data, dict):
        raise ValueError(f"Area '{area_id}' data must be an object.")

    action = str(area_data.get("action", "tap")).lower()
    if action == "tap":
        tap_area_once(config, area_id)
    elif action == "swipe":
        swipe_area_once(config, area_id)
    else:
        raise ValueError(f"Unsupported action '{action}' in area '{area_id}'.")


def interactive_loop(config: dict):
    print("Interactive mode started.")
    print("Press a configured key to run action, press 0 to exit (no Enter needed).")

    while True:
        print("Key> ", end="", flush=True)
        user_input = read_single_key()
        print(user_input)

        if user_input == "\x03":
            print("Exit (Ctrl+C).")
            break
        if user_input == "0":
            print("Exit.")
            break

        try:
            run_area_once(config, user_input)
        except Exception as exc:
            print(f"Error: {exc}", file=sys.stderr)


def main():
    args = parse_args()
    config_path = Path(args.config)

    try:
        config = load_config(config_path)
        if args.area:
            run_area_once(config, str(args.area))
        else:
            interactive_loop(config)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
