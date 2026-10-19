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
