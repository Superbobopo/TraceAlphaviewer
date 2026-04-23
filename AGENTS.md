# TraceAlphaViewer Agent Notes

## Project Snapshot

TraceAlphaViewer is a local Python/customtkinter viewer for Alpha machine `.old` traces. It parses trace lines into `MachineState` frames, then displays the machine layout, sensors, boxes, events, diagnostics, and raw trace navigation.

Run from the repository root:

```powershell
python TraceAlphaViewer\Main.py
python -m py_compile TraceAlphaViewer\Main.py TraceAlphaViewer\Models\state.py TraceAlphaViewer\Parser\trace_parser.py TraceAlphaViewer\Views\traceView.py TraceAlphaViewer\Widgets\machine_canvas.py
```

Git workflow target:

- `main` should represent the latest usable version of the project.
- Preserve older states through normal commit history and version tags, not archive branches by default.
- Use a short-lived branch only for risky work, then merge back into `main`.

## Important Files

- `TraceAlphaViewer/Main.py`: customtkinter app entrypoint.
- `TraceAlphaViewer/Views/traceView.py`: main trace viewer, player controls, tabs, navigation, callbacks.
- `TraceAlphaViewer/Widgets/machine_canvas.py`: machine schematic drawing and all visual placement/scale logic.
- `TraceAlphaViewer/Parser/trace_parser.py`: `.old` parser, event creation, box lifecycle, T5 list parsing.
- `TraceAlphaViewer/Models/state.py`: `MachineState`, `BoxInfo`, `MachineEvent`.
- `TraceAlphaViewer/Models/diagnostic.py`: diagnostic incident extraction.
- `TraceAlphaViewer/Models/diagnostic_knowledge.py`: terrain knowledge base used to explain recurring symptoms.
- `TraceAlphaViewer/TracAlpha1_001.old`: reference trace used for visual checks.

## Current T5 Decisions

T5 rendering has been tuned several times. Preserve these choices unless the user explicitly asks to recalibrate:

- T5 position mapping uses trace `x_pos`, not motor encoder `pT5`.
- `T5_X_BUTEE = 942`, right side near height measurement/buttee.
- `T5_X_MAX = 1750`, visual dezoom of the useful T5 range.
- `T5_BOX_DIM_SCALE = 0.75`, box visual scale independent from T5 position scale.
- `_T5_ENTRY_X = 1060` in `trace_parser.py`, used only as the initial visual entry point when a box is reported physically on T5 before real `X` updates arrive.
- Do not initialize a T5 box with `abs(pT5)`: `pT5` is a motor encoder, not a business `X` coordinate.
- The yellow dashed `pT5` line was removed from the canvas because it confused the box path.
- The `Mesure H.`/`LzB` point is drawn above T5, outside the belt, so compressed boxes do not cover it.

T5 box dimensions:

- C9/`width_mm` is drawn on the horizontal axis of T5.
- C6/`length_mm` is drawn on the vertical thickness of T5.
- If the C6 length does not fit vertically, reduce the whole box proportionally to keep the ratio.
- `t5_footprint_mm` from `ALPHA:T5-LIST-PACK` is only a fallback when C6/C9 dimensions are missing, not the main rendered size.

Useful trace validation points:

- Around `09:03:36` to `09:03:39`: T4 to T5 transfer should appear aligned with the T4 drop axis.
- Around `09:03:41`: `MAJ (BUTEE-T5) ... X:942` should place the box at the buttee side.
- Around `09:03:45`: boxes `178372` and `178373` should be positioned by `X=1419` and `X=1323`, separated visually.

## UI Notes

Player buttons intentionally keep compact icons:

- `|<` / `>|`: first/last frame, displayed with triangle glyphs in the UI.
- `<` / `>`: previous/next frame, displayed with triangle glyphs in the UI.
- `Play` button uses `▶` / `⏸`.
- `Err<` / `Err>`: previous/next error event, displayed with triangle glyphs in the UI.
- `<<` and `>>` near the speed slider slow down/speed up playback and update the slider.
- Speed slider is logarithmic internally for better low-speed adjustment.
- Details resize handle sits below the player bar, not above it.
- Startup loading now always uses `Precision trace` behavior (`min_dt=0.0`); there is no quality selector on the welcome screen anymore.

Bottom tabs are `Diagnostic`, `Erreur`, `Evenements`, `Trace`. The `Erreur` tab is an `EventPanel` filtered to `severity == "error"`.

Keyboard shortcuts in `traceView.py`:

- Left/Right: previous/next frame.
- Space: play/pause.
- Home/End: beginning/end.
- `e` / `E`: next/previous incident/error.

## Parser Notes

Box identity must follow the Alpha lifecycle, not just the CIP/barcode:

- `box_in_EA`: physical box on C4 / CB1.
- `box_on_T3`: physical box on T3 / C5 / CB2.
- `box_on_T4`: physical box on T4 / C6.
- `boxes_on_T5`: T5/BdD boxes controlled by `IdA`.
- `BoxInfo.id_b` is `Nboite` / `idB`, the pre-T5 flow identity.
- `BoxInfo.id_alpha` is the T5/BdD identity used by robot delete lines.
- `BoxInfo.source_ref` preserves the initial `ALPHA-INC-xxx` reference when CB2 later identifies the real product.
- Matching priority is `id_alpha`, then `id_b`, then barcode only if it is unique. Do not delete/update every box with the same CIP.
- `CB1: ajout Hist_LectCB` is an EA/C4 read and must only update `box_in_EA`.
- `CB2: ajout Hist_LectCB` is a T3/C5 read and must only update `box_on_T3`.
- `idCB2: Identif. sur le lecteur1 Ok ... (Nboite=X)` reuses a CB1 read, but `idB=X` is assigned only when that box is already on T3.
- Never assign `Nboite/idB` to an old cached CB2 box if `box_on_T3` is empty.
- Canvas rendering is stricter than parser state: EA draws `box_in_EA`; T3 draws only `box_on_T3` when `C5=1`; T4 draws `box_on_T4` when `C6=1` or a T4 position is active.
- On T3, when `C5=1`, draw the box with its leading/right edge aligned on `C5`; center it vertically in T3.
- On T4, when `C6=1`, draw the box with its leading/bottom edge aligned on `C6`; the box extends upward because C6 is the lower/end sensor.
- During `WAIT-FIN-TRANSFERT-T4/T5`, once `C6=0`, keep the T4 box moving down toward T5; do not interpret decreasing `pT4` as a visual move back up T4.
- Freshly transferred T5 boxes use `t5_entry_aligned=True` and are drawn under the visual center axis of T4 until `BUTEE-T5`, `APRES-MESURE-LARG`, or `T5-LIST-PACK` provides a stable T5 `X`.
- T3/T4 use compact visual scales distinct from the business tracking coordinates, so medication boxes do not hide belt state labels.
- T3 state text is drawn below the belt, not inside the belt.
- T4 box height is based on measured length (`box.length_mm` / `LgBtT4`) and the width must stay smaller than the height so a C6 box reads visually vertical; show `idB:X` next to it.
- T5 boxes expose `IdA`, `idB`, barcode, and dimensions on canvas hover.

Reference flow from `TracAlpha1_001.old`:

- `idCB1 --> Ref:ALPHA-INC-001` creates/updates the EA box.
- `le transfert (EA->T3) est termine` moves it to `box_on_T3`.
- `idCB2 --> Ref:3400937732284` replaces the visible reference on T3 while keeping `source_ref=ALPHA-INC-001`.
- `idCB2: (Nboite= 1)` sets `id_b=1`.
- `transfert T3->T4 termine ... idB=1` moves the same box to `box_on_T4`.
- `photoCamT5 'AjoutBtT5.idA178370.idB1'` links `id_b=1` to `id_alpha=178370`.
- `T5-DEL-PACK@Ok@178370` removes only `IdA=178370`.

Important T5 trace inputs:

- `MAJ (BUTEE-T5) ... X:942`: box against buttee.
- `MAJ (APRES-MESURE-LARG) ... nvlle lxH:WxH [xL] X:N`: measured C9 width/height and C6 length with real T5 `X`.
- `ALPHA:T5-LIST-PACK`: robot-valid box list. It includes product dimensions and goulotte footprint `X990x width height`.
- `Deplace toutes les boites ... sur N mm`: global T5 box shift.

Avoid matching by barcode only when possible: repeated products often share the same barcode. Prefer `id_alpha`/`id_b` when available.

## Editing Guidelines

- Keep edits scoped. The app is small and mostly procedural; prefer local helpers over broad refactors.
- Use ASCII for new comments/docs unless there is a strong reason not to.
- Be careful with existing file encoding: some comments display mojibake. Patch functional lines when comment matching fails.
- Do not reintroduce visual `WAIT-COND` noise on the machine canvas; belt states already appear in the right-side state table.
- For manual changes, use `apply_patch`.

## Validation Checklist

Run compile after code changes:

```powershell
python -m py_compile TraceAlphaViewer\Main.py TraceAlphaViewer\Models\state.py TraceAlphaViewer\Parser\trace_parser.py TraceAlphaViewer\Views\traceView.py TraceAlphaViewer\Widgets\machine_canvas.py
```

For documentation/release hygiene:

- Keep `README.md` up to date for humans cloning the repository from GitHub.
- Keep `AGENTS.md` focused on technical decisions, validation points, and implementation constraints.
- When a stable milestone is reached, prefer creating a Git tag (for example `v0.1.0`) instead of freezing old code on `main`.

For visual work, inspect these areas in the viewer:

- T5 buttee/height measurement side.
- C9 alignment versus actual activation state.
- T4 to T5 transfer alignment.
- T5 box spacing around `09:03:45`.
- Player controls remain readable and not clipped.
