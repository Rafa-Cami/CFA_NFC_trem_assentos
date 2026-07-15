#########################################################################################################
## CODIGO NO PC 

import socket
import json

HOST = "0.0.0.0"
PORT = 5000

server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

server.bind((HOST, PORT))

server.listen(1)

print(f"Server listening on port {PORT}")

while True:

    conn, addr = server.accept()

    print(f"\nESP32 connected: {addr}")

    file = conn.makefile("r")

    try:

        while True:

            line = file.readline()

            if not line:
                break

            message = json.loads(line)

            print("Received:", message)

            response = {
                "status": "ok",
                "received_counter": message["counter"]
            }

            conn.send((json.dumps(response) + "\n").encode())

    except Exception as e:

        print("Error:", e)

    finally:

        conn.close()

        print("ESP32 disconnected")