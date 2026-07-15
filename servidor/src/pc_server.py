#########################################################################################################
## CODIGO NO PC

import json
import socket


HOST = "0.0.0.0"
PORT = 5000


def handle_message(message):
    nfc_keys = [key for key in message if key.startswith("nfc_")]

    if nfc_keys:
        for key in nfc_keys:
            print(f"NFC recebido: {key} = {message[key]}")
    else:
        print("Mensagem recebida:", message)

    return {
        "status": "ok",
        "received": message,
    }


def main():
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

                try:
                    message = json.loads(line)
                except json.JSONDecodeError as error:
                    print("JSON invalido:", error)
                    continue

                print("Received:", message)
                response = handle_message(message)
                conn.send((json.dumps(response) + "\n").encode())

        except Exception as error:
            print("Error:", error)

        finally:
            conn.close()
            print("ESP32 disconnected")


if __name__ == "__main__":
    main()
