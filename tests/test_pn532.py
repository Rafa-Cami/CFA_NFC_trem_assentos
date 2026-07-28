import asyncio
import binascii
import importlib.util
import sys
import time
import types
import unittest
from pathlib import Path
from unittest import mock


NFC_SOURCE = Path(__file__).resolve().parents[1] / "ESP_NFC" / "src"
sys.path.insert(0, str(NFC_SOURCE))


def load_firmware_module():
    machine = types.ModuleType("machine")
    network = types.ModuleType("network")
    micropython = types.ModuleType("micropython")
    micropython.const = lambda value: value
    with mock.patch.object(time, "ticks_ms", return_value=0, create=True), (
        mock.patch.dict(
            sys.modules,
            {
                "machine": machine,
                "network": network,
                "micropython": micropython,
                "uasyncio": asyncio,
                "ubinascii": binascii,
            },
        )
    ):
        spec = importlib.util.spec_from_file_location(
            "esp_comunicando_under_test",
            NFC_SOURCE / "esp_comunicando.py",
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module


firmware = load_firmware_module()


class Pn532BehaviorTests(unittest.TestCase):
    def test_constructor_does_not_read_firmware_twice(self):
        class FakeReader(firmware.PN532):
            def _wakeup(self):
                self.woke = True

            def get_firmware_version(self):
                raise AssertionError("constructor must not query firmware")

        reader = FakeReader()
        self.assertTrue(reader.woke)

    def test_search_timeout_is_normal_absence(self):
        reader = object.__new__(firmware.PN532)

        def timeout(*args, **kwargs):
            raise firmware.PN532ResponseTimeout("no target")

        reader.call_function = timeout
        uid, outcome = reader.read_passive_target()
        self.assertIsNone(uid)
        self.assertEqual(outcome, "search_timeout")

    def test_ack_and_response_timeouts_are_distinct(self):
        reader = object.__new__(firmware.PN532)
        reader._write_frame = lambda data: None
        reader.abort_pending = lambda: None
        reader._wait_ready = lambda timeout_ms: False
        with self.assertRaises(firmware.PN532AckTimeout):
            reader.call_function(1)

        readiness = iter((True, False))
        reader._wait_ready = lambda timeout_ms: next(readiness)
        reader._read_data = lambda count: firmware._ACK
        with self.assertRaises(firmware.PN532ResponseTimeout):
            reader.call_function(1)


if __name__ == "__main__":
    unittest.main()
