STATUS_OCCUPIED = "ocupado"
STATUS_AVAILABLE = "disponível"


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

        if self.status == STATUS_OCCUPIED:
            self.led_on = False

        return self.status

    def set_led(self, value):
        if value == 0:
            self.led_on = False
            return True

        if value != 1 or not self.is_available or self.led_on:
            return False

        self.led_on = True
        return True
