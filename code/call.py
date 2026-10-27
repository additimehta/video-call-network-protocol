"""Adaptive-quality video with a byte window and selective retransmission."""
from collections import deque
from dataclasses import dataclass
import struct
import math
from statistics import median
import clock

HEADER = "!BIdHH"  # packet type, frame id, capture time (ms), index, packet_count
VIDEO = 0x10      # packet type; 0x01-0x03 are taken by the setup messages
MTU = 1500
FPS = 25
ACK = 0x11
ACK_HEADER = "!BIdQ"  # type, frame ID, receiver time (ms), total unique video bytes
SACK_RANGE = "!HH"  # inclusive first and last packet index
CHUNK = MTU - struct.calcsize(HEADER)


@dataclass
class PendingPacket:
    data: bytes
    capture_time: float
    sent_at: float
    was_retransmitted: bool = False


# Group sorted packet indices into inclusive ranges, such as [4, 5] and [7, 8].
def build_received_ranges(packet_indices):
    received_ranges = []
    for packet_index in packet_indices:
        if not received_ranges:
            received_ranges.append([packet_index, packet_index])
            continue

        previous_range = received_ranges[-1]
        previous_last_index = previous_range[1]
        if packet_index == previous_last_index + 1:
            previous_range[1] = packet_index
        else:
            received_ranges.append([packet_index, packet_index])
    return received_ranges


# Check whether a packet index belongs to any received range.
def is_packet_received(packet_index, received_ranges):
    for first_index, last_index in received_ranges:
        if first_index <= packet_index <= last_index:
            return True
    return False


class Sender:
    # Set up the sending queue, bandwidth estimates, and packet recovery state.
    def __init__(self, net, rate_kbps, rtt_ms):
        self.net = net
        self.bytes_per_second = rate_kbps * 1000 / 8
        self.estimated_rate = self.bytes_per_second
        self.last_receiver_report = None  # (receiver time, total received bytes)
        self.receiver_rate_sample = None  # baseline for the next 500 ms measurement
        self.sent_bytes = 0
        self.total_acked_bytes = 0
        self.probe = None  # (level, start time, initial ACK bytes, required rate)
        self.next_probe_ms = clock.now() + 2000
        # Start conservatively with room for a frame's transmission and jitter.
        # Replace this estimate with measured ACK turnaround as packets arrive.
        self.ack_rtt_ms = rtt_ms + 40
        self.delivery_delay_ms = rtt_ms + 40
        self.rtt_variation_ms = 5
        self.update_window()
        self.in_flight_bytes = 0 # bytes sent not ACK
        self.frames = deque()  # frames retaining every quality until transmission
        self.active_frame = None  # (frame, chosen data, next packet index)
        # ACKs for later segments also wait behind a frame's transmission.
        # Allow 40 ms for that frame plus 20 ms for jitter beyond propagation.
        self.rtt_ms = rtt_ms
        # (frame ID, packet index) -> PendingPacket.
        self.pending = {}
        self.expired_packet_timing = {}  # packet ID -> send time, byte count, retry flag
        self.late_ack_samples = deque(maxlen=256)
        self.retry_timers = {}

    # Calculate how many bytes be sent while waiting for acknowledgments.
    def update_window(self):
        allowance_ms = min(120, self.ack_rtt_ms + 4 * self.rtt_variation_ms)
        window_rate = max(self.bytes_per_second, self.estimated_rate)
        if self.probe is not None:
            window_rate = max(window_rate, self.probe[3])
        self.window_bytes = max(
            MTU, window_rate * allowance_ms / 1000 + MTU)

    # Queue a newly captured frame and send packets if the window has room.
    def on_frame(self, frame):
        self.frames.append(frame)
        self.send_waiting()

    # Optionally update RTT and variation, then return the allowed ACK delay in ms.
    def allowable_ack_rtt_ms(self, sample_rtt_ms=None):
        if sample_rtt_ms is not None:
            error = abs(sample_rtt_ms - self.ack_rtt_ms)
            self.rtt_variation_ms = 0.75 * self.rtt_variation_ms + 0.25 * error
            self.ack_rtt_ms = 0.875 * self.ack_rtt_ms + 0.125 * sample_rtt_ms
        return self.ack_rtt_ms + max(20, 4 * self.rtt_variation_ms)

    # Require several recent late confirmations before treating delivery as slow.
    def late_acks_are_slow(self):
        recent_delays = [
            sample["confirmation_delay_ms"] for sample in self.late_ack_samples
            if clock.now() - sample["ack_arrived_at_ms"] <= 500
            and not sample["was_retransmitted"]
        ]
        delay_limit_ms = self.allowable_ack_rtt_ms()
        return len(recent_delays) >= 3 and median(recent_delays) > delay_limit_ms

    # Choose frame quality using estimated bandwidth and occasional higher-quality trials.
    def select_level(self, frame):
        now = clock.now()
        # Check ACK delivery and how long the frame has been waiting.
        delay_limit_ms = self.allowable_ack_rtt_ms()
        healthy = (self.delivery_delay_ms <= delay_limit_ms
                   and not self.late_acks_are_slow()
                   and now - frame.time < 80)
        if self.probe is not None:
            level, started, acked_at_start, required_rate = self.probe
            elapsed = now - started
            if elapsed >= 600 or (elapsed >= 160 and not healthy):
                delivered = (self.total_acked_bytes - acked_at_start) * 1000 / elapsed
                if healthy and delivered >= required_rate * 0.85:
                    # A successful trial establishes capacity for this level,
                    # including the recovery margin used below.ok go
                    self.estimated_rate = max(self.estimated_rate, required_rate / 0.9)
                self.probe = None
                self.next_probe_ms = now + 2000
                self.update_window()
            else:
                selected_level = level
                print(
                    f"[QUALITY] t={clock.now():.0f}ms "
                    f"frame={frame.id} "
                    f"estimated={self.estimated_rate * 8 / 1000:.0f}kbps "
                    f"level={selected_level} "
                    f"probe={self.probe is not None}"
                )
                return level
        # Include packet headers and reserve 10% of capacity for recovery.
        available_bandwidth_bps = max(1, self.estimated_rate * 0.9) * 8
        selected_level = 0  # Best effort if even the smallest frame cannot fit.
        for level, data in enumerate(frame.data):
            packet_count = (len(data) + CHUNK - 1) // CHUNK
            wire_bytes = len(data) + packet_count * struct.calcsize(HEADER)
            required_bandwidth_bps = wire_bytes * FPS * 8
            if required_bandwidth_bps <= available_bandwidth_bps:
                selected_level = level
        # after stable delivery, then validate it using actual acknowledged bytes.


        if healthy and now >= self.next_probe_ms and selected_level + 1 < len(frame.data):
            trial_level = selected_level + 1
            data = frame.data[trial_level]
            packet_count = (len(data) + CHUNK - 1) // CHUNK
            required_rate = (len(data) + packet_count * struct.calcsize(HEADER)) * FPS
            self.probe = (trial_level, now, self.total_acked_bytes, required_rate)
            selected_level = trial_level
            self.update_window()
        print(
            f"[QUALITY] t={clock.now():.0f}ms "
            f"frame={frame.id} "
            f"estimated={self.estimated_rate * 8 / 1000:.0f}kbps "
            f"level={selected_level} "
            f"probe={self.probe is not None}"
        )
        return selected_level

    # Track acknowledged bytes for quality probes and update delivery delay.
    def record_delivery(self, packet_bytes, delivery_age):
        self.total_acked_bytes += packet_bytes
        # Includes recovery time for retried packets. This is a congestion
        # signal, separate from unambiguous RTT samples used by the window.
        self.delivery_delay_ms = 0.875 * self.delivery_delay_ms + 0.125 * delivery_age

    # Record first acknowledgment timing, excluding retries from RTT estimation.
    def record_acknowledgment(self, sent_at, packet_bytes, was_retransmitted):
        sample = clock.now() - sent_at
        self.record_delivery(packet_bytes, sample)
        if not was_retransmitted:
            self.allowable_ack_rtt_ms(sample)
            self.update_window()

    # Estimate delivery rate from unique bytes arriving at the receiver over time.
    def record_receiver_arrivals(self, receiver_time, total_received_bytes):
        if self.last_receiver_report is not None:
            previous_time, previous_bytes = self.last_receiver_report
            if receiver_time <= previous_time or total_received_bytes < previous_bytes:
                return
        self.last_receiver_report = (receiver_time, total_received_bytes)

        if self.receiver_rate_sample is None:
            self.receiver_rate_sample = (receiver_time, total_received_bytes)
            self.sent_bytes = 0
            return

        sample_time, sample_bytes = self.receiver_rate_sample
        elapsed_ms = receiver_time - sample_time
        if elapsed_ms < 500:
            return
        received_bytes = total_received_bytes - sample_bytes
        delivered_rate = received_bytes * 1000 / elapsed_ms
        # Low-quality video may not fill the link. Only interpret low delivery
        # as a capacity drop when it also falls behind what we are sending.
        # Slow ACK turnaround detects queues inside the network, even when
        # the frame buffer at the sender is small.
        oldest = self.active_frame[0] if self.active_frame is not None else (
            self.frames[0] if self.frames else None)
        backed_up = oldest is not None and clock.now() - oldest.time >= 80
        delay_limit_ms = self.allowable_ack_rtt_ms()
        slow_acks = (self.delivery_delay_ms > delay_limit_ms
                     or self.late_acks_are_slow())
        old_rate = self.estimated_rate
        if (backed_up or slow_acks) and received_bytes < 0.9 * self.sent_bytes:
            self.estimated_rate = max(1, min(self.estimated_rate, delivered_rate))
        elif delivered_rate > self.estimated_rate:
            self.estimated_rate = delivered_rate
        print(
            f"[RATE] t={clock.now():.0f}ms "
            f"measured={delivered_rate * 8 / 1000:.0f}kbps "
            f"estimate={old_rate * 8 / 1000:.0f}"
            f"->{self.estimated_rate * 8 / 1000:.0f}kbps "
            f"backed_up={backed_up} slow_acks={slow_acks}"
        )
        self.receiver_rate_sample = (receiver_time, total_received_bytes)
        self.sent_bytes = 0

    # Send queued frame packets within the byte window and drop frames that are too old.
    def send_waiting(self):
        while self.active_frame is not None or self.frames:
            if self.active_frame is None:
                frame = self.frames[0]
                if clock.now() + self.rtt_ms / 2 + 40 >= frame.time + 200:
                    self.frames.popleft()
                    continue
                # Reserve room for a full packet before choosing quality.
                if self.in_flight_bytes + MTU > self.window_bytes:
                    break
                level = self.select_level(frame)
                self.active_frame = (self.frames.popleft(), frame.data[level], 0)

            frame, data, packet_index = self.active_frame
            if clock.now() + self.rtt_ms / 2 + 40 >= frame.time + 200:
                self.active_frame = None
                continue
            packet_count = (len(data) + CHUNK - 1) // CHUNK
            payload = data[packet_index * CHUNK:(packet_index + 1) * CHUNK]
            packet = struct.pack(HEADER, VIDEO, frame.id, frame.time, packet_index, packet_count) + payload
            if self.in_flight_bytes + len(packet) > self.window_bytes:
                break
            packet_id = (frame.id, packet_index)
            # Freeze data at the selected quality for the entire frame.
            self.active_frame = None if packet_index + 1 == packet_count else (frame, data, packet_index + 1)
            self.pending[packet_id] = PendingPacket(packet, frame.time, clock.now())
            self.in_flight_bytes += len(packet)
            self.sent_bytes += len(packet)
            self.net.send(packet)
            self.start_retry_timer(packet_id)

    # Start or replace the timer that retries a packet if no acknowledgment arrives.
    def start_retry_timer(self, packet_id):
        previous = self.retry_timers.pop(packet_id, None)
        if previous is not None:
            previous.cancel()
        self.retry_timers[packet_id] = clock.set_timer(
            self.allowable_ack_rtt_ms(), lambda packet_id=packet_id: self.resend(packet_id))

    # Resend a missing packet, or stop tracking it if it is too old to arrive in time.
    def resend(self, packet_id):
        if packet_id not in self.pending:
            return  # Its ACK already arrived; nothing to resend.

        pending_packet = self.pending[packet_id]
        # Approximate forward delivery with measured RTT plus a playback margin.
        # Half the RTT is an estimate; forward and reverse delays can differ.
        if clock.now() + self.ack_rtt_ms / 2 + 40 >= pending_packet.capture_time + 200:
            # packet too old to resend
            del self.pending[packet_id]
            self.expired_packet_timing[packet_id] = (
                pending_packet.sent_at, len(pending_packet.data),
                pending_packet.was_retransmitted)
            clock.set_timer(1000, lambda packet_id=packet_id:
                            self.expired_packet_timing.pop(packet_id, None))
            timer = self.retry_timers.pop(packet_id, None)
            if timer is not None:
                timer.cancel()
            self.in_flight_bytes -= len(pending_packet.data)
            self.send_waiting()
            return

        # An ACK after a retry cannot tell us which transmission it acknowledges.
        pending_packet.was_retransmitted = True
        # Allow one fast retransmission per packet; retain timeout recovery
        # if the retry is lost too, without repeated bursts of fast retries.
        self.net.send(pending_packet.data)
        self.start_retry_timer(packet_id)

    # Read SACK ranges, clear acknowledged packets, and retry gaps before sending more data.
    def on_packet(self, packet):
        header_size = struct.calcsize(ACK_HEADER)
        range_size = struct.calcsize(SACK_RANGE)
        if (len(packet) < header_size + range_size or len(packet) > MTU
                or (len(packet) - header_size) % range_size):
            return
        packet_type, frame_id, receiver_time, total_received_bytes = struct.unpack(
            ACK_HEADER, packet[:header_size])
        if packet_type != ACK or not math.isfinite(receiver_time) or receiver_time < 0:
            return
        received_ranges = list(struct.iter_unpack(SACK_RANGE, packet[header_size:]))
        # Require sorted, disjoint ranges before changing sender state.
        previous_last_index = -1
        for first_index, last_index in received_ranges:
            if first_index > last_index or first_index <= previous_last_index:
                return
            previous_last_index = last_index

        # Each range acknowledges only packets actually received, with no
        # cumulative acknowledgment across gaps. Repeated SACKs are harmless.
        for packet_id in list(self.pending):
            packet_frame_id, packet_index = packet_id
            if packet_frame_id != frame_id or not is_packet_received(packet_index, received_ranges):
                continue
            acknowledged = self.pending.pop(packet_id)
            self.retry_timers.pop(packet_id).cancel()
            self.in_flight_bytes -= len(acknowledged.data)
            self.record_acknowledgment(
                acknowledged.sent_at, len(acknowledged.data),
                acknowledged.was_retransmitted)

        # Expiration releases window space but preserves feedback for one second.
        for packet_id in list(self.expired_packet_timing):
            packet_frame_id, packet_index = packet_id
            if packet_frame_id != frame_id or not is_packet_received(packet_index, received_ranges):
                continue
            sent_at, packet_bytes, was_retransmitted = self.expired_packet_timing.pop(packet_id)
            self.late_ack_samples.append({
                "packet_id": packet_id,
                "sent_at_ms": sent_at,
                "ack_arrived_at_ms": clock.now(),
                "receiver_time_ms": receiver_time,
                "confirmation_delay_ms": clock.now() - sent_at,
                "packet_bytes": packet_bytes,
                "was_retransmitted": was_retransmitted,
            })

        # Measurements remain useful even when all listed packets have expired.
        self.record_receiver_arrivals(receiver_time, total_received_bytes)

        # A received later packet exposes earlier gaps, even across frames.
        # Retry immediately once; a timer handles lost retries or lost SACKs.
        latest_received_packet = (frame_id, received_ranges[-1][1])
        for packet_id in list(self.pending):
            if packet_id >= latest_received_packet or packet_id not in self.pending:
                continue
            pending_packet = self.pending[packet_id]
            if not pending_packet.was_retransmitted:
                self.resend(packet_id)
        self.send_waiting()


class Receiver:
    # Set up packet receipt history, frame assembly buffers, and playback state.
    def __init__(self, net, rate_kbps, rtt_ms, player):
        self.player = player
        self.net = net
        self.total_received_bytes = 0
        self.counted_packet_ids = set()  
        self.received_packet_indices = {}  # frame ID -> received indices, independent of playback data
        self.parts = {}  # frame id -> packet pieces awaiting reassembly
        self.ready = {}  # complete frames awaiting their playback slot
        self.last_shown = -1

    # Record a video packet, send SACK feedback, and assemble complete frames for playback.
    def on_packet(self, packet):
        header_size = struct.calcsize(HEADER)
        if len(packet) < header_size or len(packet) > MTU:
            return
        packet_type, frame_id, capture_time, packet_index, packet_count = struct.unpack(HEADER, packet[:header_size])
        if packet_type != VIDEO or not 0 <= packet_index < packet_count:
            return
        packet_id = (frame_id, packet_index)
        if packet_id not in self.counted_packet_ids:
            self.counted_packet_ids.add(packet_id)
            self.total_received_bytes += len(packet)
        # Keep receipt history separate so deleting playback data does not
        # erase SACK information. Expired/duplicate arrivals also get feedback.
        if frame_id not in self.received_packet_indices:
            self.received_packet_indices[frame_id] = set()
            clock.set_timer(1000, lambda frame_id=frame_id: self.received_packet_indices.pop(frame_id, None))
        self.received_packet_indices[frame_id].add(packet_index)
        self.send_sack(frame_id, packet_index)
        deadline = capture_time + 200
        if clock.now() > deadline or frame_id <= self.last_shown or frame_id in self.ready:
            return
        if frame_id not in self.parts:
            self.parts[frame_id] = {}
            # Keep partial data through the deadline, including arrivals exactly
            # at that time. Cleanup just afterward bounds reassembly storage.
            clock.set_timer(deadline + 1 - clock.now(),
                            lambda frame_id=frame_id: self.parts.pop(frame_id, None))
        parts = self.parts[frame_id]
        parts[packet_index] = packet[header_size:]
        if len(parts) == packet_count:
            self.ready[frame_id] = b"".join(parts[packet_index] for packet_index in range(packet_count))
            del self.parts[frame_id]
            # Capture times are spaced 40 ms apart, so these slots preserve
            # order and feed at most one frame to each player refresh.
            clock.set_timer(deadline - clock.now(),
                            lambda frame_id=frame_id: self.play_frame(frame_id))

    # Send the received packet ranges for a frame, keeping the feedback within one MTU.
    def send_sack(self, frame_id, packet_index):
        received_ranges = build_received_ranges(
            sorted(self.received_packet_indices[frame_id]))
        # Keep feedback within one MTU; always include the range containing the triggering packet.
        max_ranges = (MTU - struct.calcsize(ACK_HEADER)) // struct.calcsize(SACK_RANGE)
        if len(received_ranges) > max_ranges:
            triggering_range = next(block for block in received_ranges if block[0] <= packet_index <= block[1])
            received_ranges = received_ranges[-max_ranges:]
            if triggering_range not in received_ranges:
                received_ranges = sorted([triggering_range] + received_ranges[1:])
        self.net.send(struct.pack(
            ACK_HEADER, ACK, frame_id, clock.now(), self.total_received_bytes) + b"".join(
            struct.pack(SACK_RANGE, first_index, last_index)
            for first_index, last_index in received_ranges))

    # Hand a complete frame to the player if it is newer than the last displayed frame.
    def play_frame(self, frame_id):
        data = self.ready.pop(frame_id, None)
        if data is not None and frame_id > self.last_shown:
            self.player.show(frame_id, data)
            self.last_shown = frame_id
