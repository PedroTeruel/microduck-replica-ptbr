"""PC probe unit tests; no pyserial, serial port, or hardware required."""
import importlib.util
from pathlib import Path
import struct
import unittest
ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("imu_probe", ROOT / "Tools/imu_probe.py")
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


def ft_status(device_id, data: bytes, error: int = 0) -> bytes:
    """Build a Feetech status frame: FF FF ID LEN ERR DATA CK."""
    length = len(data) + 2
    body = bytes([device_id, length, error]) + data
    return b"\xff\xff" + body + bytes([probe.checksum(body)])


class ProbeTests(unittest.TestCase):
    def test_ping_checksum_vector(self):
        # PING to ID 200, no parameters: LEN=2, CK = ~(200+2+1) = 0x34
        self.assertEqual(probe.packet(200, 0x01),
                         bytes.fromhex("ff ff c8 02 01 34"))
        # Expected status: FF FF C8 02 00 35 (CK = ~(200+2+0)).
        self.assertEqual(ft_status(200, b""),
                         bytes.fromhex("ff ff c8 02 00 35"))

    def test_read_frame(self):
        # READ addr 56, count 12 -> LEN = 4, CK = ~(200+4+2+56+12)
        frame = probe.packet(200, 0x02, bytes([56, 12]))
        self.assertEqual(frame, bytes.fromhex("ff ff c8 04 02 38 0c ed"))
        self.assertEqual(len(frame), 4 + frame[3])

    def test_status_length_and_checksum(self):
        frame = ft_status(200, bytes(range(12)))
        self.assertEqual(frame[3], 14)          # data + ERR + CK
        self.assertEqual(len(frame), 18)
        self.assertEqual(probe.checksum(frame[2:-1]), frame[-1])

    def test_sync_read_alone_frame(self):
        frame = probe.packet(254, 0x82, bytes([56, 12, 200]))
        self.assertEqual(frame[:5], bytes.fromhex("ff ff fe 05 82"))
        self.assertEqual(probe.checksum(frame[2:-1]), frame[-1])

    def test_decode_fast_block(self):
        block = bytearray(40)
        struct.pack_into("<3h", block, 0, -32768, 0, 32767)
        struct.pack_into("<3e", block, 6, .5, -.5, 0.0)
        block[12] = 7            # sample counter (byte 12)
        block[13] = 0            # status bits: ready, no error
        block[21] = 0x70         # who-am-I (LSM6DSV16X)
        struct.pack_into("<I", block, 25, 0x01020304)  # sample_count u32
        block[29] = 0x5A         # user marker
        diag = bytearray(96)
        struct.pack_into("<24I", diag, 0, *range(24))
        decoded = probe.decode(bytes(block), bytes(diag))
        self.assertTrue(decoded["ready"])
        self.assertAlmostEqual(decoded["gyro_x_dps"], -573.44)
        self.assertAlmostEqual(decoded["gyro_z_dps"], 573.4225)
        self.assertAlmostEqual(decoded["q_w"], 2 ** -.5)
        self.assertEqual(decoded["sample_count"], 0x01020304)
        self.assertEqual(decoded["who_am_i"], 0x70)
        self.assertEqual(decoded["user_marker"], 0x5A)
        self.assertEqual(decoded["counter"], 7)
        self.assertEqual(decoded["gyro_count"], 0)
        self.assertEqual(decoded["clock_hz"], 18)
        self.assertEqual(decoded["tx_busy_drops"], 22)
        self.assertEqual(decoded["reserved"], 23)

    def test_not_ready_bit(self):
        block = bytearray(40)
        struct.pack_into("<3e", block, 6, .1, .2, .3)  # valid quat
        block[13] = 0x01         # BIT0: fusion not ready
        self.assertFalse(probe.decode(bytes(block), bytes(96))["ready"])

    def test_invalid_quaternion(self):
        block = bytearray(40)
        struct.pack_into("<e", block, 6, float("nan"))
        decoded = probe.decode(bytes(block), bytes(96))
        self.assertFalse(decoded["ready"])
        self.assertNotEqual(decoded["q_w"], decoded["q_w"])  # NaN

    def test_oversize_quaternion_norm(self):
        block = bytearray(40)
        struct.pack_into("<3e", block, 6, .9, .9, .9)  # norm2 = 2.43
        decoded = probe.decode(bytes(block), bytes(96))
        self.assertFalse(decoded["ready"])

    def test_decode_length_guards(self):
        with self.assertRaises(ValueError):
            probe.decode(bytes(39), bytes(96))
        with self.assertRaises(ValueError):
            probe.decode(bytes(40), bytes(95))


if __name__ == "__main__":
    unittest.main()
