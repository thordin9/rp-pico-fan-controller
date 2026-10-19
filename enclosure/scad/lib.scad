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
// Slide rail on the outside of a long wall. Overlaps the wall by `bite`
// so the union is not a coplanar face. The zip-tie slot stays in the
// rail and does not break into the cavity. A detent near the open end
// is what the bracket jaw flexes over.
module slide_rails(length, width, t, h, end_gap, slot_l, slot_w, detent) {
    bite = 0.4;
    x0 = end_gap;
    span = length - 2 * end_gap;
    for (side = [-1, 1]) {
        y = side < 0 ? -t : width - bite;
        translate([x0, y, 0])
            difference() {
                cube([span, t + bite, h]);
                translate([span / 2 - slot_l / 2,
                           side < 0 ? 0 : bite,
                           (h - slot_w) / 2])
                    cube([slot_l, t + 0.2, slot_w]);
            }
        // Overlap the rail by 0.25 so the detent is not a coplanar face.
        bump_y = side < 0 ? -t - detent : width + t - 0.25;
        translate([x0 + 2.2, bump_y, 0.6])
            cube([1.6, detent + 0.25, h - 1.2]);
    }
}
