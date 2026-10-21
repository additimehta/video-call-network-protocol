"""Baseline call: the sender sends every frame once, at one fixed level, and the receiver
hands each frame to the player as soon as all its packets have arrived."""
import struct

HEADER = "!BIHH"  # packet type, frame id, packet index, packet count
VIDEO = 0x10      # packet type; 0x01-0x03 are taken by the setup messages
MTU = 1500
FPS = 25


class Sender:
    def __init__(self, net, rate_kbps, rtt_ms):
        self.net = net
        self.chunk = MTU - struct.calcsize(HEADER)
        self.budget = rate_kbps * 1000 / 8 / FPS  # bytes per frame that fit in the rate
        self.level = None

    def on_frame(self, frame):
        if self.level is None:
            # The highest level that fits within the rate at the start of the call.
            self.level = max([0] + [l for l, v in enumerate(frame.data) if len(v) <= self.budget])
        data = frame.data[self.level]
        chunks = [data[i:i + self.chunk] for i in range(0, len(data), self.chunk)]
        for i, c in enumerate(chunks):
            self.net.send(struct.pack(HEADER, VIDEO, frame.id, i, len(chunks)) + c)

    def on_packet(self, pkt):
        pass  # the baseline receiver sends nothing back


class Receiver:
    def __init__(self, net, rate_kbps, rtt_ms, player):
        self.player = player
        self.parts = {}    # frame id -> {packet index: bytes}
        self.done = set()  # frame ids already handed to the player

    def on_packet(self, pkt):
        _, frame_id, i, count = struct.unpack(HEADER, pkt[:struct.calcsize(HEADER)])
        if frame_id in self.done:
            return
        parts = self.parts.setdefault(frame_id, {})
        parts[i] = pkt[struct.calcsize(HEADER):]
        if len(parts) == count:
            self.done.add(frame_id)
            del self.parts[frame_id]
            self.player.show(frame_id, b"".join(parts[k] for k in range(count)))
