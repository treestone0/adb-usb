# ADB Random Tap Demo

This demo reads area ranges from a JSON file and supports:

- Interactive mode: continuously read configured keys (sample: `1/2/3/4`), run once for that area, input `0` to exit
- One-time mode: use `--area` to execute a single random tap
- Swipe mode: define `action: "swipe"` and randomize start/end points from ranges

## Requirements

- Python 3.8+
- Android platform tools (`adb`) available in PATH
- Phone connected and authorized

Install `adb` on macOS:

```bash
brew install android-platform-tools
```

If you use Linux, install the same package from your distro package manager.

Check device status:

```bash
adb devices
```

You should see at least one device in `device` state.

## Files

- `tap_demo.py`: demo script
- `areas.json`: sample area config
- `sequences.json`: optional key-to-sequence config

## Run

Install Python dependencies (none required now, but keep this step for consistency):

```bash
pip install -r requirements.txt
```

Interactive mode (recommended):

```bash
python3 tap_demo.py
```

Then input:

- any configured key (for example `1/2/3/4`): execute that area's action
- any configured sequence key (for example `a/b` in `sequences.json`): execute the sequence
- `0`: exit the program

## Sequence Config (`sequences.json`)

`sequences.json` maps one trigger key to an ordered list of area actions. Each step references one area id from `areas.json`.

Example:

```json
{
  "a": {
    "steps": [
      { "area": "1", "delay_after_min_ms": 500, "delay_after_max_ms": 1500 },
      { "area": "2", "delay_after_min_ms": 300, "delay_after_max_ms": 800 },
      { "area": "3" }
    ]
  }
}
```

Fields:

- `area`: required, area id from `areas.json`
- `delay_after_min_ms`: optional, minimum wait before next step
- `delay_after_max_ms`: optional, maximum wait before next step (defaults to min if omitted)

Run with custom sequences file:

```bash
python3 tap_demo.py --sequences /path/to/sequences.json
```

If the sequences file does not exist, interactive mode still works with area keys only.

## Preemption Behavior (Last Input Wins)

Interactive execution is preemptive:

- While a sequence is running, pressing a new key cancels the remaining sequence steps.
- The script always switches to the latest key you pressed.
- If multiple keys are pressed quickly, only the last key is kept.
- If one adb command is already running (`tap`/`swipe`), the command is not force-killed; switch happens immediately after that command returns.

One-time mode with default config (`areas.json`):

```bash
python3 tap_demo.py --area 1
```

One-time mode with custom config path:

```bash
python3 tap_demo.py --area 2 --config /path/to/areas.json
```

## JSON Format

```json
{
  "1": { "x_min": 100, "x_max": 300, "y_min": 500, "y_max": 700 },
  "2": { "x_min": 400, "x_max": 650, "y_min": 800, "y_max": 1000 },
  "3": {
    "action": "swipe",
    "duration_ms": 350,
    "start": { "x_min": 160, "x_max": 260, "y_min": 1800, "y_max": 2000 },
    "end": { "x_min": 800, "x_max": 980, "y_min": 500, "y_max": 760 }
  },
  "4": { "x_min": 700, "x_max": 900, "y_min": 1200, "y_max": 1400 }
}
```

Add more regions by adding new keys like `5`, `6`, `7`.

Tap action is default. A tap region needs:

- `x_min/x_max/y_min/y_max`

Swipe action needs:

- `action: "swipe"`
- `start` range object and `end` range object (both using `x_min/x_max/y_min/y_max`)
- optional `duration_ms` (default `300`)

## Verification

1. Run `adb version` and `adb devices` to confirm `adb` is installed and device is connected.
2. Run:
   - `python3 tap_demo.py --area 1`
   - `python3 tap_demo.py --area 2`
   - `python3 tap_demo.py --area 3`
3. Confirm the printed random coordinate is inside each area's range, and the phone receives one tap.

## Troubleshooting

If you see `No such file or directory: 'adb'`, it means `adb` is not installed or not in PATH.

1. Install with `brew install android-platform-tools`.
2. Restart terminal and run `adb version`.
3. Run the script again:

```bash
python3 tap_demo.py --area 1
```
