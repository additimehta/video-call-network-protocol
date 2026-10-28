"""SACK range and recovery regression tests."""
import struct
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
import call


class SackTests(unittest.TestCase):
    def setUp(self):
        self.sent = []
        self.callbacks = []
        self.net = SimpleNamespace(send=self.sent.append)
        def timer(delay, callback):
            self.callbacks.append(callback)
            return SimpleNamespace(cancel=lambda: None)
        for name, replacement in [('now', lambda: 0), ('set_timer', timer)]:
            patcher = patch.object(call.clock, name, replacement)
            patcher.start()
            self.addCleanup(patcher.stop)

    def sack(self, *ranges, receiver_time=0, total_received_bytes=0, triggering_index=None):
        if triggering_index is None:
            triggering_index = ranges[-1][1]
        return struct.pack(
            call.ACK_HEADER, call.ACK, 0, receiver_time, total_received_bytes, triggering_index) + b''.join(
            struct.pack(call.SACK_RANGE, *block) for block in ranges)

    def sender(self):
        sender = call.Sender(self.net, 10000, 20)
        sender.on_frame(SimpleNamespace(id=0, time=0, data=[b'x' * (9 * call.CHUNK)]))
        self.assertEqual(len(self.sent), 9)
        return sender

    def test_gap_retry_and_duplicate_feedback(self):
        sender = self.sender()
        sender.on_packet(self.sack((0, 4), (6, 8)))
        self.assertEqual(set(sender.pending), {(0, 5)})
        self.assertEqual(len(self.sent), 10)
        self.assertEqual(sender.in_flight_bytes, len(self.sent[-1]))
        sender.on_packet(self.sack((0, 4), (6, 8)))
        self.assertEqual(len(self.sent), 10)
        sender.on_packet(self.sack((0, 8)))
        self.assertFalse(sender.pending)
        self.assertEqual(sender.in_flight_bytes, 0)

    def test_timeout_without_feedback(self):
        self.sender()
        self.callbacks[0]()
        self.assertEqual(len(self.sent), 10)

    def test_retry_timeout_tracks_measured_rtt_and_variation(self):
        sender = call.Sender(self.net, 3000, 20)
        sender.pending[(0, 0)] = call.PendingPacket(b'x', 0, 0)
        sender.srtt_ms = 90
        sender.estimated_network_jitter = 15
        first_timer, second_timer = Mock(), Mock()
        with patch.object(call.clock, 'set_timer', side_effect=[first_timer, second_timer]) as timer:
            sender.start_retry_timer((0, 0))
            self.assertEqual(timer.call_args.args[0], 150)
            sender.srtt_ms = 50
            sender.estimated_network_jitter = 1
            sender.start_retry_timer((0, 0))
            self.assertEqual(timer.call_args.args[0], 70)
        first_timer.cancel.assert_called_once_with()
        self.assertIs(sender.retry_timers[(0, 0)], second_timer)

    def test_resend_deadline_uses_measured_rtt_instead_of_initial_rtt(self):
        for initial_rtt, measured_rtt, now, should_retry in (
                (20, 180, 80, False), (180, 20, 100, True)):
            with self.subTest(initial_rtt=initial_rtt, measured_rtt=measured_rtt):
                self.sent.clear()
                sender = self.sender()
                sender.rtt_ms = initial_rtt
                sender.srtt_ms = measured_rtt
                with patch.object(call.clock, 'now', return_value=now):
                    sender.resend((0, 0))
                self.assertEqual(len(self.sent), 10 if should_retry else 9)
                self.assertEqual((0, 0) in sender.pending, should_retry)
                self.assertEqual((0, 0) in sender.expired_packet_timing, not should_retry)

    def test_late_ack_is_recorded_once_without_changing_sending_controls(self):
        for retransmitted in (False, True):
            with self.subTest(retransmitted=retransmitted):
                self.sent.clear()
                sender = self.sender()
                if retransmitted:
                    sender.resend((0, 0))
                expected_bytes = len(sender.pending[(0, 0)].data)
                with patch.object(call.clock, 'now', return_value=200):
                    for packet_id in list(sender.pending):
                        sender.resend(packet_id)
                self.assertEqual(sender.in_flight_bytes, 0)
                self.assertFalse(sender.pending)
                sent_count = len(self.sent)
                controls = lambda: (
                    sender.delivery_delay_ms, sender.srtt_ms,
                    sender.estimated_network_jitter, sender.total_acked_bytes,
                    sender.window_bytes, sender.estimated_rate,
                    sender.probe, sender.next_probe_ms)
                before = controls()
                with patch.object(call.clock, 'now', return_value=250):
                    sender.on_packet(self.sack((0, 0), receiver_time=190))
                    self.assertEqual(controls(), before)
                    self.assertNotIn((0, 0), sender.expired_packet_timing)
                    self.assertEqual(list(sender.late_ack_samples), [{
                        "packet_id": (0, 0), "sent_at_ms": 0,
                        "ack_arrived_at_ms": 250, "receiver_time_ms": 190,
                        "confirmation_delay_ms": 250,
                        "packet_bytes": expected_bytes,
                        "was_retransmitted": retransmitted,
                    }])
                    sender.on_packet(self.sack((0, 0), receiver_time=190))
                    self.assertEqual(len(sender.late_ack_samples), 1)
                    self.assertEqual(controls(), before)
                self.assertEqual(sender.in_flight_bytes, 0)
                self.assertEqual(len(self.sent), sent_count)

    def test_expired_timing_history_is_cleaned_up(self):
        sender = self.sender()
        with patch.object(call.clock, 'now', return_value=200):
            sender.resend((0, 0))
        self.assertIn((0, 0), sender.expired_packet_timing)
        self.callbacks[-1]()
        self.assertNotIn((0, 0), sender.expired_packet_timing)

    def test_late_acks_alone_do_not_reduce_rate_without_a_delivery_deficit(self):
        for sent_bytes, expected_rate in ((100000, 237500), (40000, 375000)):
            with self.subTest(sent_bytes=sent_bytes):
                sender = call.Sender(self.net, 3000, 80)
                sender.record_receiver_arrivals(0, 0)
                sender.sent_bytes = sent_bytes
                sender.late_ack_samples.extend([
                    {"ack_arrived_at_ms": 500, "confirmation_delay_ms": 250,
                     "was_retransmitted": False} for _ in range(3)])
                rtt_before = (sender.srtt_ms, sender.estimated_network_jitter)
                with patch.object(call.clock, 'now', return_value=500):
                    sender.record_receiver_arrivals(500, 50000)
                self.assertEqual(sender.estimated_rate, expected_rate)
                self.assertEqual(rtt_before, (sender.srtt_ms, sender.estimated_network_jitter))
                self.assertEqual(sender.total_acked_bytes, 0)

    def test_elevated_rtt_alone_does_not_reduce_bandwidth(self):
        for srtt, baseline_time, expected in (
                (156, 0, 375000), (157, 0, 375000),
                (157, -5001, 375000)):
            with self.subTest(srtt=srtt, baseline_time=baseline_time):
                sender = call.Sender(self.net, 3000, 80)
                sender.record_receiver_arrivals(0, 0)
                sender.srtt_ms = srtt
                sender.rtt_samples.append((baseline_time, 120))
                sender.sent_bytes = 40000
                with patch.object(call.clock, 'now', return_value=0):
                    sender.record_receiver_arrivals(500, 50000)
                self.assertEqual(sender.estimated_rate, expected)

    def test_late_ack_signal_ignores_stale_retried_and_isolated_samples(self):
        sender = call.Sender(self.net, 3000, 80)
        for count, arrived_at, retransmitted, expected in (
                (2, 500, False, False), (3, 0, False, False),
                (3, 500, True, False), (3, 500, False, True)):
            with self.subTest(count=count, arrived_at=arrived_at,
                              retransmitted=retransmitted):
                sender.late_ack_samples.clear()
                sender.late_ack_samples.extend([
                    {"ack_arrived_at_ms": arrived_at, "confirmation_delay_ms": 250,
                     "was_retransmitted": retransmitted} for _ in range(count)])
                with patch.object(call.clock, 'now', return_value=600):
                    self.assertEqual(sender.late_acks_are_slow(), expected)

    def test_slow_late_acks_block_a_higher_quality_probe(self):
        sender = call.Sender(self.net, 3000, 80)
        sender.next_probe_ms = 0
        sender.late_ack_samples.extend([
            {"ack_arrived_at_ms": 0, "confirmation_delay_ms": 250,
             "was_retransmitted": False} for _ in range(3)])
        frame = SimpleNamespace(id=0, time=0,
                                data=[b'x' * size for size in (1500, 3500, 8500, 17000)])
        self.assertEqual(sender.select_level(frame), 2)
        self.assertIsNone(sender.probe)

    def test_ranges_survive_playback_data_removal(self):
        receiver = call.Receiver(self.net, 10000, 20, SimpleNamespace(show=lambda *args: None))
        for index in (4, 5, 7, 8):
            receiver.on_packet(struct.pack(call.HEADER, call.VIDEO, 0, 0, index, 9) + b'x')
        size = struct.calcsize(call.ACK_HEADER)
        self.assertEqual(list(struct.iter_unpack(call.SACK_RANGE, self.sent[-1][size:])), [(4, 5), (7, 8)])
        receiver.parts.clear()
        receiver.on_packet(struct.pack(call.HEADER, call.VIDEO, 0, 0, 6, 9) + b'x')
        self.assertEqual(list(struct.iter_unpack(call.SACK_RANGE, self.sent[-1][size:])), [(4, 8)])

    def test_malformed_feedback_is_ignored(self):
        sender = self.sender()
        for feedback in (self.sack((8, 4)), self.sack((0, 5), (4, 8)), self.sack((0, 8)) + b'x'):
            sender.on_packet(feedback)
        self.assertEqual(len(sender.pending), 9)
        self.assertEqual(len(self.sent), 9)

    def test_receiver_counts_duplicates_once_after_history_cleanup(self):
        receiver = call.Receiver(self.net, 10000, 20, SimpleNamespace(show=lambda *args: None))
        packet = struct.pack(call.HEADER, call.VIDEO, 0, 0, 0, 2) + b'x'
        receiver.on_packet(packet)
        receiver.parts.clear()
        receiver.received_packet_indices.clear()
        with patch.object(call.clock, 'now', return_value=1200):
            receiver.on_packet(packet)
        header = struct.unpack(call.ACK_HEADER, self.sent[-1][:struct.calcsize(call.ACK_HEADER)])
        self.assertEqual(header, (call.ACK, 0, 1200, len(packet), 0))
        self.assertFalse(receiver.parts)

    def test_receiver_reports_first_arrivals_after_playback_deadline(self):
        receiver = call.Receiver(self.net, 10000, 20, SimpleNamespace(show=lambda *args: None))
        packet = struct.pack(call.HEADER, call.VIDEO, 0, 0, 0, 2) + b'x'
        with patch.object(call.clock, 'now', return_value=201):
            receiver.on_packet(packet)
        self.assertEqual(receiver.total_received_bytes, len(packet))
        self.assertFalse(receiver.parts)

    def test_delivery_rate_uses_receiver_time_despite_feedback_delay(self):
        sender = call.Sender(self.net, 1000, 20)
        sender.on_packet(self.sack((0, 0), receiver_time=100, total_received_bytes=1500))
        with patch.object(call.clock, 'now', return_value=5000):
            sender.on_packet(self.sack((0, 0), receiver_time=600, total_received_bytes=101500))
        self.assertEqual(sender.estimated_rate, 132500)
        self.assertFalse(sender.pending)

    def test_reordered_reports_still_acknowledge_packets(self):
        sender = self.sender()
        sender.on_packet(self.sack((0, 0), receiver_time=600, total_received_bytes=3000))
        sender.on_packet(self.sack((0, 1), receiver_time=500, total_received_bytes=1500))
        self.assertNotIn((0, 1), sender.pending)
        self.assertEqual(sender.last_receiver_report, (600, 3000))

    def test_lost_reports_are_covered_by_cumulative_byte_total(self):
        sender = call.Sender(self.net, 1000, 20)
        sender.record_receiver_arrivals(100, 1500)
        sender.record_receiver_arrivals(1100, 201500)
        self.assertEqual(sender.estimated_rate, 132500)

    def test_invalid_or_nonmonotonic_reports_do_not_change_rate(self):
        sender = call.Sender(self.net, 1000, 20)
        sender.on_packet(self.sack((0, 0), receiver_time=100, total_received_bytes=1500))
        for receiver_time in (float('nan'), float('inf'), -1):
            sender.on_packet(self.sack((0, 0), receiver_time=receiver_time, total_received_bytes=100000))
        sender.on_packet(self.sack((0, 0), receiver_time=600, total_received_bytes=1000))
        sender.on_packet(self.sack((0, 0), receiver_time=100, total_received_bytes=1500))
        self.assertEqual(sender.last_receiver_report, (100, 1500))
        self.assertEqual(sender.estimated_rate, 125000)

    def test_receiver_echoes_the_triggering_index_instead_of_highest_received(self):
        sent = []
        receiver = call.Receiver(SimpleNamespace(send=sent.append), 3000, 80,
                                 SimpleNamespace(show=lambda *args: None))
        for index in (2, 0):
            receiver.on_packet(struct.pack(call.HEADER, call.VIDEO, 0, 0, index, 3) + b'x')
        header = struct.unpack(call.ACK_HEADER, sent[-1][:struct.calcsize(call.ACK_HEADER)])
        self.assertEqual(header[-1], 0)
        self.assertEqual(list(struct.iter_unpack(call.SACK_RANGE, sent[-1][struct.calcsize(call.ACK_HEADER):])),
                         [(0, 0), (2, 2)])
