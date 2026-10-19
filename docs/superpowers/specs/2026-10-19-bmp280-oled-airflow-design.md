# Optional BMP280s, OLED, and positive-pressure airflow

**Date:** 2026-10-19  
**Status:** Implemented  
**Hardware:** Raspberry Pi Pico W, up to four 4-pin 12 V PWM fans, optional Waveshare 0.91 inch SSD1306, optional Bosch BMP280 modules

## Goal

Keep the existing per-fan controller (PR #1: auth, watchdog, stall, non-blocking HTTP) and add three optional features that default to off:

- An internal BMP280 and an external BMP280 (temperature and pressure only).
- A 128×32 I2C OLED.
- Intake/exhaust bias so auto mode holds a slight positive pressure.

A missing or failed peripheral must not stop fan control or the watchdog.

## Decisions (locked)

| Topic | Choice |
|-------|--------|
| Sensor | BMP280 only. Chip id register `0xD0` must be `0x58`. Any other id is a permanent error |
| Humidity | Not implemented. No field, metric, page, or driver path |
| Buses | Internal BMP280 and OLED on I2C0 GP4/GP5. External BMP280 on I2C1 GP6/GP7. 100 kHz, 50 ms timeout. Sharing I2C0 at `0x77` remains a config option |
| Addresses | Both BMP280s `0x76` (SDO hardwired to GND). OLED `0x3C` |
| Temperature source | Internal BMP280 while its latest read is ok; otherwise RP2040 die, including after a runtime failure. Boot uses the die sensor |
| Airflow | Fans 1–2 intake, 3–4 exhaust. Static exhaust = clamp(curve × 0.85 + 0), then any result in (0, 18%) is lifted to 18%. Duty 0 stays off. Manual ignores the rule |
| Pressure loop | On. Each 1 s sample adds `gain * (delta_pa - 5 Pa)` to the static exhaust duty, gain 0.0005, trim capped at ±5% duty. Not an integrator. If either sensor fails, the trim is skipped and the static ratio remains |
| OLED | Four rotating pages, 3 s, updated only on the 1 s sample, plus a fifth SENSOR FAULT page while a fault is latched. 512-byte framebuffer |
| Failure policy | Log on change, keep the previous fan duty path (die fallback), feed the watchdog around the sample |
| Compensation | Bosch BST-BMP280-DS001 section 3.11.3 integer formula, not the double-precision appendix |

## Pin map

Fan pins are unchanged: PWM GP15–GP18, tach GP14/GP13/GP12/GP11. Peripherals must not use those, or GP23/GP24/GP25/GP29.

| Function | Default |
|----------|---------|
| I2C0 SDA / SCL | GP4 / GP5 |
| I2C1 SDA / SCL | GP6 / GP7 |
| Internal BMP280 | I2C0, `0x76`, SDO to GND |
| External BMP280 | I2C1, `0x76`, SDO to GND |
| OLED | I2C0, `0x3C`, 128×32 |

Power each BMP280 from Pico 3V3 (1.8–3.3 V). Tie CSB to 3V3 so the chip stays in I2C. Do not float SDO, and do not short a hardwired SDO to 3V3. The HandsOn GY-BMP280 guide says that module is hardwired to `0x76`, so the two modules use two controllers. A free SDO tied to 3V3 (`0x77` on I2C0) is the shared-bus alternative. The Waveshare OLED is I2C-only (VCC, GND, DIN, CLK) and shares I2C0. Its wiki lists 3.3/5 V on the power pin; this design uses 3V3 so a shared rail cannot feed 5 V into a BMP280.

## Architecture

```text
config.py      Wi-Fi, auth, watchdog, BMP280, OLED, airflow, fault thresholds
settings.py    Validate config; disable a bad peripheral; never retarget fan pins
faults.py      Range, jump, stuck, stale, tach, and pressure-delta checks
bmp280.py      One BMP280: id check, reset, calib, normal mode, integer compensation
sensors.py     BusPool (one machine.I2C per id) and SensorHub
ssd1306.py     I2C SSD1306, MIT attribution to micropython-lib. No SPI, no framebuf
display.py     8×8 font, four pages plus a SENSOR FAULT page while a fault is latched
fan.py         Curve, roles, ratio/offset, pressure trim, status fields
web.py         HTML + /status.json, Basic Auth unchanged
metrics.py     Prometheus gauges, pressure in pascals, sensor-fault series
main.py        prepare_fans before Wi-Fi; arm WDT; then open peripherals; 1 s sample
```

`machine` is imported only inside functions that run on the board, so the host tests import the modules on CPython.

### BMP280

- Soft reset `0xE0 = 0xB6`, then 10 ms (datasheet start-up is 2 ms). The watchdog is fed around that sleep.
- Calibration is the 24 bytes at `0x88`: T1/P1 unsigned little-endian, the rest signed.
- `ctrl_meas 0x57` (temperature ×2, pressure ×16, normal mode) is written after `config 0xA8` (1 s standby, IIR coefficient 4) while the part is still in sleep.
- Each 1 s sample is a 6-byte burst at `0xF7`. The first conversion is left for that sample; init reports `error="starting"` and does not publish 0 °C.
- A bus error clears the sample and retries init next time. A bad chip id does not retry.
- On init failure the driver scans the bus once and appends `scan=0x..` to the error.

The published integer example (adc_T 519888, adc_P 415148, the usual dig_* set) is 25.08 °C and 100653.25390625 Pa. Division truncates toward zero, matching C.

### Temperature and airflow

`select_control_temp` returns `(internal_c, "internal")` only when the internal sensor is ok. Otherwise `(die_c, "die")`.

Intake auto duty is the curve duty (18% floor at ≤35 °C, 100% at ≥55 °C). Exhaust auto duty is `clamp(base * ratio + offset)`, then `lift_exhaust_idle`: any result in `(0, MIN_SPEED)` becomes `MIN_SPEED`. Duty 0 stays off and does not alarm.

The raw idle product 0.18 × 0.85 = 0.153 sits 0.3 percentage points above `STALL_DUTY_MIN` 0.15. A fan that does not spin there raises a stall that looks like a fault. Holding idle exhaust at 18% matches the intake floor, so a stopped exhaust fan is the same kind of stall as a stopped intake fan. Above the floor the ratio still biases exhaust (50% → 42.5%, 100% → 85%).

### Pressure loop

On by default (`PRESSURE_LOOP_ENABLED`). While `pressure_delta_pa` is a number, exhaust duty adds:

```text
trim = clamp(0.0005 * (delta_pa - 5), -0.05, 0.05)
```

The trim is recomputed from the static duty every 1 s sample. It is not summed across samples, so it cannot wind up. A 10 Pa error is 0.5% duty. A 100 Pa error, larger than a plausible BMP280-to-BMP280 offset for this use, is already at the ±5% cap, and the next sample starts again from the ratio. After the trim, `lift_exhaust_idle` runs again so the loop cannot park exhaust in the 0–18% band except at duty 0.

`pressure_loop_active` is true only when the loop is enabled and this sample had a delta. A missing or failed sensor sets the delta to null, clears the active flag, and leaves the static ratio. Status, the web page (`active` / `idle` / `off`), `pico_fan_pressure_loop_enabled`, and `pico_fan_pressure_loop_active` expose that. Intake fans are not trimmed. Manual fans ignore the rule.

### OLED

Page 0: IP (or Wi-Fi state), `src internal` / `src die`, control temperature, pressure delta plus `on` / `idle` / `off`.  
Page 1: `1I   820  18%` with `m` for manual and `!` for stall.  
Page 2: internal BMP280. Page 3: external BMP280.  
A fifth page, `SENSOR FAULT`, is inserted only while a fault is latched. `display.PAGE_COUNT` stays 4; the page list is built when the framebuffer updates.  
16 columns × 4 rows. `show()` prefers `I2C.writevto`; otherwise it writes a preallocated `0x40` frame.

### Status and metrics

Status keys: `control_c`, `temp_source`, `pressure_delta_pa` (null if unknown), `pressure_loop_enabled`, `pressure_loop_active`, `sensors.internal` / `sensors.external` (`enabled`, `ok`, `chip_id`, `temp_c`, `pressure_pa`, `error`, `fault`, `fault_reason`), `oled`, `fans[].role`, `faults`, `fault_counts`. The short web strings are `short` and `short_reason`.

Gauges: `pico_fan_bmp280_up`, `pico_fan_bmp280_temperature_celsius`, `pico_fan_bmp280_pressure_pascals` (label `location`), `pico_fan_pressure_delta_pascals`, `pico_fan_pressure_loop_enabled`, `pico_fan_pressure_loop_active`, `pico_fan_control_temp_celsius`, `pico_fan_temp_source_info`, `pico_fan_intake`, `pico_fan_oled_up`. Temperature and pressure samples are omitted when the sensor is not ok.

Sensor faults: BMP280 temperature (−40..85 °C, or a jump), pressure (300..1100 hPa, or a jump), identical raw samples, stale or failed reads, die temperature, tach RPM above the plausible max or RPM at duty 0, and |internal − external| pressure. A rejected sample does not drive the curve or the pressure loop. The badge latches and clears with debounce. `faults` and `fault_reason` are in the status JSON. Prometheus uses `pico_fan_sensor_fault` and `pico_fan_sensor_fault_total` with a closed `sensor` / `location` / `reason` set. The OLED adds a fault page only while a fault is latched. Thresholds live in `config.py`.

## Main loop

1. `prepare_fans` (spin-up, overrides, die curve) before any network wait.
2. Start the radio, then arm the watchdog (8 s, max 8388 ms).
3. Open I2C only if something is enabled. Feed around BMP280 reset and around OLED init.
4. Every loop pass: feed the watchdog, poll Wi-Fi and HTTP, blink the LED. Sleep 10 ms until 1 s has elapsed.
5. On the 1 s edge: `sample_peripherals` feeds, reads both BMP280s, drops implausible samples, ticks fans, updates one OLED page, collects garbage, and feeds again. Exceptions in Wi-Fi, HTTP, the LED, logging, or a sample are contained. Ctrl+C and an uncaught error still force every fan duty to 100%.

## Out of scope

- Any sensor other than the BMP280, and any humidity reading
- Anything beyond the capped proportional exhaust trim (no integrator, no intake trim)
- TLS, or changing Basic Auth
- Moving fan PWM or tach pins

## Success criteria

1. Shipped config leaves the BMP280s and the OLED off, and existing fan tests still pass.
2. Chip id other than `0x58` is reported and not retried. A missing sensor does not stop the other sensor or the fans.
3. Host tests lock the Bosch integer compensation values, role duty, die fallback, OLED pages, status JSON, and metrics with peripherals absent and present.
4. README wiring matches the default: both BMP280s at `0x76`, internal plus OLED on I2C0, external on I2C1, with the `0x77` shared bus documented as the alternative.
5. Host tests cover the two-bus default, the shared-bus alternative, loop-on defaults, trim clamping, and fallback to the static ratio when the delta is missing.
