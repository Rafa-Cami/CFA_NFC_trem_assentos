# Minimal PN532 NFC/RFID control library for this ESP32-C3 I2C project.
#
# Based on the Adafruit PN532 library.
# Copyright (c) 2015-2018 Adafruit Industries.
# SPDX-License-Identifier: MIT

from micropython import const


_PREAMBLE = const(0x00)
_STARTCODE1 = const(0x00)
_STARTCODE2 = const(0xFF)
_POSTAMBLE = const(0x00)

_HOSTTOPN532 = const(0xD4)
_PN532TOHOST = const(0xD5)

_COMMAND_GETFIRMWAREVERSION = const(0x02)
_COMMAND_SAMCONFIGURATION = const(0x14)
_COMMAND_INLISTPASSIVETARGET = const(0x4A)

_MIFARE_ISO14443A = const(0x00)

_ACK = b"\x00\x00\xFF\x00\xFF\x00"


class BusyError(Exception):
    pass


class PN532:
    """PN532 command layer. Transport-specific subclasses implement I2C I/O."""

    def __init__(self, *, debug=False):
        self.debug = debug

        try:
            self._wakeup()
            self.get_firmware_version()
            return
        except (BusyError, RuntimeError):
            pass

        self.get_firmware_version()

    def _read_data(self, count):
        raise NotImplementedError

    def _write_data(self, framebytes):
        raise NotImplementedError

    def _wait_ready(self, timeout):
        raise NotImplementedError

    def _wakeup(self):
        raise NotImplementedError

    def _write_frame(self, data):
        assert data is not None and 1 < len(data) < 255

        length = len(data)
        frame = bytearray(length + 8)
        frame[0] = _PREAMBLE
        frame[1] = _STARTCODE1
        frame[2] = _STARTCODE2
        checksum = sum(frame[0:3])
        frame[3] = length & 0xFF
        frame[4] = (~length + 1) & 0xFF
        frame[5:-2] = data
        checksum += sum(data)
        frame[-2] = ~checksum & 0xFF
        frame[-1] = _POSTAMBLE

        if self.debug:
            print("Write frame:", [hex(i) for i in frame])
        self._write_data(bytes(frame))

    def _read_frame(self, length):
        response = self._read_data(length + 8)
        if self.debug:
            print("Read frame:", [hex(i) for i in response])

        offset = 0
        while response[offset] == 0x00:
            offset += 1
            if offset >= len(response):
                raise RuntimeError("Response frame preamble does not contain 0x00FF")
        if response[offset] != 0xFF:
            raise RuntimeError("Response frame preamble does not contain 0x00FF")

        offset += 1
        if offset >= len(response):
            raise RuntimeError("Response contains no data")

        frame_len = response[offset]
        if (frame_len + response[offset + 1]) & 0xFF != 0:
            raise RuntimeError("Response length checksum did not match length")

        checksum = sum(response[offset + 2 : offset + 2 + frame_len + 1]) & 0xFF
        if checksum != 0:
            raise RuntimeError("Response checksum did not match expected value")

        return response[offset + 2 : offset + 2 + frame_len]

    def call_function(self, command, response_length=0, params=None, timeout=1):
        if params is None:
            params = []

        data = bytearray(2 + len(params))
        data[0] = _HOSTTOPN532
        data[1] = command & 0xFF
        for index, value in enumerate(params):
            data[2 + index] = value

        try:
            self._write_frame(data)
        except OSError:
            self._wakeup()
            if self.debug:
                print("call_function OSError")
            return None

        if not self._wait_ready(timeout):
            if self.debug:
                print("call_function timeout waiting for ACK")
            return None

        if self._read_data(len(_ACK)) != _ACK:
            raise RuntimeError("Did not receive expected ACK from PN532")

        if not self._wait_ready(timeout):
            if self.debug:
                print("call_function timeout waiting for response")
            return None

        response = self._read_frame(response_length + 2)
        if not (response[0] == _PN532TOHOST and response[1] == command + 1):
            raise RuntimeError("Received unexpected command response")

        return response[2:]

    def get_firmware_version(self):
        if self.debug:
            print("Get firmware version")

        response = self.call_function(_COMMAND_GETFIRMWAREVERSION, 4, timeout=0.5)
        if response is None:
            raise RuntimeError("Failed to detect the PN532")

        if self.debug:
            print("Get firmware version response:", tuple(response))
        return tuple(response)

    def SAM_configuration(self):
        self.call_function(_COMMAND_SAMCONFIGURATION, params=[0x01, 0x14, 0x01])

    def read_passive_target(self, card_baud=_MIFARE_ISO14443A, timeout=1):
        try:
            response = self.call_function(
                _COMMAND_INLISTPASSIVETARGET,
                params=[0x01, card_baud],
                response_length=19,
                timeout=timeout,
            )
        except BusyError:
            return None

        if response is None:
            return None

        if response[0] != 0x01:
            raise RuntimeError("More than one card detected")
        if response[5] > 7:
            raise RuntimeError("Found card with unexpectedly long UID")

        return response[6 : 6 + response[5]]
