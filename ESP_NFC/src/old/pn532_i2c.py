# Minimal PN532 I2C transport for MicroPython.
#
# Based on the Adafruit PN532 I2C transport.
# Copyright (c) 2015-2018 Adafruit Industries.
# SPDX-License-Identifier: MIT

import time

from adafruit_pn532 import BusyError, PN532
from micropython import const


_I2C_ADDRESS = const(0x24)
_NOT_BUSY = const(0x01)


class PN532_I2C(PN532):
    """Driver for PN532 connected over I2C."""

    def __init__(self, i2c, *, debug=False):
        self.debug = debug
        self._i2c = i2c
        super().__init__(debug=debug)

    def _wakeup(self):
        time.sleep(0.5)

    def _wait_ready(self, timeout=1):
        status = bytearray(1)
        started_at = time.time_ns() / 1000000000

        while (time.time_ns() / 1000000000) - started_at < timeout:
            try:
                self._i2c.readfrom_into(_I2C_ADDRESS, status)
            except OSError:
                self._wakeup()
                continue

            if status[0] == _NOT_BUSY:
                return True

            time.sleep(0.05)

        return False

    def _read_data(self, count):
        frame = bytearray(count + 1)
        status = bytearray(1)

        self._i2c.readfrom_into(_I2C_ADDRESS, status)
        if status[0] != _NOT_BUSY:
            raise BusyError

        self._i2c.readfrom_into(_I2C_ADDRESS, frame)
        return frame[1:]

    def _write_data(self, framebytes):
        self._i2c.writeto(_I2C_ADDRESS, framebytes)
