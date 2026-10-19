"""Load and check optional-peripheral settings.

Invalid pins, addresses, or airflow values are reported and replaced with
a safe setting. Fan PWM and tach pins are never given to a peripheral.
Nothing here touches hardware.
"""

import fan
import faults

# Pico W: GP23 wireless power, GP24 wireless status, GP25 wireless SPI.
# GP29 is ADC3 / VSYS. User I2C pins stay off that set and off the fan pins.
_GPIO_OK = set(list(range(0, 23)) + [26, 27, 28])

DEFAULTS = {
    "i2c_freq": 100000,
    "i2c_timeout_us": 50000,
    "internal_enabled": False,
    "internal_addr": 0x76,
    "internal_i2c_id": 0,
    "internal_sda": 4,
    "internal_scl": 5,
    "external_enabled": False,
    "external_addr": 0x76,
    "external_i2c_id": 1,
    "external_sda": 6,
    "external_scl": 7,
    "oled_enabled": False,
    "oled_addr": 0x3C,
    "oled_i2c_id": 0,
    "oled_sda": 4,
    "oled_scl": 5,
    "oled_width": 128,
    "oled_height": 32,
    "oled_page_s": 3,
    "fan_roles": fan.DEFAULT_ROLES,
    "exhaust_ratio": fan.DEFAULT_EXHAUST_RATIO,
    "exhaust_offset": fan.DEFAULT_EXHAUST_OFFSET,
    "pressure_loop_enabled": True,
    "pressure_target_pa": fan.DEFAULT_PRESSURE_TARGET_PA,
    "pressure_loop_gain": fan.DEFAULT_PRESSURE_LOOP_GAIN,
    "pressure_trim_max": fan.DEFAULT_PRESSURE_TRIM_MAX,
    "wifi_enabled": True,
    "wifi_ssid": "",
    "wifi_password": "",
    "wifi_timeout_s": 20.0,
    "wifi_retry_s": 10.0,
    "http_port": 80,
    "http_user": "",
    "http_password": "",
    "metrics_require_auth": True,
    "wdt_enabled": True,
    "wdt_timeout_ms": 8000,
    "stall_duty_min": fan.STALL_DUTY_MIN,
    "stall_rpm_below": float(fan.STALL_RPM_BELOW),
}
DEFAULTS.update(faults.DEFAULT_CFG)

# config.py names, in the order a shared bus is claimed.
_DEVICES = (
    ("internal", "INTERNAL_BMP280"),
    ("external", "EXTERNAL_BMP280"),
    ("oled", "OLED"),
)

_ATTRS = {
    "i2c_freq": "I2C_FREQ",
    "i2c_timeout_us": "I2C_TIMEOUT_US",
    "internal_enabled": "INTERNAL_BMP280_ENABLED",
    "internal_addr": "INTERNAL_BMP280_ADDR",
    "internal_i2c_id": "INTERNAL_BMP280_I2C_ID",
    "internal_sda": "INTERNAL_BMP280_SDA",
    "internal_scl": "INTERNAL_BMP280_SCL",
    "external_enabled": "EXTERNAL_BMP280_ENABLED",
    "external_addr": "EXTERNAL_BMP280_ADDR",
    "external_i2c_id": "EXTERNAL_BMP280_I2C_ID",
    "external_sda": "EXTERNAL_BMP280_SDA",
    "external_scl": "EXTERNAL_BMP280_SCL",
    "oled_enabled": "OLED_ENABLED",
    "oled_addr": "OLED_ADDR",
    "oled_i2c_id": "OLED_I2C_ID",
    "oled_sda": "OLED_SDA",
    "oled_scl": "OLED_SCL",
    "oled_width": "OLED_WIDTH",
    "oled_height": "OLED_HEIGHT",
    "oled_page_s": "OLED_PAGE_S",
    "fan_roles": "FAN_ROLES",
    "exhaust_ratio": "AIRFLOW_EXHAUST_RATIO",
    "exhaust_offset": "AIRFLOW_EXHAUST_OFFSET",
    "pressure_loop_enabled": "PRESSURE_LOOP_ENABLED",
    "pressure_target_pa": "PRESSURE_TARGET_PA",
    "pressure_loop_gain": "PRESSURE_LOOP_GAIN",
    "pressure_trim_max": "PRESSURE_LOOP_TRIM_MAX",
    "wifi_enabled": "WIFI_ENABLED",
    "wifi_ssid": "WIFI_SSID",
    "wifi_password": "WIFI_PASSWORD",
    "wifi_timeout_s": "WIFI_TIMEOUT_S",
    "wifi_retry_s": "WIFI_RETRY_S",
    "http_port": "HTTP_PORT",
    "http_user": "HTTP_USER",
    "http_password": "HTTP_PASSWORD",
    "metrics_require_auth": "METRICS_REQUIRE_AUTH",
    "wdt_enabled": "WDT_ENABLED",
    "wdt_timeout_ms": "WDT_TIMEOUT_MS",
    "stall_duty_min": "STALL_DUTY_MIN",
    "stall_rpm_below": "STALL_RPM_BELOW",
    "bmp280_temp_min_c": "BMP280_TEMP_MIN_C",
    "bmp280_temp_max_c": "BMP280_TEMP_MAX_C",
    "bmp280_temp_jump_c": "BMP280_TEMP_JUMP_C",
    "bmp280_press_min_pa": "BMP280_PRESS_MIN_PA",
    "bmp280_press_max_pa": "BMP280_PRESS_MAX_PA",
    "bmp280_press_jump_pa": "BMP280_PRESS_JUMP_PA",
    "bmp280_stuck_samples": "BMP280_STUCK_SAMPLES",
    "sensor_fault_set_samples": "SENSOR_FAULT_SET_SAMPLES",
    "sensor_fault_clear_samples": "SENSOR_FAULT_CLEAR_SAMPLES",
    "sensor_stale_s": "SENSOR_STALE_S",
    "die_temp_min_c": "DIE_TEMP_MIN_C",
    "die_temp_max_c": "DIE_TEMP_MAX_C",
    "die_temp_jump_c": "DIE_TEMP_JUMP_C",
    "tach_rpm_max": "TACH_RPM_MAX",
    "tach_zero_duty_rpm": "TACH_ZERO_DUTY_RPM",
    "pressure_delta_max_pa": "PRESSURE_DELTA_MAX_PA",
}


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def load_settings(module):
    """Return ``(settings, errors)``.

    ``settings`` is always safe to apply. ``errors`` lists what was wrong
    in ``module``; those fields have already been replaced.
    """
    settings = dict(DEFAULTS)
    settings["fan_roles"] = tuple(DEFAULTS["fan_roles"])
    errors = []
    if module is None:
        return settings, errors

    for key, attr in _ATTRS.items():
        if hasattr(module, attr):
            settings[key] = getattr(module, attr)

    _check_number(settings, errors, "i2c_freq", 1000, 400000, True)
    _check_number(settings, errors, "i2c_timeout_us", 1000, 500000, True)
    _check_bool(settings, errors, "internal_enabled")
    _check_bool(settings, errors, "external_enabled")
    _check_bool(settings, errors, "oled_enabled")
    _check_bool(settings, errors, "pressure_loop_enabled")

    for prefix, label in _DEVICES:
        _check_number(settings, errors, prefix + "_addr", 0x08, 0x77, True)
        _check_number(settings, errors, prefix + "_i2c_id", 0, 1, True)
        _check_number(settings, errors, prefix + "_sda", 0, 28, True)
        _check_number(settings, errors, prefix + "_scl", 0, 28, True)

    _check_number(settings, errors, "oled_width", 8, 128, True)
    _check_number(settings, errors, "oled_height", 8, 64, True)
    _check_number(settings, errors, "oled_page_s", 1, 60, True)
    _check_number(settings, errors, "exhaust_ratio", 0.0, 2.0, False)
    _check_number(settings, errors, "exhaust_offset", -1.0, 1.0, False)
    _check_number(settings, errors, "pressure_target_pa", -10000.0, 10000.0, False)
    _check_number(settings, errors, "pressure_loop_gain", -1.0, 1.0, False)
    _check_number(settings, errors, "pressure_trim_max", 0.0, 0.5, False)
    _check_bool(settings, errors, "wifi_enabled")
    _check_bool(settings, errors, "metrics_require_auth")
    _check_bool(settings, errors, "wdt_enabled")
    _check_str(settings, errors, "wifi_ssid")
    _check_str(settings, errors, "wifi_password")
    _check_str(settings, errors, "http_user")
    _check_str(settings, errors, "http_password")
    _check_number(settings, errors, "wifi_timeout_s", 1, 120, False)
    _check_number(settings, errors, "wifi_retry_s", 1, 300, False)
    _check_number(settings, errors, "http_port", 1, 65535, True)
    _check_number(settings, errors, "wdt_timeout_ms", 1000, 8388, True)
    _check_number(settings, errors, "stall_duty_min", 0.0, 1.0, False)
    _check_number(settings, errors, "stall_rpm_below", 0, 100000, False)
    _check_number(settings, errors, "bmp280_temp_min_c", -80.0, 40.0, False)
    _check_number(settings, errors, "bmp280_temp_max_c", 0.0, 125.0, False)
    _check_number(settings, errors, "bmp280_temp_jump_c", 0.5, 40.0, False)
    _check_number(settings, errors, "bmp280_press_min_pa", 10000.0, 90000.0, False)
    _check_number(settings, errors, "bmp280_press_max_pa", 100000.0, 120000.0, False)
    _check_number(settings, errors, "bmp280_press_jump_pa", 50.0, 20000.0, False)
    _check_number(settings, errors, "bmp280_stuck_samples", 5, 3600, True)
    _check_number(settings, errors, "sensor_fault_set_samples", 1, 30, True)
    _check_number(settings, errors, "sensor_fault_clear_samples", 1, 30, True)
    _check_number(settings, errors, "sensor_stale_s", 1, 300, False)
    _check_number(settings, errors, "die_temp_min_c", -40.0, 40.0, False)
    _check_number(settings, errors, "die_temp_max_c", 40.0, 150.0, False)
    _check_number(settings, errors, "die_temp_jump_c", 1.0, 50.0, False)
    _check_number(settings, errors, "tach_rpm_max", 1000, 30000, False)
    _check_number(settings, errors, "tach_zero_duty_rpm", 1, 5000, False)
    _check_number(settings, errors, "pressure_delta_max_pa", 50.0, 50000.0, False)
    _check_order(
        settings,
        errors,
        "bmp280_temp_min_c",
        "bmp280_temp_max_c",
        "BMP280_TEMP_MIN_C must be below BMP280_TEMP_MAX_C",
    )
    _check_order(
        settings,
        errors,
        "bmp280_press_min_pa",
        "bmp280_press_max_pa",
        "BMP280_PRESS_MIN_PA must be below BMP280_PRESS_MAX_PA",
    )
    _check_order(
        settings,
        errors,
        "die_temp_min_c",
        "die_temp_max_c",
        "DIE_TEMP_MIN_C must be below DIE_TEMP_MAX_C",
    )

    height = settings["oled_height"]
    if _is_int(height) and height % 8 != 0:
        errors.append("OLED_HEIGHT must be a multiple of 8")
        settings["oled_height"] = DEFAULTS["oled_height"]

    roles = fan.normalize_roles(settings.get("fan_roles"))
    if roles is None:
        errors.append("FAN_ROLES must be four of intake or exhaust")
        settings["fan_roles"] = tuple(DEFAULTS["fan_roles"])
    else:
        settings["fan_roles"] = roles

    _check_buses(settings, errors)
    return settings, errors


def _check_str(settings, errors, key):
    value = settings.get(key)
    if isinstance(value, str):
        return
    errors.append("{} must be a string".format(_ATTRS[key]))
    settings[key] = DEFAULTS[key]


def _check_order(settings, errors, low_key, high_key, message):
    if float(settings[low_key]) < float(settings[high_key]):
        return
    errors.append(message)
    settings[low_key] = DEFAULTS[low_key]
    settings[high_key] = DEFAULTS[high_key]


def _check_bool(settings, errors, key):
    value = settings.get(key)
    if isinstance(value, bool):
        return
    errors.append("{} must be True or False".format(_ATTRS[key]))
    settings[key] = DEFAULTS[key]


def _check_number(settings, errors, key, low, high, integer):
    value = settings.get(key)
    ok_type = _is_int(value) if integer else _is_number(value)
    if ok_type and low <= float(value) <= high:
        if integer:
            settings[key] = int(value)
        else:
            settings[key] = float(value)
        return
    kind = "an integer" if integer else "a number"
    errors.append(
        "{} must be {} from {} to {}".format(_ATTRS[key], kind, low, high)
    )
    settings[key] = DEFAULTS[key]


def _pin_problem(label, pin):
    if pin in set(fan.PWM_PINS) | set(fan.TACH_PINS):
        return "{} pin GP{} is used by a fan".format(label, pin)
    if pin in (23, 24, 25, 29):
        return "{} pin GP{} is reserved on Pico W".format(label, pin)
    if pin not in _GPIO_OK:
        return "{} pin GP{} is not a free GPIO".format(label, pin)
    return None


def _disable(settings, prefix):
    settings[prefix + "_enabled"] = False


def _check_buses(settings, errors):
    claimed = {}  # i2c id -> (sda, scl, label)
    used_addr = {}  # (i2c id, addr) -> label
    for prefix, label in _DEVICES:
        if not settings.get(prefix + "_enabled"):
            continue
        sda = settings[prefix + "_sda"]
        scl = settings[prefix + "_scl"]
        i2c_id = settings[prefix + "_i2c_id"]
        addr = settings[prefix + "_addr"]
        problem = None
        if sda == scl:
            problem = "{} SDA and SCL are both GP{}".format(label, sda)
        else:
            for pin in (sda, scl):
                problem = _pin_problem(label, pin)
                if problem:
                    break
        if problem is None and i2c_id in claimed:
            prev_sda, prev_scl, prev_label = claimed[i2c_id]
            if (prev_sda, prev_scl) != (sda, scl):
                problem = (
                    "{} pins GP{}/GP{} do not match I2C{} already used by {} on GP{}/GP{}"
                ).format(label, sda, scl, i2c_id, prev_label, prev_sda, prev_scl)
        if problem is None:
            key = (i2c_id, addr)
            if key in used_addr:
                problem = "{} address 0x{:02X} on I2C{} conflicts with {}".format(
                    label, addr, i2c_id, used_addr[key]
                )
        if problem is not None:
            errors.append(problem)
            _disable(settings, prefix)
            continue
        claimed.setdefault(i2c_id, (sda, scl, label))
        used_addr[(i2c_id, addr)] = label
