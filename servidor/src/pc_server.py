import json
import socket
import threading


HOST = "0.0.0.0"
PORT = 5000
SEAT_REQUEST_TIMEOUT_SECONDS = 1.0
STATUS_OCCUPIED = "ocupado"
STATUS_AVAILABLE = "disponível"

seats = {}
seats_lock = threading.Lock()
request_id_lock = threading.Lock()
next_request_id = 1


class SeatRequestError(Exception):
    pass


class SeatRequestTimeout(SeatRequestError):
    pass


class PendingResponse:
    def __init__(self, expected_type):
        self.expected_type = expected_type
        self.event = threading.Event()
        self.response = None
        self.error = None


def allocate_request_id():
    global next_request_id

    with request_id_lock:
        request_id = next_request_id
        next_request_id += 1
    return request_id


class ClientConnection:
    def __init__(self, connection, address):
        self.connection = connection
        self.address = address
        self.seat_id = None
        self.send_lock = threading.Lock()
        self.transaction_lock = threading.Lock()
        self.pending_lock = threading.Lock()
        self.pending = {}
        self.closed = False

    def send(self, message):
        payload = (json.dumps(message, ensure_ascii=False) + "\n").encode()
        with self.send_lock:
            if self.closed:
                raise OSError("connection is closed")
            self.connection.sendall(payload)

    def request(self, message_type, expected_type, **fields):
        request_id = allocate_request_id()
        pending = PendingResponse(expected_type)
        message = {
            "type": message_type,
            "request_id": request_id,
        }
        message.update(fields)

        with self.pending_lock:
            if self.closed:
                raise SeatRequestError("seat connection is closed")
            self.pending[request_id] = pending

        try:
            self.send(message)
        except OSError as error:
            with self.pending_lock:
                self.pending.pop(request_id, None)
            raise SeatRequestError(str(error)) from error

        if not pending.event.wait(SEAT_REQUEST_TIMEOUT_SECONDS):
            with self.pending_lock:
                self.pending.pop(request_id, None)
            raise SeatRequestTimeout(
                f"timeout waiting for {expected_type} from {self.address}"
            )

        if pending.error is not None:
            raise SeatRequestError(str(pending.error))
        return pending.response

    def deliver_response(self, message):
        request_id = message.get("request_id")
        if request_id is None:
            print(f"Resposta sem request_id de {self.address}: {message}")
            return False

        with self.pending_lock:
            pending = self.pending.pop(request_id, None)

        if pending is None:
            print(
                f"Resposta inesperada ou atrasada de {self.address}: {message}"
            )
            return False

        if message.get("type") != pending.expected_type:
            pending.error = SeatRequestError(
                "expected {}, received {}".format(
                    pending.expected_type, message.get("type")
                )
            )
        else:
            pending.response = message
        pending.event.set()
        return True

    def fail_pending(self, error):
        with self.pending_lock:
            pending_responses = list(self.pending.values())
            self.pending.clear()

        for pending in pending_responses:
            pending.error = error
            pending.event.set()

    def close(self):
        with self.pending_lock:
            if self.closed:
                return
            self.closed = True

        try:
            self.connection.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            self.connection.close()
        except OSError:
            pass

        self.fail_pending(SeatRequestError("seat connection closed"))


def register_seat(client, message):
    seat_id = message.get("seat_id")
    if not isinstance(seat_id, str) or not seat_id:
        raise ValueError("seat_register sem seat_id valido")

    old_client = None
    client.seat_id = seat_id

    with seats_lock:
        previous = seats.get(seat_id)
        if previous is not None and previous is not client:
            old_client = previous
        seats[seat_id] = client

    if old_client is not None:
        old_client.close()

    print(f"Assento registrado: {seat_id} ({client.address})")
    return seat_id


def remove_seat(seat_id, client):
    if seat_id is None:
        return

    with seats_lock:
        current = seats.get(seat_id)
        if current is client:
            del seats[seat_id]
            print(f"Assento desconectado: {seat_id}")


def get_registered_seats():
    with seats_lock:
        return [(seat_id, seats[seat_id]) for seat_id in sorted(seats)]


def activate_available_seat():
    for seat_id, client in get_registered_seats():
        try:
            with client.transaction_lock:
                status_response = client.request(
                    "get_status",
                    "seat_status",
                )
                status = status_response.get("status")

                if status == STATUS_OCCUPIED:
                    print(f"Assento {seat_id}: ocupado")
                    continue
                if status != STATUS_AVAILABLE:
                    raise SeatRequestError(
                        f"status invalido de {seat_id}: {status!r}"
                    )

                led_response = client.request(
                    "set_led",
                    "set_led_result",
                    value=1,
                )
                if led_response.get("accepted") is True:
                    print(f"LED ativado no assento {seat_id}")
                    return seat_id

                print(f"Assento {seat_id} recusou a ativacao do LED")
        except (OSError, SeatRequestError) as error:
            print(f"Falha ao consultar {seat_id}: {error}")
            remove_seat(seat_id, client)
            client.close()

    return None


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


def read_json_line(response_file, address):
    line = response_file.readline()
    if not line:
        return None

    try:
        return json.loads(line)
    except ValueError as error:
        raise ValueError(f"JSON invalido de {address}: {error}") from error


def handle_client(connection, address):
    client = ClientConnection(connection, address)
    response_file = connection.makefile("r", encoding="utf-8")
    role = None
    seat_id = None
    print(f"Dispositivo conectado: {address}")

    try:
        while True:
            message = read_json_line(response_file, address)
            if message is None:
                break

            if role is None:
                if message.get("type") == "seat_register":
                    role = "seat"
                    seat_id = register_seat(client, message)
                    continue
                role = "nfc"

            if role == "seat":
                client.deliver_response(message)
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
