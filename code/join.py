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

    # send the JOIN request to the join server
    call_bytes = call.encode("utf-8")
    call_length = len(call_bytes)
    stream.send(b"JOIN " + str(call_length).encode("utf-8") + b" " + call_bytes)

    response = b""
    while True:
        parts = response.split(b" ", 2)
        if len(parts) == 3:
            message_type, length_bytes, content = parts
            try:
                length = int(length_bytes)
            except ValueError:
                return None

            if length < 0:
                return None
            if len(content) >= length:
                if message_type == b"OK":
                    return content[:length].decode("ascii")
                return None

        chunk = stream.recv(1000)
        if not chunk:
            return None
        response += chunk
