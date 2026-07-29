STATUS_OCCUPIED = "ocupado"
STATUS_AVAILABLE = "disponível"

LED_ACTIVATED = "activated"
LED_ALREADY_ACTIVE = "already_active"
LED_OCCUPIED = "occupied"
LED_INVALID_VALUE = "invalid_value"
LED_DEACTIVATED = "deactivated"


class SeatState:
    def __init__(self, window_size=10):
        if window_size <= 0:
            raise ValueError("window_size must be positive")

        self.window_size = window_size
        self.sensor_1_window = [False] * window_size
        self.sensor_2_window = [False] * window_size
        self.next_index = 0
        self.sample_count = 0
        self.occupied_readings = 0
        self.led_on = False
        self.led_deadline_ms = None

    @property
    def status(self):
        if self.sample_count < self.window_size or self.occupied_readings > 0:
            return STATUS_OCCUPIED
        return STATUS_AVAILABLE

    @property
    def is_available(self):
        return self.status == STATUS_AVAILABLE

    def add_reading(self, sensor_1_occupied, sensor_2_occupied):
        sensor_1_occupied = bool(sensor_1_occupied)
        sensor_2_occupied = bool(sensor_2_occupied)

        if self.sample_count == self.window_size:
            self.occupied_readings -= int(
                self.sensor_1_window[self.next_index]
            )
            self.occupied_readings -= int(
                self.sensor_2_window[self.next_index]
            )
        else:
            self.sample_count += 1

        self.sensor_1_window[self.next_index] = sensor_1_occupied
        self.sensor_2_window[self.next_index] = sensor_2_occupied
        self.occupied_readings += int(sensor_1_occupied)
        self.occupied_readings += int(sensor_2_occupied)
        self.next_index = (self.next_index + 1) % self.window_size

        if (sensor_1_occupied or sensor_2_occupied) and self.led_on:
            self.set_led(0)

        return self.status

    def set_led(self, value, deadline_ms=None):
        if value == 0:
            self.led_on = False
            self.led_deadline_ms = None
            return LED_DEACTIVATED

        if value != 1:
            return LED_INVALID_VALUE

        if self.led_on:
            return LED_ALREADY_ACTIVE

        if not self.is_available:
            return LED_OCCUPIED

        self.led_on = True
        self.led_deadline_ms = deadline_ms
        return LED_ACTIVATED

    def led_remaining_ms(self, now_ms, ticks_diff):
        if not self.led_on or self.led_deadline_ms is None:
            return 0
        return max(0, ticks_diff(self.led_deadline_ms, now_ms))

    def expire_led(self, now_ms, ticks_diff):
        if not self.led_on or self.led_deadline_ms is None:
            return False
        if ticks_diff(now_ms, self.led_deadline_ms) < 0:
            return False

        self.led_on = False
        self.led_deadline_ms = None
        return True
