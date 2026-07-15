import json
import socket
import threading


HOST = "0.0.0.0"
PORT = 5000

seats = {}
seats_lock = threading.Lock()


class ClientConnection:
    def __init__(self, connection, address):
        self.connection = connection
        self.address = address
        self.send_lock = threading.Lock()

    def send(self, message):
        payload = (json.dumps(message) + "\n").encode()
        with self.send_lock:
            self.connection.sendall(payload)

    def close(self):
        try:
            self.connection.close()
        except OSError:
            pass


def update_seat_status(client, message):
    seat_id = message.get("seat_id")
    if not isinstance(seat_id, str) or not seat_id:
        raise ValueError("seat_status sem seat_id valido")

    available = message.get("available") is True
    led_on = message.get("led") == 1
    old_client = None

    with seats_lock:
        previous = seats.get(seat_id)
        if previous is not None and previous["client"] is not client:
            old_client = previous["client"]

        reserved = led_on
        if previous is not None and previous["client"] is client:
            reserved = previous["reserved"] or led_on
            if not available:
                reserved = False
            elif not previous["available"] and available and not led_on:
                reserved = False

        seats[seat_id] = {
            "client": client,
            "available": available,
            "led": led_on,
            "reserved": reserved,
        }

    if old_client is not None:
        old_client.close()

    state = "livre" if available else "ocupado"
    print(f"Assento {seat_id}: {state}, LED={int(led_on)}")
    return seat_id


def remove_seat(seat_id, client):
    if seat_id is None:
        return

    with seats_lock:
        current = seats.get(seat_id)
        if current is not None and current["client"] is client:
            del seats[seat_id]
            print(f"Assento desconectado: {seat_id}")


def activate_available_seat():
    while True:
        with seats_lock:
            candidates = sorted(
                seat_id
                for seat_id, state in seats.items()
                if state["available"] and not state["reserved"]
            )

            if not candidates:
                return None

            seat_id = candidates[0]
            state = seats[seat_id]
            state["reserved"] = True
            client = state["client"]

        try:
            client.send({"type": "set_led", "seat_id": seat_id, "value": 1})
            print(f"LED solicitado para o assento {seat_id}")
            return seat_id
        except OSError as error:
            print(f"Falha ao comandar {seat_id}: {error}")
            remove_seat(seat_id, client)
            client.close()


def handle_nfc_message(message):
    nfc_keys = [key for key in message if key.startswith("nfc_")]
    if not nfc_keys:
        return {
            "status": "invalid_message",
            "received": message,
        }

    for key in nfc_keys:
        print(f"NFC recebido: {key} = {message[key]}")

    seat_id = activate_available_seat()
    if seat_id is None:
        print("Nenhum assento livre conectado")
        return {
            "status": "no_available_seat",
            "received": message,
        }

    return {
        "status": "ok",
        "received": message,
        "seat_id": seat_id,
        "led": 1,
    }


def handle_client(connection, address):
    client = ClientConnection(connection, address)
    response_file = connection.makefile("r")
    seat_id = None
    print(f"Dispositivo conectado: {address}")

    try:
        while True:
            line = response_file.readline()
            if not line:
                break

            try:
                message = json.loads(line)
            except (ValueError, json.JSONDecodeError) as error:
                print(f"JSON invalido de {address}: {error}")
                continue

            if message.get("type") == "seat_status":
                seat_id = update_seat_status(client, message)
                continue

            response = handle_nfc_message(message)
            client.send(response)

    except (OSError, ValueError) as error:
        print(f"Erro com {address}: {error}")
    finally:
        remove_seat(seat_id, client)
        try:
            response_file.close()
        except OSError:
            pass
        client.close()
        print(f"Dispositivo desconectado: {address}")


def main():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((HOST, PORT))
    server.listen(8)
    print(f"Servidor ouvindo na porta {PORT}")

    try:
        while True:
            connection, address = server.accept()
            thread = threading.Thread(
                target=handle_client,
                args=(connection, address),
                daemon=True,
            )
            thread.start()
    except KeyboardInterrupt:
        print("Servidor encerrado")
    finally:
        server.close()


if __name__ == "__main__":
    main()
