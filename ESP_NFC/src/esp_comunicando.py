# ESP32-C3 SuperMini + PN532 I2C + TCP/IP communication.
#
# Wiring:
# - PN532 SDA -> GPIO8
# - PN532 SCL -> GPIO9
# - buzzer +  -> GPIO4
# - buzzer -  -> GND

import json
import machine
import network
import socket
import time
from micropython import const

try:
    from esp_config import HOST, PASSWORD, SSID
except ImportError:
    raise RuntimeError(
        "Missing esp_config.py. Copy esp_config.example.py and configure Wi-Fi/PC."
    )


# ==========================
# Wi-Fi / PC configuration
# ==========================

# Port used by servidor/src/pc_server.py
PORT = 5000


# ==========================
# NFC configuration
# ==========================

I2C_ID = 0
I2C_SDA_PIN = 8
I2C_SCL_PIN = 9
I2C_FREQ = 100000

PN532_I2C_ADDRESS = const(0x24)

BUZZER_PIN = 4
BUZZER_FREQ = 2200
BUZZER_DUTY_U16 = 49152

# Coloque aqui os UUIDs/UIDs autorizados, no mesmo formato impresso no terminal.
# O primeiro UID da lista envia {"nfc_1": 1}, o segundo envia {"nfc_2": 1}, etc.
NFC_UUIDS = [
    "d3:8e:18:06",
]

READ_COOLDOWN_MS = 1500

_PREAMBLE = const(0x00)
_STARTCODE1 = const(0x00)
_STARTCODE2 = const(0xFF)
_POSTAMBLE = const(0x00)

_HOSTTOPN532 = const(0xD4)
_PN532TOHOST = const(0xD5)

_COMMAND_GETFIRMWAREVERSION = const(0x02)
_COMMAND_SAMCONFIGURATION = const(0x14)
_COMMAND_RFCONFIGURATION = const(0x32)
_COMMAND_INLISTPASSIVETARGET = const(0x4A)

_MIFARE_ISO14443A = const(0x00)
_I2C_READY = const(0x01)

_ACK = b"\x00\x00\xFF\x00\xFF\x00"
PN532_ACK_TIMEOUT_MS = 30
PN532_SEARCH_TIMEOUT_MS = 180
POLL_INTERVAL_MS = 50
CONSECUTIVE_READER_ERRORS = 5
CARD_ABSENCE_POLLS = 2
HEARTBEAT_INTERVAL_MS = 2000


class BusyError(Exception):
    pass


class PN532FrameWarning(Exception):
    pass


class PN532ResponseTimeout(RuntimeError):
    pass


class PN532AckTimeout(PN532ResponseTimeout):
    pass


class PN532:
    def __init__(self, *, debug=False):
        self.debug = debug
        self._wakeup()

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

    def call_function(
        self,
        command,
        response_length=0,
        params=None,
        ack_timeout_ms=PN532_ACK_TIMEOUT_MS,
        response_timeout_ms=500,
    ):
        if params is None:
            params = []

        data = bytearray(2 + len(params))
        data[0] = _HOSTTOPN532
        data[1] = command & 0xFF
        for index, value in enumerate(params):
            data[2 + index] = value

        self._write_frame(data)
        if not self._wait_ready(ack_timeout_ms):
            raise PN532AckTimeout("timeout waiting for ACK")

        if self._read_data(len(_ACK)) != _ACK:
            raise RuntimeError("Did not receive expected ACK from PN532")

        if not self._wait_ready(response_timeout_ms):
            raise PN532ResponseTimeout("timeout waiting for response")

        response = self._read_frame(response_length + 2)
        if (
            len(response) < 2
            or response[0] != _PN532TOHOST
            or response[1] != command + 1
        ):
            raise RuntimeError("Received unexpected command response")

        return response[2:]

    def get_firmware_version(self):
        if self.debug:
            print("Get firmware version")

        response = self.call_function(
            _COMMAND_GETFIRMWAREVERSION,
            4,
            response_timeout_ms=500,
        )

        if self.debug:
            print("Get firmware version response:", tuple(response))
        return tuple(response)

    def SAM_configuration(self):
        self.call_function(
            _COMMAND_SAMCONFIGURATION,
            params=[0x01, 0x14, 0x01],
            response_timeout_ms=500,
        )
        # Use one passive activation attempt per poll. This prevents an old
        # search response from being consumed by the following command.
        self.call_function(
            _COMMAND_RFCONFIGURATION,
            params=[0x05, 0xFF, 0x01, 0x00],
            response_timeout_ms=500,
        )

    def read_passive_target(self, card_baud=_MIFARE_ISO14443A):
        try:
            response = self.call_function(
                _COMMAND_INLISTPASSIVETARGET,
                params=[0x01, card_baud],
                response_length=19,
                response_timeout_ms=PN532_SEARCH_TIMEOUT_MS,
            )
        except PN532ResponseTimeout as error:
            if isinstance(error, PN532AckTimeout):
                raise
            return None

        if not response or response[0] == 0:
            return None

        if response[0] != 1 or len(response) < 6:
            raise RuntimeError("Invalid PN532 target response")

        uid_length = response[5]
        if uid_length > 7 or len(response) < 6 + uid_length:
            raise RuntimeError("Found card with unexpectedly long UID")

        return response[6 : 6 + uid_length]


class PN532_I2C(PN532):
    def __init__(self, i2c, *, debug=False):
        self._i2c = i2c
        super().__init__(debug=debug)

    def _wakeup(self):
        time.sleep(0.5)

    def _wait_ready(self, timeout_ms):
        status = bytearray(1)
        started_at = time.ticks_ms()

        while time.ticks_diff(time.ticks_ms(), started_at) < timeout_ms:
            try:
                self._i2c.readfrom_into(PN532_I2C_ADDRESS, status)
            except OSError:
                continue

            if status[0] == _I2C_READY:
                return True

            time.sleep_ms(5)

        return False

    def _read_data(self, count):
        # The PN532 I2C protocol requires a status-byte read before the frame
        # read. Keeping these as separate I2C transactions is important: a
        # single combined read can work once and leave subsequent responses
        # out of sync.
        status = bytearray(1)
        self._i2c.readfrom_into(PN532_I2C_ADDRESS, status)
        if status[0] != _I2C_READY:
            raise BusyError("PN532 not ready")

        frame = bytearray(count + 1)
        self._i2c.readfrom_into(PN532_I2C_ADDRESS, frame)
        if frame[0] != _I2C_READY:
            raise BusyError("PN532 not ready")
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


def invalid_card_beep():
    beep(90, 750)
    time.sleep_ms(55)
    beep(110, 480)
    time.sleep_ms(55)
    beep(170, 280)


def format_uid(uid):
    return ":".join("{:02x}".format(byte) for byte in uid)


def create_i2c():
    return machine.I2C(
        I2C_ID,
        scl=machine.Pin(I2C_SCL_PIN),
        sda=machine.Pin(I2C_SDA_PIN),
        freq=I2C_FREQ,
    )


def connect_wifi():
    wifi = network.WLAN(network.STA_IF)
    wifi.active(True)

    if not wifi.isconnected():
        print("Connecting to Wi-Fi...")
        wifi.connect(SSID, PASSWORD)

        while not wifi.isconnected():
            time.sleep(1)

    print("Connected to Wi-Fi")
    print("ESP32 IP:", wifi.ifconfig()[0])
    return wifi


def connect_pc(reader_ready):
    print("Connecting to PC {}:{}...".format(HOST, PORT))
    connection = None
    response_file = None
    try:
        connection = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        connection.settimeout(5)
        try:
            connection.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        except (AttributeError, OSError):
            pass
        connection.connect((HOST, PORT))
        response_file = connection.makefile("r")
        connection.send(
            (
                json.dumps(
                    {
                        "type": "nfc_register",
                        "device_id": "nfc_reader",
                        "reader_ready": reader_ready,
                    }
                )
                + "\n"
            ).encode()
        )
        line = response_file.readline()
        if not line:
            raise RuntimeError("PC disconnected during NFC registration")
        response = json.loads(line)
        if response.get("type") != "nfc_register_ack":
            raise RuntimeError("Invalid NFC registration response")
        print("Connected to PC as nfc_reader")
        return connection, response_file
    except Exception:
        close_connection(connection, response_file)
        raise


def send_nfc_message(
    connection,
    response_file,
    uid_text,
    allowed_uids,
    event_id,
):
    index = allowed_uids.index(uid_text)
    message = {
        "type": "nfc_presented",
        "event_id": event_id,
        "card_index": index + 1,
    }
    connection.send((json.dumps(message) + "\n").encode())
    print("Sent:", message)

    response = response_file.readline()
    if not response:
        raise RuntimeError("PC disconnected after NFC message")

    response = json.loads(response)
    if (
        response.get("type") != "nfc_result"
        or response.get("event_id") != event_id
    ):
        raise RuntimeError("Invalid NFC result response")
    print("PC response:", response)
    return response


def send_heartbeat(
    connection,
    response_file,
    ping_id,
    reader_ready,
):
    message = {
        "type": "ping",
        "ping_id": ping_id,
        "reader_ready": reader_ready,
    }
    connection.send((json.dumps(message) + "\n").encode())
    response = response_file.readline()
    if not response:
        raise RuntimeError("PC disconnected during heartbeat")
    response = json.loads(response)
    if (
        response.get("type") != "pong"
        or response.get("ping_id") != ping_id
    ):
        raise RuntimeError("Invalid heartbeat response")


def initialize_reader():
    i2c = create_i2c()
    print("Initializing PN532 directly at 0x24")
    pn532 = PN532_I2C(i2c, debug=False)
    ic, ver, rev, support = pn532.get_firmware_version()
    print("Found PN532 firmware version: {}.{}".format(ver, rev))
    pn532.SAM_configuration()
    return pn532


def close_connection(connection, response_file):
    if response_file is not None:
        try:
            response_file.close()
        except Exception:
            pass
    if connection is not None:
        try:
            connection.close()
        except Exception:
            pass


def main():
    print("Starting NFC + TCP/IP")
    print("I2C: SDA=GPIO{}, SCL=GPIO{}".format(I2C_SDA_PIN, I2C_SCL_PIN))
    print("Buzzer: GPIO{}".format(BUZZER_PIN))

    allowed_uids = [uid.lower() for uid in NFC_UUIDS]
    wifi = connect_wifi()

    pn532 = None
    try:
        pn532 = initialize_reader()
        success_beep()
    except Exception as error:
        print("PN532 initialization deferred:", error)

    connection = None
    response_file = None
    last_uid = None
    last_sent_at = 0
    absent_polls = CARD_ABSENCE_POLLS
    consecutive_reader_errors = 0
    last_heartbeat_at = 0
    ping_id = 0
    event_id = 0

    print("Waiting for NFC card...")

    while True:
        if connection is None:
            try:
                if not wifi.isconnected():
                    wifi = connect_wifi()
                connection, response_file = connect_pc(pn532 is not None)
                last_heartbeat_at = time.ticks_ms()
            except Exception as error:
                print("PC connection error:", error)
                close_connection(connection, response_file)
                connection = None
                response_file = None
                time.sleep(5)
                continue

        now = time.ticks_ms()
        if (
            time.ticks_diff(now, last_heartbeat_at)
            >= HEARTBEAT_INTERVAL_MS
        ):
            try:
                ping_id += 1
                send_heartbeat(
                    connection,
                    response_file,
                    ping_id,
                    pn532 is not None,
                )
                last_heartbeat_at = now
            except Exception as error:
                print("PC heartbeat error:", error)
                close_connection(connection, response_file)
                connection = None
                response_file = None
                time.sleep(1)
                continue

        if pn532 is None:
            try:
                pn532 = initialize_reader()
                consecutive_reader_errors = 0
                last_uid = None
                absent_polls = CARD_ABSENCE_POLLS
                print("PN532 recovered")
            except Exception as error:
                print("PN532 still unavailable:", error)
                time.sleep(2)
                continue

        try:
            uid = pn532.read_passive_target()
            consecutive_reader_errors = 0
        except Exception as error:
            consecutive_reader_errors += 1
            if consecutive_reader_errors == 1:
                print("PN532 read error:", error)

            if consecutive_reader_errors >= CONSECUTIVE_READER_ERRORS:
                print("Recovering PN532 after repeated read errors")

                try:
                    pn532 = initialize_reader()
                    consecutive_reader_errors = 0
                    last_uid = None
                    absent_polls = CARD_ABSENCE_POLLS
                    print("PN532 recovered")
                except Exception as recovery_error:
                    print("PN532 recovery error:", recovery_error)
                    pn532 = None
                    time.sleep(1)

            time.sleep_ms(POLL_INTERVAL_MS)
            continue

        if uid is None:
            absent_polls += 1
            if absent_polls >= CARD_ABSENCE_POLLS:
                last_uid = None
            time.sleep_ms(POLL_INTERVAL_MS)
            continue

        absent_polls = 0
        uid_text = format_uid(uid)
        if uid_text == last_uid:
            time.sleep_ms(POLL_INTERVAL_MS)
            continue

        print("Found card UID:", uid_text)
        last_uid = uid_text
        now = time.ticks_ms()
        can_send = time.ticks_diff(now, last_sent_at) >= READ_COOLDOWN_MS

        if uid_text in allowed_uids and can_send:
            try:
                event_id += 1
                response = send_nfc_message(
                    connection,
                    response_file,
                    uid_text,
                    allowed_uids,
                    event_id,
                )
            except Exception as error:
                print("PC communication error:", error)
                error_beep()
                close_connection(connection, response_file)
                connection = None
                response_file = None
                time.sleep(1)
                continue

            if response.get("status") in ("ok", "already_active"):
                success_beep()
            else:
                print("No available seat:", response)
                error_beep()
            last_sent_at = now
        elif uid_text not in allowed_uids and can_send:
            print("UID not authorized:", uid_text)
            invalid_card_beep()
            last_sent_at = now

        time.sleep_ms(POLL_INTERVAL_MS)


if __name__ == "__main__":
    main()
