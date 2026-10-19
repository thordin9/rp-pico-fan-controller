"""Per-fan PWM / tach / thermal control helpers and FanController."""

import time

FAN_COUNT = 4
PWM_PINS = (15, 16, 17, 18)
TACH_PINS = (14, 13, 12, 11)
PWM_FREQ_HZ = 25_000

MIN_TEMP_C = 35.0
MAX_TEMP_C = 55.0
MIN_SPEED = 0.18

SAMPLE_PERIOD_S = 1.0
SPINUP_DUTY = 0.60
SPINUP_TIME_S = 1.5
SPINUP_STEP_S = 0.2
RPM_PULSES_PER_REV = 2
RPM_EMA_ALPHA = 0.35
RPM_MAX_PLAUSIBLE = 10_000

# Latest 1 s sample below this RPM, while duty >= STALL_DUTY_MIN, raises stall.
# Default 1 means "RPM reads 0" (pulses_to_rpm is an int).
STALL_DUTY_MIN = 0.15
STALL_RPM_BELOW = 1

# Average this many ADC(4) reads per sample. Reads are fast; 8 cuts noise.
TEMP_ADC_SAMPLES = 8

# Drop tach edges closer together than this. 1 ms still counts a 10_000 RPM
# fan (2 pulses/rev → 3 ms between edges) and rejects sub-millisecond bounce.
TACH_MIN_INTERVAL_US = 1000

# Solid LED at or above this duty; otherwise blink with this half-period.
# The main loop must evaluate led_is_on every iteration — the half-period is
# shorter than the 1 s sample, so sampling it only inside the sample branch
# aliases the blink away.
LED_SOLID_DUTY = 0.5
LED_BLINK_HALF_MS = 500

OVERRIDES_PATH = "overrides.json"

# Auto mode positive pressure. Fans 1 and 2 intake, 3 and 4 exhaust.
# Exhaust duty starts at clamp(intake_duty * ratio + offset). Any result in
# (0, MIN_SPEED) is lifted to MIN_SPEED: 0.18 * 0.85 is 0.153, which sits on
# the 15% stall threshold and false-alarms a fan that will not spin there.
# Duty 0 stays off. Above the floor the 0.85 ratio still slows the exhaust.
DEFAULT_ROLES = ("intake", "intake", "exhaust", "exhaust")
DEFAULT_EXHAUST_RATIO = 0.85
DEFAULT_EXHAUST_OFFSET = 0.0
# Closed each 1 s sample from the static duty. Not an integrator.
# 0.0005 duty per pascal is 0.5% duty for a 10 Pa error. The trim is capped
# at ±5% so a sensor offset cannot walk the fans away from the ratio.
DEFAULT_PRESSURE_TARGET_PA = 5.0
DEFAULT_PRESSURE_LOOP_GAIN = 0.0005
DEFAULT_PRESSURE_TRIM_MAX = 0.05

# MicroPython ticks_us wraps every 2**30 microseconds.
_TICKS_MASK = 0x3FFFFFFF
_TICKS_PERIOD = 0x40000000
_TICKS_HALF = 0x20000000


def clamp_duty(fraction):
    if fraction < 0.0:
        return 0.0
    if fraction > 1.0:
        return 1.0
    return float(fraction)


def validate_duty(value):
    """Return (duty, None) or (None, error).

    The HTTP API rejects out-of-range duty with 400. clamp_duty remains for
    hardware safety and for a corrupt overrides file.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None, "invalid duty"
    duty = float(value)
    if duty != duty:
        return None, "invalid duty"
    if duty < 0.0 or duty > 1.0:
        return None, "duty out of range"
    return duty, None


def ticks_diff(ticks1, ticks2):
    """ticks1 - ticks2 with MicroPython's 30-bit wrap.

    Used from the tach IRQ. The operands are small ints (ticks fit in 30 bits);
    this function must not build objects.
    """
    diff = (ticks1 - ticks2) & _TICKS_MASK
    if diff >= _TICKS_HALF:
        diff -= _TICKS_PERIOD
    return diff


def led_is_on(duty_max, elapsed_ms, half_period_ms=LED_BLINK_HALF_MS, solid_duty=LED_SOLID_DUTY):
    """True when the status LED should be lit.

    High duty holds the LED on. Below that it blinks. ``elapsed_ms`` is any
    monotonic millisecond counter; call this every loop iteration.
    """
    if duty_max >= solid_duty:
        return True
    period = int(half_period_ms)
    if period <= 0:
        return True
    return ((int(elapsed_ms) // period) & 1) == 0


def adc_raw_to_temp_c(raw):
    """RP2040 die temperature from a single ADC(4) u16 sample."""
    voltage = raw * 3.3 / 65535
    return 27.0 - (voltage - 0.706) / 0.001721


def average_adc_raw(samples):
    """Integer mean of ADC samples. Empty input yields 0."""
    total = 0
    n = 0
    for raw in samples:
        total += raw
        n += 1
    if n <= 0:
        return 0
    return total // n


def mean_adc(read_u16, count):
    """Integer mean of ``count`` calls to an ADC read. Shared with PicoHw."""
    if count <= 0:
        return 0
    total = 0
    i = 0
    while i < count:
        total += read_u16()
        i += 1
    return total // count


def note_tach_pulse(counts, last_us, seen, index, now_us, min_interval_us):
    """Count one tach edge if it is far enough from the previous edge.

    IRQ-safe: touches only the preallocated ``counts`` / ``last_us`` / ``seen``
    slots and small ints. Returns True when the edge was counted.
    ``seen`` is a bytearray; 0 means this channel has not yet seen an edge,
    so the first edge is always accepted.
    """
    if seen[index]:
        if ticks_diff(now_us, last_us[index]) < min_interval_us:
            return False
    else:
        seen[index] = 1
    last_us[index] = now_us
    counts[index] += 1
    return True


def temp_to_duty(temp_c):
    if temp_c <= MIN_TEMP_C:
        return MIN_SPEED
    if temp_c >= MAX_TEMP_C:
        return 1.0
    span = MAX_TEMP_C - MIN_TEMP_C
    return MIN_SPEED + (1.0 - MIN_SPEED) * ((temp_c - MIN_TEMP_C) / span)


def normalize_roles(roles):
    """Return a 4-tuple of intake/exhaust, or None when the value is unusable."""
    if isinstance(roles, str) or not isinstance(roles, (list, tuple)):
        return None
    if len(roles) != FAN_COUNT:
        return None
    out = []
    for role in roles:
        if role not in ("intake", "exhaust"):
            return None
        out.append(role)
    return tuple(out)


def select_control_temp(die_c, internal_c, internal_ok):
    """Return (temp_c, source). Source is ``internal`` or ``die``.

    The internal BMP280 drives the curve only while its latest read is ok.
    A missing sample, a failed read, or a disabled sensor falls back to the
    RP2040 die temperature.
    """
    if internal_ok and internal_c is not None:
        try:
            return float(internal_c), "internal"
        except (TypeError, ValueError):
            pass
    return die_c, "die"


def lift_exhaust_idle(duty):
    """Pull a non-zero exhaust duty up to the quiet floor.

    The stall alarm starts at ``STALL_DUTY_MIN`` (15%). The curve will not
    hold an intake fan below ``MIN_SPEED`` (18%). A command in between, such
    as the raw 15.3% from ratio 0.85, is high enough to alarm and low enough
    that a healthy fan may not spin. Duty 0 is left alone: that is fan off,
    and it does not alarm.
    """
    if duty <= 0.0:
        return 0.0
    if duty < MIN_SPEED:
        return MIN_SPEED
    return duty


def pressure_trim(delta_pa, target_pa, gain, trim_max):
    """Return the exhaust duty added for one pressure sample, capped.

    The value is recomputed from the static duty every sample. It does not
    accumulate. ``trim_max`` limits how far the loop may pull away from the
    intake/exhaust ratio.
    """
    trim = float(gain) * (float(delta_pa) - float(target_pa))
    limit = abs(float(trim_max))
    if trim > limit:
        return limit
    if trim < -limit:
        return -limit
    return trim


def auto_duty_for_role(
    base_duty,
    role,
    ratio,
    offset,
    delta_pa=None,
    target_pa=0.0,
    gain=0.0,
    loop_enabled=False,
    trim_max=DEFAULT_PRESSURE_TRIM_MAX,
):
    """Duty for one auto fan.

    Intake fans take the thermal-curve duty, which already includes the
    minimum-speed floor. Exhaust fans take ``base * ratio + offset``, lifted
    out of the stall band, then an optional pressure trim. With the loop on
    but ``delta_pa`` missing, the trim is skipped and the static ratio
    remains. Manual mode does not call this.
    """
    if role == "exhaust":
        duty = clamp_duty(float(base_duty) * float(ratio) + float(offset))
        duty = lift_exhaust_idle(duty)
        if loop_enabled and delta_pa is not None:
            try:
                duty = clamp_duty(
                    duty + pressure_trim(delta_pa, target_pa, gain, trim_max)
                )
                duty = lift_exhaust_idle(duty)
            except (TypeError, ValueError):
                pass
        return duty
    return clamp_duty(base_duty)


def blank_sensor_status():
    return {
        "enabled": False,
        "ok": False,
        "chip_id": None,
        "temp_c": None,
        "pressure_pa": None,
        "error": "",
    }


def blank_oled_status():
    return {"enabled": False, "ok": False, "error": ""}


def pulses_to_rpm(pulses, elapsed_s):
    if elapsed_s <= 0:
        return 0
    rpm = (pulses / RPM_PULSES_PER_REV) * (60.0 / elapsed_s)
    if rpm < 0:
        return 0
    if rpm > RPM_MAX_PLAUSIBLE:
        return RPM_MAX_PLAUSIBLE
    return int(rpm)


def overrides_to_json(fans):
    parts = ['{"fans":[']
    for i, f in enumerate(fans):
        if i:
            parts.append(",")
        parts.append(
            '{{"mode":"{}","duty":{:.4f}}}'.format(f["mode"], float(f["duty"]))
        )
    parts.append("]}")
    return "".join(parts)


def parse_overrides_json(text):
    """Return list of {mode, duty} or None if invalid. MicroPython-safe (ujson)."""
    try:
        import json
    except ImportError:
        import ujson as json
    try:
        data = json.loads(text)
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    fans = data.get("fans")
    if not isinstance(fans, list) or len(fans) != FAN_COUNT:
        return None
    out = []
    for item in fans:
        if not isinstance(item, dict):
            return None
        mode = item.get("mode")
        duty = item.get("duty")
        if mode not in ("auto", "manual"):
            return None
        try:
            duty_f = clamp_duty(float(duty))
        except (TypeError, ValueError):
            return None
        out.append({"mode": mode, "duty": duty_f})
    return out


class FanController:
    def __init__(
        self,
        hw=None,
        overrides_path=OVERRIDES_PATH,
        stall_duty_min=None,
        stall_rpm_below=None,
        roles=None,
        exhaust_ratio=None,
        exhaust_offset=None,
        pressure_loop=True,
        pressure_target_pa=None,
        pressure_loop_gain=None,
        pressure_trim_max=None,
    ):
        self.hw = hw
        self.overrides_path = overrides_path
        self._mem_overrides = None
        self.modes = ["auto"] * FAN_COUNT
        self.duties = [MIN_SPEED] * FAN_COUNT
        self.rpms = [0.0] * FAN_COUNT
        self.stalls = [False] * FAN_COUNT
        self.stall_duty_min = (
            STALL_DUTY_MIN if stall_duty_min is None else float(stall_duty_min)
        )
        self.stall_rpm_below = (
            STALL_RPM_BELOW if stall_rpm_below is None else float(stall_rpm_below)
        )
        parsed_roles = normalize_roles(roles) if roles is not None else DEFAULT_ROLES
        self.roles = list(parsed_roles or DEFAULT_ROLES)
        self.exhaust_ratio = (
            DEFAULT_EXHAUST_RATIO if exhaust_ratio is None else float(exhaust_ratio)
        )
        self.exhaust_offset = (
            DEFAULT_EXHAUST_OFFSET if exhaust_offset is None else float(exhaust_offset)
        )
        self.pressure_loop = bool(pressure_loop)
        self.pressure_target_pa = (
            DEFAULT_PRESSURE_TARGET_PA
            if pressure_target_pa is None
            else float(pressure_target_pa)
        )
        self.pressure_loop_gain = (
            DEFAULT_PRESSURE_LOOP_GAIN
            if pressure_loop_gain is None
            else float(pressure_loop_gain)
        )
        self.pressure_trim_max = (
            DEFAULT_PRESSURE_TRIM_MAX
            if pressure_trim_max is None
            else float(pressure_trim_max)
        )
        self.pressure_loop_active = False
        self.die_c = 0.0
        self.control_c = 0.0
        self.temp_source = "die"
        self.pressure_delta_pa = None
        self.sensor_state = {
            "internal": blank_sensor_status(),
            "external": blank_sensor_status(),
        }
        self.oled_state = blank_oled_status()
        self.uptime_s = 0
        self.wifi = "offline"
        self.ip = ""
        self.ssid = ""

    def _index(self, fan_id_1based):
        if not isinstance(fan_id_1based, int):
            return None
        if fan_id_1based < 1 or fan_id_1based > FAN_COUNT:
            return None
        return fan_id_1based - 1

    def apply_control(self, fan_id_1based, mode, duty=None):
        idx = self._index(fan_id_1based)
        if idx is None:
            return False, 404, "fan not found"
        if mode not in ("auto", "manual"):
            return False, 400, "invalid mode"
        if mode == "manual":
            if duty is None:
                return False, 400, "duty required for manual"
            duty_f, err = validate_duty(duty)
            if err is not None:
                return False, 400, err
            self.modes[idx] = "manual"
            self.duties[idx] = duty_f
            if self.hw is not None:
                self.hw.set_duty(idx, duty_f)
        else:
            self.modes[idx] = "auto"
            if self.hw is not None:
                d = self._auto_duty(idx, temp_to_duty(self.control_c))
                self.duties[idx] = d
                self.hw.set_duty(idx, d)
        if not self.save_overrides():
            print("fan: warning: failed to persist overrides")
        return True, 200, "ok"

    def set_auto(self, fan_id_1based):
        return self.apply_control(fan_id_1based, "auto", None)

    def save_overrides(self):
        fans = [
            {"mode": self.modes[i], "duty": self.duties[i]} for i in range(FAN_COUNT)
        ]
        text = overrides_to_json(fans)
        if self.overrides_path == ":memory:":
            self._mem_overrides = text
            return True
        try:
            with open(self.overrides_path, "w") as f:
                f.write(text)
            return True
        except Exception as exc:
            print("fan: save_overrides failed:", exc)
            return False

    def load_overrides(self):
        try:
            if self.overrides_path == ":memory:":
                text = self._mem_overrides
                if not text:
                    return False
            else:
                with open(self.overrides_path, "r") as f:
                    text = f.read()
        except Exception:
            return False
        parsed = parse_overrides_json(text)
        if parsed is None:
            return False
        for i, item in enumerate(parsed):
            self.modes[i] = item["mode"]
            if item["mode"] == "manual":
                self.duties[i] = item["duty"]
                if self.hw is not None:
                    self.hw.set_duty(i, item["duty"])
            else:
                d = self._auto_duty(i, temp_to_duty(self.control_c))
                self.duties[i] = d
                if self.hw is not None:
                    self.hw.set_duty(i, d)
        return True

    def _auto_duty(self, index, base_duty):
        return auto_duty_for_role(
            base_duty,
            self.roles[index],
            self.exhaust_ratio,
            self.exhaust_offset,
            self.pressure_delta_pa,
            self.pressure_target_pa,
            self.pressure_loop_gain,
            self.pressure_loop,
            self.pressure_trim_max,
        )

    def note_sensors(self, snap):
        """Copy a SensorHub snapshot onto the status published by the page."""
        if not isinstance(snap, dict):
            return
        sensors = snap.get("sensors") or {}
        for name in ("internal", "external"):
            item = sensors.get(name)
            if not isinstance(item, dict):
                continue
            self.sensor_state[name] = {
                "enabled": bool(item.get("enabled")),
                "ok": bool(item.get("ok")),
                "chip_id": item.get("chip_id"),
                "temp_c": item.get("temp_c"),
                "pressure_pa": item.get("pressure_pa"),
                "error": item.get("error") or "",
            }
        if "pressure_delta_pa" in snap:
            self.pressure_delta_pa = snap.get("pressure_delta_pa")

    def note_oled(self, state):
        if not isinstance(state, dict):
            return
        self.oled_state = {
            "enabled": bool(state.get("enabled")),
            "ok": bool(state.get("ok")),
            "error": state.get("error") or "",
        }

    def tick_logic(
        self,
        die_c,
        pulse_counts,
        elapsed_s,
        internal_c=None,
        internal_ok=False,
        pressure_delta_pa=None,
    ):
        self.die_c = die_c
        # Apply this sample's delta before duties so the trim sees it.
        # None means a sensor is missing or failed: skip the trim.
        self.pressure_delta_pa = pressure_delta_pa
        self.pressure_loop_active = bool(
            self.pressure_loop and pressure_delta_pa is not None
        )
        self.control_c, self.temp_source = select_control_temp(
            die_c, internal_c, internal_ok
        )
        base_duty = temp_to_duty(self.control_c)
        for i in range(FAN_COUNT):
            if self.modes[i] == "auto":
                duty = self._auto_duty(i, base_duty)
                self.duties[i] = duty
                if self.hw is not None:
                    self.hw.set_duty(i, duty)
            raw_rpm = pulses_to_rpm(pulse_counts[i], elapsed_s)
            self.rpms[i] = (RPM_EMA_ALPHA * raw_rpm) + (
                (1.0 - RPM_EMA_ALPHA) * self.rpms[i]
            )
            # A commanded fan that produced no tach edges this sample is stalled.
            # Duty 0 is "off", not a stall. elapsed <= 0 is not a real sample.
            if elapsed_s <= 0:
                self.stalls[i] = False
            else:
                self.stalls[i] = (
                    self.duties[i] >= self.stall_duty_min
                    and raw_rpm < self.stall_rpm_below
                )

    def status_dict(self):
        return {
            "die_c": self.die_c,
            "control_c": self.control_c,
            "temp_source": self.temp_source,
            "pressure_delta_pa": self.pressure_delta_pa,
            "pressure_loop_enabled": bool(self.pressure_loop),
            "pressure_loop_active": bool(self.pressure_loop_active),
            "uptime_s": int(self.uptime_s),
            "wifi": self.wifi,
            "ip": self.ip,
            "ssid": self.ssid,
            "sensors": {
                "internal": dict(self.sensor_state["internal"]),
                "external": dict(self.sensor_state["external"]),
            },
            "oled": dict(self.oled_state),
            "fans": [
                {
                    "id": i + 1,
                    "mode": self.modes[i],
                    "duty": self.duties[i],
                    "rpm": self.rpms[i],
                    "stall": bool(self.stalls[i]),
                    "role": self.roles[i],
                }
                for i in range(FAN_COUNT)
            ],
        }

    def init_hardware(self):
        if self.hw is None:
            self.hw = PicoHw()

    def apply_auto_duties(self):
        """Push the curve, with intake/exhaust bias, onto every auto fan."""
        base = temp_to_duty(self.control_c)
        for i in range(FAN_COUNT):
            if self.modes[i] != "auto":
                continue
            duty = self._auto_duty(i, base)
            self.duties[i] = duty
            if self.hw is not None:
                self.hw.set_duty(i, duty)

    def prepare_fans(self, feed=None):
        """Spin up, then apply saved overrides or the curve.

        Call this before any network wait so PWM is not left at 0 while
        Wi-Fi associates. ``feed`` is invoked during the spin-up sleep so a
        hardware watchdog can be kicked. Returns True if overrides loaded.
        """
        self.spinup(feed=feed)
        if self.hw is not None:
            try:
                self.die_c = self.hw.read_die_temp_c()
            except Exception as exc:
                print("temp: read failed:", exc)
        # Sensors are not up yet. The die reading is the curve input until
        # a later sample reports a healthy internal BMP280.
        self.control_c = self.die_c
        self.temp_source = "die"
        loaded = self.load_overrides()
        if not loaded:
            self.apply_auto_duties()
        return loaded

    def spinup(self, feed=None):
        self.hw.set_all_duty(SPINUP_DUTY)
        for i in range(FAN_COUNT):
            self.duties[i] = SPINUP_DUTY
        # Sleep in short slices so a watchdog feed can run inside the burst.
        remaining_ms = int(round(SPINUP_TIME_S * 1000))
        step_ms = int(round(SPINUP_STEP_S * 1000))
        if step_ms < 1:
            step_ms = 1
        while remaining_ms > 0:
            delay_ms = step_ms if remaining_ms > step_ms else remaining_ms
            time.sleep(delay_ms / 1000.0)
            remaining_ms -= delay_ms
            if feed is not None:
                feed()
        self.hw.take_pulse_counts()

    def tick(
        self,
        elapsed_s,
        internal_c=None,
        internal_ok=False,
        pressure_delta_pa=None,
    ):
        try:
            die = self.hw.read_die_temp_c()
        except Exception as exc:
            print("temp: die read failed:", exc)
            die = self.die_c
        try:
            counts = self.hw.take_pulse_counts()
        except Exception as exc:
            print("tach: read failed:", exc)
            counts = [0] * FAN_COUNT
        self.tick_logic(
            die,
            counts,
            elapsed_s,
            internal_c=internal_c,
            internal_ok=internal_ok,
            pressure_delta_pa=pressure_delta_pa,
        )

    def failsafe(self):
        if self.hw is not None:
            self.hw.failsafe()


def _make_tach_handler(counts, last_us, seen, index, min_interval_us):
    # Inlined, and it calls time.ticks_diff (C) rather than the Python
    # helper. The Python helper's 30-bit wrap math can allocate a long int,
    # which is not safe in a pin IRQ. Keep this body in step with
    # note_tach_pulse: first edge counts, later edges need min_interval_us.
    def _handler(_pin):
        now = time.ticks_us()
        if seen[index]:
            if time.ticks_diff(now, last_us[index]) < min_interval_us:
                return
        else:
            seen[index] = 1
        last_us[index] = now
        counts[index] += 1

    return _handler


class PicoHw:
    def __init__(self):
        import machine

        self._machine = machine
        self.pwms = []
        for gp in PWM_PINS:
            p = machine.PWM(machine.Pin(gp))
            p.freq(PWM_FREQ_HZ)
            p.duty_u16(0)
            self.pwms.append(p)
        self.temp_adc = machine.ADC(4)
        self._pulse_counts = [0] * FAN_COUNT
        self._count_snap = [0] * FAN_COUNT
        self._tach_last_us = [0] * FAN_COUNT
        self._tach_seen = bytearray(FAN_COUNT)
        self._tach_pins = []
        for i, gp in enumerate(TACH_PINS):
            pin = machine.Pin(gp, machine.Pin.IN, machine.Pin.PULL_UP)
            pin.irq(
                trigger=machine.Pin.IRQ_RISING,
                handler=_make_tach_handler(
                    self._pulse_counts,
                    self._tach_last_us,
                    self._tach_seen,
                    i,
                    TACH_MIN_INTERVAL_US,
                ),
            )
            self._tach_pins.append(pin)

    def set_duty(self, index, fraction):
        fraction = clamp_duty(fraction)
        self.pwms[index].duty_u16(int(fraction * 65535))

    def set_all_duty(self, fraction):
        for i in range(FAN_COUNT):
            self.set_duty(i, fraction)

    def read_die_temp_c(self):
        return adc_raw_to_temp_c(mean_adc(self.temp_adc.read_u16, TEMP_ADC_SAMPLES))

    def take_pulse_counts(self):
        # Copy under the IRQ lock without allocating. The list copy happens
        # after interrupts are back on, so the handler can keep counting.
        snap = self._count_snap
        counts = self._pulse_counts
        state = self._machine.disable_irq()
        try:
            for i in range(FAN_COUNT):
                snap[i] = counts[i]
                counts[i] = 0
        finally:
            self._machine.enable_irq(state)
        return snap[:]

    def failsafe(self):
        try:
            self.set_all_duty(1.0)
        except Exception:
            pass
