"""Run sim.py with receiver-ground-truth retry metrics, without changing traffic.

Usage: python3 code/retry_metrics.py SCENARIO [FOLDER] [--test TEST]

Unnecessary retries are counted at send time, even if subsequently lost.
Useful retries deliver a previously missing packet by capture + 200 ms;
they need not complete the entire frame. Late retries arrive after that
deadline. Unnecessary and late counts can overlap. Lost retries and retries
still in flight when simulation ends cannot be classified by arrival.
"""
from collections import Counter
import json
from pathlib import Path
import struct
import sys
from unittest.mock import patch

import sim


class RetryObserver:
    def __init__(self):
        self.sent = set()
        self.received = set()
        self.metrics = Counter({
            "unnecessary_retries": 0,
            "useful_retries": 0,
            "late_retries": 0,
        })

    # Observe a send and preserve the original link's loss and arrival scheduling.
    def send(self, original_send, link, packet):
        header = "!BIdHH"
        if (link.direction != "to receiver" or len(packet) < struct.calcsize(header)
                or packet[0] != 0x10):
            return original_send(link, packet)
        _, frame_id, capture_time, packet_index, _ = struct.unpack_from(header, packet)
        packet_id = (frame_id, packet_index)
        retry = packet_id in self.sent
        self.sent.add(packet_id)
        if retry and packet_id in self.received:
            self.metrics["unnecessary_retries"] += 1
        original_receive = link.receive

        def receive(arriving_packet):
            if retry:
                if link.sim.now > capture_time + 200:
                    self.metrics["late_retries"] += 1
                elif packet_id not in self.received:
                    self.metrics["useful_retries"] += 1
            self.received.add(packet_id)
            original_receive(arriving_packet)

        link.receive = receive
        try:
            return original_send(link, packet)
        finally:
            link.receive = original_receive


def main():
    observer = RetryObserver()
    original_send = sim.Link.send

    def observed_send(link, packet):
        return observer.send(original_send, link, packet)

    with patch.object(sim.Link, "send", observed_send):
        sim.main()
    print("  retry_metrics " + " ".join(
        f"{name}={count}" for name, count in observer.metrics.items()))
    output = Path(sim.HERE) / "logs" / (
        f"{sim.RUN['scenario']}-{Path(sim.RUN['impl']).name}-retry-metrics.json")
    output.write_text(json.dumps(dict(observer.metrics), indent=2) + "\n")
    print(f"  retry log {output}")


if __name__ == "__main__":
    main()
