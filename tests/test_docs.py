"""Keep the user-facing docs aligned with config.py and metrics.py."""

import ast
import json
import os
import re
import unittest

ROOT = os.path.join(os.path.dirname(__file__), "..")

CURRENT_DOCS = (
    "README.md",
    "docs/config.md",
    "docs/how-it-works.md",
    "docs/wiring.md",
    "docs/api.md",
    "docs/troubleshooting.md",
    "enclosure/README.md",
)

FLASH_FILES = (
    "config.py",
    "settings.py",
    "faults.py",
    "fan.py",
    "wifi.py",
    "web.py",
    "metrics.py",
    "bmp280.py",
    "sensors.py",
    "display.py",
    "ssd1306.py",
    "main.py",
)


def _read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as handle:
        return handle.read()


def _config_names():
    tree = ast.parse(_read("config.py"))
    names = []
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id.isupper():
                    names.append(target.id)
    return names


def _table_names(text):
    return re.findall(r"^\| `([A-Z][A-Z0-9_]*)` \|", text, re.M)


def _fenced(text, lang):
    blocks = []
    fence = None
    body = []
    for line in text.splitlines():
        if fence is None:
            match = re.match(r"^```(" + lang + r")\s*$", line)
            if match:
                fence = match.group(1)
                body = []
        elif line.startswith("```"):
            blocks.append("\n".join(body))
            fence = None
        else:
            body.append(line)
    if fence is not None:
        raise AssertionError("unclosed %s fence" % lang)
    return blocks


class TestConfigReference(unittest.TestCase):
    def test_every_config_setting_is_in_the_table(self):
        documented = _table_names(_read("docs/config.md"))
        self.assertEqual(sorted(documented), sorted(_config_names()))
        self.assertEqual(len(documented), len(set(documented)))

    def test_pressure_loop_and_addresses_match_the_defaults(self):
        text = _read("docs/config.md")
        self.assertIn("| `PRESSURE_LOOP_ENABLED` | `True` |", text)
        self.assertIn("| `EXTERNAL_BMP280_I2C_ID` | `1` |", text)
        self.assertIn("| `EXTERNAL_BMP280_ADDR` | `0x76` |", text)
        self.assertIn("| `INTERNAL_BMP280_ADDR` | `0x76` |", text)


class TestApiReference(unittest.TestCase):
    def test_every_metric_name_is_documented(self):
        source = _read("metrics.py")
        names = sorted(set(re.findall(r"pico_fan_[a-z0-9_]+", source)))
        page = _read("docs/api.md")
        missing = [name for name in names if name not in page]
        self.assertEqual(missing, [])

    def test_grafana_example_is_json(self):
        blocks = _fenced(_read("docs/api.md"), "json")
        self.assertEqual(len(blocks), 1)
        dashboard = json.loads(blocks[0])
        self.assertEqual(dashboard["title"], "Pico fan controller")
        self.assertGreaterEqual(len(dashboard["panels"]), 4)


class TestReadme(unittest.TestCase):
    def test_flash_list_includes_faults(self):
        text = _read("README.md")
        for name in FLASH_FILES:
            self.assertIn("`%s`" % name, text)

    def test_serial_example_matches_the_format_width(self):
        text = _read("README.md") + _read("docs/troubleshooting.md")
        self.assertIn("F1=a=18%", text)
        self.assertNotIn("a= 18%", text)

    def test_pins_include_physical_numbers(self):
        wiring = _read("docs/wiring.md")
        for row in (
            "| I2C0 SDA | GP4 | 6 |",
            "| I2C0 SCL | GP5 | 7 |",
            "| I2C1 SDA | GP6 | 9 |",
            "| I2C1 SCL | GP7 | 10 |",
            "| Board power, about 5 V | VSYS | 39 |",
            "| Logic 3.3 V output | 3V3(OUT) | 36 |",
            "| Fan 1 PWM | GP15 | 20 |",
            "| Fan 1 tach | GP14 | 19 |",
            "| Fan 4 tach | GP11 | 15 |",
        ):
            self.assertIn(row, wiring)


class TestCurrentDocs(unittest.TestCase):
    def test_no_stale_sensor_or_default(self):
        for rel in CURRENT_DOCS:
            text = _read(rel)
            self.assertNotIn("BME280", text, rel)
            self.assertNotIn("humidity", text.lower(), rel)
            self.assertNotRegex(text, r"shared[- ]bus is the default", rel)
            self.assertNotRegex(text, r"loop (is )?off by default", rel)
            self.assertNotIn("15% exhaust", text, rel)

    def test_diagrams_are_closed_flowcharts(self):
        for rel in CURRENT_DOCS:
            for block in _fenced(_read(rel), "mermaid"):
                self.assertTrue(block.startswith("flowchart "), rel)
                self.assertNotRegex(block, r"^\s*end\[", rel)

    def test_local_links_resolve(self):
        link = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
        for rel in CURRENT_DOCS + (
            "docs/superpowers/specs/2026-10-19-bmp280-oled-airflow-design.md",
            "docs/superpowers/specs/2026-10-14-per-fan-control-prometheus-design.md",
            "docs/superpowers/plans/2026-10-14-per-fan-control-prometheus.md",
        ):
            base = os.path.dirname(os.path.join(ROOT, rel))
            for target in link.findall(_read(rel)):
                if target.startswith(("http://", "https://", "mailto:")):
                    continue
                path = target.split("#", 1)[0]
                if not path:
                    continue
                self.assertTrue(
                    os.path.exists(os.path.normpath(os.path.join(base, path))),
                    "%s -> %s" % (rel, target),
                )

    def test_historical_plans_are_marked(self):
        for rel in (
            "docs/superpowers/specs/2026-10-14-per-fan-control-prometheus-design.md",
            "docs/superpowers/plans/2026-10-14-per-fan-control-prometheus.md",
        ):
            self.assertIn("**Historical.**", _read(rel))
