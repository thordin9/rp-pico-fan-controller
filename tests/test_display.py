import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

import display
import ssd1306
from fake_i2c import FakeI2C


def _status(**overrides):
    base = {
        "die_c": 31.0,
        "control_c": 31.0,
        "temp_source": "die",
        "pressure_delta_pa": None,
        "wifi": "disabled",
        "ip": "",
        "sensors": {
            "internal": {
                "enabled": False,
                "ok": False,
                "chip_id": None,
                "temp_c": None,
                "pressure_pa": None,
                "error": "",
            },
            "external": {
                "enabled": False,
                "ok": False,
                "chip_id": None,
                "temp_c": None,
                "pressure_pa": None,
                "error": "",
            },
        },
        "fans": [
            {"id": 1, "mode": "auto", "duty": 0.18, "rpm": 820, "stall": False, "role": "intake"},
            {"id": 2, "mode": "manual", "duty": 0.40, "rpm": 1500, "stall": False, "role": "intake"},
            {"id": 3, "mode": "auto", "duty": 0.153, "rpm": 700, "stall": False, "role": "exhaust"},
            {"id": 4, "mode": "auto", "duty": 0.153, "rpm": 0, "stall": True, "role": "exhaust"},
        ],
    }
    base.update(overrides)
    return base


class TestPages(unittest.TestCase):
    def test_lines_fit_and_degrade_without_wifi_or_sensors(self):
        pages = display.build_pages(_status())
        self.assertEqual(len(pages), 4)
        for page in pages:
            self.assertEqual(len(page), 4)
            for line in page:
                self.assertLessEqual(len(line), 16)
        summary, fans, internal, external = pages
        self.assertEqual(summary[0], "wifi disabled")
        self.assertEqual(summary[1], "src die")
        self.assertEqual(summary[2], "T31.0C")
        self.assertEqual(summary[3], "dP --")
        self.assertEqual(internal[0], "Internal BMP280")
        self.assertEqual(internal[1], "disabled")
        self.assertEqual(external[0], "External BMP280")
        self.assertEqual(external[1], "disabled")
        self.assertIn("1I", fans[0])
        self.assertIn("820", fans[0])
        self.assertIn("18%", fans[0])
        self.assertTrue(fans[1].endswith("m"))
        self.assertIn("3E", fans[2])
        self.assertTrue(fans[3].endswith("!"))

    def test_ip_internal_source_and_readings(self):
        sensors = {
            "internal": {
                "enabled": True,
                "ok": True,
                "chip_id": 0x58,
                "temp_c": 28.4,
                "pressure_pa": 101325.2,
                "error": "",
            },
            "external": {
                "enabled": True,
                "ok": False,
                "chip_id": 0x60,
                "temp_c": None,
                "pressure_pa": None,
                "error": "chip id 0x60 is not BMP280 (0x58)",
            },
        }
        pages = display.build_pages(
            _status(
                wifi="connected",
                ip="192.168.100.250",
                control_c=28.4,
                temp_source="internal",
                pressure_delta_pa=12,
                sensors=sensors,
            )
        )
        summary, _fans, internal, external = pages
        self.assertEqual(summary[0], "192.168.100.250")
        self.assertEqual(summary[1], "src internal")
        self.assertEqual(summary[2], "T28.4C")
        self.assertEqual(summary[3], "dP +12Pa")
        self.assertEqual(internal[1], "28.4 C")
        self.assertEqual(internal[2], "101325 Pa")
        self.assertEqual(internal[3], "ok")
        self.assertEqual(external[1], "fail")
        self.assertLessEqual(len(external[2]), 16)
        self.assertIn("0x60", external[2])

    def test_no_wifi_string_when_idle(self):
        pages = display.build_pages(_status(wifi="", ip=""))
        self.assertEqual(pages[0][0], "no wifi")


class FakePanel:
    def __init__(self, fail=False):
        self.width = 128
        self.height = 32
        self.buffer = bytearray(512)
        self.shown = 0
        self.fail = fail

    def show(self):
        self.shown += 1
        if self.fail:
            raise OSError("nack")


class TestFramebuffer(unittest.TestCase):
    def test_glyph_and_blank_rows(self):
        buf = bytearray(128 * 4)
        display.blit_text(buf, 128, ("1", "", "", ""))
        # FONT "1" top row is 0x18: pixels x=3 and x=4.
        self.assertEqual(display.pixel_on(buf, 128, 3, 0), 1)
        self.assertEqual(display.pixel_on(buf, 128, 4, 0), 1)
        self.assertEqual(display.pixel_on(buf, 128, 0, 0), 0)
        self.assertEqual(display.pixel_on(buf, 128, 0, 8), 0)
        self.assertEqual(display.pixel_on(buf, 128, 10, 16), 0)
        # A second blit clears the previous glyph.
        display.blit_text(buf, 128, (" ", "", "", ""))
        self.assertEqual(display.pixel_on(buf, 128, 3, 0), 0)

    def test_pages_rotate_and_a_failed_show_does_not_raise(self):
        panel = FakePanel()
        ui = display.OledDisplay(panel, page_s=3)
        ui.update(_status(), 0)
        self.assertEqual(ui.page_index, 0)
        self.assertEqual(ui.last_lines[1], "src die")
        self.assertEqual(panel.shown, 1)
        ui.update(_status(), 2999)
        self.assertEqual(ui.page_index, 0)
        ui.update(_status(), 3000)
        self.assertEqual(ui.page_index, 1)
        self.assertIn("1I", ui.last_lines[0])
        ui.update(_status(), 6000)
        ui.update(_status(), 9000)
        ui.update(_status(), 12000)
        self.assertEqual(ui.page_index, 0)
        panel.fail = True
        status = ui.update(_status(), 12000)
        self.assertFalse(status["ok"])
        self.assertIn("update failed", status["error"])
        panel.fail = False
        status = ui.update(_status(), 12000)
        self.assertTrue(status["ok"])
        self.assertEqual(status["error"], "")

    def test_missing_panel_stays_quiet(self):
        ui = display.OledDisplay(None, enabled=True, error="init failed: nack")
        status = ui.update(_status(), 0)
        self.assertFalse(status["ok"])
        self.assertIn("init failed", status["error"])


class TestSsd1306(unittest.TestCase):
    def test_128x32_init_and_frame(self):
        i2c = FakeI2C()
        panel = ssd1306.SSD1306_I2C(128, 32, i2c, addr=0x3C)
        cmds = [cmd for addr, cmd in i2c.cmds if addr == 0x3C]
        # Multiplex ratio register then height-1, then COM pins for a 32-row panel.
        mux = cmds.index(ssd1306.SET_MUX_RATIO)
        self.assertEqual(cmds[mux + 1], 31)
        com = cmds.index(ssd1306.SET_COM_PIN_CFG)
        self.assertEqual(cmds[com + 1], 0x02)
        self.assertEqual(len(panel.buffer), 512)
        self.assertTrue(i2c.frames)
        self.assertEqual(len(i2c.frames[0][1]), 512)
        display.blit_text(panel.buffer, 128, ("1", "", "", ""))
        panel.show()
        self.assertEqual(i2c.frames[-1][1], bytes(panel.buffer))
        self.assertEqual(display.pixel_on(panel.buffer, 128, 3, 0), 1)

    def test_show_without_writevto(self):
        i2c = FakeI2C()
        i2c.writevto = None
        panel = ssd1306.SSD1306_I2C(128, 32, i2c, addr=0x3C)
        self.assertEqual(len(i2c.frames[0][1]), 512)
        self.assertEqual(panel.pages, 4)


if __name__ == "__main__":
    unittest.main()
