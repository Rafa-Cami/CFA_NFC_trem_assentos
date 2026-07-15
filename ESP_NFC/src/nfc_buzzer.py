# ESP32-C3 SuperMini + PN532 I2C + passive buzzer.
#
# Wiring:
# - PN532 SDA -> GPIO8
# - PN532 SCL -> GPIO9
# - buzzer +  -> GPIO4
# - buzzer -  -> GND

import machine
import time
from micropython import const


I2C_ID = 0
I2C_SDA_PIN = 8
I2C_SCL_PIN = 9
I2C_FREQ = 100000

PN532_I2C_ADDRESS = const(0x24)

BUZZER_PIN = 4
BUZZER_FREQ = 2200
BUZZER_DUTY_U16 = 49152

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
_I2C_READY = const(0x01)

_ACK = b"\x00\x00\xFF\x00\xFF\x00"
_READ_WARNING = const(-1)
_ERROR_BEEP_INTERVAL_MS = 1500


class BusyError(Exception):
    pass


class PN532FrameWarning(Exception):
    pass


class PN532:
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
            print("Write frame:", [hex(byte) for byte in frame])
        self._write_data(bytes(frame))

    def _read_frame(self, length):
        response = self._read_data(length + 8)
        if self.debug:
            print("Read frame:", [hex(byte) for byte in response])

        offset = 0
        while response[offset] == 0x00:
            offset += 1
            if offset >= len(response):
                raise PN532FrameWarning("Response frame preamble does not contain 0x00FF")

        if response[offset] != 0xFF:
            raise PN532FrameWarning("Response frame preamble does not contain 0x00FF")

        offset += 1
        if offset >= len(response):
            raise PN532FrameWarning("Response contains no data")

        frame_len = response[offset]
        if (frame_len + response[offset + 1]) & 0xFF != 0:
            raise PN532FrameWarning("Response length checksum did not match length")

        checksum = sum(response[offset + 2 : offset + 2 + frame_len + 1]) & 0xFF
        if checksum != 0:
            raise PN532FrameWarning("Response checksum did not match expected value")

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
        if response[0] != _PN532TOHOST or response[1] != command + 1:
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
        except PN532FrameWarning as warning:
            print("Warning:", warning)
            return _READ_WARNING

        if response is None:
            return None

        if response[0] != 0x01:
            raise RuntimeError("More than one card detected")
        if response[5] > 7:
            raise RuntimeError("Found card with unexpectedly long UID")

        return response[6 : 6 + response[5]]


class PN532_I2C(PN532):
    def __init__(self, i2c, *, debug=False):
        self._i2c = i2c
        super().__init__(debug=debug)

    def _wakeup(self):
        time.sleep(0.5)

    def _wait_ready(self, timeout=1):
        status = bytearray(1)
        started_at = time.time_ns() / 1000000000

        while (time.time_ns() / 1000000000) - started_at < timeout:
            try:
                self._i2c.readfrom_into(PN532_I2C_ADDRESS, status)
            except OSError:
                self._wakeup()
                continue

            if status[0] == _I2C_READY:
                return True

            time.sleep(0.05)

        return False

    def _read_data(self, count):
        frame = bytearray(count + 1)
        status = bytearray(1)

        self._i2c.readfrom_into(PN532_I2C_ADDRESS, status)
        if status[0] != _I2C_READY:
            raise BusyError

        self._i2c.readfrom_into(PN532_I2C_ADDRESS, frame)
        return frame[1:]

    def _write_data(self, framebytes):
        self._i2c.writeto(PN532_I2C_ADDRESS, framebytes)


def _set_pwm_duty(pwm, duty_u16):
    if hasattr(pwm, "duty_u16"):
        pwm.duty_u16(duty_u16)
    else:
        pwm.duty(int(duty_u16 * 1023 / 65535))


def beep(duration_ms=120, frequency=BUZZER_FREQ):
    buzzer = machine.PWM(machine.Pin(BUZZER_PIN, machine.Pin.OUT))
    buzzer.freq(frequency)
    _set_pwm_duty(buzzer, BUZZER_DUTY_U16)
    time.sleep_ms(duration_ms)
    _set_pwm_duty(buzzer, 0)
    buzzer.deinit()
    machine.Pin(BUZZER_PIN, machine.Pin.OUT).value(0)


def success_beep():
    beep(80, 1800)
    time.sleep_ms(60)
    beep(130, 2600)


def error_beep():
    beep(120, 500)
    time.sleep_ms(70)
    beep(170, 300)


def format_uid(uid):
    return ":".join("{:02x}".format(byte) for byte in uid)


def create_i2c():
    return machine.I2C(
        I2C_ID,
        scl=machine.Pin(I2C_SCL_PIN),
        sda=machine.Pin(I2C_SDA_PIN),
        freq=I2C_FREQ,
    )


def main():
    print("Starting NFC buzzer test")
    print("I2C: SDA=GPIO{}, SCL=GPIO{}".format(I2C_SDA_PIN, I2C_SCL_PIN))
    print("Buzzer: GPIO{}".format(BUZZER_PIN))

    i2c = create_i2c()
    devices = i2c.scan()
    print("I2C devices:", [hex(device) for device in devices])

    if PN532_I2C_ADDRESS not in devices:
        print("PN532 not found at 0x24. Check SDA/SCL, VCC, GND and I2C mode.")
        for _ in range(3):
            beep(70, 500)
            time.sleep_ms(80)
        return

    pn532 = PN532_I2C(i2c, debug=False)
    ic, ver, rev, support = pn532.get_firmware_version()
    print("Found PN532 firmware version: {}.{}".format(ver, rev))

    pn532.SAM_configuration()
    success_beep()

    print("Waiting for NFC card...")
    last_uid = None
    last_error_beep = 0

    while True:
        uid = pn532.read_passive_target(timeout=0.2)

        if uid == _READ_WARNING:
            now = time.ticks_ms()
            if time.ticks_diff(now, last_error_beep) >= _ERROR_BEEP_INTERVAL_MS:
                error_beep()
                last_error_beep = now
            time.sleep_ms(100)
            continue

        if uid is None:
            last_uid = None
            time.sleep_ms(100)
            continue

        if uid != last_uid:
            print("Found card UID:", format_uid(uid))
            success_beep()
            last_uid = uid

        time.sleep_ms(250)
