"""Non-blocking Pico W station monitor.

The main loop calls poll() with a millisecond timestamp. Association waits
happen between polls, so fan control and the watchdog keep running.
"""

# MicroPython ticks_ms / ticks_us wrap every 2**30 ticks.
_TICKS_MASK = 0x3FFFFFFF
_TICKS_PERIOD = 0x40000000
_TICKS_HALF = 0x20000000

# Wait this long after a dropout before connect(), so a one-sample
# isconnected() blip does not tear the link down.
RECONNECT_GRACE_S = 1


def ticks_diff(ticks1, ticks2):
    """Return ticks1 - ticks2 with MicroPython's 30-bit wrap."""
    diff = (int(ticks1) - int(ticks2)) & _TICKS_MASK
    if diff >= _TICKS_HALF:
        diff -= _TICKS_PERIOD
    return diff


def ticks_add(ticks, delta):
    return (int(ticks) + int(delta)) & _TICKS_MASK


class WifiMonitor:
    """Track STA association and reconnect without sleeping.

    ``wlan`` is a network.WLAN-like object (or a test double) with
    active/connect/disconnect/isconnected/ifconfig. Pass None until the
    radio has been brought up.
    """

    def __init__(self, ctrl, ssid, password, timeout_s=20, retry_s=10, grace_s=RECONNECT_GRACE_S):
        self.ctrl = ctrl
        self.ssid = ssid or ""
        self.password = password or ""
        self.timeout_ms = int(float(timeout_s) * 1000)
        self.retry_ms = int(float(retry_s) * 1000)
        self.grace_ms = int(float(grace_s) * 1000)
        self.wlan = None
        # idle | disabled | unsupported | connecting | connected | offline | timeout
        self.state = "idle"
        self._attempt_start = 0
        self._next_attempt = 0

    def mark_disabled(self, reason):
        """reason is 'disabled' or 'unsupported' (or 'offline' after radio failure)."""
        self.wlan = None
        self.state = reason
        self.ctrl.wifi = reason
        self.ctrl.ip = ""

    def attach(self, wlan):
        self.wlan = wlan

    def start_attempt(self, now_ms):
        """Begin the first association. Returns immediately."""
        if self.wlan is None:
            return self.state
        self.ctrl.ssid = self.ssid
        try:
            if self.wlan.isconnected():
                self._mark_connected()
                return self.state
        except Exception as exc:
            print("Wi-Fi: status error:", exc)
        self._begin(now_ms)
        return self.state

    def poll(self, now_ms):
        """Refresh ctrl.wifi / ctrl.ip. Never sleeps. Returns the state name."""
        if self.wlan is None:
            return self.state
        try:
            connected = bool(self.wlan.isconnected())
        except Exception as exc:
            print("Wi-Fi: status error:", exc)
            return self.state

        if connected:
            self._mark_connected()
            return self.state

        if self.state == "connected":
            print("Wi-Fi: link down")
            self.state = "offline"
            self.ctrl.wifi = "offline"
            self.ctrl.ip = ""
            self._next_attempt = ticks_add(now_ms, self.grace_ms)
            return self.state

        if self.state == "connecting":
            if ticks_diff(now_ms, self._attempt_start) >= self.timeout_ms:
                print("Wi-Fi: association timed out")
                self.state = "timeout"
                self.ctrl.wifi = "timeout"
                self.ctrl.ip = ""
                self._next_attempt = ticks_add(now_ms, self.retry_ms)
                self._disconnect()
            return self.state

        if self.state in ("offline", "timeout", "idle"):
            if ticks_diff(now_ms, self._next_attempt) >= 0:
                self._begin(now_ms)
        return self.state

    def _mark_connected(self):
        ip = ""
        try:
            ip = self.wlan.ifconfig()[0]
        except Exception as exc:
            print("Wi-Fi: ifconfig error:", exc)
        transition = self.state != "connected"
        self.state = "connected"
        self.ctrl.wifi = "connected"
        self.ctrl.ip = ip or ""
        self.ctrl.ssid = self.ssid
        if transition:
            print("Wi-Fi: connected, IP={}".format(self.ctrl.ip))

    def _disconnect(self):
        try:
            self.wlan.disconnect()
        except Exception:
            pass

    def _begin(self, now_ms):
        self._disconnect()
        try:
            self.wlan.connect(self.ssid, self.password)
        except Exception as exc:
            print("Wi-Fi: connect error:", exc)
            self.state = "timeout"
            self.ctrl.wifi = "timeout"
            self.ctrl.ip = ""
            self._next_attempt = ticks_add(now_ms, self.retry_ms)
            return
        try:
            if self.wlan.isconnected():
                self._mark_connected()
                return
        except Exception as exc:
            print("Wi-Fi: status error:", exc)
        print("Wi-Fi: connecting to {!r}".format(self.ssid))
        self.state = "connecting"
        self.ctrl.wifi = "connecting"
        self.ctrl.ip = ""
        self._attempt_start = now_ms
