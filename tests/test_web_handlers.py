import unittest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import web
import fan


class TestPathHelpers(unittest.TestCase):
    def test_path_bucket(self):
        self.assertEqual(web.path_bucket("/"), "/")
        self.assertEqual(web.path_bucket("/index.html"), "/")
        self.assertEqual(web.path_bucket("/status.json"), "/status.json")
        self.assertEqual(web.path_bucket("/metrics"), "/metrics")
        self.assertEqual(web.path_bucket("/api/fans/1"), "/api/fans")
        self.assertEqual(web.path_bucket("/api/fans/1/auto"), "/api/fans")
        self.assertEqual(web.path_bucket("/nope"), "other")

    def test_parse_fan_path(self):
        self.assertEqual(web.parse_fan_path("/api/fans/3"), (3, "set"))
        self.assertEqual(web.parse_fan_path("/api/fans/3/auto"), (3, "auto"))
        self.assertEqual(web.parse_fan_path("/api/fans/99"), (99, "set"))
        self.assertEqual(web.parse_fan_path("/status.json"), (None, None))

    def test_parse_json_body(self):
        self.assertEqual(
            web.parse_json_body(b'{"mode":"manual","duty":0.5}'),
            {"mode": "manual", "duty": 0.5},
        )
        self.assertIsNone(web.parse_json_body(b"{"))


class TestHandleControl(unittest.TestCase):
    def setUp(self):
        class FakeHw:
            def __init__(self):
                self.duties = [0.0] * fan.FAN_COUNT

            def set_duty(self, i, f):
                self.duties[i] = f

            def set_all_duty(self, f):
                for i in range(fan.FAN_COUNT):
                    self.duties[i] = f

            def read_die_temp_c(self):
                return 30.0

            def take_pulse_counts(self):
                return [0] * fan.FAN_COUNT

        self.ctrl = fan.FanController(hw=FakeHw(), overrides_path=":memory:")
        self.srv = web.HttpServer(self.ctrl, metrics_module=__import__("metrics"))

    def test_dispatch_manual(self):
        code, body, ctype = self.srv.dispatch(
            "POST", "/api/fans/2", b'{"mode":"manual","duty":0.33}'
        )
        self.assertEqual(code, 200)
        self.assertEqual(self.ctrl.modes[1], "manual")
        self.assertIn(b"duty", body)

    def test_dispatch_auto_path(self):
        self.ctrl.apply_control(2, "manual", 0.5)
        code, body, ctype = self.srv.dispatch("POST", "/api/fans/2/auto", b"")
        self.assertEqual(code, 200)
        self.assertEqual(self.ctrl.modes[1], "auto")


if __name__ == "__main__":
    unittest.main()
