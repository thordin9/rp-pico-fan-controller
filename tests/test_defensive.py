"""Defensive paths: config, HTTP, overrides, tach cap, and numeric guards."""

import os
import sys
import tempfile
import types
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import fan
import settings
import web
from tests.fake_i2c import FakeI2C, plant_bmp280
import bmp280


def _ns(**values):
    module = types.SimpleNamespace()
    for key, value in values.items():
        setattr(module, key, value)
    return module


class TestConfigValidation(unittest.TestCase):
    def test_bad_http_port_and_fault_limit_fall_back(self):
        loaded, errors = settings.load_settings(
            _ns(HTTP_PORT="eighty", BMP280_TEMP_MAX_C=-5, WDT_TIMEOUT_MS=99999)
        )
        self.assertEqual(loaded["http_port"], 80)
        self.assertAlmostEqual(loaded["bmp280_temp_max_c"], 85.0)
        self.assertEqual(loaded["wdt_timeout_ms"], 8000)
        self.assertTrue(any("HTTP_PORT" in item for item in errors))
        self.assertTrue(any("BMP280_TEMP_MAX_C" in item for item in errors))
        self.assertTrue(any("WDT_TIMEOUT_MS" in item for item in errors))

    def test_non_string_password_does_not_leak_into_settings(self):
        loaded, errors = settings.load_settings(_ns(HTTP_PASSWORD=1234))
        self.assertEqual(loaded["http_password"], "")
        self.assertTrue(any("HTTP_PASSWORD" in item for item in errors))


class TestHttpGuards(unittest.TestCase):
    def test_huge_content_length_is_rejected_without_a_giant_int(self):
        line = b"POST /api/fans/1 HTTP/1.0\r\nContent-Length: " + (b"9" * 40) + b"\r\n\r\n"
        kind, parsed = web.request_progress(line)
        self.assertEqual(kind, "bad")
        self.assertIsNone(parsed)

    def test_long_path_is_a_bad_request(self):
        line = b"GET /" + (b"a" * 80) + b" HTTP/1.0\r\n\r\n"
        kind, _parsed = web.request_progress(line)
        self.assertEqual(kind, "bad")

    def test_fan_id_must_be_a_short_integer(self):
        self.assertEqual(web.parse_fan_path("/api/fans/" + "9" * 30), (None, None))

    def test_dispatch_failure_is_500(self):
        ctrl = fan.FanController(overrides_path=":memory:")

        class BoomMetrics:
            @staticmethod
            def format_metrics(_status, _counts):
                raise RuntimeError("metrics broke")

        code, body, _ctype = web.HttpServer(ctrl, BoomMetrics()).dispatch(
            "GET", "/metrics", b""
        )
        self.assertEqual(code, 500)
        self.assertEqual(body, b"internal error")


class TestOverrides(unittest.TestCase):
    def test_nan_and_bool_are_rejected(self):
        text = (
            '{"fans":[{"mode":"manual","duty":1e309},{"mode":"auto","duty":0},'
            '{"mode":"auto","duty":0},{"mode":"auto","duty":0}]}'
        )
        self.assertIsNone(fan.parse_overrides_json(text))
        text = (
            '{"fans":[{"mode":"manual","duty":true},{"mode":"auto","duty":0},'
            '{"mode":"auto","duty":0},{"mode":"auto","duty":0}]}'
        )
        self.assertIsNone(fan.parse_overrides_json(text))

    def test_corrupt_file_falls_back_to_backup(self):
        directory = tempfile.mkdtemp()
        path = os.path.join(directory, "overrides.json")
        ctrl = fan.FanController(overrides_path=path)
        ctrl.apply_control(1, "manual", 0.4)
        # The second save keeps the previous file as overrides.json.bak.
        self.assertTrue(ctrl.save_overrides())
        self.assertTrue(os.path.exists(path))
        self.assertTrue(os.path.exists(path + ".bak"))
        with open(path, "w") as handle:
            handle.write("{not json")
        ctrl.modes = ["auto"] * fan.FAN_COUNT
        ctrl.duties = [fan.MIN_SPEED] * fan.FAN_COUNT
        self.assertTrue(ctrl.load_overrides())
        self.assertEqual(ctrl.modes[0], "manual")
        self.assertAlmostEqual(ctrl.duties[0], 0.4)

    def test_atomic_write_replaces_the_temp_file(self):
        directory = tempfile.mkdtemp()
        path = os.path.join(directory, "overrides.json")
        self.assertTrue(fan.atomic_write_text(path, '{"fans":[]}'))
        self.assertFalse(os.path.exists(path + ".tmp"))
        with open(path, "r") as handle:
            self.assertEqual(handle.read(), '{"fans":[]}')


class TestNumericAndTachGuards(unittest.TestCase):
    def test_non_finite_duty_and_temperature_go_to_full_speed(self):
        self.assertEqual(fan.clamp_duty(float("nan")), 1.0)
        self.assertEqual(fan.clamp_duty(float("inf")), 1.0)
        self.assertEqual(fan.temp_to_duty(float("nan")), 1.0)
        temp, source = fan.select_control_temp(30.0, float("nan"), True)
        self.assertEqual(source, "die")
        self.assertAlmostEqual(temp, 30.0)
        self.assertEqual(fan.pressure_trim(float("nan"), 5.0, 0.0005, 0.05), 0.0)

    def test_negative_led_elapsed_is_the_on_half(self):
        self.assertTrue(fan.led_is_on(0.1, -5))
        self.assertTrue(fan.led_is_on(0.1, 0))

    def test_tach_count_stops_at_the_cap(self):
        counts = [0]
        last = [0]
        seen = bytearray(1)
        for n in range(fan.TACH_COUNT_CAP + 25):
            fan.note_tach_pulse(counts, last, seen, 0, n * 2000, 1000)
        self.assertEqual(counts[0], fan.TACH_COUNT_CAP)
        clock = {"us": last[0] + 5000}
        fan.time.ticks_us = lambda: clock["us"]
        fan.time.ticks_diff = fan.ticks_diff
        try:
            handler = fan._make_tach_handler(counts, last, seen, 0, 1000)
            handler(None)
        finally:
            del fan.time.ticks_us
            del fan.time.ticks_diff
        self.assertEqual(counts[0], fan.TACH_COUNT_CAP)

    def test_failsafe_records_full_duty_when_pwm_raises(self):
        ctrl = fan.FanController(hw=_Hw(), overrides_path=":memory:")
        ctrl.duties = [0.2, 0.2, 0.2, 0.2]
        ctrl.failsafe()
        self.assertEqual(ctrl.duties, [1.0, 1.0, 1.0, 1.0])

    def test_not_ready_adc_is_not_a_temperature(self):
        i2c = FakeI2C()
        plant_bmp280(i2c, 0x76, adc_t=0x80000, adc_p=0x80000)
        device = bmp280.Bmp280(i2c, 0x76, "internal")
        self.assertTrue(device.init())
        status = device.read()
        self.assertFalse(status["ok"])
        self.assertEqual(status["error"], "not ready")
        self.assertIsNone(status["temp_c"])


class _Hw:
    def failsafe(self):
        raise RuntimeError("pwm dead")


if __name__ == "__main__":
    unittest.main()
