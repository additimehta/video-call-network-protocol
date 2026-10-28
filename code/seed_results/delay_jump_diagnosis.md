# delay_jump: RTT sampling stalls after the delay increase

Investigated current code with the 30% RTT threshold, 500 ms throughput
window, asymmetric bandwidth smoothing, and no experimental window scaling.
No transport or timeout behavior was changed during this investigation.

The scenario keeps capacity at 4000 kbps. At 15000 ms, one-way propagation
delay increases from 20 to 80 ms. Jitter remains 5 ms; loss remains 2%.
This is a propagation-delay change, not a bandwidth drop.

## Matched seeded traces

Used the existing delay_jump-seed-07.json and delay_jump-seed-16.json paths.
Scenario filenames affect setup timing; seed 7 here is not identical to the
supplied scenario run named delay_jump.json.

| Observation | Seed 7 | Seed 16 |
|---|---:|---:|
| Score | 0.759 | 0.685 |
| Last eligible RTT sample time (ms) | 15012.637 | 15023.497 |
| SRTT thereafter (ms) | 56.288 | 57.143 |
| Base retry timeout thereafter (ms) | 76.288 | 80.210 |
| Total retransmissions | 2342 | 1383 |
| Retries duplicating a packet at arrival | 2195 | 1279 |
| Late retries | 2091 | 6 |

After the jump, observed ACK turnaround is roughly 175 ms. The old timeout
fires before that ACK can return. Retransmitted packets are excluded from
RTT estimation, and expired-packet ACKs do not update SRTT either. These
traces have no eligible RTT samples after the times above: SRTT and its
timeout remain stuck at pre-jump values. This directly confirms the stale
RTT feedback loop in these two runs.

In seed 7, every original packet sent from 16000 through 30000 ms has a
corresponding retransmission sent in that interval (2100 originals and
2100 retries). No original sent during that interval arrives after its frame
deadline. Many retries nevertheless arrive too late and duplicate originals.

## One packet's timeline (seed 7, frame 375, packet 6)

| Event | Time (ms) |
|---|---:|
| Frame captured | 15151.000 |
| Original sent | 15199.675 |
| Timeout retry sent | 15275.963 |
| Original received | 15290.726 |
| Retry arrival predicted by deadline check | 15344.107 |
| Playback deadline | 15351.000 |
| Retry actually received | 15361.910 |

The retry was sent before the original arrived, so it is not counted as an
unnecessary retry under the current send-time definition. It is nevertheless
a duplicate at arrival and late. The stale half-SRTT plus 40 ms prediction
underestimates its forward delivery time.

## Why late-retry counts vary so much

After 16000 ms, seed 7 retries have median 83.71 ms remaining before their
deadline and median actual forward transit of 93.00 ms. Seed 16 retries have
median 119.79 ms remaining and forward transit of 94.31 ms. Originals sent
between 20000 and 30000 ms have median capture-to-send age of 40 ms in seed 7
versus 0 ms in seed 16. Thus both runs suffer stale RTT and redundant retries,
but their different sending ages leave different amounts of deadline slack.
Few late retries do not establish that retransmissions are efficient.

## Interpretation of the three diagnostic counters

`unnecessary_retries` only counts packets already received when a retry is
sent. It does not count retries sent while the original remains in flight,
even when the original later arrives first. `useful_retries` counts first
packet delivery by its deadline, not guaranteed successful frame completion.
`late_retries` counts arrivals after the frame deadline. These counters are
neither exclusive nor exhaustive; lost retries are not arrival-classified.

The low unnecessary-retry count therefore substantially understates redundant
arrivals here. Future diagnostics should also expose duplicates at arrival,
total retries, loss, and retry deadline slack.

## Separate quality-control concern

Since capacity stays constant, an RTT increase alone is not proof that the
sustainable video bitrate decreased. The baseline RTT rule can cause quality
reductions on this scenario, while expiry of low baseline samples can later
make `congested` false without fixing stale SRTT. The 20% versus 30% experiment
already demonstrates a quality cost from increased sensitivity; these traces
do not isolate every quality decision's contribution to final score.

Next work should address stale timing measurement separately from bandwidth
control, with paired performance validation. Do not simply include ambiguous
retransmission ACK ages in SRTT, since the sender cannot identify which copy
an ACK acknowledges.

Trace artifacts from this investigation:

- /tmp/cs456-seed-tests/delay_jump-seed-07-trace.json
- /tmp/cs456-seed-tests/delay_jump-seed-16-trace.json
- /tmp/cs456-seed-tests/delay_jump-seed-07-trace.log
- /tmp/cs456-seed-tests/delay_jump-seed-16-trace.log
- /tmp/cs456_trace_delay.py (observer runner)
