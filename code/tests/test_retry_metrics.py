"""Ground-truth retry classification under delayed and reordered arrivals."""
import struct
import unittest
from types import SimpleNamespace

from retry_metrics import RetryObserver


class RetryMetricsTests(unittest.TestCase):
    def setUp(self):
        self.observer = RetryObserver()
        self.arrivals = []
        self.link = SimpleNamespace(
            direction="to receiver", sim=SimpleNamespace(now=0),
            receive=lambda packet: None)
        self.packet = struct.pack("!BIdHH", 0x10, 1, 0, 0, 1) + b"data"

    def send(self, lost=False):
        def original_send(link, packet):
            if not lost:
                self.arrivals.append((link.receive, packet))
        self.observer.send(original_send, self.link, self.packet)

    def arrive(self, index, now):
        self.link.sim.now = now
        callback, packet = self.arrivals[index]
        callback(packet)

    def test_retry_recovers_lost_original_at_deadline(self):
        self.send(lost=True)
        self.send()
        self.arrive(0, 200)
        self.assertEqual(self.observer.metrics["useful_retries"], 1)
        self.assertEqual(self.observer.metrics["late_retries"], 0)

    def test_retry_sent_after_receipt_can_also_arrive_late(self):
        self.send()
        self.arrive(0, 50)
        self.send()
        self.arrive(1, 201)
        self.assertEqual(self.observer.metrics["unnecessary_retries"], 1)
        self.assertEqual(self.observer.metrics["late_retries"], 1)
        self.assertEqual(self.observer.metrics["useful_retries"], 0)

    def test_original_overtakes_retry(self):
        self.send()
        self.send()
        self.arrive(0, 100)
        self.arrive(1, 110)
        self.assertFalse(any(self.observer.metrics.values()))

    def test_retry_overtakes_original(self):
        self.send()
        self.send()
        self.arrive(1, 100)
        self.arrive(0, 110)
        self.assertEqual(self.observer.metrics["useful_retries"], 1)
