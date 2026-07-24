import sys
import unittest
from pathlib import Path


SEAT_SOURCE = Path(__file__).resolve().parents[1] / "ESP_Assentos" / "src"
sys.path.insert(0, str(SEAT_SOURCE))

from seat_state import STATUS_AVAILABLE, STATUS_OCCUPIED, SeatState


class SeatStateTests(unittest.TestCase):
    def test_stays_occupied_until_tenth_available_sample(self):
        state = SeatState(window_size=10)

        for _ in range(9):
            self.assertEqual(state.add_reading(False, False), STATUS_OCCUPIED)

        self.assertEqual(state.add_reading(False, False), STATUS_AVAILABLE)

    def test_occupied_reading_from_either_sensor_remains_for_full_window(self):
        for occupied_pair in ((True, False), (False, True), (True, True)):
            with self.subTest(occupied_pair=occupied_pair):
                state = SeatState(window_size=10)
                for _ in range(10):
                    state.add_reading(False, False)

                state.add_reading(*occupied_pair)
                self.assertEqual(state.status, STATUS_OCCUPIED)

                for _ in range(9):
                    state.add_reading(False, False)
                    self.assertEqual(state.status, STATUS_OCCUPIED)

                state.add_reading(False, False)
                self.assertEqual(state.status, STATUS_AVAILABLE)

    def test_false_available_reading_does_not_clear_occupied_window(self):
        state = SeatState(window_size=10)
        for _ in range(10):
            state.add_reading(True, False)

        state.add_reading(False, False)

        self.assertEqual(state.status, STATUS_OCCUPIED)
        self.assertEqual(state.occupied_readings, 9)

    def test_led_is_atomic_and_turns_off_when_seat_becomes_occupied(self):
        state = SeatState(window_size=10)

        self.assertFalse(state.set_led(1))
        for _ in range(10):
            state.add_reading(False, False)

        self.assertTrue(state.set_led(1))
        self.assertTrue(state.led_on)
        self.assertFalse(state.set_led(1))

        state.add_reading(False, True)
        self.assertFalse(state.led_on)
        self.assertFalse(state.set_led(1))
        self.assertTrue(state.set_led(0))


if __name__ == "__main__":
    unittest.main()
