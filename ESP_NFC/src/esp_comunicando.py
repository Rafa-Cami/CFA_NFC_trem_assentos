# ESP32-C3 SuperMini + PN532 I2C + resilient TCP/IP communication.

import json
import machine
import network
import time
import ubinascii
import uasyncio as asyncio
from micropython import const

from nfc_state import EventQueue, PresenceTracker

try:
    from esp_config import HOST, PASSWORD, SSID
except ImportError:
    raise RuntimeError(
        "Missing esp_config.py. Copy esp_config.example.py and configure it."
    )


PROTOCOL_VERSION = 1
PORT = 5000
I2C_ID = 0
I2C_SDA_PIN = 8
I2C_SCL_PIN = 9
I2C_FREQ = 100000
PN532_I2C_ADDRESS = const(0x24)
BUZZER_PIN = 4
BUZZER_DUTY_U16 = 49152
POLL_INTERVAL_MS = 50
PN532_TIMEOUT_MS = 80
WIFI_CONNECT_TIMEOUT_MS = 20000
TCP_TIMEOUT_MS = 2000
IDLE_PING_INTERVAL_MS = 1000
EVENT_MAX_AGE_MS = 30000
RECONNECT_BACKOFF_MS = (250, 500, 1000, 2000)
RECOVERY_ATTEMPTS = 3

NFC_UUIDS = [
    "d3:8e:18:06",
]

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


class BusyError(Exception):
    pass


class PN532FrameError(Exception):
    pass


class PN532Timeout(Exception):
    pass


class PN532:
    def __init__(self, *, debug=False):
        self.debug = debug
        self._wakeup()
        self.get_firmware_version()

    def _read_data(self, count):
        raise NotImplementedError

    def _write_data(self, framebytes):
        raise NotImplementedError

    def _wait_ready(self, timeout_ms):
        raise NotImplementedError

    def _wakeup(self):
        raise NotImplementedError

    def _write_frame(self, data):
        length = len(data)
        frame = bytearray(length + 8)
        frame[0] = _PREAMBLE
        frame[1] = _STARTCODE1
        frame[2] = _STARTCODE2
        frame[3] = length & 0xFF
        frame[4] = (-length) & 0xFF
        frame[5:-2] = data
        frame[-2] = (-sum(data)) & 0xFF
        frame[-1] = _POSTAMBLE
        self._write_data(bytes(frame))

    def _read_frame(self, requested_length):
        response = self._read_data(requested_length + 8)
        offset = 0
        while offset < len(response) and response[offset] == 0:
            offset += 1
        if offset >= len(response) or response[offset] != 0xFF:
            raise PN532FrameError("invalid response preamble")
        offset += 1
        if offset + 1 >= len(response):
            raise PN532FrameError("truncated response")
        frame_len = response[offset]
        if (frame_len + response[offset + 1]) & 0xFF:
            raise PN532FrameError("invalid length checksum")
        start = offset + 2
        end = start + frame_len
        if end >= len(response):
            raise PN532FrameError("truncated response data")
        if sum(response[start : end + 1]) & 0xFF:
            raise PN532FrameError("invalid data checksum")
        return response[start:end]

    def abort_pending(self):
        try:
            self._write_data(_ACK)
        except OSError:
            pass
        try:
            if self._wait_ready(10):
                self._read_data(32)
        except (OSError, BusyError, PN532FrameError):
            pass

    def call_function(
        self, command, response_length=0, params=None, timeout_ms=500
    ):
        params = [] if params is None else params
        data = bytearray(2 + len(params))
        data[0] = _HOSTTOPN532
        data[1] = command & 0xFF
        for index, value in enumerate(params):
            data[index + 2] = value

        self._write_frame(data)
        if not self._wait_ready(timeout_ms):
            self.abort_pending()
            raise PN532Timeout("timeout waiting for ACK")
        if self._read_data(len(_ACK)) != _ACK:
            self.abort_pending()
            raise PN532FrameError("unexpected ACK")
        if not self._wait_ready(timeout_ms):
            self.abort_pending()
            raise PN532Timeout("timeout waiting for response")

        response = self._read_frame(response_length + 2)
        if (
            len(response) < 2
            or response[0] != _PN532TOHOST
            or response[1] != command + 1
        ):
            raise PN532FrameError("unexpected command response")
        return response[2:]

    def get_firmware_version(self):
        response = self.call_function(
            _COMMAND_GETFIRMWAREVERSION,
            response_length=4,
            timeout_ms=500,
        )
        if len(response) != 4:
            raise PN532FrameError("invalid firmware response")
        return tuple(response)

    def configure(self):
        self.call_function(
            _COMMAND_SAMCONFIGURATION,
            params=[0x01, 0x14, 0x01],
            timeout_ms=500,
        )
        # RFConfiguration item 0x05: ATR retries, PSL retries,
        # passive activation retries. 0x00 means one passive try.
        self.call_function(
            _COMMAND_RFCONFIGURATION,
            params=[0x05, 0xFF, 0x01, 0x00],
            timeout_ms=500,
        )

    def read_passive_target(self):
        response = self.call_function(
            _COMMAND_INLISTPASSIVETARGET,
            params=[0x01, _MIFARE_ISO14443A],
            response_length=19,
            timeout_ms=PN532_TIMEOUT_MS,
        )
        if not response or response[0] == 0:
            return None
        if response[0] != 1 or len(response) < 6:
            raise PN532FrameError("invalid target response")
        uid_length = response[5]
        if uid_length > 7 or len(response) < 6 + uid_length:
            raise PN532FrameError("invalid UID length")
        return response[6 : 6 + uid_length]


class PN532_I2C(PN532):
    def __init__(self, i2c, *, debug=False):
        self._i2c = i2c
        super().__init__(debug=debug)

    def _wakeup(self):
        time.sleep_ms(500)

    def _wait_ready(self, timeout_ms):
        status = bytearray(1)
        started_at = time.ticks_ms()
        while time.ticks_diff(time.ticks_ms(), started_at) < timeout_ms:
            try:
                self._i2c.readfrom_into(PN532_I2C_ADDRESS, status)
                if status[0] == _I2C_READY:
                    return True
            except OSError:
                pass
            time.sleep_ms(5)
        return False

    def _read_data(self, count):
        frame = bytearray(count + 1)
        self._i2c.readfrom_into(PN532_I2C_ADDRESS, frame)
        if frame[0] != _I2C_READY:
            raise BusyError("PN532 not ready")
        return frame[1:]

    def _write_data(self, framebytes):
        self._i2c.writeto(PN532_I2C_ADDRESS, framebytes)


def validate_config():
    if not isinstance(SSID, str) or not SSID or SSID == "YOUR_WIFI_NAME":
        raise RuntimeError("SSID is not configured")
    if not isinstance(PASSWORD, str) or not PASSWORD:
        raise RuntimeError("PASSWORD is not configured")
    if not isinstance(HOST, str) or not HOST:
        raise RuntimeError("HOST is not configured")


def format_uid(uid):
    return ":".join("{:02x}".format(byte) for byte in uid)


def make_boot_id():
    return "{}-{:08x}".format(
        ubinascii.hexlify(machine.unique_id()).decode(),
        time.ticks_ms() & 0xFFFFFFFF,
    )


def setup_reader():
    i2c = machine.I2C(
        I2C_ID,
        scl=machine.Pin(I2C_SCL_PIN),
        sda=machine.Pin(I2C_SDA_PIN),
        freq=I2C_FREQ,
    )
    if PN532_I2C_ADDRESS not in i2c.scan():
        raise RuntimeError("PN532 not found at 0x24")
    reader = PN532_I2C(i2c)
    _, version, revision, _ = reader.get_firmware_version()
    print("PN532 firmware {}.{}".format(version, revision))
    reader.configure()
    return reader


def set_pwm_duty(pwm, duty):
    if hasattr(pwm, "duty_u16"):
        pwm.duty_u16(duty)
    else:
        pwm.duty(int(duty * 1023 / 65535))


async def play_tone(duration_ms, frequency):
    pwm = machine.PWM(machine.Pin(BUZZER_PIN, machine.Pin.OUT))
    pwm.freq(frequency)
    set_pwm_duty(pwm, BUZZER_DUTY_U16)
    await asyncio.sleep_ms(duration_ms)
    set_pwm_duty(pwm, 0)
    pwm.deinit()
    machine.Pin(BUZZER_PIN, machine.Pin.OUT).value(0)


async def buzzer_loop(events):
    patterns = {
        "success": ((80, 1800), (60, 0), (130, 2600)),
        "error": ((120, 500), (70, 0), (170, 300)),
        "invalid": ((90, 750), (55, 0), (110, 480), (55, 0), (170, 280)),
    }
    while True:
        if not events:
            await asyncio.sleep_ms(20)
            continue
        pattern = patterns.get(events.pop(0), patterns["error"])
        for duration_ms, frequency in pattern:
            if frequency:
                await play_tone(duration_ms, frequency)
            else:
                await asyncio.sleep_ms(duration_ms)


async def recover_reader():
    for attempt in range(1, RECOVERY_ATTEMPTS + 1):
        print("PN532 recovery {}/{}".format(attempt, RECOVERY_ATTEMPTS))
        await asyncio.sleep_ms(250)
        try:
            return setup_reader()
        except Exception as error:
            print("PN532 recovery failed:", error)
    print("PN532 unrecoverable; resetting ESP")
    machine.reset()


async def nfc_loop(event_queue, buzzer_events, boot_id):
    reader = await recover_reader()
    tracker = PresenceTracker(2)
    allowed = [uid.lower() for uid in NFC_UUIDS]
    sequence = 0
    errors = 0
    print("NFC reader ready")

    while True:
        try:
            uid = reader.read_passive_target()
            errors = 0
        except (OSError, BusyError, PN532Timeout, PN532FrameError) as error:
            errors += 1
            print("PN532 error:", error)
            if errors >= 3:
                reader = await recover_reader()
                errors = 0
            await asyncio.sleep_ms(POLL_INTERVAL_MS)
            continue

        uid_text = None if uid is None else format_uid(uid)
        presented = tracker.observe(uid_text)
        if presented is not None:
            print("Card presented:", presented)
            if presented not in allowed:
                buzzer_events.append("invalid")
            else:
                card_id = "nfc_{}".format(allowed.index(presented) + 1)
                event = {
                    "event_id": "{}:{}".format(boot_id, sequence),
                    "card_id": card_id,
                    "created_at_ms": time.ticks_ms(),
                }
                sequence += 1
                if not event_queue.put(event):
                    print("NFC queue full")
                    buzzer_events.append("error")
        await asyncio.sleep_ms(POLL_INTERVAL_MS)


async def connect_wifi(wifi):
    while not wifi.isconnected():
        try:
            wifi.active(True)
            wifi.disconnect()
        except OSError:
            pass
        await asyncio.sleep_ms(250)
        try:
            wifi.connect(SSID, PASSWORD)
        except OSError as error:
            print("Wi-Fi connect failed:", error)
            await asyncio.sleep_ms(1000)
            continue
        started_at = time.ticks_ms()
        while (
            not wifi.isconnected()
            and time.ticks_diff(time.ticks_ms(), started_at)
            < WIFI_CONNECT_TIMEOUT_MS
        ):
            await asyncio.sleep_ms(250)
        if not wifi.isconnected():
            print("Wi-Fi unavailable")
            await asyncio.sleep_ms(1000)
    print("Wi-Fi connected:", wifi.ifconfig()[0])


async def close_writer(writer):
    if writer is None:
        return
    try:
        writer.close()
        if hasattr(writer, "wait_closed"):
            await writer.wait_closed()
    except (OSError, AttributeError):
        pass


async def wait_for_ms(awaitable, timeout_ms):
    if hasattr(asyncio, "wait_for_ms"):
        return await asyncio.wait_for_ms(awaitable, timeout_ms)
    return await asyncio.wait_for(awaitable, timeout_ms / 1000)


async def read_with_timeout(reader):
    return await wait_for_ms(reader.readline(), TCP_TIMEOUT_MS)


async def open_registered_connection(boot_id):
    writer = None
    try:
        reader, writer = await wait_for_ms(
            asyncio.open_connection(HOST, PORT), TCP_TIMEOUT_MS
        )
        writer.write(
            (
                json.dumps(
                    {
                        "v": PROTOCOL_VERSION,
                        "type": "register",
                        "role": "nfc",
                        "device_id": "nfc_reader",
                        "boot_id": boot_id,
                    }
                )
                + "\n"
            ).encode()
        )
        await writer.drain()
        line = await read_with_timeout(reader)
        if not line:
            raise RuntimeError("server disconnected before register_ack")
        response = json.loads(line)
        if (
            response.get("v") != PROTOCOL_VERSION
            or response.get("type") != "register_ack"
            or response.get("accepted") is not True
        ):
            raise RuntimeError("NFC registration rejected")
        print("Connected to server {}:{}".format(HOST, PORT))
        return reader, writer
    except Exception:
        await close_writer(writer)
        raise


async def network_loop(event_queue, buzzer_events, boot_id):
    wifi = network.WLAN(network.STA_IF)
    backoff_index = 0
    while True:
        reader = None
        writer = None
        try:
            if not wifi.isconnected():
                await connect_wifi(wifi)
            reader, writer = await open_registered_connection(boot_id)
            backoff_index = 0
            last_ping_at = time.ticks_ms()

            while True:
                now_ms = time.ticks_ms()
                for _ in event_queue.discard_expired(now_ms):
                    print("NFC event expired")
                    buzzer_events.append("error")

                event = event_queue.peek()
                if event is None:
                    if (
                        time.ticks_diff(time.ticks_ms(), last_ping_at)
                        >= IDLE_PING_INTERVAL_MS
                    ):
                        writer.write(
                            (
                                json.dumps(
                                    {
                                        "v": PROTOCOL_VERSION,
                                        "type": "ping",
                                    }
                                )
                                + "\n"
                            ).encode()
                        )
                        await writer.drain()
                        line = await read_with_timeout(reader)
                        if not line:
                            raise RuntimeError("server disconnected")
                        pong = json.loads(line)
                        if (
                            pong.get("v") != PROTOCOL_VERSION
                            or pong.get("type") != "pong"
                        ):
                            raise RuntimeError("invalid pong")
                        last_ping_at = time.ticks_ms()
                    await asyncio.sleep_ms(50)
                    continue

                age_ms = event_queue.age_ms(event, time.ticks_ms())
                message = {
                    "v": PROTOCOL_VERSION,
                    "type": "nfc_presented",
                    "event_id": event["event_id"],
                    "card_id": event["card_id"],
                    "age_ms": age_ms,
                }
                writer.write((json.dumps(message) + "\n").encode())
                await writer.drain()
                line = await read_with_timeout(reader)
                if not line:
                    raise RuntimeError("server disconnected")
                response = json.loads(line)
                if (
                    response.get("type") != "nfc_result"
                    or response.get("event_id") != event["event_id"]
                ):
                    raise RuntimeError("unexpected server response")

                event_queue.pop()
                print("NFC result:", response.get("status"))
                if response.get("status") in ("OK", "PARTIAL"):
                    buzzer_events.append("success")
                else:
                    buzzer_events.append("error")
        except Exception as error:
            print("Network error:", error)
            delay_ms = RECONNECT_BACKOFF_MS[
                min(backoff_index, len(RECONNECT_BACKOFF_MS) - 1)
            ]
            backoff_index += 1
            await asyncio.sleep_ms(delay_ms)
        finally:
            await close_writer(writer)


async def main_async():
    validate_config()
    boot_id = make_boot_id()
    event_queue = EventQueue(8, EVENT_MAX_AGE_MS, time.ticks_diff)
    buzzer_events = []
    tasks = [
        asyncio.create_task(buzzer_loop(buzzer_events)),
        asyncio.create_task(nfc_loop(event_queue, buzzer_events, boot_id)),
        asyncio.create_task(network_loop(event_queue, buzzer_events, boot_id)),
    ]
    try:
        while True:
            await asyncio.sleep(1)
    finally:
        for task in tasks:
            task.cancel()


def main():
    print("Starting resilient NFC reader")
    try:
        asyncio.run(main_async())
    finally:
        asyncio.new_event_loop()


if __name__ == "__main__":
    main()
