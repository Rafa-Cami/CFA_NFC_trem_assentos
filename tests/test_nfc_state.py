import sys
import unittest
from pathlib import Path


NFC_SOURCE = Path(__file__).resolve().parents[1] / "ESP_NFC" / "src"
sys.path.insert(0, str(NFC_SOURCE))

from nfc_state import EventQueue, PresenceTracker


class PresenceTrackerTests(unittest.TestCase):
    def test_one_event_per_presentation(self):
        tracker = PresenceTracker(2)
        self.assertEqual(tracker.observe("a"), "a")
        self.assertIsNone(tracker.observe("a"))
        self.assertIsNone(tracker.observe(None))
        self.assertIsNone(tracker.observe("a"))
        self.assertIsNone(tracker.observe(None))
        self.assertIsNone(tracker.observe(None))
        self.assertEqual(tracker.observe("a"), "a")

    def test_different_uid_is_immediate(self):
        tracker = PresenceTracker(2)
        self.assertEqual(tracker.observe("a"), "a")
        self.assertEqual(tracker.observe("b"), "b")


class EventQueueTests(unittest.TestCase):
    def test_capacity_fifo_and_expiration(self):
        queue = EventQueue(capacity=2, max_age_ms=30000)
        first = {"created_at_ms": 0, "event_id": "1"}
        second = {"created_at_ms": 100, "event_id": "2"}
        self.assertTrue(queue.put(first))
        self.assertTrue(queue.put(second))
        self.assertFalse(queue.put({"created_at_ms": 200}))
        self.assertIs(queue.peek(), first)
        self.assertEqual(queue.discard_expired(29999), [])
        self.assertEqual(queue.discard_expired(30000), [first])
        self.assertIs(queue.pop(), second)


if __name__ == "__main__":
    unittest.main()
