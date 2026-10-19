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
    P.set("fit_clearance", 0.30)
    P.set("wall", 1.6)
    P.set("floor_t", 1.2)
    P.set("lid_t", 1.2)
    P.set("nozzle", 0.40)
    P.set("skirt_h", 3.2)
    P.set("skirt_t", 1.2)
    P.set("skirt_gap", 0.30)
    P.set("snap_protrusion", 0.65)
    P.set("snap_catch_h", 0.55)
    P.set("snap_len", 8.0)
    P.set("pico_l", 51.0)
    P.set("pico_w", 21.0)
    P.set("pico_t", 1.0)
    P.set("pico_hole_dx", 47.0)
    P.set("pico_hole_dy", 11.4)
    P.set("pico_usb_overhang", 1.3)
    P.set("pico_antenna_keepout_w", 14.0)
    P.set("pico_header_above_pcb", 8.5)
    P.set("pico_header_plastic_w", 2.54)
    P.set("pico_usb_shell_w", 8.0)
    P.set("pico_usb_shell_h", 3.8)
    P.set("pico_gutter", 4.0)
    P.set("pico_antenna_gap", 2.5)
    P.set("pico_above_header", 1.8)
    P.set("pico_standoff_h", 3.0)
    P.set("pico_standoff_od", 6.0)
    P.set("pico_bootsel_from_usb_edge", 7.5)
    P.set("pico_bootsel_hole_d", 7.0)
    P.set("oled_pcb_l", 36.0)
    P.set("oled_pcb_w", 12.5)
    P.set("oled_pcb_t", 1.20)
    P.set("oled_glass_t", 1.45)
    P.set("oled_active_l", 22.38)
    P.set("oled_active_w", 5.58)
    P.set("oled_window_extra", 0.40)
    P.set("oled_connector_w", 10.5)
    P.set("oled_nest_wall", 0.6)
    P.set("oled_active_dx", 0.0)
    P.set("oled_active_dy", 0.0)
    P.set("bmp_pcb_l", 21.0)
    P.set("bmp_pcb_w", 18.0)
    P.set("bmp_pcb_t", 1.6)
    P.set("bmp_header_above_pcb", 8.5)
    P.set("bmp_air", 2.2)
    P.set("bmp_platform_h", 2.0)
    P.set("bmp_above_header", 1.2)
    P.set("m2_insert_od", 3.5)
    P.set("m2_insert_len", 3.0)
    P.set("m2_insert_hole_d", 3.2)
    P.set("m2_insert_hole_depth", 3.6)
    P.set("m2_clearance_d", 2.4)
    P.set("m3_clearance_d", 3.4)
    P.set("ziptie_slot_l", 5.0)
    P.set("ziptie_slot_w", 1.8)
    P.set("rail_t", 1.4)
    P.set("rail_h", 3.2)
    P.set("rail_end_gap", 3.0)
    P.set("rail_clearance", 0.30)
    P.set("rail_detent", 0.40)
    P.set("corner_r", 2.0)
    P.set("fuse_overlap", 0.20, "coplanar overlap")
    P.set("cut_overshoot", 0.20, "cutter past the solid")
    P.set("stadium_flat", 0.04, "fillet flat so a semicircle stays solvable")
    P.set("snap_bite", 0.35, "snap root buried in the wall")
    P.set("label_extra", 0.45, "text cutter past the face")
    P.fml("snap_ridge_h", "snap_catch_h + snap_protrusion", 1.2)
    P.fml("snap_reach", "snap_protrusion + snap_bite", 1.0)
    P.fml("oled_stack_h", "oled_pcb_t + oled_glass_t", 2.65)
    P.fml("oled_window_l", "oled_active_l + oled_window_extra", 22.78)
    P.fml("oled_window_w", "oled_active_w + oled_window_extra", 5.98)
    P.fml("oled_pocket_l", "oled_pcb_l + 2 * fit_clearance", 36.6)
    P.fml("oled_pocket_w", "oled_pcb_w + 2 * fit_clearance", 13.1)
    P.fml("oled_nest_drop", "oled_stack_h + 0.8", 3.45)
    P.fml("bmp_pocket_l", "bmp_pcb_l + 2 * fit_clearance", 21.6)
    P.fml("bmp_pocket_w", "bmp_pcb_w + 2 * fit_clearance", 18.6)
    P.fml("bmp_chamber_l", "bmp_pcb_l + 2 * bmp_air", 25.4)
    P.fml("bmp_chamber_w", "bmp_pcb_w + 2 * bmp_air", 22.4)
    P.fml("bmp_outer_l", "bmp_chamber_l + 2 * wall", 28.6)
    P.fml("bmp_outer_w", "bmp_chamber_w + 2 * wall", 25.6)
    P.fml(
        "bmp_body_h",
        "floor_t + bmp_platform_h + bmp_pcb_t + bmp_header_above_pcb + bmp_above_header",
        14.5,
    )
    P.fml("pico_outer_l", "wall + pico_l + pico_antenna_gap + wall", 56.7)
    P.fml("pico_outer_w", "wall + pico_gutter + pico_w + pico_gutter + wall", 32.2)
    P.fml(
        "pico_base_h",
        "floor_t + pico_standoff_h + pico_t + pico_header_above_pcb + pico_above_header",
        15.5,
    )
    P.fml("pico_usb_opening_w", "pico_usb_shell_w + 3", 11.0)
    P.fml("pico_usb_opening_h", "pico_usb_shell_h + 2.2", 6.0)
    P.fml("label_depth", "0.45 + label_extra", 0.9)


def zero():
    return Dim(0.0, "0")


def lit(value):
    return Dim(float(value), "%.10g" % float(value))


def expect(dim, value, label):
    if abs(dim.v - value) > 1e-6:
        die("%s is %.6f, expected %.6f" % (label, dim.v, value))


def wall_slot(b, tag, cx, y_center, z0, length, height, through):
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


def add_rails(b, length, width):
    d = b.params.d
    bite = d("fuse_overlap") * 2  # 0.40, matches slide_rails bite
    span = length - 2 * d("rail_end_gap")
    t = d("rail_t")
    # -Y rail, overlapping the wall.
    b.pad_rect("rail_n", d("rail_end_gap"), -t, span, t + bite, d("rail_h"))
    b.pad_rect("rail_p", d("rail_end_gap"), width - bite, span, t + bite, d("rail_h"))
    slot_z = (d("rail_h") - d("ziptie_slot_w")) / 2
    cx = d("rail_end_gap") + span / 2
    b.pocket_rect(
        "zip_n",
        cx - d("ziptie_slot_l") / 2,
        -t,
        d("ziptie_slot_l"),
        t + lit(0.2),
        d("ziptie_slot_w"),
        z=slot_z.v,
    )
    b.pocket_rect(
        "zip_p",
        cx - d("ziptie_slot_l") / 2,
        width - lit(0.2),
        d("ziptie_slot_l"),
        t + lit(0.2),
        d("ziptie_slot_w"),
        z=slot_z.v,
    )
    bump_h = d("rail_h") - lit(1.2)
    b.pad_rect(
        "det_n",
        d("rail_end_gap") + lit(2.2),
        -t - d("rail_detent"),
        lit(1.6),
        d("rail_detent") + lit(0.25),
        bump_h,
        z=lit(0.6).v,
    )
    b.pad_rect(
        "det_p",
        d("rail_end_gap") + lit(2.2),
        width + t - lit(0.25),
        lit(1.6),
        d("rail_detent") + lit(0.25),
        bump_h,
        z=lit(0.6).v,
    )


def add_snap(b, tag, x, y_root, z0, sign):
    """sign +1 protrudes toward +Y. Sketch plane is YZ, padded along X."""
    d = b.params.d
    reach = d("snap_reach")
    catch = d("snap_catch_h")
    y1 = y_root + reach if sign > 0 else y_root - reach
    if sign > 0:
        pts = [
            (y_root, z0),
            (y1, z0),
            (y1, z0 + catch),
            (y_root, z0 + catch + reach),
        ]
    else:
        pts = [
            (y_root, z0),
            (y_root, z0 + catch + reach),
            (y1, z0 + catch),
            (y1, z0),
        ]
    b.pad_polygon(tag, pts, d("snap_len"), z=x.v, kind="YZ", side="Symmetric")


def build_pico_base():
    b = Builder("pico_case_base")
    P = b.params
    add_shared(P)
    P.check()
    d = P.d
    outer_l, outer_w, base_h = d("pico_outer_l"), d("pico_outer_w"), d("pico_base_h")
    expect(outer_l, 56.7, "pico_outer_l")
    expect(outer_w, 32.2, "pico_outer_w")
    expect(base_h, 15.5, "pico_base_h")
    wall = d("wall")
    b.pad_rect("shell", zero(), zero(), outer_l, outer_w, base_h, radius=d("corner_r"))
    add_rails(b, outer_l, outer_w)
    b.pocket_rect(
        "cavity",
        wall,
        wall,
        outer_l - 2 * wall,
        outer_w - 2 * wall,
        base_h - d("floor_t") + d("cut_overshoot"),
        z=d("floor_t").v,
    )
    through = wall + lit(1.2)
    pcb_y0 = wall + d("pico_gutter")
    usb_y = pcb_y0 + d("pico_w") / 2
    pcb_top = d("floor_t") + d("pico_standoff_h") + d("pico_t")
    usb_z0 = pcb_top + (d("pico_usb_shell_h") - d("pico_usb_opening_h")) / 2
    sk = b.new_sketch("usb", "YZ", (wall / 2).v)
    b.add_rect(
        sk,
        usb_y - d("pico_usb_opening_w") / 2,
        usb_z0,
        d("pico_usb_opening_w"),
        d("pico_usb_opening_h"),
        "usb",
        b.stadium_radius(d("pico_usb_opening_h")),
    )
    b.extrude(sk, "usb", through, "pocket", "Symmetric")
    aperture = d("pico_antenna_keepout_w")
    b.pocket_rect(
        "antenna",
        outer_l - wall - lit(0.4),
        pcb_y0 + (d("pico_w") - aperture) / 2,
        wall + lit(1.2),
        aperture,
        base_h,
        z=(pcb_top - lit(1.2)).v,
    )
    slot_y = wall / 2
    for i, cx in enumerate((lit(12.0), lit(19.5))):
        wall_slot(b, "fan_%d" % i, cx, slot_y, lit(5.2), lit(6.5), lit(3.4), through)
    for i, cx in enumerate((lit(30.0), lit(40.0))):
        wall_slot(b, "i2c_%d" % i, cx, slot_y, lit(5.2), lit(6.5), lit(3.4), through)
    wall_slot(b, "pwr", lit(16.0), outer_w - wall / 2, lit(4.8), lit(8.0), lit(4.0), through)

    bite = d("snap_bite")
    z_snap = base_h - lit(0.9) - d("snap_ridge_h")
    for i, frac in enumerate((lit(0.32), lit(0.68))):
        add_snap(b, "snap_n%d" % i, outer_l * frac, bite, z_snap, -1)
        add_snap(b, "snap_p%d" % i, outer_l * frac, outer_w - bite, z_snap, +1)

    cleat_h = lit(1.4)
    cleat_d = lit(1.8)
    for i, cx in enumerate((lit(12.0), lit(19.5))):
        b.pad_rect(
            "cf%d" % i,
            cx - lit(9.0) / 2,
            wall - d("fuse_overlap") * lit(1.75),
            lit(9.0),
            cleat_d,
            cleat_h,
            z=(lit(5.2) + lit(3.4) - lit(1.8)).v,
        )
    for i, cx in enumerate((lit(30.0), lit(40.0))):
        b.pad_rect(
            "cs%d" % i,
            cx - lit(9.0) / 2,
            wall - d("fuse_overlap") * lit(1.75),
            lit(9.0),
            cleat_d,
            cleat_h,
            z=(lit(5.2) + lit(3.4) - lit(1.8)).v,
        )
    b.pad_rect(
        "cpwr",
        lit(16.0) - lit(11.0) / 2,
        outer_w - wall - lit(1.45),
        lit(11.0),
        cleat_d,
        cleat_h,
        z=(lit(4.8) + lit(4.0) - lit(1.9)).v,
    )

    pcb_x0 = wall
    hx0 = pcb_x0 + (d("pico_l") - d("pico_hole_dx")) / 2
    hy0 = pcb_y0 + (d("pico_w") - d("pico_hole_dy")) / 2
    holes = (
        (hx0, hy0),
        (hx0 + d("pico_hole_dx"), hy0),
        (hx0, hy0 + d("pico_hole_dy")),
        (hx0 + d("pico_hole_dx"), hy0 + d("pico_hole_dy")),
    )
    stand_h = d("floor_t") + d("pico_standoff_h")
    for i, (hx, hy) in enumerate(holes):
        b.pad_circle("stand_%d" % i, hx, hy, d("pico_standoff_od") / 2, stand_h)
    for i, (hx, hy) in enumerate(holes):
        b.pocket_circle("ins_%d" % i, hx, hy, d("m2_insert_hole_d") / 2, d("m2_insert_hole_depth"))
        b.pocket_circle(
            "clr_%d" % i,
            hx,
            hy,
            d("m2_clearance_d") / 2,
            stand_h - d("m2_insert_hole_depth") + lit(0.05),
            z=(d("m2_insert_hole_depth") - lit(0.05)).v,
        )

    depth = d("label_depth")
    b.cut_text(
        "FAN",
        lit(2.4),
        App.Vector(15.75, 0.7, 10.6),
        (-1, 0, 0),
        (0, 0, 1),
        (0, -depth.v, 0),
        "fan",
    )
    b.cut_text("INT", lit(2.2), App.Vector(30.0, 0.7, 10.6), (-1, 0, 0), (0, 0, 1), (0, -depth.v, 0), "int")
    b.cut_text("EXT", lit(2.2), App.Vector(40.0, 0.7, 10.6), (-1, 0, 0), (0, 0, 1), (0, -depth.v, 0), "ext")
    b.cut_text(
        "PWR",
        lit(2.4),
        App.Vector(16.0, 31.5, 10.8),
        (1, 0, 0),
        (0, 0, 1),
        (0, depth.v, 0),
        "pwr",
    )
    return b


def build_pico_lid():
    b = Builder("pico_case_lid")
    P = b.params
    add_shared(P)
    P.check()
    d = P.d
    body_l, body_w = d("pico_outer_l"), d("pico_outer_w")
    lid_l = body_l + 2 * (d("skirt_gap") + d("skirt_t"))
    lid_w = body_w + 2 * (d("skirt_gap") + d("skirt_t"))
    b.pad_rect("plate", zero(), zero(), lid_l, lid_w, d("lid_t"), radius=d("corner_r"))
    b.pad_rect(
        "skirt",
        zero(),
        zero(),
        lid_l,
        lid_w,
        d("skirt_h") + d("fuse_overlap"),
        z=(d("lid_t") - d("fuse_overlap")).v,
        radius=d("corner_r") - lit(0.2),
    )
    b.pocket_rect(
        "skirt_void",
        d("skirt_t"),
        d("skirt_t"),
        lid_l - 2 * d("skirt_t"),
        lid_w - 2 * d("skirt_t"),
        d("skirt_h") + d("cut_overshoot"),
        z=d("lid_t").v,
    )

    def lid_of(v, body_span, lid_span):
        return (lid_span - body_span) / 2 + v

    ox = lid_of(d("wall") + d("pico_l") / 2 + lit(6), body_l, lid_l)
    oy = lid_of(d("wall") + d("pico_gutter") + d("pico_w") / 2, body_w, lid_w)
    ax = ox + d("oled_active_dx")
    ay = oy + d("oled_active_dy")
    x0 = ox - d("oled_pocket_l") / 2 - d("oled_nest_wall")
    y0 = oy - d("oled_pocket_w") / 2 - d("oled_nest_wall")
    nx = d("oled_pocket_l") + 2 * d("oled_nest_wall")
    ny = d("oled_pocket_w") + 2 * d("oled_nest_wall")
    b.pad_rect("nest", x0, y0, nx, ny, d("oled_nest_drop") + d("fuse_overlap"), z=(d("lid_t") - d("fuse_overlap")).v)
    b.pocket_rect(
        "nest_void",
        x0 + d("oled_nest_wall"),
        y0 + d("oled_nest_wall"),
        d("oled_pocket_l"),
        d("oled_pocket_w"),
        d("oled_nest_drop") + d("cut_overshoot"),
        z=d("lid_t").v,
    )
    gap = d("oled_connector_w") + lit(1.6)
    b.pocket_rect(
        "nest_gap",
        x0 - d("cut_overshoot"),
        y0 + (ny - gap) / 2,
        d("oled_nest_wall") + lit(0.6) + d("cut_overshoot"),
        gap,
        d("oled_nest_drop") + d("cut_overshoot"),
        z=d("lid_t").v,
    )
    # Clips grab the back of the PCB. Two bars and a small lip each.
    clip_z = d("lid_t") + d("oled_nest_drop") - d("oled_pcb_t") - lit(0.7)
    reach = lit(0.7)
    length = lit(7)
    cax = x0 + nx * lit(0.42)
    yy0 = y0 + d("oled_nest_wall") - lit(0.25)
    yy1 = y0 + d("oled_nest_wall") + d("oled_pocket_w") - lit(0.45)
    b.pad_rect("clip0", cax, yy0, length, reach, reach, z=clip_z.v)
    b.pad_rect("clip1", cax, yy1, length, reach, reach, z=clip_z.v)
    b.pad_rect("lip0", cax, yy0, length, reach, lit(0.45), z=(clip_z + reach).v)
    b.pad_rect("lip1", cax, yy1 + lit(0.45), length, lit(0.25), lit(0.45), z=(clip_z + reach).v)

    flare = d("lid_t")
    sk0 = b.new_sketch("win_out", "XY", 0.0)
    b.add_rect(
        sk0,
        ax - (d("oled_window_l") + 2 * flare) / 2,
        ay - (d("oled_window_w") + 2 * flare) / 2,
        d("oled_window_l") + 2 * flare,
        d("oled_window_w") + 2 * flare,
        "win_out",
    )
    sk1 = b.new_sketch("win_in", "XY", d("lid_t").v)
    b.add_rect(
        sk1,
        ax - d("oled_window_l") / 2,
        ay - d("oled_window_w") / 2,
        d("oled_window_l"),
        d("oled_window_w"),
        "win_in",
    )
    b.cut_loft("window", sk0, sk1)

    bootsel_x = lid_of(d("wall") + d("pico_bootsel_from_usb_edge"), body_l, lid_l)
    bootsel_y = lid_of(d("wall") + d("pico_gutter") + d("pico_w") / 2, body_w, lid_w)
    b.pocket_circle("bootsel", bootsel_x, bootsel_y, d("pico_bootsel_hole_d") / 2, d("lid_t"))

    catch0 = d("pico_base_h") - lit(0.9) - d("snap_ridge_h")
    catch1 = catch0 + d("snap_catch_h")
    z0 = d("pico_base_h") + d("lid_t") - (catch1 + lit(0.25))
    z1 = d("pico_base_h") + d("lid_t") - (catch0 - lit(0.25))
    win_h = z1 - z0
    win_l = d("snap_len") + lit(0.8)
    span = d("skirt_t") + lit(1.4)
    for i, frac in enumerate((lit(0.32), lit(0.68))):
        cx = lid_of(body_l * frac, body_l, lid_l)
        for j, side in enumerate((zero(), body_w)):
            cy = lid_of(side, body_w, lid_w)
            b.pocket_rect(
                "sw_%d%d" % (i, j),
                cx - win_l / 2,
                z0,
                win_l,
                win_h,
                span,
                z=cy.v,
                kind="XZ",
                side="Symmetric",
            )
    b.pocket_rect(
        "notch",
        ox - lit(5),
        lid_w - d("skirt_t") / 2 - lit(0.8),
        lit(10),
        d("skirt_t") + lit(1.6),
        lit(2.4),
        z=(d("lid_t") + d("skirt_h") - lit(1.15)).v,
        side="Symmetric",
    )
    return b


def build_bmp_body(ext):
    name = "bmp280_ext_body" if ext else "bmp280_int_body"
    b = Builder(name)
    P = b.params
    add_shared(P)
    P.set("is_ext", 1 if ext else 0, "variant")
    P.text("label", "EXT" if ext else "INT")
    P.check()
    d = P.d
    outer_l, outer_w, body_h = d("bmp_outer_l"), d("bmp_outer_w"), d("bmp_body_h")
    expect(outer_l, 28.6, "bmp_outer_l")
    expect(outer_w, 25.6, "bmp_outer_w")
    expect(body_h, 14.5, "bmp_body_h")
    wall = d("wall")
    b.pad_rect("shell", zero(), zero(), outer_l, outer_w, body_h, radius=d("corner_r"))
    add_rails(b, outer_l, outer_w)
    b.pocket_rect(
        "cavity",
        wall,
        wall,
        d("bmp_chamber_l"),
        d("bmp_chamber_w"),
        body_h - d("floor_t") + d("cut_overshoot"),
        z=d("floor_t").v,
    )
    cable_z0 = d("rail_h") + lit(1.2)
    wall_slot(
        b,
        "cable",
        outer_l / 2,
        zero(),
        cable_z0,
        lit(7.0),
        lit(3.4),
        wall + lit(1.2),
    )
    # Legs under the module, sunk 0.3 mm into the floor.
    x0 = wall + d("bmp_air")
    y0 = wall + d("bmp_air")
    leg = lit(2.4)
    inset = lit(0.8)
    leg_h = d("bmp_platform_h") + lit(0.3)
    for i, px in enumerate((inset, d("bmp_pocket_l") - leg - inset)):
        for j, py in enumerate((inset, d("bmp_pocket_w") - leg - inset)):
            b.pad_rect(
                "leg_%d%d" % (i, j),
                x0 + px,
                y0 + py,
                leg,
                leg,
                leg_h,
                z=(d("floor_t") - lit(0.3)).v,
            )
    b.pad_rect(
        "lip",
        x0 - lit(0.4),
        y0 + d("bmp_pocket_w") - lit(1.0),
        d("bmp_pocket_l") + lit(0.8),
        lit(1.4),
        lit(1.6),
        z=(d("floor_t") + d("bmp_platform_h") - lit(0.3)).v,
    )
    # Strain posts and bar across the cable slot.
    span = lit(7.0) - lit(0.8)
    bar_x = outer_l / 2 - span / 2
    post = lit(1.2)
    bar_z = cable_z0 + lit(3.4) - lit(1.5)
    post_h = (bar_z + lit(0.4)) - (d("floor_t") - lit(0.3))
    y_post = wall + lit(0.8)
    b.pad_rect("post0", bar_x + lit(0.2), y_post, post, lit(1.4), post_h, z=(d("floor_t") - lit(0.3)).v)
    b.pad_rect(
        "post1",
        bar_x + lit(0.2) + span - post - lit(0.4),
        y_post,
        post,
        lit(1.4),
        post_h,
        z=(d("floor_t") - lit(0.3)).v,
    )
    b.pad_rect("bar", bar_x, y_post, span, lit(1.8), lit(1.3), z=bar_z.v)
    z_snap = body_h - lit(0.85) - d("snap_ridge_h")
    add_snap(b, "snap_n", outer_l / 2, d("snap_bite"), z_snap, -1)
    add_snap(b, "snap_p", outer_l / 2, outer_w - d("snap_bite"), z_snap, +1)
    return b


def build_bmp_lid(ext):
    name = "bmp280_ext_lid" if ext else "bmp280_int_lid"
    b = Builder(name)
    P = b.params
    add_shared(P)
    P.text("label", "EXT" if ext else "INT")
    P.check()
    d = P.d
    body_l, body_w = d("bmp_outer_l"), d("bmp_outer_w")
    lid_l = body_l + 2 * (d("skirt_gap") + d("skirt_t"))
    lid_w = body_w + 2 * (d("skirt_gap") + d("skirt_t"))
    b.pad_rect("plate", zero(), zero(), lid_l, lid_w, d("lid_t"), radius=d("corner_r"))
    b.pad_rect(
        "skirt",
        zero(),
        zero(),
        lid_l,
        lid_w,
        d("skirt_h") + d("fuse_overlap"),
        z=(d("lid_t") - d("fuse_overlap")).v,
        radius=d("corner_r"),
    )
    b.pocket_rect(
        "skirt_void",
        d("skirt_t"),
        d("skirt_t"),
        lid_l - 2 * d("skirt_t"),
        lid_w - 2 * d("skirt_t"),
        d("skirt_h") + d("cut_overshoot"),
        z=d("lid_t").v,
    )
    catch0 = d("bmp_body_h") - lit(0.85) - d("snap_ridge_h")
    catch1 = catch0 + d("snap_catch_h")
    z0 = d("bmp_body_h") + d("lid_t") - (catch1 + lit(0.2))
    z1 = d("bmp_body_h") + d("lid_t") - (catch0 - lit(0.2))
    win_h = z1 - z0
    win_l = d("snap_len") + lit(0.8)
    span = d("skirt_t") + lit(1.4)

    def lid_of(v, body_span, lid_span):
        return (lid_span - body_span) / 2 + v

    for i, side in enumerate((zero(), body_w)):
        cy = lid_of(side, body_w, lid_w)
        b.pocket_rect(
            "sw_%d" % i,
            lid_l / 2 - win_l / 2,
            z0,
            win_l,
            win_h,
            span,
            z=cy.v,
            kind="XZ",
            side="Symmetric",
        )
    for i, sign in enumerate((lit(-1), lit(1))):
        cx = lid_l / 2 + sign * lit(7.2)
        b.pocket_rect(
            "vent_%d" % i,
            cx - lit(3),
            lit(-0.2),
            lit(6),
            lit(2),
            d("lid_t") + lit(0.6),
            z=(lid_w / 2).v,
            radius=b.stadium_radius(lit(2)),
            kind="XZ",
            side="Symmetric",
        )
    b.cut_text(
        "EXT" if ext else "INT",
        lit(5.0),
        App.Vector((lid_l / 2).v, (lid_w / 2).v, -0.15),
        (1, 0, 0),
        (0, 1, 0),
        (0, 0, d("label_depth").v),
        "lid",
    )
    b.pocket_rect(
        "notch",
        lid_l / 2 - lit(4.5),
        lid_w - d("skirt_t") / 2 - lit(0.8),
        lit(9),
        d("skirt_t") + lit(1.6),
        lit(2.2),
        z=(d("lid_t") + d("skirt_h") - lit(1.05)).v,
        side="Symmetric",
    )
    return b


def build_mount(pico):
    name = "mount_pico" if pico else "mount_bmp"
    b = Builder(name)
    P = b.params
    add_shared(P)
    P.set("mount_pico", 1 if pico else 0, "which")
    P.check()
    d = P.d
    body_l = d("pico_outer_l") if pico else d("bmp_outer_l")
    body_w = d("pico_outer_w") if pico else d("bmp_outer_w")
    jaw_wall = lit(1.6)
    lip = lit(1.3)
    groove_w = d("rail_t") + d("rail_clearance")
    groove_h = d("rail_h") + lit(0.25)
    jaw_h = lip + groove_h + lip
    jaw_l = body_l - lit(8)
    flange_l = lit(12)
    flange_t = lit(2.4)
    span = body_w + 2 * d("rail_t") + 2 * d("rail_clearance")
    jaw_total = jaw_wall + groove_w
    # Low jaw, then the end stop, then the high jaw. The stop is what
    # keeps the body one solid; the grooves are cut after both jaws exist.
    b.pad_rect("jaw0", zero(), zero(), jaw_l, jaw_total, jaw_h)
    b.pad_rect("stop", jaw_l - lit(1.6), zero(), lit(1.6), span + jaw_total, jaw_h)
    shift = span + jaw_total
    b.pad_rect("jaw1", zero(), shift - jaw_total, jaw_l, jaw_total, jaw_h)
    b.pad_rect("flange", jaw_l, jaw_wall, flange_l, span, flange_t)
    groove_len = jaw_l - lit(1.6) + d("cut_overshoot")
    b.pocket_rect(
        "groove0",
        -d("cut_overshoot"),
        jaw_wall,
        groove_len,
        groove_w + lit(0.2),
        groove_h,
        z=lip.v,
    )
    b.pocket_rect(
        "lead0",
        -d("cut_overshoot"),
        jaw_wall - lit(0.2),
        lit(2.4),
        groove_w + lit(0.6),
        groove_h + lit(0.4),
        z=(lip - lit(0.2)).v,
    )
    b.pocket_rect(
        "groove1",
        -d("cut_overshoot"),
        span - lit(0.2),
        groove_len,
        groove_w + lit(0.2),
        groove_h,
        z=lip.v,
    )
    b.pocket_rect(
        "lead1",
        -d("cut_overshoot"),
        span - lit(0.4),
        lit(2.4),
        groove_w + lit(0.8),
        groove_h + lit(0.4),
        z=(lip - lit(0.2)).v,
    )
    for i, frac in enumerate((lit(0.28), lit(0.72))):
        b.pocket_circle(
            "screw_%d" % i,
            jaw_l + flange_l * lit(0.55),
            jaw_wall + span * frac,
            d("m3_clearance_d") / 2,
            flange_t + d("cut_overshoot"),
        )
    b.pocket_rect(
        "fzip",
        jaw_l + lit(1.8),
        jaw_wall + span / 2 - d("ziptie_slot_l") / 2,
        d("ziptie_slot_w"),
        d("ziptie_slot_l"),
        flange_t + d("cut_overshoot"),
    )
    return b


PROBES = {
    "pico_case_base": [
        (30.0, 0.8, 6.9, False, "INT exit"),
        (35.0, 0.8, 6.9, True, "between INT and EXT"),
        (40.0, 0.8, 6.9, False, "EXT exit"),
        (0.8, 16.1, 7.1, False, "USB"),
        (3.6, 10.4, 0.6, False, "insert"),
        (16.0, 31.4, 6.8, False, "PWR"),
        (28.0, 16.0, 0.6, True, "floor"),
        (28.0, 16.0, 8.0, False, "cavity"),
        (28.35, -0.7, 1.6, False, "zip rail"),
        (55.9, 16.1, 10.0, False, "antenna"),
    ],
    "pico_case_lid": [
        (34.6, 17.6, 0.4, False, "OLED window"),
        (34.6, 24.0, 0.6, True, "beside window"),
        (10.6, 17.6, 0.6, False, "BOOTSEL"),
        (34.6, 17.6, 3.0, False, "nest pocket"),
    ],
    "bmp280_int_body": [
        (14.3, 0.8, 6.1, False, "cable"),
        (8.0, 0.8, 6.1, True, "beside cable"),
        (14.0, 12.0, 0.5, True, "floor"),
        (14.0, 12.0, 8.0, False, "cavity"),
    ],
    "bmp280_ext_body": [
        (14.3, 0.8, 6.1, False, "cable"),
        (8.0, 0.8, 6.1, True, "beside cable"),
        (14.0, 12.0, 8.0, False, "cavity"),
    ],
    "bmp280_int_lid": [
        (23.0, 14.3, 0.6, False, "vent"),
        (15.8, 14.3, 0.95, True, "label web"),
    ],
    "bmp280_ext_lid": [
        (23.0, 14.3, 0.6, False, "vent"),
        (15.8, 14.3, 0.95, True, "label web"),
    ],
    "mount_pico": [
        (24.0, 2.4, 3.0, False, "groove"),
        (24.0, 0.8, 3.0, True, "jaw wall"),
        (55.3, 11.6, 1.2, False, "flange screw"),
    ],
    "mount_bmp": [
        (10.0, 2.4, 3.0, False, "groove"),
        (10.0, 0.8, 3.0, True, "jaw wall"),
    ],
}


def render_all():
    if os.environ.get("SKIP_RENDER") == "1":
        print("SKIP_RENDER=1, not writing PNGs", flush=True)
        return
    RENDER_DIR.mkdir(parents=True, exist_ok=True)
    scad = STL_DIR / "_preview.scad"
    for stl in sorted(STL_DIR.glob("*.stl")):
        png = RENDER_DIR / (stl.stem + ".png")
        scad.write_text('import("%s");\n' % stl.resolve())
        cmd = [
            "xvfb-run", "-a", "openscad", "-o", str(png),
            "--imgsize=1200,900", "--colorscheme=Tomorrow",
            "--projection=perspective", "--autocenter", "--viewall",
            "--camera=0,0,0,55,0,32,0", str(scad),
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
    rel = vol_err / ref_vol if ref_vol else 1.0
    print(
        "COMPARE %s solid=%.2f stl=%.2f dV=%.2f (%.3f%%) dBox=%.4f tris=%d"
        % (builder.part, shape.Volume, ref_vol, shape.Volume - ref_vol, 100 * rel, bbox_err, ntri),
        flush=True,
    )
    print("  bbox solid [%.3f %.3f %.3f] [%.3f %.3f %.3f]" % (got_mn + got_mx), flush=True)
    print("  bbox stl   [%.3f %.3f %.3f] [%.3f %.3f %.3f]" % tuple(ref_mn + ref_mx), flush=True)
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
        ("mount_pico", lambda: build_mount(True)),
        ("mount_bmp", lambda: build_mount(False)),
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


try:
    main()
except SystemExit:
    raise
except Exception:
    traceback.print_exc()
    os._exit(1)
