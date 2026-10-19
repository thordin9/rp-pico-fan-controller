import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import fan
import metrics
import web


def _fans():
    return [
        {"id": 1, "mode": "auto", "duty": 0.18, "rpm": 800.0, "stall": False, "role": "intake"},
        {"id": 2, "mode": "manual", "duty": 0.40, "rpm": 1200.0, "stall": False, "role": "intake"},
        {"id": 3, "mode": "auto", "duty": 0.153, "rpm": 700.0, "stall": False, "role": "exhaust"},
        {"id": 4, "mode": "auto", "duty": 0.153, "rpm": 0.0, "stall": True, "role": "exhaust"},
    ]


def _sensor(enabled, ok, temp=None, pressure=None, chip=None, error=""):
    return {
        "enabled": enabled,
        "ok": ok,
        "chip_id": chip,
        "temp_c": temp,
        "pressure_pa": pressure,
        "error": error,
    }


def _status(internal, external, delta, source="die", control=31.0, oled=None):
    return {
        "die_c": 31.5,
        "control_c": control,
        "temp_source": source,
        "pressure_delta_pa": delta,
        "uptime_s": 12,
        "wifi": "connected",
        "ip": "192.168.4.20",
        "ssid": "lab",
        "sensors": {"internal": internal, "external": external},
        "oled": oled or {"enabled": False, "ok": False, "error": ""},
        "fans": _fans(),
    }


class TestMetricsCombinations(unittest.TestCase):
    def test_both_absent(self):
        text = metrics.format_metrics(
            _status(
                _sensor(False, False),
                _sensor(False, False),
                None,
            ),
            {},
        )
        self.assertIn('pico_fan_bmp280_up{location="internal"} 0', text)
        self.assertIn('pico_fan_bmp280_up{location="external"} 0', text)
        self.assertNotIn("pico_fan_bmp280_temperature_celsius", text)
        self.assertNotIn("pico_fan_bmp280_pressure_pascals", text)
        self.assertNotIn("pico_fan_pressure_delta_pascals", text)
        self.assertNotIn("humidity", text)
        self.assertIn('pico_fan_temp_source_info{source="die"} 1', text)
        self.assertIn('pico_fan_temp_source_info{source="internal"} 0', text)
        self.assertIn("pico_fan_control_temp_celsius 31.000", text)
        self.assertIn('pico_fan_intake{fan="1"} 1', text)
        self.assertIn('pico_fan_intake{fan="3"} 0', text)
        self.assertIn("pico_fan_oled_up 0", text)
        self.assertIn("pico_fan_die_temp_celsius 31.500", text)

    def test_internal_only(self):
        text = metrics.format_metrics(
            _status(
                _sensor(True, True, 28.25, 101325.5, 0x58),
                _sensor(False, False),
                None,
                source="internal",
                control=28.25,
            ),
            {},
        )
        self.assertIn(
            'pico_fan_bmp280_temperature_celsius{location="internal"} 28.250', text
        )
        self.assertIn(
            'pico_fan_bmp280_pressure_pascals{location="internal"} 101325.500', text
        )
        self.assertNotIn('location="external"} 28', text)
        self.assertIn('pico_fan_bmp280_up{location="external"} 0', text)
        self.assertIn('pico_fan_temp_source_info{source="internal"} 1', text)
        self.assertNotIn("pressure_delta", text)

    def test_external_only_and_failed_internal(self):
        text = metrics.format_metrics(
            _status(
                _sensor(True, False, error="chip id 0x60 is not BMP280 (0x58)"),
                _sensor(True, True, 22.0, 100000.0, 0x58),
                None,
            ),
            {},
        )
        self.assertIn('pico_fan_bmp280_up{location="internal"} 0', text)
        self.assertIn('pico_fan_bmp280_up{location="external"} 1', text)
        self.assertIn(
            'pico_fan_bmp280_temperature_celsius{location="external"} 22.000', text
        )
        self.assertNotIn('location="internal"} 0.000', text)

    def test_both_present_exports_delta_and_oled(self):
        text = metrics.format_metrics(
            _status(
                _sensor(True, True, 28.0, 101330.0, 0x58),
                _sensor(True, True, 22.0, 101320.0, 0x58),
                10.0,
                source="internal",
                control=28.0,
                oled={"enabled": True, "ok": True, "error": ""},
            ),
            {},
        )
        self.assertIn("pico_fan_pressure_delta_pascals 10.000", text)
        self.assertIn("pico_fan_oled_up 1", text)
        self.assertNotIn("humidity", text)


class TestStatusPage(unittest.TestCase):
    def _server(self, ctrl):
        return web.HttpServer(ctrl, metrics)

    def test_json_and_page_label_internal_and_external(self):
        ctrl = fan.FanController(overrides_path=":memory:")
        ctrl.note_sensors(
            {
                "sensors": {
                    "internal": _sensor(True, True, 28.5, 101325.0, 0x58),
                    "external": _sensor(True, False, error="init failed"),
                },
                "pressure_delta_pa": None,
            }
        )
        ctrl.note_oled({"enabled": True, "ok": False, "error": "init failed: nack"})
        ctrl.tick_logic(30.0, [0, 0, 0, 0], 1.0, internal_c=28.5, internal_ok=True)
        srv = self._server(ctrl)
        code, body, ctype = srv.dispatch("GET", "/status.json", b"")
        self.assertEqual(code, 200)
        data = json.loads(body)
        self.assertEqual(data["temp_source"], "internal")
        self.assertAlmostEqual(data["control_c"], 28.5)
        self.assertTrue(data["sensors"]["internal"]["ok"])
        self.assertEqual(data["sensors"]["internal"]["pressure_pa"], 101325.0)
        self.assertEqual(data["sensors"]["external"]["error"], "init failed")
        self.assertIsNone(data["pressure_delta_pa"])
        self.assertEqual(data["fans"][0]["role"], "intake")
        self.assertEqual(data["fans"][3]["role"], "exhaust")
        self.assertFalse(data["oled"]["ok"])
        self.assertNotIn("humidity", data)
        self.assertNotIn(b"humidity", body)
        code, page, _ctype = srv.dispatch("GET", "/", b"")
        self.assertEqual(code, 200)
        self.assertIn(b"Internal BMP280", page)
        self.assertIn(b"External BMP280", page)
        self.assertIn(b"Temperature source", page)
        self.assertIn(b"Pressure delta", page)
        self.assertIn(b"intake", page)
        self.assertIn(b"init failed", page)

    def test_all_disabled_status(self):
        ctrl = fan.FanController(overrides_path=":memory:")
        raw = web.HttpServer(ctrl, metrics).format_status_json()
        data = json.loads(raw)
        self.assertFalse(data["sensors"]["internal"]["enabled"])
        self.assertFalse(data["sensors"]["external"]["enabled"])
        self.assertEqual(data["temp_source"], "die")
        self.assertIsNone(data["pressure_delta_pa"])
        self.assertFalse(data["oled"]["enabled"])


if __name__ == "__main__":
    unittest.main()
