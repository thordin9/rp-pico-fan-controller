# FreeCAD enclosure models

Parametric PartDesign models of the printable parts, matching the OpenSCAD in [`../scad/`](../scad/). One `PartDesign::Body` per file, sketches on datum planes, driven by a `Params` spreadsheet.

Built and checked with **FreeCAD 1.1.4** (`freecadcmd`, pin `1.1.4`). The script exits if the interpreter is any other version.

## Files

| File | Contents |
| --- | --- |
| `pico_case_base.FCStd`, `pico_case_lid.FCStd` | Pico W case |
| `bmp280_int_body.FCStd`, `bmp280_ext_body.FCStd` | Sensor body, printed twice. Same solid; the sheet records the variant |
| `bmp280_int_lid.FCStd`, `bmp280_ext_lid.FCStd` | Sensor lids. Same shape; the debossed label is INT or EXT |
| `mount_pico.FCStd`, `mount_bmp.FCStd` | Optional slide-on wall brackets |
| [`build.py`](build.py) | Headless generator and checker |
| [`step/`](step/) | STEP from the FreeCAD solid |
| [`stl/`](stl/) | STL from the FreeCAD solid |
| [`renders/`](renders/) | PNG previews of those STLs |
| [`dof-report.txt`](dof-report.txt) | Per-sketch solver report from the last run |

The OpenSCAD meshes used as the reference stay in [`../stl/`](../stl/). This directory does not replace them. The lid-closed OLED view and the section through the window are OpenSCAD previews in [`../renders/`](../renders/), because the dummy OLED is not a printed solid.

## Open a part and edit the spreadsheet

1. Install FreeCAD 1.1.4 and open an `.FCStd`.
2. The model is the body labelled with the part name. `Params` is the spreadsheet.
3. Column A is the name, column B is the value in millimetres, column C notes where the number came from. Each value cell has an alias, so a sketch constraint reads `Params.wall` (and the same for the other names). Names follow [`../scad/dimensions.scad`](../scad/dimensions.scad) wherever that file defines the number. Derived pockets are formulas in the sheet.
4. Change a cell in column B and recompute (**Std Refresh**). Pad and pocket lengths, and every sketch constraint that corresponds to a named dimension, are bound to those aliases and follow the sheet.

Datum planes are placed by `build.py` when it generates the file. They are attached to the origin planes (`XY_Plane`, `XZ_Plane`, `YZ_Plane`), not to generated faces. A change that moves a plane (floor thickness, the Z of a slot) is applied by regenerating the file, not by the spreadsheet recompute alone.

## Rebuild, check, and export

From the repository root, with FreeCAD 1.1.4 on `PATH`:

```bash
freecadcmd enclosure/freecad/build.py
```

`build.py` rewrites each `.FCStd` from its own copy of the dimensions, then:

- solves every sketch and fails if degrees of freedom are not 0, or if any constraint is redundant, conflicting, malformed, or only partially redundant
- recomputes the document and fails unless the body is one valid solid
- compares the solid's bounding box and volume to `enclosure/stl/<part>.stl` and fails outside tolerance (0.08 mm on the box, and both 80 mm³ and 0.4% on the volume)
- writes `step/<part>.step`, `stl/<part>.stl`, and `dof-report.txt`
- renders `renders/<part>.png` with OpenSCAD when `openscad` and `xvfb-run` are installed

To keep a dimension change, edit the matching `Params.set` or `Params.fml` call in `build.py` and rerun. The script is what writes STEP and STL. `ONLY=pico_case_base` builds one part. `SKIP_RENDER=1` skips the PNGs.

From the GUI, select the body and use **File → Export** for STEP or STL of the current solid.

## What differs from the OpenSCAD solids

- A stadium in OpenSCAD is a true semicircle at each end. A fillet of exactly half the height deletes the short edge, and the solver then rejects the sketch. Those profiles are rounded rectangles with a 0.04 mm flat (`stadium_flat`). The part bounding box does not move.
- The OLED window is a subtractive loft between the outer chamfer rectangle and the active-area rectangle. Both sketches are fully constrained.
- Debossed labels (FAN, INT, EXT, PWR on the Pico base, INT or EXT on the sensor lids) are Liberation Sans Bold shape-strings, the same family as `lib.scad`, cut with a PartDesign boolean. They are not sketches, so they are not in the DOF report. The build fails if a label removes no material.
- Walls are 1.6 mm, floor and lid 1.2 mm. There is no awning, no louver loft, and no fixed ear. The bracket is its own body.
- On the last check, every bounding box matched the OpenSCAD mesh to 0.00 mm. Volume deltas were −3.9 mm³ (Pico base), +11.1 mm³ (Pico lid, 0.36%), −3.5 mm³ (both sensor bodies), about −1.5 mm³ (sensor lids), and −12.3 mm³ (both brackets). All of those are inside the pass rule. 151 sketches, each at 0 degrees of freedom, none redundant or conflicting.

## CI

There is no FreeCAD job on GitHub Actions. The checker is pinned to FreeCAD 1.1.4, which is not the Ubuntu `freecad` package, and a full headless rebuild downloads a large AppImage and then runs for several minutes. Run the command above locally. The existing unit-test workflow is unchanged.
