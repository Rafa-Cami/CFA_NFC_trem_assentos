import json
import socket
import time

import network
from machine import Pin

try:
    from esp_config import HOST, PASSWORD, SEAT_ID, SSID
except ImportError:
    raise RuntimeError(
        "Missing esp_config.py. Copy esp_config.example.py and configure it."
    )


PORT = 5000
SENSOR_PIN = 10
LED_PIN = 5
AVAILABLE_SENSOR_VALUE = 0
POLL_INTERVAL_MS = 50
STATUS_HEARTBEAT_MS = 10000
RECONNECT_DELAY_SECONDS = 3
WIFI_CONNECT_TIMEOUT_MS = 20000
WIFI_RETRY_DELAY_MS = 2000

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


sensor = Pin(SENSOR_PIN, Pin.IN)
led = Pin(LED_PIN, Pin.OUT)
led.off()


def is_available():
    return sensor.value() == AVAILABLE_SENSOR_VALUE


def wifi_status_text(wifi):
    status = wifi.status()
    return "{} ({})".format(status, WIFI_STATUS_NAMES.get(status, "unknown"))


def reset_wifi(wifi):
    try:
        wifi.disconnect()
    except OSError:
        pass

    wifi.active(False)
    time.sleep_ms(1000)
    wifi.active(True)
    time.sleep_ms(1000)


def find_target_network(wifi, ssid):
    try:
        networks = wifi.scan()
    except OSError as error:
        print("Wi-Fi scan failed:", error)
        return None

    matches = [network_data for network_data in networks if network_data[0] == ssid]
    if not matches:
        print("Configured Wi-Fi not found; visible networks:", len(networks))
        return None

    target = max(matches, key=lambda network_data: network_data[3])
    print(
        "Wi-Fi found: channel={}, signal={} dBm, security={}".format(
            target[2], target[3], target[4]
        )
    )
    return target


def connect_wifi():
    ssid = SSID
    password = PASSWORD
    if not isinstance(ssid, str) or not ssid or ssid == "YOUR_WIFI_NAME":
        raise RuntimeError("SSID is not configured in esp_config.py")
    if (
        not isinstance(password, str)
        or not password
        or password == "YOUR_WIFI_PASSWORD"
    ):
        raise RuntimeError("PASSWORD is not configured in esp_config.py")

    wifi = network.WLAN(network.STA_IF)
    ssid_bytes = ssid.encode()
    attempt = 0

    while not wifi.isconnected():
        attempt += 1
        print("Wi-Fi attempt", attempt)
        reset_wifi(wifi)
        target = find_target_network(wifi, ssid_bytes)

        if target is None:
            time.sleep_ms(WIFI_RETRY_DELAY_MS)
            continue

        try:
            if attempt % 2 == 1:
                print("Connecting with strongest access point...")
                wifi.connect(ssid, password, bssid=target[1])
            else:
                print("Connecting by SSID...")
                wifi.connect(ssid, password)
        except (OSError, TypeError) as error:
            print("Wi-Fi connect call failed:", error)
            time.sleep_ms(WIFI_RETRY_DELAY_MS)
            continue

        started_at = time.ticks_ms()
        while not wifi.isconnected() and time.ticks_diff(
            time.ticks_ms(), started_at
        ) < WIFI_CONNECT_TIMEOUT_MS:
            time.sleep_ms(250)

        if not wifi.isconnected():
            print("Wi-Fi attempt failed:", wifi_status_text(wifi))
            time.sleep_ms(WIFI_RETRY_DELAY_MS)

    print("Connected to Wi-Fi")
    print("Seat ESP IP:", wifi.ifconfig()[0])
    return wifi


def connect_server():
    print("Connecting to server {}:{}...".format(HOST, PORT))
    connection = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    connection.connect((HOST, PORT))
    connection.settimeout(0.1)
    print("Connected to server as", SEAT_ID)
    return connection


def send_message(connection, message):
    connection.send((json.dumps(message) + "\n").encode())


def send_status(connection, available, led_on):
    message = {
        "type": "seat_status",
        "seat_id": SEAT_ID,
        "available": available,
        "led": 1 if led_on else 0,
    }
    send_message(connection, message)
    print("Status sent:", message)


def handle_command(connection, message, available, led_on):
    if message.get("type") != "set_led":
        print("Unknown command:", message)
        return led_on

    requested = message.get("value") == 1
    led_on = requested and available
    led.value(1 if led_on else 0)
    print("LED ON" if led_on else "LED OFF")
    send_status(connection, available, led_on)
    return led_on


def run_connection(connection, wifi):
    available = is_available()
    led_on = False
    led.off()
    receive_buffer = b""
    last_status_at = time.ticks_ms()
    send_status(connection, available, led_on)

    while True:
        if not wifi.isconnected():
            raise RuntimeError("Wi-Fi disconnected")

        current_available = is_available()
        if current_available != available:
            available = current_available
            if not available and led_on:
                led_on = False
                led.off()
                print("Seat occupied; LED OFF")
            send_status(connection, available, led_on)
            last_status_at = time.ticks_ms()

        now = time.ticks_ms()
        if time.ticks_diff(now, last_status_at) >= STATUS_HEARTBEAT_MS:
            send_status(connection, available, led_on)
            last_status_at = now

        try:
            data = connection.recv(256)
            if not data:
                raise RuntimeError("Server disconnected")
            receive_buffer += data
        except OSError:
            data = None

        while b"\n" in receive_buffer:
            line, receive_buffer = receive_buffer.split(b"\n", 1)
            if not line:
                continue
            try:
                message = json.loads(line)
                led_on = handle_command(connection, message, available, led_on)
                last_status_at = time.ticks_ms()
            except ValueError as error:
                print("Invalid server message:", error)

        time.sleep_ms(POLL_INTERVAL_MS)


def main():
    print("Starting seat controller", SEAT_ID)
    print("Sensor GPIO{}, LED GPIO{}".format(SENSOR_PIN, LED_PIN))
    wifi = connect_wifi()

    while True:
        connection = None
        try:
            if not wifi.isconnected():
                wifi = connect_wifi()
            connection = connect_server()
            run_connection(connection, wifi)
        except Exception as error:
            print("Connection error:", error)
            led.off()
        finally:
            if connection is not None:
                try:
                    connection.close()
                except OSError:
                    pass
        time.sleep(RECONNECT_DELAY_SECONDS)


if __name__ == "__main__":
    main()
