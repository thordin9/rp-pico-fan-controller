import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

import bmp280
import sensors
from fake_i2c import REF_CALIB, FakeI2C, pack_calib, pack_sample, plant_bmp280

# Bosch BST-BMP280-DS001 section 3.11.3 integer example.
ADC_T = 519888
ADC_P = 415148
ADC_P_HIGH = 215148


class TestCompensation(unittest.TestCase):
    def test_datasheet_reference_pair(self):
        temp_c, pressure_pa = bmp280.compensate(ADC_T, ADC_P, REF_CALIB)
        # 2508 * 0.01 °C, and Q24.8 value 25767233 / 256 Pa.
        self.assertEqual(temp_c, 2508 / 100.0)
        self.assertEqual(pressure_pa, 25767233 / 256.0)
        self.assertEqual(int(pressure_pa), 100653)

    def test_datasheet_high_pressure_and_zero_p1(self):
        _temp, pressure_pa = bmp280.compensate(ADC_T, ADC_P_HIGH, REF_CALIB)
        self.assertEqual(pressure_pa, 34657840 / 256.0)
        self.assertEqual(int(pressure_pa), 135382)
        zero = list(REF_CALIB)
        zero[3] = 0
        temp_c, pressure_pa = bmp280.compensate(ADC_T, ADC_P, tuple(zero))
        self.assertEqual(temp_c, 25.08)
        self.assertEqual(pressure_pa, 0.0)

    def test_calibration_and_sample_roundtrip(self):
        parsed = bmp280.parse_calibration(pack_calib(REF_CALIB))
        self.assertEqual(parsed, REF_CALIB)
        adc_p, adc_t = bmp280.unpack_sample(pack_sample(ADC_P, ADC_T))
        self.assertEqual(adc_t, ADC_T)
        self.assertEqual(adc_p, ADC_P)
        self.assertRaises(ValueError, bmp280.parse_calibration, b"\x00" * 10)
        self.assertRaises(ValueError, bmp280.unpack_sample, b"\x00" * 3)


class TestBmp280Device(unittest.TestCase):
    def test_init_and_read_match_datasheet(self):
        i2c = FakeI2C()
        plant_bmp280(i2c, 0x76)
        dev = bmp280.Bmp280(i2c, 0x76, "internal")
        self.assertTrue(dev.init())
        # Config is written while still in sleep, then normal mode.
        self.assertEqual(i2c.mem[0x76][0xF5], bmp280.CONFIG_1HZ_FILTER4)
        self.assertEqual(i2c.mem[0x76][0xF4], bmp280.CTRL_MEAS_NORMAL)
        status = dev.read()
        self.assertTrue(status["ok"])
        self.assertEqual(status["chip_id"], 0x58)
        self.assertEqual(status["temp_c"], 25.08)
        self.assertEqual(status["pressure_pa"], 25767233 / 256.0)
        self.assertNotIn("humidity", status)

    def test_wrong_chip_id_is_a_clear_error_and_does_not_retry(self):
        i2c = FakeI2C()
        plant_bmp280(i2c, 0x76, chip=0x60)
        dev = bmp280.Bmp280(i2c, 0x76, "internal")
        self.assertFalse(dev.init())
        status = dev.status()
        self.assertFalse(status["ok"])
        self.assertEqual(status["chip_id"], 0x60)
        self.assertIn("0x60", status["error"])
        self.assertIn("0x58", status["error"])
        self.assertIsNone(status["temp_c"])
        reads = i2c.reads
        again = dev.read()
        self.assertFalse(again["ok"])
        self.assertEqual(i2c.reads, reads)

    def test_missing_device_is_logged_and_read_returns(self):
        i2c = FakeI2C()
        dev = bmp280.Bmp280(i2c, 0x76, "external")
        status = dev.read()
        self.assertFalse(status["ok"])
        self.assertIsNone(status["temp_c"])
        self.assertIn("init failed", status["error"])
        self.assertIn("scan=none", status["error"])

    def test_runtime_failure_then_recovery(self):
        i2c = FakeI2C()
        plant_bmp280(i2c, 0x77)
        dev = bmp280.Bmp280(i2c, 0x77, "external")
        self.assertEqual(dev.read()["temp_c"], 25.08)
        i2c.fail.add(0x77)
        failed = dev.read()
        self.assertFalse(failed["ok"])
        self.assertIsNone(failed["temp_c"])
        self.assertIn("read failed", failed["error"])
        i2c.fail.discard(0x77)
        recovered = dev.read()
        self.assertTrue(recovered["ok"])
        self.assertEqual(recovered["temp_c"], 25.08)


class TestSensorHub(unittest.TestCase):
    def _settings(self, **overrides):
        import settings as settings_mod

        loaded = dict(settings_mod.DEFAULTS)
        loaded["fan_roles"] = tuple(settings_mod.DEFAULTS["fan_roles"])
        loaded.update(overrides)
        return loaded

    def test_shared_bus_two_addresses_and_delta(self):
        i2c = FakeI2C()
        plant_bmp280(i2c, 0x76, adc_p=ADC_P)
        plant_bmp280(i2c, 0x77, adc_p=ADC_P_HIGH)
        calls = []

        def factory(i2c_id, sda, scl):
            calls.append((i2c_id, sda, scl))
            return i2c

        pool = sensors.BusPool(factory)
        hub = sensors.build_sensors(
            self._settings(internal_enabled=True, external_enabled=True),
            pool,
        )
        snap = hub.read()
        self.assertEqual(calls, [(0, 4, 5)])
        self.assertTrue(snap["sensors"]["internal"]["ok"])
        self.assertTrue(snap["sensors"]["external"]["ok"])
        self.assertEqual(snap["sensors"]["internal"]["chip_id"], 0x58)
        self.assertAlmostEqual(
            snap["pressure_delta_pa"],
            (25767233 / 256.0) - (34657840 / 256.0),
        )

    def test_second_bus_when_both_addresses_are_0x76(self):
        buses = {0: FakeI2C(), 1: FakeI2C()}
        plant_bmp280(buses[0], 0x76, adc_p=ADC_P)
        plant_bmp280(buses[1], 0x76, adc_p=ADC_P_HIGH)
        calls = []

        def factory(i2c_id, sda, scl):
            calls.append((i2c_id, sda, scl))
            return buses[i2c_id]

        pool = sensors.BusPool(factory)
        hub = sensors.build_sensors(
            self._settings(
                internal_enabled=True,
                external_enabled=True,
                external_addr=0x76,
                external_i2c_id=1,
                external_sda=6,
                external_scl=7,
            ),
            pool,
        )
        snap = hub.read()
        self.assertEqual(calls, [(0, 4, 5), (1, 6, 7)])
        self.assertTrue(snap["sensors"]["internal"]["ok"])
        self.assertTrue(snap["sensors"]["external"]["ok"])
        self.assertIsNotNone(snap["pressure_delta_pa"])

    def test_missing_internal_does_not_drop_external(self):
        i2c = FakeI2C()
        plant_bmp280(i2c, 0x77)
        pool = sensors.BusPool(lambda *_args: i2c)
        hub = sensors.build_sensors(
            self._settings(internal_enabled=True, external_enabled=True),
            pool,
        )
        snap = hub.read()
        self.assertFalse(snap["sensors"]["internal"]["ok"])
        self.assertTrue(snap["sensors"]["external"]["ok"])
        self.assertIsNone(snap["pressure_delta_pa"])
        self.assertIn("init failed", snap["sensors"]["internal"]["error"])

    def test_disabled_hub_is_absent(self):
        self.assertIsNone(
            sensors.build_sensors(self._settings(), sensors.BusPool(lambda *_a: None))
        )


if __name__ == "__main__":
    unittest.main()
