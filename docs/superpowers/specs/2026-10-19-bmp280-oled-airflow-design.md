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
| Buses | Default I2C0 GP4/GP5, 100 kHz, 50 ms timeout. Spare I2C1 GP6/GP7 when a module cannot leave `0x76` |
| Addresses | Internal `0x76` (SDO to GND), external `0x77` (SDO to 3V3). OLED `0x3C` |
| Temperature source | Internal BMP280 while its latest read is ok; otherwise RP2040 die, including after a runtime failure. Boot uses the die sensor |
| Airflow | Fans 1–2 intake, 3–4 exhaust. Exhaust duty = clamp(curve × 0.85 + 0). Manual ignores the rule |
| Pressure loop | Off. Optional exhaust trim `gain * (internal_Pa - external_Pa - 5 Pa)` with gain 0.002 |
| OLED | Four pages, 3 s, updated only on the 1 s sample. 512-byte framebuffer |
| Failure policy | Log on change, keep the previous fan duty path (die fallback), feed the watchdog around the sample |
| Compensation | Bosch BST-BMP280-DS001 section 3.11.3 integer formula, not the double-precision appendix |

## Pin map

Fan pins are unchanged: PWM GP15–GP18, tach GP14/GP13/GP12/GP11. Peripherals must not use those, or GP23/GP24/GP25/GP29.

| Function | Default |
|----------|---------|
| I2C0 SDA / SCL | GP4 / GP5 |
| I2C1 SDA / SCL | GP6 / GP7 |
| Internal BMP280 | I2C0, `0x76` |
| External BMP280 | I2C0, `0x77` |
| OLED | I2C0, `0x3C`, 128×32 |

Power the BMP280 from Pico 3V3 (1.8–3.3 V). Tie CSB to 3V3 so the chip stays in I2C. Do not float SDO. The HandsOn GY-BMP280 guide says that module is hardwired to `0x76`; the second-bus settings exist for that case. The Waveshare OLED is I2C-only (VCC, GND, DIN, CLK). Its wiki lists 3.3/5 V on the power pin; this design uses 3V3 so a shared rail cannot feed 5 V into a BMP280.

## Architecture

```text
config.py      Wi-Fi, auth, watchdog, BMP280, OLED, airflow
settings.py    Validate config; disable a bad peripheral; never retarget fan pins
bmp280.py      One BMP280: id check, reset, calib, normal mode, integer compensation
sensors.py     BusPool (one machine.I2C per id) and SensorHub
ssd1306.py     I2C SSD1306, MIT attribution to micropython-lib. No SPI, no framebuf
display.py     8×8 font, four pages, rotation
fan.py         Curve, roles, ratio/offset, optional pressure trim, status fields
web.py         HTML + /status.json, Basic Auth unchanged
metrics.py     Prometheus gauges, pressure in pascals
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

Intake auto duty is the curve duty (18% floor at ≤35 °C, 100% at ≥55 °C). Exhaust auto duty is `clamp(base * ratio + offset)`. With the pressure loop on and a delta available, only the exhaust duty then adds `gain * (delta_pa - target_pa)`.

Idle exhaust is 0.18 × 0.85 = 0.153, which is above `STALL_DUTY_MIN` 0.15, so a fan that does not spin there alarms. Exhaust is not raised back to the 18% floor.

### OLED

Page 0: IP (or Wi-Fi state), `src internal` / `src die`, control temperature, pressure delta.  
Page 1: `1I   820  18%` with `m` for manual and `!` for stall.  
Page 2: internal BMP280. Page 3: external BMP280.  
16 columns × 4 rows. `show()` prefers `I2C.writevto`; otherwise it writes a preallocated `0x40` frame.

### Status and metrics

Status keys: `control_c`, `temp_source`, `pressure_delta_pa` (null if unknown), `sensors.internal` / `sensors.external` (`enabled`, `ok`, `chip_id`, `temp_c`, `pressure_pa`, `error`), `oled`, `fans[].role`.

Gauges: `pico_fan_bmp280_up`, `pico_fan_bmp280_temperature_celsius`, `pico_fan_bmp280_pressure_pascals` (label `location`), `pico_fan_pressure_delta_pascals`, `pico_fan_control_temp_celsius`, `pico_fan_temp_source_info`, `pico_fan_intake`, `pico_fan_oled_up`. Temperature and pressure samples are omitted when the sensor is not ok.

## Main loop

1. `prepare_fans` (spin-up, overrides, die curve) before any network wait.
2. Start the radio, then arm the watchdog (8 s, max 8388 ms).
3. Open I2C only if something is enabled. Feed around BMP280 reset and around OLED init.
4. Every loop pass: feed the watchdog, poll Wi-Fi and HTTP, blink the LED. Sleep 10 ms until 1 s has elapsed.
5. On the 1 s edge: `sample_peripherals` feeds, reads both BMP280s, ticks fans, updates one OLED page, feeds again. Exceptions are contained.

## Out of scope

- Any sensor other than the BMP280, and any humidity reading
- Closed-loop control beyond the optional exhaust trim
- TLS, or changing Basic Auth
- Moving fan PWM or tach pins

## Success criteria

1. Shipped config leaves the BMP280s and the OLED off, and existing fan tests still pass.
2. Chip id other than `0x58` is reported and not retried. A missing sensor does not stop the other sensor or the fans.
3. Host tests lock the Bosch integer compensation values, role duty, die fallback, OLED pages, status JSON, and metrics with peripherals absent and present.
4. README wiring matches the Waveshare four-pin module and the BMP280 CSB/SDO rules, including the second-bus alternative for a hardwired `0x76`.
