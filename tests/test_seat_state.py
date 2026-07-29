import sys
import unittest
from pathlib import Path


SEAT_SOURCE = Path(__file__).resolve().parents[1] / "ESP_Assentos" / "src"
sys.path.insert(0, str(SEAT_SOURCE))

from seat_state import (
    LED_ACTIVATED,
    LED_ALREADY_ACTIVE,
    LED_DEACTIVATED,
    LED_INVALID_VALUE,
    LED_OCCUPIED,
    STATUS_AVAILABLE,
    STATUS_OCCUPIED,
    SeatState,
)


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

    def test_either_sensor_turns_off_active_led_immediately(self):
        for occupied_pair in ((True, False), (False, True), (True, True)):
            with self.subTest(occupied_pair=occupied_pair):
                state = SeatState(window_size=10)
                self.assertEqual(state.set_led(1, 10000), LED_OCCUPIED)
                for _ in range(10):
                    state.add_reading(False, False)

                self.assertEqual(state.set_led(1, 10000), LED_ACTIVATED)
                self.assertTrue(state.led_on)
                self.assertEqual(state.set_led(1, 20000), LED_ALREADY_ACTIVE)
                self.assertEqual(state.led_deadline_ms, 10000)

                state.add_reading(*occupied_pair)
                self.assertFalse(state.led_on)
                self.assertIsNone(state.led_deadline_ms)
                self.assertEqual(state.set_led(1, 20000), LED_OCCUPIED)
                self.assertEqual(state.set_led(2), LED_INVALID_VALUE)
                self.assertEqual(state.set_led(0), LED_DEACTIVATED)

    def test_led_expires_only_at_original_deadline(self):
        state = SeatState(window_size=1)
        state.add_reading(False, False)
        ticks_diff = lambda left, right: left - right

        self.assertEqual(state.set_led(1, 10000), LED_ACTIVATED)
        self.assertEqual(state.led_remaining_ms(2500, ticks_diff), 7500)
        self.assertEqual(state.set_led(1, 15000), LED_ALREADY_ACTIVE)
        self.assertEqual(state.led_deadline_ms, 10000)

        self.assertFalse(state.expire_led(9999, ticks_diff))
        self.assertTrue(state.led_on)
        self.assertTrue(state.expire_led(10000, ticks_diff))
        self.assertFalse(state.led_on)
        self.assertEqual(state.led_remaining_ms(10001, ticks_diff), 0)
        self.assertFalse(state.expire_led(20000, ticks_diff))


if __name__ == "__main__":
    unittest.main()
