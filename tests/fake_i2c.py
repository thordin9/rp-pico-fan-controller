"""In-memory I2C bus for host tests. No hardware."""


class FakeI2C:
    def __init__(self):
        self.mem = {}
        self.fail = set()
        self.cmds = []
        self.frames = []
        self.writes = []
        self.reads = 0

    def add(self, addr):
        self.mem[addr] = bytearray(256)
        return self.mem[addr]

    def readfrom_mem(self, addr, reg, nbytes):
        self.reads += 1
        if addr in self.fail or addr not in self.mem:
            raise OSError(5)
        return bytes(self.mem[addr][reg : reg + nbytes])

    def writeto(self, addr, buf):
        data = bytes(buf)
        self.writes.append((addr, data))
        if data[:1] == b"\x80" and len(data) >= 2:
            self.cmds.append((addr, data[1]))
            return len(data)
        if data[:1] == b"\x40":
            self.frames.append((addr, data[1:]))
            return len(data)
        if addr in self.fail or addr not in self.mem:
            raise OSError(5)
        if len(data) >= 2:
            reg = data[0]
            payload = data[1:]
            mem = self.mem[addr]
            end = min(len(mem), reg + len(payload))
            mem[reg:end] = payload[: end - reg]
        return len(data)

    def writevto(self, addr, bufs):
        return self.writeto(addr, b"".join(bytes(part) for part in bufs))

    def scan(self):
        return sorted(self.mem)


def pack_calib(calib):
    """Little-endian calib block. T1/P1 unsigned, the rest signed."""
    out = bytearray(24)
    unsigned = {0, 3}

    def put(index, value):
        if index not in unsigned and value < 0:
            value += 0x10000
        off = index * 2
        out[off] = value & 0xFF
        out[off + 1] = (value >> 8) & 0xFF

    for index, value in enumerate(calib):
        put(index, value)
    return out


def pack_sample(adc_p, adc_t):
    def pack(adc):
        return bytes(
            (
                (adc >> 12) & 0xFF,
                (adc >> 4) & 0xFF,
                (adc & 0x0F) << 4,
            )
        )

    return pack(adc_p) + pack(adc_t)


REF_CALIB = (
    27504,
    26435,
    -1000,
    36477,
    -10685,
    3024,
    2855,
    140,
    -7,
    15500,
    -14600,
    6000,
)


def plant_bmp280(i2c, addr, adc_t=519888, adc_p=415148, chip=0x58, calib=REF_CALIB):
    mem = i2c.add(addr)
    mem[0xD0] = chip
    mem[0x88 : 0x88 + 24] = pack_calib(calib)
    mem[0xF7 : 0xF7 + 6] = pack_sample(adc_p, adc_t)
    return mem
