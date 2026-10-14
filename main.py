"""
Raspberry Pi Pico W — 4-fan thermal PWM controller + web control + Prometheus.

Per-fan PWM (GP15–18) with independent tach (GP14–11). Auto fans follow the
die-temp curve; manual overrides persist in overrides.json. Optional Wi-Fi
serves / (control UI), /status.json, and /metrics.
"""

import time
import machine

try:
    import config
except ImportError:
    config = None

import fan
from web import HttpServer
import metrics

HTTP_POLL_MS = 50

_ctrl = None


def _make_led():
    try:
        return machine.Pin("LED", machine.Pin.OUT)
    except (ValueError, TypeError, AttributeError):
        return machine.Pin(25, machine.Pin.OUT)


def _wifi_wanted():
    if config is None or not getattr(config, "WIFI_ENABLED", True):
        return False
    ssid = getattr(config, "WIFI_SSID", "") or ""
    if not ssid or ssid == "YOUR_SSID":
        return False
    return True


def connect_wifi(ctrl):
    if not _wifi_wanted():
        ctrl.wifi = "disabled"
        return False, "Wi-Fi disabled or placeholder SSID in config.py"
    try:
        import network
    except ImportError:
        ctrl.wifi = "unsupported"
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
                ctrl.wifi = "timeout"
                ctrl.ssid = ssid
                return False, "association timed out"
            time.sleep_ms(200)
    ip = wlan.ifconfig()[0]
    ctrl.wifi = "connected"
    ctrl.ip = ip
    ctrl.ssid = ssid
    print("Wi-Fi: connected, IP={}".format(ip))
    return True, ip


def main():
    global _ctrl
    led = _make_led()
    ctrl = fan.FanController()
    ctrl.init_hardware()
    _ctrl = ctrl
    boot_ms = time.ticks_ms()

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

    http = None
    ok, detail = connect_wifi(ctrl)
    if ok:
        http = HttpServer(ctrl, metrics)
        port = getattr(config, "HTTP_PORT", 80) if config else 80
        if http.start(port):
            print("Control page: http://{}/".format(detail))
            print("Metrics: http://{}/metrics".format(detail))
        else:
            http = None
    else:
        print("Wi-Fi skipped:", detail)

    led.value(1)
    ctrl.spinup()
    ctrl.die_c = ctrl.hw.read_die_temp_c()
    if ctrl.load_overrides():
        print("Loaded overrides from", fan.OVERRIDES_PATH)
    else:
        print("No overrides file — all fans auto")

    last = time.ticks_ms()
    last_http = last
    while True:
        now = time.ticks_ms()
        if http is not None and time.ticks_diff(now, last_http) >= HTTP_POLL_MS:
            last_http = now
            http.poll()

        elapsed_ms = time.ticks_diff(now, last)
        if elapsed_ms < int(fan.SAMPLE_PERIOD_S * 1000):
            time.sleep_ms(10)
            continue
        last = now
        elapsed_s = elapsed_ms / 1000.0
        ctrl.tick(elapsed_s)
        ctrl.uptime_s = time.ticks_diff(now, boot_ms) // 1000

        duty_max = max(ctrl.duties)
        led.value(1 if duty_max >= 0.5 else (1 if (now // 500) % 2 == 0 else 0))

        parts = " ".join(
            "F{}={}={:3.0%}={:4.0f}".format(
                i + 1, ctrl.modes[i][0], ctrl.duties[i], ctrl.rpms[i]
            )
            for i in range(fan.FAN_COUNT)
        )
        print("die={:5.1f}°C  {}".format(ctrl.die_c, parts))


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
