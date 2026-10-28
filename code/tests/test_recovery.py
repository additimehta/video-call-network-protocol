"""Recovery decisions exercised with an advancing, cancellable simulated clock."""
import heapq
import struct
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import call


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.now = 0
        self.events = []
        self.sequence = 0
        self.sent = []
        self.patches = [patch.object(call.clock, 'now', lambda: self.now),
                        patch.object(call.clock, 'set_timer', self.timer)]
        for patcher in self.patches:
            patcher.start()
            self.addCleanup(patcher.stop)
        self.sender = call.Sender(SimpleNamespace(send=lambda p: self.sent.append((self.now, p))),
                                  10000, 20)

    def timer(self, delay, callback):
        timer = SimpleNamespace(cancelled=False)
        timer.cancel = lambda: setattr(timer, 'cancelled', True)
        self.sequence += 1
        heapq.heappush(self.events, (self.now + delay, self.sequence, timer, callback))
        return timer

    def advance(self, target):
        while self.events and self.events[0][0] <= target:
            self.now, _, timer, callback = heapq.heappop(self.events)
            if not timer.cancelled:
                callback()
        self.now = target

    def frame(self, frame_id=0, count=3):
        self.sender.on_frame(SimpleNamespace(id=frame_id, time=self.now,
                                            data=[b'x' * (count * call.CHUNK)]))

    def ack(self, *ranges, frame_id=0):
        packet = (struct.pack(call.ACK_HEADER, call.ACK, frame_id, self.now, 0, ranges[-1][1])
                  + b''.join(struct.pack(call.SACK_RANGE, *r) for r in ranges))
        self.sender.on_packet(packet)

    def test_three_later_received_packets_trigger_one_fast_retransmission(self):
        self.frame(count=4)
        for time, last in ((5, 1), (10, 2)):
            self.advance(time)
            self.ack((1, last))
            self.assertEqual(len(self.sent), 4)
        self.advance(15)
        self.ack((1, 3))
        self.assertEqual(len(self.sent), 5)
        self.assertEqual(self.sender.recovery_metrics['retransmissions_sack_gap'], 1)
        self.ack((1, 3))
        self.assertEqual(len(self.sent), 5)

    def test_repeated_identical_sacks_do_not_create_new_loss_evidence(self):
        self.frame(count=4)
        for time in (5, 10, 15, 20):
            self.advance(time)
            self.ack((1, 2))
        self.assertEqual(len(self.sent), 4)
        self.assertEqual(self.sender.recovery_metrics['retransmissions_sack_gap'], 0)

    def test_gap_ack_before_threshold_prevents_fast_retry_and_double_counting(self):
        self.frame(count=4)
        original_bytes = sum(len(packet) for _, packet in self.sent)
        self.advance(5)
        self.ack((1, 2))
        self.advance(10)
        self.ack((0, 3))
        self.ack((0, 3))
        self.advance(300)
        self.assertEqual(len(self.sent), 4)
        self.assertFalse(self.sender.pending)
        self.assertEqual(self.sender.in_flight_bytes, 0)
        self.assertEqual(self.sender.total_acked_bytes, original_bytes)

    def test_sack_for_later_frame_does_not_retransmit_an_earlier_frame(self):
        self.frame()
        self.advance(40)
        self.frame(frame_id=1, count=4)
        self.advance(45)
        self.ack((0, 3), frame_id=1)
        self.advance(55)
        self.assertEqual(len(self.sent), 7)
        self.assertEqual(self.sender.recovery_metrics['retransmissions'], 0)
        self.assertTrue(all((0, index) in self.sender.pending for index in range(3)))

    def test_tail_loss_with_fewer_than_three_later_packets_uses_timeout(self):
        self.frame(count=4)
        self.advance(5)
        self.ack((0, 2))
        self.advance(79)
        self.assertEqual(len(self.sent), 4)
        self.advance(80)
        self.assertEqual(self.sender.recovery_metrics['retransmissions_timeout'], 1)
        self.assertEqual(self.sender.recovery_metrics['retransmissions_sack_gap'], 0)

    def test_fast_retransmission_still_checks_the_playback_deadline(self):
        self.sender.srtt_ms = 400
        self.frame(count=4)
        self.advance(100)
        self.ack((1, 3))
        self.assertEqual(len(self.sent), 4)
        self.assertFalse(self.sender.pending)
        self.assertEqual(self.sender.in_flight_bytes, 0)
        self.assertEqual(self.sender.recovery_metrics['abandoned_deadline'], 1)

    def test_sparse_ranges_count_only_distinct_packets_above_each_gap(self):
        self.frame(count=6)
        self.advance(5)
        self.ack((1, 1), (3, 4))
        self.assertTrue(self.sender.pending[(0, 0)].was_retransmitted)
        self.assertFalse(self.sender.pending[(0, 2)].was_retransmitted)
        self.advance(10)
        self.ack((1, 1), (3, 5))
        self.assertTrue(self.sender.pending[(0, 2)].was_retransmitted)
        self.assertEqual(self.sender.recovery_metrics['retransmissions_sack_gap'], 2)

    def test_timeout_backoff_and_deadline_release_all_window_bytes(self):
        self.sender.srtt_ms = 10
        self.sender.estimated_network_jitter = 0
        self.frame(count=1)
        self.assertEqual(self.sender.pending[(0, 0)].retry_due_at, 30)
        self.advance(30)
        self.assertEqual(self.sender.pending[(0, 0)].retry_due_at, 150)
        self.advance(150)
        self.assertEqual(self.sender.pending[(0, 0)].retry_count, 2)
        self.assertEqual(self.sender.pending[(0, 0)].retry_due_at, 200)
        self.advance(200)
        self.assertEqual([time for time, _ in self.sent], [0, 30, 150])
        self.assertFalse(self.sender.pending)
        self.assertFalse(self.sender.retry_timers)
        self.assertEqual(self.sender.in_flight_bytes, 0)
        self.assertEqual(dict(self.sender.retransmissions_by_attempt), {1: 1, 2: 1})
        self.assertEqual(self.sender.recovery_metrics['abandoned_deadline'], 1)

    def test_shared_and_packet_backoff_limit_retries_before_deadline(self):
        self.sender.srtt_ms = 1
        self.sender.estimated_network_jitter = 0
        self.frame(count=1)
        self.advance(147)
        self.assertEqual([time for time, _ in self.sent], [0, 21, 105])
        self.assertEqual(self.sender.pending[(0, 0)].retry_count, 2)
        self.assertEqual(self.sender.pending[(0, 0)].retry_due_at, 200)
        self.advance(200)
        self.assertFalse(self.sender.pending)
        self.assertFalse(self.sender.retry_timers)
        self.assertEqual(self.sender.in_flight_bytes, 0)
        self.assertEqual(self.sender.recovery_metrics['abandoned_deadline'], 1)

    def test_timer_cannot_hold_tracking_beyond_playback_deadline(self):
        self.sender.srtt_ms = 400
        self.frame(count=1)
        self.assertEqual(self.sender.pending[(0, 0)].retry_due_at, 200)
        self.advance(200)
        self.assertEqual(len(self.sent), 1)
        self.assertFalse(self.sender.pending)
        self.assertEqual(self.sender.in_flight_bytes, 0)

    def test_repeated_retries_stop_when_delivery_would_miss_deadline(self):
        with patch.object(call, 'RETRY_BACKOFF_FACTOR', 1):
            self.sender.srtt_ms = 10
            self.sender.estimated_network_jitter = 0
            self.frame(count=1)
            self.advance(150)
            self.assertEqual(self.sender.pending[(0, 0)].retry_count, 2)
            self.advance(200)
        self.assertEqual([time for time, _ in self.sent], [0, 30, 90])
        self.assertFalse(self.sender.pending)
        self.assertFalse(self.sender.retry_timers)
        self.assertEqual(self.sender.in_flight_bytes, 0)
        self.assertEqual(self.sender.recovery_metrics['abandoned_deadline'], 1)

    def test_shared_backoff_applies_to_new_packets_and_resets_on_fresh_sample(self):
        self.sender.srtt_ms = 10
        self.sender.estimated_network_jitter = 0
        self.frame(count=1)
        self.advance(30)
        self.assertEqual(self.sender.rto_backoff, 2)
        self.frame(frame_id=1, count=1)
        self.assertEqual(self.sender.pending[(1, 0)].retry_due_at, 90)
        self.advance(50)
        self.ack((0, 0), frame_id=1)
        self.assertEqual(self.sender.rto_backoff, 1)
        self.assertGreater(self.sender.srtt_ms, 10)

    def test_shared_backoff_is_capped_and_retried_acks_do_not_reset_it(self):
        self.frame(count=4)
        for index in range(4):
            self.sender.resend((0, index), "timeout")
        self.assertEqual(self.sender.rto_backoff, 8)
        self.advance(20)
        self.ack((0, 3))
        self.assertEqual(self.sender.rto_backoff, 8)

    def test_ack_of_retransmission_does_not_update_rtt_or_count_twice(self):
        self.sender.srtt_ms = 10
        self.sender.estimated_network_jitter = 0
        self.frame(count=1)
        self.advance(30)
        self.advance(40)
        self.ack((0, 0))
        self.ack((0, 0))
        self.advance(300)
        self.assertEqual(self.sender.srtt_ms, 10)
        self.assertEqual(self.sender.total_acked_bytes, len(self.sent[0][1]))
        self.assertEqual(self.sender.in_flight_bytes, 0)
        self.assertEqual(len(self.sent), 2)

    def test_abandonment_and_late_ack_do_not_release_window_twice(self):
        self.frame(count=1)
        self.sender.abandon_packet((0, 0), 'deadline')
        self.sender.abandon_packet((0, 0), 'deadline')
        self.advance(100)
        self.ack((0, 0))
        self.ack((0, 0))
        self.advance(1300)
        self.assertEqual(self.sender.in_flight_bytes, 0)
        self.assertFalse(self.sender.pending)
        self.assertFalse(self.sender.expired_packet_timing)
        self.assertEqual(self.sender.total_acked_bytes, 0)
        self.assertEqual(len(self.sender.late_ack_samples), 1)
        self.assertEqual(self.sender.recovery_metrics['abandoned_deadline'], 1)

    def test_fast_retransmit_does_not_repeat_a_timeout_retransmission(self):
        self.frame(count=4)
        self.advance(80)
        before = len(self.sent)
        self.advance(85)
        self.ack((1, 3))
        self.assertEqual(len(self.sent), before)
        self.assertEqual(self.sender.recovery_metrics['retransmissions_sack_gap'], 0)


if __name__ == '__main__':
    unittest.main()
