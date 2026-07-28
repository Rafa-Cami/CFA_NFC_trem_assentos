import sys
import unittest
from pathlib import Path


SEAT_SOURCE = Path(__file__).resolve().parents[1] / "ESP_Assentos" / "src"
sys.path.insert(0, str(SEAT_SOURCE))

from seat_state import STATUS_AVAILABLE, STATUS_OCCUPIED, SeatState


class SeatStateTests(unittest.TestCase):
    def test_reports_current_or_of_both_sensors(self):
        state = SeatState()
        self.assertEqual(
            state.add_reading(False, False, 0), STATUS_AVAILABLE
        )
        self.assertEqual(
            state.add_reading(True, False, 500), STATUS_OCCUPIED
        )
        self.assertEqual(
            state.add_reading(False, True, 1000), STATUS_OCCUPIED
        )
        self.assertEqual(
            state.add_reading(False, False, 1500), STATUS_AVAILABLE
        )

    def test_reports_last_occupied_age_without_applying_ttl(self):
        state = SeatState()
        self.assertIsNone(state.last_occupied_age_ms(0))
        state.add_reading(True, False, 100)
        state.add_reading(False, False, 500)
        self.assertEqual(state.status, STATUS_AVAILABLE)
        self.assertEqual(state.last_occupied_age_ms(600), 500)

    def test_led_lease_expires_at_exact_deadline(self):
        state = SeatState()
        self.assertTrue(state.set_active("cmd-1", True, 5000, 100))
        self.assertTrue(state.led_on)
        self.assertFalse(state.expire_led(5099))
        self.assertTrue(state.led_on)
        self.assertTrue(state.expire_led(5100))
        self.assertFalse(state.led_on)

    def test_duplicate_command_does_not_extend_led_lease(self):
        state = SeatState()
        self.assertTrue(state.set_active("cmd-1", True, 5000, 0))
        self.assertTrue(state.set_active("cmd-1", True, 5000, 4000))
        self.assertTrue(state.expire_led(5000))

    def test_new_command_restarts_led_lease_and_off_is_idempotent(self):
        state = SeatState()
        state.set_active("cmd-1", True, 5000, 0)
        state.set_active("cmd-2", True, 5000, 4000)
        self.assertFalse(state.expire_led(8999))
        self.assertTrue(state.expire_led(9000))
        self.assertTrue(state.set_active("off-1", False, 0, 9000))
        self.assertTrue(state.set_active("off-1", False, 0, 9500))

    def test_occupancy_does_not_turn_off_active_led(self):
        state = SeatState()
        state.set_active("cmd", True, 5000, 0)
        state.add_reading(True, False, 100)
        self.assertTrue(state.led_on)

    def test_ticks_diff_supports_wraparound(self):
        period = 1 << 30

        def ticks_diff(now_ms, previous_ms):
            return (
                now_ms - previous_ms + period // 2
            ) % period - period // 2

        state = SeatState(ticks_diff)
        state.add_reading(True, False, period - 100)
        self.assertEqual(state.last_occupied_age_ms(50), 150)

    def test_sample_sequence_survives_connection_restarts(self):
        state = SeatState()
        self.assertEqual(state.next_sample_sequence(), 0)
        self.assertEqual(state.next_sample_sequence(), 1)
        self.assertEqual(state.sample_sequence, 2)


if __name__ == "__main__":
    unittest.main()
