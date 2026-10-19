"""Sanity checks for sensor values that must not drive the fans.

BMP280 samples are rejected for range, a sudden jump, identical raw values,
a failed read, or a stale read. The RP2040 die temperature, tach RPM, and
the internal-minus-external pressure difference have their own checks.

A rejected sample is not used for the thermal curve or the pressure loop.
The fault badge latches after a few consecutive bad samples and clears
after a few consecutive good ones, so one glitch does not flap the UI.

Reason strings are a closed set. Prometheus uses them as a label and must
not get a free-text message.
"""

REASON_TEMP_RANGE = "temp_out_of_range"
REASON_PRESS_RANGE = "pressure_out_of_range"
REASON_TEMP_JUMP = "temp_jump"
REASON_PRESS_JUMP = "pressure_jump"
REASON_STUCK = "stuck"
REASON_STALE = "stale"
REASON_READ = "read_failed"
REASON_DIE_RANGE = "die_out_of_range"
REASON_DIE_JUMP = "die_jump"
REASON_RPM_HIGH = "rpm_high"
REASON_RPM_ZERO = "rpm_at_zero_duty"
REASON_DELTA = "pressure_delta"

REASONS = (
    REASON_TEMP_RANGE,
    REASON_PRESS_RANGE,
    REASON_TEMP_JUMP,
    REASON_PRESS_JUMP,
    REASON_STUCK,
    REASON_STALE,
    REASON_READ,
    REASON_DIE_RANGE,
    REASON_DIE_JUMP,
    REASON_RPM_HIGH,
    REASON_RPM_ZERO,
    REASON_DELTA,
)

SENSORS = ("bmp280", "die", "tach", "pressure")
LOCATIONS = ("internal", "external", "die", "delta", "1", "2", "3", "4")

# Human text for the web badge. The token stays in fault_reason.
REASON_TEXT = {
    REASON_TEMP_RANGE: "temperature out of range",
    REASON_PRESS_RANGE: "pressure out of range",
    REASON_TEMP_JUMP: "temperature jumped",
    REASON_PRESS_JUMP: "pressure jumped",
    REASON_STUCK: "reading stuck",
    REASON_STALE: "reading stale",
    REASON_READ: "read failed",
    REASON_DIE_RANGE: "temperature out of range",
    REASON_DIE_JUMP: "temperature jumped",
    REASON_RPM_HIGH: "rpm out of range",
    REASON_RPM_ZERO: "rpm while stopped",
    REASON_DELTA: "pressure difference out of range",
}

REASON_SHORT = {
    REASON_TEMP_RANGE: "temp range",
    REASON_PRESS_RANGE: "pressure range",
    REASON_TEMP_JUMP: "temp jump",
    REASON_PRESS_JUMP: "pressure jump",
    REASON_STUCK: "stuck",
    REASON_STALE: "stale",
    REASON_READ: "read failed",
    REASON_DIE_RANGE: "temp range",
    REASON_DIE_JUMP: "temp jump",
    REASON_RPM_HIGH: "rpm high",
    REASON_RPM_ZERO: "rpm at 0 duty",
    REASON_DELTA: "delta range",
}

SENSOR_NAME = {
    ("bmp280", "internal"): "Internal BMP280",
    ("bmp280", "external"): "External BMP280",
    ("die", "die"): "RP2040 die",
    ("tach", "1"): "Fan 1 tach",
    ("tach", "2"): "Fan 2 tach",
    ("tach", "3"): "Fan 3 tach",
    ("tach", "4"): "Fan 4 tach",
    ("pressure", "delta"): "Pressure difference",
}

SENSOR_SHORT = {
    ("bmp280", "internal"): "INT BMP280",
    ("bmp280", "external"): "EXT BMP280",
    ("die", "die"): "DIE TEMP",
    ("tach", "1"): "TACH 1",
    ("tach", "2"): "TACH 2",
    ("tach", "3"): "TACH 3",
    ("tach", "4"): "TACH 4",
    ("pressure", "delta"): "PRESSURE dP",
}

# Defaults match config.py. Operating limits are the BMP280 datasheet
# range (-40..85 °C, 300..1100 hPa). Jumps are per 1 s sample.
DEFAULT_CFG = {
    "bmp280_temp_min_c": -40.0,
    "bmp280_temp_max_c": 85.0,
    "bmp280_temp_jump_c": 10.0,
    "bmp280_press_min_pa": 30000.0,
    "bmp280_press_max_pa": 110000.0,
    "bmp280_press_jump_pa": 1000.0,
    "bmp280_stuck_samples": 30,
    "sensor_fault_set_samples": 2,
    "sensor_fault_clear_samples": 3,
    "sensor_stale_s": 5,
    "die_temp_min_c": -20.0,
    "die_temp_max_c": 100.0,
    "die_temp_jump_c": 15.0,
    "tach_rpm_max": 10000,
    "tach_zero_duty_rpm": 1,
    "pressure_delta_max_pa": 2000.0,
}

_TICKS_MASK = 0x3FFFFFFF
_TICKS_HALF = 0x20000000


def is_finite(value):
    """True for a real number that is not NaN or infinity."""
    try:
        value = float(value)
    except (TypeError, ValueError):
        return False
    if value != value:
        return False
    if value == float("inf") or value == float("-inf"):
        return False
    return True


def age_ms(now_ms, then_ms):
    """Milliseconds from then to now, using 30-bit tick wrap. None if unknown."""
    if now_ms is None or then_ms is None:
        return None
    try:
        diff = (int(now_ms) - int(then_ms)) & _TICKS_MASK
    except (TypeError, ValueError):
        return None
    if diff >= _TICKS_HALF:
        diff -= 0x40000000
    if diff < 0:
        return None
    return diff


def fault_label(sensor, location, reason):
    """Web badge, e.g. 'External BMP280: possible fault – pressure out of range'."""
    name = SENSOR_NAME.get((sensor, location), sensor)
    text = REASON_TEXT.get(reason, "fault")
    return "{}: possible fault \u2013 {}".format(name, text)


def fault_row(sensor, location, reason):
    return {
        "sensor": sensor,
        "location": location,
        "reason": reason,
        "label": fault_label(sensor, location, reason),
        "short": SENSOR_SHORT.get((sensor, location), "SENSOR"),
        "short_reason": REASON_SHORT.get(reason, "fault"),
    }


class Latch:
    """Debounce a fault on and off.

    ``push`` returns ``(use_sample, latched_reason, newly_latched)``.
    A bad sample is never used. A good sample is used only once any latched
    fault has seen ``clear_n`` good samples in a row.
    """

    def __init__(self, set_n, clear_n):
        self.set_n = 1 if int(set_n) < 1 else int(set_n)
        self.clear_n = 1 if int(clear_n) < 1 else int(clear_n)
        self.reason = ""
        self._pending = ""
        self._bad = 0
        self._good = 0

    def push(self, reason):
        if reason:
            self._good = 0
            if reason != self._pending:
                self._pending = reason
                self._bad = 1
            else:
                self._bad += 1
            newly = False
            if self.reason and self.reason != reason:
                # Already faulted: the badge follows the current cause.
                self.reason = reason
                newly = True
            elif not self.reason and self._bad >= self.set_n:
                self.reason = reason
                newly = True
            return False, self.reason, newly
        self._bad = 0
        self._pending = ""
        if not self.reason:
            self._good = 0
            return True, "", False
        self._good += 1
        if self._good >= self.clear_n:
            self.reason = ""
            self._good = 0
            return True, "", False
        return False, self.reason, False


def _cfg_value(cfg, key):
    if cfg is not None and key in cfg:
        return cfg[key]
    return DEFAULT_CFG[key]


class _Channel:
    def __init__(self, latch):
        self.latch = latch
        self.prev_raw = None
        self.stuck = 0
        self.have = False
        self.good_a = None
        self.good_b = None
        self.candidate_a = None
        self.candidate_b = None
        self.last_ok_ms = None
        self.first_bad_ms = None

    def note_failure(self, now_ms):
        if self.first_bad_ms is None:
            self.first_bad_ms = now_ms

    def note_success(self, now_ms):
        self.first_bad_ms = None
        self.last_ok_ms = now_ms

    def is_stale(self, now_ms, stale_ms):
        if now_ms is None:
            return False
        anchor = self.last_ok_ms if self.last_ok_ms is not None else self.first_bad_ms
        if anchor is None:
            return False
        age = age_ms(now_ms, anchor)
        return age is not None and age > stale_ms


class FaultMonitor:
    """Tracks every sensor fault the controller reports."""

    def __init__(self, cfg=None, die_safe_c=55.0):
        self.bmp_temp_min = float(_cfg_value(cfg, "bmp280_temp_min_c"))
        self.bmp_temp_max = float(_cfg_value(cfg, "bmp280_temp_max_c"))
        self.bmp_temp_jump = float(_cfg_value(cfg, "bmp280_temp_jump_c"))
        self.bmp_press_min = float(_cfg_value(cfg, "bmp280_press_min_pa"))
        self.bmp_press_max = float(_cfg_value(cfg, "bmp280_press_max_pa"))
        self.bmp_press_jump = float(_cfg_value(cfg, "bmp280_press_jump_pa"))
        self.stuck_n = int(_cfg_value(cfg, "bmp280_stuck_samples"))
        set_n = int(_cfg_value(cfg, "sensor_fault_set_samples"))
        clear_n = int(_cfg_value(cfg, "sensor_fault_clear_samples"))
        self.stale_ms = int(float(_cfg_value(cfg, "sensor_stale_s")) * 1000)
        self.die_min = float(_cfg_value(cfg, "die_temp_min_c"))
        self.die_max = float(_cfg_value(cfg, "die_temp_max_c"))
        self.die_jump = float(_cfg_value(cfg, "die_temp_jump_c"))
        self.tach_rpm_max = float(_cfg_value(cfg, "tach_rpm_max"))
        self.tach_zero_rpm = float(_cfg_value(cfg, "tach_zero_duty_rpm"))
        self.delta_max = float(_cfg_value(cfg, "pressure_delta_max_pa"))
        self.die_safe_c = float(die_safe_c)
        self._set_n = set_n
        self._clear_n = clear_n
        self._bmp = {
            "internal": _Channel(Latch(set_n, clear_n)),
            "external": _Channel(Latch(set_n, clear_n)),
        }
        self._die = _Channel(Latch(set_n, clear_n))
        self._tach = [Latch(set_n, clear_n) for _ in range(4)]
        self._delta = Latch(set_n, clear_n)
        self.counts = {}

    def _count(self, sensor, location, reason, newly):
        if not newly or not reason:
            return
        key = (sensor, location, reason)
        self.counts[key] = self.counts.get(key, 0) + 1

    def observe_bmp280(self, location, now_ms, status, raw=None):
        """Return a public sensor dict. Bad samples have ok false and no values."""
        channel = self._bmp.get(location)
        if channel is None:
            return _sensor_view(status, False, "", None, None, False, "")
        if not isinstance(status, dict) or not status.get("enabled"):
            channel.latch.reason = ""
            channel.latch._pending = ""
            channel.latch._bad = 0
            channel.latch._good = 0
            return _sensor_view(status, False, "", None, None, False, "")
        if status.get("error") == "starting":
            return _sensor_view(
                status, False, "starting", None, None, bool(channel.latch.reason), channel.latch.reason
            )
        reason = self._bmp_reason(channel, now_ms, status, raw)
        if reason:
            channel.note_failure(now_ms)
        use, latched, newly = channel.latch.push(reason)
        self._count("bmp280", location, latched, newly)
        if use:
            temp = float(status.get("temp_c"))
            press = float(status.get("pressure_pa"))
            channel.have = True
            channel.good_a = temp
            channel.good_b = press
            channel.note_success(now_ms)
            return _sensor_view(status, True, "", temp, press, False, "")
        fault = bool(latched)
        if fault:
            error = fault_label("bmp280", location, latched)
        elif status.get("error"):
            # Keep the driver's text until the fault actually latches.
            error = status.get("error") or ""
        elif reason:
            error = REASON_TEXT.get(reason, "check failed")
        else:
            error = ""
        return _sensor_view(status, False, error, None, None, fault, latched)

    def _bmp_reason(self, channel, now_ms, status, raw):
        if not status.get("ok"):
            if channel.is_stale(now_ms, self.stale_ms):
                return REASON_STALE
            return REASON_READ
        temp = status.get("temp_c")
        press = status.get("pressure_pa")
        self._count_raw(channel, raw)
        if not is_finite(temp) or temp < self.bmp_temp_min or temp > self.bmp_temp_max:
            channel.candidate_a = None
            channel.candidate_b = None
            return REASON_TEMP_RANGE
        if not is_finite(press) or press < self.bmp_press_min or press > self.bmp_press_max:
            channel.candidate_a = None
            channel.candidate_b = None
            return REASON_PRESS_RANGE
        if channel.stuck >= self.stuck_n:
            return REASON_STUCK
        temp = float(temp)
        press = float(press)
        reason = self._jump_reason(
            channel,
            temp,
            press,
            self.bmp_temp_jump,
            self.bmp_press_jump,
            REASON_TEMP_JUMP,
            REASON_PRESS_JUMP,
        )
        channel.candidate_a = temp
        channel.candidate_b = press
        return reason

    def _jump_reason(self, channel, temp, press, temp_jump, press_jump, temp_reason, press_reason):
        """Jump against the last trusted sample, or against the new level once faulted.

        A step that stays put is sane again. A one-sample spike is not.
        """
        if channel.latch.reason and channel.candidate_a is not None:
            if abs(temp - float(channel.candidate_a)) > temp_jump:
                return temp_reason
            if press is not None and channel.candidate_b is not None:
                if abs(press - float(channel.candidate_b)) > press_jump:
                    return press_reason
            return ""
        if channel.have:
            if abs(temp - float(channel.good_a)) > temp_jump:
                return temp_reason
            if press is not None and channel.good_b is not None:
                if abs(press - float(channel.good_b)) > press_jump:
                    return press_reason
        return ""

    def _count_raw(self, channel, raw):
        key = _raw_key(raw)
        if key is None:
            return
        if channel.prev_raw is not None and key == channel.prev_raw:
            channel.stuck += 1
        else:
            channel.stuck = 1
            channel.prev_raw = key

    def observe_die(self, now_ms, temp_c, read_ok):
        """Return the temperature the curve may use. Never the rejected sample."""
        channel = self._die
        if not read_ok or temp_c is None:
            reason = REASON_STALE if channel.is_stale(now_ms, self.stale_ms) else REASON_READ
        elif not is_finite(temp_c) or temp_c < self.die_min or temp_c > self.die_max:
            channel.candidate_a = None
            reason = REASON_DIE_RANGE
        else:
            temp_c = float(temp_c)
            reason = self._jump_reason(
                channel,
                temp_c,
                None,
                self.die_jump,
                self.die_jump,
                REASON_DIE_JUMP,
                REASON_DIE_JUMP,
            )
            channel.candidate_a = temp_c
        if reason:
            channel.note_failure(now_ms)
            use, latched, newly = channel.latch.push(reason)
            self._count("die", "die", latched, newly)
            return self._die_fallback(channel, now_ms)
        use, latched, newly = channel.latch.push("")
        self._count("die", "die", latched, newly)
        if use:
            channel.have = True
            channel.good_a = temp_c
            channel.note_success(now_ms)
            return temp_c
        return self._die_fallback(channel, now_ms)

    def _die_fallback(self, channel, now_ms):
        if channel.have and channel.good_a is not None:
            if now_ms is None or channel.last_ok_ms is None:
                return float(channel.good_a)
            age = age_ms(now_ms, channel.last_ok_ms)
            if age is not None and age <= self.stale_ms:
                return float(channel.good_a)
        return self.die_safe_c

    def observe_tach(self, fan_id, reason):
        """Latch a tach fault. ``reason`` is empty when this sample is plausible."""
        index = int(fan_id) - 1
        if index < 0 or index >= len(self._tach):
            return
        if reason not in ("", REASON_RPM_HIGH, REASON_RPM_ZERO):
            reason = REASON_RPM_HIGH
        use, latched, newly = self._tach[index].push(reason)
        self._count("tach", str(int(fan_id)), latched, newly)
        return use

    def observe_delta(self, delta_pa):
        """Return a delta the pressure loop may use, or None."""
        if delta_pa is None or not is_finite(delta_pa):
            self._delta.reason = ""
            self._delta._pending = ""
            self._delta._bad = 0
            self._delta._good = 0
            return None
        delta_pa = float(delta_pa)
        if abs(delta_pa) > self.delta_max:
            use, latched, newly = self._delta.push(REASON_DELTA)
            self._count("pressure", "delta", latched, newly)
            return None
        use, latched, newly = self._delta.push("")
        self._count("pressure", "delta", latched, newly)
        if use:
            return delta_pa
        return None

    def active(self):
        rows = []
        for location in ("internal", "external"):
            reason = self._bmp[location].latch.reason
            if reason:
                rows.append(fault_row("bmp280", location, reason))
        if self._die.latch.reason:
            rows.append(fault_row("die", "die", self._die.latch.reason))
        for index, latch in enumerate(self._tach):
            if latch.reason:
                rows.append(fault_row("tach", str(index + 1), latch.reason))
        if self._delta.reason:
            rows.append(fault_row("pressure", "delta", self._delta.reason))
        return rows

    def count_rows(self):
        rows = []
        for sensor, location, reason in sorted(self.counts):
            rows.append(
                {
                    "sensor": sensor,
                    "location": location,
                    "reason": reason,
                    "count": self.counts[(sensor, location, reason)],
                }
            )
        return rows


def _raw_key(raw):
    if raw is None:
        return None
    try:
        if len(raw) < 2:
            return None
        return (int(raw[0]), int(raw[1]))
    except (TypeError, ValueError):
        return None


def _sensor_view(status, ok, error, temp_c, pressure_pa, fault, reason):
    chip = None
    enabled = False
    if isinstance(status, dict):
        chip = status.get("chip_id")
        enabled = bool(status.get("enabled"))
    return {
        "enabled": enabled,
        "ok": bool(ok),
        "chip_id": chip,
        "temp_c": temp_c,
        "pressure_pa": pressure_pa,
        "error": error or "",
        "fault": bool(fault),
        "fault_reason": reason or "",
    }
