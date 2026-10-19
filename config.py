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
