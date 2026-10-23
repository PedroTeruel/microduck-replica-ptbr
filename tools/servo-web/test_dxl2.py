"""DXL2 wire vectors, parser recovery and shared-port timeout regression."""
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import dxl2
import feetech


class WireTests(unittest.TestCase):
    def test_robotis_instruction_vectors(self):
        self.assertEqual(dxl2.packet(1, dxl2.PING).hex(),
                         "fffffd0001030001194e")
        self.assertEqual(dxl2.packet(1, dxl2.READ, bytes.fromhex("84000400")).hex(),
                         "fffffd0001070002840004001d15")

    def test_fragmented_status_unstuffs_payload_at_every_split(self):
        payload = b"\x01\xff\xff\xfd\xfd\x02\xff\xff\xfd\x03"
        raw = dxl2.packet(200, 0x55, b"\x00" + payload)
        for split in range(len(raw) + 1):
            with self.subTest(split=split):
                parser = dxl2.StatusParser()
                frames = parser.feed(raw[:split]) + parser.feed(raw[split:])
                self.assertEqual(frames, [(200, 0, payload, raw)])

    def test_bad_crc_and_noise_do_not_hide_the_next_status(self):
        raw = dxl2.packet(200, 0x55, b"\x00\x01\x02\x03")
        corrupt = raw[:-1] + bytes([raw[-1] ^ 1])
        parser = dxl2.StatusParser()
        self.assertEqual(parser.feed(b"noise" + corrupt + raw),
                         [(200, 0, b"\x01\x02\x03", raw)])
        self.assertGreater(parser.bad, 0)


class TraceTests(unittest.TestCase):
    def setUp(self):
        class Serial:
            def __init__(self):
                self.rx = bytearray()
                self.error = 0
                self.respond = True

            @property
            def in_waiting(self):
                return len(self.rx)

            def reset_input_buffer(self):
                self.rx.clear()

            def write(self, data):
                if self.respond:
                    payload = b"\x01\x02\x03" if data[7] == dxl2.PING else bytes(12)
                    self.rx.extend(dxl2.packet(200, 0x55, bytes([self.error]) + payload))
                return len(data)

            def read(self, size):
                result = bytes(self.rx[:size])
                del self.rx[:size]
                return result

        self.serial = Serial()
        self.bus = feetech.FeetechBus(None, ser=self.serial)
        self.logs = []
        self.bus.trace = self.logs.append
        self.client = dxl2.Dxl2Bus(self.bus, timeout=0.01)

    def test_successful_polling_respects_shared_bus_trace_skip(self):
        for _ in range(50):
            self.assertEqual(self.client.sync_read([200], 124, 12), {200: (0, bytes(12))})
        self.assertEqual(self.logs, [])

    def test_polling_trace_can_be_explicitly_enabled(self):
        self.bus.trace_skip.clear()
        self.client.sync_read([200], 124, 12)
        self.assertEqual(len(self.logs), 2)
        self.assertTrue(self.logs[0].startswith("→ DXL2 "))
        self.assertTrue(self.logs[1].startswith("← DXL2 #200 "))

    def test_ping_and_manual_read_still_trace(self):
        self.assertEqual(self.client.ping(200), (0, b"\x01\x02\x03"))
        self.assertEqual(self.client.read(200, 124, 12), (0, bytes(12)))
        self.assertEqual(len(self.logs), 4)

    def test_bus_without_trace_skip_still_traces(self):
        del self.bus.trace_skip
        self.client.sync_read([200], 124, 12)
        self.assertEqual(len(self.logs), 2)

    def test_polling_status_error_still_traces(self):
        self.serial.error = 4
        self.assertEqual(self.client.sync_read([200], 124, 12), {200: (4, bytes(12))})
        self.assertTrue(any("status_error=0x04" in line for line in self.logs))

    def test_polling_timeout_still_traces(self):
        self.serial.respond = False
        self.assertEqual(self.client.sync_read([200], 124, 12), {})
        self.assertIn("← DXL2 无有效状态包", self.logs)

    def test_partial_polling_response_still_traces(self):
        self.assertEqual(self.client.sync_read([200, 201], 124, 12), {200: (0, bytes(12))})
        self.assertEqual(len(self.logs), 2)


class TimeoutTests(unittest.TestCase):
    def ping_after_delays(self, lock_wait=0.0, write_delay=0.0):
        clock = SimpleNamespace(now=0.0)

        class Lock:
            def __enter__(self):
                clock.now += lock_wait

            def __exit__(self, *args):
                pass

        class Serial:
            def __init__(self):
                self.rx = bytearray()
                self.reads = 0

            @property
            def in_waiting(self):
                return len(self.rx)

            def reset_input_buffer(self):
                self.rx.clear()

            def write(self, data):
                clock.now += write_delay
                self.rx.extend(dxl2.packet(200, 0x55, b"\x00\x01\x02\x03"))
                return len(data)

            def read(self, size):
                self.reads += 1
                result = bytes(self.rx[:size])
                del self.rx[:size]
                return result

        serial = Serial()
        bus = SimpleNamespace(ser=serial, _io=Lock(), trace=None)
        with patch.object(dxl2.time, "monotonic", side_effect=lambda: clock.now):
            result = dxl2.Dxl2Bus(bus, timeout=0.06).ping(200)
        self.assertEqual(result, (0, b"\x01\x02\x03"))
        self.assertGreater(serial.reads, 0)

    def test_response_timeout_excludes_waiting_for_the_serial_lock(self):
        self.ping_after_delays(lock_wait=0.09)

    def test_response_timeout_starts_after_the_serial_write_completes(self):
        self.ping_after_delays(write_delay=0.09)


if __name__ == "__main__":
    unittest.main()
