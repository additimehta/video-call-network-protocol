"""Part A edge cases using the simulator's actual join server.

Run from code/: python3 -m unittest discover -s tests -v
"""

import random
import unittest

from join import get_passcode
from sim import JoinStream, message, passcode_for


class GetPasscodeTests(unittest.TestCase):
    def check_reply(self, call="clean", knobs=None, expected=None, seed=1):
        stream = JoinStream(call, random.Random(seed), knobs or {})
        self.assertEqual(get_passcode(stream, call), expected)
        self.assertEqual(stream.request, message(b"JOIN", call.encode("utf-8")))

    def test_whole_reply(self):
        self.check_reply(knobs={"recv_bytes": 1000}, expected=passcode_for("clean"))

    def test_every_chunk_size(self):
        # Includes splits inside OK, the two-digit length, and the payload.
        for size in range(1, len(message(b"OK", passcode_for("clean").encode())) + 1):
            with self.subTest(size=size):
                self.check_reply(knobs={"recv_bytes": size}, expected=passcode_for("clean"))

    def test_random_fragments_and_pauses(self):
        for seed in range(20):
            with self.subTest(seed=seed):
                self.check_reply(seed=seed, expected=passcode_for("clean"))

    def test_error_reply(self):
        for size in (1, 2, 3, 1000):
            with self.subTest(size=size):
                self.check_reply(knobs={"reply": "err", "recv_bytes": size})

    def test_every_early_close_boundary(self):
        # Empty reply, partial type, missing spaces, partial length, no payload,
        # partial payload, and all but the very last byte must return None.
        for kind, payload, reply in (
            (b"OK", passcode_for("clean").encode(), "ok"),
            (b"ERR", b"no-such-call", "err"),
        ):
            for cutoff in range(len(message(kind, payload))):
                for size in (1, 1000):
                    with self.subTest(reply=reply, cutoff=cutoff, size=size):
                        self.check_reply(knobs={"reply": reply, "close_after": cutoff,
                                                "recv_bytes": size})

    def test_close_exactly_after_complete_reply(self):
        length = len(message(b"OK", passcode_for("clean").encode()))
        for cutoff in (length, length + 1):
            with self.subTest(cutoff=cutoff):
                self.check_reply(knobs={"close_after": cutoff, "recv_bytes": 1},
                                 expected=passcode_for("clean"))

    def test_varying_passcode_lengths(self):
        calls = {}
        for i in range(10000):
            call = "call_" + str(i)
            calls.setdefault(len(passcode_for(call)), call)
            if len(calls) == 21:
                break
        self.assertEqual(set(calls), set(range(20, 41)))
        for length, call in calls.items():
            with self.subTest(length=length):
                self.check_reply(call, {"recv_bytes": 1}, passcode_for(call))

    def test_request_byte_length_and_spaces(self):
        # Additional request-format checks: UTF-8 length counts bytes.
        for call in ("", "a", "study group", " café 📞 ", "x" * 1001):
            with self.subTest(call=call):
                self.check_reply(call, {"recv_bytes": 1}, passcode_for(call))


if __name__ == "__main__":
    unittest.main()
