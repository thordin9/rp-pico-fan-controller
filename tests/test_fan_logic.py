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


if __name__ == "__main__":
    unittest.main()
