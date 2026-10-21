"""Part B: setting up the call. See Section 4 of the handout for the protocol.

    JOIN     receiver -> sender   0x01, passcode (the rest of the packet)
    ACCEPT   sender -> receiver   0x02, rate_kbps, rtt_ms (4-byte unsigned, big-endian)
    CONFIRM  receiver -> sender   0x03, rate_kbps, rtt_ms (the same values as the ACCEPT)
"""


class SenderSetup:
    def __init__(self, net, passcode, rate_kbps, rtt_ms, start_call):
        """passcode is the right passcode. Put rate_kbps and rtt_ms in your ACCEPT.
        Call start_call() when a matching CONFIRM arrives."""
        raise NotImplementedError  # TODO

    def on_packet(self, pkt):
        """A JOIN or CONFIRM arrived."""


class ReceiverSetup:
    def __init__(self, net, passcode, start_call):
        """passcode is the passcode your get_passcode returned.
        Call start_call(rate_kbps, rtt_ms) when the first ACCEPT arrives."""
        raise NotImplementedError  # TODO

    def on_packet(self, pkt):
        """An ACCEPT arrived."""
