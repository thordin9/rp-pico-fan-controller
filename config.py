"""
Local settings for the Pico W fan controller.

Edit WIFI_SSID / WIFI_PASSWORD before flashing. Do not commit real secrets
to a public fork — keep this file private or use placeholders in shared remotes.
"""

# Wi-Fi (Pico W station mode). Leave placeholders to skip networking.
WIFI_SSID = "YOUR_SSID"
WIFI_PASSWORD = "YOUR_PASSWORD"

# How long one association attempt may stay in "connecting" before it is
# abandoned. The wait is polled from the main loop; it does not block fans.
WIFI_TIMEOUT_S = 20

# Pause after a failed attempt before calling connect() again.
WIFI_RETRY_S = 10

# HTTP status page (stdlib sockets; no extra deps).
HTTP_PORT = 80

# HTTP Basic Auth. Set BOTH to a non-empty username and password to require
# auth on every endpoint (control page, /status.json, /api/fans, /metrics).
# If either is empty, auth is disabled and a warning is printed at boot.
HTTP_USER = ""
HTTP_PASSWORD = ""

# /metrics uses the same Basic Auth when this is True (the default).
# Set False only for an unauthenticated Prometheus scrape on a trusted LAN.
METRICS_REQUIRE_AUTH = True

# Hardware watchdog. The RP2040 maximum is 8388 ms. Armed after radio init
# and fed from the main loop, so the association wait cannot trip it.
# A hung loop resets the board within this window. Set False to disable.
WDT_ENABLED = True
WDT_TIMEOUT_MS = 8000

# Stall alarm: latest 1 s tach sample reports RPM < STALL_RPM_BELOW while
# commanded duty >= STALL_DUTY_MIN. Default RPM threshold 1 means "0 RPM".
# Duty 0 stays legal (fan off) and does not alarm.
STALL_DUTY_MIN = 0.15
STALL_RPM_BELOW = 1

# Set False on classic Pico (no radio) or to force offline fan-only mode.
WIFI_ENABLED = True

# --- Optional peripherals ---------------------------------------------------
# Everything below is off until you set the matching *_ENABLED flag. A part
# that is enabled but missing is logged and skipped; the fans keep running.
#
# Default buses, on pins that are free of PWM (GP15–18), tach (GP14–11),
# and the Pico W wireless pins:
#   I2C0 GP4 SDA / GP5 SCL: internal BMP280 (0x76) and the OLED (0x3C)
#   I2C1 GP6 SDA / GP7 SCL: external BMP280 (0x76)
# Both BMP280 modules are assumed hardwired to 0x76 (SDO tied to GND).
# To share one bus instead, strap the external SDO to 3V3 for address 0x77
# and use the commented block below.
#
# BMP280 (HandsOn GY-BMP280 and the Bosch part):
#   VCC -> Pico 3V3 (the module is 1.8–3.3 V; do not use 5 V)
#   GND -> Pico GND
#   SDA -> that bus's SDA, SCL -> that bus's SCL, pull-ups to 3V3
#   CSB -> 3V3 so the chip stays in I2C mode (a low CSB at power-up locks SPI)
#   SDO -> GND gives address 0x76. Do not leave SDO open. Do not short a
#   hardwired SDO to 3V3.

I2C_FREQ = 100000
I2C_TIMEOUT_US = 50000

INTERNAL_BMP280_ENABLED = False
INTERNAL_BMP280_ADDR = 0x76
INTERNAL_BMP280_I2C_ID = 0
INTERNAL_BMP280_SDA = 4
INTERNAL_BMP280_SCL = 5

EXTERNAL_BMP280_ENABLED = False
EXTERNAL_BMP280_ADDR = 0x76
EXTERNAL_BMP280_I2C_ID = 1
EXTERNAL_BMP280_SDA = 6
EXTERNAL_BMP280_SCL = 7
# Shared-bus alternative, only if this module's SDO can be tied to 3V3:
# EXTERNAL_BMP280_ADDR = 0x77
# EXTERNAL_BMP280_I2C_ID = 0
# EXTERNAL_BMP280_SDA = 4
# EXTERNAL_BMP280_SCL = 5

# Waveshare 0.91 inch SSD1306, 128x32, I2C address 0x3C. Shares I2C0.
OLED_ENABLED = False
OLED_ADDR = 0x3C
OLED_I2C_ID = 0
OLED_SDA = 4
OLED_SCL = 5
OLED_WIDTH = 128
OLED_HEIGHT = 32
OLED_PAGE_S = 3

# Positive pressure. Auto exhaust duty = clamp(intake_duty * ratio + offset).
# Fans 1 and 2 are intake, 3 and 4 are exhaust. Manual mode ignores this.
FAN_ROLES = ("intake", "intake", "exhaust", "exhaust")
AIRFLOW_EXHAUST_RATIO = 0.85
AIRFLOW_EXHAUST_OFFSET = 0.0

# Pressure trim from (internal Pa - external Pa). On by default.
# Each 1 s sample adds gain * (delta_pa - target_pa) to the static exhaust
# duty, capped at ±PRESSURE_LOOP_TRIM_MAX. It is not an integrator.
# If either BMP280 is missing or failing, the trim is skipped.
PRESSURE_LOOP_ENABLED = True
PRESSURE_TARGET_PA = 5.0
PRESSURE_LOOP_GAIN = 0.0005
PRESSURE_LOOP_TRIM_MAX = 0.05

# Sensor sanity checks. A sample outside these limits does not drive the
# fan curve or the pressure loop. The fault badge latches after
# SENSOR_FAULT_SET_SAMPLES bad samples and clears after
# SENSOR_FAULT_CLEAR_SAMPLES good ones.
# BMP280 operating range from the datasheet: -40..85 °C, 300..1100 hPa.
BMP280_TEMP_MIN_C = -40.0
BMP280_TEMP_MAX_C = 85.0
BMP280_TEMP_JUMP_C = 10.0          # max change between 1 s samples
BMP280_PRESS_MIN_PA = 30000.0      # 300 hPa
BMP280_PRESS_MAX_PA = 110000.0     # 1100 hPa
BMP280_PRESS_JUMP_PA = 1000.0      # 10 hPa per sample
BMP280_STUCK_SAMPLES = 30          # identical raw temp+pressure
SENSOR_FAULT_SET_SAMPLES = 2
SENSOR_FAULT_CLEAR_SAMPLES = 3
SENSOR_STALE_S = 5
DIE_TEMP_MIN_C = -20.0
DIE_TEMP_MAX_C = 100.0
DIE_TEMP_JUMP_C = 15.0
TACH_RPM_MAX = 10000
TACH_ZERO_DUTY_RPM = 1             # RPM at duty 0 at or above this is a fault
PRESSURE_DELTA_MAX_PA = 2000.0     # |internal - external| above this is ignored
