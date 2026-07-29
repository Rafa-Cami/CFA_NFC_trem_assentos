import json
import time

import network
import uasyncio as asyncio
from machine import Pin

from seat_state import (
    LED_ACTIVATED,
    LED_ALREADY_ACTIVE,
    LED_DEACTIVATED,
    SeatState,
)

try:
    from esp_config import HOST, PASSWORD, SEAT_ID, SSID
except ImportError:
    raise RuntimeError(
        "Missing esp_config.py. Copy esp_config.example.py and configure it."
    )


PORT = 5000
SENSOR_1_PIN = 10
SENSOR_2_PIN = 7
LED_PIN = 5
AVAILABLE_SENSOR_VALUE = 0
SENSOR_INTERVAL_MS = 500
WINDOW_SIZE = 10
RECONNECT_DELAY_SECONDS = 3
WIFI_CONNECT_TIMEOUT_MS = 20000
WIFI_RETRY_DELAY_MS = 2000
LED_ON_DURATION_MS = 10000
LED_TIMER_INTERVAL_MS = 50

WIFI_STATUS_NAMES = {
    -3: "wrong password",
    -2: "access point not found",
    -1: "connection failed",
    0: "idle",
    1: "connecting",
    3: "connected",
    201: "access point not found",
    202: "authentication rejected",
    1001: "connecting",
}


sensor_1 = Pin(SENSOR_1_PIN, Pin.IN)
sensor_2 = Pin(SENSOR_2_PIN, Pin.IN)
led = Pin(LED_PIN, Pin.OUT)
led.off()


def validate_config():
    if not isinstance(SSID, str) or not SSID or SSID == "YOUR_WIFI_NAME":
        raise RuntimeError("SSID is not configured in esp_config.py")
    if (
        not isinstance(PASSWORD, str)
        or not PASSWORD
        or PASSWORD == "YOUR_WIFI_PASSWORD"
    ):
        raise RuntimeError("PASSWORD is not configured in esp_config.py")
    if not isinstance(HOST, str) or not HOST:
        raise RuntimeError("HOST is not configured in esp_config.py")
    if not isinstance(SEAT_ID, str) or not SEAT_ID:
        raise RuntimeError("SEAT_ID is not configured in esp_config.py")


def wifi_status_text(wifi):
    status = wifi.status()
    return "{} ({})".format(status, WIFI_STATUS_NAMES.get(status, "unknown"))


def sync_led(state):
    led.value(1 if state.led_on else 0)


async def sensor_loop(state, pending_events):
    next_read_at = time.ticks_add(time.ticks_ms(), SENSOR_INTERVAL_MS)

    while True:
        wait_ms = time.ticks_diff(next_read_at, time.ticks_ms())
        if wait_ms > 0:
            await asyncio.sleep_ms(wait_ms)

        sensor_1_occupied = sensor_1.value() != AVAILABLE_SENSOR_VALUE
        sensor_2_occupied = sensor_2.value() != AVAILABLE_SENSOR_VALUE
        led_was_on = state.led_on
        state.add_reading(sensor_1_occupied, sensor_2_occupied)
        sync_led(state)

        if led_was_on and not state.led_on:
            print("LED OFF because seat became occupied")
            pending_events.append(
                {
                    "type": "seat_led_state",
                    "seat_id": SEAT_ID,
                    "led_on": False,
                    "reason": "occupied",
                }
            )

        next_read_at = time.ticks_add(next_read_at, SENSOR_INTERVAL_MS)
        if time.ticks_diff(time.ticks_ms(), next_read_at) >= 0:
            next_read_at = time.ticks_add(time.ticks_ms(), SENSOR_INTERVAL_MS)


async def connect_wifi(wifi):
    attempt = 0

    while not wifi.isconnected():
        attempt += 1
        print("Wi-Fi attempt", attempt)

        try:
            wifi.active(True)
            wifi.disconnect()
        except OSError:
            pass

        await asyncio.sleep_ms(250)

        try:
            wifi.connect(SSID, PASSWORD)
        except OSError as error:
            print("Wi-Fi connect call failed:", error)
            await asyncio.sleep_ms(WIFI_RETRY_DELAY_MS)
            continue

        started_at = time.ticks_ms()
        while not wifi.isconnected() and time.ticks_diff(
            time.ticks_ms(), started_at
        ) < WIFI_CONNECT_TIMEOUT_MS:
            await asyncio.sleep_ms(250)

        if not wifi.isconnected():
            print("Wi-Fi attempt failed:", wifi_status_text(wifi))
            await asyncio.sleep_ms(WIFI_RETRY_DELAY_MS)

    print("Connected to Wi-Fi")
    print("Seat ESP IP:", wifi.ifconfig()[0])


async def led_timer_loop(state, pending_events):
    while True:
        if state.expire_led(time.ticks_ms(), time.ticks_diff):
            sync_led(state)
            print("LED OFF after 10 seconds")
            pending_events.append(
                {
                    "type": "seat_led_state",
                    "seat_id": SEAT_ID,
                    "led_on": False,
                    "reason": "timeout",
                }
            )
        await asyncio.sleep_ms(LED_TIMER_INTERVAL_MS)


async def send_message(writer, message, send_lock):
    async with send_lock:
        writer.write((json.dumps(message) + "\n").encode())
        await writer.drain()


async def event_sender_loop(writer, send_lock, pending_events):
    while True:
        if pending_events:
            message = pending_events[0]
            await send_message(writer, message, send_lock)
            pending_events.pop(0)
            continue
        await asyncio.sleep_ms(LED_TIMER_INTERVAL_MS)


def handle_server_message(state, message):
    message_type = message.get("type")
    request_id = message.get("request_id")

    if message_type == "get_status" and request_id is not None:
        return {
            "type": "seat_status",
            "request_id": request_id,
            "status": state.status,
            "led_on": state.led_on,
            "led_remaining_ms": state.led_remaining_ms(
                time.ticks_ms(),
                time.ticks_diff,
            ),
        }

    if message_type == "set_led" and request_id is not None:
        value = message.get("value")
        deadline_ms = None
        if value == 1:
            deadline_ms = time.ticks_add(
                time.ticks_ms(),
                LED_ON_DURATION_MS,
            )
        result = state.set_led(value, deadline_ms)
        sync_led(state)
        if result == LED_ACTIVATED:
            print("LED ON for 10 seconds")
        elif result == LED_ALREADY_ACTIVE:
            print("LED already active; timer unchanged")
        elif result == LED_DEACTIVATED:
            print("LED OFF")
        else:
            print("LED command rejected:", result)
        return {
            "type": "set_led_result",
            "request_id": request_id,
            "accepted": result in (LED_ACTIVATED, LED_DEACTIVATED),
            "result": result,
            "led_on": state.led_on,
            "led_remaining_ms": state.led_remaining_ms(
                time.ticks_ms(),
                time.ticks_diff,
            ),
        }

    print("Unknown or invalid command:", message)
    return {
        "type": "error",
        "request_id": request_id,
        "error": "invalid_command",
    }


async def close_writer(writer):
    if writer is None:
        return

    try:
        writer.close()
        if hasattr(writer, "wait_closed"):
            await writer.wait_closed()
    except OSError:
        pass


async def run_connection(state, pending_events):
    print("Connecting to server {}:{}...".format(HOST, PORT))
    reader, writer = await asyncio.open_connection(HOST, PORT)
    print("Connected to server as", SEAT_ID)
    send_lock = asyncio.Lock()
    event_sender = None

    try:
        await send_message(
            writer,
            {
                "type": "seat_register",
                "seat_id": SEAT_ID,
            },
            send_lock,
        )
        print("Seat registered as", SEAT_ID)
        event_sender = asyncio.create_task(
            event_sender_loop(writer, send_lock, pending_events)
        )

        while True:
            line = await reader.readline()
            if not line:
                raise RuntimeError("Server disconnected")

            try:
                message = json.loads(line)
            except ValueError as error:
                print("Invalid server message:", error)
                continue

            response = handle_server_message(state, message)
            await send_message(writer, response, send_lock)
    finally:
        if event_sender is not None:
            event_sender.cancel()
        await close_writer(writer)


async def communication_loop(state, pending_events):
    wifi = network.WLAN(network.STA_IF)

    while True:
        try:
            if not wifi.isconnected():
                await connect_wifi(wifi)
            await run_connection(state, pending_events)
        except Exception as error:
            print("Connection error:", error)
            state.set_led(0)
            sync_led(state)
            await asyncio.sleep(RECONNECT_DELAY_SECONDS)


async def main_async():
    validate_config()
    state = SeatState(WINDOW_SIZE)
    pending_events = []

    print("Starting seat controller", SEAT_ID)
    print(
        "Sensors GPIO{} and GPIO{}, LED GPIO{}".format(
            SENSOR_1_PIN, SENSOR_2_PIN, LED_PIN
        )
    )

    asyncio.create_task(sensor_loop(state, pending_events))
    asyncio.create_task(led_timer_loop(state, pending_events))
    await communication_loop(state, pending_events)


def main():
    try:
        asyncio.run(main_async())
    finally:
        asyncio.new_event_loop()


if __name__ == "__main__":
    main()
