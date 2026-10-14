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
