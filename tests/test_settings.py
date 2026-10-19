import os
import sys
import types
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import config
import settings


def _ns(**values):
    module = types.SimpleNamespace()
    for key, value in values.items():
        setattr(module, key, value)
    return module


class TestSettings(unittest.TestCase):
    def test_shipped_config_is_all_off_and_valid(self):
        loaded, errors = settings.load_settings(config)
        self.assertEqual(errors, [])
        self.assertFalse(loaded["internal_enabled"])
        self.assertFalse(loaded["external_enabled"])
        self.assertFalse(loaded["oled_enabled"])
        self.assertTrue(loaded["pressure_loop_enabled"])
        self.assertAlmostEqual(loaded["pressure_loop_gain"], 0.0005)
        self.assertAlmostEqual(loaded["pressure_trim_max"], 0.05)
        self.assertEqual(loaded["internal_addr"], 0x76)
        self.assertEqual(loaded["internal_i2c_id"], 0)
        self.assertEqual(loaded["internal_sda"], 4)
        self.assertEqual(loaded["internal_scl"], 5)
        self.assertEqual(loaded["external_addr"], 0x76)
        self.assertEqual(loaded["external_i2c_id"], 1)
        self.assertEqual(loaded["external_sda"], 6)
        self.assertEqual(loaded["external_scl"], 7)
        self.assertEqual(loaded["oled_addr"], 0x3C)
        self.assertEqual(loaded["oled_i2c_id"], 0)
        self.assertEqual(
            loaded["fan_roles"], ("intake", "intake", "exhaust", "exhaust")
        )
        self.assertAlmostEqual(loaded["exhaust_ratio"], 0.85)
        self.assertAlmostEqual(loaded["exhaust_offset"], 0.0)

    def test_enabling_all_three_uses_two_buses_at_0x76(self):
        loaded, errors = settings.load_settings(
            _ns(
                INTERNAL_BMP280_ENABLED=True,
                EXTERNAL_BMP280_ENABLED=True,
                OLED_ENABLED=True,
            )
        )
        self.assertEqual(errors, [])
        self.assertTrue(loaded["internal_enabled"])
        self.assertTrue(loaded["external_enabled"])
        self.assertTrue(loaded["oled_enabled"])
        self.assertEqual(loaded["internal_addr"], 0x76)
        self.assertEqual(loaded["external_addr"], 0x76)
        self.assertEqual(loaded["internal_i2c_id"], 0)
        self.assertEqual(loaded["external_i2c_id"], 1)
        self.assertEqual((loaded["oled_sda"], loaded["oled_scl"]), (4, 5))
        self.assertEqual((loaded["external_sda"], loaded["external_scl"]), (6, 7))

    def test_shared_bus_0x77_is_still_valid(self):
        loaded, errors = settings.load_settings(
            _ns(
                INTERNAL_BMP280_ENABLED=True,
                EXTERNAL_BMP280_ENABLED=True,
                EXTERNAL_BMP280_ADDR=0x77,
                EXTERNAL_BMP280_I2C_ID=0,
                EXTERNAL_BMP280_SDA=4,
                EXTERNAL_BMP280_SCL=5,
                OLED_ENABLED=True,
            )
        )
        self.assertEqual(errors, [])
        self.assertTrue(loaded["external_enabled"])
        self.assertEqual(loaded["external_addr"], 0x77)
        self.assertEqual(loaded["external_i2c_id"], 0)

    def test_missing_module_uses_defaults(self):
        loaded, errors = settings.load_settings(None)
        self.assertEqual(errors, [])
        self.assertFalse(loaded["oled_enabled"])

    def test_fan_pin_and_address_conflict_disable_the_offender(self):
        loaded, errors = settings.load_settings(
            _ns(
                INTERNAL_BMP280_ENABLED=True,
                EXTERNAL_BMP280_ENABLED=True,
                EXTERNAL_BMP280_ADDR=0x76,
                EXTERNAL_BMP280_I2C_ID=0,
                EXTERNAL_BMP280_SDA=4,
                EXTERNAL_BMP280_SCL=5,
                OLED_ENABLED=True,
                OLED_SDA=15,
                OLED_SCL=8,
            )
        )
        self.assertTrue(loaded["internal_enabled"])
        self.assertFalse(loaded["external_enabled"])
        self.assertFalse(loaded["oled_enabled"])
        text = " ".join(errors)
        self.assertIn("EXTERNAL_BMP280", text)
        self.assertIn("0x76", text)
        self.assertIn("OLED", text)
        self.assertIn("GP15", text)

    def test_second_bus_same_address_is_allowed(self):
        loaded, errors = settings.load_settings(
            _ns(
                INTERNAL_BMP280_ENABLED=True,
                EXTERNAL_BMP280_ENABLED=True,
                EXTERNAL_BMP280_ADDR=0x76,
                EXTERNAL_BMP280_I2C_ID=1,
                EXTERNAL_BMP280_SDA=6,
                EXTERNAL_BMP280_SCL=7,
            )
        )
        self.assertEqual(errors, [])
        self.assertTrue(loaded["internal_enabled"])
        self.assertTrue(loaded["external_enabled"])
        self.assertEqual(loaded["external_i2c_id"], 1)

    def test_shared_bus_must_use_the_same_pins(self):
        loaded, errors = settings.load_settings(
            _ns(
                INTERNAL_BMP280_ENABLED=True,
                OLED_ENABLED=True,
                OLED_SDA=8,
                OLED_SCL=9,
            )
        )
        self.assertTrue(loaded["internal_enabled"])
        self.assertFalse(loaded["oled_enabled"])
        self.assertTrue(any("do not match" in err for err in errors))

    def test_roles_ratio_and_bool_rejected(self):
        loaded, errors = settings.load_settings(
            _ns(
                FAN_ROLES=("intake", "side", "exhaust", "exhaust"),
                AIRFLOW_EXHAUST_RATIO=True,
                PRESSURE_LOOP_ENABLED="yes",
                INTERNAL_BMP280_SDA=4,
                INTERNAL_BMP280_SCL=4,
                INTERNAL_BMP280_ENABLED=True,
            )
        )
        self.assertEqual(
            loaded["fan_roles"], ("intake", "intake", "exhaust", "exhaust")
        )
        self.assertAlmostEqual(loaded["exhaust_ratio"], 0.85)
        self.assertTrue(loaded["pressure_loop_enabled"])
        self.assertFalse(loaded["internal_enabled"])
        text = " ".join(errors)
        self.assertIn("FAN_ROLES", text)
        self.assertIn("AIRFLOW_EXHAUST_RATIO", text)
        self.assertIn("PRESSURE_LOOP_ENABLED", text)
        self.assertIn("SDA and SCL", text)

    def test_reserved_pico_w_pin(self):
        _loaded, errors = settings.load_settings(
            _ns(OLED_ENABLED=True, OLED_SDA=25, OLED_SCL=8)
        )
        self.assertTrue(any("reserved" in err for err in errors))


if __name__ == "__main__":
    unittest.main()
