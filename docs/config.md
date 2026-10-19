# Config reference

Every setting in [`config.py`](../config.py). At boot, [`settings.py`](../settings.py) checks the value. A bad value is printed on the serial console and replaced with the default below. Fan PWM and tach pins are not settings: they stay GP15–GP18 and GP14–GP11.

The thermal curve itself is not in this file. In [`fan.py`](../fan.py), `MIN_TEMP_C` is 35, `MAX_TEMP_C` is 55, and `MIN_SPEED` is 0.18 (18%).

| Option | Default | Meaning | When to change |
|--------|---------|---------|----------------|
| `WIFI_SSID` | `YOUR_SSID` | Station network name | Your Wi-Fi name. Leave the placeholder to run with no radio |
| `WIFI_PASSWORD` | `YOUR_PASSWORD` | Station password | Your Wi-Fi password. Do not commit a real one |
| `WIFI_TIMEOUT_S` | `20` | Seconds one association attempt may stay in `connecting` | Raise it on a slow access point. The wait is polled; it does not block the fans |
| `WIFI_RETRY_S` | `10` | Pause after a failed attempt before `connect()` again | Raise it if the access point rate-limits joins |
| `WIFI_ENABLED` | `True` | Open the radio at all | `False` on a classic Pico, or to force fan-only mode |
| `HTTP_PORT` | `80` | TCP port for the control page, JSON, and metrics | Another port if 80 is taken. The URL then needs `:port` |
| `HTTP_USER` | empty | Basic Auth username | Set this and the password together. Either one empty turns auth off |
| `HTTP_PASSWORD` | empty | Basic Auth password | A long password. Sent in the clear; this firmware has no TLS |
| `METRICS_REQUIRE_AUTH` | `True` | `/metrics` uses the same Basic Auth | `False` only for a scraper on a trusted LAN that cannot send a password |
| `WDT_ENABLED` | `True` | Arm the hardware watchdog after the radio starts | `False` while debugging, so Ctrl+C stays in the REPL at 100% duty |
| `WDT_TIMEOUT_MS` | `8000` | Watchdog window in milliseconds. The RP2040 maximum is 8388 | Leave it. A shorter window resets sooner; it cannot be longer than 8388 |
| `STALL_DUTY_MIN` | `0.15` | Duty at or above this, with a low tach sample, is a stall | Raise it if a healthy fan at low duty is flagged. Duty 0 never stalls |
| `STALL_RPM_BELOW` | `1` | Latest 1 s tach sample below this counts as stopped | `1` means 0 RPM. Raise it to flag a fan that spins but is far too slow |
| `I2C_FREQ` | `100000` | I2C clock in hertz | Lower it if a long cable is noisy |
| `I2C_TIMEOUT_US` | `50000` | Hardware I2C timeout, 50 ms | Leave it. A stuck bus must not block past the watchdog |
| `INTERNAL_BMP280_ENABLED` | `False` | Read the internal BMP280 | `True` after that sensor is wired |
| `INTERNAL_BMP280_ADDR` | `0x76` | 7-bit I2C address | Leave `0x76` for a hardwired SDO-to-GND module |
| `INTERNAL_BMP280_I2C_ID` | `0` | I2C controller | Leave 0. This is the bus shared with the OLED |
| `INTERNAL_BMP280_SDA` | `4` | SDA GPIO | Leave GP4 unless you move the whole bus |
| `INTERNAL_BMP280_SCL` | `5` | SCL GPIO | Leave GP5 unless you move the whole bus |
| `EXTERNAL_BMP280_ENABLED` | `False` | Read the external BMP280 | `True` after that sensor is wired |
| `EXTERNAL_BMP280_ADDR` | `0x76` | 7-bit I2C address | Leave `0x76`. Use `0x77` only for the shared-bus alternative |
| `EXTERNAL_BMP280_I2C_ID` | `1` | I2C controller | Leave 1. Set `0` only when this sensor shares I2C0 at `0x77` |
| `EXTERNAL_BMP280_SDA` | `6` | SDA GPIO | Leave GP6. Set `4` only for the shared-bus alternative |
| `EXTERNAL_BMP280_SCL` | `7` | SCL GPIO | Leave GP7. Set `5` only for the shared-bus alternative |
| `OLED_ENABLED` | `False` | Drive the SSD1306 | `True` after the display is wired |
| `OLED_ADDR` | `0x3C` | 7-bit I2C address | `0x3D` if a scan shows 61 |
| `OLED_I2C_ID` | `0` | I2C controller | Leave 0 so it shares the internal bus |
| `OLED_SDA` | `4` | SDA GPIO | Must match the internal BMP280 SDA |
| `OLED_SCL` | `5` | SCL GPIO | Must match the internal BMP280 SCL |
| `OLED_WIDTH` | `128` | Panel width in pixels | Leave 128 for the 0.91 inch module |
| `OLED_HEIGHT` | `32` | Panel height in pixels. Must be a multiple of 8 | Leave 32. 64 is the taller SSD1306 |
| `OLED_PAGE_S` | `3` | Seconds each OLED page stays up | Lower it to cycle faster |
| `FAN_ROLES` | intake, intake, exhaust, exhaust | Role of fans 1–4 | Swap words if your ducting is different. Four words, each `intake` or `exhaust` |
| `AIRFLOW_EXHAUST_RATIO` | `0.85` | Auto exhaust duty starts at intake duty times this | Lower it for more positive pressure. 0.85 at the 18% floor would be 15.3%, which is then lifted to 18% |
| `AIRFLOW_EXHAUST_OFFSET` | `0.0` | Added to that product, then clamped to 0–1 | A small positive offset runs the exhaust harder |
| `PRESSURE_LOOP_ENABLED` | `True` | Trim auto exhaust from the pressure difference | `False` to keep the static ratio even when both sensors are healthy |
| `PRESSURE_TARGET_PA` | `5.0` | Desired internal-minus-external pascals | A few pascals of positive pressure. This is not an integrator |
| `PRESSURE_LOOP_GAIN` | `0.0005` | Duty added per pascal of error, each 1 s sample | 0.0005 is 0.5% duty for a 10 Pa error. Larger gains hit the cap sooner |
| `PRESSURE_LOOP_TRIM_MAX` | `0.05` | Cap on that trim, as a duty fraction | `0.05` is ±5% duty. It cannot wind up, because the next sample starts over |
| `BMP280_TEMP_MIN_C` | `-40.0` | Coldest BMP280 temperature that may drive the fans | Datasheet operating limit. Widen it only if you know the part |
| `BMP280_TEMP_MAX_C` | `85.0` | Hottest BMP280 temperature that may drive the fans | Datasheet operating limit |
| `BMP280_TEMP_JUMP_C` | `10.0` | Max temperature change between 1 s samples | Lower it to catch smaller glitches. A real step is accepted again after the clear debounce |
| `BMP280_PRESS_MIN_PA` | `30000.0` | Lowest pressure, 300 hPa | Datasheet operating limit |
| `BMP280_PRESS_MAX_PA` | `110000.0` | Highest pressure, 1100 hPa | Datasheet operating limit |
| `BMP280_PRESS_JUMP_PA` | `1000.0` | Max pressure change between 1 s samples, 10 hPa | An enclosure does not jump by this in one second |
| `BMP280_STUCK_SAMPLES` | `30` | Identical raw temperature and pressure in a row | About 30 s at the 1 s sample. Raise it if a very still sensor is flagged |
| `SENSOR_FAULT_SET_SAMPLES` | `2` | Bad samples in a row before the badge latches | The bad sample is already discarded on the first one |
| `SENSOR_FAULT_CLEAR_SAMPLES` | `3` | Good samples in a row before the badge clears | Raise it if a sensor chatters in and out of range |
| `SENSOR_STALE_S` | `5` | Failed reads older than this are reason `stale` | Also how long a bad die reading may keep the last good die temperature |
| `DIE_TEMP_MIN_C` | `-20.0` | Coldest die temperature that may drive the curve | Below this, the reading is ignored |
| `DIE_TEMP_MAX_C` | `100.0` | Hottest die temperature that may drive the curve | The curve is already at 100% duty by 55 °C |
| `DIE_TEMP_JUMP_C` | `15.0` | Max die change between samples | A single spike is ignored |
| `TACH_RPM_MAX` | `10000` | Tach count above this is ignored | It is not smoothed into the displayed RPM |
| `TACH_ZERO_DUTY_RPM` | `1` | RPM at duty 0 at or above this is a tach fault | Any pulse while the fan is commanded off |
| `PRESSURE_DELTA_MAX_PA` | `2000.0` | Largest \|internal − external\| that may trim the fans | A real enclosure is a few pascals to a few hundred, not 2000 |

Two devices on the same I2C controller must use the same SDA and SCL. The same address on one bus disables the later device. The same address on two buses is the normal case: both BMP280s at `0x76`.
