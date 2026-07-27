import collections
import json
import socket
import threading
import time


HOST = "0.0.0.0"
PORT = 5000
PROTOCOL_VERSION = 1
MAX_FRAME_BYTES = 512
SEAT_REQUEST_TIMEOUT_SECONDS = 2.0
SEAT_SAMPLE_TIMEOUT_SECONDS = 1.5
SEAT_MONITOR_INTERVAL_SECONDS = 0.1
OCCUPANCY_TTL_SECONDS = 5.0
ACTIVE_DURATION_MS = 5000
NFC_EVENT_MAX_AGE_MS = 30000
NFC_CACHE_SECONDS = 300.0
NFC_CACHE_MAX_ENTRIES = 256

STATUS_OCCUPIED = "OCUPADO"
STATUS_AVAILABLE = "DISPONIVEL"
VALID_SEAT_STATUSES = (STATUS_OCCUPIED, STATUS_AVAILABLE)

seats = {}
seats_lock = threading.RLock()
nfc_clients = {}
nfc_clients_lock = threading.Lock()
activation_lock = threading.Lock()
command_id_lock = threading.Lock()
next_command_id = 1
nfc_cache = collections.OrderedDict()
nfc_cache_lock = threading.Lock()


class SeatRequestError(Exception):
    pass


class SeatRequestTimeout(SeatRequestError):
    pass


class PendingResponse:
    def __init__(self):
        self.event = threading.Event()
        self.response = None
        self.error = None


def allocate_command_id(prefix="cmd"):
    global next_command_id
    with command_id_lock:
        value = next_command_id
        next_command_id += 1
    return "{}:{}".format(prefix, value)


class ClientConnection:
    def __init__(self, connection, address):
        self.connection = connection
        self.address = address
        self.seat_id = None
        self.device_id = None
        self.boot_id = None
        self.send_lock = threading.Lock()
        self.pending_lock = threading.Lock()
        self.pending = {}
        self.closed = False

    def send(self, message):
        payload = (
            json.dumps(message, ensure_ascii=False, separators=(",", ":"))
            + "\n"
        ).encode("utf-8")
        if len(payload) > MAX_FRAME_BYTES:
            raise ValueError("outgoing frame exceeds maximum size")
        with self.send_lock:
            if self.closed:
                raise OSError("connection is closed")
            self.connection.sendall(payload)

    def request(self, active, duration_ms, command_id=None):
        command_id = command_id or allocate_command_id("led")
        pending = PendingResponse()
        with self.pending_lock:
            if self.closed:
                raise SeatRequestError("seat connection is closed")
            self.pending[command_id] = pending

        try:
            self.send(
                {
                    "v": PROTOCOL_VERSION,
                    "type": "set_active",
                    "command_id": command_id,
                    "active": bool(active),
                    "duration_ms": int(duration_ms),
                }
            )
        except (OSError, ValueError) as error:
            with self.pending_lock:
                self.pending.pop(command_id, None)
            raise SeatRequestError(str(error)) from error

        if not pending.event.wait(SEAT_REQUEST_TIMEOUT_SECONDS):
            with self.pending_lock:
                self.pending.pop(command_id, None)
            raise SeatRequestTimeout(
                "timeout waiting for set_active_result from {}".format(
                    self.address
                )
            )
        if pending.error is not None:
            raise SeatRequestError(str(pending.error))
        return pending.response

    def deliver_response(self, message):
        if (
            message.get("v") != PROTOCOL_VERSION
            or message.get("type") != "set_active_result"
        ):
            return False
        command_id = message.get("command_id")
        with self.pending_lock:
            pending = self.pending.pop(command_id, None)
        if pending is None:
            return False
        pending.response = message
        pending.event.set()
        return True

    def close(self):
        with self.pending_lock:
            if self.closed:
                return
            self.closed = True
            pending = list(self.pending.values())
            self.pending.clear()
        for item in pending:
            item.error = SeatRequestError("seat connection closed")
            item.event.set()
        try:
            self.connection.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            self.connection.close()
        except OSError:
            pass


class SeatRecord:
    def __init__(self, seat_id):
        self.seat_id = seat_id
        self.lock = threading.RLock()
        self.client = None
        self.connected_at = None
        self.boot_id = None
        self.last_seq = -1
        self.last_sample_at = None
        self.raw_status = STATUS_AVAILABLE
        self.occupied_until = 0.0
        self.led_active = False
        self.desired_active_until = 0.0
        self.last_reported_status = None
        self.command_lock = threading.RLock()
        self.sync_inflight = False

    def attach(self, client, boot_id):
        with self.lock:
            old_client = self.client
            self.client = client
            self.connected_at = time.monotonic()
            if boot_id != self.boot_id:
                self.boot_id = boot_id
                self.last_seq = -1
                self.last_sample_at = None
            client.seat_id = self.seat_id
            client.boot_id = boot_id
        if old_client is not None and old_client is not client:
            old_client.close()

    def detach(self, client):
        with self.lock:
            if self.client is client:
                self.client = None
                return True
        return False

    def status_at(self, now):
        return (
            STATUS_OCCUPIED
            if now < self.occupied_until
            else STATUS_AVAILABLE
        )

    def online_at(self, now):
        return (
            self.client is not None
            and self.last_sample_at is not None
            and now - self.last_sample_at < SEAT_SAMPLE_TIMEOUT_SECONDS
        )

    def update_sample(self, client, message, now=None):
        now = time.monotonic() if now is None else now
        if message.get("seat_id") != self.seat_id:
            raise ValueError("seat_sample has unexpected seat_id")
        if message.get("boot_id") != client.boot_id:
            raise ValueError("seat_sample has unexpected boot_id")
        status = message.get("status")
        if status not in VALID_SEAT_STATUSES:
            raise ValueError("invalid seat status")
        seq = message.get("seq")
        if not isinstance(seq, int) or seq < 0:
            raise ValueError("invalid seat sequence")
        age_ms = message.get("last_occupied_age_ms")
        if age_ms is not None and (
            not isinstance(age_ms, int) or age_ms < 0
        ):
            raise ValueError("invalid occupied age")
        if status == STATUS_OCCUPIED and age_ms is None:
            age_ms = 0
        led_active = message.get("led_active")
        if not isinstance(led_active, bool):
            raise ValueError("invalid led_active")

        with self.lock:
            if self.client is not client:
                return False
            if seq <= self.last_seq:
                return False
            self.last_seq = seq
            self.last_sample_at = now
            self.raw_status = status
            self.led_active = led_active
            if age_ms is not None and age_ms < int(
                OCCUPANCY_TTL_SECONDS * 1000
            ):
                candidate = now + (
                    OCCUPANCY_TTL_SECONDS - age_ms / 1000.0
                )
                self.occupied_until = max(
                    self.occupied_until, candidate
                )
            current = self.status_at(now)
            changed = self.last_reported_status != current
            self.last_reported_status = current

        if changed:
            print("Assento {}: {}".format(self.seat_id, current))
        return True

    def snapshot(self, now=None):
        now = time.monotonic() if now is None else now
        with self.lock:
            return {
                "client": self.client,
                "online": self.online_at(now),
                "status": self.status_at(now),
                "led_active": self.led_active,
                "desired_active_until": self.desired_active_until,
                "last_sample_at": self.last_sample_at,
            }


def get_or_create_seat(seat_id):
    with seats_lock:
        record = seats.get(seat_id)
        if record is None:
            record = SeatRecord(seat_id)
            seats[seat_id] = record
        return record


def register_seat(client, message):
    seat_id = message.get("seat_id")
    boot_id = message.get("boot_id")
    if not isinstance(seat_id, str) or not seat_id:
        raise ValueError("register without valid seat_id")
    if not isinstance(boot_id, str) or not boot_id:
        raise ValueError("register without valid boot_id")
    record = get_or_create_seat(seat_id)
    record.attach(client, boot_id)
    print("Assento registrado: {} ({})".format(seat_id, client.address))
    return record


def register_nfc(client, message):
    device_id = message.get("device_id")
    boot_id = message.get("boot_id")
    old_client = None
    client.device_id = device_id
    client.boot_id = boot_id
    with nfc_clients_lock:
        old_client = nfc_clients.get(device_id)
        nfc_clients[device_id] = client
    if old_client is not None and old_client is not client:
        old_client.close()
    print("Leitor NFC registrado: {} boot={} ({})".format(
        device_id, boot_id, client.address
    ))


def unregister_nfc(client):
    if client.device_id is None:
        return
    with nfc_clients_lock:
        if nfc_clients.get(client.device_id) is client:
            del nfc_clients[client.device_id]


def detach_seat(record, client):
    if record is not None and record.detach(client):
        print("Assento desconectado: {}".format(record.seat_id))


def get_seat_records():
    with seats_lock:
        return [seats[key] for key in sorted(seats)]


def command_record(record, active, duration_ms, command_id):
    with record.command_lock:
        snapshot = record.snapshot()
        client = snapshot["client"]
        if client is None:
            return False
        try:
            response = client.request(active, duration_ms, command_id)
            applied = (
                response.get("applied") is True
                and response.get("active") is bool(active)
            )
            with record.lock:
                if record.client is client and applied:
                    record.led_active = bool(response.get("active"))
            if not applied:
                detach_seat(record, client)
                client.close()
            return applied
        except (OSError, SeatRequestError) as error:
            print("Falha no comando para {}: {}".format(
                record.seat_id, error
            ))
            detach_seat(record, client)
            client.close()
            return False


def schedule_reconcile(record):
    now = time.monotonic()
    snapshot = record.snapshot(now)
    should_be_active = (
        snapshot["online"]
        and snapshot["status"] == STATUS_AVAILABLE
        and snapshot["desired_active_until"] > now
    )
    if snapshot["client"] is None or (
        snapshot["led_active"] == should_be_active
    ):
        return
    with record.lock:
        if record.sync_inflight:
            return
        record.sync_inflight = True

    def worker():
        try:
            with record.command_lock:
                now = time.monotonic()
                snapshot = record.snapshot(now)
                should_be_active = (
                    snapshot["online"]
                    and snapshot["status"] == STATUS_AVAILABLE
                    and snapshot["desired_active_until"] > now
                )
                if snapshot["led_active"] == should_be_active:
                    return
                duration_ms = (
                    max(
                        1,
                        int(
                            (snapshot["desired_active_until"] - now)
                            * 1000
                        ),
                    )
                    if should_be_active
                    else 0
                )
                command_record(
                    record,
                    should_be_active,
                    duration_ms,
                    allocate_command_id("sync"),
                )
        finally:
            with record.lock:
                record.sync_inflight = False

    threading.Thread(target=worker, daemon=True).start()


def run_commands(commands):
    results = {}
    results_lock = threading.Lock()

    def worker(record, active, duration_ms, command_id):
        result = command_record(record, active, duration_ms, command_id)
        with results_lock:
            results[record.seat_id] = result

    threads = []
    for command in commands:
        thread = threading.Thread(target=worker, args=command, daemon=True)
        thread.start()
        threads.append(thread)
    for thread in threads:
        thread.join(SEAT_REQUEST_TIMEOUT_SECONDS + 0.2)
    return results


def activate_available_seats(event_id, now=None):
    now = time.monotonic() if now is None else now
    records = get_seat_records()
    targets = []
    commands = []

    for record in records:
        snapshot = record.snapshot(now)
        eligible = snapshot["online"] and (
            snapshot["status"] == STATUS_AVAILABLE
        )
        with record.lock:
            record.desired_active_until = (
                now + ACTIVE_DURATION_MS / 1000.0 if eligible else 0.0
            )
        if eligible:
            targets.append(record.seat_id)
            commands.append(
                (
                    record,
                    True,
                    ACTIVE_DURATION_MS,
                    "{}:{}".format(event_id, record.seat_id),
                )
            )
        elif snapshot["client"] is not None and snapshot["led_active"]:
            commands.append(
                (
                    record,
                    False,
                    0,
                    "{}:{}:off".format(event_id, record.seat_id),
                )
            )

    if not targets:
        return {
            "status": "NO_AVAILABLE_SEATS",
            "activated_seats": [],
            "failed_seats": [],
        }

    results = run_commands(commands)
    activated = [seat for seat in targets if results.get(seat) is True]
    failed = [seat for seat in targets if seat not in activated]
    if activated and failed:
        status = "PARTIAL"
    elif activated:
        status = "OK"
    else:
        status = "ACTIVATION_FAILED"
    return {
        "status": status,
        "activated_seats": activated,
        "failed_seats": failed,
    }


def prune_nfc_cache(now):
    with nfc_cache_lock:
        while nfc_cache:
            _, (created_at, _) = next(iter(nfc_cache.items()))
            if (
                now - created_at <= NFC_CACHE_SECONDS
                and len(nfc_cache) <= NFC_CACHE_MAX_ENTRIES
            ):
                break
            nfc_cache.popitem(last=False)


def handle_nfc_message(message, now=None):
    now = time.monotonic() if now is None else now
    if (
        message.get("v") != PROTOCOL_VERSION
        or message.get("type") != "nfc_presented"
    ):
        return {
            "v": PROTOCOL_VERSION,
            "type": "nfc_result",
            "event_id": message.get("event_id"),
            "status": "INVALID",
            "activated_seats": [],
            "failed_seats": [],
        }
    event_id = message.get("event_id")
    card_id = message.get("card_id")
    age_ms = message.get("age_ms")
    if (
        not isinstance(event_id, str)
        or not event_id
        or not isinstance(card_id, str)
        or not card_id
        or not isinstance(age_ms, int)
        or age_ms < 0
    ):
        return {
            "v": PROTOCOL_VERSION,
            "type": "nfc_result",
            "event_id": event_id,
            "status": "INVALID",
            "activated_seats": [],
            "failed_seats": [],
        }

    prune_nfc_cache(now)
    with nfc_cache_lock:
        cached = nfc_cache.get(event_id)
        if cached is not None:
            return dict(cached[1])

    if age_ms >= NFC_EVENT_MAX_AGE_MS:
        result = {
            "status": "EXPIRED",
            "activated_seats": [],
            "failed_seats": [],
        }
    else:
        with activation_lock:
            with nfc_cache_lock:
                cached = nfc_cache.get(event_id)
                if cached is not None:
                    return dict(cached[1])
            print("NFC recebido: {} ({})".format(card_id, event_id))
            result = activate_available_seats(event_id, now)

    response = {
        "v": PROTOCOL_VERSION,
        "type": "nfc_result",
        "event_id": event_id,
        **result,
    }
    with nfc_cache_lock:
        nfc_cache[event_id] = (now, dict(response))
        nfc_cache.move_to_end(event_id)
    prune_nfc_cache(now)
    return response


def read_json_line(response_file, address):
    line = response_file.readline(MAX_FRAME_BYTES + 2)
    if not line:
        return None
    if len(line.encode("utf-8")) > MAX_FRAME_BYTES or not line.endswith("\n"):
        raise ValueError("frame too large from {}".format(address))
    try:
        message = json.loads(line)
    except ValueError as error:
        raise ValueError("invalid JSON from {}: {}".format(
            address, error
        )) from error
    if not isinstance(message, dict):
        raise ValueError("JSON frame must be an object")
    return message


def validate_register(message):
    if (
        message.get("v") != PROTOCOL_VERSION
        or message.get("type") != "register"
    ):
        raise ValueError("first frame must be a v1 register")
    role = message.get("role")
    if role not in ("seat", "nfc"):
        raise ValueError("invalid role")
    if not isinstance(message.get("device_id"), str):
        raise ValueError("invalid device_id")
    if not isinstance(message.get("boot_id"), str):
        raise ValueError("invalid boot_id")
    return role


def handle_client(connection, address):
    client = ClientConnection(connection, address)
    response_file = connection.makefile("r", encoding="utf-8")
    record = None
    print("Dispositivo conectado: {}".format(address))
    try:
        register = read_json_line(response_file, address)
        if register is None:
            return
        role = validate_register(register)
        if role == "seat":
            record = register_seat(client, register)
        else:
            register_nfc(client, register)
        client.send(
            {
                "v": PROTOCOL_VERSION,
                "type": "register_ack",
                "accepted": True,
            }
        )

        while True:
            message = read_json_line(response_file, address)
            if message is None:
                break
            if role == "seat":
                if message.get("type") == "seat_sample":
                    if record.update_sample(client, message):
                        schedule_reconcile(record)
                elif not client.deliver_response(message):
                    raise ValueError("invalid seat message")
            else:
                if (
                    message.get("v") == PROTOCOL_VERSION
                    and message.get("type") == "ping"
                ):
                    client.send(
                        {
                            "v": PROTOCOL_VERSION,
                            "type": "pong",
                        }
                    )
                else:
                    client.send(handle_nfc_message(message))
    except (OSError, ValueError) as error:
        print("Erro com {}: {}".format(address, error))
    finally:
        detach_seat(record, client)
        unregister_nfc(client)
        try:
            response_file.close()
        except OSError:
            pass
        client.close()
        print("Dispositivo desconectado: {}".format(address))


def monitor_seats():
    while True:
        time.sleep(SEAT_MONITOR_INTERVAL_SECONDS)
        now = time.monotonic()
        for record in get_seat_records():
            snapshot = record.snapshot(now)
            client = snapshot["client"]
            with record.lock:
                connected_at = record.connected_at
            if (
                client is not None
                and (
                    snapshot["last_sample_at"] is not None
                    or connected_at is not None
                )
                and not snapshot["online"]
                and now
                - (
                    snapshot["last_sample_at"]
                    if snapshot["last_sample_at"] is not None
                    else connected_at
                )
                >= SEAT_SAMPLE_TIMEOUT_SECONDS
            ):
                print("Timeout do assento {}".format(record.seat_id))
                detach_seat(record, client)
                client.close()
                continue
            if client is not None:
                schedule_reconcile(record)


def main():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
        server.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
    else:
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((HOST, PORT))
    server.listen(8)
    print("Servidor ouvindo na porta {}".format(PORT))
    threading.Thread(target=monitor_seats, daemon=True).start()
    try:
        while True:
            connection, address = server.accept()
            threading.Thread(
                target=handle_client,
                args=(connection, address),
                daemon=True,
            ).start()
    except KeyboardInterrupt:
        print("Servidor encerrado")
    finally:
        server.close()


if __name__ == "__main__":
    main()
