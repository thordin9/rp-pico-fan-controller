# Per-fan Control + Prometheus Implementation Plan

> **Historical.** This plan implemented the first per-fan firmware. Later work added Basic Auth, BMP280 sensors on two I2C buses, the OLED, a pressure loop that is on by default, exhaust idle lifted to 18%, and sensor faults. Do not treat the constraints below as the current defaults. Current behaviour is the [README](../../../README.md) and [how it works](../../how-it-works.md).

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace shared PWM with per-fan PWM (auto thermal or manual web override with flash persistence) and add a Prometheus `/metrics` endpoint plus a control UI.

**Architecture:** Split into `fan.py` (hardware + modes + overrides), `metrics.py` (Prometheus text), `web.py` (HTTP UI/API/counters), and a thin `main.py` (Wi-Fi + loop). Pure helpers are unit-tested on host with `unittest`; hardware paths run on the Pico.

**Tech Stack:** MicroPython (Pico W), stdlib sockets, `machine` PWM/ADC/IRQ, host `unittest` for pure logic.

## Global Constraints

- Pin map: Fan1–4 PWM GP15/16/17/18, tach GP14/13/12/11; PWM 25 kHz; tach pull-ups **10 kΩ** to 3V3
- Per-fan mode `auto`|`manual`; auto fans share die curve (≤35 °C → 18%, ≥55 °C → 100%)
- Persist overrides to `overrides.json` on successful control POSTs; fail-safe does not rewrite file
- HTTP: `GET /`, `GET /status.json`, `POST /api/fans/<id>`, `POST /api/fans/<id>/auto`, `GET /metrics`
- Metric names locked: `pico_fan_die_temp_celsius`, `pico_fan_duty_ratio`, `pico_fan_rpm`, `pico_fan_override`, `pico_fan_uptime_seconds`, `pico_fan_wifi_up`, `pico_fan_http_requests_total`
- Flash files: `main.py`, `fan.py`, `web.py`, `metrics.py`, `config.py`
- No auth/HTTPS; no ambient sensors; no per-fan thermal curves

## File structure

| File | Responsibility |
|------|----------------|
| `fan.py` | Pins, PWM/tach, curve helpers, FanController, overrides I/O, fail-safe |
| `metrics.py` | `format_metrics(status, http_counts) -> str` |
| `web.py` | HTTP listen/poll, HTML UI, JSON, control routes, request counters |
| `main.py` | LED, Wi-Fi, wire FanController + HttpServer, sample loop |
| `config.py` | Unchanged (Wi-Fi / port) |
| `tests/test_fan_logic.py` | Host tests: curve, RPM, overrides parse/apply |
| `tests/test_metrics.py` | Host tests: Prometheus text |
| `tests/test_web_handlers.py` | Host tests: path routing / control validation helpers |
| `README.md` | Wiring, API, flash list, scrape example |

---

### Task 1: Pure fan helpers + overrides codec

**Files:**
- Create: `fan.py`
- Create: `tests/test_fan_logic.py`
- Test: `tests/test_fan_logic.py`

**Interfaces:**
- Produces:
  - `FAN_COUNT: int = 4`
  - `PWM_PINS: tuple = (15, 16, 17, 18)`
  - `TACH_PINS: tuple = (14, 13, 12, 11)`
  - `PWM_FREQ_HZ: int = 25_000`
  - `MIN_TEMP_C: float = 35.0`, `MAX_TEMP_C: float = 55.0`, `MIN_SPEED: float = 0.18`
  - `OVERRIDES_PATH: str = "overrides.json"`
  - `clamp_duty(fraction: float) -> float`
  - `temp_to_duty(temp_c: float) -> float`
  - `pulses_to_rpm(pulses: int, elapsed_s: float) -> int`
  - `overrides_to_json(fans: list[dict]) -> str` where each dict has `mode`/`duty`
  - `parse_overrides_json(text: str) -> list[dict] | None` — `None` if invalid; length must be `FAN_COUNT`

- [ ] **Step 1: Write failing host tests**

Create `tests/test_fan_logic.py`:

```python
import unittest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import fan


class TestClampAndCurve(unittest.TestCase):
    def test_clamp_duty(self):
        self.assertEqual(fan.clamp_duty(-0.1), 0.0)
        self.assertEqual(fan.clamp_duty(1.5), 1.0)
        self.assertAlmostEqual(fan.clamp_duty(0.42), 0.42)

    def test_temp_to_duty_floor_and_ceil(self):
        self.assertAlmostEqual(fan.temp_to_duty(30.0), fan.MIN_SPEED)
        self.assertAlmostEqual(fan.temp_to_duty(55.0), 1.0)
        self.assertAlmostEqual(fan.temp_to_duty(60.0), 1.0)

    def test_temp_to_duty_midpoint(self):
        mid = (fan.MIN_TEMP_C + fan.MAX_TEMP_C) / 2
        expected = fan.MIN_SPEED + (1.0 - fan.MIN_SPEED) * 0.5
        self.assertAlmostEqual(fan.temp_to_duty(mid), expected, places=4)


class TestRpm(unittest.TestCase):
    def test_pulses_to_rpm(self):
        # 2 pulses/rev, 100 pulses in 1s → 50 rev/s → 3000 RPM
        self.assertEqual(fan.pulses_to_rpm(100, 1.0), 3000)

    def test_pulses_zero_elapsed(self):
        self.assertEqual(fan.pulses_to_rpm(10, 0), 0)


class TestOverridesCodec(unittest.TestCase):
    def test_roundtrip(self):
        fans = [
            {"mode": "auto", "duty": 0.0},
            {"mode": "manual", "duty": 0.45},
            {"mode": "auto", "duty": 0.0},
            {"mode": "manual", "duty": 1.0},
        ]
        text = fan.overrides_to_json(fans)
        parsed = fan.parse_overrides_json(text)
        self.assertEqual(parsed, fans)

    def test_invalid_returns_none(self):
        self.assertIsNone(fan.parse_overrides_json("{"))
        self.assertIsNone(fan.parse_overrides_json('{"fans":[]}'))
        self.assertIsNone(
            fan.parse_overrides_json(
                '{"fans":[{"mode":"nope","duty":0},{"mode":"auto","duty":0},'
                '{"mode":"auto","duty":0},{"mode":"auto","duty":0}]}'
            )
        )


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests — expect fail**

Run: `python3 -m unittest tests.test_fan_logic -v`  
Expected: `ModuleNotFoundError: No module named 'fan'` (or import errors for missing symbols)

- [ ] **Step 3: Implement pure helpers in `fan.py`**

Create `fan.py` with **only** constants + pure functions for now (no `machine` yet):

```python
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
```

- [ ] **Step 4: Run tests — expect pass**

Run: `python3 -m unittest tests.test_fan_logic -v`  
Expected: all OK

- [ ] **Step 5: Commit**

```bash
git add fan.py tests/test_fan_logic.py
git commit -m "feat: add fan helpers and overrides codec"
```

---

### Task 2: FanController (modes, persist, tick logic without real hardware)

**Files:**
- Modify: `fan.py`
- Modify: `tests/test_fan_logic.py`

**Interfaces:**
- Consumes: helpers from Task 1
- Produces:
  - `class FanController`
  - `__init__(self, hw=None)` — if `hw` is None, create real hardware later; tests pass a stub
  - `modes: list[str]`, `duties: list[float]`, `rpms: list[float]`, `die_c: float`, `uptime_s: int`
  - `wifi: str`, `ip: str`, `ssid: str` (set by main)
  - `apply_control(self, fan_id_1based: int, mode: str, duty=None) -> (ok: bool, code: int, message: str)` — persists on success
  - `set_auto(self, fan_id_1based: int) -> (ok, code, message)`
  - `load_overrides(self) -> bool`
  - `save_overrides(self) -> bool`
  - `tick_logic(self, die_c: float, pulse_counts: list[int], elapsed_s: float) -> None` — updates duties/rpms in memory (no PWM); auto applies curve
  - `status_dict(self) -> dict`

Hardware stub protocol for tests (duck-typed):
- `set_duty(index: int, fraction: float) -> None`
- `read_die_temp_c() -> float`
- `take_pulse_counts() -> list[int]`
- `set_all_duty(fraction: float) -> None`

- [ ] **Step 1: Extend tests for FanController logic**

Append to `tests/test_fan_logic.py`:

```python
class FakeHw:
    def __init__(self):
        self.duties = [0.0] * fan.FAN_COUNT

    def set_duty(self, index, fraction):
        self.duties[index] = fraction

    def set_all_duty(self, fraction):
        for i in range(fan.FAN_COUNT):
            self.duties[i] = fraction

    def read_die_temp_c(self):
        return 30.0

    def take_pulse_counts(self):
        return [0] * fan.FAN_COUNT


class TestFanController(unittest.TestCase):
    def setUp(self):
        self.hw = FakeHw()
        self.ctrl = fan.FanController(hw=self.hw, overrides_path=":memory:")

    def test_manual_override_skips_curve(self):
        ok, code, _ = self.ctrl.apply_control(2, "manual", 0.4)
        self.assertTrue(ok)
        self.assertEqual(code, 200)
        self.ctrl.tick_logic(55.0, [0, 0, 0, 0], 1.0)
        self.assertAlmostEqual(self.ctrl.duties[1], 0.4)
        self.assertAlmostEqual(self.ctrl.duties[0], 1.0)  # auto at ≥ MAX_TEMP_C

    def test_set_auto(self):
        self.ctrl.apply_control(1, "manual", 0.2)
        ok, code, _ = self.ctrl.set_auto(1)
        self.assertTrue(ok)
        self.ctrl.tick_logic(30.0, [0, 0, 0, 0], 1.0)
        self.assertEqual(self.ctrl.modes[0], "auto")
        self.assertAlmostEqual(self.ctrl.duties[0], fan.MIN_SPEED)

    def test_bad_fan_id(self):
        ok, code, _ = self.ctrl.apply_control(9, "manual", 0.5)
        self.assertFalse(ok)
        self.assertEqual(code, 404)

    def test_manual_requires_duty(self):
        ok, code, _ = self.ctrl.apply_control(1, "manual", None)
        self.assertFalse(ok)
        self.assertEqual(code, 400)

    def test_status_dict_shape(self):
        d = self.ctrl.status_dict()
        self.assertIn("die_c", d)
        self.assertEqual(len(d["fans"]), 4)
        self.assertEqual(d["fans"][0]["id"], 1)
```

Note: use `overrides_path=":memory:"` to skip file I/O in unit tests (`save_overrides`/`load_overrides` become no-ops that succeed, or keep an in-memory buffer). Prefer an in-memory buffer:

- If `overrides_path == ":memory:"`, keep `self._mem_overrides` string instead of touching disk.

- [ ] **Step 2: Run tests — expect fail**

Run: `python3 -m unittest tests.test_fan_logic.TestFanController -v`  
Expected: FAIL (`FanController` missing)

- [ ] **Step 3: Implement `FanController` in `fan.py`**

Add (after the helpers):

```python
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
        self._boot_ms = None

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
            # duty applied on next tick from curve; optionally set now if die known
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
```

Keep `tick_logic` applying PWM for auto fans every tick; manual fans already set via `apply_control`.

- [ ] **Step 4: Run tests — expect pass**

Run: `python3 -m unittest tests.test_fan_logic -v`  
Expected: all OK

- [ ] **Step 5: Commit**

```bash
git add fan.py tests/test_fan_logic.py
git commit -m "feat: add FanController modes and override persistence"
```

---

### Task 3: Real Pico hardware backend in `fan.py`

**Files:**
- Modify: `fan.py`

**Interfaces:**
- Produces:
  - `class PicoHw` with `set_duty`, `set_all_duty`, `read_die_temp_c`, `take_pulse_counts`, `failsafe`
  - `FanController.init_hardware(self)` — sets `self.hw = PicoHw()` if `hw` was None
  - `FanController.spinup(self)` — `set_all_duty(SPINUP_DUTY)`, sleep `SPINUP_TIME_S`, clear pulses
  - `FanController.tick(self, elapsed_s)` — read temp + pulses from hw, call `tick_logic`
  - `FanController.failsafe(self)` — hw full speed; **does not** call `save_overrides`

- [ ] **Step 1: Implement `PicoHw` and wire lifecycle methods**

Add to `fan.py` (guard import so host tests still work):

```python
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

            def _make(idx):
                def _handler(_pin):
                    self._pulse_counts[idx] += 1
                return _handler

            pin.irq(trigger=machine.Pin.IRQ_RISING, handler=_make(i))
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


# On FanController, add:

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
```

**Closure note:** the `_make(i)` pattern must capture index correctly (as in current `main.py`). Do not use a loop variable directly in the handler.

- [ ] **Step 2: Sanity-check host tests still pass**

Run: `python3 -m unittest tests.test_fan_logic -v`  
Expected: all OK (PicoHw not instantiated)

- [ ] **Step 3: Commit**

```bash
git add fan.py
git commit -m "feat: add Pico PWM/tach hardware backend"
```

---

### Task 4: Prometheus metrics formatter

**Files:**
- Create: `metrics.py`
- Create: `tests/test_metrics.py`

**Interfaces:**
- Consumes: `status_dict()` shape from FanController; `http_counts: dict[str, dict[str, int]]` mapping path bucket → code → count
- Produces: `format_metrics(status: dict, http_counts: dict) -> str`

- [ ] **Step 1: Write failing tests**

Create `tests/test_metrics.py`:

```python
import unittest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import metrics


class TestFormatMetrics(unittest.TestCase):
    def test_contains_locked_names(self):
        status = {
            "die_c": 31.5,
            "uptime_s": 12,
            "wifi": "connected",
            "ip": "1.2.3.4",
            "ssid": "x",
            "fans": [
                {"id": 1, "mode": "auto", "duty": 0.18, "rpm": 800.0},
                {"id": 2, "mode": "manual", "duty": 0.45, "rpm": 1200.0},
                {"id": 3, "mode": "auto", "duty": 0.18, "rpm": 0.0},
                {"id": 4, "mode": "auto", "duty": 0.18, "rpm": 0.0},
            ],
        }
        counts = {"/": {"200": 3}, "/metrics": {"200": 1}}
        text = metrics.format_metrics(status, counts)
        self.assertIn("pico_fan_die_temp_celsius 31.5", text)
        self.assertIn('pico_fan_duty_ratio{fan="2",mode="manual"} 0.45', text)
        self.assertIn('pico_fan_override{fan="2"} 1', text)
        self.assertIn('pico_fan_override{fan="1"} 0', text)
        self.assertIn("pico_fan_wifi_up 1", text)
        self.assertIn('pico_fan_http_requests_total{path="/",code="200"} 3', text)
        self.assertIn("# TYPE pico_fan_rpm gauge", text)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run — expect fail**

Run: `python3 -m unittest tests.test_metrics -v`  
Expected: import/attribute failure

- [ ] **Step 3: Implement `metrics.py`**

```python
"""Prometheus text exposition for the fan controller."""


def format_metrics(status, http_counts):
    lines = []

    def gauge(name, help_text):
        lines.append("# HELP {} {}".format(name, help_text))
        lines.append("# TYPE {} gauge".format(name))

    def counter(name, help_text):
        lines.append("# HELP {} {}".format(name, help_text))
        lines.append("# TYPE {} counter".format(name))

    gauge("pico_fan_die_temp_celsius", "RP2040 die temperature in Celsius")
    lines.append("pico_fan_die_temp_celsius {:.3f}".format(float(status["die_c"])))

    gauge("pico_fan_duty_ratio", "Fan PWM duty ratio 0-1")
    for f in status["fans"]:
        lines.append(
            'pico_fan_duty_ratio{{fan="{}",mode="{}"}} {:.4f}'.format(
                f["id"], f["mode"], float(f["duty"])
            )
        )

    gauge("pico_fan_rpm", "Fan tachometer RPM")
    for f in status["fans"]:
        lines.append('pico_fan_rpm{{fan="{}"}} {:.0f}'.format(f["id"], float(f["rpm"])))

    gauge("pico_fan_override", "1 if fan is in manual override")
    for f in status["fans"]:
        lines.append(
            'pico_fan_override{{fan="{}"}} {}'.format(
                f["id"], 1 if f["mode"] == "manual" else 0
            )
        )

    gauge("pico_fan_uptime_seconds", "Controller uptime in seconds")
    lines.append("pico_fan_uptime_seconds {}".format(int(status["uptime_s"])))

    gauge("pico_fan_wifi_up", "1 if Wi-Fi associated")
    wifi_up = 1 if status.get("wifi") == "connected" else 0
    lines.append("pico_fan_wifi_up {}".format(wifi_up))

    counter("pico_fan_http_requests_total", "HTTP responses by path bucket and code")
    for path, codes in http_counts.items():
        for code, n in codes.items():
            lines.append(
                'pico_fan_http_requests_total{{path="{}",code="{}"}} {}'.format(
                    path, code, int(n)
                )
            )

    lines.append("")
    return "\n".join(lines)
```

- [ ] **Step 4: Run — expect pass**

Run: `python3 -m unittest tests.test_metrics -v`  
Expected: OK

- [ ] **Step 5: Commit**

```bash
git add metrics.py tests/test_metrics.py
git commit -m "feat: add Prometheus metrics formatter"
```

---

### Task 5: HTTP routing helpers + request handling

**Files:**
- Create: `web.py`
- Create: `tests/test_web_handlers.py`

**Interfaces:**
- Consumes: `FanController.apply_control` / `set_auto` / `status_dict`; `metrics.format_metrics`
- Produces:
  - `path_bucket(path: str) -> str` — one of `/`, `/status.json`, `/metrics`, `/api/fans`, `other`
  - `parse_request_line(line: bytes) -> (method: str, path: str)`
  - `parse_fan_path(path: str) -> (fan_id: int|None, action: str|None)`  
    — `/api/fans/2` → `(2, "set")`; `/api/fans/2/auto` → `(2, "auto")`; else `(None, None)`
  - `parse_json_body(body: bytes) -> dict|None`
  - `class HttpServer` with `start(port)`, `poll()`, `http_counts`, holds refs to `fan_ctrl`

- [ ] **Step 1: Write failing tests for pure helpers**

Create `tests/test_web_handlers.py`:

```python
import unittest
import sys
import os
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import web
import fan


class TestPathHelpers(unittest.TestCase):
    def test_path_bucket(self):
        self.assertEqual(web.path_bucket("/"), "/")
        self.assertEqual(web.path_bucket("/index.html"), "/")
        self.assertEqual(web.path_bucket("/status.json"), "/status.json")
        self.assertEqual(web.path_bucket("/metrics"), "/metrics")
        self.assertEqual(web.path_bucket("/api/fans/1"), "/api/fans")
        self.assertEqual(web.path_bucket("/api/fans/1/auto"), "/api/fans")
        self.assertEqual(web.path_bucket("/nope"), "other")

    def test_parse_fan_path(self):
        self.assertEqual(web.parse_fan_path("/api/fans/3"), (3, "set"))
        self.assertEqual(web.parse_fan_path("/api/fans/3/auto"), (3, "auto"))
        self.assertEqual(web.parse_fan_path("/api/fans/99"), (99, "set"))
        self.assertEqual(web.parse_fan_path("/status.json"), (None, None))

    def test_parse_json_body(self):
        self.assertEqual(web.parse_json_body(b'{"mode":"manual","duty":0.5}'),
                         {"mode": "manual", "duty": 0.5})
        self.assertIsNone(web.parse_json_body(b"{"))


class TestHandleControl(unittest.TestCase):
    def setUp(self):
        class FakeHw:
            def __init__(self):
                self.duties = [0.0] * fan.FAN_COUNT
            def set_duty(self, i, f):
                self.duties[i] = f
            def set_all_duty(self, f):
                for i in range(fan.FAN_COUNT):
                    self.duties[i] = f
            def read_die_temp_c(self):
                return 30.0
            def take_pulse_counts(self):
                return [0] * fan.FAN_COUNT

        self.ctrl = fan.FanController(hw=FakeHw(), overrides_path=":memory:")
        self.srv = web.HttpServer(self.ctrl, metrics_module=__import__("metrics"))

    def test_dispatch_manual(self):
        code, body, ctype = self.srv.dispatch(
            "POST", "/api/fans/2", b'{"mode":"manual","duty":0.33}'
        )
        self.assertEqual(code, 200)
        self.assertEqual(self.ctrl.modes[1], "manual")
        self.assertIn(b"duty", body)

    def test_dispatch_auto_path(self):
        self.ctrl.apply_control(2, "manual", 0.5)
        code, body, ctype = self.srv.dispatch("POST", "/api/fans/2/auto", b"")
        self.assertEqual(code, 200)
        self.assertEqual(self.ctrl.modes[1], "auto")


if __name__ == "__main__":
    unittest.main()
```

Simplify Step 1: do **not** reference `fan.tests_fake_hw`; keep FakeHw inline only (as in the second class).

- [ ] **Step 2: Run — expect fail**

Run: `python3 -m unittest tests.test_web_handlers -v`  
Expected: fail missing `web`

- [ ] **Step 3: Implement `web.py` helpers + `HttpServer.dispatch` + full poll server**

Implement at minimum:

```python
def path_bucket(path):
    if path in ("/", "/index.html"):
        return "/"
    if path in ("/status.json", "/api", "/api/status"):
        return "/status.json"
    if path == "/metrics":
        return "/metrics"
    if path.startswith("/api/fans"):
        return "/api/fans"
    return "other"


def parse_request_line(line):
    parts = line.split()
    method = parts[0].decode() if parts else "GET"
    path = parts[1].decode() if len(parts) > 1 else "/"
    # strip query string
    if "?" in path:
        path = path.split("?", 1)[0]
    return method, path


def parse_fan_path(path):
    # /api/fans/<id> or /api/fans/<id>/auto
    prefix = "/api/fans/"
    if not path.startswith(prefix):
        return None, None
    rest = path[len(prefix):]
    bits = rest.split("/")
    try:
        fan_id = int(bits[0])
    except ValueError:
        return None, None
    if len(bits) == 1:
        return fan_id, "set"
    if len(bits) == 2 and bits[1] == "auto":
        return fan_id, "auto"
    return None, None


def parse_json_body(body):
    try:
        import json
    except ImportError:
        import ujson as json
    try:
        data = json.loads(body.decode() if isinstance(body, bytes) else body)
    except Exception:
        return None
    return data if isinstance(data, dict) else None
```

`HttpServer`:
- `__init__(self, fan_ctrl, metrics_module)`
- `http_counts = {}` nested dict; `_bump(path_bucket, code)`
- `dispatch(method, path, body) -> (code, body_bytes, content_type)` for unit tests and used by `poll`
- `format_status_json`, `_format_html` (control UI with inline JS)
- `start(port)`, `poll()` — port non-blocking accept from current `main.py` pattern
- On control success: return status JSON
- Content-Type for metrics: `text/plain; version=0.0.4; charset=utf-8`

**HTML UI requirements (inline in `_format_html`):**
- Table/cards for fans 1–4: RPM, duty %, mode, range input 0–100, Auto / Manual buttons
- Poll `GET /status.json` every 2s; update DOM
- On slider `change`: `POST /api/fans/<id>` with `{"mode":"manual","duty": duty/100}`
- On Auto: `POST /api/fans/<id>/auto`
- Links to `/metrics` and `/status.json`
- Show die °C, uptime, wifi, ip

Keep CSS minimal (reuse current page aesthetic: system font, simple table). Micropython: avoid large HTML; keep under ~8–12 KB.

**POST body reading:** after headers, if `Content-Length` present, read that many bytes (cap e.g. 512).

- [ ] **Step 4: Run — expect pass**

Run: `python3 -m unittest tests.test_web_handlers tests.test_fan_logic tests.test_metrics -v`  
Expected: all OK

- [ ] **Step 5: Commit**

```bash
git add web.py tests/test_web_handlers.py
git commit -m "feat: add HTTP control UI API and metrics route"
```

---

### Task 6: Thin `main.py` wiring

**Files:**
- Modify: `main.py` (replace shared-PWM monolith)

**Interfaces:**
- Consumes: `fan.FanController`, `web.HttpServer`, `config`

- [ ] **Step 1: Rewrite `main.py`**

```python
"""
Raspberry Pi Pico W — 4-fan thermal PWM controller + web control + Prometheus.
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
    led = _make_led()
    ctrl = fan.FanController()
    ctrl.init_hardware()
    boot_ms = time.ticks_ms()

    print("Pico thermal fan controller ({} fans, per-fan PWM)".format(fan.FAN_COUNT))
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
    # refresh die before applying overrides for auto fans
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
    ctrl_ref = None
    try:
        # allow failsafe access — instantiate inside main; duplicate handle:
        main()
    except KeyboardInterrupt:
        print("\nInterrupted — fail-safe: fans 100%, LED on")
        try:
            # best-effort: construct hw failsafe if main already built controller
            pass
        except Exception:
            pass
        # Prefer storing controller on module during main for failsafe:
        raise SystemExit(0)
```

**Fix fail-safe properly in the same step** — use a module-level `_ctrl`:

```python
_ctrl = None

def main():
    global _ctrl
    ...
    _ctrl = ctrl
    ...

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
```

Ensure `HttpServer.start` / `poll` match the existing non-blocking socket pattern from the old `main.py` (copy bind/listen/accept/recv logic into `web.py` if not already done in Task 5).

- [ ] **Step 2: Host regression**

Run: `python3 -m unittest discover -s tests -v`  
Expected: all OK

- [ ] **Step 3: Commit**

```bash
git add main.py
git commit -m "feat: wire per-fan controller HTTP and main loop"
```

---

### Task 7: README + device smoke checklist

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Update README**

Replace shared-PWM sections with:
- Per-fan PWM pin table (GP15–18 / tach GP14–11)
- Wiring diagram: four separate PWM wires; tach pull-ups **10 kΩ** to 3V3
- Flash list: `config.py`, `main.py`, `fan.py`, `web.py`, `metrics.py`
- Web: control UI on `/`, JSON `/status.json`, Prometheus `/metrics`
- API examples:

```bash
curl -X POST http://PICO_IP/api/fans/2 -H 'Content-Type: application/json' \
  -d '{"mode":"manual","duty":0.4}'
curl http://PICO_IP/metrics
```

- Overrides: `overrides.json` on device; reboot restores; fail-safe does not wipe
- Mermaid/ASCII diagrams updated (no shared PWM tee)

- [ ] **Step 2: Device smoke (manual, on Pico)**

After flash/rewire:
1. Serial shows per-fan PWM pins and `die=… F1=a=…`
2. Open `http://<ip>/` — set fan 2 manual 40%; others track temp
3. Reboot — fan 2 still manual 40%
4. `curl /metrics` shows locked metric names
5. Ctrl+C — fans full speed; soft reboot restores overrides

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: update README for per-fan PWM and Prometheus"
```

---

## Spec coverage (self-review)

| Spec item | Task |
|-----------|------|
| Per-fan PWM pins GP15–18 | 3, 6, 7 |
| Per-fan manual override + auto curve | 2, 5, 6 |
| Full UI on `/` | 5 |
| Rich `/metrics` | 4, 5 |
| `overrides.json` persistence; fail-safe skips write | 2, 3, 6 |
| Module split | 1–6 |
| 10 kΩ pull-ups in docs | 7 |
| API routes | 5 |
| README / flash list | 7 |

## Placeholder / consistency check

- Metric names match spec exactly.
- Fan IDs are 1-based in HTTP; 0-based internally.
- `apply_control` / `set_auto` return `(ok, code, message)` consistently for web dispatch.
- Host tests never instantiate `PicoHw`.
