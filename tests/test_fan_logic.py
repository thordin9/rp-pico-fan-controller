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
        self.assertIn("stall", d["fans"][0])

    def test_duty_out_of_range_is_400_and_does_not_persist(self):
        before = list(self.ctrl.duties)
        modes = list(self.ctrl.modes)
        hw_before = list(self.hw.duties)
        ok, code, msg = self.ctrl.apply_control(1, "manual", 1.5)
        self.assertFalse(ok)
        self.assertEqual(code, 400)
        self.assertEqual(msg, "duty out of range")
        ok, code, msg = self.ctrl.apply_control(2, "manual", -0.01)
        self.assertEqual(code, 400)
        self.assertEqual(msg, "duty out of range")
        ok, code, msg = self.ctrl.apply_control(1, "manual", True)
        self.assertEqual(code, 400)
        self.assertEqual(msg, "invalid duty")
        ok, code, msg = self.ctrl.apply_control(1, "manual", "0.4")
        self.assertEqual(code, 400)
        self.assertEqual(msg, "invalid duty")
        self.assertEqual(self.ctrl.duties, before)
        self.assertEqual(self.ctrl.modes, modes)
        self.assertEqual(self.hw.duties, hw_before)
        self.assertIsNone(self.ctrl._mem_overrides)

    def test_manual_zero_and_full_scale_allowed(self):
        ok, code, _ = self.ctrl.apply_control(1, "manual", 0)
        self.assertTrue(ok)
        self.assertEqual(code, 200)
        self.assertEqual(self.ctrl.duties[0], 0.0)
        ok, code, _ = self.ctrl.apply_control(1, "manual", 1)
        self.assertTrue(ok)
        self.assertEqual(self.ctrl.duties[0], 1.0)

    def test_auto_ignores_out_of_range_duty(self):
        self.ctrl.apply_control(1, "manual", 0.3)
        ok, code, _ = self.ctrl.apply_control(1, "auto", 9)
        self.assertTrue(ok)
        self.assertEqual(code, 200)
        self.assertEqual(self.ctrl.modes[0], "auto")

    def test_stall_when_commanded_and_rpm_reads_zero(self):
        self.ctrl.apply_control(1, "manual", 0.5)
        self.ctrl.tick_logic(30.0, [0, 0, 0, 0], 1.0)
        self.assertTrue(self.ctrl.stalls[0])
        self.assertTrue(self.ctrl.status_dict()["fans"][0]["stall"])
        # Other auto fans are at the curve floor with no pulses, so they stall too.
        self.assertTrue(self.ctrl.stalls[1])

    def test_zero_duty_is_not_a_stall(self):
        self.ctrl.apply_control(1, "manual", 0.0)
        self.ctrl.tick_logic(30.0, [0, 0, 0, 0], 1.0)
        self.assertFalse(self.ctrl.stalls[0])
        self.assertEqual(self.ctrl.duties[0], 0.0)

    def test_spinning_fan_is_not_a_stall(self):
        self.ctrl.apply_control(1, "manual", 0.5)
        self.ctrl.tick_logic(30.0, [100, 80, 80, 80], 1.0)
        self.assertFalse(self.ctrl.stalls[0])
        self.assertGreater(self.ctrl.rpms[0], 0)

    def test_stall_threshold_is_configurable(self):
        ctrl = fan.FanController(
            hw=self.hw, overrides_path=":memory:", stall_duty_min=0.40
        )
        ctrl.apply_control(1, "manual", 0.20)
        ctrl.tick_logic(30.0, [0, 0, 0, 0], 1.0)
        self.assertFalse(ctrl.stalls[0])
        ctrl.apply_control(1, "manual", 0.40)
        ctrl.tick_logic(30.0, [0, 0, 0, 0], 1.0)
        self.assertTrue(ctrl.stalls[0])

    def test_zero_elapsed_does_not_raise_stall(self):
        self.ctrl.apply_control(1, "manual", 0.5)
        self.ctrl.tick_logic(30.0, [0, 0, 0, 0], 0)
        self.assertFalse(self.ctrl.stalls[0])

    def test_prepare_fans_applies_curve_before_any_network(self):
        sleeps = []
        feeds = []
        orig = fan.time.sleep
        fan.time.sleep = lambda delay: sleeps.append(delay)
        try:
            loaded = self.ctrl.prepare_fans(feed=lambda: feeds.append(1))
        finally:
            fan.time.sleep = orig
        self.assertFalse(loaded)
        self.assertAlmostEqual(self.ctrl.duties[0], fan.MIN_SPEED)
        self.assertAlmostEqual(self.hw.duties[0], fan.MIN_SPEED)
        self.assertNotEqual(self.hw.duties[0], 0.0)
        self.assertGreaterEqual(len(feeds), 2)
        self.assertAlmostEqual(sum(sleeps), fan.SPINUP_TIME_S, places=3)
        self.assertLessEqual(max(sleeps), fan.SPINUP_STEP_S + 1e-9)

    def test_prepare_fans_restores_saved_manual_after_spinup(self):
        self.ctrl.apply_control(2, "manual", 0.4)
        orig = fan.time.sleep
        fan.time.sleep = lambda delay: None
        try:
            loaded = self.ctrl.prepare_fans(feed=lambda: None)
        finally:
            fan.time.sleep = orig
        self.assertTrue(loaded)
        self.assertEqual(self.ctrl.modes[1], "manual")
        self.assertAlmostEqual(self.ctrl.duties[1], 0.4)
        self.assertAlmostEqual(self.hw.duties[1], 0.4)
        self.assertAlmostEqual(self.ctrl.duties[0], fan.MIN_SPEED)


class TestSignalConditioning(unittest.TestCase):
    def test_average_adc_raw(self):
        self.assertEqual(fan.average_adc_raw([10, 20, 30, 40]), 25)
        self.assertEqual(fan.average_adc_raw([5]), 5)
        self.assertEqual(fan.average_adc_raw([]), 0)

    def test_adc_raw_at_27c_reference(self):
        raw = round(0.706 / 3.3 * 65535)
        self.assertAlmostEqual(fan.adc_raw_to_temp_c(raw), 27.0, places=1)

    def test_tach_debounce_rejects_close_edges(self):
        counts = [0]
        last = [0]
        seen = bytearray(1)
        self.assertTrue(fan.note_tach_pulse(counts, last, seen, 0, 5000, 1000))
        self.assertEqual(counts[0], 1)
        self.assertFalse(fan.note_tach_pulse(counts, last, seen, 0, 5500, 1000))
        self.assertEqual(counts[0], 1)
        self.assertTrue(fan.note_tach_pulse(counts, last, seen, 0, 6500, 1000))
        self.assertEqual(counts[0], 2)

    def test_tach_debounce_handles_ticks_wrap(self):
        counts = [0]
        last = [(1 << 30) - 100]
        seen = bytearray(b"\x01")
        self.assertFalse(fan.note_tach_pulse(counts, last, seen, 0, 50, 1000))
        self.assertEqual(counts[0], 0)
        self.assertTrue(fan.note_tach_pulse(counts, last, seen, 0, 1000, 1000))
        self.assertEqual(counts[0], 1)

    def test_led_blinks_on_half_period_and_stays_on_when_hot(self):
        self.assertTrue(fan.led_is_on(0.1, 0))
        self.assertTrue(fan.led_is_on(0.1, 499))
        self.assertFalse(fan.led_is_on(0.1, 500))
        self.assertFalse(fan.led_is_on(0.1, 999))
        self.assertTrue(fan.led_is_on(0.1, 1000))
        self.assertTrue(fan.led_is_on(0.5, 500))
        self.assertTrue(fan.led_is_on(1.0, 750))


if __name__ == "__main__":
    unittest.main()
