import json
import sys
import threading
import time
import unittest
from pathlib import Path


SERVER_SOURCE = Path(__file__).resolve().parents[1] / "servidor" / "src"
sys.path.insert(0, str(SERVER_SOURCE))

import pc_server


class FakeClient:
    def __init__(self, applied=True):
        self.applied = applied
        self.seat_id = None
        self.boot_id = None
        self.closed = False
        self.requests = []

    def request(self, active, duration_ms, command_id=None):
        self.requests.append((active, duration_ms, command_id))
        if isinstance(self.applied, Exception):
            raise self.applied
        return {
            "v": 1,
            "type": "set_active_result",
            "command_id": command_id,
            "applied": self.applied,
            "active": bool(active) if self.applied else False,
        }

    def close(self):
        self.closed = True


def sample(
    seat_id,
    boot_id,
    seq,
    status=pc_server.STATUS_AVAILABLE,
    age_ms=None,
    led=False,
):
    return {
        "v": 1,
        "type": "seat_sample",
        "seat_id": seat_id,
        "boot_id": boot_id,
        "seq": seq,
        "status": status,
        "last_occupied_age_ms": age_ms,
        "led_active": led,
    }


def connected_seat(
    seat_id,
    now,
    status=pc_server.STATUS_AVAILABLE,
    age_ms=None,
    applied=True,
):
    client = FakeClient(applied)
    record = pc_server.get_or_create_seat(seat_id)
    record.attach(client, "boot")
    record.update_sample(
        client,
        sample(seat_id, "boot", 0, status, age_ms),
        now=now,
    )
    return record, client


class PcServerTests(unittest.TestCase):
    def setUp(self):
        with pc_server.seats_lock:
            pc_server.seats.clear()
        with pc_server.nfc_cache_lock:
            pc_server.nfc_cache.clear()
        with pc_server.command_id_lock:
            pc_server.next_command_id = 1

    def test_ttl_boundary_and_available_does_not_clear(self):
        record, client = connected_seat(
            "Alberto",
            10.0,
            pc_server.STATUS_OCCUPIED,
            0,
        )
        record.update_sample(
            client,
            sample("Alberto", "boot", 1),
            now=11.0,
        )
        self.assertEqual(record.status_at(14.999), pc_server.STATUS_OCCUPIED)
        self.assertEqual(record.status_at(15.0), pc_server.STATUS_AVAILABLE)

    def test_occupied_sample_restarts_non_cumulative_ttl(self):
        record, client = connected_seat(
            "Bete", 0.0, pc_server.STATUS_OCCUPIED, 0
        )
        record.update_sample(
            client,
            sample(
                "Bete",
                "boot",
                1,
                pc_server.STATUS_OCCUPIED,
                0,
            ),
            now=4.0,
        )
        self.assertEqual(record.status_at(8.999), pc_server.STATUS_OCCUPIED)
        self.assertEqual(record.status_at(9.0), pc_server.STATUS_AVAILABLE)

    def test_last_occupied_age_preserves_remaining_ttl(self):
        record, _ = connected_seat(
            "Alberto", 20.0, pc_server.STATUS_AVAILABLE, 2000
        )
        self.assertEqual(record.status_at(22.999), pc_server.STATUS_OCCUPIED)
        self.assertEqual(record.status_at(23.0), pc_server.STATUS_AVAILABLE)

    def test_duplicate_and_out_of_order_samples_are_ignored(self):
        record, client = connected_seat("Alberto", 0.0)
        self.assertFalse(
            record.update_sample(
                client,
                sample(
                    "Alberto",
                    "boot",
                    0,
                    pc_server.STATUS_OCCUPIED,
                    0,
                ),
                now=1.0,
            )
        )
        self.assertEqual(record.status_at(1.0), pc_server.STATUS_AVAILABLE)

    def test_alberto_and_bete_are_independent(self):
        alberto, _ = connected_seat(
            "Alberto", 0.0, pc_server.STATUS_OCCUPIED, 0
        )
        bete, _ = connected_seat("Bete", 0.0)
        self.assertEqual(alberto.status_at(1.0), pc_server.STATUS_OCCUPIED)
        self.assertEqual(bete.status_at(1.0), pc_server.STATUS_AVAILABLE)

    def test_sample_timeout_blocks_activation(self):
        record, _ = connected_seat("Alberto", 10.0)
        self.assertTrue(record.snapshot(11.499)["online"])
        self.assertFalse(record.snapshot(11.5)["online"])

    def test_activates_all_available_seats(self):
        _, alberto = connected_seat("Alberto", 100.0)
        _, bete = connected_seat("Bete", 100.0)
        result = pc_server.activate_available_seats("evt", now=100.1)
        self.assertEqual(result["status"], "OK")
        self.assertEqual(
            result["activated_seats"], ["Alberto", "Bete"]
        )
        self.assertEqual(alberto.requests[0][1], 5000)
        self.assertEqual(bete.requests[0][1], 5000)

    def test_occupied_seat_is_not_activated(self):
        _, alberto = connected_seat(
            "Alberto", 100.0, pc_server.STATUS_OCCUPIED, 0
        )
        _, bete = connected_seat("Bete", 100.0)
        result = pc_server.activate_available_seats("evt", now=100.1)
        self.assertEqual(result["activated_seats"], ["Bete"])
        self.assertEqual(alberto.requests, [])
        self.assertEqual(len(bete.requests), 1)

    def test_partial_activation_keeps_successful_seat(self):
        _, alberto = connected_seat("Alberto", 100.0, applied=True)
        _, bete = connected_seat("Bete", 100.0, applied=False)
        result = pc_server.activate_available_seats("evt", now=100.1)
        self.assertEqual(result["status"], "PARTIAL")
        self.assertEqual(result["activated_seats"], ["Alberto"])
        self.assertEqual(result["failed_seats"], ["Bete"])

    def test_nfc_result_is_idempotent(self):
        _, client = connected_seat("Alberto", 100.0)
        message = {
            "v": 1,
            "type": "nfc_presented",
            "event_id": "boot:1",
            "card_id": "nfc_1",
            "age_ms": 0,
        }
        first = pc_server.handle_nfc_message(message, now=100.1)
        second = pc_server.handle_nfc_message(message, now=101.0)
        self.assertEqual(first, second)
        self.assertEqual(len(client.requests), 1)

    def test_expired_and_invalid_nfc_events_do_not_activate(self):
        _, client = connected_seat("Alberto", 100.0)
        expired = pc_server.handle_nfc_message(
            {
                "v": 1,
                "type": "nfc_presented",
                "event_id": "old",
                "card_id": "nfc_1",
                "age_ms": 30000,
            },
            now=100.1,
        )
        invalid = pc_server.handle_nfc_message({"type": "old"}, now=100.2)
        self.assertEqual(expired["status"], "EXPIRED")
        self.assertEqual(invalid["status"], "INVALID")
        self.assertEqual(client.requests, [])

    def test_concurrent_duplicate_event_activates_once(self):
        _, client = connected_seat("Alberto", 100.0)
        message = {
            "v": 1,
            "type": "nfc_presented",
            "event_id": "same",
            "card_id": "nfc_1",
            "age_ms": 0,
        }
        results = []

        def invoke():
            results.append(pc_server.handle_nfc_message(message, now=100.1))

        threads = [threading.Thread(target=invoke) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(1)
        self.assertEqual(len(client.requests), 1)
        self.assertEqual(results[0], results[1])


if __name__ == "__main__":
    unittest.main()
