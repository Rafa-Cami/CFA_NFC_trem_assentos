import json
import socket
import sys
import threading
import time
import unittest
from pathlib import Path


SERVER_SOURCE = Path(__file__).resolve().parents[1] / "servidor" / "src"
sys.path.insert(0, str(SERVER_SOURCE))

import pc_server


class FakeSocket:
    def __init__(self):
        self.sent = []
        self.sent_event = threading.Event()
        self.closed = False

    def sendall(self, payload):
        self.sent.append(payload)
        self.sent_event.set()

    def shutdown(self, how):
        self.closed = True

    def close(self):
        self.closed = True


class ScriptedSeat:
    def __init__(self, statuses, led_results):
        self.statuses = list(statuses)
        self.led_results = list(led_results)
        self.transaction_lock = threading.Lock()
        self.requests = []
        self.closed = False

    def request(self, message_type, expected_type, **fields):
        self.requests.append((message_type, fields))
        if message_type == "get_status":
            result = self.statuses.pop(0)
            if isinstance(result, Exception):
                raise result
            return {"type": "seat_status", "status": result}

        result = self.led_results.pop(0)
        if isinstance(result, Exception):
            raise result
        return {"type": "set_led_result", "accepted": result}

    def close(self):
        self.closed = True


class ReservableSeat:
    def __init__(self):
        self.transaction_lock = threading.Lock()
        self.led_on = False
        self.closed = False

    def request(self, message_type, expected_type, **fields):
        if message_type == "get_status":
            return {
                "type": "seat_status",
                "status": pc_server.STATUS_AVAILABLE,
            }

        if not self.led_on:
            self.led_on = True
            accepted = True
        else:
            accepted = False
        return {"type": "set_led_result", "accepted": accepted}

    def close(self):
        self.closed = True


class PcServerTests(unittest.TestCase):
    def setUp(self):
        with pc_server.seats_lock:
            pc_server.seats.clear()
        with pc_server.request_id_lock:
            pc_server.next_request_id = 1

    def tearDown(self):
        with pc_server.seats_lock:
            pc_server.seats.clear()

    def test_request_is_correlated_by_request_id(self):
        sock = FakeSocket()
        client = pc_server.ClientConnection(sock, ("127.0.0.1", 1000))
        result = {}

        def make_request():
            result["response"] = client.request(
                "get_status",
                "seat_status",
            )

        thread = threading.Thread(target=make_request)
        thread.start()
        self.assertTrue(sock.sent_event.wait(0.5))

        sent_message = json.loads(sock.sent[0])
        self.assertFalse(
            client.deliver_response(
                {
                    "type": "seat_status",
                    "request_id": sent_message["request_id"] + 1,
                    "status": pc_server.STATUS_OCCUPIED,
                }
            )
        )
        self.assertTrue(thread.is_alive())

        self.assertTrue(
            client.deliver_response(
                {
                    "type": "seat_status",
                    "request_id": sent_message["request_id"],
                    "status": pc_server.STATUS_AVAILABLE,
                }
            )
        )
        thread.join(0.5)

        self.assertFalse(thread.is_alive())
        self.assertEqual(
            result["response"]["status"], pc_server.STATUS_AVAILABLE
        )

    def test_request_times_out_without_response(self):
        sock = FakeSocket()
        client = pc_server.ClientConnection(sock, ("127.0.0.1", 1000))
        original_timeout = pc_server.SEAT_REQUEST_TIMEOUT_SECONDS
        pc_server.SEAT_REQUEST_TIMEOUT_SECONDS = 0.01
        try:
            with self.assertRaises(pc_server.SeatRequestTimeout):
                client.request("get_status", "seat_status")
        finally:
            pc_server.SEAT_REQUEST_TIMEOUT_SECONDS = original_timeout

    def test_new_registration_replaces_old_connection(self):
        old_socket = FakeSocket()
        new_socket = FakeSocket()
        old_client = pc_server.ClientConnection(old_socket, ("old", 1))
        new_client = pc_server.ClientConnection(new_socket, ("new", 2))

        pc_server.register_seat(
            old_client, {"type": "seat_register", "seat_id": "Bete"}
        )
        pc_server.register_seat(
            new_client, {"type": "seat_register", "seat_id": "Bete"}
        )

        self.assertTrue(old_socket.closed)
        self.assertIs(pc_server.seats["Bete"], new_client)

    def test_persistent_seat_connection_is_queried_only_after_nfc(self):
        server_socket, esp_socket = socket.socketpair()
        handler = threading.Thread(
            target=pc_server.handle_client,
            args=(server_socket, ("seat", 5000)),
        )
        handler.start()

        try:
            esp_socket.sendall(
                b'{"type":"seat_register","seat_id":"Bete"}\n'
            )
            deadline = time.monotonic() + 0.5
            while time.monotonic() < deadline:
                with pc_server.seats_lock:
                    if "Bete" in pc_server.seats:
                        break
                time.sleep(0.005)
            else:
                self.fail("seat did not register")

            esp_socket.settimeout(0.05)
            with self.assertRaises(socket.timeout):
                esp_socket.recv(1)
            esp_socket.settimeout(None)
            esp_file = esp_socket.makefile("r")

            def answer_server_requests():
                status_request = json.loads(esp_file.readline())
                esp_socket.sendall(
                    (
                        json.dumps(
                            {
                                "type": "seat_status",
                                "request_id": status_request["request_id"],
                                "status": pc_server.STATUS_AVAILABLE,
                            },
                            ensure_ascii=False,
                        )
                        + "\n"
                    ).encode()
                )

                led_request = json.loads(esp_file.readline())
                esp_socket.sendall(
                    (
                        json.dumps(
                            {
                                "type": "set_led_result",
                                "request_id": led_request["request_id"],
                                "accepted": True,
                            }
                        )
                        + "\n"
                    ).encode()
                )

            responder = threading.Thread(target=answer_server_requests)
            responder.start()
            response = pc_server.handle_nfc_message({"nfc_1": 1})
            responder.join(0.5)

            self.assertFalse(responder.is_alive())
            self.assertEqual(response["status"], "ok")
            self.assertEqual(response["seat_id"], "Bete")
        finally:
            try:
                esp_file.close()
            except (NameError, OSError):
                pass
            esp_socket.close()
            handler.join(0.5)

    def test_activation_skips_occupied_and_uses_next_available_seat(self):
        occupied = ScriptedSeat([pc_server.STATUS_OCCUPIED], [])
        available = ScriptedSeat([pc_server.STATUS_AVAILABLE], [True])
        with pc_server.seats_lock:
            pc_server.seats.update({"A": occupied, "B": available})

        self.assertEqual(pc_server.activate_available_seat(), "B")
        self.assertEqual(
            occupied.requests,
            [("get_status", {})],
        )
        self.assertEqual(
            available.requests,
            [("get_status", {}), ("set_led", {"value": 1})],
        )

    def test_activation_continues_after_led_rejection(self):
        rejected = ScriptedSeat([pc_server.STATUS_AVAILABLE], [False])
        accepted = ScriptedSeat([pc_server.STATUS_AVAILABLE], [True])
        with pc_server.seats_lock:
            pc_server.seats.update({"A": rejected, "B": accepted})

        self.assertEqual(pc_server.activate_available_seat(), "B")

    def test_timeout_removes_stale_seat(self):
        stale = ScriptedSeat(
            [pc_server.SeatRequestTimeout("timed out")],
            [],
        )
        with pc_server.seats_lock:
            pc_server.seats["A"] = stale

        self.assertIsNone(pc_server.activate_available_seat())
        self.assertTrue(stale.closed)
        self.assertNotIn("A", pc_server.seats)

    def test_concurrent_nfc_events_only_activate_seat_once(self):
        seat = ReservableSeat()
        with pc_server.seats_lock:
            pc_server.seats["A"] = seat

        results = []

        def activate():
            results.append(pc_server.activate_available_seat())

        threads = [threading.Thread(target=activate) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(1)

        self.assertCountEqual(results, ["A", None])

    def test_invalid_message_does_not_query_seats(self):
        seat = ScriptedSeat([pc_server.STATUS_AVAILABLE], [True])
        with pc_server.seats_lock:
            pc_server.seats["A"] = seat

        response = pc_server.handle_nfc_message({"type": "not_nfc"})

        self.assertEqual(response["status"], "invalid_message")
        self.assertEqual(seat.requests, [])


if __name__ == "__main__":
    unittest.main()
