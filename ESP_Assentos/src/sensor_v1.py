import json
import time
import ubinascii

import network
import uasyncio as asyncio
from machine import Pin, unique_id

from seat_state import SeatState

try:
    from esp_config import HOST, PASSWORD, SEAT_ID, SSID
except ImportError:
    raise RuntimeError(
        "Missing esp_config.py. Copy esp_config.example.py and configure it."
    )


PROTOCOL_VERSION = 1
PORT = 5000
SENSOR_1_PIN = 10
SENSOR_2_PIN = 7
LED_PIN = 5
AVAILABLE_SENSOR_VALUE = 0
SAMPLE_INTERVAL_MS = 500
RECONNECT_DELAY_MS = 1000
WIFI_CONNECT_TIMEOUT_MS = 20000
WIFI_RETRY_DELAY_MS = 2000
MAX_OCCUPIED_AGE_MS = 5000

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
            await asyncio.sleep_ms(WIFI_RETRY_DELAY_MS)
            continue

        started_at = time.ticks_ms()
        while (
            not wifi.isconnected()
            and time.ticks_diff(time.ticks_ms(), started_at)
            < WIFI_CONNECT_TIMEOUT_MS
        ):
            await asyncio.sleep_ms(250)

        if not wifi.isconnected():
            print("Wi-Fi unavailable, retrying")
            await asyncio.sleep_ms(WIFI_RETRY_DELAY_MS)

    print("Wi-Fi connected:", wifi.ifconfig()[0])


async def send_message(writer, message, send_lock):
    await send_lock.acquire()
    try:
        writer.write((json.dumps(message) + "\n").encode())
        await writer.drain()
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


async def sample_loop(state, writer, send_lock, boot_id):
    sequence = 0
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
                "seq": sequence,
                "status": state.status,
                "last_occupied_age_ms": age_ms,
                "led_active": state.led_on,
            },
            send_lock,
        )
        sequence += 1
        await asyncio.sleep_ms(SAMPLE_INTERVAL_MS)


async def run_connection(state, boot_id):
    print("Connecting to {}:{} as {}".format(HOST, PORT, SEAT_ID))
    reader, writer = await asyncio.open_connection(HOST, PORT)
    send_lock = asyncio.Lock()
    sample_task = None
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
            },
            send_lock,
        )
        line = await reader.readline()
        if not line:
            raise RuntimeError("server disconnected before register_ack")
        response = json.loads(line)
        if (
            response.get("v") != PROTOCOL_VERSION
            or response.get("type") != "register_ack"
            or response.get("accepted") is not True
        ):
            raise RuntimeError("seat registration rejected")

        print("Seat registered:", SEAT_ID)
        sample_task = asyncio.create_task(
            sample_loop(state, writer, send_lock, boot_id)
        )
        while True:
            line = await reader.readline()
            if not line:
                raise RuntimeError("server disconnected")
            try:
                message = json.loads(line)
            except ValueError:
                continue
            response = handle_server_message(state, message)
            if response is not None:
                await send_message(writer, response, send_lock)
    finally:
        if sample_task is not None:
            sample_task.cancel()
            try:
                await sample_task
            except asyncio.CancelledError:
                pass
        await close_writer(writer)


async def communication_loop(state, boot_id):
    wifi = network.WLAN(network.STA_IF)
    while True:
        try:
            if not wifi.isconnected():
                await connect_wifi(wifi)
            await run_connection(state, boot_id)
        except Exception as error:
            print("Connection error:", error)
            await asyncio.sleep_ms(RECONNECT_DELAY_MS)


async def main_async():
    validate_config()
    state = SeatState(time.ticks_diff, time.ticks_add)
    boot_id = make_boot_id()
    print("Seat {}, sensors GPIO{}/GPIO{}, LED GPIO{}".format(
        SEAT_ID, SENSOR_1_PIN, SENSOR_2_PIN, LED_PIN
    ))
    sensor_task = asyncio.create_task(sensor_loop(state))
    try:
        await communication_loop(state, boot_id)
    finally:
        sensor_task.cancel()


def main():
    try:
        asyncio.run(main_async())
    finally:
        asyncio.new_event_loop()


if __name__ == "__main__":
    main()
