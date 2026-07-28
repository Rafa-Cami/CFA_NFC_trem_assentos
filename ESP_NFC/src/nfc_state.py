class PresenceTracker:
    def __init__(self, absent_reads_to_rearm=2):
        if absent_reads_to_rearm <= 0:
            raise ValueError("absent_reads_to_rearm must be positive")
        self.absent_reads_to_rearm = absent_reads_to_rearm
        self.present_uid = None
        self.absent_reads = 0

    def observe(self, uid):
        if uid is None:
            self.absent_reads += 1
            if self.absent_reads >= self.absent_reads_to_rearm:
                self.present_uid = None
            return None

        self.absent_reads = 0
        if uid == self.present_uid:
            return None
        self.present_uid = uid
        return uid


class EventQueue:
    def __init__(self, capacity=8, max_age_ms=30000, ticks_diff=None):
        if capacity <= 0 or max_age_ms <= 0:
            raise ValueError("capacity and max_age_ms must be positive")
        self.capacity = capacity
        self.max_age_ms = max_age_ms
        self.ticks_diff = ticks_diff or (lambda now, then: now - then)
        self.items = []

    def put(self, event):
        if len(self.items) >= self.capacity:
            return False
        self.items.append(event)
        return True

    def peek(self):
        return self.items[0] if self.items else None

    def pop(self):
        return self.items.pop(0) if self.items else None

    def age_ms(self, event, now_ms):
        return max(0, self.ticks_diff(now_ms, event["created_at_ms"]))

    def discard_expired(self, now_ms):
        discarded = []
        while self.items and self.age_ms(
            self.items[0], now_ms
        ) >= self.max_age_ms:
            discarded.append(self.items.pop(0))
        return discarded

    def __len__(self):
        return len(self.items)


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
