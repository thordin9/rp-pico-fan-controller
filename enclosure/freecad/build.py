#!/usr/bin/env python3
"""Build the Pico W and BMP280 enclosure parts as parametric FreeCAD models.

Run with FreeCAD 1.1.4's headless interpreter (see README.md)::

    freecadcmd enclosure/freecad/build.py

The script writes one FCStd per printable part, exports STEP and STL, checks
that every sketch has 0 degrees of freedom, and compares each solid to the
OpenSCAD mesh in ``enclosure/stl/``. It exits non-zero on any failure.

Environment:
    ONLY=pico_case_base   build a single part (name without extension)
    SKIP_RENDER=1         skip the OpenSCAD preview PNGs
"""

from __future__ import annotations

import os
import struct
import sys
import traceback
from pathlib import Path

try:
    import FreeCAD as App
    import Part
    import Sketcher
except ImportError:
    sys.stderr.write("Run this script with freecadcmd, not system python.\n")
    sys.exit(1)

FREECAD_PIN = ("1", "1", "4")
FONT = "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"
ROOT = Path(__file__).resolve().parent
REF_STL = ROOT.parent / "stl"
STEP_DIR = ROOT / "step"
STL_DIR = ROOT / "stl"
RENDER_DIR = ROOT / "renders"
REPORT_PATH = ROOT / "dof-report.txt"

# Stadium ends are true semicircles in OpenSCAD. A fillet of exactly half the
# height deletes the short edge and the solver rejects it, so the profile is a
# rounded rectangle with a 0.04 mm flat. Area error is a fraction of a mm^2.
BBOX_TOL = 0.08
VOL_ABS_TOL = 80.0
VOL_REL_TOL = 0.004

# Set after Params.check compares the sheet to these Python values.
_REPORT = []


def die(msg):
    print("BUILD FAILED:", msg, flush=True)
    os._exit(1)


def require_version():
    ver = tuple(App.Version()[:3])
    print("FreeCAD", ".".join(App.Version()[:4]), flush=True)
    if ver != FREECAD_PIN:
        die(
            "This build is pinned to FreeCAD %s (got %s). "
            "See enclosure/freecad/README.md."
            % (".".join(FREECAD_PIN), ".".join(ver))
        )


class Dim:
    """A length that is both a number and a FreeCAD expression."""

    def __init__(self, value, expr):
        self.v = float(value)
        self.e = expr

    def _bin(self, other, op, fn):
        if isinstance(other, Dim):
            return Dim(fn(self.v, other.v), "(%s %s %s)" % (self.e, op, other.e))
        return Dim(fn(self.v, float(other)), "(%s %s %.10g)" % (self.e, op, float(other)))

    def __add__(self, other):
        return self._bin(other, "+", lambda a, b: a + b)

    def __radd__(self, other):
        return Dim(float(other), "%.10g" % float(other)) + self

    def __sub__(self, other):
        return self._bin(other, "-", lambda a, b: a - b)

    def __rsub__(self, other):
        return Dim(float(other), "%.10g" % float(other)) - self

    def __mul__(self, other):
        return self._bin(other, "*", lambda a, b: a * b)

    def __rmul__(self, other):
        return Dim(float(other), "%.10g" % float(other)) * self

    def __truediv__(self, other):
        return self._bin(other, "/", lambda a, b: a / b)

    def __neg__(self):
        return Dim(-self.v, "(-(%s))" % self.e)

    def __repr__(self):
        return "Dim(%s, %s)" % (self.v, self.e)


class Params:
    def __init__(self, doc):
        self.doc = doc
        self.sheet = doc.addObject("Spreadsheet::Sheet", "Params")
        self.row = 1
        self.v = {}
        self.sheet.set("A1", "name")
        self.sheet.set("B1", "value_mm")
        self.sheet.set("C1", "origin")
        self.row = 2

    def set(self, name, value, origin="dimensions.scad"):
        self.sheet.set("A%d" % self.row, name)
        self.sheet.set("B%d" % self.row, "%.10g" % float(value))
        self.sheet.set("C%d" % self.row, origin)
        self.sheet.setAlias("B%d" % self.row, name)
        self.v[name] = float(value)
        self.row += 1

    def text(self, name, value, origin="label"):
        self.sheet.set("A%d" % self.row, name)
        self.sheet.set("B%d" % self.row, str(value))
        self.sheet.set("C%d" % self.row, origin)
        self.sheet.setAlias("B%d" % self.row, name)
        self.row += 1

    def fml(self, name, formula, expected, origin="derived"):
        self.sheet.set("A%d" % self.row, name)
        expr = formula if str(formula).startswith("=") else "=" + formula
        self.sheet.set("B%d" % self.row, expr)
        self.sheet.set("C%d" % self.row, origin)
        self.sheet.setAlias("B%d" % self.row, name)
        self.v[name] = float(expected)
        self.row += 1

    def check(self):
        self.doc.recompute()
        bad = []
        for name, expected in self.v.items():
            got = float(self.sheet.get(name))
            if abs(got - expected) > 1e-5:
                bad.append((name, got, expected))
        if bad:
            die("spreadsheet mismatch: %s" % (bad[:12],))

    def d(self, name):
        if name not in self.v:
            die("unknown parameter %s" % name)
        return Dim(self.v[name], "Params.%s" % name)


def convex_hull(items):
    """Items are (x, y, payload...). Returns hull in CCW order, colinear dropped."""
    pts = sorted(items, key=lambda p: (p[0], p[1]))
    if len(pts) < 3:
        die("hull needs 3 points")

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower = []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 1e-9:
            lower.pop()
        lower.append(p)
    upper = []
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 1e-9:
            upper.pop()
        upper.append(p)
    hull = lower[:-1] + upper[:-1]
    if len(hull) < 3:
        die("hull collapsed")
    return hull


def stl_stats(path):
    data = Path(path).read_bytes()
    if len(data) < 84:
        die("empty stl %s" % path)
    n = struct.unpack_from("<I", data, 80)[0]
    if 84 + n * 50 != len(data):
        die("not a binary stl: %s" % path)
    vol = 0.0
    mn = [1e99, 1e99, 1e99]
    mx = [-1e99, -1e99, -1e99]
    off = 84
    for _ in range(n):
        vals = struct.unpack_from("<12fH", data, off)
        ax, ay, az, bx, by, bz, cx, cy, cz = vals[3:12]
        vol += ax * (by * cz - bz * cy) + bx * (cy * az - cz * ay) + cx * (ay * bz - az * by)
        for p in ((ax, ay, az), (bx, by, bz), (cx, cy, cz)):
            for k in range(3):
                mn[k] = min(mn[k], p[k])
                mx[k] = max(mx[k], p[k])
        off += 50
    return vol / 6.0, mn, mx, n


class Builder:
    def __init__(self, part_name):
        self.part = part_name
        self.doc = App.newDocument(part_name)
        self.doc.UndoMode = 0
        self.body = self.doc.addObject("PartDesign::Body", "Body")
        self.body.Label = part_name
        self.doc.recompute()
        self.planes = {f.Name: f for f in self.body.Origin.OriginFeatures}
        self.params = Params(self.doc)
        self.seq = 0
        self.sketches = []
        self._cid = 0

    def bind(self, sk, idx, name, expr):
        if not expr:
            return
        self._cid += 1
        cname = "%s_%d" % (name, self._cid)
        sk.renameConstraint(idx, cname)
        sk.setExpression("Constraints.%s" % cname, expr)

    def check_sketch(self, sk, tag):
        self.doc.recompute()
        code = sk.solve()
        red = list(sk.RedundantConstraints)
        conf = list(sk.ConflictingConstraints)
        mal = list(sk.MalformedConstraints)
        partial = list(sk.PartiallyRedundantConstraints)
        dof = int(sk.DoF)
        full = bool(sk.FullyConstrained)
        status = sk.getStatusString().split("\n")[0]
        line = (
            "%s\t%s\tDoF=%d\tsolve=%d\tfully_constrained=%s\t"
            "redundant=%s\tconflicting=%s\tmalformed=%s\tpartial=%s\tstatus=%s"
            % (self.part, tag, dof, code, full, red, conf, mal, partial, status)
        )
        self.sketches.append(line)
        print("   ", line, flush=True)
        if code != 0 or dof != 0 or not full or red or conf or mal or partial:
            die("sketch %s/%s is not fully constrained" % (self.part, tag))
        if not list(sk.ExpressionEngine):
            die("sketch %s/%s has no spreadsheet expressions" % (self.part, tag))

    def datum(self, kind, offset):
        self.seq += 1
        name = "Datum_%02d" % self.seq
        plane = {"XY": "XY_Plane", "XZ": "XZ_Plane", "YZ": "YZ_Plane"}[kind]
        if kind == "XZ":
            vec = App.Vector(0, 0, -float(offset))
        else:
            vec = App.Vector(0, 0, float(offset))
        datum = self.body.newObject("PartDesign::Plane", name)
        datum.AttachmentSupport = [(self.planes[plane], "")]
        datum.MapMode = "FlatFace"
        datum.AttachmentOffset = App.Placement(vec, App.Rotation())
        self.doc.recompute()
        base = datum.Placement.Base
        got = {"XY": base.z, "XZ": base.y, "YZ": base.x}[kind]
        if abs(got - float(offset)) > 1e-4:
            die("datum %s %s offset %s landed at %s" % (kind, name, offset, got))
        return datum

    def new_sketch(self, tag, kind="XY", offset=0.0):
        # Every sketch hangs off a datum plane that is itself attached to an
        # origin plane. A sketch attached directly to the origin XY plane
        # pockets along -Z, so holes in the floor and the ears miss the solid.
        self.seq += 1
        name = "Sk_%02d_%s" % (self.seq, tag)
        support = self.datum(kind, offset)
        sk = self.body.newObject("Sketcher::SketchObject", name)
        sk.AttachmentSupport = [(support, "")]
        sk.MapMode = "FlatFace"
        self.doc.recompute()
        return sk

    def _sharp_corners(self, sk):
        lines = [i for i, g in enumerate(sk.Geometry) if type(g).__name__ == "LineSegment"]
        found = []
        for ia in lines:
            ga = sk.Geometry[ia]
            for pos, pt in ((1, ga.StartPoint), (2, ga.EndPoint)):
                for ib in lines:
                    if ib == ia:
                        continue
                    gb = sk.Geometry[ib]
                    for other in (gb.StartPoint, gb.EndPoint):
                        if (pt - other).Length < 1e-5 and (ia, pos) not in found:
                            found.append((ia, pos))
        return found

    def _fillet_all(self, sk, radius, tag):
        radius_geo = None
        for n in range(4):
            corners = self._sharp_corners(sk)
            if not corners:
                die("%s: expected a sharp corner to fillet (%d)" % (tag, n))
            sk.fillet(corners[0][0], corners[0][1], float(radius.v), True, True)
            self.doc.recompute()
            arcs = [i for i, g in enumerate(sk.Geometry) if type(g).__name__ == "ArcOfCircle"]
            if radius_geo is None:
                sk.addConstraint(Sketcher.Constraint("Radius", arcs[-1], float(radius.v)))
                radius_geo = arcs[-1]
            else:
                sk.addConstraint(Sketcher.Constraint("Equal", radius_geo, arcs[-1]))
            self.doc.recompute()
            if sk.solve() != 0 or sk.DoF != 0 or not sk.FullyConstrained:
                die("%s: fillet %d left DoF=%s" % (tag, n, sk.DoF))
        # Fillet rewrites earlier constraints, so find the radius by type.
        radius_idx = [i for i, c in enumerate(sk.Constraints) if c.Type == "Radius"]
        if len(radius_idx) != 1:
            die("%s: expected one radius constraint, found %s" % (tag, radius_idx))
        self.bind(sk, radius_idx[0], tag + "_r", radius.e)

    def add_rect(self, sk, x, y, w, h, tag, radius=None):
        x0, y0, ww, hh = x.v, y.v, w.v, h.v
        if ww <= 0 or hh <= 0:
            die("%s: degenerate rectangle %.4f x %.4f" % (tag, ww, hh))
        sk.addGeometry(Part.LineSegment(App.Vector(x0, y0 + hh, 0), App.Vector(x0 + ww, y0 + hh, 0)), False)
        sk.addGeometry(Part.LineSegment(App.Vector(x0 + ww, y0 + hh, 0), App.Vector(x0 + ww, y0, 0)), False)
        sk.addGeometry(Part.LineSegment(App.Vector(x0 + ww, y0, 0), App.Vector(x0, y0, 0)), False)
        sk.addGeometry(Part.LineSegment(App.Vector(x0, y0, 0), App.Vector(x0, y0 + hh, 0)), False)
        sk.addConstraint(Sketcher.Constraint("Coincident", 0, 2, 1, 1))
        sk.addConstraint(Sketcher.Constraint("Coincident", 1, 2, 2, 1))
        sk.addConstraint(Sketcher.Constraint("Coincident", 2, 2, 3, 1))
        sk.addConstraint(Sketcher.Constraint("Coincident", 3, 2, 0, 1))
        sk.addConstraint(Sketcher.Constraint("Horizontal", 0))
        sk.addConstraint(Sketcher.Constraint("Horizontal", 2))
        sk.addConstraint(Sketcher.Constraint("Vertical", 1))
        sk.addConstraint(Sketcher.Constraint("Vertical", 3))
        ix = sk.addConstraint(Sketcher.Constraint("DistanceX", 2, 2, x0))
        iy = sk.addConstraint(Sketcher.Constraint("DistanceY", 2, 2, y0))
        iw = sk.addConstraint(Sketcher.Constraint("DistanceX", 0, 1, 0, 2, ww))
        ih = sk.addConstraint(Sketcher.Constraint("DistanceY", 3, 1, 3, 2, hh))
        self.bind(sk, ix, tag + "_x", x.e)
        self.bind(sk, iy, tag + "_y", y.e)
        self.bind(sk, iw, tag + "_w", w.e)
        self.bind(sk, ih, tag + "_h", h.e)
        self.check_sketch(sk, tag)
        if radius is not None and radius.v > 1e-6:
            limit = min(ww, hh) / 2.0 - 1e-4
            if radius.v > limit:
                die("%s: radius %.4f exceeds half-side %.4f" % (tag, radius.v, limit))
            self._fillet_all(sk, radius, tag)
            self.check_sketch(sk, tag + "_round")

    def add_circle(self, sk, cx, cy, radius, tag):
        sk.addGeometry(
            Part.Circle(App.Vector(cx.v, cy.v, 0), App.Vector(0, 0, 1), radius.v),
            False,
        )
        ix = sk.addConstraint(Sketcher.Constraint("DistanceX", 0, 3, cx.v))
        iy = sk.addConstraint(Sketcher.Constraint("DistanceY", 0, 3, cy.v))
        ir = sk.addConstraint(Sketcher.Constraint("Radius", 0, radius.v))
        self.bind(sk, ix, tag + "_cx", cx.e)
        self.bind(sk, iy, tag + "_cy", cy.e)
        self.bind(sk, ir, tag + "_r", radius.e)
        self.check_sketch(sk, tag)

    def add_polygon(self, sk, pts, tag):
        # pts: list of (Dim x, Dim y) in sketch coordinates
        n = len(pts)
        if n < 3:
            die("%s: polygon too small" % tag)
        for i in range(n):
            a = pts[i]
            b = pts[(i + 1) % n]
            sk.addGeometry(
                Part.LineSegment(App.Vector(a[0].v, a[1].v, 0), App.Vector(b[0].v, b[1].v, 0)),
                False,
            )
        for i in range(n):
            sk.addConstraint(Sketcher.Constraint("Coincident", i, 2, (i + 1) % n, 1))
        for i, (x, y) in enumerate(pts):
            ix = sk.addConstraint(Sketcher.Constraint("DistanceX", i, 1, x.v))
            iy = sk.addConstraint(Sketcher.Constraint("DistanceY", i, 1, y.v))
            self.bind(sk, ix, "%s_v%dx" % (tag, i), x.e)
            self.bind(sk, iy, "%s_v%dy" % (tag, i), y.e)
        self.check_sketch(sk, tag)

    def extrude(self, sk, tag, length, kind, side="One side", reversed_=False):
        self.seq += 1
        name = "%s_%02d_%s" % ("Pad" if kind == "pad" else "Pocket", self.seq, tag)
        feat = self.body.newObject(
            "PartDesign::Pad" if kind == "pad" else "PartDesign::Pocket",
            name,
        )
        feat.Profile = sk
        feat.Length = float(length.v)
        feat.SideType = side
        # A pad follows the sketch normal (+Z on an XY datum). A pocket cuts
        # against that normal, which misses every hole sketched on the floor
        # of the solid. One-sided pockets in this build sit on the low face
        # of the cut, so they are reversed to travel with the pad.
        if kind == "pocket" and reversed_:
            feat.Reversed = True
        feat.setExpression("Length", length.e)
        self.solid(tag)
        return feat

    def solid(self, tag):
        self.doc.recompute()
        shape = self.body.Shape
        state = list(self.body.Tip.State) if self.body.Tip else []
        nsolids = len(shape.Solids) if shape else 0
        vol = shape.Volume if nsolids else 0.0
        valid = bool(shape.isValid()) if shape else False
        print("  %-22s vol=%10.2f solids=%d valid=%s %s" % (tag, vol, nsolids, valid, state), flush=True)
        if (not valid) or nsolids != 1 or vol <= 0 or any(s in ("Invalid", "Error") for s in state):
            die("solid failed after %s/%s" % (self.part, tag))
        return vol

    def pad_rect(self, tag, x, y, w, h, length, z=0.0, radius=None, kind="XY"):
        sk = self.new_sketch(tag, kind, z)
        self.add_rect(sk, x, y, w, h, tag, radius)
        return self.extrude(sk, tag, length, "pad")

    def pocket_rect(self, tag, x, y, w, h, length, z=0.0, radius=None, kind="XY", side="One side"):
        sk = self.new_sketch(tag, kind, z)
        self.add_rect(sk, x, y, w, h, tag, radius)
        return self.extrude(sk, tag, length, "pocket", side, reversed_=(side == "One side"))

    def pad_circle(self, tag, cx, cy, radius, length, z=0.0, kind="XY"):
        sk = self.new_sketch(tag, kind, z)
        self.add_circle(sk, cx, cy, radius, tag)
        return self.extrude(sk, tag, length, "pad")

    def pocket_circle(self, tag, cx, cy, radius, length, z=0.0, kind="XY", side="One side"):
        sk = self.new_sketch(tag, kind, z)
        self.add_circle(sk, cx, cy, radius, tag)
        return self.extrude(sk, tag, length, "pocket", side, reversed_=(side == "One side"))

    def stadium_radius(self, height):
        return height / 2 - self.params.d("stadium_flat") / 2

    def pad_polygon(self, tag, pts, length, z=0.0, kind="XY", side="One side"):
        sk = self.new_sketch(tag, kind, z)
        self.add_polygon(sk, pts, tag)
        return self.extrude(sk, tag, length, "pad", side)

    def hull_xy(self, rects):
        """rects: (x, y, w, h) Dims. Hull in the sketch plane."""
        corners = []
        for x, y, w, h in rects:
            corners.extend([(x, y), (x + w, y), (x + w, y + h), (x, y + h)])
        items = [(p[0].v, p[1].v, p[0], p[1]) for p in corners]
        return [(it[2], it[3]) for it in convex_hull(items)]

    def cut_loft(self, tag, sketch_a, sketch_b):
        before = self.body.Shape.Volume
        self.seq += 1
        loft = self.body.newObject("PartDesign::SubtractiveLoft", "Loft_%02d_%s" % (self.seq, tag))
        loft.Profile = sketch_a
        loft.Sections = [sketch_b]
        loft.Ruled = True
        self.doc.recompute()
        shape = self.body.Shape
        state = list(loft.State)
        if (not shape.isValid()) or len(shape.Solids) != 1 or any(s in ("Invalid", "Error") for s in state):
            die("loft %s failed: %s" % (tag, state))
        delta = before - shape.Volume
        print("  %-22s vol=%10.2f  cut=%.2f" % (tag, shape.Volume, delta), flush=True)
        if delta < 0.5:
            die("loft %s did not remove material (delta %.3f)" % (tag, delta))
        return loft

    def cut_text(self, text, size, anchor, xdir, ydir, extrude, tag):
        import Draft

        ss = Draft.make_shapestring(String=text, FontFile=FONT, Size=float(size.v), Tracking=0)
        try:
            ss.setExpression("Size", size.e)
        except Exception as exc:
            print("  (shapestring size expression unavailable:", exc, ")")
        self.doc.recompute()
        if ss.Name in [o.Name for o in self.body.Group]:
            self.body.removeObject(ss)
        bb = ss.Shape.BoundBox
        center = App.Vector(bb.Center.x, bb.Center.y, 0)
        xd = App.Vector(xdir).normalize()
        yd = App.Vector(ydir).normalize()
        zd = xd.cross(yd)
        mat = App.Matrix()
        mat.A11, mat.A12, mat.A13 = xd.x, yd.x, zd.x
        mat.A21, mat.A22, mat.A23 = xd.y, yd.y, zd.y
        mat.A31, mat.A32, mat.A33 = xd.z, yd.z, zd.z
        rot = App.Rotation(mat)
        ss.Placement = App.Placement(App.Vector(anchor) - rot.multVec(center), rot)
        self.doc.recompute()
        direction = App.Vector(extrude)
        extruded = ss.Shape.extrude(direction)
        if not extruded.Solids:
            die("text %s produced no solids" % tag)
        before = self.body.Shape.Volume
        for i, solid in enumerate(extruded.Solids):
            feat = self.doc.addObject("Part::Feature", "Glyph_%s_%d" % (tag, i))
            feat.Shape = solid
            ghost = self.doc.addObject("PartDesign::Body", "GlyphBody_%s_%d" % (tag, i))
            ghost.BaseFeature = feat
            self.doc.recompute()
            boolean = self.body.newObject("PartDesign::Boolean", "Text_%s_%d" % (tag, i))
            boolean.Type = "Cut"
            boolean.setObjects([ghost])
            self.doc.recompute()
            if (not self.body.Shape.isValid()) or len(self.body.Shape.Solids) != 1:
                die("text cut %s/%d failed" % (tag, i))
        delta = before - self.body.Shape.Volume
        print("  %-22s vol=%10.2f  text_cut=%.2f" % (tag, self.body.Shape.Volume, delta), flush=True)
        if delta < 0.2:
            die("text %s did not cut the solid" % tag)

    def save(self):
        STEP_DIR.mkdir(parents=True, exist_ok=True)
        STL_DIR.mkdir(parents=True, exist_ok=True)
        fcstd = ROOT / ("%s.FCStd" % self.part)
        step = STEP_DIR / ("%s.step" % self.part)
        stl = STL_DIR / ("%s.stl" % self.part)
        self.doc.saveAs(str(fcstd))
        self.body.Shape.exportStep(str(step))
        import MeshPart

        mesh = MeshPart.meshFromShape(
            Shape=self.body.Shape,
            LinearDeflection=0.08,
            AngularDeflection=0.15,
        )
        mesh.write(str(stl))
        if not fcstd.exists() or fcstd.stat().st_size < 1000:
            die("FCStd missing for %s" % self.part)
        if not step.exists() or step.stat().st_size < 1000:
            die("STEP missing for %s" % self.part)
        if not stl.exists() or stl.stat().st_size < 1000:
            die("STL missing for %s" % self.part)
        return fcstd, step, stl


def add_shared(P):
    """Named source dimensions from enclosure/scad/dimensions.scad."""
    src = dict(
        quality=48,
        fit_clearance=0.30,
        wall=2.0,
        floor_t=2.0,
        lid_t=2.0,
        nozzle=0.40,
        skirt_h=5.0,
        skirt_t=1.8,
        skirt_gap=0.35,
        snap_protrusion=0.80,
        snap_catch_h=0.70,
        snap_len=12.0,
        pico_l=51.0,
        pico_w=21.0,
        pico_t=1.0,
        pico_hole_d=2.1,
        pico_hole_dx=47.0,
        pico_hole_dy=11.4,
        pico_pin_pitch=2.54,
        pico_pin_hole_d=1.0,
        pico_usb_overhang=1.3,
        pico_antenna_keepout_l=9.0,
        pico_antenna_keepout_w=14.0,
        pico_header_above_pcb=8.5,
        pico_header_plastic_w=2.54,
        pico_usb_shell_w=8.0,
        pico_usb_shell_h=3.8,
        pico_usb_shell_depth=6.0,
        pico_gutter=11.0,
        pico_antenna_gap=8.0,
        pico_above_header=5.5,
        pico_standoff_h=6.0,
        pico_standoff_od=7.5,
        pico_bootsel_from_usb_edge=7.5,
        pico_bootsel_from_center_y=0.0,
        pico_bootsel_hole_d=7.0,
        oled_pcb_l=36.0,
        oled_pcb_w=12.5,
        oled_pcb_t=1.20,
        oled_glass_t=1.45,
        oled_active_l=22.38,
        oled_active_w=5.58,
        oled_window_extra=0.40,
        oled_connector_w=10.5,
        oled_connector_h=6.5,
        oled_nest_wall=1.0,
        bmp_pcb_l=21.0,
        bmp_pcb_w=18.0,
        bmp_pcb_t=1.6,
        bmp_pin_count=6,
        bmp_pin_pitch=2.54,
        bmp_header_above_pcb=8.5,
        bmp_air=7.2,
        bmp_platform_h=3.0,
        bmp_above_header=1.8,
        m2_insert_od=3.5,
        m2_insert_len=3.0,
        m2_insert_hole_d=3.2,
        m2_insert_hole_depth=3.6,
        m2_clearance_d=2.4,
        m2_head_d=4.0,
        m3_clearance_d=3.4,
        ziptie_slot_l=5.0,
        ziptie_slot_w=2.2,
    )
    for name, value in src.items():
        P.set(name, value)
    # Literals that the OpenSCAD models use inline, named here so sketches can bind them.
    for name, value, origin in (
        ("stadium_flat", 0.04, "freecad stadium fillet flat"),
        ("fuse_overlap", 0.40, "coplanar-union overlap used in the SCAD"),
        ("cut_overshoot", 0.20, "boolean cutter past the solid"),
        ("wall_cut_extra", 1.2, "opening depth beyond the wall"),
        ("boss_top_gap", 0.15, "lid-boss / insert-boss stop short of the rim"),
        ("insert_overlap", 0.05, "clearance bore overlaps the insert bore"),
        ("label_depth", 0.80, "deboss_text depth on the Pico walls"),
        ("label_extra", 0.40, "deboss_text adds this to the extrude"),
        ("lid_label_depth", 0.65, "BMP lid deboss depth"),
    ):
        P.set(name, value, origin)
    P.fml("pico_row_spacing", "7 * pico_pin_pitch", 7 * 2.54)
    P.fml("pico_hole_inset_x", "(pico_l - pico_hole_dx) / 2", (51 - 47) / 2)
    P.fml("pico_hole_inset_y", "(pico_w - pico_hole_dy) / 2", (21 - 11.4) / 2)
    P.fml("pico_usb_opening_w", "pico_usb_shell_w + 3", 11)
    P.fml("pico_usb_opening_h", "pico_usb_shell_h + 2.2", 6)
    P.fml("oled_stack_h", "oled_pcb_t + oled_glass_t", 2.65)
    P.fml("oled_window_l", "oled_active_l + oled_window_extra", 22.78)
    P.fml("oled_window_w", "oled_active_w + oled_window_extra", 5.98)
    P.fml("oled_pocket_l", "oled_pcb_l + 2 * fit_clearance", 36.6)
    P.fml("oled_pocket_w", "oled_pcb_w + 2 * fit_clearance", 13.1)
    P.fml("oled_nest_drop", "oled_stack_h + 0.8", 3.45)
    P.fml("oled_nest_outer_w", "oled_pocket_w + 2 * oled_nest_wall", 15.1)
    P.fml("pico_header_inner_gap", "pico_row_spacing - pico_header_plastic_w", 17.78 - 2.54)
    P.fml("bmp_pocket_l", "bmp_pcb_l + 2 * fit_clearance", 21.6)
    P.fml("bmp_pocket_w", "bmp_pcb_w + 2 * fit_clearance", 18.6)
    P.fml("bmp_chamber_l", "bmp_pcb_l + 2 * bmp_air", 35.4)
    P.fml("bmp_chamber_w", "bmp_pcb_w + 2 * bmp_air", 32.4)
    P.fml("bmp_outer_l", "bmp_chamber_l + 2 * wall", 39.4)
    P.fml("bmp_outer_w", "bmp_chamber_w + 2 * wall", 36.4)
    P.fml(
        "bmp_inner_h",
        "bmp_platform_h + bmp_pcb_t + bmp_header_above_pcb + bmp_above_header",
        3 + 1.6 + 8.5 + 1.8,
    )
    P.fml("bmp_body_h", "floor_t + bmp_inner_h", 2 + 14.9)
    P.fml("snap_ridge_h", "snap_catch_h + snap_protrusion", 1.5)
    P.fml("snap_engagement", "snap_protrusion - skirt_gap", 0.45)
    P.fml("through_wall", "wall + wall_cut_extra", 3.2)


def add_pico_params(P):
    P.set("corner_r", 3.0, "pico_case.scad")
    P.set("ear_l", 16.0, "pico_case.scad")
    P.set("ear_w", 12.0, "pico_case.scad")
    P.set("ear_t", 3.2, "pico_case.scad")
    P.set("ear_inset", 6.0, "pico_case.scad literal")
    P.set("lid_boss_od", 8.0, "pico_case.scad")
    P.set("lid_boss_inset", 3.2, "pico_case.scad")
    P.set("fan_slot_x0", 16.0, "pico_case.scad")
    P.set("fan_slot_x1", 26.5, "pico_case.scad")
    P.set("fan_slot_l", 8.0, "pico_case.scad")
    P.set("fan_slot_h", 4.6, "pico_case.scad")
    P.set("fan_slot_z", 4.2, "pico_case.scad")
    P.set("i2c_int_x", 37.0, "pico_case.scad")
    P.set("i2c_ext_x", 47.5, "pico_case.scad")
    P.set("sensor_slot_l", 8.0, "pico_case.scad")
    P.set("sensor_slot_h", 4.2, "pico_case.scad")
    P.set("sensor_slot_z", 4.0, "pico_case.scad")
    P.set("pwr_slot_x", 16.0, "pico_case.scad")
    P.set("pwr_slot_l", 12.0, "pico_case.scad")
    P.set("pwr_slot_h", 6.0, "pico_case.scad")
    P.set("pwr_slot_z", 4.0, "pico_case.scad")
    P.set("cleat_l", 10.0, "pico_case.scad")
    P.set("cleat_depth", 2.2, "pico_case.scad cleat bar")
    P.set("cleat_h", 1.8, "pico_case.scad cleat bar")
    P.set("oled_shift_x", 6.0, "pico_case.scad")
    P.set("vent_l", 7.0, "pico_case.scad")
    P.set("vent_h", 2.4, "pico_case.scad")
    P.set("vent_z", 15.2, "pico_case.scad")
    P.set("vent_x0", 22.0, "pico_case.scad")
    P.set("vent_x1", 32.0, "pico_case.scad")
    P.set("vent_x2", 44.0, "pico_case.scad")
    P.set("antenna_margin", 4.0, "pico_case.scad")
    P.set("label_fan_size", 3.4, "pico_case.scad")
    P.set("label_i2c_size", 3.2, "pico_case.scad")
    P.set("label_fan_z", 11.6, "pico_case.scad")
    P.set("label_i2c_z", 10.6, "pico_case.scad")
    P.set("label_pwr_z", 12.2, "pico_case.scad")
    P.set("label_anchor", 0.85, "pico_case.scad deboss anchor inside the wall")
    P.set("brace_a_inset_x", 2.0, "pico_case.scad ear_brace")
    P.set("brace_a_shrink", 4.0, "pico_case.scad ear_brace")
    P.set("brace_b_inset_x", 3.0, "pico_case.scad ear_brace")
    P.set("brace_b_shrink", 6.0, "pico_case.scad ear_brace")
    P.set("brace_bar", 2.8, "pico_case.scad ear_brace")
    P.set("brace_neg_out", 1.5, "pico_case.scad ear_brace")
    P.set("brace_pos_drop", 4.3, "pico_case.scad ear_brace")
    P.set("brace_in", 1.4, "pico_case.scad ear_brace")
    P.set("lid_vent_l", 10.0, "pico_case.scad")
    P.set("lid_vent_h", 2.6, "pico_case.scad")
    P.set("lid_vent_dx", 22.0, "pico_case.scad")
    P.set("lid_vent_dy", 16.0, "pico_case.scad")
    P.set("notch_l", 12.0, "pico_case.scad")
    P.set("notch_extra_h", 2.8, "pico_case.scad fingernail")
    P.set("clip_l", 8.0, "pico_case.scad")
    P.set("clip_reach", 0.9, "pico_case.scad")
    P.text("label_fan", "FAN")
    P.text("label_int", "INT")
    P.text("label_ext", "EXT")
    P.text("label_pwr", "PWR")
    P.fml("outer_l", "wall + pico_l + pico_antenna_gap + wall", 63, "pico_case.scad")
    P.fml("outer_w", "wall + pico_gutter + pico_w + pico_gutter + wall", 47, "pico_case.scad")
    P.fml(
        "base_h",
        "floor_t + pico_standoff_h + pico_t + pico_header_above_pcb + pico_above_header",
        23,
        "pico_case.scad",
    )
    P.fml("pcb_x0", "wall", 2, "pico_case.scad")
    P.fml("pcb_y0", "wall + pico_gutter", 13, "pico_case.scad")
    P.fml("pcb_top_z", "floor_t + pico_standoff_h + pico_t", 9, "pico_case.scad")
    P.fml(
        "usb_z0",
        "pcb_top_z + (pico_usb_shell_h - pico_usb_opening_h) / 2",
        9 + (3.8 - 6) / 2,
        "pico_case.scad",
    )
    P.fml("hole_x0", "pcb_x0 + pico_hole_inset_x", 4, "pico_case.scad")
    P.fml("hole_x1", "hole_x0 + pico_hole_dx", 51, "pico_case.scad")
    P.fml("hole_y0", "pcb_y0 + pico_hole_inset_y", 17.8, "pico_case.scad")
    P.fml("hole_y1", "hole_y0 + pico_hole_dy", 29.2, "pico_case.scad")
    P.fml("oled_cx", "pcb_x0 + pico_l / 2 + oled_shift_x", 33.5, "pico_case.scad")
    P.fml("oled_cy", "pcb_y0 + pico_w / 2", 23.5, "pico_case.scad")
    P.fml("lid_outer_l", "outer_l + 2 * (skirt_gap + skirt_t)", 67.3, "pico_case.scad")
    P.fml("lid_outer_w", "outer_w + 2 * (skirt_gap + skirt_t)", 51.3, "pico_case.scad")
    P.fml("pwr_cleat_l", "pwr_slot_l + 4", 16, "pico_case.scad")
    P.fml("antenna_aperture", "pico_antenna_keepout_w + antenna_margin", 18, "pico_case.scad")
    P.fml("standoff_h", "floor_t + pico_standoff_h", 8, "pico_case.scad")
    P.fml("boss_h", "base_h - boss_top_gap", 22.85, "pico_case.scad")
    P.fml("ear_x0", "ear_inset", 6, "pico_case.scad")
    P.fml("ear_x1", "outer_l - ear_inset - ear_l", 41, "pico_case.scad")
    P.fml("skirt_corner_r", "corner_r - 0.2", 2.8, "pico_case.scad")
    P.fml("label_extrude", "label_depth + label_extra", 1.2, "lib.scad deboss_text")
    P.check()


def add_bmp_params(P, ext):
    P.set("corner_r", 2.4, "bmp280_housing.scad")
    P.set("lv_h", 1.8, "bmp280_housing.scad")
    P.set("lv_len", 12.0, "bmp280_housing.scad")
    P.set("lv_z0", 5.2, "bmp280_housing.scad")
    P.set("lv_z1", 8.15, "bmp280_housing.scad")
    P.set("ext_slot_h", 1.8, "bmp280_housing.scad")
    P.set("ext_slot_z0", 4.0, "bmp280_housing.scad")
    P.set("ext_slot_z1", 7.4, "bmp280_housing.scad")
    P.set("tab_t", 3.0, "bmp280_housing.scad")
    P.set("tab_w", 14.0, "bmp280_housing.scad")
    P.set("tab_l", 16.0, "bmp280_housing.scad")
    P.set("tab_gusset_rise", 5.2, "bmp280_housing.scad")
    P.set("tab_overlap", 0.5, "bmp280_housing.scad")
    P.set("tab_bite", 0.6, "bmp280_housing.scad gusset")
    P.set("cable_w", 8.5, "bmp280_housing.scad")
    P.set("cable_h", 4.4, "bmp280_housing.scad")
    P.set("cable_z0", 3.8, "bmp280_housing.scad")
    P.set("cable_awning_root", 3.3, "bmp280_housing.scad")
    P.set("cable_awning_proj", 2.0, "bmp280_housing.scad")
    P.set("cable_awning_tip", 0.6, "bmp280_housing.scad")
    P.set("awning_sink", 0.45, "lib.scad rain_hood root overlap")
    P.set("awning_tip_stub", 0.15, "lib.scad rain_hood")
    P.set("awning_tip_lift", 0.35, "lib.scad rain_hood")
    P.set("awning_extra_l", 2.4, "bmp280_housing.scad cable_awning")
    P.set("boss_od", 6.6, "bmp280_housing.scad")
    P.set("boss_bite", 0.55, "bmp280_housing.scad")
    P.set("eave_int", 0.3, "bmp280_housing.scad")
    P.set("eave_ext", 1.6, "bmp280_housing.scad")
    P.set("rail_t", 1.2, "bmp280_housing.scad")
    P.set("plate_lip", 0.15, "bmp280_housing.scad")
    P.set("rail_h", 1.15, "bmp280_housing.scad")
    P.set("rail_drop", 0.4, "bmp280_housing.scad")
    P.set("plate_t", 1.4, "bmp280_housing.scad")
    P.set("leg", 2.0, "bmp280_housing.scad")
    P.set("leg_inset", 0.35, "bmp280_housing.scad")
    P.set("plate_hole_x", 4.0, "bmp280_housing.scad")
    P.set("plate_hole_y", 3.6, "bmp280_housing.scad")
    P.set("baffle_t", 1.3, "bmp280_housing.scad")
    P.set("baffle_bite", 0.45, "bmp280_housing.scad")
    P.set("baffle_drop", 0.2, "bmp280_housing.scad")
    P.set("corner_gap", 6.5, "bmp280_housing.scad")
    P.set("baffle_clear", 0.8, "bmp280_housing.scad")
    P.set("cable_lv_len", 8.0, "bmp280_housing.scad")
    P.set("end_slot_l", 10.0, "bmp280_housing.scad")
    P.set("end_slot_gap", 0.7, "bmp280_housing.scad")
    P.set("snap_bite", 0.4, "bmp280_housing.scad")
    P.set("snap_z_drop", 1.05, "bmp280_housing.scad")
    P.set("cleat_post", 1.3, "bmp280_housing.scad")
    P.set("cleat_post_t", 1.5, "bmp280_housing.scad")
    P.set("cleat_bar_t", 2.2, "bmp280_housing.scad")
    P.set("cleat_bar_h", 1.6, "bmp280_housing.scad")
    P.set("hold_inset", 3.2, "bmp280_housing.scad")
    P.set("hold_d", 3.2, "bmp280_housing.scad")
    P.set("hold_gap", 0.40, "bmp280_housing.scad")
    P.set("lid_vent_l", 11.0, "bmp280_housing.scad")
    P.set("lid_vent_h", 2.2, "bmp280_housing.scad")
    P.set("lid_vent_dx", 10.0, "bmp280_housing.scad")
    P.set("lid_label_size", 7.0, "bmp280_housing.scad")
    P.set("notch_l", 12.0, "bmp280_housing.scad")
    P.set("notch_h", 2.6, "bmp280_housing.scad")
    P.set("win_pad", 0.8, "bmp280_housing.scad snap window")
    P.set("win_z_pad", 0.25, "bmp280_housing.scad snap window")
    P.set("win_extra", 1.4, "bmp280_housing.scad snap window")
    P.set("far_frac_a", 0.32, "bmp280_housing.scad")
    P.set("far_frac_b", 0.68, "bmp280_housing.scad")
    P.set("cable_frac_a", 0.20, "bmp280_housing.scad")
    P.set("cable_frac_b", 0.80, "bmp280_housing.scad")
    P.set("is_ext", 1 if ext else 0, "bmp280_housing.scad variant")
    P.text("label", "EXT" if ext else "INT")
    P.fml("ext_slope", "wall + 1", 3, "bmp280_housing.scad")
    P.fml("boss_r", "boss_od / 2", 3.3, "bmp280_housing.scad")
    P.fml("boss_from_inner", "boss_r - boss_bite", 2.75, "bmp280_housing.scad")
    P.fml("eave", "eave_ext" if ext else "eave_int", 1.6 if ext else 0.3, "bmp280_housing.scad")
    P.fml("lid_skirt_l", "bmp_outer_l + 2 * (skirt_gap + skirt_t)", 39.4 + 2 * 2.15, "bmp280_housing.scad")
    P.fml("lid_skirt_w", "bmp_outer_w + 2 * (skirt_gap + skirt_t)", 36.4 + 2 * 2.15, "bmp280_housing.scad")
    P.fml("lid_outer_l", "lid_skirt_l + 2 * eave", (39.4 + 4.3) + 2 * (1.6 if ext else 0.3), "bmp280_housing.scad")
    P.fml("lid_outer_w", "lid_skirt_w + 2 * eave", (36.4 + 4.3) + 2 * (1.6 if ext else 0.3), "bmp280_housing.scad")
    P.fml("lid_corner_r", "corner_r + eave", 2.4 + (1.6 if ext else 0.3), "bmp280_housing.scad")
    P.fml("tab_gusset_run", "tab_l * 0.55", 8.8, "bmp280_housing.scad")
    P.fml("pin_gap", "bmp_pin_count * bmp_pin_pitch + 1.2", 6 * 2.54 + 1.2, "bmp280_housing.scad")
    P.fml("ext_inner_top", "ext_slot_z1 + ext_slope + ext_slot_h", 7.4 + 3 + 1.8, "bmp280_housing.scad")
    P.fml("int_slot_top", "lv_z1 + lv_h", 8.15 + 1.8, "bmp280_housing.scad")
    P.fml("baffle_top_z", "ext_inner_top + baffle_clear", 12.2 + 0.8, "bmp280_housing.scad")
    P.fml("boss_h", "bmp_body_h - boss_top_gap - (floor_t - fuse_overlap)", 16.9 - 0.15 - (2 - 0.4), "bmp280_housing.scad")
    P.fml("label_extrude", "lid_label_depth + label_extra", 1.05, "lib.scad")
    P.check()


def zero():
    return Dim(0, "0")


def lit(value):
    return Dim(float(value), "%.10g" % float(value))


def expect(dim, value, label):
    if abs(dim.v - value) > 1e-6:
        die("%s is %.6f, expected %.6f" % (label, dim.v, value))


def finish(builder, probes):
    shape = builder.body.Shape
    ref = REF_STL / ("%s.stl" % builder.part)
    ref_vol, ref_mn, ref_mx, ntri = stl_stats(ref)
    bb = shape.BoundBox
    got_mn = (bb.XMin, bb.YMin, bb.ZMin)
    got_mx = (bb.XMax, bb.YMax, bb.ZMax)
    bbox_err = max(abs(got_mn[i] - ref_mn[i]) for i in range(3))
    bbox_err = max(bbox_err, max(abs(got_mx[i] - ref_mx[i]) for i in range(3)))
    vol_err = abs(shape.Volume - ref_vol)
    rel = vol_err / ref_vol if ref_vol else 1
    print(
        "COMPARE %s solid=%.2f stl=%.2f dV=%.2f (%.3f%%) dBox=%.4f tris=%d"
        % (builder.part, shape.Volume, ref_vol, shape.Volume - ref_vol, 100 * rel, bbox_err, ntri),
        flush=True,
    )
    print(
        "  bbox solid [%.3f %.3f %.3f] [%.3f %.3f %.3f]"
        % (got_mn + got_mx),
        flush=True,
    )
    print(
        "  bbox stl   [%.3f %.3f %.3f] [%.3f %.3f %.3f]"
        % tuple(ref_mn + ref_mx),
        flush=True,
    )
    probe_fail = []
    for x, y, z, want_solid, label in probes:
        got = shape.isInside(App.Vector(x, y, z), 0.02, True)
        if bool(got) != bool(want_solid):
            probe_fail.append("%s (%.2f,%.2f,%.2f) solid=%s want=%s" % (label, x, y, z, got, want_solid))
    if probe_fail:
        die("probes failed for %s: %s" % (builder.part, probe_fail))
    if bbox_err > BBOX_TOL:
        die("%s bbox error %.4f mm exceeds %.4f" % (builder.part, bbox_err, BBOX_TOL))
    if vol_err > VOL_ABS_TOL and rel > VOL_REL_TOL:
        die("%s volume error %.2f mm^3 (%.3f%%) exceeds tolerance" % (builder.part, vol_err, 100 * rel))
    builder.save()
    _REPORT.extend(builder.sketches)
    _REPORT.append(
        "RESULT\t%s\tvolume_solid=%.3f\tvolume_openscad_stl=%.3f\tdelta=%.3f\trel=%.6f\tbbox_delta=%.4f\tprobes=%d"
        % (builder.part, shape.Volume, ref_vol, shape.Volume - ref_vol, rel, bbox_err, len(probes))
    )
    App.closeDocument(builder.doc.Name)


# --------------------------------------------------------------------------
# Pico case
# --------------------------------------------------------------------------

def build_pico_base():
    b = Builder("pico_case_base")
    P = b.params
    add_shared(P)
    add_pico_params(P)
    d = P.d
    outer_l, outer_w, base_h = d("outer_l"), d("outer_w"), d("base_h")
    expect(outer_l, 63, "outer_l")
    expect(outer_w, 47, "outer_w")
    expect(base_h, 23, "base_h")
    wall = d("wall")
    corner = d("corner_r")
    b.pad_rect("shell", zero(), zero(), outer_l, outer_w, base_h, radius=corner)

    ear_l, ear_w, ear_t = d("ear_l"), d("ear_w"), d("ear_t")
    overlap = d("fuse_overlap")
    for i, ex in enumerate((d("ear_x0"), d("ear_x1"))):
        b.pad_rect("ear_n_%d" % i, ex, -ear_w, ear_l, ear_w + overlap, ear_t)
        b.pad_rect("ear_p_%d" % i, ex, outer_w - overlap, ear_l, ear_w + overlap, ear_t)
        brace(b, ex, -ear_w + d("brace_neg_out"), -d("brace_in"), "bn%d" % i)
        brace(
            b,
            ex,
            outer_w + ear_w - d("brace_pos_drop"),
            outer_w - d("brace_in"),
            "bp%d" % i,
        )

    inner_l = outer_l - 2 * wall
    inner_w = outer_w - 2 * wall
    b.pocket_rect(
        "cavity",
        wall,
        wall,
        inner_l,
        inner_w,
        base_h - d("floor_t") + d("cut_overshoot"),
        z=d("floor_t").v,
    )

    # Openings. Sketch on a datum through the wall; local axes follow the datum.
    through = d("through_wall")
    usb_y = d("pcb_y0") + d("pico_w") / 2
    b.pocket_rect(
        "usb",
        usb_y - d("pico_usb_opening_w") / 2,
        d("usb_z0"),
        d("pico_usb_opening_w"),
        d("pico_usb_opening_h"),
        through,
        z=(wall / 2).v,
        radius=b.stadium_radius(d("pico_usb_opening_h")),
        kind="YZ",
        side="Symmetric",
    )
    ant_y = d("pcb_y0") + (d("pico_w") - d("antenna_aperture")) / 2
    ant_z = d("pcb_top_z") - lit(2)
    ant_x = outer_l - wall / 2 + lit(0.2)
    b.pocket_rect(
        "antenna",
        ant_y,
        ant_z,
        d("antenna_aperture"),
        base_h,
        through,
        z=ant_x.v,
        kind="YZ",
        side="Symmetric",
    )
    slot_y = wall / 2
    for i, cx in enumerate((d("fan_slot_x0"), d("fan_slot_x1"))):
        wall_slot(b, "fan_%d" % i, cx, slot_y, d("fan_slot_z"), d("fan_slot_l"), d("fan_slot_h"), through)
    for i, cx in enumerate((d("i2c_int_x"), d("i2c_ext_x"))):
        wall_slot(b, "i2c_%d" % i, cx, slot_y, d("sensor_slot_z"), d("sensor_slot_l"), d("sensor_slot_h"), through)
    wall_slot(
        b,
        "pwr",
        d("pwr_slot_x"),
        outer_w - wall / 2,
        d("pwr_slot_z"),
        d("pwr_slot_l"),
        d("pwr_slot_h"),
        through,
    )
    for i, cx in enumerate((d("vent_x0"), d("vent_x1"))):
        wall_slot(b, "vent_n_%d" % i, cx, slot_y, d("vent_z"), d("vent_l"), d("vent_h"), through)
        wall_slot(b, "vent_p_%d" % i, cx, outer_w - wall / 2, d("vent_z"), d("vent_l"), d("vent_h"), through)
    wall_slot(b, "vent_pwr", d("vent_x2"), outer_w - wall / 2, d("vent_z"), d("vent_l"), d("vent_h"), through)

    m3r = d("m3_clearance_d") / 2
    slot_gap = m3r + lit(0.9)
    for i, ex in enumerate((d("ear_x0") + ear_l / 2, d("ear_x1") + ear_l / 2)):
        for j, (ey, sign) in enumerate(((-ear_w * lit(0.62), lit(1)), (outer_w + ear_w * lit(0.62), lit(-1)))):
            b.pocket_circle("ear_screw_%d%d" % (i, j), ex, ey, m3r, ear_t)
            if sign.v > 0:
                sy = ey + slot_gap
            else:
                sy = ey - slot_gap - d("ziptie_slot_w")
            b.pocket_rect(
                "ear_zip_%d%d" % (i, j),
                ex - d("ziptie_slot_l") / 2,
                sy,
                d("ziptie_slot_l"),
                d("ziptie_slot_w"),
                ear_t,
            )

    extrude = d("label_extrude")
    anchor_y = d("label_anchor")
    b.cut_text(
        "FAN",
        d("label_fan_size"),
        App.Vector((d("fan_slot_x0").v + d("fan_slot_x1").v) / 2, anchor_y.v, d("label_fan_z").v),
        (-1, 0, 0),
        (0, 0, 1),
        (0, -extrude.v, 0),
        "fan",
    )
    for word, cx, size in (
        ("INT", d("i2c_int_x"), d("label_i2c_size")),
        ("EXT", d("i2c_ext_x"), d("label_i2c_size")),
    ):
        b.cut_text(
            word,
            size,
            App.Vector(cx.v, anchor_y.v, d("label_i2c_z").v),
            (-1, 0, 0),
            (0, 0, 1),
            (0, -extrude.v, 0),
            word.lower(),
        )
    b.cut_text(
        "PWR",
        d("label_fan_size"),
        App.Vector(d("pwr_slot_x").v, (outer_w - anchor_y).v, d("label_pwr_z").v),
        (1, 0, 0),
        (0, 0, 1),
        (0, extrude.v, 0),
        "pwr",
    )

    insert_r = d("m2_insert_hole_d") / 2
    clear_r = d("m2_clearance_d") / 2
    standoff_r = d("pico_standoff_od") / 2
    for i, hx in enumerate((d("hole_x0"), d("hole_x1"))):
        for j, hy in enumerate((d("hole_y0"), d("hole_y1"))):
            b.pad_circle("standoff_%d%d" % (i, j), hx, hy, standoff_r, d("standoff_h"))
    for i, hx in enumerate((d("hole_x0"), d("hole_x1"))):
        for j, hy in enumerate((d("hole_y0"), d("hole_y1"))):
            b.pocket_circle("insert_%d%d" % (i, j), hx, hy, insert_r, d("m2_insert_hole_depth"))
            b.pocket_circle(
                "clear_%d%d" % (i, j),
                hx,
                hy,
                clear_r,
                d("standoff_h") - d("m2_insert_hole_depth") + d("insert_overlap"),
                z=(d("m2_insert_hole_depth") - d("insert_overlap")).v,
            )

    boss_r = d("lid_boss_od") / 2
    inset = d("lid_boss_inset")
    bosses = (
        (wall + inset, wall + inset),
        (wall + inset, outer_w - wall - inset),
        (outer_l - wall - inset, wall + inset),
        (outer_l - wall - inset, outer_w - wall - inset),
    )
    for i, (bx, by) in enumerate(bosses):
        b.pad_circle("boss_%d" % i, bx, by, boss_r, d("boss_h"))
    boss_hole_z = d("boss_h") - d("m2_insert_hole_depth")
    for i, (bx, by) in enumerate(bosses):
        b.pocket_circle(
            "boss_ins_%d" % i,
            bx,
            by,
            insert_r,
            d("m2_insert_hole_depth") + d("cut_overshoot"),
            z=boss_hole_z.v,
        )

    cleat_h = d("cleat_h")
    for i, cx in enumerate((d("fan_slot_x0"), d("fan_slot_x1"))):
        cleat(b, "cf%d" % i, cx, wall - overlap, d("fan_slot_z") + d("fan_slot_h") - lit(2.4), d("cleat_l"), cleat_h)
    cleat(b, "cint", d("i2c_int_x"), wall - overlap, d("sensor_slot_z") + d("sensor_slot_h") - lit(2.3), d("cleat_l"), cleat_h)
    cleat(b, "cext", d("i2c_ext_x"), wall - overlap, d("sensor_slot_z") + d("sensor_slot_h") - lit(2.3), d("cleat_l"), cleat_h)
    cleat(
        b,
        "cpwr",
        d("pwr_slot_x"),
        outer_w - wall - d("cleat_h"),
        d("pwr_slot_z") + d("pwr_slot_h") - lit(2.6),
        d("pwr_cleat_l"),
        cleat_h,
    )
    return b


def cleat(b, tag, x, y, z, length, height):
    b.pad_rect(tag, x - length / 2, y, length, b.params.d("cleat_depth"), height, z=z.v)


def brace(b, ear_x, y_out, y_in, tag):
    P = b.params
    d = P.d
    bar = d("brace_bar")
    a = (ear_x + d("brace_a_inset_x"), y_out, d("ear_l") - d("brace_a_shrink"), bar)
    c = (ear_x + d("brace_b_inset_x"), y_in, d("ear_l") - d("brace_b_shrink"), bar)
    pts = b.hull_xy((a, c))
    b.pad_polygon(tag, pts, d("ear_t"))


def wall_slot(b, tag, cx, y_center, z0, length, height, through):
    """Stadium through a Y-normal wall. Sketch is on the XZ datum (local X = global X, local Y = global Z)."""
    b.pocket_rect(
        tag,
        cx - length / 2,
        z0,
        length,
        height,
        through,
        z=y_center.v,
        radius=b.stadium_radius(height),
        kind="XZ",
        side="Symmetric",
    )


def build_pico_lid():
    b = Builder("pico_case_lid")
    P = b.params
    add_shared(P)
    add_pico_params(P)
    d = P.d
    lid_l, lid_w = d("lid_outer_l"), d("lid_outer_w")
    expect(lid_l, 67.3, "lid_outer_l")
    expect(lid_w, 51.3, "lid_outer_w")
    b.pad_rect("plate", zero(), zero(), lid_l, lid_w, d("lid_t"), radius=d("corner_r"))
    skirt_l = d("outer_l") + 2 * d("skirt_gap")
    skirt_w = d("outer_w") + 2 * d("skirt_gap")
    b.pad_rect(
        "skirt",
        d("skirt_gap"),
        d("skirt_gap"),
        skirt_l,
        skirt_w,
        d("skirt_h") + d("fuse_overlap"),
        z=(d("lid_t") - d("fuse_overlap")).v,
        radius=d("skirt_corner_r"),
    )
    b.pocket_rect(
        "skirt_void",
        d("skirt_gap") + d("skirt_t"),
        d("skirt_gap") + d("skirt_t"),
        skirt_l - 2 * d("skirt_t"),
        skirt_w - 2 * d("skirt_t"),
        d("skirt_h") + d("cut_overshoot"),
        z=d("lid_t").v,
    )

    def lid_of(body_coord, body_span, lid_span):
        return (lid_span - body_span) / 2 + body_coord

    ox = lid_of(d("oled_cx"), d("outer_l"), lid_l)
    oy = lid_of(d("oled_cy"), d("outer_w"), lid_w)
    x0 = ox - d("oled_pocket_l") / 2 - d("oled_nest_wall")
    y0 = oy - d("oled_pocket_w") / 2 - d("oled_nest_wall")
    nx = d("oled_pocket_l") + 2 * d("oled_nest_wall")
    ny = d("oled_pocket_w") + 2 * d("oled_nest_wall")
    nest_z = d("lid_t") - d("fuse_overlap")
    b.pad_rect("nest", x0, y0, nx, ny, d("oled_nest_drop") + d("fuse_overlap"), z=nest_z.v)
    # The OpenSCAD void is inside the nest difference, so it does not cut the
    # lid plate under the pocket. Start the pockets at the top of the plate.
    b.pocket_rect(
        "nest_void",
        x0 + d("oled_nest_wall"),
        y0 + d("oled_nest_wall"),
        d("oled_pocket_l"),
        d("oled_pocket_w"),
        d("oled_nest_drop") + d("cut_overshoot"),
        z=d("lid_t").v,
    )
    gap = d("oled_connector_w") + lit(2)
    b.pocket_rect(
        "nest_gap",
        x0 - d("cut_overshoot"),
        y0 + (ny - gap) / 2,
        d("oled_nest_wall") + d("fuse_overlap") + d("cut_overshoot"),
        gap,
        d("oled_nest_drop") + d("cut_overshoot"),
        z=d("lid_t").v,
    )
    add_clips(b, x0, y0, nx, nest_z)

    # Blind window: the OpenSCAD cube is centered at z=-0.2 and does not reach
    # the top of the 2 mm plate. Match that recess.
    window_top = (d("lid_t") + lit(0.5)) / 2 + lit(-0.2)
    b.pocket_rect(
        "window",
        ox - d("oled_window_l") / 2,
        oy - d("oled_window_w") / 2,
        d("oled_window_l"),
        d("oled_window_w"),
        window_top,
    )
    bootsel_x = lid_of(d("pcb_x0") + d("pico_bootsel_from_usb_edge"), d("outer_l"), lid_l)
    bootsel_y = lid_of(d("pcb_y0") + d("pico_w") / 2 + d("pico_bootsel_from_center_y"), d("outer_w"), lid_w)
    b.pocket_circle("bootsel", bootsel_x, bootsel_y, d("pico_bootsel_hole_d") / 2, d("lid_t"))
    inset = d("lid_boss_inset")
    wall = d("wall")
    bosses = (
        (wall + inset, wall + inset),
        (wall + inset, d("outer_w") - wall - inset),
        (d("outer_l") - wall - inset, wall + inset),
        (d("outer_l") - wall - inset, d("outer_w") - wall - inset),
    )
    for i, (bx, by) in enumerate(bosses):
        b.pocket_circle(
            "screw_%d" % i,
            lid_of(bx, d("outer_l"), lid_l),
            lid_of(by, d("outer_w"), lid_w),
            d("m2_clearance_d") / 2,
            d("lid_t"),
        )
    through_lid = d("lid_t") + d("label_extra") + d("cut_overshoot")
    for sx in (lit(-1), lit(1)):
        for sy in (lit(-1), lit(1)):
            cx = lid_l / 2 + sx * d("lid_vent_dx")
            cy = lid_w / 2 + sy * d("lid_vent_dy")
            b.pocket_rect(
                "lvent",
                cx - d("lid_vent_l") / 2,
                lit(-0.2),
                d("lid_vent_l"),
                d("lid_vent_h"),
                through_lid,
                z=cy.v,
                radius=b.stadium_radius(d("lid_vent_h")),
                kind="XZ",
                side="Symmetric",
            )
    skirt_outer_y = d("skirt_gap") + d("outer_w") + 2 * d("skirt_gap")
    notch_y = skirt_outer_y - d("skirt_t") / 2
    notch_z = d("lid_t") + d("skirt_h") - lit(1.3)
    b.pocket_rect(
        "notch",
        ox - d("notch_l") / 2,
        notch_y - (d("skirt_t") + lit(1.6)) / 2,
        d("notch_l"),
        d("skirt_t") + lit(1.6),
        d("notch_extra_h"),
        z=notch_z.v,
        kind="XY",
        side="Symmetric",
    )
    return b


def add_clips(b, x0, y0, nx, nest_z):
    """OLED retaining clips. Geometry matches pico_case.scad oled_nest()."""
    d = b.params.d
    clip_z = nest_z + d("oled_nest_drop") - d("clip_reach")
    reach = d("clip_reach")
    length = d("clip_l")
    ax = x0 + nx * lit(0.42)
    # side 0 grabs the -Y inner edge; side 1 the +Y edge, wedge flipped.
    yy0 = y0 + d("oled_nest_wall") - d("fuse_overlap")
    yy1 = y0 + d("oled_nest_wall") + d("oled_pocket_w") - lit(0.5)
    b.pad_rect("clip0", ax, yy0, length, reach, reach, z=clip_z.v)
    b.pad_rect("clip1", ax, yy1, length, reach, reach, z=clip_z.v)
    # Wedges are the convex hull of two thin boxes, prismatic along X.
    eps = lit(0.02)
    rise = lit(0.7)
    z1 = clip_z + reach
    # side 0
    wedge_pad(
        b,
        "wedge0",
        ax + length / 2,
        length,
        [
            (yy0, z1, reach, eps),
            (yy0 + reach, z1 + rise, eps, eps),
        ],
    )
    # side 1: the SCAD rotates the same hull 180 degrees about X
    # after shifting it by -reach in Y. The resulting boxes sit on the clip.
    wedge_pad(
        b,
        "wedge1",
        ax + length / 2,
        length,
        [
            (yy1 + lit(0.5), z1 - eps, reach, eps),
            (yy1 + lit(0.5) - eps, z1 - rise - eps, eps, eps),
        ],
    )


def wedge_pad(b, tag, x_center, length, rects):
    """rects are (y, z, dy, dz) global. Sketch on a YZ datum, pad along X."""
    corners = []
    for y, z, dy, dz in rects:
        corners.extend([(y, z), (y + dy, z), (y + dy, z + dz), (y, z + dz)])
    items = [(p[0].v, p[1].v, p[0], p[1]) for p in corners]
    pts = [(it[2], it[3]) for it in convex_hull(items)]
    # local X = global Y, local Y = global Z
    b.pad_polygon(tag, pts, length, z=x_center.v, kind="YZ", side="Symmetric")


# --------------------------------------------------------------------------
# BMP280 housing
# --------------------------------------------------------------------------

def build_bmp_body(ext):
    name = "bmp280_ext_body" if ext else "bmp280_int_body"
    b = Builder(name)
    P = b.params
    add_shared(P)
    add_bmp_params(P, ext)
    d = P.d
    outer_l, outer_w, body_h = d("bmp_outer_l"), d("bmp_outer_w"), d("bmp_body_h")
    expect(outer_l, 39.4, "bmp_outer_l")
    expect(outer_w, 36.4, "bmp_outer_w")
    expect(body_h, 16.9, "bmp_body_h")
    wall = d("wall")
    b.pad_rect("shell", zero(), zero(), outer_l, outer_w, body_h, radius=d("corner_r"))
    y0 = (outer_w - d("tab_w")) / 2
    b.pad_rect("tab_n", -d("tab_l"), y0, d("tab_l") + d("tab_overlap"), d("tab_w"), d("tab_t"))
    b.pad_rect("tab_p", outer_l - d("tab_overlap"), y0, d("tab_l") + d("tab_overlap"), d("tab_w"), d("tab_t"))
    gusset(b, "gus_n", sign=-1)
    gusset(b, "gus_p", sign=1)
    if ext:
        awning(b)

    b.pocket_rect(
        "cavity",
        wall,
        wall,
        d("bmp_chamber_l"),
        d("bmp_chamber_w"),
        body_h - d("floor_t") + d("cut_overshoot"),
        z=d("floor_t").v,
    )
    through = d("through_wall")
    if ext:
        ext_louvers(b)
    else:
        int_louvers(b, through)
    wall_slot(
        b,
        "cable",
        outer_l / 2,
        zero(),
        d("cable_z0"),
        d("cable_w"),
        d("cable_h"),
        through,
    )
    for sign, cx in ((-1, -d("tab_l") * lit(0.46)), (1, outer_l + d("tab_l") * lit(0.46))):
        b.pocket_circle("tab_screw", cx, outer_w / 2 - lit(2.4), d("m3_clearance_d") / 2, d("tab_t"))
        b.pocket_rect(
            "tab_zip",
            cx - d("ziptie_slot_l") / 2,
            outer_w / 2 + lit(1.6),
            d("ziptie_slot_l"),
            d("ziptie_slot_w"),
            d("tab_t"),
        )
    platform(b)
    rails_and_baffle(b)
    strain(b)
    insert_bosses(b)
    snaps(b)
    return b


def gusset(b, tag, sign):
    d = b.params.d
    run = d("tab_gusset_run")
    bite = d("tab_bite")
    rise = d("tab_gusset_rise")
    z0 = d("tab_t") - bite
    z1 = d("tab_t") + rise
    if sign < 0:
        pts = [(bite, z0), (-run, z0), (bite, z1)]
    else:
        pts = [(d("bmp_outer_l") - bite, z0), (d("bmp_outer_l") + run, z0), (d("bmp_outer_l") - bite, z1)]
    # Sketch on XZ: local X = global X, local Y = global Z. Pad along Y.
    b.pad_polygon(tag, pts, d("tab_w"), z=(d("bmp_outer_w") / 2).v, kind="XZ", side="Symmetric")


def awning(b):
    """Printable cable hood: convex hull of the two rain_hood boxes, rotated 180 deg."""
    d = b.params.d
    proj = d("cable_awning_proj")
    root = d("cable_awning_root")
    tip = d("cable_awning_tip")
    sink = d("awning_sink")
    stub = d("awning_tip_stub")
    lift = d("awning_tip_lift")
    zbase = d("cable_z0") + d("cable_h")
    # After rot180 and the Y translation by `sink`, in global YZ:
    # A (root) y [sink, 2*sink] if the unrotated root spans [-sink, 0] and sink is 0.45.
    # rain_hood root cube is y [-0.45, 0] with 0.45 hardcoded as the first overlap.
    # The module argument is not that 0.45; cable_awning passes the hood then we
    # translate by +0.45. Keep the SCAD literals.
    root_y0 = lit(-0.45)
    root_y1 = zero()
    tip_y0 = proj - stub
    tip_y1 = proj
    tip_z0 = proj + lift
    # rot180 about Z flips Y, then translate Y by 0.45 and Z by zbase.
    def flip(y0, y1, z0, z1):
        # (y, z) -> (-y, z) then + (0.45, zbase). y interval reverses.
        ny0 = -y1 + lit(0.45)
        ny1 = -y0 + lit(0.45)
        return ny0, ny1, z0 + zbase, z1 + zbase

    ay0, ay1, az0, az1 = flip(root_y0, root_y1, zero(), root)
    by0, by1, bz0, bz1 = flip(tip_y0, tip_y1, tip_z0, tip_z0 + tip)
    rects = [(ay0, az0, ay1 - ay0, az1 - az0), (by0, bz0, by1 - by0, bz1 - bz0)]
    corners = []
    for y, z, dy, dz in rects:
        corners.extend([(y, z), (y + dy, z), (y + dy, z + dz), (y, z + dz)])
    items = [(p[0].v, p[1].v, p[0], p[1]) for p in corners]
    pts = [(it[2], it[3]) for it in convex_hull(items)]
    length = d("cable_w") + d("awning_extra_l")
    b.pad_polygon("awning", pts, length, z=(d("bmp_outer_l") / 2).v, kind="YZ", side="Symmetric")


def int_louvers(b, through):
    d = b.params.d
    outer_l, outer_w = d("bmp_outer_l"), d("bmp_outer_w")
    for zi, z0 in enumerate((d("lv_z0"), d("lv_z1"))):
        for fi, frac in enumerate((d("far_frac_a"), d("far_frac_b"))):
            wall_slot(b, "far_%d%d" % (zi, fi), outer_l * frac, outer_w, z0, d("lv_len"), d("lv_h"), through)
        for fi, frac in enumerate((d("cable_frac_a"), d("cable_frac_b"))):
            wall_slot(b, "cab_%d%d" % (zi, fi), outer_l * frac, zero(), z0, d("cable_lv_len"), d("lv_h"), through)
    z0 = d("tab_t") + d("tab_gusset_rise") + d("end_slot_gap")
    for i, x in enumerate((zero(), outer_l)):
        # Length runs along Y, through the X wall.
        b.pocket_rect(
            "end_%d" % i,
            outer_w / 2 - d("end_slot_l") / 2,
            z0,
            d("end_slot_l"),
            d("lv_h"),
            through,
            z=x.v,
            radius=b.stadium_radius(d("lv_h")),
            kind="YZ",
            side="Symmetric",
        )


def ext_louvers(b):
    d = b.params.d
    outer_l, outer_w = d("bmp_outer_l"), d("bmp_outer_w")
    slope = d("ext_slope")
    height = d("ext_slot_h")
    # Cable wall: outer opening at y=-0.4, inner higher by ext_slope at y=2.6.
    y_out = lit(-0.4)
    y_in = y_out + slope
    for zi, z0 in enumerate((d("ext_slot_z0"), d("ext_slot_z1"))):
        for fi, frac in enumerate((d("cable_frac_a"), d("cable_frac_b"))):
            sloped_slot(b, "csl_%d%d" % (zi, fi), outer_l * frac, d("cable_lv_len"), height, y_out, y_in, z0, slope)
        for fi, frac in enumerate((d("far_frac_a"), d("far_frac_b"))):
            # Far wall is mirrored: translate to y=outer_w and negate the local Y offsets.
            sloped_slot(
                b,
                "fsl_%d%d" % (zi, fi),
                outer_l * frac,
                d("lv_len"),
                height,
                outer_w - y_out,
                outer_w - y_in,
                z0,
                slope,
            )


def sloped_slot(b, tag, cx, length, height, y0, y1, z0, rise):
    r = b.stadium_radius(height)
    sk0 = b.new_sketch(tag + "a", "XZ", y0.v)
    b.add_rect(sk0, cx - length / 2, z0, length, height, tag + "a", r)
    sk1 = b.new_sketch(tag + "b", "XZ", y1.v)
    b.add_rect(sk1, cx - length / 2, z0 + rise, length, height, tag + "b", r)
    b.cut_loft(tag, sk0, sk1)


def platform(b):
    d = b.params.d
    x0 = d("wall") + d("bmp_air") - d("fit_clearance") - d("rail_t") - d("plate_lip")
    y0 = d("wall") + d("bmp_air") - d("fit_clearance") - d("rail_t") - d("plate_lip")
    span_x = d("bmp_pocket_l") + 2 * d("rail_t") + 2 * d("plate_lip")
    span_y = d("bmp_pocket_w") + 2 * d("rail_t") + 2 * d("plate_lip")
    leg = d("leg")
    inset = d("leg_inset")
    z = d("floor_t") - d("fuse_overlap")
    leg_h = d("fuse_overlap") + d("bmp_platform_h") + d("fuse_overlap")
    for i, px in enumerate((inset, span_x - leg - inset)):
        for j, py in enumerate((inset, span_y - leg - inset)):
            b.pad_rect("leg_%d%d" % (i, j), x0 + px, y0 + py, leg, leg, leg_h, z=z.v)
    plate_z = d("floor_t") + d("bmp_platform_h")
    b.pad_rect("plate", x0, y0, span_x, span_y, d("plate_t"), z=plate_z.v)
    b.pocket_rect(
        "plate_hole",
        x0 + d("plate_hole_x") + d("plate_lip"),
        y0 + d("plate_hole_y") + d("plate_lip"),
        d("bmp_pocket_l") + 2 * d("rail_t") - lit(8),
        d("bmp_pocket_w") + 2 * d("rail_t") - lit(7.2),
        d("plate_t") + d("cut_overshoot"),
        z=plate_z.v,
    )


def rails_and_baffle(b):
    d = b.params.d
    x0 = d("wall") + d("bmp_air") - d("fit_clearance")
    y0 = d("wall") + d("bmp_air") - d("fit_clearance")
    z = d("floor_t") + d("bmp_platform_h") - d("rail_drop")
    rh = d("rail_h") + d("rail_drop")
    pocket_l, pocket_w, rail = d("bmp_pocket_l"), d("bmp_pocket_w"), d("rail_t")
    b.pad_rect("rail_far", x0 - rail, y0 + pocket_w, pocket_l + 2 * rail, rail, rh, z=z.v)
    gap0 = (pocket_l - d("pin_gap")) / 2
    b.pad_rect("rail_n0", x0 - rail, y0 - rail, gap0 + rail, rail, rh, z=z.v)
    b.pad_rect("rail_n1", x0 + gap0 + d("pin_gap"), y0 - rail, gap0 + rail, rail, rh, z=z.v)
    b.pad_rect("rail_w", x0 - rail, y0, rail, pocket_w, rh, z=z.v)
    b.pad_rect("rail_e", x0 + pocket_l, y0, rail, pocket_w, rh, z=z.v)

    ox0 = x0 - rail
    oy0 = y0 - rail
    ol = pocket_l + 2 * rail
    ow = pocket_w + 2 * rail
    bt = d("baffle_t")
    bite = d("baffle_bite")
    bz = d("floor_t") + d("bmp_platform_h") - d("baffle_drop")
    bh = d("baffle_top_z") - bz
    gap = d("corner_gap")
    b.pad_rect("baf_n", ox0 + gap, oy0 - bt + bite, ol - 2 * gap, bt, bh, z=bz.v)
    b.pad_rect("baf_f", ox0 + gap, oy0 + ow - bite, ol - 2 * gap, bt, bh, z=bz.v)
    b.pad_rect("baf_w", ox0 - bt + bite, oy0 + gap, bt, ow - 2 * gap, bh, z=bz.v)
    b.pad_rect("baf_e", ox0 + ol - bite, oy0 + gap, bt, ow - 2 * gap, bh, z=bz.v)


def strain(b):
    d = b.params.d
    span = d("cable_w") - lit(1)
    x0 = d("bmp_outer_l") / 2 - span / 2
    y0 = d("wall") + lit(1.4)
    bar_z = d("cable_z0") + d("cable_h") - d("cleat_bar_h")
    post = d("cleat_post")
    z = d("floor_t") - d("fuse_overlap")
    post_h = (bar_z + lit(0.5)) - z
    b.pad_rect("post0", x0 + lit(0.25), y0 + lit(0.35), post, d("cleat_post_t"), post_h, z=z.v)
    b.pad_rect(
        "post1",
        x0 + lit(0.25) + span - post - lit(0.5),
        y0 + lit(0.35),
        post,
        d("cleat_post_t"),
        post_h,
        z=z.v,
    )
    b.pad_rect("cleat_bar", x0, y0, span, d("cleat_bar_t"), d("cleat_bar_h"), z=bar_z.v)


def insert_bosses(b):
    d = b.params.d
    r = d("boss_od") / 2
    xs = (
        d("wall") + d("boss_from_inner"),
        d("bmp_outer_l") - d("wall") - d("boss_from_inner"),
    )
    y = d("bmp_outer_w") - d("wall") - d("boss_from_inner")
    z = d("floor_t") - d("fuse_overlap")
    for i, x in enumerate(xs):
        b.pad_circle("bboss_%d" % i, x, y, r, d("boss_h"), z=z.v)
    hole_z = z + d("boss_h") - d("m2_insert_hole_depth")
    for i, x in enumerate(xs):
        b.pocket_circle(
            "bboss_h_%d" % i,
            x,
            y,
            d("m2_insert_hole_d") / 2,
            d("m2_insert_hole_depth") + d("cut_overshoot"),
            z=hole_z.v,
        )


def snaps(b):
    d = b.params.d
    prot = d("snap_protrusion") + d("snap_bite")
    catch = d("snap_catch_h")
    z0 = d("bmp_body_h") - d("snap_z_drop") - d("snap_ridge_h")
    length = d("snap_len")
    bite = d("snap_bite")
    outer_l, outer_w = d("bmp_outer_l"), d("bmp_outer_w")
    # Profile in the plane normal to the wall, pad along the wall.
    # Y-wall ridges vary in global Y and Z, so the sketch sits on a YZ datum
    # (local X = global Y, local Y = global Z) and is padded along X.
    snap_profile(b, "snap_p", "YZ", (outer_l / 2).v, length, [
        (outer_w - bite, z0),
        (outer_w - bite + prot, z0),
        (outer_w - bite + prot, z0 + catch),
        (outer_w - bite, z0 + catch + prot),
    ])
    snap_profile(b, "snap_n", "YZ", (outer_l / 2).v, length, [
        (bite, z0),
        (bite - prot, z0),
        (bite - prot, z0 + catch),
        (bite, z0 + catch + prot),
    ])
    # X-wall ridges vary in global X and Z: XZ datum, padded along Y.
    snap_profile(b, "snap_e", "XZ", (outer_w / 2).v, length, [
        (outer_l - bite, z0),
        (outer_l - bite + prot, z0),
        (outer_l - bite + prot, z0 + catch),
        (outer_l - bite, z0 + catch + prot),
    ])
    snap_profile(b, "snap_w", "XZ", (outer_w / 2).v, length, [
        (bite, z0),
        (bite - prot, z0),
        (bite - prot, z0 + catch),
        (bite, z0 + catch + prot),
    ])


def snap_profile(b, tag, kind, offset, length, pts):
    # pts are (along outward axis, z). For an XZ sketch, outward axis is global X
    # and local Y is global Z, so the point tuple is already (local X, local Y)
    # when kind == "XZ" and outward is X. For a YZ sketch, local X is global Y,
    # so a ridge on an X-wall (outward = global X) is NOT local X.
    #
    # X-wall ridges use a YZ datum? Local X = global Y, local Y = global Z.
    # The profile varies in global X and Z, and is extruded along Y.
    # That is an XZ sketch (local X = global X, local Y = global Z), datum at
    # the Y center. So both X-wall and Y-wall ridges are:
    #   Y-wall (profile in YZ): datum is YZ? Local X = global Y. YES kind YZ,
    #   and the caller must pass kind that matches the varying axis.
    #
    # Caller convention used above:
    #   +Y/-Y ridges vary in global Y -> kind "YZ" would be correct, but the
    #   call says "XZ". Fix the mapping here by interpreting `kind` as the
    #   plane whose local X is the outward axis. XZ local X = global X, so
    #   X-wall ridges should pass XZ. Y-wall ridges should pass YZ.
    # The calls above are swapped relative to that. Swap them to the datum
    # whose local X matches the first coordinate of each point.
    b.pad_polygon(tag, pts, length, z=offset, kind=kind, side="Symmetric")


def build_bmp_lid(ext):
    name = "bmp280_ext_lid" if ext else "bmp280_int_lid"
    b = Builder(name)
    P = b.params
    add_shared(P)
    add_bmp_params(P, ext)
    d = P.d
    lid_l, lid_w = d("lid_outer_l"), d("lid_outer_w")
    b.pad_rect("plate", zero(), zero(), lid_l, lid_w, d("lid_t"), radius=d("lid_corner_r"))
    off = (lid_l - d("lid_skirt_l")) / 2
    b.pad_rect(
        "skirt",
        off,
        off,
        d("lid_skirt_l"),
        d("lid_skirt_w"),
        d("skirt_h") + d("fuse_overlap"),
        z=(d("lid_t") - d("fuse_overlap")).v,
        radius=d("corner_r"),
    )
    b.pocket_rect(
        "skirt_void",
        off + d("skirt_t"),
        off + d("skirt_t"),
        d("lid_skirt_l") - 2 * d("skirt_t"),
        d("lid_skirt_w") - 2 * d("skirt_t"),
        d("skirt_h") + d("cut_overshoot"),
        z=d("lid_t").v,
    )
    posts(b)
    snap_windows(b)
    screws(b)
    if not ext:
        lid_vents(b)
    b.cut_text(
        "EXT" if ext else "INT",
        d("lid_label_size"),
        App.Vector((lid_l / 2).v, (lid_w / 2).v, -0.2),
        (1, 0, 0),
        (0, 1, 0),
        (0, 0, d("label_extrude").v),
        "lid",
    )
    notch_y = d("eave") + d("skirt_t") / 2
    notch_z = d("lid_t") + d("skirt_h") - lit(1.2)
    depth = d("skirt_t") + d("eave") + lit(1.2)
    b.pocket_rect(
        "notch",
        lid_l / 2 - d("notch_l") / 2,
        notch_y - depth / 2,
        d("notch_l"),
        depth,
        d("notch_h"),
        z=notch_z.v,
        side="Symmetric",
    )
    return b


def posts(b):
    d = b.params.d
    post_len = d("bmp_header_above_pcb") + d("bmp_above_header") - d("hold_gap")

    def lid_of(v):
        return (d("lid_outer_l") - d("bmp_outer_l")) / 2 + v

    def lid_of_y(v):
        return (d("lid_outer_w") - d("bmp_outer_w")) / 2 + v

    xs = (
        d("wall") + d("bmp_air") + d("hold_inset"),
        d("wall") + d("bmp_air") + d("bmp_pcb_l") - d("hold_inset"),
    )
    y = d("wall") + d("bmp_air") + d("bmp_pcb_w") - d("hold_inset")
    for i, x in enumerate(xs):
        b.pad_circle(
            "post_%d" % i,
            lid_of(x),
            lid_of_y(y),
            d("hold_d") / 2,
            post_len + d("fuse_overlap"),
            z=(d("lid_t") - d("fuse_overlap")).v,
        )


def snap_windows(b):
    d = b.params.d
    catch_z0 = d("bmp_body_h") - d("snap_z_drop") - d("snap_ridge_h")
    catch_z1 = catch_z0 + d("snap_catch_h")
    z0 = d("bmp_body_h") + d("lid_t") - (catch_z1 + d("win_z_pad"))
    z1 = d("bmp_body_h") + d("lid_t") - (catch_z0 - d("win_z_pad"))
    win_h = z1 - z0
    win_l = d("snap_len") + d("win_pad")
    span = d("skirt_t") + d("eave") + d("win_extra")

    def lid_of_x(v):
        return (d("lid_outer_l") - d("bmp_outer_l")) / 2 + v

    def lid_of_y(v):
        return (d("lid_outer_w") - d("bmp_outer_w")) / 2 + v

    for i, x in enumerate((lid_of_x(zero()), lid_of_x(d("bmp_outer_l")))):
        b.pocket_rect(
            "swx_%d" % i,
            d("lid_outer_w") / 2 - win_l / 2,
            z0,
            win_l,
            win_h,
            span,
            z=x.v,
            kind="YZ",
            side="Symmetric",
        )
    for i, y in enumerate((lid_of_y(zero()), lid_of_y(d("bmp_outer_w")))):
        b.pocket_rect(
            "swy_%d" % i,
            d("lid_outer_l") / 2 - win_l / 2,
            z0,
            win_l,
            win_h,
            span,
            z=y.v,
            kind="XZ",
            side="Symmetric",
        )


def screws(b):
    d = b.params.d

    def lid_of_x(v):
        return (d("lid_outer_l") - d("bmp_outer_l")) / 2 + v

    def lid_of_y(v):
        return (d("lid_outer_w") - d("bmp_outer_w")) / 2 + v

    xs = (
        d("wall") + d("boss_from_inner"),
        d("bmp_outer_l") - d("wall") - d("boss_from_inner"),
    )
    y = d("bmp_outer_w") - d("wall") - d("boss_from_inner")
    for i, x in enumerate(xs):
        b.pocket_circle("screw_%d" % i, lid_of_x(x), lid_of_y(y), d("m2_clearance_d") / 2, d("lid_t"))


def lid_vents(b):
    d = b.params.d
    depth = d("lid_t") + d("label_extra") + d("cut_overshoot")
    for sign in (lit(-1), lit(1)):
        cx = d("lid_outer_l") / 2 + sign * d("lid_vent_dx")
        b.pocket_rect(
            "vent",
            cx - d("lid_vent_l") / 2,
            lit(-0.2),
            d("lid_vent_l"),
            d("lid_vent_h"),
            depth,
            z=(d("lid_outer_w") / 2).v,
            radius=b.stadium_radius(d("lid_vent_h")),
            kind="XZ",
            side="Symmetric",
        )


# --------------------------------------------------------------------------
# Probes taken from the OpenSCAD mesh checks (enclosure/export.sh and the
# enclosure fit review). Coordinates are in each part's own print frame.
# --------------------------------------------------------------------------

PROBES = {
    "pico_case_base": [
        (1.0, 23.5, 10.9, False, "usb opening"),
        (1.0, 12.0, 10.9, True, "usb wall"),
        (16.0, 1.0, 6.5, False, "fan slot"),
        (21.2, 1.0, 6.5, True, "between fans"),
        (37.0, 1.0, 6.1, False, "int slot"),
        (42.2, 1.0, 6.1, True, "between sensors"),
        (47.5, 1.0, 6.1, False, "ext slot"),
        (16.0, 46.0, 7.0, False, "power slot"),
        (30.0, 46.0, 7.0, True, "power wall"),
        (62.0, 23.5, 12.0, False, "antenna window"),
        (62.0, 8.0, 12.0, True, "antenna wall"),
        (4.0, 17.8, 1.0, False, "insert bore"),
        (6.2, 17.8, 4.0, True, "standoff"),
        (30.0, 23.0, 1.0, True, "floor"),
        (30.0, 23.0, 12.0, False, "cavity"),
        (5.2, 7.5, 12.0, True, "boss plastic"),
        (5.2, 5.2, 21.5, False, "boss insert"),
        (14.0, -7.44, 1.5, False, "ear screw"),
        (14.0, -3.74, 1.5, False, "ear zip"),
        (14.0, -5.29, 1.5, True, "ear between holes"),
    ],
    "pico_case_lid": [
        (35.65, 25.65, 0.4, False, "window recess"),
        (35.65, 25.65, 1.5, True, "window web"),
        (35.65, 25.65, 3.6, False, "nest pocket"),
        (48.65, 25.65, 1.0, True, "past window along length"),
        (35.65, 29.65, 1.5, True, "past window along width"),
        (11.65, 25.65, 1.0, False, "bootsel"),
        (11.65, 25.65, 1.5, False, "bootsel mid"),
        (7.35, 7.35, 1.0, False, "lid screw"),
        (54.4, 25.65, 3.6, True, "nest wall"),
    ],
    "bmp280_int_body": [
        (19.7, 1.0, 6.0, False, "cable"),
        (13.6, 1.0, 6.0, True, "beside cable"),
        (7.88, 1.0, 6.1, False, "cable louver"),
        (12.61, 35.4, 6.1, False, "far louver"),
        (20.0, 18.0, 10.0, False, "cavity"),
        (9.2, 9.2, 5.6, True, "platform"),
        (4.75, 31.65, 8.0, True, "boss"),
        (4.75, 31.65, 15.6, False, "boss insert"),
        (20.0, 12.0, 1.0, True, "floor"),
    ],
    "bmp280_ext_body": [
        (19.7, 1.0, 6.0, False, "cable"),
        (7.88, 1.0, 6.3, False, "sloped louver"),
        (7.88, 1.0, 8.0, True, "between louvers"),
        (12.61, 35.4, 6.3, False, "far louver"),
        (19.7, 0.6, 9.6, True, "awning root"),
        (19.7, -1.2, 10.8, True, "awning tip"),
        (20.0, 18.0, 10.0, False, "cavity"),
        (4.75, 31.65, 15.6, False, "boss insert"),
    ],
    "bmp280_int_lid": [
        (22.15, 20.65, 1.0, True, "center"),
        (12.15, 20.65, 1.0, False, "vent"),
        (1.65, 20.65, 4.2, False, "snap window"),
        (1.2, 8.0, 4.2, True, "skirt"),
        (7.2, 34.1, 1.0, False, "screw"),
        (14.85, 26.45, 6.0, True, "hold-down post"),
        (22.15, 20.65, 1.2, True, "label does not punch through"),
    ],
    "bmp280_ext_lid": [
        (23.45, 21.95, 1.0, True, "center"),
        (23.45, 21.95, 1.2, True, "label web"),
        (8.5, 35.4, 1.0, False, "screw"),
        (16.15, 27.75, 6.0, True, "hold-down post"),
        (3.75, 21.95, 4.2, False, "snap window"),
    ],
}


def render_all():
    if os.environ.get("SKIP_RENDER") == "1":
        print("SKIP_RENDER=1, not writing PNGs", flush=True)
        return
    RENDER_DIR.mkdir(parents=True, exist_ok=True)
    # OpenSCAD resolves import() against the .scad file, not the process cwd.
    scad = STL_DIR / "_preview.scad"
    for stl in sorted(STL_DIR.glob("*.stl")):
        png = RENDER_DIR / (stl.stem + ".png")
        scad.write_text('import("%s");\n' % stl.resolve())
        cmd = [
            "xvfb-run",
            "-a",
            "openscad",
            "-o",
            str(png),
            "--imgsize=1200,900",
            "--colorscheme=Tomorrow",
            "--projection=perspective",
            "--autocenter",
            "--viewall",
            "--camera=0,0,0,55,0,32,0",
            str(scad),
        ]
        print("render", png.name, flush=True)
        import subprocess

        proc = subprocess.run(cmd, cwd=str(STL_DIR), capture_output=True, text=True)
        if proc.returncode != 0 or not png.exists() or png.stat().st_size < 5000:
            print(proc.stdout)
            print(proc.stderr)
            die("render failed for %s" % stl.name)
    if scad.exists():
        scad.unlink()
    artifacts = Path("/opt/cursor/artifacts")
    if artifacts.is_dir():
        for png in sorted(RENDER_DIR.glob("*.png")):
            target = artifacts / ("freecad_" + png.name)
            target.write_bytes(png.read_bytes())
            print("artifact", target, flush=True)


def main():
    require_version()
    if not Path(FONT).exists():
        die("Liberation Sans Bold not found at %s" % FONT)
    only = os.environ.get("ONLY", "").strip()
    jobs = [
        ("pico_case_base", build_pico_base),
        ("pico_case_lid", build_pico_lid),
        ("bmp280_int_body", lambda: build_bmp_body(False)),
        ("bmp280_ext_body", lambda: build_bmp_body(True)),
        ("bmp280_int_lid", lambda: build_bmp_lid(False)),
        ("bmp280_ext_lid", lambda: build_bmp_lid(True)),
    ]
    for name, fn in jobs:
        if only and only != name:
            continue
        print("\n=== %s ===" % name, flush=True)
        builder = fn()
        finish(builder, PROBES[name])
    REPORT_PATH.write_text("\n".join(_REPORT) + "\n")
    print("\nDOF report written to", REPORT_PATH, flush=True)
    if not only:
        render_all()
    print("BUILD OK", flush=True)
    os._exit(0)


# freecadcmd executes the file with __name__ != "__main__".
try:
    main()
except SystemExit:
    raise
except Exception:
    traceback.print_exc()
    os._exit(1)
