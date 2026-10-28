"""Adaptive-quality video with a byte window and selective retransmission."""
from collections import Counter, deque
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
ACK_HEADER = "!BIdQH"  # type, frame ID, receiver time, unique received bytes, triggering index
SACK_RANGE = "!HH"  # inclusive first and last packet index
CHUNK = MTU - struct.calcsize(HEADER)
FAST_RETRANSMIT_PACKETS = 3
RETRY_BACKOFF_FACTOR = 2


@dataclass
class PendingPacket:
    """Original send metadata plus per-packet recovery state.

    retry_count counts all retransmissions; timeout_retries counts only those
    triggered by timeouts. retry_due_at records the next scheduled timeout
    or cleanup time in simulation milliseconds.
    """

    data: bytes
    capture_time: float
    sent_at: float
    was_retransmitted: bool = False
    retry_count: int = 0
    timeout_retries: int = 0
    retry_due_at: float | None = None
    sequence: int = 0


# Group sorted packet indices into inclusive ranges, such as [4, 5] and [7, 8].
# Returns: A list of inclusive [first, last] packet-index ranges.
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
# Returns: True if the index is in a received range; otherwise False.
def is_packet_received(packet_index, received_ranges):
    for first_index, last_index in received_ranges:
        if first_index <= packet_index <= last_index:
            return True
    return False


class Sender:
    """Send video using bandwidth adaptation, a byte window, and SACK recovery.

    Instance state:
        net: Network interface used to send packets.
        init_bw_bps: Initial bandwidth in bytes per second; remains fixed.
        estimated_rate: Current bandwidth estimate in bytes per second.
        last_receiver_report: Latest accepted (receiver time, unique byte total).
        receiver_rate_sample: Report marking the start of a delivery-rate interval.
        sent_bytes: Original packet bytes sent since that interval was started.
        total_acked_bytes: Acknowledged bytes from pending packets, used by probes.
        probe: Active (quality level, start time, initial ACK bytes, required rate),
            or None. Required rate is in bytes per second.
        next_probe_ms: Earliest simulation time at which another probe may start.
        srtt_ms: Smoothed ACK turnaround excluding retransmitted packets.
        delivery_delay_ms: Smoothed confirmation delay including recovery time.
        estimated_network_jitter: Smoothed RTT deviation in milliseconds.
        window_bytes: Maximum outstanding tracked bytes allowed by the window.
        in_flight_bytes: Bytes still in pending; excludes expired packets and
            additional copies sent by retransmission.
        frames: Unsent frames retaining every quality until one is selected.
        active_frame: Current (frame, selected data, next packet index), or None.
        rtt_ms: Initial propagation RTT used by original-send deadline checks.
        pending: (frame ID, packet index) mapped to a PendingPacket.
        expired_packet_timing: Packet ID mapped to (original send time, byte
            count, retry flag), retained for one second after expiration.
        late_ack_samples: Up to 256 late confirmation records for overload checks.
        retry_timers: Packet ID mapped to its current retry timer.
        recovery_metrics: Counts of retries by cause and packet abandonment.
        retransmissions_by_attempt: Counts of first, second, etc. retransmissions.

    Times are simulation milliseconds unless otherwise stated. Initial delay
    estimates include 40 ms of allowance until ACK measurements replace them.
    """

    # Returns: None; initializes the instance state documented above.
    def __init__(self, net, rate_kbps, rtt_ms):
        self.net = net
        self.init_bw_bps = rate_kbps * 1000 / 8
        self.estimated_rate = self.init_bw_bps
        self.last_receiver_report = None
        self.receiver_rate_sample = None
        self.sent_bytes = 0
        self.total_acked_bytes = 0
        self.probe = None
        self.next_probe_ms = clock.now() + 2000
        self.srtt_ms = rtt_ms + 40
        self.rtt_samples = deque()
        self.delivery_delay_ms = rtt_ms + 40
        self.estimated_network_jitter = 5
        self.rto_backoff = 1
        self.cwnd_bytes = 10 * MTU
        self.ssthresh_bytes = float("inf")
        self.next_packet_sequence = 0
        self.recovery_end_sequence = -1
        self.update_window()
        self.in_flight_bytes = 0
        self.frames = deque()
        self.active_frame = None
        self.rtt_ms = rtt_ms
        self.pending = {}
        self.expired_packet_timing = {}
        self.late_ack_samples = deque(maxlen=256)
        self.retry_timers = {}
        self.recovery_metrics = Counter({
            "retransmissions_timeout": 0,
            "retransmissions_sack_gap": 0,
        })
        self.retransmissions_by_attempt = Counter()

    # Apply the congestion window to the maximum outstanding byte count.
    # Returns: None; updates self.window_bytes.
    def update_window(self):
        self.window_bytes = max(MTU, self.cwnd_bytes)

    # Grow only for newly acknowledged packets outside the last loss episode.
    # Returns: None; updates the congestion window without counting duplicate ACKs.
    def increase_congestion_window(self, packet_bytes, sequence):
        if sequence <= self.recovery_end_sequence:
            return
        if self.cwnd_bytes < self.ssthresh_bytes:
            self.cwnd_bytes += min(packet_bytes, MTU)
        else:
            self.cwnd_bytes += MTU * packet_bytes / self.cwnd_bytes
        self.update_window()

    # Reduce once for losses among packets already outstanding at the first loss.
    # Returns: None; records a loss episode and updates its recovery boundary.
    def reduce_congestion_window(self, pending, reason):
        if pending.sequence <= self.recovery_end_sequence:
            return
        self.recovery_end_sequence = self.next_packet_sequence - 1
        self.ssthresh_bytes = max(
            2 * MTU, min(self.cwnd_bytes, self.in_flight_bytes) / 2)
        self.cwnd_bytes = MTU if reason == "timeout" else self.ssthresh_bytes
        self.probe = None
        self.next_probe_ms = clock.now() + 2000
        self.recovery_metrics["congestion_events_" + reason] += 1
        self.update_window()

    # Queue a newly captured frame and send packets if the window has room.
    # Returns: None; queues the frame and attempts transmission.
    def on_frame(self, frame):
        self.frames.append(frame)
        self.send_waiting()

    # Optionally update RTT and variation, then return the allowed ACK delay in ms.
    # Returns: Allowed ACK turnaround in milliseconds, optionally updating RTT estimates.
    def allowable_ack_rtt_ms(self, sample_rtt_ms=None):
        if sample_rtt_ms is not None:
            error = abs(sample_rtt_ms - self.srtt_ms)
            self.estimated_network_jitter = 0.75 * self.estimated_network_jitter + 0.25 * error
            self.srtt_ms = 0.875 * self.srtt_ms + 0.125 * sample_rtt_ms
        return self.srtt_ms + max(20, 4 * self.estimated_network_jitter)

    # Require several recent late confirmations before treating delivery as slow.
    # Returns: True if enough recent late ACKs exceed the allowed delay; otherwise False.
    def late_acks_are_slow(self):
        recent_delays = [
            sample["confirmation_delay_ms"] for sample in self.late_ack_samples
            if clock.now() - sample["ack_arrived_at_ms"] <= 500
            and not sample["was_retransmitted"]
        ]
        delay_limit_ms = self.allowable_ack_rtt_ms()
        return len(recent_delays) >= 3 and median(recent_delays) > delay_limit_ms

    # Choose frame quality using estimated bandwidth and occasional higher-quality trials.
    # Returns: The selected integer quality level, including any active probe level.
    def select_level(self, frame):
        now = clock.now()
        window_rate = self.cwnd_bytes * 1000 / max(1, self.srtt_ms)
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
            elif self.probe[3] <= window_rate * 0.9:
                selected_level = level
                print(
                    f"[QUALITY] t={clock.now():.0f}ms "
                    f"frame={frame.id} "
                    f"estimated={self.estimated_rate * 8 / 1000:.0f}kbps "
                    f"level={selected_level} "
                    f"probe={self.probe is not None}"
                )
                return level
            else:
                self.probe = None
                self.next_probe_ms = now + 2000
        # Include packet headers and reserve 10% of capacity for recovery.
        available_bandwidth_bps = max(
            1, min(self.estimated_rate, window_rate) * 0.9) * 8
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
            if required_rate <= window_rate * 0.9:
                self.probe = (trial_level, now, self.total_acked_bytes, required_rate)
                selected_level = trial_level
        print(
            f"[QUALITY] t={clock.now():.0f}ms "
            f"frame={frame.id} "
            f"estimated={self.estimated_rate * 8 / 1000:.0f}kbps "
            f"level={selected_level} "
            f"probe={self.probe is not None}"
        )
        return selected_level

    # Track acknowledged bytes for quality probes and update delivery delay.
    # Returns: None; updates acknowledged-byte and confirmation-delay measurements.
    def record_delivery(self, packet_bytes, delivery_age):
        self.total_acked_bytes += packet_bytes
        # Includes recovery time for retried packets. This is a congestion
        # signal, separate from unambiguous RTT samples used by the window.
        self.delivery_delay_ms = 0.875 * self.delivery_delay_ms + 0.125 * delivery_age

    # Record first acknowledgment timing, excluding retries from RTT estimation.
    # Returns: None; records delivery and updates RTT only for unretransmitted packets.
    def record_acknowledgment(self, sent_at, packet_bytes, was_retransmitted):
        sample = clock.now() - sent_at
        self.record_delivery(packet_bytes, sample)
        if not was_retransmitted:
            self.rtt_samples.append((clock.now(), sample))
            self.allowable_ack_rtt_ms(sample)
            self.rto_backoff = 1
            self.update_window()

    # Estimate delivery rate from unique bytes arriving at the receiver over time.
    # Returns: None; updates receiver reports and, when eligible, the bandwidth estimate.
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
        # Timing and throughput remain diagnostics; ACK/loss controls the window.
        oldest = self.active_frame[0] if self.active_frame is not None else (
            self.frames[0] if self.frames else None)
        backed_up = oldest is not None and clock.now() - oldest.time >= 80
        delay_limit_ms = self.allowable_ack_rtt_ms()
        slow_acks = (
            self.delivery_delay_ms > delay_limit_ms
            or self.late_acks_are_slow()
        )
        while self.rtt_samples and clock.now() - self.rtt_samples[0][0] > 5000:
            self.rtt_samples.popleft()
        baseline_rtt = min(
            (sample for _, sample in self.rtt_samples), default=self.srtt_ms)
        congested = self.srtt_ms > baseline_rtt * 1.3
        old_rate = self.estimated_rate

        # Raise the capacity estimate cautiously when actual delivery exceeds it.
        if delivered_rate > self.estimated_rate:
            self.estimated_rate = (
                0.9 * self.estimated_rate + 0.1 * delivered_rate)
        
        print(
            f"[RATE] t={clock.now():.0f}ms "
            f"measured={delivered_rate * 8 / 1000:.0f}kbps "
            f"estimate={old_rate * 8 / 1000:.0f}"
            f"->{self.estimated_rate * 8 / 1000:.0f}kbps "
            f"sent={self.sent_bytes} "
            f"received={received_bytes} "
            f"ratio={received_bytes / max(1, self.sent_bytes):.2f} "
            f"backed_up={backed_up} slow_acks={slow_acks} "
            f"congested={congested} baseline_rtt={baseline_rtt:.1f} "
            f"srtt={self.srtt_ms:.1f} "
            f"jitter={self.estimated_network_jitter:.1f} "
            f"delivery_delay={self.delivery_delay_ms:.1f} "
            f"delay_limit={delay_limit_ms:.1f}"
            f" window_bytes={self.window_bytes:.0f}"
            f" ssthresh_bytes={self.ssthresh_bytes:.0f}"
            f" rto_backoff={self.rto_backoff}"
            f" retransmissions_timeout={self.recovery_metrics['retransmissions_timeout']}"
            f" retransmissions_sack_gap={self.recovery_metrics['retransmissions_sack_gap']}"
        )
        self.receiver_rate_sample = (receiver_time, total_received_bytes)
        self.sent_bytes = 0

    # Send queued frame packets within the byte window and drop frames that are too old.
    # Returns: None; sends packets within the window and abandons expired frames.
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
            self.pending[packet_id] = PendingPacket(
                packet, frame.time, clock.now(), sequence=self.next_packet_sequence)
            self.next_packet_sequence += 1
            self.in_flight_bytes += len(packet)
            self.sent_bytes += len(packet)
            self.net.send(packet)
            self.start_retry_timer(packet_id)

    # Start or replace the timer that retries a packet if no acknowledgment arrives.
    # Returns: None; stores the new timer in self.retry_timers.
    def start_retry_timer(self, packet_id):
        pending = self.pending.get(packet_id)
        if pending is None:
            return
        previous = self.retry_timers.pop(packet_id, None)
        if previous is not None:
            previous.cancel()
        timeout_ms = (
            self.allowable_ack_rtt_ms() * self.rto_backoff
            * (RETRY_BACKOFF_FACTOR ** pending.timeout_retries))
        remaining_ms = max(0, pending.capture_time + 200 - clock.now())
        delay_ms = min(timeout_ms, remaining_ms)
        pending.retry_due_at = clock.now() + delay_ms
        if remaining_ms <= timeout_ms:
            callback = lambda packet_id=packet_id: self.abandon_packet(packet_id, "deadline")
        else:
            callback = lambda packet_id=packet_id: self.resend(packet_id, "timeout")
        self.retry_timers[packet_id] = clock.set_timer(
            delay_ms, callback)

    # Require three distinct later SACKed packets before a same-frame fast retry.
    # Returns: None; retries at most once through SACK evidence, subject to deadlines.
    def check_fast_retransmit(self, packet_id, received_ranges):
        pending = self.pending.get(packet_id)
        if pending is None or pending.was_retransmitted:
            return
        packet_index = packet_id[1]
        later_received = sum(
            max(0, last - max(first, packet_index + 1) + 1)
            for first, last in received_ranges)
        if later_received >= FAST_RETRANSMIT_PACKETS:
            self.resend(packet_id, "sack_gap")

    # Release tracking exactly once while retaining lightweight late-ACK metadata.
    # Returns: None; removes retry state and makes released window space available.
    def abandon_packet(self, packet_id, reason):
        pending = self.pending.pop(packet_id, None)
        if pending is None:
            return
        self.expired_packet_timing[packet_id] = (
            pending.sent_at, len(pending.data), pending.was_retransmitted)
        clock.set_timer(1000, lambda packet_id=packet_id:
                        self.expired_packet_timing.pop(packet_id, None))
        timer = self.retry_timers.pop(packet_id, None)
        if timer is not None:
            timer.cancel()
        self.in_flight_bytes -= len(pending.data)
        self.recovery_metrics["abandoned_" + reason] += 1
        self.send_waiting()

    # Resend a missing packet, or stop tracking it if it is too old to arrive in time.
    # Returns: None; retries the packet or removes expired tracking.
    def resend(self, packet_id, reason="timeout"):
        if packet_id not in self.pending:
            return  # Its ACK already arrived; nothing to resend.

        pending_packet = self.pending[packet_id]
        if reason == "timeout":
            self.rto_backoff = min(self.rto_backoff * 2, 8)
        self.reduce_congestion_window(pending_packet, reason)
        # Approximate forward delivery with measured RTT plus a playback margin.
        # Half the RTT is an estimate; forward and reverse delays can differ.
        if clock.now() + self.srtt_ms / 2 + 40 >= pending_packet.capture_time + 200:
            self.abandon_packet(packet_id, "deadline")
            return

        # An ACK after a retry cannot tell us which transmission it acknowledges.
        pending_packet.was_retransmitted = True
        pending_packet.retry_count += 1
        if reason == "timeout":
            pending_packet.timeout_retries += 1
        self.recovery_metrics["retransmissions"] += 1
        self.recovery_metrics["retransmissions_" + reason] += 1
        self.retransmissions_by_attempt[pending_packet.retry_count] += 1
        self.net.send(pending_packet.data)
        self.start_retry_timer(packet_id)

    # Read SACK ranges, clear acknowledged packets, and retry gaps before sending more data.
    # Returns: None; processes feedback or video packets and updates endpoint state.
    def on_packet(self, packet):
        header_size = struct.calcsize(ACK_HEADER)
        range_size = struct.calcsize(SACK_RANGE)
        if (len(packet) < header_size + range_size or len(packet) > MTU
                or (len(packet) - header_size) % range_size):
            return
        packet_type, frame_id, receiver_time, total_received_bytes, triggering_index = struct.unpack(
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

        if not is_packet_received(triggering_index, received_ranges):
            return

        # Each range acknowledges only packets actually received, with no
        # cumulative acknowledgment across gaps. Repeated SACKs are harmless.
        for packet_id in list(self.pending):
            packet_frame_id, packet_index = packet_id
            if packet_frame_id != frame_id or not is_packet_received(packet_index, received_ranges):
                continue
            acknowledged = self.pending.pop(packet_id)
            self.retry_timers.pop(packet_id).cancel()
            self.in_flight_bytes -= len(acknowledged.data)
            self.increase_congestion_window(len(acknowledged.data), acknowledged.sequence)
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

        # Count distinct later received packets in this frame, not repeated ACK messages.
        latest_received_index = received_ranges[-1][1]
        for packet_id in list(self.pending):
            if packet_id[0] != frame_id or packet_id[1] >= latest_received_index:
                continue
            self.check_fast_retransmit(packet_id, received_ranges)
        self.send_waiting()


class Receiver:
    """Assemble video packets, acknowledge receipts, and schedule playback.

    Instance state:
        player: Playback interface receiving complete frames.
        net: Network interface used to send ACKs.
        total_received_bytes: Cumulative unique video bytes, including headers
            and late arrivals, used for delivery-rate measurements.
        counted_packet_ids: Packet IDs already included in the byte total;
            retained even after receipt history or playback data is removed.
        received_packet_indices: Frame ID mapped to received indices for SACKs,
            maintained separately from frame assembly data.
        parts: Frame ID mapped to packet-index/payload pairs awaiting assembly.
        ready: Frame ID mapped to complete data awaiting its playback slot.
        last_shown: Last frame ID handed to the player; prevents duplicates
            and playback moving backward.
    """

    # Returns: None; initializes the instance state documented above.
    def __init__(self, net, rate_kbps, rtt_ms, player):
        self.player = player
        self.net = net
        self.total_received_bytes = 0
        self.counted_packet_ids = set()
        self.received_packet_indices = {}
        self.parts = {}
        self.ready = {}
        self.last_shown = -1

    # Record a video packet, send SACK feedback, and assemble complete frames for playback.
    # Returns: None; processes feedback or video packets and updates endpoint state.
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
    # Returns: None; sends receipt ranges and receiver measurements to the sender.
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
            ACK_HEADER, ACK, frame_id, clock.now(), self.total_received_bytes, packet_index) + b"".join(
            struct.pack(SACK_RANGE, first_index, last_index)
            for first_index, last_index in received_ranges))

    # Hand a complete frame to the player if it is newer than the last displayed frame.
    # Returns: None; hands eligible complete data to the player.
    def play_frame(self, frame_id):
        data = self.ready.pop(frame_id, None)
        if data is not None and frame_id > self.last_shown:
            self.player.show(frame_id, data)
            self.last_shown = frame_id
