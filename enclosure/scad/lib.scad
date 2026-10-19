// Shared solids. Dimensions live in dimensions.scad.

module rounded_rect(x, y, z, r) {
    rr = min(r, min(x, y) / 2 - 0.05);
    hull() {
        for (px = [rr, x - rr])
            for (py = [rr, y - rr])
                translate([px, py, 0])
                    cylinder(h=z, r=rr);
    }
}

// Stadium slot. Long axis X, thickness along Y, centred on the origin.
module stadium_x(length, height, depth) {
    r = min(height / 2, length / 2);
    span = max(length - 2 * r, 0);
    translate([0, -depth / 2, 0])
        hull() {
            for (dx = [-span / 2, span / 2])
                translate([dx, 0, r])
                    rotate([-90, 0, 0])
                        cylinder(h=depth, r=r);
        }
}

// Printable rain awning. Root sits on the Y=0 plane; callers overlap it
// with the wall. The underside rises toward +Y at 45°, so the hood prints
// without support. root_h must clear proj + 0.35 + tip_h so the top falls
// toward the tip and water drips off the edge.
module rain_hood(length, proj=2.0, root_h=3.3, tip_h=0.6) {
    hull() {
        translate([-length / 2, -0.45, 0])
            cube([length, 0.45, root_h]);
        translate([-length / 2, proj - 0.15, proj + 0.35])
            cube([length, 0.15, tip_h]);
    }
}

// Snap ridge. Root on the Y=0 plane, protrudes toward +Y.
// Bottom `snap_catch_h` is a vertical catch; above that a 45° lead-in.
module snap_ridge(length, prot, catch_h) {
    translate([-length / 2, 0, 0]) {
        cube([length, prot, catch_h]);
        hull() {
            translate([0, 0, catch_h])
                cube([length, prot, 0.02]);
            translate([0, 0, catch_h + prot])
                cube([length, 0.02, 0.02]);
        }
    }
}

module deboss_text(label, size, depth=0.65) {
    linear_extrude(height=depth + 0.4)
        offset(delta=0.02)
            text(label, size=size, font="Liberation Sans:style=Bold",
                 halign="center", valign="center");
}

// Right-triangle gusset in the XZ plane, extruded along Y.
// Hypotenuse is the top face, so it prints without support.
module gusset_xz(run, rise, thick) {
    rotate([90, 0, 0])
        linear_extrude(height=thick)
            polygon([[0, 0], [run, 0], [0, rise]]);
}
