import gc
import json
import machine
import sys
import time
import ubinascii

import network
import uasyncio as asyncio
from machine import Pin, unique_id

from seat_state import HeartbeatMonitor, ReconnectBackoff, SeatState

try:
    from esp_config import HOST, PASSWORD, SEAT_ID, SSID
except ImportError:
    raise RuntimeError(
        "Missing esp_config.py. Copy esp_config.example.py and configure it."
    )


PROTOCOL_VERSION = 1
FIRMWARE_VERSION = "1.1.0"
BUILD_ID = "seat-robustez-1"
EXPECTED_SERVER_BUILD_ID = "server-robustez-1"
PORT = 5000
SENSOR_1_PIN = 10
SENSOR_2_PIN = 7
LED_PIN = 5
AVAILABLE_SENSOR_VALUE = 0
SAMPLE_INTERVAL_MS = 500
WIFI_CONNECT_TIMEOUT_MS = 20000
IO_TIMEOUT_MS = 5000
HEARTBEAT_INTERVAL_MS = 2000
MAX_HEARTBEAT_FAILURES = 3
HEALTHY_SESSION_MS = 20000
RECONNECT_BACKOFF_MS = (500, 1000, 2000, 4000, 8000, 15000)
MAX_OCCUPIED_AGE_MS = 5000
TASK_FAILURE_WINDOW_MS = 60000
TASK_FAILURE_LIMIT = 3
WATCHDOG_TIMEOUT_MS = 8000
WATCHDOG_ARM_DELAY_MS = 5000

BOOT_STARTED_AT = time.ticks_ms()

sensor_1 = Pin(SENSOR_1_PIN, Pin.IN)
sensor_2 = Pin(SENSOR_2_PIN, Pin.IN)
led = Pin(LED_PIN, Pin.OUT)
led.off()


def validate_config():
    if not isinstance(SSID, str) or not SSID or SSID == "YOUR_WIFI_NAME":
        raise RuntimeError("SSID is not configured")
    if not isinstance(PASSWORD, str) or not PASSWORD:
        raise RuntimeError("PASSWORD is not configured")
    if not isinstance(HOST, str) or not HOST:
        raise RuntimeError("HOST is not configured")
    if not isinstance(SEAT_ID, str) or not SEAT_ID:
        raise RuntimeError("SEAT_ID is not configured")


def sync_led(state):
    led.value(1 if state.led_on else 0)


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


def make_boot_id():
    return "{}-{:08x}".format(
        ubinascii.hexlify(unique_id()).decode(),
        time.ticks_ms() & 0xFFFFFFFF,
    )


async def sensor_loop(state):
    next_read_at = time.ticks_ms()
    while True:
        wait_ms = time.ticks_diff(next_read_at, time.ticks_ms())
        if wait_ms > 0:
            await asyncio.sleep_ms(wait_ms)

        now_ms = time.ticks_ms()
        state.add_reading(
            sensor_1.value() != AVAILABLE_SENSOR_VALUE,
            sensor_2.value() != AVAILABLE_SENSOR_VALUE,
            now_ms,
        )
        sync_led(state)

        next_read_at = time.ticks_add(next_read_at, SAMPLE_INTERVAL_MS)
        if time.ticks_diff(time.ticks_ms(), next_read_at) >= 0:
            next_read_at = time.ticks_add(time.ticks_ms(), SAMPLE_INTERVAL_MS)


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


async def wait_for_ms(awaitable, timeout_ms):
    if hasattr(asyncio, "wait_for_ms"):
        return await asyncio.wait_for_ms(awaitable, timeout_ms)
    return await asyncio.wait_for(awaitable, timeout_ms / 1000)


async def send_message(writer, message, send_lock):
    await send_lock.acquire()
    try:
        writer.write((json.dumps(message) + "\n").encode())
        await wait_for_ms(writer.drain(), IO_TIMEOUT_MS)
    finally:
        send_lock.release()


async def close_writer(writer):
    if writer is None:
        return
    try:
        writer.close()
        if hasattr(writer, "wait_closed"):
            await writer.wait_closed()
    except (OSError, AttributeError):
        pass


def handle_server_message(state, message):
    if message.get("v") != PROTOCOL_VERSION:
        return None
    if message.get("type") != "set_active":
        return None

    now_ms = time.ticks_ms()
    command_id = message.get("command_id")
    applied = state.set_active(
        command_id,
        message.get("active"),
        message.get("duration_ms", 0),
        now_ms,
    )
    sync_led(state)
    return {
        "v": PROTOCOL_VERSION,
        "type": "set_active_result",
        "command_id": command_id,
        "applied": applied,
        "active": state.led_on,
    }


async def sample_loop(state, writer, send_lock, boot_id, errors):
    try:
        while True:
            now_ms = time.ticks_ms()
            state.expire_led(now_ms)
            sync_led(state)
            age_ms = state.last_occupied_age_ms(now_ms)
            if age_ms is not None and age_ms > MAX_OCCUPIED_AGE_MS:
                age_ms = None

            await send_message(
                writer,
                {
                    "v": PROTOCOL_VERSION,
                    "type": "seat_sample",
                    "seat_id": SEAT_ID,
                    "boot_id": boot_id,
                    "seq": state.sample_sequence,
                    "status": state.status,
                    "last_occupied_age_ms": age_ms,
                    "led_active": state.led_on,
                    "uptime_ms": uptime_ms(),
                    "free_heap_bytes": gc.mem_free(),
                },
                send_lock,
            )
            state.next_sample_sequence()
            await asyncio.sleep_ms(SAMPLE_INTERVAL_MS)
    except asyncio.CancelledError:
        raise
    except Exception as error:
        errors.append(error)


async def run_connection(state, boot_id, reconnect_attempt):
    log_runtime(
        "server_connecting",
        host=HOST,
        port=PORT,
        reconnect_attempt=reconnect_attempt,
    )
    reader, writer = await wait_for_ms(
        asyncio.open_connection(HOST, PORT), IO_TIMEOUT_MS
    )
    send_lock = asyncio.Lock()
    sample_task = None
    sample_errors = []
    started_at = time.ticks_ms()
    try:
        await send_message(
            writer,
            {
                "v": PROTOCOL_VERSION,
                "type": "register",
                "role": "seat",
                "device_id": SEAT_ID,
                "seat_id": SEAT_ID,
                "boot_id": boot_id,
                "firmware_version": FIRMWARE_VERSION,
                "build_id": BUILD_ID,
                "reconnect_attempt": reconnect_attempt,
            },
            send_lock,
        )
        line = await wait_for_ms(reader.readline(), IO_TIMEOUT_MS)
        if not line:
            raise RuntimeError("server disconnected before register_ack")
        response = json.loads(line)
        if (
            response.get("v") != PROTOCOL_VERSION
            or response.get("type") != "register_ack"
            or response.get("accepted") is not True
        ):
            raise RuntimeError(
                "seat registration rejected: {}".format(
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
            "seat_registered",
            seat_id=SEAT_ID,
            server_build=response.get("server_build_id"),
        )
        sample_task = asyncio.create_task(
            sample_loop(
                state,
                writer,
                send_lock,
                boot_id,
                sample_errors,
            )
        )
        heartbeat = HeartbeatMonitor(MAX_HEARTBEAT_FAILURES)
        ping_id = 0
        pending_ping_id = None
        while True:
            if sample_errors:
                raise sample_errors[0]
            try:
                line = await wait_for_ms(
                    reader.readline(), HEARTBEAT_INTERVAL_MS
                )
            except asyncio.TimeoutError:
                if heartbeat.miss():
                    raise RuntimeError("three heartbeat failures")
                ping_id += 1
                pending_ping_id = ping_id
                await send_message(
                    writer,
                    {
                        "v": PROTOCOL_VERSION,
                        "type": "ping",
                        "ping_id": ping_id,
                        "uptime_ms": uptime_ms(),
                        "free_heap_bytes": gc.mem_free(),
                    },
                    send_lock,
                )
                continue
            if not line:
                raise RuntimeError("server disconnected")
            try:
                message = json.loads(line)
            except ValueError:
                continue
            if (
                message.get("v") == PROTOCOL_VERSION
                and message.get("type") == "pong"
                and message.get("ping_id") == pending_ping_id
            ):
                heartbeat.acknowledge()
                pending_ping_id = None
                continue
            if (
                message.get("v") == PROTOCOL_VERSION
                and message.get("type") == "ping"
            ):
                await send_message(
                    writer,
                    {
                        "v": PROTOCOL_VERSION,
                        "type": "pong",
                        "ping_id": message.get("ping_id"),
                    },
                    send_lock,
                )
                heartbeat.acknowledge()
                continue
            response = handle_server_message(state, message)
            if response is not None:
                await send_message(writer, response, send_lock)
                heartbeat.acknowledge()
    finally:
        if sample_task is not None:
            sample_task.cancel()
            try:
                await sample_task
            except asyncio.CancelledError:
                pass
        await close_writer(writer)
    return time.ticks_diff(time.ticks_ms(), started_at)


async def communication_loop(state, boot_id):
    wifi = network.WLAN(network.STA_IF)
    backoff = ReconnectBackoff(
        RECONNECT_BACKOFF_MS, HEALTHY_SESSION_MS
    )
    while True:
        session_started_at = time.ticks_ms()
        try:
            if not wifi.isconnected():
                await connect_wifi(wifi)
            session_started_at = time.ticks_ms()
            await run_connection(state, boot_id, backoff.attempt)
        except Exception as error:
            session_ms = time.ticks_diff(
                time.ticks_ms(), session_started_at
            )
            gc.collect()
            backoff.record_session(session_ms)
            delay_ms = backoff.next_delay_ms(time.ticks_ms())
            log_runtime(
                "connection_error",
                error=str(error),
                reconnect_attempt=backoff.attempt,
                session_ms=session_ms,
                delay_ms=delay_ms,
            )
            await asyncio.sleep_ms(delay_ms)


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
    state = SeatState(time.ticks_diff, time.ticks_add)
    boot_id = make_boot_id()
    log_runtime(
        "boot",
        role="seat",
        device_id=SEAT_ID,
        boot_id=boot_id,
        firmware_version=FIRMWARE_VERSION,
        build_id=BUILD_ID,
        reset_cause=machine.reset_cause(),
        sensors="GPIO{}/GPIO{}".format(SENSOR_1_PIN, SENSOR_2_PIN),
        led="GPIO{}".format(LED_PIN),
    )
    tasks = [
        asyncio.create_task(
            supervise(
                "sensor_loop",
                lambda: sensor_loop(state),
                True,
            )
        ),
        asyncio.create_task(
            supervise(
                "communication_loop",
                lambda: communication_loop(state, boot_id),
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
