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

// Cantilever finger. Root on z = 0, tip toward +z, inner face on x = 0,
// hook toward +x. `arm` is the distance from the root to the catch face.
// The lead-in drops 45° because `lead` equals the hook's inward reach.
// Sizes are arguments: a file brought in with `use` cannot see the
// caller's variables. The root is buried 0.2 mm into the lid plate, the
// hook overlaps the arm, and the pull tab overlaps the outer face, so
// the finger is one solid.
module latch_finger(arm, t, w, gap, reach, catch_h, lead) {
    hx = gap + reach;
    translate([-t, -w / 2, -0.2])
        cube([t, w, arm + 0.2]);
    translate([-0.02, -w / 2, arm - 0.04])
        cube([hx + 0.02, w, catch_h + 0.04]);
    hull() {
        translate([0, -w / 2, arm + catch_h + lead - 0.04])
            cube([0.05, w, 0.05]);
        translate([hx - 0.05, -w / 2, arm + catch_h - 0.04])
            cube([0.05, w, 0.08]);
    }
    // On the outer face, just under the catch, so a pinch releases it.
    // Buried 0.2 mm into the arm (the hook is inboard of this face).
    translate([-t - 0.8, -1.1, arm - 0.7])
        cube([1.0, 2.2, 0.9]);
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
