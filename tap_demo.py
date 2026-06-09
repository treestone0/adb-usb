#!/usr/bin/env python3
import argparse
import json
import random
import subprocess
import sys
import termios
import threading
import time
import tty
from pathlib import Path


PRINT_LOCK = threading.Lock()


def _safe_print(message: str, end: str = "\r\n"):
    with PRINT_LOCK:
        normalized_message = message.replace("\n", "\r\n")
        normalized_end = end.replace("\n", "\r\n")
        print(normalized_message, end=normalized_end, flush=True)


def log_info(message: str):
    _safe_print(f"[INFO] {message}")


def log_run(message: str):
    _safe_print(f"[RUN] {message}")


def log_wait(message: str):
    _safe_print(f"[WAIT] {message}")


def log_interrupt(message: str):
    _safe_print(f"[INTERRUPT] {message}")


def log_done(message: str):
    _safe_print(f"[DONE] {message}")


def log_error(message: str):
    _safe_print(f"[ERROR] {message}")


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
    parser.add_argument(
        "--sequences",
        default="sequences.json",
        help="Path to sequences JSON config file (default: sequences.json)",
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


def load_sequences(sequences_path: Path):
    """Load optional sequences config. Returns empty dict if file doesn't exist."""
    if not sequences_path.exists():
        return {}

    try:
        with sequences_path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON format in {sequences_path}: {exc}") from exc

    if not isinstance(data, dict):
        raise ValueError("Sequences JSON root must be an object.")

    return data


def run_sequence(config: dict, sequences: dict, seq_id: str):
    if seq_id not in sequences:
        raise KeyError(f"Sequence '{seq_id}' not found in sequences config.")

    seq_data = sequences[seq_id]
    steps = seq_data.get("steps")
    if not isinstance(steps, list) or len(steps) == 0:
        raise ValueError(f"Sequence '{seq_id}' must have a non-empty 'steps' list.")

    log_run(f"sequence={seq_id} steps={len(steps)}")
    for i, step in enumerate(steps):
        area_id = str(step.get("area", ""))
        if not area_id:
            raise ValueError(f"Step {i + 1} in sequence '{seq_id}' is missing 'area'.")

        run_area_once(config, area_id)

        if i < len(steps) - 1:
            delay_min = int(step.get("delay_after_min_ms", 0))
            delay_max = int(step.get("delay_after_max_ms", delay_min))
            if delay_min > delay_max:
                raise ValueError(
                    f"Step {i + 1} in sequence '{seq_id}': "
                    "delay_after_min_ms cannot be greater than delay_after_max_ms."
                )
            if delay_max > 0:
                wait_ms = random.randint(delay_min, delay_max)
                log_wait(f"sequence={seq_id} step={i + 1} sleep_ms={wait_ms}")
                time.sleep(wait_ms / 1000.0)

    log_done(f"sequence={seq_id} completed")


def _sleep_interruptible(wait_ms: int, should_cancel) -> bool:
    """Sleep in short intervals so sequence waits can be canceled quickly."""
    remaining = wait_ms / 1000.0
    while remaining > 0:
        if should_cancel():
            return False
        chunk = 0.05 if remaining > 0.05 else remaining
        time.sleep(chunk)
        remaining -= chunk
    return True


def run_sequence_interruptible(
    config: dict,
    sequences: dict,
    seq_id: str,
    should_cancel,
):
    if seq_id not in sequences:
        raise KeyError(f"Sequence '{seq_id}' not found in sequences config.")

    seq_data = sequences[seq_id]
    steps = seq_data.get("steps")
    if not isinstance(steps, list) or len(steps) == 0:
        raise ValueError(f"Sequence '{seq_id}' must have a non-empty 'steps' list.")

    log_run(f"sequence={seq_id} steps={len(steps)}")
    for i, step in enumerate(steps):
        if should_cancel():
            log_interrupt(f"sequence={seq_id} before_step={i + 1}")
            return False

        area_id = str(step.get("area", ""))
        if not area_id:
            raise ValueError(f"Step {i + 1} in sequence '{seq_id}' is missing 'area'.")

        run_area_once(config, area_id)

        if should_cancel():
            log_interrupt(f"sequence={seq_id} after_step={i + 1}")
            return False

        if i < len(steps) - 1:
            delay_min = int(step.get("delay_after_min_ms", 0))
            delay_max = int(step.get("delay_after_max_ms", delay_min))
            if delay_min > delay_max:
                raise ValueError(
                    f"Step {i + 1} in sequence '{seq_id}': "
                    "delay_after_min_ms cannot be greater than delay_after_max_ms."
                )
            if delay_max > 0:
                wait_ms = random.randint(delay_min, delay_max)
                log_wait(f"sequence={seq_id} step={i + 1} sleep_ms={wait_ms}")
                if not _sleep_interruptible(wait_ms, should_cancel):
                    log_interrupt(f"sequence={seq_id} wait_after_step={i + 1}")
                    return False

    log_done(f"sequence={seq_id} completed")
    return True


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
    log_run(f"area={area_id} action=tap point=({x},{y})")

    result = run_adb_tap(x, y)
    if result.returncode != 0:
        stderr = result.stderr.strip() if result.stderr else "Unknown adb error."
        raise RuntimeError(f"adb tap failed: {stderr}")

    log_done(f"area={area_id} action=tap")
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
    log_run(
        f"area={area_id} action=swipe start=({start_x},{start_y}) "
        f"end=({end_x},{end_y}) duration_ms={duration_ms}"
    )

    result = run_adb_swipe(start_x, start_y, end_x, end_y, duration_ms)
    if result.returncode != 0:
        stderr = result.stderr.strip() if result.stderr else "Unknown adb error."
        raise RuntimeError(f"adb swipe failed: {stderr}")

    log_done(f"area={area_id} action=swipe")
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


def _run_by_key(config: dict, sequences: dict, key: str, should_cancel):
    if key in sequences:
        run_sequence_interruptible(config, sequences, key, should_cancel)
    else:
        run_area_once(config, key)


def _input_loop(
    state: dict,
    lock: threading.Lock,
    wake_event: threading.Event,
    valid_keys: set,
):
    while True:
        _safe_print("Key>")
        user_input = read_single_key()
        log_info(f"key={user_input}")

        with lock:
            if user_input == "\x03" or user_input == "0":
                state["exit"] = True
                wake_event.set()
                return

            if user_input not in valid_keys:
                log_info(f"ignored_invalid_key={user_input}")
                continue

            state["latest_key"] = user_input
            state["request_id"] += 1
            wake_event.set()


def interactive_loop(config: dict, sequences: dict):
    has_sequences = bool(sequences)
    log_info("interactive_mode=on")
    if has_sequences:
        log_info("input=sequence_or_area_key, quit=0")
        log_info(f"sequence_keys={','.join(sorted(sequences.keys()))}")
    else:
        log_info("input=area_key, quit=0")

    lock = threading.Lock()
    wake_event = threading.Event()
    state = {
        "latest_key": None,
        "request_id": 0,
        "exit": False,
    }
    handled_request_id = 0
    valid_keys = set(config.keys()) | set(sequences.keys())

    input_thread = threading.Thread(
        target=_input_loop,
        args=(state, lock, wake_event, valid_keys),
        daemon=True,
    )
    input_thread.start()

    while True:
        wake_event.wait(timeout=0.1)

        with lock:
            exit_requested = state["exit"]
            request_id = state["request_id"]
            key_to_run = state["latest_key"]
            has_new_request = request_id > handled_request_id and key_to_run is not None
            if not has_new_request:
                wake_event.clear()

        if exit_requested:
            log_info("exit")
            break

        if not has_new_request:
            continue

        handled_request_id = request_id

        def should_cancel_this_request() -> bool:
            with lock:
                return state["exit"] or state["request_id"] != request_id

        try:
            log_run(f"dispatch key={key_to_run} request={request_id}")
            _run_by_key(config, sequences, key_to_run, should_cancel_this_request)
            if should_cancel_this_request():
                log_interrupt(f"request={request_id} preempted")
            else:
                log_done(f"request={request_id} finished")
        except Exception as exc:
            log_error(str(exc))

    input_thread.join(timeout=0.2)


def main():
    args = parse_args()
    config_path = Path(args.config)

    sequences_path = Path(args.sequences)

    try:
        config = load_config(config_path)
        sequences = load_sequences(sequences_path)
        if args.area:
            run_area_once(config, str(args.area))
        else:
            interactive_loop(config, sequences)
    except Exception as exc:
        log_error(str(exc))
        sys.exit(1)


if __name__ == "__main__":
    main()
