"""
Local settings for the Pico W fan controller.

Edit WIFI_SSID / WIFI_PASSWORD before flashing. Do not commit real secrets
to a public fork — keep this file private or use placeholders in shared remotes.
"""

# Wi-Fi (Pico W station mode). Leave placeholders to skip networking.
WIFI_SSID = "YOUR_SSID"
WIFI_PASSWORD = "YOUR_PASSWORD"

# How long to wait for an association / IP before giving up (fan control still runs).
WIFI_TIMEOUT_S = 20

# HTTP status page (stdlib sockets; no extra deps).
HTTP_PORT = 80

# Set False on classic Pico (no radio) or to force offline fan-only mode.
WIFI_ENABLED = True
