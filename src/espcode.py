## CODIGO NO ESP 32
import network
import socket
import json
import time

# ==========================
# Wi-Fi configuration
# ==========================

SSID = "YOUR_WIFI_NAME"
PASSWORD = "YOUR_WIFI_PASSWORD"

# PC IP address
HOST = "192.168.0.105" # Mudar para o IP do seu PC
PORT = 5000


# ==========================
# Connect to Wi-Fi
# ==========================

wifi = network.WLAN(network.STA_IF)
wifi.active(True)

if not wifi.isconnected():
    print("Connecting to Wi-Fi...")
    wifi.connect(SSID, PASSWORD)

    while not wifi.isconnected():
        time.sleep(1)

print("Connected!")
print("ESP32 IP:", wifi.ifconfig()[0])


# ==========================
# Connect to PC
# ==========================

while True:

    try:

        print("Connecting to PC...")

        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.connect((HOST, PORT))

        print("Connected!")

        file = s.makefile("r")

        counter = 0

        while True:

            # Send data
            message = {
                "counter": counter,
                "temperature": 24.5,
                "humidity": 70
            }

            s.send((json.dumps(message) + "\n").encode())

            print("Sent:", message)

            # Wait for PC response
            response = file.readline()

            if not response:
                raise Exception("Disconnected")

            response = json.loads(response)

            print("Received:", response)

            counter += 1

            time.sleep(2)

    except Exception as e:

        print("Connection lost:", e)

        try:
            s.close()
        except:
            pass

        time.sleep(5)
