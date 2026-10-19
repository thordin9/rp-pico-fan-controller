import os
import sys
import types
import unittest

sys.modules.setdefault("machine", types.ModuleType("machine"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import fan
import main


class TestWatchdogClamp(unittest.TestCase):
    def test_timeout_stays_inside_rp2040_limits(self):
        self.assertEqual(main.clamp_wdt_timeout_ms(8000), 8000)
        self.assertEqual(main.clamp_wdt_timeout_ms(8388), 8388)
        self.assertEqual(main.clamp_wdt_timeout_ms(9000), main.WDT_HW_MAX_MS)
        self.assertEqual(main.clamp_wdt_timeout_ms(0), 1)
        self.assertEqual(main.clamp_wdt_timeout_ms(-5), 1)
        self.assertIsNone(main.clamp_wdt_timeout_ms("nope"))
        self.assertLessEqual(main.WDT_HW_MAX_MS, 8388)
        self.assertGreaterEqual(main.clamp_wdt_timeout_ms(8000), 1000)


class _Hw:
    def __init__(self):
        self.duties = [0.0] * fan.FAN_COUNT
        self.die = 40.0

    def set_duty(self, index, fraction):
        self.duties[index] = fraction

    def set_all_duty(self, fraction):
        for i in range(fan.FAN_COUNT):
            self.duties[i] = fraction

    def read_die_temp_c(self):
        return self.die

    def take_pulse_counts(self):
        return [10] * fan.FAN_COUNT


class _Boom:
    def read(self):
        raise OSError("bmp280 hung")

    def update(self, _status, _now):
        raise OSError("oled hung")


class TestSamplePeripherals(unittest.TestCase):
    def test_sensor_and_display_failures_still_feed_and_move_fans(self):
        ctrl = fan.FanController(hw=_Hw(), overrides_path=":memory:")
        feeds = []
        main.sample_peripherals(ctrl, _Boom(), _Boom(), 1.0, 1000, feed=lambda: feeds.append(1))
        self.assertEqual(feeds, [1, 1])
        self.assertEqual(ctrl.temp_source, "die")
        self.assertAlmostEqual(ctrl.control_c, 40.0)
        self.assertGreater(ctrl.duties[0], fan.MIN_SPEED)
        self.assertNotEqual(ctrl.duties[0], 0.0)

    def test_internal_reading_is_applied_and_display_is_noted(self):
        ctrl = fan.FanController(hw=_Hw(), overrides_path=":memory:")

        class Sensors:
            def read(self):
                return {
                    "sensors": {
                        "internal": {
                            "enabled": True,
                            "ok": True,
                            "chip_id": 0x58,
                            "temp_c": 55.0,
                            "pressure_pa": 101000.0,
                            "error": "",
                        },
                        "external": {
                            "enabled": True,
                            "ok": True,
                            "chip_id": 0x58,
                            "temp_c": 20.0,
                            "pressure_pa": 100000.0,
                            "error": "",
                        },
                    },
                    "pressure_delta_pa": 1000.0,
                }

        class Panel:
            def __init__(self):
                self.calls = 0

            def update(self, status, now_ms):
                self.calls += 1
                self.seen_source = status["temp_source"]
                self.now = now_ms
                return {"enabled": True, "ok": True, "error": ""}

        panel = Panel()
        feeds = []
        main.sample_peripherals(
            ctrl, Sensors(), panel, 1.0, 2500, feed=lambda: feeds.append(1)
        )
        self.assertEqual(feeds, [1, 1])
        self.assertEqual(ctrl.temp_source, "internal")
        self.assertAlmostEqual(ctrl.duties[0], 1.0)
        # 1000 Pa above the 5 Pa target hits the +5% trim cap, not 100% duty.
        self.assertAlmostEqual(ctrl.duties[2], 0.90)
        self.assertTrue(ctrl.pressure_loop_active)
        self.assertEqual(ctrl.pressure_delta_pa, 1000.0)
        self.assertEqual(panel.calls, 1)
        self.assertEqual(panel.seen_source, "internal")
        self.assertTrue(ctrl.oled_state["ok"])


if __name__ == "__main__":
    unittest.main()
