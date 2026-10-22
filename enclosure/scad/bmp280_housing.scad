// BMP280 housing, printed twice. One body for the purple GY-BMP280.
//   variant = "INT" or "EXT"   only the lid label changes
//   part    = "body" | "lid" | "assembly" | "section"
//
// The board sits against the side walls and the back wall, with a bay
// on the header edge for a 1×6 Dupont plug or soldered wires. Slide rails
// match the Pico case. The lid locates on a short skirt and locks with
// two cantilever fingers, one on each end.

use <lib.scad>
include <dimensions.scad>

variant = "INT";
part = "body";

ext = variant == "EXT";
label = ext ? "EXT" : "INT";

bmp_corner = 1.2;
// Rounded opening, not a full stadium: a semicircle end would pinch a
// 15.24 mm Dupont shell. 0.8 mm corners still print without a sharp notch.
cable_w = 15.5;
cable_h = 4.6;
cable_r = 0.8;
cable_z0 = rail_h + 0.55;
cable_y0 = -1.2;
cable_depth = wall + 3.4;

module fit_checks() {
    assert(variant == "INT" || variant == "EXT", "variant must be INT or EXT");
    assert(abs(bmp_outer_l - 19.1) < 1e-6, "BMP280 length drifted");
    assert(abs(bmp_outer_w - 18.35) < 1e-6, "BMP280 width drifted");
    assert(abs(bmp_body_h - 13.7) < 1e-6, "BMP280 height drifted");
    assert(abs((bmp_board_x + bmp_pcb_l / 2) - bmp_outer_l / 2) < 1e-6,
           "Header is not centred on the cable exit");
    assert(cable_z0 >= rail_h + 0.4, "Cable slot cuts the slide rail");
    assert(cable_z0 + cable_h < bmp_body_h - skirt_h - 0.4,
           "Cable slot meets the lid skirt");
    assert(cable_w + 1e-6 >= 6 * 2.54, "Exit is narrower than a 1x6 Dupont shell");
    assert(cable_h >= 4.2, "Exit is too short for a Dupont plug");
    assert(cable_w + 0.2 < bmp_chamber_l, "Cable exit breaks the side walls");
    assert(cable_y0 < -0.4, "Cable cutter does not start outside the wall");
    assert(cable_y0 + cable_depth > wall + 1.5,
           "Cable cutter does not break into the cavity");
    assert(cable_w / 2 + 0.5 < bmp_outer_l / 2 - bmp_corner,
           "Cable exit runs into the corner radius");
    assert(bmp_latch_z >= 2.4, "Latch recess meets the floor");
    assert(bmp_latch_z + latch_recess_h + bmp_latch_arm < bmp_body_h + 0.2,
           "Latch arm does not reach the recess");
    echo("FIT bmp", variant, bmp_outer_l, bmp_outer_w, bmp_body_h);
    echo("FIT bmp cable", cable_w, cable_h, "z", cable_z0);
    echo("FIT bmp board", bmp_board_x, bmp_board_y);
}

module rounded_box(x, y, z, r) {
    hull() {
        for (dx = [r, x - r])
            for (dy = [r, y - r])
                translate([dx, dy, 0])
                    cylinder(h=z, r=r);
    }
}

module cable_slot() {
    translate([bmp_outer_l / 2 - cable_w / 2, cable_y0, cable_z0])
        rounded_box(cable_w, cable_depth, cable_h, cable_r);
}

module shell() {
    difference() {
        union() {
            rounded_rect(bmp_outer_l, bmp_outer_w, bmp_body_h, bmp_corner);
            slide_rails(bmp_outer_l, bmp_outer_w, rail_t, rail_h, rail_end_gap,
                        ziptie_slot_l, ziptie_slot_w, rail_detent);
        }
        translate([wall, wall, floor_t])
            cube([bmp_chamber_l, bmp_chamber_w, bmp_body_h]);
        cable_slot();
        latch_recesses();
    }
}

module latch_recesses() {
    wy = bmp_outer_w / 2 - (latch_w + 0.8) / 2;
    translate([-0.2, wy, bmp_latch_z])
        cube([latch_recess_d + 0.2, latch_w + 0.8, latch_recess_h]);
    translate([bmp_outer_l - latch_recess_d, wy, bmp_latch_z])
        cube([latch_recess_d + 0.2, latch_w + 0.8, latch_recess_h]);
}

module platform() {
    // Pads under the corners, and a boss around each M2 hole. The walls
    // locate the board in X and against the back; the header edge stays open.
    leg = 1.8;
    for (px = [0.25, bmp_pcb_l - leg - 0.25])
        for (py = [0.25, bmp_pcb_w - leg - 0.25])
            translate([bmp_board_x + px, bmp_board_y + py, floor_t - 0.2])
                cube([leg, leg, bmp_platform_h + 0.2]);
    for (hx = [bmp_hole_inset_x, bmp_pcb_l - bmp_hole_inset_x])
        translate([bmp_board_x + hx,
                   bmp_board_y + bmp_pcb_w - bmp_hole_inset_back,
                   floor_t - 0.2])
            cylinder(d=4.2, h=bmp_platform_h + 0.2);
}

module screw_holes() {
    for (hx = [bmp_hole_inset_x, bmp_pcb_l - bmp_hole_inset_x])
        translate([bmp_board_x + hx,
                   bmp_board_y + bmp_pcb_w - bmp_hole_inset_back,
                   -0.2])
            cylinder(d=bmp_hole_d, h=floor_t + bmp_platform_h + 0.8);
}

module strain_cleat() {
    // Bar on the inner face at the top of the slot. The ends bite the
    // side walls, so the through hole stays the full opening.
    translate([wall - 0.4, wall + 0.25, cable_z0 + cable_h])
        cube([bmp_chamber_l + 0.8, 1.6, 1.2]);
}

module body() {
    color(ext ? [0.55, 0.58, 0.52] : [0.45, 0.62, 0.70])
        difference() {
            union() {
                shell();
                platform();
                strain_cleat();
            }
            screw_holes();
        }
}

lid_outer_l = bmp_outer_l + 2 * (skirt_gap + skirt_t);
lid_outer_w = bmp_outer_w + 2 * (skirt_gap + skirt_t);
ox = skirt_gap + skirt_t;
oy = skirt_gap + skirt_t;

module one_finger(arm) {
    latch_finger(arm, latch_t, latch_w, latch_gap, latch_reach, latch_catch, latch_lead);
}

module lid_latches() {
    // 180° seating mirrors Y, not X, so the end fingers stay on the ends.
    yc = oy + bmp_outer_w / 2;
    translate([ox - latch_gap, yc, lid_t])
        one_finger(bmp_latch_arm);
    translate([ox + bmp_outer_l + latch_gap, yc, lid_t])
        mirror([1, 0, 0])
            one_finger(bmp_latch_arm);
}

module latch_slots() {
    // Cut the skirt away around each finger. The finger is added back
    // and roots only in the lid plate, so the arm can flex.
    yc = oy + bmp_outer_w / 2;
    slot_w = latch_w + 2 * latch_kerf;
    h = skirt_h + 0.55;
    y0 = yc - slot_w / 2;
    translate([-0.2, y0, lid_t + 0.05])
        cube([skirt_t + 0.55, slot_w, h]);
    translate([lid_outer_l - skirt_t - 0.35, y0, lid_t + 0.05])
        cube([skirt_t + 0.6, slot_w, h]);
}

module lid_vents() {
    // Two slots over the middle of the board, where the chip sits.
    cx = ox + bmp_board_x + bmp_pcb_l / 2;
    cy = bmp_outer_w + oy - (bmp_board_y + bmp_pcb_w / 2);
    for (dx = [-1.7, 1.7])
        translate([cx + dx - 2.1, cy - 0.9, -0.2])
            rounded_box(4.2, 1.8, lid_t + 0.6, 0.6);
}

module lid() {
    color(ext ? [0.62, 0.66, 0.58] : [0.30, 0.45, 0.52])
        difference() {
            union() {
                rounded_rect(lid_outer_l, lid_outer_w, lid_t, bmp_corner);
                difference() {
                    translate([0, 0, lid_t - 0.2])
                        rounded_rect(lid_outer_l, lid_outer_w, skirt_h + 0.2, bmp_corner);
                    translate([skirt_t, skirt_t, lid_t - 0.4])
                        cube([lid_outer_l - 2 * skirt_t,
                              lid_outer_w - 2 * skirt_t,
                              skirt_h + 0.8]);
                    latch_slots();
                }
                lid_latches();
            }
            lid_vents();
            translate([lid_outer_l / 2, lid_outer_w - 4.2, -0.15])
                deboss_text(label, 3.6, 0.45);
            // Notch on the edge that seats opposite the cable wall.
            // Seating mirrors Y, so that edge is lid y = 0.
            translate([lid_outer_l / 2, skirt_t / 2, lid_t + skirt_h - 1.05])
                cube([8, skirt_t + 1.6, 2.2], center=true);
        }
}

module seated_lid() {
    // 180° about X turns the outer face up and mirrors Y. The translation
    // puts that mirrored skirt back over the body.
    translate([-(lid_outer_l - bmp_outer_l) / 2,
               bmp_outer_w + (lid_outer_w - bmp_outer_w) / 2,
               bmp_body_h + lid_t])
        rotate([180, 0, 0])
            lid();
}

module ghost_module() {
    color([0.75, 0.15, 0.12, 0.55])
        translate([bmp_board_x, bmp_board_y, floor_t + bmp_platform_h])
            cube([bmp_pcb_l, bmp_pcb_w, bmp_pcb_t]);
}

fit_checks();

if (part == "body")
    body();
else if (part == "lid")
    lid();
else if (part == "assembly") {
    body();
    ghost_module();
    seated_lid();
} else if (part == "section") {
    difference() {
        union() {
            body();
            seated_lid();
        }
        translate([-20, bmp_outer_w / 2, -5])
            cube([80, 60, 50]);
    }
    ghost_module();
} else
    assert(false, "part must be body, lid, assembly, or section");
