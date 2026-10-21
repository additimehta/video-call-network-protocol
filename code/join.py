"""Part A: get the call's passcode from the join server. See Section 3 of the handout.

    client:  JOIN <length> <call>
    server:  OK <length> <passcode>
         or  ERR <length> no-such-call
"""


def get_passcode(stream, call):
    """Ask the join server for the passcode of the call named call.

    stream.send(data) sends bytes to the join server. stream.recv(n) waits for
    bytes from it and returns up to n of them, or b"" if it closed the stream.
    Return the passcode as a string, or None if there isn't one.
    """
    raise NotImplementedError  # TODO
