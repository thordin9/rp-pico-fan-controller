"""
Raspberry Pi Pico W — 4-fan thermal PWM controller + local status page.

One shared 25 kHz PWM (GP15) drives all fans at the same duty. Four tach
inputs (GP14–GP11) count RPM independently. ADC(4) is RP2040 *die*
temperature (not ambient); the curve keeps ~30 °C idle die on a quiet floor.

Optional Wi-Fi (Pico W): edit config.py, then open http://<pico-ip>/.
"""

import time
import machine

try:
    import config
except ImportError:
    config = None

# ---------------------------------------------------------------------------
# Hardware / thermal configuration
# ---------------------------------------------------------------------------

# Shared PWM — tee this one signal to every fan PWM wire (pin 4).
PWM_PIN = 15
PWM_FREQ_HZ = 25_000

# Per-fan tach inputs (open-collector; internal pull-up). Do NOT parallel tach.
# Fan index 0..3 → GP14, GP13, GP12, GP11 (adjacent GPIOs for tidy wiring).
TACH_PINS = (14, 13, 12, 11)
FAN_COUNT = len(TACH_PINS)

# Thermal curve — DIE °C via ADC(4), not ambient air.
MIN_TEMP_C = 35.0
MAX_TEMP_C = 55.0
MIN_SPEED = 0.18

SAMPLE_PERIOD_S = 1.0
SPINUP_DUTY = 0.60
SPINUP_TIME_S = 1.5
RPM_PULSES_PER_REV = 2
RPM_EMA_ALPHA = 0.35
RPM_MAX_PLAUSIBLE = 10_000

HTTP_POLL_MS = 50  # how often the main loop services HTTP accepts

# ---------------------------------------------------------------------------
# Shared runtime status (read by the web page)
# ---------------------------------------------------------------------------

_status = {
    "die_c": 0.0,
    "duty": 0.0,
    "rpm": [0.0] * FAN_COUNT,
    "uptime_s": 0,
    "wifi": "offline",
    "ip": "",
    "ssid": "",
}

# ---------------------------------------------------------------------------
# Board detection / LED
# ---------------------------------------------------------------------------

def _make_led():
    try:
        return machine.Pin("LED", machine.Pin.OUT)
    except (ValueError, TypeError, AttributeError):
        return machine.Pin(25, machine.Pin.OUT)


led = _make_led()

# ---------------------------------------------------------------------------
# PWM + temperature
# ---------------------------------------------------------------------------

pwm = machine.PWM(machine.Pin(PWM_PIN))
pwm.freq(PWM_FREQ_HZ)
temp_adc = machine.ADC(4)

# ---------------------------------------------------------------------------
# Per-fan tach — IRQ pulse counting with atomic snapshot
# ---------------------------------------------------------------------------

_pulse_counts = [0] * FAN_COUNT
_tach_pins = []


def _make_tach_handler(index):
    def _handler(_pin):
        _pulse_counts[index] += 1

    return _handler


for i, gp in enumerate(TACH_PINS):
    pin = machine.Pin(gp, machine.Pin.IN, machine.Pin.PULL_UP)
    pin.irq(trigger=machine.Pin.IRQ_RISING, handler=_make_tach_handler(i))
    _tach_pins.append(pin)


def take_pulse_counts():
    """Atomically read and clear all tach counters. Returns a list of ints."""
    state = machine.disable_irq()
    try:
        counts = list(_pulse_counts)
        for i in range(FAN_COUNT):
            _pulse_counts[i] = 0
    finally:
        machine.enable_irq(state)
    return counts


# ---------------------------------------------------------------------------
# Control helpers
# ---------------------------------------------------------------------------

def set_duty(fraction):
    if fraction < 0.0:
        fraction = 0.0
    elif fraction > 1.0:
        fraction = 1.0
    pwm.duty_u16(int(fraction * 65535))
    return fraction


def read_die_temp_c():
    raw = temp_adc.read_u16()
    voltage = raw * 3.3 / 65535
    return 27.0 - (voltage - 0.706) / 0.001721


def temp_to_duty(temp_c):
    if temp_c <= MIN_TEMP_C:
        return MIN_SPEED
    if temp_c >= MAX_TEMP_C:
        return 1.0
    span = MAX_TEMP_C - MIN_TEMP_C
    return MIN_SPEED + (1.0 - MIN_SPEED) * ((temp_c - MIN_TEMP_C) / span)


def pulses_to_rpm(pulses, elapsed_s):
    if elapsed_s <= 0:
        return 0
    rpm = (pulses / RPM_PULSES_PER_REV) * (60.0 / elapsed_s)
    if rpm < 0:
        return 0
    if rpm > RPM_MAX_PLAUSIBLE:
        return RPM_MAX_PLAUSIBLE
    return int(rpm)


def failsafe():
    try:
        set_duty(1.0)
    except Exception:
        pass
    try:
        led.value(1)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Wi-Fi + tiny HTTP status server (stdlib sockets)
# ---------------------------------------------------------------------------

_http_sock = None


def _wifi_wanted():
    if config is None or not getattr(config, "WIFI_ENABLED", True):
        return False
    ssid = getattr(config, "WIFI_SSID", "") or ""
    if not ssid or ssid == "YOUR_SSID":
        return False
    return True


def connect_wifi():
    """Associate as station. Returns (ok, ip_or_reason)."""
    if not _wifi_wanted():
        _status["wifi"] = "disabled"
        _status["ip"] = ""
        _status["ssid"] = ""
        return False, "Wi-Fi disabled or placeholder SSID in config.py"

    try:
        import network
    except ImportError:
        _status["wifi"] = "unsupported"
        return False, "network module missing (need Pico W MicroPython)"

    ssid = config.WIFI_SSID
    password = getattr(config, "WIFI_PASSWORD", "") or ""
    timeout_s = getattr(config, "WIFI_TIMEOUT_S", 20)

    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    if not wlan.isconnected():
        print("Wi-Fi: connecting to {!r} …".format(ssid))
        wlan.connect(ssid, password)
        deadline = time.ticks_add(time.ticks_ms(), int(timeout_s * 1000))
        while not wlan.isconnected():
            if time.ticks_diff(deadline, time.ticks_ms()) <= 0:
                _status["wifi"] = "timeout"
                _status["ssid"] = ssid
                return False, "association timed out"
            time.sleep_ms(200)

    ip = wlan.ifconfig()[0]
    _status["wifi"] = "connected"
    _status["ip"] = ip
    _status["ssid"] = ssid
    print("Wi-Fi: connected, IP={}".format(ip))
    return True, ip


def start_http_server():
    """Bind a non-blocking listen socket. Returns True on success."""
    global _http_sock
    try:
        import socket
    except ImportError:
        return False

    port = getattr(config, "HTTP_PORT", 80) if config else 80
    sock = socket.socket()
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    except Exception:
        pass
    try:
        sock.bind(("0.0.0.0", port))
        sock.listen(2)
        sock.setblocking(False)
    except OSError as exc:
        print("HTTP: bind failed:", exc)
        try:
            sock.close()
        except Exception:
            pass
        return False

    _http_sock = sock
    print("HTTP: listening on port {}".format(port))
    return True


def _html_escape(text):
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _format_status_json():
    rpm = _status["rpm"]
    parts = [
        '{{"die_c":{:.1f},"duty":{:.3f},"duty_pct":{:.0f}'.format(
            _status["die_c"], _status["duty"], _status["duty"] * 100
        ),
        ',"rpm":[{}]'.format(",".join("{:.0f}".format(r) for r in rpm)),
        ',"uptime_s":{}'.format(int(_status["uptime_s"])),
        ',"wifi":"{}"'.format(_status["wifi"]),
        ',"ip":"{}"'.format(_status["ip"]),
        ',"ssid":"{}"'.format(_html_escape(_status["ssid"]).replace("\\", "")),
        "}",
    ]
    return "".join(parts)


def _format_status_html():
    rpm_rows = "".join(
        "<tr><td>Fan {}</td><td class='num'>{:.0f}</td></tr>".format(i + 1, _status["rpm"][i])
        for i in range(FAN_COUNT)
    )
    return """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="2">
<title>Pico Fan Controller</title>
<style>
  :root {{ color-scheme: light dark; }}
  body {{ font-family: ui-sans-serif, system-ui, sans-serif; margin: 1.5rem; line-height: 1.4; }}
  h1 {{ font-size: 1.25rem; margin: 0 0 0.75rem; }}
  table {{ border-collapse: collapse; width: min(24rem, 100%); }}
  th, td {{ text-align: left; padding: 0.35rem 0.5rem; border-bottom: 1px solid #8884; }}
  .num {{ text-align: right; font-variant-numeric: tabular-nums; }}
  .muted {{ opacity: 0.7; font-size: 0.9rem; }}
</style>
</head>
<body>
<h1>Pico W fan controller</h1>
<p class="muted">Die sensor (ADC4) · shared PWM · auto-refresh 2s ·
  <a href="/status.json">JSON</a></p>
<table>
  <tr><th>Metric</th><th class="num">Value</th></tr>
  <tr><td>Die temp</td><td class="num">{:.1f} °C</td></tr>
  <tr><td>PWM duty</td><td class="num">{:.0f}%</td></tr>
  <tr><td>Uptime</td><td class="num">{} s</td></tr>
  <tr><td>Wi-Fi</td><td class="num">{}</td></tr>
  <tr><td>IP</td><td class="num">{}</td></tr>
  <tr><td>SSID</td><td class="num">{}</td></tr>
  {}
</table>
</body>
</html>
""".format(
        _status["die_c"],
        _status["duty"] * 100,
        int(_status["uptime_s"]),
        _html_escape(_status["wifi"]),
        _html_escape(_status["ip"] or "—"),
        _html_escape(_status["ssid"] or "—"),
        rpm_rows,
    )


def _http_response(body, content_type="text/html; charset=utf-8", code=200):
    reason = {200: "OK", 404: "Not Found", 405: "Method Not Allowed"}.get(code, "OK")
    header = (
        "HTTP/1.0 {} {}\r\n"
        "Content-Type: {}\r\n"
        "Content-Length: {}\r\n"
        "Connection: close\r\n"
        "Cache-Control: no-store\r\n"
        "\r\n"
    ).format(code, reason, content_type, len(body))
    if isinstance(body, str):
        body = body.encode()
    return header.encode() + body


def poll_http():
    """Accept and answer at most one pending HTTP request (non-blocking)."""
    if _http_sock is None:
        return
    try:
        conn, _addr = _http_sock.accept()
    except OSError:
        return

    try:
        conn.settimeout(1.0)
        req = b""
        while b"\r\n\r\n" not in req and len(req) < 1024:
            chunk = conn.recv(256)
            if not chunk:
                break
            req += chunk
        line = req.split(b"\r\n", 1)[0] if req else b""
        parts = line.split()
        method = parts[0] if len(parts) > 0 else b"GET"
        path = parts[1] if len(parts) > 1 else b"/"

        if method != b"GET":
            resp = _http_response("Method Not Allowed", "text/plain", 405)
        elif path in (b"/", b"/index.html"):
            resp = _http_response(_format_status_html())
        elif path in (b"/status.json", b"/api", b"/api/status"):
            resp = _http_response(_format_status_json(), "application/json")
        else:
            resp = _http_response("Not Found", "text/plain", 404)

        conn.sendall(resp)
    except Exception as exc:
        print("HTTP: request error:", exc)
    finally:
        try:
            conn.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def main():
    boot_ms = time.ticks_ms()
    print("Pico thermal fan controller ({} fans, shared PWM)".format(FAN_COUNT))
    print(
        "Die curve: {:.0f}°C → {:.0%} … {:.0f}°C → 100%  (ADC4 = die, not ambient)".format(
            MIN_TEMP_C, MIN_SPEED, MAX_TEMP_C
        )
    )
    print(
        "PWM GP{} @ {} Hz | Tach {}".format(
            PWM_PIN,
            PWM_FREQ_HZ,
            ", ".join("F{}=GP{}".format(i + 1, gp) for i, gp in enumerate(TACH_PINS)),
        )
    )

    ok, detail = connect_wifi()
    if ok:
        start_http_server()
        print("Status page: http://{}/".format(detail))
    else:
        print("Wi-Fi skipped:", detail)

    led.value(1)
    set_duty(SPINUP_DUTY)
    time.sleep(SPINUP_TIME_S)
    take_pulse_counts()

    rpm_smooth = [0.0] * FAN_COUNT
    last = time.ticks_ms()
    last_http = last

    while True:
        now = time.ticks_ms()

        if time.ticks_diff(now, last_http) >= HTTP_POLL_MS:
            last_http = now
            poll_http()

        elapsed_ms = time.ticks_diff(now, last)
        if elapsed_ms < int(SAMPLE_PERIOD_S * 1000):
            time.sleep_ms(10)
            continue
        last = now
        elapsed_s = elapsed_ms / 1000.0

        temp_c = read_die_temp_c()
        duty = temp_to_duty(temp_c)
        set_duty(duty)

        counts = take_pulse_counts()
        for i, pulses in enumerate(counts):
            rpm = pulses_to_rpm(pulses, elapsed_s)
            rpm_smooth[i] = (RPM_EMA_ALPHA * rpm) + ((1.0 - RPM_EMA_ALPHA) * rpm_smooth[i])

        _status["die_c"] = temp_c
        _status["duty"] = duty
        _status["rpm"] = list(rpm_smooth)
        _status["uptime_s"] = time.ticks_diff(now, boot_ms) // 1000

        led.value(1 if duty >= 0.5 else (1 if (now // 500) % 2 == 0 else 0))

        rpm_txt = " ".join(
            "F{}={:4.0f}".format(i + 1, rpm_smooth[i]) for i in range(FAN_COUNT)
        )
        print("die={:5.1f}°C  duty={:3.0%}  {}".format(temp_c, duty, rpm_txt))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nInterrupted — fail-safe: fan 100%, LED on")
        failsafe()
    except Exception as exc:
        print("Error:", exc)
        failsafe()
        raise
