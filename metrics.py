"""Prometheus text exposition for the fan controller."""


def format_metrics(status, http_counts):
    lines = []

    def gauge(name, help_text):
        lines.append("# HELP {} {}".format(name, help_text))
        lines.append("# TYPE {} gauge".format(name))

    def counter(name, help_text):
        lines.append("# HELP {} {}".format(name, help_text))
        lines.append("# TYPE {} counter".format(name))

    gauge("pico_fan_die_temp_celsius", "RP2040 die temperature in Celsius")
    lines.append("pico_fan_die_temp_celsius {:.3f}".format(float(status["die_c"])))

    # mode is intentionally not a label here. It changes over the life of a
    # fan and would split the duty series; pico_fan_override carries mode.
    gauge("pico_fan_duty_ratio", "Fan PWM duty ratio 0-1")
    for f in status["fans"]:
        lines.append(
            'pico_fan_duty_ratio{{fan="{}"}} {:.4f}'.format(f["id"], float(f["duty"]))
        )

    gauge("pico_fan_rpm", "Fan tachometer RPM")
    for f in status["fans"]:
        lines.append('pico_fan_rpm{{fan="{}"}} {:.0f}'.format(f["id"], float(f["rpm"])))

    gauge("pico_fan_override", "1 if fan is in manual override")
    for f in status["fans"]:
        lines.append(
            'pico_fan_override{{fan="{}"}} {}'.format(
                f["id"], 1 if f["mode"] == "manual" else 0
            )
        )

    gauge(
        "pico_fan_stall",
        "1 if duty is at or above the stall threshold and the latest RPM sample is 0",
    )
    for f in status["fans"]:
        lines.append(
            'pico_fan_stall{{fan="{}"}} {}'.format(f["id"], 1 if f.get("stall") else 0)
        )

    gauge("pico_fan_uptime_seconds", "Controller uptime in seconds")
    lines.append("pico_fan_uptime_seconds {}".format(int(status["uptime_s"])))

    gauge("pico_fan_wifi_up", "1 if Wi-Fi associated")
    wifi_up = 1 if status.get("wifi") == "connected" else 0
    lines.append("pico_fan_wifi_up {}".format(wifi_up))

    if "control_c" in status:
        gauge(
            "pico_fan_control_temp_celsius",
            "Temperature driving the auto fan curve",
        )
        lines.append(
            "pico_fan_control_temp_celsius {:.3f}".format(float(status["control_c"]))
        )

    source = status.get("temp_source") or "die"
    gauge(
        "pico_fan_temp_source_info",
        "1 for the active auto-curve temperature source",
    )
    for name in ("internal", "die"):
        lines.append(
            'pico_fan_temp_source_info{{source="{}"}} {}'.format(
                name, 1 if source == name else 0
            )
        )

    sensors = status.get("sensors") or {}
    gauge(
        "pico_fan_bmp280_up",
        "1 if this BMP280 is enabled and the latest read succeeded",
    )
    for location in ("internal", "external"):
        item = sensors.get(location) or {}
        lines.append(
            'pico_fan_bmp280_up{{location="{}"}} {}'.format(
                location, 1 if item.get("ok") else 0
            )
        )

    temp_lines = []
    pressure_lines = []
    for location in ("internal", "external"):
        item = sensors.get(location) or {}
        if not item.get("ok"):
            continue
        if item.get("temp_c") is not None:
            temp_lines.append(
                'pico_fan_bmp280_temperature_celsius{{location="{}"}} {:.3f}'.format(
                    location, float(item["temp_c"])
                )
            )
        if item.get("pressure_pa") is not None:
            pressure_lines.append(
                'pico_fan_bmp280_pressure_pascals{{location="{}"}} {:.3f}'.format(
                    location, float(item["pressure_pa"])
                )
            )
    if temp_lines:
        gauge(
            "pico_fan_bmp280_temperature_celsius",
            "BMP280 temperature in Celsius",
        )
        lines.extend(temp_lines)
    if pressure_lines:
        gauge(
            "pico_fan_bmp280_pressure_pascals",
            "BMP280 pressure in pascals",
        )
        lines.extend(pressure_lines)

    if status.get("pressure_delta_pa") is not None:
        gauge(
            "pico_fan_pressure_delta_pascals",
            "Internal BMP280 pressure minus external BMP280 pressure",
        )
        lines.append(
            "pico_fan_pressure_delta_pascals {:.3f}".format(
                float(status["pressure_delta_pa"])
            )
        )

    if any("role" in f for f in status.get("fans") or []):
        gauge("pico_fan_intake", "1 if the fan is an intake fan, 0 if it is exhaust")
        for f in status["fans"]:
            role = f.get("role")
            if role not in ("intake", "exhaust"):
                continue
            lines.append(
                'pico_fan_intake{{fan="{}"}} {}'.format(
                    f["id"], 1 if role == "intake" else 0
                )
            )

    if "oled" in status:
        gauge("pico_fan_oled_up", "1 if the OLED is enabled and the last update succeeded")
        oled = status.get("oled") or {}
        lines.append("pico_fan_oled_up {}".format(1 if oled.get("ok") else 0))

    counter("pico_fan_http_requests_total", "HTTP responses by path bucket and code")
    for path, codes in http_counts.items():
        for code, n in codes.items():
            lines.append(
                'pico_fan_http_requests_total{{path="{}",code="{}"}} {}'.format(
                    path, code, int(n)
                )
            )

    lines.append("")
    return "\n".join(lines)
