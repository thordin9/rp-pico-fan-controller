import os
import sys
import types
import unittest

sys.modules.setdefault("machine", types.ModuleType("machine"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
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


if __name__ == "__main__":
    unittest.main()
