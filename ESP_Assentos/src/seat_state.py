STATUS_OCCUPIED = "OCUPADO"
STATUS_AVAILABLE = "DISPONIVEL"


class ReconnectBackoff:
    def __init__(
        self,
        delays_ms=(500, 1000, 2000, 4000, 8000, 15000),
        healthy_session_ms=20000,
        jitter_percent=20,
    ):
        self.delays_ms = tuple(delays_ms)
        self.healthy_session_ms = healthy_session_ms
        self.jitter_percent = jitter_percent
        self.index = 0
        self.attempt = 0

    def next_delay_ms(self, entropy=0):
        base = self.delays_ms[
            min(self.index, len(self.delays_ms) - 1)
        ]
        self.index += 1
        self.attempt += 1
        spread = max(1, base * self.jitter_percent // 100)
        return base + (entropy % (spread * 2 + 1)) - spread

    def record_session(self, duration_ms):
        if duration_ms >= self.healthy_session_ms:
            self.index = 0
            self.attempt = 0
            return True
        return False


class HeartbeatMonitor:
    def __init__(self, failure_limit=3):
        self.failure_limit = failure_limit
        self.failures = 0

    def acknowledge(self):
        self.failures = 0

    def miss(self):
        self.failures += 1
        return self.failures >= self.failure_limit


class SeatState:
    """Physical sensor state and an idempotent LED lease.

    Occupancy TTL is intentionally not handled here. It belongs to the server.
    """

    def __init__(self, ticks_diff=None, ticks_add=None):
        self.ticks_diff = ticks_diff or self._default_ticks_diff
        self.ticks_add = ticks_add or self._default_ticks_add
        self.status = STATUS_AVAILABLE
        self.last_occupied_at = None
        self.led_on = False
        self.led_expires_at = None
        self.last_command_id = None
        self.sample_sequence = 0

    @staticmethod
    def _default_ticks_diff(now_ms, previous_ms):
        return now_ms - previous_ms

    @staticmethod
    def _default_ticks_add(now_ms, delta_ms):
        return now_ms + delta_ms

    def add_reading(self, sensor_1_occupied, sensor_2_occupied, now_ms):
        occupied = bool(sensor_1_occupied) or bool(sensor_2_occupied)
        self.status = STATUS_OCCUPIED if occupied else STATUS_AVAILABLE
        if occupied:
            self.last_occupied_at = now_ms
        self.expire_led(now_ms)
        return self.status

    def last_occupied_age_ms(self, now_ms):
        if self.last_occupied_at is None:
            return None
        age_ms = self.ticks_diff(now_ms, self.last_occupied_at)
        return max(0, age_ms)

    def next_sample_sequence(self):
        value = self.sample_sequence
        self.sample_sequence += 1
        return value

    def expire_led(self, now_ms):
        if (
            self.led_on
            and self.led_expires_at is not None
            and self.ticks_diff(now_ms, self.led_expires_at) >= 0
        ):
            self.led_on = False
            self.led_expires_at = None
            return True
        return False

    def set_active(self, command_id, active, duration_ms, now_ms):
        if not isinstance(command_id, str) or not command_id:
            return False

        self.expire_led(now_ms)
        if command_id == self.last_command_id:
            return True

        if active is True:
            if not isinstance(duration_ms, int) or duration_ms <= 0:
                return False
            self.led_on = True
            self.led_expires_at = self.ticks_add(now_ms, duration_ms)
        elif active is False:
            self.led_on = False
            self.led_expires_at = None
        else:
            return False

        self.last_command_id = command_id
        return True
