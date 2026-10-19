"""128x32 OLED pages for the fan controller.

Four text rows of 8 px fit on the Waveshare 0.91 inch panel (16 characters).
Four pages rotate every ``page_s`` seconds. A fifth SENSOR FAULT page is
added only while a sensor fault is latched. The framebuffer is updated from
the 1 s sample, not from the 10 ms poll, so a 512-byte I2C write cannot
steal the control cadence. A missing panel or a failed write is logged and
ignored.
"""

import ssd1306

# 8x8 glyphs, byte 0 is the top row, bit 7 is the leftmost pixel.
# Printable set used by the pages. Unknown characters become "?".
FONT = {
    "!": (0x60, 0x60, 0xC0, 0xC0, 0x00, 0xC0, 0xC0, 0x00),
    "%": (0xC6, 0xCC, 0x18, 0x30, 0x60, 0xCC, 0xC6, 0x00),
    "+": (0x00, 0x18, 0x18, 0xFF, 0x18, 0x18, 0x00, 0x00),
    "-": (0x00, 0x00, 0x00, 0xFC, 0x00, 0x00, 0x00, 0x00),
    ".": (0x00, 0x00, 0x00, 0x00, 0x00, 0x60, 0xC0, 0x00),
    "0": (0x3C, 0x66, 0x6C, 0xCC, 0xD8, 0x66, 0x3C, 0x00),
    "1": (0x18, 0x38, 0x18, 0x18, 0x18, 0x18, 0x7E, 0x00),
    "2": (0x3C, 0x66, 0x06, 0x0C, 0x18, 0x60, 0xFC, 0x00),
    "3": (0x3C, 0x66, 0x06, 0x3C, 0x06, 0x66, 0x3C, 0x00),
    "4": (0x0C, 0x1C, 0x2C, 0x4C, 0xFC, 0x0C, 0x0C, 0x00),
    "5": (0x7E, 0xC0, 0xC0, 0x7C, 0x06, 0x66, 0x3C, 0x00),
    "6": (0x3C, 0x60, 0xC0, 0xFC, 0xC6, 0xC6, 0x3C, 0x00),
    "7": (0xFC, 0x06, 0x0C, 0x18, 0x30, 0x60, 0xC0, 0x00),
    "8": (0x3C, 0x66, 0xC6, 0x3C, 0xC6, 0x66, 0x3C, 0x00),
    "9": (0x3C, 0xC6, 0xC6, 0x3E, 0x06, 0x66, 0x3C, 0x00),
    "?": (0x3C, 0x66, 0x0C, 0x18, 0x00, 0x18, 0x18, 0x00),
    "A": (0x3C, 0x66, 0xC3, 0xFC, 0xC3, 0xC3, 0xC3, 0x00),
    "B": (0xFC, 0xC6, 0xC6, 0xFC, 0xC6, 0xC6, 0xFC, 0x00),
    "C": (0x3C, 0x66, 0xC0, 0xC0, 0xC0, 0x66, 0x3C, 0x00),
    "D": (0xF8, 0xCC, 0xC6, 0xC6, 0xC6, 0xCC, 0xF8, 0x00),
    "E": (0xFC, 0xC0, 0xC0, 0xF8, 0xC0, 0xC0, 0xFC, 0x00),
    "F": (0xFC, 0xC0, 0xC0, 0xF8, 0xC0, 0xC0, 0xC0, 0x00),
    "G": (0x3C, 0x66, 0xC0, 0xDE, 0xC6, 0x66, 0x3C, 0x00),
    "H": (0xC6, 0xC6, 0xC6, 0xFE, 0xC6, 0xC6, 0xC6, 0x00),
    "I": (0xFC, 0x30, 0x30, 0x30, 0x30, 0x30, 0xFC, 0x00),
    "J": (0x1E, 0x0C, 0x0C, 0x0C, 0xCC, 0xCC, 0x3C, 0x00),
    "K": (0xCC, 0xD8, 0xF0, 0xE0, 0xF0, 0xD8, 0xCC, 0x00),
    "L": (0xC0, 0xC0, 0xC0, 0xC0, 0xC0, 0xC0, 0xFC, 0x00),
    "M": (0xC6, 0xEE, 0xD6, 0xC6, 0xC6, 0xC6, 0xC6, 0x00),
    "N": (0xC6, 0xE6, 0xF6, 0xDE, 0xCE, 0xC6, 0xC6, 0x00),
    "O": (0x3C, 0x66, 0xC3, 0xC3, 0xC3, 0x66, 0x3C, 0x00),
    "P": (0xFC, 0xC6, 0xC6, 0xFC, 0xC0, 0xC0, 0xC0, 0x00),
    "Q": (0x3C, 0x66, 0xC3, 0xCB, 0x66, 0x3C, 0x06, 0x00),
    "R": (0xFC, 0xC6, 0xC6, 0xFC, 0xD8, 0xCC, 0xC6, 0x00),
    "S": (0x3E, 0xC0, 0xC0, 0x3C, 0x06, 0x06, 0xF8, 0x00),
    "T": (0xFC, 0x30, 0x30, 0x30, 0x30, 0x30, 0x30, 0x00),
    "U": (0xC6, 0xC6, 0xC6, 0xC6, 0xC6, 0x66, 0x3C, 0x00),
    "V": (0xC6, 0xC6, 0xC6, 0x6C, 0x6C, 0x38, 0x10, 0x00),
    "W": (0xC6, 0xC6, 0xC6, 0xD6, 0x6C, 0x6C, 0x28, 0x00),
    "X": (0xC6, 0x6C, 0x38, 0x10, 0x38, 0x6C, 0xC6, 0x00),
    "Y": (0xC6, 0x6C, 0x38, 0x10, 0x10, 0x10, 0x10, 0x00),
    "Z": (0xFC, 0x0C, 0x18, 0x30, 0x60, 0xC0, 0xFC, 0x00),
    " ": (0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00),
}

COLS = 16
ROWS = 4
PAGE_COUNT = 4

# MicroPython ticks_ms wraps every 2**30 ms.
_TICKS_MASK = 0x3FFFFFFF
_TICKS_PERIOD = 0x40000000
_TICKS_HALF = 0x20000000


def ticks_diff(ticks1, ticks2):
    diff = (int(ticks1) - int(ticks2)) & _TICKS_MASK
    if diff >= _TICKS_HALF:
        diff -= _TICKS_PERIOD
    return diff


def fit(text):
    text = "" if text is None else str(text)
    if len(text) > COLS:
        return text[:COLS]
    return text


def _temp_text(temp_c):
    if temp_c is None:
        return "T--"
    try:
        return "T{:.1f}C".format(float(temp_c))
    except (TypeError, ValueError):
        return "T--"


def _loop_word(status):
    if status.get("pressure_loop_active"):
        return "on"
    if status.get("pressure_loop_enabled"):
        return "idle"
    return "off"


def _delta_text(delta, status):
    word = _loop_word(status)
    if delta is None:
        return "dP -- " + word
    try:
        return "dP {:+.0f}Pa {}".format(float(delta), word)
    except (TypeError, ValueError):
        return "dP -- " + word


def _sensor_page(title, item):
    item = item or {}
    if not item.get("enabled"):
        return [title, "disabled", "", ""]
    if not item.get("ok"):
        err = item.get("error") or ""
        if err in ("", "starting"):
            return [title, "starting", "", ""]
        return [title, "fail", err, ""]
    temp_c = item.get("temp_c")
    pressure = item.get("pressure_pa")
    if temp_c is None:
        tline = "--"
    else:
        tline = "{:.1f} C".format(float(temp_c))
    if pressure is None:
        pline = "--"
    else:
        pline = "{:.0f} Pa".format(float(pressure))
    return [title, tline, pline, "ok"]


def _fan_line(fan):
    role = "E" if fan.get("role") == "exhaust" else "I"
    try:
        rpm = int(round(float(fan.get("rpm") or 0)))
    except (TypeError, ValueError):
        rpm = 0
    try:
        pct = int(round(float(fan.get("duty") or 0) * 100))
    except (TypeError, ValueError):
        pct = 0
    flags = ""
    if fan.get("mode") == "manual":
        flags += "m"
    if fan.get("stall"):
        flags += "!"
    return "{}{} {:5d} {:3d}%{}".format(fan.get("id", "?"), role, rpm, pct, flags)


def _fault_page(faults):
    """One warning page, or None when nothing is latched."""
    if not faults:
        return None
    first = faults[0] if isinstance(faults[0], dict) else {}
    extra = ""
    if len(faults) > 1:
        extra = "+{} more".format(len(faults) - 1)
    return (
        fit("SENSOR FAULT"),
        fit(str(first.get("short") or "SENSOR")),
        fit(str(first.get("short_reason") or "fault")),
        fit(extra),
    )


def build_pages(status):
    """Return 4 pages, or 5 when a sensor fault is latched.

    Each page is 4 strings of at most 16 characters.

    Page 0 is the link, the active temperature source, the control
    temperature, and the internal-minus-external pressure delta.
    Page 1 is one fan per line: role (I intake, E exhaust), RPM, duty.
    Pages 2 and 3 are the internal and external BMP280.
    """
    status = status or {}
    wifi = status.get("wifi") or ""
    ip = status.get("ip") or ""
    if wifi == "connected" and ip:
        line_ip = ip
    elif wifi:
        line_ip = "wifi " + str(wifi)
    else:
        line_ip = "no wifi"
    source = status.get("temp_source") or "die"
    if source == "internal":
        line_src = "src internal"
    else:
        line_src = "src die"
    summary = (
        fit(line_ip),
        fit(line_src),
        fit(_temp_text(status.get("control_c"))),
        fit(_delta_text(status.get("pressure_delta_pa"), status)),
    )
    fans = list(status.get("fans") or [])
    fan_lines = []
    for index in range(4):
        if index < len(fans):
            fan_lines.append(fit(_fan_line(fans[index])))
        else:
            fan_lines.append("")
    sensors = status.get("sensors") or {}
    internal = _sensor_page("Internal BMP280", sensors.get("internal"))
    external = _sensor_page("External BMP280", sensors.get("external"))
    pages = [
        summary,
        tuple(fan_lines),
        tuple(fit(line) for line in internal),
        tuple(fit(line) for line in external),
    ]
    fault_page = _fault_page(status.get("faults"))
    if fault_page is not None:
        pages.append(fault_page)
    return tuple(pages)


def pixel_on(buffer, width, x, y):
    """Read one pixel from an SSD1306 page buffer (vertical LSB)."""
    if x < 0 or y < 0:
        return 0
    page = y >> 3
    index = page * width + x
    if index < 0 or index >= len(buffer):
        return 0
    return 1 if buffer[index] & (1 << (y & 7)) else 0


def blit_text(buffer, width, lines):
    """Clear ``buffer`` and draw up to 4 lines of 16 characters.

    ``buffer`` is the SSD1306 layout: page-major, 8 vertical pixels per byte,
    least-significant bit at the top of the page.
    """
    for i in range(len(buffer)):
        buffer[i] = 0
    if width <= 0:
        return
    for row, line in enumerate(lines):
        if row >= ROWS:
            break
        y0 = row * 8
        col = 0
        for ch in line:
            if col >= COLS:
                break
            if "a" <= ch <= "z":
                ch = chr(ord(ch) - 32)
            glyph = FONT.get(ch, FONT["?"])
            x0 = col * 8
            for gy in range(8):
                bits = glyph[gy]
                if not bits:
                    continue
                y = y0 + gy
                page = y >> 3
                mask = 1 << (y & 7)
                base = page * width
                for gx in range(8):
                    if bits & (0x80 >> gx):
                        x = x0 + gx
                        if x < width:
                            buffer[base + x] |= mask
            col += 1


class OledDisplay:
    """Page rotator over an SSD1306 panel.

    ``panel`` is None when the display was enabled but could not be opened.
    ``update`` never raises.
    """

    def __init__(self, panel, page_s=3, enabled=True, error=""):
        self.panel = panel
        self.page_ms = int(page_s * 1000) if page_s and page_s > 0 else 3000
        self.enabled = bool(enabled)
        self.ok = panel is not None and not error
        self.error = error or ""
        self.page_index = 0
        self.last_lines = ("", "", "", "")
        self._last_rotate = None
        self._logged = error or ""

    def status(self):
        return {
            "enabled": self.enabled,
            "ok": bool(self.ok),
            "error": self.error or "",
        }

    def update(self, status, now_ms):
        if self.panel is None:
            self.ok = False
            return self.status()
        try:
            pages = build_pages(status)
            if self._last_rotate is None:
                self.page_index = 0
                self._last_rotate = now_ms
            elif ticks_diff(now_ms, self._last_rotate) >= self.page_ms:
                self.page_index = (self.page_index + 1) % len(pages)
                self._last_rotate = now_ms
            lines = pages[self.page_index]
            self.last_lines = lines
            blit_text(self.panel.buffer, self.panel.width, lines)
            self.panel.show()
        except Exception as exc:
            self.ok = False
            self.error = "update failed: {}".format(exc)
            self._log(self.error)
            return self.status()
        if not self.ok or self.error:
            self._log("update ok")
        self.ok = True
        self.error = ""
        return self.status()

    def _log(self, message):
        if message == self._logged:
            return
        self._logged = message
        print("oled: {}".format(message))


def build_oled(settings, pool):
    """Return an OledDisplay, or None when the OLED is disabled.

    Failures are returned as an enabled display with ``ok`` false so the
    web page can show the error. This never raises.
    """
    if not settings.get("oled_enabled"):
        return None
    try:
        bus = pool.get(settings["oled_i2c_id"], settings["oled_sda"], settings["oled_scl"])
    except Exception as exc:
        message = "i2c open failed: {}".format(exc)
        print("oled: {}".format(message))
        return OledDisplay(None, page_s=settings.get("oled_page_s") or 3, enabled=True, error=message)
    try:
        panel = ssd1306.SSD1306_I2C(
            int(settings["oled_width"]),
            int(settings["oled_height"]),
            bus,
            addr=int(settings["oled_addr"]),
        )
    except Exception as exc:
        message = "init failed: {}".format(exc)
        print("oled: {}".format(message))
        return OledDisplay(None, page_s=settings.get("oled_page_s") or 3, enabled=True, error=message)
    print(
        "oled: ready {}x{} addr=0x{:02X} I2C{} SDA=GP{} SCL=GP{}".format(
            panel.width,
            panel.height,
            int(settings["oled_addr"]),
            settings["oled_i2c_id"],
            settings["oled_sda"],
            settings["oled_scl"],
        )
    )
    return OledDisplay(panel, page_s=settings.get("oled_page_s") or 3, enabled=True)
