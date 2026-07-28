# ESP32-C3 SuperMini + PN532 I2C + resilient TCP/IP communication.

import gc
import json
import machine
import network
import sys
import time
import ubinascii
import uasyncio as asyncio
from micropython import const

from nfc_state import (
    EventQueue,
    HeartbeatMonitor,
    PresenceTracker,
    ReconnectBackoff,
)

try:
    from esp_config import HOST, PASSWORD, SSID
except ImportError:
    raise RuntimeError(
        "Missing esp_config.py. Copy esp_config.example.py and configure it."
    )


PROTOCOL_VERSION = 1
FIRMWARE_VERSION = "1.1.0"
BUILD_ID = "nfc-robustez-1"
EXPECTED_SERVER_BUILD_ID = "server-robustez-1"
PORT = 5000
I2C_ID = 0
I2C_SDA_PIN = 8
I2C_SCL_PIN = 9
I2C_FREQ = 100000
PN532_I2C_ADDRESS = const(0x24)
BUZZER_PIN = 4
BUZZER_DUTY_U16 = 49152
POLL_INTERVAL_MS = 50
PN532_ACK_TIMEOUT_MS = 30
PN532_SEARCH_TIMEOUT_MS = 180
WIFI_CONNECT_TIMEOUT_MS = 20000
IO_TIMEOUT_MS = 5000
HEARTBEAT_INTERVAL_MS = 2000
MAX_HEARTBEAT_FAILURES = 3
EVENT_MAX_AGE_MS = 30000
RECONNECT_BACKOFF_MS = (500, 1000, 2000, 4000, 8000, 15000)
HEALTHY_SESSION_MS = 20000
RECOVERY_ATTEMPTS = 3
CONSECUTIVE_READER_ERRORS = 5
TELEMETRY_INTERVAL_MS = 30000
TASK_FAILURE_WINDOW_MS = 60000
TASK_FAILURE_LIMIT = 3
WATCHDOG_TIMEOUT_MS = 8000
WATCHDOG_ARM_DELAY_MS = 5000

BOOT_STARTED_AT = time.ticks_ms()

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


class PN532AckTimeout(PN532Timeout):
    pass


class PN532ResponseTimeout(PN532Timeout):
    pass


class PN532:
    def __init__(self, *, debug=False):
        self.debug = debug
        self._wakeup()

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
        self,
        command,
        response_length=0,
        params=None,
        ack_timeout_ms=PN532_ACK_TIMEOUT_MS,
        response_timeout_ms=500,
    ):
        params = [] if params is None else params
        data = bytearray(2 + len(params))
        data[0] = _HOSTTOPN532
        data[1] = command & 0xFF
        for index, value in enumerate(params):
            data[index + 2] = value

        self._write_frame(data)
        if not self._wait_ready(ack_timeout_ms):
            self.abort_pending()
            raise PN532AckTimeout("timeout waiting for ACK")
        if self._read_data(len(_ACK)) != _ACK:
            self.abort_pending()
            raise PN532FrameError("unexpected ACK")
        if not self._wait_ready(response_timeout_ms):
            self.abort_pending()
            raise PN532ResponseTimeout("timeout waiting for response")

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
            response_timeout_ms=500,
        )
        if len(response) != 4:
            raise PN532FrameError("invalid firmware response")
        return tuple(response)

    def configure(self):
        self.call_function(
            _COMMAND_SAMCONFIGURATION,
            params=[0x01, 0x14, 0x01],
            response_timeout_ms=500,
        )
        # RFConfiguration item 0x05: ATR retries, PSL retries,
        # passive activation retries. 0x00 means one passive try.
        self.call_function(
            _COMMAND_RFCONFIGURATION,
            params=[0x05, 0xFF, 0x01, 0x00],
            response_timeout_ms=500,
        )

    def read_passive_target(self):
        try:
            response = self.call_function(
                _COMMAND_INLISTPASSIVETARGET,
                params=[0x01, _MIFARE_ISO14443A],
                response_length=19,
                ack_timeout_ms=PN532_ACK_TIMEOUT_MS,
                response_timeout_ms=PN532_SEARCH_TIMEOUT_MS,
            )
        except PN532ResponseTimeout:
            return None, "search_timeout"
        if not response or response[0] == 0:
            return None, "no_card"
        if response[0] != 1 or len(response) < 6:
            raise PN532FrameError("invalid target response")
        uid_length = response[5]
        if uid_length > 7 or len(response) < 6 + uid_length:
            raise PN532FrameError("invalid UID length")
        return response[6 : 6 + uid_length], "card"


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


def uptime_ms():
    return max(0, time.ticks_diff(time.ticks_ms(), BOOT_STARTED_AT))


def log_runtime(event, **fields):
    parts = [
        "event={}".format(event),
        "uptime_ms={}".format(uptime_ms()),
        "free_heap={}".format(gc.mem_free()),
    ]
    for key in sorted(fields):
        parts.append("{}={}".format(key, fields[key]))
    print(" ".join(parts))


def log_exception(name, error):
    log_runtime(
        "task_error",
        task=name,
        error_type=type(error).__name__,
        error=str(error),
    )
    if hasattr(sys, "print_exception"):
        sys.print_exception(error)


def jittered_delay_ms(delay_ms):
    spread = max(1, delay_ms // 5)
    return delay_ms + (
        time.ticks_ms() % (spread * 2 + 1)
    ) - spread


def format_uid(uid):
    return ":".join("{:02x}".format(byte) for byte in uid)


def make_boot_id():
    return "{}-{:08x}".format(
        ubinascii.hexlify(machine.unique_id()).decode(),
        time.ticks_ms() & 0xFFFFFFFF,
    )


def setup_reader():
    log_runtime("pn532_initializing", address="0x24")
    i2c = machine.I2C(
        I2C_ID,
        scl=machine.Pin(I2C_SCL_PIN),
        sda=machine.Pin(I2C_SDA_PIN),
        freq=I2C_FREQ,
    )
    reader = PN532_I2C(i2c)
    _, version, revision, _ = reader.get_firmware_version()
    log_runtime(
        "pn532_ready",
        firmware="{}.{}".format(version, revision),
    )
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


async def recover_reader(stats, initial=False):
    for attempt in range(1, RECOVERY_ATTEMPTS + 1):
        if not initial:
            stats["recoveries"] += 1
        log_runtime(
            "pn532_recovery",
            attempt=attempt,
            recoveries=stats["recoveries"],
        )
        await asyncio.sleep_ms(250)
        try:
            return setup_reader()
        except Exception as error:
            log_runtime(
                "pn532_recovery_failed",
                attempt=attempt,
                error_type=type(error).__name__,
                error=str(error),
            )
            gc.collect()
        await asyncio.sleep_ms(0)
    raise RuntimeError("PN532 recovery exhausted")


async def nfc_loop(event_queue, buzzer_events, boot_id, stats):
    reader = await recover_reader(stats, initial=True)
    tracker = PresenceTracker(2)
    allowed = [uid.lower() for uid in NFC_UUIDS]
    sequence = 0
    consecutive_errors = 0
    last_telemetry_at = time.ticks_ms()
    log_runtime("nfc_reader_ready")

    while True:
        try:
            uid, outcome = reader.read_passive_target()
            if outcome == "search_timeout":
                stats["search_timeouts"] += 1
            elif outcome == "no_card":
                stats["no_card"] += 1
            consecutive_errors = 0
        except OSError as error:
            stats["i2c_errors"] += 1
            consecutive_errors += 1
            log_runtime("pn532_i2c_error", error=str(error))
            uid = None
        except PN532AckTimeout as error:
            stats["ack_timeouts"] += 1
            consecutive_errors += 1
            log_runtime("pn532_ack_timeout", error=str(error))
            uid = None
        except (BusyError, PN532FrameError) as error:
            stats["frame_errors"] += 1
            consecutive_errors += 1
            log_runtime(
                "pn532_frame_error",
                error_type=type(error).__name__,
                error=str(error),
            )
            uid = None
        except PN532ResponseTimeout as error:
            stats["response_timeouts"] += 1
            consecutive_errors += 1
            log_runtime("pn532_response_timeout", error=str(error))
            uid = None

        if consecutive_errors >= CONSECUTIVE_READER_ERRORS:
            reader = await recover_reader(stats)
            consecutive_errors = 0
            await asyncio.sleep_ms(POLL_INTERVAL_MS)
            continue

        uid_text = None if uid is None else format_uid(uid)
        presented = tracker.observe(uid_text)
        if presented is not None:
            log_runtime("card_presented", uid=presented)
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
                    log_runtime("nfc_queue_full")
                    buzzer_events.append("error")
        now_ms = time.ticks_ms()
        if (
            time.ticks_diff(now_ms, last_telemetry_at)
            >= TELEMETRY_INTERVAL_MS
        ):
            log_runtime(
                "nfc_telemetry",
                queue_depth=len(event_queue),
                no_card=stats["no_card"],
                search_timeouts=stats["search_timeouts"],
                ack_timeouts=stats["ack_timeouts"],
                response_timeouts=stats["response_timeouts"],
                frame_errors=stats["frame_errors"],
                i2c_errors=stats["i2c_errors"],
                recoveries=stats["recoveries"],
            )
            last_telemetry_at = now_ms
        await asyncio.sleep_ms(POLL_INTERVAL_MS)


async def connect_wifi(wifi):
    try:
        pm_none = getattr(network, "PM_NONE", None)
        if pm_none is None:
            pm_none = getattr(wifi, "PM_NONE")
        wifi.config(pm=pm_none)
        log_runtime("wifi_power_save_disabled")
    except (AttributeError, OSError, ValueError):
        log_runtime("wifi_power_save_unchanged")

    retry_index = 0
    while not wifi.isconnected():
        try:
            wifi.active(True)
        except OSError:
            pass
        try:
            wifi.connect(SSID, PASSWORD)
        except OSError as error:
            log_runtime("wifi_connect_error", error=str(error))
        started_at = time.ticks_ms()
        while (
            not wifi.isconnected()
            and time.ticks_diff(time.ticks_ms(), started_at)
            < WIFI_CONNECT_TIMEOUT_MS
        ):
            await asyncio.sleep_ms(250)
        if not wifi.isconnected():
            delay_ms = RECONNECT_BACKOFF_MS[
                min(retry_index, len(RECONNECT_BACKOFF_MS) - 1)
            ]
            retry_index += 1
            delay_ms = jittered_delay_ms(delay_ms)
            log_runtime(
                "wifi_retry",
                attempt=retry_index,
                delay_ms=delay_ms,
            )
            await asyncio.sleep_ms(delay_ms)
    log_runtime("wifi_connected", ip=wifi.ifconfig()[0])


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
    return await wait_for_ms(reader.readline(), IO_TIMEOUT_MS)


async def send_message(writer, message):
    writer.write((json.dumps(message) + "\n").encode())
    await wait_for_ms(writer.drain(), IO_TIMEOUT_MS)


async def open_registered_connection(
    boot_id, reconnect_attempt, stats
):
    writer = None
    try:
        reader, writer = await wait_for_ms(
            asyncio.open_connection(HOST, PORT), IO_TIMEOUT_MS
        )
        await send_message(
            writer,
            {
                "v": PROTOCOL_VERSION,
                "type": "register",
                "role": "nfc",
                "device_id": "nfc_reader",
                "boot_id": boot_id,
                "firmware_version": FIRMWARE_VERSION,
                "build_id": BUILD_ID,
                "reconnect_attempt": reconnect_attempt,
                "uptime_ms": uptime_ms(),
                "free_heap_bytes": gc.mem_free(),
                "pn532_recoveries": stats["recoveries"],
            },
        )
        line = await read_with_timeout(reader)
        if not line:
            raise RuntimeError("server disconnected before register_ack")
        response = json.loads(line)
        if (
            response.get("v") != PROTOCOL_VERSION
            or response.get("type") != "register_ack"
            or response.get("accepted") is not True
        ):
            raise RuntimeError(
                "NFC registration rejected: {}".format(
                    response.get("reason", "unknown")
                )
            )
        if response.get("server_build_id") != EXPECTED_SERVER_BUILD_ID:
            raise RuntimeError(
                "incompatible server build: {}".format(
                    response.get("server_build_id")
                )
            )
        log_runtime(
            "nfc_registered",
            host=HOST,
            port=PORT,
            server_build=response.get("server_build_id"),
        )
        return reader, writer
    except Exception:
        await close_writer(writer)
        raise


async def network_loop(event_queue, buzzer_events, boot_id, stats):
    wifi = network.WLAN(network.STA_IF)
    backoff = ReconnectBackoff(
        RECONNECT_BACKOFF_MS, HEALTHY_SESSION_MS
    )
    while True:
        reader = None
        writer = None
        session_started_at = time.ticks_ms()
        try:
            if not wifi.isconnected():
                await connect_wifi(wifi)
            session_started_at = time.ticks_ms()
            reader, writer = await open_registered_connection(
                boot_id, backoff.attempt, stats
            )
            ping_id = 0
            heartbeat = HeartbeatMonitor(MAX_HEARTBEAT_FAILURES)
            last_ping_at = time.ticks_add(
                time.ticks_ms(), -HEARTBEAT_INTERVAL_MS
            )

            while True:
                now_ms = time.ticks_ms()
                for _ in event_queue.discard_expired(now_ms):
                    log_runtime("nfc_event_expired")
                    buzzer_events.append("error")

                event = event_queue.peek()
                if event is None:
                    wait_ms = HEARTBEAT_INTERVAL_MS - time.ticks_diff(
                        time.ticks_ms(), last_ping_at
                    )
                    if wait_ms > 0:
                        await asyncio.sleep_ms(wait_ms)
                    ping_id += 1
                    last_ping_at = time.ticks_ms()
                    await send_message(
                        writer,
                        {
                            "v": PROTOCOL_VERSION,
                            "type": "ping",
                            "ping_id": ping_id,
                            "uptime_ms": uptime_ms(),
                            "free_heap_bytes": gc.mem_free(),
                            "pn532_errors": (
                                stats["ack_timeouts"]
                                + stats["response_timeouts"]
                                + stats["frame_errors"]
                                + stats["i2c_errors"]
                            ),
                            "pn532_recoveries": stats["recoveries"],
                        },
                    )
                    try:
                        line = await wait_for_ms(
                            reader.readline(), HEARTBEAT_INTERVAL_MS
                        )
                    except asyncio.TimeoutError:
                        if heartbeat.miss():
                            raise RuntimeError(
                                "three heartbeat failures"
                            )
                        continue
                    if not line:
                        raise RuntimeError("server disconnected")
                    pong = json.loads(line)
                    if (
                        pong.get("v") == PROTOCOL_VERSION
                        and pong.get("type") == "pong"
                        and pong.get("ping_id") == ping_id
                    ):
                        heartbeat.acknowledge()
                    else:
                        if heartbeat.miss():
                            raise RuntimeError("invalid pong")
                    continue

                age_ms = event_queue.age_ms(event, time.ticks_ms())
                message = {
                    "v": PROTOCOL_VERSION,
                    "type": "nfc_presented",
                    "event_id": event["event_id"],
                    "card_id": event["card_id"],
                    "age_ms": age_ms,
                }
                await send_message(writer, message)
                try:
                    line = await read_with_timeout(reader)
                except asyncio.TimeoutError:
                    if heartbeat.miss():
                        raise RuntimeError(
                            "three NFC result timeouts"
                        )
                    continue
                if not line:
                    raise RuntimeError("server disconnected")
                response = json.loads(line)
                if (
                    response.get("type") != "nfc_result"
                    or response.get("event_id") != event["event_id"]
                ):
                    raise RuntimeError("unexpected server response")

                event_queue.pop()
                heartbeat.acknowledge()
                log_runtime(
                    "nfc_result",
                    event_id=event["event_id"],
                    status=response.get("status"),
                )
                if response.get("status") in ("OK", "PARTIAL"):
                    buzzer_events.append("success")
                else:
                    buzzer_events.append("error")
        except Exception as error:
            session_ms = time.ticks_diff(
                time.ticks_ms(), session_started_at
            )
            await close_writer(writer)
            writer = None
            gc.collect()
            backoff.record_session(session_ms)
            delay_ms = backoff.next_delay_ms(time.ticks_ms())
            log_runtime(
                "network_error",
                error=str(error),
                reconnect_attempt=backoff.attempt,
                session_ms=session_ms,
                delay_ms=delay_ms,
            )
            await asyncio.sleep_ms(delay_ms)
        finally:
            await close_writer(writer)


async def supervise(name, factory, essential):
    failures = []
    while True:
        try:
            await factory()
            raise RuntimeError("task returned unexpectedly")
        except asyncio.CancelledError:
            raise
        except Exception as error:
            now_ms = time.ticks_ms()
            failures = [
                item
                for item in failures
                if time.ticks_diff(now_ms, item)
                < TASK_FAILURE_WINDOW_MS
            ]
            failures.append(now_ms)
            log_exception(name, error)
            gc.collect()
            if essential and len(failures) >= TASK_FAILURE_LIMIT:
                log_runtime(
                    "device_reset",
                    reason="persistent_task_failure",
                    task=name,
                )
                await asyncio.sleep_ms(100)
                machine.reset()
            await asyncio.sleep_ms(500)


async def watchdog_loop():
    await asyncio.sleep_ms(WATCHDOG_ARM_DELAY_MS)
    try:
        watchdog = machine.WDT(timeout=WATCHDOG_TIMEOUT_MS)
    except (AttributeError, OSError, ValueError) as error:
        log_runtime("watchdog_unavailable", error=str(error))
        while True:
            await asyncio.sleep(60)
    log_runtime("watchdog_enabled", timeout_ms=WATCHDOG_TIMEOUT_MS)
    while True:
        watchdog.feed()
        await asyncio.sleep_ms(1000)


async def main_async():
    validate_config()
    boot_id = make_boot_id()
    event_queue = EventQueue(8, EVENT_MAX_AGE_MS, time.ticks_diff)
    buzzer_events = []
    stats = {
        "no_card": 0,
        "search_timeouts": 0,
        "ack_timeouts": 0,
        "response_timeouts": 0,
        "frame_errors": 0,
        "i2c_errors": 0,
        "recoveries": 0,
    }
    log_runtime(
        "boot",
        role="nfc",
        device_id="nfc_reader",
        boot_id=boot_id,
        firmware_version=FIRMWARE_VERSION,
        build_id=BUILD_ID,
        reset_cause=machine.reset_cause(),
    )
    tasks = [
        asyncio.create_task(
            supervise(
                "buzzer_loop",
                lambda: buzzer_loop(buzzer_events),
                False,
            )
        ),
        asyncio.create_task(
            supervise(
                "nfc_loop",
                lambda: nfc_loop(
                    event_queue,
                    buzzer_events,
                    boot_id,
                    stats,
                ),
                True,
            )
        ),
        asyncio.create_task(
            supervise(
                "network_loop",
                lambda: network_loop(
                    event_queue,
                    buzzer_events,
                    boot_id,
                    stats,
                ),
                True,
            )
        ),
        asyncio.create_task(watchdog_loop()),
    ]
    try:
        while True:
            await asyncio.sleep(1)
    finally:
        for task in tasks:
            task.cancel()


def main():
    try:
        asyncio.run(main_async())
    finally:
        asyncio.new_event_loop()


if __name__ == "__main__":
    main()
