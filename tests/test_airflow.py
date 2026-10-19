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
        # Raw 0.18 * 0.85 = 0.153 is inside the stall band, so idle exhaust
        # is lifted to the same 18% floor as intake.
        self.assertAlmostEqual(intake, fan.MIN_SPEED)
        self.assertAlmostEqual(exhaust, fan.MIN_SPEED)
        self.assertGreaterEqual(exhaust - fan.STALL_DUTY_MIN, 0.03)
        biased = fan.auto_duty_for_role(0.50, "exhaust", 0.85, 0.0)
        self.assertAlmostEqual(biased, 0.425)
        self.assertLess(biased, 0.50)
        self.assertGreater(biased, fan.STALL_DUTY_MIN)

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
        self.assertTrue(self.ctrl.pressure_loop)
        self.assertAlmostEqual(self.ctrl.pressure_target_pa, 5.0)
        self.assertAlmostEqual(self.ctrl.pressure_loop_gain, 0.0005)
        self.assertAlmostEqual(self.ctrl.pressure_trim_max, 0.05)
        self.assertFalse(self.ctrl.pressure_loop_active)
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
        self.assertAlmostEqual(self.ctrl.duties[2], fan.MIN_SPEED)
        self.assertFalse(self.ctrl.pressure_loop_active)

    def test_manual_overrides_role_and_stall_follows_commanded_duty(self):
        self.ctrl.apply_control(3, "manual", 0.4)
        self.ctrl.tick_logic(
            55.0, [0, 0, 0, 0], 1.0, internal_c=55.0, internal_ok=True
        )
        self.assertAlmostEqual(self.ctrl.duties[2], 0.4)
        self.assertTrue(self.ctrl.stalls[2])
        self.assertAlmostEqual(self.ctrl.duties[0], 1.0)
        # Idle exhaust is held at 18%, so a stopped exhaust fan is a real stall.
        self.ctrl.tick_logic(30.0, [0, 0, 0, 0], 1.0)
        self.assertAlmostEqual(self.ctrl.duties[3], fan.MIN_SPEED)
        self.assertTrue(self.ctrl.stalls[3])
        quiet = fan.FanController(
            hw=self.hw,
            overrides_path=":memory:",
            exhaust_ratio=0.5,
            roles=("intake", "intake", "exhaust", "exhaust"),
        )
        quiet.tick_logic(30.0, [0, 0, 0, 0], 1.0)
        self.assertAlmostEqual(quiet.duties[2], fan.MIN_SPEED)
        self.assertTrue(quiet.stalls[2])
        self.assertTrue(quiet.stalls[0])
        stopped = fan.FanController(
            hw=self.hw,
            overrides_path=":memory:",
            exhaust_ratio=0.0,
        )
        stopped.tick_logic(30.0, [0, 0, 0, 0], 1.0)
        self.assertEqual(stopped.duties[2], 0.0)
        self.assertFalse(stopped.stalls[2])

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
        self.assertAlmostEqual(self.ctrl.duties[2], fan.MIN_SPEED)
        self.assertAlmostEqual(self.hw.duties[2], fan.MIN_SPEED)

    def test_pressure_loop_clamps_and_falls_back(self):
        ctrl = fan.FanController(hw=self.hw, overrides_path=":memory:")
        # 40 °C → intake 0.385, static exhaust 0.385 * 0.85 = 0.32725.
        static = fan.auto_duty_for_role(fan.temp_to_duty(40.0), "exhaust", 0.85, 0.0)
        self.assertAlmostEqual(static, 0.385 * 0.85)
        ctrl.tick_logic(40.0, [8, 8, 8, 8], 1.0, pressure_delta_pa=None)
        self.assertFalse(ctrl.pressure_loop_active)
        self.assertAlmostEqual(ctrl.duties[0], fan.temp_to_duty(40.0))
        self.assertAlmostEqual(ctrl.duties[2], static)

        # A large error only moves exhaust by the trim cap, then holds.
        ctrl.tick_logic(40.0, [8, 8, 8, 8], 1.0, pressure_delta_pa=5000.0)
        self.assertTrue(ctrl.pressure_loop_active)
        self.assertAlmostEqual(ctrl.duties[2], static + fan.DEFAULT_PRESSURE_TRIM_MAX)
        self.assertLess(ctrl.duties[2], 1.0)
        ctrl.tick_logic(40.0, [8, 8, 8, 8], 1.0, pressure_delta_pa=-5000.0)
        self.assertAlmostEqual(ctrl.duties[2], static - fan.DEFAULT_PRESSURE_TRIM_MAX)
        # At the 18% floor the same cap would land in the stall band, so the
        # lift puts exhaust back on 18%. The loop cannot false-stall idle fans.
        ctrl.tick_logic(30.0, [8, 8, 8, 8], 1.0, pressure_delta_pa=-5000.0)
        self.assertAlmostEqual(ctrl.duties[2], fan.MIN_SPEED)
        self.assertGreaterEqual(ctrl.duties[2], ctrl.stall_duty_min)
        # Dropping the sensors returns to the static ratio on the next sample.
        ctrl.tick_logic(40.0, [8, 8, 8, 8], 1.0, pressure_delta_pa=None)
        self.assertFalse(ctrl.pressure_loop_active)
        self.assertAlmostEqual(ctrl.duties[2], static)
        self.assertFalse(ctrl.status_dict()["pressure_loop_active"])
        self.assertTrue(ctrl.status_dict()["pressure_loop_enabled"])

    def test_pressure_loop_converges_without_winding_up(self):
        ctrl = fan.FanController(hw=self.hw, overrides_path=":memory:")
        # Linear plant: Pa = 100 * (intake - exhaust). Settles inside one
        # trim step of the 5 Pa target because each sample recomputes from
        # the static duty instead of integrating the error.
        previous = None
        for _ in range(12):
            intake = ctrl.duties[0]
            exhaust = ctrl.duties[2]
            if previous is None:
                delta = 40.0
            else:
                delta = 100.0 * (intake - exhaust)
            ctrl.tick_logic(40.0, [8, 8, 8, 8], 1.0, pressure_delta_pa=delta)
            previous = ctrl.duties[2]
        intake = ctrl.duties[0]
        exhaust = ctrl.duties[2]
        delta = 100.0 * (intake - exhaust)
        static = 0.385 * 0.85
        self.assertAlmostEqual(intake, 0.385)
        self.assertGreaterEqual(exhaust, static - 0.05 - 1e-9)
        self.assertLessEqual(exhaust, static + 0.05 + 1e-9)
        self.assertAlmostEqual(delta, 5.0, delta=1.0)
        # One more sample at the same plant does not walk further away.
        again = exhaust
        ctrl.tick_logic(40.0, [8, 8, 8, 8], 1.0, pressure_delta_pa=delta)
        self.assertAlmostEqual(ctrl.duties[2], again, delta=0.002)


if __name__ == "__main__":
    unittest.main()
