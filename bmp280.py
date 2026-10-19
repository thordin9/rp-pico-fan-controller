"""BMP280 pressure and temperature driver.

Compensation is the 64-bit integer formula from Bosch BST-BMP280-DS001
section 3.11.3 (code revision 1.1). Temperature comes back in 0.01 °C
steps; pressure comes back in Q24.8 pascals and is converted to pascals.

The chip id register 0xD0 must read 0x58. Anything else is refused.
"""

import time

CHIP_ID_BMP280 = 0x58

REG_CALIB = 0x88
REG_ID = 0xD0
REG_RESET = 0xE0
REG_CONFIG = 0xF5
REG_CTRL_MEAS = 0xF4
REG_PRESS_MSB = 0xF7
CALIB_LEN = 24
SAMPLE_LEN = 6
RESET_CMD = 0xB6

# Sleep, then config, then normal mode. Datasheet: config writes in normal
# mode may be ignored, so ctrl_meas is written last.
# ctrl_meas 0x57: osrs_t x2, osrs_p x16, mode normal (tables 21, 22, 3.6).
# config 0xA8: t_standby 1000 ms, IIR filter coefficient 4, SPI 3-wire off.
CTRL_MEAS_NORMAL = 0x57
CONFIG_1HZ_FILTER4 = 0xA8

# Soft-reset start-up is 2 ms typical (datasheet tstartup). 10 ms is margin.
RESET_SETTLE_MS = 10


def _cdiv(n, d):
    """Integer division that truncates toward zero, matching the C formula."""
    if d == 0:
        return 0
    q = int(n // d)
    if ((n < 0) ^ (d < 0)) and (n % d):
        q += 1
    return q


def _u16_le(data, offset):
    return data[offset] | (data[offset + 1] << 8)


def _s16_le(data, offset):
    value = _u16_le(data, offset)
    if value & 0x8000:
        value -= 0x10000
    return value


def parse_calibration(data):
    """Return (T1, T2, T3, P1..P9) from the 24-byte calib block at 0x88.

    T1 and P1 are unsigned. The rest are signed. Little-endian, as stored.
    """
    if data is None or len(data) < CALIB_LEN:
        raise ValueError("BMP280 calibration block is short")
    raw = data
    if not isinstance(raw, (bytes, bytearray)):
        raw = bytes(raw)
    return (
        _u16_le(raw, 0),
        _s16_le(raw, 2),
        _s16_le(raw, 4),
        _u16_le(raw, 6),
        _s16_le(raw, 8),
        _s16_le(raw, 10),
        _s16_le(raw, 12),
        _s16_le(raw, 14),
        _s16_le(raw, 16),
        _s16_le(raw, 18),
        _s16_le(raw, 20),
        _s16_le(raw, 22),
    )


def unpack_sample(data):
    """Split a 6-byte burst from 0xF7 into (adc_p, adc_t), both 20-bit."""
    if data is None or len(data) < SAMPLE_LEN:
        raise ValueError("BMP280 sample is short")
    adc_p = (data[0] << 12) | (data[1] << 4) | (data[2] >> 4)
    adc_t = (data[3] << 12) | (data[4] << 4) | (data[5] >> 4)
    return adc_p, adc_t


def compensate(adc_t, adc_p, calib):
    """Return (temp_c, pressure_pa) using Bosch section 3.11.3.

    ``pressure_pa`` is the Q24.8 result divided by 256, so the datasheet
    example (adc_t 519888, adc_p 415148, the published dig_* set) is
    25.08 °C and 100653.25390625 Pa. A zero dig_P1 returns 0 Pa.
    """
    dig_t1, dig_t2, dig_t3 = calib[0], calib[1], calib[2]
    dig_p1 = calib[3]
    dig_p2, dig_p3, dig_p4 = calib[4], calib[5], calib[6]
    dig_p5, dig_p6, dig_p7 = calib[7], calib[8], calib[9]
    dig_p8, dig_p9 = calib[10], calib[11]

    var1 = (((adc_t >> 3) - (dig_t1 << 1)) * dig_t2) >> 11
    var2 = (((((adc_t >> 4) - dig_t1) * ((adc_t >> 4) - dig_t1)) >> 12) * dig_t3) >> 14
    t_fine = var1 + var2
    temp_x100 = (t_fine * 5 + 128) >> 8

    var1 = t_fine - 128000
    var2 = var1 * var1 * dig_p6
    var2 = var2 + ((var1 * dig_p5) << 17)
    var2 = var2 + (dig_p4 << 35)
    var1 = ((var1 * var1 * dig_p3) >> 8) + ((var1 * dig_p2) << 12)
    var1 = ((((1 << 47) + var1) * dig_p1) >> 33)
    if var1 == 0:
        return temp_x100 / 100.0, 0.0
    pressure = 1048576 - adc_p
    pressure = _cdiv(((pressure << 31) - var2) * 3125, var1)
    var1 = (dig_p9 * (pressure >> 13) * (pressure >> 13)) >> 25
    var2 = (dig_p8 * pressure) >> 19
    pressure = ((pressure + var1 + var2) >> 8) + (dig_p7 << 4)
    return temp_x100 / 100.0, pressure / 256.0


def _sleep_ms(ms):
    sleeper = getattr(time, "sleep_ms", None)
    if sleeper is not None:
        sleeper(ms)
        return
    time.sleep(ms / 1000.0)


def _blank_status(enabled, error=""):
    return {
        "enabled": bool(enabled),
        "ok": False,
        "chip_id": None,
        "temp_c": None,
        "pressure_pa": None,
        "error": error or "",
    }


class Bmp280:
    """One BMP280 on an injected I2C bus.

    ``name`` is ``internal`` or ``external`` and is only used in logs.
    ``init`` and ``read`` catch bus errors and record them on ``status``.
    A chip id other than 0x58 is permanent: later reads do not pretend the
    part is a BMP280.
    """

    def __init__(self, i2c, addr, name, feed=None):
        self.i2c = i2c
        self.addr = int(addr)
        self.name = name
        self.feed = feed
        self._calib = None
        self._ready = False
        self._permanent = False
        self._scanned = False
        self._status = _blank_status(True)

    def status(self):
        return {
            "enabled": True,
            "ok": bool(self._status["ok"]),
            "chip_id": self._status["chip_id"],
            "temp_c": self._status["temp_c"],
            "pressure_pa": self._status["pressure_pa"],
            "error": self._status["error"],
        }

    def init(self):
        """Identify, reset, load calibration, start normal mode.

        Returns True only when the chip id is 0x58 and configuration landed.
        """
        if self._permanent:
            return False
        try:
            chip = self._read(REG_ID, 1)[0]
        except Exception as exc:
            self._fail("init failed: {}".format(exc), scan=True)
            return False
        self._status["chip_id"] = chip
        if chip != CHIP_ID_BMP280:
            self._permanent = True
            self._ready = False
            self._calib = None
            self._fail(
                "chip id 0x{:02X} is not BMP280 (0x58)".format(chip),
                scan=True,
            )
            return False
        try:
            self._write(REG_RESET, RESET_CMD)
            if self.feed is not None:
                self.feed()
            _sleep_ms(RESET_SETTLE_MS)
            if self.feed is not None:
                self.feed()
            calib = parse_calibration(self._read(REG_CALIB, CALIB_LEN))
            # Config while the part is still in sleep (post-reset), then mode.
            self._write(REG_CONFIG, CONFIG_1HZ_FILTER4)
            self._write(REG_CTRL_MEAS, CTRL_MEAS_NORMAL)
        except Exception as exc:
            self._ready = False
            self._calib = None
            self._fail("init failed: {}".format(exc), scan=True)
            return False
        self._calib = calib
        self._ready = True
        # The first conversion is not ready yet. Leave ok false so the fan
        # curve stays on the die sensor until read() lands a real sample.
        self._status["ok"] = False
        self._status["error"] = "starting"
        self._status["temp_c"] = None
        self._status["pressure_pa"] = None
        print(
            "bmp280 {}: ready addr=0x{:02X} id=0x{:02X}".format(
                self.name, self.addr, chip
            )
        )
        return True

    def read(self):
        """Refresh temperature and pressure. Never raises.

        A bus error clears the sample and drops ``ok`` so the fan curve can
        fall back to the die sensor. The next call tries init again, unless
        the chip id was wrong.
        """
        if self._permanent:
            return self.status()
        if not self._ready or self._calib is None:
            self.init()
            if not self._ready:
                return self.status()
        try:
            adc_p, adc_t = unpack_sample(self._read(REG_PRESS_MSB, SAMPLE_LEN))
            temp_c, pressure_pa = compensate(adc_t, adc_p, self._calib)
        except Exception as exc:
            self._ready = False
            self._calib = None
            self._fail("read failed: {}".format(exc), scan=False)
            return self.status()
        self._set_status(ok=True, error="", temp_c=temp_c, pressure_pa=pressure_pa)
        return self.status()

    def _set_status(self, ok, error, temp_c, pressure_pa):
        previous = self._status["error"]
        self._status["ok"] = bool(ok)
        self._status["error"] = error or ""
        self._status["temp_c"] = temp_c
        self._status["pressure_pa"] = pressure_pa
        if error and error != previous:
            print("bmp280 {}: {}".format(self.name, error))
        elif ok and previous:
            print("bmp280 {}: reading ok".format(self.name))

    def _fail(self, error, scan):
        if scan and not self._scanned:
            self._scanned = True
            found = _scan(self.i2c)
            if found is not None:
                shown = ",".join("0x{:02X}".format(addr) for addr in found) or "none"
                error = "{} scan={}".format(error, shown)
        self._set_status(ok=False, error=error, temp_c=None, pressure_pa=None)

    def _read(self, reg, nbytes):
        data = self.i2c.readfrom_mem(self.addr, reg, nbytes)
        if len(data) < nbytes:
            raise OSError("short I2C read")
        return data

    def _write(self, reg, value):
        self.i2c.writeto(self.addr, bytes((reg, value)))


def _scan(i2c):
    scan = getattr(i2c, "scan", None)
    if scan is None:
        return None
    try:
        return list(scan())
    except Exception as exc:
        print("i2c: scan failed:", exc)
        return None


def disabled_status():
    """Status dict for a BMP280 that config left turned off."""
    return _blank_status(False)
