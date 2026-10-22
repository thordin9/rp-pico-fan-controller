// Pico W + 0.91" OLED case. Printable parts:
//   part = "base" | "lid" | "assembly" | "section" | "closed"
//
// The base prints bottom-down. The lid is modelled outer-face down
// (z = 0) with the latch fingers pointing up. Print it that way:
// the hooks are a small 45° overhang, and flipping the lid would
// put the fingers on the bed.
//
// The Pico sits on four standoffs. M2 heat-set inserts are pressed in
// from the bottom; M2 screws come down through the Pico's own holes.
// The lid snaps on. There is no screw boss and no fixed mounting ear.
// Two slide rails on the long walls take the optional bracket in
// mount.scad, and each rail has a zip-tie slot for use without it.
//
// Cable wall (y = 0, USB toward −X), four separate exits:
//   two FAN slots, INT (I2C0), EXT (I2C1). Opposite wall is PWR.

use <lib.scad>
include <dimensions.scad>

part = "base";

outer_l = pico_outer_l;
outer_w = pico_outer_w;
base_h = pico_base_h;

pcb_x0 = wall;
pcb_y0 = wall + pico_gutter;
pcb_top_z = floor_t + pico_standoff_h + pico_t;
header_top_z = pcb_top_z + pico_header_above_pcb;

hole_x = [pcb_x0 + pico_hole_inset_x, pcb_x0 + pico_hole_inset_x + pico_hole_dx];
hole_y = [pcb_y0 + pico_hole_inset_y, pcb_y0 + pico_hole_inset_y + pico_hole_dy];

usb_tip_x = pcb_x0 - pico_usb_overhang;
usb_z0 = pcb_top_z + (pico_usb_shell_h - pico_usb_opening_h) / 2;

// OLED sits on the lid, shifted toward the antenna so the nest clears
// BOOTSEL and the USB shell. The active area is centred on the module
// plus oled_active_dx / oled_active_dy.
oled_cx = pcb_x0 + pico_l / 2 + 6.0;
oled_cy = pcb_y0 + pico_w / 2;
oled_active_cx = oled_cx + oled_active_dx;
oled_active_cy = oled_cy + oled_active_dy;

corner_r = 2.0;

fan_slot_x = [12.0, 19.5];
fan_slot_l = 6.5;
fan_slot_h = 3.4;
fan_slot_z = 5.2;
i2c_int_x = 30.0;
i2c_ext_x = 40.0;
// INT and EXT take a bundled 6-wire Dupont lead (option a in the wiring
// guide). The 1x6 shell itself stays in the sensor housing.
sensor_slot_l = 8.0;
sensor_slot_h = 5.0;
sensor_slot_z = 5.2;
pwr_slot_x = 16.0;
pwr_slot_l = 8.0;
pwr_slot_h = 4.0;
pwr_slot_z = 4.8;

cleat_l = 9.0;
sensor_cleat_l = 9.6;
pwr_cleat_l = pwr_slot_l + 3.0;

module fit_checks() {
    assert(abs(outer_l - 56.7) < 1e-6, "Pico case length drifted");
    assert(abs(outer_w - 32.2) < 1e-6, "Pico case width drifted");
    assert(abs(base_h - 15.5) < 1e-6, "Pico case height drifted");
    assert(abs((hole_x[1] - hole_x[0]) - pico_hole_dx) < 1e-6, "Standoff X spacing");
    assert(abs((hole_y[1] - hole_y[0]) - pico_hole_dy) < 1e-6, "Standoff Y spacing");
    assert(usb_tip_x > 0.2 && usb_tip_x < wall - 0.15,
           "USB connector face is not inside the end wall");
    assert(usb_z0 > floor_t + 1.5, "USB opening breaks the floor");
    assert(fan_slot_z > rail_h + 0.8, "Cable slot cuts the slide rail");
    nest_half_l = (oled_pocket_l + 2 * oled_nest_wall) / 2;
    nest_x0 = oled_cx - nest_half_l;
    bootsel_x = pcb_x0 + pico_bootsel_from_usb_edge;
    assert(nest_x0 > bootsel_x + pico_bootsel_hole_d / 2 + 0.6,
           "OLED nest overlaps the BOOTSEL hole");
    assert(nest_x0 > pcb_x0 + pico_usb_shell_depth + 1.0,
           "OLED nest overlaps the USB connector");
    // Header plastic ends 2.88 mm in from the PCB edge. The nest must
    // clear that in plan; it is allowed to hang lower than the pins.
    header_inner_y = pcb_y0 + (pico_w - pico_row_spacing) / 2 + pico_header_plastic_w / 2;
    nest_y0 = oled_cy - oled_pocket_w / 2 - oled_nest_wall;
    assert(nest_y0 > header_inner_y + 0.30, "OLED nest hits a Pico header");
    assert(i2c_ext_x - i2c_int_x > sensor_slot_l + 1.5,
           "INT and EXT cable exits are not separate openings");
    assert(i2c_ext_x - i2c_int_x > sensor_cleat_l,
           "INT and EXT cleats meet");
    assert(sensor_slot_l >= 7.5 && sensor_slot_h >= 4.8,
           "Sensor exit is tight for a bundled 6-wire lead");
    assert(sensor_slot_z + sensor_slot_h + 1.4 < base_h - skirt_h - 0.4,
           "Sensor cleat meets the lid skirt");
    assert(i2c_int_x - fan_slot_x[1] > fan_slot_l / 2 + sensor_slot_l / 2 + 1.2,
           "INT exit is not separate from the fan exits");
    assert(cleat_l > fan_slot_l + 1.2, "Fan cleat does not land in the wall");
    assert(sensor_cleat_l > sensor_slot_l + 1.2, "Sensor cleat does not land in the wall");
    assert(pwr_cleat_l > pwr_slot_l + 1.5, "Power cleat does not land in the wall");
    // Straight-on, the through window covers the active area and stays
    // on the glass. The chamfer is wider, on the outside face.
    assert(oled_window_l + 1e-6 >= oled_active_l, "Window clips the active area");
    assert(oled_window_w + 1e-6 >= oled_active_w, "Window clips the active area");
    // Recess is latch_w + 0.8 wide. It has to miss every cable slot and
    // stay off the corner radius. The jaw (lip + groove + lip) ends
    // below pico_latch_z.
    half = (latch_w + 0.8) / 2;
    assert(pico_latch_front_a - half > corner_r, "Front latch runs into the USB corner");
    assert(pico_latch_front_a + half < fan_slot_x[0] - fan_slot_l / 2 - 0.3,
           "Front latch meets a FAN slot");
    assert(pico_latch_front_b - half > i2c_ext_x + sensor_slot_l / 2 + 0.3,
           "Front latch meets the EXT slot");
    assert(pico_latch_front_b + half < outer_l - corner_r, "Front latch runs into the antenna corner");
    assert(pico_latch_back_a - half > corner_r, "Back latch runs into the USB corner");
    assert(pico_latch_back_a + half < pwr_slot_x - pwr_slot_l / 2 - 0.3,
           "Back latch meets the PWR slot");
    assert(pico_latch_back_b - half > pwr_slot_x + pwr_slot_l / 2 + 0.3,
           "Back latch meets the PWR slot");
    assert(pico_latch_back_b + half < outer_l - corner_r, "Back latch runs into the antenna corner");
    echo("FIT pico case", outer_l, outer_w, base_h);
    echo("FIT pico latch", pico_latch_front_a, pico_latch_front_b, pico_latch_back_a, pico_latch_back_b);
    echo("FIT usb tip x", usb_tip_x, "opening z", usb_z0);
    echo("FIT header top", header_top_z, "nest y0", nest_y0, "header inner", header_inner_y);
    echo("FIT oled", oled_cx, oled_cy, "active", oled_active_cx, oled_active_cy, "nest x0", nest_x0);
    echo("FIT exits FAN", fan_slot_x[0], fan_slot_x[1], "INT", i2c_int_x, "EXT", i2c_ext_x, "PWR", pwr_slot_x);
}

module usb_opening() {
    translate([wall / 2, pcb_y0 + pico_w / 2, usb_z0])
        rotate([0, 0, 90])
            stadium_x(pico_usb_opening_w, pico_usb_opening_h, wall + 1.2);
}

module antenna_window() {
    aperture = pico_antenna_keepout_w;
    translate([outer_l - wall - 0.4,
               pcb_y0 + (pico_w - aperture) / 2,
               pcb_top_z - 1.2])
        cube([wall + 1.2, aperture, base_h]);
}

module cable_notches() {
    for (x = fan_slot_x)
        translate([x, wall / 2, fan_slot_z])
            stadium_x(fan_slot_l, fan_slot_h, wall + 1.2);
    translate([i2c_int_x, wall / 2, sensor_slot_z])
        stadium_x(sensor_slot_l, sensor_slot_h, wall + 1.2);
    translate([i2c_ext_x, wall / 2, sensor_slot_z])
        stadium_x(sensor_slot_l, sensor_slot_h, wall + 1.2);
    translate([pwr_slot_x, outer_w - wall / 2, pwr_slot_z])
        stadium_x(pwr_slot_l, pwr_slot_h, wall + 1.2);
}

module wall_labels() {
    translate([(fan_slot_x[0] + fan_slot_x[1]) / 2, 0.7, fan_slot_z + fan_slot_h + 2.0])
        rotate([90, 0, 0])
            mirror([1, 0, 0])
                deboss_text("FAN", 2.4, 0.45);
    translate([i2c_int_x, 0.7, sensor_slot_z + sensor_slot_h + 2.0])
        rotate([90, 0, 0])
            mirror([1, 0, 0])
                deboss_text("INT", 2.2, 0.45);
    translate([i2c_ext_x, 0.7, sensor_slot_z + sensor_slot_h + 2.0])
        rotate([90, 0, 0])
            mirror([1, 0, 0])
                deboss_text("EXT", 2.2, 0.45);
    translate([pwr_slot_x, outer_w - 0.7, pwr_slot_z + pwr_slot_h + 2.0])
        rotate([90, 0, 180])
            mirror([1, 0, 0])
                deboss_text("PWR", 2.4, 0.45);
}

module latch_recesses() {
    win = latch_w + 0.8;
    for (x = [pico_latch_front_a, pico_latch_front_b])
        translate([x - win / 2, -0.2, pico_latch_z])
            cube([win, latch_recess_d + 0.2, latch_recess_h]);
    for (x = [pico_latch_back_a, pico_latch_back_b])
        translate([x - win / 2, outer_w - latch_recess_d, pico_latch_z])
            cube([win, latch_recess_d + 0.2, latch_recess_h]);
}

module shell() {
    difference() {
        union() {
            rounded_rect(outer_l, outer_w, base_h, corner_r);
            slide_rails(outer_l, outer_w, rail_t, rail_h, rail_end_gap,
                        ziptie_slot_l, ziptie_slot_w, rail_detent);
        }
        translate([wall, wall, floor_t])
            cube([outer_l - 2 * wall, outer_w - 2 * wall, base_h]);
        usb_opening();
        antenna_window();
        cable_notches();
        wall_labels();
        latch_recesses();
    }
}

module standoffs() {
    for (x = hole_x)
        for (y = hole_y)
            translate([x, y, 0])
                cylinder(d=pico_standoff_od, h=floor_t + pico_standoff_h);
}

module cleat(x, y, z, length) {
    translate([x - length / 2, y, z])
        cube([length, 1.8, 1.4]);
}

module cleats() {
    // The bar sits on the top edge of the opening and bites the wall.
    // A bar across the inner mouth used to leave about 1.6 mm of the
    // slot, which a lead cannot pass.
    cleat(fan_slot_x[0], wall - 0.35, fan_slot_z + fan_slot_h, cleat_l);
    cleat(fan_slot_x[1], wall - 0.35, fan_slot_z + fan_slot_h, cleat_l);
    cleat(i2c_int_x, wall - 0.35, sensor_slot_z + sensor_slot_h, sensor_cleat_l);
    cleat(i2c_ext_x, wall - 0.35, sensor_slot_z + sensor_slot_h, sensor_cleat_l);
    cleat(pwr_slot_x, outer_w - wall - 1.45, pwr_slot_z + pwr_slot_h, pwr_cleat_l);
}

module base() {
    color([0.22, 0.28, 0.32])
        difference() {
            union() {
                shell();
                standoffs();
                cleats();
            }
            for (x = hole_x)
                for (y = hole_y) {
                    translate([x, y, -0.2])
                        cylinder(d=m2_insert_hole_d, h=m2_insert_hole_depth + 0.2);
                    translate([x, y, m2_insert_hole_depth - 0.05])
                        cylinder(d=m2_clearance_d, h=floor_t + pico_standoff_h);
                }
        }
}

// ---- lid, outer face on z = 0 ------------------------------------------------

lid_outer_l = outer_l + 2 * (skirt_gap + skirt_t);
lid_outer_w = outer_w + 2 * (skirt_gap + skirt_t);
ox = skirt_gap + skirt_t;
oy = skirt_gap + skirt_t;

function lid_of(v, body_span, lid_span) = (lid_span - body_span) / 2 + v;

module oled_nest() {
    x0 = lid_of(oled_cx, outer_l, lid_outer_l) - oled_pocket_l / 2 - oled_nest_wall;
    y0 = lid_of(oled_cy, outer_w, lid_outer_w) - oled_pocket_w / 2 - oled_nest_wall;
    nx = oled_pocket_l + 2 * oled_nest_wall;
    ny = oled_pocket_w + 2 * oled_nest_wall;
    gap = oled_connector_w + 1.6;
    translate([x0, y0, lid_t - 0.2]) {
        difference() {
            cube([nx, ny, oled_nest_drop + 0.2]);
            // Pocket starts at the inner face of the lid, so the glass
            // sits against that face and the window is not covered.
            translate([oled_nest_wall, oled_nest_wall, 0.2])
                cube([oled_pocket_l, oled_pocket_w, oled_nest_drop + 0.2]);
            translate([-0.2, (ny - gap) / 2, 0.2])
                cube([oled_nest_wall + 0.6, gap, oled_nest_drop + 0.2]);
        }
        clip_z = 0.2 + oled_nest_drop - oled_pcb_t - 0.7;
        for (side = [0, 1]) {
            yy = side == 0
                ? oled_nest_wall - 0.25
                : oled_nest_wall + oled_pocket_w - 0.45;
            translate([nx * 0.42, yy, clip_z])
                cube([7, 0.7, 0.7]);
            translate([nx * 0.42, side == 0 ? yy : yy + 0.45, clip_z + 0.7])
                cube([7, side == 0 ? 0.7 : 0.25, 0.45]);
        }
    }
}

module oled_window() {
    // Through opening on the active area, with a 45° viewing chamfer
    // that is wide on the outer face (z = 0) and tight on the glass.
    cx = lid_of(oled_active_cx, outer_l, lid_outer_l);
    cy = lid_of(oled_active_cy, outer_w, lid_outer_w);
    flare = lid_t;
    hull() {
        translate([cx - (oled_window_l + 2 * flare) / 2,
                   cy - (oled_window_w + 2 * flare) / 2,
                   -0.2])
            cube([oled_window_l + 2 * flare, oled_window_w + 2 * flare, 0.2]);
        translate([cx - oled_window_l / 2,
                   cy - oled_window_w / 2,
                   lid_t])
            cube([oled_window_l, oled_window_w, 0.4]);
    }
}

module bootsel_hole() {
    translate([
        lid_of(pcb_x0 + pico_bootsel_from_usb_edge, outer_l, lid_outer_l),
        lid_of(pcb_y0 + pico_w / 2 + pico_bootsel_from_center_y, outer_w, lid_outer_w),
        -0.2
    ])
        cylinder(d=pico_bootsel_hole_d, h=lid_t + 0.6);
}

module one_finger(arm) {
    latch_finger(arm, latch_t, latch_w, latch_gap, latch_reach, latch_catch, latch_lead);
}

module lid_latches() {
    // Seating mirrors Y. The cable wall (body y = 0) lands at high lid y,
    // and the hook has to point back toward the body.
    for (x = [pico_latch_front_a, pico_latch_front_b])
        translate([ox + x, oy + outer_w + latch_gap, lid_t])
            rotate([0, 0, -90])
                one_finger(pico_latch_arm);
    for (x = [pico_latch_back_a, pico_latch_back_b])
        translate([ox + x, oy - latch_gap, lid_t])
            rotate([0, 0, 90])
                one_finger(pico_latch_arm);
}

module latch_slots() {
    slot_w = latch_w + 2 * latch_kerf;
    h = skirt_h + 0.55;
    z0 = lid_t + 0.05;
    for (x = [pico_latch_front_a, pico_latch_front_b])
        translate([ox + x - slot_w / 2, lid_outer_w - skirt_t - 0.35, z0])
            cube([slot_w, skirt_t + 0.6, h]);
    for (x = [pico_latch_back_a, pico_latch_back_b])
        translate([ox + x - slot_w / 2, -0.2, z0])
            cube([slot_w, skirt_t + 0.55, h]);
}

module lid() {
    // Skirt outer matches the lid plate. Inner opening is the body plus
    // skirt_gap on every side, so the seated lid is centred.
    color([0.16, 0.38, 0.42])
        difference() {
            union() {
                rounded_rect(lid_outer_l, lid_outer_w, lid_t, corner_r);
                difference() {
                    translate([0, 0, lid_t - 0.2])
                        rounded_rect(lid_outer_l, lid_outer_w, skirt_h + 0.2, max(corner_r - 0.2, 0.4));
                    translate([skirt_t, skirt_t, lid_t - 0.4])
                        cube([lid_outer_l - 2 * skirt_t,
                              lid_outer_w - 2 * skirt_t,
                              skirt_h + 1]);
                    latch_slots();
                }
                oled_nest();
                lid_latches();
            }
            oled_window();
            bootsel_hole();
            // Opposite the cable wall once the lid is seated (Y is mirrored).
            translate([lid_of(oled_cx, outer_l, lid_outer_l),
                       skirt_t / 2,
                       lid_t + skirt_h - 1.15])
                cube([10, skirt_t + 1.6, 2.4], center=true);
        }
}

module seated_lid() {
    // 180° about X mirrors Y. Shift by the far overhang so the skirt
    // lands on the body instead of beside it.
    translate([-(lid_outer_l - outer_l) / 2,
               outer_w + (lid_outer_w - outer_w) / 2,
               base_h + lid_t])
        rotate([180, 0, 0])
            lid();
}

module oled_dummy() {
    // Glass against the lid inner face, PCB behind it, active area
    // marked on the glass. Coordinates are the case frame, lid closed.
    gx = oled_active_cx - oled_active_l / 2;
    gy = oled_active_cy - oled_active_w / 2;
    glass_z = base_h - oled_glass_t;
    color([0.12, 0.14, 0.16])
        translate([oled_cx - oled_pcb_l / 2, oled_cy - oled_pcb_w / 2,
                   base_h - oled_stack_h])
            cube([oled_pcb_l, oled_pcb_w, oled_pcb_t]);
    color([0.75, 0.82, 0.86])
        translate([oled_cx - oled_pcb_l / 2 + 1.2, oled_cy - oled_pcb_w / 2 + 1.0, glass_z])
            cube([oled_pcb_l - 2.4, oled_pcb_w - 2.0, oled_glass_t]);
    color([0.05, 0.22, 0.55])
        translate([gx, gy, glass_z + oled_glass_t - 0.12])
            cube([oled_active_l, oled_active_w, 0.16]);
}

module ghosts() {
    color([0.15, 0.55, 0.25, 0.45])
        translate([pcb_x0, pcb_y0, floor_t + pico_standoff_h])
            cube([pico_l, pico_w, pico_t]);
    oled_dummy();
}

fit_checks();

if (part == "base")
    base();
else if (part == "lid")
    lid();
else if (part == "assembly" || part == "closed") {
    base();
    ghosts();
    seated_lid();
} else if (part == "section") {
    difference() {
        union() {
            base();
            seated_lid();
        }
        // Cut on the OLED centreline so the chamfer and the glass show.
        translate([-10, oled_cy, -5])
            cube([120, 80, 80]);
    }
    ghosts();
} else
    assert(false, "part must be base, lid, assembly, closed, or section");
