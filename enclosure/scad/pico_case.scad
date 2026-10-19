// Pico W + 0.91" OLED case. Two printable parts:
//   part = "base" | "lid" | "assembly" | "section"
//
// The base prints bottom-down. The lid prints outer-face down (the way it
// is modeled). Assembly / section previews seat the lid on the base.
//
// The Pico sits on four standoffs. M2 heat-set inserts are pressed in from
// the bottom of each standoff; M2 screws come down through the Pico's own
// 2.1 mm holes. The lid is a second set of four inserts, pressed in from
// the top of the corner bosses before the lid goes on.
//
// Cable wall (y = 0, USB toward −X), four separate exits:
//   two FAN slots  — PWM/tach for the four fans, split two and two
//   INT            — internal BMP280, I2C0 (GP4 SDA / GP5 SCL), shared
//                    electrically with the OLED, which stays inside the case
//   EXT            — external BMP280, I2C1 (GP6 SDA / GP7 SCL)
// Both sensors are hardwired to 0x76, so the cables must not share a bus.
// Each sensor cable is four wires: VCC, GND, SCL, SDA.
// The opposite wall is PWR: 5 V to VSYS and 12 V for the fans.

use <lib.scad>
include <dimensions.scad>

part = "base";

outer_l = wall + pico_l + pico_antenna_gap + wall;          // 63
outer_w = wall + pico_gutter + pico_w + pico_gutter + wall; // 47
base_h = floor_t + pico_standoff_h + pico_t + pico_header_above_pcb + pico_above_header;

// PCB origin. The USB edge of the PCB is on the inner face of the USB wall,
// so the 1.3 mm overhang lands inside that wall.
pcb_x0 = wall;
pcb_y0 = wall + pico_gutter;
pcb_top_z = floor_t + pico_standoff_h + pico_t;
header_top_z = pcb_top_z + pico_header_above_pcb;

hole_x = [pcb_x0 + pico_hole_inset_x, pcb_x0 + pico_hole_inset_x + pico_hole_dx];
hole_y = [pcb_y0 + pico_hole_inset_y, pcb_y0 + pico_hole_inset_y + pico_hole_dy];

usb_tip_x = pcb_x0 - pico_usb_overhang;
usb_z0 = pcb_top_z + (pico_usb_shell_h - pico_usb_opening_h) / 2;

// OLED sits on the lid, shifted toward the antenna just enough that the
// BOOTSEL hole and the USB shell stay clear of the nest.
oled_cx = pcb_x0 + pico_l / 2 + 6.0;
oled_cy = pcb_y0 + pico_w / 2;

corner_r = 3.0;
ear_l = 16.0;
ear_w = 12.0;
ear_t = 3.2;

lid_boss_od = 8.0;
// Centre is this far in from the inner face. Smaller than the boss radius,
// so the boss bites both walls of the corner.
lid_boss_inset = 3.2;

// y = 0 wall, USB end toward −X. Centres stay clear of the corner bosses.
fan_slot_x = [16, 26.5];
fan_slot_l = 8.0;
fan_slot_h = 4.6;
fan_slot_z = 4.2;
i2c_int_x = 37;    // internal BMP280, I2C0, 4-wire
i2c_ext_x = 47.5;  // external BMP280, I2C1, 4-wire
sensor_slot_l = 8.0;
sensor_slot_h = 4.2;
sensor_slot_z = 4.0;
pwr_slot_x = 16;
pwr_slot_l = 12.0;
pwr_slot_h = 6.0;
pwr_slot_z = 4.0;

module fit_checks() {
    assert(abs(outer_l - 63) < 1e-6, "Pico case length drifted");
    assert(abs(outer_w - 47) < 1e-6, "Pico case width drifted");
    assert(abs(base_h - 23) < 1e-6, "Pico case height drifted");
    assert(abs((hole_x[1] - hole_x[0]) - pico_hole_dx) < 1e-6, "Standoff X spacing");
    assert(abs((hole_y[1] - hole_y[0]) - pico_hole_dy) < 1e-6, "Standoff Y spacing");
    assert(usb_tip_x > 0.3 && usb_tip_x < wall - 0.2,
           "USB connector face is not inside the end wall");
    assert(usb_z0 > floor_t + 1, "USB opening breaks the floor");
    nest_half_l = (oled_pocket_l + 2 * oled_nest_wall) / 2;
    nest_x0 = oled_cx - nest_half_l;
    bootsel_x = pcb_x0 + pico_bootsel_from_usb_edge;
    assert(nest_x0 > bootsel_x + pico_bootsel_hole_d / 2 + 0.8,
           "OLED nest overlaps the BOOTSEL hole");
    assert(nest_x0 > pcb_x0 + pico_usb_shell_depth + 1.0,
           "OLED nest overlaps the USB connector");
    nest_bottom = base_h - oled_nest_drop;
    assert(nest_bottom > header_top_z + 1.0,
           "OLED nest does not clear the Pico headers");
    assert(pico_antenna_gap >= 6, "Antenna end gap");
    assert(i2c_ext_x - i2c_int_x > sensor_slot_l + 2,
           "INT and EXT cable exits are not separate openings");
    assert(sensor_slot_l >= 6 && sensor_slot_h >= 3.5,
           "Sensor exit is tight for a 4-wire cable");
    assert(i2c_int_x - fan_slot_x[1] > fan_slot_l / 2 + sensor_slot_l / 2 + 1.5,
           "INT exit is not separate from the fan exits");
    boss_r = lid_boss_od / 2;
    assert(boss_r - lid_boss_inset >= 0.5, "Corner boss does not bite the wall");
    boss_usb_xmax = wall + lid_boss_inset + boss_r;
    boss_ant_xmin = outer_l - wall - lid_boss_inset - boss_r;
    assert(fan_slot_x[0] - fan_slot_l / 2 > boss_usb_xmax + 1.0,
           "Fan exit hits the USB-end corner boss");
    // Cleat is 10 mm long, so it reaches 5 mm past the slot centre.
    assert(i2c_ext_x + 5 < boss_ant_xmin - 0.6,
           "EXT exit or its cleat hits the antenna-end corner boss");
    assert(ear_t + 0.4 < fan_slot_z, "Ear brace rises into a cable slot");
    assert(cleat_l > fan_slot_l + 1.5, "Fan cleat does not land in the wall");
    assert(cleat_l > sensor_slot_l + 1.5, "Sensor cleat does not land in the wall");
    assert(pwr_cleat_l > pwr_slot_l + 2, "Power cleat does not land in the wall");
    echo("FIT pico case", outer_l, outer_w, base_h);
    echo("FIT usb tip x", usb_tip_x, "opening z", usb_z0);
    echo("FIT header top", header_top_z, "nest bottom", nest_bottom);
    echo("FIT oled center", oled_cx, oled_cy, "nest x0", nest_x0);
    echo("FIT exits FAN", fan_slot_x[0], fan_slot_x[1], "INT", i2c_int_x, "EXT", i2c_ext_x, "PWR", pwr_slot_x);
}

module ear_brace(x, y_out, y_in) {
    // Stays at ear height so it cannot run up into a cable slot.
    // Both boxes overlap the ear and, for y_in, the side wall.
    hull() {
        translate([x + 2, y_out, 0])
            cube([ear_l - 4, 2.8, ear_t]);
        translate([x + 3, y_in, 0])
            cube([ear_l - 6, 2.8, ear_t]);
    }
}

module ears() {
    xs = [6, outer_l - 6 - ear_l];
    for (x = xs) {
        translate([x, -ear_w, 0])
            cube([ear_l, ear_w + 0.6, ear_t]);
        translate([x, outer_w - 0.6, 0])
            cube([ear_l, ear_w + 0.6, ear_t]);
        ear_brace(x, -ear_w + 1.5, -1.4);
        ear_brace(x, outer_w + ear_w - 4.3, outer_w - 1.4);
    }
}

module ear_holes() {
    xs = [6 + ear_l * 0.5, outer_l - 6 - ear_l * 0.5];
    slot_gap = m3_clearance_d / 2 + 0.9;
    for (x = xs) {
        for (y = [-ear_w * 0.62, outer_w + ear_w * 0.62]) {
            translate([x, y, -0.4])
                cylinder(d=m3_clearance_d, h=ear_t + 1.2);
            // Zip slot sits toward the case, clear of the screw hole.
            dir = y < outer_w / 2 ? 1 : -1;
            slot_y = dir > 0
                ? y + slot_gap
                : y - slot_gap - ziptie_slot_w;
            translate([x - ziptie_slot_l / 2, slot_y, -0.4])
                cube([ziptie_slot_l, ziptie_slot_w, ear_t + 1.2]);
        }
    }
}

module usb_opening() {
    // Stadium length runs across the board (Y); depth runs through the USB wall.
    translate([wall / 2, pcb_y0 + pico_w / 2, usb_z0])
        rotate([0, 0, 90])
            stadium_x(pico_usb_opening_w, pico_usb_opening_h, wall + 1.2);
}

module antenna_window() {
    aperture = pico_antenna_keepout_w + 4.0; // 14 mm keep-out plus margin
    translate([outer_l - wall - 0.4, pcb_y0 + (pico_w - aperture) / 2, pcb_top_z - 2])
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

module wall_vents() {
    for (x = [22, 32]) {
        translate([x, wall / 2, 15.2])
            stadium_x(7, 2.4, wall + 1.2);
        translate([x, outer_w - wall / 2, 15.2])
            stadium_x(7, 2.4, wall + 1.2);
    }
    // Power-side wall only; the sensor side is occupied by INT and EXT.
    translate([44, outer_w - wall / 2, 15.2])
        stadium_x(7, 2.4, wall + 1.2);
}

module wall_labels() {
    // Anchor is inside the wall; the extrude runs out through the face
    // (see lib.scad deboss_text and the rotate below), leaving ~0.8 mm.
    translate([(fan_slot_x[0] + fan_slot_x[1]) / 2, 0.85, 11.6])
        rotate([90, 0, 0])
            mirror([1, 0, 0])
                deboss_text("FAN", 3.4, 0.8);
    translate([i2c_int_x, 0.85, 10.6])
        rotate([90, 0, 0])
            mirror([1, 0, 0])
                deboss_text("INT", 3.2, 0.8);
    translate([i2c_ext_x, 0.85, 10.6])
        rotate([90, 0, 0])
            mirror([1, 0, 0])
                deboss_text("EXT", 3.2, 0.8);
    translate([pwr_slot_x, outer_w - 0.85, 12.2])
        rotate([90, 0, 180])
            mirror([1, 0, 0])
                deboss_text("PWR", 3.4, 0.8);
}

module shell() {
    difference() {
        union() {
            rounded_rect(outer_l, outer_w, base_h, corner_r);
            ears();
        }
        translate([wall, wall, floor_t])
            cube([outer_l - 2 * wall, outer_w - 2 * wall, base_h]);
        usb_opening();
        antenna_window();
        cable_notches();
        wall_vents();
        ear_holes();
        wall_labels();
    }
}

module standoffs() {
    for (x = hole_x)
        for (y = hole_y)
            translate([x, y, 0])
                difference() {
                    cylinder(d=pico_standoff_od, h=floor_t + pico_standoff_h);
                    translate([0, 0, -0.2])
                        cylinder(d=m2_insert_hole_d, h=m2_insert_hole_depth + 0.2);
                    translate([0, 0, m2_insert_hole_depth - 0.05])
                        cylinder(d=m2_clearance_d,
                                 h=floor_t + pico_standoff_h);
                }
}

function boss_pos(i) =
    i == 0 ? [wall + lid_boss_inset, wall + lid_boss_inset] :
    i == 1 ? [wall + lid_boss_inset, outer_w - wall - lid_boss_inset] :
    i == 2 ? [outer_l - wall - lid_boss_inset, wall + lid_boss_inset] :
             [outer_l - wall - lid_boss_inset, outer_w - wall - lid_boss_inset];

module lid_bosses() {
    // From the floor (fused) up to the lid. Insert pocket is at the top.
    top = base_h - 0.15;
    translate([0, 0, 0])
        for (i = [0:3]) {
            p = boss_pos(i);
            translate([p[0], p[1], 0])
                difference() {
                    cylinder(d=lid_boss_od, h=top);
                    translate([0, 0, top - m2_insert_hole_depth])
                        cylinder(d=m2_insert_hole_d, h=m2_insert_hole_depth + 0.4);
                }
        }
}

// A bar across a notch. It has to be longer than the notch so the ends
// land in the wall; the slot is cut before the bar is added.
cleat_l = 10.0;
pwr_cleat_l = pwr_slot_l + 4.0;

module cleat(x, y, z, length) {
    translate([x - length / 2, y, z])
        cube([length, 2.2, 1.8]);
}

module cleats() {
    // y bites the wall by 0.4 mm. One cleat per exit, so the two I2C
    // cables stay on their own buses.
    cleat(fan_slot_x[0], wall - 0.4, fan_slot_z + fan_slot_h - 2.4, cleat_l);
    cleat(fan_slot_x[1], wall - 0.4, fan_slot_z + fan_slot_h - 2.4, cleat_l);
    cleat(i2c_int_x, wall - 0.4, sensor_slot_z + sensor_slot_h - 2.3, cleat_l);
    cleat(i2c_ext_x, wall - 0.4, sensor_slot_z + sensor_slot_h - 2.3, cleat_l);
    cleat(pwr_slot_x, outer_w - wall - 1.8, pwr_slot_z + pwr_slot_h - 2.6, pwr_cleat_l);
}

module base() {
    color([0.22, 0.28, 0.32])
        difference() {
            union() {
                shell();
                standoffs();
                lid_bosses();
                cleats();
            }
            // The shell floor is solid on its own; cut the insert bores
            // through it so an insert pressed in from below actually seats.
            for (x = hole_x)
                for (y = hole_y)
                    translate([x, y, -0.2])
                        cylinder(d=m2_insert_hole_d, h=m2_insert_hole_depth + 0.2);
        }
}

// ---- lid, outer face on z = 0 ------------------------------------------------

lid_outer_l = outer_l + 2 * (skirt_gap + skirt_t);
lid_outer_w = outer_w + 2 * (skirt_gap + skirt_t);

function lid_of(v, body_span, lid_span) = (lid_span - body_span) / 2 + v;

module oled_nest() {
    x0 = lid_of(oled_cx, outer_l, lid_outer_l) - oled_pocket_l / 2 - oled_nest_wall;
    y0 = lid_of(oled_cy, outer_w, lid_outer_w) - oled_pocket_w / 2 - oled_nest_wall;
    nx = oled_pocket_l + 2 * oled_nest_wall;
    ny = oled_pocket_w + 2 * oled_nest_wall;
    // Opening in the USB-side (−X) wall for the PH2.0 plug.
    gap = oled_connector_w + 2.0;
    translate([x0, y0, lid_t - 0.4]) {
        difference() {
            cube([nx, ny, oled_nest_drop + 0.4]);
            translate([oled_nest_wall, oled_nest_wall, -0.2])
                cube([oled_pocket_l, oled_pocket_w, oled_nest_drop + 1]);
            translate([-0.2, (ny - gap) / 2, -0.2])
                cube([oled_nest_wall + 0.6, gap, oled_nest_drop + 1]);
        }
        // Clips along the long inner edges, grabbing the back of the PCB.
        clip_z = oled_nest_drop - 0.9;
        for (side = [0, 1]) {
            yy = side == 0
                ? oled_nest_wall - 0.4
                : oled_nest_wall + oled_pocket_w - 0.5;
            translate([nx * 0.42, yy, clip_z])
                cube([8, 0.9, 0.9]);
            translate([nx * 0.42, side == 0 ? yy : yy + 0.5, clip_z + 0.9])
                rotate([side == 0 ? 0 : 180, 0, 0])
                    translate([0, side == 0 ? 0 : -0.9, 0])
                        hull() {
                            cube([8, 0.9, 0.02]);
                            translate([0, 0.9, 0.7])
                                cube([8, 0.02, 0.02]);
                        }
        }
    }
}

module oled_window() {
    translate([
        lid_of(oled_cx, outer_l, lid_outer_l),
        lid_of(oled_cy, outer_w, lid_outer_w),
        -0.2
    ])
        cube([oled_window_l, oled_window_w, lid_t + 0.5], center=true);
}

module bootsel_hole() {
    translate([
        lid_of(pcb_x0 + pico_bootsel_from_usb_edge, outer_l, lid_outer_l),
        lid_of(pcb_y0 + pico_w / 2 + pico_bootsel_from_center_y, outer_w, lid_outer_w),
        -0.2
    ])
        cylinder(d=pico_bootsel_hole_d, h=lid_t + 0.6);
}

module lid_screw_holes() {
    for (i = [0:3]) {
        p = boss_pos(i);
        translate([
            lid_of(p[0], outer_l, lid_outer_l),
            lid_of(p[1], outer_w, lid_outer_w),
            -0.2
        ])
            cylinder(d=m2_clearance_d, h=lid_t + 0.6);
    }
}

module lid_vents() {
    for (dx = [-22, 22])
        for (dy = [-16, 16])
            translate([lid_outer_l / 2 + dx, lid_outer_w / 2 + dy, -0.2])
                stadium_x(10, 2.6, lid_t + 0.6);
}

module lid() {
    skirt_outer_y = skirt_gap + outer_w + 2 * skirt_gap;
    color([0.16, 0.38, 0.42])
        difference() {
            union() {
                rounded_rect(lid_outer_l, lid_outer_w, lid_t, corner_r);
                translate([skirt_gap, skirt_gap, lid_t - 0.4])
                    difference() {
                        rounded_rect(outer_l + 2 * skirt_gap, outer_w + 2 * skirt_gap,
                                     skirt_h + 0.4, corner_r - 0.2);
                        translate([skirt_t, skirt_t, -0.2])
                            cube([outer_l + 2 * skirt_gap - 2 * skirt_t,
                                  outer_w + 2 * skirt_gap - 2 * skirt_t,
                                  skirt_h + 1]);
                    }
                oled_nest();
            }
            oled_window();
            bootsel_hole();
            lid_screw_holes();
            lid_vents();
            // Fingernail notch through the +Y skirt lip.
            translate([lid_of(oled_cx, outer_l, lid_outer_l),
                       skirt_outer_y - skirt_t / 2,
                       lid_t + skirt_h - 1.3])
                cube([12, skirt_t + 1.6, 2.8], center=true);
        }
}

module seated_lid() {
    translate([-(lid_outer_l - outer_l) / 2,
               -(lid_outer_w - outer_w) / 2,
               base_h + lid_t])
        rotate([180, 0, 0])
            lid();
}

module ghosts() {
    color([0.15, 0.55, 0.25, 0.45])
        translate([pcb_x0, pcb_y0, floor_t + pico_standoff_h])
            cube([pico_l, pico_w, pico_t]);
    color([0.85, 0.75, 0.15, 0.5])
        translate([oled_cx - oled_pcb_l / 2, oled_cy - oled_pcb_w / 2,
                   base_h - oled_stack_h])
            cube([oled_pcb_l, oled_pcb_w, oled_stack_h]);
}

fit_checks();

if (part == "base")
    base();
else if (part == "lid")
    lid();
else if (part == "assembly") {
    base();
    ghosts();
    seated_lid();
} else if (part == "section") {
    difference() {
        union() {
            base();
            seated_lid();
        }
        translate([-10, outer_w / 2, -5])
            cube([120, 80, 80]);
    }
    ghosts();
} else
    assert(false, "part must be base, lid, assembly, or section");
