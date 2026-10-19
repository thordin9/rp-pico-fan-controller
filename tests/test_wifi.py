import unittest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import wifi
import fan
import metrics


class FakeWlan:
    def __init__(self):
        self.connected = False
        self.ip = "192.168.4.20"
        self.connects = 0
        self.disconnects = 0
        self.fail = False
        self.last = None

    def isconnected(self):
        return self.connected

    def connect(self, ssid, password):
        self.connects += 1
        self.last = (ssid, password)
        if self.fail:
            raise OSError("connect failed")

    def disconnect(self):
        self.disconnects += 1

    def ifconfig(self):
        return (self.ip, "255.255.255.0", "192.168.4.1", "8.8.8.8")


class TestWifiMonitor(unittest.TestCase):
    def setUp(self):
        self.ctrl = fan.FanController(overrides_path=":memory:")
        self.wlan = FakeWlan()
        self.mon = wifi.WifiMonitor(
            self.ctrl,
            ssid="lab",
            password="pw",
            timeout_s=20,
            retry_s=10,
            grace_s=1,
        )
        self.mon.attach(self.wlan)

    def test_already_associated_after_connect_is_connected(self):
        def connect(ssid, password):
            self.wlan.connects += 1
            self.wlan.connected = True

        self.wlan.connect = connect
        self.mon.start_attempt(0)
        self.assertEqual(self.ctrl.wifi, "connected")
        self.assertEqual(self.ctrl.ip, "192.168.4.20")
        self.assertEqual(self.wlan.connects, 1)

    def test_connect_is_nonblocking_and_reports_connecting(self):
        state = self.mon.start_attempt(1000)
        self.assertEqual(state, "connecting")
        self.assertEqual(self.ctrl.wifi, "connecting")
        self.assertEqual(self.ctrl.ip, "")
        self.assertEqual(self.wlan.connects, 1)
        self.assertEqual(self.wlan.last, ("lab", "pw"))
        # Further polls while the attempt is in flight must not hammer connect().
        self.mon.poll(1500)
        self.mon.poll(5000)
        self.assertEqual(self.wlan.connects, 1)
        self.assertEqual(self.ctrl.wifi, "connecting")

    def test_association_sets_connected_and_metric(self):
        self.mon.start_attempt(0)
        self.wlan.connected = True
        self.mon.poll(100)
        self.assertEqual(self.ctrl.wifi, "connected")
        self.assertEqual(self.ctrl.ip, "192.168.4.20")
        self.assertEqual(self.ctrl.ssid, "lab")
        text = metrics.format_metrics(self.ctrl.status_dict(), {})
        self.assertIn("pico_fan_wifi_up 1", text)

    def test_dropout_clears_connected_and_reconnects_after_grace(self):
        self.wlan.connected = True
        self.mon.start_attempt(0)
        self.assertEqual(self.ctrl.wifi, "connected")
        connects = self.wlan.connects
        self.wlan.connected = False
        self.mon.poll(5000)
        self.assertEqual(self.ctrl.wifi, "offline")
        self.assertEqual(self.ctrl.ip, "")
        self.assertEqual(self.wlan.connects, connects)
        text = metrics.format_metrics(self.ctrl.status_dict(), {})
        self.assertIn("pico_fan_wifi_up 0", text)
        # Link returns during the grace window: no reconnect storm.
        self.wlan.connected = True
        self.mon.poll(5500)
        self.assertEqual(self.ctrl.wifi, "connected")
        self.assertEqual(self.wlan.connects, connects)
        self.wlan.connected = False
        self.mon.poll(6000)
        self.assertEqual(self.ctrl.wifi, "offline")
        self.mon.poll(6000 + 1000)
        self.assertEqual(self.ctrl.wifi, "connecting")
        self.assertEqual(self.wlan.connects, connects + 1)

    def test_timeout_then_retry(self):
        self.mon.start_attempt(0)
        self.mon.poll(19999)
        self.assertEqual(self.ctrl.wifi, "connecting")
        self.assertEqual(self.wlan.connects, 1)
        self.mon.poll(20000)
        self.assertEqual(self.ctrl.wifi, "timeout")
        self.assertEqual(self.ctrl.ip, "")
        self.mon.poll(20000)
        self.assertEqual(self.wlan.connects, 1)
        self.mon.poll(20000 + 10000)
        self.assertEqual(self.ctrl.wifi, "connecting")
        self.assertEqual(self.wlan.connects, 2)
        text = metrics.format_metrics(self.ctrl.status_dict(), {})
        self.assertIn("pico_fan_wifi_up 0", text)

    def test_timeout_across_ticks_wrap(self):
        start = (1 << 30) - 100
        self.mon.start_attempt(start)
        self.mon.poll(start + 50)  # still inside the window, no wrap yet
        # 1100 ms later, wrapped past 2**30.
        self.mon.poll(1000)
        self.assertEqual(self.ctrl.wifi, "connecting")
        self.mon.timeout_ms = 1000
        self.mon.poll(1000)
        self.assertEqual(self.ctrl.wifi, "timeout")

    def test_disabled_does_not_touch_the_radio(self):
        self.mon.mark_disabled("disabled")
        self.assertEqual(self.mon.poll(0), "disabled")
        self.assertEqual(self.ctrl.wifi, "disabled")
        self.assertEqual(self.wlan.connects, 0)

    def test_connect_error_schedules_retry(self):
        self.wlan.fail = True
        self.mon.start_attempt(0)
        self.assertEqual(self.ctrl.wifi, "timeout")
        self.wlan.fail = False
        self.mon.poll(9999)
        self.assertEqual(self.wlan.connects, 1)
        self.mon.poll(10000)
        self.assertEqual(self.ctrl.wifi, "connecting")
        self.assertEqual(self.wlan.connects, 2)


if __name__ == "__main__":
    unittest.main()
