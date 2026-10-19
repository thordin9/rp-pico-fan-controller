import base64
import json
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
            "POST",
            "/api/fans/2",
            b'{"mode":"manual","duty":0.33}',
            {"Content-Type": "application/json"},
        )
        self.assertEqual(code, 200)
        self.assertEqual(self.ctrl.modes[1], "manual")
        self.assertIn(b"duty", body)
        self.assertEqual(ctype, "application/json")

    def test_dispatch_auto_path(self):
        self.ctrl.apply_control(2, "manual", 0.5)
        code, body, ctype = self.srv.dispatch(
            "POST",
            "/api/fans/2/auto",
            b"{}",
            {"Content-Type": "application/json"},
        )
        self.assertEqual(code, 200)
        self.assertEqual(self.ctrl.modes[1], "auto")


def _basic(user, password):
    token = base64.b64encode(
        "{}:{}".format(user, password).encode()
    ).decode()
    return "Basic " + token


class TestAuthAndValidation(unittest.TestCase):
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
        self.srv = web.HttpServer(
            self.ctrl,
            metrics_module=__import__("metrics"),
            auth=("pico", "secret"),
            metrics_require_auth=True,
        )

    def test_resolve_auth_empty_disables(self):
        self.assertIsNone(web.resolve_auth("", ""))
        self.assertIsNone(web.resolve_auth("pico", ""))
        self.assertIsNone(web.resolve_auth("", "secret"))
        self.assertIsNone(web.resolve_auth(None, "secret"))
        self.assertEqual(web.resolve_auth("pico", "secret"), ("pico", "secret"))

    def test_missing_or_wrong_credentials_are_401(self):
        for headers in (None, {}, {"Authorization": _basic("pico", "nope")}):
            code, body, _ctype = self.srv.dispatch("GET", "/", b"", headers)
            self.assertEqual(code, 401)
            self.assertIn(b"Unauthorized", body)
            raw = web._http_response(body, "text/plain", code)
            self.assertIn(b"401 Unauthorized", raw)
            self.assertIn(b'WWW-Authenticate: Basic realm="pico-fan"', raw)
        code, _body, _ctype = self.srv.dispatch("GET", "/metrics", b"", None)
        self.assertEqual(code, 401)
        code, _body, _ctype = self.srv.dispatch(
            "GET", "/status.json", b"", {"Authorization": _basic("pico", "secret")}
        )
        self.assertEqual(code, 200)

    def test_auth_failure_does_not_change_fans(self):
        code, body, _ctype = self.srv.dispatch(
            "POST",
            "/api/fans/1",
            b'{"mode":"manual","duty":0.4}',
            {"Content-Type": "application/json"},
        )
        self.assertEqual(code, 401)
        self.assertEqual(self.ctrl.modes[0], "auto")
        self.assertIsNone(self.ctrl._mem_overrides)

    def test_basic_header_without_padding_still_matches(self):
        token = base64.b64encode(b"pico:secret").decode().rstrip("=")
        self.assertNotIn("=", token)
        code, _body, _ctype = self.srv.dispatch(
            "GET",
            "/status.json",
            b"",
            {"Authorization": "Basic " + token},
        )
        self.assertEqual(code, 200)

    def test_password_may_contain_colon(self):
        srv = web.HttpServer(
            self.ctrl,
            metrics_module=__import__("metrics"),
            auth=("pico", "sec:ret"),
        )
        code, _body, _ctype = srv.dispatch(
            "GET",
            "/status.json",
            b"",
            {"Authorization": _basic("pico", "sec:ret")},
        )
        self.assertEqual(code, 200)

    def test_metrics_can_be_opened_by_flag(self):
        srv = web.HttpServer(
            self.ctrl,
            metrics_module=__import__("metrics"),
            auth=("pico", "secret"),
            metrics_require_auth=False,
        )
        code, body, _ctype = srv.dispatch("GET", "/metrics", b"", None)
        self.assertEqual(code, 200)
        self.assertIn(b"pico_fan_duty_ratio", body)
        code, _body, _ctype = srv.dispatch("GET", "/", b"", None)
        self.assertEqual(code, 401)
        code, body, _ctype = srv.dispatch("GET", "/no-such", b"", None)
        self.assertEqual(code, 401)
        self.assertNotIn(b"Not Found", body)

    def test_control_requires_json_content_type(self):
        self.ctrl.apply_control(2, "manual", 0.5)
        code, body, _ctype = self.srv.dispatch(
            "POST",
            "/api/fans/2/auto",
            b"{}",
            {"Authorization": _basic("pico", "secret")},
        )
        self.assertEqual(code, 400)
        self.assertIn(b"content-type", body)
        self.assertEqual(self.ctrl.modes[1], "manual")
        code, _body, _ctype = self.srv.dispatch(
            "POST",
            "/api/fans/2/auto",
            b"{}",
            {
                "Authorization": _basic("pico", "secret"),
                "Content-Type": "application/json; charset=utf-8",
            },
        )
        self.assertEqual(code, 200)
        self.assertEqual(self.ctrl.modes[1], "auto")

    def test_duty_out_of_range_is_400(self):
        code, body, _ctype = self.srv.dispatch(
            "POST",
            "/api/fans/1",
            b'{"mode":"manual","duty":1.2}',
            {
                "Authorization": _basic("pico", "secret"),
                "Content-Type": "application/json",
            },
        )
        self.assertEqual(code, 400)
        self.assertIn(b"duty out of range", body)
        self.assertEqual(self.ctrl.modes[0], "auto")
        self.assertIsNone(self.ctrl._mem_overrides)

    def test_status_json_escapes_strings(self):
        self.ctrl.ssid = 'net"work\\x'
        self.ctrl.wifi = 'a"b'
        self.ctrl.ip = "10.0.0.2"
        self.srv.auth = None
        raw = self.srv.format_status_json()
        self.assertNotIn("&quot;", raw)
        self.assertNotIn("&amp;", raw)
        data = json.loads(raw)
        self.assertEqual(data["ssid"], 'net"work\\x')
        self.assertEqual(data["wifi"], 'a"b')
        self.assertEqual(data["ip"], "10.0.0.2")

    def test_control_page_reports_fetch_errors(self):
        self.srv.auth = None
        self.ctrl.wifi = "<script>"
        code, body, ctype = self.srv.dispatch("GET", "/", b"")
        self.assertEqual(code, 200)
        self.assertIn(b"text/html", ctype.encode())
        self.assertIn(b"Control request failed", body)
        self.assertIn(b"Status refresh failed", body)
        self.assertIn(b"application/json", body)
        self.assertIn(b".catch(", body)
        self.assertIn(b"&lt;script&gt;", body)
        self.assertNotIn(b"<td class=\"num\" id=\"wifi\"><script>", body)


class _FakeConn:
    def __init__(self, chunks, partial_then_block=False):
        self.chunks = list(chunks)
        self.sent = b""
        self.closed = False
        self.blocking = True
        self.partial_then_block = partial_then_block
        self._sends = 0

    def setblocking(self, flag):
        self.blocking = flag

    def recv(self, _n):
        if not self.chunks:
            raise BlockingIOError()
        item = self.chunks.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def send(self, data):
        data = bytes(data)
        self._sends += 1
        if self.partial_then_block and self._sends == 1:
            data = data[:8]
            self.sent += data
            return len(data)
        if self.partial_then_block and self._sends == 2:
            raise BlockingIOError()
        self.sent += data
        return len(data)

    def close(self):
        self.closed = True


class _FakeListen:
    def __init__(self, conns):
        self.conns = list(conns)

    def accept(self):
        if not self.conns:
            raise BlockingIOError()
        return self.conns.pop(0), ("127.0.0.1", 9)


class TestNonBlockingPoll(unittest.TestCase):
    def setUp(self):
        class FakeHw:
            def __init__(self):
                self.duties = [0.0] * fan.FAN_COUNT

            def set_duty(self, i, f):
                self.duties[i] = f

        self.ctrl = fan.FanController(hw=FakeHw(), overrides_path=":memory:")
        self.srv = web.HttpServer(self.ctrl, metrics_module=__import__("metrics"))

    def test_partial_request_returns_and_completes_later(self):
        req = b"GET /status.json HTTP/1.0\r\nHost: pico\r\n\r\n"
        conn = _FakeConn([req[:12], BlockingIOError(), req[12:]])
        self.srv._sock = _FakeListen([conn])
        self.srv.poll(0)
        self.assertIs(self.srv._client, conn)
        self.assertFalse(conn.closed)
        self.assertEqual(conn.sent, b"")
        self.srv.poll(10)
        self.assertIsNone(self.srv._client)
        self.assertTrue(conn.closed)
        self.assertIn(b"200 OK", conn.sent)
        self.assertIn(b'"wifi"', conn.sent)

    def test_partial_send_resumes_on_the_next_poll(self):
        req = b"GET /status.json HTTP/1.0\r\n\r\n"
        conn = _FakeConn([req], partial_then_block=True)
        self.srv._sock = _FakeListen([conn])
        self.srv.poll(0)
        self.assertFalse(conn.closed)
        self.assertEqual(len(conn.sent), 8)
        self.srv.poll(10)
        self.assertTrue(conn.closed)
        self.assertIn(b"200 OK", conn.sent)
        self.assertTrue(conn.sent.endswith(b"}") or b'"fans"' in conn.sent)

    def test_accept_error_closes_the_listener(self):
        class Boom:
            def accept(self):
                raise OSError(9, "EBADF")

        self.srv._sock = Boom()
        self.srv.poll(0)
        self.assertFalse(self.srv.is_listening())

    def test_slow_client_is_dropped_at_budget(self):
        conn = _FakeConn([b"GET /status"])
        self.srv._sock = _FakeListen([conn])
        self.srv.poll(0)
        self.assertFalse(conn.closed)
        self.srv.poll(web.CLIENT_BUDGET_MS)
        self.assertTrue(conn.closed)
        self.assertIsNone(self.srv._client)
        self.assertEqual(conn.sent, b"")

    def test_request_progress_waits_for_body(self):
        head = b'POST /api/fans/1 HTTP/1.0\r\nContent-Length: 5\r\n\r\n'
        status, _parsed = web.request_progress(head + b"abc")
        self.assertEqual(status, "need-data")
        status, parsed = web.request_progress(head + b"abcdeEXTRA")
        self.assertEqual(status, "ready")
        self.assertEqual(parsed[3], b"abcde")
        huge = b"GET / HTTP/1.0\r\nContent-Length: 99999\r\n\r\n"
        self.assertEqual(web.request_progress(huge)[0], "oversize")


if __name__ == "__main__":
    unittest.main()
