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
# Default bus is I2C0 on GP4 (SDA) and GP5 (SCL). Those pins are free:
# PWM is GP15–18, tach is GP14/13/12/11, and the Pico W LED is not a user GPIO.
# I2C1 on GP6/GP7 is the spare bus for a BMP280 whose address cannot move.
#
# BMP280 (HandsOn GY-BMP280 and the Bosch part):
#   VCC -> Pico 3V3 (the module is 1.8–3.3 V; do not use 5 V)
#   GND -> Pico GND
#   SDA -> SDA, SCL -> SCL, each with a pull-up to 3V3 (modules usually have one)
#   CSB -> 3V3 so the chip stays in I2C mode (a low CSB at power-up locks SPI)
#   SDO -> GND gives address 0x76; SDO -> 3V3 gives 0x77. Do not leave SDO open.
# The HandsOn guide says that module's address is hardwired to 0x76. If the
# SDO pin is tied to GND on the PCB and cannot be lifted, put the external
# sensor on I2C1 at 0x76 (see the commented example).

I2C_FREQ = 100000
I2C_TIMEOUT_US = 50000

INTERNAL_BMP280_ENABLED = False
INTERNAL_BMP280_ADDR = 0x76
INTERNAL_BMP280_I2C_ID = 0
INTERNAL_BMP280_SDA = 4
INTERNAL_BMP280_SCL = 5

EXTERNAL_BMP280_ENABLED = False
EXTERNAL_BMP280_ADDR = 0x77
EXTERNAL_BMP280_I2C_ID = 0
EXTERNAL_BMP280_SDA = 4
EXTERNAL_BMP280_SCL = 5
# Second-bus alternative when both modules are stuck at 0x76:
# EXTERNAL_BMP280_ADDR = 0x76
# EXTERNAL_BMP280_I2C_ID = 1
# EXTERNAL_BMP280_SDA = 6
# EXTERNAL_BMP280_SCL = 7

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

# Optional trim from (internal Pa - external Pa). Off by default.
# exhaust duty += gain * (delta_pa - target_pa), then clamped to 0..1.
PRESSURE_LOOP_ENABLED = False
PRESSURE_TARGET_PA = 5.0
PRESSURE_LOOP_GAIN = 0.002
