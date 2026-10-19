"""Sensor sanity checks: range, jump, stuck, stale, tach, and pressure delta."""

import os
import sys
import types
import unittest

sys.modules.setdefault("machine", types.ModuleType("machine"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import fan
import faults
import main
import metrics
import web
from display import build_pages


def _sensor(temp, pressure, raw=(1, 2), ok=True, error="", enabled=True):
    return {
        "enabled": enabled,
        "ok": ok,
        "chip_id": 0x58,
        "temp_c": temp,
        "pressure_pa": pressure,
        "error": error,
        "raw": raw,
    }


def _snap(internal, external, raw_i=(1, 2), raw_e=(3, 4)):
    if internal is not None:
        internal = dict(internal)
        internal.setdefault("raw", raw_i)
    if external is not None:
        external = dict(external)
        external.setdefault("raw", raw_e)
    return {
        "sensors": {
            "internal": internal
            if internal is not None
            else fan.blank_sensor_status(),
            "external": external
            if external is not None
            else fan.blank_sensor_status(),
        }
    }


class TestFaultMonitor(unittest.TestCase):
    def _monitor(self, **overrides):
        cfg = dict(faults.DEFAULT_CFG)
        cfg["sensor_fault_set_samples"] = 1
        cfg["sensor_fault_clear_samples"] = 2
        cfg["bmp280_stuck_samples"] = 3
        cfg.update(overrides)
        return faults.FaultMonitor(cfg, die_safe_c=55.0)

    def test_pressure_out_of_range_does_not_publish_the_value(self):
        mon = self._monitor()
        status = _sensor(25.0, 135382.0)
        out = mon.observe_bmp280("external", 0, status, status["raw"])
        self.assertFalse(out["ok"])
        self.assertIsNone(out["pressure_pa"])
        self.assertIsNone(out["temp_c"])
        self.assertTrue(out["fault"])
        self.assertEqual(out["fault_reason"], "pressure_out_of_range")
        self.assertEqual(
            out["error"],
            "External BMP280: possible fault \u2013 pressure out of range",
        )

    def test_temperature_jump_and_recovery(self):
        mon = self._monitor()
        first = mon.observe_bmp280("internal", 0, _sensor(25.0, 100000.0), (1, 1))
        self.assertTrue(first["ok"])
        jumped = mon.observe_bmp280("internal", 1000, _sensor(40.0, 100000.0), (2, 2))
        self.assertFalse(jumped["ok"])
        self.assertEqual(jumped["fault_reason"], "temp_jump")
        # Returning to 25 is a jump away from the spike, then two stable
        # samples clear the fault (clear_n is 2).
        back = mon.observe_bmp280("internal", 2000, _sensor(25.0, 100000.0), (3, 3))
        self.assertFalse(back["ok"])
        settled = mon.observe_bmp280("internal", 3000, _sensor(25.1, 100010.0), (4, 4))
        self.assertFalse(settled["ok"])
        self.assertTrue(settled["fault"])
        recovered = mon.observe_bmp280(
            "internal", 4000, _sensor(25.2, 100020.0), (5, 5)
        )
        self.assertTrue(recovered["ok"])
        self.assertFalse(recovered["fault"])
        self.assertEqual(mon.active(), [])

    def test_a_sustained_step_is_accepted_after_debounce(self):
        mon = self._monitor()
        mon.observe_bmp280("internal", 0, _sensor(25.0, 100000.0), (1, 1))
        mon.observe_bmp280("internal", 1000, _sensor(40.0, 100000.0), (2, 2))
        held = mon.observe_bmp280("internal", 2000, _sensor(40.1, 100010.0), (3, 3))
        self.assertFalse(held["ok"])
        accepted = mon.observe_bmp280(
            "internal", 3000, _sensor(40.0, 100020.0), (4, 4)
        )
        self.assertTrue(accepted["ok"])
        self.assertAlmostEqual(accepted["temp_c"], 40.0)

    def test_stuck_raw_latches_and_a_new_raw_can_clear(self):
        mon = self._monitor()
        raw = (415148, 519888)
        for _ in range(2):
            out = mon.observe_bmp280("internal", 0, _sensor(25.0, 100653.0), raw)
            self.assertTrue(out["ok"])
        stuck = mon.observe_bmp280("internal", 0, _sensor(25.0, 100653.0), raw)
        self.assertFalse(stuck["ok"])
        self.assertEqual(stuck["fault_reason"], "stuck")
        mon.observe_bmp280("internal", 0, _sensor(25.1, 100660.0), (1, 9))
        cleared = mon.observe_bmp280("internal", 0, _sensor(25.1, 100670.0), (2, 9))
        self.assertTrue(cleared["ok"])

    def test_failed_read_becomes_stale(self):
        mon = self._monitor(sensor_stale_s=5, sensor_fault_set_samples=2)
        good = _sensor(25.0, 100000.0)
        mon.observe_bmp280("external", 0, good, (1, 1))
        failed = _sensor(None, None, ok=False, error="read failed: nack")
        early = mon.observe_bmp280("external", 1000, failed, None)
        self.assertEqual(early["error"], "read failed: nack")
        self.assertFalse(early["fault"])
        latched = mon.observe_bmp280("external", 2000, failed, None)
        self.assertEqual(latched["fault_reason"], "read_failed")
        stale = mon.observe_bmp280("external", 6001, failed, None)
        self.assertEqual(stale["fault_reason"], "stale")
        self.assertIn("reading stale", stale["error"])

    def test_die_rejects_impossible_and_holds_last_good(self):
        mon = self._monitor(sensor_fault_set_samples=2, sensor_stale_s=5)
        self.assertAlmostEqual(mon.observe_die(0, 30.0, True), 30.0)
        self.assertAlmostEqual(mon.observe_die(1000, 250.0, True), 30.0)
        self.assertEqual(mon.active(), [])
        self.assertAlmostEqual(mon.observe_die(2000, 250.0, True), 30.0)
        self.assertEqual(mon.active()[0]["reason"], "die_out_of_range")
        # The bad reading is older than the stale window, so the curve goes high.
        self.assertAlmostEqual(mon.observe_die(8000, 250.0, True), 55.0)

    def test_die_read_failure_uses_safe_temperature_when_nothing_was_trusted(self):
        mon = self._monitor()
        self.assertAlmostEqual(mon.observe_die(0, None, False), 55.0)
        self.assertEqual(mon.active()[0]["sensor"], "die")

    def test_pressure_delta_is_dropped_when_implausible(self):
        mon = self._monitor(sensor_fault_set_samples=2, sensor_fault_clear_samples=3)
        self.assertIsNone(mon.observe_delta(11000.0))
        self.assertEqual(mon.active(), [])
        self.assertIsNone(mon.observe_delta(11000.0))
        self.assertEqual(mon.active()[0]["reason"], "pressure_delta")
        self.assertEqual(
            mon.active()[0]["label"],
            "Pressure difference: possible fault \u2013 pressure difference out of range",
        )
        # A sane delta is not used until the clear debounce finishes.
        self.assertIsNone(mon.observe_delta(12.0))
        self.assertIsNone(mon.observe_delta(12.0))
        self.assertAlmostEqual(mon.observe_delta(12.0), 12.0)

    def test_counter_increments_once_per_latch(self):
        mon = self._monitor()
        mon.observe_bmp280("external", 0, _sensor(25.0, 20000.0), (1, 1))
        mon.observe_bmp280("external", 1000, _sensor(25.0, 20000.0), (1, 2))
        rows = mon.count_rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["count"], 1)
        self.assertEqual(rows[0]["reason"], "pressure_out_of_range")


class _Hw:
    def __init__(self, die=30.0):
        self.die = die
        self.duties = [0.0] * fan.FAN_COUNT
        self.pulses = [0] * fan.FAN_COUNT

    def set_duty(self, index, fraction):
        self.duties[index] = fraction

    def set_all_duty(self, fraction):
        for i in range(fan.FAN_COUNT):
            self.duties[i] = fraction

    def read_die_temp_c(self):
        if isinstance(self.die, Exception):
            raise self.die
        return self.die

    def take_pulse_counts(self):
        return list(self.pulses)

    def failsafe(self):
        raise RuntimeError("pwm dead")


class TestControllerFaults(unittest.TestCase):
    def _ctrl(self, **cfg):
        base = dict(faults.DEFAULT_CFG)
        base.update(cfg)
        return fan.FanController(
            hw=_Hw(), overrides_path=":memory:", fault_cfg=base
        )

    def test_bad_external_pressure_does_not_drive_the_loop(self):
        ctrl = self._ctrl(sensor_fault_set_samples=1)
        ctrl.note_sensors(
            _snap(
                _sensor(28.0, 100653.0),
                _sensor(22.0, 135382.0),
            ),
            now_ms=0,
        )
        self.assertTrue(ctrl.sensor_state["internal"]["ok"])
        self.assertFalse(ctrl.sensor_state["external"]["ok"])
        self.assertIsNone(ctrl.pressure_delta_pa)
        ctrl.tick_logic(
            30.0,
            [0, 0, 0, 0],
            1.0,
            internal_c=28.0,
            internal_ok=True,
            pressure_delta_pa=ctrl.pressure_delta_pa,
        )
        self.assertEqual(ctrl.temp_source, "internal")
        self.assertFalse(ctrl.pressure_loop_active)
        self.assertIn("pressure out of range", ctrl.status_dict()["faults"][0]["label"])

    def test_bad_internal_temperature_falls_back_to_die(self):
        ctrl = self._ctrl(sensor_fault_set_samples=1)
        ctrl.note_sensors(_snap(_sensor(120.0, 100000.0), None), now_ms=0)
        self.assertFalse(ctrl.sensor_state["internal"]["ok"])
        ctrl.tick_logic(
            30.0,
            [0, 0, 0, 0],
            1.0,
            internal_c=None,
            internal_ok=False,
        )
        self.assertEqual(ctrl.temp_source, "die")
        self.assertAlmostEqual(ctrl.control_c, 30.0)

    def test_sample_path_ignores_an_implausible_delta(self):
        ctrl = self._ctrl(sensor_fault_set_samples=2)

        class Sensors:
            def read(self):
                return _snap(
                    _sensor(28.0, 101000.0),
                    _sensor(22.0, 90000.0),
                )

        main.sample_peripherals(ctrl, Sensors(), None, 1.0, 1000)
        self.assertIsNone(ctrl.pressure_delta_pa)
        self.assertFalse(ctrl.pressure_loop_active)
        self.assertEqual(ctrl.temp_source, "internal")
        main.sample_peripherals(ctrl, Sensors(), None, 1.0, 2000)
        reasons = [item["reason"] for item in ctrl.status_dict()["faults"]]
        self.assertIn("pressure_delta", reasons)

    def test_high_rpm_is_not_smoothed_in_and_zero_duty_rpm_is_a_fault(self):
        ctrl = self._ctrl(sensor_fault_set_samples=2)
        ctrl.apply_control(1, "manual", 0.5)
        # 400 pulses/s at 2 pulses/rev is 12000 RPM, above the 10000 cap.
        ctrl.tick_logic(30.0, [400, 0, 0, 0], 1.0)
        self.assertEqual(ctrl.rpms[0], 0.0)
        ctrl.tick_logic(30.0, [400, 0, 0, 0], 1.0)
        self.assertEqual(ctrl.rpms[0], 0.0)
        high = [
            item
            for item in ctrl.status_dict()["faults"]
            if item["reason"] == "rpm_high"
        ]
        self.assertEqual(high[0]["location"], "1")
        ctrl.apply_control(2, "manual", 0.0)
        ctrl.tick_logic(30.0, [0, 80, 0, 0], 1.0)
        ctrl.tick_logic(30.0, [0, 80, 0, 0], 1.0)
        zero = [
            item
            for item in ctrl.status_dict()["faults"]
            if item["reason"] == "rpm_at_zero_duty"
        ]
        self.assertEqual(zero[0]["label"].startswith("Fan 2 tach"), True)
        self.assertFalse(ctrl.stalls[1])

    def test_die_glitch_in_tick_does_not_drive_the_curve(self):
        hw = _Hw(30.0)
        ctrl = fan.FanController(hw=hw, overrides_path=":memory:")
        ctrl.tick(1.0, now_ms=0)
        self.assertAlmostEqual(ctrl.die_c, 30.0)
        hw.die = 400.0
        ctrl.tick(1.0, now_ms=1000)
        self.assertAlmostEqual(ctrl.die_c, 30.0)
        self.assertAlmostEqual(ctrl.duties[0], fan.MIN_SPEED)

    def test_status_page_badge_oled_and_metrics(self):
        ctrl = self._ctrl(sensor_fault_set_samples=1)
        ctrl.note_sensors(
            _snap(_sensor(25.0, 100000.0), _sensor(25.0, 135000.0)),
            now_ms=0,
        )
        status = ctrl.status_dict()
        pages = build_pages(status)
        self.assertEqual(len(pages), 5)
        self.assertEqual(pages[4][0], "SENSOR FAULT")
        self.assertEqual(pages[4][1], "EXT BMP280")
        self.assertEqual(pages[4][2], "pressure range")
        for page in pages:
            for line in page:
                self.assertLessEqual(len(line), 16)
        text = metrics.format_metrics(status, {})
        self.assertIn(
            'pico_fan_sensor_fault{sensor="bmp280",location="external",reason="pressure_out_of_range"} 1',
            text,
        )
        self.assertIn(
            'pico_fan_sensor_fault_total{sensor="bmp280",location="external",reason="pressure_out_of_range"} 1',
            text,
        )
        self.assertNotIn("135000", text)
        page = web.HttpServer(ctrl, metrics)._format_html()
        self.assertIn("External BMP280: possible fault", page)
        self.assertIn("pressure out of range", page)
        self.assertIn("class='fault'", page)
        body = web.HttpServer(ctrl, metrics).format_status_json()
        self.assertIn("pressure_out_of_range", body)


if __name__ == "__main__":
    unittest.main()
