"""Part B: setting up the call. See Section 4 of the handout for the protocol.

    JOIN     receiver -> sender   0x01, passcode (the rest of the packet)
    ACCEPT   sender -> receiver   0x02, rate_kbps, rtt_ms (4-byte unsigned, big-endian)
    CONFIRM  receiver -> sender   0x03, rate_kbps, rtt_ms (the same values as the ACCEPT)
"""

import clock
import struct

# Handshake:
# Receiver -- JOIN --> Sender
# Receiver <- ACCEPT -- Sender
# Receiver -- CONFIRM --> Sender
#
# Receiver steps:
# 1. The simulator gives ReceiverSetup the passcode from get_passcode().
# 2. Send JOIN immediately, then retry every 100 ms until ACCEPT arrives.
# 3. When ACCEPT arrives, read its rate and RTT and send them back in CONFIRM.
# 4. On the first ACCEPT, stop JOIN retries and call start_call(rate_kbps, rtt_ms).
# 5. Reply to later ACCEPTs with CONFIRM too: an earlier CONFIRM may be lost.
#
# Sender steps:
# 1. Wait for JOIN. Ignore it if its passcode is wrong.
# 2. Reply to every valid JOIN with ACCEPT containing the initial rate and RTT.
# 3. Retry ACCEPT every 100 ms until a matching CONFIRM arrives.
# 4. Ignore CONFIRMs with different values or received before sending ACCEPT.
# 5. On the first matching CONFIRM, stop ACCEPT retries and call start_call().

class SenderSetup:
    def __init__(self, net, passcode, rate_kbps, rtt_ms, start_call):
        """passcode is the right passcode. Put rate_kbps and rtt_ms in your ACCEPT.
        Call start_call() when a matching CONFIRM arrives."""
        self.net = net
        self.passcode = passcode
        self.rate_kbps = rate_kbps
        self.rtt_ms = rtt_ms
        self.start_call = start_call
        self.confirmed = False
        self.accept_packet = struct.pack("!BII", 0x02, rate_kbps, rtt_ms)
        self.accept_timer = None

    def send_accept(self):
        """Retry ACCEPT until a matching CONFIRM arrives."""
        if self.confirmed:
            return
        self.net.send(self.accept_packet)
        self.accept_timer = clock.set_timer(100, self.send_accept)

    def on_packet(self, pkt):
        """A JOIN or CONFIRM arrived."""
        if not pkt or self.confirmed:
            return
        if pkt and pkt[0] == 0x01:
            received_passcode = pkt[1:]
            if received_passcode != self.passcode.encode("ascii"):
                return
            # Reply to every valid JOIN, keeping only one retry timer.
            if self.accept_timer is not None:
                self.accept_timer.cancel()
            self.send_accept()
        elif pkt == b"\x03" + self.accept_packet[1:]:
            # A CONFIRM is valid only after we have sent ACCEPT.
            if self.accept_timer is None:
                return
            self.confirmed = True
            self.accept_timer.cancel()
            self.start_call()


class ReceiverSetup:
    def __init__(self, net, passcode, start_call):
        """passcode is the passcode your get_passcode returned.
        Call start_call(rate_kbps, rtt_ms) when the first ACCEPT arrives."""
        self.net = net
        self.passcode = passcode
        self.start_call = start_call
        self.accepted = False
        self.join_packet = b"\x01" + passcode.encode("ascii")
        self.send_join()

    def send_join(self):
        """Retry JOIN until the sender accepts it."""
        if self.accepted:
            return
        self.net.send(self.join_packet)
        self.join_timer = clock.set_timer(100, self.send_join)
        
    def on_packet(self, pkt):
        """An ACCEPT arrived."""
        if len(pkt) != 9 or pkt[0] != 0x02:
            return

        rate_kbps, rtt_ms = struct.unpack("!II", pkt[1:])

        # Reply every time: an earlier CONFIRM may have been lost.
        self.net.send(b"\x03" + pkt[1:])

        if not self.accepted:
            self.accepted = True
            self.join_timer.cancel()
            self.start_call(rate_kbps, rtt_ms)
