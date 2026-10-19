"""Internal and external BMP280s on one or two I2C buses.

The default is two buses, both at address 0x76: internal on I2C0 (GP4/GP5,
shared with the OLED) and external on I2C1 (GP6/GP7). A module that can
strap SDO to 3V3 may instead share I2C0 at 0x77. Reads never raise: a
missing or failed part is reported and the fan loop keeps using the die
temperature. The pressure trim runs only while both reads are ok.
"""

import bmp280


class BusPool:
    """Open each hardware I2C id once so several devices share the pins."""

    def __init__(self, factory):
        self.factory = factory
        self._buses = {}
        self.pins = {}

    def get(self, i2c_id, sda, scl):
        key = int(i2c_id)
        if key in self._buses:
            return self._buses[key]
        bus = self.factory(key, int(sda), int(scl))
        self._buses[key] = bus
        self.pins[key] = (int(sda), int(scl))
        return bus


class SensorHub:
    """Holds the two BMP280 endpoints and the pressure difference.

    ``internal`` / ``external`` are Bmp280 instances, or None when that
    location is disabled or its bus could not be opened. ``open_error`` is
    the message for a location that was enabled but never got a driver.
    """

    def __init__(self, internal=None, external=None, open_errors=None):
        self.internal = internal
        self.external = external
        self.open_errors = open_errors or {}

    def read(self):
        """Sample both parts. One failure does not skip the other."""
        for device in (self.internal, self.external):
            if device is None:
                continue
            try:
                device.read()
            except Exception as exc:
                print("bmp280 {}: read raised {}".format(device.name, exc))
        return self.snapshot()

    def snapshot(self):
        internal = self._one("internal", self.internal)
        external = self._one("external", self.external)
        delta = None
        if internal["ok"] and external["ok"]:
            try:
                delta = float(internal["pressure_pa"]) - float(external["pressure_pa"])
            except (TypeError, ValueError):
                delta = None
        return {
            "sensors": {"internal": internal, "external": external},
            "pressure_delta_pa": delta,
        }

    def _one(self, name, device):
        if device is not None:
            try:
                return device.status()
            except Exception as exc:
                status = bmp280.disabled_status()
                status["enabled"] = True
                status["error"] = "status failed: {}".format(exc)
                return status
        if name in self.open_errors:
            status = bmp280.disabled_status()
            status["enabled"] = True
            status["error"] = self.open_errors[name]
            return status
        return bmp280.disabled_status()


def _attach(pool, settings, prefix, name, feed):
    enabled = bool(settings.get(prefix + "_enabled"))
    if not enabled:
        return None, None
    try:
        bus = pool.get(
            settings[prefix + "_i2c_id"],
            settings[prefix + "_sda"],
            settings[prefix + "_scl"],
        )
    except Exception as exc:
        message = "i2c open failed: {}".format(exc)
        print("bmp280 {}: {}".format(name, message))
        return None, message
    device = bmp280.Bmp280(bus, settings[prefix + "_addr"], name, feed=feed)
    device.init()
    return device, None


def build_sensors(settings, pool, feed=None):
    """Return a SensorHub, or None when both BMP280s are disabled."""
    if not settings.get("internal_enabled") and not settings.get("external_enabled"):
        return None
    internal, internal_err = _attach(pool, settings, "internal", "internal", feed)
    external, external_err = _attach(pool, settings, "external", "external", feed)
    errors = {}
    if internal_err:
        errors["internal"] = internal_err
    if external_err:
        errors["external"] = external_err
    return SensorHub(internal, external, errors)


def machine_i2c_factory(freq, timeout_us):
    """Return a factory(id, sda, scl) that opens ``machine.I2C``.

    ``timeout_us`` bounds clock stretching. A NACK from a missing device
    returns immediately. Firmware that rejects the timeout keyword is
    retried without it.
    """

    def factory(i2c_id, sda, scl):
        import machine

        pin_sda = machine.Pin(sda)
        pin_scl = machine.Pin(scl)
        try:
            return machine.I2C(
                i2c_id,
                scl=pin_scl,
                sda=pin_sda,
                freq=int(freq),
                timeout=int(timeout_us),
            )
        except TypeError:
            print("i2c: this firmware has no I2C timeout; opening without it")
            return machine.I2C(i2c_id, scl=pin_scl, sda=pin_sda, freq=int(freq))

    return factory
