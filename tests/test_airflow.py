import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import fan


class TestAirflowMath(unittest.TestCase):
    def test_default_bias_and_floor(self):
        base = fan.temp_to_duty(30.0)
        self.assertAlmostEqual(base, fan.MIN_SPEED)
        intake = fan.auto_duty_for_role(base, "intake", 0.85, 0.0)
        exhaust = fan.auto_duty_for_role(base, "exhaust", 0.85, 0.0)
        self.assertAlmostEqual(intake, fan.MIN_SPEED)
        self.assertAlmostEqual(exhaust, fan.MIN_SPEED * 0.85)
        self.assertGreater(exhaust, fan.STALL_DUTY_MIN)
        self.assertLess(exhaust, intake)

    def test_offset_and_clamp(self):
        duty = fan.auto_duty_for_role(1.0, "exhaust", 1.0, -0.05)
        self.assertAlmostEqual(duty, 0.95)
        self.assertEqual(fan.auto_duty_for_role(1.0, "exhaust", 2.0, 0.5), 1.0)
        self.assertEqual(fan.auto_duty_for_role(0.2, "exhaust", 0.0, -1.0), 0.0)

    def test_pressure_loop_moves_only_exhaust(self):
        base = 0.5
        plain = fan.auto_duty_for_role(base, "exhaust", 1.0, 0.0, delta_pa=0.0)
        trimmed = fan.auto_duty_for_role(
            base,
            "exhaust",
            1.0,
            0.0,
            delta_pa=0.0,
            target_pa=5.0,
            gain=0.01,
            loop_enabled=True,
        )
        # delta below target lowers exhaust so the enclosure pressure rises.
        self.assertAlmostEqual(plain, 0.5)
        self.assertAlmostEqual(trimmed, 0.45)
        intake = fan.auto_duty_for_role(
            base,
            "intake",
            1.0,
            0.0,
            delta_pa=0.0,
            target_pa=5.0,
            gain=0.01,
            loop_enabled=True,
        )
        self.assertAlmostEqual(intake, base)
        # No delta, or the loop switched off: leave the ratio result alone.
        self.assertAlmostEqual(
            fan.auto_duty_for_role(
                base, "exhaust", 0.85, 0.0, delta_pa=None, loop_enabled=True, gain=1
            ),
            0.5 * 0.85,
        )

    def test_select_control_temp(self):
        self.assertEqual(fan.select_control_temp(31.0, 28.0, True), (28.0, "internal"))
        self.assertEqual(fan.select_control_temp(31.0, 28.0, False), (31.0, "die"))
        self.assertEqual(fan.select_control_temp(31.0, None, True), (31.0, "die"))
        self.assertEqual(fan.select_control_temp(31.0, "nope", True), (31.0, "die"))


class FakeHw:
    def __init__(self):
        self.duties = [0.0] * fan.FAN_COUNT
        self.die = 30.0

    def set_duty(self, index, fraction):
        self.duties[index] = fraction

    def set_all_duty(self, fraction):
        for i in range(fan.FAN_COUNT):
            self.duties[i] = fraction

    def read_die_temp_c(self):
        return self.die

    def take_pulse_counts(self):
        return [0] * fan.FAN_COUNT


class TestControllerAirflow(unittest.TestCase):
    def setUp(self):
        self.hw = FakeHw()
        self.ctrl = fan.FanController(hw=self.hw, overrides_path=":memory:")

    def test_defaults_match_config(self):
        self.assertEqual(tuple(self.ctrl.roles), ("intake", "intake", "exhaust", "exhaust"))
        self.assertAlmostEqual(self.ctrl.exhaust_ratio, 0.85)
        self.assertFalse(self.ctrl.pressure_loop)
        self.assertEqual(self.ctrl.temp_source, "die")

    def test_internal_temp_drives_curve_and_exhaust_is_biased(self):
        self.ctrl.tick_logic(
            30.0, [0, 0, 0, 0], 1.0, internal_c=55.0, internal_ok=True
        )
        self.assertEqual(self.ctrl.temp_source, "internal")
        self.assertAlmostEqual(self.ctrl.control_c, 55.0)
        self.assertAlmostEqual(self.ctrl.duties[0], 1.0)
        self.assertAlmostEqual(self.ctrl.duties[1], 1.0)
        self.assertAlmostEqual(self.ctrl.duties[2], 0.85)
        self.assertAlmostEqual(self.ctrl.duties[3], 0.85)
        self.assertEqual(self.ctrl.status_dict()["fans"][0]["role"], "intake")
        self.assertEqual(self.ctrl.status_dict()["fans"][2]["role"], "exhaust")

    def test_runtime_fallback_to_die(self):
        self.ctrl.tick_logic(
            30.0, [0, 0, 0, 0], 1.0, internal_c=55.0, internal_ok=True
        )
        self.ctrl.tick_logic(
            30.0, [0, 0, 0, 0], 1.0, internal_c=55.0, internal_ok=False
        )
        self.assertEqual(self.ctrl.temp_source, "die")
        self.assertAlmostEqual(self.ctrl.duties[0], fan.MIN_SPEED)
        self.assertAlmostEqual(self.ctrl.duties[2], fan.MIN_SPEED * 0.85)

    def test_manual_overrides_role_and_stall_follows_commanded_duty(self):
        self.ctrl.apply_control(3, "manual", 0.4)
        self.ctrl.tick_logic(
            55.0, [0, 0, 0, 0], 1.0, internal_c=55.0, internal_ok=True
        )
        self.assertAlmostEqual(self.ctrl.duties[2], 0.4)
        self.assertTrue(self.ctrl.stalls[2])
        self.assertAlmostEqual(self.ctrl.duties[0], 1.0)
        # Exhaust at the idle bias is still above the stall threshold.
        self.ctrl.tick_logic(30.0, [0, 0, 0, 0], 1.0)
        self.assertTrue(self.ctrl.stalls[3])
        quiet = fan.FanController(
            hw=self.hw,
            overrides_path=":memory:",
            exhaust_ratio=0.5,
            roles=("intake", "intake", "exhaust", "exhaust"),
        )
        quiet.tick_logic(30.0, [0, 0, 0, 0], 1.0)
        self.assertLess(quiet.duties[2], quiet.stall_duty_min)
        self.assertFalse(quiet.stalls[2])
        self.assertTrue(quiet.stalls[0])

    def test_pressure_loop_and_custom_roles(self):
        ctrl = fan.FanController(
            hw=self.hw,
            overrides_path=":memory:",
            roles=("exhaust", "intake", "intake", "intake"),
            exhaust_ratio=1.0,
            pressure_loop=True,
            pressure_target_pa=5.0,
            pressure_loop_gain=0.01,
        )
        ctrl.tick_logic(55.0, [0, 0, 0, 0], 1.0, pressure_delta_pa=0.0)
        self.assertAlmostEqual(ctrl.duties[0], 0.95)
        self.assertAlmostEqual(ctrl.duties[1], 1.0)
        ctrl.apply_control(1, "manual", 0.2)
        ctrl.tick_logic(55.0, [0, 0, 0, 0], 1.0, pressure_delta_pa=0.0)
        self.assertAlmostEqual(ctrl.duties[0], 0.2)

    def test_all_intake_ignores_ratio(self):
        ctrl = fan.FanController(
            hw=self.hw,
            overrides_path=":memory:",
            roles=("intake", "intake", "intake", "intake"),
            exhaust_ratio=0.5,
        )
        ctrl.tick_logic(55.0, [0, 0, 0, 0], 1.0)
        self.assertEqual(ctrl.duties, [1.0, 1.0, 1.0, 1.0])

    def test_set_auto_uses_role_duty(self):
        self.ctrl.die_c = 30.0
        self.ctrl.control_c = 30.0
        ok, _code, _msg = self.ctrl.set_auto(3)
        self.assertTrue(ok)
        self.assertAlmostEqual(self.ctrl.duties[2], fan.MIN_SPEED * 0.85)
        self.assertAlmostEqual(self.hw.duties[2], fan.MIN_SPEED * 0.85)


if __name__ == "__main__":
    unittest.main()
