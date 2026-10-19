// BMP280 housing, printed twice. One compact indoor body for both.
//   variant = "INT" or "EXT"   only the lid label changes
//   part    = "body" | "lid" | "assembly" | "section"
//
// No tabs, no rain awning, no drip loop, no radiation-shield louvers.
// Both lids are vented the same way. Slide rails match the Pico case
// so mount.scad can grip either housing. The base is flat without the
// mount; each rail has a zip-tie slot.

use <lib.scad>
include <dimensions.scad>

variant = "INT";
part = "body";

ext = variant == "EXT";
label = ext ? "EXT" : "INT";

corner_r = 2.0;
cable_w = 7.0;
cable_h = 3.4;
cable_z0 = rail_h + 1.2;

module fit_checks() {
    assert(variant == "INT" || variant == "EXT", "variant must be INT or EXT");
    assert(abs(bmp_outer_l - 28.6) < 1e-6, "BMP280 length drifted");
    assert(abs(bmp_outer_w - 25.6) < 1e-6, "BMP280 width drifted");
    assert(abs(bmp_body_h - 14.5) < 1e-6, "BMP280 height drifted");
    assert(cable_z0 > rail_h + 0.6, "Cable slot cuts the slide rail");
    assert(cable_z0 + cable_h < bmp_body_h - skirt_h - 0.4,
           "Cable slot meets the lid skirt");
    assert(cable_w >= 6.0 && cable_h >= 3.2, "Cable exit is tight for four wires");
    echo("FIT bmp", variant, bmp_outer_l, bmp_outer_w, bmp_body_h);
}

module cable_slot() {
    translate([bmp_outer_l / 2, 0, cable_z0])
        stadium_x(cable_w, cable_h, wall + 1.2);
}

module shell() {
    difference() {
        union() {
            rounded_rect(bmp_outer_l, bmp_outer_w, bmp_body_h, corner_r);
            slide_rails(bmp_outer_l, bmp_outer_w, rail_t, rail_h, rail_end_gap,
                        ziptie_slot_l, ziptie_slot_w, rail_detent);
        }
        translate([wall, wall, floor_t])
            cube([bmp_chamber_l, bmp_chamber_w, bmp_body_h]);
        cable_slot();
    }
}

module platform() {
    // Four short legs and a 0.8 mm lip so the module cannot slide into
    // the cable slot. The sensor sits on the legs, chip up.
    x0 = wall + bmp_air;
    y0 = wall + bmp_air;
    leg = 2.4;
    inset = 0.8;
    for (px = [inset, bmp_pocket_l - leg - inset])
        for (py = [inset, bmp_pocket_w - leg - inset])
            translate([x0 + px, y0 + py, floor_t - 0.3])
                cube([leg, leg, bmp_platform_h + 0.3]);
    translate([x0 - 0.4, y0 + bmp_pocket_w - 1.0, floor_t + bmp_platform_h - 0.3])
        cube([bmp_pocket_l + 0.8, 1.4, 1.6]);
}

module strain_cleat() {
    span = cable_w - 0.8;
    x0 = bmp_outer_l / 2 - span / 2;
    y0 = wall + 0.8;
    bar_z = cable_z0 + cable_h - 1.5;
    post = 1.2;
    translate([x0 + 0.2, y0, floor_t - 0.3]) {
        h = (bar_z + 0.4) - (floor_t - 0.3);
        cube([post, 1.4, h]);
        translate([span - post - 0.4, 0, 0])
            cube([post, 1.4, h]);
    }
    translate([x0, y0, bar_z])
        cube([span, 1.8, 1.3]);
}

module snaps() {
    z = bmp_body_h - 0.85 - snap_ridge_h;
    bite = 0.35;
    translate([bmp_outer_l / 2, bite, z])
        rotate([0, 0, 180])
            snap_ridge(snap_len, snap_protrusion + bite, snap_catch_h);
    translate([bmp_outer_l / 2, bmp_outer_w - bite, z])
        snap_ridge(snap_len, snap_protrusion + bite, snap_catch_h);
}

module body() {
    color(ext ? [0.55, 0.58, 0.52] : [0.45, 0.62, 0.70])
        union() {
            shell();
            platform();
            strain_cleat();
            snaps();
        }
}

lid_outer_l = bmp_outer_l + 2 * (skirt_gap + skirt_t);
lid_outer_w = bmp_outer_w + 2 * (skirt_gap + skirt_t);

function lid_of(body_coord, body_span, lid_span) =
    (lid_span - body_span) / 2 + body_coord;

module lid_snap_windows() {
    catch_z0 = bmp_body_h - 0.85 - snap_ridge_h;
    catch_z1 = catch_z0 + snap_catch_h;
    z0 = bmp_body_h + lid_t - (catch_z1 + 0.2);
    z1 = bmp_body_h + lid_t - (catch_z0 - 0.2);
    win_h = z1 - z0;
    win_l = snap_len + 0.8;
    for (side = [0, 1]) {
        y = lid_of(side == 0 ? 0 : bmp_outer_w, bmp_outer_w, lid_outer_w);
        translate([lid_outer_l / 2, y, z0 + win_h / 2])
            cube([win_l, skirt_t + 1.4, win_h], center=true);
    }
}

module lid_vents() {
    for (dx = [-7.2, 7.2])
        translate([lid_outer_l / 2 + dx, lid_outer_w / 2, -0.2])
            stadium_x(6.0, 2.0, lid_t + 0.6);
}

module lid() {
    color(ext ? [0.62, 0.66, 0.58] : [0.30, 0.45, 0.52])
        difference() {
            union() {
                rounded_rect(lid_outer_l, lid_outer_w, lid_t, corner_r);
                translate([0, 0, lid_t - 0.2])
                    difference() {
                        rounded_rect(lid_outer_l, lid_outer_w, skirt_h + 0.2, corner_r);
                        translate([skirt_t, skirt_t, -0.2])
                            cube([lid_outer_l - 2 * skirt_t,
                                  lid_outer_w - 2 * skirt_t,
                                  skirt_h + 0.8]);
                    }
            }
            lid_snap_windows();
            lid_vents();
            translate([lid_outer_l / 2, lid_outer_w / 2, -0.15])
                deboss_text(label, 5.0, 0.45);
            translate([lid_outer_l / 2, lid_outer_w - skirt_t / 2,
                       lid_t + skirt_h - 1.05])
                cube([9, skirt_t + 1.6, 2.2], center=true);
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
        translate([-20, bmp_outer_w / 2, -5])
            cube([80, 60, 50]);
    }
    ghost_module();
} else
    assert(false, "part must be body, lid, assembly, or section");
