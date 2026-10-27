"""SACK range and recovery regression tests."""
import struct
import unittest
from types import SimpleNamespace
from unittest.mock import patch
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

    def sack(self, *ranges, receiver_time=0, total_received_bytes=0):
        return struct.pack(
            call.ACK_HEADER, call.ACK, 0, receiver_time, total_received_bytes) + b''.join(
            struct.pack(call.SACK_RANGE, *block) for block in ranges)

    def sender(self):
        sender = call.Sender(self.net, 10000, 20)
        sender.on_frame(SimpleNamespace(id=0, time=0, data=[b'x' * (9 * call.CHUNK)]))
        self.assertEqual(len(self.sent), 9)
        return sender

    def test_gap_retry_and_duplicate_feedback(self):
        sender = self.sender()
        sender.on_packet(self.sack((0, 5), (7, 8)))
        self.assertEqual(set(sender.pending), {(0, 6)})
        self.assertEqual(len(self.sent), 10)
        self.assertEqual(sender.in_flight_bytes, len(self.sent[-1]))
        sender.on_packet(self.sack((0, 5), (7, 8)))
        self.assertEqual(len(self.sent), 10)
        sender.on_packet(self.sack((0, 8)))
        self.assertFalse(sender.pending)
        self.assertEqual(sender.in_flight_bytes, 0)

    def test_timeout_without_feedback(self):
        self.sender()
        self.callbacks[0]()
        self.assertEqual(len(self.sent), 10)

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
        self.assertEqual(header, (call.ACK, 0, 1200, len(packet)))
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
        self.assertEqual(sender.estimated_rate, 200000)
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
        self.assertEqual(sender.estimated_rate, 200000)

    def test_invalid_or_nonmonotonic_reports_do_not_change_rate(self):
        sender = call.Sender(self.net, 1000, 20)
        sender.on_packet(self.sack((0, 0), receiver_time=100, total_received_bytes=1500))
        for receiver_time in (float('nan'), float('inf'), -1):
            sender.on_packet(self.sack((0, 0), receiver_time=receiver_time, total_received_bytes=100000))
        sender.on_packet(self.sack((0, 0), receiver_time=600, total_received_bytes=1000))
        sender.on_packet(self.sack((0, 0), receiver_time=100, total_received_bytes=1500))
        self.assertEqual(sender.last_receiver_report, (100, 1500))
        self.assertEqual(sender.estimated_rate, 125000)
