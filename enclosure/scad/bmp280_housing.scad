// BMP280 sensor housing. One model, two variants:
//   variant = "INT"  indoor, open lid vents, slotted walls
//   variant = "EXT"  outdoor radiation shield: sloped louvers, awning, solid lid
//   part    = "body" | "lid" | "assembly" | "section"
//
// Print orientation is the modeled orientation for the body (bottom on the
// bed). The lid is modeled outer-face down, which is also its print
// orientation. Assembly / section previews seat the lid on the body.
//
// The module is cradled on a slotted platform held off the shell by thin
// legs, so the sensor is not thermally shorted to the mount and a side
// draught has to turn past a baffle before it reaches the chip.
//
// Cable is four conductors only (VCC, GND, SCL, SDA). Both modules stay at
// the hardwired address 0x76, so SDO and CSB are not brought out. The Pico
// case has a separate exit for each cable:
//   INT shares I2C0 with the OLED — GP4 SDA, GP5 SCL
//   EXT is alone on I2C1         — GP6 SDA, GP7 SCL

use <lib.scad>
include <dimensions.scad>

variant = "INT"; // INT or EXT
part = "body";   // body | lid | assembly | section

ext = variant == "EXT";
label = ext ? "EXT" : "INT";

// INT louvers: horizontal slots. Kept below the lid skirt.
lv_h = 1.8;
lv_len = 12.0;
lv_z = [5.2, 8.15];

// EXT louvers: outer opening is lower than the inner one by ext_slope,
// a 45° rise across the wall. Rain runs down the slope and back outside.
ext_slot_h = 1.8;
ext_slot_z = [4.0, 7.4];
ext_slope = wall + 1.0;

tab_t = 3.0;
tab_w = 14.0;
tab_l = 16.0;
tab_gusset_rise = 5.2;

// 4-wire cable only (VCC, GND, SCL, SDA).
cable_w = 8.5;
cable_h = 4.4;
cable_z0 = 3.8;
cable_awning_root = 3.3;
cable_awning_proj = 2.0;
cable_awning_tip = 0.6;

boss_od = 6.6;
boss_r = boss_od / 2;
// Centre sits boss_r − bite in from the inner face, so the boss bites the wall.
boss_bite = 0.55;
boss_from_inner = boss_r - boss_bite;

corner_r = 2.4;
eave = ext ? 1.6 : 0.3;
rail_t = 1.2;
plate_lip = 0.15; // plate extends past the rails so those faces are not coplanar

// Back-corner insert bosses (the two corners opposite the cable wall).
function boss_xy(i) =
    i == 0 ? [wall + boss_from_inner, bmp_outer_w - wall - boss_from_inner]
           : [bmp_outer_l - wall - boss_from_inner, bmp_outer_w - wall - boss_from_inner];

function ext_inner_top() = ext_slot_z[len(ext_slot_z) - 1] + ext_slope + ext_slot_h;
function int_slot_top() = lv_z[len(lv_z) - 1] + lv_h;
function baffle_top_z() = max(ext_inner_top(), int_slot_top()) + 0.8;
function pcb_top_z() = floor_t + bmp_platform_h + bmp_pcb_t;

module fit_checks() {
    skirt_z0 = bmp_body_h - skirt_h;
    for (z0 = lv_z) {
        assert(z0 > floor_t + 1.0, "Louver breaks out of the floor");
        assert(z0 + lv_h < skirt_z0 - 0.8, "INT louver meets the lid skirt");
    }
    for (z0 = ext_slot_z) {
        assert(z0 > tab_t + 0.4, "EXT louver meets the mounting tab");
        assert(z0 + ext_slope + ext_slot_h < bmp_body_h - 1.2,
               "EXT louver breaks out of the top of the wall");
    }
    // Neighbouring EXT ducts stay apart. Both faces shift by the same slope.
    assert(ext_slot_z[1] > ext_slot_z[0] + ext_slot_h + 1.0,
           "EXT louvers run into each other");
    // 45° awning: tip underside is proj+0.35 above the root (see rain_hood).
    assert(cable_awning_root > cable_awning_proj + 0.35 + cable_awning_tip + 0.15,
           "Cable awning top does not shed toward the tip");
    assert(cable_z0 + cable_h + cable_awning_root < skirt_z0 - 0.25,
           "Cable awning meets the lid skirt");
    assert(cable_z0 > floor_t + 0.8, "Cable exit breaks the floor");
    // Boss circle must miss the platform corner (the plate lips past the
    // rails) and the PCB.
    plate_from_inner = bmp_air - fit_clearance - rail_t - plate_lip;
    dx = plate_from_inner - boss_from_inner;
    assert(dx * sqrt(2) > boss_r + 0.45, "Platform hits an insert boss");
    pcb_dx = bmp_air - boss_from_inner;
    assert(pcb_dx * sqrt(2) > boss_r + 1.0, "Insert boss overlaps the BMP280 module");
    assert(boss_od >= m2_insert_od + 2.6, "Boss wall around the M2 insert is thin");
    assert(boss_bite >= 0.4, "Insert boss does not bite the wall");
    assert(baffle_top_z() > ext_inner_top() - 0.05, "Baffle does not cover the EXT louvers");
    assert(baffle_top_z() > int_slot_top() - 0.05, "Baffle does not cover the INT louvers");
    for (xc = cable_louver_x()) {
        half = (ext ? 8.0 : cable_lv_len) / 2;
        assert(xc + half < bmp_outer_l / 2 - cable_w / 2 - 1.2
            || xc - half > bmp_outer_l / 2 + cable_w / 2 + 1.2,
            "Cable-wall louver overlaps the cable exit");
    }
    if (!ext) {
        end_slot_z = tab_t + tab_gusset_rise + 0.7;
        assert(end_slot_z > tab_t + tab_gusset_rise + 0.3, "End slot cuts the tab gusset");
        assert(end_slot_z + lv_h < skirt_z0 - 0.4, "End slot meets the lid skirt");
    }
    echo("FIT bmp variant", variant, "outer", bmp_outer_l, bmp_outer_w, bmp_body_h);
    echo("FIT bmp platform_z", floor_t + bmp_platform_h, "pcb_top", pcb_top_z());
    echo("FIT bmp baffle_top", baffle_top_z(), "ext inner top", ext_inner_top());
}

function far_louver_x() = [bmp_outer_l * 0.32, bmp_outer_l * 0.68];
function cable_louver_x() = [bmp_outer_l * 0.20, bmp_outer_l * 0.80];
cable_lv_len = 8.0;

module shell() {
    difference() {
        union() {
            rounded_rect(bmp_outer_l, bmp_outer_w, bmp_body_h, corner_r);
            tabs();
            if (ext) cable_awning();
        }
        translate([wall, wall, floor_t])
            cube([bmp_chamber_l, bmp_chamber_w, bmp_body_h]);
        if (ext)
            ext_louvers();
        else
            int_louvers();
        cable_slot();
        tab_holes();
    }
}

module tabs() {
    y0 = (bmp_outer_w - tab_w) / 2;
    run = tab_l * 0.55;
    translate([-tab_l, y0, 0])
        cube([tab_l + 0.5, tab_w, tab_t]);
    translate([0, y0 + tab_w, tab_t])
        rotate([90, 0, 0])
            linear_extrude(height=tab_w)
                polygon([[0.6, -0.6], [-run, -0.6], [0.6, tab_gusset_rise]]);
    translate([bmp_outer_l - 0.5, y0, 0])
        cube([tab_l + 0.5, tab_w, tab_t]);
    translate([bmp_outer_l, y0 + tab_w, tab_t])
        rotate([90, 0, 0])
            linear_extrude(height=tab_w)
                polygon([[-0.6, -0.6], [run, -0.6], [-0.6, tab_gusset_rise]]);
}

module tab_holes() {
    for (side = [-1, 1]) {
        cx = side < 0 ? -tab_l * 0.46 : bmp_outer_l + tab_l * 0.46;
        translate([cx, bmp_outer_w / 2 - 2.4, -0.2])
            cylinder(d=m3_clearance_d, h=tab_t + 0.6);
        translate([cx - ziptie_slot_l / 2, bmp_outer_w / 2 + 1.6, -0.2])
            cube([ziptie_slot_l, ziptie_slot_w, tab_t + 0.6]);
    }
}

// Sloped duct. Outer opening at z_outer, inner opening higher by `drop`.
module sloped_y(length, height, y_outer, y_inner, z_outer, drop) {
    hull() {
        translate([0, y_outer, z_outer])
            stadium_x(length, height, 0.24);
        translate([0, y_inner, z_outer + drop])
            stadium_x(length, height, 0.24);
    }
}

module ext_louvers() {
    // y_out is just outside the outer face; the rise equals the run (45°).
    y_out = -0.4;
    y_in = y_out + ext_slope;
    for (z0 = ext_slot_z) {
        for (xc = far_louver_x())
            translate([xc, bmp_outer_w, 0])
                sloped_y(lv_len, ext_slot_h, -y_out, -y_in, z0, ext_slope);
        for (xc = cable_louver_x())
            translate([xc, 0, 0])
                sloped_y(cable_lv_len, ext_slot_h, y_out, y_in, z0, ext_slope);
    }
}

module int_louvers() {
    for (z0 = lv_z) {
        for (xc = far_louver_x())
            translate([xc, bmp_outer_w, z0])
                stadium_x(lv_len, lv_h, wall + 1.2);
        for (xc = cable_louver_x())
            translate([xc, 0, z0])
                stadium_x(cable_lv_len, lv_h, wall + 1.2);
    }
    z0 = tab_t + tab_gusset_rise + 0.7;
    for (side = [0, 1])
        translate([side * bmp_outer_l, bmp_outer_w / 2, z0])
            rotate([0, 0, 90])
                stadium_x(10, lv_h, wall + 1.2);
}

module cable_awning() {
    // Sunk 0.45 mm into the cable wall, then sloping out and up.
    translate([bmp_outer_l / 2, 0.45, cable_z0 + cable_h])
        rotate([0, 0, 180])
            rain_hood(cable_w + 2.4, cable_awning_proj, cable_awning_root, cable_awning_tip);
}

module cable_slot() {
    translate([bmp_outer_l / 2, 0, cable_z0])
        stadium_x(cable_w, cable_h, wall + 1.2);
}

module platform() {
    x0 = wall + bmp_air - fit_clearance - rail_t;
    y0 = wall + bmp_air - fit_clearance - rail_t;
    pw = bmp_pocket_l + 2 * rail_t;
    pd = bmp_pocket_w + 2 * rail_t;
    leg = 2.0;
    // Legs sink 0.4 mm into the floor and 0.4 mm into the plate, and they
    // sit inboard of the plate edge so the two solids are not coplanar.
    translate([x0 - plate_lip, y0 - plate_lip, floor_t - 0.4]) {
        inset = 0.35;
        span_x = pw + 2 * plate_lip;
        span_y = pd + 2 * plate_lip;
        for (px = [inset, span_x - leg - inset])
            for (py = [inset, span_y - leg - inset])
                translate([px, py, 0])
                    cube([leg, leg, 0.4 + bmp_platform_h + 0.4]);
        translate([0, 0, 0.4 + bmp_platform_h])
            difference() {
                cube([span_x, span_y, 1.4]);
                translate([4.0 + plate_lip, 3.6 + plate_lip, -0.2])
                    cube([pw - 8.0, pd - 7.2, 2.0]);
            }
    }
}

module rails_and_baffle() {
    x0 = wall + bmp_air - fit_clearance;
    y0 = wall + bmp_air - fit_clearance;
    rail_h = 1.15;
    rail_drop = 0.4;
    pin_gap = bmp_pin_count * bmp_pin_pitch + 1.2;
    translate([x0, y0, floor_t + bmp_platform_h - rail_drop]) {
        translate([-rail_t, bmp_pocket_w, 0])
            cube([bmp_pocket_l + 2 * rail_t, rail_t, rail_h + rail_drop]);
        gap0 = (bmp_pocket_l - pin_gap) / 2;
        translate([-rail_t, -rail_t, 0])
            cube([gap0 + rail_t, rail_t, rail_h + rail_drop]);
        translate([gap0 + pin_gap, -rail_t, 0])
            cube([gap0 + rail_t, rail_t, rail_h + rail_drop]);
        translate([-rail_t, 0, 0])
            cube([rail_t, bmp_pocket_w, rail_h + rail_drop]);
        translate([bmp_pocket_l, 0, 0])
            cube([rail_t, bmp_pocket_w, rail_h + rail_drop]);
    }
    ox0 = x0 - rail_t;
    oy0 = y0 - rail_t;
    ol = bmp_pocket_l + 2 * rail_t;
    ow = bmp_pocket_w + 2 * rail_t;
    bt = 1.3;
    bite = 0.45;
    bz = floor_t + bmp_platform_h - 0.2;
    bh = baffle_top_z() - bz;
    corner_gap = 6.5;
    translate([ox0 + corner_gap, oy0 - bt + bite, bz])
        cube([ol - 2 * corner_gap, bt, bh]);
    translate([ox0 + corner_gap, oy0 + ow - bite, bz])
        cube([ol - 2 * corner_gap, bt, bh]);
    translate([ox0 - bt + bite, oy0 + corner_gap, bz])
        cube([bt, ow - 2 * corner_gap, bh]);
    translate([ox0 + ol - bite, oy0 + corner_gap, bz])
        cube([bt, ow - 2 * corner_gap, bh]);
}

module strain_cleat() {
    // Posts are inset from the bar so the joint is a stab, not a coplanar face.
    span = cable_w - 1.0;
    x0 = bmp_outer_l / 2 - span / 2;
    y0 = wall + 1.4;
    bar_z = cable_z0 + cable_h - 1.6;
    post = 1.3;
    translate([x0 + 0.25, y0 + 0.35, floor_t - 0.4]) {
        h = (bar_z + 0.5) - (floor_t - 0.4);
        cube([post, 1.5, h]);
        translate([span - post - 0.5, 0, 0])
            cube([post, 1.5, h]);
    }
    translate([x0, y0, bar_z])
        cube([span, 2.2, 1.6]);
}

module insert_bosses() {
    top = bmp_body_h - 0.15;
    for (i = [0, 1]) {
        p = boss_xy(i);
        translate([p[0], p[1], floor_t - 0.4])
            difference() {
                cylinder(d=boss_od, h=top - (floor_t - 0.4));
                translate([0, 0, top - (floor_t - 0.4) - m2_insert_hole_depth])
                    cylinder(d=m2_insert_hole_d, h=m2_insert_hole_depth + 0.4);
            }
    }
}

module snap_ridges() {
    z = bmp_body_h - 1.05 - snap_ridge_h;
    bite = 0.4;
    translate([bite, bmp_outer_w / 2, z])
        rotate([0, 0, 90])
            snap_ridge(snap_len, snap_protrusion + bite, snap_catch_h);
    translate([bmp_outer_l - bite, bmp_outer_w / 2, z])
        rotate([0, 0, -90])
            snap_ridge(snap_len, snap_protrusion + bite, snap_catch_h);
    translate([bmp_outer_l / 2, bite, z])
        rotate([0, 0, 180])
            snap_ridge(snap_len, snap_protrusion + bite, snap_catch_h);
    translate([bmp_outer_l / 2, bmp_outer_w - bite, z])
        snap_ridge(snap_len, snap_protrusion + bite, snap_catch_h);
}

module body() {
    color(ext ? [0.94, 0.93, 0.88] : [0.45, 0.62, 0.70])
        union() {
            shell();
            platform();
            rails_and_baffle();
            strain_cleat();
            insert_bosses();
            snap_ridges();
        }
}

// Lid is modeled outer-face down (z = 0 on the bed).
lid_outer_l = bmp_outer_l + 2 * (skirt_gap + skirt_t) + 2 * eave;
lid_outer_w = bmp_outer_w + 2 * (skirt_gap + skirt_t) + 2 * eave;
lid_skirt_l = bmp_outer_l + 2 * (skirt_gap + skirt_t);
lid_skirt_w = bmp_outer_w + 2 * (skirt_gap + skirt_t);

function lid_of(body_coord, body_span, lid_span) =
    (lid_span - body_span) / 2 + body_coord;

module lid_snap_windows() {
    catch_z0 = bmp_body_h - 1.05 - snap_ridge_h;
    catch_z1 = catch_z0 + snap_catch_h;
    z0 = bmp_body_h + lid_t - (catch_z1 + 0.25);
    z1 = bmp_body_h + lid_t - (catch_z0 - 0.25);
    win_h = z1 - z0;
    win_l = snap_len + 0.8;
    for (side = [0, 1]) {
        x = lid_of(side == 0 ? 0 : bmp_outer_l, bmp_outer_l, lid_outer_l);
        translate([x, lid_outer_w / 2, z0 + win_h / 2])
            cube([skirt_t + eave + 1.4, win_l, win_h], center=true);
    }
    for (side = [0, 1]) {
        y = lid_of(side == 0 ? 0 : bmp_outer_w, bmp_outer_w, lid_outer_w);
        translate([lid_outer_l / 2, y, z0 + win_h / 2])
            cube([win_l, skirt_t + eave + 1.4, win_h], center=true);
    }
}

module lid_screw_holes() {
    for (i = [0, 1]) {
        p = boss_xy(i);
        translate([
            lid_of(p[0], bmp_outer_l, lid_outer_l),
            lid_of(p[1], bmp_outer_w, lid_outer_w),
            -0.2
        ])
            cylinder(d=m2_clearance_d, h=lid_t + 0.6);
    }
}

module hold_down_posts() {
    post_len = bmp_header_above_pcb + bmp_above_header - 0.40;
    inset = 3.2;
    xs = [
        wall + bmp_air + inset,
        wall + bmp_air + bmp_pcb_l - inset
    ];
    y = wall + bmp_air + bmp_pcb_w - inset;
    for (x = xs)
        translate([
            lid_of(x, bmp_outer_l, lid_outer_l),
            lid_of(y, bmp_outer_w, lid_outer_w),
            lid_t - 0.4
        ])
            cylinder(d=3.2, h=post_len + 0.4);
}

module lid_vents() {
    if (!ext) {
        for (dx = [-10, 10])
            translate([lid_outer_l / 2 + dx, lid_outer_w / 2, -0.2])
                stadium_x(11, 2.2, lid_t + 0.6);
    }
}

module lid() {
    color(ext ? [0.97, 0.97, 0.94] : [0.30, 0.45, 0.52])
        difference() {
            union() {
                rounded_rect(lid_outer_l, lid_outer_w, lid_t, corner_r + eave);
                translate([(lid_outer_l - lid_skirt_l) / 2,
                           (lid_outer_w - lid_skirt_w) / 2,
                           lid_t - 0.4])
                    difference() {
                        rounded_rect(lid_skirt_l, lid_skirt_w, skirt_h + 0.4, corner_r);
                        translate([skirt_t, skirt_t, -0.2])
                            cube([lid_skirt_l - 2 * skirt_t,
                                  lid_skirt_w - 2 * skirt_t,
                                  skirt_h + 0.8]);
                    }
                hold_down_posts();
            }
            lid_snap_windows();
            lid_screw_holes();
            lid_vents();
            translate([lid_outer_l / 2, lid_outer_w / 2, -0.2])
                deboss_text(label, 7.0, 0.65);
            translate([lid_outer_l / 2, eave + skirt_t / 2, lid_t + skirt_h - 1.2])
                cube([12, skirt_t + eave + 1.2, 2.6], center=true);
        }
}

module seated_lid() {
    translate([-(lid_outer_l - bmp_outer_l) / 2,
               -(lid_outer_w - bmp_outer_w) / 2,
               bmp_body_h + lid_t])
        rotate([180, 0, 0])
            lid();
}

module ghost_module() {
    color([0.75, 0.15, 0.12, 0.55])
        translate([wall + bmp_air, wall + bmp_air, floor_t + bmp_platform_h])
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
        translate([-40, bmp_outer_w / 2, -5])
            cube([200, 80, 80]);
    }
    ghost_module();
} else {
    assert(false, "part must be body, lid, assembly, or section");
}
