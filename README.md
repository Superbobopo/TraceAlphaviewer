# TraceAlphaViewer

Local Python/customtkinter viewer for Alpha machine `.old` traces.

It parses trace lines into `MachineState` frames, then displays:

- the machine layout and conveyors
- sensors and belt states
- boxes moving through EA, T3, T4, and T5
- events and diagnostics
- the raw trace with clickable navigation

## Current Status

This repository should track the latest usable version on `main`.

Current UI/runtime behavior:

- startup loads traces directly in full precision mode (`min_dt=0.0`)
- the welcome screen has no quality selector
- T4 to T5 transfer rendering is aligned under the visual axis of T4 until a stable T5 `X` arrives

## Requirements

- Windows
- Python 3.13+
- `customtkinter`

Tkinter is used from the standard Python installation.

## Run

From the repository root:

```powershell
python TraceAlphaViewer\Main.py
```

## Quick Validation

Compile the main modules:

```powershell
python -m py_compile TraceAlphaViewer\Main.py TraceAlphaViewer\Models\state.py TraceAlphaViewer\Parser\trace_parser.py TraceAlphaViewer\Views\traceView.py TraceAlphaViewer\Widgets\machine_canvas.py
```

Reference trace for visual checks:

- `TraceAlphaViewer/TracAlpha1_001.old`

Useful visual checkpoints:

- around `09:03:36` to `09:03:39`: T4 to T5 transfer should appear aligned under T4
- around `09:03:41`: `MAJ (BUTEE-T5) ... X:942` should place the box on the buttee side
- around `09:03:45`: boxes `178372` and `178373` should be separated visually on T5

## Keyboard Shortcuts

- `Left` / `Right`: previous / next frame
- `Space`: play / pause
- `Home` / `End`: first / last frame
- `e` / `E`: next / previous incident or error

## Important Files

- `TraceAlphaViewer/Main.py`: app entrypoint
- `TraceAlphaViewer/Views/traceView.py`: main trace viewer and controls
- `TraceAlphaViewer/Widgets/machine_canvas.py`: machine drawing and visual placement logic
- `TraceAlphaViewer/Parser/trace_parser.py`: parser and box lifecycle
- `AGENTS.md`: technical decisions and validation notes

## Limits / Notes

- The project is currently focused on local inspection of Alpha traces.
- T5 business position uses trace `x_pos`, not motor encoder `pT5`.
- For implementation details and parser/rendering decisions, see `AGENTS.md`.
