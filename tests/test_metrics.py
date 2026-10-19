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
        self.assertIn("pico_fan_die_temp_celsius 31.500", text)
        self.assertIn('pico_fan_duty_ratio{fan="2"} 0.4500', text)
        self.assertNotIn('pico_fan_duty_ratio{fan="2",mode=', text)
        self.assertIn('pico_fan_override{fan="2"} 1', text)
        self.assertIn('pico_fan_override{fan="1"} 0', text)
        self.assertIn("pico_fan_wifi_up 1", text)
        self.assertIn('pico_fan_stall{fan="1"} 0', text)
        self.assertIn('pico_fan_http_requests_total{path="/",code="200"} 3', text)
        self.assertIn("# TYPE pico_fan_rpm gauge", text)

    def test_wifi_down_and_stall(self):
        status = {
            "die_c": 40.0,
            "uptime_s": 1,
            "wifi": "timeout",
            "ip": "",
            "ssid": "x",
            "fans": [
                {"id": 1, "mode": "manual", "duty": 0.5, "rpm": 0.0, "stall": True},
                {"id": 2, "mode": "auto", "duty": 0.18, "rpm": 800.0, "stall": False},
                {"id": 3, "mode": "auto", "duty": 0.18, "rpm": 0.0, "stall": False},
                {"id": 4, "mode": "auto", "duty": 0.0, "rpm": 0.0},
            ],
        }
        text = metrics.format_metrics(status, {})
        self.assertIn("pico_fan_wifi_up 0", text)
        self.assertIn('pico_fan_stall{fan="1"} 1', text)
        self.assertIn('pico_fan_stall{fan="4"} 0', text)
        self.assertIn('pico_fan_override{fan="1"} 1', text)


if __name__ == "__main__":
    unittest.main()
