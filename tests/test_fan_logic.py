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
