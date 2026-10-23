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

    # receive the response from the join server
    response = b""

    while True:
        chunk = stream.recv(1000)
        if chunk == b"":
            break
        response += chunk 

    # parse the response
    parts = response.split(b" ", 2)

    if(len(parts) != 3):
        return None;

    msg_type = parts[0]
    content = parts[2]

    try:
        length = int(parts[1])
    except ValueError:
        return None

    # Check if the response is complete
    if length < 0 or length != len(content):
        return None

    if msg_type == b"ERR":
        return None

    if msg_type == b"OK":
        return content.decode("utf-8")

    return None




