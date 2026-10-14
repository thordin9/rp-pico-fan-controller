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
        self.assertIn("pico_fan_die_temp_celsius 31.5", text)
        self.assertIn('pico_fan_duty_ratio{fan="2",mode="manual"} 0.45', text)
        self.assertIn('pico_fan_override{fan="2"} 1', text)
        self.assertIn('pico_fan_override{fan="1"} 0', text)
        self.assertIn("pico_fan_wifi_up 1", text)
        self.assertIn('pico_fan_http_requests_total{path="/",code="200"} 3', text)
        self.assertIn("# TYPE pico_fan_rpm gauge", text)


if __name__ == "__main__":
    unittest.main()
