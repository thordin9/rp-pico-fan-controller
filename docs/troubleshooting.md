# Troubleshooting

## No Wi-Fi

`WIFI_SSID` left as `YOUR_SSID`, or `WIFI_ENABLED = False`, skips the radio on purpose. The serial line says Wi-Fi was skipped, and the fans still run.

If you set a real network and it stays on `connecting` or `timeout`:

- The password is the Wi-Fi password, not the HTTP password.
- The Pico W only joins 2.4 GHz.
- `WIFI_TIMEOUT_S` is how long one attempt may last. `WIFI_RETRY_S` is the pause before the next one.
- Power the board from a solid 5 V supply. A weak USB cable drops out under Wi-Fi.

`wifi` in the JSON is `connected`, `connecting`, `timeout`, `offline`, `disabled`, or `unsupported`. `unsupported` means the MicroPython build has no `network` module (a classic Pico image).

## 401 on every request

Auth is on because both `HTTP_USER` and `HTTP_PASSWORD` are non-empty. The browser should prompt. `curl` needs `-u user:password`.

A 401 with no prompt usually means the client sent a bad password and cached it. The header is `WWW-Authenticate: Basic realm="pico-fan"`.

To turn auth off, set either `HTTP_USER` or `HTTP_PASSWORD` to an empty string and reboot. The serial log then prints a warning. `METRICS_REQUIRE_AUTH = False` opens only `/metrics`.

## Fans do not spin

- Fan pin 2 must be on the 12 V supply. The Pico cannot power a fan.
- Fan pin 1 and the Pico must share ground with that supply.
- PWM is pin 4 of the fan, one GPIO each: GP15, GP16, GP17, GP18.
- At a cool die temperature the duty is 18%, not 0%. Some fans need more than 18% to start. The boot spin-up is 60% for 1.5 seconds; if they move then and stop, raise the floor in `fan.py` (`MIN_SPEED`) rather than the stall threshold.
- A manual duty of 0 is off. Set the fan back to auto from the page or `POST /api/fans/<id>/auto`.

## Stall alarms

A stall means duty is at least `STALL_DUTY_MIN` (15%) and the latest one-second tach sample is below `STALL_RPM_BELOW` (1, so 0 RPM).

- Tach is fan pin 3, not pin 4. Each tach has its own GPIO: GP14, GP13, GP12, GP11.
- Each tach needs 10 kΩ to Pico 3V3 (physical pin 36), not to 5 V or 12 V.
- Do not tie tach wires together.
- The RPM on the page is smoothed, so it can still show a falling number on the sample that raises the alarm.
- Auto exhaust is lifted from the raw 15.3% product up to 18% so a fan is not asked to sit on the stall line. Duty 0 does not alarm.
- RPM while the duty is 0 is a tach fault (`rpm_at_zero_duty`), not a stall.

## Sensor faults

The red badge names the sensor and the reason. The same text is in `/status.json` under `faults` and on that sensor's `error` field.

| What you see | What it means |
|--------------|----------------|
| `pressure out of range` | Outside 300–1100 hPa, or not a finite number. That sample is not used |
| `temperature out of range` | Outside −40..85 °C for a BMP280, or −20..100 °C for the die |
| `temperature jumped` or `pressure jumped` | The 1 second step was above 10 °C or 10 hPa. A new stable value is accepted after three good samples |
| `reading stuck` | The raw sample did not change for 30 samples |
| `read failed` then `reading stale` | The bus failed. After 5 seconds the reason becomes stale |
| `pressure difference out of range` | The two sensors disagree by more than 2000 Pa. The trim is skipped; the temperatures can still be used |
| `rpm out of range` | The count was above 10000 RPM and was ignored |
| `chip id 0x.. is not BMP280 (0x58)` | Wrong part. It stays rejected until you reboot with a BMP280 |

A rejected internal temperature falls back to the die. A rejected pressure falls back to the static intake/exhaust ratio. `pressure_loop_active` is then false and the page shows the loop as idle.

## I2C scan

Stop the firmware with Ctrl+C if the watchdog is disabled, or run this from a short script before `main` starts. While the firmware owns the bus, a second `I2C()` on the same pins will fail.

```python
from machine import I2C, Pin
bus0 = I2C(0, sda=Pin(4), scl=Pin(5), freq=100000)
bus1 = I2C(1, sda=Pin(6), scl=Pin(7), freq=100000)
print(bus0.scan())  # 118 is 0x76, 60 is 0x3C
print(bus1.scan())  # 118 is the external BMP280
```

| What you see | What to do |
|--------------|------------|
| `[]` | 3V3 and GND, SDA and SCL not swapped, pull-ups to 3V3 on that bus. CSB must be high before power-up. SDO must be GND for `0x76` |
| I2C0 `[118, 60]` and I2C1 `[118]` | The default: internal BMP280, OLED, external BMP280 |
| I2C0 `[118, 119, 60]` | The external SDO is at 3V3, so that sensor is `0x77` on I2C0. That is the shared-bus alternative, not the default. Set `EXTERNAL_BMP280_ADDR`, `EXTERNAL_BMP280_I2C_ID`, and the pins to match |
| `61` | OLED is at `0x3D`. Set `OLED_ADDR = 0x3D` |
| Address-conflict log line | The same address was found on one bus. The later device was turned off. Two modules at `0x76` belong on I2C0 and I2C1 |
| Reboots a few seconds after enabling a sensor | A stuck bus can block long enough to trip the 8 second watchdog. Fix the wiring. Do not raise the watchdog to hide it |

Unplug a BMP280 or the OLED while running: the next sample logs the failure and auto fans fall back to the die temperature. Plugging it back is picked up on a later sample. A wrong chip id stays rejected.

## The board reboots by itself

The hardware watchdog is on by default and cannot be turned off once armed. A hung loop, or a USB serial session that stops reading the 1 Hz print, can trip it. Close the serial port when you are not watching, or set `WDT_ENABLED = False` while debugging. Ctrl+C then stays in the REPL with the fans at 100%.

## Serial line

A normal 1 Hz line looks like this. Width comes from the format string: temperatures are 5 characters, duty is a 3-character percent, RPM is 4 characters.

```text
die= 30.2°C ctl= 28.4°C src=internal  dP=+12Pa loop=on  F1=a=18%= 820 F2=m=40%= 815 F3=a=42%= 700 F4=a=42%=   0!  wifi=connected
```

`a` is auto, `m` is manual, and `!` is stall. `loop` is `on`, `idle`, or `off`. `dP=--` means the pressure trim is not using a delta.
