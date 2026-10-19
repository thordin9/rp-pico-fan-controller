# SSD1306 OLED driver, I2C only.
#
# Init sequence and I2C framing (control byte 0x80 for a command, 0x40 for
# display data) are adapted from micropython-lib
# micropython/drivers/display/ssd1306/ssd1306.py
# Copyright (c) 2013, 2014 micropython-lib contributors
# SPDX-License-Identifier: MIT
#
# The SPI class and the framebuf base class are not included. The Waveshare
# 0.91 inch module is I2C only (VCC, GND, SDA, SCL), and text is drawn into
# the buffer by display.py so this module imports on CPython as well as
# MicroPython. The 128x32 panel uses the first half of the SSD1306's 128x64
# RAM: height 32 selects multiplex 31 and COM pin config 0x02.

SET_CONTRAST = 0x81
SET_ENTIRE_ON = 0xA4
SET_NORM_INV = 0xA6
SET_DISP = 0xAE
SET_MEM_ADDR = 0x20
SET_COL_ADDR = 0x21
SET_PAGE_ADDR = 0x22
SET_DISP_START_LINE = 0x40
SET_SEG_REMAP = 0xA0
SET_MUX_RATIO = 0xA8
SET_IREF_SELECT = 0xAD
SET_COM_OUT_DIR = 0xC0
SET_DISP_OFFSET = 0xD3
SET_COM_PIN_CFG = 0xDA
SET_DISP_CLK_DIV = 0xD5
SET_PRECHARGE = 0xD9
SET_VCOM_DESEL = 0xDB
SET_CHARGE_PUMP = 0x8D


class SSD1306_I2C:
    def __init__(self, width, height, i2c, addr=0x3C, external_vcc=False):
        self.width = width
        self.height = height
        self.i2c = i2c
        self.addr = addr
        self.external_vcc = external_vcc
        self.pages = height // 8
        self.buffer = bytearray(self.pages * width)
        # 0x40 plus the framebuffer, reused so show() does not allocate.
        self._payload = bytearray(1 + len(self.buffer))
        self._payload[0] = 0x40
        self._cmd = bytearray(2)
        self.init_display()

    def init_display(self):
        for cmd in (
            SET_DISP,  # display off
            SET_MEM_ADDR,
            0x00,  # horizontal addressing
            SET_DISP_START_LINE,
            SET_SEG_REMAP | 0x01,  # column 127 mapped to SEG0
            SET_MUX_RATIO,
            self.height - 1,
            SET_COM_OUT_DIR | 0x08,  # scan from COM[N] to COM0
            SET_DISP_OFFSET,
            0x00,
            SET_COM_PIN_CFG,
            0x02 if self.width > 2 * self.height else 0x12,
            SET_DISP_CLK_DIV,
            0x80,
            SET_PRECHARGE,
            0x22 if self.external_vcc else 0xF1,
            SET_VCOM_DESEL,
            0x30,  # 0.83 * Vcc
            SET_CONTRAST,
            0xFF,
            SET_ENTIRE_ON,  # RAM contents, not a forced-on panel
            SET_NORM_INV,
            SET_IREF_SELECT,
            0x30,  # internal IREF
            SET_CHARGE_PUMP,
            0x10 if self.external_vcc else 0x14,
            SET_DISP | 0x01,  # display on
        ):
            self.write_cmd(cmd)
        self.fill(0)
        self.show()

    def fill(self, color):
        value = 0xFF if color else 0x00
        buf = self.buffer
        for i in range(len(buf)):
            buf[i] = value

    def write_cmd(self, cmd):
        self._cmd[0] = 0x80  # Co=1, D/C#=0
        self._cmd[1] = cmd
        self.i2c.writeto(self.addr, self._cmd)

    def show(self):
        x0 = 0
        x1 = self.width - 1
        if self.width != 128:
            col_offset = (128 - self.width) // 2
            x0 += col_offset
            x1 += col_offset
        self.write_cmd(SET_COL_ADDR)
        self.write_cmd(x0)
        self.write_cmd(x1)
        self.write_cmd(SET_PAGE_ADDR)
        self.write_cmd(0)
        self.write_cmd(self.pages - 1)
        payload = self._payload
        buf = self.buffer
        # Copy into the preallocated frame. Slice assign stays in this buffer.
        payload[1 : 1 + len(buf)] = buf
        writevto = getattr(self.i2c, "writevto", None)
        if writevto is not None:
            writevto(self.addr, (b"\x40", buf))
            return
        self.i2c.writeto(self.addr, payload)

    def poweroff(self):
        self.write_cmd(SET_DISP)

    def poweron(self):
        self.write_cmd(SET_DISP | 0x01)
