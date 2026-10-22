// Parametric dimensions for the Pico W fan-controller enclosures.
// Every source dimension is named below. Derived fits add `fit_clearance`
// (a few tenths of a millimetre) per side. `assert`s at the bottom fail
// the OpenSCAD run if a pocket, window, or stack-up stops fitting.
//
// Override any of these from the CLI, for example:
//   openscad -D 'fit_clearance=0.40' -D 'variant="EXT"' ...

quality = 48;
$fn = quality;

// --------------------------------------------------------------------------
// Clearance, walls, nozzle
// --------------------------------------------------------------------------

// Extra room around every module edge, per side.
fit_clearance = 0.30;

// Nominal wall. 1.6 mm is four 0.4 mm perimeters. Floor and lid are
// 1.2 mm, three perimeters. Indoor only: no extra thickness for sun or rain.
wall = 1.6;
floor_t = 1.2;
lid_t = 1.2;
nozzle = 0.40;

// How far the lid skirt passes down over the body, and the radial gap
// between the body outside and the skirt inside (per side).
skirt_h = 3.2;
skirt_t = 1.2;
skirt_gap = 0.30;

// Cantilever latch. The skirt only locates the lid. The finger is the
// spring: 1.0 mm thick, long enough to flex, 45° lead-in, and 0.20 mm
// of interference once it sits in the recess.
latch_t = 1.0;
latch_w = 5.5;
latch_gap = 0.20;
latch_reach = 0.75;
latch_interference = 0.20;
latch_catch = 0.60;
latch_kerf = 1.2;
latch_recess_d = latch_reach - latch_interference;
latch_lead = latch_reach + latch_gap;
latch_recess_h = latch_catch + latch_lead + 0.40;
bmp_latch_z = 3.4;
pico_latch_z = 6.2;

// --------------------------------------------------------------------------
// Raspberry Pi Pico W
// Official: Raspberry Pi Pico W datasheet, section 2, "Mechanical
// specification" (datasheets.raspberrypi.com/picow/pico-w-datasheet.pdf).
//   "single sided 51 mm × 21 mm × 1 mm PCB"
//   "four 2.1 mm (± 0.05 mm) drilled mounting holes"
//   "40 main user pins on a 2.54 mm (0.1") pitch grid with 1 mm holes"
//   "micro USB port overhanging the top edge"
//   antenna keep-out "14 mm × 9 mm" (section 2.2.1)
// Figure 3 callouts used here: USB overhang 1.3 mm (typ); mounting-hole
// pattern 47.0 mm × 11.4 mm. Edge insets follow from the outline:
//   (51 − 47) / 2 = 2.0 mm from each short edge
//   (21 − 11.4) / 2 = 4.8 mm from each long edge
// --------------------------------------------------------------------------

pico_l = 51.0;
pico_w = 21.0;
pico_t = 1.0;
pico_hole_d = 2.1;
pico_hole_dx = 47.0;
pico_hole_dy = 11.4;
pico_pin_pitch = 2.54;
pico_pin_hole_d = 1.0;
pico_row_spacing = 7 * pico_pin_pitch; // 17.78 mm between pin-row centres
pico_usb_overhang = 1.3;
pico_antenna_keepout_l = 9.0;  // depth into the board from the antenna edge
pico_antenna_keepout_w = 14.0;

// Header and connector envelopes are not dimensioned as a table in the
// datasheet; they are named so a different header or a bare board is a
// one-line change. 8.5 mm is a standard 0.1" male header standing above
// the PCB (about 11.5 mm pin, ~3 mm through the 1 mm board).
pico_header_above_pcb = 8.5;
pico_header_plastic_w = 2.54;
// Micro-USB receptacle envelope. The wall opening is this plus clearance.
// The plug overmold stays outside the case because the connector face sits
// in the wall (see usb_tip_x below).
pico_usb_shell_w = 8.0;
pico_usb_shell_h = 3.8;
pico_usb_shell_depth = 6.0; // how far the shell reaches onto the PCB

// Air around the board. The long-side gutters only have to let a Dupont
// lead turn out through the wall slot; the housing itself sits on the
// header, over the PCB. The antenna keep-out is on the PCB. The end wall
// is open across it, so the gap past the board edge stays small.
pico_gutter = 4.0;
pico_antenna_gap = 2.5;
// Plastic left above the header pins before the lid inner face.
pico_above_header = 1.8;
pico_standoff_h = 3.0;     // clears solder tails and the USB solder pools
pico_standoff_od = 6.0;    // 3.5 mm insert plus 1.25 mm of plastic per side

// BOOTSEL is on the top, just inboard of the USB connector. The datasheet
// drawing does not call out the button centre, so the hole is oversized
// and these two offsets are the adjustment knobs.
pico_bootsel_from_usb_edge = 7.5;
pico_bootsel_from_center_y = 0.0;
pico_bootsel_hole_d = 7.0;

// --------------------------------------------------------------------------
// Waveshare 0.91" OLED (SSD1306, 128×32, I2C, PH2.0)
// Wiki (attached) and the product selection table:
//   module 36.0 × 12.5 mm
//   active area 22.38 × 5.58 mm
//   four pins VCC, GND, SDA, SCL on a PH2.0 connector
// Glass thickness is not published by Waveshare. 1.45 mm is the outline
// thickness of the 0.91" 128×32 panel family with this same active area
// (EastRising ER-OLED0.91-1). PCB thickness is not published either;
// 1.2 mm is the value to remeasure on the actual module.
// --------------------------------------------------------------------------

oled_pcb_l = 36.0;
oled_pcb_w = 12.5;
oled_pcb_t = 1.20;
oled_glass_t = 1.45;
oled_active_l = 22.38;
oled_active_w = 5.58;
oled_window_extra = 0.40; // total, added to the active area (0.20 per side)
// JST PH 4-circuit shroud, typical, so the nest can leave room for it.
// Not a Waveshare callout; measure and override if your connector differs.
oled_connector_w = 10.5;
oled_connector_h = 6.5;
oled_nest_wall = 0.6;
// Active-area centre relative to the module centre. The Waveshare 0.91"
// glass sits in the middle of the 36 × 12.5 mm board; nudge these if a
// remeasure shows the pixels are shifted toward the PH2.0 end.
oled_active_dx = 0.0;
oled_active_dy = 0.0;

// --------------------------------------------------------------------------
// BMP280 module. The common purple GY-BMP280-3.3, not the 21 × 18 mm
// HandsOn board. Sellers list it as 15 × 11.5 mm. Six pins on the long
// edge: VCC, GND, SCL, SDA, CSB, SDO. Tie CSB to 3V3 and SDO to GND
// with a wire (6-wire cable, or jumpers on the module).
// Two mounting holes. Centres are not on a published drawing, so they
// are named: 2.5 mm from each short edge, 2.4 mm from the edge opposite
// the header. Override the insets if you measure something else.
// Firmware buses:
//   INTERNAL BMP280 shares I2C0 with the OLED — GP4 SDA, GP5 SCL
//   EXTERNAL BMP280 is alone on I2C1       — GP6 SDA, GP7 SCL
// --------------------------------------------------------------------------

bmp_pcb_l = 15.0;
bmp_pcb_w = 11.5;
bmp_pcb_t = 1.6;
bmp_pin_count = 6;
bmp_pin_pitch = 2.54;
bmp_header_above_pcb = 8.5;
// 0.45 mm from the side walls and the back wall. The header edge has a
// bay so a 1×6 Dupont plug or soldered wires can leave that edge.
bmp_air = 0.45;
bmp_header_bay = 3.2;
bmp_hole_d = 2.2;
bmp_hole_inset_x = 2.5;
bmp_hole_inset_back = 2.4;
bmp_platform_h = 1.6;
bmp_above_header = 0.8;

// --------------------------------------------------------------------------
// Fasteners
// --------------------------------------------------------------------------

// Brass M2 heat-set insert, 3.5 mm OD × 3 mm long (Ruthex-style short).
// The printed hole is slightly under the insert OD.
m2_insert_od = 3.5;
m2_insert_len = 3.0;
m2_insert_hole_d = 3.2;
m2_insert_hole_depth = 3.6;
m2_clearance_d = 2.4;     // screw shank through plastic / standoff bore
m2_head_d = 4.0;          // pan-head envelope, for the lid hole note

// Case and sensor mounting (into a panel, not into the Pico).
// The bodies themselves are flat. A separate bracket slides onto these
// rails. The same section is used on the Pico case and both sensor bodies.
m3_clearance_d = 3.4;
ziptie_slot_l = 5.0;
ziptie_slot_w = 1.8;
rail_t = 1.4;
rail_h = 3.2;
rail_end_gap = 3.0;
rail_clearance = 0.30;
rail_detent = 0.40;

// --------------------------------------------------------------------------
// Derived fits
// --------------------------------------------------------------------------

pico_hole_inset_x = (pico_l - pico_hole_dx) / 2;
pico_hole_inset_y = (pico_w - pico_hole_dy) / 2;

// USB tip is recessed inside the USB end wall (see pico_case.scad). The
// wall opening is larger than the shell so the plug nose can enter.
pico_usb_opening_w = pico_usb_shell_w + 3.0;
pico_usb_opening_h = pico_usb_shell_h + 2.2;

oled_stack_h = oled_pcb_t + oled_glass_t;
oled_window_l = oled_active_l + oled_window_extra;
oled_window_w = oled_active_w + oled_window_extra;
oled_pocket_l = oled_pcb_l + 2 * fit_clearance;
oled_pocket_w = oled_pcb_w + 2 * fit_clearance;
oled_nest_drop = oled_stack_h + 0.8; // walls + clip reach
oled_nest_outer_w = oled_pocket_w + 2 * oled_nest_wall;

// Gap between the inner faces of the two header plastics.
pico_header_inner_gap = pico_row_spacing - pico_header_plastic_w;

bmp_pocket_l = bmp_pcb_l + 2 * bmp_air;
bmp_pocket_w = bmp_pcb_w + 2 * bmp_air;
bmp_chamber_l = bmp_pcb_l + 2 * bmp_air;
bmp_chamber_w = bmp_header_bay + bmp_pcb_w + bmp_air;
bmp_outer_l = bmp_chamber_l + 2 * wall;
bmp_outer_w = bmp_chamber_w + 2 * wall;
bmp_inner_h = bmp_platform_h + bmp_pcb_t + bmp_header_above_pcb + bmp_above_header;
bmp_body_h = floor_t + bmp_inner_h;
// Board origin inside the body. Header bay is on Y = 0, the cable face.
bmp_board_x = wall + bmp_air;
bmp_board_y = wall + bmp_header_bay;

bmp_latch_arm = bmp_body_h - (bmp_latch_z + latch_recess_h) + 0.10;
pico_outer_l = wall + pico_l + pico_antenna_gap + wall;
pico_outer_w = wall + pico_gutter + pico_w + pico_gutter + wall;
pico_base_h = floor_t + pico_standoff_h + pico_t + pico_header_above_pcb + pico_above_header;
pico_latch_arm = pico_base_h - (pico_latch_z + latch_recess_h) + 0.10;
// Centres on the long walls. The cable wall misses FAN and EXT. The far
// wall misses PWR. Both rows sit above the bracket jaw.
pico_latch_front_a = 5.2;
pico_latch_front_b = 49.0;
pico_latch_back_a = 8.0;
pico_latch_back_b = 44.0;

// --------------------------------------------------------------------------
// Fit checks. These run on every export.
// --------------------------------------------------------------------------

assert(nozzle <= 0.4 + 1e-6, "Models are tuned for a 0.4 mm nozzle");
assert(wall + 1e-6 >= 4 * nozzle, "Wall must be at least four perimeters");
assert(wall + 1e-6 >= 1.2, "Wall thinner than 1.2 mm");
assert(floor_t + 1e-6 >= 3 * nozzle, "Floor must be at least three perimeters");
assert(lid_t + 1e-6 >= 3 * nozzle, "Lid must be at least three perimeters");
assert(floor_t + 1e-6 >= 1.2, "Floor thinner than 1.2 mm");
assert(lid_t + 1e-6 >= 1.2, "Lid thinner than 1.2 mm");
assert(fit_clearance >= 0.20 && fit_clearance <= 0.60,
       "fit_clearance should stay a few tenths of a millimetre");

assert(abs(pico_hole_inset_x - 2.0) < 1e-6, "Pico hole inset X drifted from 2.0 mm");
assert(abs(pico_hole_inset_y - 4.8) < 1e-6, "Pico hole inset Y drifted from 4.8 mm");
assert(pico_hole_d + 1e-6 >= 2.0, "M2 shank (2.0 mm) must pass the Pico hole");
assert(pico_hole_d <= 2.2, "Pico mounting hole should stay the official 2.1 mm");
assert(pico_usb_opening_w >= pico_usb_shell_w + 0.8, "USB opening narrower than the shell");
assert(pico_usb_opening_h >= pico_usb_shell_h + 0.8, "USB opening shorter than the shell");
assert(pico_antenna_gap >= 2.0, "Antenna end gap is too small");
assert(pico_standoff_h >= 3.0, "Standoff will not clear solder tails");
assert(pico_above_header >= 1.2, "Not enough air above the headers");
assert(pico_standoff_od >= m2_insert_od + 2.4, "Standoff wall around the insert is thin");

assert(oled_window_l >= oled_active_l, "OLED window clips the active area");
assert(oled_window_w >= oled_active_w, "OLED window clips the active area");
assert(oled_window_l <= oled_pcb_l - 4.0, "OLED window leaves no bezel");
assert(oled_window_w <= oled_pcb_w - 2.0, "OLED window leaves no bezel");
assert(oled_pocket_l >= oled_pcb_l + 2 * 0.20, "OLED pocket is tight");
assert(oled_pocket_w >= oled_pcb_w + 2 * 0.20, "OLED pocket is tight");
assert(oled_connector_w + 1.0 < pico_header_inner_gap,
       "PH2.0 connector is wider than the gap between the Pico headers");

assert(bmp_air >= 0.30 && bmp_air <= 0.50, "BMP280 side clearance left 0.3–0.5 mm");
assert(bmp_pocket_w >= bmp_pcb_w + 2 * 0.30, "BMP280 back clearance left the band");
assert(bmp_header_bay >= 2.6, "Header bay is tight for a 1x6 Dupont plug");
assert(bmp_chamber_l + 1e-6 >= bmp_pin_count * bmp_pin_pitch,
       "Chamber is narrower than a 1x6 Dupont shell");
assert((bmp_pin_count - 1) * bmp_pin_pitch < bmp_pcb_l,
       "Pin centres do not fit the 15 mm edge");
assert(bmp_inner_h >= bmp_platform_h + bmp_pcb_t + bmp_header_above_pcb + 0.6,
       "BMP280 cavity will hit the header pins");
assert(bmp_hole_inset_x > bmp_hole_d / 2 && bmp_hole_inset_back > bmp_hole_d / 2,
       "Mounting hole runs off the module");
assert(bmp_hole_inset_x * 2 < bmp_pcb_l, "Mounting holes meet");

assert(abs((bmp_chamber_l - bmp_pcb_l) / 2 - bmp_air) < 1e-9,
       "BMP280 side clearance does not match the module");
assert(abs(bmp_chamber_w - bmp_header_bay - bmp_pcb_w - bmp_air) < 1e-9,
       "BMP280 back clearance does not match the module");
assert(abs(latch_interference - 0.20) < 1e-6, "Latch interference is not 0.20 mm");
assert(latch_recess_d > 0.40, "Latch recess is too shallow to hold");
assert(abs((latch_gap + latch_reach) - latch_gap - latch_recess_d - latch_interference) < 1e-9,
       "Hook does not engage the recess by the interference");
assert(latch_catch + 0.15 < latch_recess_h, "Catch face does not sit inside the recess");
assert(abs(latch_lead - (latch_reach + latch_gap)) < 1e-6, "Latch lead-in is not 45 degrees");
assert(latch_t <= 1.05, "Latch finger is too thick to flex");
assert(bmp_latch_arm >= 8.0, "BMP280 latch arm is too short to flex");
assert(pico_latch_arm >= 7.2, "Pico latch arm is too short to flex");
assert(pico_latch_z > 1.3 + rail_h + 0.25 + 1.3, "Pico latch sits inside the bracket jaw");
assert(skirt_t >= 1.2, "Lid skirt too thin to locate the lid");
assert(m2_insert_hole_d < m2_insert_od, "Insert hole must be under the insert OD");
assert(m2_insert_hole_depth >= m2_insert_len, "Insert pocket shorter than the insert");
assert(m2_clearance_d >= 2.05, "M2 clearance hole too tight");
assert(m3_clearance_d >= 3.2, "M3 clearance hole too tight");

echo("FIT pico outline", pico_l, pico_w, pico_t);
echo("FIT pico holes", pico_hole_dx, pico_hole_dy, pico_hole_d, "insets", pico_hole_inset_x, pico_hole_inset_y);
echo("FIT pico usb overhang", pico_usb_overhang, "opening", pico_usb_opening_w, pico_usb_opening_h);
echo("FIT oled pcb", oled_pcb_l, oled_pcb_w, "active", oled_active_l, oled_active_w, "window", oled_window_l, oled_window_w);
echo("FIT oled pocket", oled_pocket_l, oled_pocket_w, "stack", oled_stack_h);
echo("FIT bmp pocket", bmp_pocket_l, bmp_pocket_w, "chamber", bmp_chamber_l, bmp_chamber_w, "body", bmp_outer_l, bmp_outer_w, bmp_body_h);
echo("FIT latch", latch_interference, "arm", bmp_latch_arm, pico_latch_arm);
