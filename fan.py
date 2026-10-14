"""Per-fan PWM / tach / thermal control helpers and FanController."""

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
RPM_PULSES_PER_REV = 2
RPM_EMA_ALPHA = 0.35
RPM_MAX_PLAUSIBLE = 10_000

OVERRIDES_PATH = "overrides.json"


def clamp_duty(fraction):
    if fraction < 0.0:
        return 0.0
    if fraction > 1.0:
        return 1.0
    return float(fraction)


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
    def __init__(self, hw=None, overrides_path=OVERRIDES_PATH):
        self.hw = hw
        self.overrides_path = overrides_path
        self._mem_overrides = None
        self.modes = ["auto"] * FAN_COUNT
        self.duties = [MIN_SPEED] * FAN_COUNT
        self.rpms = [0.0] * FAN_COUNT
        self.die_c = 0.0
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
            try:
                duty_f = clamp_duty(float(duty))
            except (TypeError, ValueError):
                return False, 400, "invalid duty"
            self.modes[idx] = "manual"
            self.duties[idx] = duty_f
            if self.hw is not None:
                self.hw.set_duty(idx, duty_f)
        else:
            self.modes[idx] = "auto"
            if self.hw is not None:
                d = temp_to_duty(self.die_c)
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
                d = temp_to_duty(self.die_c)
                self.duties[i] = d
                if self.hw is not None:
                    self.hw.set_duty(i, d)
        return True

    def tick_logic(self, die_c, pulse_counts, elapsed_s):
        self.die_c = die_c
        auto_duty = temp_to_duty(die_c)
        for i in range(FAN_COUNT):
            if self.modes[i] == "auto":
                self.duties[i] = auto_duty
                if self.hw is not None:
                    self.hw.set_duty(i, auto_duty)
            rpm = pulses_to_rpm(pulse_counts[i], elapsed_s)
            self.rpms[i] = (RPM_EMA_ALPHA * rpm) + ((1.0 - RPM_EMA_ALPHA) * self.rpms[i])

    def status_dict(self):
        return {
            "die_c": self.die_c,
            "uptime_s": int(self.uptime_s),
            "wifi": self.wifi,
            "ip": self.ip,
            "ssid": self.ssid,
            "fans": [
                {
                    "id": i + 1,
                    "mode": self.modes[i],
                    "duty": self.duties[i],
                    "rpm": self.rpms[i],
                }
                for i in range(FAN_COUNT)
            ],
        }

    def init_hardware(self):
        if self.hw is None:
            self.hw = PicoHw()

    def spinup(self):
        import time

        self.hw.set_all_duty(SPINUP_DUTY)
        time.sleep(SPINUP_TIME_S)
        self.hw.take_pulse_counts()

    def tick(self, elapsed_s):
        die = self.hw.read_die_temp_c()
        counts = self.hw.take_pulse_counts()
        self.tick_logic(die, counts, elapsed_s)

    def failsafe(self):
        if self.hw is not None:
            self.hw.failsafe()


def _make_tach_handler(counts, index):
    def _handler(_pin):
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
        self._tach_pins = []
        for i, gp in enumerate(TACH_PINS):
            pin = machine.Pin(gp, machine.Pin.IN, machine.Pin.PULL_UP)
            pin.irq(
                trigger=machine.Pin.IRQ_RISING,
                handler=_make_tach_handler(self._pulse_counts, i),
            )
            self._tach_pins.append(pin)

    def set_duty(self, index, fraction):
        fraction = clamp_duty(fraction)
        self.pwms[index].duty_u16(int(fraction * 65535))

    def set_all_duty(self, fraction):
        for i in range(FAN_COUNT):
            self.set_duty(i, fraction)

    def read_die_temp_c(self):
        raw = self.temp_adc.read_u16()
        voltage = raw * 3.3 / 65535
        return 27.0 - (voltage - 0.706) / 0.001721

    def take_pulse_counts(self):
        state = self._machine.disable_irq()
        try:
            counts = list(self._pulse_counts)
            for i in range(FAN_COUNT):
                self._pulse_counts[i] = 0
        finally:
            self._machine.enable_irq(state)
        return counts

    def failsafe(self):
        try:
            self.set_all_duty(1.0)
        except Exception:
            pass
