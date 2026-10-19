// Optional wall bracket. Slides onto the rails of one case and stops
// against the far end. The case is usable without this part: the base
// is flat for tape, and each rail has its own zip-tie slot.
//
//   which = "pico" | "bmp"
//
// Prints flange-down. The jaws are a C-section around the rail, open
// toward the case, so there is no overhang in this orientation.

use <lib.scad>
include <dimensions.scad>

which = "pico";

pico = which == "pico";
body_l = pico ? 56.7 : 28.6;
body_w = pico ? 32.2 : 25.6;

jaw_wall = 1.6;
lip = 1.3;
groove_w = rail_t + rail_clearance;
groove_h = rail_h + 0.25;
jaw_h = lip + groove_h + lip;
jaw_l = body_l - 8.0;
flange_l = 12.0;
flange_t = 2.4;

module fit_checks() {
    assert(which == "pico" || which == "bmp", "which must be pico or bmp");
    assert(groove_w > rail_t + 0.2, "Bracket groove is tight on the rail");
    assert(groove_h > rail_h + 0.15, "Bracket groove is shorter than the rail");
    assert(jaw_l > body_l * 0.5, "Bracket jaws are too short to hold");
    echo("FIT mount", which, "body", body_l, body_w, "jaw", jaw_l, jaw_h);
}

module jaw() {
    difference() {
        cube([jaw_l, jaw_wall + groove_w, jaw_h]);
        translate([-0.2, jaw_wall, lip])
            cube([jaw_l + 0.4, groove_w + 0.2, groove_h]);
        // Lead-in at the open end.
        translate([-0.2, jaw_wall - 0.2, lip - 0.2])
            cube([2.4, groove_w + 0.6, groove_h + 0.4]);
    }
}

module bracket() {
    // Jaws open toward +Y / −Y around a case of width body_w.
    span = body_w + 2 * rail_t + 2 * rail_clearance;
    difference() {
        union() {
            translate([0, 0, 0])
                jaw();
            translate([0, span + jaw_wall + groove_w, 0])
                mirror([0, 1, 0])
                    jaw();
            // End stop, just past the jaws, ties the two sides together.
            translate([jaw_l - 1.6, 0, 0])
                cube([1.6, span + jaw_wall + groove_w, jaw_h]);
            // Screw flange beyond the stop.
            translate([jaw_l, jaw_wall, 0])
                cube([flange_l, span, flange_t]);
        }
        // Two M3 holes and one zip-tie slot in the flange.
        for (dy = [span * 0.28, span * 0.72])
            translate([jaw_l + flange_l * 0.55, jaw_wall + dy, -0.2])
                cylinder(d=m3_clearance_d, h=flange_t + 0.6);
        translate([jaw_l + 1.8, jaw_wall + span / 2 - ziptie_slot_l / 2, -0.2])
            cube([ziptie_slot_w, ziptie_slot_l, flange_t + 0.6]);
    }
}

fit_checks();
bracket();
