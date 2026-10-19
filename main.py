"""
Raspberry Pi Pico W — 4-fan thermal PWM controller + web control + Prometheus.

Per-fan PWM (GP15–18) with independent tach (GP14–11). Auto fans follow the
die-temp curve; manual overrides persist in overrides.json. Optional Wi-Fi
serves / (control UI), /status.json, and /metrics.

Fans are brought up before any network wait. Wi-Fi association is polled
from the main loop so a dropout reconnects without blocking fan control.
"""

import time
import machine

try:
    import config
except ImportError:
    config = None

import fan
from web import HttpServer, resolve_auth, AUTH_DISABLED_WARNING
import metrics
import wifi

HTTP_POLL_MS = 50
HTTP_RESTART_MS = 2000
WIFI_POLL_MS = 500
# RP2040 watchdog is a 24-bit counter at 1 µs. MicroPython rejects above this.
WDT_HW_MAX_MS = 8388

_ctrl = None
_wdt = None


def _feed_wdt():
    if _wdt is not None:
        _wdt.feed()


def _make_led():
    try:
        return machine.Pin("LED", machine.Pin.OUT)
    except (ValueError, TypeError, AttributeError):
        return machine.Pin(25, machine.Pin.OUT)


def _cfg(name, default):
    if config is None:
        return default
    return getattr(config, name, default)


def clamp_wdt_timeout_ms(timeout_ms, hw_max=WDT_HW_MAX_MS):
    """Clamp a requested watchdog timeout into the RP2040's legal range."""
    try:
        timeout = int(timeout_ms)
    except (TypeError, ValueError):
        return None
    if timeout > hw_max:
        return hw_max
    if timeout < 1:
        return 1
    return timeout


def _wifi_wanted():
    if not _cfg("WIFI_ENABLED", True):
        return False
    ssid = _cfg("WIFI_SSID", "") or ""
    if not ssid or ssid == "YOUR_SSID":
        return False
    return True


def _start_wdt():
    global _wdt
    if not _cfg("WDT_ENABLED", True):
        print("WDT: disabled in config")
        _wdt = None
        return None
    requested = _cfg("WDT_TIMEOUT_MS", 8000)
    timeout = clamp_wdt_timeout_ms(requested)
    if timeout is None:
        print("WDT: invalid timeout {!r}; watchdog not started".format(requested))
        _wdt = None
        return None
    if timeout != int(requested):
        print(
            "WDT: timeout {} ms adjusted to {} ms (RP2040 allows 1..{})".format(
                requested, timeout, WDT_HW_MAX_MS
            )
        )
    try:
        _wdt = machine.WDT(timeout=timeout)
    except Exception as exc:
        print("WDT: not started:", exc)
        _wdt = None
        return None
    print("WDT: armed, timeout {} ms".format(timeout))
    _feed_wdt()
    return _wdt


def _open_wlan():
    import network

    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    return wlan


def _host_for_url(ip, port):
    if int(port) == 80:
        return str(ip)
    return "{}:{}".format(ip, port)


def _start_http(ctrl, auth):
    http = HttpServer(
        ctrl,
        metrics,
        auth=auth,
        metrics_require_auth=bool(_cfg("METRICS_REQUIRE_AUTH", True)),
    )
    port = int(_cfg("HTTP_PORT", 80))
    if not http.start(port):
        return None
    host = _host_for_url(ctrl.ip, port)
    print("Control page: http://{}/".format(host))
    print("Metrics: http://{}/metrics".format(host))
    return http


def main():
    global _ctrl
    led = _make_led()
    ctrl = fan.FanController(
        stall_duty_min=_cfg("STALL_DUTY_MIN", fan.STALL_DUTY_MIN),
        stall_rpm_below=_cfg("STALL_RPM_BELOW", fan.STALL_RPM_BELOW),
    )
    ctrl.init_hardware()
    _ctrl = ctrl
    boot_ms = time.ticks_ms()

    # Safe PWM before banners or any network wait: spin-up, then the curve
    # or saved overrides. Hardware holds that duty while Wi-Fi comes up.
    led.value(1)
    overrides_loaded = ctrl.prepare_fans(feed=_feed_wdt)
    _feed_wdt()

    print("Pico thermal fan controller ({} fans, per-fan PWM)".format(fan.FAN_COUNT))
    print(
        "Die curve: {:.0f}°C → {:.0%} … {:.0f}°C → 100%  (ADC4 = die, not ambient)".format(
            fan.MIN_TEMP_C, fan.MIN_SPEED, fan.MAX_TEMP_C
        )
    )
    print(
        "PWM {} @ {} Hz | Tach {}".format(
            ", ".join("F{}=GP{}".format(i + 1, gp) for i, gp in enumerate(fan.PWM_PINS)),
            fan.PWM_FREQ_HZ,
            ", ".join("F{}=GP{}".format(i + 1, gp) for i, gp in enumerate(fan.TACH_PINS)),
        )
    )
    if overrides_loaded:
        print("Loaded overrides from", fan.OVERRIDES_PATH)
    else:
        print("No overrides file — all fans auto")

    auth = resolve_auth(_cfg("HTTP_USER", ""), _cfg("HTTP_PASSWORD", ""))
    if auth is None:
        print(AUTH_DISABLED_WARNING)
    else:
        print("HTTP: basic auth enabled")

    mon = wifi.WifiMonitor(
        ctrl,
        ssid=_cfg("WIFI_SSID", "") or "",
        password=_cfg("WIFI_PASSWORD", "") or "",
        timeout_s=_cfg("WIFI_TIMEOUT_S", 20),
        retry_s=_cfg("WIFI_RETRY_S", 10),
    )
    if not _wifi_wanted():
        mon.mark_disabled("disabled")
        print("Wi-Fi skipped: disabled or placeholder SSID in config.py")
    else:
        try:
            _feed_wdt()
            print("Wi-Fi: starting radio")
            wlan = _open_wlan()
            _feed_wdt()
            mon.attach(wlan)
            mon.start_attempt(time.ticks_ms())
        except ImportError:
            mon.mark_disabled("unsupported")
            print("Wi-Fi skipped: network module missing (need Pico W MicroPython)")
        except Exception as exc:
            mon.mark_disabled("offline")
            print("Wi-Fi: radio init failed:", exc)

    # Arm only after radio init. wlan.active(True) can block for seconds and
    # must not trip the watchdog. Association itself is polled below, and the
    # loop feeds on every pass, including the fast 10 ms sleep.
    _start_wdt()

    http = None
    last = time.ticks_ms()
    last_http = last
    last_wifi = last
    last_http_start = None
    uptime_ms = time.ticks_diff(last, boot_ms)
    if uptime_ms < 0:
        uptime_ms = 0
    while True:
        _feed_wdt()
        now = time.ticks_ms()

        if time.ticks_diff(now, last_wifi) >= WIFI_POLL_MS:
            last_wifi = now
            mon.poll(now)
        if http is not None and not http.is_listening():
            http = None
        if http is None and ctrl.wifi == "connected":
            if (
                last_http_start is None
                or time.ticks_diff(now, last_http_start) >= HTTP_RESTART_MS
            ):
                last_http_start = now
                http = _start_http(ctrl, auth)

        if http is not None and time.ticks_diff(now, last_http) >= HTTP_POLL_MS:
            last_http = now
            http.poll(now)

        # Blink from the fast path. The sample branch runs only once a second,
        # which is too slow to show a 500 ms phase.
        elapsed_boot = time.ticks_diff(now, boot_ms)
        duty_max = max(ctrl.duties)
        led.value(1 if fan.led_is_on(duty_max, elapsed_boot) else 0)

        elapsed_ms = time.ticks_diff(now, last)
        if elapsed_ms < int(fan.SAMPLE_PERIOD_S * 1000):
            time.sleep_ms(10)
            continue
        last = now
        elapsed_s = elapsed_ms / 1000.0
        # Accumulate in a Python int. ticks_diff(now, boot) wraps after ~6 days.
        uptime_ms += elapsed_ms
        ctrl.tick(elapsed_s)
        ctrl.uptime_s = uptime_ms // 1000

        parts = " ".join(
            "F{}={}={:3.0%}={:4.0f}{}".format(
                i + 1,
                ctrl.modes[i][0],
                ctrl.duties[i],
                ctrl.rpms[i],
                "!" if ctrl.stalls[i] else "",
            )
            for i in range(fan.FAN_COUNT)
        )
        print(
            "die={:5.1f}°C  {}  wifi={}".format(ctrl.die_c, parts, ctrl.wifi)
        )


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nInterrupted — fail-safe: fans 100%, LED on")
        if _ctrl is not None:
            _ctrl.failsafe()
        try:
            _make_led().value(1)
        except Exception:
            pass
    except Exception as exc:
        print("Error:", exc)
        if _ctrl is not None:
            _ctrl.failsafe()
        try:
            _make_led().value(1)
        except Exception:
            pass
        raise
