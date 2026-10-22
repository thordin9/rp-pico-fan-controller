#!/usr/bin/env bash
# Rebuild binary STLs and PNG previews. Fails if OpenSCAD asserts, if a
# mesh is not a single 2-manifold shell, or if a preview PNG is empty.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
SCAD="$ROOT/scad"
STL="$ROOT/stl"
PNG="$ROOT/renders"
Q="${QUALITY:-48}"
PQ="${PREVIEW_QUALITY:-28}"

mkdir -p "$STL" "$PNG"

run_stl() {
  local src="$1" out="$2"
  shift 2
  local log
  log="$(mktemp)"
  if ! openscad -o "$out" --export-format binstl -D "quality=${Q}" "$@" "$SCAD/$src" >"$log" 2>&1; then
    cat "$log"
    echo "OpenSCAD failed while writing $out" >&2
    exit 1
  fi
  if grep -Eq "ERROR:|Assertion" "$log"; then
    cat "$log"
    echo "OpenSCAD reported an error for $out" >&2
    exit 1
  fi
  if grep -Eq "Simple:[[:space:]]+no|not a valid 2-manifold" "$log"; then
    cat "$log"
    echo "Mesh is not a valid 2-manifold: $out" >&2
    exit 1
  fi
  if ! grep -Eq "Simple:[[:space:]]+yes" "$log"; then
    cat "$log"
    echo "OpenSCAD did not report Simple: yes for $out" >&2
    exit 1
  fi
  rm -f "$log"
  echo "stl $out"
}

run_png() {
  local src="$1" out="$2"
  shift 2
  local camera="0,0,0,55,0,32,0"
  if [[ "${1:-}" == --camera ]]; then
    camera="$2"
    shift 2
  fi
  local log
  log="$(mktemp)"
  if ! xvfb-run -a openscad -o "$out" \
      --imgsize=1200,900 \
      --colorscheme=Tomorrow \
      --projection=perspective \
      --autocenter --viewall \
      --camera="$camera" \
      -D "quality=${PQ}" "$@" "$SCAD/$src" >"$log" 2>&1; then
    cat "$log"
    echo "OpenSCAD preview failed for $out" >&2
    exit 1
  fi
  if grep -Eq "ERROR:|Assertion" "$log"; then
    cat "$log"
    echo "OpenSCAD reported an error for $out" >&2
    exit 1
  fi
  local bytes
  bytes="$(wc -c < "$out")"
  if [[ "$bytes" -lt 5000 ]]; then
    echo "Preview looks empty ($bytes bytes): $out" >&2
    exit 1
  fi
  rm -f "$log"
  echo "png $out ($bytes bytes)"
}

run_stl pico_case.scad "$STL/pico_case_base.stl" -D 'part="base"'
run_stl pico_case.scad "$STL/pico_case_lid.stl" -D 'part="lid"'
run_stl bmp280_housing.scad "$STL/bmp280_int_body.stl" -D 'variant="INT"' -D 'part="body"'
run_stl bmp280_housing.scad "$STL/bmp280_int_lid.stl" -D 'variant="INT"' -D 'part="lid"'
run_stl bmp280_housing.scad "$STL/bmp280_ext_body.stl" -D 'variant="EXT"' -D 'part="body"'
run_stl bmp280_housing.scad "$STL/bmp280_ext_lid.stl" -D 'variant="EXT"' -D 'part="lid"'
run_stl mount.scad "$STL/mount_pico.stl" -D 'which="pico"'
run_stl mount.scad "$STL/mount_bmp.stl" -D 'which="bmp"'

run_png pico_case.scad "$PNG/pico_case_base.png" -D 'part="base"'
run_png pico_case.scad "$PNG/pico_case_lid.png" -D 'part="lid"'
run_png pico_case.scad "$PNG/pico_case_section.png" -D 'part="section"'
run_png pico_case.scad "$PNG/pico_case_closed.png" -D 'part="closed"'
run_png bmp280_housing.scad "$PNG/bmp280_int_body.png" -D 'variant="INT"' -D 'part="body"'
run_png bmp280_housing.scad "$PNG/bmp280_int_lid.png" -D 'variant="INT"' -D 'part="lid"'
run_png bmp280_housing.scad "$PNG/bmp280_ext_body.png" -D 'variant="EXT"' -D 'part="body"'
run_png bmp280_housing.scad "$PNG/bmp280_ext_lid.png" -D 'variant="EXT"' -D 'part="lid"'
run_png bmp280_housing.scad "$PNG/bmp280_section.png" -D 'variant="INT"' -D 'part="section"'
run_png bmp280_housing.scad "$PNG/bmp280_assembly.png" -D 'variant="INT"' -D 'part="assembly"'
# Cable face is Y=0. Look from in front and below so the through exit is the subject.
run_png bmp280_housing.scad "$PNG/bmp280_cable_exit.png" \
    --camera "0,0,0,25,0,20,0" \
    -D 'variant="INT"' -D 'part="body"'
run_png mount.scad "$PNG/mount_pico.png" -D 'which="pico"'
run_png mount.scad "$PNG/mount_bmp.png" -D 'which="bmp"'

python3 - "$STL" << 'PY'
import struct, collections, sys
from pathlib import Path

stl_dir = Path(sys.argv[1])

def load(path):
    data = Path(path).read_bytes()
    n = struct.unpack_from("<I", data, 80)[0]
    tris = []
    off = 84
    for _ in range(n):
        v = struct.unpack_from("<12fH", data, off)
        tris.append((v[3:6], v[6:9], v[9:12]))
        off += 50
    return tris

def q(p, s=1000):
    return tuple(int(round(c * s)) for c in p)

def analyze(path):
    tris = load(path)
    parent = {}
    def find(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra
    edges = collections.Counter()
    degen = 0
    for a, b, c in tris:
        qa, qb, qc = q(a), q(b), q(c)
        if len({qa, qb, qc}) < 3:
            degen += 1
            continue
        union(qa, qb)
        union(qa, qc)
        for e in (tuple(sorted((qa, qb))), tuple(sorted((qb, qc))), tuple(sorted((qc, qa)))):
            edges[e] += 1
    shells = len({find(v) for v in parent})
    bad = {k: v for k, v in collections.Counter(edges.values()).items() if k != 2}
    # A few zero-area triangles show up where a cylinder meets the floor
    # (standoffs, bosses). Slicers drop them. The edge test is on the rest.
    if shells != 1 or bad or degen > 80:
        raise SystemExit(f"{path.name}: shells={shells} bad_edges={bad} degen={degen}")
    print(f"mesh {path.name}: tris={len(tris)} shells=1 degen={degen}")
    return [t for t in tris if len({q(t[0]), q(t[1]), q(t[2])}) == 3]

def inside(tris, pt):
    dirs = [(1, 0.013, 0.027), (0.017, 1, 0.023), (0.019, 0.011, 1)]
    votes = []
    for dx, dy, dz in dirs:
        hits = 0
        ox, oy, oz = pt
        for a, b, c in tris:
            ax, ay, az = a
            bx, by, bz = b
            cx, cy, cz = c
            e1 = (bx - ax, by - ay, bz - az)
            e2 = (cx - ax, cy - ay, cz - az)
            px = dy * e2[2] - dz * e2[1]
            py = dz * e2[0] - dx * e2[2]
            pz = dx * e2[1] - dy * e2[0]
            det = e1[0] * px + e1[1] * py + e1[2] * pz
            if abs(det) < 1e-9:
                continue
            inv = 1 / det
            sx, sy, sz = ox - ax, oy - ay, oz - az
            u = (sx * px + sy * py + sz * pz) * inv
            if u < 0 or u > 1:
                continue
            qx = sy * e1[2] - sz * e1[1]
            qy = sz * e1[0] - sx * e1[2]
            qz = sx * e1[1] - sy * e1[0]
            v = (dx * qx + dy * qy + dz * qz) * inv
            if v < 0 or u + v > 1:
                continue
            t = (e2[0] * qx + e2[1] * qy + e2[2] * qz) * inv
            if t > 1e-6:
                hits += 1
        votes.append(hits % 2 == 1)
    return sum(votes) >= 2

def expect(tris, name, pt, want):
    got = inside(tris, pt)
    if got != want:
        raise SystemExit(f"FAIL {name} at {pt}: inside={got}, expected {want}")

base = analyze(stl_dir / "pico_case_base.stl")
# Separate exits on the cable wall, and the holes that have to stay open.
expect(base, "INT exit", (30.0, 0.8, 6.9), False)
expect(base, "INT exit into cavity", (30.0, 2.0, 6.9), False)
expect(base, "wall between INT and EXT", (35.0, 0.8, 6.9), True)
expect(base, "EXT exit", (40.0, 0.8, 6.9), False)
expect(base, "EXT exit into cavity", (40.0, 2.0, 6.9), False)
expect(base, "FAN exit", (12.0, 0.8, 6.9), False)
expect(base, "FAN exit into cavity", (12.0, 2.0, 6.9), False)
expect(base, "second FAN exit into cavity", (19.5, 2.0, 6.9), False)
expect(base, "USB opening", (0.8, 16.1, 7.1), False)
expect(base, "standoff insert bore", (3.6, 10.4, 0.6), False)
expect(base, "PWR exit", (16.0, 31.4, 6.8), False)
expect(base, "PWR exit into cavity", (16.0, 30.3, 6.8), False)
expect(base, "floor", (28.0, 16.0, 0.6), True)
expect(base, "zip slot in rail", (28.35, -0.7, 1.6), False)
expect(base, "front latch recess", (5.2, 0.25, 7.2), False)
expect(base, "wall behind front latch", (5.2, 1.15, 7.2), True)
expect(base, "back latch recess", (44.0, 31.9, 7.2), False)

lid = analyze(stl_dir / "pico_case_lid.stl")
# Through-window on the active-area centre. Beside it the lid is solid.
expect(lid, "OLED window", (34.6, 17.6, 0.4), False)
expect(lid, "lid beside window", (34.6, 24.0, 0.6), True)
expect(lid, "BOOTSEL", (10.6, 17.6, 0.6), False)
expect(lid, "front latch arm", (6.7, 34.4, 5.0), True)
expect(lid, "front latch hook", (6.7, 33.2, 8.9), True)
expect(lid, "back latch arm", (9.5, 0.8, 5.0), True)
expect(lid, "front latch kerf", (3.35, 34.5, 2.8), False)

ib = analyze(stl_dir / "bmp280_int_body.stl")
expect(ib, "INT cable in the wall", (9.55, 0.8, 6.05), False)
expect(ib, "INT cable into the cavity", (9.55, 2.2, 6.05), False)
expect(ib, "INT cable outside the wall", (9.55, -0.4, 6.05), False)
expect(ib, "INT wall beside cable", (1.2, 0.8, 6.05), True)
expect(ib, "INT floor", (9.5, 10.0, 0.4), True)
expect(ib, "INT cavity", (9.5, 10.0, 8.0), False)
expect(ib, "INT latch recess", (0.25, 9.175, 4.4), False)
expect(ib, "INT wall behind latch", (1.15, 9.175, 4.4), True)
expect(ib, "INT cleat", (9.55, 2.2, 8.9), True)
expect(ib, "INT under cleat", (9.55, 2.2, 7.5), False)

eb = analyze(stl_dir / "bmp280_ext_body.stl")
expect(eb, "EXT cable in the wall", (9.55, 0.8, 6.05), False)
expect(eb, "EXT cable into the cavity", (9.55, 2.2, 6.05), False)
expect(eb, "EXT wall beside cable", (1.2, 0.8, 6.05), True)
expect(eb, "EXT cavity", (9.5, 10.0, 8.0), False)
expect(eb, "EXT latch recess", (0.25, 9.175, 4.4), False)
expect(eb, "EXT wall behind latch", (1.15, 9.175, 4.4), True)

il = analyze(stl_dir / "bmp280_int_lid.stl")
expect(il, "INT lid vent", (11.05, 9.3, 0.4), False)
expect(il, "INT label does not punch through", (11.05, 17.15, 1.05), True)
expect(il, "INT latch arm", (0.8, 10.675, 5.0), True)
expect(il, "INT latch hook", (1.7, 10.675, 9.95), True)
expect(il, "INT latch kerf", (0.6, 7.3, 2.8), False)
el = analyze(stl_dir / "bmp280_ext_lid.stl")
expect(el, "EXT lid vent", (11.05, 9.3, 0.4), False)
expect(el, "EXT latch hook", (1.7, 10.675, 9.95), True)

analyze(stl_dir / "mount_pico.stl")
analyze(stl_dir / "mount_bmp.stl")
print("fit checks passed")
PY
